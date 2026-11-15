from __future__ import annotations

from datetime import datetime, timedelta, timezone

# The UI, the logs and every outbound notification are meant for a Chinese
# audience, so wall-clock times are rendered in UTC+8.  Storage stays UTC.
SHANGHAI_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


def utcnow() -> datetime:
    """Naive UTC, which is what SQLite round-trips predictably."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(microsecond=0).isoformat() + "Z"


def _as_shanghai(value: datetime) -> datetime:
    """Stored datetimes are naive UTC; treat anything naive as UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SHANGHAI_TZ)


def to_iso_shanghai(value: datetime | None) -> str | None:
    """ISO-8601 with an explicit ``+08:00`` offset (for webhook payloads)."""
    if value is None:
        return None
    return _as_shanghai(value).replace(microsecond=0).isoformat()


def to_text_shanghai(value: datetime | None) -> str | None:
    """``2026-11-15 16:23:06`` in UTC+8, for chat messages."""
    if value is None:
        return None
    return _as_shanghai(value).strftime("%Y-%m-%d %H:%M:%S")



def from_epoch_ms(value: int | float | None) -> datetime | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    # fnTV stores milliseconds; tolerate seconds just in case.
    if number > 10_000_000_000:
        number = number / 1000.0
    return datetime.fromtimestamp(number, tz=timezone.utc).replace(tzinfo=None)


def from_epoch_s(value: int | float | None) -> datetime | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return datetime.fromtimestamp(number, tz=timezone.utc).replace(tzinfo=None)


def humanize_age(value: datetime | None) -> str | None:
    if value is None:
        return None
    delta = utcnow() - value
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    return f"{seconds // 86400} 天前"


def ceil_seconds(until: datetime | None) -> int:
    if until is None:
        return 0
    remaining = (until - utcnow()).total_seconds()
    return max(0, int(remaining + 0.999))


def add_days(days: int) -> datetime:
    return utcnow() + timedelta(days=days)
