"""
APScheduler wrapper — registers periodic jobs and exposes start/shutdown
hooks called from the FastAPI lifespan in backend/main.py.

Design
──────
A single AsyncIOScheduler runs in-process alongside the FastAPI event loop.
Jobs are kept simple (no chaining, no dependencies) — each one re-opens its
own DB session, swallows its own exceptions, and returns a summary dict.

Why AsyncIOScheduler (not BackgroundScheduler)
──────────────────────────────────────────────
The web app already has an event loop, and AsyncIOScheduler integrates with
it cleanly — no extra thread, no coordination overhead.  Job functions are
sync (they do blocking I/O), so we wrap them with `run_in_threadpool` style
delegation via APScheduler's executor.

Toggle
──────
Set `SCHEDULER_ENABLED=false` (or the equivalent settings flag) to disable
the scheduler entirely — useful for tests and for one-shot CLI invocations.
"""

from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.config import settings
from backend.services import jobs

log = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None


def _register_jobs(scheduler: AsyncIOScheduler) -> None:
    """
    Install every periodic job onto `scheduler`.

    Cadences are tuned conservatively:
      • Alerts every hour — frequent enough that a freshly-crossed threshold
        gets attention within an hour, sparse enough that cooldown gating
        keeps inbox volume sane.
      • Prediction scoring every 6h — predictions mature on calendar dates,
        so 6h granularity is plenty.
      • Retraining + recalibration weekly — these are expensive and
        relatively stable signals.
    """
    scheduler.add_job(
        jobs.evaluate_active_alerts,
        trigger    = IntervalTrigger(hours=1),
        id         = "evaluate_active_alerts",
        name       = "Alert sweep (hourly)",
        max_instances=1, coalesce=True, replace_existing=True,
    )

    scheduler.add_job(
        jobs.score_matured_predictions,
        trigger    = IntervalTrigger(hours=6),
        id         = "score_matured_predictions",
        name       = "Prediction maturity scoring (6h)",
        max_instances=1, coalesce=True, replace_existing=True,
    )

    # Sunday 02:00 UTC — chosen for lowest-traffic window.
    scheduler.add_job(
        jobs.retrain_ml_model,
        trigger    = CronTrigger(day_of_week="sun", hour=2, minute=0),
        id         = "retrain_ml_model",
        name       = "ML model retrain (weekly)",
        max_instances=1, coalesce=True, replace_existing=True,
    )

    # Sunday 03:00 UTC — a comfortable hour after the retrain so the two
    # never collide on a single-core box.
    scheduler.add_job(
        jobs.recalibrate_sectors,
        trigger    = CronTrigger(day_of_week="sun", hour=3, minute=0),
        id         = "recalibrate_sectors",
        name       = "Sector recalibration (weekly)",
        max_instances=1, coalesce=True, replace_existing=True,
    )


def start_scheduler() -> Optional[AsyncIOScheduler]:
    """Initialise the singleton scheduler and start it.  Idempotent."""
    global _scheduler
    if not settings.scheduler_enabled:
        log.info("scheduler: disabled via settings.scheduler_enabled=false")
        return None

    if _scheduler is not None and _scheduler.running:
        return _scheduler

    sched = AsyncIOScheduler(timezone="UTC")
    _register_jobs(sched)
    sched.start()
    log.info(
        "scheduler: started — jobs=%s",
        sorted(j.id for j in sched.get_jobs()),
    )
    _scheduler = sched
    return sched


def shutdown_scheduler() -> None:
    """Gracefully stop the scheduler if it's running."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("scheduler: shut down")
    _scheduler = None


def get_scheduler() -> Optional[AsyncIOScheduler]:
    """Expose the scheduler instance (or None) for status endpoints."""
    return _scheduler


def get_job_status() -> dict:
    """Return a structured snapshot of the scheduler state."""
    if _scheduler is None or not _scheduler.running:
        return {"running": False, "jobs": []}
    return {
        "running": True,
        "jobs": [
            {
                "id":        j.id,
                "name":      j.name,
                "next_run":  j.next_run_time.isoformat() if j.next_run_time else None,
                "trigger":   str(j.trigger),
            }
            for j in _scheduler.get_jobs()
        ],
    }
