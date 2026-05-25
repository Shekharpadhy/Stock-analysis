"""
Background jobs — pure functions invoked by the APScheduler runner.

Why this lives separate from scheduler.py
─────────────────────────────────────────
Tests want to exercise the *work*, not the scheduling.  Keeping these as
plain functions that take a DB session means tests can call them directly
against an in-memory DB and assert on side effects, while scheduler.py just
wires them onto cron triggers.

Each job:
  • Opens its own DB session (closed in a finally).
  • Catches and logs its own exceptions — a single bad ticker must not
    prevent later iterations.
  • Returns a structured summary dict for monitoring/logging.

Available jobs
──────────────
  score_matured_predictions  — every 6h
  evaluate_active_alerts     — every 1h (absolute conditions + cooldown)
  retrain_ml_model           — weekly
  recalibrate_sectors        — weekly
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from backend.database.db import (
    SessionLocal, CompanyRecord, AlertSubscription,
)
from backend.services import alerts as alert_svc
from backend.services import scheduler_lock

log = logging.getLogger(__name__)


# Cooldown between two consecutive fires of the same subscription.  24h
# avoids spamming the same alert when the underlying condition is persistent
# (e.g., a stock that's been at risk_score=85 for a week).
ALERT_COOLDOWN = timedelta(hours=24)


def _with_session(work: Callable[[Any], Dict[str, Any]]) -> Dict[str, Any]:
    """
    Run `work(db)` with a freshly-opened session, guaranteeing the session
    is closed even if the work raises.  Returns the work's summary dict
    (or an `{"error": ...}` dict on failure).
    """
    db = SessionLocal()
    try:
        return work(db)
    except Exception as exc:
        log.exception("job: unexpected failure")
        return {"error": str(exc)}
    finally:
        db.close()


def _with_leader_session(work: Callable[[Any], Dict[str, Any]]) -> Dict[str, Any]:
    """
    Same as _with_session, but the job body only runs when this worker holds
    the scheduler lock.  Followers report `{"skipped": "not_leader"}` so the
    summary dict is still consistent and the metric counter still moves.
    """
    db = SessionLocal()
    try:
        if not scheduler_lock.try_acquire(db):
            log.debug("job: skipped — another worker holds the scheduler lock")
            return {"skipped": "not_leader",
                    "holder":  scheduler_lock.current_holder(db)}
        return work(db)
    except Exception as exc:
        log.exception("job: unexpected failure")
        return {"error": str(exc)}
    finally:
        db.close()


# ── job: prediction maturity scoring ──────────────────────────────────────────

def score_matured_predictions() -> Dict[str, Any]:
    """
    Grade every Prediction whose horizon has matured against the actual
    forward price.  Idempotent — the underlying track_record helper only
    touches rows where scored=False.
    """
    from backend.services.track_record import score_matured_predictions as _impl

    def _work(db):
        result = _impl(db) or {}
        log.info("jobs: matured-prediction scoring — %s", result)
        return {"job": "score_matured_predictions", **result}

    return _with_leader_session(_work)


# ── job: alert evaluation (absolute + cooldown) ───────────────────────────────

def evaluate_active_alerts(now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    For every active AlertSubscription:
      1. Load the CompanyRecord for its ticker.
      2. Evaluate the absolute condition (not edge-triggered).
      3. If true AND outside the per-sub cooldown window → dispatch +
         update last_fired_at.

    Returns a summary with counts of subs evaluated / fired / skipped.
    """
    now = now or datetime.now(timezone.utc)

    def _work(db):
        subs = (
            db.query(AlertSubscription)
            .filter(AlertSubscription.active.is_(True))
            .all()
        )

        # Pre-load all the relevant CompanyRecords in one query (avoids N+1
        # when there are many subscriptions).
        tickers = {s.ticker for s in subs}
        if tickers:
            recs = {
                r.ticker: r
                for r in db.query(CompanyRecord)
                .filter(CompanyRecord.ticker.in_(tickers)).all()
            }
        else:
            recs = {}

        fired = skipped_cooldown = no_data = not_triggered = 0
        for sub in subs:
            rec = recs.get(sub.ticker)
            if rec is None:
                no_data += 1
                continue

            triggered, current_value = alert_svc._evaluate_absolute(
                sub.condition, sub.threshold, rec,
            )
            if not triggered:
                not_triggered += 1
                continue

            # Cooldown gate — never fire two alerts within ALERT_COOLDOWN.
            last = sub.last_fired_at
            if last is not None:
                # Stored as naive UTC; treat consistently.
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if now - last < ALERT_COOLDOWN:
                    skipped_cooldown += 1
                    continue

            payload = alert_svc._build_alert_payload(
                sub.ticker, sub.condition, sub.threshold, current_value,
            )
            try:
                alert_svc.dispatch(sub, payload)
                # Stamp regardless of delivery outcome — we count an
                # "attempt" so a permanently broken channel doesn't
                # rapid-fire on every scheduler tick.
                sub.last_fired_at = now.replace(tzinfo=None)
                fired += 1
            except Exception as exc:
                log.warning("jobs: dispatch failed for sub %s — %s", sub.id, exc)

        db.commit()
        result = {
            "job":               "evaluate_active_alerts",
            "evaluated":         len(subs),
            "fired":             fired,
            "skipped_cooldown":  skipped_cooldown,
            "no_company_data":   no_data,
            "not_triggered":     not_triggered,
        }
        log.info("jobs: alert sweep — %s", result)
        return result

    return _with_leader_session(_work)


# ── job: weekly ML model retrain ──────────────────────────────────────────────

def retrain_ml_model() -> Dict[str, Any]:
    """
    Retrain the XGBoost distress model on the latest CompanyRecord +
    BacktestObservation data.  Silently no-ops when there isn't enough
    labelled data — the existing model on disk stays in place.
    """
    from backend.services import ml_model

    def _work(db):
        try:
            meta = ml_model.train(db)
            log.info("jobs: ml_model retrained — n=%d AUC=%.4f",
                     meta["n_samples"], meta["cv_auc"])
            return {"job": "retrain_ml_model", "trained": True, "meta": meta}
        except ValueError as exc:
            # Not-enough-data is expected and non-fatal; surface it but
            # don't blow up the scheduler.
            log.info("jobs: ml_model retrain skipped — %s", exc)
            return {"job": "retrain_ml_model", "trained": False,
                    "reason": str(exc)}

    return _with_leader_session(_work)


# ── job: weekly sector recalibration ──────────────────────────────────────────

def recalibrate_sectors() -> Dict[str, Any]:
    """Re-estimate sector medians/spreads from accumulated CompanyRecord rows."""
    from backend.services.calibration import recalibrate_sector_profiles

    def _work(db):
        result = recalibrate_sector_profiles(db)
        log.info("jobs: sector recalibration — %s", result)
        return {"job": "recalibrate_sectors", **(result or {})}

    return _with_leader_session(_work)
