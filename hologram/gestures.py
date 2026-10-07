"""Turn raw press/release edges into tap, double-tap and hold gestures.

Pure and clock-driven (callers pass timestamps), so it is fully testable and
works the same for the GPIO button, the touch strip and the keyboard mock.
"""
from __future__ import annotations

from enum import Enum


class Gesture(Enum):
    TAP = "tap"
    DOUBLE_TAP = "double_tap"
    HOLD = "hold"


class GestureDetector:
    def __init__(self, hold_s: float = 0.6, double_tap_s: float = 0.0) -> None:
        """``double_tap_s`` = 0 disables double taps, so a tap fires on release
        with no delay (what you want for a camera shutter)."""
        self.hold_s = hold_s
        self.double_tap_s = double_tap_s
        self._pressed_at: float | None = None
        self._hold_fired = False
        self._pending_tap: float | None = None   # release time of an unconfirmed single tap

    def _flush_stale(self, t: float) -> list[Gesture]:
        if self._pending_tap is not None and t - self._pending_tap > self.double_tap_s:
            self._pending_tap = None
            return [Gesture.TAP]
        return []

    def press(self, t: float) -> list[Gesture]:
        out = self._flush_stale(t)
        self._pressed_at = t
        self._hold_fired = False
        return out

    def release(self, t: float) -> list[Gesture]:
        if self._pressed_at is None:
            return []
        out = self.poll(t)               # a hold may have matured just before release
        self._pressed_at = None
        if self._hold_fired:
            return out
        if self.double_tap_s <= 0:
            return out + [Gesture.TAP]
        if self._pending_tap is not None:
            self._pending_tap = None
            return out + [Gesture.DOUBLE_TAP]
        self._pending_tap = t
        return out

    def poll(self, t: float) -> list[Gesture]:
        out: list[Gesture] = []
        if self._pressed_at is not None:
            if not self._hold_fired and t - self._pressed_at >= self.hold_s:
                self._hold_fired = True
                self._pending_tap = None
                out.append(Gesture.HOLD)
        else:
            out += self._flush_stale(t)
        return out
