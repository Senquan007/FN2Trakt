from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from app.api import auth as auth_api
from app.api import (
    dashboard,
    fntv,
    history,
    media,
    plays,
    settings as settings_api,
    sync,
    tokens,
    trakt,
    users,
    v1,
    webhooks,
)
from app.config import settings
from app.db.models import AppUser
from app.db.session import SessionLocal, init_db
from app.fntv import FnTvError
from app.security import hash_password
from app.services import scheduler
from app.services.ingest import recompute_completed
from app.services.settings_service import get_float
from app.trakt.client import TraktError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("fn2trakt")


def _bootstrap_admin() -> None:
    if not settings.admin_username or not settings.admin_password:
        return
    db = SessionLocal()
    try:
        if (db.scalar(select(func.count(AppUser.id))) or 0) > 0:
            return
        user = AppUser(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
            role="admin",
            is_active=True,
        )
        db.add(user)
        db.commit()
        logger.info("bootstrap admin %s created", settings.admin_username)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    _bootstrap_admin()
    db = SessionLocal()
    try:
        # Keep completed flags consistent with the (possibly new) default
        # threshold after an upgrade.
        recompute_completed(db, get_float(db, "sync.watched_threshold", 80.0))
        scheduler.configure(db)
    finally:
        db.close()
    scheduler.start()
    logger.info("%s started, fnTV db: %s", settings.app_name, settings.fntv_db_path)
    yield
    scheduler.shutdown()


app = FastAPI(title=settings.app_name, version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(TraktError)
async def trakt_error_handler(_request: Request, exc: TraktError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(FnTvError)
async def fntv_error_handler(_request: Request, exc: FnTvError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/api/health")
def health():
    return {"ok": True, "app": settings.app_name, "version": "3.0.0"}


app.include_router(auth_api.router)
app.include_router(auth_api.setup_router)
app.include_router(users.router)
app.include_router(fntv.router)
app.include_router(trakt.router)
app.include_router(media.router)
app.include_router(plays.router)
app.include_router(sync.router)
app.include_router(dashboard.router)
app.include_router(settings_api.router)
app.include_router(history.router)
app.include_router(tokens.router)
app.include_router(webhooks.router)
app.include_router(v1.router)


def _mount_frontend() -> None:
    dist: Path = settings.frontend_dist
    index = dist / "index.html"
    if not index.exists():
        logger.info("frontend build not found at %s (run npm run build)", dist)
        return
    assets = dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)


_mount_frontend()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
