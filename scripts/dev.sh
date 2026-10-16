#!/usr/bin/env bash
set -euo pipefail

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Python environment missing. Run: uv sync --group dev" >&2
  exit 1
fi

export PYTHONPATH=apps/api
exec .venv/bin/python scripts/local-runtime.py start
