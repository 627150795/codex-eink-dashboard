from dataclasses import replace
import time
import unittest

from PIL import Image

from codex_eink.models import DashboardView, ProjectState, ProjectStatus, QuotaState, QuotaWindow
from codex_eink.render import _overflow_rows, _portrait_reset_label, _portrait_status_tokens, render_dashboard


class RenderTests(unittest.TestCase):
    def sample_view(self):
        projects = tuple(
            ProjectState(
                session_id=str(i),
                title=f"项目 {i} mixed English 很长很长的名字 🚀",
                status=ProjectStatus.ACTIVE,
                updated_at=100 - i,
            )
            for i in range(10)
        )
        return DashboardView(
            global_status="RUN",
            active_projects=projects,
            alerts=(ProjectState("done", "完成的项目", ProjectStatus.DONE, 99, summary="测试通过"),),
            quota=QuotaState(
                primary=QuotaWindow(used_percent=62, resets_at=500),
                secondary=QuotaWindow(used_percent=26, resets_at=time.mktime((2026, 7, 21, 15, 30, 0, 0, 0, -1))),
            ),
            synced_at=100,
            fresh=True,
            battery_voltage=3.47,
        )

    def test_all_profiles_are_exact_and_binary(self):
        for size in ((212, 104), (250, 122), (296, 128), (400, 300)):
            with self.subTest(size=size):
                image = render_dashboard(self.sample_view(), size)
                self.assertEqual(image.size, size)
                self.assertTrue(set(image.convert("L").tobytes()).issubset({0, 255}))

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            render_dashboard(self.sample_view(), (320, 240))

    def test_render_does_not_mutate_view(self):
        view = self.sample_view()
        before = view.active_projects
        render_dashboard(view, (212, 104))
        self.assertEqual(view.active_projects, before)

    def test_portrait_uses_weekly_date_but_not_battery_or_time_of_day(self):
        view = self.sample_view()
        portrait = render_dashboard(view, (212, 104), orientation="portrait_cw")
        self.assertEqual(portrait.size, (212, 104))
        self.assertTrue(set(portrait.convert("L").tobytes()).issubset({0, 255}))

        changed_voltage = render_dashboard(replace(view, battery_voltage=3.9), (212, 104), orientation="portrait_cw")
        self.assertEqual(portrait.tobytes(), changed_voltage.tobytes())

        changed_short_window = replace(
            view,
            synced_at=9999,
            quota=replace(view.quota, primary=replace(view.quota.primary, resets_at=9999)),
        )
        self.assertEqual(
            portrait.tobytes(),
            render_dashboard(changed_short_window, (212, 104), orientation="portrait_cw").tobytes(),
        )

        changed_weekly_time = replace(
            view,
            quota=replace(view.quota, secondary=replace(view.quota.secondary, resets_at=time.mktime((2026, 7, 21, 23, 30, 0, 0, 0, -1)))),
        )
        self.assertEqual(
            portrait.tobytes(),
            render_dashboard(changed_weekly_time, (212, 104), orientation="portrait_cw").tobytes(),
        )

        changed_weekly_date = replace(
            view,
            quota=replace(view.quota, secondary=replace(view.quota.secondary, resets_at=time.mktime((2026, 7, 22, 15, 30, 0, 0, 0, -1)))),
        )
        self.assertNotEqual(
            portrait.tobytes(),
            render_dashboard(changed_weekly_date, (212, 104), orientation="portrait_cw").tobytes(),
        )

    def test_portrait_reset_label_uses_weekly_window_or_api(self):
        reset_at = time.mktime((2026, 7, 21, 15, 30, 0, 0, 0, -1))
        quota = QuotaState(
            primary=QuotaWindow(used_percent=20, resets_at=1000, window_duration_mins=300),
            secondary=QuotaWindow(used_percent=30, resets_at=reset_at, window_duration_mins=10080),
            plan_type="plus",
        )
        self.assertEqual(_portrait_reset_label(quota), "7.21")
        self.assertEqual(_portrait_reset_label(replace(quota, plan_type="api")), "API")

    def test_portrait_reset_label_falls_back_to_primary_when_the_weekly_window_is_primary(self):
        reset_at = time.mktime((2026, 7, 26, 21, 44, 0, 0, 0, -1))
        quota = QuotaState(primary=QuotaWindow(used_percent=100, resets_at=reset_at), plan_type="plus")
        self.assertEqual(_portrait_reset_label(quota), "7.26")

    def test_portrait_api_hides_quota_and_moves_tasks_upward(self):
        view = self.sample_view()
        normal = render_dashboard(view, (212, 104), orientation="portrait_cw").transpose(Image.Transpose.ROTATE_90)
        api_view = replace(view, quota=replace(view.quota, plan_type="api"))
        api = render_dashboard(api_view, (212, 104), orientation="portrait_cw").transpose(Image.Transpose.ROTATE_90)

        self.assertEqual(normal.crop((0, 53, 104, 143)).tobytes(), api.crop((0, 24, 104, 114)).tobytes())

    def test_portrait_status_strip_uses_progress_and_fixed_icons(self):
        status_projects = (
            ProjectState("active", "Active", ProjectStatus.ACTIVE, 100, progress_current=2, progress_total=3),
            ProjectState("running", "Running", ProjectStatus.ACTIVE, 99),
            ProjectState("done", "Done", ProjectStatus.DONE, 98, unread=True),
            ProjectState("error", "Error", ProjectStatus.ERROR, 97),
            ProjectState("active-2", "Active 2", ProjectStatus.ACTIVE, 96, progress_current=4, progress_total=6),
            ProjectState("running-2", "Running 2", ProjectStatus.ACTIVE, 95),
            ProjectState("done-2", "Done 2", ProjectStatus.DONE, 94, unread=True),
            ProjectState("error-2", "Error 2", ProjectStatus.ERROR, 93),
            ProjectState("ignored", "Ignored", ProjectStatus.ACTIVE, 92),
        )
        view = replace(self.sample_view(), status_projects=status_projects)
        self.assertEqual(
            _portrait_status_tokens(view),
            ("2/3", "running", "done", "error", "4/6", "running", "done", "error"),
        )

        logical = render_dashboard(view, (212, 104), orientation="portrait_cw").transpose(Image.Transpose.ROTATE_90)
        self.assertGreater(sum(pixel == 0 for pixel in logical.crop((0, 160, 104, 184)).get_flattened_data()), 0)
        self.assertGreater(sum(pixel == 0 for pixel in logical.crop((0, 184, 104, 208)).get_flattened_data()), 0)
        text_bbox = logical.crop((0, 160, 26, 184)).convert("L").point(lambda pixel: 255 - pixel).getbbox()
        icon_bbox = logical.crop((26, 160, 52, 184)).convert("L").point(lambda pixel: 255 - pixel).getbbox()
        self.assertLessEqual(abs(text_bbox[1] - icon_bbox[1]), 1)
        self.assertGreaterEqual(160 + text_bbox[1], 168)

        blank = replace(view, status_projects=(), alerts=())
        logical = render_dashboard(blank, (212, 104), orientation="portrait_cw").transpose(Image.Transpose.ROTATE_90)
        self.assertEqual(set(logical.crop((0, 160, 104, 212)).get_flattened_data()), {1})

    def test_portrait_task_rows_use_six_slots_and_ellipsis(self):
        rows = _overflow_rows(self.sample_view().active_projects, 6, overflow_label="...")
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[-1], (">", "..."))

    def test_portrait_status_strip_omits_alert_summary(self):
        physical = render_dashboard(self.sample_view(), (212, 104), orientation="portrait_cw")
        logical = physical.transpose(Image.Transpose.ROTATE_90)
        summary_ink = sum(pixel == 0 for pixel in logical.crop((0, 160, 104, 212)).get_flattened_data())
        self.assertEqual(summary_ink, 0)


if __name__ == "__main__":
    unittest.main()
