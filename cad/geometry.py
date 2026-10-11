"""Dependency-free solid geometry shared by every CAD exporter.

The model is built only from *extrusions*: a closed 2D profile (with optional
holes) drawn on one of the three principal planes and pushed along that
plane's normal axis. That is exactly what Revit's ``NewExtrusion`` and IFC's
``IfcExtrudedAreaSolid`` understand, so the same solids feed the Revit
script, the IFC file and the SVG drawings without any translation loss.

World axes (millimetres): X = wearer's right, Y = forward (where the wearer
looks), Z = up. The origin is the centre of the bridge on the back face of
the front frame.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Loop = tuple[Vec2, ...]

# Sketch plane -> (u axis, v axis, index of the world axis it is extruded along)
PLANES: dict[str, tuple[Vec3, Vec3, int]] = {
    "XZ": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), 1),
    "YZ": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), 0),
    "XY": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), 2),
}

# Revit rejects curves shorter than its ShortCurveTolerance (~0.8 mm), so arcs
# are never split into edges shorter than this.
MIN_EDGE_MM = 1.0


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a: Vec3, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def normalize(a: Vec3) -> Vec3:
    n = math.sqrt(dot(a, a))
    if n == 0:
        raise ValueError("cannot normalise a zero vector")
    return (a[0] / n, a[1] / n, a[2] / n)


def plane_normal(plane: str) -> Vec3:
    u, v, _ = PLANES[plane]
    return cross(u, v)


def signed_area(loop: Loop) -> float:
    area = 0.0
    for i, (x0, y0) in enumerate(loop):
        x1, y1 = loop[(i + 1) % len(loop)]
        area += x0 * y1 - x1 * y0
    return area / 2.0


def dedupe(points: list[Vec2], tol: float = 1e-6) -> list[Vec2]:
    """Drop consecutive duplicates (including a repeated closing point)."""
    out: list[Vec2] = []
    for p in points:
        if not out or math.dist(p, out[-1]) > tol:
            out.append(p)
    while len(out) > 1 and math.dist(out[0], out[-1]) <= tol:
        out.pop()
    return out


def arc(cx: float, cy: float, r: float, a0: float, a1: float,
        min_edge: float = MIN_EDGE_MM, max_segments: int = 12) -> list[Vec2]:
    """Points along an arc (inclusive of both ends), edges >= ``min_edge``."""
    sweep = a1 - a0
    n = max(1, min(max_segments, int(abs(sweep) * r / min_edge)))
    while n > 1 and 2 * r * math.sin(abs(sweep) / (2 * n)) < min_edge:
        n -= 1
    return [(cx + r * math.cos(a0 + sweep * i / n), cy + r * math.sin(a0 + sweep * i / n))
            for i in range(n + 1)]


def rect(cx: float, cy: float, w: float, h: float, r: float = 0.0) -> Loop:
    """Axis-aligned (optionally rounded) rectangle, counter-clockwise."""
    r = max(0.0, min(r, w / 2, h / 2))
    if r * math.sqrt(2) < MIN_EDGE_MM:   # a one-edge corner would still be too short for Revit
        return ((cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2),
                (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2))
    hw, hh = w / 2 - r, h / 2 - r
    pts: list[Vec2] = []
    for (sx, sy), start in (((1, 1), 0.0), ((-1, 1), 90.0), ((-1, -1), 180.0), ((1, -1), 270.0)):
        pts += arc(cx + sx * hw, cy + sy * hh, r, math.radians(start), math.radians(start + 90))
    return tuple(dedupe(pts))


def circle(cx: float, cy: float, r: float) -> Loop:
    return tuple(dedupe(arc(cx, cy, r, 0.0, 2 * math.pi, max_segments=24)))


def poly(*points: Vec2) -> Loop:
    return tuple(dedupe(list(points)))


def ellipse_arc(cx: float, cy: float, rx: float, ry: float, a0: float, a1: float,
                min_edge: float = MIN_EDGE_MM, max_segments: int = 48) -> list[Vec2]:
    """Points along an elliptical arc (inclusive of both ends)."""
    sweep = a1 - a0
    n = max(1, min(max_segments, int(abs(sweep) * max(rx, ry) / (2 * min_edge))))

    def pt(i: int) -> Vec2:
        a = a0 + sweep * i / n
        return (cx + rx * math.cos(a), cy + ry * math.sin(a))

    pts = [pt(i) for i in range(n + 1)]
    while n > 1 and min(math.dist(pts[i], pts[i + 1]) for i in range(n)) < min_edge:
        n -= 1
        pts = [pt(i) for i in range(n + 1)]
    return pts


def ellipse_band(cx: float, cy: float, rx_out: float, ry_out: float, rx_in: float, ry_in: float,
                 a0: float, a1: float, max_segments: int = 48) -> Loop:
    """Closed outline of an elliptical ring sector between angles a0..a1 (radians)."""
    outer = ellipse_arc(cx, cy, rx_out, ry_out, a0, a1, max_segments=max_segments)
    inner = ellipse_arc(cx, cy, rx_in, ry_in, a1, a0, max_segments=max_segments)
    return tuple(dedupe(outer + inner))


def offset_convex(loop: Loop, d: float) -> Loop:
    """Shrink a convex counter-clockwise polygon by ``d`` (grow if negative)."""
    n = len(loop)
    lines = []
    for i in range(n):
        (x0, y0), (x1, y1) = loop[i], loop[(i + 1) % n]
        ex, ey = x1 - x0, y1 - y0
        length = math.hypot(ex, ey)
        nx, ny = -ey / length, ex / length            # inward normal for CCW
        lines.append(((x0 + nx * d, y0 + ny * d), (ex, ey)))
    out = []
    for i in range(n):
        (px, py), (dx, dy) = lines[i - 1]
        (qx, qy), (ex, ey) = lines[i]
        den = dx * ey - dy * ex
        if abs(den) < 1e-12:
            out.append((qx, qy))
            continue
        t = ((qx - px) * ey - (qy - py) * ex) / den
        out.append((px + dx * t, py + dy * t))
    return tuple(out)


def _ccw(loop: Loop) -> Loop:
    return loop if signed_area(loop) > 0 else tuple(reversed(loop))


def _cw(loop: Loop) -> Loop:
    return loop if signed_area(loop) < 0 else tuple(reversed(loop))


@dataclass(frozen=True)
class Solid:
    """A profile on ``plane`` extruded across ``span`` along the plane normal.

    ``span`` is the (min, max) world coordinate on the extrusion axis (Y for
    an XZ sketch, X for YZ, Z for XY). The outer loop is stored
    counter-clockwise and holes clockwise, as seen from the plane normal.
    """

    plane: str
    outer: Loop
    span: tuple[float, float]
    holes: tuple[Loop, ...] = ()

    def __post_init__(self) -> None:
        if self.plane not in PLANES:
            raise ValueError(f"unknown plane {self.plane!r}")
        if not self.span[1] > self.span[0]:
            raise ValueError(f"empty extrusion span {self.span}")
        if len(self.outer) < 3:
            raise ValueError("profile needs at least three points")
        object.__setattr__(self, "outer", _ccw(tuple(self.outer)))
        object.__setattr__(self, "holes", tuple(_cw(tuple(h)) for h in self.holes))

    @property
    def axis(self) -> int:
        return PLANES[self.plane][2]

    @property
    def normal(self) -> Vec3:
        return plane_normal(self.plane)

    @property
    def depth(self) -> float:
        return self.span[1] - self.span[0]

    @property
    def start(self) -> float:
        """Coordinate of the sketch plane, so extruding +depth along the
        normal covers exactly ``span`` (the XZ normal points to -Y)."""
        return self.span[0] if self.normal[self.axis] > 0 else self.span[1]

    def point3(self, p: Vec2, s: float) -> Vec3:
        u, v, axis = PLANES[self.plane]
        xyz = [u[i] * p[0] + v[i] * p[1] for i in range(3)]
        xyz[axis] = s
        return (xyz[0], xyz[1], xyz[2])

    def loops(self) -> tuple[Loop, ...]:
        return (self.outer, *self.holes)

    def translated(self, d: Vec3) -> Solid:
        u, v, axis = PLANES[self.plane]
        du, dv = dot(d, u), dot(d, v)

        def move(loop: Loop) -> Loop:
            return tuple((x + du, y + dv) for x, y in loop)

        return Solid(self.plane, move(self.outer),
                     (self.span[0] + d[axis], self.span[1] + d[axis]),
                     tuple(move(h) for h in self.holes))

    def mirrored_x(self) -> Solid:
        """Mirror across the YZ plane (left part from a right part)."""
        if self.plane == "YZ":
            return Solid(self.plane, self.outer, (-self.span[1], -self.span[0]), self.holes)

        def flip(loop: Loop) -> Loop:
            return tuple((-x, y) for x, y in loop)

        return Solid(self.plane, flip(self.outer), self.span, tuple(flip(h) for h in self.holes))

    def faces(self) -> list[tuple[tuple[tuple[Vec3, ...], ...], Vec3]]:
        """Boundary faces as (loops, outward normal); caps keep their holes."""
        n = self.normal
        s0, s1 = self.span
        lo = tuple(tuple(self.point3(p, s0) for p in loop) for loop in self.loops())
        hi = tuple(tuple(self.point3(p, s1) for p in loop) for loop in self.loops())
        # The +normal cap is whichever end lies further along the normal.
        far, near = (hi, lo) if n[self.axis] > 0 else (lo, hi)
        out = [(far, n), (near, scale(n, -1.0))]
        for loop_lo, loop_hi in zip(lo, hi):
            for i in range(len(loop_lo)):
                j = (i + 1) % len(loop_lo)
                edge = sub(loop_lo[j], loop_lo[i])
                out.append((((loop_lo[i], loop_lo[j], loop_hi[j], loop_hi[i]),),
                            normalize(cross(edge, n))))
        return out

    def bbox(self) -> tuple[Vec3, Vec3]:
        pts = [self.point3(p, s) for p in self.outer for s in self.span]
        return (tuple(min(p[i] for p in pts) for i in range(3)),  # type: ignore[return-value]
                tuple(max(p[i] for p in pts) for i in range(3)))

    def volume(self) -> float:
        return (signed_area(self.outer) + sum(signed_area(h) for h in self.holes)) * self.depth


def bbox_union(boxes: list[tuple[Vec3, Vec3]]) -> tuple[Vec3, Vec3]:
    return (tuple(min(b[0][i] for b in boxes) for i in range(3)),  # type: ignore[return-value]
            tuple(max(b[1][i] for b in boxes) for i in range(3)))
