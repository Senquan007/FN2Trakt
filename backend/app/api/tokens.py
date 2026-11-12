from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import AppUser
from app.db.session import get_db
from app.services.api_tokens import (
    DEFAULT_SCOPES,
    SCOPES,
    TokenError,
    create_token,
    list_tokens,
    public_token,
    revoke_token,
)

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    scopes: list[str] | None = None
    expires_days: int | None = Field(default=None, ge=1, le=3650)


@router.get("")
def tokens(user: AppUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return {
        "items": [public_token(row) for row in list_tokens(db, user)],
        "scopes": [{"key": key, "label": label} for key, label in SCOPES.items()],
        "default_scopes": DEFAULT_SCOPES,
    }


@router.post("")
def create(
    payload: TokenCreate,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row, token = create_token(db, user, payload.name, payload.scopes, payload.expires_days)
    except TokenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"token": token, "item": public_token(row)}


@router.delete("/{token_id}")
def revoke(
    token_id: int,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not revoke_token(db, user, token_id):
        raise HTTPException(status_code=404, detail="Token 不存在")
    return {"ok": True}
