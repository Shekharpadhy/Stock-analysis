"""
Quality scoring — the Quality dimension of the BCSI composite.

  Piotroski F-Score   A 9-point fundamental-quality checklist (Piotroski 2000).
                      Stocks scoring 8-9 have historically outperformed; 0-2
                      underperform. Profitability (4) + leverage/liquidity (3)
                      + operating efficiency (2).
  Graham Number       Benjamin Graham's intrinsic-value ceiling:
                      sqrt(22.5 x EPS x book-value-per-share).
  Magic Formula       Greenblatt's two quality/value metrics — earnings yield
                      (EBIT / enterprise value) and return on capital
                      (EBIT / (net working capital + net fixed assets)).

Everything is computed from the financial statements yfinance already provides
plus a few fields from the fundamentals dict — no extra data fetch.
"""

import math
import warnings
from typing import Optional

from backend.services.advanced_scores import _row, _val


def _gt(a, b) -> bool:
    """True only when both values exist and a > b."""
    return a is not None and b is not None and a > b


# ── Piotroski F-Score ─────────────────────────────────────────────────────────
def compute_piotroski(bs, inc, cf) -> dict:
    """
    9-point Piotroski F-Score. A criterion that cannot be verified (missing
    data) scores 0 — the standard conservative treatment.
    """
    ni_0 = _val(_row(inc, "Net Income", "Net Income Common Stockholders"), 0)
    ni_1 = _val(_row(inc, "Net Income", "Net Income Common Stockholders"), 1)
    ta_0 = _val(_row(bs, "Total Assets"), 0)
    ta_1 = _val(_row(bs, "Total Assets"), 1)
    ocf  = _val(_row(cf, "Operating Cash Flow",
                     "Cash Flow From Continuing Operating Activities"), 0)
    rev_0 = _val(_row(inc, "Total Revenue", "Operating Revenue"), 0)
    rev_1 = _val(_row(inc, "Total Revenue", "Operating Revenue"), 1)
    gp_0  = _val(_row(inc, "Gross Profit"), 0)
    gp_1  = _val(_row(inc, "Gross Profit"), 1)
    ltd_0 = _val(_row(bs, "Long Term Debt",
                      "Long Term Debt And Capital Lease Obligation"), 0)
    ltd_1 = _val(_row(bs, "Long Term Debt",
                      "Long Term Debt And Capital Lease Obligation"), 1)
    ca_0 = _val(_row(bs, "Current Assets"), 0)
    ca_1 = _val(_row(bs, "Current Assets"), 1)
    cl_0 = _val(_row(bs, "Current Liabilities"), 0)
    cl_1 = _val(_row(bs, "Current Liabilities"), 1)
    sh_0 = _val(_row(bs, "Ordinary Shares Number", "Share Issued"), 0)
    sh_1 = _val(_row(bs, "Ordinary Shares Number", "Share Issued"), 1)

    def _ratio(n, d):
        return n / d if (n is not None and d) else None

    criteria = {
        # Profitability
        "positive_net_income":         bool(ni_0 is not None and ni_0 > 0),
        "positive_operating_cash_flow": bool(ocf is not None and ocf > 0),
        "roa_improved":   _gt(_ratio(ni_0, ta_0), _ratio(ni_1, ta_1)),
        "cash_exceeds_earnings": bool(ocf is not None and ni_0 is not None and ocf > ni_0),
        # Leverage / liquidity / funding
        "leverage_decreased": (
            _ratio(ltd_0, ta_0) is not None and _ratio(ltd_1, ta_1) is not None
            and _ratio(ltd_0, ta_0) < _ratio(ltd_1, ta_1)
        ),
        "current_ratio_improved": _gt(_ratio(ca_0, cl_0), _ratio(ca_1, cl_1)),
        "no_share_dilution": bool(sh_0 is not None and sh_1 is not None and sh_0 <= sh_1),
        # Operating efficiency
        "gross_margin_improved":  _gt(_ratio(gp_0, rev_0), _ratio(gp_1, rev_1)),
        "asset_turnover_improved": _gt(_ratio(rev_0, ta_0), _ratio(rev_1, ta_1)),
    }
    return {
        "f_score": sum(1 for passed in criteria.values() if passed),
        "max": 9,
        "criteria": criteria,
    }


# ── Graham Number ─────────────────────────────────────────────────────────────
def graham_number(eps: Optional[float], bvps: Optional[float]) -> Optional[float]:
    """Graham's intrinsic-value ceiling. Defined only for positive EPS and BVPS."""
    if eps is None or bvps is None or eps <= 0 or bvps <= 0:
        return None
    return round(math.sqrt(22.5 * eps * bvps), 2)


# ── Magic Formula metrics ─────────────────────────────────────────────────────
def magic_formula(inc, bs, raw: dict) -> dict:
    """Greenblatt's earnings yield (EBIT/EV) and return on capital."""
    ebit = _val(_row(inc, "EBIT", "Operating Income"), 0)
    market_cap = raw.get("market_cap")
    total_debt = raw.get("total_debt") or 0
    cash = raw.get("total_cash") or 0

    earnings_yield = None
    if ebit is not None and market_cap:
        ev = market_cap + total_debt - cash
        if ev > 0:
            earnings_yield = round(ebit / ev * 100, 2)

    ca  = _val(_row(bs, "Current Assets"), 0)
    cl  = _val(_row(bs, "Current Liabilities"), 0)
    nfa = _val(_row(bs, "Net PPE", "Net Property Plant And Equipment"), 0)
    return_on_capital = None
    if ebit is not None and None not in (ca, cl, nfa):
        capital = (ca - cl) + nfa
        if capital > 0:
            return_on_capital = round(ebit / capital * 100, 2)

    return {
        "earnings_yield_pct": earnings_yield,
        "return_on_capital_pct": return_on_capital,
    }


# ── Master ─────────────────────────────────────────────────────────────────────
def quality_from_statements(bs, inc, cf, raw: dict) -> dict:
    """Compute the full quality picture from statement DataFrames + the raw dict."""
    piotroski = compute_piotroski(bs, inc, cf)

    equity = _val(_row(bs, "Common Stock Equity", "Stockholders Equity",
                       "Total Equity Gross Minority Interest"), 0)
    shares = raw.get("shares_outstanding")
    bvps = (equity / shares
            if (equity and shares and equity > 0 and shares > 0) else None)
    graham = graham_number(raw.get("eps_ttm"), bvps)

    f = piotroski["f_score"]
    quality_score = round(f / 9 * 100, 1)
    if f >= 7:
        label = "Strong"
    elif f >= 4:
        label = "Adequate"
    else:
        label = "Weak"

    return {
        "quality_score": quality_score,     # 0–100, higher = better
        "quality_label": label,
        "piotroski": piotroski,
        "graham_number": graham,
        "magic_formula": magic_formula(inc, bs, raw),
    }


def compute_quality(ticker_obj, raw: dict) -> dict:
    """Read the statements off a yfinance Ticker and compute the quality score."""
    # Same retry-wrapped yfinance access as ingestion + advanced_scores.
    from backend.services.ingestion import _safe_yf
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bs  = _safe_yf(lambda: ticker_obj.balance_sheet)
            inc = _safe_yf(lambda: ticker_obj.financials)
            cf  = _safe_yf(lambda: ticker_obj.cashflow)
        return quality_from_statements(bs, inc, cf, raw)
    except Exception:
        return {
            "quality_score": None, "quality_label": "Unknown",
            "piotroski": {"f_score": 0, "max": 9, "criteria": {}},
            "graham_number": None,
            "magic_formula": {"earnings_yield_pct": None,
                              "return_on_capital_pct": None},
        }
