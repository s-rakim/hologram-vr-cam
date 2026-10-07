"""SVG drawings of the glasses: x-ray isometric, exploded view and a
third-angle orthographic sheet with dimensions.

A tiny painter's-algorithm renderer: every extrusion is broken into faces,
back faces are culled, the rest are sorted far-to-near and written as SVG
paths. No dependencies, deterministic output.
"""
from __future__ import annotations

import html
from dataclasses import dataclass

from .geometry import Vec3, add, cross, dot, normalize
from .spec import FRAME_HALF_WIDTH, IPD, LENS_CENTER_X, LENS_W, MATERIALS, PARTS, POD_Y, Part, overall_envelope

FONT = "Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif"
INK = "#1b2230"
MUTED = "#5b6475"
PAPER = "#f6f7f9"
ACCENT = "#2f6fde"
LIGHT = normalize((-0.35, 0.55, 0.85))


@dataclass(frozen=True)
class Camera:
    toward_viewer: Vec3
    up_hint: Vec3 = (0.0, 0.0, 1.0)

    @property
    def basis(self) -> tuple[Vec3, Vec3, Vec3]:
        c = normalize(self.toward_viewer)
        r = normalize(cross(self.up_hint, c))
        return r, cross(c, r), c

    def project(self, p: Vec3) -> tuple[float, float, float]:
        r, u, c = self.basis
        return dot(p, r), -dot(p, u), -dot(p, c)   # screen x, screen y (down), depth (far = big)


FRONT = Camera((0.0, 1.0, 0.0))
TOP = Camera((0.0, 0.0, 1.0), (0.0, -1.0, 0.0))
SIDE = Camera((-1.0, 0.0, 0.0))                     # third-angle right-side view
ISO = Camera((0.95, 1.0, 0.72))


@dataclass
class Face:
    loops: list[list[tuple[float, float]]]
    depth: float
    fill: str
    fill_opacity: float
    stroke: str
    part: str


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _shade(rgb: tuple[int, int, int], normal: Vec3) -> tuple[str, str]:
    lam = max(0.0, dot(normal, LIGHT))
    k = 0.62 + 0.5 * lam
    lift = 34 * lam
    fill = tuple(c * k + lift for c in rgb)
    edge = tuple(c * 0.55 for c in rgb)
    return _hex(fill), _hex(edge)


def collect_faces(parts: tuple[Part, ...], cam: Camera, *, xray: bool = False, flat: bool = False,
                  explode: float = 0.0) -> list[Face]:
    _, _, toward = cam.basis
    faces: list[Face] = []
    for part in parts:
        mat = MATERIALS[part.material]
        offset = tuple(e * explode for e in part.explode)
        see_through = xray and mat.shell
        for solid in part.solids:
            for loops3, normal in solid.faces():
                if dot(normal, toward) <= 1e-9:
                    continue  # back face
                pts = [[cam.project(add(p, offset)) for p in loop] for loop in loops3]  # type: ignore[arg-type]
                depth = sum(p[2] for p in pts[0]) / len(pts[0])
                if flat:
                    tint = tuple(255 - (255 - c) * 0.22 for c in mat.rgb)
                    fill, stroke, opacity = _hex(tint), INK, 1.0
                else:
                    fill, stroke = _shade(mat.rgb, normal)
                    opacity = 1.0 - mat.transparency / 100.0 * 0.6
                    if see_through:
                        opacity = min(opacity, 0.16 if mat.transparency else 0.22)
                faces.append(Face([[(x, y) for x, y, _ in loop] for loop in pts], depth, fill, opacity, stroke,
                                  part.id))
    faces.sort(key=lambda f: -f.depth)
    return faces


def faces_bounds(faces: list[Face]) -> tuple[float, float, float, float]:
    xs = [x for f in faces for loop in f.loops for x, _ in loop]
    ys = [y for f in faces for loop in f.loops for _, y in loop]
    return min(xs), min(ys), max(xs), max(ys)


@dataclass
class Fit:
    scale: float
    tx: float
    ty: float

    def __call__(self, x: float, y: float) -> tuple[float, float]:
        return x * self.scale + self.tx, y * self.scale + self.ty


def fit_box(bounds: tuple[float, float, float, float], box: tuple[float, float, float, float],
            scale: float | None = None) -> Fit:
    x0, y0, x1, y1 = bounds
    bx, by, bw, bh = box
    s = scale or min(bw / (x1 - x0), bh / (y1 - y0))
    return Fit(s, bx + (bw - (x1 - x0) * s) / 2 - x0 * s, by + (bh - (y1 - y0) * s) / 2 - y0 * s)


def faces_svg(faces: list[Face], fit: Fit, stroke_width: float = 0.6) -> str:
    out = []
    for f in faces:
        d = " ".join("M" + " L".join(f"{fit(x, y)[0]:.2f},{fit(x, y)[1]:.2f}" for x, y in loop) + " Z"
                     for loop in f.loops)
        out.append(f'<path d="{d}" fill="{f.fill}" fill-opacity="{f.fill_opacity:.2f}" stroke="{f.stroke}" '
                   f'stroke-opacity="{min(1.0, f.fill_opacity + 0.35):.2f}" stroke-width="{stroke_width}" '
                   f'stroke-linejoin="round" fill-rule="evenodd"/>')
    return "\n".join(out)


def text(x: float, y: float, s: str, size: float = 12, weight: int = 400, fill: str = INK,
         anchor: str = "start", extra: str = "") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}" {extra}>{html.escape(s)}</text>')


def sheet(width: int, height: int, title: str, subtitle: str, number: str, body: str) -> str:
    """Drawing border and title block around ``body``."""
    tb_w, tb_h = 380, 92
    tx, ty = width - tb_w - 24, height - tb_h - 24
    env = overall_envelope()
    rows = [
        ("PROJECT", "Hologram VR Cam glasses"),
        ("DRAWN BY", "Malcolm Opondo"),
        ("UNITS / SIZE", f"mm  |  {env.width:.0f} W x {env.depth:.0f} D x {env.height:.0f} H"),
    ]
    tb = [f'<rect x="{tx}" y="{ty}" width="{tb_w}" height="{tb_h}" fill="#ffffff" stroke="{INK}" stroke-width="1.2"/>',
          f'<line x1="{tx + 290}" y1="{ty}" x2="{tx + 290}" y2="{ty + tb_h}" stroke="{INK}" stroke-width="0.8"/>']
    for i, (k, v) in enumerate(rows):
        y = ty + 22 + i * 26
        tb.append(text(tx + 10, y - 6, k, 8, 600, MUTED, extra='letter-spacing="0.8"'))
        tb.append(text(tx + 10, y + 6, v, 11, 500))
        if i:
            tb.append(f'<line x1="{tx}" y1="{y - 18}" x2="{tx + 290}" y2="{y - 18}" stroke="{INK}" stroke-width="0.5"/>')
    tb.append(text(tx + 335, ty + 28, "SHEET", 8, 600, MUTED, "middle", 'letter-spacing="0.8"'))
    tb.append(text(tx + 335, ty + 62, number, 26, 700, INK, "middle"))
    return "\n".join((
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{PAPER}"/>',
        f'<rect x="12" y="12" width="{width - 24}" height="{height - 24}" fill="none" stroke="{INK}" stroke-width="1.6"/>',
        text(36, 52, title, 22, 700),
        text(36, 74, subtitle, 12.5, 400, MUTED),
        body,
        *tb,
        "</svg>",
    ))


# --------------------------------------------------------------------------
# Sheet 1: assembled x-ray isometric
# --------------------------------------------------------------------------
ACCESSORIES = ("visor", "magnets")


def draw_assembly() -> str:
    width, height = 1500, 900
    worn = tuple(p for p in PARTS if p.id not in ACCESSORIES)
    faces = collect_faces(worn, ISO, xray=True)
    model_box = (330.0, 110.0, width - 660.0, 660.0)
    fit = fit_box(faces_bounds(faces), model_box)
    body = [faces_svg(faces, fit, 0.7)]

    callouts = [
        ("camera", "POV camera", "OV5647 5 MP, 1080p30 H.264 video"),
        ("privacy_led", "Privacy LED", "Lit whenever the camera records"),
        ("pi_zero_2w", "Raspberry Pi Zero 2 W", "Capture, encode, head-tracked render"),
        ("battery", "Power pod (left temple)", "1000 mAh LiPo + charger / 5 V boost"),
        ("oled_right", "Stereo display", "2x 1080p micro-OLED + birdbath optics"),
        ("imu", "Head tracking", "MPU-6050 IMU, 3DoF orientation"),
        ("microphone", "Microphone", "INMP441 I2S MEMS, records audio"),
        ("capture_button", "Capture button", "Press = photo, hold = video"),
        ("touch_strip", "Touch strip", "Tap = mode, double tap = recenter"),
        ("speaker", "Open-ear speaker", "Driven by a MAX98357A I2S amp"),
    ]
    body.append(_callouts(callouts, ISO, fit, width, model_box[0] + model_box[2] / 2))
    body.append(text(36, height - 36, "Shells drawn translucent so the electronics are visible. "
                     "Wearer's right temple in front; magnetic VR visor not shown.", 11, 400, MUTED))
    return sheet(width, height, "HOLOGRAM VR CAM - ASSEMBLY (X-RAY ISOMETRIC)",
                 "VR display glasses with a POV video camera, driven by a Raspberry Pi Zero 2 W", "1 / 4",
                 "\n".join(body))


def _part_anchor(part: Part, cam: Camera, fit: Fit, explode: float = 0.0) -> tuple[float, float]:
    biggest = max(part.solids, key=lambda s: abs(s.volume()))
    lo, hi = biggest.bbox()
    centre = tuple((a + b) / 2 + e * explode for a, b, e in zip(lo, hi, part.explode))
    x, y, _ = cam.project(centre)  # type: ignore[arg-type]
    return fit(x, y)


def _callouts(items: list[tuple[str, str, str]], cam: Camera, fit: Fit, width: int, split_x: float) -> str:
    """Two-line labels stacked in the left and right margins with leader lines."""
    parts = {p.id: p for p in PARTS}
    anchors = [(_part_anchor(parts[pid], cam, fit), title, detail) for pid, title, detail in items]
    left = sorted([a for a in anchors if a[0][0] < split_x], key=lambda a: a[0][1])
    right = sorted([a for a in anchors if a[0][0] >= split_x], key=lambda a: a[0][1])
    out = []
    for column, x_text, anchor, x_lead in ((left, 40, "start", 300), (right, width - 40, "end", width - 300)):
        ys = _spread([a[0][1] for a in column], 150, 760, 58)
        for ((ax, ay), title, detail), ty in zip(column, ys):
            out.append(f'<polyline points="{x_text:.1f},{ty + 8:.1f} {x_lead:.1f},{ty + 8:.1f} {ax:.1f},{ay:.1f}" '
                       f'fill="none" stroke="{ACCENT}" stroke-width="1" stroke-opacity="0.85"/>')
            out.append(f'<circle cx="{ax:.1f}" cy="{ay:.1f}" r="3.2" fill="{ACCENT}"/>')
            out.append(text(x_text, ty - 10, title, 12.5, 700, INK, anchor))
            out.append(text(x_text, ty + 4, detail, 11, 400, MUTED, anchor))
    return "\n".join(out)


def _spread(ys: list[float], lo: float, hi: float, gap: float) -> list[float]:
    """Nudge sorted label positions apart by at least ``gap`` inside [lo, hi]."""
    out: list[float] = []
    for y in ys:
        y = max(lo, y if not out else max(y, out[-1] + gap))
        out.append(y)
    overflow = (out[-1] - hi) if out else 0
    if overflow > 0:
        out = [y - overflow for y in out]
        for i in range(len(out) - 2, -1, -1):
            out[i] = min(out[i], out[i + 1] - gap)
    return out


# --------------------------------------------------------------------------
# Sheet 2: exploded view with numbered balloons and parts list
# --------------------------------------------------------------------------
def draw_exploded() -> str:
    width, height = 1600, 1000
    faces = collect_faces(PARTS, ISO, explode=1.0)
    fit = fit_box(faces_bounds(faces), (40, 100, 1080, 800))
    body = [faces_svg(faces, fit, 0.6)]

    # One balloon per BOM-visible part, de-duplicating mirrored pairs.
    numbered: list[tuple[int, Part, str]] = []
    seen: dict[str, int] = {}
    for part in PARTS:
        base = part.name.replace(" (left)", "").replace(" (right)", "").replace(" (left eye)", "") \
            .replace(" (right eye)", "").replace(" (left temple)", "").replace(" (right temple)", "")
        if base not in seen:
            seen[base] = len(seen) + 1
        numbered.append((seen[base], part, base))

    for n, part, _ in numbered:
        x, y = _part_anchor(part, ISO, fit, 1.0)
        body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="#ffffff" stroke="{ACCENT}" stroke-width="1.4"/>')
        body.append(text(x, y + 3.6, str(n), 9.5, 700, ACCENT, "middle"))

    # Parts list.
    lx, ly = 1150, 110
    body.append(f'<rect x="{lx - 14}" y="{ly - 22}" width="{width - lx - 22}" height="{len(seen) * 21.5 + 40}" '
                f'fill="#ffffff" stroke="{INK}" stroke-width="0.8"/>')
    body.append(text(lx, ly, "PARTS", 10, 700, MUTED, extra='letter-spacing="1"'))
    counts: dict[int, int] = {}
    for n, _, _ in numbered:
        counts[n] = counts.get(n, 0) + 1
    for base, n in seen.items():
        y = ly + 8 + n * 21.5
        qty = counts[n]
        body.append(f'<circle cx="{lx + 8}" cy="{y - 4}" r="8" fill="#ffffff" stroke="{ACCENT}" stroke-width="1.2"/>')
        body.append(text(lx + 8, y - 0.5, str(n), 8.5, 700, ACCENT, "middle"))
        body.append(text(lx + 24, y, base + (f"  x{qty}" if qty > 1 else ""), 11))
    body.append(text(36, height - 36, "Parts are pulled apart along their assembly direction. "
                     "Balloon numbers match the parts list and the BOM in docs/bom.md.", 11, 400, MUTED))
    return sheet(width, height, "HOLOGRAM VR CAM - EXPLODED ASSEMBLY",
                 "Build order: frame > optics > brow electronics > temples (compute right, power left) > visor",
                 "2 / 4", "\n".join(body))


# --------------------------------------------------------------------------
# Sheet 3: orthographic views with dimensions
# --------------------------------------------------------------------------
def _dim(p1: tuple[float, float], p2: tuple[float, float], offset: float, label: str,
         vertical: bool = False) -> str:
    """Linear dimension between two drawing points, offset perpendicular."""
    (x1, y1), (x2, y2) = p1, p2
    out = []
    if vertical:
        x = min(x1, x2) + offset if offset > 0 else min(x1, x2) + offset
        out += [f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x:.1f}" y2="{y1:.1f}" stroke="{MUTED}" stroke-width="0.6"/>',
                f'<line x1="{x2:.1f}" y1="{y2:.1f}" x2="{x:.1f}" y2="{y2:.1f}" stroke="{MUTED}" stroke-width="0.6"/>',
                f'<line x1="{x:.1f}" y1="{y1:.1f}" x2="{x:.1f}" y2="{y2:.1f}" stroke="{INK}" stroke-width="0.9" '
                f'marker-start="url(#arrow)" marker-end="url(#arrow)"/>',
                text(x - 6, (y1 + y2) / 2, label, 11, 600, INK, "middle",
                     f'transform="rotate(-90 {x - 6:.1f} {(y1 + y2) / 2:.1f})"')]
    else:
        y = max(y1, y2) + offset
        out += [f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x1:.1f}" y2="{y:.1f}" stroke="{MUTED}" stroke-width="0.6"/>',
                f'<line x1="{x2:.1f}" y1="{y2:.1f}" x2="{x2:.1f}" y2="{y:.1f}" stroke="{MUTED}" stroke-width="0.6"/>',
                f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" stroke="{INK}" stroke-width="0.9" '
                f'marker-start="url(#arrow)" marker-end="url(#arrow)"/>',
                text((x1 + x2) / 2, y - 5, label, 11, 600, INK, "middle")]
    return "\n".join(out)


def draw_orthographic() -> str:
    width, height = 1500, 1080
    scale = 3.0
    worn = tuple(p for p in PARTS if p.id not in ACCESSORIES)
    views = {name: collect_faces(worn, cam, flat=True) for name, cam in
             (("front", FRONT), ("top", TOP), ("side", SIDE))}
    b = {k: faces_bounds(v) for k, v in views.items()}

    front_w = (b["front"][2] - b["front"][0]) * scale
    front_h = (b["front"][3] - b["front"][1]) * scale
    top_h = (b["top"][3] - b["top"][1]) * scale
    side_w = (b["side"][2] - b["side"][0]) * scale
    left, gap = 130, 110
    top_y = 120
    front_y = top_y + top_h + gap

    fits = {
        "top": fit_box(b["top"], (left, top_y, front_w, top_h), scale),
        "front": fit_box(b["front"], (left, front_y, front_w, front_h), scale),
        "side": fit_box(b["side"], (left + front_w + gap + 40, front_y, side_w, front_h), scale),
    }
    body = ['<defs><marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0,1 L9,5 L0,9 z" fill="{INK}"/></marker></defs>']
    for name in ("top", "front", "side"):
        body.append(faces_svg(views[name], fits[name], 0.55))

    def pt(view: str, cam: Camera, p: Vec3) -> tuple[float, float]:
        x, y, _ = cam.project(p)
        return fits[view](x, y)

    env = overall_envelope()
    f = fits["front"]
    fx0, fy0 = f(b["front"][0], b["front"][1])
    fx1, fy1 = f(b["front"][2], b["front"][3])
    body.append(_dim((fx0, fy1), (fx1, fy1), 52, f"{env.width:.0f}"))
    body.append(_dim((fx0, fy0), (fx0, fy1), -34, f"{env.height:.0f}", vertical=True))
    lens_l = pt("front", FRONT, (LENS_CENTER_X - LENS_W / 2, 0, 22))
    lens_r = pt("front", FRONT, (LENS_CENTER_X + LENS_W / 2, 0, 22))
    body.append(_dim(lens_r, lens_l, -16, f"lens {LENS_W:.0f}"))
    bridge_l = pt("front", FRONT, (LENS_CENTER_X - LENS_W / 2, 0, 22))
    bridge_r = pt("front", FRONT, (-(LENS_CENTER_X - LENS_W / 2), 0, 22))
    body.append(_dim(bridge_l, bridge_r, -16, f"{2 * (LENS_CENTER_X - LENS_W / 2):.0f}"))
    oc_l = pt("front", FRONT, (-IPD / 2, 0, -24))
    oc_r = pt("front", FRONT, (IPD / 2, 0, -24))
    body.append(_dim(oc_r, oc_l, 20, f"IPD {IPD:.0f} (optical centres)"))

    s = fits["side"]
    sx0, sy0 = s(b["side"][0], b["side"][1])
    sx1, sy1 = s(b["side"][2], b["side"][3])
    body.append(_dim((sx0, sy1), (sx1, sy1), 46, f"{env.depth:.0f}"))
    pod_a = pt("side", SIDE, (-FRAME_HALF_WIDTH, POD_Y[1], 22))
    pod_b = pt("side", SIDE, (-FRAME_HALF_WIDTH, POD_Y[0], 22))
    body.append(_dim(pod_a, pod_b, -16, f"pod {POD_Y[1] - POD_Y[0]:.0f}"))

    t = fits["top"]
    tx0, ty0 = t(b["top"][0], b["top"][1])
    tx1, ty1 = t(b["top"][2], b["top"][3])
    body.append(_dim((tx1, ty0), (tx1, ty1), 34, f"{env.depth:.0f}", vertical=True))

    for name, label in (("top", "TOP VIEW"), ("front", "FRONT VIEW"), ("side", "RIGHT-SIDE VIEW (wearer's left)")):
        x0, y0 = fits[name](b[name][0], b[name][1])
        body.append(text(x0, y0 - (44 if name != "top" else 14), label, 10.5, 700, MUTED,
                         extra='letter-spacing="1"'))

    iso = collect_faces(worn, ISO, xray=True)
    iso_fit = fit_box(faces_bounds(iso), (left + front_w + gap + 60, top_y + 190, 560, 300))
    body.append(faces_svg(iso, iso_fit, 0.5))

    notes = [
        "NOTES",
        "1. Third-angle projection. Dimensions in mm. Visor not shown.",
        "2. Frame, brow bay, pods and arms: SLS PA12 nylon, 1.5 mm walls.",
        f"3. Lens {LENS_W:.0f} mm, bridge {2 * (LENS_CENTER_X - LENS_W / 2):.0f} mm, "
        f"optical centres at {IPD:.0f} mm IPD.",
        "4. Temples flex ~5 deg outward when worn; model shows them parallel.",
        "5. Source of truth: cad/spec.py (regenerate with python -m cad.generate).",
    ]
    nx, ny = left + front_w + gap + 40, top_y + 40
    for i, line in enumerate(notes):
        body.append(text(nx, ny + i * 22, line, 12 if i else 10.5, 700 if i == 0 else 400,
                         MUTED if i == 0 else INK, extra='letter-spacing="1"' if i == 0 else ""))
    return sheet(width, height, "HOLOGRAM VR CAM - ORTHOGRAPHIC VIEWS",
                 "Overall dimensions and key optical spacing", "3 / 4", "\n".join(body))


__all__ = ["Camera", "collect_faces", "draw_assembly", "draw_exploded", "draw_orthographic"]
