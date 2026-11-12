"""fnTV (飞牛影视) read-only database access."""

from app.fntv.models import FnItemRow, FnTvError, FnUserRow, NormalizedPlay, Snapshot
from app.fntv.reader import (
    dump_schema,
    inspect_database,
    raw_summary,
    read_snapshot,
    read_users,
)

__all__ = [
    "FnItemRow",
    "FnTvError",
    "FnUserRow",
    "NormalizedPlay",
    "Snapshot",
    "dump_schema",
    "inspect_database",
    "raw_summary",
    "read_snapshot",
    "read_users",
]
