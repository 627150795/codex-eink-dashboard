from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .models import SUPPORTED_RESOLUTIONS


@dataclass(frozen=True)
class AppConfig:
    device_name_prefix: str = "SKD-CLOCK"
    device_address: str | None = None
    resolution: tuple[int, int] | None = None
    active_poll_seconds: int = 30
    idle_poll_seconds: int = 60
    coalesce_seconds: float = 1.0
    privacy_mode: str = "summary"
    account_mode: str = "auto"
    scan_timeout_seconds: float = 12.0
    status_timeout_seconds: float = 8.0
    image_index: int = 0
    orientation: str = "landscape"
    codex_home: Path | None = None

    def __post_init__(self) -> None:
        if self.resolution is not None:
            value = tuple(int(item) for item in self.resolution)
            if value not in SUPPORTED_RESOLUTIONS:
                raise ValueError(f"unsupported panel resolution: {value}")
            object.__setattr__(self, "resolution", value)
        if self.privacy_mode not in {"summary", "titles"}:
            raise ValueError("privacy_mode must be 'summary' or 'titles'")
        if self.account_mode not in {"auto", "api"}:
            raise ValueError("account_mode must be 'auto' or 'api'")
        if not 0 <= self.image_index <= 6:
            raise ValueError("image_index must be between 0 and 6")
        if self.orientation not in {"landscape", "portrait_cw", "portrait_ccw"}:
            raise ValueError("orientation must be landscape, portrait_cw, or portrait_ccw")
        if self.active_poll_seconds < 30 or self.idle_poll_seconds < 60:
            raise ValueError("poll intervals are too aggressive for an e-ink display")
        if self.coalesce_seconds <= 0:
            raise ValueError("coalesce_seconds must be greater than zero")
        if self.codex_home is None:
            root = os.environ.get("CODEX_HOME")
            object.__setattr__(self, "codex_home", Path(root) if root else Path.home() / ".codex")
        elif not isinstance(self.codex_home, Path):
            object.__setattr__(self, "codex_home", Path(self.codex_home))

    @classmethod
    def load(cls, path: str | Path | None = None) -> "AppConfig":
        if path is None:
            return cls()
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if payload.get("resolution") is not None:
            payload["resolution"] = tuple(payload["resolution"])
        if payload.get("codex_home") is not None:
            payload["codex_home"] = Path(payload["codex_home"])
        return cls(**payload)
