"""Local mirror of the Trakt watched history.

The sync feature copies fnTV -> Trakt.  This module is the other direction:
it pulls the complete Trakt history into ``trakt_history`` and optionally
backfills matching local ``play_record`` rows.  Pulling history never touches
play records; applying a backfill always creates a database backup first.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.fntv.reader import read_library
from app.db.models import (
    AppUser,
    MediaItem,
    PlayRecord,
    Setting,
    SyncRecord,
    TraktAccount,
    TraktHistory,
)
from app.services.credentials import bundle_for_account
from app.services.matching import normalize_title
from app.services.settings_service import fntv_db_path, set_setting
from app.trakt.auth import ensure_access_token
from app.trakt.client import TraktAuthError, TraktClient, TraktError
from app.utils.time import to_iso_z, utcnow

logger = logging.getLogger(__name__)

BACKFILL_LOCK = threading.Lock()
MAX_PAGES = 100
PAGE_SIZE = 100


def _parse_watched_at(value: Any) -> datetime:
    if not value:
        return utcnow()
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return utcnow()
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass
class LibraryEntry:
    guid: str
    fn_type: str
    title: str
    show_title: str | None
    show_guid: str | None
    season_number: int | None
    episode_number: int | None
    tmdb_id: int | None
    imdb_id: str | None
    episode_imdb_id: str | None
    runtime_minutes: int | None
    year: int | None


@dataclass
class LibraryIndex:
    movies_tmdb: dict[int, LibraryEntry] = field(default_factory=dict)
    movies_imdb: dict[str, LibraryEntry] = field(default_factory=dict)
    movies_title: dict[tuple[str, int | None], LibraryEntry] = field(default_factory=dict)
    episodes_show_tmdb: dict[tuple[int, int, int], LibraryEntry] = field(default_factory=dict)
    episodes_show_imdb: dict[tuple[str, int, int], LibraryEntry] = field(default_factory=dict)
    episodes_imdb: dict[str, LibraryEntry] = field(default_factory=dict)
    episodes_title: dict[tuple[str, int, int], LibraryEntry] = field(default_factory=dict)
    by_guid: dict[str, LibraryEntry] = field(default_factory=dict)


def _entry_from_media(item: MediaItem) -> LibraryEntry:
    return LibraryEntry(
        guid=item.fn_guid,
        fn_type=item.fn_type,
        title=item.title,
        show_title=item.show_title,
        show_guid=item.show_guid,
        season_number=item.season_number,
        episode_number=item.episode_number,
        tmdb_id=item.tmdb_id,
        imdb_id=item.imdb_id,
        episode_imdb_id=item.episode_imdb_id,
        runtime_minutes=item.runtime_minutes,
        year=item.year,
    )


def _entry_from_row(row: dict[str, Any]) -> LibraryEntry:
    return LibraryEntry(
        guid=str(row["guid"]),
        fn_type=str(row["fn_type"]),
        title=str(row.get("title") or ""),
        show_title=row.get("show_title"),
        show_guid=row.get("show_guid"),
        season_number=row.get("season_number"),
        episode_number=row.get("episode_number"),
        tmdb_id=row.get("tmdb_id"),
        imdb_id=row.get("imdb_id"),
        episode_imdb_id=row.get("episode_imdb_id"),
        runtime_minutes=row.get("runtime_minutes"),
        year=row.get("year"),
    )


def _index_add(index: LibraryIndex, item: LibraryEntry) -> None:
    index.by_guid.setdefault(item.guid, item)
    if item.fn_type == "Movie":
        if item.tmdb_id:
            index.movies_tmdb.setdefault(int(item.tmdb_id), item)
        if item.imdb_id:
            index.movies_imdb.setdefault(item.imdb_id, item)
        key = (normalize_title(item.title), item.year)
        index.movies_title.setdefault(key, item)
        index.movies_title.setdefault((normalize_title(item.title), None), item)
    else:
        season = int(item.season_number or 0)
        number = int(item.episode_number or 0)
        if not season or not number:
            return
        if item.tmdb_id:
            index.episodes_show_tmdb.setdefault((int(item.tmdb_id), season, number), item)
        if item.imdb_id:
            index.episodes_show_imdb.setdefault((item.imdb_id, season, number), item)
        if item.episode_imdb_id:
            index.episodes_imdb.setdefault(item.episode_imdb_id, item)
        title = normalize_title(item.show_title or item.title)
        index.episodes_title.setdefault((title, season, number), item)


def build_library_index(db: Session) -> LibraryIndex:
    index = LibraryIndex()
    seen: set[str] = set()
    for item in db.scalars(select(MediaItem).where(MediaItem.fn_type.in_(["Movie", "Episode"]))).all():
        entry = _entry_from_media(item)
        if entry.guid not in seen:
            seen.add(entry.guid)
            _index_add(index, entry)
    # The local MediaItem table only contains media that have play records.
    # Read the full fnTV item table so "in library but never played" can be
    # distinguished from "not in library".
    try:
        for row in read_library(fntv_db_path(db)):
            entry = _entry_from_row(row)
            if entry.guid not in seen:
                seen.add(entry.guid)
                _index_add(index, entry)
    except Exception as exc:
        logger.warning("could not read full fnTV library: %s", exc)
    return index


def _movie_from_raw(raw: dict[str, Any], index: LibraryIndex) -> LibraryEntry | None:
    movie = raw.get("movie") or {}
    ids = movie.get("ids") or {}
    if ids.get("tmdb"):
        found = index.movies_tmdb.get(int(ids["tmdb"]))
        if found:
            return found
    if ids.get("imdb"):
        found = index.movies_imdb.get(str(ids["imdb"]))
        if found:
            return found
    title = normalize_title(movie.get("title"))
    year = _int(movie.get("year"))
    return index.movies_title.get((title, year)) or index.movies_title.get((title, None))


def _episode_from_raw(raw: dict[str, Any], index: LibraryIndex) -> LibraryEntry | None:
    episode = raw.get("episode") or {}
    show = raw.get("show") or {}
    season = _int(episode.get("season")) or 0
    number = _int(episode.get("number")) or 0
    if not season or not number:
        return None
    show_ids = show.get("ids") or {}
    episode_ids = episode.get("ids") or {}
    if show_ids.get("tmdb"):
        found = index.episodes_show_tmdb.get((int(show_ids["tmdb"]), season, number))
        if found:
            return found
    if show_ids.get("imdb"):
        found = index.episodes_show_imdb.get((str(show_ids["imdb"]), season, number))
        if found:
            return found
    if episode_ids.get("imdb"):
        found = index.episodes_imdb.get(str(episode_ids["imdb"]))
        if found:
            return found
    title = normalize_title(show.get("title") or episode.get("title"))
    return index.episodes_title.get((title, season, number))


def _record_values(raw: dict[str, Any], account_id: int) -> dict[str, Any] | None:
    history_id = _int(raw.get("id"))
    kind = raw.get("type")
    if not history_id or kind not in {"movie", "episode"}:
        return None
    watched_at = _parse_watched_at(raw.get("watched_at"))
    if kind == "movie":
        movie = raw.get("movie") or {}
        ids = movie.get("ids") or {}
        return {
            "trakt_account_id": account_id,
            "trakt_history_id": history_id,
            "history_type": "movie",
            "action": str(raw.get("action") or "watch"),
            "watched_at": watched_at,
            "title": str(movie.get("title") or "未知电影"),
            "show_title": None,
            "year": _int(movie.get("year")),
            "season_number": None,
            "episode_number": None,
            "runtime_minutes": _int(movie.get("runtime")),
            "trakt_movie_id": _int(ids.get("trakt")),
            "trakt_show_id": None,
            "trakt_episode_id": None,
            "tmdb_id": _int(ids.get("tmdb")),
            "imdb_id": _str(ids.get("imdb")),
            "show_tmdb_id": None,
            "show_imdb_id": None,
            "raw_json": raw,
        }
    episode = raw.get("episode") or {}
    show = raw.get("show") or {}
    show_ids = show.get("ids") or {}
    episode_ids = episode.get("ids") or {}
    season = _int(episode.get("season")) or 0
    number = _int(episode.get("number")) or 0
    return {
        "trakt_account_id": account_id,
        "trakt_history_id": history_id,
        "history_type": "episode",
        "action": str(raw.get("action") or "watch"),
        "watched_at": watched_at,
        "title": str(episode.get("title") or f"S{season:02d}E{number:02d}"),
        "show_title": str(show.get("title") or ""),
        "year": _int(show.get("year")),
        "season_number": season or None,
        "episode_number": number or None,
        "runtime_minutes": _int(episode.get("runtime")),
        "trakt_movie_id": None,
        "trakt_show_id": _int(show_ids.get("trakt")),
        "trakt_episode_id": _int(episode_ids.get("trakt")),
        "tmdb_id": _int(episode_ids.get("tmdb")),
        "imdb_id": _str(episode_ids.get("imdb")),
        "show_tmdb_id": _int(show_ids.get("tmdb")),
        "show_imdb_id": _str(show_ids.get("imdb")),
        "raw_json": raw,
    }


def _account_user(db: Session, account: TraktAccount) -> AppUser | None:
    return db.get(AppUser, account.app_user_id)


def pull_history(db: Session, account: TraktAccount, max_pages: int = MAX_PAGES) -> dict[str, Any]:
    """Fetch all pages of Trakt history and upsert them locally."""
    bundle = bundle_for_account(db, account)
    if not bundle.client_id:
        raise TraktError("尚未配置 Trakt 应用凭据")
    token = ensure_access_token(db, account)

    fetched = stored = pages = 0
    total = 0
    with TraktClient(bundle.client_id, bundle.client_secret) as client:
        page = 1
        while page <= max_pages:
            items, page_count, item_count = client.history_page(token, page=page, limit=PAGE_SIZE)
            pages = max(pages, page_count)
            total = max(total, item_count)
            for raw in items:
                values = _record_values(raw, account.id)
                if values is None:
                    continue
                fetched += 1
                row = db.scalar(
                    select(TraktHistory).where(
                        TraktHistory.trakt_account_id == account.id,
                        TraktHistory.trakt_history_id == values["trakt_history_id"],
                    )
                )
                if row is None:
                    row = TraktHistory(**values)
                    db.add(row)
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
                stored += 1
            db.commit()
            if page >= page_count:
                break
            page += 1

    matched = match_history(db, account)
    set_setting(db, "trakt.history.last_pull_at", to_iso_z(utcnow()))
    set_setting(db, "trakt.history.last_pull_count", str(stored))
    db.commit()
    return {
        "fetched": fetched,
        "stored": stored,
        "pages": pages,
        "trakt_total": total,
        "matched": matched["matched"],
        "library_only": matched["library_only"],
        "not_in_library": matched["not_in_library"],
        "last_pull_at": to_iso_z(utcnow()),
    }


def _local_play_map(db: Session, account: TraktAccount) -> dict[str, PlayRecord]:
    user = _account_user(db, account)
    if user is None or not user.fn_user_guid:
        return {}
    rows = db.scalars(
        select(PlayRecord).where(PlayRecord.fn_user_guid == user.fn_user_guid)
    ).all()
    return {row.fn_item_guid: row for row in rows}


def match_history(db: Session, account: TraktAccount) -> dict[str, int]:
    index = build_library_index(db)
    plays = _local_play_map(db, account)
    counts = {"matched": 0, "library_only": 0, "not_in_library": 0}
    rows = db.scalars(
        select(TraktHistory).where(TraktHistory.trakt_account_id == account.id)
    ).all()
    for row in rows:
        raw = row.raw_json or {}
        media = (
            _movie_from_raw(raw, index)
            if row.history_type == "movie"
            else _episode_from_raw(raw, index)
        )
        if media is None:
            row.media_guid = None
            row.play_id = None
            row.match_status = "not_in_library"
        else:
            row.media_guid = media.guid
            play = plays.get(media.guid)
            if play is None:
                row.play_id = None
                row.match_status = "library_only"
            else:
                row.play_id = play.id
                row.match_status = "matched"
        counts[row.match_status] = counts.get(row.match_status, 0) + 1
    db.commit()
    return counts


def _plan_rows(db: Session, account: TraktAccount) -> list[dict[str, Any]]:
    user = _account_user(db, account)
    can_create = bool(user and user.fn_user_guid)
    plays = _local_play_map(db, account)
    sync_map: dict[int, SyncRecord] = {}
    if plays:
        sync_map = {
            row.play_id: row
            for row in db.scalars(
                select(SyncRecord).where(
                    SyncRecord.trakt_account_id == account.id,
                    SyncRecord.play_id.in_([p.id for p in plays.values()]),
                )
            ).all()
        }
    histories = db.scalars(
        select(TraktHistory)
        .where(TraktHistory.trakt_account_id == account.id)
        .order_by(TraktHistory.watched_at.desc())
    ).all()
    plan: list[dict[str, Any]] = []
    for history in histories:
        play = plays.get(history.media_guid) if history.media_guid else None
        if history.match_status != "matched" or play is None:
            if history.match_status == "library_only" and can_create:
                state = "create"
            elif history.match_status == "library_only":
                state = "library_only"
            else:
                state = "not_in_library"
        else:
            sync = sync_map.get(play.id)
            already = bool(
                play.completed
                and play.watched
                and (play.progress_percent or 0) >= 100
                and sync is not None
                and sync.status == "success"
            )
            state = "already" if already else "update"
        plan.append(
            {
                "history_id": history.id,
                "trakt_history_id": history.trakt_history_id,
                "type": history.history_type,
                "title": history.title,
                "show_title": history.show_title,
                "season": history.season_number,
                "episode": history.episode_number,
                "watched_at": to_iso_z(history.watched_at),
                "match_status": history.match_status,
                "state": state,
                "media_guid": history.media_guid,
                "play_id": play.id if play else None,
                "current_progress": round(play.progress_percent or 0, 1) if play else None,
                "current_completed": bool(play.completed) if play else False,
                "runtime_minutes": history.runtime_minutes,
            }
        )
    return plan


def preview_backfill(db: Session, account: TraktAccount) -> dict[str, Any]:
    match_history(db, account)
    plan = _plan_rows(db, account)
    summary = {
        "total": len(plan),
        "update": sum(1 for row in plan if row["state"] == "update"),
        "create": sum(1 for row in plan if row["state"] == "create"),
        "already": sum(1 for row in plan if row["state"] == "already"),
        "library_only": sum(1 for row in plan if row["state"] == "library_only"),
        "not_in_library": sum(1 for row in plan if row["state"] == "not_in_library"),
    }
    return {
        "summary": summary,
        "items": [row for row in plan if row["state"] in {"update", "create"}][:20],
        "all_items": plan[:20],
        "backup_dir": str(settings.data_dir / "backups"),
        "last_pull_at": (db.get(Setting, "trakt.history.last_pull_at").value
        if db.get(Setting, "trakt.history.last_pull_at")
        else None),
        "can_apply": summary["update"] + summary["create"] > 0,
    }


def database_backup() -> Path:
    """Consistent SQLite backup before a destructive backfill."""
    source_path = settings.data_dir / "fn2trakt.db"
    if not source_path.exists():
        raise TraktError("本地数据库不存在，无法备份")
    backup_dir = settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    destination = backup_dir / f"fn2trakt-{stamp}-before-backfill.db"
    suffix = 1
    while destination.exists():
        destination = backup_dir / f"fn2trakt-{stamp}-before-backfill-{suffix}.db"
        suffix += 1
    source = sqlite3.connect(source_path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return destination


def apply_backfill(db: Session, account: TraktAccount) -> dict[str, Any]:
    if not BACKFILL_LOCK.acquire(blocking=False):
        raise TraktError("已有回填任务正在执行，请稍后再试")
    try:
        plan = _plan_rows(db, account)
        targets = [row for row in plan if row["state"] in {"update", "create"}]
        if not targets:
            return {
                "updated": 0,
                "created": 0,
                "skipped": len(plan),
                "backup_path": None,
                "message": "没有需要回填的记录",
            }

        user = _account_user(db, account)
        if user is None or not user.fn_user_guid:
            raise TraktError("当前 Trakt 账号没有绑定飞牛用户，无法写入本地播放记录")

        backup = database_backup()
        index = build_library_index(db)
        updated = created = 0
        for item in targets:
            history = db.get(TraktHistory, item["history_id"])
            if history is None:
                continue
            watched_at = history.watched_at or utcnow()
            play: PlayRecord | None = None
            if item["state"] == "update":
                play = db.get(PlayRecord, item["play_id"]) if item["play_id"] else None
            else:
                entry = index.by_guid.get(history.media_guid or "")
                if entry is None:
                    continue
                media = db.get(MediaItem, entry.guid)
                if media is None:
                    media = MediaItem(
                        fn_guid=entry.guid,
                        fn_type=entry.fn_type,
                        title=entry.title,
                    )
                    db.add(media)
                media.fn_type = entry.fn_type
                media.title = entry.title
                media.original_title = entry.show_title if entry.fn_type == "Episode" else entry.title
                media.show_guid = entry.show_guid
                media.show_title = entry.show_title
                media.season_number = entry.season_number
                media.episode_number = entry.episode_number
                media.year = entry.year
                media.tmdb_id = entry.tmdb_id
                media.imdb_id = entry.imdb_id
                media.episode_imdb_id = entry.episode_imdb_id
                media.runtime_minutes = entry.runtime_minutes
                db.flush()
                play = db.scalar(
                    select(PlayRecord).where(
                        PlayRecord.fn_item_guid == entry.guid,
                        PlayRecord.fn_user_guid == user.fn_user_guid,
                    )
                )
                if play is None:
                    play = PlayRecord(
                        fn_item_guid=entry.guid,
                        fn_user_guid=user.fn_user_guid,
                        play_type="trakt_backfill",
                    )
                    db.add(play)
                    db.flush()
                    created += 1
            if play is None:
                continue
            history.play_id = play.id
            history.match_status = "matched"
            runtime_seconds = (history.runtime_minutes or 0) * 60 or play.runtime_seconds
            play.watched = True
            play.completed = True
            play.progress_percent = 100.0
            if runtime_seconds:
                play.runtime_seconds = runtime_seconds
                play.position_seconds = runtime_seconds
            play.fn_update_time = watched_at
            if play.fn_create_time is None:
                play.fn_create_time = watched_at
            raw = dict(play.raw_json or {})
            raw["trakt_backfill"] = {
                "history_id": history.trakt_history_id,
                "watched_at": to_iso_z(watched_at),
                "backup": str(backup),
            }
            play.raw_json = raw

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
            record.action = "backfill"
            record.watched_at = watched_at
            record.trakt_history_id = history.trakt_history_id
            record.response_json = {"backfilled": True, "history_id": history.trakt_history_id}
            record.error = None
            record.updated_at = utcnow()
            if item["state"] == "update":
                updated += 1

        db.commit()
        set_setting(db, "trakt.backfill.last_at", to_iso_z(utcnow()))
        set_setting(db, "trakt.backfill.last_backup", str(backup))
        set_setting(db, "trakt.backfill.last_updated", str(updated))
        set_setting(db, "trakt.backfill.last_created", str(created))
        db.commit()
        logger.info("trakt backfill updated=%s created=%s backup=%s", updated, created, backup)
        try:
            from app.services.webhooks import emit_event

            emit_event(
                db,
                "backfill.completed",
                {
                    "updated": updated,
                    "created": created,
                    "skipped": len(plan) - updated - created,
                    "not_in_library": sum(1 for row in plan if row["state"] == "not_in_library"),
                    "library_only": sum(1 for row in plan if row["state"] == "library_only"),
                    "backup_path": str(backup),
                    "trakt_user": account.trakt_username,
                },
            )
        except Exception:
            logger.exception("failed to emit backfill webhook")
        return {
            "updated": updated,
            "created": created,
            "skipped": len(plan) - updated - created,
            "backup_path": str(backup),
            "message": f"已更新 {updated} 条、新建 {created} 条本地观看记录",
        }
    finally:
        BACKFILL_LOCK.release()


def history_summary(db: Session, account: TraktAccount) -> dict[str, Any]:
    rows = db.scalars(
        select(TraktHistory).where(TraktHistory.trakt_account_id == account.id)
    ).all()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.match_status] = counts.get(row.match_status, 0) + 1
    last_pull = db.get(Setting, "trakt.history.last_pull_at")
    last_backfill = db.get(Setting, "trakt.backfill.last_at")
    last_backup = db.get(Setting, "trakt.backfill.last_backup")
    last_updated = db.get(Setting, "trakt.backfill.last_updated")
    return {
        "total": len(rows),
        "matched": counts.get("matched", 0),
        "library_only": counts.get("library_only", 0),
        "not_in_library": counts.get("not_in_library", 0),
        "last_pull_at": last_pull.value if last_pull else None,
        "last_backfill_at": last_backfill.value if last_backfill else None,
        "last_backup": last_backup.value if last_backup else None,
        "last_updated": int(last_updated.value) if last_updated and last_updated.value.isdigit() else 0,
        "backup_dir": str(settings.data_dir / "backups"),
    }


def history_public(row: TraktHistory, local_completed: bool = False) -> dict[str, Any]:
    return {
        "id": row.id,
        "trakt_id": row.trakt_history_id,
        "type": row.history_type,
        "action": row.action,
        "watched_at": to_iso_z(row.watched_at),
        "title": row.title,
        "show_title": row.show_title,
        "year": row.year,
        "season": row.season_number,
        "episode": row.episode_number,
        "runtime_minutes": row.runtime_minutes,
        "ids": {
            "trakt": row.trakt_movie_id if row.history_type == "movie" else row.trakt_show_id,
            "trakt_episode": row.trakt_episode_id,
            "tmdb": row.tmdb_id,
            "imdb": row.imdb_id,
            "show_tmdb": row.show_tmdb_id,
            "show_imdb": row.show_imdb_id,
        },
        "match_status": row.match_status,
        "in_library": row.match_status in {"matched", "library_only"},
        "media_guid": row.media_guid,
        "play_id": row.play_id,
        "local_completed": local_completed,
    }


def history_stats(db: Session, account: TraktAccount) -> dict[str, Any]:
    rows = db.scalars(
        select(TraktHistory).where(TraktHistory.trakt_account_id == account.id)
    ).all()
    movies = [row for row in rows if row.history_type == "movie"]
    episodes = [row for row in rows if row.history_type == "episode"]
    shows = {(row.show_tmdb_id or row.show_imdb_id or row.show_title) for row in episodes}
    minutes = sum((row.runtime_minutes or 0) for row in rows)
    by_month: dict[str, int] = {}
    for row in rows:
        key = row.watched_at.strftime("%Y-%m") if row.watched_at else "unknown"
        by_month[key] = by_month.get(key, 0) + 1
    top: dict[str, int] = {}
    for row in episodes:
        name = row.show_title or row.title
        top[name] = top.get(name, 0) + 1
    first = min((row.watched_at for row in rows if row.watched_at), default=None)
    last = max((row.watched_at for row in rows if row.watched_at), default=None)
    return {
        "total": len(rows),
        "movies": len(movies),
        "episodes": len(episodes),
        "shows": len([s for s in shows if s]),
        "minutes": minutes,
        "hours": round(minutes / 60, 1),
        "first_watched_at": to_iso_z(first),
        "last_watched_at": to_iso_z(last),
        "by_month": [{"month": key, "count": value} for key, value in sorted(by_month.items())],
        "top_shows": [
            {"title": title, "count": count}
            for title, count in sorted(top.items(), key=lambda item: item[1], reverse=True)[:10]
        ],
        "matched": sum(1 for row in rows if row.match_status == "matched"),
        "library_only": sum(1 for row in rows if row.match_status == "library_only"),
        "not_in_library": sum(1 for row in rows if row.match_status == "not_in_library"),
    }
