from __future__ import annotations

import sqlite3

import pytest

from app.fntv.conn import open_readonly
from app.fntv.models import FnTvError
from app.utils.time import to_iso_shanghai, to_text_shanghai


@pytest.fixture()
def sample_db(tmp_path):
    path = tmp_path / "trimmedia.db"
    con = sqlite3.connect(path)
    try:
        con.execute("CREATE TABLE item (guid TEXT PRIMARY KEY, title TEXT)")
        con.execute("INSERT INTO item VALUES ('a', '示例')")
        con.commit()
    finally:
        con.close()
    return path


def test_open_readonly_reads_normally(sample_db):
    con = open_readonly(sample_db)
    try:
        assert con.execute("SELECT title FROM item").fetchone()[0] == "示例"
    finally:
        con.close()


def test_open_readonly_retries_transient_failure(sample_db, monkeypatch):
    """The old code could not catch this: connect() is lazy, the failure only
    appears on the first statement."""
    real_connect = sqlite3.connect
    calls = {"n": 0}

    def flaky(target, *args, **kwargs):
        if isinstance(target, str) and "mode=ro" in target:
            calls["n"] += 1
            if calls["n"] <= 2:
                raise sqlite3.OperationalError("unable to open database file")
        return real_connect(target, *args, **kwargs)

    monkeypatch.setattr("app.fntv.conn.sqlite3.connect", flaky)
    con = open_readonly(sample_db)
    try:
        assert con.execute("SELECT count(*) FROM item").fetchone()[0] == 1
    finally:
        con.close()
    assert calls["n"] == 3


def test_open_readonly_falls_back_to_snapshot(sample_db, monkeypatch):
    real_connect = sqlite3.connect

    def broken(target, *args, **kwargs):
        if isinstance(target, str) and "mode=ro" in target:
            raise sqlite3.OperationalError("unable to open database file")
        return real_connect(target, *args, **kwargs)

    monkeypatch.setattr("app.fntv.conn.sqlite3.connect", broken)
    con = open_readonly(sample_db)
    try:
        # Still readable through a throw-away copy of the database.
        assert con.execute("SELECT title FROM item").fetchone()[0] == "示例"
    finally:
        con.close()


def test_open_readonly_missing_file_is_a_friendly_error(tmp_path):
    with pytest.raises(FnTvError) as excinfo:
        open_readonly(tmp_path / "nope.db")
    assert "不存在" in str(excinfo.value)


def test_webhook_times_use_shanghai_offset():
    from datetime import datetime

    moment = datetime(2026, 11, 15, 8, 23, 6)  # naive UTC == 16:23:06 +08:00
    assert to_iso_shanghai(moment) == "2026-11-15T16:23:06+08:00"
    assert to_text_shanghai(moment) == "2026-11-15 16:23:06"
