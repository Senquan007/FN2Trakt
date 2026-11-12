from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import user_payload
from app.api.deps import get_admin_user, get_current_user
from app.db.models import AppUser, FnUser, PlayRecord, TraktAccount
from app.db.session import get_db
from app.fntv import FnTvError, read_users
from app.security import hash_password
from app.services.settings_service import fntv_db_path
from app.utils.time import utcnow

router = APIRouter(prefix="/api/users", tags=["users"])


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    role: str = "user"
    fn_user_guid: str | None = None


class UserUpdate(BaseModel):
    is_active: bool | None = None
    role: str | None = None
    fn_user_guid: str | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)


def _ensure_fn_user(db: Session, guid: str) -> bool:
    if db.get(FnUser, guid) is not None:
        return True
    try:
        for row in read_users(fntv_db_path(db)):
            db.merge(
                FnUser(
                    guid=row.guid,
                    username=row.username,
                    is_admin=row.is_admin,
                    status=row.status,
                    last_login_time=row.last_login_time,
                )
            )
        db.commit()
    except FnTvError:
        return False
    return db.get(FnUser, guid) is not None


def _validate_role(role: str) -> str:
    if role not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="角色只能是 admin 或 user")
    return role


@router.get("")
def list_users(admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)):
    users = db.scalars(select(AppUser).order_by(AppUser.id)).all()
    counts = dict(
        db.execute(
            select(PlayRecord.fn_user_guid, func.count(PlayRecord.id))
            .where(PlayRecord.completed.is_(True))
            .group_by(PlayRecord.fn_user_guid)
        ).all()
    )
    bound = {row.app_user_id for row in db.scalars(select(TraktAccount)).all()}
    result = []
    for user in users:
        payload = user_payload(db, user)
        payload["completed_count"] = counts.get(user.fn_user_guid, 0)
        payload["trakt_bound"] = user.id in bound
        result.append(payload)
    return {"items": result}


@router.post("")
def create_user(payload: UserCreate, admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)):
    username = payload.username.strip()
    if db.scalar(select(AppUser).where(func.lower(AppUser.username) == username.lower())):
        raise HTTPException(status_code=400, detail="用户名已存在")
    if payload.fn_user_guid and not _ensure_fn_user(db, payload.fn_user_guid):
        raise HTTPException(status_code=400, detail="飞牛用户不存在，请先刷新飞牛数据")
    user = AppUser(
        username=username,
        password_hash=hash_password(payload.password),
        role=_validate_role(payload.role),
        fn_user_guid=payload.fn_user_guid,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="该飞牛用户已绑定其他账号")
    return {"user": user_payload(db, user)}


@router.patch("/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    if payload.role is not None:
        role = _validate_role(payload.role)
        if user.role == "admin" and role != "admin":
            admin_count = db.scalar(select(func.count(AppUser.id)).where(AppUser.role == "admin")) or 0
            if admin_count <= 1:
                raise HTTPException(status_code=400, detail="至少保留一个管理员")
        user.role = role
    if payload.is_active is not None:
        if not payload.is_active and user.id == admin.id:
            raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
        user.is_active = payload.is_active
    if "fn_user_guid" in payload.model_fields_set:
        if payload.fn_user_guid and not _ensure_fn_user(db, payload.fn_user_guid):
            raise HTTPException(status_code=400, detail="飞牛用户不存在")
        user.fn_user_guid = payload.fn_user_guid or None
    if payload.password:
        user.password_hash = hash_password(payload.password)
    user.updated_at = utcnow()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="该飞牛用户已绑定其他账号")
    return {"user": user_payload(db, user)}


@router.delete("/{user_id}")
def delete_user(user_id: int, admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)):
    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    if user.role == "admin":
        admin_count = db.scalar(select(func.count(AppUser.id)).where(AppUser.role == "admin")) or 0
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="至少保留一个管理员")
    db.delete(user)
    db.commit()
    return {"ok": True}
