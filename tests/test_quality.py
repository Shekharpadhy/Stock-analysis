"""Tests for the quality scoring engine — Piotroski, Graham, Magic Formula."""

import pandas as pd
import pytest

from backend.services.quality import (
    compute_piotroski, graham_number, magic_formula, quality_from_statements,
)

_DATES = [pd.Timestamp("2024-12-31"), pd.Timestamp("2023-12-31")]


def _stmt(rows: dict) -> pd.DataFrame:
    return pd.DataFrame.from_dict(rows, orient="index", columns=_DATES)


# A company improving on every Piotroski axis (current year first).
_STRONG_INC = _stmt({
    "Net Income":    [150, 100],
    "Total Revenue": [1000, 900],
    "Gross Profit":  [500, 400],
    "EBIT":          [200, 160],
})
_STRONG_BS = _stmt({
    "Total Assets":           [1000, 1000],
    "Common Stock Equity":    [600, 500],
    "Long Term Debt":         [200, 300],     # leverage falling
    "Current Assets":         [600, 500],
    "Current Liabilities":    [300, 300],     # current ratio rising
    "Ordinary Shares Number": [100, 100],     # no dilution
    "Net PPE":                [400, 380],
})
_STRONG_CF = _stmt({"Operating Cash Flow": [180, 120]})

# A company deteriorating on every axis.
_WEAK_INC = _stmt({
    "Net Income":    [-50, 20],
    "Total Revenue": [800, 1000],
    "Gross Profit":  [200, 350],
    "EBIT":          [-30, 40],
})
_WEAK_BS = _stmt({
    "Total Assets":           [1200, 1000],
    "Common Stock Equity":    [300, 400],
    "Long Term Debt":         [500, 300],     # leverage rising
    "Current Assets":         [400, 500],
    "Current Liabilities":    [400, 300],     # current ratio falling
    "Ordinary Shares Number": [130, 100],     # dilution
    "Net PPE":                [350, 380],
})
_WEAK_CF = _stmt({"Operating Cash Flow": [-20, 60]})


# ── Piotroski F-Score ─────────────────────────────────────────────────────────
def test_strong_company_scores_near_nine():
    r = compute_piotroski(_STRONG_BS, _STRONG_INC, _STRONG_CF)
    assert r["f_score"] == 9
    assert r["max"] == 9


def test_weak_company_scores_low():
    r = compute_piotroski(_WEAK_BS, _WEAK_INC, _WEAK_CF)
    assert r["f_score"] <= 2


def test_piotroski_missing_data_does_not_award_points():
    empty = _stmt({"Net Income": [None, None]})
    r = compute_piotroski(empty, empty, empty)
    assert r["f_score"] == 0


# ── Graham Number ─────────────────────────────────────────────────────────────
def test_graham_number_known_value():
    # sqrt(22.5 * 10 * 40) = sqrt(9000) ~ 94.87
    assert graham_number(10.0, 40.0) == pytest.approx(94.87, abs=0.1)


def test_graham_number_none_for_negative_inputs():
    assert graham_number(-2.0, 40.0) is None
    assert graham_number(10.0, 0.0) is None
    assert graham_number(None, 40.0) is None


# ── Magic Formula ─────────────────────────────────────────────────────────────
def test_magic_formula_computes_yield_and_roc():
    raw = {"market_cap": 8000, "total_debt": 1000, "total_cash": 1000}
    m = magic_formula(_STRONG_INC, _STRONG_BS, raw)
    # EV = 8000 + 1000 - 1000 = 8000; EBIT 200 → yield 2.5%
    assert m["earnings_yield_pct"] == pytest.approx(2.5, abs=0.1)
    # capital = (600-300) + 400 = 700; EBIT 200 → ROC ~28.6%
    assert m["return_on_capital_pct"] == pytest.approx(28.57, abs=0.1)


# ── quality_from_statements ───────────────────────────────────────────────────
def test_quality_strong_company():
    raw = {"eps_ttm": 1.5, "shares_outstanding": 100,
           "market_cap": 8000, "total_debt": 1000, "total_cash": 1000}
    q = quality_from_statements(_STRONG_BS, _STRONG_INC, _STRONG_CF, raw)
    assert q["quality_label"] == "Strong"
    assert q["quality_score"] == pytest.approx(100.0)
    assert q["graham_number"] is not None     # positive EPS + BVPS


def test_quality_weak_company():
    raw = {"eps_ttm": -0.5, "shares_outstanding": 130,
           "market_cap": 2000, "total_debt": 500, "total_cash": 100}
    q = quality_from_statements(_WEAK_BS, _WEAK_INC, _WEAK_CF, raw)
    assert q["quality_label"] == "Weak"
    assert q["graham_number"] is None         # negative EPS → undefined
