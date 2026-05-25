"""
DB-backed leader election for the APScheduler instance.

Why
───
APScheduler's in-process design means N application workers running
SCHEDULER_ENABLED=true would all fire every job N times.  This module
lets us safely scale the web tier horizontally: every worker boots a
scheduler, but only the worker that holds the DB lock actually runs jobs.

How it works
────────────
A single row in `scheduler_lock` is the elected leadership token.  Acquiring
the lock is a conditional UPDATE/INSERT:

  1. If no row exists, INSERT with our worker_id + expires_at = now + lease.
  2. If a row exists and is expired, UPDATE to steal it.
  3. If a row exists and is still ours, UPDATE expires_at (heartbeat).
  4. Otherwise we're a follower — back off.

The implementation only uses portable SQL (no Postgres-specific
pg_advisory_lock) so SQLite + dev workflows work identically.

Boundaries
──────────
This module is concurrency-correct for any DB that gives row-level
linearisability under SERIALIZABLE / SQLite's default isolation.  For
Postgres + multi-process we rely on the unique PK constraint to break ties:
two simultaneous INSERTs on the same `name` cannot both succeed; the loser
sees IntegrityError and reads the row again to evaluate.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database.db import SchedulerLock

log = logging.getLogger(__name__)


# Per-process worker identity.  Generated once at module import so all calls
# from the same process compare equal.
WORKER_ID: str = str(uuid.uuid4())

# Lease duration. Long enough to survive a brief GC pause / network hiccup;
# short enough that a crashed leader gets replaced reasonably fast.
LEASE_SECONDS = 90

LOCK_NAME = "singleton"     # only one scheduler lock today; extensible later


def try_acquire(db: Session, now: Optional[datetime] = None) -> bool:
    """
    Attempt to become / remain the scheduler leader.

    Returns
    -------
        True  — this worker holds the lock (either freshly acquired or
                heartbeat refreshed).
        False — another worker holds it; we are a follower.
    """
    now = now or datetime.utcnow()
    new_expiry = now + timedelta(seconds=LEASE_SECONDS)

    row = db.query(SchedulerLock).filter_by(name=LOCK_NAME).first()

    # Case 1 — no row yet: try to claim.
    if row is None:
        try:
            db.add(SchedulerLock(
                name=LOCK_NAME, worker_id=WORKER_ID,
                acquired_at=now, expires_at=new_expiry,
            ))
            db.commit()
            log.info("scheduler_lock: acquired by worker %s", WORKER_ID)
            return True
        except IntegrityError:
            # Another worker INSERTed first — fall through to re-read.
            db.rollback()
            row = db.query(SchedulerLock).filter_by(name=LOCK_NAME).first()
            if row is None:
                # Genuinely odd; treat as follower this tick.
                return False

    # Case 2 — we already hold it: heartbeat.
    if row.worker_id == WORKER_ID:
        row.expires_at  = new_expiry
        row.acquired_at = row.acquired_at   # explicit no-op for clarity
        db.commit()
        return True

    # Case 3 — someone else holds it. Lease still valid?
    if row.expires_at > now:
        return False

    # Case 4 — expired lease. Steal it.
    row.worker_id   = WORKER_ID
    row.acquired_at = now
    row.expires_at  = new_expiry
    db.commit()
    log.info("scheduler_lock: stolen from expired holder, now held by %s",
             WORKER_ID)
    return True


def release(db: Session) -> None:
    """
    Drop the lock on graceful shutdown so another worker can take over
    without waiting for the lease to expire.  No-op if we don't hold it.
    """
    row = db.query(SchedulerLock).filter_by(name=LOCK_NAME).first()
    if row is not None and row.worker_id == WORKER_ID:
        db.delete(row)
        db.commit()
        log.info("scheduler_lock: released by worker %s", WORKER_ID)


def current_holder(db: Session) -> Optional[dict]:
    """Inspection helper for /scheduler/status."""
    row = db.query(SchedulerLock).filter_by(name=LOCK_NAME).first()
    if row is None:
        return None
    return {
        "worker_id":   row.worker_id,
        "acquired_at": row.acquired_at.isoformat() if row.acquired_at else None,
        "expires_at":  row.expires_at.isoformat()  if row.expires_at  else None,
        "is_us":       row.worker_id == WORKER_ID,
    }
