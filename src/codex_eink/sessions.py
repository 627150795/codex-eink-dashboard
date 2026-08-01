from __future__ import annotations

import json
import os
import re
import sqlite3
import dataclasses
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .models import ProjectState, ProjectStatus


_SPACE = re.compile(r"\s+")
_PLAN_STATUS = re.compile(r"(?:[\"']status[\"']|status)\s*:\s*[\"'](completed|in_progress|pending)[\"']")
_MAX_TEXT_SCAN_CHARS = 4096
_MAX_TITLE_SCAN_CHARS = 1024


def _epoch(value: str | None, fallback: float = 0.0) -> float:
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return fallback


def _clean_text(value: object, limit: int = 240) -> str:
    if not isinstance(value, str):
        return ""
    value = value[: max(limit, _MAX_TEXT_SCAN_CHARS)]
    value = "".join(ch if ch >= " " else " " for ch in value)
    return _SPACE.sub(" ", value).strip()[:limit]


def _summary_text(content: object) -> str:
    if not isinstance(content, list):
        return _clean_text(content)
    for item in content:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        for line in item["text"].splitlines():
            candidate = _clean_text(line)
            if candidate:
                return candidate
    return ""


def load_session_titles(path: str | Path) -> dict[str, str]:
    latest: dict[str, tuple[str, str]] = {}
    try:
        lines = Path(path).read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return {}
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        session_id = row.get("id")
        title = _clean_text(row.get("thread_name"))
        updated = str(row.get("updated_at") or "")
        if session_id and title and updated >= latest.get(session_id, ("", ""))[0]:
            latest[session_id] = (updated, title)
    return {session_id: value[1] for session_id, value in latest.items()}


def load_state_titles(path: str | Path) -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
        try:
            rows = connection.execute(
                "SELECT id, substr(title, 1, ?) FROM threads "
                "WHERE title <> '' AND COALESCE(thread_source, 'user') <> 'subagent'",
                (_MAX_TITLE_SCAN_CHARS,),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return {}
    return {str(session_id): _clean_text(title) for session_id, title in rows if _clean_text(title)}


def _state_title_cursor(path: str | Path) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
        try:
            row = connection.execute(
                "SELECT COALESCE(MAX(COALESCE(updated_at_ms, updated_at * 1000)), 0) FROM threads"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return 0
    return int(row[0] or 0) if row else 0


def _load_state_title_updates(path: str | Path, since_ms: int) -> tuple[dict[str, str | None], int] | None:
    path = Path(path)
    if not path.exists():
        return {}, since_ms
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
        try:
            rows = connection.execute(
                "SELECT id, substr(title, 1, ?), COALESCE(thread_source, 'user'), "
                "COALESCE(updated_at_ms, updated_at * 1000, 0) FROM threads "
                "WHERE COALESCE(updated_at_ms, updated_at * 1000, 0) >= ?",
                (_MAX_TITLE_SCAN_CHARS, since_ms),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return None

    updates: dict[str, str | None] = {}
    cursor = since_ms
    for session_id, title, thread_source, updated_at_ms in rows:
        cursor = max(cursor, int(updated_at_ms or 0))
        cleaned = _clean_text(title)
        updates[str(session_id)] = cleaned if cleaned and str(thread_source).casefold() != "subagent" else None
    return updates, cursor


class TitleSnapshotCache:
    """Cache thread titles and query only rows changed since the last state event."""

    def __init__(
        self,
        codex_home: str | Path,
        *,
        reconcile_seconds: float = 300.0,
        clock=time.monotonic,
    ) -> None:
        self.codex_home = Path(codex_home)
        self.reconcile_seconds = reconcile_seconds
        self._clock = clock
        self._session_titles: dict[str, str] = {}
        self._state_titles: dict[str, str] = {}
        self._state_cursor_ms = 0
        self._initialized = False
        self._last_reconcile_at = 0.0

    def collect(self, *, changed_sources: Iterable[str] | None = None) -> dict[str, str]:
        now = self._clock()
        sources = frozenset(changed_sources or ())
        full_reconcile = (
            not self._initialized
            or changed_sources is None
            or now - self._last_reconcile_at >= self.reconcile_seconds
            or "unknown" in sources
        )
        state_path = self.codex_home / "state_5.sqlite"

        if full_reconcile:
            self._session_titles = load_session_titles(self.codex_home / "session_index.jsonl")
            self._state_titles = load_state_titles(state_path)
            self._state_cursor_ms = _state_title_cursor(state_path)
            self._initialized = True
            self._last_reconcile_at = now
        else:
            if "session_index" in sources:
                self._session_titles = load_session_titles(self.codex_home / "session_index.jsonl")
            if "state_db" in sources:
                result = _load_state_title_updates(state_path, self._state_cursor_ms)
                if result is None:
                    self._state_titles = load_state_titles(state_path)
                    self._state_cursor_ms = _state_title_cursor(state_path)
                else:
                    updates, self._state_cursor_ms = result
                    for session_id, title in updates.items():
                        if title is None:
                            self._state_titles.pop(session_id, None)
                        else:
                            self._state_titles[session_id] = title

        titles = dict(self._session_titles)
        titles.update(self._state_titles)
        return titles


def load_unread_thread_ids(path: str | Path) -> set[str]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return set()
    state = payload.get("electron-persisted-atom-state")
    if not isinstance(state, dict):
        return set()
    hosts = state.get("unread-thread-ids-by-host-v1")
    if not isinstance(hosts, dict):
        return set()
    local = hosts.get("local")
    if not isinstance(local, list):
        return set()
    return {item for item in local if isinstance(item, str)}


def load_recent_thread_ids(path: str | Path, *, now: float | None = None, grace_seconds: int = 600) -> set[str] | None:
    path = Path(path)
    if not path.exists():
        return None
    cutoff = int(now if now is not None else time.time()) - grace_seconds
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
        try:
            rows = connection.execute(
                "SELECT DISTINCT thread_id FROM logs WHERE thread_id IS NOT NULL AND ts >= ?",
                (cutoff,),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    return {str(row[0]) for row in rows if row[0]}


def reconcile_live_activity(
    projects: list[ProjectState],
    live_thread_ids: set[str] | None,
    *,
    now: float,
    grace_seconds: int = 600,
) -> list[ProjectState]:
    if live_thread_ids is None:
        return projects
    output = []
    for project in projects:
        if project.status == ProjectStatus.DONE and project.terminal_source == "final_answer" and project.session_id in live_thread_ids:
            output.append(
                dataclasses.replace(
                    project,
                    status=ProjectStatus.ACTIVE,
                    summary="",
                    terminal_id="",
                    terminal_source="",
                )
            )
        elif (
            project.status == ProjectStatus.ACTIVE
            and project.session_id not in live_thread_ids
            and now - project.updated_at > grace_seconds
        ):
            output.append(dataclasses.replace(project, status=ProjectStatus.IDLE))
        else:
            output.append(project)
    return output


def _bounded_rollout_rows(path: Path, chunk_size: int = 1024 * 1024, max_tail_bytes: int = 64 * 1024 * 1024) -> list[dict]:
    """Read session metadata plus enough tail to contain the newest task start."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            head = handle.readline(512 * 1024)
            if size <= chunk_size * 2:
                handle.seek(0)
                data = handle.read()
            else:
                collected = b""
                position = size
                while position > 0 and len(collected) < max_tail_bytes:
                    take = min(chunk_size, position)
                    position -= take
                    handle.seek(position)
                    collected = handle.read(take) + collected
                    if b'"task_started"' in collected:
                        break
                data = head + b"\n" + collected
    except OSError:
        return []
    rows = []
    seen = set()
    for raw_line in data.decode("utf-8", errors="replace").splitlines():
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        marker = (row.get("timestamp"), row.get("type"), str(row.get("payload", {}).get("id") or row.get("payload", {}).get("turn_id") or ""))
        if marker in seen:
            continue
        seen.add(marker)
        rows.append(row)
    return rows


def _display_title(title: str) -> str:
    return title or "未命名任务"


def _plan_progress(payload: dict, turn_id: str) -> tuple[int, int] | None:
    metadata = payload.get("internal_chat_message_metadata_passthrough")
    metadata_turn_id = str(metadata.get("turn_id") or "") if isinstance(metadata, dict) else ""
    if metadata_turn_id and metadata_turn_id != turn_id:
        return None
    try:
        arguments = json.loads(payload.get("arguments") or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    plan = arguments.get("plan") if isinstance(arguments, dict) else None
    if not isinstance(plan, list) or not plan:
        return None
    return _progress_from_plan(plan)


def _progress_from_plan(plan: list[dict]) -> tuple[int, int] | None:
    if not plan:
        return None
    current = next((index + 1 for index, item in enumerate(plan) if item.get("status") == "in_progress"), None)
    if current is None:
        completed = sum(item.get("status") == "completed" for item in plan)
        current = min(len(plan), max(1, completed + 1))
    return current, len(plan)


def _custom_plan_progress(payload: dict, turn_id: str) -> tuple[int, int] | None:
    metadata = payload.get("internal_chat_message_metadata_passthrough")
    metadata_turn_id = str(metadata.get("turn_id") or "") if isinstance(metadata, dict) else ""
    if metadata_turn_id and metadata_turn_id != turn_id:
        return None
    source = payload.get("input")
    if not isinstance(source, str):
        return None
    update_plan_at = source.find("tools.update_plan")
    if update_plan_at < 0:
        return None
    plan_start = re.search(r"\bplan\s*:\s*\[", source[update_plan_at:])
    if plan_start is None:
        return None
    start = update_plan_at + plan_start.end() - 1
    depth = 0
    quote = ""
    escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {"'", '"', "`"}:
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                statuses = _PLAN_STATUS.findall(source[start : index + 1])
                return _progress_from_plan([{"status": status} for status in statuses])
    return None


def parse_rollout(path: str | Path, titles: dict[str, str]) -> ProjectState | None:
    path = Path(path)
    rows = _bounded_rollout_rows(path)
    if not rows:
        return None

    meta = next((row.get("payload", {}) for row in rows if row.get("type") == "session_meta"), {})
    if str(meta.get("thread_source", "user")).lower() in {"subagent", "sub_agent"}:
        return None
    session_id = str(meta.get("id") or meta.get("session_id") or "")
    if not session_id:
        match = re.search(r"([0-9a-f]{8}-[0-9a-f-]{27,})", path.name, re.I)
        session_id = match.group(1) if match else path.stem
    cwd = str(meta.get("cwd") or "")

    last_start = -1
    turn_id = ""
    for index, row in enumerate(rows):
        payload = row.get("payload") or {}
        if row.get("type") == "event_msg" and payload.get("type") == "task_started":
            last_start = index
            turn_id = str(payload.get("turn_id") or "")

    terminal: tuple[int, ProjectStatus, str, str, str] | None = None
    progress_current: int | None = None
    progress_total: int | None = None
    for index, row in enumerate(rows):
        if index <= last_start:
            continue
        payload = row.get("payload") or {}
        payload_type = str(payload.get("type") or "")
        if row.get("type") == "response_item" and payload_type == "function_call" and payload.get("name") == "update_plan":
            progress = _plan_progress(payload, turn_id)
            if progress is not None:
                progress_current, progress_total = progress
        elif row.get("type") == "response_item" and payload_type == "custom_tool_call" and payload.get("name") == "exec":
            progress = _custom_plan_progress(payload, turn_id)
            if progress is not None:
                progress_current, progress_total = progress
        elif row.get("type") == "response_item" and payload_type == "message" and payload.get("role") == "assistant" and payload.get("phase") == "final_answer":
            metadata = payload.get("internal_chat_message_metadata_passthrough") or {}
            terminal_turn = str(metadata.get("turn_id") or turn_id)
            terminal = (index, ProjectStatus.DONE, terminal_turn, _summary_text(payload.get("content")), "final_answer")
        elif row.get("type") == "event_msg" and payload_type == "turn_aborted":
            terminal = (index, ProjectStatus.STOPPED, str(payload.get("turn_id") or turn_id), _clean_text(payload.get("reason")), "turn_aborted")
        elif row.get("type") == "event_msg" and payload_type == "task_complete":
            error = payload.get("error")
            message = error.get("message") if isinstance(error, dict) else error
            status = ProjectStatus.ERROR if error else ProjectStatus.DONE
            summary = _clean_text(message or payload.get("last_agent_message"))
            terminal = (index, status, str(payload.get("turn_id") or turn_id), summary, "task_complete")
        elif payload_type in {"task_failed", "turn_failed", "stream_error", "system_error"} or row.get("type") == "error":
            terminal = (
                index,
                ProjectStatus.ERROR,
                str(payload.get("turn_id") or turn_id),
                _clean_text(payload.get("message") or payload.get("error")),
                "error",
            )

    if last_start < 0:
        status = terminal[1] if terminal else ProjectStatus.IDLE
    else:
        status = terminal[1] if terminal else ProjectStatus.ACTIVE
    summary = terminal[3] if terminal else ""
    terminal_id = terminal[2] if terminal else ""
    terminal_source = terminal[4] if terminal else ""
    updated_at = max((_epoch(row.get("timestamp")) for row in rows), default=path.stat().st_mtime)
    title = _display_title(titles.get(session_id, ""))
    return ProjectState(
        session_id=session_id,
        title=title,
        status=status,
        updated_at=updated_at,
        summary=summary,
        cwd=cwd,
        turn_id=turn_id,
        terminal_id=terminal_id,
        terminal_source=terminal_source,
        progress_current=progress_current,
        progress_total=progress_total,
    )


def discover_rollouts(root: str | Path, max_files: int = 120) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    files = list(root.rglob("rollout-*.jsonl"))
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return files[:max_files]


def collect_projects(root: str | Path, titles: dict[str, str], max_files: int = 120) -> list[ProjectState]:
    projects = []
    for path in discover_rollouts(root, max_files=max_files):
        project = parse_rollout(path, titles)
        if project is not None:
            projects.append(project)
    projects.sort(key=lambda item: item.updated_at, reverse=True)
    return projects


@dataclasses.dataclass(frozen=True)
class _RolloutCacheEntry:
    fingerprint: tuple[int, int]
    project: ProjectState | None


class SessionSnapshotCache:
    """Keep parsed rollout state in memory and reparse only changed files."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_files: int = 120,
        reconcile_seconds: float = 300.0,
        clock=time.monotonic,
    ) -> None:
        self.root = Path(root)
        self.max_files = max_files
        self.reconcile_seconds = reconcile_seconds
        self._clock = clock
        self._entries: dict[str, _RolloutCacheEntry] = {}
        self._initialized = False
        self._last_reconcile_at = 0.0

    @staticmethod
    def _key(path: str | Path) -> str:
        return os.path.normcase(os.path.abspath(path))

    @staticmethod
    def _fingerprint(path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    @staticmethod
    def _is_rollout(path: Path) -> bool:
        return path.suffix.casefold() == ".jsonl" and path.name.casefold().startswith("rollout-")

    def collect(
        self,
        titles: dict[str, str],
        *,
        changed_paths: Iterable[str | Path] | None = None,
        force_reconcile: bool = False,
    ) -> list[ProjectState]:
        now = self._clock()
        reconcile_due = self._initialized and now - self._last_reconcile_at >= self.reconcile_seconds
        full_reconcile = not self._initialized or force_reconcile or changed_paths is None or reconcile_due

        if full_reconcile:
            targets = discover_rollouts(self.root, max_files=self.max_files)
            live_keys = {self._key(path) for path in targets}
            for key in tuple(self._entries):
                if key not in live_keys:
                    del self._entries[key]
            self._initialized = True
            self._last_reconcile_at = now
        else:
            targets = [Path(path) for path in changed_paths if self._is_rollout(Path(path))]

        for path in targets:
            key = self._key(path)
            fingerprint = self._fingerprint(path)
            if fingerprint is None:
                self._entries.pop(key, None)
                continue
            cached = self._entries.get(key)
            if cached is not None and cached.fingerprint == fingerprint:
                continue
            self._entries[key] = _RolloutCacheEntry(fingerprint, parse_rollout(path, titles))

        if len(self._entries) > self.max_files:
            newest = sorted(
                self._entries.items(),
                key=lambda item: item[1].fingerprint[0],
                reverse=True,
            )[: self.max_files]
            self._entries = dict(newest)

        projects = []
        for entry in self._entries.values():
            project = entry.project
            if project is None:
                continue
            current_title = _display_title(titles.get(project.session_id, ""))
            if project.title != current_title:
                project = dataclasses.replace(project, title=current_title)
            projects.append(project)
        projects.sort(key=lambda item: item.updated_at, reverse=True)
        return projects
