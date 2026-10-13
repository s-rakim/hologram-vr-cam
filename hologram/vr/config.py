"""Hologram VR helmet configuration.

Default pins match the wiring in cad/products/vr.py and the default optics
match the CAD model (tests check both). Override any value with a TOML file
(see config/vr.toml), e.g. after calibrating the mirrors for your build.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import PowerConfig, ThermalConfig, load_toml
from .optics import LensOptics, ReflectorOptics


@dataclass(frozen=True)
class PinConfig:
    """BCM GPIO numbers on the Pi 5 header."""

    mode_button: int = 17         # tap = next mode, hold 2 s = power off
    action_button: int = 27       # tap = next panorama / photo, hold = recentre
    volume_down: int = 13
    volume_up: int = 5
    display_power: int = 22       # load switch on the display board's 5 V (displays fully off in sleep)
    imu_interrupt: int = 4


@dataclass(frozen=True)
class DisplayConfig:
    enabled: bool = True
    size: tuple[int, int] = (2880, 1440)   # one HDMI signal, left half = left eye's panel
    render_scale: float = 0.5              # render 720 x 720 per eye and scale up
    fps: int = 60
    optics: str = "reflector"              # reflector (brow panels + visor mirrors) | lens
    start_mode: str = "panorama"           # panorama | gallery | passthrough
    motion_threshold_deg: float = 0.05     # a still view is not re-rendered
    sleep_after_still_s: float = 60.0      # displays off when the helmet is put down
    wake_threshold_deg: float = 2.0

    def eye_size(self) -> tuple[int, int]:
        """Rendered pixels per eye (the GPU scales the frame up to the panels)."""
        w, h = self.size
        return max(8, int(w / 2 * self.render_scale)), max(8, int(h * self.render_scale))


@dataclass(frozen=True)
class TrackingConfig:
    enabled: bool = True
    i2c_bus: int = 1
    address: int = 0x68
    rate_hz: float = 200.0                 # matches the MPU-6050's 200 Hz sample rate (hologram/imu.py)
    beta: float = 0.05
    calibration_samples: int = 400
    axis_map: tuple[str, str, str] = ("x", "y", "z")


@dataclass(frozen=True)
class MediaConfig:
    panoramas: str = "~/Pictures/Hologram/360"   # 2:1 equirectangular photos (+ optional .wav beside each)
    photos: str = "~/DCIM/Hologram"              # photos copied over from the Hologram Cam glasses
    screen_width_m: float = 2.4
    screen_distance_m: float = 2.0


@dataclass(frozen=True)
class PassthroughConfig:
    enabled: bool = True
    size: tuple[int, int] = (1280, 720)
    hfov_deg: float = 102.0                # Camera Module 3 Wide
    zoom: float = 1.0                      # 1 = the room at its true size


@dataclass(frozen=True)
class SoundConfig:
    enabled: bool = True
    device: str = "plughw:CARD=sndrpihifiberry,DEV=0"   # the I2S amps (hifiberry-dac overlay); list: aplay -L
    volume: float = 0.35
    volume_step: float = 0.05
    ear_pattern: float = 0.5      # virtual ear microphones: 1 = omni, 0.5 = cardioid, 0 = figure-of-eight


@dataclass(frozen=True)
class VrConfig:
    pins: PinConfig = field(default_factory=PinConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    reflector: ReflectorOptics = field(default_factory=ReflectorOptics)
    lens: LensOptics = field(default_factory=LensOptics)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    media: MediaConfig = field(default_factory=MediaConfig)
    passthrough: PassthroughConfig = field(default_factory=PassthroughConfig)
    sound: SoundConfig = field(default_factory=SoundConfig)
    thermal: ThermalConfig = field(default_factory=ThermalConfig)
    power: PowerConfig = field(default_factory=PowerConfig)

    def optics(self) -> ReflectorOptics | LensOptics:
        return self.reflector if self.display.optics == "reflector" else self.lens


def load_config(path: str | Path | None = None) -> VrConfig:
    cfg = load_toml(VrConfig(), path)
    if cfg.display.start_mode not in ("panorama", "gallery", "passthrough"):
        raise ValueError("display.start_mode must be panorama, gallery or passthrough")
    if cfg.display.optics not in ("reflector", "lens"):
        raise ValueError("display.optics must be reflector or lens")
    if not 0.0 <= cfg.sound.ear_pattern <= 1.0:
        raise ValueError("sound.ear_pattern must be between 0 and 1")
    return cfg
