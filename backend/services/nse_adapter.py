"""
NSE India — direct public-endpoint adapter for Indian (.NS) tickers.

Why
───
FMP's free tier ships only the /profile endpoint for international listings
(price, market cap, beta, 52-wk range) but NOT the financial statements that
power Altman Z, Beneish M, Piotroski, Quality Score, etc.  yfinance — our
historical fallback — is blocked at the IP level by Yahoo when called from
cloud providers (Render, Fly, Railway).  Result: Indian tickers analysed in
production showed mostly blank tiles.

This adapter calls NSE India's own public JSON endpoints directly.  NSE
serves the data the website itself consumes, so coverage matches what an
end-user sees on nseindia.com.

How NSE's endpoints behave
──────────────────────────
NSE requires a session cookie obtained by first hitting the landing page
with a browser-like User-Agent.  The cookie is then sent on every API call
or the request returns 401.  We rebuild the session lazily and cache it
in-process — a single warm cookie covers many requests.

Endpoints used
──────────────
  • /api/quote-equity?symbol=X            — last price, day/52-wk range, total
                                            traded value, change
  • /api/equity-meta-info?symbol=X        — companyName, industry, sector
  • /api/corporates-financial-results?... — quarterly results filings
                                            (XBRL parsing TBD — out of scope
                                            for v1)

What this adapter CAN fill
──────────────────────────
  name, sector, industry, current_price, market_cap, beta, 52-wk hi/lo,
  shares_outstanding (computed: market_cap / current_price)

What it CANNOT fill
───────────────────
  Full income statement, balance sheet, cash flow.  NSE serves these as
  XBRL attachments on /corporates-financial-results which need separate
  parsing.  For now those fields stay None and downstream engines return
  Unavailable sentinels — same behaviour as the FMP-only fallback.  The
  showcase snapshot pipeline (run from a residential IP) fills the gap
  for the curated demo ticker list.

Failure modes
─────────────
Network error, non-200 response, missing required key in payload — all
yield None so callers fall through to yfinance / showcase / Unavailable.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

import requests

log = logging.getLogger(__name__)

_BASE = "https://www.nseindia.com"
_TIMEOUT = 8

# Browser-like headers — NSE's WAF rejects bare python-requests UA.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Safari/605.1.15"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# Session is reused across calls so the warm cookie covers many requests.
# Reset every COOKIE_TTL seconds because NSE rotates session cookies.
_SESSION: Optional[requests.Session] = None
_SESSION_AT: float = 0.0
_SESSION_TTL = 300  # 5 minutes — comfortably inside NSE's rotation window
_SESSION_LOCK = threading.Lock()


def _get_session() -> Optional[requests.Session]:
    """Build (or refresh) the NSE session with a warm cookie.

    NSE requires a first GET to the landing page so the WAF sets cookies.
    Without that warm-up step every /api/* call returns 401.
    """
    global _SESSION, _SESSION_AT
    now = time.time()
    with _SESSION_LOCK:
        if _SESSION is not None and (now - _SESSION_AT) < _SESSION_TTL:
            return _SESSION
        try:
            s = requests.Session()
            s.headers.update(_HEADERS)
            # Two warm-up hits — NSE sometimes serves the cookie only on the
            # second request because the first triggers a CSRF redirect.
            s.get(_BASE, timeout=_TIMEOUT)
            s.get(f"{_BASE}/market-data/live-equity-market", timeout=_TIMEOUT)
            _SESSION = s
            _SESSION_AT = now
            return s
        except requests.RequestException as exc:
            log.warning("nse_adapter: session warm-up failed — %s", exc)
            _SESSION = None
            return None


def _strip_ns(ticker: str) -> str:
    """RELIANCE.NS → RELIANCE.  NSE's own API doesn't use the .NS suffix."""
    return ticker.upper().replace(".NS", "").strip()


def is_indian_ticker(ticker: str) -> bool:
    """True if ticker looks like an NSE listing.  Used by the ingestion
    pipeline to decide whether to attempt this adapter at all."""
    return ticker.upper().endswith(".NS")


def _get_json(path: str, **params) -> Optional[Any]:
    """GET an NSE endpoint with the warm session.  Retries once if the
    session cookie expired in flight (NSE returns 401 in that case)."""
    for attempt in range(2):
        session = _get_session()
        if session is None:
            return None
        try:
            resp = session.get(f"{_BASE}{path}", params=params, timeout=_TIMEOUT)
            if resp.status_code == 401 and attempt == 0:
                # Cookie expired mid-flight — force a session refresh.
                global _SESSION
                _SESSION = None
                continue
            if resp.status_code != 200:
                log.info("nse_adapter: HTTP %d on %s", resp.status_code, path)
                return None
            return resp.json()
        except requests.RequestException as exc:
            log.info("nse_adapter: network failure on %s — %s", path, exc)
            return None
        except ValueError:  # JSONDecodeError subclasses ValueError
            log.info("nse_adapter: non-JSON response on %s", path)
            return None
    return None


def fetch_fundamentals(ticker: str) -> Optional[Dict[str, Any]]:
    """Return a fundamentals dict for ticker, or None if NSE can't help.

    The shape matches what fmp_adapter.fetch_fundamentals returns so callers
    don't need to special-case the source.  Statement fields not exposed by
    NSE's public API stay None.
    """
    if not is_indian_ticker(ticker):
        return None

    sym = _strip_ns(ticker)

    quote = _get_json("/api/quote-equity", symbol=sym)
    if not quote:
        return None

    meta = _get_json("/api/equity-meta-info", symbol=sym) or {}

    info        = quote.get("info") or {}
    price_info  = quote.get("priceInfo") or {}
    sec_info    = quote.get("securityInfo") or {}
    industry    = quote.get("industryInfo") or {}
    week_range  = price_info.get("weekHighLow") or {}

    current_price = _to_float(price_info.get("lastPrice"))
    issued_size   = _to_float(sec_info.get("issuedSize"))  # shares outstanding
    market_cap    = None
    if current_price is not None and issued_size is not None:
        market_cap = round(current_price * issued_size, 2)

    name = (
        info.get("companyName")
        or meta.get("companyName")
        or sym
    )

    sector = (
        industry.get("macro")
        or industry.get("sector")
        or meta.get("industry")
        or "Unknown"
    )
    industry_name = (
        industry.get("industry")
        or industry.get("basicIndustry")
        or sector
    )

    data: Dict[str, Any] = {
        # ── Identity ──────────────────────────────────────────────
        "ticker":              ticker.upper(),
        "name":                name,
        "sector":              sector,
        "industry":            industry_name,

        # ── Market / price ────────────────────────────────────────
        "market_cap":          market_cap,
        "current_price":       current_price,
        "fifty_two_week_high": _to_float(week_range.get("max")),
        "fifty_two_week_low":  _to_float(week_range.get("min")),
        "beta":                None,    # NSE doesn't publish beta

        # ── Income / margins / per-share (NSE doesn't ship these) ─
        "revenue_ttm":         None,
        "revenue_growth_yoy":  None,
        "earnings_growth":     None,
        "net_margin":          None,
        "roa":                 None,
        "roe":                 None,

        # ── Valuation multiples (NSE quote-equity does NOT ship these
        #     — they live on the financial-results filings and need XBRL) ─
        "pe_ratio":            None,
        "forward_pe":          None,
        "peg_ratio":           None,
        "ev_ebitda":           None,
        "ev_revenue":          None,

        # ── Per-share ────────────────────────────────────────────-
        "eps_ttm":             None,
        "eps_forward":         None,

        # ── Balance sheet ────────────────────────────────────────-
        "debt_to_equity":      None,
        "current_ratio":       None,
        "total_cash":          None,
        "total_debt":          None,
        "shares_outstanding":  issued_size,

        # ── Cash flow ────────────────────────────────────────────-
        "free_cashflow":       None,

        # ── Analyst data ─────────────────────────────────────────-
        "analyst_target_mean": None,
        "analyst_target_high": None,
        "analyst_target_low":  None,
        "analyst_count":       None,
        "recommendation":      None,

        # ── Income distribution ──────────────────────────────────-
        "dividend_yield":      None,
        "payout_ratio":        None,
    }
    return data


def _to_float(value) -> Optional[float]:
    """NSE returns numbers as strings sometimes ('1,217.50') — normalise."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
