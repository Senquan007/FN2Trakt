from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings as env_settings
from app.db.models import TraktAccount, TraktCredential
from app.services.settings_service import get_setting

DEFAULT_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"


class CredentialError(ValueError):
    pass


@dataclass(frozen=True)
class CredentialBundle:
    credential_id: int | None
    name: str | None
    client_id: str | None
    client_secret: str | None
    redirect_uri: str
    source: str  # database | environment | none


def list_credentials(db: Session) -> list[TraktCredential]:
    return list(db.scalars(select(TraktCredential).order_by(TraktCredential.id)).all())


def get_credential(db: Session, credential_id: int) -> TraktCredential | None:
    return db.get(TraktCredential, credential_id)


def active_credential(db: Session) -> TraktCredential | None:
    rows = list_credentials(db)
    if not rows:
        return None
    for row in rows:
        if row.is_default:
            return row
    return rows[0]


def _bundle_from_row(row: TraktCredential) -> CredentialBundle:
    return CredentialBundle(
        credential_id=row.id,
        name=row.name,
        client_id=row.client_id,
        client_secret=row.client_secret,
        redirect_uri=row.redirect_uri or DEFAULT_REDIRECT_URI,
        source="database",
    )


def active_bundle(db: Session) -> CredentialBundle:
    row = active_credential(db)
    if row is not None:
        return _bundle_from_row(row)
    if env_settings.trakt_client_id:
        return CredentialBundle(
            credential_id=None,
            name="环境变量凭据",
            client_id=env_settings.trakt_client_id,
            client_secret=env_settings.trakt_client_secret,
            redirect_uri=get_setting(db, "trakt.redirect_uri") or DEFAULT_REDIRECT_URI,
            source="environment",
        )
    return CredentialBundle(None, None, None, None, DEFAULT_REDIRECT_URI, "none")


def bundle_for_account(db: Session, account: TraktAccount | None) -> CredentialBundle:
    if account is not None and account.credential_id:
        row = db.get(TraktCredential, account.credential_id)
        if row is not None:
            return _bundle_from_row(row)
    return active_bundle(db)


def account_counts(db: Session) -> dict[int, int]:
    rows = db.execute(
        select(TraktAccount.credential_id, func.count(TraktAccount.id))
        .where(TraktAccount.credential_id.is_not(None))
        .group_by(TraktAccount.credential_id)
    ).all()
    return {int(credential_id): int(count) for credential_id, count in rows}


def summarize(credential: TraktCredential, account_count: int = 0) -> dict:
    """Public representation. Never includes client_id or client_secret."""
    return {
        "id": credential.id,
        "name": credential.name,
        "has_secret": bool(credential.client_secret),
        "redirect_uri": credential.redirect_uri or DEFAULT_REDIRECT_URI,
        "is_default": credential.is_default,
        "account_count": account_count,
        "created_at": credential.created_at.isoformat() + "Z",
        "updated_at": credential.updated_at.isoformat() + "Z",
    }


def _clean_name(name: str | None) -> str:
    value = (name or "").strip()
    if not value:
        raise CredentialError("请输入凭据名称")
    if len(value) > 64:
        raise CredentialError("凭据名称不能超过 64 个字符")
    return value


def _clean_client_id(client_id: str | None) -> str:
    value = (client_id or "").strip()
    if not value:
        raise CredentialError("请输入 Client ID")
    if len(value) < 16:
        raise CredentialError("Client ID 看起来不合法")
    return value


def _clean_secret(secret: str | None) -> str | None:
    if secret is None:
        return None
    value = secret.strip()
    if not value:
        return None
    if len(value) < 16:
        raise CredentialError("Client Secret 看起来不合法")
    return value


def _clean_redirect(redirect_uri: str | None) -> str:
    value = (redirect_uri or "").strip()
    return value or DEFAULT_REDIRECT_URI


def _assert_unique_name(db: Session, name: str, exclude_id: int | None = None) -> None:
    query = select(TraktCredential).where(func.lower(TraktCredential.name) == name.lower())
    if exclude_id is not None:
        query = query.where(TraktCredential.id != exclude_id)
    if db.scalar(query) is not None:
        raise CredentialError("凭据名称已存在")


def create_credential(
    db: Session,
    *,
    name: str,
    client_id: str,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
) -> TraktCredential:
    clean_name = _clean_name(name)
    _assert_unique_name(db, clean_name)
    first = not list_credentials(db)
    credential = TraktCredential(
        name=clean_name,
        client_id=_clean_client_id(client_id),
        client_secret=_clean_secret(client_secret),
        redirect_uri=_clean_redirect(redirect_uri),
        is_default=first,
    )
    db.add(credential)
    db.commit()
    db.refresh(credential)
    return credential


def update_credential(
    db: Session,
    credential: TraktCredential,
    *,
    name: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    clear_secret: bool = False,
    redirect_uri: str | None = None,
) -> TraktCredential:
    if name is not None:
        clean_name = _clean_name(name)
        _assert_unique_name(db, clean_name, exclude_id=credential.id)
        credential.name = clean_name
    if client_id is not None and client_id.strip():
        credential.client_id = _clean_client_id(client_id)
    if clear_secret:
        credential.client_secret = None
    elif client_secret is not None and client_secret.strip():
        credential.client_secret = _clean_secret(client_secret)
    if redirect_uri is not None:
        credential.redirect_uri = _clean_redirect(redirect_uri)
    db.commit()
    db.refresh(credential)
    return credential


def delete_credential(db: Session, credential: TraktCredential) -> None:
    used = db.scalar(
        select(func.count(TraktAccount.id)).where(TraktAccount.credential_id == credential.id)
    ) or 0
    if used:
        raise CredentialError(f"已有 {used} 个 Trakt 账号使用该凭据，请先让这些账号重新授权或解绑")
    was_default = credential.is_default
    db.delete(credential)
    db.flush()
    if was_default:
        remaining = list_credentials(db)
        if remaining:
            remaining[0].is_default = True
    db.commit()


def set_default(db: Session, credential: TraktCredential) -> TraktCredential:
    for row in list_credentials(db):
        row.is_default = row.id == credential.id
    db.commit()
    db.refresh(credential)
    return credential
