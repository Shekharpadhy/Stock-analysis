"""Tests for the backtest harness — metrics, aggregation, and end-to-end run."""

import datetime as dt

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.db import Base, PriceHistory, BacktestObservation
from backend.services import backtest
from backend.services.backtest import _compute_metrics, aggregate_report, run_backtest


def _obs(risk_label, risk_score, val_label, upside, fwd):
    return {
        "ticker": "X", "risk_score": risk_score, "risk_label": risk_label,
        "valuation_label": val_label, "upside_pct": upside,
        "forward_return_pct": fwd,
    }


# ── _compute_metrics ──────────────────────────────────────────────────────────
def test_metrics_detects_clear_separation():
    obs = [
        _obs("Low Risk", 20, "Undervalued", 12, 15),
        _obs("Low Risk", 25, "Moderately Undervalued", 8, 10),
        _obs("Low Risk", 22, "Undervalued", 14, 20),
        _obs("High Risk", 78, "Overvalued", -25, -28),
        _obs("High Risk", 82, "Overvalued", -30, -18),
        _obs("High Risk", 70, "Overvalued", -12, -22),
    ]
    r = _compute_metrics(obs, 12)
    assert r["n_measurable"] == 6
    assert r["risk_tiers"]["Low Risk"]["avg_return"] == 15.0
    assert r["risk_tiers"]["High Risk"]["avg_return"] == pytest.approx(-22.67, abs=0.1)
    assert "SHOWS separation" in r["verdict"]
    assert r["risk_return_correlation"] < -0.5      # higher risk → lower return
    assert r["directional_hit_rate"] == 100.0       # every sign matched
    assert 0.0 <= r["brier_score"] <= 1.0


def test_metrics_detects_no_separation():
    obs = [
        _obs("Low Risk", 20, "Undervalued", 10, -10),
        _obs("Low Risk", 24, "Undervalued", 8, -5),
        _obs("High Risk", 80, "Overvalued", -20, 25),
        _obs("High Risk", 76, "Overvalued", -15, 18),
    ]
    r = _compute_metrics(obs, 12)
    assert "NO separation" in r["verdict"]


def test_metrics_empty_is_graceful():
    r = _compute_metrics([], 12)
    assert r["n_observations"] == 0
    assert r["n_measurable"] == 0
    assert "No measurable observations" in r["verdict"]


def test_metrics_ignores_unmeasurable_observations():
    obs = [
        _obs("Low Risk", 20, "Undervalued", 10, 12),
        _obs("High Risk", 80, "Overvalued", -20, None),   # horizon past data
    ]
    r = _compute_metrics(obs, 12)
    assert r["n_observations"] == 2
    assert r["n_measurable"] == 1


# ── DB-backed: aggregate_report + run_backtest ────────────────────────────────
@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_aggregate_report_reads_stored_observations(db):
    for rl, rs, fwd in [("Low Risk", 22, 14), ("High Risk", 78, -20)]:
        db.add(BacktestObservation(
            ticker="X", fy_end=dt.date(2022, 12, 31), as_of=dt.date(2023, 3, 31),
            sector="Industrials", horizon_months=12, risk_score=rs, risk_label=rl,
            valuation_label="Fairly Valued", upside_pct=1.0, base_target=100.0,
            price_at_as_of=100.0, forward_return_pct=fwd,
        ))
    db.commit()
    r = aggregate_report(db, horizon_months=12)
    assert r["n_measurable"] == 2
    assert "Low Risk" in r["risk_tiers"] and "High Risk" in r["risk_tiers"]


_DATES = [pd.Timestamp("2022-12-31"), pd.Timestamp("2021-12-31"),
          pd.Timestamp("2020-12-31")]


def _stmt(rows):
    return pd.DataFrame.from_dict(rows, orient="index", columns=_DATES)


def test_run_backtest_end_to_end(db, monkeypatch):
    inc = _stmt({
        "Total Revenue":    [1200, 1000, 900],
        "Net Income":       [150, 120, 100],
        "Diluted EPS":      [3.0, 2.4, 2.0],
        "Operating Income": [200, 170, 150],
        "EBIT":             [200, 170, 150],
        "Gross Profit":     [500, 420, 380],
        "Interest Expense": [20, 18, 16],
    })
    bs = _stmt({
        "Total Assets":          [2000, 1850, 1700],
        "Common Stock Equity":   [1000, 900, 800],
        "Total Debt":            [600, 580, 560],
        "Current Assets":        [700, 650, 600],
        "Current Liabilities":   [350, 340, 330],
        "Total Liabilities Net Minority Interest": [1000, 950, 900],
        "Working Capital":       [350, 310, 270],
        "Retained Earnings":     [500, 420, 350],
        "Ordinary Shares Number":[50, 50, 50],
        "Cash And Cash Equivalents": [200, 180, 160],
        "Receivables":           [150, 140, 130],
        "Net PPE":               [800, 760, 720],
    })
    cf = _stmt({
        "Operating Cash Flow":   [180, 150, 130],
        "Free Cash Flow":        [120, 100, 85],
        "Depreciation And Amortization": [60, 55, 50],
    })
    monkeypatch.setattr(backtest, "fetch_statements", lambda t: (bs, inc, cf))

    # Pre-seed daily prices spanning the fiscal years and their 12-month horizons.
    d, price = dt.date(2021, 1, 1), 100.0
    while d <= dt.date(2024, 12, 31):
        db.add(PriceHistory(ticker="AAA", date=d, close=price, volume=1e6))
        price += 0.05
        d += dt.timedelta(days=1)
    db.commit()

    report = run_backtest(db, {"AAA": "Industrials"}, horizon_months=12, fetch=False)

    stored = db.query(BacktestObservation).all()
    assert len(stored) >= 1                       # FY2021 (+FY2022) reconstructed
    assert all(o.ticker == "AAA" for o in stored)
    assert report["n_observations"] == len(stored)
    assert report["n_measurable"] >= 1            # horizons covered by seeded prices
