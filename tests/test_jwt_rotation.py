"""
Tests for JWT key rotation (Task #47).

Contract being verified
───────────────────────
  • A token signed with the CURRENT secret always verifies.
  • A token signed with JWT_SECRET_PREVIOUS verifies — but only while the
    previous secret is set.
  • A token signed with neither secret is rejected.
  • A fresh token is always signed with the CURRENT secret (so the rotation
    window naturally shrinks as old tokens expire).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from jose import jwt

from backend import auth
from backend.config import settings


def _make_token(secret: str, sub: str = "alice", role: str = "user",
                expires_in_minutes: int = 60) -> str:
    payload = {
        "sub":  sub,
        "role": role,
        "exp":  datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
    }
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def test_current_secret_token_verifies(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "current-secret-1")
    monkeypatch.setattr(settings, "jwt_secret_previous", "")
    tok = _make_token("current-secret-1")
    payload = auth._decode_token(tok)
    assert payload["sub"] == "alice"


def test_previous_secret_token_verifies_during_rotation(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "new-secret-2")
    monkeypatch.setattr(settings, "jwt_secret_previous", "old-secret-1")

    legacy_token = _make_token("old-secret-1")
    payload = auth._decode_token(legacy_token)
    assert payload["sub"] == "alice"


def test_previous_secret_rejected_after_window_closes(monkeypatch):
    """Once JWT_SECRET_PREVIOUS is cleared, legacy tokens stop verifying."""
    monkeypatch.setattr(settings, "jwt_secret", "new-secret-2")
    monkeypatch.setattr(settings, "jwt_secret_previous", "")
    legacy_token = _make_token("old-secret-1")
    with pytest.raises(HTTPException) as exc:
        auth._decode_token(legacy_token)
    assert exc.value.status_code == 401


def test_unknown_secret_token_rejected(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "current-secret-1")
    monkeypatch.setattr(settings, "jwt_secret_previous", "old-secret-1")
    rogue = _make_token("attacker-secret-xyz")
    with pytest.raises(HTTPException) as exc:
        auth._decode_token(rogue)
    assert exc.value.status_code == 401


def test_create_access_token_always_uses_current(monkeypatch):
    """New issuance never targets the rotation fallback."""
    monkeypatch.setattr(settings, "jwt_secret", "current-secret-x")
    monkeypatch.setattr(settings, "jwt_secret_previous", "old-secret-x")
    tok = auth.create_access_token("bob", role="user")
    # Decoding against the OLD secret must FAIL.
    with pytest.raises(Exception):
        jwt.decode(tok, "old-secret-x", algorithms=[settings.jwt_algorithm])
    # Decoding against the CURRENT secret must SUCCEED.
    payload = jwt.decode(tok, "current-secret-x",
                         algorithms=[settings.jwt_algorithm])
    assert payload["sub"] == "bob"


def test_duplicate_secrets_handled_gracefully(monkeypatch):
    """If operator misconfigures both env vars to the same value, no crash."""
    monkeypatch.setattr(settings, "jwt_secret", "same-secret")
    monkeypatch.setattr(settings, "jwt_secret_previous", "same-secret")
    tok = _make_token("same-secret")
    payload = auth._decode_token(tok)
    assert payload["sub"] == "alice"


def test_expired_token_rejected_regardless_of_rotation(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "current-secret")
    monkeypatch.setattr(settings, "jwt_secret_previous", "old-secret")
    expired = _make_token("current-secret", expires_in_minutes=-1)
    with pytest.raises(HTTPException) as exc:
        auth._decode_token(expired)
    assert exc.value.status_code == 401
