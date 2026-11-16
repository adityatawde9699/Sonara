#!/usr/bin/env bash
set -euo pipefail

assets="$(cd "$1" && pwd)"
deb="$assets/Sonara-linux-x86_64.deb"
appimage="$assets/Sonara-linux-x86_64.AppImage"
sentinel="$HOME/.local/share/com.sonara.reader/uninstall-preservation-check.txt"
mkdir -p "$(dirname "$sentinel")"
echo "Keep this user data during package removal." > "$sentinel"

sudo apt-get install --yes "$deb"
# Fail with a message, not a later "command not found", when a part is
# missing. (`set -e` ignores a failure inside an `a && b && c` list.)
require() {
  if [[ -z "$2" ]]; then
    echo "Installed package is missing $1." >&2
    exit 1
  fi
}

# Tauri installs bundle resources under /usr/lib/<product>/ on Linux, so
# the staged tree lands at /usr/lib/Sonara/sonara/.
installed_app="$(command -v sonara-desktop || true)"
installed_runtime="$(find /usr/lib -type f -path '*/sonara/sonara-runtime' -print -quit)"
installed_tools="$(find /usr/lib -type d -path '*/sonara/tools' -print -quit)"
require "the sonara-desktop launcher" "$installed_app"
require "the bundled inference runtime" "$installed_runtime"
require "the bundled document tools" "$installed_tools"
xvfb-run --auto-servernum "$installed_app" --sonara-smoke-check
bash "$GITHUB_WORKSPACE/packaging/smoke_installed_tools.sh" "$installed_tools"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"
chmod +x "$appimage"
"$appimage" --appimage-extract >/dev/null
appimage_app="$(find squashfs-root -type f -name sonara-desktop -print -quit)"
appimage_tools="$(find squashfs-root -type d -path '*/sonara/tools' -print -quit)"
require "the AppImage executable" "$appimage_app"
require "the AppImage document tools" "$appimage_tools"
# Start through AppRun, as the AppImage does: Tauri's AppImage rewrites
# WebKit's helper paths to be relative to the directory AppRun enters.
test -x squashfs-root/AppRun || { echo "The AppImage has no AppRun launcher." >&2; exit 1; }
xvfb-run --auto-servernum squashfs-root/AppRun --sonara-smoke-check
bash "$GITHUB_WORKSPACE/packaging/smoke_installed_tools.sh" "$appimage_tools"

# Remove by the package's own name (Tauri derives it from the product name).
sudo apt-get remove --yes "$(dpkg-deb --field "$deb" Package)"
test -f "$sentinel"
echo "Linux clean .deb/AppImage install, resource discovery, PDF/OCR, and user-data preservation checks passed."
