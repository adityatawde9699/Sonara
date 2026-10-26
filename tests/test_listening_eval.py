import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from benchmark import BENCHMARK_PASSAGES
from listening_eval import loudness_match_wav


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


if __name__ == "__main__":
    unittest.main()
