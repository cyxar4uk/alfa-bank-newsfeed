#!/usr/bin/env bash
# Линтер, форматирование и тесты одной командой: ./check.sh (из apps/api)
set -euo pipefail
cd "$(dirname "$0")"
uv run ruff check .
uv run ruff format --check .
uv run pytest "$@"
