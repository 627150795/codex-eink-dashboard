# Portrait Dashboard Implementation Plan

> **For AI agents:** Execute this plan with TDD: write each test first, run it
> to observe the expected failure, then implement only the behavior it covers.

**Goal:** Add a selectable portrait dashboard with device-voltage display and
30/60-second monitoring while retaining the landscape layout.

**Architecture:** Keep the BLE protocol and physical resolution unchanged.
Render a portrait logical canvas, rotate it into the existing physical frame,
and include the status-packet voltage in `DashboardView` before hashing.

### Task 1: Configuration and rendering

**Files:**
- Modify: `src/codex_eink/models.py`
- Modify: `src/codex_eink/config.py`
- Modify: `src/codex_eink/render.py`
- Test: `tests/test_models.py`
- Test: `tests/test_render.py`

- [ ] Add tests for the landscape default, 30/60-second limits, portrait
  rendering, voltage-dependent pixels, and time-independent portrait pixels.
- [ ] Run the new tests and observe failure.
- [ ] Add the minimum configuration, model field, and portrait renderer.
- [ ] Re-run the new tests.

### Task 2: Data flow and deployment configuration

**Files:**
- Modify: `src/codex_eink/cli.py`
- Modify: `run-background.ps1`
- Modify: `config.example.json`
- Create: `config.json`
- Test: `tests/test_windows_task.py`

- [ ] Add a test requiring the background runner to load `config.json`.
- [ ] Run it and observe failure.
- [ ] Probe the existing status path before rendering and pass voltage to the
  view; select portrait and 30/60 seconds in `config.json`.
- [ ] Re-run the new test and the complete suite.

### Task 3: Live verification

**Files:**
- Modify: `README.md`
- Modify: `ACCEPTANCE.md`

- [ ] Generate and inspect the portrait preview.
- [ ] Restart only `Codex E-Ink Dashboard`, force one upload, and verify its
  log records a successful 23-packet transmission.
- [ ] Run the full test suite, bytecode compilation, dependency check, and
  confirm the scheduled task remains running.
