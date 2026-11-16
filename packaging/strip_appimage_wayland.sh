#!/usr/bin/env bash
# Repack the Tauri AppImage without its bundled Wayland client libraries.
#
# linuxdeploy copies libwayland-* from the build machine. On a newer host the
# system GPU driver's EGL platform (for example NVIDIA's libnvidia-egl-wayland2)
# then calls into that older libwayland-client and crashes the app before its
# window opens. Every desktop that can show the window already has libwayland,
# so the AppImage uses the host's copy instead.
#
# Needs desktop-file-validate (desktop-file-utils), which appimagetool runs.
# Usage: strip_appimage_wayland.sh <path/to/App.AppImage>
set -euo pipefail

appimage="$(realpath "${1:?Usage: strip_appimage_wayland.sh <AppImage>}")"
tool_image="${TAURI_CACHE_DIR:-$HOME/.cache/tauri}/linuxdeploy-plugin-appimage.AppImage"
if [[ ! -f "$tool_image" ]]; then
  echo "appimagetool not found: $tool_image (run tauri build first)." >&2
  exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"

# Extract instead of mounting, so this works without FUSE on CI runners.
"$tool_image" --appimage-extract >/dev/null
mv squashfs-root tool
appimagetool="$work/tool/appimagetool-prefix/usr/bin/appimagetool"
test -x "$appimagetool" || { echo "appimagetool is missing from $tool_image." >&2; exit 1; }

chmod +x "$appimage"
# Reuse the AppImage's own runtime header so repacking needs no download.
offset="$("$appimage" --appimage-offset)"
head -c "$offset" "$appimage" > runtime
"$appimage" --appimage-extract >/dev/null

shopt -s nullglob
removed=(squashfs-root/usr/lib/libwayland-*.so*)
if (( ${#removed[@]} == 0 )); then
  echo "No bundled libwayland libraries; nothing to strip."
  exit 0
fi
rm -f "${removed[@]}"
printf 'Removed %s\n' "${removed[@]#squashfs-root/}"

ARCH=x86_64 "$appimagetool" --no-appstream --runtime-file runtime squashfs-root repacked.AppImage >/dev/null
chmod +x repacked.AppImage
mv repacked.AppImage "$appimage"
echo "Repacked $appimage without bundled libwayland."
