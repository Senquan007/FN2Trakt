#!/usr/bin/env bash
# Local development: FastAPI (with reload) + Vite dev server.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x backend/.venv/bin/python ]]; then
  echo "backend/.venv not found. Run: make install" >&2
  exit 1
fi
if [[ ! -d frontend/node_modules ]]; then
  echo "frontend/node_modules not found. Run: make install-web" >&2
  exit 1
fi

(
  cd backend
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
) &
BACKEND_PID=$!

cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "API: http://127.0.0.1:8080  |  Web: http://127.0.0.1:5173"
cd frontend
npm run dev
