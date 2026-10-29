from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_version = load_module("sonara_release_version", "packaging/check_release_version.py")
release_assets = load_module("sonara_release_assets", "packaging/prepare_release_assets.py")
asset_verifier = load_module("sonara_release_asset_verifier", "packaging/verify_release_assets.py")
runtime_check = load_module("sonara_frozen_runtime_check", "packaging/check_frozen_runtime.py")
build_architecture = load_module("sonara_build_architecture", "packaging/check_build_architecture.py")
release_matrix = load_module("sonara_release_matrix", "packaging/release_matrix.py")
native_tools_check = load_module("sonara_native_tools_check", "packaging/check_native_tools.py")


class ReleasePackagingTests(unittest.TestCase):
    def test_release_tag_matches_both_desktop_version_files(self):
        cargo = release_version.tomllib.loads((ROOT / "src-tauri/Cargo.toml").read_text(encoding="utf-8"))
        current_version = cargo["package"]["version"]
        self.assertEqual(release_version.check_release_version(f"v{current_version}"), current_version)
        with self.assertRaisesRegex(ValueError, "does not match"):
            release_version.check_release_version("v99.0.0")

    def test_prepares_expected_linux_files_with_stable_names(self):
        version = release_version.tomllib.loads(
            (ROOT / "src-tauri/Cargo.toml").read_text(encoding="utf-8")
        )["package"]["version"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            (bundle / "deb").mkdir(parents=True)
            (bundle / "appimage").mkdir()
            (bundle / f"deb/Sonara_{version}_amd64.deb").write_bytes(b"deb")
            (bundle / f"appimage/Sonara_{version}_amd64.AppImage").write_bytes(b"appimage")

            prepared = release_assets.prepare_assets(bundle, "linux", "x86_64", root / "assets")
            self.assertEqual(
                {path.name for path in prepared},
                {"Sonara-linux-x86_64.deb", "Sonara-linux-x86_64.AppImage"},
            )

    def test_rejects_missing_installer_instead_of_publishing_partial_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Sonara-linux-x86_64.deb").write_bytes(b"deb")
            with self.assertRaisesRegex(ValueError, "Missing required installers"):
                asset_verifier.verify_assets(root)

    def test_platform_release_can_publish_its_complete_subset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Sonara-linux-x86_64.deb").write_bytes(b"deb")
            (root / "Sonara-linux-x86_64.AppImage").write_bytes(b"appimage")
            asset_verifier.verify_assets(root, "linux")

    def test_windows_setup_asset_must_be_unambiguous(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bundle").mkdir()
            (root / "bundle/sonara-setup.exe").write_bytes(b"exe")
            (root / "bundle/other-setup.exe").write_bytes(b"exe")
            with self.assertRaisesRegex(FileNotFoundError, "found 2"):
                release_assets.prepare_assets(root / "bundle", "windows", "x86_64", root / "assets")

    def test_frozen_runtime_check_rejects_missing_inference_dependencies(self):
        result = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"ok": False, "runtimes": {"kokoro-onnx": {"available": False}}}),
            stderr="",
        )
        with patch.object(runtime_check.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "inference runtimes are unavailable"):
                runtime_check.main(Path("runtime"))

    def test_native_runner_architecture_aliases_are_normalized(self):
        self.assertEqual(build_architecture.normalize_architecture("AMD64"), "x86_64")
        self.assertEqual(build_architecture.normalize_architecture("arm64"), "aarch64")
        self.assertEqual(build_architecture.normalize_architecture("unknown"), "")

    def test_release_matrix_selects_only_requested_platform(self):
        selected = release_matrix.release_matrix("linux")["include"]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["platform"], "linux")
        self.assertEqual(len(release_matrix.release_matrix("all")["include"]), 4)

    def test_poppler_bbox_output_is_compared_as_plain_text(self):
        result = native_tools_check.normalize_bbox_text(
            '<word xMin="1">Sonara</word><word>reads</word> local documents aloud.'
        )
        self.assertEqual(result, "Sonara reads local documents aloud.")


if __name__ == "__main__":
    unittest.main()
