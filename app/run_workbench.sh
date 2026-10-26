#!/usr/bin/env bash
# USDM -> P21 Workbench launcher (macOS / Linux)
# Usage: ./run_workbench.sh [--port 8765] [--base-url https://my-company.pinnacle21.com] [--no-browser]
# Optional: export P21_API_KEY=... before running to use the P21E API without typing the key in the UI.
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.8+ is required. On macOS install it from https://www.python.org/downloads/ or with: brew install python" >&2
  exit 1
fi

echo "Starting USDM -> P21 Workbench with $($PY --version 2>&1) ..."
exec "$PY" usdm_p21_app.py "$@"
