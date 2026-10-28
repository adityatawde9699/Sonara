import tempfile
import threading
import os
import unittest
import wave
from pathlib import Path

from document import Document, DocumentBlock, SourceBox
from narration import build_narration_plan
from tts_engine import (
    AudioFormat,
    EngineCapabilities,
    SynthesisCancelled,
    SynthesisSettings,
    SynthesisStream,
    PiperEngine,
    TtsError,
    prune_audio_cache,
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


if __name__ == "__main__":
    unittest.main()
