"""Tests for the BCSI composite score."""

from backend.services.bcsi import compute_bcsi


def _ensemble(score):   return {"composite_score": score}
def _valuation(upside): return {"upside_pct": upside}
def _quality(score):    return {"quality_score": score}
def _governance(score): return {"governance_score": score}
def _momentum(score):   return {"momentum_score": score}


# ── Composition ───────────────────────────────────────────────────────────────
def test_strong_company_scores_high():
    r = compute_bcsi(_ensemble(15), _valuation(25), _quality(89), _governance(10))
    # low risk, undervalued, high quality, clean governance → Strong
    assert r["bcsi_label"] == "Strong"
    assert r["bcsi_score"] >= 70


def test_weak_company_scores_low():
    r = compute_bcsi(_ensemble(80), _valuation(-35), _quality(11), _governance(85))
    assert r["bcsi_label"] in ("Weak", "Watch")
    assert r["bcsi_score"] < 45


def test_dimensions_invert_risk_and_governance():
    r = compute_bcsi(_ensemble(30), _valuation(0), _quality(70), _governance(20))
    # risk dimension = 100 - 30 ; governance = 100 - 20
    assert r["dimensions"]["risk"]["score"] == 70.0
    assert r["dimensions"]["governance"]["score"] == 80.0
    # valuation centred at 50 for zero upside
    assert r["dimensions"]["valuation"]["score"] == 50.0


def test_score_in_range():
    r = compute_bcsi(_ensemble(50), _valuation(10), _quality(55), _governance(40))
    assert 0 <= r["bcsi_score"] <= 100


# ── Graceful coverage ─────────────────────────────────────────────────────────
def test_governance_optional_and_weights_renormalise():
    with_gov = compute_bcsi(_ensemble(30), _valuation(10), _quality(70), _governance(20))
    no_gov   = compute_bcsi(_ensemble(30), _valuation(10), _quality(70), None)
    assert "governance" in with_gov["dimensions"]
    assert "governance" not in no_gov["dimensions"]
    # weights of present dimensions always sum to 1
    for r in (with_gov, no_gov):
        total = sum(d["weight"] for d in r["dimensions"].values())
        assert abs(total - 1.0) < 0.01


def test_momentum_absent_when_not_provided():
    r = compute_bcsi(_ensemble(30), _valuation(10), _quality(70), _governance(20))
    assert "momentum" not in r["dimensions"]
    # 4 of 5 dimensions present → 80% coverage
    assert r["confidence"] == 80


def test_momentum_included_when_provided():
    r = compute_bcsi(
        _ensemble(30), _valuation(10), _quality(70), _governance(20),
        momentum=_momentum(75),
    )
    assert "momentum" in r["dimensions"]
    assert r["dimensions"]["momentum"]["score"] == 75
    # All 5 dimensions present → full coverage
    assert r["confidence"] == 100
    # Weights still sum to 1
    total = sum(d["weight"] for d in r["dimensions"].values())
    assert abs(total - 1.0) < 0.01


def test_strong_momentum_raises_score():
    weak_mom   = compute_bcsi(_ensemble(30), _valuation(10), _quality(70),
                              _governance(20), momentum=_momentum(15))
    strong_mom = compute_bcsi(_ensemble(30), _valuation(10), _quality(70),
                              _governance(20), momentum=_momentum(90))
    assert strong_mom["bcsi_score"] > weak_mom["bcsi_score"]


def test_confidence_drops_without_governance():
    full = compute_bcsi(_ensemble(30), _valuation(10), _quality(70), _governance(20))
    sparse = compute_bcsi(_ensemble(30), _valuation(None),
                          {"quality_score": None}, None)
    assert sparse["confidence"] < full["confidence"]


def test_no_data_returns_unknown():
    r = compute_bcsi({"composite_score": None}, {"upside_pct": None},
                     {"quality_score": None}, None)
    assert r["bcsi_score"] is None
    assert r["bcsi_label"] == "Unknown"
