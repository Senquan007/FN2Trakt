#!/bin/sh
set -eu

DATA_DIR="${FN2TRAKT_DATA_DIR:-/data}"
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
PORT="${FN2TRAKT_PORT:-8080}"

mkdir -p "$DATA_DIR"

if [ "$(id -u)" = "0" ]; then
  # Bind mounts are often owned by the NAS user; make the data volume writable.
  chown -R "$PUID:$PGID" "$DATA_DIR" 2>/dev/null || true
  exec gosu "$PUID:$PGID" uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
