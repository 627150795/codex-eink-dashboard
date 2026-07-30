from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


SUPPORTED_RESOLUTIONS = ((212, 104), (250, 122), (296, 128), (400, 300))


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    WAITING = "waiting"
    DONE = "done"
    ERROR = "error"
    STOPPED = "stopped"
    IDLE = "idle"


@dataclass(frozen=True)
class ProjectState:
    session_id: str
    title: str
    status: ProjectStatus
    updated_at: float
    summary: str = ""
    cwd: str = ""
    turn_id: str = ""
    terminal_id: str = ""
    terminal_source: str = ""
    waiting_reason: str = ""
    progress_current: int | None = None
    progress_total: int | None = None
    unread: bool = False

    @property
    def alert_id(self) -> str:
        terminal = self.terminal_id or self.turn_id or str(int(self.updated_at))
        return f"{self.session_id}:{terminal}:{self.status.value}"


@dataclass(frozen=True)
class QuotaWindow:
    used_percent: float
    resets_at: float | None = None
    window_duration_mins: int | None = None

    @property
    def remaining_percent(self) -> int:
        return round(max(0.0, min(100.0, 100.0 - float(self.used_percent))))

    @property
    def display_remaining_percent(self) -> int:
        return self.remaining_percent


@dataclass(frozen=True)
class QuotaState:
    primary: QuotaWindow | None = None
    secondary: QuotaWindow | None = None
    plan_type: str | None = None
    reached: str | None = None
    credits: float | None = None

    @property
    def exhausted(self) -> bool:
        return bool(
            self.reached
            or (self.primary and self.primary.used_percent >= 100)
            or (self.secondary and self.secondary.used_percent >= 100)
        )


@dataclass(frozen=True)
class DashboardView:
    global_status: str
    active_projects: tuple[ProjectState, ...] = field(default_factory=tuple)
    alerts: tuple[ProjectState, ...] = field(default_factory=tuple)
    status_projects: tuple[ProjectState, ...] = field(default_factory=tuple)
    quota: QuotaState = field(default_factory=QuotaState)
    synced_at: float = 0.0
    fresh: bool = True
    battery_voltage: float | None = None
