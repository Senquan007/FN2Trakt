from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings as env_settings
from app.db.models import Setting

DEFAULTS = {
    "fntv.db_path": None,  # falls back to env
    "sync.interval_minutes": str(env_settings.sync_interval_minutes),
    "sync.enabled": "true" if env_settings.sync_enabled else "false",
    "sync.watched_threshold": "80",
    "sync.auto_start": "true",
    "trakt.redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
}


def get_setting(db: Session, key: str) -> str | None:
    row = db.get(Setting, key)
    if row is not None and row.value not in (None, ""):
        return row.value
    return DEFAULTS.get(key)


def set_setting(db: Session, key: str, value: str | None) -> None:
    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.flush()


def get_bool(db: Session, key: str, default: bool = False) -> bool:
    raw = get_setting(db, key)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def get_int(db: Session, key: str, default: int) -> int:
    raw = get_setting(db, key)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def get_float(db: Session, key: str, default: float) -> float:
    raw = get_setting(db, key)
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


def resolve_fntv_path(raw: str | None):
    from pathlib import Path

    from app.config import ROOT_DIR

    if not raw:
        return env_settings.fntv_db_path
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = ROOT_DIR / p
    return p


def fntv_db_path(db: Session):
    raw = get_setting(db, "fntv.db_path")
    return resolve_fntv_path(raw)


def all_settings(db: Session) -> dict[str, Any]:
    rows = db.scalars(select(Setting)).all()
    stored = {row.key: row.value for row in rows}
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in stored.items() if v is not None})
    return merged
