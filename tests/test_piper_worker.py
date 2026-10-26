import unittest
from types import SimpleNamespace

from piper_worker import _variation_scales


class PiperVariationTests(unittest.TestCase):
    def setUp(self):
        self.voice_config = SimpleNamespace(noise_scale=0.667, noise_w_scale=0.8)

    def test_voice_default_defers_to_model_config(self):
        self.assertEqual(_variation_scales(self.voice_config, "voice_default"), (None, None))

    def test_less_and_more_variation_scale_the_selected_voice_defaults(self):
        less = _variation_scales(self.voice_config, "less")
        more = _variation_scales(self.voice_config, "more")
        self.assertAlmostEqual(less[0], 0.667 * 0.85)
        self.assertAlmostEqual(less[1], 0.8 * 0.85)
        self.assertAlmostEqual(more[0], 0.667 * 1.10)
        self.assertAlmostEqual(more[1], 0.8 * 1.10)

    def test_variation_rejects_unsupported_names_and_out_of_range_values(self):
        with self.assertRaisesRegex(ValueError, "variation must be"):
            _variation_scales(self.voice_config, "dramatic")
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            _variation_scales(self.voice_config, "voice_default", noise_scale=1.1)


if __name__ == "__main__":
    unittest.main()
