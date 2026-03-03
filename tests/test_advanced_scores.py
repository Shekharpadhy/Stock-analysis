"""
Tests for advanced_scores.py — Altman Z', Beneish M, ICR, FCF margin.
These feed the ensemble; their correctness underpins the whole risk score.
"""

import pandas as pd
import pytest

from backend.services.advanced_scores import (
    compute_altman,
    compute_beneish,
    compute_interest_coverage,
    compute_fcf_margin,
    compute_all_advanced,
)


def _statement(rows: dict) -> pd.DataFrame:
    """Build a yfinance-shaped statement: rows = line items, cols = periods.

    rows: {line_item: [current_year_value, prior_year_value]}
    """
    return pd.DataFrame.from_dict(rows, orient="index", columns=["2024", "2023"])


# ── Altman Z'-Score ───────────────────────────────────────────────────────────
def test_altman_safe_company():
    bs = _statement({
        "Total Assets": [1000, 950],
        "Working Capital": [200, 180],
        "Retained Earnings": [400, 350],
        "Common Stock Equity": [600, 550],
        "Total Liabilities Net Minority Interest": [400, 400],
    })
    inc = _statement({"EBIT": [150, 140], "Total Revenue": [800, 720]})
    r = compute_altman(bs, inc)
    # Z' = 6.56*0.2 + 3.26*0.4 + 6.72*0.15 + 1.05*1.5 = 5.199
    assert r["z_score"] == pytest.approx(5.199, abs=0.01)
    assert r["zone"] == "Safe"


def test_altman_distress_company():
    bs = _statement({
        "Total Assets": [1000, 1000],
        "Working Capital": [-150, -100],
        "Retained Earnings": [-300, -200],
        "Common Stock Equity": [50, 80],
        "Total Liabilities Net Minority Interest": [950, 920],
    })
    inc = _statement({"EBIT": [-40, -20], "Total Revenue": [500, 600]})
    r = compute_altman(bs, inc)
    assert r["zone"] == "Distress"


def test_altman_unavailable_on_missing_data():
    bs = _statement({"Working Capital": [200, 180]})   # no Total Assets
    inc = _statement({"EBIT": [150, 140]})
    r = compute_altman(bs, inc)
    assert r["zone"] == "Unavailable"
    assert r["z_score"] is None


# ── Beneish M-Score ───────────────────────────────────────────────────────────
def test_beneish_returns_valid_structure():
    bs = _statement({
        "Total Assets": [1100, 1000],
        "Receivables": [90, 82],
        "Current Assets": [400, 360],
        "Net PPE": [300, 280],
        "Long Term Debt": [200, 190],
        "Current Liabilities": [150, 140],
    })
    inc = _statement({
        "Total Revenue": [880, 800],
        "Gross Profit": [350, 320],
        "General And Administrative Expense": [120, 110],
        "Net Income": [130, 120],
    })
    cf = _statement({
        "Depreciation And Amortization": [40, 36],
        "Operating Cash Flow": [150, 140],
    })
    r = compute_beneish(bs, inc, cf)
    assert isinstance(r["m_score"], float)
    assert r["flag"] in {"Likely Manipulator", "Grey Zone", "Low Manipulation Risk"}


def test_beneish_unavailable_without_two_periods_of_revenue():
    bs  = _statement({"Total Assets": [1100, 1000]})
    inc = _statement({"Total Revenue": [880, float("nan")]})   # only one period
    cf  = _statement({"Operating Cash Flow": [150, 140]})
    r = compute_beneish(bs, inc, cf)
    assert r["flag"] == "Unavailable"
    assert r["m_score"] is None


# ── Interest Coverage Ratio ───────────────────────────────────────────────────
def test_interest_coverage_strong():
    inc = _statement({"EBIT": [150, 140], "Interest Expense": [30, 28]})
    r = compute_interest_coverage(inc)
    assert r["icr"] == pytest.approx(5.0, abs=0.01)
    assert "coverage" in r["icr_label"].lower()


def test_interest_coverage_critical():
    inc = _statement({"EBIT": [20, 18], "Interest Expense": [40, 35]})
    r = compute_interest_coverage(inc)
    assert r["icr"] < 1.0
    assert "Critical" in r["icr_label"]


def test_interest_coverage_unavailable():
    inc = _statement({"EBIT": [150, 140]})   # no interest line
    r = compute_interest_coverage(inc)
    assert r["icr_label"] == "Unavailable"


# ── Free Cash Flow margin ─────────────────────────────────────────────────────
def test_fcf_margin():
    inc = _statement({"Total Revenue": [800, 720]})
    cf  = _statement({"Free Cash Flow": [120, 100]})
    assert compute_fcf_margin(inc, cf) == pytest.approx(15.0, abs=0.01)


def test_fcf_margin_none_when_missing():
    inc = _statement({"Total Revenue": [800, 720]})
    cf  = _statement({"Operating Cash Flow": [120, 100]})   # no Free Cash Flow
    assert compute_fcf_margin(inc, cf) is None


# ── compute_all_advanced integration ──────────────────────────────────────────
class _FakeTicker:
    def __init__(self, bs, inc, cf):
        self.balance_sheet = bs
        self.financials = inc
        self.cashflow = cf


def test_compute_all_advanced_structure():
    bs = _statement({
        "Total Assets": [1000, 950],
        "Working Capital": [200, 180],
        "Retained Earnings": [400, 350],
        "Common Stock Equity": [600, 550],
        "Total Liabilities Net Minority Interest": [400, 400],
        "Current Assets": [400, 360],
        "Receivables": [90, 82],
        "Net PPE": [300, 280],
        "Current Liabilities": [150, 140],
        "Long Term Debt": [200, 190],
    })
    inc = _statement({
        "EBIT": [150, 140],
        "Total Revenue": [800, 720],
        "Gross Profit": [320, 290],
        "Interest Expense": [30, 28],
        "Net Income": [130, 120],
    })
    cf = _statement({
        "Free Cash Flow": [120, 100],
        "Operating Cash Flow": [150, 140],
        "Depreciation And Amortization": [40, 36],
    })
    r = compute_all_advanced(_FakeTicker(bs, inc, cf))
    assert set(r) >= {"altman", "beneish", "icr", "icr_label", "fcf_margin"}
    assert r["altman"]["zone"] == "Safe"
    assert r["icr"] == pytest.approx(5.0, abs=0.01)
    assert r["fcf_margin"] == pytest.approx(15.0, abs=0.01)
