from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import FnUser, MediaItem, PlayRecord
from app.fntv import Snapshot
from app.utils.time import utcnow


@dataclass
class IngestResult:
    users: int
    media: int
    plays: int
    completed: int
    created_plays: int
    updated_plays: int
    warnings: list[str]


def ingest_snapshot(db: Session, snapshot: Snapshot) -> IngestResult:
    created_plays = 0
    updated_plays = 0
    completed = 0

    for user in snapshot.users:
        row = db.get(FnUser, user.guid)
        if row is None:
            row = FnUser(guid=user.guid)
            db.add(row)
        row.username = user.username
        row.is_admin = user.is_admin
        row.status = user.status
        row.last_login_time = user.last_login_time
        row.updated_at = utcnow()

    media_seen: set[str] = set()
    for play in snapshot.plays:
        media = db.get(MediaItem, play.item_guid)
        if media is None:
            media = MediaItem(fn_guid=play.item_guid, fn_type=play.item_type)
            db.add(media)
        media.fn_type = {
            "episode": "Episode",
            "movie": "Movie",
            "video": "Video",
        }.get(play.item_type, "Unknown")
        media.title = play.title
        media.original_title = play.show_title if play.item_type == "episode" else play.title
        media.season_number = play.season_number
        media.episode_number = play.episode_number
        media.show_guid = play.show_guid
        media.show_title = play.show_title
        media.year = play.year
        media.tmdb_id = play.tmdb_id
        media.imdb_id = play.imdb_id
        media.episode_imdb_id = play.episode_imdb_id
        media.runtime_minutes = play.runtime_minutes
        media.release_date = play.release_date
        media.overview = play.overview
        media.updated_at = utcnow()
        media_seen.add(play.item_guid)

        record = db.scalar(
            select(PlayRecord).where(
                PlayRecord.fn_item_guid == play.item_guid,
                PlayRecord.fn_user_guid == play.user_guid,
            )
        )
        if record is None:
            record = PlayRecord(fn_item_guid=play.item_guid, fn_user_guid=play.user_guid)
            db.add(record)
            created_plays += 1
        else:
            updated_plays += 1

        record.position_seconds = play.position_seconds
        record.watched = play.watched
        record.resolution = play.resolution
        record.play_type = play.item_type
        record.fn_create_time = play.create_time
        record.fn_update_time = play.update_time
        record.runtime_seconds = play.runtime_seconds
        record.progress_percent = play.progress_percent
        record.completed = play.completed
        record.last_seen_at = utcnow()
        record.raw_json = play.raw
        if play.completed:
            completed += 1

    db.flush()
    return IngestResult(
        users=len(snapshot.users),
        media=len(media_seen),
        plays=len(snapshot.plays),
        completed=completed,
        created_plays=created_plays,
        updated_plays=updated_plays,
        warnings=snapshot.warnings,
    )


def recompute_completed(db: Session, threshold: float) -> int:
    """Re-evaluate completed flags after the upload threshold changes."""
    changed = 0
    for record in db.scalars(select(PlayRecord)).all():
        supported = record.play_type in {"movie", "episode"}
        completed = supported and (
            bool(record.watched)
            or (record.progress_percent is not None and record.progress_percent >= threshold)
        )
        if record.completed != completed:
            record.completed = completed
            changed += 1
    db.commit()
    return changed
