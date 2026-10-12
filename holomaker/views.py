"""Novel views from one RGB-D image (depth-image-based rendering).

Each pixel is pushed sideways by the parallax it would show if the camera
moved ``tx`` metres to the right: x' = x - fx * tx / Z. Nearer pixels win
where two land on the same spot (z-buffer), and the holes that open up behind
foreground objects are filled from the background side.

One RGB-D image only knows the surfaces its camera saw, so this works for
modest moves (a few centimetres to ~15 cm at arm's length): enough for the
40-100 views of a light field display or a stereo pair, not for walking around
the back of an object.
"""
from __future__ import annotations

import numpy as np

from .depth import fill_from_background


def shift_view(rgb: np.ndarray, depth: np.ndarray, fx: float, tx: float,
               fill: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Render (rgb, depth) as seen by the same camera moved ``tx`` m to the right.

    Returns (rgb, depth); without ``fill``, holes are black with NaN depth.
    """
    h, w = depth.shape
    rows, cols = np.indices((h, w))
    ok = np.isfinite(depth) & (depth > 0)
    z = depth[ok]
    xn = np.rint(cols[ok] - fx * tx / z).astype(np.int64)
    r = rows[ok]
    inside = (xn >= 0) & (xn < w)
    z, xn, r = z[inside], xn[inside], r[inside]
    src = rgb[ok][inside]

    lin = r * w + xn
    zbuf = np.full(h * w, np.inf, dtype=np.float32)
    np.minimum.at(zbuf, lin, z)
    win = z <= zbuf[lin]
    out = np.zeros((h * w, rgb.shape[2]), dtype=rgb.dtype)
    out[lin[win]] = src[win]
    zout = np.where(np.isinf(zbuf), np.nan, zbuf).reshape(h, w).astype(np.float32)
    out = out.reshape(h, w, -1)
    if fill and not np.isfinite(zout).all():
        zout, out = fill_from_background(zout, out)
    return out, zout


def view_sweep(rgb: np.ndarray, depth: np.ndarray, fx: float, n_views: int,
               span_m: float) -> list[np.ndarray]:
    """``n_views`` images from camera positions evenly spread over ``span_m``,
    centred on the original camera, ordered left to right."""
    if n_views < 1:
        raise ValueError("n_views must be at least 1")
    if n_views == 1:
        return [rgb.copy()]
    offsets = np.linspace(-span_m / 2, span_m / 2, n_views)
    return [shift_view(rgb, depth, fx, float(t))[0] for t in offsets]
