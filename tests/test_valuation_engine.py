"""
Tests for valuation_engine.py — locks in the Monte Carlo (defect 2),
disagreement-aware confidence (defect 4), and DCF-spine (defect 5) fixes.
"""

import pytest

from backend.services.valuation_engine import compute_valuation


FCF_COMPANY = {
    "ticker": "TESTCO", "current_price": 1000.0,
    "eps_forward": 50.0, "eps_ttm": 48.0,
    "free_cashflow": 5e9, "shares_outstanding": 1e8,
    "total_cash": 1e9, "total_debt": 5e8,
    "beta": 1.0, "earnings_growth": 0.12, "revenue_growth_yoy": 11.0,
    "fifty_two_week_low": 800.0, "fifty_two_week_high": 1200.0,
    "analyst_target_mean": 1050.0, "analyst_count": 10,
}

REQUIRED_KEYS = {
    "dcf_fair_value", "pe_fair_value", "peg_fair_value", "analyst_consensus",
    "composite_fair_value", "upside_pct", "valuation_label", "valuation_confidence",
    "bear_target", "base_target", "bull_target", "stretched_bull_target",
    "entry_zone_low", "entry_zone_high", "trim_level", "hard_stop",
    "prob_undervalued", "mc_interval", "method_agreement", "agreement_note",
    "methods_used", "assumptions",
}


# ── Output contract ───────────────────────────────────────────────────────────
def test_output_contract():
    v = compute_valuation(FCF_COMPANY, "Industrials")
    assert REQUIRED_KEYS <= set(v)


def test_confidence_in_range():
    v = compute_valuation(FCF_COMPANY, "Industrials")
    assert 5 <= v["valuation_confidence"] <= 95


def test_prob_undervalued_is_a_percentage():
    v = compute_valuation(FCF_COMPANY, "Industrials")
    assert 0 <= v["prob_undervalued"] <= 100


# ── Defect 2: probabilistic Monte Carlo scenarios ─────────────────────────────
def test_scenario_targets_strictly_ordered():
    v = compute_valuation(FCF_COMPANY, "Industrials")
    assert (v["bear_target"] < v["base_target"]
            < v["bull_target"] < v["stretched_bull_target"])


def test_scenarios_are_not_fixed_multipliers():
    """The old engine used base x0.55 / x1.45. Monte Carlo must be asymmetric."""
    v = compute_valuation(FCF_COMPANY, "Industrials")
    bear_ratio = v["bear_target"] / v["base_target"]
    bull_ratio = v["bull_target"] / v["base_target"]
    assert bear_ratio != pytest.approx(0.55, abs=0.01)
    assert bull_ratio != pytest.approx(1.45, abs=0.01)


def test_monte_carlo_is_reproducible():
    """Per-ticker seed → identical output for identical input."""
    v1 = compute_valuation(FCF_COMPANY, "Industrials")
    v2 = compute_valuation(FCF_COMPANY, "Industrials")
    assert v1["base_target"] == v2["base_target"]
    assert v1["bear_target"] == v2["bear_target"]
    assert v1["bull_target"] == v2["bull_target"]


def test_mc_interval_matches_bear_bull():
    v = compute_valuation(FCF_COMPANY, "Industrials")
    assert v["mc_interval"] == [v["bear_target"], v["bull_target"]]


# ── Defect 5: DCF spine, EPS fallback ─────────────────────────────────────────
def test_fcf_spine_used_when_fcf_positive():
    v = compute_valuation(FCF_COMPANY, "Industrials")
    assert v["assumptions"]["spine"] == "FCF"


def test_eps_spine_fallback_caps_confidence():
    no_fcf = dict(FCF_COMPANY, free_cashflow=None)
    v = compute_valuation(no_fcf, "Industrials")
    assert v["assumptions"]["spine"] == "EPS projection"
    assert v["valuation_confidence"] <= 62


def test_unvaluable_when_no_fcf_and_no_eps():
    nada = dict(FCF_COMPANY, free_cashflow=None, eps_forward=None, eps_ttm=None)
    v = compute_valuation(nada, "Industrials")
    assert v["valuation_label"] == "Unvaluable"
    assert v["base_target"] is None


# ── Defect 4: disagreement collapses confidence ───────────────────────────────
def test_aligned_methods_yield_high_agreement():
    """When DCF, P/E and analyst all point to the same value → high agreement."""
    base = compute_valuation(FCF_COMPANY, "Industrials")["base_target"]
    aligned = dict(
        FCF_COMPANY,
        eps_forward=round(base / 20.0, 2),   # Industrials sector P/E = 20
        analyst_target_mean=base,
    )
    v = compute_valuation(aligned, "Industrials")
    assert v["method_agreement"] == "high"


def test_divergent_methods_yield_low_agreement_and_low_confidence():
    diverge = dict(FCF_COMPANY, analyst_target_mean=5000.0)
    v = compute_valuation(diverge, "Industrials")
    assert v["method_agreement"] == "low"
    assert v["valuation_confidence"] < 60


def test_agreement_label_independent_of_mc_width():
    """
    A wide Monte Carlo spread must NOT by itself force a 'low' label —
    that conflates model uncertainty with method disagreement.
    """
    base = compute_valuation(FCF_COMPANY, "Industrials")["base_target"]
    aligned = dict(
        FCF_COMPANY,
        eps_forward=round(base / 20.0, 2),
        analyst_target_mean=base,
    )
    v = compute_valuation(aligned, "Industrials")
    # MC spread is inherently wide for a terminal-value DCF, yet methods agree.
    assert v["method_agreement"] in ("high", "moderate")


# ── Actionable levels ─────────────────────────────────────────────────────────
def test_entry_trim_stop_ordering():
    v = compute_valuation(FCF_COMPANY, "Industrials")
    assert v["entry_zone_low"] < v["entry_zone_high"] <= v["base_target"]
    assert v["hard_stop"] < v["entry_zone_low"]
    assert v["trim_level"] <= v["bull_target"]
