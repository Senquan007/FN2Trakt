from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import STATE


@pytest.fixture(scope="module")
def client():
    STATE.authorized = False
    STATE.history_payloads.clear()
    with TestClient(app) as test_client:
        status = test_client.get("/api/setup/status").json()
        assert status["fntv"]["ok"], status
        assert status["needs_setup"]

        fn_user = status["fntv_users"][0]["guid"]
        response = test_client.post(
            "/api/setup",
            json={"username": "admin", "password": "admin123", "fn_user_guid": fn_user},
        )
        assert response.status_code == 200, response.text
        assert response.json()["user"]["is_admin"]

        response = test_client.post("/api/fntv/refresh", json={"run_matching": True})
        assert response.status_code == 200, response.text
        assert response.json()["snapshot"]["plays"] >= 1

        response = test_client.post(
            "/api/trakt/credentials",
            json={"name": "测试凭据", "client_id": "c" * 64},
        )
        assert response.status_code == 200, response.text
        credential = response.json()["credential"]
        assert credential["is_default"]
        assert "client_id" not in credential and "client_secret" not in credential
        yield test_client


def test_dashboard_and_plays(client):
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["stats"]["total_plays"] >= 1
    assert dashboard["stats"]["completed"] >= 1

    plays = client.get("/api/plays", params={"status": "completed"}).json()
    assert plays["total"] >= 1
    assert plays["items"][0]["match"]["status"] in {"auto", "manual"}


def test_device_flow(client):
    start = client.post("/api/trakt/device/start")
    assert start.status_code == 200, start.text
    data = start.json()
    assert data["user_code"] == "ABCD1234"
    assert data["verification_url"] == "https://auth.trakt.tv/activate"

    first = client.get(f"/api/trakt/device/{data['id']}").json()
    assert first["status"] == "pending"

    STATE.authorized = True
    time.sleep(1.2)
    second = client.get(f"/api/trakt/device/{data['id']}").json()
    assert second["status"] == "authorized", second
    assert STATE.device_token_bodies
    assert "client_secret" not in STATE.device_token_bodies[-1]
    assert second["account"]["trakt_username"] == "mock-user"

    account = client.get("/api/trakt/account").json()["account"]
    assert account["trakt_slug"] == "mock-user"
    assert account["status"] == "active"


def test_credentials_management(client):
    listed = client.get("/api/trakt/credentials").json()["items"]
    assert len(listed) == 1
    assert "client_id" not in listed[0]
    assert "client_secret" not in listed[0]

    created = client.post(
        "/api/trakt/credentials",
        json={
            "name": "备用凭据",
            "client_id": "d" * 64,
            "client_secret": "s" * 64,
            "redirect_uri": "https://example.com/callback",
        },
    )
    assert created.status_code == 200, created.text
    second = created.json()["credential"]
    assert second["has_secret"] is True
    assert second["is_default"] is False

    defaulted = client.post(f"/api/trakt/credentials/{second['id']}/default")
    assert defaulted.status_code == 200
    assert defaulted.json()["credential"]["is_default"] is True

    updated = client.patch(
        f"/api/trakt/credentials/{second['id']}",
        json={"name": "备用凭据 2", "clear_secret": True},
    )
    assert updated.status_code == 200
    assert updated.json()["credential"]["has_secret"] is False
    assert "client_id" not in updated.json()["credential"]

    deleted = client.delete(f"/api/trakt/credentials/{second['id']}")
    assert deleted.status_code == 200
    remaining = client.get("/api/trakt/credentials").json()["items"]
    assert len(remaining) == 1
    assert remaining[0]["is_default"] is True


def test_single_play_upload_and_duplicate(client):
    plays = client.get("/api/plays", params={"status": "completed"}).json()["items"]
    target = next(item for item in plays if item["match"]["status"] in {"auto", "manual"})
    response = client.post(f"/api/sync/play/{target['id']}")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "success", result

    assert STATE.history_payloads, "mock Trakt should receive history payload"
    payload = STATE.history_payloads[-1]
    assert "movies" in payload or "shows" in payload

    again = client.post(f"/api/sync/play/{target['id']}").json()
    assert again["status"] == "success"
    assert "已经同步" in again["message"]

    synced = client.get("/api/plays", params={"status": "synced"}).json()
    assert synced["total"] >= 1
    assert synced["summary"]["synced"] >= 1
    assert any(item["id"] == target["id"] for item in synced["items"])


def test_full_sync_run(client):
    preview = client.get("/api/sync/preview").json()
    assert preview["bound"] is True
    response = client.post("/api/sync/run")
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]

    deadline = time.time() + 20
    final = None
    while time.time() < deadline:
        runs = client.get("/api/sync/runs").json()["items"]
        final = next((run for run in runs if run["id"] == run_id), None)
        if final and final["status"] not in {"queued", "running"}:
            break
        time.sleep(0.4)
    assert final is not None
    assert final["status"] in {"success", "partial"}, final
    assert final["uploaded"] + final["failed"] >= 0


def test_token_refresh(client):
    from app.db.models import TraktAccount
    from app.db.session import SessionLocal
    from app.trakt.auth import ensure_access_token
    from app.utils.time import utcnow

    db = SessionLocal()
    try:
        account = db.query(TraktAccount).first()
        account.token_expires_at = utcnow()
        db.commit()
        token = ensure_access_token(db, account)
        assert token == "access-refreshed"
        assert STATE.refresh_calls >= 1
        assert STATE.refresh_bodies
        assert "client_secret" not in STATE.refresh_bodies[-1]
        assert STATE.refresh_bodies[-1].get("redirect_uri")
        db.refresh(account)
        assert account.status == "active"
    finally:
        db.close()


def test_manual_match_search(client):
    response = client.get("/api/media/search", params={"query": "漫长的季节", "media_type": "show"})
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items and items[0]["ids"]["tmdb"] == 225008


def test_settings_roundtrip(client):
    settings = client.get("/api/settings").json()
    assert settings["sync"]["interval_minutes"] >= 1
    assert settings["sync"]["watched_threshold"] == 80.0
    response = client.put(
        "/api/settings",
        json={"sync_interval_minutes": 7, "watched_threshold": 88, "sync_enabled": True},
    )
    assert response.status_code == 200, response.text
    updated = client.get("/api/settings").json()
    assert updated["sync"]["interval_minutes"] == 7
    assert updated["sync"]["watched_threshold"] == 88


def test_api_token_and_trakt_history_pull(client):
    from sqlalchemy import select

    from app.db.models import MediaItem, PlayRecord, TraktHistory
    from app.db.session import SessionLocal
    from tests.conftest import STATE

    db = SessionLocal()
    try:
        movie = db.scalar(
            select(MediaItem).where(MediaItem.fn_type == "Movie", MediaItem.tmdb_id.is_not(None))
        )
        assert movie is not None, "fixture should contain a movie"
        movie_tmdb = movie.tmdb_id
        movie_title = movie.title
        movie_year = movie.year
        runtime = movie.runtime_minutes or 100
    finally:
        db.close()

    STATE.history_items = [
        {
            "id": 990001,
            "watched_at": "2025-05-06T07:08:09.000Z",
            "action": "watch",
            "type": "movie",
            "movie": {
                "title": movie_title,
                "year": movie_year,
                "runtime": runtime,
                "ids": {"trakt": 880001, "tmdb": movie_tmdb},
            },
        }
    ]

    created = client.post(
        "/api/tokens",
        json={"name": "测试只读 Token", "scopes": ["history:read", "library:read"]},
    )
    assert created.status_code == 200, created.text
    token = created.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = client.get("/api/v1/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["token"]["prefix"].startswith("fnt_")

    pulled = client.post("/api/trakt/history/pull", json={})
    assert pulled.status_code == 200, pulled.text
    body = pulled.json()
    assert body["stored"] >= 1
    assert body["matched"] >= 1, body

    db = SessionLocal()
    try:
        history = db.scalar(
            select(TraktHistory).where(TraktHistory.trakt_history_id == 990001)
        )
        assert history is not None
        assert history.match_status in {"matched", "library_only"}
        assert history.media_guid
    finally:
        db.close()

    listed = client.get("/api/v1/history", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] >= 1
    stats = client.get("/api/v1/history/stats", headers=headers).json()
    assert stats["movies"] >= 1

    revoked = client.delete(f"/api/tokens/{created.json()['item']['id']}")
    assert revoked.status_code == 200
    assert client.get("/api/v1/me", headers=headers).status_code == 401

    # The library-only movie is reused by the write-back test below.
    STATE.history_items = []


def test_refresh_reuses_unchanged_database(client):
    first = client.post("/api/fntv/refresh", json={})
    assert first.status_code == 200, first.text
    assert first.json()["changed"] is True
    assert first.json()["snapshot"]["plays"] >= 1

    second = client.post("/api/fntv/refresh", json={"force": False})
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["changed"] is False
    # The previous summary is replayed so the UI can still render numbers.
    assert body["snapshot"]["plays"] >= 1

    scheduler = client.get("/api/settings").json()["scheduler"]
    assert scheduler["last_refresh_at"]
    assert scheduler["ingest_enabled"] is True
    assert scheduler["last_refresh_error"] is None


def test_fntv_writeback_preview_and_apply(client, tmp_path):
    """Write-back runs against a throw-away copy of the fnTV database."""
    import shutil
    import sqlite3

    from sqlalchemy import select

    from app.db.models import AppUser
    from app.db.session import SessionLocal
    from app.services.settings_service import fntv_db_path, set_setting
    from tests.conftest import STATE

    accounts = client.get("/api/trakt/history/accounts").json()["items"]
    assert accounts, "fixture should have a bound Trakt account"
    account_id = accounts[0]["id"]

    db = SessionLocal()
    try:
        user = db.get(AppUser, accounts[0]["app_user_id"])
        assert user is not None and user.fn_user_guid
        fn_guid = user.fn_user_guid
        source = fntv_db_path(db)
    finally:
        db.close()

    copy_path = tmp_path / "trimmedia.db"
    shutil.copy2(source, copy_path)

    con = sqlite3.connect(copy_path)
    con.row_factory = sqlite3.Row
    try:
        candidate = con.execute(
            """
            SELECT i.guid, i.title, i.tmdb_id, i.runtime
            FROM item i
            WHERE i.type = 'Movie'
              AND EXISTS (
                  SELECT 1 FROM item_media m
                  WHERE m.item_guid = i.guid AND COALESCE(m.can_play, 1) = 1
              )
              AND NOT EXISTS (
                  SELECT 1 FROM item_user_play p
                  WHERE p.item_guid = i.guid AND p.user_guid = ?
              )
            LIMIT 1
            """,
            (fn_guid,),
        ).fetchone()
        assert candidate is not None, "fnTV fixture should contain an unplayed movie"
    finally:
        con.close()

    db = SessionLocal()
    try:
        set_setting(db, "fntv.db_path", str(copy_path))
        db.commit()
    finally:
        db.close()

    STATE.history_items = [
        {
            "id": 990010,
            "watched_at": "2025-07-08T09:10:11.000Z",
            "action": "watch",
            "type": "movie",
            "movie": {
                "title": candidate["title"],
                "year": None,
                "runtime": candidate["runtime"] or 90,
                "ids": {"trakt": 880010, "tmdb": candidate["tmdb_id"]},
            },
        }
    ]
    try:
        preview = client.post(
            "/api/fntv/writeback/preview",
            json={"account_id": account_id, "pull": True},
        )
        assert preview.status_code == 200, preview.text
        plan = preview.json()
        assert plan["pulled"] is not None
        assert plan["can_apply"] is True, plan
        assert plan["summary"]["create"] >= 1
        assert plan["target_user"]["guid"] == fn_guid
        assert any(item["media_guid"] == candidate["guid"] for item in plan["items"])

        applied = client.post(
            "/api/fntv/writeback/apply",
            json={
                "account_id": account_id,
                "confirm": True,
                "expected_total": plan["summary"]["total"],
            },
        )
        assert applied.status_code == 200, applied.text
        result = applied.json()
        assert result["created"] >= 1
        from pathlib import Path

        assert Path(result["backup_path"]).exists()

        # A second preview must not plan the same rows again: they are already
        # in fnTV and are reported separately so the UI can show progress.
        again = client.post(
            "/api/fntv/writeback/preview", json={"account_id": account_id}
        )
        assert again.status_code == 200, again.text
        replan = again.json()
        assert replan["summary"]["already_written"] >= 1, replan["summary"]
        assert replan["summary"]["total"] == 0, replan["summary"]
        assert replan["can_apply"] is False
        assert replan["written_items"], replan

        # ...and the written play is visible on 观看记录 as 已写入飞牛.
        plays = client.get("/api/plays", params={"status": "writeback_written"}).json()
        assert plays["total"] >= 1, plays["summary"]
        row = next(row for row in plays["items"] if row["item_guid"] == candidate["guid"])
        assert row["writeback"]["status"] == "written"
        assert row["writeback"]["at"]

        # The copy now holds a watched play record...
        con = sqlite3.connect(copy_path)
        try:
            row = con.execute(
                "SELECT ts, watched FROM item_user_play WHERE item_guid=? AND user_guid=?",
                (candidate["guid"], fn_guid),
            ).fetchone()
        finally:
            con.close()
        assert row is not None and row[1] == 1

        # ...while the original fnTV database was never touched.
        con = sqlite3.connect(source)
        try:
            untouched = con.execute(
                "SELECT COUNT(*) FROM item_user_play WHERE item_guid=? AND user_guid=?",
                (candidate["guid"], fn_guid),
            ).fetchone()[0]
        finally:
            con.close()
        assert untouched == 0
    finally:
        db = SessionLocal()
        try:
            set_setting(db, "fntv.db_path", None)
            db.commit()
        finally:
            db.close()
        STATE.history_items = []


def _wait_delivery(client, delivery_id: int, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        rows = client.get("/api/webhooks/deliveries").json()["items"]
        for row in rows:
            if row["id"] == delivery_id:
                last = row
                if row["status"] != "pending":
                    return row
        time.sleep(0.05)
    return last


def _create_endpoint(client, **kwargs) -> dict:
    payload = {"name": kwargs.pop("name", "测试机器人"), "url": kwargs.pop("url")}
    payload.update(kwargs)
    response = client.post("/api/webhooks", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["endpoint"]


def test_webhook_feishu_signature_accepted(client):
    """飞书自定义机器人签名必须放在请求体内，否则会报 19021。"""
    endpoint = _create_endpoint(
        client,
        name="飞书机器人",
        url=f"{STATE.base_url}/feishu",
        format="feishu",
        secret=STATE.feishu_secret,
        events=["test"],
    )
    assert endpoint["format"] == "feishu"
    assert "secret" not in endpoint or endpoint.get("secret") is None

    STATE.webhook_payloads.clear()
    created = client.post(f"/api/webhooks/{endpoint['id']}/test")
    assert created.status_code == 200, created.text
    delivery = _wait_delivery(client, created.json()["delivery"]["id"])

    assert delivery["status"] == "success", delivery
    assert delivery["response_status"] == 200
    assert delivery["error"] is None

    body = STATE.webhook_payloads[-1]
    assert body["msg_type"] == "text"
    assert body["content"]["text"]
    assert body["timestamp"] and body["sign"]


def test_webhook_feishu_rejection_is_surfaced(client):
    """签名错误时飞书仍返回 HTTP 200，错误只藏在响应体里，必须判为失败。"""
    endpoint = _create_endpoint(
        client,
        name="飞书机器人（错签名）",
        url=f"{STATE.base_url}/feishu",
        format="feishu",
        secret="wrong-secret",
        events=["test"],
    )

    created = client.post(f"/api/webhooks/{endpoint['id']}/test")
    assert created.status_code == 200, created.text
    delivery = _wait_delivery(client, created.json()["delivery"]["id"])

    assert delivery["status"] == "failed", delivery
    assert delivery["response_status"] == 200
    assert "19021" in (delivery["error"] or "")


def test_webhook_rejects_unknown_format(client):
    response = client.post(
        "/api/webhooks",
        json={"name": "错误类型", "url": "http://127.0.0.1:1/hook", "format": "slack"},
    )
    assert response.status_code == 400, response.text


def test_media_targets_include_plays_without_media_row(client):
    """观看记录 counts an unmatched play even when its media row is missing;
    媒体匹配 must list it too, otherwise the item can never be fixed."""
    from sqlalchemy import select

    from app.db.models import FnUser, MediaItem, PlayRecord
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        fn_user = db.scalar(select(FnUser))
        assert fn_user is not None
        ghost_guid = "ghost-item-0001"
        play = PlayRecord(
            fn_item_guid=ghost_guid,
            fn_user_guid=fn_user.guid,
            play_type="movie",
            completed=True,
            watched=True,
            progress_percent=100.0,
        )
        db.add(play)
        db.commit()
    finally:
        db.close()

    try:
        plays = client.get("/api/plays", params={"status": "unmatched"}).json()
        assert any(row["item_guid"] == ghost_guid for row in plays["items"]), plays["summary"]

        targets = client.get("/api/media/targets", params={"status": "all"}).json()
        ghost = next((row for row in targets["items"] if row["media_guid"] == ghost_guid), None)
        assert ghost is not None, targets["summary"]
        assert ghost["count"] >= 1
        assert ghost["orphan"] is True
        assert targets["summary"]["unmatched"] >= 1
    finally:
        db = SessionLocal()
        try:
            row = db.scalar(select(PlayRecord).where(PlayRecord.fn_item_guid == ghost_guid))
            if row is not None:
                db.delete(row)
                db.commit()
            media = db.get(MediaItem, ghost_guid)
            if media is not None:
                db.delete(media)
                db.commit()
        finally:
            db.close()


def test_unmatched_media_triggers_webhook(client):
    """A newly unmatched item must notify, exactly once, with a UTC+8 time."""
    from sqlalchemy import select

    from app.db.models import FnUser, PlayRecord, WebhookEndpoint
    from app.db.session import SessionLocal
    from app.services.webhooks import UNMATCHED_SIGNATURE_KEY, notify_unmatched

    endpoint = _create_endpoint(
        client,
        name="未匹配通知",
        url=f"{STATE.base_url}/webhook",
        events=["sync.unmatched"],
    )

    db = SessionLocal()
    try:
        fn_user = db.scalar(select(FnUser))
        ghost_guid = "ghost-item-0002"
        db.add(
            PlayRecord(
                fn_item_guid=ghost_guid,
                fn_user_guid=fn_user.guid,
                play_type="movie",
                completed=True,
                watched=True,
                progress_percent=100.0,
            )
        )
        db.commit()
        # The first call sees a new unmatched item and must send.
        assert notify_unmatched(db, trigger="test") >= 1
        # The same set again must be silent.
        assert notify_unmatched(db, trigger="test") == 0
    finally:
        db.close()

    deliveries = client.get("/api/webhooks/deliveries").json()["items"]
    unmatched = [row for row in deliveries if row["event"] == "sync.unmatched"]
    assert unmatched, deliveries
    assert any(row["endpoint_id"] == endpoint["id"] for row in unmatched)
    delivered = _wait_delivery(client, unmatched[0]["id"])
    assert delivered["status"] == "success", delivered

    payload = STATE.webhook_payloads[-1]
    assert payload["event"] == "sync.unmatched"
    assert payload["data"]["unmatched"] >= 1
    assert payload["data"]["records"]
    # Webhook timestamps use the operator timezone (UTC+8).
    assert payload["sent_at"].endswith("+08:00"), payload["sent_at"]

    # Cleanup: the ghost play, the endpoint and the dedupe signature.
    from app.db.models import Setting

    db = SessionLocal()
    try:
        for model, expr in (
            (PlayRecord, PlayRecord.fn_item_guid == "ghost-item-0002"),
            (WebhookEndpoint, WebhookEndpoint.id == endpoint["id"]),
            (Setting, Setting.key == UNMATCHED_SIGNATURE_KEY),
        ):
            row = db.scalar(select(model).where(expr))
            if row is not None:
                db.delete(row)
        db.commit()
    finally:
        db.close()


def test_plays_split_unmatched_and_rejected(client):
    """未匹配 must not include 已忽略, so the two pages agree."""
    from sqlalchemy import select

    from app.db.models import MediaItem, MediaMatch, PlayRecord
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        play = db.scalar(select(PlayRecord).where(PlayRecord.completed.is_(True)))
        assert play is not None
        media = db.get(MediaItem, play.fn_item_guid)
        assert media is not None
        guid = media.show_guid if media.fn_type == "Episode" and media.show_guid else media.fn_guid
        match = db.scalar(select(MediaMatch).where(MediaMatch.media_guid == guid))
        if match is None:
            match = MediaMatch(media_guid=guid, media_type="movie" if media.fn_type == "Movie" else "show")
            db.add(match)
        previous = match.status
        match.status = "rejected"
        db.commit()
    finally:
        db.close()

    try:
        summary = client.get("/api/plays").json()["summary"]
        assert summary["rejected"] >= 1
        rejected = client.get("/api/plays", params={"status": "rejected"}).json()
        assert rejected["total"] >= 1
        assert all(row["state"] == "rejected" for row in rejected["items"])
        unmatched = client.get("/api/plays", params={"status": "unmatched"}).json()
        assert all(
            row["match"] is None or row["match"]["status"] != "rejected"
            for row in unmatched["items"]
        )
    finally:
        db = SessionLocal()
        try:
            match = db.scalar(select(MediaMatch).where(MediaMatch.media_guid == guid))
            if match is not None:
                match.status = previous
                db.commit()
        finally:
            db.close()


def test_media_targets_include_episode_without_show(client):
    """An episode whose show could not be resolved used to be invisible on the
    match page while 观看记录 still counted it as unmatched."""
    from sqlalchemy import select

    from app.db.models import FnUser, MediaItem, MediaMatch, PlayRecord
    from app.db.session import SessionLocal

    guid = "orphan-episode-0001"
    db = SessionLocal()
    try:
        fn_user = db.scalar(select(FnUser))
        db.add(
            MediaItem(
                fn_guid=guid,
                fn_type="Episode",
                title="孤儿剧集",
                show_title=None,
                show_guid=None,
                season_number=1,
                episode_number=1,
            )
        )
        db.add(
            PlayRecord(
                fn_item_guid=guid,
                fn_user_guid=fn_user.guid,
                play_type="episode",
                completed=True,
                watched=True,
                progress_percent=100.0,
            )
        )
        db.commit()
    finally:
        db.close()

    try:
        targets = client.get("/api/media/targets", params={"status": "all"}).json()
        card = next((row for row in targets["items"] if row["media_guid"] == guid), None)
        assert card is not None, targets["summary"]
        assert card["count"] >= 1

        # It is a matchable target: a manual match lands on the same guid the
        # uploader uses for such an episode.
        match = client.post(
            "/api/media/match",
            json={
                "media_guid": guid,
                "candidate": {
                    "title": "孤儿剧集",
                    "year": 2020,
                    "ids": {"trakt": 771001, "slug": "orphan-show", "tmdb": 771001},
                },
            },
        )
        assert match.status_code == 200, match.text
        assert match.json()["match"]["status"] == "manual"

        plays = client.get("/api/plays", params={"status": "pending"}).json()
        assert any(row["item_guid"] == guid for row in plays["items"]), plays["summary"]
    finally:
        db = SessionLocal()
        try:
            row = db.scalar(select(PlayRecord).where(PlayRecord.fn_item_guid == guid))
            if row is not None:
                db.delete(row)
            match_row = db.scalar(select(MediaMatch).where(MediaMatch.media_guid == guid))
            if match_row is not None:
                db.delete(match_row)
            media = db.get(MediaItem, guid)
            if media is not None:
                db.delete(media)
            db.commit()
        finally:
            db.close()


def test_completed_play_reports_full_progress(client):
    """飞牛把已看完条目的播放位置清零，进度条不能显示 0%。

    ``completed`` comes from ``watched=1`` while ``progress_percent`` is purely
    ``position / runtime``, so a finished item can legitimately store 0%.  The
    API now exposes ``progress_display`` so the chip and the bar agree, without
    rewriting the raw value.
    """
    from sqlalchemy import select

    from app.db.models import FnUser, PlayRecord
    from app.db.session import SessionLocal

    finished_guid = "progress-reset-0001"
    partial_guid = "progress-partial-0001"
    db = SessionLocal()
    try:
        fn_user = db.scalar(select(FnUser))
        assert fn_user is not None
        db.add(
            PlayRecord(
                fn_item_guid=finished_guid,
                fn_user_guid=fn_user.guid,
                play_type="movie",
                completed=True,
                watched=True,
                progress_percent=0.0,
                position_seconds=0,
                runtime_seconds=5400,
            )
        )
        db.add(
            PlayRecord(
                fn_item_guid=partial_guid,
                fn_user_guid=fn_user.guid,
                play_type="movie",
                completed=False,
                watched=False,
                progress_percent=42.5,
                position_seconds=2295,
                runtime_seconds=5400,
            )
        )
        db.commit()
    finally:
        db.close()

    try:
        unmatched = client.get("/api/plays", params={"status": "unmatched", "page_size": 100}).json()
        finished = next((row for row in unmatched["items"] if row["item_guid"] == finished_guid), None)
        assert finished is not None, unmatched["summary"]
        assert finished["completed"] is True
        assert finished["progress_percent"] == 0.0
        assert finished["progress_display"] == 100.0

        incomplete = client.get("/api/plays", params={"status": "incomplete", "page_size": 100}).json()
        partial = next((row for row in incomplete["items"] if row["item_guid"] == partial_guid), None)
        assert partial is not None, incomplete["summary"]
        # Unfinished rows keep their real progress.
        assert partial["progress_display"] == 42.5
    finally:
        db = SessionLocal()
        try:
            for guid in (finished_guid, partial_guid):
                row = db.scalar(select(PlayRecord).where(PlayRecord.fn_item_guid == guid))
                if row is not None:
                    db.delete(row)
            db.commit()
        finally:
            db.close()
