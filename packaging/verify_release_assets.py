"""Ensure the combined release contains every advertised installer and its SBOM."""

from __future__ import annotations

from pathlib import Path
import sys


REQUIRED_BY_PLATFORM = {
    "windows": {"Sonara-windows-x86_64-setup.exe"},
    "linux": {"Sonara-linux-x86_64.deb", "Sonara-linux-x86_64.AppImage"},
    "macos": {"Sonara-macos-aarch64.dmg", "Sonara-macos-x86_64.dmg"},
}
REQUIRED_ALL = set().union(*REQUIRED_BY_PLATFORM.values())
# Linux and macOS only, used while the Windows installer is blocked.
REQUIRED_UNIX = REQUIRED_BY_PLATFORM["linux"] | REQUIRED_BY_PLATFORM["macos"]
# One CycloneDX SBOM per built target (packaging/generate_sbom.py).
SBOM_BY_PLATFORM = {
    "windows": {"Sonara-windows-x86_64.cdx.json"},
    "linux": {"Sonara-linux-x86_64.cdx.json"},
    "macos": {"Sonara-macos-aarch64.cdx.json", "Sonara-macos-x86_64.cdx.json"},
}


def _platforms(platform: str) -> tuple[str, ...]:
    if platform == "all":
        return tuple(REQUIRED_BY_PLATFORM)
    if platform == "unix":
        return ("linux", "macos")
    if platform not in REQUIRED_BY_PLATFORM:
        raise KeyError(platform)
    return (platform,)


def verify_assets(directory: Path, platform: str = "all") -> None:
    actual = {path.name for path in directory.iterdir() if path.is_file()}
    platforms = _platforms(platform)
    required = set().union(*(REQUIRED_BY_PLATFORM[name] for name in platforms))
    sboms = set().union(*(SBOM_BY_PLATFORM[name] for name in platforms))
    missing = sorted(required - actual)
    if missing:
        raise ValueError("Missing required installers: " + ", ".join(missing))
    missing_sboms = sorted(sboms - actual)
    if missing_sboms:
        raise ValueError("Missing SBOMs: " + ", ".join(missing_sboms))
    empty = sorted(name for name in required | sboms if (directory / name).stat().st_size == 0)
    if empty:
        raise ValueError("Empty release assets: " + ", ".join(empty))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--platform", choices=("all", "unix", *REQUIRED_BY_PLATFORM), default="all")
    arguments = parser.parse_args()
    try:
        verify_assets(arguments.directory, arguments.platform)
    except (KeyError, OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(f"All required {arguments.platform} installers and SBOMs are present and non-empty.")
