from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MediaItem, MediaMatch, PlayRecord
from app.services.credentials import active_bundle
from app.services.settings_service import get_int
from app.trakt.client import TraktClient, TraktError
from app.utils.time import utcnow

_PUNCT_RE = re.compile(r"[\s\-_:：·.,，。!！?？'\"“”‘’()（）\[\]【】/\\&]+")


def normalize_title(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).casefold()
    text = _PUNCT_RE.sub("", text)
    return text.strip()


@dataclass
class Target:
    guid: str
    media_type: str  # movie | show
    title: str
    year: int | None
    tmdb_id: int | None
    imdb_id: str | None


def collect_targets(db: Session) -> dict[str, Target]:
    """Build one match target per movie, and per show for episodes.

    Episodes whose parent show could not be resolved still get their own
    target keyed by the episode guid.  Without that fallback they were
    invisible on the 媒体匹配 page even though 观看记录 listed them as
    unmatched, because no target was ever created for them.
    """
    targets: dict[str, Target] = {}
    rows = db.scalars(select(MediaItem).where(MediaItem.fn_type.in_(["Movie", "Episode"]))).all()
    for item in rows:
        if item.fn_type == "Movie":
            targets[item.fn_guid] = Target(
                guid=item.fn_guid,
                media_type="movie",
                title=item.title,
                year=item.year,
                tmdb_id=item.tmdb_id,
                imdb_id=item.imdb_id,
            )
        else:
            key = item.show_guid or item.fn_guid
            if key in targets:
                continue
            targets[key] = Target(
                guid=key,
                media_type="show",
                title=item.show_title or item.title,
                year=item.year,
                tmdb_id=item.tmdb_id,
                imdb_id=item.imdb_id,
            )
    return targets


@dataclass
class TargetCard:
    """A row on the 媒体匹配 page: one movie, or one show."""

    guid: str
    media_type: str
    title: str
    year: int | None
    tmdb_id: int | None
    imdb_id: str | None
    count: int = 0
    samples: list[str] = field(default_factory=list)
    match: MediaMatch | None = None
    orphan: bool = False

    @property
    def state(self) -> str:
        return self.match.status if self.match is not None else "unmatched"


def target_overview(db: Session, *, user_guid: str | None = None) -> dict[str, TargetCard]:
    """One card per matchable target, including unattached plays.

    The previous implementation iterated ``collect_targets()`` only, so a play
    whose ``media_item`` row was missing (or whose episode had no resolved
    show) never showed up here even though 观看记录 counted it as unmatched.
    Building the overview from the play records themselves makes both pages
    agree by construction.
    """
    targets = collect_targets(db)
    media_by_guid = {
        item.fn_guid: item
        for item in db.scalars(
            select(MediaItem).where(MediaItem.fn_type.in_(["Movie", "Episode", "Video", "Unknown"]))
        ).all()
    }
    matches = {row.media_guid: row for row in db.scalars(select(MediaMatch)).all()}

    cards: dict[str, TargetCard] = {
        guid: TargetCard(
            guid=guid,
            media_type=target.media_type,
            title=target.title,
            year=target.year,
            tmdb_id=target.tmdb_id,
            imdb_id=target.imdb_id,
            match=matches.get(guid),
        )
        for guid, target in targets.items()
    }

    plays = db.scalars(select(PlayRecord).where(PlayRecord.completed.is_(True))).all()
    for play in plays:
        if user_guid and play.fn_user_guid != user_guid:
            continue
        media = media_by_guid.get(play.fn_item_guid)
        if media is None:
            key = play.fn_item_guid
        elif media.fn_type == "Episode":
            key = media.show_guid or media.fn_guid
        else:
            key = media.fn_guid
        card = cards.get(key)
        if card is None:
            card = TargetCard(
                guid=key,
                media_type="movie" if media is not None and media.fn_type == "Movie" else "show",
                title=(media.title if media is not None else "未知条目"),
                year=media.year if media is not None else None,
                tmdb_id=media.tmdb_id if media is not None else None,
                imdb_id=media.imdb_id if media is not None else None,
                match=matches.get(key),
                orphan=True,
            )
            cards[key] = card
        card.count += 1
        if media is not None and len(card.samples) < 3:
            card.samples.append(media.title)

    return cards


def _ids_from_target(target: Target) -> dict[str, Any]:
    ids: dict[str, Any] = {}
    if target.tmdb_id:
        ids["tmdb"] = target.tmdb_id
    if target.imdb_id:
        ids["imdb"] = target.imdb_id
    return ids


def _match_from_candidate(target: Target, candidate: dict[str, Any], source: str, confidence: str) -> MediaMatch:
    ids = candidate.get("ids") or {}
    return MediaMatch(
        media_guid=target.guid,
        media_type=target.media_type,
        status="auto",
        confidence=confidence,
        source=source,
        trakt_id=ids.get("trakt"),
        trakt_slug=ids.get("slug"),
        trakt_title=candidate.get("title"),
        trakt_year=candidate.get("year"),
        ids_json={k: v for k, v in ids.items() if v is not None},
    )


def _candidate_payload(raw: dict[str, Any]) -> dict[str, Any] | None:
    kind = raw.get("type")
    if kind not in {"movie", "show"}:
        return None
    obj = raw.get(kind) or {}
    ids = obj.get("ids") or {}
    if not ids.get("trakt") and not ids.get("tmdb") and not ids.get("imdb"):
        return None
    return {
        "type": kind,
        "title": obj.get("title") or "",
        "year": obj.get("year"),
        "ids": ids,
        "overview": obj.get("overview"),
        "score": raw.get("score"),
        "slug": ids.get("slug"),
    }


def search_candidates(
    db: Session, query: str, media_type: str, limit: int = 10
) -> list[dict[str, Any]]:
    bundle = active_bundle(db)
    if not bundle.client_id:
        raise TraktError("需要先在系统设置中配置 Trakt 应用凭据才能搜索")
    with TraktClient(bundle.client_id, bundle.client_secret) as client:
        results = client.search(query, media_type, limit=limit)
    candidates = [_candidate_payload(item) for item in results]
    return [c for c in candidates if c]


def _pick_exact(target: Target, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    wanted = normalize_title(target.title)
    if not wanted:
        return None
    for candidate in candidates:
        if normalize_title(candidate.get("title")) != wanted:
            continue
        if target.year and candidate.get("year"):
            if abs(int(candidate["year"]) - int(target.year)) > 1:
                continue
        return candidate
    return None


def _cooling_down(row: MediaMatch, hours: int) -> bool:
    """Recently searched titles are not searched again on every cycle.

    Without this, an automatic read every few minutes would hammer the Trakt
    search API for titles that simply are not on Trakt.
    """
    if hours <= 0 or row.updated_at is None:
        return False
    return (utcnow() - row.updated_at) < timedelta(hours=hours)


def ensure_matches(db: Session, allow_search: bool = True) -> dict[str, int]:
    targets = collect_targets(db)
    existing = {row.media_guid: row for row in db.scalars(select(MediaMatch)).all()}
    retry_hours = max(0, get_int(db, "sync.match_retry_hours", 12))

    created = updated = by_id = by_search = unmatched = skipped_recent = 0
    bundle = active_bundle(db)
    search_client: TraktClient | None = None
    search_budget = 30
    if allow_search and bundle.client_id:
        search_client = TraktClient(bundle.client_id, bundle.client_secret)

    try:
        for guid, target in targets.items():
            current = existing.get(guid)
            if current is not None and current.status in {"manual", "rejected"}:
                continue
            if current is not None and current.status == "auto":
                # Refresh only when the source IDs disappeared; never demote silently.
                continue
            if current is not None and current.status == "unmatched" and _cooling_down(current, retry_hours):
                unmatched += 1
                skipped_recent += 1
                continue

            ids = _ids_from_target(target)
            if ids:
                match = _match_from_candidate(
                    target,
                    {"title": target.title, "year": target.year, "ids": ids},
                    source="tmdb" if target.tmdb_id else "imdb",
                    confidence="id",
                )
                match.status = "auto"
                if current is None:
                    db.add(match)
                    created += 1
                else:
                    _copy_match(current, match)
                    updated += 1
                by_id += 1
                continue

            candidate = None
            if search_client is not None and target.title and search_budget > 0:
                search_budget -= 1
                try:
                    results = search_client.search(target.title, target.media_type, limit=8)
                except TraktError:
                    # Network/auth problem: stop searching for the rest of this run.
                    search_client.close()
                    search_client = None
                    results = []
                candidates = [c for c in (_candidate_payload(r) for r in results) if c]
                candidate = _pick_exact(target, candidates)

            if candidate is not None:
                match = _match_from_candidate(target, candidate, source="search", confidence="title")
                match.status = "auto"
                if current is None:
                    db.add(match)
                    created += 1
                else:
                    _copy_match(current, match)
                    updated += 1
                by_search += 1
            else:
                if current is None:
                    db.add(
                        MediaMatch(
                            media_guid=guid,
                            media_type=target.media_type,
                            status="unmatched",
                            trakt_title=target.title,
                            trakt_year=target.year,
                        )
                    )
                    created += 1
                elif current.status == "unmatched":
                    # Restart the cooldown so the next cycle does not search again.
                    current.updated_at = utcnow()
                unmatched += 1
        db.commit()
    finally:
        if search_client is not None:
            search_client.close()

    return {
        "targets": len(targets),
        "created": created,
        "updated": updated,
        "by_id": by_id,
        "by_search": by_search,
        "unmatched": unmatched,
        "skipped_recent": skipped_recent,
    }


def _copy_match(dest: MediaMatch, src: MediaMatch) -> None:
    dest.media_type = src.media_type
    dest.status = src.status
    dest.confidence = src.confidence
    dest.source = src.source
    dest.trakt_id = src.trakt_id
    dest.trakt_slug = src.trakt_slug
    dest.trakt_title = src.trakt_title
    dest.trakt_year = src.trakt_year
    dest.ids_json = src.ids_json


def apply_manual_match(db: Session, media_guid: str, candidate: dict[str, Any]) -> MediaMatch:
    item = db.get(MediaItem, media_guid)
    if item is not None:
        media_type = "movie" if item.fn_type == "Movie" else "show"
        title = item.title if media_type == "movie" else (item.show_title or item.title)
        year = item.year
    else:
        media_type = candidate.get("type") or "show"
        title = candidate.get("title")
        year = candidate.get("year")

    ids = candidate.get("ids") or {}
    if not ids:
        raise TraktError("候选条目缺少 Trakt ID")

    match = db.scalar(select(MediaMatch).where(MediaMatch.media_guid == media_guid))
    if match is None:
        match = MediaMatch(media_guid=media_guid)
        db.add(match)
    match.media_type = media_type
    match.status = "manual"
    match.confidence = "manual"
    match.source = "manual"
    match.trakt_id = ids.get("trakt")
    match.trakt_slug = ids.get("slug")
    match.trakt_title = candidate.get("title") or title
    match.trakt_year = candidate.get("year") or year
    match.ids_json = {k: v for k, v in ids.items() if v is not None}
    match.note = None
    db.commit()
    return match


def reject_match(db: Session, media_guid: str) -> None:
    match = db.scalar(select(MediaMatch).where(MediaMatch.media_guid == media_guid))
    if match is None:
        match = MediaMatch(media_guid=media_guid, status="rejected")
        db.add(match)
    else:
        match.status = "rejected"
    db.commit()


def match_for_play(db: Session, play: PlayRecord, media: MediaItem | None) -> MediaMatch | None:
    if media is None:
        return None
    guid = media.show_guid if media.fn_type == "Episode" else media.fn_guid
    if not guid:
        return None
    return db.scalar(select(MediaMatch).where(MediaMatch.media_guid == guid))
