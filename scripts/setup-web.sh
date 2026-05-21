#!/usr/bin/env bash
# Build web/dist via npm. Uses default TLS first; retries with repo-root ca-bundle.crt only if install fails (same pattern as scripts/setup.sh for pip).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CA_BUNDLE="$ROOT/ca-bundle.crt"

cd "$ROOT/web"

if ! command -v npm >/dev/null 2>&1; then
  echo "[setup-web] ERROR: npm not found. Install Node.js LTS from https://nodejs.org/"
  exit 1
fi

echo "[setup-web] Repository root: $ROOT"
echo "[setup-web] Optional corp CA (retry only if default npm TLS fails): $CA_BUNDLE"
echo "[setup-web] npm install + npm run build in $ROOT/web ..."

unset NODE_EXTRA_CA_CERTS || true
set +e
npm install --no-fund --no-audit
st=$?

if [[ $st -ne 0 && -f "$CA_BUNDLE" ]]; then
  echo ""
  echo "[setup-web] Default npm TLS failed - retrying with repo-root ca-bundle.crt ..."
  export NODE_EXTRA_CA_CERTS="$CA_BUNDLE"
  npm install --no-fund --no-audit --cafile="$CA_BUNDLE"
  st=$?
fi
set -e

if [[ $st -ne 0 ]]; then
  echo ""
  echo "[setup-web] npm install failed."
  echo "            Behind a corp proxy (SELF_SIGNED_CERT_IN_CHAIN): PEM at $CA_BUNDLE"
  echo "Docs: docs/multimode.md (npm TLS)."
  exit 1
fi

npm run build
echo ""
echo "[setup-web] OK - web/dist is ready. Start the API: ./scripts/run-api.sh  then open http://127.0.0.1:8080/"
