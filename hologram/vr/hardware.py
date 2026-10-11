"""Build the real (Raspberry Pi 5) or mock hardware for the VR headset."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from ..fuelgauge import MAX17048, FuelGauge, MockFuelGauge
from ..imu import MPU6050, Imu, MockImu
from ..thermal import soc_temperature
from .audio import MemorySink, Sink, aplay_factory
from .config import VrConfig
from .display import Display, NullDisplay, PygameDisplay

log = logging.getLogger(__name__)
EdgeCallback = Callable[[bool], None]
BUTTONS = ("mode", "action", "volume_down", "volume_up")


class PreviewCamera(Protocol):
    """Passthrough camera: only powered while passthrough mode is on."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def frame(self) -> np.ndarray | None: ...


@dataclass
class VrHardware:
    camera: PreviewCamera | None
    imu: Imu | None
    display: Display
    audio_sink: Callable[[int], Sink]                       # sample rate -> stereo output
    gauge: FuelGauge | None
    read_temperature: Callable[[], float | None]
    bind_inputs: Callable[[dict[str, EdgeCallback]], None]  # button name (BUTTONS) -> edge callback
    set_display_power: Callable[[bool], None]
    keep: list[object] = field(default_factory=list)


class Picamera2Preview:
    def __init__(self, size: tuple[int, int]) -> None:
        from picamera2 import Picamera2

        self.cam = Picamera2()
        self.cam.configure(self.cam.create_preview_configuration(main={"size": tuple(size), "format": "XBGR8888"}))
        self.running = False

    def start(self) -> None:
        if not self.running:
            self.cam.start()
            self.running = True

    def stop(self) -> None:
        if self.running:
            self.cam.stop()
            self.running = False

    def frame(self) -> np.ndarray | None:
        return self.cam.capture_array("main")[..., :3] if self.running else None   # [R, G, B, X] -> RGB


class MockPreview:
    """Moving test pattern instead of a camera."""

    def __init__(self, size: tuple[int, int] = (640, 360)) -> None:
        self.size = size
        self.running = False
        self._t0 = time.monotonic()

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def frame(self) -> np.ndarray | None:
        if not self.running:
            return None
        w, h = self.size
        t = time.monotonic() - self._t0
        x = np.linspace(0, 1, w, dtype=np.float32)[None, :]
        y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        r = (np.sin(2 * np.pi * (x * 3 + t * 0.2)) * 0.5 + 0.5) * 255
        g = np.broadcast_to(y * 255, (h, w))
        b = np.full((h, w), 140.0)
        return np.stack(np.broadcast_arrays(r, g, b), axis=-1).astype(np.uint8)


def build_pi(cfg: VrConfig, windowed: bool = False) -> VrHardware:
    from gpiozero import Button, DigitalOutputDevice

    keep: list[object] = []
    power = DigitalOutputDevice(cfg.pins.display_power, initial_value=True)
    keep.append(power)

    def bind(callbacks: dict[str, EdgeCallback]) -> None:
        for name, cb in callbacks.items():
            button = Button(getattr(cfg.pins, f"{name}_button" if name in ("mode", "action") else name),
                            pull_up=True, bounce_time=0.02)
            button.when_pressed = lambda cb=cb: cb(True)
            button.when_released = lambda cb=cb: cb(False)
            keep.append(button)

    imu: Imu | None = None
    if cfg.tracking.enabled:
        try:
            imu = MPU6050(cfg.tracking.i2c_bus, cfg.tracking.address, cfg.tracking.axis_map)
        except OSError as err:
            log.error("IMU unavailable, head tracking off: %s", err)
    gauge: FuelGauge | None = None
    if cfg.power.fuel_gauge:
        try:
            gauge = MAX17048(cfg.power.i2c_bus, cfg.power.fuel_gauge_address, alert_percent=None)
        except OSError as err:
            log.error("fuel gauge unavailable: %s", err)
    camera: PreviewCamera | None = None
    if cfg.passthrough.enabled:
        try:
            camera = Picamera2Preview(cfg.passthrough.size)
        except Exception as err:   # no camera fitted: passthrough mode is skipped
            log.error("passthrough camera unavailable: %s", err)

    return VrHardware(
        camera=camera,
        imu=imu,
        display=PygameDisplay(cfg.display.size, windowed=windowed) if cfg.display.enabled else NullDisplay(),
        audio_sink=aplay_factory(cfg.sound.device),
        gauge=gauge,
        read_temperature=lambda: soc_temperature(cfg.thermal.sensor_path),
        bind_inputs=bind,
        set_display_power=lambda on: power.on() if on else power.off(),
        keep=keep,
    )


def build_mock(cfg: VrConfig, windowed: bool = False) -> VrHardware:
    power_log: list[bool] = []
    hw = VrHardware(
        camera=MockPreview() if cfg.passthrough.enabled else None,
        imu=MockImu() if cfg.tracking.enabled else None,
        display=PygameDisplay(cfg.display.size, windowed=True) if windowed else NullDisplay(),
        audio_sink=lambda rate: MemorySink(rate, realtime=True),
        gauge=MockFuelGauge(90.0),
        read_temperature=lambda: 50.0,
        bind_inputs=lambda _callbacks: None,   # window keys arrive through display.poll_keys()
        set_display_power=power_log.append,
    )
    hw.keep.append(power_log)
    return hw
