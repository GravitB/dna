#!/usr/bin/env bash
# Downloads Erbgut (HackMIT 2026) into vendor/ at the exact commit Lazarus was built against.
# Erbgut has no license file: it is not redistributed in this repo. Credit: github.com/timarnoldev/hackmit2026
set -euo pipefail
cd "$(dirname "$0")/.."
COMMIT=556924ab285980c5523a93871474ec773d32b7d9
DEST=vendor/hackmit2026-main
if [ -f "$DEST/dnacodec/encoder.py" ]; then echo "Erbgut already in $DEST"; exit 0; fi
mkdir -p vendor
git clone --quiet https://github.com/timarnoldev/hackmit2026.git "$DEST"
git -C "$DEST" checkout --quiet "$COMMIT"
echo "Erbgut ready in $DEST ($(git -C "$DEST" rev-parse --short HEAD))"
