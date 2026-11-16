import json
import tempfile
import threading
import os
import unittest
import wave
from pathlib import Path

import numpy as np
from unittest.mock import patch

from audio_processing import speech_level_dbfs
from document import Document, DocumentBlock, SourceBox
from narration import build_narration_plan
import tts_engine
from tts_engine import (
    AudioFormat,
    EngineCapabilities,
    SynthesisCancelled,
    SynthesisSettings,
    SynthesisStream,
    PiperEngine,
    TtsError,
    prune_audio_cache,
    validate_voice_name,
)


FORMAT = AudioFormat(22050, 1, 2)


def make_plan(text="First sentence. Second sentence. Third sentence.", *, separate_paragraphs=False):
    paragraphs = text.split("\n\n") if separate_paragraphs else [text]
    document = Document(
        schema_version=1,
        source_name="tts-test.pdf",
        source_sha256="f" * 64,
        extractor="unit-test",
        extractor_version="1",
        page_count=1,
        blocks=tuple(DocumentBlock(
            id=f"block-{index}",
            kind="paragraph",
            kind_source="unit-test",
            order=index,
            text=paragraph,
            source=SourceBox(1, 612, 792, 72, 72 + index * 20, 540, 90 + index * 20),
        ) for index, paragraph in enumerate(paragraphs)),
        notes=(),
    )
    return build_narration_plan(document)


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.cancelled = threading.Event()
        self.blocked_started = threading.Event()
        self.block_on = None
        self.fail_on = None

    @property
    def capabilities(self):
        return EngineCapabilities(
            engine="Fake",
            engine_version="1",
            voice="fake-voice",
            language="en",
            model_available=True,
            audio_format=FORMAT,
            minimum_speed=0.5,
            maximum_speed=2.0,
            supported_controls=("speed",),
            unsupported_controls=("emotion",),
            supports_inflight_cancellation=True,
            device="CPU",
        )

    @property
    def cache_identity(self):
        return "fake-model-v1"

    def begin_stream(self):
        return object()

    def end_stream(self, token):
        return None

    def synthesize_to_wav(self, text, speed, output_path, cancel_event, timeout_seconds):
        self.calls.append((text, speed))
        if self.fail_on == text:
            raise TtsError("injected synthesis failure")
        if self.block_on == text:
            self.blocked_started.set()
            while not cancel_event.wait(0.01):
                pass
            raise SynthesisCancelled("cancelled fake inference")
        with wave.open(str(output_path), "wb") as output:
            output.setnchannels(FORMAT.channels)
            output.setsampwidth(FORMAT.sample_width_bytes)
            output.setframerate(FORMAT.sample_rate)
            output.writeframes(b"\0\0" * 2205)
        return FORMAT

    def cancel_active(self):
        self.cancelled.set()


def read_all(stream):
    with stream:
        return list(stream)


class SynthesisStreamTests(unittest.TestCase):
    def test_invalid_piper_variation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "variation must be"):
            PiperEngine(Path("missing.onnx"), variation="dramatic")

    def test_missing_model_and_invalid_configuration_are_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(TtsError, "model is missing"):
                PiperEngine(root / "missing.onnx")
            model = root / "model.onnx"
            model.write_bytes(b"model placeholder")
            config = root / "model.onnx.json"
            config.write_text("not json", encoding="utf-8")
            with self.assertRaisesRegex(TtsError, "Could not read Piper model configuration"):
                PiperEngine(model, config)

    def test_cache_pruning_is_lru_and_preserves_protected_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = []
            for index in range(3):
                path = root / (f"{index + 1:064x}.wav")
                with wave.open(str(path), "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(22050)
                    audio.writeframes(b"\0\0" * 100)
                os.utime(path, (index + 1, index + 1))
                files.append(path)
            total_size = sum(path.stat().st_size for path in files)
            removed, remaining = prune_audio_cache(root, total_size - files[0].stat().st_size, protected={files[0]})
            self.assertEqual(removed, 1)
            self.assertLessEqual(remaining, total_size - files[0].stat().st_size)
            self.assertTrue(files[0].exists())
            self.assertFalse(files[1].exists())
            self.assertTrue(files[2].exists())

    def test_chunks_keep_unit_mapping_and_audio_format(self):
        plan = make_plan()
        engine = FakeEngine()
        chunks = read_all(SynthesisStream(engine, plan, prefetch_chunks=1))
        self.assertEqual([chunk.unit_id for chunk in chunks], [unit.id for unit in plan.units])
        self.assertEqual([chunk.source_text for chunk in chunks], [unit.source_text for unit in plan.units])
        self.assertTrue(all(chunk.audio_format == FORMAT for chunk in chunks))
        self.assertTrue(all(chunk.duration_seconds == 0.1 for chunk in chunks))
        self.assertTrue(all(not chunk.wav_path.exists() for chunk in chunks))

    def test_first_chunk_is_available_while_later_unit_is_still_synthesizing(self):
        plan = make_plan("First sentence.\n\nSecond sentence.\n\nThird sentence.", separate_paragraphs=True)
        engine = FakeEngine()
        engine.block_on = plan.units[1].spoken_text
        stream = SynthesisStream(engine, plan, prefetch_chunks=1)
        first = next(stream)
        self.assertEqual(first.unit_id, plan.units[0].id)
        self.assertTrue(engine.blocked_started.wait(timeout=1))
        self.assertTrue(engine.cancelled.is_set() is False)
        self.assertEqual(len(engine.calls), 2)
        stream.cancel()
        self.assertTrue(engine.cancelled.is_set())

    def test_engine_errors_reach_consumer(self):
        plan = make_plan()
        engine = FakeEngine()
        engine.fail_on = plan.units[0].spoken_text
        stream = SynthesisStream(engine, plan)
        with self.assertRaisesRegex(TtsError, "injected synthesis failure"):
            next(stream)

    def test_cache_hits_and_speed_changes_invalidate_entries(self):
        plan = make_plan("One sentence.")
        engine = FakeEngine()
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            first = read_all(SynthesisStream(engine, plan, cache_dir=cache))
            self.assertFalse(first[0].cached)
            first_call_count = len(engine.calls)
            second = read_all(SynthesisStream(engine, plan, cache_dir=cache))
            self.assertTrue(second[0].cached)
            self.assertEqual(len(engine.calls), first_call_count)
            changed_speed = read_all(SynthesisStream(
                engine,
                plan,
                cache_dir=cache,
                settings=SynthesisSettings(speed=1.2),
            ))
            self.assertFalse(changed_speed[0].cached)
            self.assertEqual(len(engine.calls), first_call_count + 1)
            self.assertEqual(engine.calls[-1][1], 1.2)
            self.assertGreaterEqual(len(list(cache.glob("*.wav"))), 2)

    def test_cache_is_pruned_at_start_and_end_not_after_every_chunk(self):
        text = "\n\n".join(f"Paragraph number {index}." for index in range(12))
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(tts_engine, "prune_audio_cache", wraps=tts_engine.prune_audio_cache) as prune:
            chunks = read_all(SynthesisStream(FakeEngine(), make_plan(text, separate_paragraphs=True),
                                              cache_dir=Path(temp)))
        self.assertEqual(len(chunks), 12)
        self.assertEqual(prune.call_count, 2)

    def test_corrupt_cache_is_removed_and_regenerated(self):
        plan = make_plan("One sentence.")
        engine = FakeEngine()
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            stream = SynthesisStream(engine, plan, cache_dir=cache)
            first = read_all(stream)
            first[0].wav_path.write_bytes(b"bad")
            second = read_all(SynthesisStream(engine, plan, cache_dir=cache))
            self.assertFalse(second[0].cached)
            self.assertEqual(len(engine.calls), 2)

    def test_bad_speed_and_queue_configuration_fail_early(self):
        with self.assertRaises(ValueError):
            SynthesisSettings(speed=2.1)
        with self.assertRaises(ValueError):
            SynthesisStream(FakeEngine(), make_plan(), prefetch_chunks=0)


class ToneEngine(FakeEngine):
    """Writes speech-like tone with 300 ms of built-in silence on each side."""

    def __init__(self, amplitude):
        super().__init__()
        self.amplitude = amplitude

    def synthesize_to_wav(self, text, speed, output_path, cancel_event, timeout_seconds):
        self.calls.append((text, speed))
        rate = FORMAT.sample_rate
        tone = self.amplitude * np.sin(2 * np.pi * 180 * np.arange(rate // 2) / rate)
        samples = np.concatenate([np.zeros(rate * 3 // 10), tone, np.zeros(rate * 3 // 10)])
        with wave.open(str(output_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes((samples * 32767).astype("<i2").tobytes())
        return FORMAT


class AudioFinishingTests(unittest.TestCase):
    def _levels(self, engine, cache_dir=None):
        chunks = read_all(SynthesisStream(engine, make_plan("Only sentence."), cache_dir=cache_dir))
        with wave.open(str(chunks[0].wav_path), "rb") as source:
            samples = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768
        return chunks[0], speech_level_dbfs(samples, FORMAT.sample_rate)

    def test_chunks_are_trimmed_and_level_matched_across_voices(self):
        with tempfile.TemporaryDirectory() as temp:
            loud, loud_level = self._levels(ToneEngine(0.5), Path(temp) / "a")
            soft, soft_level = self._levels(ToneEngine(0.08), Path(temp) / "b")
            # 0.5 s of tone plus short pads, not the 1.1 s the engine wrote.
            self.assertLess(loud.duration_seconds, 0.6)
            self.assertAlmostEqual(loud.duration_seconds, soft.duration_seconds, delta=0.02)
            self.assertAlmostEqual(loud_level, soft_level, delta=0.3)
            # Cached chunks are already finished.
            cached, cached_level = self._levels(ToneEngine(0.5), Path(temp) / "a")
            self.assertTrue(cached.cached)
            self.assertAlmostEqual(cached_level, loud_level, delta=0.01)


class PiperProfileTests(unittest.TestCase):
    def _engine(self, root, voice, variation):
        model = root / f"{voice}.onnx"
        model.write_bytes(b"model placeholder")
        (root / f"{voice}.onnx.json").write_text(json.dumps({"audio": {"sample_rate": 22050}}), encoding="utf-8")
        return PiperEngine(model, variation=variation)

    def test_measured_voice_profile_reaches_the_worker_request(self):
        sent = {}

        class FakeClient:
            def synthesize(self, request_id, text, speed, variation, output_path, **kwargs):
                sent.update(kwargs, variation=variation)
                with wave.open(str(output_path), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(22050)
                    output.writeframes(b"\1\0" * 100)
                return {"sample_rate": 22050, "channels": 1, "sample_width_bytes": 2}

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(tts_engine.PINNED_PIPER_VOICES, clear=True):
                engine = self._engine(root, "en_US-john-medium", "more")
                default = self._engine(root, "en_US-ryan-medium", "voice_default")
            engine._get_worker = lambda cancel_event: FakeClient()
            engine.synthesize_to_wav("Hello.", 1.0, root / "out.wav", threading.Event(), 5)
            self.assertEqual(sent["noise_scales"], (0.75, 0.85))
            self.assertEqual(sent["sentence_pause_ms"], 230)
            # Changing a profile value must not reuse audio made with the old one.
            self.assertIn("noise=(0.75, 0.85)", engine.cache_identity)
            self.assertIsNone(default.noise_scales)
            self.assertIn("sentence_pause_ms=200", default.cache_identity)


class VoiceIntegrityTests(unittest.TestCase):
    def _write_voice(self, root, voice, model=b"model placeholder"):
        model_path = root / f"{voice}.onnx"
        model_path.write_bytes(model)
        (root / f"{voice}.onnx.json").write_text(json.dumps({"audio": {"sample_rate": 22050}}), encoding="utf-8")
        return model_path

    def test_a_bundled_voice_id_with_different_files_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            model = self._write_voice(Path(temp), "en_US-ryan-medium")
            with self.assertRaisesRegex(TtsError, "does not match its published checksum"):
                PiperEngine(model)

    def test_user_installed_voices_are_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = PiperEngine(self._write_voice(Path(temp), "en_GB-custom-medium"))
            self.assertEqual(engine.capabilities.voice, "en_GB-custom-medium")

    def test_installed_bundled_voices_match_their_pins(self):
        models = Path(__file__).resolve().parents[1] / "models" / "piper"
        installed = [voice for voice in tts_engine.PINNED_PIPER_VOICES if (models / f"{voice}.onnx").is_file()]
        if not installed:
            self.skipTest("no bundled Piper voices are installed")
        for voice in installed:
            with self.subTest(voice=voice):
                PiperEngine(models / f"{voice}.onnx")

    def test_voice_names_cannot_leave_the_model_directory(self):
        for good in ("en_US-ryan-medium", "af_sarah"):
            self.assertEqual(validate_voice_name(good), good)
        for bad in ("../secret", "en_US/../../x", "voice.onnx", "", "-flag", "a" * 200, "C:\\x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_voice_name(bad)


class KokoroLanguageTests(unittest.TestCase):
    def test_voice_prefix_selects_phonemizer_and_narration_language(self):
        self.assertEqual(tts_engine.kokoro_language("af_sarah"), ("en-us", "en_US"))
        self.assertEqual(tts_engine.kokoro_language("bm_george"), ("en-gb", "en_GB"))
        self.assertEqual(tts_engine.kokoro_language("ff_siwis"), ("fr-fr", "fr_FR"))
        self.assertEqual(tts_engine.kokoro_language("zf_xiaobei"), ("cmn", "zh_CN"))

    def test_japanese_and_malformed_voices_are_refused(self):
        with self.assertRaisesRegex(tts_engine.TtsError, "misaki"):
            tts_engine.kokoro_language("jf_alpha")
        for voice in ("../af_sarah", "af-sarah", "xf_test", "AF_SARAH"):
            with self.assertRaises(tts_engine.TtsError):
                tts_engine.kokoro_language(voice)


if __name__ == "__main__":
    unittest.main()
