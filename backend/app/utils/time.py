from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    """Naive UTC, which is what SQLite round-trips predictably."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(microsecond=0).isoformat() + "Z"


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
