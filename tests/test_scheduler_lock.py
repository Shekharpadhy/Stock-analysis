"""
Tests for the scheduler leader-election lock (Task #50).

Contract under test
───────────────────
  • First caller acquires the lock.
  • Subsequent calls from the SAME worker_id keep the lock (heartbeat).
  • Calls from a DIFFERENT worker_id are rejected while the lease is valid.
  • Once the lease expires, a different worker can steal.
  • release() lets a graceful shutdown hand off immediately.
  • Jobs wrapped in _with_leader_session run for the leader and report
    "not_leader" for followers (no duplicate work).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.db import Base, SchedulerLock
from backend.services import scheduler_lock
import backend.services.jobs as jobs


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db_session():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _reset_worker_id(monkeypatch):
    """Force a deterministic worker ID per-test so leader/follower semantics
    are unambiguous."""
    monkeypatch.setattr(scheduler_lock, "WORKER_ID", "worker-A")
    yield


# ── try_acquire ───────────────────────────────────────────────────────────────

def test_first_call_acquires(db_session):
    assert scheduler_lock.try_acquire(db_session) is True
    row = db_session.query(SchedulerLock).first()
    assert row.worker_id == "worker-A"


def test_same_worker_heartbeats(db_session, monkeypatch):
    scheduler_lock.try_acquire(db_session)
    t0 = db_session.query(SchedulerLock).first().expires_at

    # Bump time forward; same worker calls again → expires_at extends.
    later = datetime.utcnow() + timedelta(seconds=30)
    assert scheduler_lock.try_acquire(db_session, now=later) is True
    t1 = db_session.query(SchedulerLock).first().expires_at
    assert t1 > t0


def test_different_worker_rejected_while_valid(db_session, monkeypatch):
    scheduler_lock.try_acquire(db_session)        # worker-A acquires

    monkeypatch.setattr(scheduler_lock, "WORKER_ID", "worker-B")
    assert scheduler_lock.try_acquire(db_session) is False
    # Row still belongs to worker-A.
    assert db_session.query(SchedulerLock).first().worker_id == "worker-A"


def test_different_worker_steals_expired_lock(db_session, monkeypatch):
    scheduler_lock.try_acquire(db_session)

    # Expire the lease manually.
    row = db_session.query(SchedulerLock).first()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()

    monkeypatch.setattr(scheduler_lock, "WORKER_ID", "worker-B")
    assert scheduler_lock.try_acquire(db_session) is True
    assert db_session.query(SchedulerLock).first().worker_id == "worker-B"


def test_release_lets_next_worker_acquire_immediately(db_session, monkeypatch):
    scheduler_lock.try_acquire(db_session)
    scheduler_lock.release(db_session)
    assert db_session.query(SchedulerLock).first() is None

    monkeypatch.setattr(scheduler_lock, "WORKER_ID", "worker-B")
    assert scheduler_lock.try_acquire(db_session) is True


def test_release_no_op_for_non_holder(db_session, monkeypatch):
    scheduler_lock.try_acquire(db_session)        # worker-A holds it
    monkeypatch.setattr(scheduler_lock, "WORKER_ID", "worker-B")
    scheduler_lock.release(db_session)            # should NOT delete the row
    assert db_session.query(SchedulerLock).first() is not None


def test_current_holder_returns_state(db_session):
    assert scheduler_lock.current_holder(db_session) is None
    scheduler_lock.try_acquire(db_session)
    info = scheduler_lock.current_holder(db_session)
    assert info["worker_id"] == "worker-A"
    assert info["is_us"] is True


# ── leader-gated job wrapper ──────────────────────────────────────────────────

def test_leader_session_runs_work_for_leader(db_session, monkeypatch):
    monkeypatch.setattr(jobs, "SessionLocal",
                        sessionmaker(bind=db_session.bind))
    out = jobs._with_leader_session(lambda db: {"did_work": True})
    assert out == {"did_work": True}


def test_leader_session_skips_followers(db_session, monkeypatch):
    """Pre-seed a lock owned by a different worker; our call must defer."""
    db_session.add(SchedulerLock(
        name=scheduler_lock.LOCK_NAME, worker_id="other-worker",
        acquired_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(seconds=60),
    ))
    db_session.commit()

    monkeypatch.setattr(jobs, "SessionLocal",
                        sessionmaker(bind=db_session.bind))
    sentinel = []
    out = jobs._with_leader_session(lambda db: sentinel.append("ran") or {"x": 1})
    assert out["skipped"] == "not_leader"
    assert sentinel == []          # work was NOT executed


def test_evaluate_active_alerts_is_leader_gated(db_session, monkeypatch):
    """Plug in our DB AND a foreign-owned lock; the job must skip."""
    db_session.add(SchedulerLock(
        name=scheduler_lock.LOCK_NAME, worker_id="other-worker",
        acquired_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(seconds=60),
    ))
    db_session.commit()

    monkeypatch.setattr(jobs, "SessionLocal",
                        sessionmaker(bind=db_session.bind))
    with patch("backend.services.jobs.alert_svc.dispatch") as mock_dispatch:
        out = jobs.evaluate_active_alerts()
    assert out.get("skipped") == "not_leader"
    mock_dispatch.assert_not_called()
