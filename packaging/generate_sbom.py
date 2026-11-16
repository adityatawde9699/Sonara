"""Write a CycloneDX 1.6 SBOM for one Sonara installer.

The bill of materials is built from what the release build actually used:

- Rust crates from ``Cargo.lock``, narrowed to the target platform with
  ``cargo metadata --filter-platform`` output when given (``--cargo-metadata``).
- Frontend packages from ``package-lock.json``. Only production packages ship
  in the bundled JavaScript; build and test tooling is left out.
- Python distributions installed in the interpreter running this script,
  which in CI is the one that froze the runtime. Build-only tools such as
  PyInstaller are left out.
- The pinned Piper voices, with their published SHA-256 hashes.
- Poppler and Tesseract from the staged tools directory, when given.

No third-party SBOM tool is needed, so the generator adds nothing to the
supply chain it describes. Output is deterministic for the same inputs; set
``SOURCE_DATE_EPOCH`` to fix the timestamp.
"""

from __future__ import annotations

import argparse
import base64
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SBOM_NAMESPACE = uuid.UUID("0b8d7a2e-6f1c-4c55-9d7e-2c5a8f3e9b10")

# Installed in the build environment but not shipped in the frozen runtime.
PYTHON_BUILD_ONLY = {
    "pip", "setuptools", "wheel", "pyinstaller", "pyinstaller-hooks-contrib",
    "altgraph", "macholib", "pefile", "pywin32-ctypes",
}


def _normalize_python_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _component(
    kind: str,
    name: str,
    version: str,
    purl: str | None,
    *,
    hashes: Iterable[tuple[str, str]] = (),
    licenses: Iterable[str] = (),
    group: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    component: dict[str, Any] = {"type": kind, "name": name, "version": version}
    if group:
        component["group"] = group
    if description:
        component["description"] = description
    if purl:
        component["purl"] = purl
        component["bom-ref"] = purl
    else:
        component["bom-ref"] = f"{kind}:{name}@{version}"
    hash_list = [{"alg": alg, "content": content} for alg, content in hashes]
    if hash_list:
        component["hashes"] = hash_list
    license_list = [{"expression": value} if " " in value else {"license": {"id": value}} for value in licenses if value]
    if license_list:
        component["licenses"] = license_list
    return component


def cargo_components(lock_path: Path, metadata_path: Path | None) -> list[dict[str, Any]]:
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    selected: set[tuple[str, str]] | None = None
    workspace: set[str] = set()
    if metadata_path is not None:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        packages = {package["id"]: package for package in metadata["packages"]}
        workspace = {packages[member]["name"] for member in metadata.get("workspace_members", [])}
        selected = {
            (packages[node["id"]]["name"], packages[node["id"]]["version"])
            for node in metadata["resolve"]["nodes"]
        }
    components = []
    for package in lock.get("package", []):
        name, version = package["name"], package["version"]
        if name in workspace or "source" not in package:
            continue  # Sonara itself is the SBOM's root component.
        if selected is not None and (name, version) not in selected:
            continue
        hashes = [("SHA-256", package["checksum"])] if "checksum" in package else []
        components.append(_component("library", name, version, f"pkg:cargo/{name}@{version}", hashes=hashes))
    return components


def npm_components(lock_path: Path) -> list[dict[str, Any]]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    components = []
    for key, package in lock.get("packages", {}).items():
        if not key or package.get("dev") or package.get("link"):
            continue
        name = package.get("name") or key.rsplit("node_modules/", 1)[-1]
        version = package["version"]
        group, _, base = name.rpartition("/")
        purl_name = f"%40{group[1:]}/{base}" if group else base
        hashes = []
        integrity = package.get("integrity", "")
        if integrity.startswith("sha512-"):
            hashes.append(("SHA-512", base64.b64decode(integrity[7:]).hex()))
        components.append(
            _component(
                "library", base, version, f"pkg:npm/{purl_name}@{version}",
                hashes=hashes, licenses=[package.get("license", "")], group=group or None,
            )
        )
    return components


def python_components(distributions: Iterable[importlib.metadata.Distribution]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for distribution in distributions:
        name = distribution.metadata["Name"]
        if not name:
            continue
        normalized = _normalize_python_name(name)
        if normalized in PYTHON_BUILD_ONLY or normalized in seen:
            continue
        version = distribution.version
        license_value = distribution.metadata.get("License-Expression") or ""
        seen[normalized] = _component(
            "library", normalized, version, f"pkg:pypi/{normalized}@{version}",
            licenses=[license_value] if license_value and len(license_value) < 100 else [],
        )
    return list(seen.values())


def voice_components() -> list[dict[str, Any]]:
    sys.path.insert(0, str(ROOT))
    try:
        from tts_engine import PINNED_PIPER_VOICES
    finally:
        sys.path.remove(str(ROOT))
    components = []
    for voice, (model_sha256, config_sha256) in sorted(PINNED_PIPER_VOICES.items()):
        components.append(
            _component(
                "machine-learning-model", voice, "1", None,
                hashes=[("SHA-256", model_sha256)],
                description=f"Piper voice from rhasspy/piper-voices; config SHA-256 {config_sha256}",
            )
        )
    return components


def _tool_version(executable: Path, argument: str) -> str | None:
    try:
        result = subprocess.run(
            [str(executable), argument], capture_output=True, text=True, timeout=30, check=False
        )
    except OSError:
        return None
    match = re.search(r"(\d+\.\d+(?:\.\d+)*)", result.stdout + result.stderr)
    return match.group(1) if match else None


def tool_components(tools_dir: Path) -> list[dict[str, Any]]:
    suffix = ".exe" if os.name == "nt" else ""
    probes = (("poppler", "pdftotext", "-v"), ("tesseract", "tesseract", "--version"))
    components = []
    for name, binary, argument in probes:
        candidates = [path for path in tools_dir.rglob(f"{binary}{suffix}") if path.is_file()]
        version = _tool_version(candidates[0], argument) if candidates else None
        if version:
            components.append(
                _component("application", name, version, f"pkg:generic/{name}@{version}")
            )
    return components


def build_sbom(
    *,
    version: str,
    platform: str,
    components: list[dict[str, Any]],
    timestamp: datetime,
) -> dict[str, Any]:
    components = sorted(components, key=lambda item: (item["type"], item.get("group", ""), item["name"], item["version"]))
    body = json.dumps(components, sort_keys=True)
    serial = uuid.uuid5(SBOM_NAMESPACE, f"{version}|{platform}|{body}")
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tools": {"components": [{"type": "application", "name": "sonara-generate-sbom"}]},
            "component": {
                "type": "application",
                "name": "sonara",
                "version": version,
                "bom-ref": f"sonara@{version}",
                "licenses": [{"license": {"id": "GPL-3.0-only"}}],
                "properties": [{"name": "sonara:platform", "value": platform}],
            },
        },
        "components": components,
    }


def _timestamp() -> datetime:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    return datetime.now(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", required=True, help="Release version, such as v1.0.2")
    parser.add_argument("--platform", required=True, help="Installer platform and architecture label")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cargo-lock", type=Path, default=ROOT / "src-tauri" / "Cargo.lock")
    parser.add_argument("--cargo-metadata", type=Path, help="cargo metadata --filter-platform output")
    parser.add_argument("--npm-lock", type=Path, default=ROOT / "ui-react" / "package-lock.json")
    parser.add_argument("--tools", type=Path, help="Staged Poppler and Tesseract directory")
    parser.add_argument("--no-python", action="store_true", help="Leave out installed Python distributions")
    args = parser.parse_args(argv)

    components = cargo_components(args.cargo_lock, args.cargo_metadata) + npm_components(args.npm_lock)
    if not args.no_python:
        components += python_components(importlib.metadata.distributions())
    components += voice_components()
    if args.tools is not None:
        components += tool_components(args.tools)
    sbom = build_sbom(version=args.version, platform=args.platform, components=components, timestamp=_timestamp())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {len(sbom['components'])} components to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
