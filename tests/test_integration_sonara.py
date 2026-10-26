"""Opt-in real Poppler/Piper integration test; no network or audio device needed."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import wave
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import sonara
from narration import build_narration_plan
from tts_engine import AudioFormat, PiperEngine, SynthesisStream, TtsError
from fixtures.pdf_corpus import CORPUS, generate_corpus, write_malformed_pdf
from fixtures.pdf_fixture import EXPECTED_TEXT, make_corpus_pdf, make_pdf


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "piper"
VOICE = "en_US-john-medium"


@unittest.skipUnless(
    os.environ.get("SONARA_RUN_INTEGRATION") == "1",
    "opt-in real Poppler/Piper test; set SONARA_RUN_INTEGRATION=1",
)
class SonaraIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = []
        if shutil.which("pdftotext") is None:
            missing.append("Poppler pdftotext (install poppler-utils)")
        try:
            piper_available = importlib.util.find_spec("piper") is not None
        except ModuleNotFoundError:
            piper_available = False
        if not piper_available:
            missing.append("piper-tts in the active Python environment")
        model = MODEL_DIR / f"{VOICE}.onnx"
        config = MODEL_DIR / f"{VOICE}.onnx.json"
        if not model.is_file() or model.stat().st_size == 0:
            missing.append(f"local voice model: {model}")
        if not config.is_file() or config.stat().st_size == 0:
            missing.append(f"local voice configuration: {config}")
        if missing:
            raise unittest.SkipTest("missing integration prerequisite(s): " + "; ".join(missing))

        configuration = json.loads(config.read_text(encoding="utf-8"))
        cls.expected_sample_rate = configuration["audio"]["sample_rate"]

    def test_real_pdf_extraction_piper_wav_and_player(self):
        with tempfile.TemporaryDirectory(prefix="sonara-integration-") as temp_dir:
            temp = Path(temp_dir)
            pdf = make_pdf(temp / "known-text.pdf")

            extracted = sonara.extract_pdf(pdf)
            self.assertEqual(extracted, EXPECTED_TEXT)

            malformed_pdf = temp / "malformed.pdf"
            malformed_pdf.write_bytes(b"not a PDF document")
            with self.assertRaisesRegex(sonara.SonaraError, "PDF extraction failed"):
                sonara.extract_pdf(malformed_pdf)

            output_dir = temp / "generated-reader"
            args = SimpleNamespace(
                pdf=pdf,
                output_dir=output_dir,
                voice=VOICE,
                data_dir=MODEL_DIR,
                piper="piper",
                pdftotext="pdftotext",
            )
            player_path = sonara.read_document(args)
            wav_path = output_dir / "speech.wav"

            self.assertEqual(player_path, output_dir / "index.html")
            self.assertTrue(wav_path.is_file())
            self.assertGreater(wav_path.stat().st_size, 44)
            with wave.open(str(wav_path), "rb") as audio:
                self.assertEqual(audio.getcomptype(), "NONE")
                self.assertEqual(audio.getnchannels(), 1)
                self.assertEqual(audio.getsampwidth(), 2)
                self.assertEqual(audio.getframerate(), self.expected_sample_rate)
                self.assertGreater(audio.getnframes(), 0)
                self.assertGreater(audio.getnframes() / audio.getframerate(), 0)

            player = player_path.read_text(encoding="utf-8")
            self.assertIn("This audio chunk could not be loaded", player)
            self.assertIn("localStorage.setItem", player)
            chunk_manifest = json.loads((output_dir / "audio_chunks.json").read_text(encoding="utf-8"))
            self.assertEqual(chunk_manifest["engine"], "Piper")
            self.assertEqual(len(chunk_manifest["chunks"]), len(build_narration_plan(sonara.extract_pdf_document(pdf)).units))
            self.assertTrue(all(chunk["duration_seconds"] > 0 for chunk in chunk_manifest["chunks"]))
            for chunk in chunk_manifest["chunks"]:
                chunk_path = output_dir / chunk["audio_file"]
                self.assertTrue(chunk_path.is_file())
                with wave.open(str(chunk_path), "rb") as chunk_audio:
                    self.assertEqual(chunk_audio.getframerate(), self.expected_sample_rate)
                    self.assertEqual(chunk_audio.getnchannels(), 1)
                    self.assertEqual(chunk_audio.getsampwidth(), 2)
                    self.assertGreater(chunk_audio.getnframes(), 0)
                self.assertIn(chunk["audio_file"], player)


@unittest.skipUnless(
    os.environ.get("SONARA_RUN_INTEGRATION") == "1",
    "opt-in real Piper Python API test; set SONARA_RUN_INTEGRATION=1",
)
class PiperApiIntegrationTests(unittest.TestCase):
    def test_persistent_piper_worker_emits_mapped_valid_wav_chunks(self):
        model = MODEL_DIR / f"{VOICE}.onnx"
        config = MODEL_DIR / f"{VOICE}.onnx.json"
        missing = [str(path) for path in (model, config) if not path.is_file() or path.stat().st_size == 0]
        try:
            piper_available = importlib.util.find_spec("piper") is not None
        except ModuleNotFoundError:
            piper_available = False
        if not piper_available:
            missing.append("piper-tts in the active Python environment")
        if missing:
            self.skipTest("missing integration prerequisite(s): " + "; ".join(missing))
        if shutil.which("pdftotext") is None:
            self.skipTest("missing integration prerequisite: Poppler pdftotext")

        with tempfile.TemporaryDirectory(prefix="sonara-piper-api-") as temp_dir:
            pdf = make_pdf(Path(temp_dir) / "known-text.pdf")
            document = sonara.extract_pdf_document(pdf)
            plan = build_narration_plan(document)
            engine = PiperEngine(model, config)
            self.assertEqual(engine.capabilities.voice, VOICE)
            self.assertEqual(engine.capabilities.language, "en_US")
            self.assertEqual(engine.capabilities.supported_controls, ("speed", "variation"))
            self.assertIn("emotion", engine.capabilities.unsupported_controls)
            self.assertTrue(engine.capabilities.supports_inflight_cancellation)
            sample_rate = json.loads(config.read_text(encoding="utf-8"))["audio"]["sample_rate"]
            blocks_by_id = {block.id: block for block in document.blocks}
            try:
                observed = []
                with SynthesisStream(engine, plan, prefetch_chunks=1) as chunks:
                    for chunk in chunks:
                        self.assertEqual(chunk.audio_format, AudioFormat(sample_rate, 1, 2))
                        self.assertEqual(
                            blocks_by_id[chunk.source_block_id].text[chunk.source_start:chunk.source_end],
                            chunk.source_text,
                        )
                        with wave.open(str(chunk.wav_path), "rb") as audio:
                            self.assertEqual(audio.getcomptype(), "NONE")
                            self.assertEqual(audio.getnchannels(), 1)
                            self.assertEqual(audio.getsampwidth(), 2)
                            self.assertEqual(audio.getframerate(), sample_rate)
                            self.assertGreater(audio.getnframes(), 0)
                        observed.append((chunk.unit_id, chunk.source_text, chunk.duration_seconds))
                self.assertEqual([item[0] for item in observed], [unit.id for unit in plan.units])
                self.assertEqual([item[1] for item in observed], [unit.source_text for unit in plan.units])
                self.assertTrue(all(item[2] > 0 for item in observed))
                self.assertEqual(engine.model_load_count, 1)
                self.assertTrue(engine._worker.is_alive)
            finally:
                engine.close()
            self.assertIsNone(engine._worker)

    def test_cancel_terminates_active_worker_process(self):
        model = MODEL_DIR / f"{VOICE}.onnx"
        config = MODEL_DIR / f"{VOICE}.onnx.json"
        if not model.is_file() or not config.is_file() or importlib.util.find_spec("piper") is None:
            self.skipTest("missing local Piper model, configuration, or piper-tts runtime")
        if shutil.which("pdftotext") is None:
            self.skipTest("missing integration prerequisite: Poppler pdftotext")
        with tempfile.TemporaryDirectory(prefix="sonara-piper-cancel-") as temp_dir:
            pdf = make_pdf(Path(temp_dir) / "known-text.pdf")
            source = sonara.extract_pdf_document(pdf)
            first = replace(source.blocks[0], text="A short opening sentence. " + ("longword " * 5000) + "end.")
            document = replace(source, blocks=(first,))
            plan = build_narration_plan(document)
            engine = PiperEngine(model, config)
            stream = SynthesisStream(engine, plan, prefetch_chunks=1)
            try:
                first_chunk = next(stream)
                self.assertEqual(first_chunk.unit_id, plan.units[0].id)
                worker = engine._worker
                self.assertIsNotNone(worker)
                worker_pid = worker.process.pid
                stream.cancel()
                self.assertIsNotNone(worker.process.poll())
                self.assertEqual(engine.model_load_count, 1)
                self.assertGreater(worker_pid, 0)
            finally:
                stream.close()
                engine.close()

    def test_corrupt_model_is_reported_without_hanging_or_leaking_worker(self):
        if importlib.util.find_spec("piper") is None:
            self.skipTest("missing integration prerequisite: piper-tts in the active Python environment")
        with tempfile.TemporaryDirectory(prefix="sonara-corrupt-model-") as temp_dir:
            temp = Path(temp_dir)
            bad_model = temp / "corrupt.onnx"
            bad_model.write_bytes(b"not an ONNX model")
            bad_config = temp / "corrupt.onnx.json"
            bad_config.write_bytes((MODEL_DIR / f"{VOICE}.onnx.json").read_bytes())
            engine = PiperEngine(bad_model, bad_config, load_timeout_seconds=10)
            stream = SynthesisStream(engine, build_narration_plan(
                sonara.extract_pdf_document(make_pdf(temp / "known-text.pdf"))
            ))
            try:
                with self.assertRaisesRegex(TtsError, "Could not load Piper voice"):
                    next(stream)
                self.assertIsNone(engine._worker)
            finally:
                stream.close()
                engine.close()

    def test_symbols_and_punctuation_without_phonemes_emit_valid_audio(self):
        model = MODEL_DIR / f"{VOICE}.onnx"
        config = MODEL_DIR / f"{VOICE}.onnx.json"
        if not model.is_file() or not config.is_file() or importlib.util.find_spec("piper") is None:
            self.skipTest("missing local Piper model, configuration, or piper-tts runtime")
        engine = PiperEngine(model, config)
        try:
            with tempfile.TemporaryDirectory(prefix="sonara-symbol-chunk-") as temp:
                out = Path(temp) / "ellipsis.wav"
                cancel = threading.Event()
                fmt = engine.synthesize_to_wav("...", 1.0, out, cancel, 30.0)
                self.assertTrue(out.is_file())
                self.assertGreater(out.stat().st_size, 44)
                with wave.open(str(out), "rb") as audio:
                    self.assertEqual(audio.getframerate(), fmt.sample_rate)
                    self.assertEqual(audio.getnchannels(), 1)
                    self.assertEqual(audio.getsampwidth(), 2)
                    self.assertGreater(audio.getnframes(), 0)
        finally:
            engine.close()


@unittest.skipUnless(
    os.environ.get("SONARA_RUN_INTEGRATION") == "1",
    "opt-in real Poppler PDF corpus test; set SONARA_RUN_INTEGRATION=1",
)
class PdfCorpusIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("pdftotext") is None:
            raise unittest.SkipTest("missing integration prerequisite: Poppler pdftotext (install poppler-utils)")

    def test_generated_corpus_preserves_text_order_and_source_locations(self):
        with tempfile.TemporaryDirectory(prefix="sonara-pdf-corpus-") as temp_dir:
            root = Path(temp_dir)
            for name, path in generate_corpus(root).items():
                with self.subTest(fixture=name):
                    expected = CORPUS[name]
                    document = sonara.extract_pdf_document(path)
                    self.assertEqual(document.text, expected["expected_text"])
                    self.assertEqual(document.page_count, expected["page_count"])
                    self.assertEqual([block.order for block in document.blocks], list(range(len(document.blocks))))
                    self.assertEqual(len({block.id for block in document.blocks}), len(document.blocks))
                    self.assertTrue(all(block.source.page <= document.page_count for block in document.blocks))
                    self.assertTrue(all(block.source.page_width > 0 and block.source.page_height > 0 for block in document.blocks))
                    self.assertEqual(
                        document.source_sha256,
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                    note_codes = {note.code for note in document.notes}
                    self.assertTrue(expected.get("notes", set()).issubset(note_codes), (name, note_codes))
                    kinds = {block.kind for block in document.blocks}
                    self.assertTrue(expected.get("kinds", set()).issubset(kinds), (name, kinds))
                    if name == "structure":
                        self.assertIn("footnote", kinds)
                        self.assertEqual(
                            next(block for block in document.blocks if block.kind == "heading").kind_source,
                            "relative_line_height",
                        )
                    if name == "mixed_text_and_image":
                        self.assertEqual(document.blocks[0].source.page, 1)
                        warning = next(note for note in document.notes if note.code == "page_without_selectable_text")
                        self.assertEqual(warning.page, 2)
                    if name == "repeated_passage":
                        self.assertEqual(len(document.blocks), 2)
                        self.assertEqual(Counter(block.text for block in document.blocks)["Repeated source paragraph."], 2)

                    repeated = sonara.extract_pdf_document(path)
                    self.assertEqual([block.id for block in document.blocks], [block.id for block in repeated.blocks])
                    self.assertEqual(json.loads(document.to_json())["schema_version"], 1)

                    baseline = subprocess.run(
                        [shutil.which("pdftotext"), "-layout", "-enc", "UTF-8", str(path), "-"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        check=True,
                    ).stdout
                    self.assertEqual(document.text.split(), baseline.split(), f"bbox/layout token mismatch: {name}")

            columns = sonara.extract_pdf_document(root / "two_columns.pdf")
            self.assertEqual(
                [note.code for note in columns.notes].count("side_by_side_reading_order_uncertain"), 1
            )

            scanned_only = make_corpus_pdf(root / "scanned-only.pdf", [[]], image_pages={1})
            with self.assertRaisesRegex(sonara.SonaraError, "scanned PDF; OCR is not implemented"):
                sonara.extract_pdf_document(scanned_only)

            malformed = write_malformed_pdf(root / "malformed.pdf")
            with self.assertRaisesRegex(sonara.SonaraError, "PDF extraction failed"):
                sonara.extract_pdf_document(malformed)


if __name__ == "__main__":
    unittest.main()
