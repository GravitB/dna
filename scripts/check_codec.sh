#!/usr/bin/env bash
# Check that the bundled codec source is available.
set -euo pipefail
cd "$(dirname "$0")/.."
test -f lazarus/dna_codec/encoder.py || { echo "Bundled codec source is missing. Restore lazarus/dna_codec from Git." >&2; exit 1; }
echo "Using bundled codec source (lazarus/dna_codec)"
