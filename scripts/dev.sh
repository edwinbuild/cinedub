#!/usr/bin/env bash
set -euo pipefail

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Python environment missing. Run: uv sync --group dev" >&2
  exit 1
fi

cleanup() {
  kill "${api_pid:-}" "${worker_pid:-}" "${web_pid:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

PYTHONPATH=apps/api .venv/bin/alembic -c alembic.ini upgrade head
.venv/bin/uvicorn cinedub_api.main:app --app-dir apps/api --host 127.0.0.1 --port 8000 &
api_pid=$!
PYTHONPATH=apps/api .venv/bin/python apps/worker/main.py &
worker_pid=$!
npm run dev:web &
web_pid=$!

wait -n "$api_pid" "$worker_pid" "$web_pid"
