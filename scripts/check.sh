#!/usr/bin/env bash
set -euo pipefail

UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/cinedub-uv-cache} uv run ruff check apps tests scripts migrations
UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/cinedub-uv-cache} uv run pytest -q
npm run contracts:check
npm run typecheck
npm run lint:web
