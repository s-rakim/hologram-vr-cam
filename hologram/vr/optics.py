"""Where each display pixel appears to the eye.

The renderer works from per-eye *ray tables*: for every pixel of the eye's
image, the unit direction (headset axes: X = right, Y = forward, Z = up) in
which the eye sees that pixel, or "nothing" for pixels the eye cannot see.
Rendering a frame is then just rotating those rays by the head orientation
and looking up colours, whatever the optics.

``ReflectorOptics`` is the F1 helmet's design: each eye's display sits in the
brow and projects its picture down onto a concave mirror in the visor, which
reflects a magnified, distant image into the eye (the way wide-angle
see-through headsets such as Project North Star work). The mirror is a patch
of an ellipsoid with one focus at the eye (F1) and the other (F2) above it.
An ellipsoid reflects every ray through one focus to the other, so a ray
that reaches the eye must have left the display along a line through F2:
the eye sees display point D in the direction of the mirror point where the
line F2 -> D meets the ellipsoid. That is exact, closed-form and fast.

``LensOptics`` is the classic design (a panel straight ahead behind a
magnifier lens, with barrel pre-distortion), kept for lens-based builds.

All lengths are millimetres. Parameters describe the RIGHT eye; the left eye
is the mirror image in X.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class RayTable:
    """Unit view directions (h, w, 3) for one eye and a mask of pixels that show something."""

    rays: np.ndarray
    valid: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        return self.rays.shape[0], self.rays.shape[1]


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


# ---------------------------------------------------------------------------
# Reflector (projection) optics
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReflectorOptics:
    ipd: float = 63.0
    mirror_point: Vec3 = (14.0, 68.0, 8.0)    # mirror centre, relative to the eye (x outward)
    focus: Vec3 = (16.0, 5.0, 75.0)           # ellipsoid focus F2, relative to the eye
    image_distance_m: float = 1.5             # where the picture appears to be (sets the display distance)
    display_mm: tuple[float, float] = (52.1, 52.1)    # active area (w, h) of one 2.9in 1440x1440 panel
    display_roll_deg: float = 0.0             # panel turned about its own normal
    left_flip: tuple[bool, bool] = (False, False)     # (x, y): match how each panel's pixels run once mounted
    right_flip: tuple[bool, bool] = (False, False)
    nasal_clearance: float = 1.5              # each mirror stops this far from the centre line
    eye_relief_min: float = 25.0              # mirror points closer than this to the eye are unusable
    forward_min: float = 20.0                 # ...and so are points less than this far in front of it
    mirror_az_deg: tuple[float, float] = (-25.0, 55.0)   # the mirror's edges, as view angles from the eye
    mirror_el_deg: tuple[float, float] = (-40.0, 36.0)   # (azimuth + = outward, elevation + = up)

    # -- geometry of the right eye -------------------------------------------------------
    def eye(self, side: int = 1) -> np.ndarray:
        return np.array([side * self.ipd / 2, 0.0, 0.0])

    def _rel(self, v: Vec3, side: int) -> np.ndarray:
        return self.eye(side) + np.array([side * v[0], v[1], v[2]])

    def foci(self, side: int = 1) -> tuple[np.ndarray, np.ndarray]:
        return self.eye(side), self._rel(self.focus, side)

    def major_axis(self) -> float:
        """2a: the constant |P - F1| + |P - F2| of the mirror ellipsoid."""
        p0 = self._rel(self.mirror_point, 1)
        f1, f2 = self.foci(1)
        return float(np.linalg.norm(p0 - f1) + np.linalg.norm(p0 - f2))

    def focal_length(self) -> float:
        """Effective focal length of the mirror at its centre (F2 is imaged onto F1)."""
        p0 = self._rel(self.mirror_point, 1)
        f1, f2 = self.foci(1)
        b1, b2 = np.linalg.norm(p0 - f1), np.linalg.norm(p0 - f2)
        return float(b1 * b2 / (b1 + b2))

    def display_frame(self, side: int = 1) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Display centre, and unit vectors along its pixel columns (u) and rows (v)."""
        p0 = self._rel(self.mirror_point, side)
        f1, f2 = self.foci(side)
        axis = _unit(p0 - f2)                          # F2 -> mirror centre; the panel faces back along it
        f = self.focal_length()
        virtual = self.image_distance_m * 1000.0 + float(np.linalg.norm(p0 - f1))
        d_obj = 1.0 / (1.0 / f + 1.0 / virtual)        # mirror equation with a virtual image
        centre = p0 - axis * d_obj
        across = np.cross(axis, np.array([0.0, 0.0, 1.0]))
        if np.linalg.norm(across) < 1e-6:
            across = np.array([1.0, 0.0, 0.0])
        u = _unit(across) * side                       # roughly "outward" for each eye
        if u[0] * side < 0:
            u = -u
        v = np.cross(axis, u) * side
        r = math.radians(self.display_roll_deg)
        u, v = u * math.cos(r) + v * math.sin(r), -u * math.sin(r) + v * math.cos(r)
        return centre, u, v

    def display_points(self, w: int, h: int, side: int = 1) -> np.ndarray:
        """Physical position of each rendered pixel (h, w, 3), on a w x h grid over the panel."""
        centre, u, v = self.display_frame(side)
        dw, dh = self.display_mm
        xs = ((np.arange(w) + 0.5) / w - 0.5) * dw
        ys = ((np.arange(h) + 0.5) / h - 0.5) * dh
        flip_x, flip_y = self.right_flip if side > 0 else self.left_flip
        if flip_x != (side < 0):                       # a panel can't be mirrored: the left one runs backwards
            xs = -xs
        if flip_y:
            ys = -ys
        gx, gy = np.meshgrid(xs, ys)
        return centre + gx[..., None] * u + gy[..., None] * v

    def mirror_points(self, d: np.ndarray, side: int = 1) -> np.ndarray:
        """Where the line F2 -> d meets the mirror ellipsoid (beyond d)."""
        f1, f2 = self.foci(side)
        a2 = self.major_axis()
        u = _unit(d - f2)
        g = f2 - f1
        t = (a2 * a2 - g @ g) / (2 * a2 + 2 * (u @ g))
        return f2 + u * t[..., None]

    def panel_clearance(self, samples: int = 25) -> float:
        """Smallest gap (mm) between the panel and the mirror along the light path; must be > 0."""
        d = self.display_points(samples, samples)
        p = self.mirror_points(d)
        _, f2 = self.foci()
        return float((np.linalg.norm(p - f2, axis=-1) - np.linalg.norm(d - f2, axis=-1)).min())

    def panel_corners(self, side: int = 1) -> np.ndarray:
        centre, u, v = self.display_frame(side)
        w, h = self.display_mm
        return np.array([centre + sx * w / 2 * u + sy * h / 2 * v for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))])

    def view_hits(self, az_deg: np.ndarray, el_deg: np.ndarray, side: int = 1) -> np.ndarray:
        """Mirror point the eye sees when looking at (azimuth outward, elevation)."""
        a, e = np.radians(az_deg) * side, np.radians(el_deg)
        dirs = np.stack([np.cos(e) * np.sin(a), np.cos(e) * np.cos(a), np.sin(e)], axis=-1)
        f1, f2 = self.foci(side)
        a2 = self.major_axis()
        g = f1 - f2
        t = (a2 * a2 - g @ g) / (2 * a2 + 2 * (dirs @ g))
        return f1 + dirs * t[..., None]

    def ray_table(self, w: int, h: int, side: int = 1) -> RayTable:
        d = self.display_points(w, h, side)
        p = self.mirror_points(d, side)
        f1, f2 = self.foci(side)
        rays = _unit(p - f1)
        dist = np.linalg.norm(p - f1, axis=-1)
        valid = (np.linalg.norm(p - f2, axis=-1) > np.linalg.norm(d - f2, axis=-1))   # panel before mirror
        valid &= side * p[..., 0] > self.nasal_clearance                              # stops at the nose
        valid &= dist > self.eye_relief_min
        valid &= p[..., 1] - f1[1] > self.forward_min                                  # in front of the face
        valid &= ~self._blocked_by_display(f1, p, side)
        az = np.degrees(np.arctan2(rays[..., 0], rays[..., 1])) * side
        el = np.degrees(np.arcsin(np.clip(rays[..., 2], -1.0, 1.0)))
        valid &= (az >= self.mirror_az_deg[0]) & (az <= self.mirror_az_deg[1])
        valid &= (el >= self.mirror_el_deg[0]) & (el <= self.mirror_el_deg[1])
        return RayTable(rays.astype(np.float32), valid)

    def _blocked_by_display(self, eye: np.ndarray, p: np.ndarray, side: int) -> np.ndarray:
        """True where the eye's line of sight to the mirror passes through the panel itself."""
        centre, u, v = self.display_frame(side)
        n = np.cross(u, v)
        seg = p - eye
        denom = seg @ n
        with np.errstate(divide="ignore", invalid="ignore"):
            s = ((centre - eye) @ n) / denom
        hit = eye + seg * s[..., None]
        local = hit - centre
        inside = (np.abs(local @ u) < self.display_mm[0] / 2 + 2.0) & (np.abs(local @ v) < self.display_mm[1] / 2 + 2.0)
        return np.isfinite(s) & (s > 0) & (s < 1) & inside


# ---------------------------------------------------------------------------
# Lens optics (panel + magnifier)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LensOptics:
    fov_deg: float = 90.0            # horizontal field across one panel at the centre scale
    k1: float = 0.22                 # barrel pre-distortion for the lens's pincushion
    k2: float = 0.24
    lens_center_shift: float = 0.0   # positive moves both lens centres towards the nose
    cant_deg: float = 0.0            # each panel turned outward

    def ray_table(self, w: int, h: int, side: int = 1) -> RayTable:
        g = eye_grid(w, h, self.k1, self.k2, center_x=side * self.lens_center_shift)
        t = math.tan(math.radians(self.fov_deg) / 2)
        d = np.stack([g.sx * t, np.ones_like(g.sx), -g.sy * t], -1)
        c = math.radians(self.cant_deg) * side
        rz = np.array([[math.cos(c), math.sin(c), 0], [-math.sin(c), math.cos(c), 0], [0, 0, 1]])
        rays = _unit(d @ rz.T)
        return RayTable(rays.astype(np.float32), np.ones((h, w), bool))


@dataclass(frozen=True)
class EyeGrid:
    """Normalised sample coordinates for one eye: x spans [-1, 1], y uses the same scale."""

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


def stereo_tables(optics: ReflectorOptics | LensOptics, w: int, h: int) -> tuple[RayTable, RayTable]:
    """(left, right) ray tables at the render resolution of one eye."""
    return optics.ray_table(w, h, side=-1), optics.ray_table(w, h, side=+1)


# ---------------------------------------------------------------------------
# Field of view
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FieldOfView:
    horizontal: float          # both eyes together, degrees
    vertical: float
    per_eye_horizontal: float
    overlap: float             # seen by both eyes (stereo)
    nasal: float               # per eye, towards the nose
    temporal: float            # per eye, towards the ear


def field_of_view(optics: ReflectorOptics | LensOptics, samples: int = 241) -> FieldOfView:
    """Measured from the ray tables, along the horizon and the vertical meridian."""
    left, right = stereo_tables(optics, samples, samples)

    def extents(t: RayTable, side: int) -> tuple[float, float, float, float]:
        r = t.rays[t.valid]
        az = np.degrees(np.arctan2(r[:, 0], r[:, 1])) * side      # + = outward
        el = np.degrees(np.arcsin(np.clip(r[:, 2], -1, 1)))
        near = np.abs(el) < 3.0
        mid = np.abs(az) < 3.0
        return (float(az[near].max()), float(-az[near].min()),
                float(el[mid].max()) if mid.any() else 0.0, float(-el[mid].min()) if mid.any() else 0.0)

    t_out, t_in, up, down = extents(right, 1)
    l_out, l_in, _, _ = extents(left, -1)
    return FieldOfView(
        horizontal=t_out + l_out,
        vertical=up + down,
        per_eye_horizontal=t_out + t_in,
        overlap=t_in + l_in,
        nasal=t_in,
        temporal=t_out,
    )


def eye_view(panel: np.ndarray, table: RayTable, size: int = 480, fov_deg: float = 140.0) -> np.ndarray:
    """What one eye sees: the panel image (h, w, C) pushed back through the optics.

    Returns a (size, size, C) image covering ``fov_deg`` in azimuth and
    elevation (equal-angle projection, straight ahead in the middle), with
    black where the eye sees no panel. Handy to check the pre-warp and see
    the field of view without building anything."""
    r = table.rays[table.valid]
    colours = panel[table.valid]
    half = math.radians(fov_deg) / 2
    az = np.arctan2(r[:, 0], r[:, 1])
    el = np.arcsin(np.clip(r[:, 2], -1, 1))
    u = np.round((az / half + 1) * (size - 1) / 2).astype(int)
    v = np.round((1 - el / half) * (size - 1) / 2).astype(int)
    keep = (u >= 0) & (u < size) & (v >= 0) & (v < size)
    out = np.zeros((size, size) + panel.shape[2:], panel.dtype)
    out[v[keep], u[keep]] = colours[keep]
    filled = np.zeros((size, size), bool)
    filled[v[keep], u[keep]] = True
    for _ in range(2):                      # close the pinholes between splatted pixels
        for dv, du in ((0, 1), (1, 0), (0, -1), (-1, 0)):
            src = np.roll(np.roll(out, dv, 0), du, 1)
            have = np.roll(np.roll(filled, dv, 0), du, 1) & ~filled
            out[have] = src[have]
            filled |= have
    return out
