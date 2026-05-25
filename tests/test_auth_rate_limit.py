"""
Explicit verification that the rate-limiter decorations on auth endpoints
actually fire when slowapi is enabled.

Strategy
────────
The full test suite runs with RATE_LIMIT_ENABLED=false (see conftest.py).
For these tests we flip the live limiter's `enabled` flag on, reset its
counters, hammer the endpoint past the configured threshold, and confirm
the 429 lands.  We also restore the previous state so other test files
aren't affected.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.limiter import limiter
from backend.main import app


@pytest.fixture
def rate_limited_client():
    """Activate the limiter for the duration of one test; restore on exit."""
    was_enabled = limiter.enabled
    limiter.enabled = True
    limiter.reset()
    try:
        with TestClient(app) as c:
            yield c
    finally:
        limiter.enabled = was_enabled
        limiter.reset()


BASE = "/api/v1"


def test_auth_login_user_returns_429_when_exhausted(rate_limited_client):
    """
    /auth/login is decorated with rate_limit_auth_login (default 10/minute).
    The 11th request inside one minute must 429.
    """
    body = {"username": "ghost", "email": "x@y.com", "password": "wrong"}

    for i in range(10):
        r = rate_limited_client.post(f"{BASE}/auth/login", json=body)
        # 401 because the user doesn't exist — rate limiter not yet tripped.
        assert r.status_code == 401, f"call {i+1} got {r.status_code}"

    # 11th call within the same minute: limiter should reject.
    r = rate_limited_client.post(f"{BASE}/auth/login", json=body)
    assert r.status_code == 429, r.text


def test_auth_admin_token_also_rate_limited(rate_limited_client):
    """Admin token endpoint shares the same login throttle (10/min)."""
    creds = {"username": "wrong", "password": "wrong"}

    for _ in range(10):
        r = rate_limited_client.post(f"{BASE}/auth/token", data=creds)
        assert r.status_code == 401

    r = rate_limited_client.post(f"{BASE}/auth/token", data=creds)
    assert r.status_code == 429


def test_auth_register_rate_limited(rate_limited_client):
    """/auth/register defaults to 5/hour — 6th request should 429."""
    for i in range(5):
        body = {"username": f"ratelim_{i}", "email": f"r{i}@x.com",
                "password": "GoodPass1!"}
        r = rate_limited_client.post(f"{BASE}/auth/register", json=body)
        # 201 first time, 409 if dupe — both legitimate, not 429 yet.
        assert r.status_code in (201, 409), \
            f"call {i+1} got {r.status_code}: {r.text}"

    r = rate_limited_client.post(f"{BASE}/auth/register", json={
        "username": "u_over", "email": "over@x.com", "password": "GoodPass1!",
    })
    assert r.status_code == 429
