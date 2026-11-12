from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user
from app.config import settings
from app.db.models import AppUser, PlayRecord
from app.db.session import get_db
from app.fntv import FnTvError, inspect_database
from app.services import scheduler
from app.services.credentials import active_bundle, list_credentials
from app.services.settings_service import (
    fntv_db_path,
    get_bool,
    get_float,
    get_int,
    set_setting,
    resolve_fntv_path,
)
from app.trakt.client import TraktError

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsPayload(BaseModel):
    fntv_db_path: str | None = None
    sync_interval_minutes: int | None = None
    sync_enabled: bool | None = None
    watched_threshold: float | None = None


class PathPayload(BaseModel):
    path: str | None = None


@router.get("")
def get_settings(admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)):
    bundle = active_bundle(db)
    return {
        "fntv_db_path": str(fntv_db_path(db)),
        "default_fntv_db_path": str(settings.fntv_db_path),
        "sync": {
            "enabled": get_bool(db, "sync.enabled", True),
            "interval_minutes": max(1, get_int(db, "sync.interval_minutes", 5)),
            "watched_threshold": get_float(db, "sync.watched_threshold", 80.0),
        },
        "scheduler": scheduler.state(db),
        "trakt": {
            "configured": bool(bundle.client_id),
            "name": bundle.name,
            "source": bundle.source,
            "has_secret": bool(bundle.client_secret),
            "credential_count": len(list_credentials(db)),
        },
    }


@router.put("")
def update_settings(
    payload: SettingsPayload,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    if payload.fntv_db_path is not None:
        path = payload.fntv_db_path.strip()
        if path:
            info = inspect_database(resolve_fntv_path(path))
            if not info.get("ok"):
                raise HTTPException(status_code=400, detail=info.get("error") or "飞牛数据库不可用")
            set_setting(db, "fntv.db_path", path)
        else:
            set_setting(db, "fntv.db_path", None)
    if payload.sync_interval_minutes is not None:
        minutes = max(1, min(1440, int(payload.sync_interval_minutes)))
        set_setting(db, "sync.interval_minutes", str(minutes))
    if payload.sync_enabled is not None:
        set_setting(db, "sync.enabled", "true" if payload.sync_enabled else "false")
    threshold_changed = False
    if payload.watched_threshold is not None:
        threshold = max(50.0, min(100.0, float(payload.watched_threshold)))
        threshold_changed = abs(get_float(db, "sync.watched_threshold", 80.0) - threshold) > 0.001
        set_setting(db, "sync.watched_threshold", str(threshold))
    db.commit()
    if threshold_changed:
        from app.services.ingest import recompute_completed

        threshold = get_float(db, "sync.watched_threshold", 80.0)
        recompute_completed(db, threshold)
    scheduler.configure(db)
    return {"ok": True, "scheduler": scheduler.state(db)}


@router.post("/test-fntv")
def test_fntv(payload: PathPayload, admin: AppUser = Depends(get_admin_user)):
    info = inspect_database(resolve_fntv_path(payload.path or None))
    return info
