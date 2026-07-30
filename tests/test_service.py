import tempfile
import unittest
from pathlib import Path

from PIL import Image

from codex_eink.service import FrameCache, frame_digest, quantize_battery_voltage, quantize_sync_time, should_upload


class ServiceTests(unittest.TestCase):
    def test_identical_frame_is_suppressed(self):
        image = Image.new("1", (212, 104), 1)
        digest = frame_digest(image)
        self.assertFalse(should_upload(digest, digest))
        self.assertTrue(should_upload(digest, None))

    def test_sync_time_changes_only_every_five_minutes(self):
        self.assertEqual(quantize_sync_time(601), 600)
        self.assertEqual(quantize_sync_time(899), 600)
        self.assertEqual(quantize_sync_time(900), 900)

    def test_battery_quantization_hysteresis_holds_display_bucket(self):
        self.assertEqual(quantize_battery_voltage(3.47), 3.5)
        self.assertEqual(quantize_battery_voltage(3.44, 3.5), 3.5)
        self.assertEqual(quantize_battery_voltage(3.41, 3.5), 3.4)
        self.assertEqual(quantize_battery_voltage(None, 3.5), 3.5)

    def test_frame_cache_persists_battery_display(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = FrameCache(Path(folder) / ".state.json")
            cache.save(digest="abc", synced_at=1.0, resolution=(212, 104), battery_display=3.5)
            loaded = cache.load()
        self.assertEqual(loaded["frame_digest"], "abc")
        self.assertEqual(loaded["resolution"], [212, 104])
        self.assertEqual(loaded["battery_display"], 3.5)


if __name__ == "__main__":
    unittest.main()
