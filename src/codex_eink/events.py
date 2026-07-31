from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


_ROOT_FILES = {
    "session_index.jsonl",
    ".codex-global-state.json",
}
_DATABASE_SOURCES = {
    "state_5.sqlite": "state_db",
    "state_5.sqlite-wal": "state_db",
    "state_5.sqlite-shm": "state_db",
    "logs_2.sqlite": "activity_db",
    "logs_2.sqlite-wal": "activity_db",
    "logs_2.sqlite-shm": "activity_db",
}


class _CodexChangeHandler(FileSystemEventHandler):
    def __init__(self, watcher: "CodexEventWatcher") -> None:
        self.watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        paths = [event.src_path]
        destination = getattr(event, "dest_path", None)
        if destination:
            paths.append(destination)
        for path in paths:
            if self.watcher.is_relevant_path(path):
                self.watcher.signal(path)
                return


class CodexEventWatcher:
    """Signal relevant local Codex changes without polling every file."""

    def __init__(self, codex_home: str | Path, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.codex_home = Path(codex_home)
        self._clock = clock
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._last_signal_at: float | None = None
        self._pending_sources: set[str] = set()
        self._observer: Observer | None = None

    def is_relevant_path(self, path: str | Path) -> bool:
        relative = self._relative_path(path)
        if relative is None:
            return False
        if relative.name in _ROOT_FILES and len(relative.parts) == 1:
            return True
        if len(relative.parts) == 1 and relative.name in _DATABASE_SOURCES:
            return True
        return bool(relative.parts and relative.parts[0] == "sessions" and relative.suffix == ".jsonl")

    def _relative_path(self, path: str | Path) -> Path | None:
        root = os.path.normcase(os.path.abspath(self.codex_home))
        candidate = os.path.normcase(os.path.abspath(path))
        try:
            relative = Path(os.path.relpath(candidate, root))
        except ValueError:
            return None
        if relative.parts and relative.parts[0] == "..":
            return None
        return relative

    def source_for_path(self, path: str | Path) -> str | None:
        relative = self._relative_path(path)
        if relative is None:
            return None
        if relative.parts and relative.parts[0] == "sessions" and relative.suffix == ".jsonl":
            return "rollout"
        if len(relative.parts) == 1 and relative.name == "session_index.jsonl":
            return "session_index"
        if len(relative.parts) == 1 and relative.name == ".codex-global-state.json":
            return "unread"
        if len(relative.parts) == 1:
            return _DATABASE_SOURCES.get(relative.name)
        return None

    def signal(self, path: str | Path | None = None) -> None:
        with self._lock:
            self._last_signal_at = self._clock()
            source = self.source_for_path(path) if path is not None else None
            self._pending_sources.add(source or "unknown")
            self._event.set()

    def consume_sources(self) -> frozenset[str]:
        with self._lock:
            sources = frozenset(self._pending_sources)
            self._pending_sources.clear()
            return sources

    @staticmethod
    def only_database_sources(sources: frozenset[str]) -> bool:
        return bool(sources) and sources.issubset({"state_db", "activity_db"})

    def wait(self, timeout: float | None) -> bool:
        return self._event.wait(timeout)

    def quiet_remaining(self, seconds: float) -> float:
        with self._lock:
            if self._last_signal_at is None:
                return 0.0
            return max(0.0, self._last_signal_at + seconds - self._clock())

    def wait_until_quiet(self, seconds: float) -> None:
        while True:
            self._event.clear()
            remaining = self.quiet_remaining(seconds)
            if remaining <= 0:
                return
            self._event.wait(remaining)

    def start(self) -> None:
        if self._observer is not None:
            return
        observer = Observer()
        observer.schedule(_CodexChangeHandler(self), str(self.codex_home), recursive=True)
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=5)
        self._observer = None

    def __enter__(self) -> "CodexEventWatcher":
        self.start()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.stop()
