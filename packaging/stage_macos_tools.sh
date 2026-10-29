#!/usr/bin/env bash
set -euo pipefail

output="$1"
mkdir -p "$output/bin" "$output/tessdata" "$output/share" "$output/licenses"

poppler_prefix="$(brew --prefix poppler)"
tesseract_prefix="$(brew --prefix tesseract)"
cp "${poppler_prefix}/bin/pdftotext" "$output/bin/pdftotext"
cp "${poppler_prefix}/bin/pdftoppm" "$output/bin/pdftoppm"
cp "${tesseract_prefix}/bin/tesseract" "$output/bin/tesseract"
cp "${tesseract_prefix}/share/tessdata/eng.traineddata" "$output/tessdata/eng.traineddata"
cp -R "${tesseract_prefix}/share/tessdata/configs" "$output/tessdata/configs"
cp -R "${tesseract_prefix}/share/tessdata/tessconfigs" "$output/tessdata/tessconfigs"

if [[ -d "${poppler_prefix}/share/poppler" ]]; then
  cp -R "${poppler_prefix}/share/poppler" "$output/share/poppler"
fi

for name in poppler tesseract; do
  prefix="$(brew --prefix "$name")"
  license="$(find "$prefix/share/doc" -type f \( -iname COPYING -o -iname LICENSE -o -iname LICENSE.txt \) -print -quit 2>/dev/null || true)"
  if [[ -n "$license" ]]; then
    cp "$license" "$output/licenses/${name}-$(basename "$license")"
  fi
done

# Bundle each executable's transitive dylib closure and rewrite install names
# to resolve beside the staged tools. System-provided /usr/lib dependencies remain.
dylibbundler -od -b \
  -x "$output/bin/pdftotext" \
  -x "$output/bin/pdftoppm" \
  -x "$output/bin/tesseract" \
  -d "$output/lib" \
  -p '@executable_path/../lib'

for tool in "$output/bin/pdftotext" "$output/bin/pdftoppm" "$output/bin/tesseract"; do
  otool -L "$tool" | while read -r dependency _; do
    [[ -z "$dependency" || "$dependency" == "$tool:" ]] && continue
    case "$dependency" in
      /opt/homebrew/*|/usr/local/*)
        echo "Unbundled Homebrew dependency remains in $tool: $dependency" >&2
        exit 1
        ;;
    esac
  done
done
