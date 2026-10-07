"""Wiring schematic (sheet 4) generated from :data:`cad.spec.WIRES`.

Signal wires are routed orthogonally through per-wire lanes; power and
ground connections are drawn as net flags so the sheet stays readable.
"""
from __future__ import annotations

from dataclasses import dataclass

from .spec import DEVICES, PI_HEADER, WIRES, Wire
from .svg_draw import ACCENT, INK, MUTED, sheet, text

KIND_COLOUR = {
    "power": "#d1453b",
    "ground": "#1b2230",
    "i2c": "#2f6fde",
    "i2s": "#1f9d6a",
    "gpio": "#e08a12",
    "audio": "#7b8494",
    "video": "#8a4fd3",
}
ROW = 20
HEADER = 38

# Device placement: (x, y, width) and which edge each pin sits on.
LAYOUT: dict[str, tuple[float, float, float, dict[str, str]]] = {
    "battery": (44, 130, 140, {"+": "R", "-": "R"}),
    "switch": (44, 300, 140, {"COM": "R", "NO": "R"}),
    "boost": (270, 130, 170, {"BAT": "L", "EN": "L", "5V": "R", "LBO": "R", "GND": "R"}),
    "led": (270, 330, 170, {"CTRL": "R", "5V": "R", "GND": "R"}),
    "imu": (1180, 100, 220, {}),
    "button": (1180, 250, 220, {}),
    "touch": (1180, 340, 220, {}),
    "mic": (1180, 450, 220, {}),
    "amp": (1180, 620, 220, {"OUT+": "R", "OUT-": "R"}),
    "speaker": (1452, 720, 104, {"+": "L", "-": "L"}),
}
PI_BOX = (650.0, 250.0, 280.0, 450.0)
PI_LEFT = (2, 16, 15)
PI_RIGHT = (3, 5, 7, 11, 13, 12, 35, 38, 40)
DRAWN_POWER = {(("battery", "+"), ("boost", "BAT")), (("boost", "5V"), ("pi", "2"))}


@dataclass
class PinPos:
    x: float
    y: float
    side: str   # edge the pin sits on: "L" or "R"


def _device_pins() -> dict[tuple[str, str], PinPos]:
    pos: dict[tuple[str, str], PinPos] = {}
    for dev_id, (x, y, w, sides) in LAYOUT.items():
        for i, pin in enumerate(DEVICES[dev_id].pins):
            side = sides.get(pin, "L")
            pos[(dev_id, pin)] = PinPos(x if side == "L" else x + w, y + HEADER + ROW * i + ROW / 2, side)
    px, py, pw, _ = PI_BOX
    for i, n in enumerate(PI_LEFT):
        pos[("pi", str(n))] = PinPos(px, py + 70 + 34 * i, "L")
    for i, n in enumerate(PI_RIGHT):
        pos[("pi", str(n))] = PinPos(px + pw, py + 70 + 34 * i, "R")
    return pos


def _device_box(dev_id: str) -> str:
    x, y, w, sides = LAYOUT[dev_id]
    dev = DEVICES[dev_id]
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


def _pi_box() -> str:
    x, y, w, h = PI_BOX
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#eef6f0" stroke="#1f7a46" stroke-width="1.6"/>',
           text(x + w / 2, y + 26, "Raspberry Pi Zero 2 W", 15, 700, "#13512e", "middle"),
           text(x + w / 2, y + 44, "Right temple pod  |  40-pin header pads", 10, 400, MUTED, "middle")]
    for pins, side in ((PI_LEFT, "L"), (PI_RIGHT, "R")):
        for i, n in enumerate(pins):
            yy = y + 70 + 34 * i
            label = f"{n}  {PI_HEADER[n]}" if side == "L" else f"{PI_HEADER[n]}  {n}"
            if side == "L":
                out.append(text(x + 10, yy + 4, label, 10.5, 600))
            else:
                out.append(text(x + w - 10, yy + 4, label, 10.5, 600, INK, "end"))
            out.append(f'<circle cx="{x if side == "L" else x + w}" cy="{yy}" r="3" fill="{INK}"/>')
    notes = ["Power pins", "3V3 out: 1, 17", "5V: 2, 4", "GND: 6, 9, 14, 20, 25, 30, 34, 39"]
    for i, line in enumerate(notes):
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


def _net_name(w: Wire) -> str:
    for end in (w.a, w.b):
        if end[0] == "pi" and end[1].isdigit():
            return PI_HEADER[int(end[1])].split()[0]
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


def _ribbon(points: list[tuple[float, float]], label: str, lx: float, ly: float, anchor: str = "middle") -> str:
    pts = " ".join(f"{x},{y}" for x, y in points)
    c = KIND_COLOUR["video"]
    return "\n".join((
        f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="9" stroke-opacity="0.22" stroke-linejoin="round"/>',
        f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="1.4" stroke-dasharray="5 3"/>',
        text(lx, ly, label, 10, 600, c, anchor),
    ))


def _simple_box(x: float, y: float, w: float, h: float, title: str, sub: str) -> str:
    return "\n".join((
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="#ffffff" stroke="{INK}" stroke-width="1.2"/>',
        text(x + w / 2, y + h / 2 - 2, title, 12, 700, INK, "middle"),
        text(x + w / 2, y + h / 2 + 13, sub, 9.5, 400, MUTED, "middle"),
    ))


def draw_schematic() -> str:
    width, height = 1600, 1000
    pins = _device_pins()
    body = [_pi_box(), *(_device_box(d) for d in LAYOUT)]

    left: list[tuple[Wire, PinPos, PinPos]] = []
    right: list[tuple[Wire, PinPos, PinPos]] = []
    local: list[tuple[Wire, PinPos, PinPos]] = []
    flags: list[tuple[PinPos, str, str]] = []
    for w in WIRES:
        if w.kind == "video":
            continue
        a, b = (w.b, w.a) if w.a[0] == "pi" else (w.a, w.b)   # a = device end, b = Pi end if any
        drawn_power = (w.a, w.b) in DRAWN_POWER or (w.b, w.a) in DRAWN_POWER
        if w.kind in ("power", "ground") and not drawn_power:
            for end, other in ((a, b), (b, a)):
                if end in pins:
                    hint = f"pin {other[1]}" if other[0] == "pi" else ""
                    flags.append((pins[end], _net_name(w), hint))
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

    for group, near, far in ((right, PI_BOX[0] + PI_BOX[2] + 26, 1090), (left, PI_BOX[0] - 26, 500)):
        lanes = _lanes([(pi, dev) for _, pi, dev in group], near, far)
        by_pin: dict[float, list[float]] = {}
        for (w, pi, dev), lane in zip(group, lanes):
            body.append(_route(pi, dev, lane, KIND_COLOUR[w.kind]))
            by_pin.setdefault(pi.y, []).append(lane)
        for y, ls in by_pin.items():   # junction dots where a Pi pin feeds two devices
            if len(ls) > 1:
                far_lane = max(ls, key=lambda v: abs(v - (PI_BOX[0] + PI_BOX[2] / 2)))
                for lane in ls:
                    if lane != far_lane:
                        body.append(f'<circle cx="{lane}" cy="{y}" r="3.4" fill="{KIND_COLOUR["i2s"]}"/>')

    for i, (w, p, q) in enumerate(local):
        lane = (p.x + q.x) / 2 + (i % 2) * 8 - 4
        body.append(_route(p, q, lane, KIND_COLOUR[w.kind]))

    # Wire notes that matter for the build.
    lbo = pins[("boost", "LBO")]
    body.append(text(lbo.x + 12, lbo.y - 5, "1N5817 Schottky, cathode to LBO", 9, 600, KIND_COLOUR["gpio"]))
    ctrl = pins[("led", "CTRL")]
    body.append(text(ctrl.x + 12, ctrl.y - 5, "2N7002 gate, 100 k to GND", 9, 600, KIND_COLOUR["gpio"]))

    # Video: camera CSI on top, HDMI to the micro-OLED driver below.
    px, py, pw, ph = PI_BOX
    body.append(_simple_box(px + 50, 112, pw - 100, 56, "OV5647 camera", "Right endpiece  |  5 MP"))
    body.append(_ribbon([(px + pw / 2, 168), (px + pw / 2, py)], "CSI  |  22-pin 0.5 mm FPC via right hinge",
                        px + pw / 2 - 12, 206, "end"))
    dy = py + ph + 90
    body.append(_simple_box(px + 30, dy, pw - 60, 64, "Micro-OLED driver", "Brow bay  |  5 V + GND from PowerBoost"))
    body.append(_ribbon([(px + pw / 2, py + ph), (px + pw / 2, dy)], "mini-HDMI  |  1920x1080 side-by-side",
                        px + pw / 2 + 12, py + ph + 48, "start"))
    body.append(_simple_box(px - 250, dy + 4, 150, 56, "Micro-OLED L", "0.49 in 1080p"))
    body.append(_simple_box(px + pw + 100, dy + 4, 150, 56, "Micro-OLED R", "0.49 in 1080p"))
    body.append(_ribbon([(px + 30, dy + 32), (px - 100, dy + 32)], "MIPI", px - 35, dy + 24))
    body.append(_ribbon([(px + pw - 30, dy + 32), (px + pw + 100, dy + 32)], "MIPI", px + pw + 35, dy + 24))

    # Legend.
    lx, ly = 44, 560
    body.append(text(lx, ly, "LEGEND", 10, 700, MUTED, extra='letter-spacing="1"'))
    entries = [("power", "Power (5 V / 3V3)"), ("ground", "Ground"), ("i2c", "I2C (IMU)"),
               ("i2s", "I2S audio (mic + amp)"), ("gpio", "GPIO (button, touch, LED, LBO)"),
               ("audio", "Speaker"), ("video", "FPC / HDMI ribbon")]
    for i, (kind, label) in enumerate(entries):
        y = ly + 22 + i * 22
        dash = ' stroke-dasharray="5 3"' if kind == "video" else ""
        body.append(f'<line x1="{lx}" y1="{y - 4}" x2="{lx + 34}" y2="{y - 4}" stroke="{KIND_COLOUR[kind]}" '
                    f'stroke-width="2.4"{dash}/>')
        body.append(text(lx + 44, y, label, 11))
    body.append(text(lx, ly + 200, "Flags: a red arrow is a power net, the bars are ground;", 10, 400, MUTED))
    body.append(text(lx, ly + 216, "'pin N' names the Pi header pin that net is wired to.", 10, 400, MUTED))
    body.append(text(lx, ly + 240, "Dots on a lane = one Pi pin feeding two devices (shared I2S clocks).", 10, 400,
                     ACCENT))

    return sheet(width, height, "HOLOGRAM VR CAM - WIRING SCHEMATIC",
                 "Every connection, generated from cad/spec.py (pin table: docs/wiring.md)", "4 / 4",
                 "\n".join(body))
