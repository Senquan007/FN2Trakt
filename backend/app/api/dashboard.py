from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.serializers import media_display, sync_dict
from app.db.models import (
    AppUser,
    FnUser,
    MediaItem,
    MediaMatch,
    PlayRecord,
    SyncRecord,
    SyncRun,
    TraktAccount,
)
from app.db.session import get_db
from app.utils.time import humanize_age, to_iso_z, utcnow

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    scope = None if user.is_admin else user.fn_user_guid
    plays = db.scalars(select(PlayRecord).order_by(PlayRecord.fn_update_time.desc())).all()
    if scope:
        plays = [p for p in plays if p.fn_user_guid == scope]
    completed = [p for p in plays if p.completed]

    media_map = {
        m.fn_guid: m
        for m in db.scalars(
            select(MediaItem).where(MediaItem.fn_guid.in_({p.fn_item_guid for p in plays}))
        ).all()
    }
    target_guids = {
        media_map[p.fn_item_guid].show_guid
        if p.fn_item_guid in media_map and media_map[p.fn_item_guid].fn_type == "Episode" and media_map[p.fn_item_guid].show_guid
        else p.fn_item_guid
        for p in plays
        if p.fn_item_guid in media_map
    }
    matches = {
        m.media_guid: m for m in db.scalars(select(MediaMatch).where(MediaMatch.media_guid.in_(target_guids))).all()
    }

    accounts_by_fn: dict[str, TraktAccount] = {}
    for account in db.scalars(select(TraktAccount)).all():
        app_user = db.get(AppUser, account.app_user_id)
        if app_user and app_user.fn_user_guid:
            accounts_by_fn[app_user.fn_user_guid] = account
    account_ids = {a.id for a in accounts_by_fn.values()}
    sync_rows = (
        db.scalars(select(SyncRecord).where(SyncRecord.trakt_account_id.in_(account_ids))).all() if account_ids else []
    )
    sync_by_pair = {(r.play_id, r.trakt_account_id): r for r in sync_rows}

    stats = {
        "total_plays": len(plays),
        "completed": len(completed),
        "synced": 0,
        "failed": 0,
        "pending": 0,
        "blocked": 0,
        "unmatched": 0,
    }
    type_stats = {
        "movie": {"plays": 0, "completed": 0, "synced": 0, "items": 0},
        "episode": {"plays": 0, "completed": 0, "synced": 0, "episodes": 0, "shows": 0},
    }
    movie_items: set[str] = set()
    episode_items: set[str] = set()
    show_items: set[str] = set()
    status_dist = Counter()
    trend: dict[str, int] = defaultdict(int)
    top: Counter = Counter()
    for play in plays:
        media = media_map.get(play.fn_item_guid)
        if media is not None and media.fn_type == "Episode":
            target_guid = media.show_guid
            name = media.show_title or media.title
        else:
            target_guid = play.fn_item_guid
            name = media.title if media else "未知"
        match = matches.get(target_guid) if target_guid else None
        kind = "movie" if media is not None and media.fn_type == "Movie" else (
            "episode" if media is not None and media.fn_type == "Episode" else None
        )
        if kind is not None:
            type_stats[kind]["plays"] += 1
            if kind == "movie":
                movie_items.add(media.fn_guid)
            else:
                episode_items.add(media.fn_guid)
                show_items.add(media.show_guid or media.fn_guid)
        if play.completed and (match is None or match.status == "unmatched"):
            stats["unmatched"] += 1

        if play.completed:
            account = accounts_by_fn.get(play.fn_user_guid)
            record = sync_by_pair.get((play.id, account.id)) if account else None
            state = record.status if record else "pending"
            status_dist[state] += 1
            if kind is not None:
                type_stats[kind]["completed"] += 1
            if state == "success":
                stats["synced"] += 1
                if kind is not None:
                    type_stats[kind]["synced"] += 1
            elif state == "failed":
                stats["failed"] += 1
            elif state == "blocked":
                stats["blocked"] += 1
            else:
                stats["pending"] += 1
        if play.fn_update_time:
            day = play.fn_update_time.date().isoformat()
            trend[day] += 1
        if play.completed and media is not None and media.fn_type == "Episode":
            top[name] += 1

    type_stats["movie"]["items"] = len(movie_items)
    type_stats["episode"]["episodes"] = len(episode_items)
    type_stats["episode"]["shows"] = len(show_items)

    days = []
    today = utcnow().date()
    for offset in range(29, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        days.append({"date": day, "count": trend.get(day, 0)})

    recent = []
    for play in completed[:8]:
        media = media_map.get(play.fn_item_guid)
        match = None
        if media is not None:
            target_guid = media.show_guid if media.fn_type == "Episode" and media.show_guid else media.fn_guid
            match = matches.get(target_guid)
        account = accounts_by_fn.get(play.fn_user_guid)
        record = sync_by_pair.get((play.id, account.id)) if account else None
        recent.append(
            {
                "id": play.id,
                "title": media_display(media) if media else "未知条目",
                "type": media.fn_type if media else "Unknown",
                "progress": play.progress_percent,
                "watched_at": to_iso_z(play.fn_update_time),
                "watched_human": humanize_age(play.fn_update_time),
                "match_status": match.status if match else "unmatched",
                "sync_status": record.status if record else "pending",
            }
        )

    runs_query = select(SyncRun).order_by(SyncRun.id.desc()).limit(6)
    if not user.is_admin:
        runs_query = select(SyncRun).where(SyncRun.app_user_id == user.id).order_by(SyncRun.id.desc()).limit(6)
    runs = db.scalars(runs_query).all()

    fn_users = db.scalar(select(FnUser).where(FnUser.guid == scope)) if scope else None
    return {
        "stats": stats,
        "status_distribution": [
            {"status": key, "count": value} for key, value in status_dist.items() if value
        ],
        "type_stats": type_stats,
        "trend": days,
        "top_shows": [{"title": title, "count": count} for title, count in top.most_common(8)],
        "recent": recent,
        "runs": [
            {
                "id": run.id,
                "trigger": run.trigger,
                "status": run.status,
                "started_at": to_iso_z(run.started_at),
                "finished_at": to_iso_z(run.finished_at),
                "uploaded": run.uploaded,
                "failed": run.failed,
                "message": run.message,
            }
            for run in runs
        ],
        "trakt_bound": len(accounts_by_fn),
        "fn_users": db.scalar(select(FnUser).where(FnUser.guid == scope)).username if scope and fn_users else None,
        "scope": scope,
        "generated_at": to_iso_z(utcnow()),
    }
