"""
Engine calibration.

The sector risk profiles in ensemble_risk.SECTOR_RISK_PROFILES are reasoned
estimates. This module re-estimates them from the real company fundamentals the
platform accumulates in the companies table: as more tickers are analysed, each
sector's median/spread self-calibrate from measured data. Sectors with too few
companies keep the hardcoded estimate.

It also provides reliability analysis (see reliability_report) — checking
whether the risk score is well-calibrated as a probability.
"""

import logging
from datetime import datetime
from statistics import mean

import numpy as np
from sqlalchemy.orm import Session

from backend.database.db import CompanyRecord, SectorProfile, BacktestObservation

log = logging.getLogger(__name__)

_DRAWDOWN_THRESHOLD = -20.0   # forward return below this = a "bad outcome"
_RELIABILITY_CAVEATS = [
    "Reliability is computed from backtest observations — it inherits their "
    "survivorship bias and small-sample limits.",
    "A 'bad outcome' is defined as a forward return below -20%.",
]

# Metrics with both a CompanyRecord column and a sector-profile entry.
_METRICS = ["debt_to_equity", "current_ratio", "net_margin",
            "revenue_growth_yoy", "pe_ratio", "roe", "beta"]

_MIN_SAMPLE = 8   # a (sector, metric) needs this many values to be calibrated


def _robust_spread(values: list) -> float:
    """
    A robust, ~1-sigma scale: IQR / 1.349 (the normal-consistent conversion),
    floored so the spread is never zero or implausibly tiny — a zero spread
    would make the risk engine's logistic curve infinitely steep.
    """
    q1, q3 = np.percentile(values, [25, 75])
    iqr_sigma = (q3 - q1) / 1.349
    med = abs(float(np.median(values)))
    return float(max(iqr_sigma, med * 0.15, 0.01))


def recalibrate_sector_profiles(db: Session, min_sample: int = _MIN_SAMPLE) -> dict:
    """
    Re-estimate per-sector metric distributions from CompanyRecord rows and
    upsert them into sector_profiles. A (sector, metric) is only calibrated
    once it has at least `min_sample` non-null values. Returns a summary.
    """
    companies = db.query(CompanyRecord).all()

    by_sector: dict[str, list] = {}
    for c in companies:
        if c.sector:
            by_sector.setdefault(c.sector, []).append(c)

    calibrated: dict[str, dict] = {}
    for sector, rows in by_sector.items():
        metrics_done = []
        for metric in _METRICS:
            values = [getattr(r, metric) for r in rows
                      if getattr(r, metric) is not None]
            if len(values) < min_sample:
                continue
            _upsert_profile(
                db, sector, metric,
                median_v=float(np.median(values)),
                spread_v=_robust_spread(values),
                sample_size=len(values),
            )
            metrics_done.append(metric)
        if metrics_done:
            calibrated[sector] = {"metrics": metrics_done, "companies": len(rows)}

    db.commit()
    return {
        "total_companies": len(companies),
        "min_sample": min_sample,
        "calibrated_sectors": calibrated,
    }


def _upsert_profile(db, sector, metric, median_v, spread_v, sample_size):
    row = (db.query(SectorProfile)
             .filter(SectorProfile.sector == sector,
                     SectorProfile.metric == metric)
             .first())
    if row:
        row.median = median_v
        row.spread = spread_v
        row.sample_size = sample_size
        row.updated_at = datetime.utcnow()
    else:
        db.add(SectorProfile(sector=sector, metric=metric, median=median_v,
                             spread=spread_v, sample_size=sample_size))


def get_calibrated_profiles(db: Session) -> dict:
    """
    Sector profiles for the risk engine: data-calibrated where the
    sector_profiles table has entries, hardcoded estimates everywhere else.

    Shape matches ensemble_risk.SECTOR_RISK_PROFILES:
        {sector: {metric: (median, spread)}}
    """
    from backend.services.ensemble_risk import SECTOR_RISK_PROFILES

    profiles = {s: dict(metrics) for s, metrics in SECTOR_RISK_PROFILES.items()}
    for row in db.query(SectorProfile).all():
        profiles.setdefault(row.sector, {})[row.metric] = (row.median, row.spread)
    return profiles


# ── Reliability analysis ──────────────────────────────────────────────────────
def reliability_report(db: Session, horizon_months: int = 12) -> dict:
    """
    Check whether the risk score is well-calibrated as a probability.

    Backtest observations are bucketed by risk_score band. For each band the
    average predicted bad-outcome probability (risk_score / 100) is compared
    with the observed rate of bad outcomes. A well-calibrated model has the
    two tracking each other; a persistent positive gap means the score is
    overconfident (cries wolf), a negative gap means underconfident.
    """
    rows = (db.query(BacktestObservation)
              .filter(BacktestObservation.horizon_months == horizon_months,
                      BacktestObservation.forward_return_pct.isnot(None),
                      BacktestObservation.risk_score.isnot(None))
              .all())

    report = {
        "horizon_months": horizon_months,
        "n": len(rows),
        "buckets": [],
        "overall_gap": None,
        "verdict": "",
        "caveats": _RELIABILITY_CAVEATS,
    }
    if not rows:
        report["verdict"] = ("No measurable backtest observations — run the "
                              "backtest harness before assessing reliability.")
        return report

    bands = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100)]
    weighted_pred = weighted_obs = 0.0
    for lo, hi in bands:
        if hi < 100:
            bucket = [r for r in rows if lo <= r.risk_score < hi]
        else:
            bucket = [r for r in rows if lo <= r.risk_score <= hi]
        if not bucket:
            continue
        avg_pred = mean(r.risk_score for r in bucket) / 100.0
        obs_bad = mean(1.0 if r.forward_return_pct < _DRAWDOWN_THRESHOLD else 0.0
                       for r in bucket)
        report["buckets"].append({
            "risk_score_band": f"{lo}-{hi}",
            "n": len(bucket),
            "avg_predicted_bad_prob": round(avg_pred, 3),
            "observed_bad_rate": round(obs_bad, 3),
            "gap": round(avg_pred - obs_bad, 3),
        })
        weighted_pred += avg_pred * len(bucket)
        weighted_obs += obs_bad * len(bucket)

    overall_gap = (weighted_pred - weighted_obs) / len(rows)
    report["overall_gap"] = round(overall_gap, 3)
    if abs(overall_gap) <= 0.10:
        report["verdict"] = (f"Well-calibrated: predicted and observed "
                             f"bad-outcome rates agree within "
                             f"{abs(overall_gap) * 100:.0f}pp.")
    elif overall_gap > 0.10:
        report["verdict"] = (f"Overconfident: the risk score over-predicts bad "
                             f"outcomes by ~{overall_gap * 100:.0f}pp — it "
                             f"cries wolf.")
    else:
        report["verdict"] = (f"Underconfident: the risk score under-predicts "
                             f"bad outcomes by ~{abs(overall_gap) * 100:.0f}pp.")
    return report
