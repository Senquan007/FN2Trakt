from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"


def _resolve(path: str | Path, default: Path) -> Path:
    if not path:
        return default
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = ROOT_DIR / p
    return p.resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FN2TRAKT_",
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "FN2Trakt"
    host: str = "0.0.0.0"
    port: int = 8080

    data_dir: Path = ROOT_DIR / "data"
    fntv_db_path: Path = ROOT_DIR / "DB" / "trimmedia.db"

    # Set FN2TRAKT_SECRET_KEY in production. Generated per process otherwise.
    secret_key: str = ""
    session_days: int = 30
    cookie_secure: bool = False

    # Optional bootstrap admin (only used when the database has no users).
    admin_username: str | None = None
    admin_password: str | None = None

    # Optional Trakt app credentials; the settings page can also store them.
    trakt_client_id: str | None = None
    trakt_client_secret: str | None = None
    trakt_api_base: str = "https://api.trakt.tv"
    trakt_auth_base: str = "https://auth.trakt.tv"
    trakt_trust_env: bool = True  # honour system HTTP(S)_PROXY settings

    sync_interval_minutes: int = 5
    sync_enabled: bool = True

    # Serve the built frontend from here when it exists.
    frontend_dist: Path = BACKEND_DIR / "static"

    def __init__(self, **values):
        super().__init__(**values)
        self.data_dir = _resolve(self.data_dir, ROOT_DIR / "data")
        self.fntv_db_path = _resolve(self.fntv_db_path, ROOT_DIR / "DB" / "trimmedia.db")
        self.frontend_dist = _resolve(self.frontend_dist, BACKEND_DIR / "static")
        if not self.secret_key:
            # Stable enough for a local single-node deployment; override via env.
            key_file = self.data_dir / ".secret_key"
            try:
                self.data_dir.mkdir(parents=True, exist_ok=True)
                if key_file.exists():
                    self.secret_key = key_file.read_text(encoding="utf-8").strip()
                if not self.secret_key:
                    self.secret_key = secrets.token_urlsafe(48)
                    key_file.write_text(self.secret_key, encoding="utf-8")
                    os.chmod(key_file, 0o600)
            except OSError:
                self.secret_key = secrets.token_urlsafe(48)

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'fn2trakt.db'}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
