"""Ensure native CI runners match the architecture used in release filenames."""

from __future__ import annotations

import argparse
import platform


ALIASES = {
    "amd64": "x86_64",
    "x64": "x86_64",
    "x86_64": "x86_64",
    "arm64": "aarch64",
    "aarch64": "aarch64",
}


def normalize_architecture(machine: str) -> str:
    return ALIASES.get(machine.lower(), "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", choices=("x86_64", "aarch64"), required=True)
    args = parser.parse_args()
    actual = normalize_architecture(platform.machine())
    if actual != args.expected:
        raise SystemExit(f"Runner architecture mismatch: expected {args.expected}, detected {platform.machine()} ({actual or 'unknown'}).")
    print(f"Confirmed native build architecture: {actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
