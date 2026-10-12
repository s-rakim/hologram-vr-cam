"""Synthetic test scene: a textured RGB-D image and the stereo pair it implies.

Used by the demo and the tests, so the whole pipeline can be checked against
known depth without cameras.
"""
from __future__ import annotations

import numpy as np

from .camera import Intrinsics
from .views import shift_view


def _texture(rng: np.random.Generator, h: int, w: int, block: int = 2) -> np.ndarray:
    small = rng.random((h // block + 1, w // block + 1)).astype(np.float32)
    return np.kron(small, np.ones((block, block), np.float32))[:h, :w]


def demo_scene(k: Intrinsics, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    """(rgb, depth) for a wall at 3 m, a box at 1.8 m and a ball at 1.2 m."""
    h, w = k.height, k.width
    rng = np.random.default_rng(seed)
    v, u = np.indices((h, w), dtype=np.float32) + 0.5
    rx, ry = (u - k.cx) / k.fx, (v - k.cy) / k.fy        # ray slopes

    depth = np.full((h, w), 3.0, np.float32)
    colour = np.empty((h, w, 3), np.float32)
    colour[:] = (90, 110, 150)

    box = (np.abs(rx * 1.8 - 0.45) < 0.3) & (np.abs(ry * 1.8 - 0.1) < 0.35)
    depth[box] = 1.8
    colour[box] = (220, 170, 60)

    # Ball: centre (-0.25, 0, 1.2), radius 0.3; nearest ray-sphere hit.
    c = np.array([-0.25, 0.0, 1.2], np.float32)
    d = np.stack([rx, ry, np.ones_like(rx)], -1)
    a = (d * d).sum(-1)
    b = (d * c).sum(-1)
    disc = b * b - a * (c @ c - 0.3 ** 2)
    hit = disc > 0
    t = np.where(hit, (b - np.sqrt(np.maximum(disc, 0))) / a, np.inf)
    ball = hit & (t < depth)
    depth[ball] = t[ball]
    shade = np.clip(1.3 - (depth - 0.9) * 1.5, 0.6, 1.0)
    colour[ball] = np.array([210, 60, 70], np.float32) * shade[ball, None]

    tex = 0.55 + 0.45 * _texture(rng, h, w)
    rgb = np.clip(colour * tex[..., None], 0, 255).astype(np.uint8)
    return rgb, depth


def demo_stereo_pair(k: Intrinsics, baseline_m: float = 0.063,
                     seed: int = 7) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(left, right, true left-camera depth) for a rig with the given baseline."""
    left, depth = demo_scene(k, seed)
    right, _ = shift_view(left, depth, k.fx, baseline_m)
    return left, right, depth
