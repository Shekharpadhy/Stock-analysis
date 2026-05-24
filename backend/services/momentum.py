"""
Momentum scoring engine — the fifth and final BCSI dimension.

Design philosophy
─────────────────
Momentum is intentionally a *blended* signal, not a single price-return read.
A stock that's up 40% YTD on falling volume with sell-side downgrades is not
in the same regime as one up 40% on rising volume with upgrades, and the
score must reflect that.

Components (all normalised to 0-100, higher = stronger momentum)
────────────────────────────────────────────────────────────────
  price_3m         3-month price return
  price_6m         6-month price return
  price_12m        12-month price return
  position_52w     where current price sits in the 52-week range
  volume_trend     20-day avg volume / 180-day avg volume
  analyst_strength sell-side recommendation strength
  news_sentiment   lexicon-scored recent headlines (v0.5.0)

Component weights (within momentum)
───────────────────────────────────
  price returns (averaged when ≥2 horizons present)  35%
  52-week position                                   17%
  volume trend                                       13%
  analyst strength                                   20%
  news sentiment                                     15%
                                                    ────
                                                    100%

Coverage handling
─────────────────
Components renormalise over whichever signals have data — identical contract
to BCSI itself. Confidence reports the fraction of components present so the
caller can downweight low-coverage scores.

Optimisations
─────────────
  * Single price-history query per ticker fetches the entire 13-month window
    once; all return/position/volume calculations operate on the resulting
    in-memory DataFrame.  No N+1 queries.
  * Vectorised pandas/numpy throughout — no Python-level row loops.
  * Pure functions (no DB writes); callers persist the result.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from backend.database.db import PriceHistory

log = logging.getLogger(__name__)


# ── tunables ──────────────────────────────────────────────────────────────────

# Within-momentum weights — these sum to 1.0 and renormalise over available
# components.  Tuned so that fundamentals (price action) dominate, but
# sentiment (analysts) and tape signals (volume) still meaningfully shift the
# score.
_COMPONENT_WEIGHTS: Dict[str, float] = {
    "price_returns":    0.35,   # averaged across 3M/6M/12M when available
    "position_52w":     0.17,
    "volume_trend":     0.13,
    "analyst_strength": 0.20,
    "news_sentiment":   0.15,
}

# Sigmoid temperature for return-to-score mapping.  At ±30% return the score
# is ~88/12 — picked so that a "normal" annual move spans the full middle
# range without saturating, but extreme moves still rail at 0/100.
_RETURN_TEMP_PCT = 30.0

# Volume ratio temperature: ratio 2.0 → 75, ratio 0.5 → 37.5
_VOLUME_TEMP = 25.0

# Map yfinance-style recommendation strings to 0-100.  None / unknown skips
# the component entirely (rather than defaulting to 50, which would smuggle
# in a fake signal).
_ANALYST_MAP: Dict[str, float] = {
    "strong_buy":   90.0,
    "strongbuy":    90.0,
    "buy":          75.0,
    "outperform":   75.0,
    "overweight":   70.0,
    "hold":         50.0,
    "neutral":      50.0,
    "underperform": 30.0,
    "underweight":  30.0,
    "sell":         25.0,
    "strong_sell":  10.0,
    "strongsell":   10.0,
}


# ── component scoring helpers (pure, vectorisable) ────────────────────────────

def _return_to_score(ret_pct: Optional[float]) -> Optional[float]:
    """
    Map a percentage return into a 0-100 score via a tanh sigmoid centred at 0.

      ret_pct=0  →  50  (neutral)
      ret_pct=+30→  ~88
      ret_pct=-30→  ~12
      large gains/losses asymptote to 100/0
    """
    if ret_pct is None or (isinstance(ret_pct, float) and math.isnan(ret_pct)):
        return None
    return round(50.0 + 50.0 * math.tanh(ret_pct / _RETURN_TEMP_PCT), 1)


def _volume_ratio_to_score(ratio: Optional[float]) -> Optional[float]:
    """
    Map a recent-vs-trailing volume ratio into a 0-100 score.

      ratio=1.0  →  50 (in line)
      ratio=2.0  →  75 (recent volume 2× normal)
      ratio=0.5  → 37.5 (recent volume 1/2 normal)
      Clipped to [0, 100].
    """
    if ratio is None or ratio <= 0 or math.isnan(ratio):
        return None
    return round(max(0.0, min(100.0, 50.0 + _VOLUME_TEMP * (ratio - 1.0))), 1)


def _analyst_to_score(recommendation: Optional[str]) -> Optional[float]:
    """
    Map a recommendation string to a 0-100 score, or None when unknown.

    All separators are stripped so the input form is forgiving — "strong_buy",
    "strong buy", "Strong-Buy", and "StrongBuy" all resolve to the same key.
    """
    if not recommendation:
        return None
    raw = recommendation.strip().lower()
    # Try the form with `_` first (matches keys like "strong_buy"), then a
    # fully-collapsed form (matches keys like "strongbuy") — this keeps the
    # map readable while accepting any common separator convention.
    underscore = raw.replace("-", "_").replace(" ", "_")
    if underscore in _ANALYST_MAP:
        return _ANALYST_MAP[underscore]
    collapsed = "".join(c for c in raw if c.isalpha())
    return _ANALYST_MAP.get(collapsed)


# ── price-derived components from a price DataFrame ───────────────────────────

@dataclass(frozen=True)
class _PriceComponents:
    """Components computable from a price/volume series. None when unavailable."""
    price_3m_score:   Optional[float]
    price_6m_score:   Optional[float]
    price_12m_score:  Optional[float]
    position_52w_score: Optional[float]
    volume_trend_score: Optional[float]

    # Raw (un-scored) values — exposed in the response for inspection.
    raw: Dict[str, Optional[float]]


def _price_components(df: pd.DataFrame) -> _PriceComponents:
    """
    Compute every price-derived component from a price history DataFrame.

    `df` must be indexed by date (ascending) with columns ['close', 'volume'].
    All components gracefully degrade to None when the underlying window is
    not present in the data.
    """
    if df.empty:
        return _PriceComponents(None, None, None, None, None, raw={
            "ret_3m": None, "ret_6m": None, "ret_12m": None,
            "high_52w": None, "low_52w": None, "current_price": None,
            "vol_avg_20d": None, "vol_avg_180d": None, "vol_ratio": None,
        })

    closes  = df["close"].astype(float)
    volumes = df["volume"].astype(float) if "volume" in df.columns else None
    current = float(closes.iloc[-1])
    as_of   = df.index[-1]

    # ── price returns over multiple horizons (vectorised lookups) ─────────────
    def _ret_n_months(months: int) -> Optional[float]:
        # Find first close on/after (as_of - months).  Using searchsorted on the
        # ascending DatetimeIndex avoids a linear scan.
        cutoff = as_of - pd.DateOffset(months=months)
        idx = closes.index.searchsorted(cutoff, side="left")
        if idx >= len(closes):
            return None
        start = float(closes.iloc[idx])
        if start <= 0:
            return None
        return (current - start) / start * 100.0

    ret_3m  = _ret_n_months(3)
    ret_6m  = _ret_n_months(6)
    ret_12m = _ret_n_months(12)

    # ── 52-week position ──────────────────────────────────────────────────────
    cutoff_52w = as_of - pd.DateOffset(weeks=52)
    last_year = closes[closes.index >= cutoff_52w]
    if len(last_year) >= 2:
        high_52w = float(last_year.max())
        low_52w  = float(last_year.min())
        if high_52w > low_52w:
            position_52w = (current - low_52w) / (high_52w - low_52w) * 100.0
            position_52w = round(max(0.0, min(100.0, position_52w)), 1)
        else:
            position_52w = 50.0
    else:
        high_52w = low_52w = None
        position_52w = None

    # ── volume trend ──────────────────────────────────────────────────────────
    vol_avg_20d = vol_avg_180d = vol_ratio = None
    volume_trend_score = None
    if volumes is not None and volumes.notna().any():
        recent  = volumes.tail(20).dropna()
        trailing = volumes.tail(180).dropna()
        if len(recent) >= 5 and len(trailing) >= 30 and trailing.mean() > 0:
            vol_avg_20d  = float(recent.mean())
            vol_avg_180d = float(trailing.mean())
            vol_ratio    = vol_avg_20d / vol_avg_180d
            volume_trend_score = _volume_ratio_to_score(vol_ratio)

    return _PriceComponents(
        price_3m_score   = _return_to_score(ret_3m),
        price_6m_score   = _return_to_score(ret_6m),
        price_12m_score  = _return_to_score(ret_12m),
        position_52w_score = position_52w,
        volume_trend_score = volume_trend_score,
        raw = {
            "ret_3m":  None if ret_3m  is None else round(ret_3m,  2),
            "ret_6m":  None if ret_6m  is None else round(ret_6m,  2),
            "ret_12m": None if ret_12m is None else round(ret_12m, 2),
            "high_52w": high_52w,
            "low_52w":  low_52w,
            "current_price": round(current, 4),
            "vol_avg_20d":  None if vol_avg_20d  is None else round(vol_avg_20d,  0),
            "vol_avg_180d": None if vol_avg_180d is None else round(vol_avg_180d, 0),
            "vol_ratio":    None if vol_ratio    is None else round(vol_ratio,    3),
        },
    )


# ── price-history loader (single optimised query) ─────────────────────────────

def _load_price_history(
    db: Session,
    ticker: str,
    as_of: dt.date,
    months: int = 14,    # 14 months gives a comfortable buffer over 12M lookback
) -> pd.DataFrame:
    """
    Pull the price/volume series for the last `months` months in a single
    SQL query, return as a date-indexed DataFrame.  Empty DataFrame when no
    data exists for the ticker.
    """
    start = as_of - dt.timedelta(days=months * 31)
    rows = (
        db.query(PriceHistory.date, PriceHistory.close, PriceHistory.volume)
          .filter(
              PriceHistory.ticker == ticker.upper(),
              PriceHistory.date >= start,
              PriceHistory.date <= as_of,
          )
          .order_by(PriceHistory.date.asc())
          .all()
    )
    if not rows:
        return pd.DataFrame(columns=["close", "volume"])

    df = pd.DataFrame(rows, columns=["date", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


# ── public API ────────────────────────────────────────────────────────────────

def _label(score: Optional[float]) -> str:
    """Map a 0-100 momentum score into a categorical label."""
    if score is None:
        return "Unknown"
    if score >= 70: return "Strong"
    if score >= 55: return "Positive"
    if score >= 40: return "Neutral"
    if score >= 25: return "Negative"
    return "Weak"


def compute_momentum(
    ticker: str,
    db: Session,
    recommendation: Optional[str] = None,
    as_of: Optional[dt.date] = None,
    news_score: Optional[float] = None,
    news_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compute the momentum score for `ticker`.

    Parameters
    ----------
    ticker : str
        Symbol to score.  Lower-case input is normalised.
    db : Session
        Active SQLAlchemy session — only used to read PriceHistory.
    recommendation : Optional[str]
        Sell-side recommendation string (e.g. "buy", "strong_buy", "hold").
        Pass through from CompanyRecord.recommendation.
    as_of : Optional[date]
        Anchor date for the calculation.  Defaults to today.  Used by the
        backtest harness to evaluate momentum at past points in time.

    Returns
    -------
    dict
        {
          "momentum_score":     float | None    # 0-100, None on no data
          "momentum_label":     str             # Strong | Positive | Neutral | Negative | Weak | Unknown
          "components":         dict            # per-component 0-100 scores
          "raw":                dict            # raw underlying values
          "confidence":         int             # 0-100, fraction of components present
        }
    """
    as_of = as_of or dt.date.today()
    ticker_u = ticker.upper().strip()

    # 1. Load all the price data we need in one query.
    df = _load_price_history(db, ticker_u, as_of)
    price = _price_components(df)

    # 2. Compute the average price-return score across whichever horizons we
    #    have data for.  Treating them as one composite component is the
    #    cleanest way to avoid double-counting overlapping windows.
    return_scores = [s for s in (price.price_3m_score,
                                 price.price_6m_score,
                                 price.price_12m_score) if s is not None]
    price_returns_score = (
        round(float(np.mean(return_scores)), 1) if return_scores else None
    )

    # 3. Analyst component.
    analyst_score = _analyst_to_score(recommendation)

    # 4. Per-component dict — the order here drives both UI display and
    #    confidence accounting.
    components: Dict[str, Optional[float]] = {
        "price_returns":    price_returns_score,
        "position_52w":     price.position_52w_score,
        "volume_trend":     price.volume_trend_score,
        "analyst_strength": analyst_score,
        "news_sentiment":   news_score,
    }

    # 5. Weighted sum, renormalised over whatever components have data.
    present = {k: v for k, v in components.items() if v is not None}
    if not present:
        return {
            "momentum_score":  None,
            "momentum_label":  "Unknown",
            "components":      components,
            "raw":             {**price.raw, "recommendation": recommendation},
            "confidence":      0,
        }

    total_w = sum(_COMPONENT_WEIGHTS[k] for k in present)
    score = round(
        sum(v * (_COMPONENT_WEIGHTS[k] / total_w) for k, v in present.items()),
        1,
    )

    return {
        "momentum_score":  score,
        "momentum_label":  _label(score),
        "components":      components,
        "raw": {
            **price.raw,
            "recommendation": recommendation,
            "news":           news_meta,
        },
        "confidence":      round(len(present) / len(_COMPONENT_WEIGHTS) * 100),
    }
