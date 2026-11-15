from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user, get_current_user
from app.db.models import AppUser, MediaItem, MediaMatch
from app.db.session import get_db
from app.services.matching import (
    apply_manual_match,
    ensure_matches,
    reject_match,
    search_candidates,
    target_overview,
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
    cards = target_overview(db, user_guid=_scope_user(user))
    # Every card that has at least one completed play belongs on this page, so
    # the numbers here always match what 观看记录 reports as unmatched.
    active = [card for card in cards.values() if card.count > 0]
    summary = {
        "unmatched": sum(1 for c in active if c.state == "unmatched"),
        "auto": sum(1 for c in active if c.state == "auto"),
        "manual": sum(1 for c in active if c.state == "manual"),
        "rejected": sum(1 for c in active if c.state == "rejected"),
    }

    items = []
    for card in active:
        if status != "all" and card.state != status:
            continue
        items.append(
            {
                "media_guid": card.guid,
                "media_type": card.media_type,
                "title": card.title,
                "year": card.year,
                "tmdb_id": card.tmdb_id,
                "imdb_id": card.imdb_id,
                "count": card.count,
                "samples": card.samples,
                "orphan": card.orphan,
                "match": {
                    "status": card.state,
                    "title": card.match.trakt_title if card.match else None,
                    "year": card.match.trakt_year if card.match else None,
                    "slug": card.match.trakt_slug if card.match else None,
                    "source": card.match.source if card.match else None,
                    "ids": card.match.ids_json if card.match else None,
                },
            }
        )
    items.sort(key=lambda row: (-row["count"], row["title"]))
    return {"items": items, "total": len(items), "summary": summary}


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
