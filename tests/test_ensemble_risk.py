"""
Tests for ensemble_risk.py — locks in the orthogonality (defect 1) and
sector-relative percentile scoring (defect 3) fixes.
"""

import pytest

from backend.services.ensemble_risk import compute_ensemble_risk


# ── Fixtures / helpers ────────────────────────────────────────────────────────
def _advanced(
    altman_zone="Safe", altman_z=3.5,
    beneish_flag="Low Manipulation Risk", beneish_m=-2.6,
    icr=8.0, fcf=15.0,
):
    return {
        "altman":  {"zone": altman_zone, "z_score": altman_z},
        "beneish": {"flag": beneish_flag, "m_score": beneish_m},
        "icr": icr, "icr_label": "Strong coverage", "fcf_margin": fcf,
    }


HEALTHY = {
    "debt_to_equity": 40, "current_ratio": 2.0, "net_margin": 16,
    "revenue_growth_yoy": 12, "pe_ratio": 22, "roe": 18, "beta": 1.0,
}

REQUIRED_KEYS = {
    "composite_score", "composite_label", "confidence",
    "components", "flags", "sector_calibrated", "methodology",
}


# ── Output contract ───────────────────────────────────────────────────────────
def test_output_contract():
    r = compute_ensemble_risk(HEALTHY, _advanced(), "Industrials")
    assert REQUIRED_KEYS <= set(r)
    assert set(r["components"]) == {"altman", "beneish", "fundamental", "cashflow"}


def test_score_in_range():
    r = compute_ensemble_risk(HEALTHY, _advanced(), "Industrials")
    assert 0 <= r["composite_score"] <= 100


def test_label_matches_score_bands():
    r = compute_ensemble_risk(HEALTHY, _advanced(), "Industrials")
    s, label = r["composite_score"], r["composite_label"]
    if s >= 60:
        assert label == "High Risk"
    elif s >= 35:
        assert label == "Medium Risk"
    else:
        assert label == "Low Risk"


def test_weights_sum_to_one():
    r = compute_ensemble_risk(HEALTHY, _advanced(), "Industrials")
    total = sum(c["weight"] for c in r["components"].values())
    assert total == pytest.approx(1.0, abs=0.01)


# ── Directional sanity ────────────────────────────────────────────────────────
def test_healthy_company_is_low_risk():
    r = compute_ensemble_risk(HEALTHY, _advanced(), "Industrials")
    assert r["composite_label"] == "Low Risk"


def test_distressed_company_is_high_risk():
    adv = _advanced(
        altman_zone="Distress", altman_z=0.4,
        beneish_flag="Likely Manipulator", beneish_m=-1.0,
        icr=0.7, fcf=-8.0,
    )
    bad = {
        "debt_to_equity": 450, "current_ratio": 0.6, "net_margin": -10,
        "revenue_growth_yoy": -25, "pe_ratio": -4, "roe": -12, "beta": 2.6,
    }
    r = compute_ensemble_risk(bad, adv, "Industrials")
    assert r["composite_label"] == "High Risk"
    assert r["composite_score"] > 60


# ── Defect 1: orthogonality by construction ───────────────────────────────────
def test_fundamental_runs_slim_when_altman_available():
    r = compute_ensemble_risk(HEALTHY, _advanced(altman_zone="Safe"), "Industrials")
    fund = r["components"]["fundamental"]
    assert "slim" in fund["mode"]
    assert fund["metrics_scored"] == ["revenue_growth_yoy", "beta", "pe_ratio"]


def test_fundamental_runs_full_when_altman_unavailable():
    adv = _advanced(altman_zone="Unavailable", altman_z=None)
    r = compute_ensemble_risk(HEALTHY, adv, "Industrials")
    fund = r["components"]["fundamental"]
    assert fund["mode"] == "full"
    assert len(fund["metrics_scored"]) == 7
    assert r["components"]["altman"]["available"] is False


def test_altman_carries_more_weight_than_slim_fundamental():
    # When Altman is present it owns leverage/liquidity/profitability and should
    # outweigh the slim fundamental scorecard.
    r = compute_ensemble_risk(HEALTHY, _advanced(), "Industrials")
    assert r["components"]["altman"]["weight"] > r["components"]["fundamental"]["weight"]


# ── Defect 3: sector-relative percentile scoring ──────────────────────────────
def test_same_leverage_scores_differently_by_sector():
    """700% D/E is near-typical for banks, extreme for an IT firm."""
    adv = _advanced(
        altman_zone="Unavailable", altman_z=None,
        beneish_flag="Unavailable", beneish_m=None, icr=None, fcf=None,
    )
    high_de = dict(HEALTHY, debt_to_equity=700)
    bank = compute_ensemble_risk(high_de, adv, "Financials")
    it   = compute_ensemble_risk(high_de, adv, "Information Technology")
    assert (bank["components"]["fundamental"]["score"]
            < it["components"]["fundamental"]["score"])


def test_sector_calibrated_flag():
    known   = compute_ensemble_risk(HEALTHY, _advanced(), "Information Technology")
    unknown = compute_ensemble_risk(HEALTHY, _advanced(), "Nonexistent Sector")
    assert known["sector_calibrated"] is True
    assert unknown["sector_calibrated"] is False


# ── Confidence reflects data availability ─────────────────────────────────────
def test_confidence_drops_with_missing_data():
    full = compute_ensemble_risk(HEALTHY, _advanced(), "Industrials")
    sparse_adv = {
        "altman":  {"zone": "Unavailable", "z_score": None},
        "beneish": {"flag": "Unavailable", "m_score": None},
        "icr": None, "icr_label": "Unavailable", "fcf_margin": None,
    }
    sparse = compute_ensemble_risk({"beta": 1.0}, sparse_adv, "Industrials")
    assert sparse["confidence"] < full["confidence"]


def test_distress_zone_surfaces_a_flag():
    adv = _advanced(altman_zone="Distress", altman_z=0.5)
    r = compute_ensemble_risk(HEALTHY, adv, "Industrials")
    assert any("Distress" in f for f in r["flags"])


# ── Regression: negative D/E (negative equity) must not score as low-risk ─────
def test_negative_debt_to_equity_is_skipped_not_scored_low():
    """A negative D/E (negative shareholder equity) is uninterpretable as a
    leverage ratio — it must be skipped, not scored as pristine leverage."""
    sparse_adv = {
        "altman":  {"zone": "Unavailable", "z_score": None},
        "beneish": {"flag": "Unavailable", "m_score": None},
        "icr": None, "icr_label": "Unavailable", "fcf_margin": None,
    }
    base = {"current_ratio": 1.6, "net_margin": 10, "revenue_growth_yoy": 6,
            "pe_ratio": 18, "roe": 12, "beta": 1.0}
    neg_de  = {**base, "debt_to_equity": -250}   # negative equity
    no_de   = dict(base)                         # D/E absent entirely

    r_neg  = compute_ensemble_risk(neg_de, sparse_adv, "Industrials")
    r_none = compute_ensemble_risk(no_de,  sparse_adv, "Industrials")

    # Negative D/E is skipped → identical to D/E being absent (not scored low).
    assert (r_neg["components"]["fundamental"]["score"]
            == r_none["components"]["fundamental"]["score"])
    assert "debt_to_equity" not in r_neg["components"]["fundamental"]["metrics_scored"]
