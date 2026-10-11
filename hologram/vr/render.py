"""Stereo renderer for the headset's displays.

The display shows one side-by-side frame: the left half goes to the left
eye's panel and the right half to the right eye's. Everything here works on
per-eye *ray tables* (see ``optics.py``) computed once at start-up: for each
output pixel, the direction the eye sees it in. Per frame we only rotate
those rays by the head orientation and look up colours, which keeps the
Pi 5 busy with a few vector operations per frame whatever the optics.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from .optics import RayTable


def grid_world(width: int = 2048, height: int = 1024) -> np.ndarray:
    """Built-in equirectangular test scene: sky, ground, 15 degree grid and
    coloured compass posts so head tracking is easy to judge."""
    lon = (np.arange(width, dtype=np.float32) + 0.5) / width * 360.0 - 180.0
    lat = 90.0 - (np.arange(height, dtype=np.float32) + 0.5) / height * 180.0
    LON, LAT = np.meshgrid(lon, lat)
    sky = np.stack([40 + 0.6 * LAT, 80 + 0.9 * LAT, 140 + 1.2 * LAT], -1)
    ground = np.stack([60 - 0.3 * LAT, 52 - 0.3 * LAT, 46 - 0.2 * LAT], -1)
    img = np.where((LAT >= 0)[..., None], sky, ground)
    grid = (np.abs((LON + 7.5) % 15 - 7.5) < 0.35) | (np.abs((LAT + 7.5) % 15 - 7.5) < 0.35)
    img[grid] = img[grid] * 0.5 + 110
    img[np.abs(LAT) < 0.5] = (235, 235, 235)
    posts = {0.0: (230, 70, 60), 90.0: (70, 190, 90), 180.0: (240, 200, 60), -90.0: (80, 140, 240)}
    for centre, colour in posts.items():
        dlon = np.abs(((LON - centre) + 180) % 360 - 180)
        img[(dlon < 4) & (LAT > -10) & (LAT < 25)] = colour
    return np.clip(img, 0, 255).astype(np.uint8)


class _Eyes:
    """Flattened ray tables for both eyes."""

    def __init__(self, tables: Sequence[RayTable]) -> None:
        if len(tables) != 2 or tables[0].shape != tables[1].shape:
            raise ValueError("need two ray tables of the same size")
        self.eye_h, self.eye_w = tables[0].shape
        self._rays = [np.ascontiguousarray(t.rays.reshape(-1, 3), np.float32) for t in tables]
        self._dark = [~t.valid.ravel() for t in tables]
        self._same = (np.array_equal(self._rays[0], self._rays[1])
                      and np.array_equal(self._dark[0], self._dark[1]))

    def side_by_side(self, eyes: list[np.ndarray]) -> np.ndarray:
        out = []
        for colours, dark in zip(eyes, self._dark):
            colours[dark] = 0
            out.append(colours.reshape(self.eye_h, self.eye_w, 3))
        return np.concatenate(out, axis=1)


class PanoramaRenderer(_Eyes):
    """Head-tracked view into a 360 degree equirectangular image (mono)."""

    def __init__(self, pano: np.ndarray, tables: Sequence[RayTable]) -> None:
        super().__init__(tables)
        if pano.ndim != 3 or pano.shape[2] != 3:
            raise ValueError("panorama must be (H, W, 3)")
        self.pano = np.ascontiguousarray(pano)

    def sample_pano(self, w: np.ndarray) -> np.ndarray:
        """Colours of the panorama along world-space rays ``w`` (N, 3)."""
        lon = np.arctan2(w[:, 0], w[:, 1])
        lat = np.arcsin(np.clip(w[:, 2], -1.0, 1.0))
        ph, pw, _ = self.pano.shape
        u = ((lon * (0.5 / math.pi) + 0.5) * pw).astype(np.int32) % pw
        v = np.clip(((0.5 - lat / math.pi) * ph).astype(np.int32), 0, ph - 1)
        return self.pano[v, u]

    def shade(self, w: np.ndarray) -> np.ndarray:
        return self.sample_pano(w)

    def render(self, rotation: np.ndarray) -> np.ndarray:
        r = np.asarray(rotation, dtype=np.float32).T                  # device -> world
        left = self.shade(self._rays[0] @ r)
        right = left.copy() if self._same else self.shade(self._rays[1] @ r)
        return self.side_by_side([left, right])


class VirtualScreenRenderer(PanoramaRenderer):
    """A flat photo on a big virtual screen in front of you, over a dimmed 360 scene.

    The screen sits ``distance`` metres straight ahead (world +Y) and is
    ``width`` metres wide, so 2.4 m at 2 m fills about 62 degrees.
    """

    def __init__(self, background: np.ndarray, image: np.ndarray, tables: Sequence[RayTable],
                 width: float = 2.4, distance: float = 2.0, dim: float = 0.35) -> None:
        super().__init__((background * dim).astype(np.uint8), tables)
        self.width, self.distance = width, distance
        self.set_image(image)

    def set_image(self, image: np.ndarray) -> None:
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("image must be (H, W, 3)")
        self.image = np.ascontiguousarray(image)
        self.height = self.width * image.shape[0] / image.shape[1]

    def shade(self, w: np.ndarray) -> np.ndarray:
        out = self.sample_pano(w)
        ahead = w[:, 1] > 1e-3
        t = self.distance / np.where(ahead, w[:, 1], 1.0)
        x, z = w[:, 0] * t, w[:, 2] * t
        on = ahead & (np.abs(x) < self.width / 2) & (np.abs(z) < self.height / 2)
        ih, iw, _ = self.image.shape
        u = np.clip(((x[on] / self.width + 0.5) * iw).astype(np.int32), 0, iw - 1)
        v = np.clip(((0.5 - z[on] / self.height) * ih).astype(np.int32), 0, ih - 1)
        out[on] = self.image[v, u]
        return out


class PassthroughRenderer(_Eyes):
    """The front camera's view, mapped to the true directions each eye looks in.

    The camera is a pinhole with horizontal field ``hfov_deg`` looking
    straight ahead; with ``zoom`` = 1 the room appears at its real size and
    position. Directions the camera cannot see stay black.
    """

    def __init__(self, src_w: int, src_h: int, tables: Sequence[RayTable], hfov_deg: float = 102.0,
                 zoom: float = 1.0) -> None:
        super().__init__(tables)
        self.src_w, self.src_h = src_w, src_h
        f = (src_w / 2) / math.tan(math.radians(hfov_deg) / 2) * zoom
        self._maps = []
        for rays, dark in zip(self._rays, self._dark):
            ahead = rays[:, 1] > 1e-3
            y = np.where(ahead, rays[:, 1], 1.0)
            px = src_w / 2 + f * rays[:, 0] / y
            py = src_h / 2 - f * rays[:, 2] / y
            seen = ahead & (px >= 0) & (px < src_w) & (py >= 0) & (py < src_h)
            idx = (np.clip(py.astype(np.int32), 0, src_h - 1) * src_w
                   + np.clip(px.astype(np.int32), 0, src_w - 1))
            self._maps.append((idx, ~seen | dark))

    def render(self, frame: np.ndarray) -> np.ndarray:
        if frame.shape[:2] != (self.src_h, self.src_w):
            raise ValueError(f"expected a {self.src_w}x{self.src_h} frame, got {frame.shape[1]}x{frame.shape[0]}")
        flat = frame.reshape(-1, 3)
        eyes = []
        for idx, hidden in self._maps:
            eye = flat[idx]
            eye[hidden] = 0
            eyes.append(eye)
        return self.side_by_side(eyes)


def draw_rec_indicator(frame: np.ndarray, elapsed_s: float, blink: bool = True) -> np.ndarray:
    """Red dot in the upper-left of each eye (wearer-facing status light)."""
    h, w, _ = frame.shape
    eye_w = w // 2
    r = max(3, h // 60)
    yy, xx = np.ogrid[:2 * r + 1, :2 * r + 1]
    disk = (yy - r) ** 2 + (xx - r) ** 2 <= r * r
    if blink and int(elapsed_s * 2) % 2:
        return frame
    for ox in (0, eye_w):
        y0, x0 = h // 8, ox + eye_w // 6
        frame[y0:y0 + 2 * r + 1, x0:x0 + 2 * r + 1][disk] = (230, 40, 40)
    return frame
