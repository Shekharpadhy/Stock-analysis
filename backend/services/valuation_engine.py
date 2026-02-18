"""
Valuation Engine — Monte Carlo DCF with honest uncertainty.

Design (addresses prior defects 2, 4, 5):

  Defect 2 — Scenarios are now probabilistic, not mechanical.
    Bear / Base / Bull / Stretched are read as the 10th / 50th / 90th / 98th
    percentiles of a 10,000-run Monte Carlo simulation over distributions of
    growth, WACC, terminal growth, and starting cash-flow. They are no longer
    base × fixed-multiplier.

  Defect 5 — DCF is the spine; earnings-based methods are corroboration only.
    Price targets come ONLY from the Monte Carlo DCF. P/E and PEG fair values
    are computed as cross-checks and never vote on the target. This removes the
    circularity where forward-EPS (which IS analyst consensus) fed three
    "independent" methods. When no FCF exists, the DCF falls back to an
    EPS-projection spine — and confidence is capped lower, because in that case
    there is no FCF-independent anchor.

  Defect 4 — Disagreement collapses confidence, loudly.
    valuation_confidence is driven by (a) the internal Monte Carlo spread and
    (b) how far the earnings-multiple and analyst cross-checks sit from the DCF
    median. Wide disagreement → low confidence + an explicit agreement label
    and a human-readable note.

Reproducibility: the RNG is seeded from the ticker, so the same inputs always
produce the same output (a quality requirement, not just a nicety).

Accuracy note: percentiles describe model uncertainty given the assumptions —
they are not guaranteed price forecasts. The assumption distributions below are
reasonable estimates; they should be refined against measured data in Phase 3.
"""

import hashlib
from typing import Optional

import numpy as np


# ── Sector median multiples (used for the EPS-spine exit multiple and the
#    P/E corroboration cross-check). Long-run historical estimates. ──────────
SECTOR_MULTIPLES: dict[str, dict] = {
    "Information Technology": {"pe": 26.0, "growth_proxy": 0.14},
    "Technology":             {"pe": 26.0, "growth_proxy": 0.14},
    "Health Care":            {"pe": 21.0, "growth_proxy": 0.10},
    "Financials":             {"pe": 13.0, "growth_proxy": 0.08},
    "Consumer Discretionary": {"pe": 22.0, "growth_proxy": 0.10},
    "Consumer Staples":       {"pe": 20.0, "growth_proxy": 0.07},
    "Industrials":            {"pe": 20.0, "growth_proxy": 0.09},
    "Materials":              {"pe": 16.0, "growth_proxy": 0.08},
    "Energy":                 {"pe": 14.0, "growth_proxy": 0.05},
    "Utilities":              {"pe": 17.0, "growth_proxy": 0.05},
    "Real Estate":            {"pe": 28.0, "growth_proxy": 0.06},
    "Communication Services": {"pe": 18.0, "growth_proxy": 0.09},
}
_DEFAULT_MULTIPLES = {"pe": 18.0, "growth_proxy": 0.09}

# Monte Carlo
_N_SIMS = 10_000

# Assumption-distribution parameters (1-sigma scales)
_WACC_SIGMA      = 0.012   # WACC is fairly stable year-to-year
_TERMINAL_G_MEAN = 0.025
_TERMINAL_G_SIGMA = 0.005
_FCF_NOISE_SIGMA = 0.08    # trailing FCF is a noisy proxy for normalised FCF
_EPS_NOISE_SIGMA = 0.10
_EXIT_PE_SIGMA_FRAC = 0.30 # sector P/E varies widely across the cycle

# Entry / exit / stop constants (relative to the probabilistic targets)
_ENTRY_LOW  = 0.82   # buy-zone floor: 18% below base fair value
_ENTRY_HIGH = 0.91   # buy-zone ceiling: 9% below base fair value
_TRIM       = 0.96   # trim within 4% of the bull target
_STOP_52W   = 0.97   # technical stop reference: just below the 52-week low
_STOP_ENTRY = 0.83   # fundamental stop floor: 17% below the buy-zone floor
_STOP_CEIL  = 0.97   # the stop must sit at least 3% below the buy-zone floor

# Per-year growth deceleration (mean reversion)
_DECEL = np.array([1.00, 0.97, 0.94, 0.91, 0.88])


# ── WACC (CAPM approximation) ────────────────────────────────────────────────
def _wacc(beta: Optional[float], market: str = "global") -> float:
    if market == "india":
        rf, erp = 0.070, 0.050
    else:
        rf, erp = 0.050, 0.055
    b = beta if (beta and 0.1 <= beta <= 4.0) else 1.0
    return rf + b * erp


def _growth_sigma(base_growth: float) -> float:
    """Growth uncertainty scales with the magnitude of the growth estimate."""
    s = 0.40 * abs(base_growth) + 0.02
    return float(np.clip(s, 0.04, 0.12))


def _seed_for(ticker: str) -> int:
    """Deterministic per-ticker seed → reproducible Monte Carlo."""
    digest = hashlib.md5(ticker.upper().encode()).hexdigest()[:8]
    return int(digest, 16)


# ── Monte Carlo DCF — FCF spine ──────────────────────────────────────────────
def _mc_dcf_fcf(
    base_fcf: float,
    base_growth: float,
    base_wacc: float,
    cash: Optional[float],
    debt: Optional[float],
    shares: float,
    rng: np.random.Generator,
) -> np.ndarray:
    n = _N_SIMS
    g  = np.clip(rng.normal(base_growth, _growth_sigma(base_growth), n), -0.35, 0.80)
    w  = np.clip(rng.normal(base_wacc, _WACC_SIGMA, n), 0.06, 0.22)
    tg = rng.normal(_TERMINAL_G_MEAN, _TERMINAL_G_SIGMA, n)
    tg = np.maximum(np.minimum(tg, w - 0.02), 0.0)          # keep tg < wacc
    fcf0 = base_fcf * rng.normal(1.0, _FCF_NOISE_SIGMA, n)  # margin/normalisation noise

    cf = fcf0.copy()
    pv = np.zeros(n)
    for t in range(5):
        cf = cf * (1.0 + g * _DECEL[t])
        pv += cf / (1.0 + w) ** (t + 1)

    tv = cf * (1.0 + tg) / (w - tg)
    pv += tv / (1.0 + w) ** 5

    net_cash = (cash or 0.0) - (debt or 0.0)
    return (pv + net_cash) / shares


# ── Monte Carlo DCF — EPS-projection fallback (no FCF) ───────────────────────
def _mc_dcf_eps(
    eps: float,
    base_growth: float,
    sector_pe: float,
    rng: np.random.Generator,
) -> np.ndarray:
    n = _N_SIMS
    g    = np.clip(rng.normal(base_growth, _growth_sigma(base_growth), n), -0.35, 0.80)
    pe   = np.clip(rng.normal(sector_pe, _EXIT_PE_SIGMA_FRAC * sector_pe, n), 5.0, 60.0)
    eps0 = eps * rng.normal(1.0, _EPS_NOISE_SIGMA, n)
    eps_3yr = eps0 * (1.0 + g) ** 3
    return eps_3yr * pe


def _peg_value(eps: float, growth_decimal: float) -> Optional[float]:
    """PEG = 1.0 fair value: fair P/E = growth% × 100, clamped to a sane band."""
    if growth_decimal <= 0:
        return None
    fair_pe = float(np.clip(growth_decimal * 100.0, 8.0, 50.0))
    return round(eps * fair_pe, 2)


# ── Master valuation function ─────────────────────────────────────────────────
def compute_valuation(data: dict, sector: str = "default") -> dict:
    """
    Monte Carlo DCF valuation with probabilistic Bear/Base/Bull/Stretched
    targets and disagreement-aware confidence.

    Args:
        data:   enriched fundamentals dict from fetch_yahoo_fundamentals_full()
        sector: GICS sector string from classify_sector()
    """
    mults = SECTOR_MULTIPLES.get(sector, _DEFAULT_MULTIPLES)

    ticker         = (data.get("ticker") or "UNKNOWN").upper()
    current_price  = data.get("current_price")
    eps_ttm        = data.get("eps_ttm")
    eps_fwd        = data.get("eps_forward")
    fcf            = data.get("free_cashflow")
    shares         = data.get("shares_outstanding")
    cash           = data.get("total_cash")
    debt           = data.get("total_debt")
    beta           = data.get("beta")
    earn_growth    = data.get("earnings_growth")
    rev_growth_pct = data.get("revenue_growth_yoy")
    fifty_two_low  = data.get("fifty_two_week_low")
    fifty_two_high = data.get("fifty_two_week_high")
    analyst_mean   = data.get("analyst_target_mean")
    analyst_count  = data.get("analyst_count") or 0

    eps = eps_fwd or eps_ttm

    # Best base growth estimate
    if earn_growth and -0.50 < earn_growth < 1.50:
        base_growth = float(earn_growth)
    elif rev_growth_pct:
        base_growth = float(rev_growth_pct) / 100.0
    else:
        base_growth = mults["growth_proxy"]
    base_growth = max(-0.20, min(base_growth, 0.60))

    wacc_base = _wacc(beta)
    rng = np.random.default_rng(_seed_for(ticker))

    # ── Run the Monte Carlo spine ─────────────────────────────────
    sims: Optional[np.ndarray] = None
    spine_kind = None
    if fcf and fcf > 0 and shares and shares > 0:
        sims = _mc_dcf_fcf(fcf, base_growth, wacc_base, cash, debt, shares, rng)
        spine_kind = "fcf"
    elif eps and eps > 0:
        sims = _mc_dcf_eps(eps, base_growth, mults["pe"], rng)
        spine_kind = "eps"

    if sims is None:
        return _empty_valuation(current_price, fifty_two_low, fifty_two_high)

    p10, p50, p90, p98 = (float(x) for x in np.percentile(sims, [10, 50, 90, 98]))
    bear_t  = round(max(p10, 0.0), 2)
    base_t  = round(max(p50, 0.0), 2)
    bull_t  = round(max(p90, 0.0), 2)
    str_t   = round(max(p98, 0.0), 2)

    prob_undervalued = (
        round(float(np.mean(sims > current_price)) * 100.0, 1)
        if current_price else None
    )

    # ── Corroboration cross-checks (do NOT vote on the target) ────
    pe_val:  Optional[float] = round(eps * mults["pe"], 2) if (eps and eps > 0) else None
    peg_val: Optional[float] = _peg_value(eps, base_growth) if (eps and eps > 0) else None
    analyst_val: Optional[float] = (
        analyst_mean if (analyst_mean and analyst_count >= 3) else None
    )

    # Earnings-multiple cross-check = sector-P/E fair value only.
    # PEG is kept as a displayed figure but deliberately excluded from the
    # agreement maths: PEG=1 is a growth rule-of-thumb, not a valuation model
    # of the same class as DCF — including it biases the cross-check low for
    # moderate-growth firms and manufactures false disagreement.
    earnings_xcheck = pe_val

    # ── Disagreement → confidence (defect 4) ──────────────────────
    internal_spread = (p90 - p10) / p50 if p50 > 0 else 2.0  # relative MC width

    gaps: list[float] = []
    if base_t > 0:
        if earnings_xcheck is not None:
            gaps.append(abs(earnings_xcheck - base_t) / base_t)
        if analyst_val is not None:
            gaps.append(abs(analyst_val - base_t) / base_t)
    avg_gap = sum(gaps) / len(gaps) if gaps else None

    confidence = 100.0
    # The EPS-spine has no FCF-independent anchor → structurally less trustworthy.
    if spine_kind == "eps":
        confidence = min(confidence, 62.0)
    # Monte Carlo internal width is separate model uncertainty. A DCF with a
    # terminal value is inherently wide (~0.7–0.9 p10–p90 spread is normal);
    # penalise only excess width beyond that baseline.
    confidence -= min(30.0, max(0.0, internal_spread - 0.45) * 35.0)
    # Cross-checks disagree with the DCF → lower confidence, loudly.
    if avg_gap is not None:
        confidence -= min(34.0, avg_gap * 90.0)
    else:
        confidence -= 12.0  # no independent corroboration available at all
    # Thin analyst coverage → mild penalty.
    if analyst_count < 3:
        confidence -= 6.0
    confidence = int(round(max(5.0, min(confidence, 95.0))))

    # Agreement label reflects CROSS-METHOD consensus only. The Monte Carlo
    # internal spread is a separate axis (model uncertainty) — it already feeds
    # the confidence number above. It must NOT gate this label, or a wide-but-
    # consistent DCF gets mislabelled "disagree".
    if avg_gap is None:
        agreement = "unverified"
        note = ("No independent cross-check available (no analyst coverage and "
                "no earnings-multiple estimate) — treat the target as a model "
                "estimate only.")
    elif avg_gap < 0.10:
        agreement = "high"
        note = (f"DCF and the independent cross-checks agree within "
                f"{avg_gap*100:.0f}% — the target is well corroborated.")
    elif avg_gap < 0.25:
        agreement = "moderate"
        note = (f"DCF and cross-checks diverge by ~{avg_gap*100:.0f}%. The base "
                f"target is usable; the Bear–Bull range carries the uncertainty.")
    else:
        agreement = "low"
        parts = [f"DCF base ₹{base_t:,.0f}"]
        if earnings_xcheck is not None:
            parts.append(f"earnings-multiple ₹{earnings_xcheck:,.0f}")
        if analyst_val is not None:
            parts.append(f"analyst ₹{analyst_val:,.0f}")
        note = ("Methods strongly disagree (" + " vs ".join(parts) +
                "). Treat this valuation as low-confidence — the inputs do not "
                "tell a consistent story.")

    # ── Entry / Trim / Hard Stop ──────────────────────────────────
    entry_low  = round(base_t * _ENTRY_LOW,  2) if base_t else None
    entry_high = round(base_t * _ENTRY_HIGH, 2) if base_t else None
    trim_level = round(bull_t * _TRIM,        2) if bull_t else None
    hard_stop: Optional[float] = None
    if entry_low:
        # Fundamental floor; the 52-week low tightens it upward when relevant.
        raw_stop = entry_low * _STOP_ENTRY
        if fifty_two_low:
            raw_stop = max(raw_stop, fifty_two_low * _STOP_52W)
        # But the stop must sit strictly below the buy zone — a stop inside the
        # entry zone is incoherent (you would be buying below your own stop).
        hard_stop = round(min(raw_stop, entry_low * _STOP_CEIL), 2)

    # ── Upside / valuation label ──────────────────────────────────
    upside_pct = None
    valuation_label = "Unknown"
    if current_price and base_t:
        upside_pct = round((base_t - current_price) / current_price * 100.0, 1)
        if upside_pct > 20:
            valuation_label = "Undervalued"
        elif upside_pct > 5:
            valuation_label = "Moderately Undervalued"
        elif upside_pct > -5:
            valuation_label = "Fairly Valued"
        elif upside_pct > -20:
            valuation_label = "Moderately Overvalued"
        else:
            valuation_label = "Overvalued"

    methods_used = [
        "Monte Carlo DCF — FCF spine (10k sims)" if spine_kind == "fcf"
        else "Monte Carlo DCF — EPS-projection spine (10k sims)"
    ]
    if earnings_xcheck is not None:
        methods_used.append("Earnings-multiple cross-check")
    if analyst_val is not None:
        methods_used.append(f"Analyst consensus cross-check ({analyst_count} analysts)")

    return {
        # Spine fair value = Monte Carlo median (NOT a blend of circular methods)
        "dcf_fair_value":        base_t,
        "composite_fair_value":  base_t,
        # Corroboration estimates — cross-checks only, never vote on the target
        "pe_fair_value":         pe_val,
        "peg_fair_value":        peg_val,
        "analyst_consensus":     analyst_val,
        # Verdict
        "upside_pct":            upside_pct,
        "valuation_label":       valuation_label,
        "valuation_confidence":  confidence,
        # Probabilistic scenario targets (MC percentiles)
        "bear_target":           bear_t,
        "base_target":           base_t,
        "bull_target":           bull_t,
        "stretched_bull_target": str_t,
        # Actionable levels
        "entry_zone_low":        entry_low,
        "entry_zone_high":       entry_high,
        "trim_level":            trim_level,
        "hard_stop":             hard_stop,
        # Honest-uncertainty fields
        "prob_undervalued":      prob_undervalued,
        "mc_interval":           [bear_t, bull_t],
        "method_agreement":      agreement,
        "agreement_note":        note,
        "methods_used":          methods_used,
        "assumptions": {
            "spine":                 "FCF" if spine_kind == "fcf" else "EPS projection",
            "base_growth_rate_pct":  round(base_growth * 100.0, 1),
            "growth_sigma_pct":      round(_growth_sigma(base_growth) * 100.0, 1),
            "wacc_pct":              round(wacc_base * 100.0, 1),
            "terminal_growth_pct":   round(_TERMINAL_G_MEAN * 100.0, 1),
            "sector_pe_median":      mults["pe"],
            "monte_carlo_runs":      _N_SIMS,
            "internal_spread_pct":   round(internal_spread * 100.0, 1),
        },
    }


def _empty_valuation(price, low, high) -> dict:
    """Returned when there is neither positive FCF nor positive EPS to value."""
    return {
        "dcf_fair_value": None, "composite_fair_value": None,
        "pe_fair_value": None, "peg_fair_value": None, "analyst_consensus": None,
        "upside_pct": None, "valuation_label": "Unvaluable",
        "valuation_confidence": 0,
        "bear_target": None, "base_target": None,
        "bull_target": None, "stretched_bull_target": None,
        "entry_zone_low": None, "entry_zone_high": None,
        "trim_level": None, "hard_stop": None,
        "prob_undervalued": None, "mc_interval": None,
        "method_agreement": "unverified",
        "agreement_note": ("No positive free cash flow and no positive earnings — "
                           "a DCF cannot be run. The company cannot be valued on "
                           "fundamentals alone."),
        "methods_used": [],
        "assumptions": {},
    }
