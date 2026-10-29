"""Ensure the combined release contains every advertised installer."""

from __future__ import annotations

from pathlib import Path
import sys


REQUIRED_BY_PLATFORM = {
    "windows": {"Sonara-windows-x86_64-setup.exe"},
    "linux": {"Sonara-linux-x86_64.deb", "Sonara-linux-x86_64.AppImage"},
    "macos": {"Sonara-macos-aarch64.dmg", "Sonara-macos-x86_64.dmg"},
}
REQUIRED_ALL = set().union(*REQUIRED_BY_PLATFORM.values())


def verify_assets(directory: Path, platform: str = "all") -> None:
    actual = {path.name for path in directory.iterdir() if path.is_file()}
    required = REQUIRED_ALL if platform == "all" else REQUIRED_BY_PLATFORM[platform]
    missing = sorted(required - actual)
    if missing:
        raise ValueError("Missing required installers: " + ", ".join(missing))
    empty = sorted(name for name in required if (directory / name).stat().st_size == 0)
    if empty:
        raise ValueError("Empty installer assets: " + ", ".join(empty))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--platform", choices=("all", *REQUIRED_BY_PLATFORM), default="all")
    arguments = parser.parse_args()
    try:
        verify_assets(arguments.directory, arguments.platform)
    except (KeyError, OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(f"All required {arguments.platform} installer assets are present and non-empty.")
