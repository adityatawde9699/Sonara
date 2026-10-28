import unittest

from resource_policy import ResourceProfile, get_resource_profile


class ResourceProfileTests(unittest.TestCase):
    def test_named_profiles_bound_tts_work(self):
        low = get_resource_profile("low_resource")
        standard = get_resource_profile("standard")
        high = get_resource_profile("high_performance")
        self.assertEqual(low.tts_prefetch_chunks, 1)
        self.assertEqual(standard.tts_prefetch_chunks, 2)
        self.assertGreater(high.tts_prefetch_chunks, standard.tts_prefetch_chunks)
        self.assertGreater(high.audio_cache_bytes, low.audio_cache_bytes)

    def test_unknown_and_invalid_custom_profiles_are_rejected(self):
        with self.assertRaises(ValueError):
            get_resource_profile("automatic")
        with self.assertRaises(ValueError):
            get_resource_profile("custom")
        custom = ResourceProfile("custom", 17, 1)
        with self.assertRaises(ValueError):
            get_resource_profile("custom", custom=custom)


if __name__ == "__main__":
    unittest.main()
