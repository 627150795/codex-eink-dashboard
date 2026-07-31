from __future__ import annotations

import dataclasses
from collections.abc import Iterable

from .models import ProjectState, ProjectStatus


TERMINAL_NOTIFICATION_TTL = 2 * 60 * 60
_TERMINAL_STATUSES = frozenset({ProjectStatus.DONE, ProjectStatus.ERROR})


def terminal_notification_visible(project: ProjectState, *, now: float) -> bool:
    """Return whether a terminal project still belongs in the status strip."""
    return (
        project.status in _TERMINAL_STATUSES
        and project.unread
        and now - project.updated_at < TERMINAL_NOTIFICATION_TTL
    )


def terminal_notification_projects(
    projects: Iterable[ProjectState],
    *,
    now: float,
) -> list[ProjectState]:
    """Return visible terminal notifications in the stable done-then-error order."""
    projects = tuple(projects)
    seen: set[str] = set()
    output: list[ProjectState] = []
    for status in (ProjectStatus.DONE, ProjectStatus.ERROR):
        for project in sorted(projects, key=lambda item: item.updated_at, reverse=True):
            if project.status != status or not terminal_notification_visible(project, now=now):
                continue
            if project.alert_id in seen:
                continue
            seen.add(project.alert_id)
            output.append(project)
    return output


def apply_terminal_notification_state(
    projects: Iterable[ProjectState],
    unread_ids: set[str],
    *,
    now: float,
) -> list[ProjectState]:
    """Merge Codex's unread set into projects using one terminal lifecycle."""
    output = []
    for project in projects:
        unread = (
            project.status in _TERMINAL_STATUSES
            and project.session_id in unread_ids
            and now - project.updated_at < TERMINAL_NOTIFICATION_TTL
        )
        output.append(dataclasses.replace(project, unread=unread))
    return output
