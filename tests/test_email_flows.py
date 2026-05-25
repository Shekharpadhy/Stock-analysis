"""
Tests for the v1.0 account-lifecycle email flows.

Covered
───────
  • user_tokens.generate() / redeem() / invalidate_pending()
  • POST /auth/register triggers a verification email (mocked send)
  • GET  /auth/verify marks user.email_verified true
  • POST /auth/verify/resend behaves identically for unknown / known emails
    (no account enumeration)
  • POST /auth/password-reset/request always 202, regardless of email match
  • POST /auth/password-reset/confirm sets a new password, invalidates other
    live reset tokens
  • Tokens are single-use, expiry is enforced, wrong-purpose redemption fails
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.db import Base, User, UserToken, get_db
from backend.main import app
from backend.services import user_tokens


BASE = "/api/v1"


# ── DB + client fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def db_session():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    sess = Session()
    yield sess
    sess.close()


@pytest.fixture
def client(db_session):
    def _override():
        yield db_session
    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_user(db, **kwargs):
    from backend.auth import hash_password
    defaults = dict(
        username="alice", email="alice@example.com",
        hashed_password=hash_password("GoodPass1!"),
        role="user", is_active=True, email_verified=False,
    )
    defaults.update(kwargs)
    u = User(**defaults); db.add(u); db.commit(); db.refresh(u)
    return u


# ── user_tokens primitive ─────────────────────────────────────────────────────

def test_generate_returns_plaintext_and_stores_hash(db_session):
    user = _make_user(db_session)
    plaintext = user_tokens.generate(db_session, user.id, "email_verify")
    assert isinstance(plaintext, str) and len(plaintext) >= 32

    row = db_session.query(UserToken).filter_by(user_id=user.id).first()
    assert row is not None
    # The plaintext is NEVER in the DB — only its hash.
    assert plaintext not in row.token_hash
    assert row.used_at is None


def test_redeem_success_marks_used(db_session):
    user = _make_user(db_session)
    plaintext = user_tokens.generate(db_session, user.id, "email_verify")
    out = user_tokens.redeem(db_session, plaintext, "email_verify")
    assert out == user.id

    # Second redemption attempt fails.
    out2 = user_tokens.redeem(db_session, plaintext, "email_verify")
    assert out2 is None


def test_redeem_wrong_purpose_fails(db_session):
    user = _make_user(db_session)
    plaintext = user_tokens.generate(db_session, user.id, "email_verify")
    out = user_tokens.redeem(db_session, plaintext, "password_reset")
    assert out is None


def test_redeem_expired_fails(db_session):
    user = _make_user(db_session)
    plaintext = user_tokens.generate(db_session, user.id, "email_verify",
                                     ttl_hours=24)
    # Manually expire by setting expires_at in the past.
    row = db_session.query(UserToken).filter_by(user_id=user.id).first()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()

    assert user_tokens.redeem(db_session, plaintext, "email_verify") is None


def test_redeem_unknown_token_returns_none(db_session):
    assert user_tokens.redeem(db_session, "totally-bogus", "email_verify") is None
    assert user_tokens.redeem(db_session, "", "email_verify") is None


def test_invalidate_pending_burns_live_tokens(db_session):
    user = _make_user(db_session)
    tok1 = user_tokens.generate(db_session, user.id, "password_reset")
    tok2 = user_tokens.generate(db_session, user.id, "password_reset")

    user_tokens.invalidate_pending(db_session, user.id, "password_reset")

    assert user_tokens.redeem(db_session, tok1, "password_reset") is None
    assert user_tokens.redeem(db_session, tok2, "password_reset") is None


# ── /auth/register → verify ──────────────────────────────────────────────────

def test_register_sends_verification_email(client, db_session):
    with patch("backend.api.routes.email_delivery.send_verification_email",
               return_value=True) as mock_send:
        resp = client.post(f"{BASE}/auth/register", json={
            "username": "newbie", "email": "newbie@example.com",
            "password": "GoodPass1!",
        })
    assert resp.status_code == 201
    mock_send.assert_called_once()
    to_addr, link = mock_send.call_args.args
    assert to_addr == "newbie@example.com"
    assert "/api/v1/auth/verify?token=" in link

    # And the user starts as unverified.
    user = db_session.query(User).filter_by(username="newbie").first()
    assert user.email_verified is False


def test_register_response_marks_user_unverified(client):
    with patch("backend.api.routes.email_delivery.send_verification_email",
               return_value=True):
        resp = client.post(f"{BASE}/auth/register", json={
            "username": "ver_check", "email": "ver_check@example.com",
            "password": "GoodPass1!",
        })
    assert resp.status_code == 201
    assert resp.json()["email_verified"] is False


def test_verify_endpoint_flips_flag(client, db_session):
    with patch("backend.api.routes.email_delivery.send_verification_email",
               return_value=True) as mock_send:
        client.post(f"{BASE}/auth/register", json={
            "username": "verify_user", "email": "v@example.com",
            "password": "GoodPass1!",
        })
    link = mock_send.call_args.args[1]
    token = link.split("token=")[1]

    resp = client.get(f"{BASE}/auth/verify?token={token}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "verified"

    user = db_session.query(User).filter_by(username="verify_user").first()
    assert user.email_verified is True


def test_verify_invalid_token_400(client):
    resp = client.get(f"{BASE}/auth/verify?token=garbage")
    assert resp.status_code == 400


def test_verify_token_single_use(client, db_session):
    with patch("backend.api.routes.email_delivery.send_verification_email",
               return_value=True) as mock_send:
        client.post(f"{BASE}/auth/register", json={
            "username": "single_use", "email": "s@example.com",
            "password": "GoodPass1!",
        })
    token = mock_send.call_args.args[1].split("token=")[1]

    assert client.get(f"{BASE}/auth/verify?token={token}").status_code == 200
    assert client.get(f"{BASE}/auth/verify?token={token}").status_code == 400


def test_resend_verification_is_idempotent_on_unknown_email(client):
    with patch("backend.api.routes.email_delivery.send_verification_email") as mock_send:
        resp = client.post(f"{BASE}/auth/verify/resend",
                           json={"email": "nobody@example.com"})
    assert resp.status_code == 202
    mock_send.assert_not_called()    # no enumeration via send


def test_resend_verification_for_known_unverified_user(client, db_session):
    _make_user(db_session, email_verified=False)
    with patch("backend.api.routes.email_delivery.send_verification_email",
               return_value=True) as mock_send:
        resp = client.post(f"{BASE}/auth/verify/resend",
                           json={"email": "alice@example.com"})
    assert resp.status_code == 202
    mock_send.assert_called_once()


# ── Password reset ───────────────────────────────────────────────────────────

def test_password_reset_request_unknown_email_still_202(client):
    with patch("backend.api.routes.email_delivery.send_password_reset_email") as mock_send:
        resp = client.post(f"{BASE}/auth/password-reset/request",
                           json={"email": "ghost@example.com"})
    assert resp.status_code == 202
    mock_send.assert_not_called()


def test_password_reset_request_known_email_sends(client, db_session):
    _make_user(db_session)
    with patch("backend.api.routes.email_delivery.send_password_reset_email",
               return_value=True) as mock_send:
        resp = client.post(f"{BASE}/auth/password-reset/request",
                           json={"email": "alice@example.com"})
    assert resp.status_code == 202
    mock_send.assert_called_once()
    to_addr, link = mock_send.call_args.args
    assert to_addr == "alice@example.com"
    assert "/api/v1/auth/password-reset/confirm?token=" in link


def test_password_reset_confirm_changes_password(client, db_session):
    user = _make_user(db_session)
    with patch("backend.api.routes.email_delivery.send_password_reset_email",
               return_value=True) as mock_send:
        client.post(f"{BASE}/auth/password-reset/request",
                    json={"email": user.email})
    token = mock_send.call_args.args[1].split("token=")[1]

    resp = client.post(f"{BASE}/auth/password-reset/confirm", json={
        "token": token, "new_password": "BrandNewPass1!",
    })
    assert resp.status_code == 200

    # Old password no longer works.
    bad = client.post(f"{BASE}/auth/login", json={
        "username": user.username, "email": "x@x", "password": "GoodPass1!",
    })
    assert bad.status_code == 401

    # New one does.
    good = client.post(f"{BASE}/auth/login", json={
        "username": user.username, "email": "x@x", "password": "BrandNewPass1!",
    })
    assert good.status_code == 200


def test_password_reset_confirm_short_password_rejected(client, db_session):
    user = _make_user(db_session)
    with patch("backend.api.routes.email_delivery.send_password_reset_email",
               return_value=True) as mock_send:
        client.post(f"{BASE}/auth/password-reset/request",
                    json={"email": user.email})
    token = mock_send.call_args.args[1].split("token=")[1]

    resp = client.post(f"{BASE}/auth/password-reset/confirm",
                       json={"token": token, "new_password": "short"})
    assert resp.status_code == 422


def test_password_reset_token_single_use(client, db_session):
    user = _make_user(db_session)
    with patch("backend.api.routes.email_delivery.send_password_reset_email",
               return_value=True) as mock_send:
        client.post(f"{BASE}/auth/password-reset/request",
                    json={"email": user.email})
    token = mock_send.call_args.args[1].split("token=")[1]

    assert client.post(f"{BASE}/auth/password-reset/confirm", json={
        "token": token, "new_password": "BrandNewPass1!",
    }).status_code == 200
    # Second use fails.
    assert client.post(f"{BASE}/auth/password-reset/confirm", json={
        "token": token, "new_password": "AnotherPass1!",
    }).status_code == 400


def test_new_request_invalidates_previous_reset_token(client, db_session):
    user = _make_user(db_session)
    with patch("backend.api.routes.email_delivery.send_password_reset_email",
               return_value=True) as mock_send:
        client.post(f"{BASE}/auth/password-reset/request",
                    json={"email": user.email})
        old_token = mock_send.call_args.args[1].split("token=")[1]
        # Second request should invalidate the first.
        client.post(f"{BASE}/auth/password-reset/request",
                    json={"email": user.email})

    # First (now invalidated) token must NOT work.
    resp = client.post(f"{BASE}/auth/password-reset/confirm", json={
        "token": old_token, "new_password": "AnotherPass1!",
    })
    assert resp.status_code == 400
