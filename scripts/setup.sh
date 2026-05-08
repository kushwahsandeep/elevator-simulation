#!/usr/bin/env bash
# One-time environment setup for this repo (macOS / Linux).
# Run from repo root:  chmod +x scripts/setup.sh && ./scripts/setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Creating virtual environment in .venv ..."
  python3 -m venv .venv
fi

# shellcheck source=/dev/null
source .venv/bin/activate

echo "Installing dependencies (pytest) ..."
if pip install --upgrade pip && pip install -r requirements.txt; then
  :
else
  echo ""
  echo "If SSL / proxy errors, retry with:"
  echo '  pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org'
  exit 1
fi

echo ""
echo "Done. Next time: source .venv/bin/activate"
echo "  python -m pytest tests -v"
echo "  python main.py examples/sample_requests.csv -n 2 -e 1 -c 8"
