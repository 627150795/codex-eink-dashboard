import unittest

from codex_eink.models import ProjectState, ProjectStatus
from codex_eink.notifications import apply_terminal_notification_state


class TerminalNotificationTests(unittest.TestCase):
    def test_unread_state_is_limited_to_current_terminal_notifications(self):
        projects = [
            ProjectState("fresh", "Fresh", ProjectStatus.DONE, 7199),
            ProjectState("expired", "Expired", ProjectStatus.ERROR, 0),
            ProjectState("active", "Active", ProjectStatus.ACTIVE, 7199),
        ]

        updated = apply_terminal_notification_state(projects, {"fresh", "expired", "active"}, now=7200)

        self.assertEqual(
            [(project.session_id, project.unread) for project in updated],
            [("fresh", True), ("expired", False), ("active", False)],
        )


if __name__ == "__main__":
    unittest.main()
