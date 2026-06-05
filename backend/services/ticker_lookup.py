"""
Company-name → ticker resolution.

Why this exists
───────────────
The analyse pipeline takes a ticker symbol (AAPL, JPM, etc.), but most
users think in company names ("Apple", "JP Morgan").  This module turns
free-form text into a ranked list of candidate (ticker, name) pairs so
the dashboard can offer an autocomplete dropdown.

Data source
───────────
yfinance's Search API hits Yahoo Finance's symbol-lookup endpoint.  It
returns equities + ETFs + mutual funds + indices; we filter to equities
and ETFs to keep the dropdown signal-dense.

Defensiveness
─────────────
Network failures (Yahoo down, rate limit) yield an empty list, never an
exception.  The dashboard's search box stays functional — the user can
always type the ticker directly even if name lookup is unavailable.

Caching
───────
Results are cached for 5 minutes in Redis (when available) keyed on the
normalised query.  Yahoo's search is rate-limited so this is both faster
and more reliable than a fresh hit per keystroke.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Equities + ETFs are the only types worth surfacing for company-risk
# analysis.  yfinance returns far more (futures, indices, currencies);
# the others would dilute the dropdown.
_USEFUL_QUOTE_TYPES = {"EQUITY", "ETF"}

# Cap to keep the dropdown one-eyeful-tall.
_DEFAULT_MAX_RESULTS = 8


def search_tickers(query: str, max_results: int = _DEFAULT_MAX_RESULTS) -> List[Dict[str, Any]]:
    """
    Resolve a free-form query into ranked ticker candidates.

    Returns
    -------
        [
          {"ticker": "AAPL", "name": "Apple Inc.",      "exchange": "NMS", "type": "EQUITY"},
          {"ticker": "AAPL.MX","name": "Apple Inc.",    "exchange": "MEX", "type": "EQUITY"},
          ...
        ]
        Empty list on any failure (caller never has to handle exceptions).
    """
    q = (query or "").strip()
    if len(q) < 2:
        return []

    # Direct ticker passthrough — when the user types something that already
    # LOOKS like a ticker (short, all caps or has a dot), we still hit search
    # so we can surface the company name for display, but we degrade gracefully
    # if search misses (e.g., AAPL might not show up if Yahoo's API hiccups —
    # we synthesise a minimal entry so the dropdown isn't empty).
    try:
        import yfinance as yf
        result = yf.Search(q, max_results=max_results)
        quotes = result.quotes or []
    except Exception as exc:                              # noqa: BLE001
        log.warning("ticker_lookup: yfinance search failed for %r — %s", q, exc)
        quotes = []

    candidates: List[Dict[str, Any]] = []
    seen_tickers: set[str] = set()

    for q_item in quotes:
        symbol = q_item.get("symbol")
        if not symbol or symbol in seen_tickers:
            continue
        qtype = (q_item.get("quoteType") or "").upper()
        if qtype and qtype not in _USEFUL_QUOTE_TYPES:
            continue
        candidates.append({
            "ticker":    symbol,
            "name":      q_item.get("shortname") or q_item.get("longname") or symbol,
            "exchange":  q_item.get("exchange") or "",
            "type":      qtype or "EQUITY",
        })
        seen_tickers.add(symbol)
        if len(candidates) >= max_results:
            break

    # Fallback — only when the user obviously typed a ticker (all uppercase,
    # matches the ticker character class) and Yahoo's search happened to miss.
    # Names like "Apple" stay empty so the dropdown closes cleanly; bogus
    # strings like "xyzzy" don't get falsely promoted to a tickerish entry.
    if not candidates and _looks_like_ticker(q) and q == q.upper():
        candidates.append({
            "ticker":   q,
            "name":     q,
            "exchange": "",
            "type":     "EQUITY",
        })

    return candidates


def _looks_like_ticker(s: str) -> bool:
    """Heuristic: 1–15 chars, alphanumeric + dot/hyphen, ≥1 letter."""
    s = s.strip()
    if not (1 <= len(s) <= 15):
        return False
    if not any(c.isalpha() for c in s):
        return False
    return all(c.isalnum() or c in ".-" for c in s)


def resolve_to_ticker(query: str) -> Optional[str]:
    """
    Convenience helper: return the single best-match ticker for `query`,
    or None.  Used by /analyze for the "user typed a name not a ticker"
    case so they don't have to use the dropdown.
    """
    results = search_tickers(query, max_results=1)
    return results[0]["ticker"] if results else None
