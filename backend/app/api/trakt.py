from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import user_payload
from app.api.deps import get_admin_user, get_current_user
from app.db.models import AppUser, TraktAccount
from app.db.session import get_db
from app.services.credentials import (
    CredentialError,
    account_counts,
    active_bundle,
    create_credential,
    delete_credential,
    get_credential,
    list_credentials,
    set_default,
    summarize,
    update_credential,
)
from app.trakt.auth import (
    account_public,
    auth_status,
    disconnect,
    get_account,
    start_device_auth,
)
from app.trakt.client import TraktError

router = APIRouter(prefix="/api/trakt", tags=["trakt"])


class CredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    client_id: str = Field(min_length=16, max_length=255)
    client_secret: str | None = Field(default=None, max_length=255)
    redirect_uri: str | None = Field(default=None, max_length=255)


class CredentialUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    client_id: str | None = Field(default=None, max_length=255)
    client_secret: str | None = Field(default=None, max_length=255)
    clear_secret: bool = False
    redirect_uri: str | None = Field(default=None, max_length=255)


@router.get("/credential-status")
def credential_status(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Safe summary for the binding page: never returns the Client ID or Secret."""
    bundle = active_bundle(db)
    payload = {"configured": bool(bundle.client_id)}
    if user.is_admin:
        payload.update(
            {
                "name": bundle.name,
                "source": bundle.source,
                "has_secret": bool(bundle.client_secret),
            }
        )
    return payload


@router.get("/credentials")
def credentials(admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)):
    counts = account_counts(db)
    return {
        "items": [summarize(row, counts.get(row.id, 0)) for row in list_credentials(db)],
    }


@router.post("/credentials")
def create_credential_endpoint(
    payload: CredentialCreate, admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)
):
    try:
        credential = create_credential(
            db,
            name=payload.name,
            client_id=payload.client_id,
            client_secret=payload.client_secret,
            redirect_uri=payload.redirect_uri,
        )
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"credential": summarize(credential, 0)}


@router.patch("/credentials/{credential_id}")
def update_credential_endpoint(
    credential_id: int,
    payload: CredentialUpdate,
    admin: AppUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    credential = get_credential(db, credential_id)
    if credential is None:
        raise HTTPException(status_code=404, detail="凭据不存在")
    try:
        credential = update_credential(
            db,
            credential,
            name=payload.name,
            client_id=payload.client_id,
            client_secret=payload.client_secret,
            clear_secret=payload.clear_secret,
            redirect_uri=payload.redirect_uri,
        )
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    counts = account_counts(db)
    return {"credential": summarize(credential, counts.get(credential.id, 0))}


@router.post("/credentials/{credential_id}/default")
def set_default_credential(
    credential_id: int, admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)
):
    credential = get_credential(db, credential_id)
    if credential is None:
        raise HTTPException(status_code=404, detail="凭据不存在")
    credential = set_default(db, credential)
    counts = account_counts(db)
    return {"credential": summarize(credential, counts.get(credential.id, 0))}


@router.delete("/credentials/{credential_id}")
def delete_credential_endpoint(
    credential_id: int, admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)
):
    credential = get_credential(db, credential_id)
    if credential is None:
        raise HTTPException(status_code=404, detail="凭据不存在")
    try:
        delete_credential(db, credential)
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.post("/device/start")
def device_start(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return start_device_auth(db, user)
    except TraktError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/device/{auth_id}")
def device_poll(auth_id: str, user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return auth_status(db, auth_id, user)
    except TraktError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/account")
def account(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"account": account_public(get_account(db, user.id))}


@router.delete("/account")
def unbind(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    disconnect(db, user)
    return {"ok": True}


@router.get("/accounts")
def accounts(admin: AppUser = Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(TraktAccount, AppUser).join(AppUser, AppUser.id == TraktAccount.app_user_id).order_by(AppUser.username)
    ).all()
    counts = account_counts(db)
    return {
        "items": [
            {
                "account": account_public(account),
                "user": user_payload(db, app_user),
                "credential_id": account.credential_id,
            }
            for account, app_user in rows
        ],
        "credential_counts": counts,
    }
