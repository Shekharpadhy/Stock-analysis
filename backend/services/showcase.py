"""
Showcase mode — pre-computed full-fidelity snapshots for a curated ticker list.

Why
───
On cloud-IP deployments (Render, Fly, Railway) yfinance is blocked by Yahoo
and FMP's free tier ships only /profile data for non-US listings.  Result:
when a recruiter analyses RELIANCE.NS in the live demo, the dashboard shows
mostly blank tiles even though every engine in the codebase works fine.

The showcase pipeline solves this by running the analysis from a residential
IP (developer's laptop or a scheduled GitHub Action), persisting the full
output to the `showcase_snapshots` table, and serving that snapshot whenever
live fetch returns sparse data for a curated ticker.

What "sparse" means
───────────────────
A `raw` dict is sparse when both `pe_ratio` and `roe` are None — i.e. the
statements aren't filled in.  This is the most reliable signal because both
fields are populated by every fundamentals source EXCEPT FMP's
international-profile-only path.

Curated list
────────────
Hand-picked to cover the tickers a portfolio reviewer is most likely to type:
US mega-caps, Indian mega-caps, India IT/banking, and the M&M ticker the
README screenshots highlight.  Keep this short — every entry costs ~1s of
refresh time and one row in Redis cache.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from backend.database.db import ShowcaseSnapshot

log = logging.getLogger(__name__)

# Curated tickers — the demo's "always-populated" set.  Keep <= 20 to stay
# well under FMP's 250/day free-tier cap when the refresh job runs
# (~6 endpoints per ticker × 20 tickers = 120 calls per refresh).
SHOWCASE_TICKERS = [
    # US mega-caps
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    # India mega-caps + banking + IT
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "BAJFINANCE.NS", "M&M.NS", "LT.NS",
    # ETFs / index proxies
    "SPY", "QQQ",
]


def is_showcase_ticker(ticker: str) -> bool:
    """True when a ticker is in the curated demo set."""
    return ticker.upper() in {t.upper() for t in SHOWCASE_TICKERS}


def is_sparse(raw: dict) -> bool:
    """A raw payload is 'sparse' when the fundamental statement fields are
    blank — the signal that FMP only returned /profile data and the rest of
    the dashboard will be empty.

    PE and ROE are the canonical indicators: both populated when any real
    fundamentals source returned data; both None when only FMP /profile
    worked or yfinance silently no-op'd.
    """
    if not raw:
        return True
    return raw.get("pe_ratio") is None and raw.get("roe") is None


def load_snapshot(db: Session, ticker: str) -> Optional[Tuple[dict, dict, dict]]:
    """Return (raw, advanced, quality) for ticker from the snapshot table,
    or None if no snapshot exists.  Used by the analyze endpoint as the
    fallback when live fetch returns sparse data."""
    row = db.query(ShowcaseSnapshot).filter_by(ticker=ticker.upper()).first()
    if row is None:
        return None
    try:
        return (
            json.loads(row.raw_json),
            json.loads(row.advanced_json),
            json.loads(row.quality_json),
        )
    except (ValueError, TypeError) as exc:
        log.warning("showcase: snapshot for %s is corrupt — %s", ticker, exc)
        return None


def save_snapshot(db: Session, ticker: str,
                  raw: dict, advanced: dict, quality: dict) -> None:
    """Upsert a snapshot.  Called by the refresh job; safe to call from
    the analyze endpoint too if we ever want opportunistic warm-up."""
    ticker_u = ticker.upper()
    row = db.query(ShowcaseSnapshot).filter_by(ticker=ticker_u).first()
    if row is None:
        row = ShowcaseSnapshot(ticker=ticker_u)
        db.add(row)
    row.raw_json      = json.dumps(raw,      default=str)
    row.advanced_json = json.dumps(advanced, default=str)
    row.quality_json  = json.dumps(quality,  default=str)
    row.refreshed_at  = datetime.utcnow()
    db.commit()


def refresh_one(db: Session, ticker: str) -> bool:
    """Fetch ticker live and persist the full result as a snapshot.

    Returns True on success, False if the live fetch returned sparse data
    (in which case the snapshot is NOT overwritten — we'd rather keep a
    stale-but-complete snapshot than replace it with blanks).
    """
    # Import inside the function to avoid the circular import at module load:
    # ingestion → showcase via the analyze flow → ingestion again.
    from backend.services.ingestion import fetch_company_data

    try:
        raw, advanced, quality = fetch_company_data(ticker)
    except Exception as exc:                                      # noqa: BLE001
        log.warning("showcase: refresh failed for %s — %s", ticker, exc)
        return False

    if is_sparse(raw):
        log.warning("showcase: refresh for %s returned sparse data — "
                    "keeping existing snapshot", ticker)
        return False

    save_snapshot(db, ticker, raw, advanced, quality)
    log.info("showcase: snapshot refreshed for %s", ticker)
    return True


def refresh_all(db: Session) -> dict:
    """Refresh every ticker in SHOWCASE_TICKERS.  Returns a small summary
    dict the CLI prints — and that the future scheduled job will log."""
    summary = {"refreshed": [], "skipped": [], "failed": []}
    for t in SHOWCASE_TICKERS:
        try:
            ok = refresh_one(db, t)
            (summary["refreshed"] if ok else summary["skipped"]).append(t)
        except Exception as exc:                                  # noqa: BLE001
            log.exception("showcase: unexpected error on %s", t)
            summary["failed"].append({"ticker": t, "error": str(exc)})
    return summary
