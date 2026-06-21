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

from backend.database.db import PendingSnapshot, ShowcaseSnapshot

log = logging.getLogger(__name__)

# Curated tickers — always-refreshed nightly so the demo dashboard always
# renders complete data for the tickers a portfolio reviewer is most likely
# to type.  Sized around 100; the nightly GitHub Action refreshes the full
# list using yfinance (FMP free tier caps at 250/day which doesn't cover
# ~6 endpoints × 100 tickers = 600 calls).
SHOWCASE_TICKERS = [
    # ── US mega-caps & top S&P 500 (~50) ─────────────────────────────────
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
    "BRK-B", "JPM", "V", "UNH", "JNJ", "WMT", "MA", "PG", "XOM", "HD",
    "CVX", "ABBV", "LLY", "MRK", "AVGO", "PEP", "KO", "COST", "BAC",
    "WFC", "TMO", "ORCL", "MCD", "DIS", "CSCO", "ABT", "ADBE", "NFLX",
    "ACN", "AMD", "CRM", "LIN", "NKE", "TXN", "PM", "INTC", "VZ",
    "CMCSA", "NEE", "INTU", "T", "IBM",

    # ── India Nifty 50 ───────────────────────────────────────────────────
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "ITC.NS", "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "BAJFINANCE.NS", "MARUTI.NS",
    "M&M.NS", "HCLTECH.NS", "SUNPHARMA.NS", "TITAN.NS", "ULTRACEMCO.NS",
    "NESTLEIND.NS", "WIPRO.NS", "NTPC.NS", "TATAMOTORS.NS", "POWERGRID.NS",
    "TECHM.NS", "ONGC.NS", "BAJAJFINSV.NS", "DRREDDY.NS", "ADANIENT.NS",
    "JSWSTEEL.NS", "TATASTEEL.NS", "COALINDIA.NS", "GRASIM.NS",
    "INDUSINDBK.NS", "BPCL.NS", "CIPLA.NS", "EICHERMOT.NS", "BRITANNIA.NS",
    "HEROMOTOCO.NS", "DIVISLAB.NS", "HINDALCO.NS", "APOLLOHOSP.NS",
    "BAJAJ-AUTO.NS", "UPL.NS", "ADANIPORTS.NS", "SBILIFE.NS", "HDFCLIFE.NS",
    "TATACONSUM.NS", "LTIM.NS",

    # ── ETFs / index proxies ─────────────────────────────────────────────
    "SPY", "QQQ", "VOO", "VTI", "IVV", "DIA", "IWM",
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


# ── Pending queue (user-requested tickers that need a snapshot) ──────────────

def enqueue_snapshot(db: Session, ticker: str) -> None:
    """Insert ticker into the pending queue (or bump request_count if it's
    already there).  Called from the analyze endpoint when a user searches
    a non-showcase ticker that returned sparse live data — the nightly
    refresh job will pick it up.

    Best-effort: any DB error is logged and swallowed so a queue failure
    doesn't break the analyze response the user is waiting on.
    """
    ticker_u = ticker.upper()
    try:
        row = db.query(PendingSnapshot).filter_by(ticker=ticker_u).first()
        if row is None:
            row = PendingSnapshot(ticker=ticker_u, request_count=1)
            db.add(row)
        else:
            row.request_count = (row.request_count or 0) + 1
            row.last_requested_at = datetime.utcnow()
        db.commit()
    except Exception as exc:                                      # noqa: BLE001
        log.warning("showcase: enqueue_snapshot(%s) failed — %s", ticker, exc)
        db.rollback()


def drain_pending(db: Session, limit: int = 200) -> dict:
    """Refresh every ticker in the pending queue, then remove successful
    entries from the queue.  Failed entries stay queued so the next run
    retries — but with each failure they fall down the priority list
    naturally (we'd add per-row failure counters if this becomes flaky).

    `limit` caps the per-run drain so a sudden flood of new searches
    doesn't blow past the FMP free-tier quota in a single nightly run.
    Default 200 = 1200 FMP calls at 6 per ticker — comfortably above the
    250/day FMP cap, but the refresh job uses yfinance as the primary on
    GitHub-Actions runners (which don't get throttled like Render does).
    """
    pending = (db.query(PendingSnapshot)
                 .order_by(PendingSnapshot.request_count.desc(),
                           PendingSnapshot.first_requested_at.asc())
                 .limit(limit)
                 .all())
    summary = {"refreshed": [], "skipped": [], "failed": []}
    for row in pending:
        t = row.ticker
        try:
            ok = refresh_one(db, t)
            if ok:
                summary["refreshed"].append(t)
                db.delete(row)
                db.commit()
            else:
                summary["skipped"].append(t)
        except Exception as exc:                                  # noqa: BLE001
            log.exception("showcase: pending refresh error on %s", t)
            summary["failed"].append({"ticker": t, "error": str(exc)})
    return summary
