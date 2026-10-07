"""The outward-facing privacy LED.

Rule: whenever the camera is recording video, the LED is solidly on. The
capture controller turns it on *before* starting the encoder and refuses to
record if that fails. Photos get a short double flash.
"""
from __future__ import annotations

from typing import Protocol


class LedOutput(Protocol):
    def on(self) -> None: ...
    def off(self) -> None: ...
    def blink(self, on_time: float, off_time: float, n: int) -> None: ...


class PrivacyLed:
    def __init__(self, output: LedOutput) -> None:
        self._out = output
        self.recording = False

    def set_recording(self, active: bool) -> None:
        if active:
            self._out.on()       # raises if the driver fails; state is only set on success
        else:
            self._out.off()
        self.recording = active

    def photo_flash(self) -> None:
        if not self.recording:   # while recording it simply stays on
            self._out.blink(0.12, 0.08, 2)

    def warn(self) -> None:
        """Three quick blinks: capture refused (hot, storage full, low battery)."""
        if not self.recording:
            self._out.blink(0.06, 0.06, 3)


class MemoryLed:
    """Records what it was told to do; used by tests and the desktop mock."""

    def __init__(self, fail: bool = False) -> None:
        self.is_on = False
        self.history: list[str] = []
        self.fail = fail

    def on(self) -> None:
        if self.fail:
            raise OSError("LED driver not responding")
        self.is_on = True
        self.history.append("on")

    def off(self) -> None:
        self.is_on = False
        self.history.append("off")

    def blink(self, on_time: float, off_time: float, n: int) -> None:
        self.history.append(f"blink x{n}")
