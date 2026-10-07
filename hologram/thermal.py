"""Thermal guard: the electronics sit against the wearer's head.

Video encoding is the hottest thing the Pi does, so recording stops when the
SoC passes ``stop_c`` and is refused until it cools below ``resume_c``.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def soc_temperature(path: str = "/sys/class/thermal/thermal_zone0/temp") -> float | None:
    try:
        return int(Path(path).read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


class ThermalGuard:
    def __init__(self, read_c: Callable[[], float | None], stop_c: float = 80.0, resume_c: float = 70.0) -> None:
        if resume_c >= stop_c:
            raise ValueError("resume_c must be below stop_c")
        self._read = read_c
        self.stop_c = stop_c
        self.resume_c = resume_c
        self.hot = False
        self.last_c: float | None = None

    def update(self) -> bool:
        """Re-read the sensor; returns True while too hot to record."""
        t = self._read()
        self.last_c = t
        if t is None:
            return self.hot
        if self.hot and t < self.resume_c:
            self.hot = False
        elif not self.hot and t >= self.stop_c:
            self.hot = True
        return self.hot
