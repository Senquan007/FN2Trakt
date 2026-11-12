from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user, get_current_user
from app.db.models import AppUser, MediaItem, MediaMatch, PlayRecord
from app.db.session import get_db
from app.services.matching import (
    apply_manual_match,
    collect_targets,
    ensure_matches,
    reject_match,
    search_candidates,
)
from app.trakt.client import TraktError

router = APIRouter(prefix="/api/media", tags=["media"])


class MatchPayload(BaseModel):
    media_guid: str
    candidate: dict[str, Any]


class RejectPayload(BaseModel):
    media_guid: str


def _scope_user(user: AppUser) -> str | None:
    return None if user.is_admin else user.fn_user_guid


@router.get("/targets")
def targets(
    status: str = "unmatched",
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    targets_map = collect_targets(db)
    matches = {m.media_guid: m for m in db.scalars(select(MediaMatch)).all()}
    media_rows = db.scalars(select(MediaItem).where(MediaItem.fn_type.in_(["Movie", "Episode"]))).all()
    target_by_item: dict[str, str] = {}
    media_by_guid = {item.fn_guid: item for item in media_rows}
    for item in media_rows:
        target_by_item[item.fn_guid] = (
            item.show_guid if item.fn_type == "Episode" and item.show_guid else item.fn_guid
        )

    scope = _scope_user(user)
    play_rows = db.scalars(select(PlayRecord).where(PlayRecord.completed.is_(True))).all()
    counts: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    for play in play_rows:
        if scope and play.fn_user_guid != scope:
            continue
        guid = target_by_item.get(play.fn_item_guid)
        if not guid:
            continue
        counts[guid] = counts.get(guid, 0) + 1
        if len(samples.setdefault(guid, [])) < 3:
            media = media_by_guid.get(play.fn_item_guid)
            if media is not None:
                samples[guid].append(media.title)

    items = []
    for guid, target in targets_map.items():
        match = matches.get(guid)
        state = match.status if match else "unmatched"
        if status != "all" and state != status:
            continue
        if counts.get(guid, 0) == 0:
            continue
        items.append(
            {
                "media_guid": guid,
                "media_type": target.media_type,
                "title": target.title,
                "year": target.year,
                "tmdb_id": target.tmdb_id,
                "imdb_id": target.imdb_id,
                "count": counts.get(guid, 0),
                "samples": samples.get(guid, []),
                "match": {
                    "status": state,
                    "title": match.trakt_title if match else None,
                    "year": match.trakt_year if match else None,
                    "slug": match.trakt_slug if match else None,
                    "source": match.source if match else None,
                    "ids": match.ids_json if match else None,
                },
            }
        )
    items.sort(key=lambda row: (-row["count"], row["title"]))
    return {
        "items": items,
        "total": len(items),
        "summary": {
            "unmatched": sum(1 for g in targets_map if (matches.get(g).status if matches.get(g) else "unmatched") == "unmatched" and counts.get(g, 0) > 0),
            "auto": sum(1 for g in targets_map if (matches.get(g).status if matches.get(g) else "unmatched") == "auto" and counts.get(g, 0) > 0),
            "manual": sum(1 for g in targets_map if (matches.get(g).status if matches.get(g) else "unmatched") == "manual" and counts.get(g, 0) > 0),
            "rejected": sum(1 for g in targets_map if (matches.get(g).status if matches.get(g) else "unmatched") == "rejected" and counts.get(g, 0) > 0),
        },
    }


@router.post("/rematch")
def rematch(admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        return ensure_matches(db)
    except TraktError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/search")
def search(
    query: str | None = None,
    media_type: str | None = None,
    media_guid: str | None = None,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current = None
    if media_guid:
        media = db.get(MediaItem, media_guid)
        if media is not None:
            media_type = "movie" if media.fn_type == "Movie" else "show"
            query = query or (media.title if media.fn_type == "Movie" else (media.show_title or media.title))
            existing = db.scalar(select(MediaMatch).where(MediaMatch.media_guid == media_guid))
            if existing is not None:
                current = {
                    "status": existing.status,
                    "title": existing.trakt_title,
                    "slug": existing.trakt_slug,
                    "ids": existing.ids_json,
                }
    if not query:
        raise HTTPException(status_code=400, detail="请输入搜索关键词")
    media_type = media_type or "show"
    try:
        candidates = search_candidates(db, query, media_type, limit=12)
    except TraktError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"items": candidates, "current": current, "query": query, "type": media_type}


@router.post("/match")
def match(payload: MatchPayload, admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        result = apply_manual_match(db, payload.media_guid, payload.candidate)
    except TraktError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "match": {
            "status": result.status,
            "title": result.trakt_title,
            "slug": result.trakt_slug,
            "ids": result.ids_json,
        }
    }


@router.post("/reject")
def reject(payload: RejectPayload, admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)):
    reject_match(db, payload.media_guid)
    return {"ok": True}
