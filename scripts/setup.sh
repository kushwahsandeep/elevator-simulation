#!/usr/bin/env bash
# Install core + API Python deps (.venv). Run once from repo root or via this script path:
#   chmod +x scripts/setup.sh && ./scripts/setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Creating virtual environment in .venv ..."
  python3 -m venv .venv
fi

# shellcheck source=/dev/null
source .venv/bin/activate

COMMON_HOST_ARGS=(--trusted-host pypi.org --trusted-host files.pythonhosted.org)
# pip: default TLS first; ca-bundle/trusted-host only after failure (--retries 0 limits urllib3 noise).
PIP_FAST=(--retries 0)

print_ssl_failure() {
  echo ""
  echo "[setup] ERROR: pip could not use PyPI (often: SSL CERTIFICATE_VERIFY_FAILED / self-signed certificate in chain)."
  echo "[setup] Put your TLS CA bundle here, then run this script again:"
  echo "          $ROOT/ca-bundle.crt"
  echo "[setup] More options: docs/multimode.md (pip and SSL)"
}

upgrade_pip_with_retries() {
  set +e
  pip install "${PIP_FAST[@]}" --upgrade pip
  local st=$?
  if [[ $st -ne 0 && -f "$ROOT/ca-bundle.crt" ]]; then
    echo ""
    echo "Retrying pip upgrade with repo-root ca-bundle.crt ..."
    pip install "${PIP_FAST[@]}" --upgrade pip --cert "$ROOT/ca-bundle.crt" "${COMMON_HOST_ARGS[@]}"
    st=$?
  fi
  if [[ $st -ne 0 ]]; then
    echo ""
    echo "Retrying pip upgrade with trusted-hosts only ..."
    pip install "${PIP_FAST[@]}" --upgrade pip "${COMMON_HOST_ARGS[@]}"
    st=$?
  fi
  set -e
  if [[ $st -ne 0 ]]; then
    print_ssl_failure
  fi
  return "$st"
}

install_requirements_with_retries() {
  local req=$1
  set +e
  pip install "${PIP_FAST[@]}" -r "$req"
  local st=$?
  if [[ $st -ne 0 && -f "$ROOT/ca-bundle.crt" ]]; then
    echo ""
    echo "Retrying pip install -r ${req} with ca-bundle.crt ..."
    pip install "${PIP_FAST[@]}" -r "$req" --cert "$ROOT/ca-bundle.crt" "${COMMON_HOST_ARGS[@]}"
    st=$?
  fi
  if [[ $st -ne 0 ]]; then
    echo ""
    echo "Retrying pip install -r ${req} with trusted-hosts only ..."
    pip install "${PIP_FAST[@]}" -r "$req" "${COMMON_HOST_ARGS[@]}"
    st=$?
  fi
  set -e
  if [[ $st -ne 0 ]]; then
    print_ssl_failure
  fi
  return "$st"
}

echo "Installing Python deps (requirements.txt + requirements-api.txt) ..."
upgrade_pip_with_retries || exit 1
install_requirements_with_retries requirements.txt || exit 1
install_requirements_with_retries requirements-api.txt || exit 1

if command -v npm >/dev/null 2>&1; then
  echo ""
  echo "Building web UI (optional)..."
  if bash "$ROOT/scripts/setup-web.sh"; then
    :
  else
    echo "[setup] Web UI build failed - Python CLI/API are still OK. Fix Node/npm and run scripts/setup-web.sh"
  fi
else
  echo ""
  echo "[setup] npm not on PATH - skipped web UI build. API still works (e.g. /docs)."
  echo "        For the browser UI: install Node.js LTS, then ./scripts/setup-web.sh"
  echo "        (that creates web/dist/; it is gitignored — build after clone on any machine with npm)."
fi

echo ""
echo "Done. Run next steps from project root: $ROOT"
echo "  source \"$ROOT/.venv/bin/activate\""
echo "  python -m pytest tests -v"
echo "  python main.py examples/sample_requests.csv -n 2 -e 1 -c 8"
echo "  ./scripts/run-api.sh"
echo "  Or from repo root: python -m uvicorn api.server:app --reload --host 127.0.0.1 --port 8080"
echo "  Open http://127.0.0.1:8080/ for the UI when web/dist exists, else see /docs."
