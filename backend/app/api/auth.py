from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    SESSION_COOKIE,
    create_login_session,
    get_current_user,
    revoke_session,
)
from app.config import settings
from app.db.models import AppUser, FnUser, TraktAccount
from app.db.session import get_db
from app.fntv import FnTvError, inspect_database, read_snapshot, read_users
from app.security import hash_password, verify_password
from app.services.ingest import ingest_snapshot
from app.services.matching import ensure_matches
from app.services.settings_service import fntv_db_path, get_float
from app.trakt.auth import account_public
from app.utils.time import utcnow


router = APIRouter(prefix="/api/auth", tags=["auth"])
setup_router = APIRouter(prefix="/api/setup", tags=["setup"])


class LoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class SetupPayload(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    fn_user_guid: str | None = None


class PasswordPayload(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


def user_payload(db: Session, user: AppUser) -> dict:
    fn_user = db.get(FnUser, user.fn_user_guid) if user.fn_user_guid else None
    account = db.scalar(select(TraktAccount).where(TraktAccount.app_user_id == user.id))
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "fn_user_guid": user.fn_user_guid,
        "fn_username": fn_user.username if fn_user else None,
        "created_at": user.created_at.isoformat() + "Z",
        "last_login_at": user.last_login_at.isoformat() + "Z" if user.last_login_at else None,
        "trakt": account_public(account),
    }


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


@router.post("/login")
def login(payload: LoginPayload, request: Request, response: Response, db: Session = Depends(get_db)):
    username = payload.username.strip()
    user = db.scalar(select(AppUser).where(func.lower(AppUser.username) == username.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    token, _ = create_login_session(db, user, request)
    _set_session_cookie(response, token)
    return {"user": user_payload(db, user)}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        revoke_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"user": user_payload(db, user)}


@router.post("/password")
def change_password(
    payload: PasswordPayload,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    user.password_hash = hash_password(payload.new_password)
    user.updated_at = utcnow()
    db.commit()
    return {"ok": True}


@setup_router.get("/status")
def setup_status(db: Session = Depends(get_db)):
    user_count = db.scalar(select(func.count(AppUser.id))) or 0
    if user_count > 0:
        return {"needs_setup": False, "fntv": None, "fntv_users": []}
    path = fntv_db_path(db)
    info = inspect_database(path)
    users: list[dict] = []
    if info.get("ok"):
        try:
            users = [
                {"guid": u.guid, "username": u.username, "is_admin": u.is_admin, "status": u.status}
                for u in read_users(path)
            ]
        except FnTvError as exc:
            info["error"] = str(exc)
    return {
        "needs_setup": user_count == 0,
        "fntv": info,
        "fntv_users": users,
    }


@setup_router.post("")
def setup(payload: SetupPayload, request: Request, response: Response, db: Session = Depends(get_db)):
    if (db.scalar(select(func.count(AppUser.id))) or 0) > 0:
        raise HTTPException(status_code=400, detail="系统已完成初始化")
    username = payload.username.strip()
    if len(username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少 2 个字符")
    if payload.fn_user_guid:
        fn_user = db.get(FnUser, payload.fn_user_guid)
        if fn_user is None:
            # Populate the cache once so the binding can be validated.
            path = fntv_db_path(db)
            try:
                for item in read_users(path):
                    db.merge(FnUser(guid=item.guid, username=item.username, is_admin=item.is_admin, status=item.status))
                db.commit()
            except FnTvError as exc:
                raise HTTPException(status_code=400, detail=f"无法读取飞牛用户: {exc}")
            if db.get(FnUser, payload.fn_user_guid) is None:
                raise HTTPException(status_code=400, detail="飞牛用户不存在")
    user = AppUser(
        username=username,
        password_hash=hash_password(payload.password),
        role="admin",
        fn_user_guid=payload.fn_user_guid,
        is_active=True,
    )
    db.add(user)
    db.commit()

    # Warm the local cache so the first dashboard is not empty.
    try:
        snapshot = read_snapshot(fntv_db_path(db), get_float(db, "sync.watched_threshold", 80.0))
        ingest_snapshot(db, snapshot)
        db.commit()
        ensure_matches(db, allow_search=False)
    except Exception:
        db.rollback()

    token, _ = create_login_session(db, user, request)
    _set_session_cookie(response, token)
    return {"user": user_payload(db, user)}
