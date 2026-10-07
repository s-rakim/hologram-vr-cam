"""Command line entry point.

    python -m hologram run [--config FILE] [--mock] [--window]
    python -m hologram demo [--out DIR]
    python -m hologram snapshot [--mode panorama|passthrough] [--yaw DEG] [--pitch DEG] [--out FILE]
    python -m hologram imu-check
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

from . import __version__
from . import quaternion as qt
from .app import HologramApp, Mode, system_poweroff
from .config import load_config
from .hardware import build_mock, build_pi
from .imageio import write_png


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    hw = build_mock(cfg, windowed=args.window) if args.mock else build_pi(cfg, windowed=args.window)
    HologramApp(cfg, hw, shutdown=None if args.mock else system_poweroff).run()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Headless walk-through with mock hardware: photo, video, mode switch."""
    out = Path(args.out or tempfile.mkdtemp(prefix="hologram-demo-"))
    cfg = load_config(args.config)
    cfg = replace(cfg, capture=replace(cfg.capture, media_dir=str(out), min_free_mb=0))
    app = HologramApp(cfg, build_mock(cfg))

    def press(source: str, seconds: float) -> None:
        (app.on_button if source == "button" else app.on_touch)(True)
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.step()
            time.sleep(0.02)
        (app.on_button if source == "button" else app.on_touch)(False)
        app.step()

    print(f"Media folder: {out}")
    press("button", 0.1)
    print("tap capture button  -> photo")
    press("button", 0.8)
    print("hold capture button -> recording (privacy LED on:", app.led.recording, ")")
    write_png(out / "preview_panorama_recording.png", app.render())
    time.sleep(1.0)
    press("button", 0.1)
    print("tap capture button  -> stop video")
    press("touch", 0.1)
    time.sleep(0.5)
    app.step()
    print("tap touch strip     -> mode:", app.mode.value)
    write_png(out / "preview_passthrough.png", app.render())
    app.close()
    print("\nEvents:")
    for kind, info in app.history:
        print(f"  {kind:14} {info}")
    print("\nFiles:", *sorted(p.name for p in out.iterdir()), sep="\n  ")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    """Render one side-by-side frame to a PNG (check optics settings off-device)."""
    cfg = load_config(args.config)
    cfg = replace(cfg, display=replace(cfg.display, start_mode=args.mode))
    app = HologramApp(cfg, build_mock(cfg))
    q = qt.mul(qt.yaw_quat(math.radians(args.yaw)), qt.from_axis_angle((1, 0, 0), math.radians(args.pitch)))
    app.tracker.set_orientation(q)
    frame = app.render()
    if frame is None:
        print("display mode is off: nothing to render", file=sys.stderr)
        return 1
    write_png(args.out, frame)
    print(f"wrote {args.out} ({frame.shape[1]}x{frame.shape[0]}, mode={Mode(args.mode).value})")
    return 0


def cmd_imu_check(args: argparse.Namespace) -> int:
    """Print live head orientation from the real IMU (Ctrl+C to stop)."""
    from .fusion import HeadTracker
    from .imu import MPU6050

    cfg = load_config(args.config)
    imu = MPU6050(cfg.tracking.i2c_bus, cfg.tracking.address, cfg.tracking.axis_map)
    tracker = HeadTracker(cfg.tracking.beta)
    print("Keep the glasses still for calibration...")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hologram", description="Hologram VR Cam glasses")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="run the glasses")
    p.add_argument("--config", help="TOML config file")
    p.add_argument("--mock", action="store_true", help="fake hardware (desktop)")
    p.add_argument("--window", action="store_true", help="show output in a window (SPACE=button, T=touch)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("demo", help="headless walk-through with mock hardware")
    p.add_argument("--config")
    p.add_argument("--out", help="folder for the demo media")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("snapshot", help="render one stereo frame to PNG")
    p.add_argument("--config")
    p.add_argument("--mode", choices=["panorama", "passthrough"], default="panorama")
    p.add_argument("--yaw", type=float, default=0.0, help="degrees, left positive")
    p.add_argument("--pitch", type=float, default=0.0, help="degrees, up positive")
    p.add_argument("--out", default="hologram_frame.png")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("imu-check", help="print live orientation from the IMU")
    p.add_argument("--config")
    p.set_defaults(func=cmd_imu_check)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
