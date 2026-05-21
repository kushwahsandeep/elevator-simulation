#!/usr/bin/env bash
# Start FastAPI from repo root (so `import api` works). Run:  ./scripts/run-api.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f "$ROOT/.venv/bin/python" ]]; then
  echo "ERROR: No .venv found. Run scripts/setup.sh from the repo root first."
  exit 1
fi

echo "[run-api] Project root: $ROOT"
echo "[run-api] Swagger: http://127.0.0.1:8080/docs"
if [[ ! -f "$ROOT/web/dist/index.html" ]]; then
  echo ""
  echo "WARNING: web/dist/index.html is missing — the React UI will NOT load at http://127.0.0.1:8080/"
  echo "          You will only see a placeholder page until you build the bundle."
  echo "          Fix: run  ./scripts/setup-web.sh   (requires Node.js and npm)"
  echo ""
else
  echo "[run-api] SPA UI:   http://127.0.0.1:8080/"
fi
echo '[run-api] Tip: use 127.0.0.1 instead of localhost if the browser cannot connect.'
HOST="${ELEVATOR_API_HOST:-127.0.0.1}"
exec "$ROOT/.venv/bin/python" -m uvicorn api.server:app --reload --host "$HOST" --port 8080
