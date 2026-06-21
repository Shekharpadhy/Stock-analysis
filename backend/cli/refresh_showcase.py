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
        else:
            results = showcase.refresh_all(db)
    finally:
        db.close()

    print(json.dumps(results, indent=2, default=str))
    return 0 if not results.get("failed") else 1


if __name__ == "__main__":
    sys.exit(main())
