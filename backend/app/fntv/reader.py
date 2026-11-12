from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from app.fntv.models import (
    FnItemRow,
    FnTvError,
    FnUserRow,
    NormalizedPlay,
    Snapshot,
)
from app.utils.time import from_epoch_ms

EPISODE_TYPES = {"episode"}
MOVIE_TYPES = {"movie"}
SHOW_TYPES = {"tv", "show"}
SEASON_TYPES = {"season"}

_YEAR_RE = re.compile(r"(\d{4})")


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FnTvError(f"飞牛数据库不存在: {path}")
    if not path.is_file():
        raise FnTvError(f"飞牛数据库路径不是文件: {path}")
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error as exc:  # pragma: no cover - depends on host state
        raise FnTvError(f"无法打开飞牛数据库: {exc}") from exc
    con.row_factory = sqlite3.Row
    return con


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in con.execute(f"PRAGMA table_info('{table}')")]


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _pick(row: sqlite3.Row, names: tuple[str, ...]) -> Any:
    keys = row.keys()
    for name in names:
        if name in keys:
            return row[name]
    return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_year(*values: Any) -> int | None:
    for value in values:
        if not value:
            continue
        match = _YEAR_RE.search(str(value))
        if match:
            year = int(match.group(1))
            if 1880 <= year <= 2100:
                return year
    return None


def inspect_database(path: Path) -> dict[str, Any]:
    """Cheap structural probe used by the settings page."""
    try:
        con = _connect(path)
    except FnTvError as exc:
        return {
            "ok": False,
            "path": str(path),
            "tables": [],
            "missing_tables": ["item", "user", "item_user_play"],
            "counts": {},
            "error": str(exc),
        }
    try:
        tables = [
            row["name"]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ]
        required = {"item", "user", "item_user_play"}
        missing = sorted(required - set(tables))
        counts: dict[str, int] = {}
        for table in ("item", "user", "item_user_play"):
            if table in tables:
                counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        item_columns = _columns(con, "item") if "item" in tables else []
        play_columns = _columns(con, "item_user_play") if "item_user_play" in tables else []
        return {
            "ok": not missing,
            "path": str(path),
            "tables": tables,
            "missing_tables": missing,
            "counts": counts,
            "has_tmdb": "tmdb_id" in item_columns,
            "has_imdb": "imdb_id" in item_columns,
            "has_episode_imdb": "episode_imdb_id" in item_columns,
            "item_columns": item_columns,
            "play_columns": play_columns,
            "size_bytes": path.stat().st_size,
            "error": None if not missing else f"缺少数据表: {', '.join(missing)}",
        }
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "path": str(path),
            "tables": [],
            "missing_tables": ["item", "user", "item_user_play"],
            "counts": {},
            "error": f"读取数据库失败: {exc}",
        }
    finally:
        con.close()


def read_users(path: Path) -> list[FnUserRow]:
    con = _connect(path)
    try:
        if not _table_exists(con, "user"):
            return []
        columns = _columns(con, "user")
        last_login = "last_login_time" if "last_login_time" in columns else "NULL"
        rows = con.execute(
            f"SELECT guid, username, is_admin, status, {last_login} AS last_login_time FROM user ORDER BY username"
        ).fetchall()
        users: list[FnUserRow] = []
        for row in rows:
            guid = _clean_str(row["guid"])
            username = _clean_str(row["username"])
            if not guid or not username:
                continue
            if guid == "default-user-template":
                continue
            users.append(
                FnUserRow(
                    guid=guid,
                    username=username,
                    is_admin=bool(_to_int(row["is_admin"])),
                    status=_to_int(row["status"]) or 0,
                    last_login_time=from_epoch_ms(row["last_login_time"]),
                )
            )
        return users
    finally:
        con.close()


def _load_items(con: sqlite3.Connection) -> dict[str, FnItemRow]:
    if not _table_exists(con, "item"):
        raise FnTvError("飞牛数据库缺少 item 表")
    columns = set(_columns(con, "item"))
    wanted = [
        ("guid", "guid"),
        ("trim_id", "trim_id"),
        ("type", "type"),
        ("title", "title"),
        ("original_title", "original_title"),
        ("parent_guid", "parent_guid"),
        ("season_number", "season_number"),
        ("episode_number", "episode_number"),
        ("tmdb_id", "tmdb_id"),
        ("imdb_id", "imdb_id"),
        ("episode_imdb_id", "episode_imdb_id"),
        ("runtime", "runtime"),
        ("release_date", "release_date"),
        ("first_air_date", "first_air_date"),
        ("overview", "overview"),
    ]
    select_parts = [name if name in columns else f"NULL AS {alias}" for name, alias in wanted]
    sql = f"SELECT {', '.join(select_parts)} FROM item"
    items: dict[str, FnItemRow] = {}
    for row in con.execute(sql):
        guid = _clean_str(row["guid"])
        if not guid:
            continue
        items[guid] = FnItemRow(
            guid=guid,
            fn_type=_clean_str(row["type"]) or "Unknown",
            title=_clean_str(row["title"]) or guid,
            original_title=_clean_str(row["original_title"]),
            parent_guid=_clean_str(row["parent_guid"]),
            season_number=_to_int(row["season_number"]),
            episode_number=_to_int(row["episode_number"]),
            tmdb_id=_to_int(row["tmdb_id"]),
            imdb_id=_clean_str(row["imdb_id"]),
            episode_imdb_id=_clean_str(row["episode_imdb_id"]),
            runtime=_to_int(row["runtime"]),
            release_date=_clean_str(row["release_date"]),
            first_air_date=_clean_str(row["first_air_date"]),
            overview=_clean_str(row["overview"]),
        )
    return items


def _resolve_show(items: dict[str, FnItemRow], item: FnItemRow) -> FnItemRow | None:
    seen: set[str] = set()
    current = item
    for _ in range(8):
        if current.guid in seen:
            return None
        seen.add(current.guid)
        kind = (current.fn_type or "").lower()
        if kind in SHOW_TYPES:
            return current
        if kind in MOVIE_TYPES:
            return None
        if not current.parent_guid:
            return None
        nxt = items.get(current.parent_guid)
        if nxt is None:
            return None
        current = nxt
    return None


def _video_duration_seconds(con: sqlite3.Connection, media_guid: str | None) -> int | None:
    if not media_guid or not _table_exists(con, "media_stream"):
        return None
    try:
        row = con.execute(
            "SELECT MAX(duration) FROM media_stream WHERE media_guid=? AND codec_type='video'",
            (media_guid,),
        ).fetchone()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    value = float(row[0])
    if value > 100_000:  # milliseconds
        value = value / 1000
    return int(value) if value > 0 else None


def read_snapshot(path: Path, watched_threshold: float = 80.0) -> Snapshot:
    con = _connect(path)
    warnings: list[str] = []
    try:
        if not _table_exists(con, "item_user_play"):
            raise FnTvError("飞牛数据库缺少 item_user_play 表")
        items = _load_items(con)
        users = {user.guid: user for user in read_users(path)}

        columns = set(_columns(con, "item_user_play"))
        wanted = [
            "item_guid",
            "user_guid",
            "ts",
            "watched",
            "media_guid",
            "resolution",
            "type",
            "visible",
            "create_time",
            "update_time",
        ]
        select_parts = [name if name in columns else f"NULL AS {name}" for name in wanted]
        rows = con.execute(
            f"SELECT {', '.join(select_parts)} FROM item_user_play ORDER BY update_time DESC"
        ).fetchall()

        plays: list[NormalizedPlay] = []
        skipped = 0
        video_cache: dict[str, int | None] = {}
        for row in rows:
            item = items.get(_clean_str(row["item_guid"]) or "")
            user_guid = _clean_str(row["user_guid"])
            if item is None or not user_guid:
                skipped += 1
                continue
            if row["visible"] is not None and _to_int(row["visible"]) == 0:
                skipped += 1
                continue

            kind = (item.fn_type or "").lower()
            show: FnItemRow | None = None
            if kind in EPISODE_TYPES:
                item_type = "episode"
                show = _resolve_show(items, item)
                if show is None:
                    warnings.append(f"剧集缺少所属剧: {item.title}")
            elif kind in MOVIE_TYPES:
                item_type = "movie"
            else:
                item_type = "video" if kind == "video" else "unknown"

            if item_type == "episode":
                season_number = item.season_number
                episode_number = item.episode_number
                tmdb_id = (show.tmdb_id if show and show.tmdb_id else item.tmdb_id)
                imdb_id = (show.imdb_id if show and show.imdb_id else item.imdb_id)
                runtime_minutes = (item.runtime if item.runtime else (show.runtime if show else None))
                title = item.title
                show_guid = show.guid if show else None
                show_title = show.title if show else None
                year = _extract_year(
                    show.release_date if show else None,
                    show.first_air_date if show else None,
                )
            elif item_type == "movie":
                season_number = None
                episode_number = None
                tmdb_id = item.tmdb_id
                imdb_id = item.imdb_id
                runtime_minutes = item.runtime
                title = item.title
                show_guid = None
                show_title = None
                year = _extract_year(item.release_date, item.first_air_date)
            else:
                season_number = None
                episode_number = None
                tmdb_id = item.tmdb_id
                imdb_id = item.imdb_id
                runtime_minutes = item.runtime
                title = item.title
                show_guid = None
                show_title = None
                year = None

            runtime_seconds: int | None = None
            if runtime_minutes and runtime_minutes > 0:
                runtime_seconds = runtime_minutes * 60
            else:
                media_guid = _clean_str(row["media_guid"])
                if media_guid:
                    if media_guid not in video_cache:
                        video_cache[media_guid] = _video_duration_seconds(con, media_guid)
                    runtime_seconds = video_cache[media_guid]

            position = _to_int(row["ts"]) or 0
            watched = bool(_to_int(row["watched"]))
            progress: float | None = None
            if runtime_seconds and runtime_seconds > 0:
                progress = round(min(position / runtime_seconds * 100.0, 100.0), 1)
            # Only movies/episodes can be mapped to Trakt; unclassified Video
            # entries must not become "completed" just because they cross the
            # progress threshold.
            completed = False
            if item_type in {"movie", "episode"}:
                completed = watched or (progress is not None and progress >= watched_threshold)

            plays.append(
                NormalizedPlay(
                    item_guid=item.guid,
                    user_guid=user_guid,
                    item_type=item_type,
                    title=title,
                    show_guid=show_guid,
                    show_title=show_title,
                    season_number=season_number,
                    episode_number=episode_number,
                    tmdb_id=tmdb_id,
                    imdb_id=imdb_id,
                    episode_imdb_id=item.episode_imdb_id,
                    runtime_minutes=runtime_minutes,
                    year=year,
                    release_date=item.release_date or item.first_air_date,
                    overview=item.overview,
                    position_seconds=position,
                    watched=watched,
                    resolution=_clean_str(row["resolution"]),
                    create_time=from_epoch_ms(row["create_time"]),
                    update_time=from_epoch_ms(row["update_time"]),
                    runtime_seconds=runtime_seconds,
                    progress_percent=progress,
                    completed=completed,
                    raw={
                        "fn_type": item.fn_type,
                        "user": users.get(user_guid).username if user_guid in users else None,
                        "media_guid": _clean_str(row["media_guid"]),
                    },
                )
            )

        users_list = sorted(users.values(), key=lambda u: u.username.lower())
        if skipped:
            warnings.append(f"跳过 {skipped} 条无法关联到媒体或用户的播放记录")
        return Snapshot(
            path=str(path),
            users=users_list,
            plays=plays,
            items_count=len(items),
            raw_play_count=len(rows),
            skipped=skipped,
            warnings=warnings[:20],
        )
    finally:
        con.close()


def dump_schema(path: Path) -> str:
    con = _connect(path)
    try:
        rows = con.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL ORDER BY name"
        ).fetchall()
        parts = [f"-- fnTV schema dump\n-- source: {path}\n"]
        for row in rows:
            parts.append(f"{row['sql']};\n")
        return "\n".join(parts)
    finally:
        con.close()


def raw_summary(path: Path) -> dict[str, Any]:
    """Aggregate counts used by the dashboard header."""
    con = _connect(path)
    try:
        summary: dict[str, Any] = {}
        summary["item_types"] = {
            row["type"]: row["count"]
            for row in con.execute("SELECT type, COUNT(*) AS count FROM item GROUP BY type")
        }
        summary["users"] = con.execute("SELECT COUNT(*) FROM user").fetchone()[0]
        summary["plays"] = con.execute("SELECT COUNT(*) FROM item_user_play").fetchone()[0]
        summary["last_play_at"] = con.execute("SELECT MAX(update_time) FROM item_user_play").fetchone()[0]
        return summary
    finally:
        con.close()


def read_library(path: Path) -> list[dict[str, Any]]:
    """Return every Movie/Episode in the fnTV item table.

    ``read_snapshot`` only returns items that have a play record; this helper is
    used by the Trakt backfill to distinguish "in library but never played"
    from "not in library at all".
    """
    con = _connect(path)
    try:
        items = _load_items(con)
        entries: list[dict[str, Any]] = []
        for item in items.values():
            kind = (item.fn_type or "").lower()
            if kind in MOVIE_TYPES:
                entries.append(
                    {
                        "guid": item.guid,
                        "fn_type": "Movie",
                        "title": item.title,
                        "show_title": None,
                        "show_guid": None,
                        "season_number": None,
                        "episode_number": None,
                        "tmdb_id": item.tmdb_id,
                        "imdb_id": item.imdb_id,
                        "episode_imdb_id": None,
                        "runtime_minutes": item.runtime,
                        "year": _extract_year(item.release_date, item.first_air_date),
                    }
                )
            elif kind in EPISODE_TYPES:
                show = _resolve_show(items, item)
                if show is None:
                    continue
                entries.append(
                    {
                        "guid": item.guid,
                        "fn_type": "Episode",
                        "title": item.title,
                        "show_title": show.title,
                        "show_guid": show.guid,
                        "season_number": item.season_number,
                        "episode_number": item.episode_number,
                        "tmdb_id": show.tmdb_id or item.tmdb_id,
                        "imdb_id": show.imdb_id or item.imdb_id,
                        "episode_imdb_id": item.episode_imdb_id,
                        "runtime_minutes": item.runtime or show.runtime,
                        "year": _extract_year(show.release_date, show.first_air_date),
                    }
                )
        return entries
    finally:
        con.close()
