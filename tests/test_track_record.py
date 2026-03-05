"""Tests for the live self-scoring track record."""

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.db import Base, PriceHistory, Prediction
from backend.services.track_record import (
    record_prediction, score_matured_predictions, track_record_report,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


_RAW = {"current_price": 100.0}
_ENSEMBLE = {"composite_score": 30.0, "composite_label": "Low Risk"}
_VALUATION = {
    "valuation_label": "Undervalued", "upside_pct": 12.0,
    "base_target": 110.0, "bear_target": 80.0, "bull_target": 150.0,
}


# ── Recording ─────────────────────────────────────────────────────────────────
def test_record_prediction_creates_one_row_per_horizon(db):
    created = record_prediction(db, "AAA", _RAW, _ENSEMBLE, _VALUATION)
    assert created == 3                                  # default horizons 3,6,12
    assert db.query(Prediction).count() == 3
    assert {p.horizon_months for p in db.query(Prediction).all()} == {3, 6, 12}


def test_record_prediction_deduplicates_same_day(db):
    record_prediction(db, "AAA", _RAW, _ENSEMBLE, _VALUATION)
    second = record_prediction(db, "AAA", _RAW, _ENSEMBLE, _VALUATION)
    assert second == 0                                   # same ticker/horizons/day
    assert db.query(Prediction).count() == 3


def test_record_prediction_skips_when_price_unknown(db):
    assert record_prediction(db, "AAA", {"current_price": None},
                             _ENSEMBLE, _VALUATION) == 0
    assert db.query(Prediction).count() == 0


# ── Scoring ───────────────────────────────────────────────────────────────────
def test_score_matured_prediction_grades_correctly(db):
    matured = dt.date.today() - dt.timedelta(days=5)
    db.add(Prediction(
        ticker="AAA", predicted_at=matured - dt.timedelta(days=90),
        horizon_months=3, matures_on=matured,
        price_at_prediction=100.0, risk_score=30.0, risk_label="Low Risk",
        valuation_label="Undervalued", upside_pct=12.0,
        base_target=110.0, bear_target=80.0, bull_target=150.0, scored=False,
    ))
    # Actual price at maturity = 120 → +20% return.
    db.add(PriceHistory(ticker="AAA", date=matured, close=120.0, volume=1e6))
    db.commit()

    result = score_matured_predictions(db, fetch=False)
    assert result["scored"] == 1

    p = db.query(Prediction).first()
    assert p.scored is True
    assert p.actual_return_pct == 20.0
    assert p.direction_correct is True                   # upside +12 vs actual +20
    assert p.base_hit is True                            # 120 within 15% of 110


def test_score_leaves_prediction_pending_without_price(db):
    matured = dt.date.today() - dt.timedelta(days=5)
    db.add(Prediction(
        ticker="ZZZ", predicted_at=matured - dt.timedelta(days=90),
        horizon_months=3, matures_on=matured,
        price_at_prediction=100.0, risk_score=30.0, risk_label="Low Risk",
        valuation_label="Undervalued", upside_pct=12.0,
        base_target=110.0, bear_target=80.0, bull_target=150.0, scored=False,
    ))
    db.commit()
    # No price data for ZZZ → cannot score → stays pending.
    result = score_matured_predictions(db, fetch=False)
    assert result["scored"] == 0
    assert db.query(Prediction).first().scored is False


def test_unmatured_prediction_is_not_scored(db):
    future = dt.date.today() + dt.timedelta(days=200)
    db.add(Prediction(
        ticker="AAA", predicted_at=dt.date.today(), horizon_months=12,
        matures_on=future, price_at_prediction=100.0, risk_score=30.0,
        risk_label="Low Risk", valuation_label="Undervalued", upside_pct=12.0,
        base_target=110.0, bear_target=80.0, bull_target=150.0, scored=False,
    ))
    db.commit()
    result = score_matured_predictions(db, fetch=False)
    assert result["matured"] == 0


# ── Reporting ─────────────────────────────────────────────────────────────────
def test_track_record_report_empty(db):
    r = track_record_report(db)
    assert r["total_predictions"] == 0
    assert "No predictions have matured" in r["verdict"]


def test_track_record_report_aggregates_scored(db):
    matured = dt.date.today() - dt.timedelta(days=5)
    db.add(Prediction(
        ticker="AAA", predicted_at=matured - dt.timedelta(days=90),
        horizon_months=3, matures_on=matured, price_at_prediction=100.0,
        risk_score=30.0, risk_label="Low Risk", valuation_label="Undervalued",
        upside_pct=12.0, base_target=110.0, bear_target=80.0, bull_target=150.0,
        scored=True, price_at_maturity=120.0, actual_return_pct=20.0,
        direction_correct=True, base_hit=True,
    ))
    db.commit()
    r = track_record_report(db)
    assert r["scored"] == 1
    assert r["by_horizon"]["3"]["directional_hit_rate"] == 100.0
    assert r["by_horizon"]["3"]["avg_actual_return"] == 20.0
