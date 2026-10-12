"""One call from a stereo pair (or RGB + depth) to every output format."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from hologram.imageio import write_png

from .camera import Intrinsics
from .depth import disparity_to_depth, fill_from_background, stereo_disparity
from .outputs import (
    anaglyph,
    contact_sheet,
    depth_preview,
    isolate,
    pepper_ghost,
    quilt,
    quilt_name,
    side_by_side,
    volume_slices,
)
from .pointcloud import to_points, write_ply
from .views import shift_view, view_sweep


@dataclass
class MakerSettings:
    hfov_deg: float = 66.0          # Raspberry Pi Camera Module 3 (standard lens)
    baseline_m: float = 0.063       # distance between the two lenses
    max_disp: int = 64              # largest disparity searched, pixels (sets the nearest depth)
    window_radius: int = 3          # matching window is (2r+1)^2
    quilt_cols: int = 8
    quilt_rows: int = 6
    view_span_m: float = 0.12       # camera travel across all quilt views
    subject_max_depth: float | None = None   # black out the background beyond this (pyramid, volume)
    slices: int = 16
    pyramid_size: int = 1080
    point_stride: int = 1


@dataclass
class MakerResult:
    depth: np.ndarray
    files: dict[str, str] = field(default_factory=dict)
    stats: dict[str, float] = field(default_factory=dict)


def depth_from_stereo(left: np.ndarray, right: np.ndarray, s: MakerSettings) -> tuple[np.ndarray, float]:
    """Metric depth for the left image (holes filled) and the fraction matched."""
    k = Intrinsics.from_fov(left.shape[1], left.shape[0], s.hfov_deg)
    disp = stereo_disparity(left, right, s.max_disp, s.window_radius)
    valid = float(np.isfinite(disp).mean())
    depth = disparity_to_depth(disp, k.fx, s.baseline_m)
    if not np.isfinite(depth).any():
        raise ValueError("no stereo matches: check the pair is rectified and max_disp is large enough")
    return fill_from_background(depth)[0], valid


def make_outputs(rgb: np.ndarray, depth: np.ndarray, out_dir: str | Path, s: MakerSettings,
                 stem: str = "hologram", stats: dict[str, float] | None = None) -> MakerResult:
    """Write the point cloud, quilt, pyramid layout, slices and stereo images."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    h, w = depth.shape
    k = Intrinsics.from_fov(w, h, s.hfov_deg)
    res = MakerResult(depth=depth, stats=dict(stats or {}))

    def save(key: str, name: str, img: np.ndarray) -> None:
        write_png(out / name, img)
        res.files[key] = str(out / name)

    save("image", f"{stem}_image.png", rgb)
    save("depth", f"{stem}_depth.png", depth_preview(depth))
    np.save(out / f"{stem}_depth_m.npy", depth)
    res.files["depth_m"] = str(out / f"{stem}_depth_m.npy")

    pts, cols = to_points(rgb, depth, k, s.point_stride, s.subject_max_depth)
    write_ply(out / f"{stem}.ply", pts, cols)
    res.files["point_cloud"] = str(out / f"{stem}.ply")

    left, _ = shift_view(rgb, depth, k.fx, -s.baseline_m / 2)
    right, _ = shift_view(rgb, depth, k.fx, +s.baseline_m / 2)
    save("side_by_side", f"{stem}_sbs.png", side_by_side(left, right))
    save("anaglyph", f"{stem}_anaglyph.png", anaglyph(left, right))

    n = s.quilt_cols * s.quilt_rows
    views = view_sweep(rgb, depth, k.fx, n, s.view_span_m)
    save("quilt", quilt_name(stem, s.quilt_cols, s.quilt_rows, w, h), quilt(views, s.quilt_cols, s.quilt_rows))

    subject_depth = depth if s.subject_max_depth is None else np.where(depth <= s.subject_max_depth, depth, np.nan)
    subject = rgb if s.subject_max_depth is None else isolate(rgb, depth, s.subject_max_depth)
    side_l, _ = shift_view(subject, depth, k.fx, -s.view_span_m / 2)
    side_r, _ = shift_view(subject, depth, k.fx, +s.view_span_m / 2)
    save("pyramid", f"{stem}_pyramid.png",
         pepper_ghost(subject, s.pyramid_size, right=side_r, left=side_l))

    # Percentiles, not min/max, so a few mismatched pixels don't stretch the slice range.
    near, far = (float(v) for v in np.nanpercentile(subject_depth, [1, 99]))
    slices, edges = volume_slices(rgb, subject_depth, s.slices, near, far)
    sdir = out / f"{stem}_slices"
    sdir.mkdir(exist_ok=True)
    for i, sl in enumerate(slices):
        write_png(sdir / f"slice_{i:03d}.png", sl)
    res.files["slices"] = str(sdir)
    save("slice_sheet", f"{stem}_slices.png", contact_sheet(slices, cols=math.ceil(math.sqrt(s.slices))))

    finite = depth[np.isfinite(depth)]
    res.stats.update(points=float(len(pts)), depth_min_m=float(finite.min()), depth_max_m=float(finite.max()))
    meta = {"settings": asdict(s), "stats": res.stats, "slice_edges_m": edges.round(4).tolist(),
            "files": {key: Path(p).name for key, p in res.files.items()}}
    (out / f"{stem}.json").write_text(json.dumps(meta, indent=2))
    res.files["manifest"] = str(out / f"{stem}.json")
    return res


def make_from_stereo(left: np.ndarray, right: np.ndarray, out_dir: str | Path, s: MakerSettings,
                     stem: str = "hologram") -> MakerResult:
    depth, valid = depth_from_stereo(left, right, s)
    res = make_outputs(left, depth, out_dir, s, stem, stats={"matched_fraction": valid})
    write_png(Path(out_dir) / f"{stem}_input_sbs.png", side_by_side(left, right))
    res.files["input_sbs"] = str(Path(out_dir) / f"{stem}_input_sbs.png")
    return res
