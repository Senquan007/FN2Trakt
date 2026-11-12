from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MediaItem, MediaMatch, PlayRecord
from app.services.credentials import active_bundle
from app.trakt.client import TraktClient, TraktError

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
    """Build one match target per movie, and per show for episodes."""
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
        elif item.show_guid and item.show_guid not in targets:
            targets[item.show_guid] = Target(
                guid=item.show_guid,
                media_type="show",
                title=item.show_title or item.title,
                year=item.year,
                tmdb_id=item.tmdb_id,
                imdb_id=item.imdb_id,
            )
    return targets


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


def ensure_matches(db: Session, allow_search: bool = True) -> dict[str, int]:
    targets = collect_targets(db)
    existing = {row.media_guid: row for row in db.scalars(select(MediaMatch)).all()}

    created = updated = by_id = by_search = unmatched = 0
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
                    pass
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
