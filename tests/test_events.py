import unittest
from pathlib import Path

from codex_eink.events import CodexEventWatcher


class CodexEventWatcherTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("C:/codex")
        self.watcher = CodexEventWatcher(self.root)

    def test_only_dashboard_state_sources_are_relevant(self):
        self.assertTrue(self.watcher.is_relevant_path(self.root / "sessions" / "2026" / "07" / "rollout-a.jsonl"))
        self.assertTrue(self.watcher.is_relevant_path(self.root / "session_index.jsonl"))
        self.assertTrue(self.watcher.is_relevant_path(self.root / ".codex-global-state.json"))
        self.assertFalse(self.watcher.is_relevant_path(self.root / "state_5.sqlite-wal"))
        self.assertFalse(self.watcher.is_relevant_path(self.root / "logs_2.sqlite"))
        self.assertFalse(self.watcher.is_relevant_path(self.root / "logs" / "unrelated.log"))

    def test_burst_signal_extends_the_quiet_period(self):
        clock = [100.0]
        watcher = CodexEventWatcher(self.root, clock=lambda: clock[0])
        watcher.signal()
        clock[0] = 100.5
        self.assertEqual(watcher.quiet_remaining(1.0), 0.5)
        watcher.signal()
        clock[0] = 101.0
        self.assertEqual(watcher.quiet_remaining(1.0), 0.5)

    def test_signal_after_a_completed_wait_remains_pending(self):
        self.watcher.signal()
        self.assertTrue(self.watcher.wait(0))
        self.watcher.wait_until_quiet(0)
        self.assertFalse(self.watcher.wait(0))
        self.watcher.signal()
        self.assertTrue(self.watcher.wait(0))


if __name__ == "__main__":
    unittest.main()
