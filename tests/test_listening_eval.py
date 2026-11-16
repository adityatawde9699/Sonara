import csv
import io
import json
import math
import struct
import tempfile
import threading
import unittest
import wave
from contextlib import redirect_stdout
from pathlib import Path

from benchmark import BENCHMARK_PASSAGES
from listening_eval import (
    BLIND_FIELDS,
    Condition,
    analyze_ratings,
    create_listening_pack,
    load_ratings,
    loudness_match_wav,
    main,
)
from tts_engine import AudioFormat, EngineCapabilities


class ToneEngine:
    """Writes a short tone per unit; enough for pack creation without a model."""

    def __init__(self, sample_rate, amplitude):
        self.format = AudioFormat(sample_rate, 1, 2)
        self.amplitude = amplitude
        self.closed = False

    @property
    def capabilities(self):
        return EngineCapabilities(
            engine="Tone", engine_version="1", voice="tone", language="en", model_available=True,
            audio_format=self.format, minimum_speed=0.5, maximum_speed=2.0, supported_controls=("speed",),
            unsupported_controls=(), supports_inflight_cancellation=False, device="CPU",
        )

    @property
    def cache_identity(self):
        return f"tone-{self.format.sample_rate}-{self.amplitude}"

    def begin_stream(self):
        return object()

    def end_stream(self, token):
        return None

    def cancel_active(self):
        return None

    def close(self):
        self.closed = True

    def synthesize_to_wav(self, text, speed, output_path, cancel_event: threading.Event, timeout_seconds):
        frames = [round(self.amplitude * math.sin(index * 0.05)) for index in range(self.format.sample_rate // 10)]
        with wave.open(str(output_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(self.format.sample_rate)
            output.writeframes(struct.pack(f"<{len(frames)}h", *frames))
        return self.format


def read_rows(path):
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_sheet(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BLIND_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


class ListeningEvaluationTests(unittest.TestCase):
    def test_corpus_covers_reports_terms_measurements_questions_dialogue_and_citations(self):
        names = {name for name, _ in BENCHMARK_PASSAGES}
        self.assertTrue({
            "Research report",
            "Technical prose",
            "Numbers and units",
            "Question and emphasis",
            "Dialogue and quotes",
            "Citation and date",
        }.issubset(names))

    def test_rms_level_matching_respects_peak_ceiling(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.wav"
            samples = [round(1000 * math.sin(index * 0.1)) for index in range(2000)]
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(22050)
                output.writeframes(struct.pack(f"<{len(samples)}h", *samples))

            loudness_match_wav(path)

            with wave.open(str(path), "rb") as matched:
                result = struct.unpack(f"<{matched.getnframes()}h", matched.readframes(matched.getnframes()))
            rms_dbfs = 20 * math.log10(math.sqrt(sum(value * value for value in result) / len(result)) / 32768)
            peak_dbfs = 20 * math.log10(max(abs(value) for value in result) / 32767)
            self.assertAlmostEqual(rms_dbfs, -20.0, delta=0.1)
            self.assertLessEqual(peak_dbfs, -1.0)


class ListeningPackTests(unittest.TestCase):
    def test_pack_blinds_engines_with_different_sample_rates(self):
        engines = []

        def opener(rate, amplitude):
            def open_engine():
                engine = ToneEngine(rate, amplitude)
                engines.append(engine)
                return engine
            return open_engine

        conditions = [
            Condition("piper:voice_default", "piper", "en_US-ryan-medium", "voice_default", "en_US", opener(22050, 900)),
            Condition("kokoro:af_sarah", "kokoro", "af_sarah", "voice_default", "en_US", opener(24000, 4000)),
        ]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            metadata = create_listening_pack("en_US-ryan-medium", output, output, conditions=conditions, seed=7)
            blind = read_rows((output / "participant-pack/blind-ratings.csv"))
            key = read_rows((output / "facilitator-only/facilitator-key.csv"))
            clip_names = {path.stem for path in (output / "participant-pack/clips").glob("*.wav")}
            rates = set()
            for path in (output / "participant-pack/clips").glob("*.wav"):
                with wave.open(str(path), "rb") as clip:
                    rates.add(clip.getframerate())
        self.assertTrue(all(engine.closed for engine in engines))
        self.assertEqual(metadata["rating_count"], 2 * len(BENCHMARK_PASSAGES))
        self.assertEqual({row["clip_id"] for row in blind}, clip_names)
        self.assertEqual({row["condition"] for row in key}, {"piper:voice_default", "kokoro:af_sarah"})
        # The participant sheet never names the engine or condition.
        self.assertEqual(list(blind[0]), BLIND_FIELDS)
        self.assertEqual(rates, {22050, 24000})

    def test_pack_needs_two_distinct_conditions(self):
        condition = Condition("piper:less", "piper", "v", "less", "en_US", lambda: ToneEngine(22050, 900))
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(ValueError, "two distinct"):
            create_listening_pack("v", Path(temp), Path(temp), conditions=[condition, condition])


class RatingAnalysisTests(unittest.TestCase):
    GROUPS = ("prompt-01", "prompt-02", "prompt-03")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.key_path = self.root / "facilitator-key.csv"
        rows = []
        for group in self.GROUPS:
            for condition in ("piper:voice_default", "kokoro:af_sarah"):
                rows.append({"clip_id": f"{group}-{condition.split(':')[0]}", "comparison_group": group, "condition": condition})
        with self.key_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["clip_id", "comparison_group", "condition"])
            writer.writeheader()
            writer.writerows(rows)

    def tearDown(self):
        self.temp.cleanup()

    def sheet(self, name, piper_score, kokoro_score, prefer="kokoro"):
        rows = []
        for group in self.GROUPS:
            for engine, score in (("piper", piper_score), ("kokoro", kokoro_score)):
                rows.append({
                    "comparison_group": group, "clip_id": f"{group}-{engine}",
                    "naturalness_1_to_5": str(score), "intelligibility_1_to_5": "4",
                    "preferred_in_group": "x" if engine == prefer else "", "notes": "",
                })
        path = self.root / f"{name}.csv"
        write_sheet(path, rows)
        return path

    def test_paired_difference_and_preference_favour_the_better_condition(self):
        sheets = [self.sheet(f"listener-{index:02d}", 2 + index % 2, 4 + index % 2) for index in range(8)]
        ratings, warnings = load_ratings(self.key_path, sheets)
        report = analyze_ratings(ratings, samples=500)
        self.assertEqual(warnings, [])
        self.assertEqual(report["raters"], 8)
        kokoro = next(entry for entry in report["conditions"] if entry["condition"] == "kokoro:af_sarah")
        paired = kokoro["naturalness"]["paired_difference_vs_baseline"]
        self.assertEqual(paired["mean"], 2.0)
        self.assertEqual(paired["ci95"], [2.0, 2.0])
        self.assertGreater(kokoro["naturalness"]["ci95"][1], kokoro["naturalness"]["ci95"][0])
        self.assertEqual(kokoro["preference_share"]["share"], 1.0)
        self.assertEqual(kokoro["preference_share"]["chance"], 0.5)
        self.assertIn("Only 8 listeners", " ".join(report["caveats"]))

    def test_preference_share_stays_a_proportion_under_resampling(self):
        sheets = [self.sheet(f"l{index}", 3, 3, prefer="kokoro" if index % 3 else "piper") for index in range(5)]
        ratings, _ = load_ratings(self.key_path, sheets)
        report = analyze_ratings(ratings, samples=400)
        shares = [entry["preference_share"] for entry in report["conditions"]]
        self.assertAlmostEqual(sum(share["share"] for share in shares), 1.0)
        for share in shares:
            low, high = share["ci95"]
            self.assertTrue(0 <= low <= share["share"] <= high <= 1, share)

    def test_analysis_is_reproducible(self):
        sheets = [self.sheet(f"l{index}", 1 + index % 5, 5 - index % 3) for index in range(6)]
        ratings, _ = load_ratings(self.key_path, sheets)
        self.assertEqual(analyze_ratings(ratings, samples=300), analyze_ratings(ratings, samples=300))

    def test_invalid_scores_and_unknown_clips_are_errors(self):
        path = self.sheet("bad", 3, 6)
        with self.assertRaisesRegex(ValueError, "from 1 to 5, got '6'"):
            load_ratings(self.key_path, [path])
        rows = read_rows(self.sheet("other", 3, 3))
        rows[0]["clip_id"] = "clip-from-another-pack"
        write_sheet(self.root / "other.csv", rows)
        with self.assertRaisesRegex(ValueError, "not in the facilitator key"):
            load_ratings(self.key_path, [self.root / "other.csv"])

    def test_incomplete_sheets_and_bad_preferences_are_warnings(self):
        rows = read_rows(self.sheet("partial", 3, 4))
        rows = [row for row in rows if row["clip_id"] != "prompt-03-piper"]
        rows[0]["preferred_in_group"] = "x"
        rows[1]["preferred_in_group"] = "x"  # two preferred clips in prompt-01
        write_sheet(self.root / "partial.csv", rows)
        ratings, warnings = load_ratings(self.key_path, [self.root / "partial.csv"])
        self.assertEqual(len(ratings), 5)
        self.assertIn("partial: 1 of 6 clips were not rated.", warnings)
        self.assertTrue(any("preferences ignored for prompt-01" in w for w in warnings))
        self.assertFalse(any(r.preferred for r in ratings if r.group == "prompt-01"))
        report = analyze_ratings(ratings, samples=100)
        self.assertIsNone(report["conditions"][0]["naturalness"]["ci95"])  # one listener

    def test_command_line_prints_a_table_and_writes_json(self):
        sheets = [self.sheet(f"listener-{index}", 3, 4) for index in range(3)]
        output = self.root / "report.json"
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["analyze", "--key", str(self.key_path), "--bootstrap-samples", "200", "--json", str(output), *map(str, sheets)])
        self.assertEqual(code, 0)
        self.assertIn("3 listeners, 18 ratings; baseline piper:voice_default", buffer.getvalue())
        self.assertIn("kokoro:af_sarah - baseline, naturalness: +1.00", buffer.getvalue())
        self.assertEqual(json.loads(output.read_text())["raters"], 3)


if __name__ == "__main__":
    unittest.main()
