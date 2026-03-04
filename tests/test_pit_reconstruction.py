"""Tests for point-in-time input reconstruction."""

import datetime as dt

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.db import Base, PriceHistory
from backend.services.pit_reconstruction import (
    available_fiscal_years, reconstruct_inputs,
)

# Fiscal year-end columns, most recent first (yfinance ordering).
_DATES = [pd.Timestamp("2024-12-31"),
          pd.Timestamp("2023-12-31"),
          pd.Timestamp("2022-12-31")]


def _stmt(rows: dict) -> pd.DataFrame:
    return pd.DataFrame.from_dict(rows, orient="index", columns=_DATES)


@pytest.fixture
def statements():
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
        "Total Assets":            [2000, 1850, 1700],
        "Common Stock Equity":     [1000, 900, 800],
        "Total Debt":              [600, 580, 560],
        "Current Assets":          [700, 650, 600],
        "Current Liabilities":     [350, 340, 330],
        "Total Liabilities Net Minority Interest": [1000, 950, 900],
        "Working Capital":         [350, 310, 270],
        "Retained Earnings":       [500, 420, 350],
        "Ordinary Shares Number":  [50, 50, 50],
        "Cash And Cash Equivalents": [200, 180, 160],
        "Receivables":             [150, 140, 130],
        "Net PPE":                 [800, 760, 720],
    })
    cf = _stmt({
        "Operating Cash Flow":   [180, 150, 130],
        "Free Cash Flow":        [120, 100, 85],
        "Depreciation And Amortization": [60, 55, 50],
    })
    return bs, inc, cf


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    # Seed daily prices spanning the FY2023 as_of (~2024-03-30) and its
    # trailing 52 weeks.
    d, price = dt.date(2023, 3, 1), 100.0
    while d <= dt.date(2024, 5, 1):
        session.add(PriceHistory(ticker="AAA", date=d, close=price, volume=1e6))
        price += 0.1
        d += dt.timedelta(days=1)
    session.commit()
    yield session
    session.close()


def test_available_fiscal_years_drops_oldest(statements):
    _, inc, _ = statements
    assert available_fiscal_years(inc) == [
        dt.date(2024, 12, 31), dt.date(2023, 12, 31),
    ]


def test_reconstruct_fy2023_fundamentals(statements, db):
    bs, inc, cf = statements
    out = reconstruct_inputs("AAA", bs, inc, cf, dt.date(2023, 12, 31), db)
    assert out is not None
    raw = out["raw"]
    assert raw["revenue_growth_yoy"] == pytest.approx(11.11, abs=0.1)  # 1000 vs 900
    assert raw["net_margin"]        == pytest.approx(12.0,  abs=0.1)   # 120/1000
    assert raw["debt_to_equity"]    == pytest.approx(64.44, abs=0.1)   # 580/900
    assert raw["current_ratio"]     == pytest.approx(1.91,  abs=0.02)  # 650/340
    assert raw["roe"]               == pytest.approx(13.33, abs=0.1)   # 120/900
    assert raw["earnings_growth"]   == pytest.approx(0.20,  abs=0.01)  # 2.4/2.0
    assert raw["eps_ttm"] == 2.4
    assert out["as_of"] == dt.date(2024, 3, 30)        # fy_end + 90 days


def test_reconstruct_advanced_scores_present(statements, db):
    bs, inc, cf = statements
    adv = reconstruct_inputs("AAA", bs, inc, cf, dt.date(2023, 12, 31), db)["advanced"]
    assert adv["altman"]["zone"] in ("Safe", "Grey", "Distress")
    assert adv["beneish"]["flag"] in (
        "Low Manipulation Risk", "Grey Zone", "Likely Manipulator")
    assert adv["icr"] == pytest.approx(9.44, abs=0.1)   # EBIT 170 / interest 18
    assert adv["fcf_margin"] == pytest.approx(10.0, abs=0.1)  # FCF 100 / rev 1000


def test_reconstruct_picks_the_correct_year(statements, db):
    bs, inc, cf = statements
    fy2024 = reconstruct_inputs("AAA", bs, inc, cf, dt.date(2024, 12, 31), db)
    fy2023 = reconstruct_inputs("AAA", bs, inc, cf, dt.date(2023, 12, 31), db)
    assert fy2024["raw"]["revenue_growth_yoy"] == pytest.approx(20.0, abs=0.1)
    assert fy2023["raw"]["revenue_growth_yoy"] == pytest.approx(11.11, abs=0.1)


def test_reconstruct_returns_none_without_prior_year(statements, db):
    bs, inc, cf = statements
    # FY2022 is the oldest column — no prior year for YoY growth / Beneish.
    assert reconstruct_inputs("AAA", bs, inc, cf, dt.date(2022, 12, 31), db) is None


# ── Regression: negative shareholder equity → D/E and ROE are unknown ─────────
def test_negative_equity_yields_none_de_and_roe(db):
    """Negative equity makes D/E meaningless and ROE misleading (a loss over
    negative equity flips positive) — both must come back None."""
    dates = [pd.Timestamp("2023-12-31"), pd.Timestamp("2022-12-31")]

    def s(rows):
        return pd.DataFrame.from_dict(rows, orient="index", columns=dates)

    inc = s({"Total Revenue": [1000, 900], "Net Income": [-50, -30],
             "EBIT": [20, 15]})
    bs = s({"Total Assets": [2000, 1900],
            "Common Stock Equity": [-100, -50],          # negative equity
            "Total Debt": [800, 750], "Current Assets": [400, 380],
            "Current Liabilities": [300, 290]})
    cf = s({"Operating Cash Flow": [40, 30], "Free Cash Flow": [20, 15]})

    out = reconstruct_inputs("NEG", bs, inc, cf, dt.date(2023, 12, 31), db)
    assert out is not None
    assert out["raw"]["debt_to_equity"] is None    # uninterpretable → unknown
    assert out["raw"]["roe"] is None               # would falsely flip positive
