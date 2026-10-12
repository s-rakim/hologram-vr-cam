"""Hologram Maker command line.

    python -m holomaker demo [--out DIR]
    python -m holomaker stereo LEFT RIGHT [--baseline-mm 63] [--hfov 66] [--out DIR]
    python -m holomaker rgbd IMAGE DEPTH.npy [--hfov 66] [--out DIR]
    python -m holomaker capture [--out DIR]          (Raspberry Pi 5, two cameras)
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np

from . import __version__
from .camera import Intrinsics
from .pipeline import MakerResult, MakerSettings, make_from_stereo, make_outputs
from .scene import demo_stereo_pair


def _settings(args: argparse.Namespace) -> MakerSettings:
    s = MakerSettings()
    s.hfov_deg = args.hfov
    s.baseline_m = args.baseline_mm / 1000.0
    s.max_disp = args.max_disp
    s.quilt_cols, s.quilt_rows = args.quilt
    s.view_span_m = args.span_mm / 1000.0
    s.subject_max_depth = args.subject_depth
    s.slices = args.slices
    return s


def _load(path: str) -> np.ndarray:
    from hologram.imageio import load_image
    return load_image(path)


def _report(res: MakerResult, out: Path) -> None:
    print(f"Output folder: {out}")
    for key, value in res.stats.items():
        print(f"  {key:18} {value:.3f}" if isinstance(value, float) and value % 1 else f"  {key:18} {value:g}")
    for key, path in res.files.items():
        print(f"  {key:18} {Path(path).name}")


def _out(args: argparse.Namespace, prefix: str) -> Path:
    return Path(args.out or tempfile.mkdtemp(prefix=prefix))


def cmd_demo(args: argparse.Namespace) -> int:
    """Synthetic stereo pair -> depth -> every output, checked against the true depth."""
    s = _settings(args)
    if s.subject_max_depth is None:
        s.subject_max_depth = 2.5          # drop the back wall so the ball and box float
    k = Intrinsics.from_fov(320, 240, s.hfov_deg)
    left, right, truth = demo_stereo_pair(k, s.baseline_m)
    out = _out(args, "holomaker-demo-")
    res = make_from_stereo(left, right, out, s, stem="demo")
    err = np.abs(res.depth - truth) / truth
    res.stats["median_depth_error_pct"] = float(np.median(err) * 100)
    _report(res, out)
    return 0


def cmd_stereo(args: argparse.Namespace) -> int:
    s = _settings(args)
    left, right = _load(args.left), _load(args.right)
    out = _out(args, "holomaker-")
    _report(make_from_stereo(left, right, out, s, stem=args.stem), out)
    return 0


def cmd_rgbd(args: argparse.Namespace) -> int:
    """For depth from another source: a depth camera, a phone LiDAR or a monocular model."""
    s = _settings(args)
    rgb = _load(args.image)
    depth = np.load(args.depth).astype(np.float32)
    if depth.shape != rgb.shape[:2]:
        print(f"depth is {depth.shape[1]}x{depth.shape[0]} but the image is {rgb.shape[1]}x{rgb.shape[0]}",
              file=sys.stderr)
        return 1
    out = _out(args, "holomaker-")
    _report(make_outputs(rgb, depth, out, s, stem=args.stem), out)
    return 0


def cmd_capture(args: argparse.Namespace) -> int:  # pragma: no cover - needs a Pi
    from hologram.imageio import write_png

    from .capture import capture_pair

    s = _settings(args)
    out = _out(args, "holomaker-capture-")
    out.mkdir(parents=True, exist_ok=True)
    left, right = capture_pair(*args.size)
    write_png(out / f"{args.stem}_left.png", left)
    write_png(out / f"{args.stem}_right.png", right)
    _report(make_from_stereo(left, right, out, s, stem=args.stem), out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holomaker", description="Turn stereo photos into 3D/hologram outputs")
    parser.add_argument("--version", action="version", version=__version__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", help="output folder (default: a new temp folder)")
    common.add_argument("--stem", default="hologram", help="output file name prefix")
    common.add_argument("--hfov", type=float, default=66.0, help="camera horizontal field of view, degrees")
    common.add_argument("--baseline-mm", type=float, default=63.0, help="distance between the two lenses")
    common.add_argument("--max-disp", type=int, default=64, help="largest disparity searched, pixels")
    common.add_argument("--quilt", type=int, nargs=2, default=(8, 6), metavar=("COLS", "ROWS"))
    common.add_argument("--span-mm", type=float, default=120.0, help="camera travel across the quilt views")
    common.add_argument("--subject-depth", type=float, help="remove background beyond this many metres")
    common.add_argument("--slices", type=int, default=16, help="depth slices for a volumetric display")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("demo", parents=[common], help="run the pipeline on a synthetic scene")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("stereo", parents=[common], help="rectified left/right photos -> outputs")
    p.add_argument("left")
    p.add_argument("right")
    p.set_defaults(func=cmd_stereo)

    p = sub.add_parser("rgbd", parents=[common], help="photo + depth map in metres (.npy) -> outputs")
    p.add_argument("image")
    p.add_argument("depth")
    p.set_defaults(func=cmd_rgbd)

    p = sub.add_parser("capture", parents=[common], help="capture with two Pi 5 cameras, then process")
    p.add_argument("--size", type=int, nargs=2, default=(1280, 960), metavar=("W", "H"))
    p.set_defaults(func=cmd_capture)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
