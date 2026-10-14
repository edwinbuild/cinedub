#!/usr/bin/env bash
set -euo pipefail

test_state=$(mktemp -d /tmp/cinedub-e2e-XXXXXX)
export CINEDUB_DATABASE_URL="sqlite:///$test_state/cinedub.db"
export CINEDUB_STORAGE_ROOT="$test_state/storage"
export CINEDUB_TRANSCRIBER=${CINEDUB_E2E_TRANSCRIBER:-fake}
export CINEDUB_DIARIZER=fake CINEDUB_TRANSLATOR=fake
export CINEDUB_VOICE_SYNTHESIZER=fake
export SARVAM_API_KEY="" CINEDUB_SARVAM_API_KEY=""
export CINEDUB_WEB_ORIGIN=http://127.0.0.1:3011
export NEXT_PUBLIC_CINEDUB_API_URL=http://127.0.0.1:8011
export PYTHONPATH=apps/api

cleanup() {
  kill "${api_pid:-}" "${worker_pid:-}" "${web_pid:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
.venv/bin/python -c 'from cinedub_api.database import create_database; create_database()'
.venv/bin/uvicorn cinedub_api.main:app --host 127.0.0.1 --port 8011 &
api_pid=$!
.venv/bin/python apps/worker/main.py &
worker_pid=$!
npm run dev --workspace @cinedub/web -- --port 3011 &
web_pid=$!
wait -n "$api_pid" "$worker_pid" "$web_pid"
