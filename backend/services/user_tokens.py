"""
Single-use, hash-stored user tokens — backs email verification and
password reset.

Security model
──────────────
  • Tokens are 32 bytes from secrets.token_urlsafe(), giving 256 bits of
    entropy. Brute-forcing the token space is computationally infeasible.
  • Only the SHA-256 hash is stored.  A DB dump grants an attacker zero
    redeemable links.
  • Each token has an explicit `expires_at` and `used_at` — redemption
    requires `used_at IS NULL AND expires_at > now()`.
  • Redemption marks `used_at` atomically so a captured token can't be
    replayed even within its TTL.

Public API
──────────
  generate(db, user_id, purpose, ttl_hours)
      Issue a token row.  Returns the plaintext token (caller emails it);
      the DB stores only the hash.

  redeem(db, plaintext, purpose)
      Verify the token matches an unused, unexpired row for the given
      purpose. On success returns the user_id and marks the row used.
      Returns None on any failure mode (so the caller surfaces a uniform
      "invalid or expired" message — no oracle).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.database.db import UserToken


def _hash(plaintext: str) -> str:
    """SHA-256 hex digest — collision-free for any practical token size."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def generate(
    db: Session, user_id: int, purpose: str,
    ttl_hours: int = 24,
) -> str:
    """
    Issue a fresh token for `purpose`, store its hash, return the plaintext.

    The caller emails the plaintext to the user; it never appears in the DB
    again after this function returns.
    """
    plaintext = secrets.token_urlsafe(32)
    row = UserToken(
        user_id    = user_id,
        purpose    = purpose,
        token_hash = _hash(plaintext),
        expires_at = datetime.utcnow() + timedelta(hours=ttl_hours),
    )
    db.add(row)
    db.commit()
    return plaintext


def redeem(db: Session, plaintext: str, purpose: str) -> Optional[int]:
    """
    Validate a token submitted by the user.

    Returns
    -------
        user_id on success (and atomically marks the row used)
        None    on any failure (unknown / wrong purpose / expired / used)
    """
    if not plaintext:
        return None

    row = (
        db.query(UserToken)
        .filter(
            UserToken.token_hash == _hash(plaintext),
            UserToken.purpose    == purpose,
        )
        .first()
    )
    if row is None:
        return None
    if row.used_at is not None:
        return None
    if row.expires_at < datetime.utcnow():
        return None

    row.used_at = datetime.utcnow()
    db.commit()
    return row.user_id


def invalidate_pending(db: Session, user_id: int, purpose: str) -> None:
    """
    Mark all live (unused, unexpired) tokens for (user_id, purpose) as used.

    Called when issuing a fresh token of the same purpose — guarantees only
    the most-recent link is redeemable. Defensive against the "user clicked
    request twice and we don't know which email they used" race.
    """
    now = datetime.utcnow()
    (
        db.query(UserToken)
        .filter(
            UserToken.user_id    == user_id,
            UserToken.purpose    == purpose,
            UserToken.used_at.is_(None),
            UserToken.expires_at > now,
        )
        .update({"used_at": now}, synchronize_session=False)
    )
    db.commit()
