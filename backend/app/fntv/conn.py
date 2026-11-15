"""Resilient, read-only access to the fnTV ``trimmedia.db``.

Why this module exists
----------------------
``sqlite3.connect`` is lazy: it only opens the file when the first statement
runs.  A transient failure therefore surfaces *in the middle of a query* as
``unable to open database file`` - far away from the ``connect`` call, where a
``try/except`` around ``connect()`` cannot catch it.  That is exactly how a
momentary hiccup (a fnTV checkpoint, a slow network mount, a briefly missing
``-shm``) used to escape as an HTTP 500.

``open_readonly`` handles that by

1. forcing a probe statement, so a broken open fails fast and locally,
2. retrying a few times with a short back-off (the usual cause is momentary),
3. falling back to a throw-away copy of the database (+ its WAL) when the live
   file still cannot be opened.  The copy also gives a consistent snapshot, so
   a long scan never races with a running fnTV writer.
"""

from __future__ import annotations

import atexit
import logging
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from app.fntv.models import FnTvError

logger = logging.getLogger(__name__)

RETRIES = 4
BACKOFF_SECONDS = 0.15

# Temporary snapshot directories that still need removing.  ``sqlite3.Connection``
# does not support weak references (and cannot be finalised), so cleanup is tied
# to ``close()`` with an ``atexit`` sweep as a safety net.
_TEMP_DIRS: set[str] = set()


@atexit.register
def _cleanup_temp_dirs() -> None:
    for directory in list(_TEMP_DIRS):
        shutil.rmtree(directory, ignore_errors=True)
    _TEMP_DIRS.clear()


class _SnapshotConnection(sqlite3.Connection):
    """Connection that deletes its throw-away database copy on close."""

    fn2trakt_tmpdir: str | None = None

    def close(self) -> None:
        try:
            super().close()
        finally:
            directory = self.fn2trakt_tmpdir
            if directory:
                self.fn2trakt_tmpdir = None
                _TEMP_DIRS.discard(directory)
                shutil.rmtree(directory, ignore_errors=True)


def _probe(con: sqlite3.Connection) -> None:
    """Force SQLite to actually open the file (connect alone does not)."""
    con.execute("SELECT count(*) FROM sqlite_master").fetchone()


def _snapshot(path: Path) -> sqlite3.Connection:
    """Open a private copy of the database.

    Only ``.db`` and ``-wal`` are copied: ``-shm`` is a shared-memory index that
    SQLite rebuilds from the WAL, and a stale copy of it is worse than none.
    """
    directory = Path(tempfile.mkdtemp(prefix="fn2trakt-fntv-"))
    _TEMP_DIRS.add(str(directory))
    copy = directory / path.name
    try:
        shutil.copy2(path, copy)
        wal = Path(f"{path}-wal")
        if wal.exists():
            shutil.copy2(wal, Path(f"{copy}-wal"))
        con = sqlite3.connect(copy, timeout=10, factory=_SnapshotConnection)
        con.fn2trakt_tmpdir = str(directory)
        con.row_factory = sqlite3.Row
        _probe(con)
    except Exception:
        _TEMP_DIRS.discard(str(directory))
        shutil.rmtree(directory, ignore_errors=True)
        raise
    logger.warning("fnTV database opened from a temporary snapshot: %s", path)
    return con


def open_readonly(path: Path, *, timeout: float = 10.0) -> sqlite3.Connection:
    """Open ``path`` read-only, raising :class:`FnTvError` with a clear message."""
    path = Path(path)
    if not path.exists():
        raise FnTvError(f"飞牛数据库不存在: {path}")
    if not path.is_file():
        raise FnTvError(f"飞牛数据库路径不是文件: {path}")

    last: sqlite3.Error | None = None
    for attempt in range(RETRIES):
        con: sqlite3.Connection | None = None
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout)
            con.row_factory = sqlite3.Row
            con.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
            _probe(con)
            return con
        except sqlite3.Error as exc:
            last = exc
            if con is not None:
                con.close()
            if attempt + 1 < RETRIES:
                time.sleep(BACKOFF_SECONDS * (attempt + 1))

    try:
        return _snapshot(path)
    except (sqlite3.Error, OSError) as exc:
        detail = last or exc
        raise FnTvError(f"无法打开飞牛数据库 {path}: {detail}") from detail
