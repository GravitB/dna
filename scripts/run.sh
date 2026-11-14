#!/usr/bin/env bash
# One command: fetch Erbgut if needed, install, build the UI, start the server on :8000.
set -euo pipefail
cd "$(dirname "$0")/.."
scripts/get_erbgut.sh
if command -v uv >/dev/null 2>&1; then
  (cd lazarus && uv sync --quiet)
elif [ ! -x lazarus/.venv/bin/python ]; then
  echo "Install uv (https://docs.astral.sh/uv/getting-started/installation/) and rerun scripts/run.sh" >&2
  exit 1
fi
(cd web && npm ci --silent && npm run build --silent)
echo "Lazarus on http://localhost:8000"
cd lazarus && exec .venv/bin/python -m uvicorn lazarus.api:app --host 127.0.0.1 --port 8000
