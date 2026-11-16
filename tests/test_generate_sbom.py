import base64
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))

import generate_sbom  # noqa: E402


class FakeDistribution:
    def __init__(self, name, version, license_expression=""):
        self.metadata = {"Name": name, "License-Expression": license_expression}
        self.version = version


class SbomTests(unittest.TestCase):
    def test_cargo_components_follow_the_target_platform_and_skip_the_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "Cargo.lock"
            lock.write_text(
                """
[[package]]
name = "sonara-desktop"
version = "1.0.1"

[[package]]
name = "serde"
version = "1.0.229"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "aa"

[[package]]
name = "windows-sys"
version = "0.61.2"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "bb"
""",
                encoding="utf-8",
            )
            metadata = Path(directory) / "metadata.json"
            metadata.write_text(json.dumps({
                "packages": [
                    {"id": "root", "name": "sonara-desktop", "version": "1.0.1"},
                    {"id": "serde", "name": "serde", "version": "1.0.229"},
                ],
                "workspace_members": ["root"],
                "resolve": {"nodes": [{"id": "root"}, {"id": "serde"}]},
            }), encoding="utf-8")
            everything = generate_sbom.cargo_components(lock, None)
            linux = generate_sbom.cargo_components(lock, metadata)
        self.assertEqual([item["name"] for item in everything], ["serde", "windows-sys"])
        self.assertEqual([item["purl"] for item in linux], ["pkg:cargo/serde@1.0.229"])
        self.assertEqual(linux[0]["hashes"], [{"alg": "SHA-256", "content": "aa"}])

    def test_npm_components_are_production_only_with_scoped_purls_and_hashes(self):
        digest = hashlib.sha512(b"react").digest()
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "package-lock.json"
            lock.write_text(json.dumps({"packages": {
                "": {"name": "ui-react"},
                "node_modules/react": {
                    "version": "19.3.1", "license": "MIT",
                    "integrity": "sha512-" + base64.b64encode(digest).decode(),
                },
                "node_modules/@scope/lib": {"version": "1.0.0"},
                "node_modules/vite": {"version": "8.0.0", "dev": True},
            }}), encoding="utf-8")
            components = generate_sbom.npm_components(lock)
        by_name = {item["name"]: item for item in components}
        self.assertEqual(set(by_name), {"react", "lib"})
        self.assertEqual(by_name["lib"]["purl"], "pkg:npm/%40scope/lib@1.0.0")
        self.assertEqual(by_name["lib"]["group"], "@scope")
        self.assertEqual(by_name["react"]["hashes"], [{"alg": "SHA-512", "content": digest.hex()}])
        self.assertEqual(by_name["react"]["licenses"], [{"license": {"id": "MIT"}}])

    def test_python_components_leave_out_build_tools_and_normalize_names(self):
        components = generate_sbom.python_components([
            FakeDistribution("Piper_TTS", "1.8.0", "GPL-3.0-or-later"),
            FakeDistribution("pyinstaller", "6.22.3"),
            FakeDistribution("pip", "25.0"),
            FakeDistribution("piper-tts", "1.8.0"),  # duplicate install record
        ])
        self.assertEqual([item["purl"] for item in components], ["pkg:pypi/piper-tts@1.8.0"])

    def test_document_is_deterministic_with_unique_references(self):
        components = generate_sbom.npm_components(ROOT / "ui-react" / "package-lock.json")
        components += generate_sbom.voice_components()
        stamp = datetime(2026, 11, 16, tzinfo=timezone.utc)
        first = generate_sbom.build_sbom(version="v1", platform="linux-x86_64", components=list(components), timestamp=stamp)
        second = generate_sbom.build_sbom(version="v1", platform="linux-x86_64", components=list(reversed(components)), timestamp=stamp)
        self.assertEqual(first, second)
        self.assertEqual(first["specVersion"], "1.6")
        self.assertEqual(first["metadata"]["timestamp"], "2026-11-16T00:00:00Z")
        references = [item["bom-ref"] for item in first["components"]]
        self.assertEqual(len(references), len(set(references)))

    def test_repository_sbom_lists_shipped_parts_and_no_build_tooling(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sbom.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = generate_sbom.main([
                    "--version", "v1", "--platform", "linux-x86_64", "--output", str(output), "--no-python",
                ])
            self.assertEqual(code, 0)
            sbom = json.loads(output.read_text(encoding="utf-8"))
        names = {item["name"] for item in sbom["components"]}
        self.assertTrue({"tauri", "react", "react-dom", "en_US-ryan-medium"} <= names)
        self.assertNotIn("vite", names)
        self.assertNotIn("sonara-desktop", names)
        voice = next(item for item in sbom["components"] if item["name"] == "en_US-ryan-medium")
        self.assertEqual(voice["type"], "machine-learning-model")
        self.assertEqual(len(voice["hashes"][0]["content"]), 64)


if __name__ == "__main__":
    unittest.main()
