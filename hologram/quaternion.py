"""Unit quaternions as plain (w, x, y, z) tuples.

Plain floats rather than numpy: the fusion loop runs at 200 Hz on tiny
vectors, where numpy's per-call overhead dominates.

Convention: an orientation ``q`` maps device-frame vectors to world-frame
vectors (v_world = q * v_device * q^-1). Both frames are X right, Y forward,
Z up.
"""
from __future__ import annotations

import math

Quat = tuple[float, float, float, float]
Vec = tuple[float, float, float]

IDENTITY: Quat = (1.0, 0.0, 0.0, 0.0)


def mul(a: Quat, b: Quat) -> Quat:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def conj(q: Quat) -> Quat:
    return (q[0], -q[1], -q[2], -q[3])


def normalize(q: Quat) -> Quat:
    n = math.sqrt(sum(c * c for c in q))
    if n == 0:
        return IDENTITY
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def from_axis_angle(axis: Vec, angle: float) -> Quat:
    n = math.sqrt(sum(c * c for c in axis))
    s = math.sin(angle / 2) / n
    return (math.cos(angle / 2), axis[0] * s, axis[1] * s, axis[2] * s)


def rotate(q: Quat, v: Vec) -> Vec:
    _, x, y, z = mul(mul(q, (0.0, v[0], v[1], v[2])), conj(q))
    return (x, y, z)


def to_matrix(q: Quat) -> tuple[Vec, Vec, Vec]:
    """Row-major 3x3 rotation matrix R with v_world = R @ v_device."""
    w, x, y, z = q
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
        (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
        (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)),
    )


def yaw(q: Quat) -> float:
    """Heading of the device's forward axis, radians, counter-clockwise from +Y."""
    fx, fy, _ = rotate(q, (0.0, 1.0, 0.0))
    return math.atan2(-fx, fy)


def pitch(q: Quat) -> float:
    """Elevation of the forward axis above the horizon, radians."""
    _, _, fz = rotate(q, (0.0, 1.0, 0.0))
    return math.asin(max(-1.0, min(1.0, fz)))


def yaw_quat(angle: float) -> Quat:
    return from_axis_angle((0.0, 0.0, 1.0), angle)
