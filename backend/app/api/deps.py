from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ApiToken, AppUser, LoginSession
from app.db.session import get_db
from app.security import hash_token
from app.utils.time import utcnow

SESSION_COOKIE = "fn2t_session"


def _token_from_request(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        return token
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> AppUser:
    token = _token_from_request(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    token_hash = hash_token(token)
    session = db.get(LoginSession, token_hash)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录")
    if session.expires_at <= utcnow():
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    user = db.get(AppUser, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不可用")
    return user


def get_admin_user(user: AppUser = Depends(get_current_user)) -> AppUser:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def create_login_session(
    db: Session, user: AppUser, request: Request, days: int | None = None
) -> tuple[str, LoginSession]:
    from app.security import new_session_token

    days = days or settings.session_days
    token = new_session_token()
    session = LoginSession(
        token_hash=hash_token(token),
        user_id=user.id,
        expires_at=utcnow() + timedelta(days=days),
        user_agent=(request.headers.get("user-agent") or "")[:255],
        ip_address=(request.client.host if request.client else None),
    )
    db.add(session)
    user.last_login_at = utcnow()
    db.commit()
    return token, session


def revoke_session(db: Session, token: str) -> None:
    session = db.get(LoginSession, hash_token(token))
    if session is not None:
        db.delete(session)
        db.commit()


def visible_play_filter(user: AppUser):
    """Non-admin users only see their own fnTV user's records."""
    return None if user.is_admin else user.fn_user_guid


@dataclass
class ApiAuth:
    user: AppUser
    token: ApiToken


def _api_bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    return token or None


def get_api_auth(request: Request, db: Session = Depends(get_db)) -> ApiAuth:
    """Authenticate a personal API token (``fnt_...``), never a login cookie."""
    token = _api_bearer(request)
    if not token or not token.startswith("fnt_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要 API Token：Authorization: Bearer fnt_...",
            headers={"WWW-Authenticate": "Bearer"},
        )
    row = db.scalar(
        select(ApiToken).where(
            ApiToken.token_hash == hash_token(token),
            ApiToken.revoked_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API Token 无效或已撤销")
    if row.expires_at is not None and row.expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API Token 已过期")
    user = db.get(AppUser, row.app_user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不可用")
    row.last_used_at = utcnow()
    db.commit()
    return ApiAuth(user=user, token=row)


def require_api_scope(*scopes: str):
    def dependency(auth: ApiAuth = Depends(get_api_auth)) -> ApiAuth:
        allowed = set(auth.token.scopes or [])
        missing = [scope for scope in scopes if scope not in allowed]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Token 缺少权限: {', '.join(missing)}",
            )
        return auth

    return dependency
