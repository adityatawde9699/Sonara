"""Return the native CI targets selected for a release run."""

from __future__ import annotations

import json
import sys


TARGETS = {
    "windows": {"label": "Windows x86_64", "os": "windows-latest", "platform": "windows", "arch": "x86_64", "bundle": "nsis"},
    "linux": {"label": "Linux x86_64", "os": "ubuntu-24.04", "platform": "linux", "arch": "x86_64", "bundle": "deb,appimage"},
    "macos-aarch64": {"label": "macOS aarch64", "os": "macos-15", "platform": "macos", "arch": "aarch64", "bundle": "dmg"},
    "macos-x86_64": {"label": "macOS x86_64", "os": "macos-15-intel", "platform": "macos", "arch": "x86_64", "bundle": "dmg"},
}


def release_matrix(target: str) -> dict[str, list[dict[str, str]]]:
    if target == "all":
        selected = list(TARGETS.values())
    elif target == "macos":
        selected = [TARGETS["macos-aarch64"], TARGETS["macos-x86_64"]]
    elif target in TARGETS:
        selected = [TARGETS[target]]
    else:
        raise ValueError(f"Unsupported release target: {target}")
    return {"include": selected}


if __name__ == "__main__":
    try:
        print(json.dumps(release_matrix(sys.argv[1]), separators=(",", ":")))
    except (IndexError, ValueError) as error:
        raise SystemExit(str(error)) from error
