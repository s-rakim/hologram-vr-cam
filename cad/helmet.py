"""F1-style closed-face helmet shell for the VR headset.

The outer surface is one smooth radial function around a centre inside the
head (an egg that is narrower at the front, with a forward chin bar, a high
crown and a rear that drops low over the neck, like a Formula 1 helmet).
It is split into six printable sections, leaving the wrap-around eye port
open for the visor. Two representations come from the same surface:

* smooth closed meshes (``section_mesh``) for the STL files you print,
* stepped horizontal extrusions (``section_solids``) for the IFC / Revit
  model and the drawings, sliced from those meshes.

Coordinates: X = wearer's right, Y = forward, Z = up; the origin is between
the eyes at eye level. Angles: theta is the azimuth seen from above,
counter-clockwise from +X (front = 90 deg); phi is the elevation from the
helmet centre.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .geometry import MIN_EDGE_MM, Solid, Vec2, Vec3, signed_area

CENTER = (0.0, -76.0, 18.0)       # radial centre, inside the head
SHELL = 2.4                       # printed wall: 6 perimeters of a 0.4 mm nozzle (LW-PLA or PETG)

# Outer surface: a piecewise ellipsoid (C1-smooth) plus a chin bar and a neck lip.
HALF_WIDTH_FRONT = 134.0          # x half-width towards the face (room for the visor mirrors)
HALF_WIDTH_REAR = 123.0           # ... and at the back
FRONT = 174.0                     # centre -> front of the eye port
REAR = 165.0                      # centre -> back (long tail, like an F1 shell)
UP = 146.0                        # centre -> crown
DOWN = 176.0                      # centre -> bottom of the chin bar / neck
BROW_FULLNESS = 0.75              # squarer upper-front corners (superellipsoid exponent 2 -> 2.75) for the optics
BROW_LOW = 0.45                   # ... from this far below the centre (direction z component)
CHIN = 34.0                       # extra forward push of the chin bar
CHIN_PHI = -50.0                  # elevation of the chin bar's nose
NECK_LIP = 7.0                    # the rear edge flares out over the neck

# Eye port (the visor covers it): azimuth half-width and elevation range.
PORT_HALF_DEG = 42.0
PORT_PHI = (-10.0, 5.0)


BOTTOM_SIDE = -122.0              # height of the lower edge (mm, from eye level) under the jaw ...
BOTTOM_FRONT = -142.0             # ... at the chin bar
BOTTOM_REAR = -150.0              # ... and at the back of the neck


def bottom_z(theta: np.ndarray) -> np.ndarray:
    s = np.sin(theta)
    return BOTTOM_SIDE + (BOTTOM_FRONT - BOTTOM_SIDE) * np.maximum(s, 0.0) ** 2 \
        + (BOTTOM_REAR - BOTTOM_SIDE) * np.maximum(-s, 0.0) ** 2


def bottom_phi(theta: np.ndarray) -> np.ndarray:
    """Elevation of the lower edge, found so the edge runs at ``bottom_z`` (a near-level line from the side)."""
    theta = np.asarray(theta, float)
    target = bottom_z(theta)
    lo = np.full_like(theta, math.radians(-88.0))
    hi = np.full_like(theta, math.radians(-15.0))
    for _ in range(48):                             # z rises with phi along each azimuth: bisect
        mid = (lo + hi) / 2
        z = CENTER[2] + radius(theta, mid) * np.sin(mid)
        below = z < target
        lo, hi = np.where(below, mid, lo), np.where(below, hi, mid)
    return (lo + hi) / 2


def direction(theta: np.ndarray, phi: np.ndarray) -> np.ndarray:
    c = np.cos(phi)
    return np.stack([c * np.cos(theta), c * np.sin(theta), np.sin(phi)], axis=-1)


def radius(theta: np.ndarray, phi: np.ndarray) -> np.ndarray:
    """Distance from CENTER to the outer surface in direction (theta, phi)."""
    d = direction(theta, phi)
    dx, dy, dz = d[..., 0], d[..., 1], d[..., 2]
    ax = HALF_WIDTH_REAR + (HALF_WIDTH_FRONT - HALF_WIDTH_REAR) * np.clip(dy, 0.0, 1.0)
    ay = np.where(dy > 0, FRONT, REAR)
    az = np.where(dz > 0, UP, DOWN)
    brow = np.clip(dy, 0.0, 1.0) * np.clip((dz + BROW_LOW) / 0.5, 0.0, 1.0) ** 2 * np.clip((0.95 - dz) / 0.4, 0.0, 1.0)
    n = 2.0 + BROW_FULLNESS * brow
    r = (np.abs(dx / ax) ** n + np.abs(dy / ay) ** n + np.abs(dz / az) ** n) ** (-1.0 / n)
    dtheta = np.angle(np.exp(1j * (theta - math.pi / 2)))           # azimuth from straight ahead
    chin = CHIN * np.exp(-(dtheta / math.radians(55)) ** 2) * np.exp(-((phi - math.radians(CHIN_PHI)) / math.radians(20)) ** 2)
    back = np.angle(np.exp(1j * (theta + math.pi / 2)))             # azimuth from straight behind
    lip = NECK_LIP * np.exp(-(back / math.radians(75)) ** 2) * np.clip((math.radians(-45) - phi) / math.radians(18), 0, 1) ** 2
    return r + chin + lip


def surface(theta: np.ndarray, phi: np.ndarray, inset: float = 0.0) -> np.ndarray:
    """Points ``inset`` mm inside the outer surface (measured along the radius)."""
    r = radius(theta, phi) - inset
    return np.asarray(CENTER) + direction(theta, phi) * r[..., None]


@dataclass(frozen=True)
class Section:
    id: str
    name: str
    theta: tuple[float, float]           # degrees
    phi: tuple[float | None, float]      # degrees; None = the helmet's lower edge


PORT = (90.0 - PORT_HALF_DEG, 90.0 + PORT_HALF_DEG)
SECTIONS: tuple[Section, ...] = (
    Section("shell_crown_front", "Shell: crown front", (0.0, 180.0), (PORT_PHI[1], 90.0)),
    Section("shell_crown_rear", "Shell: crown rear", (180.0, 360.0), (PORT_PHI[1], 90.0)),
    Section("shell_cheek_right", "Shell: right cheek", (0.0, PORT[0]), PORT_PHI),
    Section("shell_cheek_left", "Shell: left cheek", (PORT[1], 180.0), PORT_PHI),
    Section("shell_chin_bar", "Shell: chin bar", (0.0, 180.0), (None, PORT_PHI[0])),
    Section("shell_rear_lower", "Shell: rear lower", (180.0, 360.0), (None, PORT_PHI[1])),
)


def section_grid(s: Section, inset: float, angle_step_deg: float = 3.0) -> np.ndarray:
    """(rows + 1, cols + 1, 3) points over a section; the last row is the apex for the crown."""
    t0, t1 = (math.radians(a) for a in s.theta)
    cols = max(2, math.ceil((s.theta[1] - s.theta[0]) / angle_step_deg))
    theta = np.linspace(t0, t1, cols + 1)
    p0 = bottom_phi(theta) if s.phi[0] is None else np.full_like(theta, math.radians(s.phi[0]))
    p1 = math.radians(s.phi[1])
    rows = max(2, math.ceil(math.degrees(p1 - p0.min()) / angle_step_deg))
    t = np.linspace(0.0, 1.0, rows + 1)[:, None]
    phi = p0[None, :] + (p1 - p0[None, :]) * t
    return surface(np.broadcast_to(theta, phi.shape), phi, inset)


def reaches_apex(s: Section) -> bool:
    return s.phi[1] >= 90.0 - 1e-9


# --------------------------------------------------------------------------
# Smooth closed meshes for printing
# --------------------------------------------------------------------------
Mesh = tuple[list[Vec3], list[tuple[int, int, int]]]


def layer_mesh(outer: np.ndarray, inner: np.ndarray, apex: bool = False) -> Mesh:
    """Watertight, outward-facing mesh of the layer between two (rows + 1, cols + 1, 3) grids.

    With ``apex`` the last row of each grid is a single point (the crown)."""
    verts: list[Vec3] = []

    def index(grid: np.ndarray) -> list[list[int]]:
        rows_idx = []
        for i, row in enumerate(grid):
            if apex and i == len(grid) - 1:                 # every column meets at the top
                verts.append(tuple(float(c) for c in row[0]))
                rows_idx.append([len(verts) - 1] * len(row))
                continue
            ids = []
            for p in row:
                verts.append(tuple(float(c) for c in p))
                ids.append(len(verts) - 1)
            rows_idx.append(ids)
        return rows_idx

    o, n = index(outer), index(inner)
    rows, cols = len(o) - 1, len(o[0]) - 1
    tris: list[tuple[int, int, int]] = []

    def quad(a: int, b: int, c: int, d: int) -> None:
        for tri in ((a, b, c), (a, c, d)):
            if len(set(tri)) == 3:
                tris.append(tri)

    for i in range(rows):
        for j in range(cols):
            quad(o[i][j], o[i][j + 1], o[i + 1][j + 1], o[i + 1][j])
            quad(n[i][j], n[i + 1][j], n[i + 1][j + 1], n[i][j + 1])
    for j in range(cols):                                     # bottom rim
        quad(o[0][j], n[0][j], n[0][j + 1], o[0][j + 1])
        if not apex:                                          # top rim
            quad(o[rows][j], o[rows][j + 1], n[rows][j + 1], n[rows][j])
    for i in range(rows):                                     # the two cut faces
        quad(o[i][0], o[i + 1][0], n[i + 1][0], n[i][0])
        quad(o[i][cols], n[i][cols], n[i + 1][cols], o[i + 1][cols])
    return verts, orient(verts, tris)


def section_mesh(s: Section, angle_step_deg: float = 3.0, insets: tuple[float, float] = (0.0, SHELL)) -> Mesh:
    """Watertight, outward-facing triangle mesh of one shell section (mm)."""
    return layer_mesh(section_grid(s, insets[0], angle_step_deg), section_grid(s, insets[1], angle_step_deg),
                      apex=reaches_apex(s))


def orient(verts: list[Vec3], tris: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """Make every triangle wind consistently, then face outward (positive volume)."""
    edges: dict[tuple[int, int], list[int]] = {}
    for k, (a, b, c) in enumerate(tris):
        for e in ((a, b), (b, c), (c, a)):
            edges.setdefault((min(e), max(e)), []).append(k)
    work = [list(t) for t in tris]
    seen = [False] * len(work)
    for start in range(len(work)):
        if seen[start]:
            continue
        seen[start] = True
        stack = [start]
        while stack:
            k = stack.pop()
            a, b, c = work[k]
            for u, v in ((a, b), (b, c), (c, a)):
                for m in edges[(min(u, v), max(u, v))]:
                    if seen[m]:
                        continue
                    t = work[m]
                    if (u, v) in {(t[0], t[1]), (t[1], t[2]), (t[2], t[0])}:   # same direction: flip it
                        t[1], t[2] = t[2], t[1]
                    seen[m] = True
                    stack.append(m)
    if signed_volume(verts, work) < 0:
        work = [[a, c, b] for a, b, c in work]
    return [(a, b, c) for a, b, c in work]


def signed_volume(verts: list[Vec3], tris) -> float:
    v = 0.0
    for a, b, c in tris:
        (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = verts[a], verts[b], verts[c]
        v += (x1 * (y2 * z3 - y3 * z2) - x2 * (y1 * z3 - y3 * z1) + x3 * (y1 * z2 - y2 * z1)) / 6.0
    return v


def is_watertight(tris) -> bool:
    """Every edge used exactly twice, once in each direction."""
    count: dict[tuple[int, int], int] = {}
    for a, b, c in tris:
        for e in ((a, b), (b, c), (c, a)):
            count[e] = count.get(e, 0) + 1
    return all(n == 1 and count.get((e[1], e[0]), 0) == 1 for e, n in count.items())


# --------------------------------------------------------------------------
# Stepped extrusions for IFC / Revit / drawings
# --------------------------------------------------------------------------
def _crossing(column: np.ndarray, z: float) -> Vec2 | None:
    """(x, y) where a column of surface points (z rising) passes height z."""
    zs = column[:, 2]
    if not zs[0] <= z <= zs[-1]:
        return None
    k = int(np.searchsorted(zs, z))
    k = min(max(k, 1), len(zs) - 1)
    za, zb = zs[k - 1], zs[k]
    f = 0.0 if zb == za else (z - za) / (zb - za)
    p = column[k - 1] + (column[k] - column[k - 1]) * f
    return float(p[0]), float(p[1])


def _clean(points: list[Vec2]) -> list[Vec2]:
    """Drop points closer than MIN_EDGE_MM to the last kept one (Revit's short-curve limit)."""
    out: list[Vec2] = []
    for p in points:
        if not out or math.dist(p, out[-1]) >= MIN_EDGE_MM:
            out.append(p)
    while len(out) > 2 and math.dist(out[0], out[-1]) < MIN_EDGE_MM:
        out.pop()
    return out


def band_solids(outer: np.ndarray, inner: np.ndarray | None, z0: float, z1: float,
                step: float = 12.0, cap_center: Vec2 | None = None) -> tuple[Solid, ...]:
    """Horizontal slices of the layer between two surface grids, as XY extrusions.

    ``outer``/``inner`` are (rows, cols, 3) grids whose columns rise in z.
    Where the inner surface has ended (the very top) a slice becomes a solid
    cap closed at ``cap_center``.
    """
    n = max(1, round((z1 - z0) / step))
    out: list[Solid] = []
    for i in range(n):
        za, zb = z0 + (z1 - z0) * i / n, z0 + (z1 - z0) * (i + 1) / n
        zm = (za + zb) / 2
        runs: list[list[tuple[Vec2, Vec2 | None]]] = [[]]
        for j in range(outer.shape[1]):
            po = _crossing(outer[:, j], zm)
            pi = _crossing(inner[:, j], zm) if inner is not None else None
            if po is None or (pi is None and cap_center is None):
                if runs[-1]:
                    runs.append([])
                continue
            runs[-1].append((po, pi))
        for run in runs:
            if len(run) < 2:
                continue
            outer_pts = [po for po, _ in run]
            if all(pi is not None for _, pi in run):
                loop = outer_pts + [pi for _, pi in reversed(run)]
            elif cap_center is not None:
                loop = outer_pts + [cap_center]
            else:
                continue
            loop = _clean(loop)
            if len(loop) >= 3 and abs(signed_area(tuple(loop))) > 4.0:
                out.append(Solid("XY", tuple(loop), (za, zb)))
    return tuple(out)


def section_solids(s: Section, step: float = 12.0, insets: tuple[float, float] = (0.0, SHELL)) -> tuple[Solid, ...]:
    outer = section_grid(s, insets[0], 4.0)
    inner = section_grid(s, insets[1], 4.0)
    z0, z1 = float(outer[..., 2].min()), float(outer[..., 2].max())
    cap = (CENTER[0], CENTER[1]) if reaches_apex(s) else None
    return band_solids(outer, inner, z0, z1, step, cap_center=cap)


def patch_solids(front: np.ndarray, back: np.ndarray, steps: int = 8) -> tuple[Solid, ...]:
    """Stepped extrusions of a thin curved or tilted plate given as two grids whose columns rise in z."""
    z0 = float(min(front[0, :, 2].min(), back[0, :, 2].min()))
    z1 = float(max(front[-1, :, 2].max(), back[-1, :, 2].max()))
    step = max(2.0, (z1 - z0) / steps)
    return band_solids(front, back, z0, z1, step)


def surface_point(theta_deg: float, phi_deg: float, inset: float = 0.0) -> Vec3:
    p = surface(np.array(math.radians(theta_deg)), np.array(math.radians(phi_deg)), inset)
    return float(p[0]), float(p[1]), float(p[2])


def inside_margin(points: np.ndarray) -> np.ndarray:
    """How far (mm, along the radius) each point sits inside the shell's inner surface."""
    v = np.asarray(points, float) - np.asarray(CENTER)
    dist = np.linalg.norm(v, axis=-1)
    theta = np.arctan2(v[..., 1], v[..., 0])
    phi = np.arcsin(np.clip(v[..., 2] / dist, -1.0, 1.0))
    return radius(theta, phi) - SHELL - dist
