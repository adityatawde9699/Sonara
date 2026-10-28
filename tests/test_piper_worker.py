import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

from piper_worker import PIPER_SENTENCE_PAUSE_MS, _write_sentences_with_pauses


class PiperSentencePauseTests(unittest.TestCase):
    def _wav(self, chunks):
        class FakeVoice:
            config = SimpleNamespace(sample_rate=22050)

            def synthesize(self, text, *, syn_config):
                yield from chunks

        return FakeVoice()

    def test_inserts_pause_between_sentences_but_not_after_last_sentence(self):
        audio_chunks = [
            SimpleNamespace(audio_int16_bytes=b"\x01\x00" * 2),
            SimpleNamespace(audio_int16_bytes=b"\x02\x00" * 2),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "speech.wav"
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(22050)
                _write_sentences_with_pauses(self._wav(audio_chunks), "First. Second.", wav_file, object())

            with wave.open(str(path), "rb") as wav_file:
                frame_count = wav_file.getnframes()
                frames = wav_file.readframes(frame_count)

        pause_frames = round(22050 * PIPER_SENTENCE_PAUSE_MS / 1000)
        self.assertEqual(frame_count, 4 + pause_frames)
        self.assertEqual(frames[:4], b"\x01\x00" * 2)
        self.assertEqual(frames[4:4 + pause_frames * 2], bytes(pause_frames * 2))
        self.assertEqual(frames[-4:], b"\x02\x00" * 2)

    def test_single_sentence_has_no_added_silence(self):
        audio = b"\x01\x00" * 3
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "speech.wav"
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(22050)
                _write_sentences_with_pauses(self._wav([SimpleNamespace(audio_int16_bytes=audio)]), "Only.", wav_file, object())

            with wave.open(str(path), "rb") as wav_file:
                self.assertEqual(wav_file.readframes(wav_file.getnframes()), audio)


if __name__ == "__main__":
    unittest.main()
