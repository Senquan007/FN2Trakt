from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppUser, MediaItem, MediaMatch, PlayRecord, SyncRecord, TraktAccount
from app.utils.time import humanize_age, to_iso_z


def media_display(media: MediaItem) -> str:
    if media.fn_type == "Episode" and media.season_number and media.episode_number:
        return f"{media.show_title or media.title} - S{media.season_number:02d}E{media.episode_number:02d}"
    return media.title


def trakt_url(media: MediaItem, match: MediaMatch | None) -> str | None:
    if match is None or not match.trakt_slug:
        return None
    if media.fn_type == "Episode":
        base = f"https://trakt.tv/shows/{match.trakt_slug}"
        if media.season_number and media.episode_number:
            return f"{base}/seasons/{media.season_number}/episodes/{media.episode_number}"
        return base
    return f"https://trakt.tv/movies/{match.trakt_slug}"


def match_dict(match: MediaMatch | None) -> dict[str, Any] | None:
    if match is None:
        return None
    return {
        "status": match.status,
        "source": match.source,
        "confidence": match.confidence,
        "title": match.trakt_title,
        "year": match.trakt_year,
        "trakt_id": match.trakt_id,
        "slug": match.trakt_slug,
        "ids": match.ids_json,
        "updated_at": to_iso_z(match.updated_at),
    }


def sync_dict(record: SyncRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "status": record.status,
        "attempts": record.attempts,
        "watched_at": to_iso_z(record.watched_at),
        "error": record.error,
        "updated_at": to_iso_z(record.updated_at),
        "updated_human": humanize_age(record.updated_at),
        "response": record.response_json,
    }


def play_dict(
    play: PlayRecord,
    media: MediaItem | None,
    match: MediaMatch | None,
    sync: SyncRecord | None,
    username: str | None = None,
) -> dict[str, Any]:
    target = media or MediaItem(fn_guid=play.fn_item_guid, fn_type=play.play_type or "Unknown", title="未知条目")
    return {
        "id": play.id,
        "item_guid": play.fn_item_guid,
        "user_guid": play.fn_user_guid,
        "username": username,
        "type": target.fn_type,
        "title": target.title,
        "show_title": target.show_title,
        "season_number": target.season_number,
        "episode_number": target.episode_number,
        "display_title": media_display(target),
        "year": target.year,
        "tmdb_id": target.tmdb_id,
        "imdb_id": target.imdb_id,
        "resolution": play.resolution,
        "position_seconds": play.position_seconds,
        "runtime_seconds": play.runtime_seconds,
        "progress_percent": play.progress_percent,
        "completed": play.completed,
        "watched": play.watched,
        "fn_create_time": to_iso_z(play.fn_create_time),
        "fn_update_time": to_iso_z(play.fn_update_time),
        "last_play_human": humanize_age(play.fn_update_time),
        "match": match_dict(match),
        "match_media_guid": (
            target.show_guid if target.fn_type == "Episode" and target.show_guid else target.fn_guid
        ),
        "sync": sync_dict(sync),
        "trakt_url": trakt_url(target, match),
    }


def load_play_rows(
    db: Session,
    plays: list[PlayRecord],
    account: TraktAccount | None,
    usernames: dict[str, str],
) -> list[dict[str, Any]]:
    if not plays:
        return []
    item_guids = {play.fn_item_guid for play in plays}
    media_map = {
        item.fn_guid: item
        for item in db.scalars(select(MediaItem).where(MediaItem.fn_guid.in_(item_guids))).all()
    }
    target_guids = set()
    for media in media_map.values():
        target_guids.add(media.show_guid if media.fn_type == "Episode" and media.show_guid else media.fn_guid)
    match_map = {
        match.media_guid: match
        for match in db.scalars(select(MediaMatch).where(MediaMatch.media_guid.in_(target_guids))).all()
    }
    sync_map: dict[int, SyncRecord] = {}
    if account is not None:
        sync_map = {
            record.play_id: record
            for record in db.scalars(
                select(SyncRecord).where(
                    SyncRecord.trakt_account_id == account.id,
                    SyncRecord.play_id.in_({play.id for play in plays}),
                )
            ).all()
        }

    result = []
    for play in plays:
        media = media_map.get(play.fn_item_guid)
        target_guid = None
        if media is not None:
            target_guid = media.show_guid if media.fn_type == "Episode" and media.show_guid else media.fn_guid
        result.append(
            play_dict(
                play,
                media,
                match_map.get(target_guid) if target_guid else None,
                sync_map.get(play.id),
                usernames.get(play.fn_user_guid),
            )
        )
    return result


def account_for(db: Session, user: AppUser) -> TraktAccount | None:
    return db.scalar(select(TraktAccount).where(TraktAccount.app_user_id == user.id))
