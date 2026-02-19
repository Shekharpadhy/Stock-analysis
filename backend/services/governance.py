"""
Governance scoring — the India risk edge.

Turns governance signals the generic global tools ignore into a single
0–100 governance risk score (higher = worse):

  - Promoter pledge        level AND velocity. A rising promoter pledge is one
                           of the strongest early warnings in Indian markets —
                           it preceded the collapses of Yes Bank, DHFL and Zee.
  - SEBI enforcement       a pending action is a hard red flag.
  - Auditor changes        a mid-cycle auditor exit is a known fraud precursor.
  - Board independence     SEBI norms expect >= 1/3 independent directors.

Honest note on data: there is NO free API for any of these. Promoter-pledge
figures live on BSE, SEBI orders on sebi.gov.in, board data in annual reports —
all behind anti-bot measures. This module is the SCORING engine; getting the
data in is a separate problem (manual import, or a paid feed) — see the
governance ingestion endpoints.
"""

from typing import Optional


# ── Component weights (renormalised over whichever components have data) ─────
_WEIGHTS = {"pledge": 0.40, "sebi": 0.25, "auditor": 0.20, "board": 0.15}


def _pledge_component(pledge: float, prior: Optional[float]) -> tuple[float, list[str]]:
    """Pledge risk = level band + velocity penalty."""
    if pledge >= 75:
        level = 90
    elif pledge >= 50:
        level = 70
    elif pledge >= 25:
        level = 45
    elif pledge >= 10:
        level = 20
    elif pledge > 0:
        level = 8
    else:
        level = 0

    velocity = 0
    delta = None
    if prior is not None:
        delta = pledge - prior
        if delta >= 25:
            velocity = 25
        elif delta >= 10:
            velocity = 12
        elif delta > 0:
            velocity = 4

    score = float(min(level + velocity, 100))

    flags: list[str] = []
    if pledge >= 50:
        msg = f"Promoter pledge at {pledge:.0f}%"
        if delta is not None and delta >= 10:
            msg += f" — up from {prior:.0f}% a year ago"
        flags.append(msg)
    elif delta is not None and delta >= 15:
        flags.append(f"Promoter pledge rising fast: {prior:.0f}% to {pledge:.0f}%")
    return score, flags


def compute_governance_score(data: dict) -> dict:
    """
    Compute the governance risk score from whatever governance fields are
    available. Returns score (0–100, higher = worse), label, per-component
    breakdown, flags, and a confidence reflecting data coverage.
    """
    components: dict[str, dict] = {}
    flags: list[str] = []

    # ── Promoter pledge ──────────────────────────────────────────
    pledge = data.get("promoter_pledge_pct")
    if pledge is not None:
        score, pledge_flags = _pledge_component(
            pledge, data.get("promoter_pledge_pct_prior")
        )
        components["pledge"] = {"score": score, "base_w": _WEIGHTS["pledge"]}
        flags.extend(pledge_flags)

    # ── SEBI enforcement ─────────────────────────────────────────
    pending = data.get("sebi_action_pending")
    count = data.get("sebi_action_count")
    if pending is not None or count is not None:
        if pending:
            sebi_score = 90.0
            flags.append("SEBI enforcement action pending against the "
                         "company or its promoters")
        elif count and count > 0:
            sebi_score = 35.0
            flags.append(f"{count} past SEBI enforcement action(s) on record")
        else:
            sebi_score = 0.0
        components["sebi"] = {"score": sebi_score, "base_w": _WEIGHTS["sebi"]}

    # ── Auditor ──────────────────────────────────────────────────
    changed = data.get("auditor_changed_recently")
    if changed is not None:
        components["auditor"] = {
            "score": 80.0 if changed else 5.0, "base_w": _WEIGHTS["auditor"],
        }
        if changed:
            flags.append("Auditor changed within the last ~2 years — a known "
                         "red flag for accounting risk")

    # ── Board independence ───────────────────────────────────────
    board_size = data.get("board_size")
    indep = data.get("independent_director_count")
    if board_size and indep is not None and board_size > 0:
        indep_pct = indep / board_size * 100.0
        if indep_pct < 33.3:
            board_score = 70.0
        elif indep_pct < 50.0:
            board_score = 35.0
        else:
            board_score = 5.0
        components["board"] = {"score": board_score, "base_w": _WEIGHTS["board"]}
        if indep_pct < 33.3:
            flags.append(f"Only {indep}/{board_size} directors independent "
                         f"({indep_pct:.0f}%) — below SEBI's one-third norm")

    # ── Composite ────────────────────────────────────────────────
    if not components:
        return {
            "governance_score": None,
            "governance_label": "Unknown",
            "components": {},
            "flags": [],
            "confidence": 0,
            "methodology": "No governance data available for this ticker.",
        }

    total_w = sum(c["base_w"] for c in components.values())
    weighted_avg = sum(c["score"] * (c["base_w"] / total_w)
                       for c in components.values())
    worst = max(c["score"] for c in components.values())
    # Governance red flags do NOT average away: one catastrophic signal — an
    # 80% promoter pledge, a pending SEBI action — means poor governance even
    # if the board and auditor are pristine. The score is the midpoint of the
    # weighted average and the single worst component.
    score = round(0.5 * weighted_avg + 0.5 * worst, 1)

    if score >= 70:
        label = "Poor"
    elif score >= 50:
        label = "Weak"
    elif score >= 25:
        label = "Adequate"
    else:
        label = "Strong"

    return {
        "governance_score": score,
        "governance_label": label,
        "components": {
            name: {"score": c["score"], "weight": round(c["base_w"] / total_w, 3)}
            for name, c in components.items()
        },
        "flags": flags,
        "confidence": round(len(components) / len(_WEIGHTS) * 100),
        "methodology": "Governance risk: promoter pledge (level + velocity) "
                       "40% + SEBI enforcement 25% + auditor changes 20% + "
                       "board independence 15%. Score = midpoint of that "
                       "weighted average and the single worst component, so "
                       "one catastrophic signal cannot be averaged away.",
    }
