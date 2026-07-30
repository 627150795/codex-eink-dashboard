from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path


_TS = re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_UPLOAD = re.compile(r"uploaded\s+(?P<n>\d+)\s+packets", re.I)
_UNCHANGED = re.compile(r"\bunchanged\b", re.I)
_RETRY = re.compile(r"\bretry:\s*(?P<msg>.*)$", re.I)
_SERVICE_START = re.compile(r"\bservice-start\b", re.I)
_SERVICE_EXIT = re.compile(r"\bservice-exit\b", re.I)
_SERVICE_ERROR = re.compile(r"\bservice-error\b", re.I)
_WINERROR = re.compile(r"WinError\s+(-?\d+)", re.I)


@dataclass
class DayStats:
    day: str
    uploaded: int = 0
    unchanged: int = 0
    retry: int = 0
    service_start: int = 0
    service_exit: int = 0
    service_error: int = 0
    other: int = 0
    packets: int = 0
    first_ts: str | None = None
    last_ts: str | None = None
    max_upload_streak: int = 0
    upload_bursts: int = 0
    retries: Counter[str] = field(default_factory=Counter)
    hourly: dict[str, Counter[str]] = field(default_factory=dict)

    @property
    def polls(self) -> int:
        return self.uploaded + self.unchanged + self.retry

    @property
    def upload_ratio(self) -> float:
        return self.uploaded / self.polls if self.polls else 0.0

    @property
    def unchanged_ratio(self) -> float:
        return self.unchanged / self.polls if self.polls else 0.0


def _bucket_retry(msg: str) -> str:
    text = (msg or "").strip()
    if "Invalid PDU" in text:
        return "GATT Invalid PDU"
    if "not found" in text.lower():
        return "device not found"
    if m := _WINERROR.search(text):
        return f"WinError {m.group(1)}"
    cleaned = re.sub(r"[^\x20-\x7E]+", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" :")
    return cleaned[:100] if cleaned else "retry"


def _classify(line: str) -> tuple[str, str | None, int]:
    if m := _UPLOAD.search(line):
        return "uploaded", None, int(m.group("n"))
    if _UNCHANGED.search(line):
        return "unchanged", None, 0
    if m := _RETRY.search(line):
        return "retry", _bucket_retry(m.group("msg") or ""), 0
    if _SERVICE_START.search(line):
        return "service_start", None, 0
    if _SERVICE_EXIT.search(line):
        return "service_exit", None, 0
    if _SERVICE_ERROR.search(line):
        return "service_error", None, 0
    return "other", None, 0


def parse_log_lines(lines: list[str]) -> dict[str, DayStats]:
    days: dict[str, DayStats] = {}
    streak = 0
    current_day: str | None = None

    for raw in lines:
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue
        ts_match = _TS.search(line)
        if not ts_match:
            continue
        ts = ts_match.group("ts")
        day = ts[:10]
        hour = ts[11:13]
        if day != current_day:
            streak = 0
            current_day = day
        stats = days.get(day)
        if stats is None:
            stats = DayStats(day=day)
            days[day] = stats
        if stats.first_ts is None:
            stats.first_ts = ts
        stats.last_ts = ts
        hour_bucket = stats.hourly.setdefault(hour, Counter())

        kind, detail, packets = _classify(line)
        if kind == "uploaded":
            stats.uploaded += 1
            stats.packets += packets
            hour_bucket["uploaded"] += 1
            streak += 1
            if streak == 1:
                stats.upload_bursts += 1
            stats.max_upload_streak = max(stats.max_upload_streak, streak)
        elif kind == "unchanged":
            stats.unchanged += 1
            hour_bucket["unchanged"] += 1
            streak = 0
        elif kind == "retry":
            stats.retry += 1
            hour_bucket["retry"] += 1
            streak = 0
            if detail:
                stats.retries[detail] += 1
        elif kind == "service_start":
            stats.service_start += 1
            hour_bucket["service_start"] += 1
            streak = 0
        elif kind == "service_exit":
            stats.service_exit += 1
            hour_bucket["service_exit"] += 1
            streak = 0
        elif kind == "service_error":
            stats.service_error += 1
            hour_bucket["service_error"] += 1
            streak = 0
        else:
            stats.other += 1
            hour_bucket["other"] += 1
            streak = 0
    return days


def load_log(path: str | Path) -> dict[str, DayStats]:
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gbk", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    return parse_log_lines(text.splitlines())


def filter_days(
    days: dict[str, DayStats],
    *,
    day: str | None = None,
    since: str | None = None,
    last: int | None = None,
) -> list[DayStats]:
    items = [days[k] for k in sorted(days)]
    if day:
        items = [item for item in items if item.day == day]
    if since:
        items = [item for item in items if item.day >= since]
    if last is not None and last > 0:
        items = items[-last:]
    return items


def format_report(days: list[DayStats], *, top_retries: int = 5, hourly: bool = False) -> str:
    if not days:
        return "no matching log days"

    lines: list[str] = []
    lines.append("Codex e-ink log daily stats")
    lines.append("=" * 72)

    total = DayStats(day="TOTAL")
    for d in days:
        total.uploaded += d.uploaded
        total.unchanged += d.unchanged
        total.retry += d.retry
        total.service_start += d.service_start
        total.service_exit += d.service_exit
        total.service_error += d.service_error
        total.other += d.other
        total.packets += d.packets
        total.max_upload_streak = max(total.max_upload_streak, d.max_upload_streak)
        total.upload_bursts += d.upload_bursts
        total.retries.update(d.retries)
        if total.first_ts is None or (d.first_ts and d.first_ts < total.first_ts):
            total.first_ts = d.first_ts
        if total.last_ts is None or (d.last_ts and d.last_ts > total.last_ts):
            total.last_ts = d.last_ts

    header = f"{'day':<12} {'up':>5} {'unch':>5} {'retry':>5} {'up%':>6} {'unch%':>6} {'pkts':>6} {'max↑':>4} {'burst':>5}"
    lines.append(header)
    lines.append("-" * len(header))
    for d in days:
        lines.append(
            f"{d.day:<12} {d.uploaded:5d} {d.unchanged:5d} {d.retry:5d} "
            f"{d.upload_ratio * 100:5.1f}% {d.unchanged_ratio * 100:5.1f}% "
            f"{d.packets:6d} {d.max_upload_streak:4d} {d.upload_bursts:5d}"
        )
    if len(days) > 1:
        lines.append("-" * len(header))
        lines.append(
            f"{'TOTAL':<12} {total.uploaded:5d} {total.unchanged:5d} {total.retry:5d} "
            f"{total.upload_ratio * 100:5.1f}% {total.unchanged_ratio * 100:5.1f}% "
            f"{total.packets:6d} {total.max_upload_streak:4d} {total.upload_bursts:5d}"
        )

    lines.append("")
    lines.append(f"span: {total.first_ts or '-'}  ->  {total.last_ts or '-'}")
    lines.append(
        f"service: start={total.service_start} exit={total.service_exit} error={total.service_error} other={total.other}"
    )

    if total.retries:
        lines.append("")
        lines.append("top retries:")
        for msg, count in total.retries.most_common(top_retries):
            lines.append(f"  {count:4d}  {msg}")

    if hourly:
        lines.append("")
        lines.append("hourly (selected days):")
        h_header = f"{'day':<12} {'hh':>2} {'up':>5} {'unch':>5} {'retry':>5} {'up%':>6}"
        lines.append(h_header)
        lines.append("-" * len(h_header))
        for d in days:
            for hour in sorted(d.hourly):
                c = d.hourly[hour]
                up = c.get("uploaded", 0)
                unch = c.get("unchanged", 0)
                retry = c.get("retry", 0)
                polls = up + unch + retry
                ratio = (up / polls * 100.0) if polls else 0.0
                lines.append(f"{d.day:<12} {hour:>2} {up:5d} {unch:5d} {retry:5d} {ratio:5.1f}%")

    lines.append("")
    if total.polls == 0:
        lines.append("hint: no poll outcomes yet")
    elif total.upload_ratio > 0.4:
        lines.append("hint: upload% still high — check voltage jitter / content churn / old binary")
    elif total.upload_ratio > 0.15:
        lines.append("hint: moderate upload% — OK if tasks/quota actually changed")
    else:
        lines.append("hint: low upload% — content-first path looks healthy")
    return "\n".join(lines)


def default_log_path(project_root: str | Path | None = None) -> Path:
    root = Path(project_root) if project_root else Path.cwd()
    return root / "logs" / "dashboard.log"


def recent_day_bounds(days: int = 1, today: date | None = None) -> str:
    base = today or date.today()
    return (base - timedelta(days=max(0, days - 1))).isoformat()
