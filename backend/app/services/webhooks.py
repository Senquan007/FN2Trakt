"""Outbound webhook notifications for sync failures and unmatched records."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    MediaItem,
    PlayRecord,
    Setting,
    SyncRecord,
    SyncRun,
    TraktAccount,
    WebhookDelivery,
    WebhookEndpoint,
)
from app.db.session import SessionLocal
from app.services.settings_service import set_setting
from app.utils.time import to_iso_z, utcnow

logger = logging.getLogger(__name__)

EVENTS: dict[str, str] = {
    "sync.failed": "同步任务失败或部分失败",
    "sync.unmatched": "存在未匹配 / 上传失败的记录",
    "sync.completed": "同步完成且有新记录上传",
    "backfill.completed": "Trakt 观看历史回填完成",
    "test": "测试通知",
}

DEFAULT_EVENTS = ["sync.failed", "sync.unmatched"]
MAX_ATTEMPTS = 3
RETRY_MINUTES = 5
APP_VERSION = "3.0.0"


class WebhookError(ValueError):
    pass


def validate_url(value: str) -> str:
    url = (value or "").strip()
    if not url or len(url) > 1024:
        raise WebhookError("Webhook URL 不能为空且不能超过 1024 个字符")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WebhookError("Webhook URL 必须是 http:// 或 https:// 地址")
    return url


def validate_events(events: list[str] | None) -> list[str]:
    selected = [event for event in (events or DEFAULT_EVENTS) if event]
    unknown = [event for event in selected if event not in EVENTS]
    if unknown:
        raise WebhookError(f"未知事件: {', '.join(unknown)}")
    if not selected:
        raise WebhookError("至少选择一个事件")
    return list(dict.fromkeys(selected))


def create_endpoint(
    db: Session,
    name: str,
    url: str,
    events: list[str] | None,
    secret: str | None = None,
    enabled: bool = True,
) -> WebhookEndpoint:
    if not (name or "").strip():
        raise WebhookError("请填写名称")
    row = WebhookEndpoint(
        name=name.strip()[:64],
        url=validate_url(url),
        events=validate_events(events),
        secret=(secret or "").strip() or None,
        enabled=enabled,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_endpoint(
    db: Session,
    row: WebhookEndpoint,
    *,
    name: str | None = None,
    url: str | None = None,
    events: list[str] | None = None,
    secret: str | None = None,
    clear_secret: bool = False,
    enabled: bool | None = None,
) -> WebhookEndpoint:
    if name is not None:
        if not name.strip():
            raise WebhookError("名称不能为空")
        row.name = name.strip()[:64]
    if url is not None:
        row.url = validate_url(url)
    if events is not None:
        row.events = validate_events(events)
    if clear_secret:
        row.secret = None
    elif secret is not None and secret.strip():
        row.secret = secret.strip()
    if enabled is not None:
        row.enabled = enabled
    db.commit()
    db.refresh(row)
    return row


def public_endpoint(row: WebhookEndpoint) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "url": row.url,
        "events": row.events or [],
        "enabled": row.enabled,
        "has_secret": bool(row.secret),
        "created_at": to_iso_z(row.created_at),
        "updated_at": to_iso_z(row.updated_at),
        "last_delivery_at": to_iso_z(row.last_delivery_at),
        "last_status": row.last_status,
        "last_error": row.last_error,
    }


def public_delivery(row: WebhookDelivery) -> dict[str, Any]:
    return {
        "id": row.id,
        "endpoint_id": row.endpoint_id,
        "event": row.event,
        "status": row.status,
        "attempts": row.attempts,
        "response_status": row.response_status,
        "response_body": row.response_body,
        "error": row.error,
        "created_at": to_iso_z(row.created_at),
        "delivered_at": to_iso_z(row.delivered_at),
        "next_retry_at": to_iso_z(row.next_retry_at),
    }


def _signature(secret: str | None, body: bytes) -> str | None:
    if not secret:
        return None
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _run_delivery(delivery_id: int) -> None:
    db = SessionLocal()
    try:
        delivery = db.get(WebhookDelivery, delivery_id)
        if delivery is None:
            return
        endpoint = db.get(WebhookEndpoint, delivery.endpoint_id)
        if endpoint is None or not endpoint.enabled:
            delivery.status = "failed"
            delivery.error = "Webhook 已禁用或不存在"
            delivery.next_retry_at = None
            db.commit()
            return
        payload = delivery.payload_json or {}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"FN2Trakt/{APP_VERSION}",
            "X-FN2Trakt-Event": delivery.event,
            "X-FN2Trakt-Delivery": str(delivery.id),
        }
        signature = _signature(endpoint.secret, body)
        if signature:
            headers["X-FN2Trakt-Signature"] = signature
        delivery.attempts = (delivery.attempts or 0) + 1
        db.commit()
        try:
            with httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False) as client:
                response = client.post(endpoint.url, content=body, headers=headers)
            delivery.response_status = response.status_code
            delivery.response_body = (response.text or "")[:2000]
            if 200 <= response.status_code < 300:
                delivery.status = "success"
                delivery.error = None
                delivery.delivered_at = utcnow()
                delivery.next_retry_at = None
            else:
                delivery.status = "failed"
                delivery.error = f"HTTP {response.status_code}"
                delivery.next_retry_at = (
                    utcnow() + timedelta(minutes=RETRY_MINUTES)
                    if delivery.attempts < MAX_ATTEMPTS
                    else None
                )
        except Exception as exc:  # network errors must not break the sync
            delivery.status = "failed"
            delivery.error = str(exc)[:1000]
            delivery.response_status = None
            delivery.next_retry_at = (
                utcnow() + timedelta(minutes=RETRY_MINUTES)
                if delivery.attempts < MAX_ATTEMPTS
                else None
            )
        endpoint.last_delivery_at = utcnow()
        endpoint.last_status = delivery.status
        endpoint.last_error = delivery.error
        db.commit()
        logger.info("webhook delivery %s event=%s status=%s", delivery.id, delivery.event, delivery.status)
    except Exception:
        db.rollback()
        logger.exception("webhook delivery failed")
    finally:
        db.close()


def _spawn(delivery_id: int) -> None:
    threading.Thread(target=_run_delivery, args=(delivery_id,), daemon=True).start()


def emit_event(
    db: Session,
    event: str,
    data: dict[str, Any],
    *,
    endpoint_ids: list[int] | None = None,
) -> int:
    if event not in EVENTS:
        raise WebhookError(f"未知事件: {event}")
    stmt = select(WebhookEndpoint).where(WebhookEndpoint.enabled.is_(True))
    if endpoint_ids is not None:
        stmt = stmt.where(WebhookEndpoint.id.in_(endpoint_ids))
    endpoints = [
        row for row in db.scalars(stmt).all() if event in (row.events or [])
    ]
    if not endpoints:
        return 0
    payload = {
        "event": event,
        "version": APP_VERSION,
        "sent_at": to_iso_z(utcnow()),
        "data": data,
    }
    deliveries = []
    for endpoint in endpoints:
        delivery = WebhookDelivery(
            endpoint_id=endpoint.id,
            event=event,
            payload_json=payload,
            status="pending",
        )
        db.add(delivery)
        deliveries.append(delivery)
    db.commit()
    for delivery in deliveries:
        _spawn(delivery.id)
    return len(deliveries)


def _record_sample(
    db: Session, account: TraktAccount, limit: int = 20
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(SyncRecord, PlayRecord, MediaItem)
        .join(PlayRecord, PlayRecord.id == SyncRecord.play_id)
        .outerjoin(MediaItem, MediaItem.fn_guid == PlayRecord.fn_item_guid)
        .where(
            SyncRecord.trakt_account_id == account.id,
            SyncRecord.status.in_(["blocked", "failed"]),
        )
        .order_by(SyncRecord.updated_at.desc())
        .limit(limit)
    ).all()
    samples = []
    for record, _play, media in rows:
        if media is None:
            title = "未知媒体"
            kind = "unknown"
        elif media.fn_type == "Episode":
            title = f"{media.show_title or media.title} - S{media.season_number or 0:02d}E{media.episode_number or 0:02d}"
            kind = "episode"
        else:
            title = media.title
            kind = "movie"
        samples.append({"title": title, "type": kind, "status": record.status, "reason": record.error})
    return samples


def notify_sync_run(db: Session, run: SyncRun, app_user: AppUser) -> None:
    """Emit failure/unmatched events once at the end of a sync run."""
    try:
        account = db.scalar(select(TraktAccount).where(TraktAccount.app_user_id == app_user.id))
        if account is None:
            return
        samples = _record_sample(db, account)
        base = {
            "run_id": run.id,
            "trigger": run.trigger,
            "status": run.status,
            "message": run.message,
            "app_user": app_user.username,
            "trakt_user": account.trakt_username,
            "scanned": run.scanned,
            "uploaded": run.uploaded,
            "failed": run.failed,
        }
        if run.status in {"failed", "partial"} or run.failed:
            emit_event(db, "sync.failed", {**base, "records": samples})
        if samples:
            signature = hashlib.sha256(
                json.dumps(sorted((row["title"], row["status"]) for row in samples), ensure_ascii=False).encode()
            ).hexdigest()
            previous = db.get(Setting, "webhook.unmatched_signature")
            if previous is None or previous.value != signature:
                sent = emit_event(db, "sync.unmatched", {**base, "records": samples})
                if sent:
                    set_setting(db, "webhook.unmatched_signature", signature)
                    db.commit()
        if run.status == "success" and run.uploaded and not samples:
            emit_event(db, "sync.completed", base)
    except Exception:
        logger.exception("failed to emit sync webhook")


def retry_delivery(db: Session, delivery: WebhookDelivery) -> None:
    if delivery.attempts >= MAX_ATTEMPTS:
        raise WebhookError("该投递已达到最大重试次数")
    delivery.status = "pending"
    delivery.next_retry_at = None
    db.commit()
    _spawn(delivery.id)


def retry_due(db: Session) -> int:
    rows = db.scalars(
        select(WebhookDelivery).where(
            WebhookDelivery.status == "failed",
            WebhookDelivery.attempts < MAX_ATTEMPTS,
            WebhookDelivery.next_retry_at.is_not(None),
            WebhookDelivery.next_retry_at <= utcnow(),
        )
    ).all()
    for row in rows:
        row.status = "pending"
        row.next_retry_at = None
    if rows:
        db.commit()
        for row in rows:
            _spawn(row.id)
    return len(rows)


def send_test(db: Session, endpoint: WebhookEndpoint) -> WebhookDelivery:
    payload = {
        "event": "test",
        "version": APP_VERSION,
        "sent_at": to_iso_z(utcnow()),
        "data": {
            "message": "这是一条来自 FN2Trakt 的测试通知",
            "endpoint": endpoint.name,
        },
    }
    delivery = WebhookDelivery(
        endpoint_id=endpoint.id,
        event="test",
        payload_json=payload,
        status="pending",
    )
    db.add(delivery)
    db.commit()
    _spawn(delivery.id)
    return delivery
