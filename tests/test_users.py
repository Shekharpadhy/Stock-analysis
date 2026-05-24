"""
Unit + integration tests for multi-user workspace (Task #27).

Covers:
  - User registration: happy path, duplicate username, duplicate email,
    short username, short password
  - User login: valid credentials, wrong password, unknown user
  - GET /users/me: authenticated user + admin synthetic profile
  - Watchlist: add, list, duplicate, remove, 404
  - GET /users (admin list): requires admin token
  - Password hashing helpers
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.db import Base, get_db
from backend.main import app
from backend.auth import hash_password, verify_password

# ── fixtures ──────────────────────────────────────────────────────────────────

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
    from backend.database.db import User, WatchlistEntry
    Session = sessionmaker(bind=db_engine)
    sess = Session()
    yield sess
    sess.rollback()
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


BASE = "/api/v1"


def _admin_token(client) -> str:
    resp = client.post(
        f"{BASE}/auth/token",
        data={"username": "admin", "password": "change-me"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _register(client, username="alice", email="alice@example.com", password="Passw0rd!"):
    return client.post(
        f"{BASE}/auth/register",
        json={"username": username, "email": email, "password": password},
    )


def _login(client, username="alice", password="Passw0rd!"):
    return client.post(
        f"{BASE}/auth/login",
        json={"username": username, "email": "unused@x.com", "password": password},
    )


# ── password hashing helpers ──────────────────────────────────────────────────

def test_hash_and_verify_password():
    h = hash_password("secret123")
    assert verify_password("secret123", h) is True
    assert verify_password("wrong", h) is False


def test_hash_is_not_plaintext():
    h = hash_password("mysecret")
    assert "mysecret" not in h


def test_new_hashes_use_argon2id():
    """v0.5.0+ defaults to argon2id — every fresh hash carries that marker."""
    h = hash_password("anything")
    assert h.startswith("$argon2"), h


def test_legacy_sha256_crypt_hash_still_verifies():
    """Backward-compat: hashes from v0.2.x must still verify."""
    from passlib.hash import sha256_crypt
    legacy = sha256_crypt.hash("OldPassword1!")
    assert legacy.startswith("$5$")           # sha256_crypt marker
    assert verify_password("OldPassword1!", legacy) is True


def test_legacy_login_rehashes_to_argon2(client, db_session):
    """End-to-end: a user whose row has a sha256_crypt hash logs in,
    server transparently upgrades the hash to argon2id, next login
    succeeds against the new hash."""
    from passlib.hash import sha256_crypt
    from backend.database.db import User

    # Seed a user with a legacy hash directly in the DB.
    legacy_user = User(
        username="legacy", email="legacy@example.com",
        hashed_password=sha256_crypt.hash("LegacyPass1!"),
        role="user", is_active=True,
    )
    db_session.add(legacy_user)
    db_session.commit()

    # First login: succeeds + triggers the rehash.
    resp = client.post(f"{BASE}/auth/login",
                       json={"username": "legacy", "email": "u@x",
                             "password": "LegacyPass1!"})
    assert resp.status_code == 200

    # Inspect the stored hash — must now be argon2.
    db_session.refresh(legacy_user)
    assert legacy_user.hashed_password.startswith("$argon2"), \
        legacy_user.hashed_password

    # Second login still works against the new hash.
    resp2 = client.post(f"{BASE}/auth/login",
                        json={"username": "legacy", "email": "u@x",
                              "password": "LegacyPass1!"})
    assert resp2.status_code == 200


# ── registration ──────────────────────────────────────────────────────────────

def test_register_success(client):
    resp = _register(client)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["username"] == "alice"
    assert data["role"] == "user"
    assert data["is_active"] is True
    assert "password" not in data
    assert "hashed_password" not in data


def test_register_duplicate_username(client):
    _register(client, username="bob", email="bob@example.com")
    resp = _register(client, username="bob", email="bob2@example.com")
    assert resp.status_code == 409


def test_register_duplicate_email(client):
    _register(client, username="carol", email="shared@example.com")
    resp = _register(client, username="carol2", email="shared@example.com")
    assert resp.status_code == 409


def test_register_short_username(client):
    resp = _register(client, username="ab", email="ab@example.com")
    assert resp.status_code == 422


def test_register_short_password(client):
    resp = _register(client, username="dave", email="dave@example.com", password="short")
    assert resp.status_code == 422


# ── login ─────────────────────────────────────────────────────────────────────

def test_login_success(client):
    _register(client, username="eve", email="eve@example.com", password="EvePass1!")
    resp = _login(client, username="eve", password="EvePass1!")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client):
    _register(client, username="frank", email="frank@example.com", password="FrankPass1!")
    resp = _login(client, username="frank", password="wrongpass")
    assert resp.status_code == 401


def test_login_unknown_user(client):
    resp = _login(client, username="nobody", password="whatever123")
    assert resp.status_code == 401


# ── /users/me ─────────────────────────────────────────────────────────────────

def test_get_me_authenticated(client):
    _register(client, username="grace", email="grace@example.com", password="GracePass1!")
    token = _login(client, "grace", "GracePass1!").json()["access_token"]
    resp = client.get(f"{BASE}/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "grace"


def test_get_me_admin_synthetic(client):
    token = _admin_token(client)
    resp = client.get(f"{BASE}/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"
    assert resp.json()["role"] == "admin"


def test_get_me_unauthenticated(client):
    resp = client.get(f"{BASE}/users/me")
    assert resp.status_code == 401


# ── watchlist ─────────────────────────────────────────────────────────────────

def _user_token(client, suffix="watch") -> str:
    uname = f"user_{suffix}"
    email = f"{uname}@example.com"
    _register(client, username=uname, email=email, password="WatchPass1!")
    return _login(client, username=uname, password="WatchPass1!").json()["access_token"]


def test_watchlist_add_and_list(client):
    token = _user_token(client, "add")
    headers = {"Authorization": f"Bearer {token}"}

    # Add two tickers
    for t in ["AAPL", "MSFT"]:
        resp = client.post(
            f"{BASE}/users/me/watchlist",
            json={"ticker": t},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["ticker"] == t

    # List
    list_resp = client.get(f"{BASE}/users/me/watchlist", headers=headers)
    assert list_resp.status_code == 200
    tickers = [e["ticker"] for e in list_resp.json()]
    assert "AAPL" in tickers
    assert "MSFT" in tickers


def test_watchlist_duplicate_rejected(client):
    token = _user_token(client, "dup")
    headers = {"Authorization": f"Bearer {token}"}
    client.post(f"{BASE}/users/me/watchlist", json={"ticker": "TSLA"}, headers=headers)
    resp = client.post(f"{BASE}/users/me/watchlist", json={"ticker": "TSLA"}, headers=headers)
    assert resp.status_code == 409


def test_watchlist_remove(client):
    token = _user_token(client, "rm")
    headers = {"Authorization": f"Bearer {token}"}
    client.post(f"{BASE}/users/me/watchlist", json={"ticker": "NVDA"}, headers=headers)
    del_resp = client.delete(f"{BASE}/users/me/watchlist/NVDA", headers=headers)
    assert del_resp.status_code == 204

    list_resp = client.get(f"{BASE}/users/me/watchlist", headers=headers)
    tickers = [e["ticker"] for e in list_resp.json()]
    assert "NVDA" not in tickers


def test_watchlist_remove_not_in_list(client):
    token = _user_token(client, "notfound")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.delete(f"{BASE}/users/me/watchlist/ZZZZ", headers=headers)
    assert resp.status_code == 404


def test_watchlist_with_notes(client):
    token = _user_token(client, "notes")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        f"{BASE}/users/me/watchlist",
        json={"ticker": "AMZN", "notes": "watching for earnings"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["notes"] == "watching for earnings"


def test_watchlist_unauthenticated(client):
    resp = client.get(f"{BASE}/users/me/watchlist")
    assert resp.status_code == 401


# ── admin list users ──────────────────────────────────────────────────────────

def test_list_users_as_admin(client):
    _register(client, username="henry", email="henry@example.com")
    token = _admin_token(client)
    resp = client.get(f"{BASE}/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    usernames = [u["username"] for u in resp.json()]
    assert "henry" in usernames


def test_list_users_as_regular_user_forbidden(client):
    _register(client, username="ivan", email="ivan@example.com", password="IvanPass1!")
    token = _login(client, "ivan", "IvanPass1!").json()["access_token"]
    resp = client.get(f"{BASE}/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_list_users_unauthenticated(client):
    resp = client.get(f"{BASE}/users")
    assert resp.status_code == 401
