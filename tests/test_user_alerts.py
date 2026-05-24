"""
Tests for the per-user alert subscription endpoints (Task #31) and the
watchlist-add → default-alert auto-creation hook.

Coverage
────────
  • Auto-creation of default alerts when a ticker is added to a watchlist
  • Soft-delete of those alerts when the ticker is removed
  • GET  /users/me/alerts
  • POST /users/me/alerts (with default email, with override, no channel)
  • DELETE /users/me/alerts/{id}
  • Cross-user isolation (one user cannot see/delete another's alerts)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.db import (
    Base, get_db, User, AlertSubscription, WatchlistEntry,
)
from backend.main import app


BASE = "/api/v1"


@pytest.fixture(scope="module")
def db_engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)
    sess = Session()
    yield sess
    sess.rollback()
    # Wipe between tests so each starts clean.
    sess.query(AlertSubscription).delete()
    sess.query(WatchlistEntry).delete()
    sess.query(User).delete()
    sess.commit()
    sess.close()


@pytest.fixture
def client(db_session):
    def _override():
        yield db_session
    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── helpers ───────────────────────────────────────────────────────────────────

def _register_and_login(client, username, email="x@example.com",
                        password="GoodPass1!"):
    client.post(f"{BASE}/auth/register",
                json={"username": username, "email": email, "password": password})
    resp = client.post(f"{BASE}/auth/login",
                       json={"username": username, "email": "u@x",
                             "password": password})
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── watchlist-add auto-creates default alerts ─────────────────────────────────

def test_watchlist_add_creates_default_alerts(client, db_session):
    token = _register_and_login(client, "alice", "alice@example.com")
    resp = client.post(f"{BASE}/users/me/watchlist",
                       json={"ticker": "AAPL"}, headers=_auth(token))
    assert resp.status_code == 201

    subs = db_session.query(AlertSubscription).all()
    # Two defaults: risk_score_above + distress_zone
    assert len(subs) == 2
    conditions = sorted(s.condition for s in subs)
    assert conditions == ["distress_zone", "risk_score_above"]
    assert all(s.email == "alice@example.com" for s in subs)
    assert all(s.ticker == "AAPL" for s in subs)


def test_watchlist_remove_deactivates_alerts(client, db_session):
    token = _register_and_login(client, "bob", "bob@example.com")
    client.post(f"{BASE}/users/me/watchlist",
                json={"ticker": "TSLA"}, headers=_auth(token))

    # Two active subs.
    active_before = db_session.query(AlertSubscription).filter_by(active=True).count()
    assert active_before == 2

    del_resp = client.delete(f"{BASE}/users/me/watchlist/TSLA", headers=_auth(token))
    assert del_resp.status_code == 204

    active_after = db_session.query(AlertSubscription).filter_by(active=True).count()
    assert active_after == 0
    # Rows still present but soft-deleted — total count unchanged.
    total = db_session.query(AlertSubscription).count()
    assert total == 2


def test_watchlist_readd_after_delete_doesnt_duplicate_alerts(client, db_session):
    token = _register_and_login(client, "carol", "carol@example.com")
    client.post(f"{BASE}/users/me/watchlist",
                json={"ticker": "NVDA"}, headers=_auth(token))
    client.delete(f"{BASE}/users/me/watchlist/NVDA", headers=_auth(token))
    client.post(f"{BASE}/users/me/watchlist",
                json={"ticker": "NVDA"}, headers=_auth(token))

    # Still only 2 rows — the auto-create code skips when one already exists.
    total = db_session.query(AlertSubscription).count()
    assert total == 2


# ── user-scoped alert endpoints ───────────────────────────────────────────────

def test_list_my_alerts_starts_empty(client):
    token = _register_and_login(client, "dave", "dave@example.com")
    resp = client.get(f"{BASE}/users/me/alerts", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_my_alert_uses_account_email_by_default(client, db_session):
    token = _register_and_login(client, "eve", "eve@example.com")
    resp = client.post(
        f"{BASE}/users/me/alerts",
        json={"ticker": "AAPL", "condition": "risk_score_above",
              "threshold": 80.0},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "eve@example.com"


def test_create_my_alert_with_email_override(client):
    token = _register_and_login(client, "frank", "frank@example.com")
    resp = client.post(
        f"{BASE}/users/me/alerts",
        json={"ticker": "AAPL", "condition": "distress_zone",
              "email": "ops@example.com"},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "ops@example.com"


def test_create_my_alert_invalid_condition(client):
    token = _register_and_login(client, "grace", "grace@example.com")
    resp = client.post(
        f"{BASE}/users/me/alerts",
        json={"ticker": "AAPL", "condition": "totally_made_up"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


def test_create_my_alert_requires_auth(client):
    resp = client.post(
        f"{BASE}/users/me/alerts",
        json={"ticker": "AAPL", "condition": "distress_zone"},
    )
    assert resp.status_code == 401


def test_list_my_alerts_returns_only_my_alerts(client, db_session):
    """Cross-user isolation — alice never sees bob's subscriptions."""
    a_tok = _register_and_login(client, "alice_iso", "alice_iso@example.com")
    b_tok = _register_and_login(client, "bob_iso",   "bob_iso@example.com")

    client.post(f"{BASE}/users/me/alerts",
                json={"ticker": "AAPL", "condition": "distress_zone"},
                headers=_auth(a_tok))
    client.post(f"{BASE}/users/me/alerts",
                json={"ticker": "TSLA", "condition": "distress_zone"},
                headers=_auth(b_tok))

    alice_alerts = client.get(f"{BASE}/users/me/alerts",
                              headers=_auth(a_tok)).json()
    bob_alerts   = client.get(f"{BASE}/users/me/alerts",
                              headers=_auth(b_tok)).json()
    assert {a["ticker"] for a in alice_alerts} == {"AAPL"}
    assert {a["ticker"] for a in bob_alerts}   == {"TSLA"}


def test_delete_my_alert(client, db_session):
    token = _register_and_login(client, "henry", "henry@example.com")
    create_resp = client.post(
        f"{BASE}/users/me/alerts",
        json={"ticker": "NVDA", "condition": "distress_zone"},
        headers=_auth(token),
    )
    sub_id = create_resp.json()["id"]

    del_resp = client.delete(f"{BASE}/users/me/alerts/{sub_id}", headers=_auth(token))
    assert del_resp.status_code == 204

    listed = client.get(f"{BASE}/users/me/alerts", headers=_auth(token)).json()
    assert all(a["id"] != sub_id for a in listed)


def test_user_cannot_delete_another_users_alert(client, db_session):
    a_tok = _register_and_login(client, "alice_perm", "alice_perm@example.com")
    b_tok = _register_and_login(client, "bob_perm",   "bob_perm@example.com")

    create_resp = client.post(
        f"{BASE}/users/me/alerts",
        json={"ticker": "META", "condition": "distress_zone"},
        headers=_auth(a_tok),
    )
    a_sub_id = create_resp.json()["id"]

    del_resp = client.delete(f"{BASE}/users/me/alerts/{a_sub_id}", headers=_auth(b_tok))
    assert del_resp.status_code == 404      # not even visible to bob
