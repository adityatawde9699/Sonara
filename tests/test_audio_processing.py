import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from audio_processing import (
    DEFAULT_FINISH,
    apply_fades,
    finish_wav,
    match_level,
    speech_level_dbfs,
    trim_silence,
)

RATE = 22050


def tone(ms: int, amplitude: float = 0.3) -> np.ndarray:
    return (amplitude * np.sin(2 * np.pi * 200 * np.arange(RATE * ms // 1000) / RATE)).astype(np.float32)


def silence(ms: int) -> np.ndarray:
    return np.zeros(RATE * ms // 1000, dtype=np.float32)


class TrimTests(unittest.TestCase):
    def test_edges_are_cut_to_the_configured_pads(self):
        samples = np.concatenate([silence(250), tone(400), silence(300)])
        trimmed = trim_silence(samples, RATE)
        expected_ms = 400 + DEFAULT_FINISH.lead_pad_ms + DEFAULT_FINISH.trail_pad_ms
        self.assertAlmostEqual(1000 * len(trimmed) / RATE, expected_ms, delta=12)

    def test_quiet_tail_within_range_of_the_peak_is_kept(self):
        # A soft word ending 30 dB under the peak is speech, not silence.
        samples = np.concatenate([tone(300), tone(200, 0.3 * 10 ** (-30 / 20)), silence(300)])
        self.assertGreater(1000 * len(trim_silence(samples, RATE)) / RATE, 500)

    def test_silent_and_empty_chunks_are_left_alone(self):
        quiet = silence(100)
        self.assertIs(trim_silence(quiet, RATE), quiet)
        self.assertEqual(len(trim_silence(np.zeros(0, dtype=np.float32), RATE)), 0)


class LevelTests(unittest.TestCase):
    def test_gated_level_ignores_silence(self):
        speech = tone(500)
        with_gaps = np.concatenate([silence(1000), speech, silence(1000)])
        self.assertAlmostEqual(speech_level_dbfs(with_gaps, RATE), speech_level_dbfs(speech, RATE), delta=0.5)
        self.assertIsNone(speech_level_dbfs(silence(200), RATE))

    def test_voices_at_different_levels_end_at_the_same_level(self):
        loud, _ = match_level(tone(500, 0.4), RATE)
        soft, gain = match_level(tone(500, 0.1), RATE)
        self.assertGreater(gain, 0)
        self.assertAlmostEqual(speech_level_dbfs(loud, RATE), DEFAULT_FINISH.target_speech_dbfs, delta=0.2)
        self.assertAlmostEqual(speech_level_dbfs(soft, RATE), DEFAULT_FINISH.target_speech_dbfs, delta=0.2)

    def test_gain_respects_the_peak_ceiling_and_the_gain_limit(self):
        # A sparse click train has a low RMS but high peaks.
        clicks = silence(500)
        clicks[::2000] = 0.9
        boosted, _ = match_level(clicks, RATE)
        self.assertLessEqual(float(np.max(np.abs(boosted))), 10 ** (DEFAULT_FINISH.peak_ceiling_dbfs / 20) + 1e-4)
        _, gain = match_level(tone(500, 0.001), RATE)
        self.assertLessEqual(gain, DEFAULT_FINISH.max_gain_db)


class FadeAndFileTests(unittest.TestCase):
    def test_fades_start_and_end_at_zero(self):
        faded = apply_fades(np.full(RATE // 10, 0.5, dtype=np.float32), RATE)
        self.assertEqual(faded[0], 0)
        self.assertLess(abs(faded[-1]), 1e-3)
        self.assertAlmostEqual(float(faded[len(faded) // 2]), 0.5)

    def test_finish_wav_rewrites_the_file_in_place(self):
        samples = np.concatenate([silence(300), tone(400, 0.1), silence(300)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chunk.wav"
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(RATE)
                output.writeframes((samples * 32767).astype("<i2").tobytes())
            gain = finish_wav(path)
            with wave.open(str(path), "rb") as finished:
                frames = finished.getnframes()
                result = np.frombuffer(finished.readframes(frames), dtype="<i2").astype(np.float32) / 32768
            self.assertEqual(sorted(item.name for item in Path(directory).iterdir()), ["chunk.wav"])
        self.assertGreater(gain, 0)
        self.assertLess(frames / RATE, 0.5)
        self.assertAlmostEqual(speech_level_dbfs(result, RATE), DEFAULT_FINISH.target_speech_dbfs, delta=0.3)

    def test_finish_wav_rejects_stereo(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stereo.wav"
            with wave.open(str(path), "wb") as output:
                output.setnchannels(2)
                output.setsampwidth(2)
                output.setframerate(RATE)
                output.writeframes(b"\0\0\0\0" * 10)
            with self.assertRaises(ValueError):
                finish_wav(path)


if __name__ == "__main__":
    unittest.main()
