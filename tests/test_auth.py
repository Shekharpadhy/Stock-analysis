"""Tests for JWT authentication — token creation, validation, admin check."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt

from backend.config import settings
from backend import auth


# ── Admin credential check ────────────────────────────────────────────────────
def test_authenticate_admin_accepts_correct_credentials():
    assert auth.authenticate_admin(
        settings.admin_username, settings.admin_password
    ) is True


def test_authenticate_admin_rejects_wrong_password():
    assert auth.authenticate_admin(settings.admin_username, "definitely-wrong") is False


def test_authenticate_admin_rejects_wrong_username():
    assert auth.authenticate_admin("intruder", settings.admin_password) is False


# ── Token round-trip ──────────────────────────────────────────────────────────
def test_valid_token_roundtrips_through_require_auth():
    token = auth.create_access_token("admin")
    assert auth.require_auth(token=token) == "admin"


# ── Rejection paths ───────────────────────────────────────────────────────────
def test_garbage_token_is_rejected():
    with pytest.raises(HTTPException) as exc:
        auth.require_auth(token="not-a-real-jwt")
    assert exc.value.status_code == 401


def test_token_signed_with_wrong_secret_is_rejected():
    forged = jwt.encode(
        {"sub": "admin"}, "the-wrong-secret", algorithm=settings.jwt_algorithm
    )
    with pytest.raises(HTTPException) as exc:
        auth.require_auth(token=forged)
    assert exc.value.status_code == 401


def test_expired_token_is_rejected():
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    expired = jwt.encode(
        {"sub": "admin", "exp": past},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(HTTPException) as exc:
        auth.require_auth(token=expired)
    assert exc.value.status_code == 401


def test_token_without_subject_is_rejected():
    no_sub = jwt.encode(
        {"foo": "bar", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(HTTPException) as exc:
        auth.require_auth(token=no_sub)
    assert exc.value.status_code == 401
