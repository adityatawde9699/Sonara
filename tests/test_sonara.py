import io
from contextlib import redirect_stderr
from dataclasses import replace
import re
import shutil
from io import StringIO
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sonara
from document import ExtractionNote, parse_bbox_layout


BBOX_LAYOUT = '''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><doc><page width="612" height="792"><flow>
<block xMin="72" yMin="43" xMax="220" yMax="55"><line xMin="72" yMin="43" xMax="220" yMax="55"><word xMin="72" yMin="43" xMax="110" yMax="55">A</word><word xMin="114" yMin="43" xMax="220" yMax="55">paragraph.</word></line></block>
</flow></page></doc></body></html>'''


class FakeProcess:
    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def wait(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


class ExtractTests(unittest.TestCase):
    def test_missing_pdf_is_reported(self):
        with self.assertRaisesRegex(sonara.SonaraError, "does not exist"):
            sonara.extract_pdf(Path("missing.pdf"))

    @patch("sonara._pdftotext_version", return_value="test")
    @patch("sonara.subprocess.Popen")
    @patch("sonara.shutil.which", return_value="/usr/bin/pdftotext")
    def test_extracts_text_with_source_layout(self, _which, popen, _version):
        popen.return_value = FakeProcess(stdout=BBOX_LAYOUT.encode("utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "book.pdf"
            pdf.write_bytes(b"test pdf")
            document = sonara.extract_pdf_document(pdf)
            self.assertEqual(document.text, "A paragraph.")
            self.assertEqual(document.blocks[0].source.page, 1)
            self.assertEqual(document.blocks[0].source.x_min, 72)
            self.assertEqual(document.extractor_version, "test")
        self.assertIn("-bbox-layout", popen.call_args.args[0])

    @patch("sonara._pdftotext_version", return_value="test")
    @patch("sonara.subprocess.Popen")
    @patch("sonara.shutil.which", return_value="/usr/bin/pdftotext")
    def test_empty_pdf_reports_ocr_limit(self, _which, popen, _version):
        popen.return_value = FakeProcess(stdout=b'<html xmlns="http://www.w3.org/1999/xhtml"><body><doc><page width="612" height="792"/></doc></body></html>')
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "scan.pdf"
            pdf.write_bytes(b"test pdf")
            with self.assertRaisesRegex(sonara.SonaraError, "OCR is not implemented"):
                sonara.extract_pdf(pdf)

    @patch("sonara._pdftotext_version", return_value="test")
    @patch("sonara.subprocess.Popen")
    @patch("sonara.shutil.which", return_value="/usr/bin/pdftotext")
    def test_poppler_failure_reports_stderr(self, _which, popen, _version):
        popen.return_value = FakeProcess(stderr=b"Syntax Error: damaged PDF", returncode=1)
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "damaged.pdf"
            pdf.write_bytes(b"not a PDF")
            with self.assertRaisesRegex(sonara.SonaraError, "damaged PDF"):
                sonara.extract_pdf(pdf)

    @patch("sonara.extract_pdf_document", side_effect=sonara.SonaraError("No selectable text was found"))
    def test_empty_extraction_does_not_create_output(self, _extract):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = type("Args", (), {
                "pdf": root / "empty.pdf",
                "output_dir": root / "output",
                "voice": "en_US-john-medium",
                "data_dir": root / "models",
                "piper": "piper",
                "pdftotext": "pdftotext",
            })()
            with self.assertRaisesRegex(sonara.SonaraError, "No selectable text"):
                sonara.read_document(args)
            self.assertFalse(args.output_dir.exists())

    def test_document_schema_serializes_stable_blocks(self):
        kwargs = dict(source_name="sample.pdf", source_sha256="a" * 64, extractor_version="test")
        first = parse_bbox_layout(BBOX_LAYOUT, **kwargs)
        second = parse_bbox_layout(BBOX_LAYOUT, **kwargs)
        self.assertEqual(first.schema_version, 1)
        self.assertEqual(first.blocks[0].id, second.blocks[0].id)
        self.assertEqual(first.to_dict()["blocks"][0]["source"]["page"], 1)
        self.assertIn('"schema_version": 1', first.to_json())

    def test_extraction_warnings_are_shown_by_cli_path(self):
        document = replace(
            parse_bbox_layout(
                BBOX_LAYOUT,
                source_name="sample.pdf",
                source_sha256="a" * 64,
                extractor_version="test",
            ),
            notes=(ExtractionNote("review", "Please review this page order.", page=1),),
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = type("Args", (), {
                "pdf": root / "sample.pdf",
                "output_dir": root / "output",
                "voice": "voice",
                "data_dir": root,
                "piper": "piper",
                "pdftotext": "pdftotext",
            })()
            stderr = StringIO()
            with patch("sonara.extract_pdf_document", return_value=document), patch(
                "sonara._piper_python_api_available", return_value=True
            ), patch(
                "sonara._synthesize_plan",
                return_value={"schema_version": 1, "document_source_sha256": document.source_sha256, "chunks": []},
            ) as synthesize_plan, redirect_stderr(stderr):
                sonara.read_document(args)
            self.assertIn("sonara: review: Please review this page order. (page 1)", stderr.getvalue())
            synthesize_plan.assert_called_once()

    @patch("sonara.PDF_EXTRACTION_TIMEOUT_SECONDS", 0)
    @patch("sonara._pdftotext_version", return_value="test")
    @patch("sonara.subprocess.Popen")
    @patch("sonara.shutil.which", return_value="/usr/bin/pdftotext")
    def test_extraction_timeout_is_actionable(self, _which, popen, _version):
        process = FakeProcess()
        process.returncode = None
        popen.return_value = process
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "slow.pdf"
            pdf.write_bytes(b"test pdf")
            with self.assertRaisesRegex(sonara.SonaraError, "exceeded 0 seconds"):
                sonara.extract_pdf_document(pdf)
        self.assertEqual(process.returncode, -9)

    @patch("sonara.MAX_BBOX_OUTPUT_BYTES", 8)
    @patch("sonara._pdftotext_version", return_value="test")
    @patch("sonara.subprocess.Popen")
    @patch("sonara.shutil.which", return_value="/usr/bin/pdftotext")
    def test_extraction_output_limit_is_actionable(self, _which, popen, _version):
        popen.return_value = FakeProcess(stdout=b"x" * 9)
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "large-output.pdf"
            pdf.write_bytes(b"test pdf")
            with self.assertRaisesRegex(sonara.SonaraError, "output exceeded the 0 MiB limit"):
                sonara.extract_pdf_document(pdf)

    def test_pdf_size_limit_prevents_external_processing(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "large.pdf"
            with pdf.open("wb") as file:
                file.truncate(sonara.MAX_PDF_BYTES + 1)
            with patch("sonara.subprocess.Popen") as popen:
                with self.assertRaisesRegex(sonara.SonaraError, "100 MiB"):
                    sonara.extract_pdf_document(pdf)
            popen.assert_not_called()


class PlayerTests(unittest.TestCase):
    def test_title_is_escaped_and_player_persists_progress_and_speed(self):
        page = sonara.player_html("<script>bad</script>.pdf")
        self.assertIn("&lt;script&gt;bad&lt;/script&gt;.pdf", page)
        self.assertIn("localStorage.setItem", page)
        self.assertIn("playbackRate", page)
        self.assertIn("No audio chunks are available.", page)
        self.assertIn("blocks saved progress for local files", page)

    def test_chunk_player_has_accessible_controls_recovery_and_document_progress(self):
        manifest = {
            "schema_version": 1,
            "document_source_sha256": "a" * 64,
            "narration_ruleset_version": "rules-1",
            "chunks": [{
                "audio_file": "chunks/doc/run/chunk-000000.wav",
                "duration_seconds": 2.0,
                "pause_after_ms": 300,
            }],
        }
        page = sonara.player_html("Research.pdf", manifest)
        for expected in (
            'aria-label="Seek through document"',
            'id="play"',
            'id="pause"',
            'id="retry"',
            'id="skip"',
            "audio.play()",
            "audio.pause()",
            "localStorage.setItem",
            "sonara-progress-v1:",
            "pause_after_ms",
            "loadedmetadata",
            "beforeunload",
            "Progress could not be saved",
        ):
            self.assertIn(expected, page)
        self.assertIn("chunks/doc/run/chunk-000000.wav", page)

    def test_desktop_player_reports_media_errors_and_url_normalization(self):
        source = (Path(__file__).resolve().parents[1] / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn("Media error ${mediaError.code}", source)
        self.assertIn('error?.name === "NotAllowedError"', source)
        self.assertIn("new URL(audio.currentSrc).pathname", source)
        self.assertIn('audio.addEventListener("playing"', source)
        self.assertIn("session.audioBaseUrl", source)
        self.assertIn("Playback did not start within 5 seconds", source)
        self.assertIn("audio did not load within 12 seconds", source)

    def test_chunk_player_manifest_cannot_close_its_script_element(self):
        manifest = {
            "schema_version": 1,
            "document_source_sha256": "b" * 64,
            "chunks": [{"audio_file": "</script><script>alert(1)</script>", "duration_seconds": 1}],
        }
        page = sonara.player_html("<title>.pdf", manifest)
        self.assertIn("\\u003c/script\\u003e", page)
        self.assertIn("&lt;title&gt;.pdf", page)
        self.assertNotIn("<script>alert(1)</script>", page)

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable for embedded player syntax check")
    def test_generated_player_javascript_parses(self):
        page = sonara.player_html("test.pdf", {
            "schema_version": 1,
            "document_source_sha256": "c" * 64,
            "chunks": [{"audio_file": "chunks/test.wav", "duration_seconds": 1.0}],
        })
        scripts = re.findall(r"<script(?: [^>]*)?>(.*?)</script>", page, flags=re.DOTALL)
        self.assertEqual(len(scripts), 2)
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / "player.js"
            script.write_text(scripts[1], encoding="utf-8")
            result = subprocess.run([shutil.which("node"), "--check", str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stale_chunk_cleanup_only_removes_manifest_owned_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_chunk = root / "chunks" / "old-doc" / "run" / "chunk-000000.wav"
            old_chunk.parent.mkdir(parents=True)
            old_chunk.write_bytes(b"generated")
            unrelated = root / "chunks" / "user-file.wav"
            unrelated.write_bytes(b"keep")
            outside = root.parent / f"{root.name}-outside.wav"
            outside.write_bytes(b"keep outside")
            try:
                sonara._cleanup_old_chunks(
                    root,
                    {"chunks": [
                        {"audio_file": "chunks/old-doc/run/chunk-000000.wav"},
                        {"audio_file": f"../../{outside.name}"},
                    ]},
                    {"chunks": []},
                )
                self.assertFalse(old_chunk.exists())
                self.assertTrue(unrelated.exists())
                self.assertTrue(outside.exists())
            finally:
                outside.unlink(missing_ok=True)

    def test_piper_help_describes_module_and_executable_fallback(self):
        parser = sonara.build_parser()
        read_parser = parser._subparsers._group_actions[0].choices["read"]
        help_text = read_parser.format_help()
        self.assertIn("persistent active-Python worker", help_text)
        self.assertIn("executable", help_text)

    def test_spoken_text_preview_is_bounded_and_does_not_synthesize(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            document = root / "sample.txt"
            document.write_text("e.g. 5 km/h. Published 2026-10-27; see [12, 14].", encoding="utf-8")
            args = sonara.build_parser().parse_args([
                "read", str(document), "--voice", "en_US-ryan-medium", "--data-dir", str(root),
                "--preview", "--expand-dates", "--expand-citations",
            ])
            preview = sonara.preview_document(args)

        self.assertEqual(preview["sourceName"], "sample.txt")
        self.assertEqual(preview["totalUnits"], 2)
        self.assertIn("five kilometers per hour", preview["units"][0]["spokenText"])
        self.assertIn("October twenty-seventh", preview["units"][1]["spokenText"])
        self.assertEqual(preview["units"][1]["changes"][0]["matchedSourceText"], "2026-10-27")

    def test_large_documents_are_rejected_until_chunking_exists(self):
        with self.assertRaisesRegex(sonara.SonaraError, "100 KB"):
            sonara.synthesize("x" * 100_001, "voice", Path("models"), Path("out.wav"), "piper")

    def test_executable_override_uses_temporary_input_file_not_text_argv(self):
        text = "Sensitive document text stays out of process arguments."
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_dir = root / "voices"
            data_dir.mkdir()
            output = root / "speech.wav"
            captured = {}

            def run(command, **kwargs):
                captured["command"] = command
                captured["input_text"] = Path(command[command.index("--input-file") + 1]).read_text(encoding="utf-8")
                output.write_bytes(b"placeholder wav")
                return SimpleNamespace(returncode=0, stderr="")

            with patch("sonara.shutil.which", return_value="/usr/bin/custom-piper"), patch("sonara.subprocess.run", side_effect=run):
                sonara.synthesize(text, "voice", data_dir, output, "/usr/bin/custom-piper")
            self.assertEqual(captured["input_text"], text)
            self.assertNotIn(text, captured["command"])
            self.assertFalse(Path(captured["command"][captured["command"].index("--input-file") + 1]).exists())


if __name__ == "__main__":
    unittest.main()
