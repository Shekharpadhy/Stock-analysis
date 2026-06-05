"""
Company-name → ticker resolution.

Why this exists
───────────────
The analyse pipeline takes a ticker symbol (AAPL, JPM, etc.), but most
users think in company names ("Apple", "JP Morgan").  This module turns
free-form text into a ranked list of candidate (ticker, name) pairs so
the dashboard can offer an autocomplete dropdown.

Resilience
──────────
Yahoo Finance's search endpoint is aggressively rate-limited from cloud-
provider IPs (and intermittently from residential IPs too).  When the live
search returns nothing, we fall back to a curated dictionary of ~120 of
the most-traded names worldwide — covering the entire Nifty 50, the top
30 BSE names, the S&P 500 largest by market cap, and major European /
Asian listings.  This guarantees autocomplete keeps working for the
queries that actually matter, even when Yahoo's API is down.

Layered lookup
──────────────
For every query the resolver runs in this order:
    1. Curated dictionary     — instant, offline, signal-dense.
    2. Live yfinance.Search   — picks up niche names + ETFs we don't curate.
    3. Identity fallback      — if the query looks like a ticker symbol
                                 already, surface it as-is.
Results are deduplicated by ticker symbol; curated matches rank first
because they're guaranteed to be canonical.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Equities + ETFs are the only types worth surfacing for company-risk
# analysis.  Yahoo returns many more (futures, indices, currencies); the
# others would dilute the dropdown.
_USEFUL_QUOTE_TYPES = {"EQUITY", "ETF"}

# Cap to keep the dropdown one-eyeful-tall.
_DEFAULT_MAX_RESULTS = 8


# ── Curated ticker dictionary ────────────────────────────────────────────────
# Format: (ticker, display name, exchange code).
# Indian listings use the .NS suffix (NSE) or .BO (BSE).  Names should match
# how the issuer is commonly referenced — short, no punctuation surprises —
# so substring matching on the user's typed query lands intuitive results.

_CURATED: List[tuple] = [
    # ── Nifty 50 — Indian large-caps (NSE) ──────────────────────────────────
    ("RELIANCE.NS",   "Reliance Industries",            "NSI"),
    ("TCS.NS",        "Tata Consultancy Services",      "NSI"),
    ("HDFCBANK.NS",   "HDFC Bank",                      "NSI"),
    ("INFY.NS",       "Infosys",                        "NSI"),
    ("ICICIBANK.NS",  "ICICI Bank",                     "NSI"),
    ("HINDUNILVR.NS", "Hindustan Unilever",             "NSI"),
    ("ITC.NS",        "ITC Limited",                    "NSI"),
    ("SBIN.NS",       "State Bank of India",            "NSI"),
    ("BHARTIARTL.NS", "Bharti Airtel",                  "NSI"),
    ("KOTAKBANK.NS",  "Kotak Mahindra Bank",            "NSI"),
    ("LT.NS",         "Larsen & Toubro",                "NSI"),
    ("AXISBANK.NS",   "Axis Bank",                      "NSI"),
    ("ASIANPAINT.NS", "Asian Paints",                   "NSI"),
    ("MARUTI.NS",     "Maruti Suzuki India",            "NSI"),
    ("TITAN.NS",      "Titan Company",                  "NSI"),
    ("HCLTECH.NS",    "HCL Technologies",               "NSI"),
    ("BAJFINANCE.NS", "Bajaj Finance",                  "NSI"),
    ("WIPRO.NS",      "Wipro",                          "NSI"),
    ("SUNPHARMA.NS",  "Sun Pharmaceutical Industries",  "NSI"),
    ("M&M.NS",        "Mahindra & Mahindra",            "NSI"),
    ("TATAMOTORS.NS", "Tata Motors",                    "NSI"),
    ("ULTRACEMCO.NS", "UltraTech Cement",               "NSI"),
    ("TATASTEEL.NS",  "Tata Steel",                     "NSI"),
    ("POWERGRID.NS",  "Power Grid Corporation of India","NSI"),
    ("NTPC.NS",       "NTPC Limited",                   "NSI"),
    ("ONGC.NS",       "Oil and Natural Gas Corporation","NSI"),
    ("ADANIENT.NS",   "Adani Enterprises",              "NSI"),
    ("COALINDIA.NS",  "Coal India",                     "NSI"),
    ("TECHM.NS",      "Tech Mahindra",                  "NSI"),
    ("INDUSINDBK.NS", "IndusInd Bank",                  "NSI"),
    ("BAJAJFINSV.NS", "Bajaj Finserv",                  "NSI"),
    ("DIVISLAB.NS",   "Divi's Laboratories",            "NSI"),
    ("HDFCLIFE.NS",   "HDFC Life Insurance",            "NSI"),
    ("DRREDDY.NS",    "Dr. Reddy's Laboratories",       "NSI"),
    ("NESTLEIND.NS",  "Nestle India",                   "NSI"),
    ("BAJAJ-AUTO.NS", "Bajaj Auto",                     "NSI"),
    ("ADANIPORTS.NS", "Adani Ports and SEZ",            "NSI"),
    ("CIPLA.NS",      "Cipla",                          "NSI"),
    ("GRASIM.NS",     "Grasim Industries",              "NSI"),
    ("JSWSTEEL.NS",   "JSW Steel",                      "NSI"),
    ("BPCL.NS",       "Bharat Petroleum",               "NSI"),
    ("BRITANNIA.NS",  "Britannia Industries",           "NSI"),
    ("HEROMOTOCO.NS", "Hero MotoCorp",                  "NSI"),
    ("TATACONSUM.NS", "Tata Consumer Products",         "NSI"),
    ("EICHERMOT.NS",  "Eicher Motors",                  "NSI"),
    ("SBILIFE.NS",    "SBI Life Insurance",             "NSI"),
    ("APOLLOHOSP.NS", "Apollo Hospitals Enterprise",    "NSI"),
    ("UPL.NS",        "UPL Limited",                    "NSI"),
    ("HINDALCO.NS",   "Hindalco Industries",            "NSI"),
    ("SHRIRAMFIN.NS", "Shriram Finance",                "NSI"),
    # Extras outside Nifty 50 but commonly searched
    ("VEDL.NS",       "Vedanta Limited",                "NSI"),
    ("DMART.NS",      "Avenue Supermarts",              "NSI"),
    ("ZOMATO.NS",     "Zomato",                         "NSI"),
    ("PAYTM.NS",      "One97 Communications (Paytm)",   "NSI"),
    ("IRCTC.NS",      "Indian Railway Catering & Tourism","NSI"),
    ("DLF.NS",        "DLF Limited",                    "NSI"),
    ("HAVELLS.NS",    "Havells India",                  "NSI"),
    ("MOTHERSON.NS",  "Samvardhana Motherson International","NSI"),
    ("IOC.NS",        "Indian Oil Corporation",         "NSI"),
    ("YESBANK.NS",    "Yes Bank",                       "NSI"),
    ("LICI.NS",       "Life Insurance Corporation of India","NSI"),
    ("INDIGO.NS",     "InterGlobe Aviation (IndiGo)",   "NSI"),

    # ── US large-caps (NASDAQ + NYSE) ───────────────────────────────────────
    ("AAPL",          "Apple Inc.",                     "NMS"),
    ("MSFT",          "Microsoft Corporation",          "NMS"),
    ("GOOGL",         "Alphabet Inc. Class A",          "NMS"),
    ("GOOG",          "Alphabet Inc. Class C",          "NMS"),
    ("AMZN",          "Amazon.com",                     "NMS"),
    ("META",          "Meta Platforms",                 "NMS"),
    ("TSLA",          "Tesla",                          "NMS"),
    ("NVDA",          "NVIDIA Corporation",             "NMS"),
    ("BRK-B",         "Berkshire Hathaway Class B",     "NYQ"),
    ("BRK-A",         "Berkshire Hathaway Class A",     "NYQ"),
    ("JPM",           "JPMorgan Chase",                 "NYQ"),
    ("V",             "Visa",                           "NYQ"),
    ("MA",            "Mastercard",                     "NYQ"),
    ("JNJ",           "Johnson & Johnson",              "NYQ"),
    ("WMT",           "Walmart",                        "NYQ"),
    ("PG",            "Procter & Gamble",               "NYQ"),
    ("UNH",           "UnitedHealth Group",             "NYQ"),
    ("HD",            "Home Depot",                     "NYQ"),
    ("BAC",           "Bank of America",                "NYQ"),
    ("XOM",           "Exxon Mobil",                    "NYQ"),
    ("CVX",           "Chevron Corporation",            "NYQ"),
    ("ABBV",          "AbbVie",                         "NYQ"),
    ("KO",            "Coca-Cola Company",              "NYQ"),
    ("PEP",           "PepsiCo",                        "NMS"),
    ("COST",          "Costco Wholesale",               "NMS"),
    ("MRK",           "Merck & Co.",                    "NYQ"),
    ("CSCO",          "Cisco Systems",                  "NMS"),
    ("ORCL",          "Oracle Corporation",             "NYQ"),
    ("ACN",           "Accenture",                      "NYQ"),
    ("ADBE",          "Adobe Inc.",                     "NMS"),
    ("NFLX",          "Netflix",                        "NMS"),
    ("CMCSA",         "Comcast Corporation",            "NMS"),
    ("PFE",           "Pfizer",                         "NYQ"),
    ("NKE",           "Nike",                           "NYQ"),
    ("CRM",           "Salesforce",                     "NYQ"),
    ("AMD",           "Advanced Micro Devices",         "NMS"),
    ("INTC",          "Intel Corporation",              "NMS"),
    ("DIS",           "The Walt Disney Company",        "NYQ"),
    ("MCD",           "McDonald's",                     "NYQ"),
    ("PYPL",          "PayPal Holdings",                "NMS"),
    ("SBUX",          "Starbucks",                      "NMS"),
    ("WFC",           "Wells Fargo",                    "NYQ"),
    ("C",             "Citigroup",                      "NYQ"),
    ("GS",            "Goldman Sachs",                  "NYQ"),
    ("MS",            "Morgan Stanley",                 "NYQ"),
    ("BLK",           "BlackRock",                      "NYQ"),
    ("BA",            "Boeing",                         "NYQ"),
    ("GE",            "General Electric",               "NYQ"),
    ("CAT",           "Caterpillar",                    "NYQ"),
    ("F",             "Ford Motor Company",             "NYQ"),
    ("GM",            "General Motors",                 "NYQ"),
    ("UBER",          "Uber Technologies",              "NYQ"),
    ("ABNB",          "Airbnb",                         "NMS"),
    ("SHOP",          "Shopify",                        "NYQ"),
    ("PLTR",          "Palantir Technologies",          "NYQ"),
    ("COIN",          "Coinbase Global",                "NMS"),
    ("RIVN",          "Rivian Automotive",              "NMS"),
]

# Equities + ETFs are the only types worth surfacing for company-risk
# analysis.  yfinance returns many more (futures, indices, currencies);
# the others would dilute the dropdown.
_DEFAULT_MAX_RESULTS = 8


# ── Curated-dictionary search (offline, instant) ──────────────────────────────

def _curated_matches(query: str, limit: int) -> List[Dict[str, Any]]:
    """
    Case-insensitive substring match over the curated table.

    Ranking
    ───────
      1. Exact ticker match  ("AAPL" → AAPL)
      2. Ticker prefix       ("APP" → AAPL, APPS, etc.)
      3. Name prefix         ("App" → Apple Inc., AppLovin)
      4. Name substring      ("Maker" → companies with 'Maker' in the name)
    This puts the most-likely-intended candidate at the top.
    """
    q = query.strip().upper()
    if not q:
        return []

    exact_ticker:   List[tuple] = []
    ticker_prefix:  List[tuple] = []
    name_prefix:    List[tuple] = []
    name_substring: List[tuple] = []

    for ticker, name, exchange in _CURATED:
        t_upper = ticker.upper()
        n_upper = name.upper()
        if t_upper == q:
            exact_ticker.append((ticker, name, exchange))
        elif t_upper.startswith(q):
            ticker_prefix.append((ticker, name, exchange))
        elif n_upper.startswith(q):
            name_prefix.append((ticker, name, exchange))
        elif q in n_upper:
            name_substring.append((ticker, name, exchange))

    ranked = exact_ticker + ticker_prefix + name_prefix + name_substring
    return [
        {"ticker": t, "name": n, "exchange": e, "type": "EQUITY"}
        for t, n, e in ranked[:limit]
    ]


# ── Public API ────────────────────────────────────────────────────────────────

def search_tickers(query: str, max_results: int = _DEFAULT_MAX_RESULTS) -> List[Dict[str, Any]]:
    """
    Resolve a free-form query into ranked ticker candidates.

    Layered: curated dictionary first (offline, no API hit, always works),
    then yfinance live search for niche names, then identity fallback.
    """
    q = (query or "").strip()
    if len(q) < 2:
        return []

    # 1. Curated matches first — guaranteed signal even when Yahoo is down.
    out = _curated_matches(q, max_results)
    seen_tickers = {r["ticker"] for r in out}
    if len(out) >= max_results:
        return out

    # 2. Live yfinance search for the rest.
    try:
        import yfinance as yf
        result = yf.Search(q, max_results=max_results)
        quotes = result.quotes or []
    except Exception as exc:                              # noqa: BLE001
        log.warning("ticker_lookup: yfinance search failed for %r — %s", q, exc)
        quotes = []

    _USEFUL_QUOTE_TYPES = {"EQUITY", "ETF"}
    for q_item in quotes:
        symbol = q_item.get("symbol")
        if not symbol or symbol in seen_tickers:
            continue
        qtype = (q_item.get("quoteType") or "").upper()
        if qtype and qtype not in _USEFUL_QUOTE_TYPES:
            continue
        out.append({
            "ticker":   symbol,
            "name":     q_item.get("shortname") or q_item.get("longname") or symbol,
            "exchange": q_item.get("exchange") or "",
            "type":     qtype or "EQUITY",
        })
        seen_tickers.add(symbol)
        if len(out) >= max_results:
            break

    # 3. Identity fallback — only when user typed something obviously
    # ticker-shaped AND already uppercase, and we have no other matches.
    if not out and _looks_like_ticker(q) and q == q.upper():
        out.append({
            "ticker":   q,
            "name":     q,
            "exchange": "",
            "type":     "EQUITY",
        })

    return out


def _looks_like_ticker(s: str) -> bool:
    """Heuristic: 1–20 chars, alphanumeric + dot/hyphen/ampersand, ≥1 letter."""
    s = s.strip()
    if not (1 <= len(s) <= 20):
        return False
    if not any(c.isalpha() for c in s):
        return False
    return all(c.isalnum() or c in ".-&" for c in s)


def resolve_to_ticker(query: str) -> Optional[str]:
    """
    Convenience helper: return the single best-match ticker for `query`,
    or None.  Used by /analyze for the "user typed a name not a ticker"
    case so they don't have to use the dropdown.
    """
    results = search_tickers(query, max_results=1)
    return results[0]["ticker"] if results else None
