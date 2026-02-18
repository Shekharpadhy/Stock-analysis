"""
Ensemble Risk Engine — sector-relative, orthogonal-by-construction.

Design (addresses prior defects 1 and 3):

  Defect 1 — Multicollinearity removed by construction.
    Each economic concept now has exactly ONE owner in the ensemble:
      • Leverage, liquidity, operating profitability, solvency → Altman Z'
      • Earnings manipulation                                  → Beneish M
      • Debt serviceability + cash generation                  → ICR / FCF
      • Growth trajectory, market volatility, valuation risk    → fundamental
    When Altman IS available, the fundamental scorecard only scores the three
    things Altman cannot see (growth, beta, P/E) — it no longer re-counts
    leverage/liquidity/margin. When Altman is UNAVAILABLE the scorecard
    re-absorbs the full metric set, because nothing else is covering them.
    Components no longer share inputs, so the ensemble no longer double-counts.

  Defect 3 — Sector-relative percentile scoring, not absolute thresholds.
    Each metric is scored continuously against its sector reference
    distribution (median + spread) via a logistic curve, instead of a hard
    step at D/E > 100/200. A 150% D/E is now scored against the IT sector
    distribution (alarming) or the NBFC distribution (unremarkable) — the same
    number, the correct verdict, no skip-lists.

  Caveat (honest): the SECTOR_RISK_PROFILES below are reasoned estimates of
  each sector's metric distribution. The *method* is now correct; the
  *parameters* should be re-estimated from measured data in Phase 3.

Output score: 0–100 (higher = riskier).
Labels: Low Risk (< 35) | Medium Risk (35–60) | High Risk (> 60)
"""

import math
from typing import Optional


# ── Sector reference distributions: metric → (median, spread) ────────────────
# spread is a ~1-sigma scale. Metrics absent from a sector's dict are simply
# not scored for that sector (e.g. current_ratio is meaningless for banks).
_DEFAULT_PROFILE = {
    "debt_to_equity": (90.0, 80.0), "current_ratio": (1.6, 0.7),
    "net_margin": (10.0, 9.0), "revenue_growth_yoy": (8.0, 10.0),
    "pe_ratio": (20.0, 11.0), "roe": (14.0, 11.0), "beta": (1.05, 0.35),
}
SECTOR_RISK_PROFILES: dict[str, dict] = {
    "Information Technology": {
        "debt_to_equity": (30.0, 45.0), "current_ratio": (2.0, 0.9),
        "net_margin": (14.0, 11.0), "revenue_growth_yoy": (12.0, 13.0),
        "pe_ratio": (27.0, 13.0), "roe": (18.0, 13.0), "beta": (1.15, 0.35),
    },
    "Technology": {
        "debt_to_equity": (30.0, 45.0), "current_ratio": (2.0, 0.9),
        "net_margin": (14.0, 11.0), "revenue_growth_yoy": (12.0, 13.0),
        "pe_ratio": (27.0, 13.0), "roe": (18.0, 13.0), "beta": (1.15, 0.35),
    },
    "Health Care": {
        "debt_to_equity": (55.0, 55.0), "current_ratio": (2.2, 1.0),
        "net_margin": (10.0, 12.0), "revenue_growth_yoy": (9.0, 9.0),
        "pe_ratio": (22.0, 11.0), "roe": (14.0, 12.0), "beta": (0.95, 0.30),
    },
    "Financials": {  # banks: current_ratio omitted on purpose — not meaningful
        "debt_to_equity": (700.0, 500.0),
        "net_margin": (22.0, 11.0), "revenue_growth_yoy": (10.0, 9.0),
        "pe_ratio": (13.0, 6.0), "roe": (13.0, 7.0), "beta": (1.05, 0.30),
    },
    "Consumer Discretionary": {
        "debt_to_equity": (90.0, 80.0), "current_ratio": (1.5, 0.6),
        "net_margin": (7.0, 7.0), "revenue_growth_yoy": (8.0, 9.0),
        "pe_ratio": (22.0, 11.0), "roe": (15.0, 12.0), "beta": (1.20, 0.35),
    },
    "Consumer Staples": {
        "debt_to_equity": (80.0, 70.0), "current_ratio": (1.4, 0.5),
        "net_margin": (9.0, 6.0), "revenue_growth_yoy": (6.0, 6.0),
        "pe_ratio": (24.0, 10.0), "roe": (20.0, 12.0), "beta": (0.70, 0.25),
    },
    "Industrials": {
        "debt_to_equity": (90.0, 75.0), "current_ratio": (1.6, 0.6),
        "net_margin": (8.0, 6.0), "revenue_growth_yoy": (8.0, 8.0),
        "pe_ratio": (20.0, 9.0), "roe": (15.0, 10.0), "beta": (1.10, 0.30),
    },
    "Materials": {
        "debt_to_equity": (75.0, 65.0), "current_ratio": (1.8, 0.7),
        "net_margin": (8.0, 8.0), "revenue_growth_yoy": (7.0, 11.0),
        "pe_ratio": (15.0, 8.0), "roe": (12.0, 10.0), "beta": (1.15, 0.35),
    },
    "Energy": {
        "debt_to_equity": (60.0, 55.0), "current_ratio": (1.3, 0.5),
        "net_margin": (8.0, 10.0), "revenue_growth_yoy": (5.0, 16.0),
        "pe_ratio": (13.0, 7.0), "roe": (12.0, 12.0), "beta": (1.10, 0.40),
    },
    "Utilities": {
        "debt_to_equity": (140.0, 90.0), "current_ratio": (1.0, 0.4),
        "net_margin": (12.0, 8.0), "revenue_growth_yoy": (4.0, 5.0),
        "pe_ratio": (18.0, 7.0), "roe": (10.0, 5.0), "beta": (0.60, 0.25),
    },
    "Real Estate": {
        "debt_to_equity": (130.0, 100.0), "current_ratio": (1.5, 0.8),
        "net_margin": (20.0, 18.0), "revenue_growth_yoy": (6.0, 10.0),
        "pe_ratio": (30.0, 14.0), "roe": (9.0, 7.0), "beta": (1.05, 0.35),
    },
    "Communication Services": {
        "debt_to_equity": (95.0, 80.0), "current_ratio": (1.3, 0.6),
        "net_margin": (12.0, 11.0), "revenue_growth_yoy": (8.0, 9.0),
        "pe_ratio": (19.0, 10.0), "roe": (14.0, 11.0), "beta": (1.00, 0.30),
    },
}

# Which metrics carry risk when the value is HIGH vs LOW.
_HIGH_IS_BAD = {"debt_to_equity", "pe_ratio", "beta"}

# Fundamental scorecard scope (defect 1):
#   slim  → only what Altman cannot see (used when Altman IS available)
#   full  → everything (used when Altman is unavailable and must be covered)
_SLIM_METRICS = ("revenue_growth_yoy", "beta", "pe_ratio")
_FULL_METRICS = ("debt_to_equity", "current_ratio", "net_margin",
                 "revenue_growth_yoy", "pe_ratio", "roe", "beta")

_METRIC_LABELS = {
    "debt_to_equity": "Leverage (D/E)", "current_ratio": "Liquidity (current ratio)",
    "net_margin": "Net margin", "revenue_growth_yoy": "Revenue growth",
    "pe_ratio": "Valuation (P/E)", "roe": "Return on equity", "beta": "Volatility (beta)",
}


# ── Continuous, sector-relative per-metric risk (defect 3) ───────────────────
def _metric_risk(value: float, median: float, spread: float, high_is_bad: bool) -> float:
    """
    Logistic risk in [0, 1]. A sector-median company scores ~0.33; a company
    one sector-sigma worse scores ~0.62; two sigma worse ~0.84; one sigma
    better ~0.13. Continuous — no step thresholds.
    """
    if spread <= 0:
        return 0.5
    z = (value - median) / spread
    if not high_is_bad:
        z = -z                              # flip so positive z = worse
    z = max(-60.0, min(60.0, z))            # guard against math.exp overflow
    return 1.0 / (1.0 + math.exp(-1.2 * (z - 0.6)))


# ── Component: Altman Z'-Score ───────────────────────────────────────────────
def _altman_risk(altman: dict) -> Optional[float]:
    """Returns risk 0–100, or None when the Z-score is unavailable."""
    zone = altman.get("zone")
    z    = altman.get("z_score")
    if zone in (None, "Unavailable") or z is None:
        return None
    if zone == "Safe":
        return round(max(0.0, 15.0 - (z - 2.6) / (5.0 - 2.6) * 15.0), 1)
    if zone == "Grey":
        return round(60.0 - (z - 1.1) / (2.6 - 1.1) * 25.0, 1)
    return round(max(70.0, 95.0 - max(z, 0.0) / 1.1 * 25.0), 1)   # Distress


# ── Component: Beneish M-Score ───────────────────────────────────────────────
def _beneish_risk(beneish: dict) -> Optional[float]:
    """Returns risk 0–100, or None when the M-score is unavailable."""
    flag = beneish.get("flag")
    m    = beneish.get("m_score")
    if flag in (None, "Unavailable") or m is None:
        return None
    if flag == "Low Manipulation Risk":
        return round(max(0.0, 10.0 + (m + 3.5) / (-2.22 + 3.5) * 10.0), 1)
    if flag == "Grey Zone":
        return round(35.0 + (m + 2.22) / (-1.78 + 2.22) * 20.0, 1)
    return round(min(95.0, 60.0 + (m + 1.78) * 20.0), 1)          # Likely Manipulator


# ── Component: Cash-flow health (ICR + FCF) ──────────────────────────────────
def _cashflow_risk(advanced: dict) -> tuple[Optional[float], list[str]]:
    icr   = advanced.get("icr")
    fcf_m = advanced.get("fcf_margin")
    score = 0.0
    flags: list[str] = []
    pts   = 0

    if icr is not None:
        pts += 1
        if icr < 1.0:
            score += 50; flags.append(f"Cannot cover interest (ICR {icr:.2f}x)")
        elif icr < 1.5:
            score += 35; flags.append(f"Barely covering interest (ICR {icr:.2f}x)")
        elif icr < 3.0:
            score += 15; flags.append(f"Weak interest coverage (ICR {icr:.2f}x)")

    if fcf_m is not None:
        pts += 1
        if fcf_m < 0:
            score += 35; flags.append(f"Negative free cash flow ({fcf_m:.1f}%)")
        elif fcf_m < 3:
            score += 15; flags.append(f"Thin FCF margin ({fcf_m:.1f}%)")

    if pts == 0:
        return None, []
    return round(min(score, 100.0), 1), flags


# ── Component: Sector-relative fundamental scorecard (defects 1 + 3) ─────────
def _fundamental_risk(
    data: dict, sector: str, altman_available: bool, profiles: dict = None,
) -> tuple[float, list[str], int, list[str]]:
    """
    Returns (risk 0–100, flags, metrics_scored, metric_names_used).

    Scope is orthogonal-by-construction: when Altman is available this scores
    only growth / beta / P/E (what Altman cannot see). When Altman is
    unavailable it scores the full set, since nothing else covers leverage,
    liquidity and profitability.

    `profiles` (sector → metric → (median, spread)) overrides the hardcoded
    SECTOR_RISK_PROFILES — used to feed data-calibrated profiles from
    calibration.get_calibrated_profiles(). Defaults to the hardcoded estimates.
    """
    profile = (profiles or SECTOR_RISK_PROFILES).get(sector, _DEFAULT_PROFILE)
    metrics = _SLIM_METRICS if altman_available else _FULL_METRICS

    risks: list[float] = []
    flags: list[str] = []
    used:  list[str] = []

    for metric in metrics:
        value = data.get(metric)
        if value is None or metric not in profile:
            continue

        # A negative D/E means negative shareholder equity — the ratio is
        # uninterpretable (it can be buyback-driven OR distress-driven), so it
        # is skipped here. The negative-equity distress signal is carried by
        # Altman's X4 (equity / liabilities) instead. Scoring it as a number
        # would otherwise rank a negative-equity firm as having pristine
        # leverage — the bug this guard fixes.
        if metric == "debt_to_equity" and value < 0:
            continue

        # P/E is non-monotonic: a negative P/E means losses, not cheapness.
        if metric == "pe_ratio" and value < 0:
            risk = 0.90
        else:
            median, spread = profile[metric]
            risk = _metric_risk(value, median, spread, metric in _HIGH_IS_BAD)

        risks.append(risk)
        used.append(metric)

        if risk > 0.66:
            median, _ = profile[metric]
            flags.append(
                f"{_METRIC_LABELS[metric]} weak vs {sector} sector "
                f"({_fmt(metric, value)} vs sector ~{_fmt(metric, median)})"
            )

    if not risks:
        return 50.0, [], 0, []
    return round(sum(risks) / len(risks) * 100.0, 1), flags, len(risks), used


def _fmt(metric: str, value: float) -> str:
    if metric in ("debt_to_equity", "net_margin", "revenue_growth_yoy", "roe"):
        return f"{value:.0f}%"
    if metric == "pe_ratio":
        return f"{value:.1f}x"
    return f"{value:.2f}"


# ── Master ensemble ───────────────────────────────────────────────────────────
def compute_ensemble_risk(
    data: dict, advanced: dict, sector: str = "Unknown", profiles: dict = None,
) -> dict:
    """
    Orthogonal 4-component ensemble. Components share no inputs, so the
    composite no longer double-counts leverage/profitability. Weights are
    renormalised over whichever components have data.

    `profiles` optionally supplies data-calibrated sector profiles (see
    calibration.get_calibrated_profiles); when omitted the hardcoded
    SECTOR_RISK_PROFILES estimates are used.
    """
    altman_dict  = advanced.get("altman", {})
    beneish_dict = advanced.get("beneish", {})

    altman_score  = _altman_risk(altman_dict)
    altman_avail  = altman_score is not None
    beneish_score = _beneish_risk(beneish_dict)
    cf_score, cf_flags = _cashflow_risk(advanced)

    fund_score, fund_flags, fund_n, fund_metrics = _fundamental_risk(
        data, sector, altman_avail, profiles
    )

    # Base weights. Fundamental carries far more load when Altman is missing,
    # because in that mode it is the only thing covering leverage/liquidity.
    components: dict[str, dict] = {}
    if altman_avail:
        components["altman"] = {"score": altman_score, "base_w": 0.40}
    if beneish_score is not None:
        components["beneish"] = {"score": beneish_score, "base_w": 0.20}
    components["fundamental"] = {
        "score": fund_score,
        "base_w": 0.22 if altman_avail else 0.52,
    }
    if cf_score is not None:
        components["cashflow"] = {"score": cf_score, "base_w": 0.18}

    total_w = sum(c["base_w"] for c in components.values())
    composite = round(
        sum(c["score"] * (c["base_w"] / total_w) for c in components.values()), 1
    )

    if composite >= 60:
        label = "High Risk"
    elif composite >= 35:
        label = "Medium Risk"
    else:
        label = "Low Risk"

    # Flags — surface the model-level signals first
    flags: list[str] = []
    if altman_dict.get("zone") == "Distress":
        z = altman_dict.get("z_score")
        flags.append(f"Altman Z-Score in Distress zone (Z={z:.2f})" if z else
                     "Altman Z-Score: Distress zone")
    if beneish_dict.get("flag") == "Likely Manipulator":
        m = beneish_dict.get("m_score")
        flags.append(f"Beneish M-Score flags probable earnings manipulation (M={m:.2f})"
                     if m else "Beneish M-Score: Likely Manipulator")
    flags.extend(cf_flags)
    flags.extend(fund_flags)

    # Confidence — how much data the ensemble actually had
    confidence = round(
        (28 if altman_avail else 0)
        + (20 if beneish_score is not None else 0)
        + min(fund_n / len(_FULL_METRICS) * 32, 32)
        + (10 if advanced.get("icr") is not None else 0)
        + (10 if advanced.get("fcf_margin") is not None else 0)
    )

    sector_known = sector in SECTOR_RISK_PROFILES

    def _component_out(name: str, extra: dict) -> dict:
        if name in components:
            c = components[name]
            return {"score": c["score"], "weight": round(c["base_w"] / total_w, 3),
                    "available": True, **extra}
        return {"score": None, "weight": 0.0, "available": False, **extra}

    parts = [f"{n} {components[n]['base_w']/total_w:.0%}" for n in components]
    methodology = (
        "Orthogonal ensemble (components share no inputs): " + " + ".join(parts)
        + (". Altman unavailable — fundamental scorecard running in full mode."
           if not altman_avail else
           ". Fundamental scorecard scores only growth/beta/P/E; "
           "leverage/liquidity/profitability are owned by Altman.")
    )

    return {
        "composite_score": composite,
        "composite_label": label,
        "confidence":      confidence,
        "components": {
            "altman": _component_out("altman", {
                "zone": altman_dict.get("zone"),
                "z_score": altman_dict.get("z_score"),
                "owns": "leverage, liquidity, operating profitability, solvency",
            }),
            "beneish": _component_out("beneish", {
                "flag": beneish_dict.get("flag"),
                "m_score": beneish_dict.get("m_score"),
                "owns": "earnings manipulation",
            }),
            "fundamental": {
                "score": fund_score,
                "weight": round(components["fundamental"]["base_w"] / total_w, 3),
                "available": True,
                "mode": "full" if not altman_avail else "slim (growth/beta/P/E only)",
                "metrics_scored": fund_metrics,
                "sector_relative": True,
                "owns": "growth trajectory, market volatility, valuation risk",
            },
            "cashflow": _component_out("cashflow", {
                "icr": advanced.get("icr"),
                "fcf_margin": advanced.get("fcf_margin"),
                "owns": "debt serviceability, cash generation",
            }),
        },
        "flags":             flags,
        "sector_calibrated": sector_known,
        "methodology":       methodology,
    }
