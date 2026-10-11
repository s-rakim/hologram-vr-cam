"""Wiring schematic (sheet 4) generated from a product's wire list.

Signal wires are routed orthogonally through per-wire lanes; power and
ground connections are drawn as net flags so the sheet stays readable.
"""
from __future__ import annotations

from dataclasses import dataclass

from .product import Product, Ribbon, Wire
from .svg_draw import ACCENT, INK, MUTED, sheet, text

KIND_COLOUR = {
    "power": "#d1453b",
    "ground": "#1b2230",
    "i2c": "#2f6fde",
    "i2s": "#1f9d6a",
    "gpio": "#e08a12",
    "audio": "#7b8494",
    "video": "#8a4fd3",
    "analog": "#0f9fa8",
    "touch": "#b4559b",
}
ROW = 20
HEADER = 38
PIN_PITCH = 34


@dataclass
class PinPos:
    x: float
    y: float
    side: str   # edge the pin sits on: "L" or "R"


def _device_pins(product: Product) -> dict[tuple[str, str], PinPos]:
    sch = product.schematic
    pos: dict[tuple[str, str], PinPos] = {}
    for dev_id, (x, y, w, sides) in sch.layout.items():
        for i, pin in enumerate(product.devices[dev_id].pins):
            side = sides.get(pin, "L")
            pos[(dev_id, pin)] = PinPos(x if side == "L" else x + w, y + HEADER + ROW * i + ROW / 2, side)
    px, py, pw, _ = sch.compute_box
    for i, n in enumerate(sch.left_pins):
        pos[("pi", str(n))] = PinPos(px, py + 70 + PIN_PITCH * i, "L")
    for i, n in enumerate(sch.right_pins):
        pos[("pi", str(n))] = PinPos(px + pw, py + 70 + PIN_PITCH * i, "R")
    return pos


def _device_box(product: Product, dev_id: str) -> str:
    x, y, w, sides = product.schematic.layout[dev_id]
    dev = product.devices[dev_id]
    h = HEADER + ROW * len(dev.pins) + 6
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="#ffffff" stroke="{INK}" stroke-width="1.2"/>',
           text(x + 10, y + 17, dev.name, 12, 700),
           text(x + 10, y + 31, dev.location, 9.5, 400, MUTED)]
    for i, pin in enumerate(dev.pins):
        yy = y + HEADER + ROW * i + ROW / 2
        side = sides.get(pin, "L")
        if side == "L":
            out.append(text(x + 10, yy + 4, pin, 10.5, 500))
        else:
            out.append(text(x + w - 10, yy + 4, pin, 10.5, 500, INK, "end"))
        cx = x if side == "L" else x + w
        out.append(f'<circle cx="{cx}" cy="{yy}" r="2.6" fill="{INK}"/>')
    return "\n".join(out)


def _pi_box(product: Product) -> str:
    sch = product.schematic
    x, y, w, h = sch.compute_box
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#eef6f0" stroke="#1f7a46" stroke-width="1.6"/>',
           text(x + w / 2, y + 26, product.compute, 15, 700, "#13512e", "middle"),
           text(x + w / 2, y + 44, product.compute_location, 10, 400, MUTED, "middle")]
    for pins, side in ((sch.left_pins, "L"), (sch.right_pins, "R")):
        for i, n in enumerate(pins):
            yy = y + 70 + PIN_PITCH * i
            name = product.header[n] if isinstance(n, int) else ""
            label = (f"{n}  {name}" if side == "L" else f"{name}  {n}").strip()
            if side == "L":
                out.append(text(x + 10, yy + 4, label, 10.5, 600))
            else:
                out.append(text(x + w - 10, yy + 4, label, 10.5, 600, INK, "end"))
            out.append(f'<circle cx="{x if side == "L" else x + w}" cy="{yy}" r="3" fill="{INK}"/>')
    for i, line in enumerate(sch.power_notes):
        out.append(text(x + 10, y + h - 74 + i * 16, line, 9.5 if i else 9, 700 if i == 0 else 400,
                        MUTED if i == 0 else INK))
    return "\n".join(out)


def _flag(p: PinPos, net: str, hint: str) -> str:
    """Power/ground net flag hanging off a pin."""
    d = -1 if p.side == "L" else 1
    x2 = p.x + d * 16
    colour = KIND_COLOUR["ground" if net == "GND" else "power"]
    out = [f'<line x1="{p.x}" y1="{p.y}" x2="{x2}" y2="{p.y}" stroke="{colour}" stroke-width="1.4"/>']
    if net == "GND":
        for k, half in enumerate((6, 4, 2)):
            xx = x2 + d * k * 3
            out.append(f'<line x1="{xx}" y1="{p.y - half}" x2="{xx}" y2="{p.y + half}" stroke="{colour}" stroke-width="1.4"/>')
        tx = x2 + d * 12
    else:
        out.append(f'<path d="M{x2},{p.y} l{d * 6},-5 l{d * 6},5 l{-d * 6},5 z" fill="{colour}"/>')
        tx = x2 + d * 16
    label = net + (f" ({hint})" if hint else "")
    out.append(text(tx, p.y + 3.5, label, 9, 600, colour, "start" if d > 0 else "end"))
    return "\n".join(out)


def _net_name(product: Product, w: Wire) -> str:
    for end in (w.a, w.b):
        if end[0] == "pi":
            return product.header[int(end[1])].split()[0] if end[1].isdigit() else end[1]
    return "GND" if w.kind == "ground" else "5V"


def _route(p: PinPos, q: PinPos, lane: float, colour: str, width: float = 1.6) -> str:
    return (f'<polyline points="{p.x},{p.y} {lane},{p.y} {lane},{q.y} {q.x},{q.y}" fill="none" '
            f'stroke="{colour}" stroke-width="{width}" stroke-linejoin="round"/>')


def _lanes(wires: list[tuple[PinPos, PinPos]], x_near: float, x_far: float) -> list[float]:
    """Pick a lane per wire (Pi end first) so parallel runs do not cross."""
    order = sorted(range(len(wires)), key=lambda i: (wires[i][1].y > wires[i][0].y,
                                                     wires[i][0].y if wires[i][1].y <= wires[i][0].y
                                                     else -wires[i][0].y))
    step = (x_far - x_near) / max(1, len(wires) - 1)
    lanes = [0.0] * len(wires)
    for rank, i in enumerate(order):
        lanes[i] = x_near + step * rank
    return lanes


def _ribbon(r: Ribbon) -> str:
    pts = " ".join(f"{x},{y}" for x, y in r.points)
    c = KIND_COLOUR["video"]
    out = [f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="9" stroke-opacity="0.22" stroke-linejoin="round"/>',
           f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="1.4" stroke-dasharray="5 3"/>',
           text(r.label_xy[0], r.label_xy[1], r.label, 10, 600, c, r.anchor)]
    if r.box is not None:
        out.insert(0, _simple_box(*r.box))
    return "\n".join(out)


def _simple_box(x: float, y: float, w: float, h: float, title: str, sub: str) -> str:
    return "\n".join((
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="#ffffff" stroke="{INK}" stroke-width="1.2"/>',
        text(x + w / 2, y + h / 2 - 2, title, 12, 700, INK, "middle"),
        text(x + w / 2, y + h / 2 + 13, sub, 9.5, 400, MUTED, "middle"),
    ))


LEGEND = (("power", "Power"), ("ground", "Ground"), ("i2c", "I2C"), ("i2s", "I2S audio"),
          ("gpio", "GPIO"), ("analog", "Analog (battery sense)"), ("touch", "Capacitive touch"),
          ("audio", "Speaker"), ("video", "FPC / HDMI ribbon"))


def draw_schematic(product: Product) -> str:
    sch = product.schematic
    width, height = sch.size
    px, py, pw, ph = sch.compute_box
    pins = _device_pins(product)
    body = [*(_ribbon(r) for r in sch.ribbons), _pi_box(product), *(_device_box(product, d) for d in sch.layout)]

    left: list[tuple[Wire, PinPos, PinPos]] = []
    right: list[tuple[Wire, PinPos, PinPos]] = []
    local: list[tuple[Wire, PinPos, PinPos]] = []
    flags: list[tuple[PinPos, str, str]] = []
    for w in product.wires:
        if w.kind == "video":
            continue
        a, b = (w.b, w.a) if w.a[0] == "pi" else (w.a, w.b)   # a = device end, b = Pi end if any
        drawn_power = (w.a, w.b) in sch.drawn_power or (w.b, w.a) in sch.drawn_power
        if w.kind in ("power", "ground") and not drawn_power:
            for end, other in ((a, b), (b, a)):
                if end in pins:
                    hint = f"pin {other[1]}" if other[0] == "pi" and other[1].isdigit() else ""
                    flags.append((pins[end], _net_name(product, w), hint))
            continue
        if b[0] == "pi":
            (left if pins[b].side == "L" else right).append((w, pins[b], pins[a]))
        else:
            local.append((w, pins[a], pins[b]))

    wired = {(p.x, p.y) for _, p, q in left + right + local for p in (p, q)}
    unique: dict[tuple[float, float], tuple[PinPos, str, str]] = {}
    for p, net, hint in flags:   # one flag per unwired pin, preferring one that names a Pi pin
        key = (p.x, p.y)
        if key in wired:
            continue
        if key not in unique or (hint and not unique[key][2]):
            unique[key] = (p, net, hint)
    body += [_flag(*f) for f in unique.values()]

    shared = False
    for group, near, far in ((right, px + pw + 26, sch.right_lane_far), (left, px - 26, sch.left_lane_far)):
        lanes = _lanes([(pi, dev) for _, pi, dev in group], near, far)
        by_pin: dict[float, list[tuple[float, str]]] = {}
        for (w, pi, dev), lane in zip(group, lanes):
            body.append(_route(pi, dev, lane, KIND_COLOUR[w.kind]))
            by_pin.setdefault(pi.y, []).append((lane, w.kind))
        for y, ls in by_pin.items():   # junction dots where one Pi pin feeds two devices
            if len(ls) > 1:
                shared = True
                far_lane = max(ls, key=lambda v: abs(v[0] - (px + pw / 2)))
                for lane, kind in ls:
                    if lane != far_lane[0]:
                        body.append(f'<circle cx="{lane}" cy="{y}" r="3.4" fill="{KIND_COLOUR[kind]}"/>')

    for i, (w, p, q) in enumerate(local):
        lane = (p.x + q.x) / 2 + (i % 2) * 8 - 4
        body.append(_route(p, q, lane, KIND_COLOUR[w.kind]))

    for dev, pin, note in sch.pin_notes:      # wire notes that matter for the build
        p = pins[(dev, pin)]
        d = 1 if p.side == "R" else -1
        body.append(text(p.x + d * 12, p.y - 5, note, 9, 600, KIND_COLOUR["gpio"], "start" if d > 0 else "end"))

    lx, ly = sch.legend_xy
    kinds = {w.kind for w in product.wires}
    entries = [e for e in LEGEND if e[0] in kinds]
    body.append(text(lx, ly, "LEGEND", 10, 700, MUTED, extra='letter-spacing="1"'))
    for i, (kind, label) in enumerate(entries):
        y = ly + 22 + i * 22
        dash = ' stroke-dasharray="5 3"' if kind == "video" else ""
        body.append(f'<line x1="{lx}" y1="{y - 4}" x2="{lx + 34}" y2="{y - 4}" stroke="{KIND_COLOUR[kind]}" '
                    f'stroke-width="2.4"{dash}/>')
        body.append(text(lx + 44, y, label, 11))
    y = ly + 22 + len(entries) * 22 + 14
    body.append(text(lx, y, "Flags: a red arrow is a power net, the bars are ground;", 10, 400, MUTED))
    body.append(text(lx, y + 16, "'pin N' names the header pin that net is wired to.", 10, 400, MUTED))
    if shared:
        body.append(text(lx, y + 40, "A dot on a lane = one header pin feeding two devices.", 10, 400, ACCENT))

    return sheet(product, width, height, f"{product.title} - WIRING SCHEMATIC",
                 f"Every connection, generated from cad/products/{product.key}.py (pin table: docs/{product.key}/wiring.md)",
                 "4 / 4", "\n".join(body))
