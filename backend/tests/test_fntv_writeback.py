from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.fntv.models import FnItemRow
from app.services.fntv_writeback import _write_play
from app.services.trakt_history import LibraryEntry


def _entry() -> LibraryEntry:
    return LibraryEntry(
        guid="item-1",
        fn_type="Movie",
        title="Example Movie",
        show_title=None,
        show_guid=None,
        season_number=None,
        episode_number=None,
        tmdb_id=1,
        imdb_id=None,
        episode_imdb_id=None,
        runtime_minutes=120,
        year=2024,
    )


def test_write_play_creates_then_updates(tmp_path):
    path = tmp_path / "media.db"
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE item (guid TEXT PRIMARY KEY, type TEXT);
        CREATE TABLE user (guid TEXT PRIMARY KEY, username TEXT);
        CREATE TABLE item_media (guid TEXT PRIMARY KEY, item_guid TEXT, can_play INTEGER, sort_num INTEGER, create_time INTEGER);
        CREATE TABLE media_stream (guid TEXT, media_guid TEXT, codec_type TEXT, is_default INTEGER, "index" INTEGER);
        CREATE TABLE item_user_play (
            item_guid TEXT NOT NULL,
            user_guid TEXT NOT NULL,
            ts INTEGER DEFAULT 0,
            watched INTEGER DEFAULT 0,
            media_guid TEXT,
            video_guid TEXT,
            audio_guid TEXT,
            subtitle_guid TEXT,
            type TEXT,
            visible INTEGER DEFAULT 1,
            create_time INTEGER,
            update_time INTEGER
        );
        CREATE UNIQUE INDEX uk_item_user ON item_user_play(item_guid, user_guid);
        INSERT INTO item VALUES ('item-1', 'Movie');
        INSERT INTO user VALUES ('user-1', 'demo');
        INSERT INTO item_media VALUES ('media-1', 'item-1', 1, 0, 1);
        INSERT INTO media_stream VALUES ('video-1', 'media-1', 'video', 1, 0);
        INSERT INTO media_stream VALUES ('audio-1', 'media-1', 'audio', 1, 1);
        """
    )
    entry = _entry()
    watched = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    assert _write_play(con, "user-1", entry, watched, 7200) == "created"
    con.commit()
    row = con.execute(
        "SELECT ts, watched, type, media_guid, video_guid, audio_guid "
        "FROM item_user_play WHERE item_guid='item-1' AND user_guid='user-1'"
    ).fetchone()
    assert tuple(row) == (7200, 1, "Movie", "media-1", "video-1", "audio-1")

    assert _write_play(con, "user-1", entry, watched, 7200) == "updated"
    con.commit()
    count = con.execute("SELECT count(*) FROM item_user_play").fetchone()[0]
    assert count == 1
    con.close()
