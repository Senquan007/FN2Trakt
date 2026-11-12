from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user
from app.db.models import AppUser, WebhookDelivery, WebhookEndpoint
from app.db.session import get_db
from app.services.webhooks import (
    EVENTS,
    WebhookError,
    create_endpoint,
    public_delivery,
    public_endpoint,
    retry_delivery,
    send_test,
    update_endpoint,
)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


class WebhookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=1, max_length=1024)
    events: list[str] | None = None
    secret: str | None = Field(default=None, max_length=255)
    enabled: bool = True


class WebhookUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    url: str | None = Field(default=None, max_length=1024)
    events: list[str] | None = None
    secret: str | None = Field(default=None, max_length=255)
    clear_secret: bool = False
    enabled: bool | None = None


def _endpoint(db: Session, endpoint_id: int) -> WebhookEndpoint:
    row = db.get(WebhookEndpoint, endpoint_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Webhook 不存在")
    return row


@router.get("")
def list_endpoints(admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(WebhookEndpoint).order_by(WebhookEndpoint.id.desc())).all()
    return {
        "items": [public_endpoint(row) for row in rows],
        "events": [{"key": key, "label": label} for key, label in EVENTS.items()],
    }


@router.post("")
def create(
    payload: WebhookCreate,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    try:
        row = create_endpoint(db, payload.name, payload.url, payload.events, payload.secret, payload.enabled)
    except WebhookError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"endpoint": public_endpoint(row)}


@router.patch("/{endpoint_id}")
def update(
    endpoint_id: int,
    payload: WebhookUpdate,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    row = _endpoint(db, endpoint_id)
    try:
        row = update_endpoint(
            db,
            row,
            name=payload.name,
            url=payload.url,
            events=payload.events,
            secret=payload.secret,
            clear_secret=payload.clear_secret,
            enabled=payload.enabled,
        )
    except WebhookError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"endpoint": public_endpoint(row)}


@router.delete("/{endpoint_id}")
def delete(
    endpoint_id: int,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    row = _endpoint(db, endpoint_id)
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/{endpoint_id}/test")
def test(
    endpoint_id: int,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    row = _endpoint(db, endpoint_id)
    delivery = send_test(db, row)
    return {"delivery": public_delivery(delivery)}


@router.get("/deliveries")
def deliveries(
    endpoint_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    stmt = select(WebhookDelivery).order_by(WebhookDelivery.id.desc()).limit(limit)
    if endpoint_id is not None:
        stmt = stmt.where(WebhookDelivery.endpoint_id == endpoint_id)
    return {"items": [public_delivery(row) for row in db.scalars(stmt).all()]}


@router.post("/deliveries/{delivery_id}/retry")
def retry(
    delivery_id: int,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    row = db.get(WebhookDelivery, delivery_id)
    if row is None:
        raise HTTPException(status_code=404, detail="投递记录不存在")
    try:
        retry_delivery(db, row)
    except WebhookError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"delivery": public_delivery(row)}
