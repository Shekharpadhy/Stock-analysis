"""
Unit tests for backend/services/alerts.py and the /alerts/* API endpoints.

Tests cover:
  - Condition evaluation (edge-triggered logic for each condition)
  - Email and Slack delivery helpers (mocked transport)
  - dispatch() routing
  - get_config() sanitisation
  - API: GET /alerts/config
  - API: GET /alerts/subscriptions
  - API: POST /alerts/subscriptions (validation + creation)
  - API: DELETE /alerts/subscriptions/{id}
  - API: POST /alerts/test/{id}
  - check_and_fire() integration (fires on transition, silent when stable)
"""

from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.services.alerts as alert_svc
from backend.database.db import Base, AlertSubscription, get_db
from backend.main import app

# ── test DB fixtures ──────────────────────────────────────────────────────────

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
    # Delete alert rows between tests to avoid unique-constraint collisions
    sess.query(AlertSubscription).delete()
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

# ── helpers ───────────────────────────────────────────────────────────────────

def _make_rec(**kwargs):
    rec = MagicMock()
    defaults = dict(
        risk_score=50.0, altman_zone="Safe",
        quality_score=60.0,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(rec, k, v)
    return rec


def _make_sub(
    condition="risk_score_above",
    threshold=70.0,
    email="test@example.com",
    slack_webhook=None,
    active=True,
):
    sub = MagicMock()
    sub.id            = 1
    sub.ticker        = "AAPL"
    sub.condition     = condition
    sub.threshold     = threshold
    sub.email         = email
    sub.slack_webhook = slack_webhook
    sub.active        = active
    return sub


# ── condition evaluation ──────────────────────────────────────────────────────

def test_risk_score_crosses_above():
    old = _make_rec(risk_score=65.0)
    new = _make_rec(risk_score=75.0)
    triggered, val = alert_svc._evaluate_condition("risk_score_above", 70.0, old, new)
    assert triggered is True
    assert val == 75.0


def test_risk_score_stays_above_no_retrigger():
    """Already above threshold — no edge transition → should NOT fire."""
    old = _make_rec(risk_score=72.0)
    new = _make_rec(risk_score=80.0)
    triggered, _ = alert_svc._evaluate_condition("risk_score_above", 70.0, old, new)
    assert triggered is False


def test_risk_score_below_threshold_no_fire():
    old = _make_rec(risk_score=50.0)
    new = _make_rec(risk_score=60.0)
    triggered, _ = alert_svc._evaluate_condition("risk_score_above", 70.0, old, new)
    assert triggered is False


def test_distress_zone_transition():
    old = _make_rec(altman_zone="Grey")
    new = _make_rec(altman_zone="Distress")
    triggered, val = alert_svc._evaluate_condition("distress_zone", None, old, new)
    assert triggered is True
    assert val == "Distress"


def test_distress_zone_already_distress_no_retrigger():
    old = _make_rec(altman_zone="Distress")
    new = _make_rec(altman_zone="Distress")
    triggered, _ = alert_svc._evaluate_condition("distress_zone", None, old, new)
    assert triggered is False


def test_ml_prob_crosses_above():
    old = _make_rec()
    old._last_ml_prob = 0.45
    triggered, val = alert_svc._evaluate_condition(
        "ml_prob_above", 0.60, old, old, ml_prob=0.72
    )
    assert triggered is True
    assert val == 0.72


def test_ml_prob_no_prob_given():
    old = _make_rec()
    triggered, val = alert_svc._evaluate_condition("ml_prob_above", 0.60, old, old)
    assert triggered is False


def test_quality_score_drops_below():
    old = _make_rec(quality_score=45.0)
    new = _make_rec(quality_score=35.0)
    triggered, val = alert_svc._evaluate_condition("quality_score_below", 40.0, old, new)
    assert triggered is True
    assert val == 35.0


def test_quality_score_already_below_no_retrigger():
    old = _make_rec(quality_score=30.0)
    new = _make_rec(quality_score=25.0)
    triggered, _ = alert_svc._evaluate_condition("quality_score_below", 40.0, old, new)
    assert triggered is False


# ── payload builder ───────────────────────────────────────────────────────────

def test_build_alert_payload_fields():
    p = alert_svc._build_alert_payload("AAPL", "risk_score_above", 70.0, 75.3)
    assert p["ticker"] == "AAPL"
    assert "AAPL" in p["headline"]
    assert p["condition"] == "risk_score_above"
    assert p["threshold"] == 70.0
    assert p["current_value"] == 75.3


# ── delivery helpers ──────────────────────────────────────────────────────────

def test_send_email_skipped_when_not_configured(monkeypatch):
    monkeypatch.setattr(alert_svc.settings, "alert_smtp_host", "")
    payload = alert_svc._build_alert_payload("X", "distress_zone", None, "Distress")
    result = alert_svc._send_email("someone@example.com", payload)
    assert result is False


def test_send_email_calls_smtp(monkeypatch):
    monkeypatch.setattr(alert_svc.settings, "alert_smtp_host", "smtp.test.com")
    monkeypatch.setattr(alert_svc.settings, "alert_smtp_user", "user@test.com")
    monkeypatch.setattr(alert_svc.settings, "alert_smtp_password", "secret")
    monkeypatch.setattr(alert_svc.settings, "alert_smtp_port", 587)

    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)

    with patch("smtplib.SMTP", return_value=mock_smtp):
        payload = alert_svc._build_alert_payload("AAPL", "risk_score_above", 70.0, 75.0)
        result = alert_svc._send_email("dest@example.com", payload)

    assert result is True
    mock_smtp.sendmail.assert_called_once()


def test_send_slack_skipped_when_no_url():
    payload = alert_svc._build_alert_payload("X", "distress_zone", None, "Distress")
    result = alert_svc._send_slack("", payload)
    assert result is False


def test_send_slack_posts_to_webhook(monkeypatch):
    payload = alert_svc._build_alert_payload("AAPL", "risk_score_above", 70.0, 75.0)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        result = alert_svc._send_slack("https://hooks.slack.com/test", payload)

    assert result is True
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "blocks" in call_kwargs.kwargs["json"]


# ── dispatch ──────────────────────────────────────────────────────────────────

def test_dispatch_routes_to_email_and_slack(monkeypatch):
    sub = _make_sub(email="a@b.com", slack_webhook="https://hooks.slack.com/x")
    payload = alert_svc._build_alert_payload("AAPL", "risk_score_above", 70.0, 75.0)

    with patch.object(alert_svc, "_send_email", return_value=True) as me, \
         patch.object(alert_svc, "_send_slack", return_value=True) as ms:
        result = alert_svc.dispatch(sub, payload)

    me.assert_called_once_with("a@b.com", payload)
    ms.assert_called_once_with("https://hooks.slack.com/x", payload)
    assert result == {"email": True, "slack": True}


def test_dispatch_only_email_when_no_slack(monkeypatch):
    monkeypatch.setattr(alert_svc.settings, "alert_slack_webhook", "")
    sub = _make_sub(email="a@b.com", slack_webhook=None)
    payload = alert_svc._build_alert_payload("AAPL", "risk_score_above", 70.0, 75.0)

    with patch.object(alert_svc, "_send_email", return_value=True) as me, \
         patch.object(alert_svc, "_send_slack") as ms:
        result = alert_svc.dispatch(sub, payload)

    me.assert_called_once()
    ms.assert_not_called()
    assert "email" in result


# ── get_config ────────────────────────────────────────────────────────────────

def test_get_config_returns_valid_conditions():
    cfg = alert_svc.get_config()
    assert "risk_score_above" in cfg["valid_conditions"]
    assert "distress_zone" in cfg["valid_conditions"]
    assert "smtp_configured" in cfg
    assert "slack_configured" in cfg


# ── check_and_fire integration ────────────────────────────────────────────────

def test_check_and_fire_fires_on_transition():
    old = _make_rec(risk_score=60.0)
    new = _make_rec(risk_score=80.0)

    sub = _make_sub(condition="risk_score_above", threshold=70.0, email="x@y.com")

    db = MagicMock()
    # check_and_fire calls .filter(cond1, cond2).all() — single filter call
    db.query.return_value.filter.return_value.all.return_value = [sub]

    with patch.object(alert_svc, "dispatch", return_value={"email": True}) as md:
        fired = alert_svc.check_and_fire("AAPL", old, new, db)

    assert len(fired) == 1
    assert fired[0]["payload"]["ticker"] == "AAPL"
    md.assert_called_once()


def test_check_and_fire_silent_when_not_triggered():
    old = _make_rec(risk_score=40.0)
    new = _make_rec(risk_score=50.0)

    sub = _make_sub(condition="risk_score_above", threshold=70.0, email="x@y.com")

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [sub]

    with patch.object(alert_svc, "dispatch") as md:
        fired = alert_svc.check_and_fire("AAPL", old, new, db)

    assert fired == []
    md.assert_not_called()


# ── API endpoints ─────────────────────────────────────────────────────────────

def test_api_get_config(client):
    resp = client.get(f"{BASE}/alerts/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "valid_conditions" in data
    assert "smtp_configured" in data


def test_api_list_subscriptions_empty(client):
    resp = client.get(f"{BASE}/alerts/subscriptions")
    assert resp.status_code == 200
    assert resp.json() == []


def _get_token(client) -> str:
    resp = client.post(
        f"{BASE}/auth/token",
        data={"username": "admin", "password": "change-me"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_api_create_subscription(client):
    token = _get_token(client)
    resp = client.post(
        f"{BASE}/alerts/subscriptions",
        json={
            "ticker": "AAPL",
            "condition": "risk_score_above",
            "threshold": 70.0,
            "email": "alert@example.com",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert data["condition"] == "risk_score_above"
    assert data["active"] is True


def test_api_create_subscription_invalid_condition(client):
    token = _get_token(client)
    resp = client.post(
        f"{BASE}/alerts/subscriptions",
        json={
            "ticker": "AAPL",
            "condition": "not_a_real_condition",
            "email": "x@example.com",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_api_create_subscription_no_channel(client):
    token = _get_token(client)
    resp = client.post(
        f"{BASE}/alerts/subscriptions",
        json={
            "ticker": "AAPL",
            "condition": "risk_score_above",
            "threshold": 70.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_api_create_subscription_requires_auth(client):
    resp = client.post(
        f"{BASE}/alerts/subscriptions",
        json={
            "ticker": "AAPL",
            "condition": "risk_score_above",
            "email": "x@example.com",
        },
    )
    assert resp.status_code == 401


def test_api_list_after_create(client):
    token = _get_token(client)
    client.post(
        f"{BASE}/alerts/subscriptions",
        json={"ticker": "TSLA", "condition": "distress_zone", "email": "b@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = client.get(f"{BASE}/alerts/subscriptions")
    assert resp.status_code == 200
    tickers = [s["ticker"] for s in resp.json()]
    assert "TSLA" in tickers


def test_api_delete_subscription(client):
    token = _get_token(client)
    create_resp = client.post(
        f"{BASE}/alerts/subscriptions",
        json={"ticker": "MSFT", "condition": "distress_zone", "email": "c@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    sub_id = create_resp.json()["id"]

    del_resp = client.delete(
        f"{BASE}/alerts/subscriptions/{sub_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 204

    # Should not appear in listing any more
    list_resp = client.get(f"{BASE}/alerts/subscriptions")
    ids = [s["id"] for s in list_resp.json()]
    assert sub_id not in ids


def test_api_delete_nonexistent(client):
    token = _get_token(client)
    resp = client.delete(
        f"{BASE}/alerts/subscriptions/99999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_api_test_alert(client):
    token = _get_token(client)
    create_resp = client.post(
        f"{BASE}/alerts/subscriptions",
        json={"ticker": "NVDA", "condition": "risk_score_above",
              "threshold": 70.0, "email": "d@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    sub_id = create_resp.json()["id"]

    with patch.object(alert_svc, "_send_email", return_value=True):
        resp = client.post(
            f"{BASE}/alerts/test/{sub_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "payload" in data
    assert "TEST" in data["payload"]["headline"]


def test_api_test_alert_nonexistent(client):
    token = _get_token(client)
    resp = client.post(
        f"{BASE}/alerts/test/99999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
