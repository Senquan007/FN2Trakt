"""Dangerous Trakt -> fnTV write-back.

The normal sync path only reads ``trimmedia.db``.  This module is the one
explicit exception: an administrator can write matched Trakt history into
fnTV's ``item_user_play`` table.  Every write is preceded by a consistent
SQLite backup stored in the application data directory.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AppUser, PlayRecord, Setting, SyncRecord, TraktAccount, TraktHistory
from app.fntv import FnTvError, read_snapshot
from app.fntv.conn import open_readonly
from app.services.ingest import ingest_snapshot
from app.services.settings_service import fntv_db_path, get_float, set_setting
from app.services.trakt_history import build_library_index, match_history
from app.utils.time import to_iso_z, utcnow

logger = logging.getLogger(__name__)

WRITEBACK_LOCK = threading.Lock()
BACKUP_PREFIX = "fntv-"
BACKUP_SUFFIX = ".db"
# SyncRecord.action marker for "written into fnTV" (upload rows use "history").
WRITEBACK_ACTION = "fntv_writeback"


class FnTvWritebackError(RuntimeError):
    """A user-facing write-back error."""


def _backup_dir() -> Path:
    path = settings.data_dir / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _stamp() -> str:
    return utcnow().strftime("%Y%m%d-%H%M%S")


def _backup_path(reason: str) -> Path:
    directory = _backup_dir()
    destination = directory / f"{BACKUP_PREFIX}{_stamp()}-{reason}{BACKUP_SUFFIX}"
    suffix = 1
    while destination.exists():
        destination = directory / f"{BACKUP_PREFIX}{_stamp()}-{reason}-{suffix}{BACKUP_SUFFIX}"
        suffix += 1
    return destination


def _epoch_ms(value: datetime | None) -> int:
    if value is None:
        return int(utcnow().replace(tzinfo=timezone.utc).timestamp() * 1000)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


def _chunks(values: list[str], size: int = 400):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return (
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        is not None
    )


def _connect_read(path: Path) -> sqlite3.Connection:
    """Read-only connection that survives transient fnTV database hiccups."""
    return open_readonly(path, timeout=30.0)


def _connect_write(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _target_user(db: Session, account: TraktAccount) -> AppUser:
    user = db.get(AppUser, account.app_user_id)
    if user is None or not user.fn_user_guid:
        raise FnTvWritebackError("当前 Trakt 账号没有绑定飞牛用户")
    return user


def _fn_user_name(con: sqlite3.Connection, guid: str) -> str | None:
    if not _table_exists(con, "user"):
        return None
    row = con.execute("SELECT username FROM user WHERE guid=?", (guid,)).fetchone()
    return str(row["username"]) if row else None


def _existing_plays(path: Path, user_guid: str, guids: list[str]) -> dict[str, sqlite3.Row]:
    if not guids:
        return {}
    con = _connect_read(path)
    try:
        if not _table_exists(con, "item_user_play"):
            raise FnTvWritebackError("飞牛数据库缺少 item_user_play 表")
        result: dict[str, sqlite3.Row] = {}
        for chunk in _chunks(guids):
            placeholders = ",".join("?" for _ in chunk)
            rows = con.execute(
                f"SELECT item_guid, ts, watched, media_guid FROM item_user_play "
                f"WHERE user_guid=? AND item_guid IN ({placeholders})",
                (user_guid, *chunk),
            ).fetchall()
            for row in rows:
                result[str(row["item_guid"])] = row
        return result
    finally:
        con.close()


def _latest_histories(db: Session, account: TraktAccount) -> list[TraktHistory]:
    rows = db.scalars(
        select(TraktHistory)
        .where(
            TraktHistory.trakt_account_id == account.id,
            TraktHistory.media_guid.is_not(None),
            TraktHistory.match_status.in_(["matched", "library_only"]),
        )
        .order_by(TraktHistory.watched_at.desc())
    ).all()
    # One physical fnTV play row per item.  The latest Trakt watch wins.
    latest: dict[str, TraktHistory] = {}
    for row in rows:
        if row.media_guid and row.media_guid not in latest:
            latest[row.media_guid] = row
    return list(latest.values())


def _writable(path: Path) -> tuple[bool, str | None]:
    if not path.exists():
        return False, f"飞牛数据库不存在: {path}"
    if not path.is_file():
        return False, f"飞牛数据库路径不是文件: {path}"
    if not os.access(path, os.R_OK):
        return False, "当前容器用户没有读取飞牛数据库的权限"
    if not os.access(path, os.W_OK):
        return False, "当前容器用户没有写入飞牛数据库的权限"
    if not os.access(path.parent, os.W_OK):
        return False, "当前容器用户没有写入飞牛数据库目录的权限（WAL 需要 -shm）"
    return True, None


def _history_item(row: TraktHistory, entry) -> dict[str, Any]:
    return {
        "history_id": row.id,
        "trakt_history_id": row.trakt_history_id,
        "media_guid": row.media_guid,
        "type": "episode" if row.history_type == "episode" else "movie",
        "title": row.title,
        "show_title": row.show_title,
        "season": row.season_number,
        "episode": row.episode_number,
        "watched_at": to_iso_z(row.watched_at),
        "runtime_minutes": row.runtime_minutes or entry.runtime_minutes,
        "fn_type": entry.fn_type,
    }


def _match_counts(db: Session, account: TraktAccount) -> dict[str, int]:
    rows = db.execute(
        select(TraktHistory.match_status, func.count(TraktHistory.id))
        .where(TraktHistory.trakt_account_id == account.id)
        .group_by(TraktHistory.match_status)
    ).all()
    counts = {"matched": 0, "library_only": 0, "not_in_library": 0}
    for status, count in rows:
        counts[status or "not_in_library"] = count
    return counts


def _skipped_item(row: TraktHistory, reason: str = "不在飞牛媒体库") -> dict[str, Any]:
    return {
        "history_id": row.id,
        "type": "episode" if row.history_type == "episode" else "movie",
        "title": row.title,
        "show_title": row.show_title,
        "season": row.season_number,
        "episode": row.episode_number,
        "watched_at": to_iso_z(row.watched_at),
        "reason": reason,
    }


def _playable_items(path: Path, guids: list[str]) -> set[str]:
    """Items that have at least one playable media file in fnTV.

    ``item_user_play.media_guid`` should point at a real file; without it fnTV
    usually shows nothing, so such history rows are reported as skipped
    instead of silently written as ghost records.
    """
    unique = sorted({guid for guid in guids if guid})
    if not unique:
        return set()
    try:
        con = _connect_read(path)
    except (sqlite3.Error, FnTvError):
        # A read failure here must never abort the whole preview (this used to
        # surface as an HTTP 500).  Treating every item as playable keeps the
        # plan conservative: the real write still validates each row.
        logger.warning("could not open fnTV database, assuming every item is playable", exc_info=True)
        return set(unique)
    try:
        if not _table_exists(con, "item_media"):
            return set(unique)
        found: set[str] = set()
        for chunk in _chunks(unique):
            placeholders = ",".join("?" for _ in chunk)
            rows = con.execute(
                f"SELECT DISTINCT item_guid FROM item_media "
                f"WHERE COALESCE(can_play, 1)=1 AND item_guid IN ({placeholders})",
                chunk,
            ).fetchall()
            found.update(str(row["item_guid"]) for row in rows)
        return found
    except sqlite3.Error:
        logger.warning("could not read item_media, assuming every item is playable", exc_info=True)
        return set(unique)
    finally:
        con.close()


def written_history_ids(db: Session, account: TraktAccount) -> dict[int, datetime]:
    """Trakt history rows already written into fnTV: ``trakt_history_id -> when``."""
    rows = db.scalars(
        select(SyncRecord).where(
            SyncRecord.trakt_account_id == account.id,
            SyncRecord.action == WRITEBACK_ACTION,
            SyncRecord.status == "success",
        )
    ).all()
    return {row.trakt_history_id: row.updated_at for row in rows if row.trakt_history_id}


def preview_writeback(
    db: Session, account: TraktAccount, *, pull: bool = False, include_written: bool = False
) -> dict[str, Any]:
    """Return a dry-run plan for writing Trakt history into fnTV.

    ``pull=True`` first refreshes the local Trakt history mirror from the Trakt
    API.  Without that step the preview is based on whatever history was
    fetched last, which is why the two "回填/写入" buttons used to be needed
    together.

    History that was already written is excluded (and counted in
    ``summary.already_written``) unless ``include_written`` is set, so a second
    run does not rewrite the same rows and the UI can show real progress.
    """
    pulled = None
    if pull:
        from app.services.trakt_history import pull_history

        # pull_history() already re-runs match_history() at the end.
        pulled = pull_history(db, account)
    else:
        match_history(db, account)

    target = _target_user(db, account)
    path = fntv_db_path(db)
    writable, reason = _writable(path)
    index = build_library_index(db)
    histories = _latest_histories(db, account)
    counts = _match_counts(db, account)
    history_total = sum(counts.values())
    written = written_history_ids(db, account)

    try:
        existing = _existing_plays(
            path,
            target.fn_user_guid,
            [row.media_guid for row in histories if row.media_guid],
        )
    except (sqlite3.Error, FnTvError, FnTvWritebackError) as exc:
        raise FnTvWritebackError(f"无法读取飞牛播放记录: {exc}") from exc

    # Validate the fnTV user on a best-effort basis; a missing user is almost
    # always a stale binding rather than something the write can fix.
    username = None
    try:
        con = _connect_read(path)
        try:
            username = _fn_user_name(con, target.fn_user_guid)
        finally:
            con.close()
    except (sqlite3.Error, FnTvError) as exc:
        if writable:
            logger.warning("could not read fnTV users: %s", exc)
    if username is None:
        writable = False
        reason = reason or "绑定的飞牛用户不存在"

    items: list[dict[str, Any]] = []
    orphans = 0
    resolved: list[tuple[TraktHistory, Any]] = []
    for row in histories:
        entry = index.by_guid.get(row.media_guid or "")
        if entry is None:
            orphans += 1
            continue
        resolved.append((row, entry))

    playable = _playable_items(path, [entry.guid for _row, entry in resolved])
    unplayable: list[dict[str, Any]] = []
    already: list[dict[str, Any]] = []
    for row, entry in resolved:
        if playable and entry.guid not in playable:
            unplayable.append(_skipped_item(row, "飞牛缺少可播放文件"))
            continue
        item = _history_item(row, entry)
        current = existing.get(entry.guid)
        item["state"] = "update" if current is not None else "create"
        item["current_ts"] = int(current["ts"] or 0) if current is not None else None
        item["current_watched"] = bool(current["watched"]) if current is not None else False
        item["written"] = bool(row.trakt_history_id) and row.trakt_history_id in written
        item["written_at"] = (
            to_iso_z(written[row.trakt_history_id])
            if row.trakt_history_id and row.trakt_history_id in written
            else None
        )
        if item["written"] and not include_written:
            already.append(item)
            continue
        items.append(item)

    skipped_rows = db.scalars(
        select(TraktHistory)
        .where(
            TraktHistory.trakt_account_id == account.id,
            TraktHistory.match_status == "not_in_library",
        )
        .order_by(TraktHistory.watched_at.desc())
        .limit(20)
    ).all()
    skipped_items = [_skipped_item(row) for row in skipped_rows] + unplayable[:20]

    summary = {
        "total": len(items),
        "update": sum(1 for item in items if item["state"] == "update"),
        "create": sum(1 for item in items if item["state"] == "create"),
        "already_written": len(already),
        "skipped": counts.get("not_in_library", 0) + orphans + len(unplayable),
        "matched": counts.get("matched", 0),
        "library_only": counts.get("library_only", 0),
        "not_in_library": counts.get("not_in_library", 0),
        "history_total": history_total,
    }

    error = reason
    if not history_total:
        error = "本地还没有 Trakt 观看历史，请先点击「拉取 Trakt 历史」"
    elif not items and already:
        error = f"该账号的 {len(already)} 条 Trakt 历史已全部写入飞牛，无需重复写入"

    last = db.get(Setting, "fntv.writeback.last_at")
    last_backup = db.get(Setting, "fntv.writeback.last_backup")
    last_pull = db.get(Setting, "trakt.history.last_pull_at")
    return {
        "summary": summary,
        "items": items[:20],
        "written_items": already[:20],
        "skipped_items": skipped_items,
        "counts": counts,
        "pulled": pulled,
        "include_written": include_written,
        "backup_dir": str(_backup_dir()),
        "target_user": {
            "guid": target.fn_user_guid,
            "username": username or target.username,
        },
        "writable": writable,
        "error": error,
        "can_apply": writable and bool(items),
        "last_writeback_at": last.value if last else None,
        "last_backup": last_backup.value if last_backup else None,
        "last_pull_at": last_pull.value if last_pull else None,
    }


def _pick_media(con: sqlite3.Connection, item_guid: str) -> dict[str, str | None]:
    if not _table_exists(con, "item_media"):
        return {}
    media = con.execute(
        "SELECT guid FROM item_media WHERE item_guid=? AND COALESCE(can_play, 1)=1 "
        "ORDER BY sort_num, create_time LIMIT 1",
        (item_guid,),
    ).fetchone()
    if media is None:
        return {}
    media_guid = str(media["guid"])
    result: dict[str, str | None] = {"media_guid": media_guid}
    if _table_exists(con, "media_stream"):
        rows = con.execute(
            'SELECT guid, codec_type FROM media_stream WHERE media_guid=? '
            'ORDER BY COALESCE(is_default, 0) DESC, "index" ASC',
            (media_guid,),
        ).fetchall()
        for row in rows:
            kind = str(row["codec_type"] or "").lower()
            key = {"video": "video_guid", "audio": "audio_guid", "subtitle": "subtitle_guid"}.get(kind)
            if key and key not in result:
                result[key] = str(row["guid"])
    return result


def _write_play(
    con: sqlite3.Connection,
    user_guid: str,
    entry,
    watched_at: datetime,
    runtime_seconds: int,
) -> str:
    current = con.execute(
        "SELECT item_guid FROM item_user_play WHERE item_guid=? AND user_guid=?",
        (entry.guid, user_guid),
    ).fetchone()
    media = _pick_media(con, entry.guid)
    timestamp = _epoch_ms(watched_at)
    if current is not None:
        con.execute(
            """
            UPDATE item_user_play
            SET ts = CASE WHEN ? > 0 THEN ? ELSE ts END,
                watched = 1,
                visible = 1,
                media_guid = COALESCE(media_guid, ?),
                video_guid = COALESCE(video_guid, ?),
                audio_guid = COALESCE(audio_guid, ?),
                subtitle_guid = COALESCE(subtitle_guid, ?),
                type = COALESCE(type, ?),
                create_time = COALESCE(create_time, ?),
                update_time = ?
            WHERE item_guid=? AND user_guid=?
            """,
            (
                runtime_seconds,
                runtime_seconds,
                media.get("media_guid"),
                media.get("video_guid"),
                media.get("audio_guid"),
                media.get("subtitle_guid"),
                entry.fn_type,
                timestamp,
                timestamp,
                entry.guid,
                user_guid,
            ),
        )
        return "updated"

    con.execute(
        """
        INSERT INTO item_user_play
        (item_guid, user_guid, ts, watched, media_guid, video_guid, audio_guid,
         subtitle_guid, type, visible, create_time, update_time)
        VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            entry.guid,
            user_guid,
            runtime_seconds,
            media.get("media_guid"),
            media.get("video_guid"),
            media.get("audio_guid"),
            media.get("subtitle_guid"),
            entry.fn_type,
            timestamp,
            timestamp,
        ),
    )
    return "created"


def backup_fntv(db: Session, reason: str = "before-writeback") -> Path:
    path = fntv_db_path(db)
    writable, error = _writable(path)
    if not writable:
        raise FnTvWritebackError(error or "飞牛数据库不可写")
    destination = _backup_path(reason)
    source = _connect_read(path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
        target.commit()
        # Make each backup a standalone .db file.  Without this, a WAL-mode
        # target can leave -wal/-shm next to the backup and a copied .db alone
        # would be incomplete.
        try:
            target.execute("PRAGMA journal_mode=DELETE")
            target.commit()
        except sqlite3.Error:
            logger.warning("could not checkpoint fnTV backup", exc_info=True)
    finally:
        target.close()
        source.close()
    return destination


def apply_writeback(
    db: Session,
    account: TraktAccount,
    *,
    expected_total: int | None = None,
    include_written: bool = False,
) -> dict[str, Any]:
    if not WRITEBACK_LOCK.acquire(blocking=False):
        raise FnTvWritebackError("已有飞牛写入任务正在执行，请稍后再试")
    try:
        match_history(db, account)
        target = _target_user(db, account)
        path = fntv_db_path(db)
        writable, error = _writable(path)
        if not writable:
            raise FnTvWritebackError(error or "飞牛数据库不可写")

        index = build_library_index(db)
        histories = _latest_histories(db, account)
        candidates = [(row, index.by_guid.get(row.media_guid or "")) for row in histories]
        candidates = [(row, entry) for row, entry in candidates if entry is not None]
        playable = _playable_items(path, [entry.guid for _row, entry in candidates])
        targets = [
            (row, entry)
            for row, entry in candidates
            if not playable or entry.guid in playable
        ]
        # Rows already written into fnTV are not rewritten: the history mirror
        # keeps them, so without this filter every run would redo everything.
        written = written_history_ids(db, account)
        already_written = 0
        if not include_written:
            kept = []
            for row, entry in targets:
                if row.trakt_history_id and row.trakt_history_id in written:
                    already_written += 1
                    continue
                kept.append((row, entry))
            targets = kept
        if expected_total is not None and expected_total != len(targets):
            # Second confirmation guard: the plan changed between preview and
            # apply (a new pull, a re-match, a deleted play...) so the admin
            # must look at the numbers again.
            raise FnTvWritebackError(
                f"待写入记录已从 {expected_total} 条变为 {len(targets)} 条，请重新预览后再确认"
            )
        if not targets:
            return {
                "updated": 0,
                "created": 0,
                "skipped": len(histories),
                "already_written": already_written,
                "backup_path": None,
                "message": (
                    f"{already_written} 条历史已写入过飞牛，没有新的记录需要写入"
                    if already_written
                    else "没有可写入飞牛的 Trakt 记录"
                ),
            }

        backup = backup_fntv(db)
        created = updated = 0
        con = _connect_write(path)
        try:
            con.execute("BEGIN IMMEDIATE")
            if not _table_exists(con, "item_user_play"):
                raise FnTvWritebackError("飞牛数据库缺少 item_user_play 表")
            if _fn_user_name(con, target.fn_user_guid) is None:
                raise FnTvWritebackError("绑定的飞牛用户不存在，无法写入")
            for history, entry in targets:
                runtime = int((history.runtime_minutes or entry.runtime_minutes or 0) * 60)
                result = _write_play(con, target.fn_user_guid, entry, history.watched_at, runtime)
                if result == "created":
                    created += 1
                else:
                    updated += 1
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

        # Keep the local mirror in sync and prevent the normal uploader from
        # re-posting exactly the history we just wrote into fnTV.
        local_warning = None
        try:
            snapshot = read_snapshot(path, watched_threshold=get_float(db, "sync.watched_threshold", 80.0))
            ingest_snapshot(db, snapshot)
            db.flush()
            for history, entry in targets:
                play = db.scalar(
                    select(PlayRecord).where(
                        PlayRecord.fn_item_guid == entry.guid,
                        PlayRecord.fn_user_guid == target.fn_user_guid,
                    )
                )
                if play is None:
                    continue
                history.play_id = play.id
                history.match_status = "matched"
                record = db.scalar(
                    select(SyncRecord).where(
                        SyncRecord.play_id == play.id,
                        SyncRecord.trakt_account_id == account.id,
                    )
                )
                if record is None:
                    record = SyncRecord(play_id=play.id, trakt_account_id=account.id)
                    db.add(record)
                record.status = "success"
                record.action = "fntv_writeback"
                record.watched_at = history.watched_at
                record.trakt_history_id = history.trakt_history_id
                record.response_json = {
                    "fntv_writeback": True,
                    "history_id": history.trakt_history_id,
                    "backup": str(backup),
                }
                record.error = None
                record.updated_at = utcnow()
            db.commit()
        except Exception as exc:
            db.rollback()
            local_warning = f"飞牛写入已完成，但本地记录刷新失败: {exc}"
            logger.exception("failed to refresh local mirror after fnTV writeback")

        counts = _match_counts(db, account)
        skipped = counts.get("not_in_library", 0) + max(0, len(histories) - len(targets))
        set_setting(db, "fntv.writeback.last_at", to_iso_z(utcnow()))
        set_setting(db, "fntv.writeback.last_backup", str(backup))
        set_setting(db, "fntv.writeback.last_created", str(created))
        set_setting(db, "fntv.writeback.last_updated", str(updated))
        db.commit()

        try:
            from app.services.webhooks import emit_event

            emit_event(
                db,
                "backfill.completed",
                {
                    "updated": updated,
                    "created": created,
                    "skipped": skipped,
                    "already_written": already_written,
                    "not_in_library": counts.get("not_in_library", 0),
                    "backup_path": str(backup),
                    "trakt_user": account.trakt_username,
                    "app_user": target.username,
                    "message": f"写入飞牛完成：更新 {updated} 条，新建 {created} 条",
                },
            )
        except Exception:  # notifications must never break the write
            logger.exception("failed to emit writeback webhook")

        message = f"已写入飞牛：更新 {updated} 条，新建 {created} 条"
        if already_written:
            message += f"，跳过已写入 {already_written} 条"
        if local_warning:
            message += f"；{local_warning}"
        return {
            "updated": updated,
            "created": created,
            "skipped": skipped,
            "already_written": already_written,
            "backup_path": str(backup),
            "target_user": {
                "guid": target.fn_user_guid,
                "username": target.username,
            },
            "message": message,
            "local_warning": local_warning,
        }
    finally:
        WRITEBACK_LOCK.release()


def list_backups() -> list[dict[str, Any]]:
    directory = _backup_dir()
    items: list[dict[str, Any]] = []
    for path in sorted(directory.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"), reverse=True):
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )
    return items


def _safe_backup(name: str) -> Path:
    if not name or Path(name).name != name or not name.startswith(BACKUP_PREFIX) or not name.endswith(BACKUP_SUFFIX):
        raise FnTvWritebackError("无效的备份文件名")
    path = (_backup_dir() / name).resolve()
    if path.parent != _backup_dir().resolve() or not path.is_file():
        raise FnTvWritebackError("备份文件不存在")
    return path


def restore_fntv(db: Session, name: str) -> dict[str, Any]:
    if not WRITEBACK_LOCK.acquire(blocking=False):
        raise FnTvWritebackError("已有飞牛写入任务正在执行，请稍后再试")
    try:
        backup = _safe_backup(name)
        target_path = fntv_db_path(db)
        writable, error = _writable(target_path)
        if not writable:
            raise FnTvWritebackError(error or "飞牛数据库不可写")

        safety = backup_fntv(db, reason="before-restore")
        source = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
        target = _connect_write(target_path)
        try:
            source.backup(target)
            target.commit()
            try:
                target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                logger.warning("wal checkpoint after restore failed", exc_info=True)
        except Exception:
            target.rollback()
            raise
        finally:
            target.close()
            source.close()

        set_setting(db, "fntv.restore.last_at", to_iso_z(utcnow()))
        set_setting(db, "fntv.restore.last_backup", str(backup))
        set_setting(db, "fntv.restore.last_safety", str(safety))
        db.commit()
        return {
            "restored": backup.name,
            "safety_backup": str(safety),
            "message": f"已从 {backup.name} 恢复飞牛数据库",
        }
    finally:
        WRITEBACK_LOCK.release()
