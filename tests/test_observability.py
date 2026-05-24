"""
Tests for Task #37 — /health, /metrics, and the MetricRegistry primitive.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.db import Base, get_db
from backend.main import app
from backend.services.metrics import MetricRegistry, REGISTRY


BASE = "/api/v1"


# ── MetricRegistry primitive ──────────────────────────────────────────────────

def test_inc_starts_at_zero_then_accumulates():
    r = MetricRegistry()
    assert r.get("foo") == 0.0
    r.inc("foo")
    r.inc("foo", value=2.5)
    assert r.get("foo") == 3.5


def test_inc_keyed_by_labels():
    r = MetricRegistry()
    r.inc("alerts_fired_total", labels={"condition": "risk_score_above"})
    r.inc("alerts_fired_total", labels={"condition": "risk_score_above"})
    r.inc("alerts_fired_total", labels={"condition": "distress_zone"})
    assert r.get("alerts_fired_total",
                 labels={"condition": "risk_score_above"}) == 2
    assert r.get("alerts_fired_total",
                 labels={"condition": "distress_zone"}) == 1


def test_label_order_independent():
    r = MetricRegistry()
    r.inc("m", labels={"a": "1", "b": "2"})
    r.inc("m", labels={"b": "2", "a": "1"})       # same logical key
    assert r.get("m", labels={"a": "1", "b": "2"}) == 2


def test_render_emits_prometheus_text():
    r = MetricRegistry()
    r.describe("test_total", "A test counter")
    r.inc("test_total")
    r.inc("test_total", labels={"sector": "Tech"})
    out = r.render()
    assert "# HELP test_total A test counter" in out
    assert "# TYPE test_total counter"        in out
    assert "test_total 1"                     in out
    assert 'test_total{sector="Tech"} 1'      in out


def test_render_escapes_special_chars_in_labels():
    r = MetricRegistry()
    r.inc("m", labels={"x": 'a"b\\c\n'})
    out = r.render()
    # Quotes, backslashes, newlines all escaped per Prometheus spec.
    assert 'x="a\\"b\\\\c\\n"' in out


def test_reset_clears_state():
    r = MetricRegistry()
    r.inc("foo")
    r.reset()
    assert r.get("foo") == 0.0
    assert r.render().strip() == ""


# ── Endpoint tests ────────────────────────────────────────────────────────────

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


def test_health_reports_components(client):
    resp = client.get(f"{BASE}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert "database"  in data["components"]
    assert "scheduler" in data["components"]
    assert "ml_model"  in data["components"]
    assert data["components"]["database"]["status"] == "ok"


def test_health_database_down_returns_503(client, db_session, monkeypatch):
    """If SELECT 1 raises, /health reports `down` with HTTP 503."""
    def _raise(*a, **kw):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(db_session, "execute", _raise)
    resp = client.get(f"{BASE}/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "down"


def test_metrics_returns_prometheus_text(client):
    REGISTRY.inc("analyses_total", labels={"sector": "Tech"})
    resp = client.get(f"{BASE}/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert "analyses_total" in body
    assert 'sector="Tech"'  in body


def test_metrics_endpoint_unauthenticated(client):
    """Prometheus scrapers can't carry bearer tokens — /metrics must be open."""
    resp = client.get(f"{BASE}/metrics")
    assert resp.status_code == 200
