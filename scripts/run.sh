#!/usr/bin/env bash
# One command: fetch Erbgut if needed, install, build the UI, start the server on :8000.
set -euo pipefail
cd "$(dirname "$0")/.."
scripts/get_erbgut.sh
(cd lazarus && uv sync --quiet)
(cd web && npm install --silent && npm run build --silent)
echo "Lazarus on http://localhost:8000"
cd lazarus && exec uv run uvicorn lazarus.api:app --host 127.0.0.1 --port 8000
