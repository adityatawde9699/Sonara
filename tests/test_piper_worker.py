import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from piper_worker import PIPER_SENTENCE_PAUSE_MS, _sentence_pause_ms, _write_sentences_with_pauses

RATE = 22050


def sentence(speech_ms: int, lead_ms: int = 0, trail_ms: int = 0) -> bytes:
    """A tone burst with optional built-in silence, like a Piper sentence chunk."""
    tone = 0.3 * np.sin(2 * np.pi * 220 * np.arange(RATE * speech_ms // 1000) / RATE)
    samples = np.concatenate([np.zeros(RATE * lead_ms // 1000), tone, np.zeros(RATE * trail_ms // 1000)])
    return (samples * 32767).astype("<i2").tobytes()


class PiperSentencePauseTests(unittest.TestCase):
    def _voice(self, chunks):
        class FakeVoice:
            config = SimpleNamespace(sample_rate=RATE)

            def synthesize(self, text, *, syn_config):
                yield from (SimpleNamespace(audio_int16_bytes=chunk) for chunk in chunks)

        return FakeVoice()

    def _render(self, chunks, **kwargs) -> np.ndarray:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "speech.wav"
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(RATE)
                _write_sentences_with_pauses(self._voice(chunks), "First. Second.", wav_file, object(), **kwargs)
            with wave.open(str(path), "rb") as wav_file:
                return np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype="<i2")

    @staticmethod
    def _silent_runs_ms(samples: np.ndarray) -> list[float]:
        quiet = np.abs(samples) < 30
        runs, length = [], 0
        for value in quiet:
            if value:
                length += 1
            elif length:
                runs.append(length)
                length = 0
        if length:
            runs.append(length)
        return [1000 * run / RATE for run in runs]

    def test_built_in_silence_is_trimmed_so_the_planned_pause_is_the_gap(self):
        # Voices differ: one leaves 200 ms of trailing silence, one leaves none.
        padded = self._render([sentence(300, 40, 200), sentence(300, 60, 150)])
        tight = self._render([sentence(300), sentence(300)])
        gap = max(self._silent_runs_ms(padded))
        # Pause plus the trailing and leading pads (40 + 15 ms) and up to one
        # 10 ms analysis frame each; untrimmed it would be about 460 ms.
        self.assertGreaterEqual(gap, PIPER_SENTENCE_PAUSE_MS)
        self.assertLessEqual(gap, PIPER_SENTENCE_PAUSE_MS + 80)
        # Without trimming the two voices would differ by about 260 ms here.
        self.assertLess(abs(gap - max(self._silent_runs_ms(tight))), 80)

    def test_no_pause_after_the_last_sentence_and_custom_pause_length(self):
        single = self._render([sentence(200, 0, 300)])
        # Trailing built-in silence is cut to the trail pad, not kept at 300 ms.
        self.assertLess(len(single), RATE * 0.26)
        two = self._render([sentence(200), sentence(200)], pause_ms=500)
        self.assertGreaterEqual(max(self._silent_runs_ms(two)), 500)
        self.assertEqual(two[0], 0)  # faded in, no click at the chunk edge

    def test_sentence_pause_is_validated(self):
        self.assertEqual(_sentence_pause_ms(None), PIPER_SENTENCE_PAUSE_MS)
        self.assertEqual(_sentence_pause_ms(230), 230)
        for value in (-1, 5000, True, "200", float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _sentence_pause_ms(value)


if __name__ == "__main__":
    unittest.main()
