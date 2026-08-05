import json
import tempfile
import unittest
from pathlib import Path

from codex_eink.config import AppConfig
from codex_eink.models import SUPPORTED_RESOLUTIONS, ProjectState, ProjectStatus, QuotaWindow


class ModelTests(unittest.TestCase):
    def test_supported_panel_profiles_are_exact(self):
        self.assertEqual(
            SUPPORTED_RESOLUTIONS,
            ((212, 104), (250, 122), (296, 128), (400, 300)),
        )

    def test_config_defaults_keep_landscape_and_use_fastest_safe_polling(self):
        config = AppConfig()
        self.assertEqual(config.device_name_prefix, "SKD-CLOCK")
        self.assertEqual(config.orientation, "landscape")
        self.assertEqual(config.active_poll_seconds, 30)
        self.assertEqual(config.idle_poll_seconds, 60)
        self.assertEqual(config.ble_keepalive_seconds, 20)
        self.assertFalse(config.ble_always_connected)
        self.assertEqual(config.privacy_mode, "summary")

    def test_config_loads_resolution_override(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(
                json.dumps({"resolution": [296, 128], "privacy_mode": "titles", "orientation": "portrait_cw"}),
                encoding="utf-8",
            )
            config = AppConfig.load(path)
        self.assertEqual(config.resolution, (296, 128))
        self.assertEqual(config.privacy_mode, "titles")
        self.assertEqual(config.orientation, "portrait_cw")

    def test_invalid_resolution_is_rejected(self):
        with self.assertRaises(ValueError):
            AppConfig(resolution=(320, 240))

    def test_invalid_orientation_is_rejected(self):
        with self.assertRaises(ValueError):
            AppConfig(orientation="diagonal")

    def test_negative_ble_keepalive_is_rejected(self):
        with self.assertRaises(ValueError):
            AppConfig(ble_keepalive_seconds=-1)

    def test_project_terminal_identity_is_stable(self):
        project = ProjectState(
            session_id="abc",
            title="Demo",
            status=ProjectStatus.DONE,
            updated_at=123.0,
            terminal_id="turn-1",
        )
        self.assertEqual(project.alert_id, "abc:turn-1:done")

    def test_quota_display_uses_exact_remaining_percentage(self):
        self.assertEqual(QuotaWindow(used_percent=71).display_remaining_percent, 29)
        self.assertEqual(QuotaWindow(used_percent=72).display_remaining_percent, 28)
        self.assertEqual(QuotaWindow(used_percent=97).display_remaining_percent, 3)


if __name__ == "__main__":
    unittest.main()
