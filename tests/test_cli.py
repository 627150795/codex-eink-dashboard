import asyncio
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image

from codex_eink.ble import DeviceStatus
from codex_eink.cli import UpdateOutcome, _once, collect_view, command_run, wait_for_refresh
from codex_eink.config import AppConfig
from codex_eink.events import CodexChanges
from codex_eink.models import DashboardView, ProjectState, ProjectStatus, QuotaState, QuotaWindow
from codex_eink.service import FrameCache, frame_digest


class CollectViewTests(unittest.TestCase):
    def test_live_quota_failure_keeps_last_successful_value(self):
        live_quota = QuotaState(primary=QuotaWindow(used_percent=82), plan_type="plus")
        with (
            patch("codex_eink.cli.load_session_titles", return_value={}),
            patch("codex_eink.cli.load_state_titles", return_value={}),
            patch("codex_eink.cli.collect_projects", return_value=[]),
            patch("codex_eink.cli.load_recent_thread_activity", return_value={}),
            patch("codex_eink.cli.reconcile_live_activity", return_value=[]),
            patch("codex_eink.cli.read_live_quota", side_effect=[live_quota, RuntimeError("down"), RuntimeError("down")]),
            patch("codex_eink.cli.read_quota_fallback", side_effect=AssertionError("stale fallback used")),
            patch("codex_eink.cli._LAST_SUCCESSFUL_LIVE_QUOTA", None),
        ):
            before = collect_view(AppConfig(codex_home=Path("C:/codex-test"))).quota
            after = collect_view(AppConfig(codex_home=Path("C:/codex-test"))).quota
        self.assertEqual(before, live_quota)
        self.assertEqual(after, live_quota)

    def test_event_refresh_keeps_cached_live_quota_out_of_historical_fallback(self):
        live_quota = QuotaState(primary=QuotaWindow(used_percent=100), plan_type="plus")
        historical_quota = QuotaState(primary=QuotaWindow(used_percent=70))
        with (
            patch("codex_eink.cli.load_session_titles", return_value={}),
            patch("codex_eink.cli.load_state_titles", return_value={}),
            patch("codex_eink.cli.collect_projects", return_value=[]),
            patch("codex_eink.cli.load_recent_thread_activity", return_value={}),
            patch("codex_eink.cli.reconcile_live_activity", return_value=[]),
            patch("codex_eink.cli.read_quota_fallback", return_value=historical_quota) as fallback,
            patch("codex_eink.cli._LAST_SUCCESSFUL_LIVE_QUOTA", live_quota),
        ):
            view = collect_view(
                AppConfig(codex_home=Path("C:/codex-test")),
                live_quota=False,
                use_quota_fallback=False,
            )

        self.assertEqual(view.quota, live_quota)
        fallback.assert_not_called()

    def test_live_quota_rejects_partial_rebound(self):
        for current_used, stale_used in ((100, 93), (60, 55), (10, 5)):
            current_quota = QuotaState(primary=QuotaWindow(used_percent=current_used), plan_type="plus")
            stale_quota = QuotaState(primary=QuotaWindow(used_percent=stale_used), plan_type="plus")
            with self.subTest(current_used=current_used, stale_used=stale_used):
                with (
                    patch("codex_eink.cli.load_session_titles", return_value={}),
                    patch("codex_eink.cli.load_state_titles", return_value={}),
                    patch("codex_eink.cli.collect_projects", return_value=[]),
                    patch("codex_eink.cli.load_recent_thread_activity", return_value={}),
                    patch("codex_eink.cli.reconcile_live_activity", return_value=[]),
                    patch("codex_eink.cli.read_live_quota", return_value=stale_quota),
                    patch("codex_eink.cli.read_quota_fallback", side_effect=AssertionError("fallback used")),
                    patch("codex_eink.cli._LAST_SUCCESSFUL_LIVE_QUOTA", current_quota),
                ):
                    view = collect_view(AppConfig(codex_home=Path("C:/codex-test")))

                self.assertEqual(view.quota, current_quota)

    def test_live_quota_accepts_reset_range(self):
        current_quota = QuotaState(primary=QuotaWindow(used_percent=100), plan_type="plus")
        for reset_used in (2, 1, 0):
            reset_quota = QuotaState(primary=QuotaWindow(used_percent=reset_used), plan_type="plus")
            with self.subTest(reset_used=reset_used):
                with (
                    patch("codex_eink.cli.load_session_titles", return_value={}),
                    patch("codex_eink.cli.load_state_titles", return_value={}),
                    patch("codex_eink.cli.collect_projects", return_value=[]),
                    patch("codex_eink.cli.load_recent_thread_activity", return_value={}),
                    patch("codex_eink.cli.reconcile_live_activity", return_value=[]),
                    patch("codex_eink.cli.read_live_quota", return_value=reset_quota),
                    patch("codex_eink.cli.read_quota_fallback", side_effect=AssertionError("fallback used")),
                    patch("codex_eink.cli._LAST_SUCCESSFUL_LIVE_QUOTA", current_quota),
                ):
                    view = collect_view(AppConfig(codex_home=Path("C:/codex-test")))

                self.assertEqual(view.quota, reset_quota)

    def test_transient_live_quota_error_is_retried_before_fallback(self):
        live_quota = QuotaState(primary=QuotaWindow(used_percent=20), plan_type="plus")
        with (
            patch("codex_eink.cli.load_session_titles", return_value={}),
            patch("codex_eink.cli.load_state_titles", return_value={}),
            patch("codex_eink.cli.collect_projects", return_value=[]),
            patch("codex_eink.cli.load_recent_thread_activity", return_value={}),
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
            patch("codex_eink.cli.load_recent_thread_activity", return_value={}),
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
            patch("codex_eink.cli.load_recent_thread_activity", return_value={}),
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
            patch("codex_eink.cli.load_recent_thread_activity", return_value={}),
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
    def test_event_refresh_uses_cached_quota_before_next_poll(self):
        config = AppConfig(codex_home=Path("C:/codex-test"))
        watcher = MagicMock()
        watcher.__enter__.return_value = watcher
        watcher.__exit__.return_value = None
        watcher.revision = 0
        watcher.consume_changes.return_value = CodexChanges(
            frozenset({"rollout"}),
            frozenset({Path("C:/codex-test/sessions/rollout-a.jsonl")}),
            1,
        )
        calls = []
        transport = MagicMock()
        transport.close = AsyncMock()

        async def fake_once(_config, **kwargs):
            calls.append(kwargs)
            if len(calls) > 1:
                raise KeyboardInterrupt
            return UpdateOutcome("unchanged", None, False)

        args = SimpleNamespace(config=None, preview="previews/live.png")
        with (
            patch("codex_eink.cli._config", return_value=config),
            patch("codex_eink.cli.CodexEventWatcher", return_value=watcher),
            patch("codex_eink.cli._transport", return_value=transport) as make_transport,
            patch("codex_eink.cli._once", side_effect=fake_once),
            patch("codex_eink.cli.collect_view", side_effect=AssertionError("duplicate collection")),
            patch("codex_eink.cli.wait_for_refresh", return_value=True),
        ):
            self.assertEqual(command_run(args), 0)

        self.assertEqual(calls[0]["live_quota"], True)
        self.assertEqual(calls[0]["use_quota_fallback"], True)
        self.assertEqual(calls[1]["live_quota"], False)
        self.assertEqual(calls[1]["use_quota_fallback"], False)
        self.assertIs(calls[0]["transport"], transport)
        self.assertIs(calls[1]["transport"], transport)
        make_transport.assert_called_once_with(config, keepalive_seconds=20)
        transport.close.assert_awaited_once()

    def test_always_connected_mode_maintains_an_indefinite_transport(self):
        config = AppConfig(codex_home=Path("C:/codex-test"), ble_always_connected=True)
        watcher = MagicMock()
        watcher.__enter__.return_value = watcher
        watcher.__exit__.return_value = None
        watcher.revision = 0
        transport = MagicMock()
        transport.ensure_connected = AsyncMock(return_value=True)
        transport.close = AsyncMock()
        calls = 0

        async def fake_once(_config, **_kwargs):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise KeyboardInterrupt
            return UpdateOutcome("unchanged", None, False)

        args = SimpleNamespace(config=None, preview="previews/live.png")
        with (
            patch("codex_eink.cli._config", return_value=config),
            patch("codex_eink.cli.CodexEventWatcher", return_value=watcher),
            patch("codex_eink.cli._transport", return_value=transport) as make_transport,
            patch("codex_eink.cli._once", side_effect=fake_once),
            patch("codex_eink.cli.wait_for_refresh", return_value=True),
        ):
            self.assertEqual(command_run(args), 0)

        make_transport.assert_called_once_with(config, keepalive_seconds=None)
        transport.ensure_connected.assert_awaited_once()
        transport.close.assert_awaited_once()

    def test_stale_frame_is_dropped_before_ble_connect(self):
        with tempfile.TemporaryDirectory() as folder:
            preview = Path(folder) / "preview.png"
            FrameCache(preview.parent / ".state.json").save(
                digest="old",
                synced_at=1,
                resolution=(212, 104),
                battery_display=3.5,
            )
            image = Image.new("1", (212, 104), 0)
            transport = MagicMock()
            view = DashboardView(global_status="IDLE")
            with (
                patch("codex_eink.cli._transport", return_value=transport),
                patch("codex_eink.cli.collect_view", return_value=view),
                patch("codex_eink.cli.render_dashboard", return_value=image),
            ):
                outcome = asyncio.run(
                    _once(
                        AppConfig(codex_home=Path(folder), resolution=(212, 104), account_mode="api"),
                        force=False,
                        preview_path=preview,
                        is_stale=lambda: True,
                    )
                )

        self.assertEqual(outcome.message, "superseded")
        transport.with_client.assert_not_called()
        self.assertFalse(preview.exists())

    def test_unchanged_frame_does_not_rewrite_existing_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            preview = Path(folder) / "preview.png"
            preview.write_bytes(b"existing-preview")
            image = Image.new("1", (212, 104), 1)
            FrameCache(preview.parent / ".state.json").save(
                digest=frame_digest(image),
                synced_at=1,
                resolution=(212, 104),
                battery_display=3.5,
            )
            transport = MagicMock()
            view = DashboardView(global_status="IDLE")
            with (
                patch("codex_eink.cli._transport", return_value=transport),
                patch("codex_eink.cli.collect_view", return_value=view),
                patch("codex_eink.cli.render_dashboard", return_value=image),
            ):
                outcome = asyncio.run(
                    _once(
                        AppConfig(codex_home=Path(folder), resolution=(212, 104), account_mode="api"),
                        force=False,
                        preview_path=preview,
                    )
                )

            self.assertEqual(preview.read_bytes(), b"existing-preview")
        self.assertEqual(outcome.message, "unchanged")
        transport.with_client.assert_not_called()

    def test_bootstrap_reads_status_and_uploads_on_one_connection(self):
        with tempfile.TemporaryDirectory() as folder:
            preview = Path(folder) / "preview.png"
            image = Image.new("1", (212, 104), 1)
            status = DeviceStatus(0, (212, 104), False, 1.2, 3.7, 24, True, True)
            transport = MagicMock()
            transport._read_status = AsyncMock(return_value=status)
            transport.write_packets = AsyncMock()

            async def with_client(callback, *, retries):
                self.assertEqual(retries, 2)
                return await callback(object())

            transport.with_client = AsyncMock(side_effect=with_client)
            view = DashboardView(global_status="IDLE")
            with (
                patch("codex_eink.cli._transport", return_value=transport),
                patch("codex_eink.cli.collect_view", return_value=view),
                patch("codex_eink.cli.render_dashboard", return_value=image),
            ):
                outcome = asyncio.run(
                    _once(
                        AppConfig(codex_home=Path(folder), account_mode="api"),
                        force=True,
                        preview_path=preview,
                    )
                )

        self.assertTrue(outcome.message.startswith("uploaded "))
        transport.with_client.assert_awaited_once()
        transport._read_status.assert_awaited_once()
        transport.write_packets.assert_awaited_once()
        transport.probe.assert_not_called()
        transport.upload.assert_not_called()

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
