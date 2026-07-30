from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import DashboardView, ProjectState, ProjectStatus, SUPPORTED_RESOLUTIONS


_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)

_STATUS_GLYPHS = {
    "running": ("0011100", "0111110", "1111111", "1111111", "1111111", "0111110", "0011100"),
    "done": ("0000001", "0000011", "0000110", "1101100", "0111000", "0010000", "0000000"),
    "error": ("1000001", "0100010", "0010100", "0001000", "0010100", "0100010", "1000001"),
}


def _font(size: int, bold: bool = False):
    candidates = list(_FONT_CANDIDATES)
    if bold:
        candidates.insert(0, Path("C:/Windows/Fonts/msyhbd.ttc"))
        candidates.insert(1, Path("C:/Windows/Fonts/arialbd.ttf"))
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, value: str, font) -> int:
    box = draw.textbbox((0, 0), value, font=font)
    return max(0, box[2] - box[0])


def _fit(draw: ImageDraw.ImageDraw, value: str, width: int, font) -> str:
    value = " ".join(str(value).split())
    if _text_width(draw, value, font) <= width:
        return value
    suffix = "..."
    available = max(0, width - _text_width(draw, suffix, font))
    low, high = 0, len(value)
    while low < high:
        middle = (low + high + 1) // 2
        if _text_width(draw, value[:middle], font) <= available:
            low = middle
        else:
            high = middle - 1
    return value[:low].rstrip() + suffix


def _clock(epoch: float | None) -> str:
    if not epoch:
        return "--:--"
    return time.strftime("%H:%M", time.localtime(epoch))


def _quota_label(window) -> str:
    return f"LEFT {window.display_remaining_percent}%" if window else "Q --"


def _portrait_reset_label(quota) -> str:
    if (quota.plan_type or "").casefold() == "api":
        return "API"
    weekly_window = quota.secondary or quota.primary
    resets_at = weekly_window.resets_at if weekly_window else None
    if not resets_at:
        return "--.--"
    reset = time.localtime(resets_at)
    return f"{reset.tm_mon}.{reset.tm_mday}"


def _bar(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, height: int, remaining: int | None) -> None:
    draw.rectangle((x, y, x + width - 1, y + height - 1), outline=0, fill=1)
    if remaining is None:
        return
    fill_width = round((width - 2) * max(0, min(100, remaining)) / 100)
    if fill_width:
        draw.rectangle((x + 1, y + 1, x + fill_width, y + height - 2), fill=0)


def _row_prefix(project: ProjectState) -> str:
    if project.status == ProjectStatus.WAITING:
        return "?"
    if project.status == ProjectStatus.ERROR:
        return "!"
    return ">"


def _alert_text(project: ProjectState, include_summary: bool = True) -> str:
    label = {ProjectStatus.DONE: "DONE", ProjectStatus.ERROR: "ERR", ProjectStatus.STOPPED: "STOP"}.get(project.status, "INFO")
    text = f"{label} {project.title}"
    if include_summary and project.summary:
        text += f": {project.summary}"
    return text


def _overflow_rows(
    projects: tuple[ProjectState, ...], slots: int, overflow_label: str | None = None
) -> list[tuple[str, str]]:
    if len(projects) <= slots:
        return [(_row_prefix(item), item.title) for item in projects]
    visible = max(0, slots - 1)
    rows = [(_row_prefix(item), item.title) for item in projects[:visible]]
    rows.append((">", overflow_label if overflow_label is not None else f"+{len(projects) - visible} more"))
    return rows


def _portrait_status_tokens(view: DashboardView) -> tuple[str, ...]:
    tokens = []
    for project in view.status_projects:
        if project.status in {ProjectStatus.ACTIVE, ProjectStatus.WAITING}:
            if project.progress_current and project.progress_total:
                tokens.append(f"{project.progress_current}/{project.progress_total}")
            else:
                tokens.append("running")
        elif project.status == ProjectStatus.DONE and project.unread:
            tokens.append("done")
        elif project.status == ProjectStatus.ERROR:
            tokens.append("error")
        if len(tokens) == 8:
            break
    return tuple(tokens)


def _draw_status_glyph(draw: ImageDraw.ImageDraw, x: int, y: int, name: str) -> None:
    for row, bits in enumerate(_STATUS_GLYPHS[name]):
        for column, bit in enumerate(bits):
            if bit == "1":
                draw.point((x + column, y + row), fill=0)


def _header(draw, width: int, status: str, count: int, sync: float, font, inverted: bool = False):
    label = f"{status} {count}"
    if inverted:
        draw.rectangle((0, 0, width - 1, 18), fill=0)
        fill = 1
    else:
        fill = 0
    draw.text((3, 1), label, font=font, fill=fill)
    sync_text = f"SYNC {_clock(sync)}"
    draw.text((width - _text_width(draw, sync_text, font) - 3, 1), sync_text, font=font, fill=fill)


def _render_212(draw, view: DashboardView):
    small = _font(11)
    tiny = _font(9)
    _header(draw, 212, view.global_status, len(view.active_projects), view.synced_at, small, view.global_status in {"OFFLINE", "ERR", "LIMIT"})
    draw.line((0, 19, 211, 19), fill=0)
    quota = _quota_label(view.quota.primary)
    draw.text((3, 21), quota, font=small, fill=0)
    if view.quota.primary:
        _bar(draw, 112, 24, 96, 7, view.quota.primary.display_remaining_percent)
    for index, (prefix, title) in enumerate(_overflow_rows(view.active_projects, 2)):
        y = 38 + index * 15
        draw.text((3, y), prefix, font=small, fill=0)
        draw.text((16, y), _fit(draw, title, 192, small), font=small, fill=0)
    draw.line((0, 70, 211, 70), fill=0)
    alert = _alert_text(view.alerts[0], include_summary=False) if view.alerts else "NO ALERT"
    draw.text((3, 72), _fit(draw, alert, 206, tiny), font=tiny, fill=0)
    draw.text((3, 91), f"R {_clock(view.quota.primary.resets_at) if view.quota.primary else '--:--'}", font=tiny, fill=0)


def _render_250(draw, view: DashboardView):
    small = _font(11)
    tiny = _font(9)
    _header(draw, 250, view.global_status, len(view.active_projects), view.synced_at, small, view.global_status in {"OFFLINE", "ERR", "LIMIT"})
    draw.text((3, 21), _quota_label(view.quota.primary), font=small, fill=0)
    _bar(draw, 111, 24, 135, 7, view.quota.primary.display_remaining_percent if view.quota.primary else None)
    for index, (prefix, title) in enumerate(_overflow_rows(view.active_projects, 3)):
        y = 37 + index * 15
        draw.text((3, y), prefix, font=small, fill=0)
        draw.text((16, y), _fit(draw, title, 229, small), font=small, fill=0)
    draw.line((0, 84, 249, 84), fill=0)
    alert = _alert_text(view.alerts[0]) if view.alerts else "NO ALERT"
    draw.text((3, 87), _fit(draw, alert, 244, tiny), font=tiny, fill=0)
    reset = _clock(view.quota.primary.resets_at) if view.quota.primary else "--:--"
    draw.text((3, 108), f"RESET {reset}", font=tiny, fill=0)


def _render_296(draw, view: DashboardView):
    small = _font(11)
    tiny = _font(9)
    rail_x = 204
    _header(draw, 296, view.global_status, len(view.active_projects), view.synced_at, small, view.global_status in {"OFFLINE", "ERR", "LIMIT"})
    draw.line((0, 19, 295, 19), fill=0)
    draw.line((rail_x, 20, rail_x, 103), fill=0)
    for index, (prefix, title) in enumerate(_overflow_rows(view.active_projects, 4)):
        y = 23 + index * 18
        draw.text((3, y), prefix, font=small, fill=0)
        draw.text((16, y), _fit(draw, title, rail_x - 20, small), font=small, fill=0)
    primary = view.quota.primary
    secondary = view.quota.secondary
    draw.text((rail_x + 5, 23), _quota_label(primary), font=tiny, fill=0)
    _bar(draw, rail_x + 5, 38, 82, 8, primary.display_remaining_percent if primary else None)
    draw.text((rail_x + 5, 50), f"R {_clock(primary.resets_at) if primary else '--:--'}", font=tiny, fill=0)
    draw.text((rail_x + 5, 67), f"Q2 {secondary.display_remaining_percent}%" if secondary else "Q2 --", font=tiny, fill=0)
    _bar(draw, rail_x + 5, 82, 82, 8, secondary.display_remaining_percent if secondary else None)
    draw.line((0, 104, 295, 104), fill=0)
    alert = _alert_text(view.alerts[0]) if view.alerts else "NO ALERT"
    draw.text((3, 108), _fit(draw, alert, 290, tiny), font=tiny, fill=0)


def _render_400(draw, view: DashboardView):
    title_font = _font(16, bold=True)
    body = _font(14)
    small = _font(11)
    inverted = view.global_status in {"OFFLINE", "ERR", "LIMIT"}
    if inverted:
        draw.rectangle((0, 0, 399, 28), fill=0)
    fill = 1 if inverted else 0
    draw.text((7, 3), f"CODEX  {view.global_status} {len(view.active_projects)}", font=title_font, fill=fill)
    sync = f"SYNC {_clock(view.synced_at)}"
    draw.text((393 - _text_width(draw, sync, body), 5), sync, font=body, fill=fill)
    draw.line((0, 30, 399, 30), fill=0)
    split = 270
    draw.text((7, 35), "RUNNING PROJECTS", font=small, fill=0)
    draw.text((split + 8, 35), "QUOTA", font=small, fill=0)
    draw.line((split, 31, split, 207), fill=0)
    for index, (prefix, title) in enumerate(_overflow_rows(view.active_projects, 7)):
        y = 54 + index * 21
        draw.text((7, y), prefix, font=body, fill=0)
        draw.text((25, y), _fit(draw, title, split - 31, body), font=body, fill=0)
    primary = view.quota.primary
    secondary = view.quota.secondary
    draw.text((split + 8, 57), _quota_label(primary), font=body, fill=0)
    _bar(draw, split + 8, 80, 114, 11, primary.display_remaining_percent if primary else None)
    draw.text((split + 8, 97), f"RESET {_clock(primary.resets_at) if primary else '--:--'}", font=small, fill=0)
    draw.text((split + 8, 126), f"Q2 LEFT {secondary.display_remaining_percent}%" if secondary else "Q2 --", font=small, fill=0)
    _bar(draw, split + 8, 145, 114, 11, secondary.display_remaining_percent if secondary else None)
    draw.text((split + 8, 162), f"RESET {_clock(secondary.resets_at) if secondary else '--:--'}", font=small, fill=0)
    if view.quota.credits is not None:
        draw.text((split + 8, 187), f"CREDITS {view.quota.credits:g}", font=small, fill=0)
    draw.line((0, 208, 399, 208), fill=0)
    draw.text((7, 212), "ALERTS", font=small, fill=0)
    alerts = view.alerts[:2]
    for index, alert in enumerate(alerts):
        y = 231 + index * 31
        draw.text((7, y), _fit(draw, _alert_text(alert, include_summary=False), 386, body), font=body, fill=0)
        if alert.summary:
            draw.text((25, y + 16), _fit(draw, alert.summary, 368, small), font=small, fill=0)
    if not alerts:
        draw.text((7, 231), "NO ALERT", font=body, fill=0)


def _render_portrait_212(draw, view: DashboardView):
    small = _font(10)
    tiny = _font(8)
    draw.rectangle((0, 0, 103, 18), fill=0)
    draw.text((3, 2), f"{view.global_status} {len(view.active_projects)}", font=small, fill=1)
    reset = _portrait_reset_label(view.quota)
    draw.text((101 - _text_width(draw, reset, small), 2), reset, font=small, fill=1)
    draw.line((0, 20, 103, 20), fill=0)

    primary = view.quota.primary
    api_plan = (view.quota.plan_type or "").casefold() == "api"
    if not api_plan:
        draw.text((3, 24), _quota_label(primary), font=small, fill=0)
        _bar(draw, 3, 39, 98, 8, primary.display_remaining_percent if primary else None)

    task_label_y = 24 if api_plan else 53
    task_row_y = 36 if api_plan else 65
    draw.text((3, task_label_y), "TASKS", font=tiny, fill=0)
    for index, (prefix, title) in enumerate(_overflow_rows(view.active_projects, 6, overflow_label="...")):
        y = task_row_y + index * 15
        draw.text((3, y), prefix, font=small, fill=0)
        draw.text((15, y), _fit(draw, title, 86, small), font=small, fill=0)

    draw.line((0, 158, 103, 158), fill=0)
    tokens = _portrait_status_tokens(view)
    if tokens:
        slot_width = 104 // 4
        for index, token in enumerate(tokens):
            row, column = divmod(index, 4)
            left = column * slot_width
            y = 169 + row * 24
            if token in _STATUS_GLYPHS:
                _draw_status_glyph(draw, left + (slot_width - 7) // 2, y, token)
            else:
                draw.text((left + (slot_width - _text_width(draw, token, small)) // 2, y - 4), token, font=small, fill=0)


def render_dashboard(view: DashboardView, size: tuple[int, int], *, orientation: str = "landscape") -> Image.Image:
    size = tuple(size)
    if size not in SUPPORTED_RESOLUTIONS:
        raise ValueError(f"unsupported panel resolution: {size}")
    if orientation in {"portrait_cw", "portrait_ccw"}:
        if size != (212, 104):
            raise ValueError("portrait layout is currently available for the 212x104 panel only")
        portrait = Image.new("1", (104, 212), 1)
        _render_portrait_212(ImageDraw.Draw(portrait), view)
        rotation = Image.Transpose.ROTATE_270 if orientation == "portrait_cw" else Image.Transpose.ROTATE_90
        return portrait.transpose(rotation)
    if orientation != "landscape":
        raise ValueError(f"unsupported orientation: {orientation}")
    image = Image.new("1", size, 1)
    draw = ImageDraw.Draw(image)
    if size == (212, 104):
        _render_212(draw, view)
    elif size == (250, 122):
        _render_250(draw, view)
    elif size == (296, 128):
        _render_296(draw, view)
    else:
        _render_400(draw, view)
    return image
