from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.serializers import load_play_rows, play_dict
from app.db.models import (
    AppUser,
    FnUser,
    MediaItem,
    MediaMatch,
    PlayRecord,
    SyncRecord,
    TraktAccount,
)
from app.db.session import get_db
from app.utils.time import to_iso_z

router = APIRouter(prefix="/api/plays", tags=["plays"])

def _parse_date(value: str | None, end: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        if end and len(value) <= 10:
            parsed = parsed + timedelta(days=1)
        return parsed
    except ValueError:
        return None


def _context(db: Session, plays: list[PlayRecord]):
    media_map = {
        item.fn_guid: item
        for item in db.scalars(
            select(MediaItem).where(MediaItem.fn_guid.in_({p.fn_item_guid for p in plays}))
        ).all()
    }
    target_guids = {
        media.show_guid if media.fn_type == "Episode" and media.show_guid else media.fn_guid
        for media in media_map.values()
    }
    matches = {
        m.media_guid: m
        for m in db.scalars(select(MediaMatch).where(MediaMatch.media_guid.in_(target_guids))).all()
    }
    accounts_by_fn: dict[str, TraktAccount] = {}
    for account in db.scalars(select(TraktAccount)).all():
        app_user = db.get(AppUser, account.app_user_id)
        if app_user and app_user.fn_user_guid:
            accounts_by_fn[app_user.fn_user_guid] = account
    account_ids = {account.id for account in accounts_by_fn.values()}
    sync_rows = (
        db.scalars(select(SyncRecord).where(SyncRecord.trakt_account_id.in_(account_ids))).all()
        if account_ids
        else []
    )
    sync_by_pair = {(row.play_id, row.trakt_account_id): row for row in sync_rows}
    usernames = {row.guid: row.username for row in db.scalars(select(FnUser)).all()}
    return media_map, matches, accounts_by_fn, sync_by_pair, usernames


@router.get("")
def list_plays(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = "all",
    media_type: str | None = None,
    query: str | None = None,
    fn_user_guid: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scope = None if user.is_admin else user.fn_user_guid
    if scope is None and fn_user_guid:
        scope = fn_user_guid

    plays = db.scalars(select(PlayRecord).order_by(PlayRecord.fn_update_time.desc())).all()
    if scope:
        plays = [play for play in plays if play.fn_user_guid == scope]
    media_map, matches, accounts_by_fn, sync_by_pair, usernames = _context(db, plays)
    start = _parse_date(date_from)
    end = _parse_date(date_to, end=True)

    rows = []
    summary = {"total": 0, "completed": 0, "synced": 0, "pending": 0, "failed": 0, "blocked": 0, "unmatched": 0}
    for play in plays:
        media = media_map.get(play.fn_item_guid)
        target_guid = (
            media.show_guid
            if media is not None and media.fn_type == "Episode" and media.show_guid
            else (media.fn_guid if media is not None else None)
        )
        match = matches.get(target_guid) if target_guid else None
        account = accounts_by_fn.get(play.fn_user_guid)
        sync = sync_by_pair.get((play.id, account.id)) if account else None

        if media_type and media_type != "all":
            expected = {"episode": "Episode", "movie": "Movie"}.get(media_type, media_type)
            if media is None or media.fn_type != expected:
                continue
        if query:
            needle = query.strip().casefold()
            haystack = " ".join(
                filter(
                    None,
                    [
                        media.title if media else "",
                        media.show_title if media else "",
                        media.original_title if media else "",
                    ],
                )
            ).casefold()
            if needle not in haystack:
                continue
        if start and play.fn_update_time and play.fn_update_time < start:
            continue
        if end and play.fn_update_time and play.fn_update_time >= end:
            continue

        if not play.completed:
            state = "incomplete"
        elif match is None or match.status in {"unmatched", "rejected"}:
            state = "unmatched"
        elif sync is not None:
            # SyncRecord stores "success"; the API/UI state is "synced".
            state = "synced" if sync.status == "success" else sync.status
        else:
            state = "pending"

        if status == "completed" and state == "incomplete":
            continue
        if status in {"pending", "synced", "failed", "blocked", "unmatched"} and state != status:
            continue

        summary["total"] += 1
        if play.completed:
            summary["completed"] += 1
            if state == "synced":
                summary["synced"] += 1
            elif state == "failed":
                summary["failed"] += 1
            elif state == "blocked":
                summary["blocked"] += 1
            elif state == "unmatched":
                summary["unmatched"] += 1
            else:
                summary["pending"] += 1

        item = play_dict(play, media, match, sync, usernames.get(play.fn_user_guid))
        item["state"] = state
        rows.append(item)

    total = len(rows)
    start_index = (page - 1) * page_size
    items = rows[start_index : start_index + page_size]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if page_size else 0,
        "summary": summary,
        "users": [
            {"guid": row.guid, "username": row.username}
            for row in db.scalars(select(FnUser).order_by(FnUser.username)).all()
        ],
    }


@router.get("/{play_id}")
def play_detail(play_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    play = db.get(PlayRecord, play_id)
    if play is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    if not user.is_admin and play.fn_user_guid != user.fn_user_guid:
        raise HTTPException(status_code=403, detail="无权查看该记录")
    media = db.get(MediaItem, play.fn_item_guid)
    target_guid = None
    if media is not None:
        target_guid = media.show_guid if media.fn_type == "Episode" and media.show_guid else media.fn_guid
    match = db.scalar(select(MediaMatch).where(MediaMatch.media_guid == target_guid)) if target_guid else None
    fn_user = db.get(FnUser, play.fn_user_guid)
    account = None
    if fn_user is not None:
        app_user = db.scalar(select(AppUser).where(AppUser.fn_user_guid == fn_user.guid))
        if app_user is not None:
            account = db.scalar(select(TraktAccount).where(TraktAccount.app_user_id == app_user.id))
    sync = (
        db.scalar(
            select(SyncRecord).where(SyncRecord.play_id == play.id, SyncRecord.trakt_account_id == account.id)
        )
        if account
        else None
    )
    payload = load_play_rows(db, [play], account, {play.fn_user_guid: fn_user.username if fn_user else ""})[0]
    if not play.completed:
        payload["state"] = "incomplete"
    elif match is None or match.status in {"unmatched", "rejected"}:
        payload["state"] = "unmatched"
    elif sync is not None:
        payload["state"] = "synced" if sync.status == "success" else sync.status
    else:
        payload["state"] = "pending"
    payload["raw"] = play.raw_json
    payload["sync_request"] = sync.request_json if sync else None
    payload["created_at"] = to_iso_z(play.first_seen_at)
    payload["synced_at"] = to_iso_z(sync.updated_at) if sync else None
    return payload
