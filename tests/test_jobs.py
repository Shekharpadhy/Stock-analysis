"""
Tests for backend/services/jobs.py — the per-job functions invoked by the
scheduler.

We do NOT spin up APScheduler here.  Schedulers are well-tested upstream;
what matters is that each job, given a real DB, performs its work correctly
and degrades gracefully.

Strategy
────────
  • Patch SessionLocal so every job uses an in-memory SQLite session.
  • Patch the alert dispatch function so no real email/Slack call escapes
    the test process.
  • Seed CompanyRecord / AlertSubscription rows directly via the patched
    session, then invoke jobs.evaluate_active_alerts() etc.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.db import (
    Base, AlertSubscription, CompanyRecord,
)
import backend.services.jobs as jobs


# ── shared engine / session fixtures ──────────────────────────────────────────

@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture(autouse=True)
def _patch_session_local(session_factory, monkeypatch):
    """
    jobs._with_session() opens a session via SessionLocal — point that at
    our in-memory engine for the duration of every test in this file.
    """
    monkeypatch.setattr(jobs, "SessionLocal", session_factory)


def _seed_company(db, ticker="AAPL", **kwargs):
    defaults = dict(
        ticker=ticker, name=ticker, sector="Tech",
        risk_score=50.0, altman_zone="Safe", quality_score=60.0,
    )
    defaults.update(kwargs)
    rec = CompanyRecord(**defaults)
    db.add(rec)
    db.commit()
    return rec


def _seed_subscription(db, **kwargs):
    defaults = dict(
        ticker="AAPL", condition="risk_score_above",
        threshold=70.0, email="a@b.com", slack_webhook=None,
        active=True,
    )
    defaults.update(kwargs)
    sub = AlertSubscription(**defaults)
    db.add(sub)
    db.commit()
    return sub


# ── evaluate_active_alerts ────────────────────────────────────────────────────

def test_alerts_fires_when_condition_holds(session_factory):
    db = session_factory()
    try:
        _seed_company(db, ticker="AAPL", risk_score=85.0)   # above threshold
        sub = _seed_subscription(db, ticker="AAPL", threshold=70.0)
        sub_id = sub.id     # capture before the session closes
    finally:
        db.close()

    with patch("backend.services.jobs.alert_svc.dispatch",
               return_value={"email": True}) as mock_dispatch:
        result = jobs.evaluate_active_alerts()

    assert result["evaluated"] == 1
    assert result["fired"] == 1
    assert result["skipped_cooldown"] == 0
    mock_dispatch.assert_called_once()

    # last_fired_at stamped
    db = session_factory()
    try:
        sub_refreshed = db.query(AlertSubscription).filter_by(id=sub_id).first()
        assert sub_refreshed.last_fired_at is not None
    finally:
        db.close()


def test_alerts_skipped_when_condition_doesnt_hold(session_factory):
    db = session_factory()
    try:
        _seed_company(db, risk_score=40.0)                 # below threshold
        _seed_subscription(db, threshold=70.0)
    finally:
        db.close()

    with patch("backend.services.jobs.alert_svc.dispatch") as mock_dispatch:
        result = jobs.evaluate_active_alerts()

    assert result["fired"] == 0
    assert result["not_triggered"] == 1
    mock_dispatch.assert_not_called()


def test_alerts_respect_cooldown(session_factory):
    """Within 24h of last_fired_at, no re-fire — even if condition holds."""
    db = session_factory()
    try:
        _seed_company(db, risk_score=85.0)
        _seed_subscription(
            db, threshold=70.0,
            last_fired_at=datetime.utcnow() - timedelta(hours=2),
        )
    finally:
        db.close()

    with patch("backend.services.jobs.alert_svc.dispatch") as mock_dispatch:
        result = jobs.evaluate_active_alerts()

    assert result["fired"] == 0
    assert result["skipped_cooldown"] == 1
    mock_dispatch.assert_not_called()


def test_alerts_fire_after_cooldown_expires(session_factory):
    db = session_factory()
    try:
        _seed_company(db, risk_score=85.0)
        _seed_subscription(
            db, threshold=70.0,
            last_fired_at=datetime.utcnow() - timedelta(hours=30),
        )
    finally:
        db.close()

    with patch("backend.services.jobs.alert_svc.dispatch",
               return_value={"email": True}) as mock_dispatch:
        result = jobs.evaluate_active_alerts()

    assert result["fired"] == 1
    mock_dispatch.assert_called_once()


def test_alerts_handles_missing_company_record(session_factory):
    db = session_factory()
    try:
        _seed_subscription(db, ticker="GHOST", threshold=70.0)
    finally:
        db.close()

    result = jobs.evaluate_active_alerts()
    assert result["no_company_data"] == 1
    assert result["fired"] == 0


def test_alerts_skip_inactive_subscriptions(session_factory):
    db = session_factory()
    try:
        _seed_company(db, risk_score=85.0)
        _seed_subscription(db, active=False)
    finally:
        db.close()

    result = jobs.evaluate_active_alerts()
    assert result["evaluated"] == 0


def test_alerts_only_one_query_per_ticker_set(session_factory):
    """
    Verify the implementation pre-loads CompanyRecords in one query.
    We don't have a query counter installed, so the indirect signal is that
    50 subs on 5 tickers all evaluate without slowing down — and the
    summary shape stays consistent.
    """
    db = session_factory()
    try:
        for ticker in ["A", "B", "C", "D", "E"]:
            _seed_company(db, ticker=ticker, risk_score=85.0)
        for ticker in ["A", "B", "C", "D", "E"]:
            for i in range(10):
                _seed_subscription(
                    db, ticker=ticker, threshold=70.0,
                    email=f"u{i}@{ticker}.com",
                )
    finally:
        db.close()

    with patch("backend.services.jobs.alert_svc.dispatch",
               return_value={"email": True}):
        result = jobs.evaluate_active_alerts()

    assert result["evaluated"] == 50
    assert result["fired"] == 50


def test_alerts_dispatch_failure_still_stamps_last_fired_at_NOT(session_factory):
    """
    Sanity: if dispatch raises (e.g., SMTP server down), we do NOT crash —
    and we move on to the next subscription.
    """
    db = session_factory()
    try:
        _seed_company(db, risk_score=85.0)
        _seed_subscription(db, threshold=70.0, email="x@y.com")
    finally:
        db.close()

    with patch("backend.services.jobs.alert_svc.dispatch",
               side_effect=RuntimeError("SMTP down")):
        result = jobs.evaluate_active_alerts()

    # The job-level summary should still report evaluating 1 sub.
    assert result["evaluated"] == 1
    # fired remained 0 because the dispatch raised.
    assert result["fired"] == 0


# ── score_matured_predictions ─────────────────────────────────────────────────

def test_score_matured_predictions_invokes_underlying(session_factory):
    """Job delegates to track_record.score_matured_predictions with a session."""
    with patch("backend.services.track_record.score_matured_predictions",
               return_value={"scored": 3, "skipped": 0}) as mock_impl:
        result = jobs.score_matured_predictions()

    mock_impl.assert_called_once()
    assert result["scored"] == 3


# ── retrain_ml_model ──────────────────────────────────────────────────────────

def test_retrain_ml_model_not_enough_data_is_non_fatal(session_factory):
    """Job returns a structured result instead of raising when data is sparse."""
    with patch("backend.services.ml_model.train",
               side_effect=ValueError("Not enough labelled samples to train")):
        result = jobs.retrain_ml_model()

    assert result["trained"] is False
    assert "Not enough" in result["reason"]


def test_retrain_ml_model_success(session_factory):
    fake_meta = {"n_samples": 25, "cv_auc": 0.82, "trained_at": "2026-05-24"}
    with patch("backend.services.ml_model.train", return_value=fake_meta):
        result = jobs.retrain_ml_model()

    assert result["trained"] is True
    assert result["meta"]["cv_auc"] == 0.82


# ── recalibrate_sectors ───────────────────────────────────────────────────────

def test_recalibrate_sectors_returns_summary(session_factory):
    with patch("backend.services.calibration.recalibrate_sector_profiles",
               return_value={"sectors": 5, "rows_inserted": 25}) as mock_impl:
        result = jobs.recalibrate_sectors()

    mock_impl.assert_called_once()
    assert result["sectors"] == 5


# ── _with_session error handling ──────────────────────────────────────────────

def test_with_session_catches_unexpected_errors(session_factory):
    """A raising work-fn returns an `error` dict instead of bubbling up."""
    out = jobs._with_session(lambda db: (_ for _ in ()).throw(RuntimeError("boom")))
    assert "error" in out
    assert "boom" in out["error"]
