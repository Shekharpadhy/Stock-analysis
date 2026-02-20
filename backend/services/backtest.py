"""
Backtesting harness.

Runs the risk + valuation engines on reconstructed point-in-time inputs across
a universe of tickers and historical fiscal years, then scores each prediction
against the ACTUAL forward price return that followed. This is what replaces
the borrowed "85%" — accuracy is measured here, not claimed.

Honest limitations:
  - Survivorship bias: the universe contains only tickers yfinance still
    serves. Companies that failed or delisted — exactly the ones a risk model
    should catch — are absent unless explicitly added.
  - Small samples: yfinance gives ~4 years of statements, so each ticker
    yields only ~2-3 observations. Treat the metrics as suggestive.
  - Approximate point-in-time (see pit_reconstruction): beta and analyst data
    are omitted; statements are yfinance's current, possibly-restated view.
"""

import logging
from statistics import mean, median
from typing import Optional

from sqlalchemy.orm import Session

from backend.database.db import BacktestObservation
from backend.services.ensemble_risk import compute_ensemble_risk
from backend.services.valuation_engine import compute_valuation
from backend.services.pit_reconstruction import (
    available_fiscal_years, reconstruct_inputs, fetch_statements,
)
from backend.services.price_history import fetch_and_store_prices, forward_return

log = logging.getLogger(__name__)

_DRAWDOWN_THRESHOLD = -20.0   # forward return below this counts as a "bad outcome"

_CAVEATS = [
    "Survivorship bias: universe contains only currently-listed tickers; "
    "failed/delisted companies are absent.",
    "Small sample expected (~2-3 observations per ticker) — suggestive, not "
    "statistically robust.",
    "Approximate point-in-time: beta and analyst data omitted; statements are "
    "yfinance's current (possibly restated) view.",
]


# ── Run ───────────────────────────────────────────────────────────────────────
def run_backtest(
    db: Session,
    universe: dict[str, str],
    horizon_months: int = 12,
    fetch: bool = True,
    price_years: int = 6,
) -> dict:
    """
    Backtest the engines over `universe` ({ticker: sector}). Stores one
    BacktestObservation per (ticker, fiscal year) and returns the aggregated
    accuracy report. A ticker's prior observations for the same horizon are
    replaced, so re-running is idempotent.
    """
    for raw_ticker, sector in universe.items():
        ticker = raw_ticker.upper()
        try:
            if fetch:
                fetch_and_store_prices(db, ticker, years=price_years)
            bs, inc, cf = fetch_statements(ticker)
        except Exception as e:                       # noqa: BLE001
            log.warning("backtest: skipping %s — fetch failed (%s)", ticker, e)
            continue

        db.query(BacktestObservation).filter(
            BacktestObservation.ticker == ticker,
            BacktestObservation.horizon_months == horizon_months,
        ).delete()

        for fy_end in available_fiscal_years(inc):
            recon = reconstruct_inputs(ticker, bs, inc, cf, fy_end, db)
            if recon is None:
                continue
            raw, advanced = recon["raw"], recon["advanced"]
            as_of = recon["as_of"]

            # Deliberately NOT passing calibrated profiles here: those are
            # calibrated from the *current* companies table, and using them to
            # score a past fiscal year would be look-ahead bias. The backtest
            # uses the hardcoded estimates only.
            risk = compute_ensemble_risk(raw, advanced, sector)
            val  = compute_valuation(raw, sector)
            fwd  = forward_return(db, ticker, as_of, horizon_months)

            db.add(BacktestObservation(
                ticker=ticker, fy_end=fy_end, as_of=as_of, sector=sector,
                horizon_months=horizon_months,
                risk_score=risk["composite_score"],
                risk_label=risk["composite_label"],
                valuation_label=val["valuation_label"],
                upside_pct=val["upside_pct"],
                base_target=val["base_target"],
                price_at_as_of=raw.get("current_price"),
                forward_return_pct=fwd,
            ))
    db.commit()
    return aggregate_report(db, horizon_months)


# ── Aggregate ─────────────────────────────────────────────────────────────────
def aggregate_report(db: Session, horizon_months: int = 12) -> dict:
    """Aggregate all stored observations for the given horizon into a report."""
    rows = (db.query(BacktestObservation)
              .filter(BacktestObservation.horizon_months == horizon_months)
              .all())
    return _compute_metrics([_to_dict(r) for r in rows], horizon_months)


def _to_dict(r: BacktestObservation) -> dict:
    return {
        "ticker": r.ticker, "risk_score": r.risk_score,
        "risk_label": r.risk_label, "valuation_label": r.valuation_label,
        "upside_pct": r.upside_pct, "forward_return_pct": r.forward_return_pct,
    }


# ── Metrics ───────────────────────────────────────────────────────────────────
def _compute_metrics(obs: list[dict], horizon_months: int) -> dict:
    measurable = [o for o in obs if o["forward_return_pct"] is not None]

    report = {
        "horizon_months": horizon_months,
        "n_observations": len(obs),
        "n_measurable": len(measurable),
        "risk_tiers": {},
        "valuation_tiers": {},
        "risk_return_correlation": None,
        "directional_hit_rate": None,
        "brier_score": None,
        "verdict": "",
        "caveats": _CAVEATS,
    }
    if not measurable:
        report["verdict"] = ("No measurable observations yet — run the harness, "
                             "or wait for prediction horizons to mature.")
        return report

    # Risk tiers — mean/median forward return per risk label
    for label in ("Low Risk", "Medium Risk", "High Risk"):
        rs = [o["forward_return_pct"] for o in measurable if o["risk_label"] == label]
        if rs:
            report["risk_tiers"][label] = {
                "n": len(rs),
                "avg_return": round(mean(rs), 2),
                "median_return": round(median(rs), 2),
            }

    # Valuation tiers
    for label in sorted({o["valuation_label"] for o in measurable if o["valuation_label"]}):
        rs = [o["forward_return_pct"] for o in measurable if o["valuation_label"] == label]
        if rs:
            report["valuation_tiers"][label] = {"n": len(rs), "avg_return": round(mean(rs), 2)}

    # Directional hit rate — did sign(upside_pct) match sign(forward return)?
    directional = [o for o in measurable if o["upside_pct"] is not None]
    if directional:
        hits = sum(1 for o in directional
                   if (o["upside_pct"] >= 0) == (o["forward_return_pct"] >= 0))
        report["directional_hit_rate"] = round(hits / len(directional) * 100, 1)

    # Spearman rank correlation: risk_score vs forward return (expect negative)
    report["risk_return_correlation"] = _spearman(
        [o["risk_score"] for o in measurable],
        [o["forward_return_pct"] for o in measurable],
    )

    # Brier score — risk_score/100 read as P(forward return < -20%)
    report["brier_score"] = _brier(measurable)

    report["verdict"] = _verdict(report["risk_tiers"])
    return report


def _spearman(x: list, y: list) -> Optional[float]:
    """Spearman rank correlation via numpy (rank → Pearson)."""
    if len(x) < 3:
        return None
    import numpy as np
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    if rx.std() == 0 or ry.std() == 0:
        return None
    return round(float(np.corrcoef(rx, ry)[0, 1]), 3)


def _brier(measurable: list[dict]) -> Optional[float]:
    pts = []
    for o in measurable:
        if o["risk_score"] is None:
            continue
        pred = o["risk_score"] / 100.0
        actual = 1.0 if o["forward_return_pct"] < _DRAWDOWN_THRESHOLD else 0.0
        pts.append((pred - actual) ** 2)
    return round(sum(pts) / len(pts), 4) if pts else None


def _verdict(risk_tiers: dict) -> str:
    hi = risk_tiers.get("High Risk", {}).get("avg_return")
    lo = risk_tiers.get("Low Risk", {}).get("avg_return")
    if hi is None or lo is None:
        return ("Not enough observations across both the Low and High risk "
                "tiers to judge separation.")
    gap = lo - hi
    if gap > 5:
        return (f"Risk engine SHOWS separation: Low Risk averaged {lo}% vs "
                f"High Risk {hi}% — a {gap:+.1f}pp spread in the expected "
                f"direction (lower-risk stocks outperformed).")
    if gap > 0:
        return (f"Weak separation: Low Risk {lo}% vs High Risk {hi}% "
                f"({gap:+.1f}pp) — directionally correct but small.")
    return (f"NO separation: High Risk ({hi}%) did not underperform Low Risk "
            f"({lo}%) — the model or the sample needs work.")
