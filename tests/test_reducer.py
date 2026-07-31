import unittest

from codex_eink.models import ProjectState, ProjectStatus, QuotaState, QuotaWindow
from codex_eink.reducer import reduce_dashboard


class ReducerTests(unittest.TestCase):
    def project(self, session_id, status, updated_at, title=None):
        return ProjectState(session_id, title or session_id, status, updated_at, terminal_id=f"turn-{session_id}")

    def test_running_has_priority_over_recent_completion(self):
        view = reduce_dashboard(
            [self.project("run", ProjectStatus.ACTIVE, 100), self.project("done", ProjectStatus.DONE, 99)],
            QuotaState(),
            now=110,
            last_success_at=110,
        )
        self.assertEqual(view.global_status, "RUN")
        self.assertEqual([p.session_id for p in view.active_projects], ["run"])
        self.assertEqual(view.alerts[0].session_id, "done")

    def test_error_and_limit_precedence(self):
        quota = QuotaState(primary=QuotaWindow(used_percent=100, resets_at=500))
        view = reduce_dashboard([], quota, now=100, last_success_at=100)
        self.assertEqual(view.global_status, "LIMIT")

    def test_stale_state_is_offline_but_keeps_projects(self):
        view = reduce_dashboard(
            [self.project("run", ProjectStatus.ACTIVE, 100)],
            QuotaState(),
            now=300,
            last_success_at=100,
            poll_seconds=60,
        )
        self.assertEqual(view.global_status, "OFFLINE")
        self.assertEqual(len(view.active_projects), 1)

    def test_terminal_alerts_are_deduplicated(self):
        duplicate = self.project("done", ProjectStatus.DONE, 100)
        view = reduce_dashboard([duplicate, duplicate], QuotaState(), now=110, last_success_at=110)
        self.assertEqual(len(view.alerts), 1)

    def test_active_order_is_stable_when_only_activity_timestamps_change(self):
        older_session = self.project("001", ProjectStatus.ACTIVE, 999)
        newer_session = self.project("002", ProjectStatus.ACTIVE, 1)
        view = reduce_dashboard([older_session, newer_session], QuotaState(), now=1000, last_success_at=1000)
        self.assertEqual([item.session_id for item in view.active_projects], ["002", "001"])

    def test_status_projects_keep_unread_terminal_tasks_after_alert_ttl(self):
        active = ProjectState("active", "Active", ProjectStatus.ACTIVE, 100, progress_current=2, progress_total=3)
        unread_done = ProjectState("done", "Done", ProjectStatus.DONE, 1, unread=True)
        unread_error = ProjectState("error", "Error", ProjectStatus.ERROR, 2, unread=True)
        view = reduce_dashboard(
            [unread_done, unread_error, active],
            QuotaState(),
            now=1000,
            last_success_at=1000,
            completion_ttl=60,
        )
        self.assertEqual([item.session_id for item in view.status_projects], ["active", "done", "error"])

    def test_status_projects_clear_unread_terminal_tasks_after_two_hours(self):
        done = ProjectState("done", "Done", ProjectStatus.DONE, 1, unread=True)
        error = ProjectState("error", "Error", ProjectStatus.ERROR, 1, unread=True)
        view = reduce_dashboard([done, error], QuotaState(), now=7202, last_success_at=7202)
        self.assertEqual(view.status_projects, ())

    def test_status_projects_exclude_acknowledged_error(self):
        error = self.project("error", ProjectStatus.ERROR, 999)
        view = reduce_dashboard([error], QuotaState(), now=1000, last_success_at=1000)
        self.assertEqual(view.status_projects, ())
        self.assertEqual(view.global_status, "IDLE")

    def test_expired_terminal_notification_cannot_keep_global_done_status(self):
        done = ProjectState("done", "Done", ProjectStatus.DONE, 1, unread=True)
        view = reduce_dashboard(
            [done],
            QuotaState(),
            now=7202,
            last_success_at=7202,
            completion_ttl=10000,
        )
        self.assertEqual(view.status_projects, ())
        self.assertEqual(view.global_status, "IDLE")


if __name__ == "__main__":
    unittest.main()
