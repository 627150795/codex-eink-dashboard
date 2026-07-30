from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
import time
from pathlib import Path

from PIL import Image

from .ble import BleTransport, DeviceStatus
from .config import AppConfig
from .events import CodexEventWatcher
from .models import DashboardView, ProjectStatus, QuotaState, SUPPORTED_RESOLUTIONS
from .protocol import build_bw_packets, build_bwr_packets
from .quota import read_live_quota, read_quota_fallback
from .reducer import reduce_dashboard
from .render import render_dashboard
from .logstats import default_log_path, filter_days, format_report, load_log, recent_day_bounds
from .service import FrameCache, frame_digest, quantize_battery_voltage, quantize_sync_time, should_upload
from .sessions import collect_projects, load_recent_thread_ids, load_session_titles, load_state_titles, load_unread_thread_ids, reconcile_live_activity


_LAST_SUCCESSFUL_LIVE_QUOTA: QuotaState | None = None


def _config(path: str | None) -> AppConfig:
    return AppConfig.load(path) if path else AppConfig()


def _read_live_quota_with_retry() -> QuotaState | None:
    global _LAST_SUCCESSFUL_LIVE_QUOTA
    for attempt in range(2):
        try:
            quota = read_live_quota(timeout=10)
        except Exception:
            if attempt == 0:
                time.sleep(0.25)
            continue
        if quota.primary or quota.secondary or (quota.plan_type or "").casefold() == "api":
            _LAST_SUCCESSFUL_LIVE_QUOTA = quota
            return quota
        if attempt == 0:
            time.sleep(0.25)
    return None


def collect_view(config: AppConfig, *, live_quota: bool = True) -> DashboardView:
    codex_home = config.codex_home
    assert codex_home is not None
    titles = load_session_titles(codex_home / "session_index.jsonl")
    titles.update(load_state_titles(codex_home / "state_5.sqlite"))
    projects = collect_projects(codex_home / "sessions", titles)
    now = time.time()
    live_ids = load_recent_thread_ids(codex_home / "logs_2.sqlite", now=now)
    projects = reconcile_live_activity(projects, live_ids, now=now)
    unread_ids = load_unread_thread_ids(codex_home / ".codex-global-state.json")
    projects = [
        dataclasses.replace(
            project,
            unread=project.status in {ProjectStatus.DONE, ProjectStatus.ERROR} and project.session_id in unread_ids,
        )
        for project in projects
    ]
    if config.privacy_mode == "titles":
        projects = [dataclasses.replace(item, summary="") for item in projects]
    quota = QuotaState(plan_type="api") if config.account_mode == "api" else QuotaState()
    if live_quota and config.account_mode != "api":
        live_quota_value = _read_live_quota_with_retry()
        if live_quota_value is not None:
            quota = live_quota_value
        elif _LAST_SUCCESSFUL_LIVE_QUOTA is not None:
            quota = _LAST_SUCCESSFUL_LIVE_QUOTA
    if (
        quota.primary is None
        and quota.secondary is None
        and (quota.plan_type or "").casefold() != "api"
    ):
        quota = read_quota_fallback(codex_home / "sessions")
    view = reduce_dashboard(
        projects,
        quota,
        now=now,
        last_success_at=now,
        poll_seconds=config.active_poll_seconds if any(item.status.value in {"active", "waiting"} for item in projects) else config.idle_poll_seconds,
    )
    return dataclasses.replace(view, synced_at=quantize_sync_time(now))


def _transport(config: AppConfig) -> BleTransport:
    return BleTransport(
        name_prefix=config.device_name_prefix,
        address=config.device_address,
        scan_timeout=config.scan_timeout_seconds,
        status_timeout=config.status_timeout_seconds,
    )


def _cached_resolution(config: AppConfig, cached: dict) -> tuple[int, int] | None:
    if config.resolution is not None:
        return config.resolution
    value = cached.get("resolution")
    if isinstance(value, list) and len(value) == 2:
        return int(value[0]), int(value[1])
    return None


def _cached_battery(cached: dict) -> float | None:
    value = cached.get("battery_display")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _save_preview(config: AppConfig, view: DashboardView, resolution: tuple[int, int], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    image = render_dashboard(view, resolution, orientation=config.orientation)
    image.save(output, format="PNG", optimize=False)
    return output


def command_preview(args) -> int:
    config = _config(args.config)
    view = collect_view(config, live_quota=not args.no_live_quota)
    output = Path(args.output)
    if args.all:
        output.mkdir(parents=True, exist_ok=True)
        for resolution in SUPPORTED_RESOLUTIONS:
            path = output / f"codex-eink-{resolution[0]}x{resolution[1]}.png"
            _save_preview(config, view, resolution, path)
            print(path.resolve())
    else:
        resolution = tuple(args.resolution) if args.resolution else config.resolution or (296, 128)
        print(_save_preview(config, view, resolution, output).resolve())
    return 0


async def _probe(config: AppConfig):
    return await _transport(config).probe()


def command_probe(args) -> int:
    status = asyncio.run(_probe(_config(args.config)))
    print(json.dumps(dataclasses.asdict(status), ensure_ascii=False, indent=2))
    return 0


def _build_packets(config: AppConfig, image: Image.Image, status: DeviceStatus, resolution: tuple[int, int]):
    if status.is_bwr:
        red_plane = Image.new("1", resolution, 1)
        return build_bwr_packets(image, red_plane)
    return build_bw_packets(image, image_index=config.image_index)


async def _once(config: AppConfig, *, force: bool, preview_path: Path) -> tuple[str, object]:
    """Content-first update path.

    1. Render with cached resolution + stabilized battery (no BLE).
    2. If the bitmap digest is unchanged, stay silent — do not scan/connect.
    3. Only when upload is needed, open one BLE session: read status, re-render
       with live quantized voltage, write packets on the same connection.
    """
    transport = _transport(config)
    cache = FrameCache(preview_path.parent / ".state.json")
    cached = cache.load()
    resolution = _cached_resolution(config, cached)
    battery_display = _cached_battery(cached)
    previous = cached.get("frame_digest")
    preview_path.parent.mkdir(parents=True, exist_ok=True)

    # Bootstrap: resolution unknown — must probe once, then continue content-first.
    if resolution is None:
        status = await transport.probe()
        resolution = status.resolution
        if config.resolution is not None and config.resolution != status.resolution:
            raise ValueError(f"configured resolution {config.resolution} does not match device {status.resolution}")
        battery_display = quantize_battery_voltage(status.voltage, battery_display)
        view = dataclasses.replace(collect_view(config), battery_voltage=battery_display)
        image = render_dashboard(view, resolution, orientation=config.orientation)
        image.save(preview_path, format="PNG", optimize=False)
        digest = frame_digest(image)
        if not force and not should_upload(digest, previous):
            cache.save(digest=digest, synced_at=time.time(), resolution=resolution, battery_display=battery_display)
            return "unchanged", status

        packets = _build_packets(config, image, status, resolution)
        uploaded = await transport.upload(packets, expected_resolution=resolution, retries=2)
        cache.save(digest=digest, synced_at=time.time(), resolution=resolution, battery_display=battery_display)
        return f"uploaded {len(packets)} packets", uploaded

    # Normal path: decide from local content first.
    view = dataclasses.replace(collect_view(config), battery_voltage=battery_display)
    image = render_dashboard(view, resolution, orientation=config.orientation)
    image.save(preview_path, format="PNG", optimize=False)
    digest = frame_digest(image)
    if not force and not should_upload(digest, previous):
        return "unchanged", None

    async def session(client):
        status = await transport._read_status(client)
        if status.resolution != resolution:
            raise ValueError(f"device resolution {status.resolution} does not match frame {resolution}")
        live_battery = quantize_battery_voltage(status.voltage, battery_display)
        live_view = dataclasses.replace(view, battery_voltage=live_battery)
        live_image = render_dashboard(live_view, resolution, orientation=config.orientation)
        live_image.save(preview_path, format="PNG", optimize=False)
        live_digest = frame_digest(live_image)
        if not force and not should_upload(live_digest, previous):
            cache.save(
                digest=live_digest,
                synced_at=time.time(),
                resolution=resolution,
                battery_display=live_battery,
            )
            return "unchanged", status, live_digest, live_battery, 0

        packets = _build_packets(config, live_image, status, resolution)
        await transport.write_packets(client, packets, expected_resolution=resolution, status=status)
        cache.save(
            digest=live_digest,
            synced_at=time.time(),
            resolution=resolution,
            battery_display=live_battery,
        )
        return f"uploaded {len(packets)} packets", status, live_digest, live_battery, len(packets)

    result, status, _digest, _battery, _count = await transport.with_client(session, retries=2)
    return result, status


def command_once(args) -> int:
    config = _config(args.config)
    result, status = asyncio.run(_once(config, force=args.force, preview_path=Path(args.preview)))
    print(result)
    if status is not None:
        print(json.dumps(dataclasses.asdict(status), ensure_ascii=False, indent=2))
    return 0


def wait_for_refresh(watcher, *, fallback_seconds: float, coalesce_seconds: float) -> bool:
    if not watcher.wait(fallback_seconds):
        return False
    watcher.wait_until_quiet(coalesce_seconds)
    return True


def command_run(args) -> int:
    config = _config(args.config)
    preview = Path(args.preview)
    assert config.codex_home is not None
    with CodexEventWatcher(config.codex_home) as watcher:
        while True:
            try:
                result, _status = asyncio.run(_once(config, force=False, preview_path=preview))
                print(time.strftime("%Y-%m-%d %H:%M:%S"), result, flush=True)
                view = collect_view(config, live_quota=False)
                delay = config.active_poll_seconds if view.active_projects else config.idle_poll_seconds
            except KeyboardInterrupt:
                return 0
            except Exception as exc:
                print(time.strftime("%Y-%m-%d %H:%M:%S"), f"retry: {exc}", file=sys.stderr, flush=True)
                delay = config.active_poll_seconds
            try:
                wait_for_refresh(
                    watcher,
                    fallback_seconds=delay,
                    coalesce_seconds=config.coalesce_seconds,
                )
            except KeyboardInterrupt:
                return 0


def command_stats(args) -> int:
    log_path = Path(args.log) if args.log else default_log_path()
    if not log_path.is_file():
        raise FileNotFoundError(f"log not found: {log_path}")
    days = load_log(log_path)
    since = args.since
    if args.last_days is not None and since is None and args.day is None:
        since = recent_day_bounds(args.last_days)
    selected = filter_days(days, day=args.day, since=since, last=args.last)
    if args.json:
        payload = [
            {
                "day": d.day,
                "uploaded": d.uploaded,
                "unchanged": d.unchanged,
                "retry": d.retry,
                "upload_ratio": round(d.upload_ratio, 4),
                "unchanged_ratio": round(d.unchanged_ratio, 4),
                "packets": d.packets,
                "max_upload_streak": d.max_upload_streak,
                "upload_bursts": d.upload_bursts,
                "service_start": d.service_start,
                "service_exit": d.service_exit,
                "service_error": d.service_error,
                "first_ts": d.first_ts,
                "last_ts": d.last_ts,
                "retries": dict(d.retries),
                "hourly": {h: dict(c) for h, c in sorted(d.hourly.items())},
            }
            for d in selected
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_report(selected, hourly=args.hourly))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex task/quota dashboard for SKD-CLOCK e-ink displays")
    parser.add_argument("--config", help="JSON configuration file")
    sub = parser.add_subparsers(dest="command", required=True)

    preview = sub.add_parser("preview", help="render without Bluetooth")
    preview.add_argument("--resolution", type=int, nargs=2, choices=range(104, 401))
    preview.add_argument("--all", action="store_true", help="render all supported panel profiles")
    preview.add_argument("--output", default="previews")
    preview.add_argument("--no-live-quota", action="store_true")
    preview.set_defaults(handler=command_preview)

    probe = sub.add_parser("probe", help="connect and read device status without image data")
    probe.set_defaults(handler=command_probe)

    once = sub.add_parser("once", help="render and upload one changed frame")
    once.add_argument("--force", action="store_true", help="upload even if the bitmap is unchanged")
    once.add_argument("--preview", default="previews/live.png")
    once.set_defaults(handler=command_once)

    run = sub.add_parser("run", help="keep monitoring at e-ink-safe intervals")
    run.add_argument("--preview", default="previews/live.png")
    run.set_defaults(handler=command_run)

    stats = sub.add_parser("stats", help="daily upload/unchanged/retry stats from dashboard.log")
    stats.add_argument("--log", help="path to dashboard.log (default: logs/dashboard.log)")
    stats.add_argument("--day", help="single day YYYY-MM-DD")
    stats.add_argument("--since", help="include days on/after YYYY-MM-DD")
    stats.add_argument("--last", type=int, help="keep only the last N days after other filters")
    stats.add_argument("--last-days", type=int, dest="last_days", help="shortcut: since (today - N + 1)")
    stats.add_argument("--hourly", action="store_true", help="include per-hour breakdown")
    stats.add_argument("--json", action="store_true", help="machine-readable JSON")
    stats.set_defaults(handler=command_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
