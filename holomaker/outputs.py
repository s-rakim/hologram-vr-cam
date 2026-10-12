"""Display formats: what each kind of "hologram" display wants to be fed.

| Display                                   | Format here           |
|-------------------------------------------|-----------------------|
| Pepper's-ghost pyramid on a screen        | :func:`pepper_ghost`  |
| Light field display (Looking Glass)       | :func:`quilt`         |
| Swept-volume / volumetric display         | :func:`volume_slices` |
| Red/cyan glasses                          | :func:`anaglyph`      |
| VR headset, 3D TV, the Hologram VR glasses| :func:`side_by_side`  |
"""
from __future__ import annotations

import numpy as np


def fit(img: np.ndarray, width: int, height: int) -> np.ndarray:
    """Nearest-neighbour resize that keeps the aspect ratio, centred on black."""
    h, w = img.shape[:2]
    s = min(width / w, height / h)
    nw, nh = max(1, round(w * s)), max(1, round(h * s))
    ys = np.minimum((np.arange(nh) + 0.5) / s, h - 1).astype(np.int64)
    xs = np.minimum((np.arange(nw) + 0.5) / s, w - 1).astype(np.int64)
    out = np.zeros((height, width) + img.shape[2:], dtype=img.dtype)
    y0, x0 = (height - nh) // 2, (width - nw) // 2
    out[y0:y0 + nh, x0:x0 + nw] = img[ys][:, xs]
    return out


def isolate(rgb: np.ndarray, depth: np.ndarray, max_depth: float) -> np.ndarray:
    """Black out everything farther than ``max_depth`` m.

    Pepper's-ghost and volumetric displays show black as *nothing*, so the
    subject floats in the air only once its background is removed.
    """
    keep = np.isfinite(depth) & (depth <= max_depth)
    return np.where(keep[..., None], rgb, 0).astype(rgb.dtype)


def pepper_ghost(front: np.ndarray, size: int = 1080, right: np.ndarray | None = None,
                 back: np.ndarray | None = None, left: np.ndarray | None = None,
                 gap: float = 0.0) -> np.ndarray:
    """Four-sided layout for a clear pyramid standing point-down on a screen.

    Each copy sits on one side of an empty centre square with its *top facing
    outwards*: a pyramid face at 45 degrees reflects screen points farther from
    the centre higher up, so the viewer on that side sees the image upright and
    not mirrored. Pass ``right``/``back``/``left`` (e.g. parallax views) to show a
    different side of the subject on each face; otherwise ``front`` is reused.
    ``gap`` (0-1 of a cell) pushes the images away from the centre square.
    """
    cell = size // 3
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    push = round(gap * cell)
    faces = {
        "bottom": (front, 2),        # viewer at the bottom edge of the screen
        "right": (right if right is not None else front, 3),
        "top": (back if back is not None else front, 0),
        "left": (left if left is not None else front, 1),
    }
    mid = (size - cell) // 2
    for side, (img, quarter_turns) in faces.items():
        tile = np.rot90(fit(img[..., :3], cell, cell), quarter_turns)
        if side == "bottom":
            y, x = min(size - cell, mid + cell + push), mid
        elif side == "top":
            y, x = max(0, mid - cell - push), mid
        elif side == "left":
            y, x = mid, max(0, mid - cell - push)
        else:
            y, x = mid, min(size - cell, mid + cell + push)
        canvas[y:y + cell, x:x + cell] = tile
    return canvas


def quilt(views: list[np.ndarray], cols: int, rows: int) -> np.ndarray:
    """Pack views into a Looking Glass quilt.

    View 0 is the leftmost camera and goes in the bottom-left tile; views fill
    left to right, then bottom to top. Save the result with a name ending in
    ``_qs{cols}x{rows}a{aspect}`` so Looking Glass software detects the layout.
    """
    if len(views) != cols * rows:
        raise ValueError(f"need {cols * rows} views for a {cols}x{rows} quilt, got {len(views)}")
    h, w = views[0].shape[:2]
    out = np.zeros((rows * h, cols * w, 3), dtype=np.uint8)
    for i, v in enumerate(views):
        r, c = divmod(i, cols)
        y = (rows - 1 - r) * h
        out[y:y + h, c * w:(c + 1) * w] = v[..., :3]
    return out


def quilt_name(stem: str, cols: int, rows: int, view_w: int, view_h: int) -> str:
    return f"{stem}_qs{cols}x{rows}a{view_w / view_h:.2f}.png"


def volume_slices(rgb: np.ndarray, depth: np.ndarray, n: int, near: float | None = None,
                  far: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Cut the scene into ``n`` depth slices, near to far.

    Slice i holds only the pixels whose depth falls in its band (everything else
    black). A swept-volume display shows slice i when its moving screen is at
    depth position i; persistence of vision stacks them into a solid image.
    Returns (slices (n, H, W, 3), band edges (n + 1,) in metres).
    """
    finite = depth[np.isfinite(depth)]
    if finite.size == 0:
        raise ValueError("depth map has no valid pixels")
    near = float(finite.min()) if near is None else near
    far = float(finite.max()) if far is None else far
    if far <= near:
        far = near + 1e-3
    edges = np.linspace(near, far, n + 1)
    idx = np.digitize(np.where(np.isfinite(depth), depth, np.inf), edges[1:-1])
    inside = np.isfinite(depth) & (depth >= near) & (depth <= far)
    slices = np.zeros((n,) + rgb.shape[:2] + (3,), dtype=np.uint8)
    for i in range(n):
        m = inside & (idx == i)
        slices[i][m] = rgb[..., :3][m]
    return slices, edges


def contact_sheet(images: np.ndarray | list[np.ndarray], cols: int) -> np.ndarray:
    """Tile images left to right, top to bottom (for previewing slices)."""
    n = len(images)
    rows = -(-n // cols)
    h, w = images[0].shape[:2]
    out = np.zeros((rows * h, cols * w, 3), dtype=np.uint8)
    for i, img in enumerate(images):
        r, c = divmod(i, cols)
        out[r * h:(r + 1) * h, c * w:(c + 1) * w] = img[..., :3]
    return out


def anaglyph(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Red/cyan anaglyph: red channel from the left eye, green and blue from the right."""
    out = right[..., :3].copy()
    out[..., 0] = left[..., 0]
    return out


def side_by_side(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Left eye | right eye, full width each (the Hologram VR glasses' input format)."""
    return np.concatenate([left[..., :3], right[..., :3]], axis=1)


def depth_preview(depth: np.ndarray) -> np.ndarray:
    """Grey depth image for checking results: near is bright, far is dark, invalid is red."""
    out = np.zeros(depth.shape + (3,), dtype=np.uint8)
    ok = np.isfinite(depth)
    if ok.any():
        lo, hi = np.percentile(depth[ok], [1, 99])
        g = np.clip((hi - depth) / max(hi - lo, 1e-6), 0, 1) * 235 + 20
        out[ok] = g[ok, None].astype(np.uint8)
    out[~ok] = (200, 30, 30)
    return out
