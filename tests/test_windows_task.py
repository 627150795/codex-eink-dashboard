from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WindowsTaskScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.installer = (PROJECT_ROOT / "install-task.ps1").read_text(encoding="utf-8")
        cls.runner = (PROJECT_ROOT / "run-background.ps1").read_text(encoding="utf-8")

    def test_task_is_allowed_to_run_on_battery(self) -> None:
        self.assertIn("-AllowStartIfOnBatteries", self.installer)
        self.assertIn("-DontStopIfGoingOnBatteries", self.installer)

    def test_task_has_one_minute_watchdog_trigger(self) -> None:
        self.assertIn("$watchdogTrigger", self.installer)
        self.assertIn("-RepetitionInterval (New-TimeSpan -Minutes 1)", self.installer)
        self.assertIn("-Trigger $logonTrigger, $watchdogTrigger", self.installer)

    def test_runner_invokes_venv_python_directly(self) -> None:
        self.assertIn(".venv\\Scripts\\python.exe", self.runner)
        self.assertNotIn("start.ps1", self.runner)

    def test_runner_records_process_lifecycle(self) -> None:
        self.assertIn("service-start", self.runner)
        self.assertIn("service-exit", self.runner)

    def test_runner_loads_the_deployed_dashboard_config(self) -> None:
        self.assertIn("$configPath", self.runner)
        self.assertIn("--config $configPath", self.runner)


if __name__ == "__main__":
    unittest.main()
