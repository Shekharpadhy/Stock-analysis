"""
Tests for backend/middleware.py — request ID propagation.

The contract under test
───────────────────────
  • Every response carries an X-Request-ID header.
  • The ID is a UUID-shaped string when none is supplied.
  • A client-supplied X-Request-ID is echoed back when it matches the
    acceptable charset (UUID-ish).
  • A malformed inbound ID is ignored (no echo) so a hostile client can't
    pin its own trace key.
  • Concurrent requests get distinct IDs — no leakage across the ContextVar.
  • The active ID is visible to code inside the request handler via
    get_request_id().
  • Logs emitted during the request carry request_id in the JSON payload.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.logging_config import configure_logging
from backend.middleware import (
    RequestIDMiddleware, RequestIDLogFilter, get_request_id,
)


@pytest.fixture
def app():
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/peek")
    def peek():
        return {"id": get_request_id()}

    @app.get("/log-me")
    def log_me():
        logging.getLogger("test").info("hello from handler")
        return {"ok": True}

    return app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


# ── Header behaviour ──────────────────────────────────────────────────────────

def test_response_always_carries_request_id(client):
    r = client.get("/peek")
    assert "X-Request-ID" in r.headers
    rid = r.headers["X-Request-ID"]
    # Auto-generated → looks like a UUID.
    uuid.UUID(rid)


def test_inbound_request_id_is_honoured(client):
    supplied = "trace-abc-12345678"
    r = client.get("/peek", headers={"X-Request-ID": supplied})
    assert r.headers["X-Request-ID"] == supplied


def test_malformed_inbound_id_is_ignored(client):
    """Spaces / control chars / overly long → reject and regenerate."""
    bad = "not allowed because spaces"
    r = client.get("/peek", headers={"X-Request-ID": bad})
    assert r.headers["X-Request-ID"] != bad
    uuid.UUID(r.headers["X-Request-ID"])


def test_handler_sees_active_id_via_contextvar(client):
    r = client.get("/peek")
    body = r.json()
    assert body["id"] == r.headers["X-Request-ID"]


# ── Per-request isolation ─────────────────────────────────────────────────────

def test_each_request_gets_distinct_id(client):
    seen = set()
    for _ in range(10):
        seen.add(client.get("/peek").headers["X-Request-ID"])
    assert len(seen) == 10


def test_concurrent_requests_dont_leak_ids(app):
    """ContextVar isolates per-request — concurrent calls each see their own."""
    client = TestClient(app)
    def _call(_):
        return client.get("/peek").json()["id"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(_call, range(40)))

    assert len(set(ids)) == 40, "ContextVar leaked across requests"


# ── ContextVar default ────────────────────────────────────────────────────────

def test_get_request_id_returns_none_outside_a_request():
    """Anyone calling get_request_id() at module level / startup gets None."""
    assert get_request_id() is None


# ── Log filter integration ────────────────────────────────────────────────────

def test_log_filter_stamps_records_inside_request(app, capsys):
    """Logs emitted inside a request should carry request_id."""
    configure_logging(level="INFO", fmt="json")    # installs the filter
    client = TestClient(app)
    r = client.get("/log-me", headers={"X-Request-ID": "req-test-12345"})
    out = capsys.readouterr().out
    # Find the log line emitted by the handler.
    matching = [ln for ln in out.splitlines()
                if ln.startswith("{") and '"hello from handler"' in ln]
    assert matching, f"no log line captured; got:\n{out}"
    payload = json.loads(matching[-1])
    assert payload["request_id"] == "req-test-12345"
    assert r.headers["X-Request-ID"] == "req-test-12345"


def test_log_filter_uses_placeholder_outside_request():
    """Records emitted outside a request get '-' so the key is always present."""
    configure_logging(level="INFO", fmt="json")
    rec  = logging.LogRecord(
        name="x", level=logging.INFO, pathname=__file__,
        lineno=1, msg="standalone", args=(), exc_info=None,
    )
    RequestIDLogFilter().filter(rec)
    assert rec.request_id == "-"
