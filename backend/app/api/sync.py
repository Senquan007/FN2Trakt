from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user, get_current_user
from app.api.serializers import media_display
from app.db.models import AppUser, MediaItem, PlayRecord, SyncRecord, SyncRun, TraktAccount
from app.db.session import get_db
from app.services.sync import preview_sync, start_sync, sync_single_play
from app.utils.time import humanize_age, to_iso_z

router = APIRouter(prefix="/api/sync", tags=["sync"])


class RunPayload(BaseModel):
    app_user_id: int | None = None


@router.get("/preview")
def preview(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return preview_sync(db, user)


@router.post("/run")
def run(
    payload: RunPayload | None = None,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target_id = user.id
    if payload and payload.app_user_id and user.is_admin:
        target_id = payload.app_user_id
    target = db.get(AppUser, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not target.fn_user_guid:
        raise HTTPException(status_code=400, detail="该账号尚未绑定飞牛用户")
    account = db.scalar(select(TraktAccount).where(TraktAccount.app_user_id == target.id))
    if account is None:
        raise HTTPException(status_code=400, detail="该账号尚未绑定 Trakt")
    run_row = start_sync(target.id, "manual")
    if run_row is None:
        raise HTTPException(status_code=409, detail="已有同步任务正在运行，请稍后再试")
    return {"run_id": run_row.id, "status": run_row.status}


@router.post("/run-all")
def run_all_endpoint(admin: AppUser = Depends(get_admin_user)):
    from app.services.sync import run_all

    run_ids = run_all("manual")
    return {"run_ids": run_ids, "count": len(run_ids)}


@router.post("/play/{play_id}")
def sync_play(play_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    play = db.get(PlayRecord, play_id)
    if play is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    owner = db.scalar(select(AppUser).where(AppUser.fn_user_guid == play.fn_user_guid))
    if owner is None:
        raise HTTPException(status_code=400, detail="该记录没有对应的站内用户")
    if not user.is_admin and owner.id != user.id:
        raise HTTPException(status_code=403, detail="无权操作该记录")
    try:
        result = sync_single_play(db, play, owner)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.get("/runs")
def runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = select(SyncRun).order_by(SyncRun.id.desc())
    if not user.is_admin:
        query = query.where(SyncRun.app_user_id == user.id)
    rows = db.scalars(query).all()
    total = len(rows)
    rows = rows[(page - 1) * page_size : page * page_size]
    usernames = {u.id: u.username for u in db.scalars(select(AppUser)).all()}
    return {
        "items": [
            {
                "id": row.id,
                "app_user_id": row.app_user_id,
                "username": usernames.get(row.app_user_id) if row.app_user_id else None,
                "trigger": row.trigger,
                "status": row.status,
                "started_at": to_iso_z(row.started_at),
                "finished_at": to_iso_z(row.finished_at),
                "duration_seconds": (row.finished_at - row.started_at).total_seconds() if row.finished_at else None,
                "scanned": row.scanned,
                "completed": row.completed,
                "uploaded": row.uploaded,
                "failed": row.failed,
                "skipped": row.skipped,
                "message": row.message,
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/records")
def records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user.is_admin:
        own = db.scalar(select(TraktAccount).where(TraktAccount.app_user_id == user.id))
        account_ids = {own.id} if own else set()
    else:
        account_ids = {row.id for row in db.scalars(select(TraktAccount)).all()}

    query = select(SyncRecord).where(SyncRecord.trakt_account_id.in_(account_ids)).order_by(SyncRecord.updated_at.desc())
    if status:
        query = query.where(SyncRecord.status == status)
    rows = db.scalars(query).all()
    total = len(rows)
    rows = rows[(page - 1) * page_size : page * page_size]

    play_map = {p.id: p for p in db.scalars(select(PlayRecord).where(PlayRecord.id.in_({r.play_id for r in rows}))).all()}
    media_map = {
        m.fn_guid: m
        for m in db.scalars(select(MediaItem).where(MediaItem.fn_guid.in_({p.fn_item_guid for p in play_map.values()}))).all()
    }
    account_map = {a.id: a for a in db.scalars(select(TraktAccount)).all()}
    fn_to_app = {u.fn_user_guid: u for u in db.scalars(select(AppUser).where(AppUser.fn_user_guid.is_not(None))).all()}

    items = []
    for record in rows:
        play = play_map.get(record.play_id)
        media = media_map.get(play.fn_item_guid) if play else None
        account = account_map.get(record.trakt_account_id)
        app_user = fn_to_app.get(play.fn_user_guid) if play else None
        items.append(
            {
                "id": record.id,
                "play_id": record.play_id,
                "status": record.status,
                "title": media_display(media) if media else "未知条目",
                "username": app_user.username if app_user else None,
                "trakt_username": account.trakt_username if account else None,
                "watched_at": to_iso_z(record.watched_at),
                "attempts": record.attempts,
                "error": record.error,
                "updated_at": to_iso_z(record.updated_at),
                "updated_human": humanize_age(record.updated_at),
                "response": record.response_json,
            }
        )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/records/{record_id}/retry")
def retry(record_id: int, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.get(SyncRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="同步记录不存在")
    account = db.get(TraktAccount, record.trakt_account_id)
    if account is None:
        raise HTTPException(status_code=400, detail="Trakt 账号已解绑")
    if not user.is_admin and account.app_user_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作该记录")
    record.status = "pending"
    record.error = None
    db.commit()
    run_row = start_sync(account.app_user_id, "retry")
    return {"ok": True, "run_id": run_row.id if run_row else None}
