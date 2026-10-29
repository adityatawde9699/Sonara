#!/usr/bin/env bash
set -euo pipefail

tools="$(cd "$1" && pwd)"
export PATH="$tools/bin:$PATH"
export TESSDATA_PREFIX="$tools/tessdata"
export POPPLER_DATADIR="$tools/share/poppler"
export LD_LIBRARY_PATH="$tools/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

"$tools/bin/pdftotext" -v >/dev/null 2>&1
"$tools/bin/pdftoppm" -v >/dev/null 2>&1
"$tools/bin/tesseract" --list-langs | grep -qx 'eng'
echo "Installed Poppler and English Tesseract resources load successfully."
