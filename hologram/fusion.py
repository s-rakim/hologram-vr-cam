"""Madgwick gradient-descent orientation filter (gyroscope + accelerometer).

Gives 3DoF head orientation. Pitch and roll are anchored by gravity; yaw has
no magnetometer reference and drifts slowly, so the wearer recentres it
with a double tap (see :meth:`HeadTracker.recenter`).
"""
from __future__ import annotations

import math
import threading

from . import quaternion as qt


class Madgwick:
    def __init__(self, beta: float = 0.05, q: qt.Quat = qt.IDENTITY) -> None:
        self.beta = beta
        self.q = q

    def update(self, gyro: qt.Vec, accel: qt.Vec, dt: float) -> qt.Quat:
        """Advance by ``dt`` seconds. ``gyro`` in rad/s, ``accel`` in any unit
        (only its direction is used), both in the device frame."""
        q0, q1, q2, q3 = self.q
        gx, gy, gz = gyro
        ax, ay, az = accel

        # Rate of change of the quaternion from the gyroscope.
        d0 = 0.5 * (-q1 * gx - q2 * gy - q3 * gz)
        d1 = 0.5 * (q0 * gx + q2 * gz - q3 * gy)
        d2 = 0.5 * (q0 * gy - q1 * gz + q3 * gx)
        d3 = 0.5 * (q0 * gz + q1 * gy - q2 * gx)

        norm = math.sqrt(ax * ax + ay * ay + az * az)
        if norm > 1e-9:
            ax, ay, az = ax / norm, ay / norm, az / norm
            # Gradient of the error between measured and predicted gravity.
            s0 = 4 * q0 * q2 * q2 + 2 * q2 * ax + 4 * q0 * q1 * q1 - 2 * q1 * ay
            s1 = (4 * q1 * q3 * q3 - 2 * q3 * ax + 4 * q0 * q0 * q1 - 2 * q0 * ay - 4 * q1
                  + 8 * q1 * q1 * q1 + 8 * q1 * q2 * q2 + 4 * q1 * az)
            s2 = (4 * q0 * q0 * q2 + 2 * q0 * ax + 4 * q2 * q3 * q3 - 2 * q3 * ay - 4 * q2
                  + 8 * q2 * q1 * q1 + 8 * q2 * q2 * q2 + 4 * q2 * az)
            s3 = 4 * q1 * q1 * q3 - 2 * q1 * ax + 4 * q2 * q2 * q3 - 2 * q2 * ay
            sn = math.sqrt(s0 * s0 + s1 * s1 + s2 * s2 + s3 * s3)
            if sn > 1e-12:
                d0 -= self.beta * s0 / sn
                d1 -= self.beta * s1 / sn
                d2 -= self.beta * s2 / sn
                d3 -= self.beta * s3 / sn

        self.q = qt.normalize((q0 + d0 * dt, q1 + d1 * dt, q2 + d2 * dt, q3 + d3 * dt))
        return self.q


class HeadTracker:
    """Thread-safe wrapper: fusion + gyro bias + yaw recentring."""

    def __init__(self, beta: float = 0.05) -> None:
        self._filter = Madgwick(beta)
        self._lock = threading.Lock()
        self._yaw_offset = qt.IDENTITY
        self.gyro_bias: qt.Vec = (0.0, 0.0, 0.0)
        self._last_t: float | None = None

    def calibrate(self, samples: list[tuple[qt.Vec, qt.Vec]]) -> qt.Vec:
        """Average gyro readings taken while the glasses sit still."""
        if samples:
            n = len(samples)
            self.gyro_bias = tuple(sum(g[i] for g, _ in samples) / n for i in range(3))  # type: ignore[assignment]
            ax, ay, az = (sum(a[i] for _, a in samples) / n for i in range(3))
            with self._lock:   # start level with gravity instead of converging from identity
                self._filter.q = _tilt_from_gravity((ax, ay, az))
        return self.gyro_bias

    def update(self, gyro: qt.Vec, accel: qt.Vec, t: float) -> None:
        dt = 0.0 if self._last_t is None else min(0.1, max(0.0, t - self._last_t))
        self._last_t = t
        g = (gyro[0] - self.gyro_bias[0], gyro[1] - self.gyro_bias[1], gyro[2] - self.gyro_bias[2])
        with self._lock:
            self._filter.update(g, accel, dt)

    def set_orientation(self, q: qt.Quat) -> None:
        with self._lock:
            self._filter.q = qt.normalize(q)

    def recenter(self) -> None:
        """Make the current heading the new 'straight ahead'."""
        with self._lock:
            self._yaw_offset = qt.yaw_quat(qt.yaw(self._filter.q))

    def orientation(self) -> qt.Quat:
        with self._lock:
            return qt.mul(qt.conj(self._yaw_offset), self._filter.q)


def _tilt_from_gravity(accel: qt.Vec) -> qt.Quat:
    """Orientation (zero yaw) whose world-up matches the measured gravity."""
    ax, ay, az = accel
    n = math.sqrt(ax * ax + ay * ay + az * az)
    if n < 1e-9:
        return qt.IDENTITY
    ux, uy, uz = ax / n, ay / n, az / n     # world up, seen in the device frame
    # Rotate device-frame 'up' onto world +Z: axis = up x z, angle = acos(up . z).
    axis = (uy, -ux, 0.0)
    s = math.sqrt(axis[0] ** 2 + axis[1] ** 2)
    if s < 1e-9:
        return qt.IDENTITY if uz > 0 else qt.from_axis_angle((1.0, 0.0, 0.0), math.pi)
    return qt.from_axis_angle(axis, math.atan2(s, uz))
