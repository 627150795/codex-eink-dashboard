from __future__ import annotations

from .models import DashboardView, ProjectState, ProjectStatus, QuotaState
from .notifications import terminal_notification_projects


def reduce_dashboard(
    projects: list[ProjectState] | tuple[ProjectState, ...],
    quota: QuotaState,
    *,
    now: float,
    last_success_at: float,
    poll_seconds: int = 60,
    completion_ttl: int = 1800,
    error_ttl: int = 86400,
) -> DashboardView:
    active = [item for item in projects if item.status in {ProjectStatus.ACTIVE, ProjectStatus.WAITING}]
    active.sort(key=lambda item: item.session_id, reverse=True)
    active.sort(key=lambda item: 0 if item.status == ProjectStatus.WAITING else 1)

    seen = set()
    alerts = []
    for item in sorted(projects, key=lambda project: project.updated_at, reverse=True):
        if item.status not in {ProjectStatus.DONE, ProjectStatus.ERROR, ProjectStatus.STOPPED}:
            continue
        ttl = error_ttl if item.status == ProjectStatus.ERROR else completion_ttl
        if now - item.updated_at > ttl or item.alert_id in seen:
            continue
        seen.add(item.alert_id)
        alerts.append(item)

    terminal_notifications = terminal_notification_projects(projects, now=now)
    active_alert_ids = {item.alert_id for item in active}
    status_projects = list(active) + [item for item in terminal_notifications if item.alert_id not in active_alert_ids]

    fresh = now - last_success_at <= (2 * poll_seconds + 15)
    if not fresh:
        global_status = "OFFLINE"
    elif quota.exhausted:
        global_status = "LIMIT"
    elif any(item.status == ProjectStatus.ERROR for item in terminal_notifications):
        global_status = "ERR"
    elif active:
        global_status = "WAIT" if any(item.status == ProjectStatus.WAITING for item in active) else "RUN"
    elif any(item.status == ProjectStatus.DONE for item in terminal_notifications):
        global_status = "DONE"
    else:
        global_status = "IDLE"
    return DashboardView(
        global_status=global_status,
        active_projects=tuple(active),
        alerts=tuple(alerts),
        status_projects=tuple(status_projects),
        quota=quota,
        synced_at=last_success_at,
        fresh=fresh,
    )
