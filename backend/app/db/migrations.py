"""Small, idempotent SQLite migrations for existing deployments."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Setting, TraktAccount, TraktCredential

logger = logging.getLogger(__name__)

DEFAULT_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"
LEGACY_KEYS = ("trakt.client_id", "trakt.client_secret", "trakt.redirect_uri")


def _table_columns(conn, table: str) -> list[str]:
    return [row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")]


def _add_missing_columns(engine: Engine) -> None:
    with engine.begin() as conn:
        columns = _table_columns(conn, "trakt_account")
        if columns and "credential_id" not in columns:
            conn.exec_driver_sql("ALTER TABLE trakt_account ADD COLUMN credential_id INTEGER")
            logger.info("added trakt_account.credential_id")
        webhook_columns = _table_columns(conn, "webhook_endpoint")
        if webhook_columns and "format" not in webhook_columns:
            conn.exec_driver_sql("ALTER TABLE webhook_endpoint ADD COLUMN format VARCHAR(16)")
            # Existing endpoints keep NULL: resolve_format() then detects the
            # platform from the URL, so 飞书 endpoints start working without
            # being edited.
            logger.info("added webhook_endpoint.format")


def _legacy_value(db: Session, key: str) -> str | None:
    row = db.get(Setting, key)
    if row is None or not row.value:
        return None
    return row.value


def migrate_credentials(engine: Engine, session_factory: sessionmaker[Session]) -> None:
    """Create a named credential from the pre-credential settings keys.

    Older builds stored a single `trakt.client_id` / `trakt.client_secret` pair in
    the settings table. This turns it into the default named credential and links
    existing Trakt accounts to it. All operations are idempotent.
    """
    _add_missing_columns(engine)

    db = session_factory()
    try:
        credentials = db.scalars(select(TraktCredential).order_by(TraktCredential.id)).all()
        legacy_client_id = _legacy_value(db, "trakt.client_id")
        legacy_secret = _legacy_value(db, "trakt.client_secret")
        legacy_redirect = _legacy_value(db, "trakt.redirect_uri")

        if not credentials and legacy_client_id:
            credential = TraktCredential(
                name="默认凭据",
                client_id=legacy_client_id,
                client_secret=legacy_secret,
                redirect_uri=legacy_redirect or DEFAULT_REDIRECT_URI,
                is_default=True,
            )
            db.add(credential)
            db.flush()
            credentials = [credential]
            logger.info("migrated legacy Trakt client id into credential '默认凭据'")

        if credentials:
            default = next((row for row in credentials if row.is_default), credentials[0])
            if not default.is_default:
                default.is_default = True
            for account in db.scalars(select(TraktAccount)).all():
                if account.credential_id is None:
                    account.credential_id = default.id
            for key in LEGACY_KEYS:
                row = db.get(Setting, key)
                if row is not None:
                    db.delete(row)
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
