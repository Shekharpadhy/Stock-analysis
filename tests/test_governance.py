"""Tests for the governance scoring engine."""

from backend.services.governance import compute_governance_score


# ── Pledge: level + velocity ──────────────────────────────────────────────────
def test_zero_pledge_clean_governance_scores_strong():
    r = compute_governance_score({
        "promoter_pledge_pct": 0.0, "promoter_pledge_pct_prior": 0.0,
        "sebi_action_pending": False, "sebi_action_count": 0,
        "auditor_changed_recently": False,
        "board_size": 10, "independent_director_count": 6,
    })
    assert r["governance_label"] == "Strong"
    assert r["governance_score"] < 25
    assert r["flags"] == []


def test_high_pledge_drives_poor_governance():
    r = compute_governance_score({
        "promoter_pledge_pct": 80.0, "promoter_pledge_pct_prior": 40.0,
        "sebi_action_pending": False, "sebi_action_count": 0,
        "auditor_changed_recently": False,
        "board_size": 10, "independent_director_count": 6,
    })
    # 80% pledged, up 40pp in a year — a Yes-Bank-style signal.
    assert r["governance_score"] > 50
    assert any("pledge" in f.lower() for f in r["flags"])


def test_rising_pledge_scores_worse_than_flat_pledge():
    flat = compute_governance_score({"promoter_pledge_pct": 40.0,
                                     "promoter_pledge_pct_prior": 40.0})
    rising = compute_governance_score({"promoter_pledge_pct": 40.0,
                                       "promoter_pledge_pct_prior": 5.0})
    assert rising["governance_score"] > flat["governance_score"]


# ── SEBI / auditor red flags ──────────────────────────────────────────────────
def test_pending_sebi_action_is_a_hard_flag():
    r = compute_governance_score({"sebi_action_pending": True})
    assert any("SEBI" in f for f in r["flags"])
    assert r["components"]["sebi"]["score"] == 90.0


def test_auditor_change_is_flagged():
    r = compute_governance_score({"auditor_changed_recently": True})
    assert any("Auditor" in f for f in r["flags"])


# ── Board independence ────────────────────────────────────────────────────────
def test_weak_board_independence_is_flagged():
    r = compute_governance_score({"board_size": 8, "independent_director_count": 2})
    # 2/8 = 25% — below SEBI's one-third norm.
    assert any("independent" in f for f in r["flags"])
    assert r["components"]["board"]["score"] == 70.0


def test_strong_board_independence_no_flag():
    r = compute_governance_score({"board_size": 8, "independent_director_count": 5})
    assert not any("independent" in f for f in r["flags"])


# ── Structure / graceful degradation ──────────────────────────────────────────
def test_no_data_returns_unknown():
    r = compute_governance_score({})
    assert r["governance_score"] is None
    assert r["governance_label"] == "Unknown"
    assert r["confidence"] == 0


def test_confidence_reflects_data_coverage():
    partial = compute_governance_score({"promoter_pledge_pct": 10.0})
    full = compute_governance_score({
        "promoter_pledge_pct": 10.0, "sebi_action_pending": False,
        "auditor_changed_recently": False,
        "board_size": 10, "independent_director_count": 5,
    })
    assert partial["confidence"] < full["confidence"]
    assert full["confidence"] == 100


def test_component_weights_renormalise_to_one():
    r = compute_governance_score({
        "promoter_pledge_pct": 10.0, "sebi_action_pending": False,
        "auditor_changed_recently": False,
        "board_size": 10, "independent_director_count": 5,
    })
    total = sum(c["weight"] for c in r["components"].values())
    assert abs(total - 1.0) < 0.01
