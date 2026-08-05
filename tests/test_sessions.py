import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import codex_eink.sessions as sessions_module
from codex_eink.models import ProjectStatus
from codex_eink.sessions import (
    SessionSnapshotCache,
    TitleSnapshotCache,
    collect_projects,
    load_session_titles,
    load_state_titles,
    load_recent_thread_activity,
    load_unread_thread_ids,
    parse_rollout,
    reconcile_live_activity,
)


def row(timestamp, row_type, payload):
    return json.dumps(
        {"timestamp": timestamp, "type": row_type, "payload": payload},
        ensure_ascii=False,
    )


def write_rollout(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


class SessionCollectorTests(unittest.TestCase):
    def test_recent_thread_activity_keeps_latest_timestamp_per_thread(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "logs.sqlite"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE logs (thread_id TEXT, ts INTEGER)")
            connection.executemany(
                "INSERT INTO logs VALUES (?, ?)",
                [("thread-a", 90), ("thread-a", 110), ("thread-b", 105), (None, 120)],
            )
            connection.commit()
            connection.close()

            activity = load_recent_thread_activity(path, now=120, grace_seconds=20)

        self.assertEqual(activity, {"thread-a": 110.0, "thread-b": 105.0})

    def test_state_titles_bound_pathological_title_length(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE threads (id TEXT, title TEXT, thread_source TEXT)")
            connection.execute(
                "INSERT INTO threads VALUES (?, ?, ?)",
                ("long", "useful title " + "x" * 200_000, "user"),
            )
            connection.commit()
            connection.close()

            titles = load_state_titles(path)

        self.assertTrue(titles["long"].startswith("useful title "))
        self.assertEqual(len(titles["long"]), 240)

    def test_title_cache_skips_rollout_events_and_reads_incremental_state_updates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "session_index.jsonl").write_text(
                json.dumps({"id": "thread", "thread_name": "Index title", "updated_at": "2026-01-01T00:00:00Z"}),
                encoding="utf-8",
            )
            state_path = root / "state_5.sqlite"
            connection = sqlite3.connect(state_path)
            connection.execute(
                "CREATE TABLE threads (id TEXT, title TEXT, thread_source TEXT, updated_at INTEGER, updated_at_ms INTEGER)"
            )
            connection.execute("INSERT INTO threads VALUES (?, ?, ?, ?, ?)", ("thread", "State title", "user", 1, 1000))
            connection.commit()
            connection.close()
            cache = TitleSnapshotCache(root)

            self.assertEqual(cache.collect()["thread"], "State title")
            with patch(
                "codex_eink.sessions._load_state_title_updates",
                wraps=sessions_module._load_state_title_updates,
            ) as updates:
                self.assertEqual(cache.collect(changed_sources={"rollout"})["thread"], "State title")
                updates.assert_not_called()

                connection = sqlite3.connect(state_path)
                connection.execute("UPDATE threads SET title = ?, updated_at_ms = ? WHERE id = ?", ("New title", 2000, "thread"))
                connection.commit()
                connection.close()
                self.assertEqual(cache.collect(changed_sources={"state_db"})["thread"], "New title")
                updates.assert_called_once()

                connection = sqlite3.connect(state_path)
                connection.execute("UPDATE threads SET title = '', updated_at_ms = 3000 WHERE id = 'thread'")
                connection.commit()
                connection.close()
                self.assertEqual(cache.collect(changed_sources={"state_db"})["thread"], "Index title")

    def test_snapshot_cache_reparses_only_changed_rollout(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "sessions"
            path = root / "rollout-cached.jsonl"
            rows = [
                row("2026-07-20T00:00:00Z", "session_meta", {"id": "cached", "thread_source": "user"}),
                row("2026-07-20T00:00:01Z", "event_msg", {"type": "task_started", "turn_id": "turn-1"}),
            ]
            write_rollout(path, rows)
            cache = SessionSnapshotCache(root)

            with patch("codex_eink.sessions.parse_rollout", wraps=parse_rollout) as parse:
                first = cache.collect({"cached": "Old title"})
                unchanged = cache.collect({"cached": "New title"}, changed_paths=[])
                write_rollout(
                    path,
                    rows + [row("2026-07-20T00:00:02Z", "event_msg", {"type": "task_complete", "turn_id": "turn-1"})],
                )
                changed = cache.collect({"cached": "New title"}, changed_paths=[path])

            self.assertEqual(parse.call_count, 2)
            self.assertEqual(first[0].status, ProjectStatus.ACTIVE)
            self.assertEqual(unchanged[0].title, "New title")
            self.assertEqual(changed[0].status, ProjectStatus.DONE)

    def test_snapshot_cache_periodically_reconciles_missed_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "sessions"
            first_path = root / "rollout-first.jsonl"
            second_path = root / "rollout-second.jsonl"
            write_rollout(
                first_path,
                [row("2026-07-20T00:00:00Z", "session_meta", {"id": "first", "thread_source": "user"})],
            )
            clock = [0.0]
            cache = SessionSnapshotCache(root, reconcile_seconds=300, clock=lambda: clock[0])
            self.assertEqual([item.session_id for item in cache.collect({})], ["first"])

            write_rollout(
                second_path,
                [row("2026-07-20T00:00:01Z", "session_meta", {"id": "second", "thread_source": "user"})],
            )
            clock[0] = 299.0
            self.assertEqual([item.session_id for item in cache.collect({}, changed_paths=[])], ["first"])
            clock[0] = 301.0
            self.assertEqual(
                {item.session_id for item in cache.collect({}, changed_paths=[])},
                {"first", "second"},
            )

    def test_latest_started_turn_without_terminal_is_active(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rollout-active.jsonl"
            write_rollout(
                path,
                [
                    row("2026-07-20T00:00:00Z", "session_meta", {"id": "s1", "cwd": "C:/work/demo", "thread_source": "user"}),
                    row("2026-07-20T00:00:01Z", "event_msg", {"type": "task_started", "turn_id": "t1"}),
                    row("2026-07-20T00:00:02Z", "event_msg", {"type": "user_message", "message": "实现仪表盘"}),
                    row("2026-07-20T00:00:03Z", "response_item", {"type": "message", "role": "assistant", "phase": "commentary", "content": [{"type": "output_text", "text": "正在做"}]}),
                ],
            )
            project = parse_rollout(path, {"s1": "墨水屏监控"})
        self.assertEqual(project.status, ProjectStatus.ACTIVE)
        self.assertEqual(project.title, "墨水屏监控")

    def test_final_answer_after_latest_start_is_done_with_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rollout-done.jsonl"
            write_rollout(
                path,
                [
                    row("2026-07-20T00:00:00Z", "session_meta", {"id": "s2", "cwd": "C:/work/demo", "thread_source": "user"}),
                    row("2026-07-20T00:00:01Z", "event_msg", {"type": "task_started", "turn_id": "t2"}),
                    row("2026-07-20T00:00:05Z", "response_item", {"type": "message", "role": "assistant", "phase": "final_answer", "internal_chat_message_metadata_passthrough": {"turn_id": "t2"}, "content": [{"type": "output_text", "text": "已经完成并通过 12 项测试。\n详情略。"}]}),
                ],
            )
            project = parse_rollout(path, {})
        self.assertEqual(project.status, ProjectStatus.DONE)
        self.assertEqual(project.summary, "已经完成并通过 12 项测试。")
        self.assertEqual(project.terminal_id, "t2")

    def test_newer_start_supersedes_older_final_answer(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rollout-multi.jsonl"
            write_rollout(
                path,
                [
                    row("2026-07-20T00:00:00Z", "session_meta", {"id": "s3", "cwd": "C:/work/demo", "thread_source": "user"}),
                    row("2026-07-20T00:00:01Z", "event_msg", {"type": "task_started", "turn_id": "old"}),
                    row("2026-07-20T00:00:02Z", "response_item", {"type": "message", "role": "assistant", "phase": "final_answer", "content": [{"type": "output_text", "text": "旧任务完成"}]}),
                    row("2026-07-20T00:00:03Z", "event_msg", {"type": "task_started", "turn_id": "new"}),
                ],
            )
            project = parse_rollout(path, {})
        self.assertEqual(project.status, ProjectStatus.ACTIVE)
        self.assertEqual(project.turn_id, "new")

    def test_turn_aborted_is_stopped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rollout-stop.jsonl"
            write_rollout(
                path,
                [
                    row("2026-07-20T00:00:00Z", "session_meta", {"id": "s4", "cwd": "C:/work/demo", "thread_source": "user"}),
                    row("2026-07-20T00:00:01Z", "event_msg", {"type": "task_started", "turn_id": "t4"}),
                    row("2026-07-20T00:00:02Z", "event_msg", {"type": "turn_aborted", "turn_id": "t4", "reason": "interrupted"}),
                ],
            )
            project = parse_rollout(path, {})
        self.assertEqual(project.status, ProjectStatus.STOPPED)

    def test_current_turn_plan_reports_in_progress_item(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rollout-plan.jsonl"
            write_rollout(
                path,
                [
                    row("2026-07-20T00:00:00Z", "session_meta", {"id": "plan", "thread_source": "user"}),
                    row("2026-07-20T00:00:01Z", "event_msg", {"type": "task_started", "turn_id": "turn-1"}),
                    row(
                        "2026-07-20T00:00:02Z",
                        "response_item",
                        {
                            "type": "function_call",
                            "name": "update_plan",
                            "arguments": json.dumps(
                                {
                                    "plan": [
                                        {"status": "completed"},
                                        {"status": "in_progress"},
                                        {"status": "pending"},
                                    ]
                                }
                            ),
                            "internal_chat_message_metadata_passthrough": {"turn_id": "turn-1"},
                        },
                    ),
                ],
            )
            project = parse_rollout(path, {})
        self.assertEqual((project.progress_current, project.progress_total), (2, 3))

    def test_current_turn_plan_in_custom_exec_call_reports_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rollout-custom-plan.jsonl"
            write_rollout(
                path,
                [
                    row("2026-07-20T00:00:00Z", "session_meta", {"id": "custom-plan", "thread_source": "user"}),
                    row("2026-07-20T00:00:01Z", "event_msg", {"type": "task_started", "turn_id": "turn-1"}),
                    row(
                        "2026-07-20T00:00:02Z",
                        "response_item",
                        {
                            "type": "custom_tool_call",
                            "name": "exec",
                            "input": (
                                'const result = await tools.update_plan({explanation: "working", plan: ['
                                '{step: "inspect", status: "completed"}, '
                                '{step: "implement", status: "in_progress"}, '
                                '{step: "verify", status: "pending"}]});'
                            ),
                            "internal_chat_message_metadata_passthrough": {"turn_id": "turn-1"},
                        },
                    ),
                ],
            )
            project = parse_rollout(path, {})
        self.assertEqual((project.progress_current, project.progress_total), (2, 3))

    def test_task_complete_error_is_reported_as_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rollout-error.jsonl"
            write_rollout(
                path,
                [
                    row("2026-07-20T00:00:00Z", "session_meta", {"id": "error", "thread_source": "user"}),
                    row("2026-07-20T00:00:01Z", "event_msg", {"type": "task_started", "turn_id": "turn-1"}),
                    row(
                        "2026-07-20T00:00:02Z",
                        "event_msg",
                        {"type": "task_complete", "turn_id": "turn-1", "error": {"message": "connection lost"}},
                    ),
                ],
            )
            project = parse_rollout(path, {})
        self.assertEqual(project.status, ProjectStatus.ERROR)

    def test_task_complete_without_error_is_reported_as_done(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rollout-complete.jsonl"
            write_rollout(
                path,
                [
                    row("2026-07-20T00:00:00Z", "session_meta", {"id": "complete", "thread_source": "user"}),
                    row("2026-07-20T00:00:01Z", "event_msg", {"type": "task_started", "turn_id": "turn-1"}),
                    row("2026-07-20T00:00:02Z", "event_msg", {"type": "task_complete", "turn_id": "turn-1"}),
                ],
            )
            project = parse_rollout(path, {})
        self.assertEqual(project.status, ProjectStatus.DONE)

    def test_unread_thread_ids_reads_local_host_list(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            path.write_text(
                json.dumps({"electron-persisted-atom-state": {"unread-thread-ids-by-host-v1": {"local": ["done-thread"]}}}),
                encoding="utf-8",
            )
            unread = load_unread_thread_ids(path)
        self.assertEqual(unread, {"done-thread"})

    def test_subagents_are_excluded_and_month_directories_are_discovered(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "sessions"
            write_rollout(
                root / "2026" / "06" / "30" / "rollout-user.jsonl",
                [
                    row("2026-06-30T23:59:00Z", "session_meta", {"id": "user", "cwd": "C:/work/a", "thread_source": "user"}),
                    row("2026-06-30T23:59:01Z", "event_msg", {"type": "task_started", "turn_id": "u"}),
                ],
            )
            write_rollout(
                root / "2026" / "07" / "01" / "rollout-sub.jsonl",
                [row("2026-07-01T00:00:00Z", "session_meta", {"id": "sub", "cwd": "C:/work/a", "thread_source": "subagent"})],
            )
            projects = collect_projects(root, {})
        self.assertEqual([item.session_id for item in projects], ["user"])

    def test_latest_session_index_name_wins(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "session_index.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"id": "s", "thread_name": "旧名", "updated_at": "2026-01-01T00:00:00Z"}, ensure_ascii=False),
                        json.dumps({"id": "s", "thread_name": "新名", "updated_at": "2026-01-02T00:00:00Z"}, ensure_ascii=False),
                    ]
                ),
                encoding="utf-8",
            )
            titles = load_session_titles(path)
        self.assertEqual(titles["s"], "新名")

    def test_existing_codex_title_is_shown_verbatim(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rollout-title.jsonl"
            write_rollout(
                path,
                [
                    row("2026-07-20T00:00:00Z", "session_meta", {"id": "named", "cwd": "C:/work/demo", "thread_source": "user"}),
                    row("2026-07-20T00:00:01Z", "event_msg", {"type": "task_started", "turn_id": "turn-1"}),
                    row("2026-07-20T00:00:02Z", "event_msg", {"type": "user_message", "message": "generate an English replacement name"}),
                ],
            )
            project = parse_rollout(path, {"named": "目前的任务名称"})
        self.assertEqual(project.title, "目前的任务名称")

    def test_missing_codex_title_uses_fixed_unnamed_label(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rollout-untitled.jsonl"
            write_rollout(
                path,
                [
                    row("2026-07-20T00:00:00Z", "session_meta", {"id": "untitled", "cwd": "C:/work/english-folder", "thread_source": "user"}),
                    row("2026-07-20T00:00:01Z", "event_msg", {"type": "task_started", "turn_id": "turn-1"}),
                    row("2026-07-20T00:00:02Z", "event_msg", {"type": "user_message", "message": "generate an English replacement name"}),
                ],
            )
            project = parse_rollout(path, {})
        self.assertEqual(project.title, "未命名任务")

    def test_stale_unmatched_start_is_not_reported_as_running(self):
        from codex_eink.models import ProjectState

        active = ProjectState("live", "Live", ProjectStatus.ACTIVE, 990)
        stale = ProjectState("stale", "Stale", ProjectStatus.ACTIVE, 100)
        reconciled = reconcile_live_activity([active, stale], {"live"}, now=1000, grace_seconds=600)
        self.assertEqual(reconciled[0].status, ProjectStatus.ACTIVE)
        self.assertEqual(reconciled[1].status, ProjectStatus.IDLE)

    def test_live_thread_overrides_a_provisional_final_answer(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rollout-live.jsonl"
            write_rollout(
                path,
                [
                    row("2026-07-23T13:28:17Z", "session_meta", {"id": "live", "thread_source": "user"}),
                    row("2026-07-23T13:28:18Z", "event_msg", {"type": "task_started", "turn_id": "turn-1"}),
                    row(
                        "2026-07-23T13:28:19Z",
                        "response_item",
                        {
                            "type": "message",
                            "role": "assistant",
                            "phase": "final_answer",
                            "internal_chat_message_metadata_passthrough": {"turn_id": "turn-1"},
                            "content": [{"text": "provisional"}],
                        },
                    ),
                ],
            )
            project = parse_rollout(path, {})
        reconciled = reconcile_live_activity([project], {"live"}, now=1784813300)
        self.assertEqual(reconciled[0].status, ProjectStatus.ACTIVE)

    def test_stale_activity_does_not_reopen_final_answer(self):
        from codex_eink.models import ProjectState

        project = ProjectState(
            "done",
            "Done",
            ProjectStatus.DONE,
            100,
            summary="finished",
            terminal_id="turn-1",
            terminal_source="final_answer",
        )
        reconciled = reconcile_live_activity([project], {"done": 99}, now=200)
        self.assertEqual(reconciled[0].status, ProjectStatus.DONE)
        self.assertEqual(reconciled[0].summary, "finished")

    def test_newer_activity_reopens_final_answer(self):
        from codex_eink.models import ProjectState

        project = ProjectState(
            "done",
            "Done",
            ProjectStatus.DONE,
            100,
            summary="finished",
            terminal_id="turn-1",
            terminal_source="final_answer",
        )
        reconciled = reconcile_live_activity([project], {"done": 101}, now=200)
        self.assertEqual(reconciled[0].status, ProjectStatus.ACTIVE)
        self.assertEqual(reconciled[0].summary, "")

    def test_live_thread_does_not_override_task_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rollout-complete.jsonl"
            write_rollout(
                path,
                [
                    row("2026-07-23T13:28:17Z", "session_meta", {"id": "complete", "thread_source": "user"}),
                    row("2026-07-23T13:28:18Z", "event_msg", {"type": "task_started", "turn_id": "turn-1"}),
                    row("2026-07-23T13:28:19Z", "event_msg", {"type": "task_complete", "turn_id": "turn-1"}),
                ],
            )
            project = parse_rollout(path, {})
        reconciled = reconcile_live_activity([project], {"complete"}, now=1784813300)
        self.assertEqual(reconciled[0].status, ProjectStatus.DONE)


if __name__ == "__main__":
    unittest.main()
