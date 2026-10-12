"""Stereo depth: block matching on a rectified pair, then disparity -> metres.

The matcher is plain numpy: for every candidate disparity it compares the left
image with the right image shifted by that many pixels, sums the absolute
differences over a square window (box filter via an integral image), and keeps
the cheapest disparity per pixel. Both images are mean-subtracted first, so a
small exposure difference between the two cameras doesn't bias the match.
A left/right consistency check marks occlusions and mismatches as NaN.

At 640x480 with 64 disparities this takes a few seconds on a Pi 5. For live
depth use a stereo camera with on-board matching (OAK-D) or run a monocular
model on an AI accelerator, then feed the depth map to the rest of the pipeline.
"""
from __future__ import annotations

import numpy as np

_LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float32)


def to_gray(rgb: np.ndarray) -> np.ndarray:
    """(H, W, 3) uint8 -> (H, W) float32 luma; 2D input is passed through."""
    if rgb.ndim == 2:
        return rgb.astype(np.float32)
    return rgb[..., :3].astype(np.float32) @ _LUMA


def box_sum(img: np.ndarray, radius: int) -> np.ndarray:
    """Sum over a (2r+1)^2 window around every pixel (edges replicated)."""
    k = 2 * radius + 1
    p = np.pad(img.astype(np.float64), radius, mode="edge")
    c = np.zeros((p.shape[0] + 1, p.shape[1] + 1))
    c[1:, 1:] = p.cumsum(0).cumsum(1)
    return c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]


def _normalise(gray: np.ndarray, radius: int) -> np.ndarray:
    k = (2 * radius + 1) ** 2
    return (gray - box_sum(gray, radius) / k).astype(np.float32)


def _costs(ref: np.ndarray, other: np.ndarray, max_disp: int, radius: int, sign: int) -> np.ndarray:
    """Cost volume (D, H, W). ``sign`` -1: ref pixel x matches other at x - d
    (left reference); +1: x + d (right reference). Out-of-image is +inf."""
    h, w = ref.shape
    vol = np.full((max_disp, h, w), np.inf, dtype=np.float32)
    for d in range(max_disp):
        diff = np.full((h, w), np.nan, dtype=np.float32)
        if sign < 0:
            diff[:, d:] = np.abs(ref[:, d:] - other[:, :w - d])
        else:
            diff[:, :w - d] = np.abs(ref[:, :w - d] - other[:, d:])
        valid = ~np.isnan(diff)
        cost = box_sum(np.where(valid, diff, 0.0), radius) / np.maximum(box_sum(valid, radius), 1)
        vol[d] = np.where(valid, cost, np.inf)
    return vol


def _winner(vol: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Integer winner and parabola-refined sub-pixel disparity."""
    best = np.argmin(vol, axis=0)
    d = best.astype(np.float32)
    rows, cols = np.indices(best.shape)
    inner = (best > 0) & (best < vol.shape[0] - 1)
    b = np.clip(best, 1, vol.shape[0] - 2)
    c0, c1, c2 = vol[b - 1, rows, cols], vol[b, rows, cols], vol[b + 1, rows, cols]
    with np.errstate(invalid="ignore", divide="ignore"):
        denom = c0 - 2 * c1 + c2
        off = np.where(inner & np.isfinite(denom) & (denom > 0), 0.5 * (c0 - c2) / denom, 0.0)
    return best, d + np.clip(off, -0.5, 0.5).astype(np.float32)


def stereo_disparity(left: np.ndarray, right: np.ndarray, max_disp: int = 64, radius: int = 3,
                     lr_tolerance: float = 1.0, min_texture: float = 2.0) -> np.ndarray:
    """Disparity in pixels for each left-image pixel; NaN where unreliable.

    ``left``/``right`` must be rectified (rows aligned), same size, RGB or gray.
    Pixels fail when the left->right and right->left matches disagree by more
    than ``lr_tolerance`` (occlusions) or the patch is flatter than
    ``min_texture`` (mean absolute deviation in grey levels: blank walls, sky).
    """
    if left.shape[:2] != right.shape[:2]:
        raise ValueError("left and right images must be the same size")
    if max_disp < 2 or max_disp >= left.shape[1]:
        raise ValueError("max_disp must be at least 2 and smaller than the image width")
    gl, gr = to_gray(left), to_gray(right)
    nl, nr = _normalise(gl, radius * 2), _normalise(gr, radius * 2)
    best_l, disp = _winner(_costs(nl, nr, max_disp, radius, sign=-1))
    best_r, _ = _winner(_costs(nr, nl, max_disp, radius, sign=+1))

    h, w = best_l.shape
    rows, cols = np.indices((h, w))
    back = best_r[rows, np.clip(cols - best_l, 0, w - 1)]
    k = (2 * radius + 1) ** 2
    texture = box_sum(np.abs(_normalise(gl, radius)), radius) / k
    ok = (np.abs(back - best_l) <= lr_tolerance) & (texture >= min_texture) & (cols - best_l >= 0)
    return np.where(ok, disp, np.nan).astype(np.float32)


def disparity_to_depth(disparity: np.ndarray, fx: float, baseline_m: float) -> np.ndarray:
    """Z = fx * B / d, in metres. Zero, negative and NaN disparities give NaN."""
    with np.errstate(divide="ignore", invalid="ignore"):
        z = fx * baseline_m / disparity
    return np.where(np.isfinite(z) & (disparity > 0), z, np.nan).astype(np.float32)


def depth_to_disparity(depth: np.ndarray, fx: float, baseline_m: float) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return (fx * baseline_m / depth).astype(np.float32)


def row_neighbours(valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For each pixel, the column of the nearest valid pixel to its left
    (-1 if none) and to its right (W if none), within the same row."""
    w = valid.shape[1]
    cols = np.broadcast_to(np.arange(w), valid.shape)
    left = np.maximum.accumulate(np.where(valid, cols, -1), axis=1)
    right = np.minimum.accumulate(np.where(valid, cols, w)[:, ::-1], axis=1)[:, ::-1]
    return left, right


def fill_from_background(depth: np.ndarray, *images: np.ndarray) -> tuple[np.ndarray, ...]:
    """Fill NaN depth along each row from whichever neighbour is *farther*.

    Holes in stereo depth and in re-rendered views are almost always
    disocclusions: background that one camera saw and the other didn't, so the
    far side is the right guess. ``images`` (H, W, C) get the same pixels copied.
    Returns (depth, *images).
    """
    valid = np.isfinite(depth)
    if valid.all():
        return (depth, *images)
    if not valid.any():
        raise ValueError("depth map has no valid pixels")
    h, w = depth.shape
    left, right = row_neighbours(valid)
    rows = np.arange(h)[:, None]
    zl = np.where(left >= 0, depth[rows, np.clip(left, 0, w - 1)], -np.inf)
    zr = np.where(right < w, depth[rows, np.clip(right, 0, w - 1)], -np.inf)
    src = np.clip(np.where(zl >= zr, left, right), 0, w - 1)
    has = (left >= 0) | (right < w)
    fallback = float(np.nanmedian(depth))
    out = [np.where(valid, depth, np.where(has, depth[rows, src], fallback)).astype(np.float32)]
    for img in images:
        out.append(np.where(valid[..., None], img, img[rows, src]))
    return tuple(out)
