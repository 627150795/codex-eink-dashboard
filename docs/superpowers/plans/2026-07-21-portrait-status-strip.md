# Portrait Status Strip Implementation Plan

> **For AI agents:** Required sub-skill: use `executing-plans` to execute this plan inline. Track each step with `- [ ]`.

**Goal:** Replace the portrait bottom alert summary with compact, truthful per-thread progress, unread-completion, and failure markers.

**Architecture:** Extend `ProjectState` with optional progress and unread state. Parse the current-turn `update_plan` call from each rollout, merge unread thread IDs from Codex Desktop state in `collect_view`, and render at most four fixed-width bottom-strip tokens in portrait mode.

**Tech Stack:** Python 3.12, standard-library JSON, Pillow, `unittest`.

---

### Task 1: Capture plan progress, unread completion, and task-complete failures

**Files:**
- Modify: `src/codex_eink/models.py`
- Modify: `src/codex_eink/sessions.py`
- Modify: `tests/test_sessions.py`

- [x] **Step 1: Add failing session tests**

```python
def test_current_turn_plan_reports_in_progress_item(self):
    project = parse_rollout(path, {})
    self.assertEqual((project.progress_current, project.progress_total), (2, 3))

def test_task_complete_error_is_reported_as_failure(self):
    project = parse_rollout(path, {})
    self.assertEqual(project.status, ProjectStatus.ERROR)

def test_unread_thread_ids_reads_local_host_list(self):
    self.assertEqual(load_unread_thread_ids(path), {"done-thread"})
```

- [x] **Step 2: Run the session tests and observe failures**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -p test_sessions.py -v`

Expected: FAIL because progress fields and `load_unread_thread_ids` do not exist, and `task_complete.error` is not terminal.

- [x] **Step 3: Implement the minimum parsing behavior**

```python
@dataclass(frozen=True)
class ProjectState:
    # existing fields
    progress_current: int | None = None
    progress_total: int | None = None
    unread: bool = False
```

Parse the latest `response_item:function_call` named `update_plan` whose
metadata turn ID matches the newest `task_started`. Decode its JSON arguments,
find the first `in_progress` plan item, and return its one-based position and
the plan length. Read `unread-thread-ids-by-host-v1.local` from the supplied
state JSON. Treat a post-start `task_complete` with a nonempty `error` value as
`ProjectStatus.ERROR`.

- [x] **Step 4: Re-run the session tests**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -p test_sessions.py -v`

Expected: PASS.

### Task 2: Merge unread state into dashboard projects

**Files:**
- Modify: `src/codex_eink/cli.py`
- Modify: `tests/test_cli.py`

- [x] **Step 1: Add a failing unread-merge test**

```python
def test_completed_unread_thread_is_marked_for_the_status_strip(self):
    view = collect_view(AppConfig(codex_home=Path("C:/codex-test")), live_quota=False)
    self.assertTrue(view.alerts[0].unread)
```

- [x] **Step 2: Run the CLI tests and observe failure**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -p test_cli.py -v`

Expected: FAIL because `collect_view` does not load or merge the unread ID set.

- [x] **Step 3: Load and merge unread IDs**

```python
unread_ids = load_unread_thread_ids(codex_home / ".codex-global-state.json")
projects = [
    dataclasses.replace(project, unread=project.status == ProjectStatus.DONE and project.session_id in unread_ids)
    for project in projects
]
```

- [x] **Step 4: Re-run the CLI tests**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -p test_cli.py -v`

Expected: PASS.

### Task 3: Render the reusable portrait status strip

**Files:**
- Modify: `src/codex_eink/render.py`
- Modify: `tests/test_render.py`

- [x] **Step 1: Add a failing portrait rendering test**

```python
def test_portrait_status_strip_replaces_alert_text(self):
    logical = render_dashboard(view, (212, 104), orientation="portrait_cw").transpose(Image.Transpose.ROTATE_90)
    self.assertGreater(sum(pixel == 0 for pixel in logical.crop((0, 147, 104, 190)).get_flattened_data()), 20)
```

- [x] **Step 2: Run the renderer tests and observe failure**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -p test_render.py -v`

Expected: FAIL because the current layout renders `ALERT` text and completion summaries.

- [x] **Step 3: Implement fixed glyphs and status tokens**

```python
_STATUS_GLYPHS = {
    "running": ("0011100", "0111110", "1111111", "1111111", "1111111", "0111110", "0011100"),
    "done": ("0000001", "0000011", "0000110", "1101100", "0111000", "0010000", "0000000"),
    "error": ("1000001", "0100010", "0010100", "0001000", "0010100", "0100010", "1000001"),
}
```

Use a helper to draw one glyph from this table and another helper to return up
to four tokens: active progress or running glyph, unread done glyph, then
error glyph. Replace only the portrait `ALERT` section with its top rule and
these tokens.

- [x] **Step 4: Re-run renderer tests**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -p test_render.py -v`

Expected: PASS.

### Task 4: Verify and deploy

**Files:**
- Modify: `README.md`
- Modify: `ACCEPTANCE.md`

- [x] **Step 1: Run regression checks**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -v`

Expected: all tests pass.

- [x] **Step 2: Generate and inspect the portrait preview**

Run: `./.venv/Scripts/python.exe -m codex_eink --config config.json preview --output previews/status-strip-preview.png`

Expected: bottom strip contains compact tokens and no alert title, task title, or completion summary.

- [x] **Step 3: Stop only the dashboard task, force one 23-packet upload, then start the task**

Run: `./.venv/Scripts/python.exe -m codex_eink --config config.json once --force --preview previews/live.png`

Expected: `uploaded 23 packets`; the scheduled task returns to `Running`.
