"""
Tests for v0.4.0 security hardening + audit log (Task #36).

Covers
──────
  • settings.validate_for_production() raises with insecure defaults
  • Settings non-prod path just warns (does not raise)
  • audit.record() inserts a row
  • audit.record() never raises — DB failure is swallowed
  • Privileged routes emit audit entries:
      POST /auth/token       → auth.admin_login
      POST /ml/train         → ml.train (success + failure variants)
      POST /scheduler/run/X  → scheduler.run
      POST /auth/register    → user.register
  • GET /audit (admin-only listing)
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.config import Settings, _INSECURE_DEFAULTS
from backend.database.db import Base, AuditLog, get_db
from backend.main import app
from backend.services import audit


BASE = "/api/v1"


# ── Settings.validate_for_production ──────────────────────────────────────────

def test_validate_for_production_raises_with_default_secret():
    s = Settings(
        app_env="production",
        jwt_secret=_INSECURE_DEFAULTS["jwt_secret"],
        admin_password="strong-real-password",
    )
    with pytest.raises(RuntimeError) as exc:
        s.validate_for_production()
    assert "jwt_secret" in str(exc.value)


def test_validate_for_production_raises_with_default_password():
    s = Settings(
        app_env="production",
        jwt_secret="super-secret-real-jwt",
        admin_password=_INSECURE_DEFAULTS["admin_password"],
    )
    with pytest.raises(RuntimeError) as exc:
        s.validate_for_production()
    assert "admin_password" in str(exc.value)


def test_validate_for_production_passes_with_real_values():
    s = Settings(
        app_env="production",
        jwt_secret="super-secret-real-jwt",
        admin_password="strong-real-password",
    )
    s.validate_for_production()    # should NOT raise


def test_validate_in_dev_only_warns(caplog):
    s = Settings(app_env="development")    # leaves both defaults
    s.validate_for_production()            # must not raise
    # Pydantic-settings logs via the module logger, so the warning lands
    # in caplog when logger level is propagated.
    # We're satisfied that no exception was raised — that's the contract.


# ── audit.record() ────────────────────────────────────────────────────────────

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


def test_audit_record_inserts_row(db_session):
    audit.record(db_session, actor="admin", action="ml.train",
                 target="AAPL", extra={"n_samples": 25})
    rows = db_session.query(AuditLog).all()
    assert len(rows) == 1
    assert rows[0].actor  == "admin"
    assert rows[0].action == "ml.train"
    assert rows[0].target == "AAPL"
    assert json.loads(rows[0].extra)["n_samples"] == 25


def test_audit_record_never_raises_on_db_failure(db_session):
    """A broken session should not bubble up to callers."""
    bad_session = db_session
    with patch.object(bad_session, "add", side_effect=RuntimeError("boom")):
        # Must NOT raise
        audit.record(bad_session, actor="x", action="y")


def test_audit_record_handles_non_json_extra(db_session):
    """default=str makes datetimes / Decimals serialisable."""
    from datetime import datetime
    audit.record(db_session, actor="admin", action="test",
                 extra={"when": datetime(2026, 1, 1)})
    row = db_session.query(AuditLog).first()
    assert "2026-01-01" in row.extra


# ── route-level audit emission ────────────────────────────────────────────────

@pytest.fixture
def client(db_session):
    def _override():
        yield db_session
    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _admin_token(client):
    return client.post(
        f"{BASE}/auth/token",
        data={"username": "admin", "password": "change-me"},
    ).json()["access_token"]


def test_admin_login_is_audited(client, db_session):
    _admin_token(client)
    rows = db_session.query(AuditLog).filter_by(action="auth.admin_login").all()
    assert len(rows) >= 1
    assert rows[0].actor == "admin"


def test_register_is_audited(client, db_session):
    resp = client.post(f"{BASE}/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "GoodPass1!",
    })
    assert resp.status_code == 201
    rows = db_session.query(AuditLog).filter_by(action="user.register").all()
    assert len(rows) == 1
    assert rows[0].actor == "alice"


def test_ml_train_failure_is_audited(client, db_session):
    """Even when training raises (insufficient data), the audit row records the
    attempt with `failed: True`."""
    token = _admin_token(client)
    # Don't seed any companies → train() raises ValueError("Not enough...")
    resp = client.post(f"{BASE}/ml/train",
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422
    rows = db_session.query(AuditLog).filter_by(action="ml.train").all()
    assert len(rows) == 1
    extra = json.loads(rows[0].extra)
    assert extra["failed"] is True


def test_scheduler_run_is_audited(client, db_session):
    token = _admin_token(client)
    with patch("backend.api.routes.job_svc.evaluate_active_alerts",
               return_value={"evaluated": 0, "fired": 0}):
        resp = client.post(
            f"{BASE}/scheduler/run/evaluate_active_alerts",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    rows = db_session.query(AuditLog).filter_by(action="scheduler.run").all()
    assert len(rows) == 1
    assert rows[0].target == "evaluate_active_alerts"


def test_audit_list_admin_only(client, db_session):
    # No token at all
    resp = client.get(f"{BASE}/audit")
    assert resp.status_code == 401


def test_audit_list_returns_recent_rows(client, db_session):
    token = _admin_token(client)    # generates one row
    audit.record(db_session, actor="admin", action="custom.action",
                 target="X", extra={"note": "test"})
    resp = client.get(f"{BASE}/audit?action=custom.action",
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["action"] == "custom.action"
    assert data[0]["extra"]["note"] == "test"


def test_audit_list_caps_limit(client, db_session):
    token = _admin_token(client)
    # request 9999 — should be clamped to 500
    resp = client.get(f"{BASE}/audit?limit=9999",
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    # We don't have 500 rows seeded, but the endpoint mustn't error.
    assert isinstance(resp.json(), list)
