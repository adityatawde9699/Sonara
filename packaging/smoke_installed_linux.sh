#!/usr/bin/env bash
set -euo pipefail

assets="$(cd "$1" && pwd)"
deb="$assets/Sonara-linux-x86_64.deb"
appimage="$assets/Sonara-linux-x86_64.AppImage"
sentinel="$HOME/.local/share/com.sonara.reader/uninstall-preservation-check.txt"
mkdir -p "$(dirname "$sentinel")"
echo "Keep this user data during package removal." > "$sentinel"

sudo apt-get install --yes "$deb"
installed_app="$(command -v sonara-desktop)"
installed_runtime="$(find /usr -type f -path '*/resources/sonara/sonara-runtime' -print -quit)"
installed_tools="$(find /usr -type d -path '*/resources/sonara/tools' -print -quit)"
test -n "$installed_app" && test -n "$installed_runtime" && test -n "$installed_tools"
xvfb-run --auto-servernum "$installed_app" --sonara-smoke-check
bash "$GITHUB_WORKSPACE/packaging/smoke_installed_tools.sh" "$installed_tools"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"
chmod +x "$appimage"
"$appimage" --appimage-extract >/dev/null
appimage_app="$(find squashfs-root -type f -name sonara-desktop -print -quit)"
appimage_tools="$(find squashfs-root -type d -path '*/resources/sonara/tools' -print -quit)"
test -n "$appimage_app" && test -n "$appimage_tools"
xvfb-run --auto-servernum "$appimage_app" --sonara-smoke-check
bash "$GITHUB_WORKSPACE/packaging/smoke_installed_tools.sh" "$appimage_tools"

sudo apt-get remove --yes sonara-desktop
test -f "$sentinel"
echo "Linux clean .deb/AppImage install, resource discovery, PDF/OCR, and user-data preservation checks passed."
