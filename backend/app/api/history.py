from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user
from app.db.models import AppUser, TraktAccount, TraktHistory
from app.db.session import get_db
from app.services.trakt_history import (
    apply_backfill,
    history_summary,
    preview_backfill,
    pull_history,
)
from app.trakt.client import TraktError

router = APIRouter(prefix="/api/trakt/history", tags=["trakt-history"])


class HistoryAction(BaseModel):
    account_id: int | None = None


class BackfillApply(BaseModel):
    account_id: int | None = None
    confirm: bool = False


def _account(db: Session, admin: AppUser, account_id: int | None) -> TraktAccount:
    if account_id is not None:
        row = db.get(TraktAccount, account_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Trakt 账号不存在")
        return row
    row = db.scalar(select(TraktAccount).where(TraktAccount.app_user_id == admin.id))
    if row is None:
        raise HTTPException(status_code=404, detail="当前管理员尚未绑定 Trakt 账号")
    return row


@router.get("/accounts")
def accounts(admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(TraktAccount).order_by(TraktAccount.id)).all()
    counts = {
        account_id: count
        for account_id, count in db.execute(
            select(TraktHistory.trakt_account_id, func.count(TraktHistory.id)).group_by(
                TraktHistory.trakt_account_id
            )
        ).all()
    }
    items = []
    for row in rows:
        user = db.get(AppUser, row.app_user_id)
        items.append(
            {
                "id": row.id,
                "app_user_id": row.app_user_id,
                "username": user.username if user else None,
                "trakt_username": row.trakt_username,
                "status": row.status,
                "history_count": counts.get(row.id, 0),
            }
        )
    return {"items": items}


@router.get("/summary")
def summary(
    account_id: int | None = None,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    account = _account(db, admin, account_id)
    return {"account": {"id": account.id, "trakt_username": account.trakt_username}, **history_summary(db, account)}


@router.post("/pull")
def pull(
    payload: HistoryAction,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    account = _account(db, admin, payload.account_id)
    try:
        result = pull_history(db, account)
    except TraktError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"account": {"id": account.id, "trakt_username": account.trakt_username}, **result}


@router.get("/preview")
def preview(
    account_id: int | None = None,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    account = _account(db, admin, account_id)
    return {"account": {"id": account.id, "trakt_username": account.trakt_username}, **preview_backfill(db, account)}


@router.post("/apply")
def apply(
    payload: BackfillApply,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="请确认已了解该操作会修改本地观看记录")
    account = _account(db, admin, payload.account_id)
    try:
        return apply_backfill(db, account)
    except TraktError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
