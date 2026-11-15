"""Outbound webhook notifications for sync failures and unmatched records.

Three delivery shapes are supported:

* ``generic``  – the raw FN2Trakt JSON document plus ``X-FN2Trakt-Signature``
  (HMAC-SHA256 of the body), for self-hosted receivers / Home Assistant.
* ``feishu``   – 飞书自定义机器人.  The timestamp and signature must live *inside*
  the JSON body and the message must use ``msg_type``/``content``; sending the
  generic document is what produces ``code 19021 sign match fail``.
* ``dingtalk`` / ``wecom`` – 钉钉加签与企业微信群机器人 markdown messages.

The format is stored per endpoint and auto-detected from the URL when unset,
so endpoints created by older versions keep working.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
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
from app.utils.time import to_iso_shanghai, to_iso_z, to_text_shanghai, utcnow

logger = logging.getLogger(__name__)

EVENTS: dict[str, str] = {
    "sync.failed": "同步任务失败或部分失败",
    "sync.unmatched": "存在未匹配到 Trakt 的媒体（需手动匹配）",
    "sync.completed": "同步完成且有新记录上传",
    "backfill.completed": "写入飞牛完成（Trakt 历史回填）",
    "test": "测试通知",
}

FORMATS: dict[str, str] = {
    "generic": "通用 JSON（HMAC-SHA256 签名头）",
    "feishu": "飞书自定义机器人",
    "dingtalk": "钉钉自定义机器人（加签）",
    "wecom": "企业微信群机器人",
}

DEFAULT_EVENTS = ["sync.failed", "sync.unmatched"]
MAX_ATTEMPTS = 3
RETRY_MINUTES = 5
APP_VERSION = __version__


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


def validate_format(value: str | None) -> str:
    fmt = (value or "").strip().lower()
    if fmt not in FORMATS:
        raise WebhookError(f"未知的 Webhook 类型: {value}")
    return fmt


def detect_format(url: str) -> str:
    """Guess the receiver from its host so old endpoints keep working."""
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("open.feishu.cn") or host.endswith("open.larksuite.com") or host.endswith(
        "open.larkoffice.com"
    ):
        return "feishu"
    if host.endswith("oapi.dingtalk.com"):
        return "dingtalk"
    if host.endswith("qyapi.weixin.qq.com"):
        return "wecom"
    return "generic"


def resolve_format(row: WebhookEndpoint) -> str:
    stored = (row.format or "").strip().lower()
    if stored in FORMATS:
        return stored
    return detect_format(row.url)


def create_endpoint(
    db: Session,
    name: str,
    url: str,
    events: list[str] | None,
    secret: str | None = None,
    enabled: bool = True,
    format: str | None = None,
) -> WebhookEndpoint:
    if not (name or "").strip():
        raise WebhookError("请填写名称")
    cleaned_url = validate_url(url)
    row = WebhookEndpoint(
        name=name.strip()[:64],
        url=cleaned_url,
        events=validate_events(events),
        secret=(secret or "").strip() or None,
        enabled=enabled,
        format=validate_format(format) if format else detect_format(cleaned_url),
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
    format: str | None = None,
) -> WebhookEndpoint:
    if name is not None:
        if not name.strip():
            raise WebhookError("名称不能为空")
        row.name = name.strip()[:64]
    if url is not None:
        row.url = validate_url(url)
        if format is None:
            # Keep an explicitly chosen format, otherwise re-detect after a URL change.
            row.format = detect_format(row.url)
    if events is not None:
        row.events = validate_events(events)
    if clear_secret:
        row.secret = None
    elif secret is not None and secret.strip():
        row.secret = secret.strip()
    if enabled is not None:
        row.enabled = enabled
    if format is not None:
        row.format = validate_format(format)
    db.commit()
    db.refresh(row)
    return row


def public_endpoint(row: WebhookEndpoint) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "url": row.url,
        "events": row.events or [],
        "format": resolve_format(row),
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


def feishu_sign(timestamp: str, secret: str) -> str:
    """飞书自定义机器人签名。

    ``string_to_sign = f"{timestamp}\\n{secret}"`` is the HMAC **key** and the
    message is empty; the result is Base64 encoded.  A wrong algorithm (or a
    timestamp more than one hour off) is exactly what Feishu reports as
    ``19021 sign match fail``.
    """
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def dingtalk_signed_url(url: str, secret: str) -> str:
    timestamp = str(int(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    sign = quote(base64.b64encode(digest).decode("utf-8"), safe="")
    parsed = urlparse(url)
    extra = f"timestamp={timestamp}&sign={sign}"
    query = f"{parsed.query}&{extra}" if parsed.query else extra
    return urlunparse(parsed._replace(query=query))


def _event_title(event: str) -> str:
    return EVENTS.get(event, event)


def im_message(payload: dict[str, Any]) -> tuple[str, str]:
    """Human readable (title, text) used by the chat-bot formats."""
    event = str(payload.get("event") or "test")
    data = payload.get("data") or {}
    title = f"FN2Trakt · {_event_title(event)}"
    lines = [title]
    for key, label in (
        ("app_user", "用户"),
        ("trakt_user", "Trakt"),
        ("status", "状态"),
        ("message", "说明"),
    ):
        value = data.get(key)
        if value:
            lines.append(f"{label}：{value}")
    stats = [
        f"{label} {data[key]}"
        for key, label in (
            ("scanned", "扫描"),
            ("uploaded", "上传"),
            ("failed", "失败"),
            ("unmatched", "未匹配媒体"),
            ("unmatched_plays", "未匹配记录"),
        )
        if data.get(key) is not None
    ]
    if stats:
        lines.append("统计：" + " · ".join(stats))
    if data.get("updated") is not None or data.get("created") is not None:
        lines.append(f"写入：更新 {data.get('updated', 0)} · 新建 {data.get('created', 0)}")
    records = data.get("records") or []
    if records:
        lines.append("")
        lines.append("明细：")
        for row in records[:8]:
            reason = f"（{row.get('reason')}）" if row.get("reason") else ""
            lines.append(f"· {row.get('title') or '未知'} {reason}")
        if len(records) > 8:
            lines.append(f"… 其余 {len(records) - 8} 条")
    if data.get("backup_path"):
        lines.append(f"备份：{data['backup_path']}")
    lines.append("")
    lines.append(f"时间：{_sent_at_label(payload)}")
    return title, "\n".join(lines)


def _sent_at_label(payload: dict[str, Any]) -> str:
    """Render ``sent_at`` in UTC+8, the timezone the operators live in."""
    raw = payload.get("sent_at")
    moment: datetime | None = None
    if raw:
        try:
            moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return str(raw)
    text = to_text_shanghai(moment or utcnow())
    return f"{text} (UTC+8)"


def _json_bytes(body: dict[str, Any]) -> bytes:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def build_request(endpoint: WebhookEndpoint, payload: dict[str, Any]) -> tuple[str, bytes, dict[str, str]]:
    """Return (url, body, headers) for the endpoint's configured platform."""
    fmt = resolve_format(endpoint)
    secret = endpoint.secret or ""
    url = endpoint.url
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": f"FN2Trakt/{APP_VERSION}",
        "X-FN2Trakt-Event": str(payload.get("event") or ""),
    }
    if fmt == "feishu":
        _, text = im_message(payload)
        body: dict[str, Any] = {"msg_type": "text", "content": {"text": text}}
        if secret:
            timestamp = str(int(time.time()))
            body["timestamp"] = timestamp
            body["sign"] = feishu_sign(timestamp, secret)
        return url, _json_bytes(body), headers
    if fmt == "dingtalk":
        title, text = im_message(payload)
        if secret:
            url = dingtalk_signed_url(url, secret)
        return url, _json_bytes({"msgtype": "markdown", "markdown": {"title": title, "text": text}}), headers
    if fmt == "wecom":
        _, text = im_message(payload)
        return url, _json_bytes({"msgtype": "markdown", "markdown": {"content": text}}), headers
    body = _json_bytes(payload)
    signature = _signature(secret, body)
    if signature:
        headers["X-FN2Trakt-Signature"] = signature
    return url, body, headers


def remote_error(body: str | None) -> str | None:
    """Chat bots answer ``200 OK`` even when they reject the message.

    Feishu returns ``{"code": 19021, ...}``, DingTalk/WeCom return
    ``errcode``.  Without this check a rejected delivery would be recorded as
    successful, which is how the signature failure stayed invisible.
    """
    if not body:
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    for key in ("code", "errcode", "StatusCode", "status_code"):
        if key not in data:
            continue
        try:
            code = int(data[key])
        except (TypeError, ValueError):
            continue
        if code == 0:
            return None
        message = data.get("msg") or data.get("errmsg") or data.get("message") or ""
        return f"{key}={code} {message}".strip()
    if data.get("ok") is False:
        return str(data.get("error") or "ok=false")
    return None


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
        target_url, body, headers = build_request(endpoint, payload)
        delivery.attempts = (delivery.attempts or 0) + 1
        db.commit()
        try:
            with httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False) as client:
                response = client.post(target_url, content=body, headers=headers)
            text = response.text or ""
            delivery.response_status = response.status_code
            delivery.response_body = text[:2000]
            rejected = remote_error(text)
            if 200 <= response.status_code < 300 and not rejected:
                delivery.status = "success"
                delivery.error = None
                delivery.delivered_at = utcnow()
                delivery.next_retry_at = None
            else:
                delivery.status = "failed"
                delivery.error = rejected or f"HTTP {response.status_code}"
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
        "sent_at": to_iso_shanghai(utcnow()),
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
    """Emit failure events at the end of a sync run.

    Unmatched media is *not* reported from here any more: blocked items never
    get a SyncRecord until an upload is attempted, so this path silently
    skipped exactly the case users cared about.  :func:`notify_unmatched`
    reads the match table instead and is the single owner of ``sync.unmatched``.
    """
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
        notify_unmatched(db, trigger=run.trigger)
        if run.status == "success" and run.uploaded and not samples:
            emit_event(db, "sync.completed", base)
    except Exception:
        logger.exception("failed to emit sync webhook")


UNMATCHED_SIGNATURE_KEY = "webhook.unmatched_signature"
UNMATCHED_SAMPLE_LIMIT = 20


def unmatched_snapshot(db: Session) -> tuple[list[dict[str, Any]], int]:
    """Media that has completed plays but no usable Trakt match."""
    from app.services.matching import target_overview

    cards = [
        card
        for card in target_overview(db).values()
        if card.count > 0 and card.state == "unmatched"
    ]
    cards.sort(key=lambda card: (-card.count, card.title))
    records = [
        {
            "title": card.title,
            "type": card.media_type,
            "status": "unmatched",
            "reason": f"{card.count} 条已看完记录未匹配到 Trakt",
        }
        for card in cards[:UNMATCHED_SAMPLE_LIMIT]
    ]
    return records, sum(card.count for card in cards)


def notify_unmatched(db: Session, *, trigger: str = "scheduled") -> int:
    """Emit ``sync.unmatched`` whenever the unmatched set changes.

    A signature over ``(guid, play count)`` keeps the notification from firing
    on every scheduler tick, while a genuinely new unmatched item (or a changed
    count) still produces a message.  When everything is matched again the
    stored signature is removed, so a later re-appearance notifies again.
    """
    try:
        records, plays = unmatched_snapshot(db)
        if not records:
            previous = db.get(Setting, UNMATCHED_SIGNATURE_KEY)
            if previous is not None:
                db.delete(previous)
                db.commit()
            return 0

        signature = hashlib.sha256(
            json.dumps(sorted((row["title"], row["reason"]) for row in records), ensure_ascii=False).encode()
        ).hexdigest()
        previous = db.get(Setting, UNMATCHED_SIGNATURE_KEY)
        if previous is not None and previous.value == signature:
            return 0

        sent = emit_event(
            db,
            "sync.unmatched",
            {
                "trigger": trigger,
                "status": "unmatched",
                "app_user": None,
                "message": (
                    f"{len(records)} 个媒体（{plays} 条已看完记录）未匹配到 Trakt，"
                    "请到「媒体匹配」页面手动指定"
                ),
                "unmatched": len(records),
                "unmatched_plays": plays,
                "records": records,
            },
        )
        if sent:
            set_setting(db, UNMATCHED_SIGNATURE_KEY, signature)
            db.commit()
        return sent
    except Exception:
        logger.exception("failed to emit unmatched webhook")
        return 0



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
        "sent_at": to_iso_shanghai(utcnow()),
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
