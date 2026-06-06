"""
Financial Modeling Prep (FMP) — primary fundamentals data source.

Why
───
yfinance scrapes Yahoo Finance, which throttles cloud-IP traffic
aggressively.  FMP is a real API with a sane free tier (250 requests/day)
and meaningfully better coverage for non-US listings — Indian NSE / BSE
tickers (M&M.NS, RELIANCE.NS, etc.) are first-class, where yfinance
treats them as second-class scraped data.

This module is a thin adapter: it fetches from FMP's `/stable/` endpoint
family and returns a dict in the SAME shape as
ingestion.fetch_yahoo_fundamentals_full, so callers can swap providers
without touching the engines downstream.

Endpoints used (all on the free tier as of 2026):
  • /stable/profile?symbol=X            — name, sector, market cap, price, beta
  • /stable/income-statement?symbol=X   — revenue, net income, margins
  • /stable/balance-sheet-statement?X   — debt, cash, equity
  • /stable/cash-flow-statement?X       — free cash flow
  • /stable/key-metrics?symbol=X        — PE, PB, ROE, ROA
  • /stable/ratios?symbol=X             — current ratio, debt-to-equity, etc.

Each ticker analysis hits ~6 endpoints; with the 4-hour cache that's
~6 calls per ticker per 4 hours, easily under the free-tier ceiling.

Failure modes
─────────────
Network error, 401 unauthorised, 429 rate-limit, empty payload — all
yield None so the caller can fall through to yfinance as a backup.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import requests

from backend.config import settings

log = logging.getLogger(__name__)

_BASE = "https://financialmodelingprep.com/stable"
_TIMEOUT = 10  # seconds — short, since this is the fast path


def is_configured() -> bool:
    """True when a FMP_API_KEY is set in settings.  No key → skip FMP entirely."""
    return bool(getattr(settings, "fmp_api_key", "").strip())


def _get(path: str, **params) -> Optional[Any]:
    """
    Wrap requests.get with proper error handling.  Returns the parsed JSON
    payload, or None on any failure (network, 4xx, 5xx, empty response).
    """
    if not is_configured():
        return None
    try:
        params["apikey"] = settings.fmp_api_key
        resp = requests.get(f"{_BASE}{path}", params=params, timeout=_TIMEOUT)
        if resp.status_code == 401:
            log.warning("fmp_adapter: 401 — FMP_API_KEY invalid or expired")
            return None
        if resp.status_code == 429:
            log.warning("fmp_adapter: 429 — FMP rate limit exhausted (free tier 250/day)")
            return None
        if resp.status_code != 200:
            log.warning("fmp_adapter: HTTP %d on %s", resp.status_code, path)
            return None
        data = resp.json()
        # FMP returns lists for record endpoints; treat empty list as miss.
        if isinstance(data, list) and not data:
            return None
        # Some error paths return {"Error Message": "..."} — treat as miss.
        if isinstance(data, dict) and "Error Message" in data:
            log.warning("fmp_adapter: FMP error on %s — %s", path, data.get("Error Message"))
            return None
        return data
    except requests.RequestException as exc:
        log.warning("fmp_adapter: network failure on %s — %s", path, exc)
        return None
    except Exception as exc:                                  # noqa: BLE001
        log.warning("fmp_adapter: unexpected failure on %s — %s", path, exc)
        return None


# ── shape helpers ────────────────────────────────────────────────────────────

def _first(data) -> Optional[Dict[str, Any]]:
    """FMP returns single-row info as `[ {...} ]` — unwrap to the dict."""
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return None


def _safe_pct(value: Optional[float]) -> Optional[float]:
    """Yahoo's fields like profitMargins are decimals; downstream code multiplies
    by 100 itself.  FMP returns the same shape (decimal margins) so we just
    pass-through — but guard against None / NaN."""
    if value is None:
        return None
    try:
        f = float(value)
        return f if f == f else None      # NaN check
    except (TypeError, ValueError):
        return None


def _pct_from_decimal(value: Optional[float]) -> Optional[float]:
    """Convert a decimal (e.g. 0.23) to percentage display (23.0)."""
    v = _safe_pct(value)
    return None if v is None else round(v * 100.0, 2)


# ── public entry point ──────────────────────────────────────────────────────-

def fetch_fundamentals(ticker: str) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """
    Return (fundamentals_dict, raw_payloads_for_advanced_scoring) or None
    if FMP can't satisfy the request.

    Shape of fundamentals_dict matches ingestion.fetch_yahoo_fundamentals_full
    exactly — same keys, same types — so downstream code (compute_ensemble_risk,
    compute_valuation, etc.) is unchanged.

    Shape of raw_payloads is a dict of the four FMP statements
    {balance_sheet, income_statement, cash_flow, ratios, key_metrics} which
    advanced_scores + quality engines can consume in place of yfinance's
    DataFrames.  (Right now those engines call yfinance directly; converting
    them is a follow-up — for the FMP path we currently return None for the
    raw object and the advanced/quality scores degrade gracefully.)
    """
    if not is_configured():
        return None

    ticker_u = ticker.upper().strip()

    # 1. Profile — basic info, price, marketCap, beta
    profile = _first(_get(f"/profile", symbol=ticker_u))
    if not profile:
        return None

    # 2. Latest income statement (full-year)
    income_list = _get(f"/income-statement", symbol=ticker_u, limit=2) or []
    income      = income_list[0] if income_list else {}
    income_prev = income_list[1] if len(income_list) > 1 else {}

    # 3. Balance sheet (latest)
    balance = _first(_get(f"/balance-sheet-statement", symbol=ticker_u, limit=1)) or {}

    # 4. Cash flow (latest)
    cashflow = _first(_get(f"/cash-flow-statement", symbol=ticker_u, limit=1)) or {}

    # 5. Key metrics (PE, PB, ROE, ROA) — TTM if available
    metrics = _first(_get(f"/key-metrics", symbol=ticker_u, limit=1)) or {}

    # 6. Financial ratios (current ratio, debt-to-equity, etc.)
    ratios = _first(_get(f"/ratios", symbol=ticker_u, limit=1)) or {}

    # ── Compose into yfinance-shaped dict ─────────────────────────────────────

    revenue_current = income.get("revenue")
    revenue_prior   = income_prev.get("revenue")
    revenue_growth  = None
    if revenue_current and revenue_prior and revenue_prior != 0:
        revenue_growth = round(
            (revenue_current - revenue_prior) / abs(revenue_prior) * 100, 2
        )

    # Free cash flow — FMP gives us this directly
    fcf = cashflow.get("freeCashFlow")

    data: Dict[str, Any] = {
        # ── Identity ──────────────────────────────────────────────────
        "ticker":                ticker_u,
        "name":                  profile.get("companyName") or ticker_u,
        "sector":                profile.get("sector") or "Unknown",
        "industry":              profile.get("industry") or "Unknown",

        # ── Market / price ───────────────────────────────────────────-
        "market_cap":            profile.get("marketCap"),
        "current_price":         profile.get("price"),
        "fifty_two_week_high":   _parse_range_high(profile.get("range")),
        "fifty_two_week_low":    _parse_range_low(profile.get("range")),
        "beta":                  profile.get("beta"),

        # ── Income ────────────────────────────────────────────────────
        "revenue_ttm":           revenue_current,
        "revenue_growth_yoy":    revenue_growth,
        "earnings_growth":       None,   # not in FMP profile; left None
        "net_margin":            _pct_from_decimal(ratios.get("netProfitMargin")),
        "roa":                   _pct_from_decimal(ratios.get("returnOnAssets")
                                                    or metrics.get("returnOnTangibleAssets")),
        "roe":                   _pct_from_decimal(ratios.get("returnOnEquity")
                                                    or metrics.get("roe")),

        # ── Valuation multiples ───────────────────────────────────────
        "pe_ratio":              metrics.get("peRatio") or ratios.get("priceToEarningsRatio"),
        "forward_pe":            None,   # not in free tier reliably
        "peg_ratio":             metrics.get("pegRatio"),
        "ev_ebitda":             metrics.get("enterpriseValueOverEBITDA"),
        "ev_revenue":            metrics.get("evToSales"),

        # ── Per-share ────────────────────────────────────────────────-
        "eps_ttm":               income.get("eps"),
        "eps_forward":           None,

        # ── Balance sheet ─────────────────────────────────────────────
        "debt_to_equity":        ratios.get("debtToEquityRatio")
                                  or ratios.get("debtEquityRatio"),
        "current_ratio":         ratios.get("currentRatio"),
        "total_cash":            balance.get("cashAndCashEquivalents")
                                  or balance.get("cashAndShortTermInvestments"),
        "total_debt":            balance.get("totalDebt"),
        "shares_outstanding":    income.get("weightedAverageShsOut")
                                  or profile.get("sharesOutstanding"),

        # ── Cash flow ────────────────────────────────────────────────-
        "free_cashflow":         fcf,

        # ── Analyst data ─────────────────────────────────────────────-
        # FMP's analyst endpoints are paid; leave None on free tier.
        "analyst_target_mean":   None,
        "analyst_target_high":   None,
        "analyst_target_low":    None,
        "analyst_count":         None,
        "recommendation":        None,

        # ── Income distribution ──────────────────────────────────────-
        "dividend_yield":        _pct_from_decimal(ratios.get("dividendYield")),
        "payout_ratio":          _pct_from_decimal(ratios.get("dividendPayoutRatio")),
    }

    # Raw payloads for advanced_scores / quality engines — None for now;
    # those engines will fall through to their "missing data" branches and
    # return Unavailable sentinels.  A future commit can teach them to read
    # from these FMP payloads directly.
    raw_for_advanced = {
        "income":   income,
        "balance":  balance,
        "cashflow": cashflow,
        "ratios":   ratios,
        "metrics":  metrics,
    }
    return data, raw_for_advanced


# ── range parsing ─────────────────────────────────────────────────────────────

def _parse_range_high(range_str: Optional[str]) -> Optional[float]:
    """FMP's 'range' field looks like '195.07-316.94'. Return the high."""
    if not range_str or "-" not in range_str:
        return None
    try:
        return float(range_str.split("-")[1].strip())
    except (ValueError, IndexError):
        return None


def _parse_range_low(range_str: Optional[str]) -> Optional[float]:
    """FMP's 'range' field looks like '195.07-316.94'. Return the low."""
    if not range_str or "-" not in range_str:
        return None
    try:
        return float(range_str.split("-")[0].strip())
    except (ValueError, IndexError):
        return None
