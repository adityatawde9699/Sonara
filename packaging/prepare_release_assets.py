"""Copy Tauri installers to stable cross-platform release filenames."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil


ASSET_SUFFIXES = {
    ("windows", "x86_64"): [("-setup.exe", "Sonara-windows-x86_64-setup.exe")],
    ("linux", "x86_64"): [
        (".deb", "Sonara-linux-x86_64.deb"),
        (".appimage", "Sonara-linux-x86_64.AppImage"),
    ],
    ("macos", "aarch64"): [(".dmg", "Sonara-macos-aarch64.dmg")],
    ("macos", "x86_64"): [(".dmg", "Sonara-macos-x86_64.dmg")],
}


def prepare_assets(bundle_root: Path, platform: str, arch: str, output: Path) -> list[Path]:
    try:
        expected = ASSET_SUFFIXES[(platform, arch)]
    except KeyError as error:
        raise ValueError(f"Unsupported release target: {platform}/{arch}") from error
    candidates = [path for path in bundle_root.rglob("*") if path.is_file()]
    output.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for suffix, filename in expected:
        matches = [path for path in candidates if path.name.lower().endswith(suffix.lower())]
        if len(matches) != 1:
            raise FileNotFoundError(
                f"Expected exactly one {suffix} installer for {platform}/{arch}; found {len(matches)}."
            )
        destination = output / filename
        shutil.copy2(matches[0], destination)
        copied.append(destination)
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--platform", choices=("windows", "linux", "macos"), required=True)
    parser.add_argument("--arch", choices=("x86_64", "aarch64"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for asset in prepare_assets(args.bundle_root, args.platform, args.arch, args.output):
        print(asset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
