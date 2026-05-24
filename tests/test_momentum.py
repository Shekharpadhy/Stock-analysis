"""
Unit tests for backend/services/momentum.py.

Coverage
────────
  • Pure scoring helpers: return → score, volume ratio → score, analyst → score
  • _price_components: handles empty / partial / full price history
  • compute_momentum: end-to-end with a synthetic price series in a real
    in-memory SQLite DB
  • Coverage handling: missing components renormalise without inflating score
  • Edge cases: unknown ticker, all-flat prices, zero volume, unknown
    recommendation string
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.db import Base, PriceHistory
from backend.services import momentum as mom


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db_session():
    """Fresh in-memory DB per test — momentum tests insert price rows."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    sess = Session()
    yield sess
    sess.close()


def _seed_prices(
    db,
    ticker: str,
    as_of: dt.date,
    pattern: str = "uptrend",
    days: int = 400,
    base: float = 100.0,
):
    """
    Insert `days` daily prices ending on `as_of`.

    Patterns
    ────────
      uptrend   — linear ~30% gain over the window
      downtrend — linear ~30% loss over the window
      flat      — constant price
      v_shape   — drop then recover (current = base)
    """
    rows = []
    for i in range(days):
        date = as_of - dt.timedelta(days=days - 1 - i)
        t = i / max(1, days - 1)         # 0 → 1
        if pattern == "uptrend":
            close = base * (1.0 + 0.30 * t)
        elif pattern == "downtrend":
            close = base * (1.0 - 0.30 * t)
        elif pattern == "flat":
            close = base
        elif pattern == "v_shape":
            # Drop to 70% at midpoint, recover to 100%.
            close = base * (1.0 - 0.30 * (1 - abs(2 * t - 1)))
        else:
            raise ValueError(f"unknown pattern: {pattern}")
        rows.append(PriceHistory(
            ticker=ticker.upper(), date=date, close=close, volume=1_000_000.0,
        ))
    db.add_all(rows)
    db.commit()


# ── helper scoring functions ──────────────────────────────────────────────────

def test_return_to_score_centered_at_zero():
    assert mom._return_to_score(0.0) == 50.0


def test_return_to_score_positive():
    s = mom._return_to_score(30.0)
    assert 80.0 < s < 95.0


def test_return_to_score_negative_symmetric():
    s_pos = mom._return_to_score(30.0)
    s_neg = mom._return_to_score(-30.0)
    # Symmetric around 50
    assert abs((s_pos - 50) + (s_neg - 50)) < 0.5


def test_return_to_score_saturates():
    very_high = mom._return_to_score(1000.0)
    very_low  = mom._return_to_score(-1000.0)
    assert very_high >= 99.0
    assert very_low  <= 1.0


def test_return_to_score_none():
    assert mom._return_to_score(None) is None
    assert mom._return_to_score(float("nan")) is None


def test_volume_ratio_neutral_at_one():
    assert mom._volume_ratio_to_score(1.0) == 50.0


def test_volume_ratio_higher_recent_volume():
    assert mom._volume_ratio_to_score(2.0) == 75.0
    assert mom._volume_ratio_to_score(3.0) == 100.0    # clipped


def test_volume_ratio_lower_recent_volume():
    assert mom._volume_ratio_to_score(0.5) == 37.5


def test_volume_ratio_invalid():
    assert mom._volume_ratio_to_score(None) is None
    assert mom._volume_ratio_to_score(0.0) is None
    assert mom._volume_ratio_to_score(-1.0) is None


def test_analyst_to_score_known_strings():
    assert mom._analyst_to_score("strong_buy") == 90.0
    assert mom._analyst_to_score("Buy") == 75.0
    assert mom._analyst_to_score("HOLD") == 50.0
    assert mom._analyst_to_score("Strong Sell") == 10.0
    assert mom._analyst_to_score("under-perform") == 30.0


def test_analyst_to_score_unknown_returns_none():
    assert mom._analyst_to_score(None) is None
    assert mom._analyst_to_score("") is None
    assert mom._analyst_to_score("gibberish") is None


# ── _price_components from DataFrames ─────────────────────────────────────────

def _frame_uptrend(days=400, base=100.0):
    end = dt.date(2026, 5, 24)
    dates = [end - dt.timedelta(days=days - 1 - i) for i in range(days)]
    closes = [base * (1.0 + 0.30 * i / max(1, days - 1)) for i in range(days)]
    return pd.DataFrame({
        "close":  closes,
        "volume": [1_000_000.0] * days,
    }, index=pd.to_datetime(dates))


def test_price_components_empty():
    comp = mom._price_components(pd.DataFrame(columns=["close", "volume"]))
    assert comp.price_3m_score is None
    assert comp.price_12m_score is None
    assert comp.position_52w_score is None
    assert comp.volume_trend_score is None


def test_price_components_uptrend_scores_above_50():
    comp = mom._price_components(_frame_uptrend())
    # In a 30% uptrend, every horizon should score > 50.
    assert comp.price_3m_score  > 50
    assert comp.price_6m_score  > 50
    assert comp.price_12m_score > 50
    # And the 12M return should be the largest of the three.
    assert comp.price_12m_score >= comp.price_6m_score >= comp.price_3m_score
    # Near 52w high → position close to 100.
    assert comp.position_52w_score > 90


def test_price_components_downtrend_scores_below_50():
    end = dt.date(2026, 5, 24)
    days = 400
    dates = [end - dt.timedelta(days=days - 1 - i) for i in range(days)]
    closes = [100.0 * (1.0 - 0.30 * i / max(1, days - 1)) for i in range(days)]
    df = pd.DataFrame({"close": closes, "volume": [1e6] * days},
                      index=pd.to_datetime(dates))
    comp = mom._price_components(df)
    assert comp.price_3m_score  < 50
    assert comp.price_12m_score < 50
    assert comp.position_52w_score < 10        # near 52w low


def test_price_components_flat_is_neutral():
    end = dt.date(2026, 5, 24)
    days = 400
    dates = [end - dt.timedelta(days=days - 1 - i) for i in range(days)]
    df = pd.DataFrame({"close": [100.0] * days, "volume": [1e6] * days},
                      index=pd.to_datetime(dates))
    comp = mom._price_components(df)
    assert comp.price_3m_score == 50.0
    assert comp.price_12m_score == 50.0


def test_price_components_volume_trend_rising():
    end = dt.date(2026, 5, 24)
    days = 200
    dates = [end - dt.timedelta(days=days - 1 - i) for i in range(days)]
    # Last 20 days: 3× the trailing average.
    vols = [1e6] * (days - 20) + [3e6] * 20
    df = pd.DataFrame({"close": [100.0] * days, "volume": vols},
                      index=pd.to_datetime(dates))
    comp = mom._price_components(df)
    assert comp.volume_trend_score is not None
    assert comp.volume_trend_score > 60        # recent volume well above trailing


# ── compute_momentum end-to-end ───────────────────────────────────────────────

def test_compute_momentum_no_data(db_session):
    out = mom.compute_momentum("UNKNOWN", db_session)
    assert out["momentum_score"] is None
    assert out["momentum_label"] == "Unknown"
    assert out["confidence"] == 0


def test_compute_momentum_uptrend_with_strong_buy(db_session):
    as_of = dt.date(2026, 5, 24)
    _seed_prices(db_session, "AAPL", as_of, pattern="uptrend")
    out = mom.compute_momentum("AAPL", db_session,
                               recommendation="strong_buy", as_of=as_of)
    assert out["momentum_score"] is not None
    assert out["momentum_score"] > 70             # all signals aligned bullish
    assert out["momentum_label"] in ("Strong", "Positive")
    # All four components present (constant-volume series → ratio 1.0 → score 50)
    assert out["confidence"] == 100
    assert out["components"]["analyst_strength"] == 90.0
    assert out["components"]["volume_trend"] == 50.0   # flat volume = neutral
    assert out["raw"]["ret_12m"] > 25


def test_compute_momentum_downtrend_with_strong_sell(db_session):
    as_of = dt.date(2026, 5, 24)
    _seed_prices(db_session, "BADCO", as_of, pattern="downtrend")
    out = mom.compute_momentum("BADCO", db_session,
                               recommendation="strong_sell", as_of=as_of)
    assert out["momentum_score"] is not None
    assert out["momentum_score"] < 30             # all signals bearish
    assert out["momentum_label"] in ("Weak", "Negative")
    assert out["components"]["analyst_strength"] == 10.0


def test_compute_momentum_flat_with_no_analyst(db_session):
    as_of = dt.date(2026, 5, 24)
    _seed_prices(db_session, "FLAT", as_of, pattern="flat")
    out = mom.compute_momentum("FLAT", db_session, as_of=as_of)
    assert out["momentum_score"] is not None
    # Flat → returns 50, 52w_position undefined (high==low)
    # → returns_score=50, position_52w=50, no volume signal (flat), no analyst.
    assert 45 <= out["momentum_score"] <= 55
    assert out["components"]["analyst_strength"] is None
    # No analyst data → confidence < 100
    assert out["confidence"] < 100


def test_compute_momentum_renormalises_when_no_analyst(db_session):
    """Score must NOT be artificially capped just because one component is None."""
    as_of = dt.date(2026, 5, 24)
    _seed_prices(db_session, "X", as_of, pattern="uptrend")
    with_analyst    = mom.compute_momentum("X", db_session,
                                           recommendation="strong_buy", as_of=as_of)
    without_analyst = mom.compute_momentum("X", db_session, as_of=as_of)

    # Both should be positive momentum.
    assert with_analyst["momentum_score"]    > 60
    assert without_analyst["momentum_score"] > 60
    # The version with bullish analysts should be modestly higher.
    assert with_analyst["momentum_score"] >= without_analyst["momentum_score"]


def test_compute_momentum_v_shape_recovers_to_neutral(db_session):
    """
    A V-shape where the price ends back at the starting level should produce
    near-zero 12M return — but the recovery means current price is near the
    52-week high, so position_52w is bullish.  Net score should be near 50.
    """
    as_of = dt.date(2026, 5, 24)
    _seed_prices(db_session, "VSHAPE", as_of, pattern="v_shape")
    out = mom.compute_momentum("VSHAPE", db_session, as_of=as_of)
    assert out["momentum_score"] is not None
    # ret_12m ≈ 0% → score 50; position_52w ≈ 100; volume neutral.
    # Weighted: 0.40*50 + 0.20*100 = 40 → /0.60 weight → 66.7
    assert 55 <= out["momentum_score"] <= 80


def test_compute_momentum_unknown_recommendation_doesnt_break(db_session):
    as_of = dt.date(2026, 5, 24)
    _seed_prices(db_session, "Y", as_of, pattern="uptrend")
    out = mom.compute_momentum("Y", db_session, recommendation="???", as_of=as_of)
    assert out["momentum_score"] is not None
    assert out["components"]["analyst_strength"] is None


def test_compute_momentum_handles_ticker_case(db_session):
    as_of = dt.date(2026, 5, 24)
    _seed_prices(db_session, "MSFT", as_of, pattern="uptrend")
    out = mom.compute_momentum("msft", db_session, as_of=as_of)
    assert out["momentum_score"] is not None


def test_label_mapping():
    assert mom._label(None) == "Unknown"
    assert mom._label(85)   == "Strong"
    assert mom._label(60)   == "Positive"
    assert mom._label(45)   == "Neutral"
    assert mom._label(30)   == "Negative"
    assert mom._label(10)   == "Weak"


# ── component weights sanity ──────────────────────────────────────────────────

def test_component_weights_sum_to_one():
    assert abs(sum(mom._COMPONENT_WEIGHTS.values()) - 1.0) < 1e-9
