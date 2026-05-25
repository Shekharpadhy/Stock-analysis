"""
Integration tests that exercise the assembled FastAPI app end-to-end.

These differ from the unit-style tests in tests/test_*.py in that they boot
the real `app` (with full lifespan, all middleware, all routers) and assert
the public HTTP surface — no dependency overrides, no monkeypatching.

They run inside the same suite — there's no separate CI job.  Scheduler is
already disabled via conftest.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app

BASE = "/api/v1"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ── Health + metrics surface ──────────────────────────────────────────────────

def test_health_endpoint_returns_ok(client):
    resp = client.get(f"{BASE}/health")
    assert resp.status_code in (200, 503)        # 503 only if DB ping fails
    data = resp.json()
    assert "status"     in data
    assert "components" in data


def test_metrics_endpoint_serves_prometheus_text(client):
    resp = client.get(f"{BASE}/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")


# ── X-Request-ID middleware integration ───────────────────────────────────────

def test_every_response_has_request_id_header(client):
    resp = client.get(f"{BASE}/health")
    assert "X-Request-ID" in resp.headers
    assert len(resp.headers["X-Request-ID"]) >= 6


# ── Auth surface — public routes don't 500 even when unauthenticated ──────────

def test_admin_only_endpoint_returns_401_without_token(client):
    resp = client.get(f"{BASE}/audit")
    assert resp.status_code == 401


def test_admin_token_endpoint_responds(client):
    """Just verifies the endpoint is mounted — bad creds → 401, not 404 / 500."""
    resp = client.post(
        f"{BASE}/auth/token",
        data={"username": "wrong", "password": "wrong"},
    )
    assert resp.status_code == 401


def test_companies_listing_is_public(client):
    resp = client.get(f"{BASE}/companies")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_openapi_schema_served(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert schema["info"]["title"]
    # Spot-check that v1.0 endpoints appear in the published schema.
    paths = schema["paths"]
    assert "/api/v1/auth/register"               in paths
    assert "/api/v1/auth/verify"                 in paths
    assert "/api/v1/auth/password-reset/request" in paths
    assert "/api/v1/users/me/portfolio"          in paths
