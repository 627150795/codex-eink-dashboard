# Event-Driven E-Ink Refresh Implementation Plan

> **For the implementing agent:** Execute this plan inline, using TDD and preserving the user's existing uncommitted changes.

**Goal:** Refresh the e-ink dashboard promptly after a visible local Codex state change while showing only existing Codex thread titles.

**Architecture:** A small `events.py` module owns Windows file-system observation and exposes a coalesced `threading.Event`. The existing synchronous service loop waits for that event or its normal polling deadline, then reuses `_once()` and the existing frame-hash/BLE path. Session parsing uses the stored Codex title only; it never invents a title from prompt text, a directory, or an ID.

**Tech stack:** Python 3.11+, watchdog, existing Pillow/Bleak/pytest suite.

---

## File changes

- Create `src/codex_eink/events.py`: filtered Codex file watcher, event signalling, quiet-period coalescing, lifecycle ownership.
- Modify `src/codex_eink/cli.py`: start the watcher in `command_run`, run immediately on a coalesced event, retain active/idle timer fallback.
- Modify `src/codex_eink/config.py`: make the existing `coalesce_seconds` setting a validated short quiet period with a one-second default.
- Modify `src/codex_eink/sessions.py`: use stored thread titles or the fixed `未命名任务` label only.
- Modify `pyproject.toml`: add watchdog runtime dependency.
- Create `tests/test_events.py`: test filtering, coalescing, and event preservation without relying on Windows notifications, including exclusion of the self-written thread-state and activity databases.
- Modify `tests/test_sessions.py` and `tests/test_cli.py`: lock title-only fallback and event-triggered loop behaviour.
- Modify `README.md` and `ACCEPTANCE.md`: document event-driven refresh, fallback polling, and naming policy.

## Task 1: Lock title-only task names

**Files:**
- Modify `tests/test_sessions.py`
- Modify `src/codex_eink/sessions.py:193-202,224-300`

- [ ] Add failing tests for a stored Chinese/English Codex title being retained verbatim and a missing title becoming exactly `未命名任务`.
- [ ] Run `pytest tests/test_sessions.py -q`; expect the missing-title assertion to fail because the current code falls back to user text, CWD, or an ID.
- [ ] Replace `_fallback_title(title, user_text, cwd, session_id)` with a title-only helper returning `title or "未命名任务"`; remove parsing state made unnecessary by the old fallbacks.
- [ ] Run `pytest tests/test_sessions.py -q`; expect PASS.

## Task 2: Add a filtered, coalescing Codex watcher

**Files:**
- Create `tests/test_events.py`
- Create `src/codex_eink/events.py`
- Modify `pyproject.toml`

- [ ] Write failing unit tests around an injectable event signal: only session rollouts, `session_index.jsonl`, and `.codex-global-state.json` are relevant; `state_5.sqlite`/WAL and `logs_2.sqlite`/WAL are excluded because quota collection writes them; bursts reset the quiet deadline; a signal that arrives while processing remains observable afterwards.
- [ ] Run `pytest tests/test_events.py -q`; expect collection failure because the watcher module does not exist.
- [ ] Add `watchdog>=4.0` to project dependencies. Implement `CodexEventWatcher` with one `Observer`, a path filter, `signal()`, `wait(timeout)`, `wait_until_quiet(seconds)`, and deterministic `start()/stop()` methods. Schedule the Codex home directory recursively; filter events before signalling so unrelated Codex files do not trigger work.
- [ ] Install the added dependency into the existing project virtual environment and run `pytest tests/test_events.py -q`; expect PASS.

## Task 3: Replace sleep-only scheduling with event-or-timeout scheduling

**Files:**
- Modify `tests/test_cli.py`
- Modify `src/codex_eink/cli.py:216-237`
- Modify `src/codex_eink/config.py:16-42`

- [ ] Add a failing test for the runner's scheduling helper: a queued event runs before the active/idle fallback deadline; a quiet event is delayed only by `coalesce_seconds`; no event still uses the existing poll delay.
- [ ] Run `pytest tests/test_cli.py -q`; expect failure because the helper and watcher integration do not exist.
- [ ] Extract the loop's wait decision into a small testable helper. In `command_run`, create one watcher for the process lifetime, invoke `_once()` at startup, then wait for either a watcher signal or the computed fallback delay. Coalesce a signal for one second and immediately run `_once()`; do not force upload so the existing image digest remains the final screen-change gate.
- [ ] Validate `coalesce_seconds > 0` and set its default to `1.0`; keep the existing 30/60-second minimums because they are now fallback rather than the normal active-change path.
- [ ] Run `pytest tests/test_cli.py tests/test_events.py -q`; expect PASS.

## Task 4: Regression, live service verification, and documentation

**Files:**
- Modify `README.md`
- Modify `ACCEPTANCE.md`
- Modify `docs/superpowers/specs/2026-07-22-event-driven-refresh-design.md` only if test evidence changes an assertion

- [ ] Run the full test suite: `.venv\\Scripts\\python.exe -m pytest -q`.
- [ ] Run compile/dependency checks: `.venv\\Scripts\\python.exe -m compileall -q src` and `.venv\\Scripts\\python.exe -m pip check`.
- [ ] Restart only the `Codex E-Ink Dashboard` task so it loads the new watcher, then induce a harmless local visible-state fixture or observe the next real state-file change. Record the source-change timestamp and matching dashboard log timestamp; confirm no BLE upload occurs for an unchanged frame.
- [ ] Update README and acceptance documentation with the one-second coalescing interval, title-only naming, 30/60-second fallback, and measured verification evidence.

## Review checklist

- The only immediate triggers are visible task status/progress/unread changes and local quota-related Codex events; irrelevant file writes can only cause an unchanged local hash check.
- Events received during BLE work are not lost.
- The screen never uses user prompts, working directories, or IDs as generated task names.
- Existing content-first hash behaviour, device protocol, orientation, and account logic are unchanged.
