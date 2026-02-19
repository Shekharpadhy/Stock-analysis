"""
Live self-scoring track record.

Every analyze call records a forward-looking prediction (risk label, valuation,
Bear/Base/Bull targets) with a maturity date. Once a prediction's horizon
matures, score_matured_predictions() grades it against the actual price. The
result is a genuine, falsifiable accuracy record that builds over real time —
the forward-looking complement to the (backward-looking) backtest harness.
"""

import datetime as dt
import logging
from statistics import mean

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.db import Prediction
from backend.services.price_history import fetch_and_store_prices, price_on

log = logging.getLogger(__name__)

_BASE_HIT_TOLERANCE = 0.15   # actual within +/-15% of the base target = a "hit"

_CAVEATS = [
    "The track record builds over real time — early numbers reflect very few "
    "matured predictions and are not yet meaningful.",
    "Predictions are only recorded for tickers users actually analyse, so the "
    "sample is a usage-driven set, not a controlled universe.",
]


def _horizons() -> list[int]:
    return [int(h) for h in settings.prediction_horizons.split(",") if h.strip()]


# ── Recording ─────────────────────────────────────────────────────────────────
def record_prediction(db: Session, ticker: str, raw: dict,
                       ensemble: dict, valuation: dict) -> int:
    """
    Record one Prediction per configured horizon, deduplicated to at most one
    per (ticker, horizon, day). Returns the number of rows created. A no-op if
    the current price is unknown (the prediction could never be scored).
    """
    ticker = ticker.upper()
    price = raw.get("current_price")
    if price is None:
        return 0

    today = dt.date.today()
    created = 0
    for h in _horizons():
        already = (db.query(Prediction)
                     .filter(Prediction.ticker == ticker,
                             Prediction.horizon_months == h,
                             Prediction.predicted_at == today)
                     .first())
        if already:
            continue
        db.add(Prediction(
            ticker=ticker,
            predicted_at=today,
            horizon_months=h,
            matures_on=today + relativedelta(months=h),
            price_at_prediction=price,
            risk_score=ensemble["composite_score"],
            risk_label=ensemble["composite_label"],
            valuation_label=valuation["valuation_label"],
            upside_pct=valuation["upside_pct"],
            base_target=valuation["base_target"],
            bear_target=valuation["bear_target"],
            bull_target=valuation["bull_target"],
            scored=False,
        ))
        created += 1
    db.commit()
    return created


# ── Scoring ───────────────────────────────────────────────────────────────────
def score_matured_predictions(db: Session, fetch: bool = True) -> dict:
    """Grade every matured, unscored prediction against the actual price."""
    today = dt.date.today()
    pending = (db.query(Prediction)
                 .filter(Prediction.scored == False,           # noqa: E712
                         Prediction.matures_on <= today)
                 .all())

    if fetch:
        for ticker in {p.ticker for p in pending}:
            try:
                fetch_and_store_prices(db, ticker, years=2)
            except Exception as e:                             # noqa: BLE001
                log.warning("track-record: price fetch failed for %s (%s)",
                            ticker, e)

    scored = 0
    for p in pending:
        price_now = price_on(db, p.ticker, p.matures_on, tolerance_days=15)
        if price_now is None or not p.price_at_prediction:
            continue   # leave pending — scoreable once prices are available
        actual = (price_now - p.price_at_prediction) / p.price_at_prediction * 100.0
        p.price_at_maturity = round(price_now, 2)
        p.actual_return_pct = round(actual, 2)
        p.direction_correct = (
            p.upside_pct is not None and (p.upside_pct >= 0) == (actual >= 0)
        )
        p.base_hit = (
            p.base_target is not None and price_now > 0
            and abs(price_now - p.base_target) / price_now <= _BASE_HIT_TOLERANCE
        )
        p.scored = True
        scored += 1

    db.commit()
    return {"matured": len(pending), "scored": scored,
            "still_pending": len(pending) - scored}


# ── Reporting ─────────────────────────────────────────────────────────────────
def track_record_report(db: Session) -> dict:
    preds = db.query(Prediction).all()
    scored = [p for p in preds if p.scored]

    report = {
        "total_predictions": len(preds),
        "scored": len(scored),
        "pending": len(preds) - len(scored),
        "by_horizon": {},
        "verdict": "",
        "caveats": _CAVEATS,
    }
    if not scored:
        report["verdict"] = ("No predictions have matured yet — the track "
                              "record accumulates as horizons mature.")
        return report

    for h in sorted({p.horizon_months for p in scored}):
        hp = [p for p in scored if p.horizon_months == h]
        dirs = [p for p in hp if p.direction_correct is not None]
        bases = [p for p in hp if p.base_hit is not None]
        rets = [p.actual_return_pct for p in hp if p.actual_return_pct is not None]

        tiers = {}
        for label in ("Low Risk", "Medium Risk", "High Risk"):
            tr = [p.actual_return_pct for p in hp
                  if p.risk_label == label and p.actual_return_pct is not None]
            if tr:
                tiers[label] = round(mean(tr), 2)

        report["by_horizon"][str(h)] = {
            "n": len(hp),
            "directional_hit_rate": (
                round(sum(bool(p.direction_correct) for p in dirs) / len(dirs) * 100, 1)
                if dirs else None),
            "base_target_hit_rate": (
                round(sum(bool(p.base_hit) for p in bases) / len(bases) * 100, 1)
                if bases else None),
            "avg_actual_return": round(mean(rets), 2) if rets else None,
            "avg_return_by_risk_tier": tiers,
        }

    report["verdict"] = (
        f"{len(scored)} prediction(s) scored across "
        f"{len(report['by_horizon'])} horizon(s). Accuracy strengthens as more "
        f"predictions mature."
    )
    return report
