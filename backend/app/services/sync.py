from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    MediaItem,
    MediaMatch,
    PlayRecord,
    SyncRecord,
    SyncRun,
    TraktAccount,
)
from app.db.session import SessionLocal
from app.services.matching import collect_targets, ensure_matches
from app.services.credentials import bundle_for_account
from app.services.settings_service import get_float
from app.trakt.auth import account_public, ensure_access_token
from app.trakt.client import TraktAuthError, TraktClient, TraktError
from app.utils.time import to_iso_z, utcnow

_RUN_LOCK = threading.Lock()
_ID_KEYS = ("trakt", "tmdb", "imdb", "tvdb")


@dataclass
class PlanEntry:
    play: PlayRecord
    media: MediaItem
    match: MediaMatch | None
    sync: SyncRecord | None
    state: str  # ready | synced | blocked | unsupported
    reason: str | None = None


@dataclass
class Batch:
    kind: str
    payload: dict[str, Any]
    entries: list[PlanEntry] = field(default_factory=list)


def _pick_ids(ids: dict | None) -> dict[str, Any]:
    if not ids:
        return {}
    return {key: ids[key] for key in _ID_KEYS if ids.get(key) not in (None, "", 0)}


def _watched_at(play: PlayRecord):
    return play.fn_update_time or play.fn_create_time or play.last_seen_at


def build_plan(db: Session, app_user: AppUser, account: TraktAccount | None) -> list[PlanEntry]:
    plays = db.scalars(
        select(PlayRecord)
        .where(PlayRecord.fn_user_guid == app_user.fn_user_guid, PlayRecord.completed.is_(True))
        .order_by(PlayRecord.fn_update_time.asc())
    ).all()
    media_map = {
        item.fn_guid: item
        for item in db.scalars(select(MediaItem).where(MediaItem.fn_guid.in_({p.fn_item_guid for p in plays}))).all()
    }
    sync_map: dict[int, SyncRecord] = {}
    if account is not None:
        sync_map = {
            row.play_id: row
            for row in db.scalars(
                select(SyncRecord).where(
                    SyncRecord.trakt_account_id == account.id,
                    SyncRecord.play_id.in_({p.id for p in plays}),
                )
            ).all()
        }

    entries: list[PlanEntry] = []
    for play in plays:
        media = media_map.get(play.fn_item_guid)
        sync = sync_map.get(play.id)
        if media is None:
            entries.append(PlanEntry(play, MediaItem(fn_guid=play.fn_item_guid, fn_type="Unknown"), None, sync, "unsupported", "媒体条目缺失"))
            continue
        if media.fn_type not in {"Movie", "Episode"}:
            entries.append(PlanEntry(play, media, None, sync, "unsupported", "无法识别的媒体类型"))
            continue
        target_guid = media.show_guid if media.fn_type == "Episode" else media.fn_guid
        match = db.scalar(select(MediaMatch).where(MediaMatch.media_guid == target_guid)) if target_guid else None
        if match is None or match.status in {"unmatched", "rejected"} or not _pick_ids(match.ids_json):
            state = "blocked"
            reason = "未匹配到 Trakt 条目" if match is None or match.status == "unmatched" else (
                "已忽略该条目" if match.status == "rejected" else "匹配结果缺少 Trakt ID"
            )
            entries.append(PlanEntry(play, media, match, sync, state, reason))
            continue
        if sync is not None and sync.status == "success":
            entries.append(PlanEntry(play, media, match, sync, "synced"))
        else:
            entries.append(PlanEntry(play, media, match, sync, "ready"))
    return entries


def plan_summary(entries: list[PlanEntry]) -> dict[str, int]:
    summary = {"total": len(entries), "ready": 0, "synced": 0, "blocked": 0, "unsupported": 0}
    for entry in entries:
        summary[entry.state] = summary.get(entry.state, 0) + 1
    return summary


def preview_sync(db: Session, app_user: AppUser) -> dict[str, Any]:
    account = db.scalar(select(TraktAccount).where(TraktAccount.app_user_id == app_user.id))
    if account is None:
        return {"bound": False, "summary": {"total": 0, "ready": 0, "synced": 0, "blocked": 0, "unsupported": 0}, "samples": []}
    ensure_matches(db)
    entries = build_plan(db, app_user, account)
    samples = [
        {
            "title": _display(entry),
            "state": entry.state,
            "reason": entry.reason,
            "watched_at": to_iso_z(_watched_at(entry.play)),
        }
        for entry in entries
        if entry.state != "synced"
    ][:10]
    return {"bound": True, "summary": plan_summary(entries), "samples": samples, "account": account_public(account)}


def _display(entry: PlanEntry) -> str:
    media = entry.media
    if media.fn_type == "Episode" and media.season_number and media.episode_number:
        return f"{media.show_title or media.title} - S{media.season_number:02d}E{media.episode_number:02d}"
    return media.title


def _build_batches(entries: list[PlanEntry]) -> list[Batch]:
    batches: list[Batch] = []
    movies = [entry for entry in entries if entry.media.fn_type == "Movie"]
    for index in range(0, len(movies), 50):
        chunk = movies[index : index + 50]
        payload = {
            "movies": [
                {"ids": _pick_ids(entry.match.ids_json if entry.match else None), "watched_at": to_iso_z(_watched_at(entry.play))}
                for entry in chunk
            ]
        }
        batches.append(Batch(kind="movies", payload=payload, entries=chunk))

    shows: dict[str, list[PlanEntry]] = {}
    for entry in entries:
        if entry.media.fn_type == "Episode":
            key = entry.media.show_guid or entry.media.fn_guid
            shows.setdefault(key, []).append(entry)

    for show_entries in shows.values():
        by_season: dict[int, list[PlanEntry]] = {}
        for entry in show_entries:
            by_season.setdefault(int(entry.media.season_number or 0), []).append(entry)
        seasons_payload: list[dict[str, Any]] = []
        season_entries: list[PlanEntry] = []
        for season_number, rows in sorted(by_season.items()):
            episodes = []
            for entry in rows:
                episodes.append(
                    {
                        "number": int(entry.media.episode_number or 0),
                        "watched_at": to_iso_z(_watched_at(entry.play)),
                    }
                )
                season_entries.append(entry)
            seasons_payload.append({"number": season_number, "episodes": episodes})
        ids = _pick_ids(show_entries[0].match.ids_json if show_entries[0].match else None)
        payload = {"shows": [{"ids": ids, "seasons": seasons_payload}]}
        batches.append(Batch(kind="episodes", payload=payload, entries=season_entries))
    return batches


def _not_found_ids(response: dict[str, Any], kind: str) -> set[str]:
    not_found = response.get("not_found") or {}
    items = not_found.get(kind) or []
    values: set[str] = set()
    for item in items:
        ids = (item or {}).get("ids") or {}
        for key in _ID_KEYS:
            value = ids.get(key)
            if value not in (None, "", 0):
                values.add(str(value))
    return values


def _classify(batch: Batch, response: dict[str, Any]) -> tuple[list[PlanEntry], list[PlanEntry]]:
    if batch.kind == "movies":
        missing = _not_found_ids(response, "movies")
    else:
        missing = _not_found_ids(response, "shows") | _not_found_ids(response, "episodes")
    ok: list[PlanEntry] = []
    failed: list[PlanEntry] = []
    if not missing:
        return list(batch.entries), []
    for entry in batch.entries:
        ids = _pick_ids(entry.match.ids_json if entry.match else None)
        if any(str(value) in missing for value in ids.values()):
            failed.append(entry)
        else:
            ok.append(entry)
    return ok, failed


def _upsert_sync_record(db: Session, account: TraktAccount, entry: PlanEntry) -> SyncRecord:
    record = entry.sync
    if record is None:
        record = db.scalar(
            select(SyncRecord).where(
                SyncRecord.play_id == entry.play.id,
                SyncRecord.trakt_account_id == account.id,
            )
        )
    if record is None:
        record = SyncRecord(play_id=entry.play.id, trakt_account_id=account.id)
        db.add(record)
    record.watched_at = _watched_at(entry.play)
    entry.sync = record
    return record


def _mark_blocked(db: Session, account: TraktAccount, entry: PlanEntry) -> None:
    record = _upsert_sync_record(db, account, entry)
    if record.status == "success":
        return
    record.status = "blocked"
    record.error = entry.reason or "未匹配到 Trakt 条目"
    record.updated_at = utcnow()


def execute_sync(db: Session, run: SyncRun, app_user: AppUser) -> None:
    account = db.scalar(select(TraktAccount).where(TraktAccount.app_user_id == app_user.id))
    run.status = "running"
    db.commit()
    try:
        if account is None:
            run.status = "skipped"
            run.message = "尚未绑定 Trakt 账号"
            run.finished_at = utcnow()
            db.commit()
            return

        bundle = bundle_for_account(db, account)
        if not bundle.client_id:
            run.status = "failed"
            run.message = "尚未配置 Trakt Client ID"
            run.finished_at = utcnow()
            db.commit()
            return

        try:
            token = ensure_access_token(db, account)
        except TraktAuthError as exc:
            run.status = "failed"
            run.message = str(exc)
            run.finished_at = utcnow()
            db.commit()
            return

        match_stats = ensure_matches(db)
        entries = build_plan(db, app_user, account)
        summary = plan_summary(entries)
        run.scanned = summary["total"]
        run.completed = summary["ready"] + summary["synced"]
        run.matched = match_stats.get("targets", 0)
        db.commit()

        for entry in entries:
            if entry.state == "blocked":
                _mark_blocked(db, account, entry)
            elif entry.state == "unsupported":
                _mark_blocked(db, account, entry)
        db.commit()

        ready = [entry for entry in entries if entry.state == "ready"]
        if not ready:
            run.status = "success"
            run.message = "没有需要上传的新记录"
            run.finished_at = utcnow()
            db.commit()
            return

        batches = _build_batches(ready)
        uploaded = failed = 0
        with TraktClient(bundle.client_id, bundle.client_secret) as client:
            for batch in batches:
                payloads = [entry for entry in batch.entries]
                if not payloads:
                    continue
                for entry in payloads:
                    record = _upsert_sync_record(db, account, entry)
                    record.status = "pending"
                    record.action = "history"
                    record.request_json = batch.payload
                    record.error = None
                    record.attempts = (record.attempts or 0) + 1
                    record.updated_at = utcnow()
                db.commit()
                try:
                    response = client.add_history(token, batch.payload)
                except TraktAuthError as exc:
                    for entry in payloads:
                        record = _upsert_sync_record(db, account, entry)
                        record.status = "failed"
                        record.error = str(exc)
                        record.updated_at = utcnow()
                    account.status = "error"
                    account.last_error = str(exc)
                    db.commit()
                    run.status = "failed"
                    run.message = str(exc)
                    run.finished_at = utcnow()
                    db.commit()
                    return
                except TraktError as exc:
                    for entry in payloads:
                        record = _upsert_sync_record(db, account, entry)
                        record.status = "failed"
                        record.error = str(exc)
                        record.response_json = exc.payload if isinstance(exc.payload, dict) else None
                        record.updated_at = utcnow()
                    failed += len(payloads)
                    db.commit()
                    continue

                ok, missing = _classify(batch, response)
                for entry in ok:
                    record = _upsert_sync_record(db, account, entry)
                    record.status = "success"
                    record.response_json = response
                    record.error = None
                    record.updated_at = utcnow()
                    uploaded += 1
                for entry in missing:
                    record = _upsert_sync_record(db, account, entry)
                    record.status = "failed"
                    record.error = "Trakt 未找到该条目，请手动匹配"
                    record.response_json = response
                    record.updated_at = utcnow()
                    failed += 1
                db.commit()

        run.uploaded = uploaded
        run.failed = failed
        run.status = "success" if failed == 0 else ("partial" if uploaded else "failed")
        run.message = f"上传 {uploaded} 条，失败 {failed} 条"
        run.finished_at = utcnow()
        if account is not None:
            account.status = "active"
            account.last_error = None
        db.commit()
    except Exception as exc:  # pragma: no cover - defensive bookkeeping
        db.rollback()
        run.status = "failed"
        run.message = f"同步异常: {exc}"
        run.finished_at = utcnow()
        db.commit()
    finally:
        try:
            from app.services.webhooks import notify_sync_run

            notify_sync_run(db, run, app_user)
        except Exception:  # notifications must never break a sync run
            pass


def _run_thread(run_id: int, app_user_id: int) -> None:
    db = SessionLocal()
    try:
        run = db.get(SyncRun, run_id)
        app_user = db.get(AppUser, app_user_id)
        if run is None or app_user is None:
            return
        execute_sync(db, run, app_user)
    finally:
        db.close()
        _RUN_LOCK.release()


def start_sync(app_user_id: int, trigger: str = "manual") -> SyncRun | None:
    if not _RUN_LOCK.acquire(blocking=False):
        return None
    db = SessionLocal()
    try:
        app_user = db.get(AppUser, app_user_id)
        if app_user is None:
            _RUN_LOCK.release()
            return None
        run = SyncRun(app_user_id=app_user.id, trigger=trigger, status="queued")
        db.add(run)
        db.commit()
        db.refresh(run)
        thread = threading.Thread(target=_run_thread, args=(run.id, app_user.id), daemon=True)
        thread.start()
        return run
    except Exception:
        _RUN_LOCK.release()
        raise
    finally:
        db.close()


def run_all(trigger: str = "scheduled") -> list[int]:
    db = SessionLocal()
    run_ids: list[int] = []
    try:
        users = db.scalars(
            select(AppUser).where(AppUser.is_active.is_(True), AppUser.fn_user_guid.is_not(None))
        ).all()
        for user in users:
            account = db.scalar(select(TraktAccount).where(TraktAccount.app_user_id == user.id))
            if account is None or account.status == "error":
                continue
            run = SyncRun(app_user_id=user.id, trigger=trigger, status="queued")
            db.add(run)
            db.flush()
            run_ids.append(run.id)
        db.commit()
    finally:
        db.close()
    if run_ids:
        thread = threading.Thread(target=_run_many, args=(run_ids,), daemon=True)
        thread.start()
    return run_ids


def _run_many(run_ids: list[int]) -> None:
    for run_id in run_ids:
        db = SessionLocal()
        try:
            run = db.get(SyncRun, run_id)
            if run is None:
                continue
            app_user = db.get(AppUser, run.app_user_id) if run.app_user_id else None
            if app_user is None:
                continue
            if not _RUN_LOCK.acquire(blocking=False):
                run.status = "skipped"
                run.message = "另一个同步任务正在运行"
                run.finished_at = utcnow()
                db.commit()
                continue
            try:
                execute_sync(db, run, app_user)
            finally:
                _RUN_LOCK.release()
        finally:
            db.close()


def sync_single_play(db: Session, play: PlayRecord, app_user: AppUser) -> dict[str, Any]:
    """Upload exactly one completed play, synchronously, for manual testing/force-sync."""
    if not play.completed:
        raise TraktError("该记录尚未看完，不会写入 Trakt 历史")
    account = db.scalar(select(TraktAccount).where(TraktAccount.app_user_id == app_user.id))
    if account is None:
        raise TraktError("该用户尚未绑定 Trakt 账号")
    bundle = bundle_for_account(db, account)
    if not bundle.client_id:
        raise TraktError("尚未配置 Trakt 应用凭据")

    ensure_matches(db)
    media = db.get(MediaItem, play.fn_item_guid)
    if media is None:
        raise TraktError("媒体条目不存在")
    if media.fn_type not in {"Movie", "Episode"}:
        raise TraktError("该媒体类型不支持同步")
    target_guid = media.show_guid if media.fn_type == "Episode" else media.fn_guid
    match = db.scalar(select(MediaMatch).where(MediaMatch.media_guid == target_guid)) if target_guid else None
    if match is None or match.status in {"unmatched", "rejected"} or not _pick_ids(match.ids_json):
        raise TraktError("该媒体尚未匹配到 Trakt 条目，请先在「媒体匹配」中处理")

    existing = db.scalar(
        select(SyncRecord).where(
            SyncRecord.play_id == play.id,
            SyncRecord.trakt_account_id == account.id,
        )
    )
    if existing is not None and existing.status == "success":
        return {"status": "success", "message": "该记录已经同步过，无需重复上传", "record_id": existing.id}

    if not _RUN_LOCK.acquire(blocking=False):
        raise TraktError("已有同步任务正在运行，请稍后再试")
    try:
        token = ensure_access_token(db, account)
        entry = PlanEntry(play=play, media=media, match=match, sync=existing, state="ready")
        batch = _build_batches([entry])[0]
        record = _upsert_sync_record(db, account, entry)
        record.status = "pending"
        record.action = "history"
        record.request_json = batch.payload
        record.error = None
        record.attempts = (record.attempts or 0) + 1
        record.updated_at = utcnow()
        db.commit()

        with TraktClient(bundle.client_id, bundle.client_secret) as client:
            response = client.add_history(token, batch.payload)
        ok, missing = _classify(batch, response)
        if ok and not missing:
            record.status = "success"
            record.response_json = response
            record.error = None
            record.updated_at = utcnow()
            db.commit()
            return {"status": "success", "message": "已写入 Trakt 观看历史", "response": response, "record_id": record.id}
        record.status = "failed"
        record.response_json = response
        record.error = "Trakt 未找到该条目，请检查匹配结果"
        record.updated_at = utcnow()
        db.commit()
        return {"status": "failed", "message": record.error, "response": response, "record_id": record.id}
    except TraktAuthError as exc:
        account.status = "error"
        account.last_error = str(exc)
        db.commit()
        raise
    finally:
        _RUN_LOCK.release()
