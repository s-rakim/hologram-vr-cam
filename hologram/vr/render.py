"""Stereo renderer for the helmet's displays.

The displays show one side-by-side frame: the left half goes to the left
eye's panel and the right half to the right eye's. Everything here works on
a *ray table* for the whole frame (see ``optics.py``), computed once at
start-up: for each output pixel, the direction the eye sees it in. Per frame
we only rotate those rays by the head orientation and look up colours.

Speed matters on a Pi 5, so the hot path is laid out for numpy:

* rays are stored as three contiguous rows (x, y, z), so every step is a
  straight vector operation with no strided access;
* images are packed as one ``uint32`` per pixel (R, G, B, X bytes), so a
  pixel lookup is a single gather instead of three;
* frames come out as ``(H, W, 4)`` RGBX ``uint8``, which pygame can show
  without copying (``pygame.image.frombuffer(..., "RGBX")``).
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from .optics import RayTable

Frame = np.ndarray   # (H, W, 4) uint8, RGBX


def grid_world(width: int = 2048, height: int = 1024) -> np.ndarray:
    """Built-in equirectangular test scene: sky, ground, 15 degree grid and
    coloured compass posts (red ahead, green right, yellow behind, blue left)
    so head tracking and the optics calibration are easy to judge."""
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


def pack(rgb: np.ndarray) -> np.ndarray:
    """(H, W, 3 or 4) uint8 -> (H, W) uint32, one RGBX pixel per element."""
    if rgb.ndim != 3 or rgb.shape[2] not in (3, 4) or rgb.dtype != np.uint8:
        raise ValueError("expected an (H, W, 3) or (H, W, 4) uint8 image")
    if rgb.shape[2] == 3:
        rgbx = np.empty(rgb.shape[:2] + (4,), np.uint8)
        rgbx[..., :3] = rgb
        rgbx[..., 3] = 0
        rgb = rgbx
    return np.ascontiguousarray(rgb).view(np.uint32)[..., 0]


def unpack(packed: np.ndarray) -> Frame:
    """(H, W) uint32 -> (H, W, 4) uint8 RGBX (a view, no copy)."""
    return np.ascontiguousarray(packed).view(np.uint8).reshape(packed.shape + (4,))


class _Frame:
    """The ray tables of both eyes laid out as one side-by-side frame."""

    def __init__(self, tables: Sequence[RayTable]) -> None:
        if len(tables) != 2 or tables[0].shape != tables[1].shape:
            raise ValueError("need two ray tables of the same size")
        self.eye_h, self.eye_w = tables[0].shape
        rays = np.concatenate([t.rays for t in tables], axis=1)            # (h, 2w, 3)
        self._rays = np.ascontiguousarray(rays.reshape(-1, 3).T, np.float32)   # (3, N)
        self._dark = ~np.concatenate([t.valid for t in tables], axis=1).ravel()

    @property
    def size(self) -> tuple[int, int]:
        return 2 * self.eye_w, self.eye_h

    def _finish(self, pixels: np.ndarray) -> Frame:
        pixels[self._dark] = 0
        return unpack(pixels.reshape(self.eye_h, 2 * self.eye_w))


class PanoramaRenderer(_Frame):
    """Head-tracked view into a 360 degree equirectangular image (mono)."""

    def __init__(self, pano: np.ndarray, tables: Sequence[RayTable]) -> None:
        super().__init__(tables)
        if pano.ndim != 3 or pano.shape[2] not in (3, 4):
            raise ValueError("panorama must be (H, W, 3)")
        self.ph, self.pw = pano.shape[:2]
        self._pano = pack(pano).ravel()
        self._ku = np.float32(self.pw / (2 * math.pi))
        self._kv = np.float32(self.ph / math.pi)

    def pano_index(self, w: np.ndarray) -> np.ndarray:
        """Flat panorama pixel index along world-space rays ``w`` (3, N). Clips w[2] in place."""
        x, y, z = w
        lon = np.arctan2(x, y)
        np.clip(z, -1.0, 1.0, out=z)
        lat = np.arcsin(z)
        u = (lon * self._ku + np.float32(self.pw / 2)).astype(np.int32)
        np.minimum(u, self.pw - 1, out=u)
        v = (np.float32(self.ph / 2) - lat * self._kv).astype(np.int32)
        np.clip(v, 0, self.ph - 1, out=v)
        v *= self.pw
        v += u
        return v

    def shade(self, w: np.ndarray) -> np.ndarray:
        return self._pano[self.pano_index(w)]

    def render(self, rotation: np.ndarray) -> Frame:
        w = np.asarray(rotation, dtype=np.float32) @ self._rays           # device -> world
        return self._finish(self.shade(w))


class VirtualScreenRenderer(PanoramaRenderer):
    """A flat photo on a big virtual screen in front of you, over a dimmed 360 scene.

    The screen sits ``distance`` metres straight ahead (world +Y) and is
    ``width`` metres wide, so 2.4 m at 2 m fills about 62 degrees.
    """

    def __init__(self, background: np.ndarray, image: np.ndarray, tables: Sequence[RayTable],
                 width: float = 2.4, distance: float = 2.0, dim: float = 0.35) -> None:
        super().__init__((background[..., :3] * dim).astype(np.uint8), tables)
        self.width, self.distance = width, distance
        self.set_image(image)

    def set_image(self, image: np.ndarray) -> None:
        if image.ndim != 3 or image.shape[2] not in (3, 4):
            raise ValueError("image must be (H, W, 3)")
        self.ih, self.iw = image.shape[:2]
        self._image = pack(image).ravel()
        self.height = self.width * self.ih / self.iw

    def shade(self, w: np.ndarray) -> np.ndarray:
        out = self._pano[self.pano_index(w)]
        x, y, z = w
        ahead = y > 1e-3
        t = np.float32(self.distance) / np.where(ahead, y, np.float32(1.0))
        sx, sz = x * t, z * t
        on = ahead & (np.abs(sx) < self.width / 2) & (np.abs(sz) < self.height / 2)
        u = ((sx[on] / self.width + 0.5) * self.iw).astype(np.int32)
        v = ((0.5 - sz[on] / self.height) * self.ih).astype(np.int32)
        np.clip(u, 0, self.iw - 1, out=u)
        np.clip(v, 0, self.ih - 1, out=v)
        out[on] = self._image[v * self.iw + u]
        return out


class PassthroughRenderer(_Frame):
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
        x, y, z = self._rays
        ahead = y > 1e-3
        yy = np.where(ahead, y, 1.0)
        px = src_w / 2 + f * x / yy
        py = src_h / 2 - f * z / yy
        seen = ahead & (px >= 0) & (px < src_w) & (py >= 0) & (py < src_h)
        self._idx = (np.clip(py.astype(np.int32), 0, src_h - 1) * src_w
                     + np.clip(px.astype(np.int32), 0, src_w - 1))
        self._dark = self._dark | ~seen

    def render(self, frame: np.ndarray) -> Frame:
        if frame.shape[:2] != (self.src_h, self.src_w):
            raise ValueError(f"expected a {self.src_w}x{self.src_h} frame, got {frame.shape[1]}x{frame.shape[0]}")
        return self._finish(pack(frame).ravel()[self._idx])
