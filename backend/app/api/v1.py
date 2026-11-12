"""Versioned personal API for FN2Trakt.

All endpoints except /health use a personal bearer token (``fnt_...``) created
on the developer page.  Tokens are scoped; the token owner is always the data
owner, so one user cannot read another user's history.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import ApiAuth, require_api_scope
from app.db.models import (
    MediaItem,
    PlayRecord,
    SyncRecord,
    SyncRun,
    TraktAccount,
    TraktHistory,
)
from app.db.session import get_db
from app.fntv.reader import read_library
from app.services.settings_service import fntv_db_path
from app.services.sync import start_sync
from app.services.trakt_history import (
    history_public,
    history_stats,
    pull_history,
)
from app.trakt.auth import account_public
from app.utils.time import to_iso_z

router = APIRouter(prefix="/api/v1", tags=["v1"])


def _account(db: Session, auth: ApiAuth, account_id: int | None = None) -> TraktAccount | None:
    if account_id is not None:
        if not auth.user.is_admin:
            raise HTTPException(status_code=403, detail="只有管理员可以指定 account_id")
        account = db.get(TraktAccount, account_id)
        return account
    return db.scalar(select(TraktAccount).where(TraktAccount.app_user_id == auth.user.id))


def _require_account(db: Session, auth: ApiAuth, account_id: int | None = None) -> TraktAccount:
    account = _account(db, auth, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="尚未绑定 Trakt 账号")
    return account


def _date_bounds(from_date: date | None, to_date: date | None) -> tuple[datetime | None, datetime | None]:
    start = datetime.combine(from_date, time.min) if from_date else None
    end = datetime.combine(to_date, time.max) if to_date else None
    return start, end


def _history_stmt(account_id: int, **filters: Any):
    stmt = select(TraktHistory).where(TraktHistory.trakt_account_id == account_id)
    kind = filters.get("kind")
    if kind in {"movie", "episode"}:
        stmt = stmt.where(TraktHistory.history_type == kind)
    status = filters.get("status")
    if status in {"matched", "library_only", "not_in_library"}:
        stmt = stmt.where(TraktHistory.match_status == status)
    query = (filters.get("query") or "").strip()
    if query:
        like = f"%{query}%"
        stmt = stmt.where(or_(TraktHistory.title.ilike(like), TraktHistory.show_title.ilike(like)))
    if filters.get("start"):
        stmt = stmt.where(TraktHistory.watched_at >= filters["start"])
    if filters.get("end"):
        stmt = stmt.where(TraktHistory.watched_at <= filters["end"])
    return stmt


def _completed_map(db: Session, rows: list[TraktHistory]) -> dict[int, bool]:
    ids = {row.play_id for row in rows if row.play_id}
    if not ids:
        return {}
    return {
        play.id: bool(play.completed)
        for play in db.scalars(select(PlayRecord).where(PlayRecord.id.in_(ids))).all()
    }


@router.get("/health")
def health():
    return {"ok": True, "api": "v1"}


@router.get("/me")
def me(auth: ApiAuth = Depends(require_api_scope("history:read")), db: Session = Depends(get_db)):
    account = _account(db, auth)
    count = (
        db.scalar(
            select(func.count(TraktHistory.id)).where(
                TraktHistory.trakt_account_id == account.id
            )
        )
        if account
        else 0
    )
    return {
        "user": {"id": auth.user.id, "username": auth.user.username, "is_admin": auth.user.is_admin},
        "scopes": auth.token.scopes or [],
        "token": {"id": auth.token.id, "name": auth.token.name, "prefix": auth.token.token_prefix},
        "account": account_public(account),
        "history_count": count or 0,
    }


@router.get("/history")
def history(
    kind: str | None = Query(default=None, alias="type"),
    status: str | None = None,
    q: str | None = None,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    account_id: int | None = None,
    auth: ApiAuth = Depends(require_api_scope("history:read")),
    db: Session = Depends(get_db),
):
    account = _require_account(db, auth, account_id)
    start, end = _date_bounds(from_date, to_date)
    base = _history_stmt(account.id, kind=kind, status=status, query=q, start=start, end=end)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    order_by = TraktHistory.watched_at.asc() if order == "asc" else TraktHistory.watched_at.desc()
    rows = db.scalars(
        base.order_by(order_by, TraktHistory.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    completed = _completed_map(db, rows)
    return {
        "items": [history_public(row, completed.get(row.play_id or 0, False)) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": page * page_size < total,
    }


@router.get("/history/recent")
def recent_history(
    limit: int = Query(default=10, ge=1, le=50),
    kind: str | None = Query(default=None, alias="type"),
    auth: ApiAuth = Depends(require_api_scope("history:read")),
    db: Session = Depends(get_db),
):
    account = _require_account(db, auth)
    stmt = _history_stmt(account.id, kind=kind).order_by(TraktHistory.watched_at.desc()).limit(limit)
    rows = db.scalars(stmt).all()
    completed = _completed_map(db, rows)
    return {"items": [history_public(row, completed.get(row.play_id or 0, False)) for row in rows]}


@router.get("/history/stats")
def stats(
    auth: ApiAuth = Depends(require_api_scope("history:read")),
    db: Session = Depends(get_db),
):
    account = _require_account(db, auth)
    return history_stats(db, account)


@router.get("/history/export")
def export_history(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    kind: str | None = Query(default=None, alias="type"),
    status: str | None = None,
    q: str | None = None,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    auth: ApiAuth = Depends(require_api_scope("history:read")),
    db: Session = Depends(get_db),
):
    account = _require_account(db, auth)
    start, end = _date_bounds(from_date, to_date)
    stmt = _history_stmt(account.id, kind=kind, status=status, query=q, start=start, end=end)
    rows = db.scalars(stmt.order_by(TraktHistory.watched_at.desc()).limit(50000)).all()
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["watched_at", "type", "title", "show_title", "season", "episode", "match_status", "media_guid"])
        for row in rows:
            writer.writerow(
                [
                    to_iso_z(row.watched_at),
                    row.history_type,
                    row.title,
                    row.show_title or "",
                    row.season_number or "",
                    row.episode_number or "",
                    row.match_status,
                    row.media_guid or "",
                ]
            )
        return Response(
            content="\ufeff" + buffer.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="fn2trakt-history.csv"'},
        )
    completed = _completed_map(db, rows)
    return {
        "exported_at": to_iso_z(datetime.utcnow()),
        "count": len(rows),
        "items": [history_public(row, completed.get(row.play_id or 0, False)) for row in rows],
    }


@router.get("/library")
def library(
    q: str | None = None,
    kind: str | None = Query(default=None, alias="type", pattern="^(movie|episode)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    auth: ApiAuth = Depends(require_api_scope("library:read")),
    db: Session = Depends(get_db),
):
    try:
        rows = read_library(fntv_db_path(db))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无法读取飞牛媒体库: {exc}") from exc
    if kind == "movie":
        rows = [row for row in rows if row["fn_type"] == "Movie"]
    elif kind == "episode":
        rows = [row for row in rows if row["fn_type"] == "Episode"]
    if q:
        needle = q.strip().casefold()
        rows = [
            row
            for row in rows
            if needle in str(row.get("title") or "").casefold()
            or needle in str(row.get("show_title") or "").casefold()
        ]
    rows.sort(
        key=lambda row: (
            str(row.get("show_title") or row.get("title") or "").casefold(),
            int(row.get("season_number") or 0),
            int(row.get("episode_number") or 0),
        )
    )
    total = len(rows)
    page_rows = rows[(page - 1) * page_size : page * page_size]
    plays: dict[str, PlayRecord] = {}
    if auth.user.fn_user_guid and page_rows:
        plays = {
            row.fn_item_guid: row
            for row in db.scalars(
                select(PlayRecord).where(
                    PlayRecord.fn_user_guid == auth.user.fn_user_guid,
                    PlayRecord.fn_item_guid.in_([row["guid"] for row in page_rows]),
                )
            ).all()
        }
    return {
        "items": [
            {
                "id": row["guid"],
                "type": "movie" if row["fn_type"] == "Movie" else "episode",
                "title": row.get("title"),
                "show_title": row.get("show_title"),
                "year": row.get("year"),
                "season": row.get("season_number"),
                "episode": row.get("episode_number"),
                "tmdb_id": row.get("tmdb_id"),
                "imdb_id": row.get("imdb_id"),
                "episode_imdb_id": row.get("episode_imdb_id"),
                "runtime_minutes": row.get("runtime_minutes"),
                "has_play": row["guid"] in plays,
                "completed": bool(plays[row["guid"]].completed) if row["guid"] in plays else False,
                "progress": round(plays[row["guid"]].progress_percent or 0, 1) if row["guid"] in plays else 0,
            }
            for row in page_rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": page * page_size < total,
    }


@router.get("/sync/status")
def sync_status(
    auth: ApiAuth = Depends(require_api_scope("history:read")),
    db: Session = Depends(get_db),
):
    account = _account(db, auth)
    if account is None:
        return {"bound": False, "counts": {}, "runs": []}
    counts = {
        status: count
        for status, count in db.execute(
            select(SyncRecord.status, func.count(SyncRecord.id))
            .where(SyncRecord.trakt_account_id == account.id)
            .group_by(SyncRecord.status)
        ).all()
    }
    runs = db.scalars(
        select(SyncRun)
        .where(SyncRun.app_user_id == auth.user.id)
        .order_by(SyncRun.id.desc())
        .limit(5)
    ).all()
    return {
        "bound": True,
        "account": account_public(account),
        "counts": counts,
        "runs": [
            {
                "id": run.id,
                "trigger": run.trigger,
                "status": run.status,
                "started_at": to_iso_z(run.started_at),
                "finished_at": to_iso_z(run.finished_at),
                "scanned": run.scanned,
                "uploaded": run.uploaded,
                "failed": run.failed,
                "message": run.message,
            }
            for run in runs
        ],
    }


@router.post("/sync/run")
def run_sync(
    auth: ApiAuth = Depends(require_api_scope("sync:write")),
    db: Session = Depends(get_db),
):
    if not auth.user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    run = start_sync(auth.user.id, "api")
    if run is None:
        raise HTTPException(status_code=409, detail="已有同步任务正在运行")
    return {"run_id": run.id, "status": "queued"}


@router.post("/history/refresh")
def refresh_history(
    auth: ApiAuth = Depends(require_api_scope("history:write")),
    db: Session = Depends(get_db),
):
    account = _require_account(db, auth)
    result = pull_history(db, account)
    return result
