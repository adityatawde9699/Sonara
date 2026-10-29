"""Fail tagged releases whose tag and desktop bundle versions disagree."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def check_release_version(tag: str) -> str:
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("Release tags must use stable vMAJOR.MINOR.PATCH versions.")
    version = tag[1:]
    cargo = tomllib.loads((ROOT / "src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    tauri = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    actual = {"Cargo.toml": cargo["package"]["version"], "tauri.conf.json": tauri["version"]}
    mismatched = [f"{name}={value}" for name, value in actual.items() if value != version]
    if mismatched:
        raise ValueError(f"Release tag {tag} does not match desktop version {version}: " + ", ".join(mismatched))
    return version


if __name__ == "__main__":
    release_tag = os.environ.get("RELEASE_TAG", "")
    print(f"Validated release version {check_release_version(release_tag)}")
