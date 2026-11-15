from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user
from app.db.models import AppUser, TraktAccount
from app.db.session import get_db
from app.fntv import FnTvError
from app.services.fntv_writeback import (
    FnTvWritebackError,
    apply_writeback,
    list_backups,
    preview_writeback,
    restore_fntv,
)
from app.trakt.client import TraktError

router = APIRouter(prefix="/api/fntv", tags=["fntv-writeback"])


class WritebackPayload(BaseModel):
    account_id: int | None = None
    confirm: bool = False
    expected_total: int | None = None
    pull: bool = False
    include_written: bool = False


class RestorePayload(BaseModel):
    backup: str
    confirm: bool = False


def _account(db: Session, account_id: int | None) -> TraktAccount:
    if account_id is not None:
        account = db.get(TraktAccount, account_id)
    else:
        account = db.scalar(select(TraktAccount).order_by(TraktAccount.id))
    if account is None:
        raise HTTPException(status_code=400, detail="没有可用的 Trakt 账号")
    return account


@router.get("/writeback/preview")
def writeback_preview(
    account_id: int | None = None,
    include_written: bool = False,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    account = _account(db, account_id)
    try:
        return preview_writeback(db, account, include_written=include_written)
    except (FnTvWritebackError, FnTvError, TraktError, sqlite3.Error) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/writeback/preview")
def writeback_preview_post(
    payload: WritebackPayload,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """Preview that may first pull the Trakt history (network + local write)."""
    account = _account(db, payload.account_id)
    try:
        return preview_writeback(db, account, pull=payload.pull, include_written=payload.include_written)
    except (FnTvWritebackError, FnTvError, TraktError, sqlite3.Error) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/writeback/apply")
def writeback_apply(
    payload: WritebackPayload,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="请先确认写入飞牛数据库")
    account = _account(db, payload.account_id)
    try:
        return apply_writeback(
            db,
            account,
            expected_total=payload.expected_total,
            include_written=payload.include_written,
        )
    except (FnTvWritebackError, FnTvError, TraktError, sqlite3.Error) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/backups")
def backups(admin: AppUser = Depends(get_admin_user)):
    return {"items": list_backups()}


@router.post("/restore")
def restore(
    payload: RestorePayload,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="请先确认恢复飞牛数据库")
    try:
        return restore_fntv(db, payload.backup)
    except (FnTvWritebackError, FnTvError, sqlite3.Error) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
