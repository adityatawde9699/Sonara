import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import model_downloads
from model_downloads import DownloadError, Model, ModelFile
from tts_engine import PINNED_PIPER_VOICES


def make_model(*payloads: bytes) -> Model:
    files = tuple(
        ModelFile(f"file{index}.bin", f"https://example.test/file{index}.bin", len(data), hashlib.sha256(data).hexdigest())
        for index, data in enumerate(payloads)
    )
    return Model(id="test", kind="piper", label="Test", files=files)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeOpener:
    """Serves fixed bytes per URL, like an HTTPS server."""

    def __init__(self, bodies: dict[str, bytes], error: Exception | None = None):
        self.bodies = bodies
        self.error = error
        self.requested: list[str] = []

    def open(self, request, timeout=None):
        self.requested.append(request.full_url)
        if self.error is not None:
            raise self.error
        return FakeResponse(self.bodies[request.full_url])


class CatalogTests(unittest.TestCase):
    def test_every_source_is_https_at_a_fixed_revision(self):
        for model in model_downloads.CATALOG.values():
            for file in model.files:
                self.assertTrue(file.url.startswith("https://"), file.url)
                self.assertRegex(file.sha256, r"^[0-9a-f]{64}$")
                self.assertGreater(file.size, 0)
                self.assertNotIn("/main/", file.url)

    def test_piper_hashes_are_the_ones_enforced_at_load(self):
        for voice, (model_sha, config_sha) in PINNED_PIPER_VOICES.items():
            files = model_downloads.CATALOG[voice].files
            self.assertEqual([file.sha256 for file in files], [model_sha, config_sha])
            self.assertEqual([file.name for file in files], [f"{voice}.onnx", f"{voice}.onnx.json"])

    def test_kokoro_installs_the_file_names_the_engine_loads(self):
        names = [file.name for file in model_downloads.KOKORO.files]
        self.assertEqual(names, ["kokoro-v1.0.onnx", "voices-v1.0.bin"])


class InstallTests(unittest.TestCase):
    def test_verified_files_are_installed_and_reported(self):
        model = make_model(b"model weights", b"config")
        opener = FakeOpener({file.url: data for file, data in zip(model.files, (b"model weights", b"config"))})
        progress: list[tuple[int, int]] = []
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "models"
            model_downloads.install(model, target, opener=opener, on_progress=lambda r, t: progress.append((r, t)))
            self.assertEqual((target / "file0.bin").read_bytes(), b"model weights")
            self.assertEqual((target / "file1.bin").read_bytes(), b"config")
            self.assertEqual(sorted(path.name for path in target.iterdir()), ["file0.bin", "file1.bin"])
            self.assertTrue(model_downloads.is_installed(model, target))
        self.assertEqual(progress[-1], (model.total_size, model.total_size))

    def test_a_hash_mismatch_leaves_nothing_installed(self):
        model = make_model(b"expected")
        opener = FakeOpener({model.files[0].url: b"tampered"})
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with self.assertRaisesRegex(DownloadError, "integrity check"):
                model_downloads.install(model, target, opener=opener)
            self.assertEqual(list(target.iterdir()), [])

    def test_a_body_larger_than_published_is_refused(self):
        model = make_model(b"small")
        opener = FakeOpener({model.files[0].url: b"small but much longer"})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(DownloadError, "larger than its published size"):
                model_downloads.install(model, Path(directory), opener=opener)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_a_short_body_is_reported_as_incomplete(self):
        model = make_model(b"complete file")
        opener = FakeOpener({model.files[0].url: b"complete"})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(DownloadError, "incomplete"):
                model_downloads.install(model, Path(directory), opener=opener)

    def test_network_errors_become_readable_messages(self):
        model = make_model(b"data")
        opener = FakeOpener({}, error=urllib.error.URLError("no route to host"))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(DownloadError, "no route to host"):
                model_downloads.install(model, Path(directory), opener=opener)

    def test_files_that_already_verify_are_not_downloaded_again(self):
        model = make_model(b"kept", b"fresh")
        opener = FakeOpener({model.files[1].url: b"fresh"})
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "file0.bin").write_bytes(b"kept")
            model_downloads.install(model, target, opener=opener)
        self.assertEqual(opener.requested, [model.files[1].url])

    def test_redirects_to_plain_http_are_refused(self):
        handler = model_downloads._HttpsOnlyRedirects()
        request = urllib.request.Request("https://example.test/file")
        with self.assertRaisesRegex(DownloadError, "non-HTTPS"):
            handler.redirect_request(request, None, 302, "Found", {}, "http://example.test/file")


class CommandLineTests(unittest.TestCase):
    def test_status_lists_every_model_with_its_install_state(self):
        with tempfile.TemporaryDirectory() as directory:
            piper = Path(directory) / "piper"
            kokoro = Path(directory) / "kokoro"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = model_downloads.main(["status", "--piper-dir", str(piper), "--kokoro-dir", str(kokoro)])
        rows = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual({row["id"] for row in rows}, set(model_downloads.CATALOG))
        self.assertTrue(all(row["installed"] is False for row in rows))

    def test_install_failure_is_reported_as_a_json_error_event(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            model_downloads, "install", side_effect=DownloadError("server answered 404")
        ), contextlib.redirect_stdout(output):
            code = model_downloads.main(["install", "en_US-ryan-medium", "--dest", directory])
        event = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(code, 1)
        self.assertEqual(event, {"event": "error", "message": "server answered 404", "model": "en_US-ryan-medium"})

    def test_unknown_models_are_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            model_downloads.main(["install", "../../etc", "--dest", "/tmp"])


if __name__ == "__main__":
    unittest.main()
