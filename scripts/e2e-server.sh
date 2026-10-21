#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${CINEDUB_E2E_STATE_ROOT:-}" ]]; then
  test_state=$CINEDUB_E2E_STATE_ROOT
  if [[ ! "$test_state" =~ ^/tmp/cinedub-e2e-[A-Za-z0-9_]+$ || ! -d "$test_state" || -L "$test_state" || -e "$test_state/cinedub.db" ]]; then
    echo "An explicitly supplied E2E state must be a new empty /tmp/cinedub-e2e-* directory" >&2
    exit 1
  fi
  if [[ -n "$(ls -A "$test_state")" ]]; then
    echo "The explicit E2E directory must be empty" >&2
    exit 1
  fi
else
  test_state=$(mktemp -d /tmp/cinedub-e2e-XXXXXX)
fi
export CINEDUB_ENV=e2e
export CINEDUB_DATABASE_URL="sqlite:///$test_state/cinedub.db"
export CINEDUB_STORAGE_ROOT="$test_state/storage"
export CINEDUB_TRANSCRIBER=${CINEDUB_E2E_TRANSCRIBER:-fake}
export CINEDUB_DIARIZER=fake CINEDUB_TRANSLATOR=fake
export CINEDUB_VOICE_SYNTHESIZER=fake
# Every model-backed stage defaults to its labelled DEMO provider; opt-in specs select local models.
local_or_fake() { [[ "${1:-}" == "1" ]] && echo local || echo fake; }
acoustic=$(local_or_fake "$( [[ "${CINEDUB_E2E_ALIGNMENT:-}${CINEDUB_E2E_PERFORMANCE:-}" == *1* ]] && echo 1)")
export CINEDUB_STEM_SEPARATOR=$(local_or_fake "${CINEDUB_E2E_SEPARATOR:-}")
export CINEDUB_TIMING_ALIGNER=$(local_or_fake "${CINEDUB_E2E_ALIGNMENT:-}")
export CINEDUB_PERFORMANCE_ANALYZER=$acoustic
export CINEDUB_TARGET_TIMING_ALIGNER=$(local_or_fake "${CINEDUB_E2E_PERFORMANCE:-}")
export CINEDUB_DIALOGUE_ADAPTER=$(local_or_fake "${CINEDUB_E2E_ADAPTATION:-}")
export CINEDUB_EMOTION_ANALYZER=$(local_or_fake "${CINEDUB_E2E_EMOTION:-}")
export SARVAM_API_KEY="" CINEDUB_SARVAM_API_KEY=""
export CINEDUB_WEB_ORIGIN=http://127.0.0.1:3011
export NEXT_PUBLIC_CINEDUB_API_URL=http://127.0.0.1:8011
export PYTHONPATH=apps/api

if [[ "${CINEDUB_E2E_LAUNCHER:-}" == "1" ]]; then
  export PORT=3011 CINEDUB_API_PORT=8011 CINEDUB_API_HOST=127.0.0.1
  exec bash scripts/dev.sh
fi

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
