"""Read the fnTV (飞牛) database into the local mirror.

The uploader only ever reads ``play_record``; without this step a play that
fnTV recorded after the last manual refresh would never reach Trakt.  The
scheduler therefore runs :func:`refresh_fntv` before every upload cycle.

Reading ``trimmedia.db`` is a full scan of ``item`` + ``item_user_play``, so the
step is skipped when neither the database file nor its WAL sidecar changed
since the last successful read.  Callers can pass ``force=True`` (the manual
"重新读取飞牛数据" button) to bypass the check.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.fntv import FnTvError, read_snapshot
from app.services.ingest import ingest_snapshot
from app.services.matching import ensure_matches
from app.services.settings_service import fntv_db_path, get_float, get_setting, set_setting
from app.utils.time import to_iso_z, utcnow

logger = logging.getLogger(__name__)

SIGNATURE_KEY = "fntv.refresh.signature"
LAST_AT_KEY = "fntv.refresh.last_at"
LAST_SUMMARY_KEY = "fntv.refresh.last_summary"
LAST_ERROR_KEY = "fntv.refresh.last_error"
LAST_TRIGGER_KEY = "fntv.refresh.last_trigger"

_LOCK = threading.Lock()


class RefreshBusy(RuntimeError):
    """Another fnTV read is already running."""


def database_signature(path: Path) -> str:
    """Cheap fingerprint of the fnTV database.

    The fnTV database runs in WAL mode, where ordinary writes land in
    ``-wal`` and the main file only changes on checkpoint.  Watching both is
    enough to notice almost every change without opening the database.
    ``-shm`` is deliberately ignored: readers touch it without any data
    change and would trigger a needless full scan.
    """
    parts: list[str] = []
    for candidate in (path, Path(f"{path}-wal")):
        try:
            stat = candidate.stat()
        except OSError:
            continue
        parts.append(f"{candidate.name}:{stat.st_mtime_ns}:{stat.st_size}")
    return "|".join(parts)


def last_state(db: Session) -> dict[str, Any]:
    """Snapshot of the last read, used by the settings page."""
    summary_raw = get_setting(db, LAST_SUMMARY_KEY)
    summary: dict[str, Any] | None = None
    if summary_raw:
        try:
            parsed = json.loads(summary_raw)
            if isinstance(parsed, dict):
                summary = parsed
        except ValueError:
            summary = None
    return {
        "last_refresh_at": get_setting(db, LAST_AT_KEY),
        "last_refresh_error": get_setting(db, LAST_ERROR_KEY),
        "last_refresh_trigger": get_setting(db, LAST_TRIGGER_KEY),
        "last_refresh_summary": summary,
        "signature": get_setting(db, SIGNATURE_KEY),
    }


def _summary_payload(result, snapshot, match_stats: dict[str, int] | None) -> dict[str, Any]:
    return {
        "users": result.users,
        "media": result.media,
        "plays": result.plays,
        "completed": result.completed,
        "created": result.created_plays,
        "updated": result.updated_plays,
        "skipped": snapshot.skipped,
        "warnings": list(result.warnings)[:5],
        "matching": match_stats,
    }


def _remember(db: Session, *, signature: str, summary: dict[str, Any], trigger: str) -> None:
    set_setting(db, SIGNATURE_KEY, signature)
    set_setting(db, LAST_AT_KEY, to_iso_z(utcnow()))
    set_setting(db, LAST_SUMMARY_KEY, json.dumps(summary, ensure_ascii=False))
    set_setting(db, LAST_ERROR_KEY, None)
    set_setting(db, LAST_TRIGGER_KEY, trigger)
    db.commit()


def _notify_unmatched(db: Session, trigger: str) -> None:
    """Tell the operator about media that just became unmatchable.

    Runs after every successful read so an unmatched item found by the
    background scanner reaches the webhook even when no Trakt upload happens
    (an upload is never attempted for unmatched media).
    """
    try:
        from app.services.webhooks import notify_unmatched

        notify_unmatched(db, trigger=trigger)
    except Exception:  # notifications must never break the read
        logger.exception("failed to notify unmatched media")


def refresh_fntv(
    db: Session,
    *,
    trigger: str = "manual",
    force: bool = False,
    run_matching: bool = True,
) -> dict[str, Any]:
    """Ingest the fnTV database into the local mirror.

    ``trigger`` is only used for bookkeeping ("manual", "scheduled", "startup").
    Raises :class:`app.fntv.FnTvError` when the database cannot be read and
    :class:`RefreshBusy` when a concurrent read is in progress.
    """
    path = fntv_db_path(db)
    signature = database_signature(path)
    previous = get_setting(db, SIGNATURE_KEY)

    if not force and previous and previous == signature:
        state = last_state(db)
        return {
            "ok": True,
            "changed": False,
            "skipped_reason": "unchanged",
            "path": str(path),
            "trigger": trigger,
            **state,
        }

    if not _LOCK.acquire(blocking=False):
        raise RefreshBusy("已有飞牛数据读取任务正在运行，请稍后再试")

    started = time.monotonic()
    try:
        threshold = get_float(db, "sync.watched_threshold", 80.0)
        snapshot = read_snapshot(path, watched_threshold=threshold)
        result = ingest_snapshot(db, snapshot)
        db.commit()
        match_stats = ensure_matches(db) if run_matching else None
        summary = _summary_payload(result, snapshot, match_stats)
        _remember(db, signature=signature, summary=summary, trigger=trigger)
        _notify_unmatched(db, trigger)
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "fnTV refresh (%s): plays=%s created=%s updated=%s in %sms",
            trigger,
            summary["plays"],
            summary["created"],
            summary["updated"],
            duration_ms,
        )
        return {
            "ok": True,
            "changed": True,
            "skipped_reason": None,
            "path": str(path),
            "trigger": trigger,
            "duration_ms": duration_ms,
            "snapshot": summary,
            "matching": match_stats,
            "last_refresh_at": get_setting(db, LAST_AT_KEY),
            "last_refresh_summary": summary,
            "last_refresh_error": None,
        }
    except FnTvError as exc:
        # Keep the previous signature so the next cycle retries automatically
        # once the database is mounted/readable again.
        set_setting(db, LAST_ERROR_KEY, str(exc))
        db.commit()
        logger.warning("fnTV refresh failed: %s", exc)
        raise
    except Exception as exc:  # pragma: no cover - defensive bookkeeping
        db.rollback()
        set_setting(db, LAST_ERROR_KEY, f"读取飞牛数据库失败: {exc}")
        db.commit()
        logger.exception("fnTV refresh crashed")
        raise
    finally:
        _LOCK.release()


def auto_refresh_enabled(db: Session) -> bool:
    from app.services.settings_service import get_bool

    return get_bool(db, "sync.ingest_enabled", True)
