"""Pinhole camera model shared by the depth, point cloud and view code."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Intrinsics:
    """Pinhole intrinsics in pixels. Image x runs right, y runs down."""

    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float

    @classmethod
    def from_fov(cls, width: int, height: int, hfov_deg: float) -> Intrinsics:
        """Square pixels, principal point at the image centre."""
        f = width / 2.0 / math.tan(math.radians(hfov_deg) / 2.0)
        return cls(width, height, f, f, width / 2.0, height / 2.0)

    def scaled(self, width: int, height: int) -> Intrinsics:
        """The same camera at another resolution (for downscaled processing)."""
        sx, sy = width / self.width, height / self.height
        return Intrinsics(width, height, self.fx * sx, self.fy * sy, self.cx * sx, self.cy * sy)
