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

web_port=${PORT:-3000}
export CINEDUB_WEB_ORIGIN=${CINEDUB_WEB_ORIGIN:-http://127.0.0.1:$web_port}
read -r api_host api_port < <(PYTHONPATH=apps/api .venv/bin/python -c \
  'from cinedub_api.config import get_settings; s=get_settings(); print(s.api_host, s.api_port)')
export NEXT_PUBLIC_CINEDUB_API_URL=${NEXT_PUBLIC_CINEDUB_API_URL:-http://$api_host:$api_port}
PYTHONPATH=apps/api .venv/bin/python -c \
  'from cinedub_api.database import create_database; create_database()'
.venv/bin/uvicorn cinedub_api.main:app --app-dir apps/api --host "$api_host" --port "$api_port" &
api_pid=$!
PYTHONPATH=apps/api .venv/bin/python apps/worker/main.py &
worker_pid=$!
npm run dev --workspace @cinedub/web -- --port "$web_port" &
web_pid=$!

wait -n "$api_pid" "$worker_pid" "$web_pid"
