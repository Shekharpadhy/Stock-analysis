import logging
import yfinance as yf
import requests
from typing import Optional
from backend.config import settings
from backend.services.advanced_scores import compute_all_advanced
from backend.services.quality import compute_quality
from backend.services import cache

log = logging.getLogger(__name__)


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
        stock = yf.Ticker(ticker)
        # yfinance's .info property occasionally crashes on its own with
        # cryptic AttributeErrors when Yahoo returns a partial / rate-limited
        # response.  Wrap the call so the user sees a useful message instead
        # of "NoneType has no attribute 'update'".
        try:
            info = stock.info
        except AttributeError:
            info = None
        except Exception as exc:                                  # noqa: BLE001
            # yfinance can raise json.JSONDecodeError, ConnectionError, etc.
            # Treat any of them as "couldn't fetch" — same downstream handling.
            log.warning("ingestion(%s): stock.info raised %s", ticker, type(exc).__name__)
            info = None

        if not info or info.get("quoteType") is None:
            # One more try via the lighter fast_info endpoint — sometimes one
            # works when the other doesn't.  fast_info gives us price + name
            # but not the financials, so we'd still 422 the analyse — but the
            # error message is at least honest about WHY.
            try:
                fast = stock.fast_info
                if fast and getattr(fast, "last_price", None):
                    raise ValueError(
                        f"Yahoo Finance is currently rate-limiting requests "
                        f"for {ticker}.  Try again in a minute, or try a "
                        f"different ticker."
                    )
            except (AttributeError, Exception):                   # noqa: BLE001
                pass
            raise ValueError(
                f"Could not fetch fundamentals for {ticker}.  Yahoo Finance "
                f"may be temporarily rate-limiting our IP — wait ~60 seconds "
                f"and try again, or try a different ticker."
            )

        # ── Revenue growth (YoY from income statement) ────────────
        financials      = stock.financials
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
        raise ValueError(f"Failed to fetch data for {ticker}: {e}")


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
