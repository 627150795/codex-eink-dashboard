from pathlib import Path
import time
import unittest
from unittest.mock import patch

from codex_eink.cli import collect_view, wait_for_refresh
from codex_eink.config import AppConfig
from codex_eink.models import ProjectState, ProjectStatus, QuotaState, QuotaWindow


class CollectViewTests(unittest.TestCase):
    def test_live_quota_failure_keeps_last_successful_value(self):
        live_quota = QuotaState(primary=QuotaWindow(used_percent=82), plan_type="plus")
        with (
            patch("codex_eink.cli.load_session_titles", return_value={}),
            patch("codex_eink.cli.load_state_titles", return_value={}),
            patch("codex_eink.cli.collect_projects", return_value=[]),
            patch("codex_eink.cli.load_recent_thread_ids", return_value=[]),
            patch("codex_eink.cli.reconcile_live_activity", return_value=[]),
            patch("codex_eink.cli.read_live_quota", side_effect=[live_quota, RuntimeError("down"), RuntimeError("down")]),
            patch("codex_eink.cli.read_quota_fallback", side_effect=AssertionError("stale fallback used")),
            patch("codex_eink.cli._LAST_SUCCESSFUL_LIVE_QUOTA", None),
        ):
            before = collect_view(AppConfig(codex_home=Path("C:/codex-test"))).quota
            after = collect_view(AppConfig(codex_home=Path("C:/codex-test"))).quota
        self.assertEqual(before, live_quota)
        self.assertEqual(after, live_quota)

    def test_transient_live_quota_error_is_retried_before_fallback(self):
        live_quota = QuotaState(primary=QuotaWindow(used_percent=20), plan_type="plus")
        with (
            patch("codex_eink.cli.load_session_titles", return_value={}),
            patch("codex_eink.cli.load_state_titles", return_value={}),
            patch("codex_eink.cli.collect_projects", return_value=[]),
            patch("codex_eink.cli.load_recent_thread_ids", return_value=[]),
            patch("codex_eink.cli.reconcile_live_activity", return_value=[]),
            patch("codex_eink.cli.read_live_quota", side_effect=[RuntimeError("temporary"), live_quota]) as read_live,
            patch("codex_eink.cli.read_quota_fallback", side_effect=AssertionError("stale fallback used")),
        ):
            view = collect_view(AppConfig(codex_home=Path("C:/codex-test")))
        self.assertEqual(view.quota, live_quota)
        self.assertEqual(read_live.call_count, 2)

    def test_verified_api_plan_does_not_read_session_quota(self):
        with (
            patch("codex_eink.cli.load_session_titles", return_value={}),
            patch("codex_eink.cli.load_state_titles", return_value={}),
            patch("codex_eink.cli.collect_projects", return_value=[]),
            patch("codex_eink.cli.load_recent_thread_ids", return_value=[]),
            patch("codex_eink.cli.reconcile_live_activity", return_value=[]),
            patch("codex_eink.cli.read_live_quota", return_value=QuotaState(plan_type="api")),
            patch("codex_eink.cli.read_quota_fallback", side_effect=AssertionError("fallback used")),
        ):
            view = collect_view(AppConfig(codex_home=Path("C:/codex-test")))
        self.assertEqual(view.quota.plan_type, "api")

    def test_configured_api_plan_skips_live_and_session_quota_reads(self):
        with (
            patch("codex_eink.cli.load_session_titles", return_value={}),
            patch("codex_eink.cli.load_state_titles", return_value={}),
            patch("codex_eink.cli.collect_projects", return_value=[]),
            patch("codex_eink.cli.load_recent_thread_ids", return_value=[]),
            patch("codex_eink.cli.reconcile_live_activity", return_value=[]),
            patch("codex_eink.cli.read_live_quota", side_effect=AssertionError("live quota used")),
            patch("codex_eink.cli.read_quota_fallback", side_effect=AssertionError("fallback used")),
        ):
            view = collect_view(AppConfig(codex_home=Path("C:/codex-test"), account_mode="api"))
        self.assertEqual(view.quota.plan_type, "api")

    def test_completed_unread_thread_is_marked_for_the_status_strip(self):
        now = time.time()
        completed = ProjectState("done", "Done", ProjectStatus.DONE, now)
        failed = ProjectState("error", "Error", ProjectStatus.ERROR, now)
        with (
            patch("codex_eink.cli.load_session_titles", return_value={}),
            patch("codex_eink.cli.load_state_titles", return_value={}),
            patch("codex_eink.cli.collect_projects", return_value=[completed, failed]),
            patch("codex_eink.cli.load_recent_thread_ids", return_value=[]),
            patch("codex_eink.cli.reconcile_live_activity", return_value=[completed, failed]),
            patch("codex_eink.cli.load_unread_thread_ids", return_value={"done", "error"}),
            patch("codex_eink.cli.read_quota_fallback", return_value=QuotaState()),
        ):
            view = collect_view(AppConfig(codex_home=Path("C:/codex-test")), live_quota=False)
        self.assertEqual(
            [(project.session_id, project.unread) for project in view.status_projects],
            [("done", True), ("error", True)],
        )


class _WatcherStub:
    def __init__(self, signaled: bool):
        self.signaled = signaled
        self.wait_calls = []
        self.quiet_calls = []

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        return self.signaled

    def wait_until_quiet(self, seconds):
        self.quiet_calls.append(seconds)


class RefreshSchedulingTests(unittest.TestCase):
    def test_event_preempts_the_poll_deadline(self):
        watcher = _WatcherStub(signaled=True)
        self.assertTrue(wait_for_refresh(watcher, fallback_seconds=30, coalesce_seconds=1))
        self.assertEqual(watcher.wait_calls, [30])
        self.assertEqual(watcher.quiet_calls, [1])

    def test_poll_deadline_does_not_add_a_coalesce_delay(self):
        watcher = _WatcherStub(signaled=False)
        self.assertFalse(wait_for_refresh(watcher, fallback_seconds=60, coalesce_seconds=1))
        self.assertEqual(watcher.wait_calls, [60])
        self.assertEqual(watcher.quiet_calls, [])


if __name__ == "__main__":
    unittest.main()
