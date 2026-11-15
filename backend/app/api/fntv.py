from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user, get_current_user
from app.db.models import AppUser, FnUser, MediaMatch, PlayRecord
from app.db.session import get_db
from app.fntv import FnTvError, dump_schema, inspect_database, raw_summary, read_users
from app.services.refresh import RefreshBusy, auto_refresh_enabled, last_state, refresh_fntv
from app.services.settings_service import fntv_db_path

router = APIRouter(prefix="/api/fntv", tags=["fntv"])


class RefreshPayload(BaseModel):
    run_matching: bool = True
    force: bool = True


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
    return {
        "database": info,
        "summary": summary,
        "cached": cached,
        "path": str(path),
        "refresh": {**last_state(db), "auto_enabled": auto_refresh_enabled(db)},
    }


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
    try:
        result = refresh_fntv(
            db,
            trigger="manual",
            force=payload.force,
            run_matching=payload.run_matching,
        )
    except RefreshBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FnTvError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("snapshot") is None:
        # Unchanged database (force=False): replay the previous summary so the
        # caller still gets a meaningful payload.
        result["snapshot"] = result.get("last_refresh_summary")
    return result


@router.get("/schema")
def schema(admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        return {"sql": dump_schema(fntv_db_path(db))}
    except FnTvError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
