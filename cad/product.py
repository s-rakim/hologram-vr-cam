"""Building blocks shared by every product model (camera glasses, VR headset).

A :class:`Product` bundles everything the exporters need: the parts (as
extrusions), the bill of materials, the wiring, and the per-product drawing
annotations. ``python -m cad.generate`` turns each product into its IFC
model, Revit JSON, drawings and docs.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .geometry import Loop, Solid, Vec3, bbox_union


@dataclass(frozen=True)
class Material:
    name: str
    rgb: tuple[int, int, int]
    transparency: int = 0          # 0..100 (Revit convention)
    shell: bool = False            # drawn see-through in the x-ray view


MATERIALS: dict[str, Material] = {
    "frame": Material("HVR Frame - PA12 nylon matte black", (40, 40, 46), shell=True),
    "lens": Material("HVR Lens - polycarbonate smoke", (96, 118, 140), 65, shell=True),
    "clear_lens": Material("HVR Lens - optical acrylic", (170, 205, 225), 55),
    "optic_housing": Material("HVR Optics housing - PC-ABS", (88, 92, 104), 30, shell=True),
    "glass": Material("HVR Optics - glass", (150, 205, 235), 45),
    "display": Material("HVR Display panel", (24, 26, 34)),
    "pcb_green": Material("HVR PCB - FR4 green", (34, 120, 64)),
    "pcb_blue": Material("HVR PCB - FR4 blue", (38, 86, 168)),
    "pcb_purple": Material("HVR PCB - FR4 purple", (106, 64, 150)),
    "chip": Material("HVR IC package", (30, 30, 30)),
    "battery": Material("HVR Li-ion cell", (214, 178, 64)),
    "metal": Material("HVR Stainless steel", (176, 178, 184)),
    "aluminium": Material("HVR Aluminium heat spreader", (190, 194, 200)),
    "silicone": Material("HVR Silicone", (226, 226, 222), 20),
    "foam": Material("HVR Face foam - PU", (58, 60, 66), shell=True),
    "strap": Material("HVR Strap - TPU", (52, 54, 60), shell=True),
    "led": Material("HVR Privacy LED", (250, 250, 255), 10),
    "camera": Material("HVR Camera module", (22, 22, 24)),
    "copper": Material("HVR Copper tape", (196, 120, 60)),
    "visor": Material("HVR Shell - ABS", (16, 16, 18), shell=True),
    "magnet": Material("HVR Neodymium magnet", (150, 150, 158)),
    "livery": Material("HVR Helmet shell - LW-PLA, painted red", (200, 34, 44), shell=True),
    "visor_smoke": Material("HVR Visor - dark smoke", (34, 40, 52), 35, shell=True),
    "mirror": Material("HVR Visor mirror - first-surface aluminium", (206, 212, 222), 20),
}


@dataclass(frozen=True)
class Part:
    id: str
    name: str
    group: str
    material: str
    solids: tuple[Solid, ...]
    explode: Vec3 = (0.0, 0.0, 0.0)
    ifc_class: str = "IfcBuildingElementProxy"
    ifc_type: str = "NOTDEFINED"
    bom: str | None = None        # BOM line this part is bought/made as

    def mirrored(self, new_id: str, new_name: str) -> Part:
        ex, ey, ez = self.explode
        return Part(new_id, new_name, self.group, self.material,
                    tuple(s.mirrored_x() for s in self.solids), (-ex, ey, ez),
                    self.ifc_class, self.ifc_type, self.bom)


@dataclass(frozen=True)
class BomLine:
    key: str
    qty: str
    item: str
    spec: str
    notes: str = ""


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    location: str
    pins: tuple[str, ...]


@dataclass(frozen=True)
class Wire:
    kind: str                    # power | ground | i2c | i2s | gpio | video | audio
    a: tuple[str, str]           # (device id or "pi", pin name or header number)
    b: tuple[str, str]
    note: str = ""


def pi_pin(pin: int) -> tuple[str, str]:
    return ("pi", str(pin))


# The Raspberry Pi 40-pin header is the same on the Zero 2 W and the Pi 5.
PI_HEADER: dict[int, str] = {
    1: "3V3", 2: "5V", 3: "GPIO2 SDA", 4: "5V", 5: "GPIO3 SCL", 6: "GND", 7: "GPIO4",
    8: "GPIO14 TXD", 9: "GND", 10: "GPIO15 RXD", 11: "GPIO17", 12: "GPIO18 PCM_CLK", 13: "GPIO27",
    14: "GND", 15: "GPIO22", 16: "GPIO23", 17: "3V3", 18: "GPIO24", 19: "GPIO10 MOSI", 20: "GND",
    21: "GPIO9 MISO", 22: "GPIO25", 23: "GPIO11 SCLK", 24: "GPIO8 CE0", 25: "GND", 26: "GPIO7 CE1",
    29: "GPIO5", 30: "GND", 31: "GPIO6", 32: "GPIO12", 33: "GPIO13", 34: "GND",
    35: "GPIO19 PCM_FS", 36: "GPIO16", 37: "GPIO26", 38: "GPIO20 PCM_DIN", 39: "GND", 40: "GPIO21 PCM_DOUT",
}


@dataclass(frozen=True)
class Dim:
    """A dimension line on the orthographic sheet, between two world points."""

    view: str                    # front | top | side
    a: Vec3
    b: Vec3
    offset: float                # px; +ve below / right, -ve above / left
    label: str
    vertical: bool = False


@dataclass(frozen=True)
class Ribbon:
    """A ribbon/FPC link on the schematic, with an optional box at its far end."""

    points: tuple[tuple[float, float], ...]
    label: str
    label_xy: tuple[float, float]
    anchor: str = "middle"
    box: tuple[float, float, float, float, str, str] | None = None   # x, y, w, h, title, subtitle


@dataclass(frozen=True)
class SchematicSpec:
    layout: dict[str, tuple[float, float, float, dict[str, str]]]   # device -> (x, y, width, pin sides)
    compute_box: tuple[float, float, float, float]
    left_pins: tuple[int | str, ...]       # header pin numbers, or named pads such as "BAT+"
    right_pins: tuple[int | str, ...]
    drawn_power: frozenset[tuple[tuple[str, str], tuple[str, str]]] = frozenset()
    ribbons: tuple[Ribbon, ...] = ()
    pin_notes: tuple[tuple[str, str, str], ...] = ()      # (device, pin, note) printed next to the pin
    left_lane_far: float = 500.0
    right_lane_far: float = 1090.0
    legend_xy: tuple[float, float] = (44.0, 560.0)
    power_notes: tuple[str, ...] = ("Power pins", "3V3 out: 1, 17", "5V: 2, 4", "GND: 6, 9, 14, 20, 25, 30, 34, 39")
    size: tuple[int, int] = (1600, 1000)


@dataclass(frozen=True)
class Envelope:
    width: float
    depth: float
    height: float


@dataclass(frozen=True)
class Product:
    key: str                      # short id used for folders: "cam", "vr"
    name: str                     # "Hologram Cam"
    tagline: str
    compute: str                  # name of the board the wiring header belongs to
    compute_location: str
    parts: tuple[Part, ...]
    bom: tuple[BomLine, ...]
    devices: dict[str, Device]
    wires: tuple[Wire, ...]
    schematic: SchematicSpec
    callouts: tuple[tuple[str, str, str], ...]           # (part id, title, detail) on the assembly sheet
    dims: tuple[Dim, ...] = ()
    notes: tuple[str, ...] = ()                          # orthographic sheet notes
    accessories: tuple[str, ...] = ()                    # part ids left out of the assembly/ortho sheets
    iso: Vec3 = (0.95, 1.0, 0.72)                        # direction towards the viewer for 3D sheets
    exploded_subtitle: str = ""
    printed: tuple[str, ...] = ()                        # part ids exported as STL
    header: dict[int, str] = field(default_factory=lambda: dict(PI_HEADER))
    # part id -> function returning a smooth (vertices mm, triangles) mesh for STL export,
    # used instead of tessellating the IFC extrusions (e.g. the curved helmet shell)
    meshes: dict[str, Callable[[], tuple[list[Vec3], list[tuple[int, int, int]]]]] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return self.name.upper()

    @property
    def materials(self) -> dict[str, Material]:
        used = {p.material for p in self.parts}
        return {k: m for k, m in MATERIALS.items() if k in used}

    def part(self, part_id: str) -> Part:
        return next(p for p in self.parts if p.id == part_id)

    def worn_parts(self) -> tuple[Part, ...]:
        return tuple(p for p in self.parts if p.id not in self.accessories)

    def envelope(self) -> Envelope:
        lo, hi = bbox_union([s.bbox() for p in self.worn_parts() for s in p.solids])
        return Envelope(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])

    def gpio_of(self, device: str, pin: str) -> int:
        """BCM GPIO number wired to ``device.pin`` (used to check software config)."""
        for w in self.wires:
            for here, there in ((w.a, w.b), (w.b, w.a)):
                if here == (device, pin) and there[0] == "pi" and there[1].isdigit():
                    label = self.header[int(there[1])]
                    if label.startswith("GPIO"):
                        return int(label.split()[0][4:])
        raise KeyError(f"{device}.{pin} is not wired to a GPIO")


def xz(outer: Loop, y: tuple[float, float], holes: tuple[Loop, ...] = ()) -> Solid:
    """Profile in the front (XZ) plane, extruded across a Y range."""
    return Solid("XZ", outer, y, holes)


def yz(outer: Loop, x: tuple[float, float], holes: tuple[Loop, ...] = ()) -> Solid:
    """Profile in the side (YZ) plane, extruded across an X range."""
    return Solid("YZ", outer, x, holes)


def xy(outer: Loop, z: tuple[float, float], holes: tuple[Loop, ...] = ()) -> Solid:
    """Profile in the top (XY) plane, extruded across a Z range."""
    return Solid("XY", outer, z, holes)
