#!/usr/bin/env bash
# Local production-style start: serve the built frontend from FastAPI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

if [[ ! -x .venv/bin/python ]]; then
  echo "backend/.venv not found. Run: make install" >&2
  exit 1
fi

exec .venv/bin/python -m uvicorn app.main:app \
  --host "${FN2TRAKT_HOST:-0.0.0.0}" \
  --port "${FN2TRAKT_PORT:-8080}"
