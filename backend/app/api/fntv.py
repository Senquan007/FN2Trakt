from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user, get_current_user
from app.db.models import AppUser, FnUser, MediaMatch, PlayRecord
from app.db.session import get_db
from app.fntv import FnTvError, dump_schema, inspect_database, raw_summary, read_snapshot, read_users
from app.services.ingest import ingest_snapshot
from app.services.matching import ensure_matches
from app.services.settings_service import fntv_db_path, get_float

router = APIRouter(prefix="/api/fntv", tags=["fntv"])


class RefreshPayload(BaseModel):
    run_matching: bool = True


@router.get("/status")
def status(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    path = fntv_db_path(db)
    info = inspect_database(path)
    summary = None
    if info.get("ok"):
        try:
            summary = raw_summary(path)
        except Exception as exc:  # keep the status endpoint resilient
            info["error"] = f"读取统计失败: {exc}"
    cached = {
        "fn_users": db.scalar(select(func.count(FnUser.guid))) or 0,
        "plays": db.scalar(select(func.count(PlayRecord.id))) or 0,
        "completed": db.scalar(select(func.count(PlayRecord.id)).where(PlayRecord.completed.is_(True))) or 0,
        "unmatched": db.scalar(select(func.count(MediaMatch.id)).where(MediaMatch.status == "unmatched")) or 0,
    }
    return {"database": info, "summary": summary, "cached": cached, "path": str(path)}


@router.get("/users")
def users(admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)):
    path = fntv_db_path(db)
    try:
        rows = read_users(path)
    except FnTvError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    bound = {
        row.fn_user_guid
        for row in db.scalars(select(AppUser).where(AppUser.fn_user_guid.is_not(None))).all()
    }
    play_counts = dict(
        db.execute(
            select(PlayRecord.fn_user_guid, func.count(PlayRecord.id))
            .where(PlayRecord.completed.is_(True))
            .group_by(PlayRecord.fn_user_guid)
        ).all()
    )
    return {
        "items": [
            {
                "guid": row.guid,
                "username": row.username,
                "is_admin": row.is_admin,
                "status": row.status,
                "last_login_time": row.last_login_time.isoformat() + "Z" if row.last_login_time else None,
                "bound": row.guid in bound,
                "completed_count": play_counts.get(row.guid, 0),
            }
            for row in rows
        ]
    }


@router.post("/refresh")
def refresh(
    payload: RefreshPayload,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    path = fntv_db_path(db)
    threshold = get_float(db, "sync.watched_threshold", 80.0)
    try:
        snapshot = read_snapshot(path, watched_threshold=threshold)
    except FnTvError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = ingest_snapshot(db, snapshot)
    db.commit()
    match_stats = ensure_matches(db) if payload.run_matching else None
    return {
        "snapshot": {
            "users": result.users,
            "media": result.media,
            "plays": result.plays,
            "completed": result.completed,
            "created": result.created_plays,
            "updated": result.updated_plays,
            "skipped": snapshot.skipped,
            "warnings": result.warnings,
        },
        "matching": match_stats,
    }


@router.get("/schema")
def schema(admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        return {"sql": dump_schema(fntv_db_path(db))}
    except FnTvError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
