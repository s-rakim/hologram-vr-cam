"""Build the real (Pi) or mock (desktop/test) hardware from a Config."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from .capture import CameraBackend, MockCamera, Picamera2Backend
from .config import Config
from .display import Display, NullDisplay, PygameDisplay
from .imu import MPU6050, Imu, MockImu
from .privacy_led import LedOutput, MemoryLed
from .thermal import soc_temperature

log = logging.getLogger(__name__)
EdgeCallback = Callable[[bool], None]


@dataclass
class Hardware:
    camera: CameraBackend
    led: LedOutput
    imu: Imu | None
    display: Display
    read_temperature: Callable[[], float | None]
    # Called with a callback taking pressed=True/False; wires up the inputs.
    bind_inputs: Callable[[EdgeCallback, EdgeCallback, Callable[[], None]], None]
    keep: list[object] = field(default_factory=list)   # objects that must stay alive (gpiozero)


class GpioLed:
    def __init__(self, pin: int) -> None:
        from gpiozero import LED
        self._led = LED(pin)

    def on(self) -> None:
        self._led.on()

    def off(self) -> None:
        self._led.off()

    def blink(self, on_time: float, off_time: float, n: int) -> None:
        self._led.blink(on_time=on_time, off_time=off_time, n=n, background=True)


def build_pi(cfg: Config, windowed: bool = False) -> Hardware:
    from gpiozero import Button

    keep: list[object] = []

    def bind(on_button: EdgeCallback, on_touch: EdgeCallback, on_low_battery: Callable[[], None]) -> None:
        button = Button(cfg.pins.capture_button, pull_up=True, bounce_time=0.02)
        touch = Button(cfg.pins.touch, pull_up=False, bounce_time=0.02)        # TTP223 drives high
        low = Button(cfg.pins.low_battery, pull_up=True, bounce_time=0.5)      # LBO pulls low
        button.when_pressed, button.when_released = (lambda: on_button(True)), (lambda: on_button(False))
        touch.when_pressed, touch.when_released = (lambda: on_touch(True)), (lambda: on_touch(False))
        low.when_pressed = on_low_battery
        keep.extend((button, touch, low))
        if low.is_pressed:
            on_low_battery()

    imu: Imu | None = None
    if cfg.tracking.enabled:
        try:
            imu = MPU6050(cfg.tracking.i2c_bus, cfg.tracking.address, cfg.tracking.axis_map)
        except OSError as err:
            log.error("IMU unavailable, head tracking off: %s", err)

    display: Display = NullDisplay()
    if cfg.display.enabled:
        display = PygameDisplay(cfg.display.size, windowed=windowed)

    return Hardware(
        camera=Picamera2Backend(cfg.capture),
        led=GpioLed(cfg.pins.privacy_led),
        imu=imu,
        display=display,
        read_temperature=lambda: soc_temperature(cfg.thermal.sensor_path),
        bind_inputs=bind,
        keep=keep,
    )


def build_mock(cfg: Config, windowed: bool = False) -> Hardware:
    """Desktop stand-ins: synthetic camera, fake head motion, optional window."""
    display: Display = NullDisplay()
    if windowed:
        display = PygameDisplay(cfg.display.size, windowed=True)
    return Hardware(
        camera=MockCamera(),
        led=MemoryLed(),
        imu=MockImu() if cfg.tracking.enabled else None,
        display=display,
        read_temperature=lambda: 45.0,
        bind_inputs=lambda *_: None,   # keyboard events arrive through display.poll_keys()
    )
