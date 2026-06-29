#!/usr/bin/env bash
# Linux / macOS installer for aliexpress-spider
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"

echo "==> aliexpress-spider installer"
echo "Project: $ROOT"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Error: python3 not found. Install Python 3.10+ first." >&2
  exit 1
fi

PY_VERSION="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "Python: $PY_VERSION ($("$PYTHON" -c 'import sys; print(sys.executable)'))"

"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "Error: Python 3.10+ required." >&2; exit 1; }

if [ ! -d .venv ]; then
  echo "==> Creating virtual environment .venv"
  "$PYTHON" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Upgrading pip"
python -m pip install --upgrade pip

echo "==> Installing package and dependencies"
pip install -e .

echo "==> Installing Playwright Chromium"
python -m playwright install chromium

echo "==> Verifying install"
python -c "import em_product; import aliexpress_spider; print('em_product OK')"

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "==> Created .env from .env.example (edit before crawling)"
fi

echo
echo "Installation complete."
echo
echo "Next steps:"
echo "  ./scripts/verify.sh          # pass captcha once"
echo "  ./scripts/start.sh           # start crawl (headless)"
echo "  ./scripts/start.sh --headed --no-exit-on-block --captcha-wait 120"
echo
