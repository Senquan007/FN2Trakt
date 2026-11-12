from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError
from sqlalchemy.orm import Session

from app.services.settings_service import get_bool, get_int
from app.utils.time import to_iso_z

JOB_ID = "fn2trakt-sync"
WEBHOOK_JOB_ID = "fn2trakt-webhook-retry"
_scheduler = BackgroundScheduler(job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120})
_started = False


def _job() -> None:
    from app.services.sync import run_all

    try:
        run_all("scheduled")
    except Exception:  # pragma: no cover - background safety
        pass


def _webhook_job() -> None:
    from app.db.session import SessionLocal
    from app.services.webhooks import retry_due

    db = SessionLocal()
    try:
        retry_due(db)
    except Exception:  # pragma: no cover - background safety
        pass
    finally:
        db.close()


def start() -> None:
    global _started
    if not _started:
        _scheduler.start()
        _started = True


def shutdown() -> None:
    global _started
    if _started:
        _scheduler.shutdown(wait=False)
        _started = False


def configure(db: Session) -> None:
    try:
        _scheduler.remove_job(JOB_ID)
    except JobLookupError:
        pass
    if get_bool(db, "sync.enabled", True):
        minutes = max(1, get_int(db, "sync.interval_minutes", 5))
        _scheduler.add_job(_job, "interval", minutes=minutes, id=JOB_ID, replace_existing=True)
    try:
        _scheduler.remove_job(WEBHOOK_JOB_ID)
    except JobLookupError:
        pass
    _scheduler.add_job(
        _webhook_job, "interval", minutes=5, id=WEBHOOK_JOB_ID, replace_existing=True
    )


def state(db: Session) -> dict:
    enabled = get_bool(db, "sync.enabled", True)
    minutes = max(1, get_int(db, "sync.interval_minutes", 5))
    job = _scheduler.get_job(JOB_ID) if _started else None
    next_run: datetime | None = getattr(job, "next_run_time", None) if job else None
    if next_run is not None and next_run.tzinfo is None:
        next_run = next_run.astimezone()
    return {
        "running": _started,
        "enabled": enabled,
        "interval_minutes": minutes,
        "next_run_at": to_iso_z(next_run),
    }
