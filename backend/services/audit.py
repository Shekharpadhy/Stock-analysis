"""
Audit log helper — a single `record()` call from any privileged code path.

Design
──────
  • Best-effort: a failed audit write MUST NOT block the action it's auditing.
    Caller wraps via the provided record() which swallows-and-logs its own
    errors.
  • Idempotent: every call inserts a new row; we never update/delete.
  • Cheap: one INSERT, no joins, indexed on (actor, action, target, timestamp)
    for typical queries.

Conventions
───────────
  actor   "admin" for the built-in admin, otherwise the username
  action  short verb-like string: "ml.train", "scheduler.run", "alert.fire",
          "user.register", "watchlist.add"
  target  the thing acted upon (ticker, user_id, job_name, subscription_id)
  extra   any JSON-serialisable dict with action-specific context
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.database.db import AuditLog

log = logging.getLogger(__name__)


def record(
    db: Session,
    actor: str,
    action: str,
    target: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Persist a single audit row.  Never raises — any DB error is logged and
    discarded so we don't break the operation being audited.
    """
    try:
        row = AuditLog(
            actor  = actor,
            action = action,
            target = target,
            extra  = json.dumps(extra, default=str) if extra else None,
        )
        db.add(row)
        db.commit()
    except Exception as exc:                          # noqa: BLE001
        log.warning("audit: failed to record %s/%s — %s", actor, action, exc)
        try:
            db.rollback()
        except Exception:
            pass
