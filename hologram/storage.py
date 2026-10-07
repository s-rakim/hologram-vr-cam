"""Where photos and videos go, and whether there is room for more."""
from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

EXTENSIONS = {"video": "mp4", "photo": "jpg"}


class MediaStore:
    def __init__(self, root: str | Path, min_free_mb: int = 500,
                 disk_usage: Callable[[Path], tuple[int, int, int]] = shutil.disk_usage,
                 clock: Callable[[], datetime] = datetime.now) -> None:
        self.root = Path(root).expanduser()
        self.min_free_mb = min_free_mb
        self._disk_usage = disk_usage
        self._clock = clock

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def free_mb(self) -> float:
        self.ensure()
        return self._disk_usage(self.root)[2] / 1_000_000

    def has_space(self) -> bool:
        return self.free_mb() >= self.min_free_mb

    def new_path(self, kind: str) -> Path:
        """HVR_20260107_143015.mp4, with _2, _3... if that second is taken."""
        self.ensure()
        stem = "HVR_" + self._clock().strftime("%Y%m%d_%H%M%S")
        ext = EXTENSIONS[kind]
        path = self.root / f"{stem}.{ext}"
        n = 2
        while path.exists():
            path = self.root / f"{stem}_{n}.{ext}"
            n += 1
        return path

    def media(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(p for p in self.root.iterdir() if p.suffix.lstrip(".") in EXTENSIONS.values())
