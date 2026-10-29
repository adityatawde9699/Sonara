"""Ensure the combined release contains every advertised installer."""

from __future__ import annotations

from pathlib import Path
import sys


REQUIRED = {
    "Sonara-windows-x86_64-setup.exe",
    "Sonara-linux-x86_64.deb",
    "Sonara-linux-x86_64.AppImage",
    "Sonara-macos-aarch64.dmg",
    "Sonara-macos-x86_64.dmg",
}


def verify_assets(directory: Path) -> None:
    actual = {path.name for path in directory.iterdir() if path.is_file()}
    missing = sorted(REQUIRED - actual)
    if missing:
        raise ValueError("Missing required installers: " + ", ".join(missing))
    empty = sorted(name for name in REQUIRED if (directory / name).stat().st_size == 0)
    if empty:
        raise ValueError("Empty installer assets: " + ", ".join(empty))


if __name__ == "__main__":
    try:
        verify_assets(Path(sys.argv[1]))
    except (IndexError, OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print("All five platform installer assets are present and non-empty.")
