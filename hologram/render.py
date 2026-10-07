"""Stereo side-by-side renderer for the two micro-OLEDs.

The display driver takes one 1920x1080 HDMI frame and gives the left half to
the left eye and the right half to the right eye. Everything here works on
per-eye *sample grids* computed once at start-up: for each output pixel, the
grid holds where to sample after undoing the lens distortion. Per frame we
only rotate rays (panorama) or gather pixels (passthrough), which keeps a Pi
Zero 2 W at ~30 fps at half resolution.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class EyeGrid:
    """Normalised sample coordinates for one eye.

    Units: the eye image spans x in [-1, 1]; y uses the same scale (so it
    spans +/- height/width). After pre-distortion, |x| may exceed 1 at the
    edges, which simply samples a little outside the nominal field of view.
    """

    sx: np.ndarray
    sy: np.ndarray


def eye_grid(width: int, height: int, k1: float = 0.0, k2: float = 0.0, center_x: float = 0.0) -> EyeGrid:
    """Barrel pre-distortion grid: output radius r samples the source at
    r * (1 + k1 r^2 + k2 r^4), cancelling a lens's pincushion distortion.
    ``center_x`` is the lens centre in the same normalised units."""
    xs = (np.arange(width, dtype=np.float32) + 0.5) / width * 2.0 - 1.0 - center_x
    ys = ((np.arange(height, dtype=np.float32) + 0.5) - height / 2.0) / (width / 2.0)
    x, y = np.meshgrid(xs, ys)
    r2 = x * x + y * y
    f = 1.0 + k1 * r2 + k2 * r2 * r2
    return EyeGrid(x * f, y * f)


def stereo_grids(eye_w: int, eye_h: int, k1: float, k2: float, shift: float) -> tuple[EyeGrid, EyeGrid]:
    """Left/right grids; a positive ``shift`` moves both lens centres towards the nose."""
    return (eye_grid(eye_w, eye_h, k1, k2, center_x=+shift),
            eye_grid(eye_w, eye_h, k1, k2, center_x=-shift))


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


class PanoramaRenderer:
    """Head-tracked view into a 360 degree equirectangular image (mono)."""

    def __init__(self, pano: np.ndarray, eye_w: int, eye_h: int, fov_deg: float,
                 k1: float = 0.0, k2: float = 0.0, shift: float = 0.0) -> None:
        if pano.ndim != 3 or pano.shape[2] != 3:
            raise ValueError("panorama must be (H, W, 3)")
        self.pano = np.ascontiguousarray(pano)
        self.eye_w, self.eye_h = eye_w, eye_h
        t = math.tan(math.radians(fov_deg) / 2)
        self._rays = []
        for g in stereo_grids(eye_w, eye_h, k1, k2, shift):
            d = np.stack([g.sx * t, np.ones_like(g.sx), -g.sy * t], -1).reshape(-1, 3)
            self._rays.append((d / np.linalg.norm(d, axis=1, keepdims=True)).astype(np.float32))
        self._same = shift == 0.0   # identical eyes: render once, show twice

    def render_eye(self, rays: np.ndarray, rotation: np.ndarray) -> np.ndarray:
        w = rays @ np.asarray(rotation, dtype=np.float32).T        # device -> world
        lon = np.arctan2(w[:, 0], w[:, 1])
        lat = np.arcsin(np.clip(w[:, 2], -1.0, 1.0))
        ph, pw, _ = self.pano.shape
        u = ((lon * (0.5 / math.pi) + 0.5) * pw).astype(np.int32) % pw
        v = np.clip(((0.5 - lat / math.pi) * ph).astype(np.int32), 0, ph - 1)
        return self.pano[v, u].reshape(self.eye_h, self.eye_w, 3)

    def render(self, rotation: np.ndarray) -> np.ndarray:
        left = self.render_eye(self._rays[0], rotation)
        right = left if self._same else self.render_eye(self._rays[1], rotation)
        return np.concatenate([left, right], axis=1)


class PassthroughRenderer:
    """Camera feed to both eyes (the camera is mono, so both eyes match)."""

    def __init__(self, src_w: int, src_h: int, eye_w: int, eye_h: int,
                 k1: float = 0.0, k2: float = 0.0, shift: float = 0.0, zoom: float = 1.0) -> None:
        self.src_w, self.src_h = src_w, src_h
        self.eye_w, self.eye_h = eye_w, eye_h
        self._maps = []
        for g in stereo_grids(eye_w, eye_h, k1, k2, shift):
            px = (g.sx / zoom * 0.5 + 0.5) * src_w
            py = src_h / 2.0 + g.sy / zoom * (src_w / 2.0)
            valid = (px >= 0) & (px < src_w) & (py >= 0) & (py < src_h)
            idx = (np.clip(py.astype(np.int32), 0, src_h - 1) * src_w
                   + np.clip(px.astype(np.int32), 0, src_w - 1))
            self._maps.append((idx.ravel(), ~valid.ravel()))

    def render(self, frame: np.ndarray) -> np.ndarray:
        if frame.shape[:2] != (self.src_h, self.src_w):
            raise ValueError(f"expected a {self.src_w}x{self.src_h} frame, got {frame.shape[1]}x{frame.shape[0]}")
        flat = frame.reshape(-1, 3)
        eyes = []
        for idx, outside in self._maps:
            eye = flat[idx]
            eye[outside] = 0
            eyes.append(eye.reshape(self.eye_h, self.eye_w, 3))
        return np.concatenate(eyes, axis=1)


def draw_rec_indicator(frame: np.ndarray, elapsed_s: float, blink: bool = True) -> np.ndarray:
    """Red dot in the upper-left of each eye while recording (wearer-facing)."""
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
