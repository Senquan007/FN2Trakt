from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ApiToken, AppUser
from app.security import hash_token
from app.utils.time import to_iso_z, utcnow

SCOPES: dict[str, str] = {
    "history:read": "读取本地 Trakt 观看历史、统计与导出",
    "library:read": "读取飞牛媒体库与本地播放状态",
    "history:write": "从 Trakt 拉取/刷新自己的观看历史",
    "sync:write": "触发同步任务（仅管理员）",
}

ADMIN_SCOPES = {"sync:write"}
DEFAULT_SCOPES = ["history:read", "library:read"]


class TokenError(ValueError):
    pass


def validate_scopes(scopes: list[str] | None, is_admin: bool) -> list[str]:
    selected = [scope for scope in (scopes or DEFAULT_SCOPES) if scope]
    unknown = [scope for scope in selected if scope not in SCOPES]
    if unknown:
        raise TokenError(f"未知权限: {', '.join(unknown)}")
    if not selected:
        raise TokenError("至少选择一个权限")
    if not is_admin and any(scope in ADMIN_SCOPES for scope in selected):
        raise TokenError("当前账号不能创建包含管理员权限的 Token")
    return list(dict.fromkeys(selected))


def create_token(
    db: Session,
    user: AppUser,
    name: str,
    scopes: list[str] | None,
    expires_days: int | None = None,
) -> tuple[ApiToken, str]:
    clean_name = name.strip()
    if not clean_name:
        raise TokenError("请填写 Token 名称")
    if len(clean_name) > 64:
        raise TokenError("Token 名称不能超过 64 个字符")
    selected = validate_scopes(scopes, user.is_admin)
    token = "fnt_" + secrets.token_urlsafe(32)
    row = ApiToken(
        app_user_id=user.id,
        name=clean_name,
        token_prefix=token[:12],
        token_hash=hash_token(token),
        scopes=selected,
        expires_at=utcnow() + timedelta(days=expires_days) if expires_days and expires_days > 0 else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, token


def list_tokens(db: Session, user: AppUser, include_revoked: bool = False) -> list[ApiToken]:
    stmt = select(ApiToken).where(ApiToken.app_user_id == user.id).order_by(ApiToken.id.desc())
    if not include_revoked:
        stmt = stmt.where(ApiToken.revoked_at.is_(None))
    return list(db.scalars(stmt).all())


def revoke_token(db: Session, user: AppUser, token_id: int) -> bool:
    row = db.get(ApiToken, token_id)
    if row is None or row.app_user_id != user.id:
        return False
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        db.commit()
    return True


def public_token(row: ApiToken) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "prefix": row.token_prefix,
        "scopes": row.scopes or [],
        "created_at": to_iso_z(row.created_at),
        "last_used_at": to_iso_z(row.last_used_at),
        "expires_at": to_iso_z(row.expires_at),
        "revoked_at": to_iso_z(row.revoked_at),
        "revoked": row.revoked_at is not None,
    }
