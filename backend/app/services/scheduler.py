from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError
from sqlalchemy.orm import Session

from app.services.settings_service import get_bool, get_int
from app.utils.time import to_iso_z

logger = logging.getLogger(__name__)

JOB_ID = "fn2trakt-sync"
WEBHOOK_JOB_ID = "fn2trakt-webhook-retry"
_scheduler = BackgroundScheduler(job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120})
_started = False


def _ingest_step() -> None:
    """Read new plays out of the fnTV database into the local mirror."""
    from app.db.session import SessionLocal
    from app.fntv import FnTvError
    from app.services.refresh import RefreshBusy, auto_refresh_enabled, refresh_fntv

    db = SessionLocal()
    try:
        if not auto_refresh_enabled(db):
            return
        try:
            refresh_fntv(db, trigger="scheduled")
        except RefreshBusy:
            logger.info("scheduled fnTV refresh skipped: another read is running")
        except FnTvError as exc:
            logger.warning("scheduled fnTV refresh failed: %s", exc)
    except Exception:  # pragma: no cover - background safety
        logger.exception("scheduled fnTV refresh crashed")
    finally:
        db.close()


def _sync_step() -> None:
    """Upload newly completed plays to Trakt."""
    from app.db.session import SessionLocal
    from app.services.settings_service import get_bool
    from app.services.sync import run_all

    db = SessionLocal()
    try:
        if not get_bool(db, "sync.enabled", True):
            return
    finally:
        db.close()
    try:
        run_all("scheduled")
    except Exception:  # pragma: no cover - background safety
        logger.exception("scheduled Trakt sync crashed")


def _job() -> None:
    # Order matters: ingest first, upload second.  A failing fnTV read must not
    # prevent the uploader from retrying records that are already mirrored.
    _ingest_step()
    _sync_step()


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
    ingest_enabled = get_bool(db, "sync.ingest_enabled", True)
    sync_enabled = get_bool(db, "sync.enabled", True)
    if ingest_enabled or sync_enabled:
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
    from app.services.refresh import last_state

    enabled = get_bool(db, "sync.enabled", True)
    ingest_enabled = get_bool(db, "sync.ingest_enabled", True)
    minutes = max(1, get_int(db, "sync.interval_minutes", 5))
    job = _scheduler.get_job(JOB_ID) if _started else None
    next_run: datetime | None = getattr(job, "next_run_time", None) if job else None
    if next_run is not None and next_run.tzinfo is None:
        next_run = next_run.astimezone()
    refresh = last_state(db)
    return {
        "running": _started,
        "enabled": enabled,
        "ingest_enabled": ingest_enabled,
        "interval_minutes": minutes,
        "next_run_at": to_iso_z(next_run),
        "last_refresh_at": refresh["last_refresh_at"],
        "last_refresh_error": refresh["last_refresh_error"],
        "last_refresh_trigger": refresh["last_refresh_trigger"],
        "last_refresh_summary": refresh["last_refresh_summary"],
    }
