# API Account Detection Implementation Plan

> **For AI agents:** Required sub-skill: use `executing-plans` to execute this plan inline. Track each step with `- [ ]`.

**Goal:** Show `API` in the portrait header only when Codex explicitly reports that ChatGPT quota access is unavailable because the account uses API authentication.

**Architecture:** Convert the explicit JSON-RPC error from `account/rateLimits/read` into `QuotaState(plan_type="api")`. Preserve that known state in `collect_view()` instead of replacing it with historical session quota data. The renderer continues to map `plan_type="api"` to the existing `API` label.

**Tech Stack:** Python 3.11, standard-library `unittest`, existing Codex app-server JSON-RPC reader.

---

### Task 1: Recognize only the explicit API authentication response

**Files:**
- Modify: `tests/test_quota.py`
- Modify: `src/codex_eink/quota.py`

- [ ] **Step 1: Add failing classifier tests**

```python
from codex_eink.quota import parse_rate_limits, quota_from_rate_limit_error

def test_api_authentication_error_produces_api_plan(self):
    quota = quota_from_rate_limit_error(
        {"code": -32600, "message": "chatgpt authentication required to read rate limits"}
    )
    self.assertEqual(quota.plan_type, "api")

def test_unrelated_rate_limit_error_remains_unknown(self):
    self.assertIsNone(quota_from_rate_limit_error({"code": -32600, "message": "invalid request"}))
```

- [ ] **Step 2: Run the classifier tests and observe failure**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -p test_quota.py -v`

Expected: test collection fails because `quota_from_rate_limit_error` does not exist.

- [ ] **Step 3: Implement the minimum classifier and use it for JSON-RPC errors**

```python
def quota_from_rate_limit_error(error: object) -> QuotaState | None:
    if not isinstance(error, dict):
        return None
    message = error.get("message")
    if not isinstance(message, str) or "chatgpt authentication required" not in message.casefold():
        return None
    return QuotaState(plan_type="api")
```

At the `message.get("id") == 2` error branch, return this value when it is not `None`; retain the existing exception for all other errors.

- [ ] **Step 4: Re-run the classifier tests**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -p test_quota.py -v`

Expected: both classifier tests pass.

### Task 2: Keep verified API state out of the historical fallback

**Files:**
- Create: `tests/test_cli.py`
- Modify: `src/codex_eink/cli.py`

- [ ] **Step 1: Add a failing API fallback test**

```python
from pathlib import Path
from unittest.mock import patch

from codex_eink.cli import collect_view
from codex_eink.config import AppConfig
from codex_eink.models import QuotaState

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
```

- [ ] **Step 2: Run the fallback test and observe failure**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -p test_cli.py -v`

Expected: FAIL with `AssertionError: fallback used`.

- [ ] **Step 3: Guard the fallback in `collect_view()`**

```python
if (
    quota.primary is None
    and quota.secondary is None
    and (quota.plan_type or "").casefold() != "api"
):
    quota = read_quota_fallback(codex_home / "sessions")
```

- [ ] **Step 4: Re-run the fallback test**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -p test_cli.py -v`

Expected: PASS.

### Task 3: Persist the verified API account mode for background refreshes

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/codex_eink/config.py`
- Modify: `src/codex_eink/cli.py`
- Modify: `config.json`

- [ ] **Step 1: Add a failing configured-API test**

```python
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
```

- [ ] **Step 2: Run the configured-API test and observe failure**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -p test_cli.py -v`

Expected: FAIL because `AppConfig` has no `account_mode` setting.

- [ ] **Step 3: Add the `auto`/`api` account setting and bypass quota collection in API mode**

```python
account_mode: str = "auto"

if self.account_mode not in {"auto", "api"}:
    raise ValueError("account_mode must be 'auto' or 'api'")
```

```python
quota = QuotaState(plan_type="api") if config.account_mode == "api" else QuotaState()
if live_quota and config.account_mode != "api":
    # existing live rate-limit read
```

Set `"account_mode": "api"` in the deployed `config.json`.

- [ ] **Step 4: Re-run the configured-API test**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -p test_cli.py -v`

Expected: both API tests pass.

### Task 4: Document and verify the visible result

**Files:**
- Modify: `README.md`
- Modify: `ACCEPTANCE.md`

- [ ] **Step 1: Correct the portrait quota-source documentation**

Replace the statement that a missing secondary window falls back to the primary window with: only a secondary weekly window displays `M.D`; the explicit API authentication response displays `API`; otherwise the header displays `--.--`.

- [ ] **Step 2: Run regression checks**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -v`

Expected: all tests pass.

- [ ] **Step 3: Restart only the dashboard task and let it apply the changed frame**

Run: `Stop-ScheduledTask -TaskName 'Codex E-Ink Dashboard'`, then `Start-ScheduledTask -TaskName 'Codex E-Ink Dashboard'`.

Expected: the restarted task renders `previews/live.png` with the `API` header and records `uploaded 23 packets` in `logs/dashboard.log`; no concurrent manual BLE upload is started.

- [ ] **Step 4: Confirm the scheduled task is still running**

Run: `Get-ScheduledTask -TaskName 'Codex E-Ink Dashboard' | Select-Object TaskName,State`

Expected: `State` is `Running`.
