"""Configuration: dataclass defaults, optionally overridden by a TOML file.

The default pin numbers match the wiring in cad/spec.py (a test enforces it).
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PinConfig:
    """BCM GPIO numbers."""

    capture_button: int = 17      # active low, internal pull-up
    touch: int = 27               # TTP223 output, active high
    privacy_led: int = 22         # 2N7002 gate
    low_battery: int = 23         # PowerBoost LBO through a Schottky, active low
    imu_interrupt: int = 4


@dataclass(frozen=True)
class CaptureConfig:
    media_dir: str = "~/DCIM/Hologram"
    video_size: tuple[int, int] = (1920, 1080)
    framerate: int = 30
    bitrate: int = 10_000_000
    max_clip_seconds: float = 60.0    # Ray-Ban Meta style default; raise to 180 if you like
    record_audio: bool = True
    audio_device: str = "plughw:CARD=sndrpigooglevoi"   # ALSA capture device; list with: arecord -L
    min_free_mb: int = 500


@dataclass(frozen=True)
class DisplayConfig:
    enabled: bool = True
    size: tuple[int, int] = (1920, 1080)   # full side-by-side frame sent over HDMI
    render_scale: float = 0.5              # render at half resolution, scale up on output
    fps: int = 30
    eye_fov_deg: float = 45.0              # horizontal field of view of one eye
    k1: float = 0.0                        # radial pre-distortion; birdbath optics need ~0
    k2: float = 0.0
    lens_center_shift: float = 0.0         # +ve moves each lens centre towards the nose
    passthrough_zoom: float = 1.0
    start_mode: str = "panorama"           # panorama | passthrough | off
    panorama: str = ""                     # equirectangular image; empty = built-in grid world


@dataclass(frozen=True)
class TrackingConfig:
    enabled: bool = True
    i2c_bus: int = 1
    address: int = 0x68
    rate_hz: float = 200.0
    beta: float = 0.05                     # Madgwick gain: higher trusts the accelerometer more
    calibration_samples: int = 200
    axis_map: tuple[str, str, str] = ("x", "y", "z")   # device x/y/z from sensor axes, e.g. ("-y", "x", "z")


@dataclass(frozen=True)
class ThermalConfig:
    sensor_path: str = "/sys/class/thermal/thermal_zone0/temp"
    stop_recording_c: float = 80.0
    resume_c: float = 70.0


@dataclass(frozen=True)
class PowerConfig:
    shutdown_on_low_battery: bool = True


@dataclass(frozen=True)
class Config:
    pins: PinConfig = field(default_factory=PinConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    thermal: ThermalConfig = field(default_factory=ThermalConfig)
    power: PowerConfig = field(default_factory=PowerConfig)


def _merge(obj: Any, data: dict[str, Any], where: str) -> Any:
    known = {f.name: f for f in fields(obj)}
    changes: dict[str, Any] = {}
    for key, value in data.items():
        if key not in known:
            raise ValueError(f"unknown config key {where}{key}")
        current = getattr(obj, key)
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ValueError(f"{where}{key} must be a table")
            changes[key] = _merge(current, value, f"{where}{key}.")
        elif isinstance(current, tuple):
            if not isinstance(value, (list, tuple)) or len(value) != len(current):
                raise ValueError(f"{where}{key} must be a list of {len(current)} items")
            changes[key] = tuple(value)
        elif isinstance(current, bool):
            if not isinstance(value, bool):
                raise ValueError(f"{where}{key} must be true or false")
            changes[key] = value
        elif isinstance(current, float) and isinstance(value, (int, float)) and not isinstance(value, bool):
            changes[key] = float(value)
        elif isinstance(current, int) and isinstance(value, int) and not isinstance(value, bool):
            changes[key] = value
        elif isinstance(current, str) and isinstance(value, str):
            changes[key] = value
        else:
            raise ValueError(f"{where}{key} has the wrong type")
    return replace(obj, **changes)


def load_config(path: str | Path | None = None) -> Config:
    """Defaults, overridden by the TOML file at ``path`` if given."""
    cfg = Config()
    if path is None:
        return cfg
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    cfg = _merge(cfg, data, "")
    if cfg.display.start_mode not in ("panorama", "passthrough", "off"):
        raise ValueError("display.start_mode must be panorama, passthrough or off")
    if cfg.thermal.resume_c >= cfg.thermal.stop_recording_c:
        raise ValueError("thermal.resume_c must be below thermal.stop_recording_c")
    return cfg
