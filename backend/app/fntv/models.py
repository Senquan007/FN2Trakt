from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


class FnTvError(RuntimeError):
    """Raised when the fnTV database cannot be read or is unsupported."""


@dataclass
class FnUserRow:
    guid: str
    username: str
    is_admin: bool = False
    status: int = 1
    last_login_time: datetime | None = None


@dataclass
class FnItemRow:
    guid: str
    fn_type: str
    title: str
    original_title: str | None = None
    parent_guid: str | None = None
    season_number: int | None = None
    episode_number: int | None = None
    tmdb_id: int | None = None
    imdb_id: str | None = None
    episode_imdb_id: str | None = None
    runtime: int | None = None
    release_date: str | None = None
    first_air_date: str | None = None
    overview: str | None = None


@dataclass
class NormalizedPlay:
    item_guid: str
    user_guid: str
    item_type: str  # movie | episode | video | unknown
    title: str
    show_guid: str | None
    show_title: str | None
    season_number: int | None
    episode_number: int | None
    tmdb_id: int | None
    imdb_id: str | None
    episode_imdb_id: str | None
    runtime_minutes: int | None
    year: int | None
    release_date: str | None
    overview: str | None
    position_seconds: int
    watched: bool
    resolution: str | None
    create_time: datetime | None
    update_time: datetime | None
    runtime_seconds: int | None
    progress_percent: float | None
    completed: bool
    raw: dict = field(default_factory=dict)

    @property
    def display_title(self) -> str:
        if self.item_type == "episode" and self.season_number and self.episode_number:
            return f"{self.show_title or self.title} - S{self.season_number:02d}E{self.episode_number:02d}"
        return self.title

    @property
    def match_guid(self) -> str | None:
        """The guid used for Trakt matching (the show for episodes)."""
        if self.item_type == "episode":
            return self.show_guid
        if self.item_type == "movie":
            return self.item_guid
        return None


@dataclass
class Snapshot:
    path: str
    users: list[FnUserRow]
    plays: list[NormalizedPlay]
    items_count: int
    raw_play_count: int
    skipped: int
    warnings: list[str]
