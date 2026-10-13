"""Hologram VR headset command line.

    python -m hologram.vr run [--config FILE] [--mock] [--window]
    python -m hologram.vr demo [--out DIR]
    python -m hologram.vr snapshot [--mode panorama|gallery|passthrough] [--yaw DEG] [--pitch DEG] [--out FILE]
    python -m hologram.vr imu-check
    python -m hologram.vr optics [--config FILE]
    python -m hologram.vr eye-view [--yaw DEG] [--out FILE]

Every command reads /etc/hologram/vr.toml when it exists (the helmet's installed
settings), unless --config FILE says otherwise.
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from .. import __version__
from .. import quaternion as qt
from ..imageio import write_png
from .app import Mode, VrApp, system_poweroff
from .config import load_config
from .hardware import build_mock, build_pi
from .optics import ReflectorOptics, eye_view, field_of_view


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    hw = build_mock(cfg, windowed=args.window) if args.mock else build_pi(cfg, windowed=args.window)
    VrApp(cfg, hw, shutdown=None if args.mock else system_poweroff).run()
    return 0


def _mock_app(args: argparse.Namespace, mode: str = "panorama", clock=None, scale: float = 0.25) -> VrApp:
    cfg = load_config(args.config)
    cfg = replace(cfg, display=replace(cfg.display, start_mode=mode, render_scale=scale))
    return VrApp(cfg, build_mock(cfg), **({"clock": clock} if clock else {}))


def cmd_demo(args: argparse.Namespace) -> int:
    """Headless walk-through: render each mode, show render-skipping and sleep."""
    out = Path(args.out or tempfile.mkdtemp(prefix="hologram-vr-demo-"))
    out.mkdir(parents=True, exist_ok=True)
    clock = [0.0]
    app = _mock_app(args, clock=lambda: clock[0])
    app.tracking_live = True              # as if the IMU were running, so the helmet can sleep

    def tap(which: str) -> None:
        app.press(which, True)
        app.step()
        clock[0] += 0.1
        app.press(which, False)
        app.step()

    print(f"Frames folder: {out}")
    for _ in Mode:
        frame = app.render()
        if frame is not None:
            write_png(out / f"{app.mode.value}.png", frame)
        print(f"{app.mode.value:12} rendered {frame.shape[1]}x{frame.shape[0]}" if frame is not None
              else f"{app.mode.value:12} (no frame)")
        print(f"{'':12} still head, second render skipped: {app.render() is None}")
        tap("mode")
    tap("volume_up")
    print(f"volume up -> {app.audio.volume:.2f}")
    clock[0] += app.cfg.display.sleep_after_still_s + 1
    app.step()
    print(f"left still for {app.cfg.display.sleep_after_still_s:.0f} s -> asleep: {app.asleep}")
    app.close()
    print("\nEvents:", *[f"  {k:10} {v}" for k, v in app.history], sep="\n")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    """Render one side-by-side frame to a PNG (check lens settings off-device)."""
    app = _mock_app(args, args.mode)
    q = qt.mul(qt.yaw_quat(math.radians(args.yaw)), qt.from_axis_angle((1, 0, 0), math.radians(args.pitch)))
    app.tracker.set_orientation(q)
    frame = app.render()
    if frame is None:
        print("nothing to render", file=sys.stderr)
        return 1
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    write_png(args.out, frame)
    print(f"wrote {args.out} ({frame.shape[1]}x{frame.shape[0]}, mode={args.mode})")
    return 0


def cmd_eye_view(args: argparse.Namespace) -> int:
    """Simulate what each eye sees through the optics (pre-warped panel -> mirror -> eye)."""
    app = _mock_app(args, "panorama", scale=0.6)
    app.tracker.set_orientation(qt.yaw_quat(math.radians(args.yaw)))
    frame = app.render()
    left_t, right_t = app.tables()
    w = left_t.shape[1]
    eyes = [eye_view(frame[:, :w], left_t, args.size, args.fov), eye_view(frame[:, w:], right_t, args.size, args.fov)]
    gap = np.full((args.size, 8, frame.shape[2]), 255, np.uint8)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    write_png(args.out, np.concatenate([eyes[0], gap, eyes[1]], axis=1))
    print(f"wrote {args.out}: left and right eye, {args.fov:.0f} deg across each")
    return 0


def cmd_imu_check(args: argparse.Namespace) -> int:
    """Print live head orientation from the real IMU (Ctrl+C to stop)."""
    from ..fusion import HeadTracker
    from ..imu import MPU6050

    cfg = load_config(args.config)
    imu = MPU6050(cfg.tracking.i2c_bus, cfg.tracking.address, cfg.tracking.axis_map)
    tracker = HeadTracker(cfg.tracking.beta)
    print("Keep the headset still for calibration...")
    samples = []
    for _ in range(cfg.tracking.calibration_samples):
        s = imu.read()
        samples.append((s.gyro, s.accel))
        time.sleep(1 / cfg.tracking.rate_hz)
    print("gyro bias rad/s:", tracker.calibrate(samples))
    last = 0.0
    try:
        while True:
            s = imu.read()
            now = time.monotonic()
            tracker.update(s.gyro, s.accel, now)
            if now - last > 0.2:
                q = tracker.orientation()
                print(f"\ryaw {math.degrees(qt.yaw(q)):7.1f}   pitch {math.degrees(qt.pitch(q)):6.1f}", end="")
                last = now
            time.sleep(1 / cfg.tracking.rate_hz)
    except KeyboardInterrupt:
        print()
    return 0


def cmd_optics(args: argparse.Namespace) -> int:
    """Field of view and mirror numbers for the configured optics (ray traced)."""
    cfg = load_config(args.config)
    optics = cfg.optics()
    fov = field_of_view(optics)
    print(f"optics: {cfg.display.optics}")
    print(f"field of view, both eyes: {fov.horizontal:.0f} deg horizontal x {fov.vertical:.0f} deg vertical")
    print(f"per eye: {fov.per_eye_horizontal:.0f} deg ({fov.nasal:.0f} nasal + {fov.temporal:.0f} temporal), "
          f"stereo overlap {fov.overlap:.0f} deg")
    if isinstance(optics, ReflectorOptics):
        centre, _, _ = optics.display_frame()
        print(f"mirror: ellipsoid 2a = {optics.major_axis():.1f} mm, focal length {optics.focal_length():.1f} mm")
        print("right display centre (mm from between the eyes): "
              f"x {centre[0]:.1f}, y {centre[1]:.1f}, z {centre[2]:.1f}")
    return 0


SYSTEM_CONFIG = Path("/etc/hologram/vr.toml")    # written by deploy/setup_pi5.sh


def _default_config() -> str | None:
    """Commands use the helmet's installed settings unless told otherwise."""
    return str(SYSTEM_CONFIG) if SYSTEM_CONFIG.is_file() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hologram.vr", description="Hologram VR headset")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="run the headset")
    p.add_argument("--config", default=_default_config(),
                   help="TOML config file (default: /etc/hologram/vr.toml if it exists, else built-in settings)")
    p.add_argument("--mock", action="store_true", help="fake hardware (desktop)")
    p.add_argument("--window", action="store_true",
                   help="show output in a window (M = mode, SPACE = action, -/= = volume)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("demo", help="headless walk-through with mock hardware")
    p.add_argument("--config", default=_default_config())
    p.add_argument("--out", help="folder for the rendered frames")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("snapshot", help="render one stereo frame to PNG")
    p.add_argument("--config", default=_default_config())
    p.add_argument("--mode", choices=[m.value for m in Mode], default="panorama")
    p.add_argument("--yaw", type=float, default=0.0, help="degrees, left positive")
    p.add_argument("--pitch", type=float, default=0.0, help="degrees, up positive")
    p.add_argument("--out", default="hologram_frame.png")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("optics", help="print the field of view of the configured optics")
    p.add_argument("--config", default=_default_config())
    p.set_defaults(func=cmd_optics)

    p = sub.add_parser("eye-view", help="simulate what each eye sees through the optics")
    p.add_argument("--config", default=_default_config())
    p.add_argument("--yaw", type=float, default=0.0)
    p.add_argument("--size", type=int, default=480)
    p.add_argument("--fov", type=float, default=140.0)
    p.add_argument("--out", default="hologram_eye_view.png")
    p.set_defaults(func=cmd_eye_view)

    p = sub.add_parser("imu-check", help="print live orientation from the IMU")
    p.add_argument("--config", default=_default_config())
    p.set_defaults(func=cmd_imu_check)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING if args.cmd != "run" else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
