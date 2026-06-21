"""Refresh the showcase ticker snapshots.

Run this from a RESIDENTIAL IP (your laptop, not Render) so yfinance and
NSE work freely.  The resulting snapshots are written to the database
DATABASE_URL points at — point it at production Postgres to populate the
live demo dashboard.

Usage
─────
    # From repo root
    python -m backend.cli.refresh_showcase

    # Refresh a single ticker
    python -m backend.cli.refresh_showcase RELIANCE.NS

    # Point at production Postgres for the night-batch
    DATABASE_URL=postgres://... python -m backend.cli.refresh_showcase

Environment
───────────
Set FMP_API_KEY (recommended) so the run uses FMP as the primary source.
With FMP unset the script falls back to yfinance — fine on a residential IP.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from backend.database.db import SessionLocal, init_db
from backend.services import showcase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("refresh_showcase")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tickers", nargs="*",
        help="Specific tickers to refresh.  Default: every ticker in "
             "SHOWCASE_TICKERS.",
    )
    parser.add_argument(
        "--migrate", action="store_true",
        help="Run alembic migrations before refreshing.  Use when bootstrapping "
             "a fresh DB.",
    )
    args = parser.parse_args(argv)

    if args.migrate:
        log.info("running alembic upgrade head before refresh")
        init_db()

    db = SessionLocal()
    try:
        if args.tickers:
            results = {"refreshed": [], "skipped": [], "failed": []}
            for t in args.tickers:
                try:
                    ok = showcase.refresh_one(db, t)
                    (results["refreshed"] if ok else results["skipped"]).append(t)
                except Exception as exc:                          # noqa: BLE001
                    results["failed"].append({"ticker": t, "error": str(exc)})
            # No-args mode is the only one that drains the queue; explicit
            # ticker arg means "refresh just these, leave the queue alone".
            pending_results = None
        else:
            results = showcase.refresh_all(db)
            log.info("draining pending-snapshot queue (user-requested tickers)")
            pending_results = showcase.drain_pending(db)
    finally:
        db.close()

    output = {"showcase": results}
    if pending_results is not None:
        output["pending"] = pending_results
    print(json.dumps(output, indent=2, default=str))
    failed = results.get("failed") or (pending_results or {}).get("failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
