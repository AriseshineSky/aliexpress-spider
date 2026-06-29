#!/usr/bin/env bash
# Start aliexpress-spider crawl (after install.sh).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV_PYTHON="$ROOT/.venv/bin/python"
USER_DATA_DIR="${USER_DATA_DIR:-$HOME/.aliexpress-spider/browser}"

if [ ! -x "$VENV_PYTHON" ]; then
  echo "Error: .venv not found. Run ./scripts/install.sh first." >&2
  exit 1
fi

exec "$VENV_PYTHON" -m aliexpress_spider crawl \
  --user-data-dir "$USER_DATA_DIR" \
  --output-dir "$ROOT/data" \
  "$@"
