#!/usr/bin/env bash
set -euo pipefail

dmg="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
mount="$(mktemp -d)"
# Resolve symlinks: mktemp lands under /var, a symlink to /private/var, and
# Tauri refuses to start an executable whose path contains a symlink.
install_root="$(cd "$(mktemp -d)" && pwd -P)"
user_data="$HOME/Library/Application Support/com.sonara.reader"
sentinel="$user_data/uninstall-preservation-check.txt"
mkdir -p "$user_data"
echo "Keep this user data during uninstall." > "$sentinel"

device="$(hdiutil attach "$dmg" -nobrowse -readonly -mountpoint "$mount" | awk '/\/dev\// { print $1; exit }')"
app_source="$(find "$mount" -maxdepth 2 -name '*.app' -print -quit)"
if [[ -z "$device" || -z "$app_source" ]]; then
  echo "Could not mount the macOS installer image." >&2
  exit 1
fi
app="$install_root/Sonara.app"
ditto "$app_source" "$app"
codesign --verify --deep --strict --verbose=2 "$app"
if [[ "${SONARA_MACOS_UNSIGNED:-}" == "1" ]]; then
  signing="ad hoc signature (Gatekeeper and notarization not checked: unsigned build)"
else
  spctl --assess --type execute --verbose=2 "$app"
  xcrun stapler validate "$dmg"
  signing="code-signature, notarization"
fi

app_executable="$(find "$app/Contents/MacOS" -type f -perm -111 -print -quit)"
tools="$app/Contents/Resources/sonara/tools"
test -x "$app_executable" && test -d "$tools"
"$app_executable" --sonara-smoke-check
bash packaging/smoke_installed_tools.sh "$tools"

hdiutil detach "$device" -quiet
rm -rf "$app" "$install_root" "$mount"
test -f "$sentinel"
echo "macOS clean DMG install, resource discovery, PDF/OCR, ${signing}, and user-data checks passed."
