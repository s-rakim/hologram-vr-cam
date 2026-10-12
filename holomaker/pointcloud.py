"""RGB-D -> coloured point cloud, saved as binary PLY.

PLY opens in MeshLab, CloudCompare, Blender (File > Import > PLY) and three.js.
Output axes follow the usual 3D-tool convention: X right, Y up, and the camera
looking down -Z, so the cloud appears the right way up in any viewer.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .camera import Intrinsics


def backproject(depth: np.ndarray, k: Intrinsics) -> np.ndarray:
    """(H, W) metres -> (H, W, 3) points in camera axes (x right, y down, z forward)."""
    h, w = depth.shape
    u, v = np.meshgrid(np.arange(w, dtype=np.float32) + 0.5, np.arange(h, dtype=np.float32) + 0.5)
    return np.stack([(u - k.cx) / k.fx * depth, (v - k.cy) / k.fy * depth, depth], -1)


def to_points(rgb: np.ndarray, depth: np.ndarray, k: Intrinsics, stride: int = 1,
              max_depth: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Valid pixels as (N, 3) float32 points (X right, Y up, -Z forward) and (N, 3) uint8 colours."""
    if rgb.shape[:2] != depth.shape:
        raise ValueError("rgb and depth must have the same height and width")
    xyz = backproject(depth, k)[::stride, ::stride].reshape(-1, 3)
    col = rgb[::stride, ::stride, :3].reshape(-1, 3)
    ok = np.isfinite(xyz).all(axis=1) & (xyz[:, 2] > 0)
    if max_depth is not None:
        ok &= xyz[:, 2] <= max_depth
    pts = xyz[ok] * np.array([1, -1, -1], dtype=np.float32)
    return pts.astype(np.float32), col[ok].astype(np.uint8)


_PLY_DTYPE = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("red", "u1"), ("green", "u1"), ("blue", "u1")])


def write_ply(path: str | Path, points: np.ndarray, colors: np.ndarray) -> None:
    """Binary little-endian PLY with float xyz and uchar rgb per vertex."""
    if len(points) != len(colors):
        raise ValueError("points and colors must have the same length")
    rec = np.empty(len(points), dtype=_PLY_DTYPE)
    rec["x"], rec["y"], rec["z"] = points[:, 0], points[:, 1], points[:, 2]
    rec["red"], rec["green"], rec["blue"] = colors[:, 0], colors[:, 1], colors[:, 2]
    header = (
        "ply\nformat binary_little_endian 1.0\ncomment hologram-vr-cam holomaker\n"
        f"element vertex {len(rec)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
    )
    Path(path).write_bytes(header.encode("ascii") + rec.tobytes())


def read_ply(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Read a PLY written by :func:`write_ply` back into (points, colors)."""
    data = Path(path).read_bytes()
    end = data.index(b"end_header\n") + len(b"end_header\n")
    header = data[:end].decode("ascii").splitlines()
    if "format binary_little_endian 1.0" not in header:
        raise ValueError("only binary little-endian PLY written by write_ply is supported")
    count = next(int(line.split()[2]) for line in header if line.startswith("element vertex"))
    rec = np.frombuffer(data, dtype=_PLY_DTYPE, count=count, offset=end)
    pts = np.stack([rec["x"], rec["y"], rec["z"]], -1)
    return pts, np.stack([rec["red"], rec["green"], rec["blue"]], -1)
