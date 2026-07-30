from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image


def frame_digest(image: Image.Image) -> str:
    payload = f"{image.width}x{image.height}:{image.mode}:".encode("ascii") + image.tobytes()
    return hashlib.sha256(payload).hexdigest()


def should_upload(current_digest: str, previous_digest: str | None) -> bool:
    return not previous_digest or current_digest != previous_digest


def quantize_sync_time(epoch: float, interval_seconds: int = 300) -> float:
    return float(int(epoch) - int(epoch) % interval_seconds)


def quantize_battery_voltage(
    voltage: float | None,
    previous_display: float | None = None,
    *,
    step: float = 0.1,
    hold: float = 0.08,
) -> float | None:
    """Stabilize BAT x.xV so millivolt noise cannot force full-frame refreshes.

    Keep the last displayed 0.1 V bucket until the live voltage moves at least
    ``hold`` volts away from that displayed value, then snap to the nearest step.
    """
    if voltage is None:
        return previous_display
    if previous_display is None or abs(float(voltage) - float(previous_display)) >= hold:
        return round(round(float(voltage) / step) * step, 1)
    return round(float(previous_display), 1)


class FrameCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save(
        self,
        *,
        digest: str,
        synced_at: float,
        resolution: tuple[int, int],
        battery_display: float | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict = {
            "frame_digest": digest,
            "synced_at": synced_at,
            "resolution": list(resolution),
        }
        if battery_display is not None:
            payload["battery_display"] = round(float(battery_display), 1)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
