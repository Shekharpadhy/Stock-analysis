"""
Point-in-time input reconstruction.

Rebuilds the (raw, advanced) input dicts that compute_ensemble_risk() and
compute_valuation() consume — but for a PAST fiscal year, using only data that
was knowable shortly after that year was reported.

Sources:
  - yfinance annual statements (income / balance sheet / cash flow), ~4 years
  - the price_history table (Task 8) for historical prices and 52-week ranges

Honest limitations — this is APPROXIMATE point-in-time, not true PIT:
  - Statements are yfinance's current view; minor restatements are not undone.
  - beta is not reconstructed (omitted → the valuation engine defaults its WACC
    beta to 1.0 and the risk scorecard simply skips beta).
  - analyst targets / forward EPS have no free history (omitted → the valuation
    engine runs without the analyst cross-check; the DCF spine is unaffected).

The reporting lag IS modelled: a fiscal year's data is treated as available
fiscal_year_end + 90 days (the typical annual-report filing delay), and that
is the `as_of` date used for the price lookup and forward-return measurement.
"""

import datetime as dt
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from backend.services.advanced_scores import (
    _row, _val,
    compute_altman, compute_beneish,
    compute_interest_coverage, compute_fcf_margin,
)
from backend.services.price_history import price_on, trailing_high_low

_FILING_LAG_DAYS = 90


# ── Date / slicing helpers ────────────────────────────────────────────────────
def _to_date(col) -> dt.date:
    if isinstance(col, dt.datetime):
        return col.date()
    if isinstance(col, dt.date):
        return col
    return pd.Timestamp(col).date()


def _slice_from(df, fy_end: dt.date):
    """Keep columns dated on/before fy_end, most-recent first (col 0 = target)."""
    if df is None or getattr(df, "empty", True):
        return df
    keep = sorted([c for c in df.columns if _to_date(c) <= fy_end],
                  key=_to_date, reverse=True)
    return df[keep] if keep else df.iloc[:, :0]


def _pct_change(cur, prior) -> Optional[float]:
    if cur is None or prior in (None, 0):
        return None
    return round((cur - prior) / abs(prior) * 100.0, 2)


def _ratio(num, den, pct: bool = False) -> Optional[float]:
    if num is None or den in (None, 0):
        return None
    r = num / den
    return round(r * 100.0, 2) if pct else round(r, 4)


# ── Public API ────────────────────────────────────────────────────────────────
def available_fiscal_years(inc) -> list[dt.date]:
    """Fiscal year-end dates (most recent first) that have a usable prior year."""
    if inc is None or getattr(inc, "empty", True):
        return []
    dates = sorted({_to_date(c) for c in inc.columns}, reverse=True)
    return dates[:-1]   # the oldest column has no prior year → drop it


def fetch_statements(ticker: str):
    """Fetch the three annual statements from yfinance. Network call."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    return t.balance_sheet, t.financials, t.cashflow


def reconstruct_inputs(
    ticker: str, bs, inc, cf, fy_end: dt.date, db: Session,
) -> Optional[dict]:
    """
    Reconstruct the engine inputs for `ticker` as of the fiscal year ending
    `fy_end`.

    Returns {"ticker", "fy_end", "as_of", "raw", "advanced"}, or None when there
    is no prior year (needed for YoY growth and the Beneish M-Score).
    """
    inc_s = _slice_from(inc, fy_end)
    if inc_s is None or getattr(inc_s, "empty", True) or inc_s.shape[1] < 2:
        return None
    bs_s = _slice_from(bs, fy_end)
    cf_s = _slice_from(cf, fy_end)

    as_of = fy_end + dt.timedelta(days=_FILING_LAG_DAYS)

    raw = _build_raw(ticker, bs_s, inc_s, cf_s, as_of, db)
    icr = compute_interest_coverage(inc_s)
    advanced = {
        "altman":     compute_altman(bs_s, inc_s),
        "beneish":    compute_beneish(bs_s, inc_s, cf_s),
        "icr":        icr["icr"],
        "icr_label":  icr["icr_label"],
        "fcf_margin": compute_fcf_margin(inc_s, cf_s),
    }
    return {
        "ticker": ticker.upper(),
        "fy_end": fy_end,
        "as_of":  as_of,
        "raw":    raw,
        "advanced": advanced,
    }


# ── Internals ─────────────────────────────────────────────────────────────────
def _build_raw(ticker, bs, inc, cf, as_of: dt.date, db: Session) -> dict:
    """Reconstruct the `raw` fundamentals dict from sliced statements + prices."""
    rev          = _row(inc, "Total Revenue", "Operating Revenue")
    rev_0, rev_1 = _val(rev, 0), _val(rev, 1)
    ni_s         = _row(inc, "Net Income", "Net Income Common Stockholders")
    ni_0, ni_1   = _val(ni_s, 0), _val(ni_s, 1)
    eps_s        = _row(inc, "Diluted EPS", "Basic EPS")
    eps_0, eps_1 = _val(eps_s, 0), _val(eps_s, 1)

    total_assets = _val(_row(bs, "Total Assets"), 0)
    equity       = _val(_row(bs, "Common Stock Equity", "Stockholders Equity",
                              "Total Equity Gross Minority Interest"), 0)
    total_debt   = _val(_row(bs, "Total Debt",
                              "Long Term Debt And Capital Lease Obligation"), 0)
    cur_assets   = _val(_row(bs, "Current Assets"), 0)
    cur_liab     = _val(_row(bs, "Current Liabilities"), 0)
    cash         = _val(_row(bs, "Cash And Cash Equivalents",
                              "Cash Cash Equivalents And Short Term Investments"), 0)
    shares       = _val(_row(bs, "Ordinary Shares Number", "Share Issued"), 0)
    fcf          = _val(_row(cf, "Free Cash Flow"), 0)

    # EPS fallback: net income / shares when an EPS line is absent.
    if eps_0 is None and ni_0 is not None and shares:
        eps_0 = round(ni_0 / shares, 4)
    if eps_1 is None and ni_1 is not None and shares:
        eps_1 = round(ni_1 / shares, 4)

    # Earnings growth (decimal) — prefer EPS, fall back to net income.
    earnings_growth = None
    if eps_0 is not None and eps_1 not in (None, 0):
        earnings_growth = round(eps_0 / eps_1 - 1.0, 4)
    elif ni_0 is not None and ni_1 not in (None, 0):
        earnings_growth = round(ni_0 / ni_1 - 1.0, 4)

    price = price_on(db, ticker, as_of, tolerance_days=20)
    pe    = _ratio(price, eps_0) if (price and eps_0 and eps_0 > 0) else None
    hi, lo = trailing_high_low(db, ticker, as_of)

    # Negative shareholder equity makes D/E and ROE meaningless — and ROE
    # actively misleading, since a loss divided by negative equity flips it
    # positive. Treat both as unknown; Altman's X4 still flags the distress.
    equity_ok      = equity is not None and equity > 0
    debt_to_equity = _ratio(total_debt, equity, pct=True) if equity_ok else None
    roe            = _ratio(ni_0, equity, pct=True) if equity_ok else None

    return {
        "ticker":              ticker.upper(),
        "current_price":       price,
        "revenue_ttm":         rev_0,
        "revenue_growth_yoy":  _pct_change(rev_0, rev_1),
        "earnings_growth":     earnings_growth,
        "net_margin":          _ratio(ni_0, rev_0, pct=True),
        "roa":                 _ratio(ni_0, total_assets, pct=True),
        "roe":                 roe,
        "pe_ratio":            pe,
        "eps_ttm":             eps_0,
        "eps_forward":         None,                    # no free history
        "debt_to_equity":      debt_to_equity,
        "current_ratio":       _ratio(cur_assets, cur_liab),
        "total_cash":          cash,
        "total_debt":          total_debt,
        "shares_outstanding":  shares,
        "free_cashflow":       fcf,
        "beta":                None,                    # not reconstructed
        "fifty_two_week_high": hi,
        "fifty_two_week_low":  lo,
        "analyst_target_mean": None,                    # no free history
        "analyst_count":       0,
    }
