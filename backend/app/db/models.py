from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.utils.time import utcnow


class Base(DeclarativeBase):
    pass


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    fn_user_guid: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    trakt_account: Mapped["TraktAccount | None"] = relationship(
        back_populates="app_user", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class LoginSession(Base):
    __tablename__ = "login_session"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TraktCredential(Base):
    """A named Trakt OAuth application credential.

    Client ID / Secret are never returned by the API after being stored.
    """

    __tablename__ = "trakt_credential"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    redirect_uri: Mapped[str] = mapped_column(
        String(255), default="urn:ietf:wg:oauth:2.0:oob", nullable=False
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class TraktAccount(Base):
    __tablename__ = "trakt_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    credential_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    trakt_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trakt_slug: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trakt_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    last_auth_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    app_user: Mapped[AppUser] = relationship(back_populates="trakt_account")


class TraktAuthSession(Base):
    __tablename__ = "trakt_auth_session"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    app_user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)
    device_code: Mapped[str] = mapped_column(String(128), nullable=False)
    user_code: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_url: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class FnUser(Base):
    __tablename__ = "fn_user"

    guid: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_login_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class MediaItem(Base):
    __tablename__ = "media_item"

    fn_guid: Mapped[str] = mapped_column(String(64), primary_key=True)
    fn_type: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    original_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    season_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    show_guid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    show_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imdb_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    episode_imdb_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    release_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    poster_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    @property
    def is_episode(self) -> bool:
        return self.fn_type == "Episode" or (self.season_number or 0) > 0


class MediaMatch(Base):
    __tablename__ = "media_match"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_guid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    media_type: Mapped[str] = mapped_column(String(16), default="show", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="unmatched", nullable=False, index=True)
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str | None] = mapped_column(String(24), nullable=True)
    trakt_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trakt_slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trakt_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    trakt_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ids_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class PlayRecord(Base):
    __tablename__ = "play_record"
    __table_args__ = (
        UniqueConstraint("fn_item_guid", "fn_user_guid", name="uq_play_item_user"),
        Index("ix_play_user_time", "fn_user_guid", "fn_update_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fn_item_guid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    fn_user_guid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    position_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    watched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolution: Mapped[str | None] = mapped_column(String(32), nullable=True)
    play_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    fn_create_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fn_update_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    runtime_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class SyncRecord(Base):
    __tablename__ = "sync_record"
    __table_args__ = (
        UniqueConstraint("play_id", "trakt_account_id", name="uq_sync_play_account"),
        Index("ix_sync_account_status", "trakt_account_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    play_id: Mapped[int] = mapped_column(ForeignKey("play_record.id", ondelete="CASCADE"), nullable=False)
    trakt_account_id: Mapped[int] = mapped_column(
        ForeignKey("trakt_account.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    watched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    action: Mapped[str] = mapped_column(String(16), default="history", nullable=False)
    trakt_history_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class SyncRun(Base):
    __tablename__ = "sync_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    trigger: Mapped[str] = mapped_column(String(24), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scanned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    matched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uploaded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class TraktHistory(Base):
    """One Trakt watched-history event pulled into the local database.

    This is independent from ``PlayRecord``: it is the complete Trakt-side
    history, including titles that are not present in the fnTV library.  The
    backfill step links the rows that can be matched to a local play record.
    """

    __tablename__ = "trakt_history"
    __table_args__ = (
        UniqueConstraint("trakt_account_id", "trakt_history_id", name="uq_trakt_history_account"),
        Index("ix_trakt_history_account_watched", "trakt_account_id", "watched_at"),
        Index("ix_trakt_history_watched", "watched_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trakt_account_id: Mapped[int] = mapped_column(
        ForeignKey("trakt_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trakt_history_id: Mapped[int] = mapped_column(Integer, nullable=False)
    history_type: Mapped[str] = mapped_column(String(16), nullable=False)  # movie | episode
    action: Mapped[str] = mapped_column(String(16), default="watch", nullable=False)
    watched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    title: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    show_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    season_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    trakt_movie_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trakt_show_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trakt_episode_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imdb_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    show_tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    show_imdb_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    media_guid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    play_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    match_status: Mapped[str] = mapped_column(
        String(24), default="not_in_library", nullable=False, index=True
    )  # matched | library_only | not_in_library
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ApiToken(Base):
    """A personal access token for the read/write HTTP API."""

    __tablename__ = "api_token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    scopes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoint"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    events: Mapped[list | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class WebhookDelivery(Base):
    __tablename__ = "webhook_delivery"
    __table_args__ = (Index("ix_webhook_delivery_retry", "status", "next_retry_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(
        ForeignKey("webhook_endpoint.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
