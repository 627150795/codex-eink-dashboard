from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .models import QuotaState, QuotaWindow


def _number(value):
    if isinstance(value, (int, float)):
        return value
    return None


def _window(value: object) -> QuotaWindow | None:
    if not isinstance(value, dict):
        return None
    used = _number(value.get("usedPercent"))
    if used is None:
        used = _number(value.get("used_percent"))
    if used is None:
        return None
    resets = _number(value.get("resetsAt"))
    if resets is None:
        resets = _number(value.get("resets_at"))
    duration = _number(value.get("windowDurationMins"))
    if duration is None:
        duration = _number(value.get("window_duration_mins"))
    return QuotaWindow(float(used), float(resets) if resets is not None else None, int(duration) if duration is not None else None)


def parse_rate_limits(payload: object) -> QuotaState:
    if not isinstance(payload, dict):
        return QuotaState()
    bucket = payload.get("rateLimitsByLimitId", {}).get("codex") if isinstance(payload.get("rateLimitsByLimitId"), dict) else None
    if not isinstance(bucket, dict):
        bucket = payload.get("rateLimits") if isinstance(payload.get("rateLimits"), dict) else payload
    credits = bucket.get("credits")
    if isinstance(credits, dict):
        credits = _number(credits.get("balance") or credits.get("remaining"))
    return QuotaState(
        primary=_window(bucket.get("primary")),
        secondary=_window(bucket.get("secondary")),
        plan_type=bucket.get("planType") or bucket.get("plan_type") or payload.get("planType"),
        reached=bucket.get("rateLimitReachedType") or bucket.get("rate_limit_reached_type"),
        credits=float(credits) if isinstance(credits, (int, float)) else None,
    )


def quota_from_rate_limit_error(error: object) -> QuotaState | None:
    if not isinstance(error, dict):
        return None
    message = error.get("message")
    if not isinstance(message, str) or "chatgpt authentication required" not in message.casefold():
        return None
    return QuotaState(plan_type="api")


def find_codex_executable() -> str:
    explicit = os.environ.get("CODEX_CLI")
    if explicit and Path(explicit).exists():
        return explicit
    located = shutil.which("codex") or shutil.which("codex.exe")
    if located:
        return located
    candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin" / "codex.exe"
    if candidate.exists():
        return str(candidate)
    raise FileNotFoundError("Codex CLI was not found")


def read_live_quota(timeout: float = 10.0, executable: str | None = None) -> QuotaState:
    process = subprocess.Popen(
        [executable or find_codex_executable(), "app-server", "--listen", "stdio://"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    messages: queue.Queue[dict] = queue.Queue()

    def reader() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except json.JSONDecodeError:
                continue

    threading.Thread(target=reader, daemon=True).start()

    def send(message: dict) -> None:
        assert process.stdin is not None
        process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()

    deadline = time.monotonic() + timeout
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "codex-eink", "version": "0.1.0"}, "capabilities": {"experimentalApi": True, "requestAttestation": False}}})
        while time.monotonic() < deadline:
            try:
                message = messages.get(timeout=max(0.05, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise TimeoutError("Codex app-server initialize timed out") from exc
            if message.get("id") == 1:
                if message.get("error"):
                    raise RuntimeError(str(message["error"]))
                break
        send({"jsonrpc": "2.0", "method": "initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read"})
        while time.monotonic() < deadline:
            try:
                message = messages.get(timeout=max(0.05, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise TimeoutError("Codex rate-limit request timed out") from exc
            if message.get("id") == 2:
                if message.get("error"):
                    api_quota = quota_from_rate_limit_error(message["error"])
                    if api_quota is not None:
                        return api_quota
                    raise RuntimeError(str(message["error"]))
                return parse_rate_limits(message.get("result"))
        raise TimeoutError("Codex rate-limit request timed out")
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


def read_quota_fallback(session_root: str | Path, max_files: int = 40) -> QuotaState:
    root = Path(session_root)
    if not root.exists():
        return QuotaState()
    files = sorted(root.rglob("rollout-*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)[:max_files]
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = row.get("payload") or {}
            limits = payload.get("rate_limits") or row.get("rate_limits")
            if row.get("type") == "event_msg" and payload.get("type") == "token_count" and isinstance(limits, dict):
                parsed = parse_rate_limits(limits)
                if parsed.primary or parsed.secondary:
                    return parsed
    return QuotaState()
