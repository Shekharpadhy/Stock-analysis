import logging
import time
import yfinance as yf

# ── Browser-impersonating session (curl_cffi) ────────────────────────────────
# Yahoo Finance aggressively throttles requests with a "python-requests" or
# default User-Agent.  curl_cffi mimics a real Safari TLS handshake + headers
# so requests look indistinguishable from a desktop browser, dodging most
# of Yahoo's bot-detection.  This is the single biggest reliability win on
# cloud-hosted IPs.  yfinance 0.2.55+ accepts `session=...` on Ticker().
try:
    from curl_cffi import requests as cffi_requests
    _YF_SESSION = cffi_requests.Session(impersonate="safari15_5")
except Exception:                                              # noqa: BLE001
    # If curl_cffi unavailable (very old Python, missing wheel), fall back to
    # default yfinance behaviour — strictly worse but functional.
    _YF_SESSION = None
import requests
from typing import Any, Callable, Optional
from backend.config import settings
from backend.services.advanced_scores import compute_all_advanced
from backend.services.quality import compute_quality
from backend.services import cache

log = logging.getLogger(__name__)


# ── Retry helper ──────────────────────────────────────────────────────────────
def _safe_yf(getter: Callable[[], Any],
             attempts: int = 3,
             base_delay: float = 0.5,
             default: Any = None) -> Any:
    """
    Call a yfinance property/method with retry-on-transient-failure.

    yfinance fails on cloud IPs in three distinct ways, all transient and
    individually retryable:
      • AttributeError when Yahoo returns a partial dict and yfinance's
        internal .update() crashes.
      • JSONDecodeError when Yahoo returns truncated HTML instead of JSON.
      • ConnectionError on rate-limit responses (429).

    Delay sequence: 0.5s, 1s, 2s (~3.5s worst case, well under the 30s
    request timeout).  Returns `default` after persistent failure rather
    than raising — every caller in this module already handles None.
    """
    last_exc = None
    for attempt in range(attempts):
        try:
            result = getter()
            if result is not None:
                return result
        except Exception as exc:                                  # noqa: BLE001
            last_exc = exc
            log.info("_safe_yf: attempt %d/%d raised %s",
                     attempt + 1, attempts, type(exc).__name__)
        if attempt < attempts - 1:
            time.sleep(base_delay * (2 ** attempt))
    if last_exc:
        log.warning("_safe_yf: retries exhausted (%s)", type(last_exc).__name__)
    return default


SEC_BASE = "https://data.sec.gov"
_HEADERS  = {"User-Agent": settings.sec_user_agent}

# In-process cache for the 8 MB company_tickers.json — downloaded once per run
_CIK_CACHE: dict[str, str] = {}


# ── Full fetch: returns (fundamentals_dict, ticker_obj) ──────────────────────
def fetch_yahoo_fundamentals_full(ticker: str) -> tuple[dict, object]:
    """
    Single yfinance session — downloads info, balance_sheet, financials, and
    cashflow in one Ticker object.  Returns:
      - fundamentals dict  (all fields needed by risk + valuation engines)
      - raw yfinance Ticker object  (for advanced_scores.compute_all_advanced)

    Raises ValueError on data fetch failure.
    """
    try:
        # yf.Ticker() itself can raise YFRateLimitError on cloud-IP throttling
        # in recent yfinance versions — wrap the constructor too so a rate-limit
        # error here doesn't escape to the outer catch.  We pass the
        # browser-impersonating curl_cffi session if available; that alone
        # bypasses ~95 % of Yahoo's bot-detection because the TLS handshake
        # looks like Safari, not Python.
        stock = _safe_yf(
            lambda: yf.Ticker(ticker, session=_YF_SESSION) if _YF_SESSION
                    else yf.Ticker(ticker),
            attempts=2,
        )
        if stock is None:
            raise ValueError(
                f"Yahoo Finance rate-limited the request for {ticker}. "
                f"Please wait 30-60 seconds and try again."
            )

        # Every yfinance attribute access goes through _safe_yf, which retries
        # on the cloud-IP failure modes (rate-limit AttributeError, partial
        # JSON, connection errors) with 0.5s / 1s / 2s back-off.  Returns None
        # after persistent failure — handled below.
        info = _safe_yf(lambda: stock.info)

        if not info or info.get("quoteType") is None:
            # Probe fast_info as a secondary check — sometimes one Yahoo
            # endpoint works while the other doesn't.  Used purely to
            # distinguish "ticker bad" from "rate-limited" in the message.
            fast = _safe_yf(lambda: stock.fast_info, attempts=1, default=None)
            had_partial = bool(fast and getattr(fast, "last_price", None))
            raise ValueError(
                f"Yahoo Finance is currently rate-limiting requests for "
                f"{ticker}.  Try again in a minute."
                if had_partial else
                f"Could not fetch fundamentals for {ticker}.  Yahoo Finance "
                f"may be temporarily rate-limiting our IP — wait ~60 seconds "
                f"and try again, or try a different ticker."
            )

        # ── Revenue growth (YoY from income statement) ────────────
        # _safe_yf returns None on persistent failure → the empty-frame check
        # below handles that as "no revenue growth available".
        financials      = _safe_yf(lambda: stock.financials)
        revenue_current = None
        revenue_prior   = None
        if financials is not None and not financials.empty:
            rev_row = financials[financials.index == "Total Revenue"]
            if not rev_row.empty:
                values = rev_row.iloc[0].dropna().values
                if len(values) >= 1:
                    revenue_current = float(values[0])
                if len(values) >= 2:
                    revenue_prior   = float(values[1])

        revenue_growth = None
        if revenue_current and revenue_prior and revenue_prior != 0:
            revenue_growth = round(
                (revenue_current - revenue_prior) / abs(revenue_prior) * 100, 2
            )

        data = {
            # ── Identity ──────────────────────────────────────────
            "ticker":              ticker.upper(),
            "name":                info.get("longName") or info.get("shortName", ticker),
            "sector":              info.get("sector", "Unknown"),
            "industry":            info.get("industry", "Unknown"),

            # ── Market / price ────────────────────────────────────
            "market_cap":          info.get("marketCap"),
            "current_price":       info.get("currentPrice") or info.get("regularMarketPrice"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low":  info.get("fiftyTwoWeekLow"),
            "beta":                info.get("beta"),

            # ── Income ────────────────────────────────────────────
            "revenue_ttm":         info.get("totalRevenue"),
            "revenue_growth_yoy":  revenue_growth,
            "earnings_growth":     info.get("earningsGrowth"),  # decimal
            "net_margin":          _safe_pct(info.get("profitMargins")),
            "roa":                 _safe_pct(info.get("returnOnAssets")),
            "roe":                 _safe_pct(info.get("returnOnEquity")),

            # ── Valuation multiples ───────────────────────────────
            "pe_ratio":            info.get("trailingPE"),
            "forward_pe":          info.get("forwardPE"),
            "peg_ratio":           info.get("pegRatio"),
            "ev_ebitda":           info.get("enterpriseToEbitda"),
            "ev_revenue":          info.get("enterpriseToRevenue"),

            # ── Per-share ─────────────────────────────────────────
            "eps_ttm":             info.get("trailingEps"),
            "eps_forward":         info.get("forwardEps"),

            # ── Balance sheet ─────────────────────────────────────
            "debt_to_equity":      info.get("debtToEquity"),
            "current_ratio":       info.get("currentRatio"),
            "total_cash":          info.get("totalCash"),
            "total_debt":          info.get("totalDebt"),
            "shares_outstanding":  info.get("sharesOutstanding"),

            # ── Cash flow ─────────────────────────────────────────
            "free_cashflow":       info.get("freeCashflow"),

            # ── Analyst data ──────────────────────────────────────
            "analyst_target_mean": info.get("targetMeanPrice"),
            "analyst_target_high": info.get("targetHighPrice"),
            "analyst_target_low":  info.get("targetLowPrice"),
            "analyst_count":       info.get("numberOfAnalystOpinions"),
            "recommendation":      info.get("recommendationKey"),

            # ── Income distribution ───────────────────────────────
            "dividend_yield":      _safe_pct(info.get("dividendYield")),
            "payout_ratio":        _safe_pct(info.get("payoutRatio")),
        }
        return data, stock

    except ValueError:
        raise
    except Exception as e:
        # Final safety net — if a yfinance exception slipped past every
        # _safe_yf wrapper, translate it into the same user-friendly message
        # rather than leaking the raw yfinance error string.  The sentinel
        # [retry-v2] is here so we can verify this exact code is the one
        # serving traffic after a deploy.
        msg = str(e).lower()
        if "rate" in msg or "too many requests" in msg or "limit" in msg:
            raise ValueError(
                f"Yahoo Finance is rate-limiting requests for {ticker} "
                f"right now.  Wait ~60 seconds and try again. [retry-v2]"
            )
        raise ValueError(
            f"Could not fetch data for {ticker}.  Yahoo Finance returned "
            f"an unexpected response — try again in a minute. [retry-v2]"
        )


def fetch_yahoo_fundamentals(ticker: str) -> dict:
    """Convenience wrapper — returns only the dict (no ticker object)."""
    data, _ = fetch_yahoo_fundamentals_full(ticker)
    return data


def fetch_company_data(ticker: str) -> tuple[dict, dict, dict]:
    """
    Fetch fundamentals + advanced scores + quality scores for a ticker,
    returning three plain JSON-serialisable dicts: (raw, advanced, quality).

    The combined result is cached in Redis for settings.cache_ttl seconds, so
    repeated analysis of the same ticker within the window does NOT re-hit
    Yahoo Finance (which rate-limits aggressively). If Redis is unreachable the
    cache transparently no-ops and every call fetches fresh. The cache key is
    versioned ("yfc:v2:") — bumped when the payload shape changes so old
    entries do not poison a new schema.
    """
    ticker = ticker.upper()
    key = f"yfc:v2:{ticker}"

    cached = cache.cache_get(key)
    if cached is not None:
        return cached["raw"], cached["advanced"], cached["quality"]

    raw, ticker_obj = fetch_yahoo_fundamentals_full(ticker)
    advanced = compute_all_advanced(ticker_obj)
    quality  = compute_quality(ticker_obj, raw)
    cache.cache_set(
        key, {"raw": raw, "advanced": advanced, "quality": quality},
        settings.cache_ttl,
    )
    return raw, advanced, quality


# ── SEC EDGAR ─────────────────────────────────────────────────────────────────
def fetch_sec_filings(cik: str, form_type: str = "10-K", limit: int = 5) -> list[dict]:
    try:
        cik_padded       = str(cik).zfill(10)
        submissions_url  = f"{SEC_BASE}/submissions/CIK{cik_padded}.json"
        resp             = requests.get(submissions_url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        data     = resp.json()
        filings  = data.get("filings", {}).get("recent", {})
        forms    = filings.get("form", [])
        dates    = filings.get("filingDate", [])
        accessions = filings.get("accessionNumber", [])

        results = []
        for i, form in enumerate(forms):
            if form == form_type and len(results) < limit:
                results.append({
                    "form":      form,
                    "date":      dates[i]      if i < len(dates)      else None,
                    "accession": accessions[i] if i < len(accessions) else None,
                })
        return results
    except Exception:
        return []


def lookup_cik_by_ticker(ticker: str) -> Optional[str]:
    upper = ticker.upper()
    if upper in _CIK_CACHE:
        return _CIK_CACHE[upper]
    try:
        url  = f"{SEC_BASE}/files/company_tickers.json"
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        for _, company in resp.json().items():
            if company.get("ticker", "").upper() == upper:
                cik = str(company["cik_str"])
                _CIK_CACHE[upper] = cik
                return cik
        return None
    except Exception:
        return None


def _safe_pct(value) -> Optional[float]:
    if value is None:
        return None
    return round(float(value) * 100, 2)
