#!/usr/bin/env bash
# Clean reinstall: remove .venv and run install.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
echo "==> Reinstall aliexpress-spider (clean .venv)"
rm -rf .venv
exec "$ROOT/scripts/install.sh"
