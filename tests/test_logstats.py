import tempfile
import unittest
from pathlib import Path

from codex_eink.logstats import filter_days, format_report, load_log, parse_log_lines


SAMPLE = """
2026-07-20 23:59:07 2026-07-20 23:59:07 uploaded 23 packets
2026-07-21 00:01:05 2026-07-21 00:01:05 uploaded 23 packets
2026-07-21 00:09:12 2026-07-21 00:09:12 unchanged
2026-07-21 01:01:27 service-start wrapper-pid=49076
2026-07-21 01:02:05 2026-07-21 01:02:05 uploaded 23 packets
2026-07-21 15:51:50 2026-07-21 15:51:50 retry: (4, 'GATT Protocol Error: Invalid PDU')
2026-07-21 16:17:44 2026-07-21 16:17:44 retry: e-ink device not found (AA:BB:CC:DD:EE:FF); wait
2026-07-21 17:08:52 2026-07-21 17:08:52 unchanged
2026-07-21 17:09:33 2026-07-21 17:09:33 unchanged
""".strip()


class LogStatsTests(unittest.TestCase):
    def test_parse_daily_counts_and_retry_buckets(self):
        days = parse_log_lines(SAMPLE.splitlines())
        self.assertIn("2026-07-20", days)
        self.assertIn("2026-07-21", days)
        d20 = days["2026-07-20"]
        d21 = days["2026-07-21"]
        self.assertEqual(d20.uploaded, 1)
        self.assertEqual(d20.packets, 23)
        self.assertEqual(d21.uploaded, 2)
        self.assertEqual(d21.unchanged, 3)
        self.assertEqual(d21.retry, 2)
        self.assertEqual(d21.service_start, 1)
        self.assertEqual(d21.retries["GATT Invalid PDU"], 1)
        self.assertEqual(d21.retries["device not found"], 1)
        self.assertEqual(d21.max_upload_streak, 1)
        self.assertEqual(d21.hourly["00"]["uploaded"], 1)
        self.assertEqual(d21.hourly["00"]["unchanged"], 1)

    def test_upload_streak_across_consecutive_uploads(self):
        lines = [
            "2026-07-21 10:00:00 uploaded 23 packets",
            "2026-07-21 10:01:00 uploaded 23 packets",
            "2026-07-21 10:02:00 uploaded 23 packets",
            "2026-07-21 10:03:00 unchanged",
            "2026-07-21 10:04:00 uploaded 23 packets",
        ]
        day = parse_log_lines(lines)["2026-07-21"]
        self.assertEqual(day.max_upload_streak, 3)
        self.assertEqual(day.upload_bursts, 2)

    def test_filter_and_report(self):
        days = parse_log_lines(SAMPLE.splitlines())
        only = filter_days(days, day="2026-07-21")
        self.assertEqual(len(only), 1)
        report = format_report(only, hourly=True)
        self.assertIn("2026-07-21", report)
        self.assertIn("top retries", report)
        self.assertIn("GATT Invalid PDU", report)
        self.assertIn("hourly", report)

    def test_winerror_bucket(self):
        lines = ["2026-07-21 12:00:00 retry: [WinError -2147418113] 乱七八糟"]
        day = parse_log_lines(lines)["2026-07-21"]
        self.assertEqual(day.retries["WinError -2147418113"], 1)

    def test_load_log_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "dashboard.log"
            path.write_text(SAMPLE + "\n", encoding="utf-8")
            days = load_log(path)
        self.assertEqual(days["2026-07-20"].uploaded, 1)


if __name__ == "__main__":
    unittest.main()
