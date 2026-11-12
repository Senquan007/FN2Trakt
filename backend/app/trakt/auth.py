from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppUser, TraktAccount, TraktAuthSession
from app.services.credentials import active_bundle, bundle_for_account
from app.trakt.client import TraktAuthError, TraktClient, TraktError
from app.utils.time import ceil_seconds, to_iso_z, utcnow


def _client(db: Session) -> TraktClient:
    bundle = active_bundle(db)
    if not bundle.client_id:
        raise TraktError("尚未配置 Trakt 应用凭据，请先在系统设置中添加")
    return TraktClient(bundle.client_id, bundle.client_secret)


def account_public(account: TraktAccount | None) -> dict[str, Any] | None:
    if account is None:
        return None
    return {
        "id": account.id,
        "trakt_username": account.trakt_username,
        "trakt_slug": account.trakt_slug,
        "trakt_user_id": account.trakt_user_id,
        "avatar_url": account.avatar_url,
        "status": account.status,
        "last_error": account.last_error,
        "authorized_at": to_iso_z(account.last_auth_at or account.created_at),
        "token_expires_at": to_iso_z(account.token_expires_at),
        "can_refresh": bool(account.refresh_token),
    }


def get_account(db: Session, app_user_id: int) -> TraktAccount | None:
    return db.scalar(select(TraktAccount).where(TraktAccount.app_user_id == app_user_id))


def start_device_auth(db: Session, app_user: AppUser) -> dict[str, Any]:
    with _client(db) as client:
        payload = client.device_code()
    if not payload or not payload.get("device_code"):
        raise TraktError("Trakt 未返回设备码，请检查 Client ID 是否正确")

    expires_in = int(payload.get("expires_in") or 600)
    interval = max(1, int(payload.get("interval") or 5))
    auth = TraktAuthSession(
        id=str(uuid.uuid4()),
        app_user_id=app_user.id,
        device_code=payload["device_code"],
        user_code=payload.get("user_code") or "",
        verification_url=payload.get("verification_url") or "https://auth.trakt.tv/activate",
        expires_at=utcnow() + timedelta(seconds=expires_in),
        interval_seconds=interval,
        status="pending",
    )
    db.add(auth)
    db.commit()

    return {
        "id": auth.id,
        "user_code": auth.user_code,
        "verification_url": auth.verification_url,
        "expires_in": expires_in,
        "expires_at": to_iso_z(auth.expires_at),
        "interval": interval,
        "seconds_remaining": ceil_seconds(auth.expires_at),
        "status": auth.status,
    }


def auth_status(db: Session, auth_id: str, app_user: AppUser) -> dict[str, Any]:
    auth = db.get(TraktAuthSession, auth_id)
    if auth is None or auth.app_user_id != app_user.id:
        raise TraktError("绑定会话不存在或已失效")

    if auth.status == "authorized":
        account = get_account(db, app_user.id)
        return {"status": "authorized", "account": account_public(account), "seconds_remaining": 0}
    if auth.status in {"expired", "denied", "error"}:
        return {
            "status": auth.status,
            "error": auth.error,
            "seconds_remaining": ceil_seconds(auth.expires_at),
        }
    if utcnow() >= auth.expires_at:
        auth.status = "expired"
        auth.error = "授权码已过期，请重新生成"
        db.commit()
        return {"status": "expired", "error": auth.error, "seconds_remaining": 0}

    # Be a good citizen: never poll faster than the interval Trakt returned.
    if auth.last_polled_at is not None:
        next_poll = auth.last_polled_at + timedelta(seconds=auth.interval_seconds)
        if utcnow() < next_poll:
            return {
                "status": "pending",
                "user_code": auth.user_code,
                "verification_url": auth.verification_url,
                "seconds_remaining": ceil_seconds(auth.expires_at),
                "retry_in": ceil_seconds(next_poll),
            }

    auth.last_polled_at = utcnow()
    db.commit()

    with _client(db) as client:
        status_code, payload = client.device_token(auth.device_code)
        if status_code == 200 and isinstance(payload, dict) and payload.get("access_token"):
            try:
                _save_account(db, app_user, client, payload)
            except TraktError as exc:
                auth.status = "error"
                auth.error = f"授权成功但保存账号失败: {exc}"
                db.commit()
                return {"status": "error", "error": auth.error, "seconds_remaining": 0}
            auth.status = "authorized"
            auth.error = None
            db.commit()
            return {
                "status": "authorized",
                "account": account_public(get_account(db, app_user.id)),
                "seconds_remaining": 0,
            }

    if status_code == 400:
        db.commit()
        return {
            "status": "pending",
            "user_code": auth.user_code,
            "verification_url": auth.verification_url,
            "seconds_remaining": ceil_seconds(auth.expires_at),
            "retry_in": auth.interval_seconds,
        }

    messages = {
        404: "设备码无效，请重新生成",
        409: "该授权码已被使用，请重新生成",
        410: "授权码已过期，请重新生成",
        418: "你在 Trakt 上拒绝了本次授权",
        429: "轮询过于频繁，已自动降速",
    }
    if status_code == 429:
        db.commit()
        return {
            "status": "pending",
            "user_code": auth.user_code,
            "verification_url": auth.verification_url,
            "seconds_remaining": ceil_seconds(auth.expires_at),
            "retry_in": max(10, auth.interval_seconds * 2),
        }

    auth.status = "denied" if status_code == 418 else "error"
    auth.error = messages.get(status_code, f"Trakt 返回异常状态 {status_code}")
    db.commit()
    return {"status": auth.status, "error": auth.error, "seconds_remaining": 0}


def _save_account(
    db: Session, app_user: AppUser, client: TraktClient, payload: dict[str, Any]
) -> TraktAccount:
    access_token = str(payload["access_token"])
    refresh_token = str(payload.get("refresh_token") or "")
    expires_in = int(payload.get("expires_in") or 0)
    expires_at = utcnow() + timedelta(seconds=expires_in) if expires_in else None

    profile: dict[str, Any] = {}
    try:
        profile = client.me(access_token) or {}
    except TraktError:
        profile = {}

    bundle = active_bundle(db)
    account = get_account(db, app_user.id)
    if account is None:
        account = TraktAccount(app_user_id=app_user.id, access_token=access_token, refresh_token=refresh_token)
        db.add(account)

    account.credential_id = bundle.credential_id
    account.access_token = access_token
    account.refresh_token = refresh_token or account.refresh_token
    account.token_expires_at = expires_at
    account.scope = str(payload.get("scope") or "public")
    account.status = "active"
    account.last_error = None
    account.last_auth_at = utcnow()
    if profile:
        account.trakt_username = profile.get("username") or account.trakt_username
        account.trakt_slug = (profile.get("ids") or {}).get("slug") or account.trakt_slug
        account.trakt_user_id = (profile.get("ids") or {}).get("trakt") or account.trakt_user_id
        images = profile.get("images") or {}
        avatar = images.get("avatar") or {}
        account.avatar_url = avatar.get("full") or account.avatar_url
    db.flush()
    return account


def ensure_access_token(db: Session, account: TraktAccount, force_refresh: bool = False) -> str:
    """Refresh when the token is close to expiry; returns a usable access token."""
    needs_refresh = force_refresh
    if not needs_refresh and account.token_expires_at is not None:
        needs_refresh = account.token_expires_at - utcnow() < timedelta(hours=12)
    if not needs_refresh:
        return account.access_token
    if not account.refresh_token:
        raise TraktAuthError("Trakt 授权已过期且没有 refresh_token，请重新绑定")

    bundle = bundle_for_account(db, account)
    if not bundle.client_id:
        raise TraktAuthError("尚未配置 Trakt 应用凭据，请先在系统设置中添加")
    try:
        with TraktClient(bundle.client_id, bundle.client_secret) as client:
            payload = client.refresh(account.refresh_token, bundle.redirect_uri)
    except TraktError as exc:
        account.status = "error"
        account.last_error = str(exc)
        db.commit()
        raise TraktAuthError(f"刷新 Trakt 授权失败: {exc}") from exc

    access_token = payload.get("access_token")
    if not access_token:
        raise TraktAuthError("Trakt 刷新响应缺少 access_token")
    expires_in = int(payload.get("expires_in") or 0)
    account.access_token = str(access_token)
    if payload.get("refresh_token"):
        account.refresh_token = str(payload["refresh_token"])
    account.token_expires_at = utcnow() + timedelta(seconds=expires_in) if expires_in else None
    account.status = "active"
    account.last_error = None
    account.last_refresh_at = utcnow()
    db.commit()
    return account.access_token


def disconnect(db: Session, app_user: AppUser) -> None:
    account = get_account(db, app_user.id)
    if account is not None:
        db.delete(account)
    # Remove any lingering pending auth sessions.
    for auth in db.scalars(select(TraktAuthSession).where(TraktAuthSession.app_user_id == app_user.id)):
        db.delete(auth)
    db.commit()
