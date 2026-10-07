"""Minimal IFC4 (STEP physical file) writer for the glasses model.

Revit opens IFC natively (File > Open > IFC), so this is the most direct
way to get the model into Revit without Revit itself being installed here.
Each part becomes one IFC element whose body is a set of
``IfcExtrudedAreaSolid``s, coloured and tagged with a material. Pure Python,
no ifcopenshell required (it is only used by the tests, to validate).
"""
from __future__ import annotations

import datetime as _dt
import uuid

from .geometry import Solid, Vec3
from .spec import MATERIALS, PARTS, Part

_GUID_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"
_NAMESPACE = uuid.UUID("6f1d3c0e-5a8b-4f7e-9a51-0b6c1e2d7f43")


def ifc_guid(key: str) -> str:
    """Deterministic 22-character IFC GlobalId for ``key``."""
    raw = uuid.uuid5(_NAMESPACE, key).bytes

    def b64(value: int, width: int) -> str:
        return "".join(_GUID_CHARS[(value >> (6 * i)) & 63] for i in reversed(range(width)))

    return b64(raw[0], 2) + "".join(
        b64((raw[i] << 16) | (raw[i + 1] << 8) | raw[i + 2], 4) for i in range(1, 16, 3))


def _real(v: float) -> str:
    text = f"{v:.6f}".rstrip("0")
    if text in ("-0.", "-0"):
        text = "0."
    return text


def _str(s: str | None) -> str:
    if s is None:
        return "$"
    s.encode("ascii")  # STEP strings must be plain ASCII here
    return "'" + s.replace("\\", "\\\\").replace("'", "''") + "'"


class _Step:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self._cache: dict[str, int] = {}

    def add(self, entity: str, *args: str, reuse: bool = False) -> int:
        body = f"{entity}({','.join(args)})"
        if reuse and body in self._cache:
            return self._cache[body]
        n = len(self.lines) + 1
        self.lines.append(f"#{n}={body};")
        if reuse:
            self._cache[body] = n
        return n

    def point(self, *coords: float) -> int:
        return self.add("IFCCARTESIANPOINT", "(" + ",".join(_real(c) for c in coords) + ")", reuse=True)

    def direction(self, *coords: float) -> int:
        return self.add("IFCDIRECTION", "(" + ",".join(_real(c) for c in coords) + ")", reuse=True)

    def placement3d(self, origin: Vec3, axis: Vec3, ref: Vec3) -> int:
        return self.add("IFCAXIS2PLACEMENT3D", f"#{self.point(*origin)}",
                        f"#{self.direction(*axis)}", f"#{self.direction(*ref)}", reuse=True)


def _ref(ids: list[int]) -> str:
    return "(" + ",".join(f"#{i}" for i in ids) + ")"


def _solid(step: _Step, solid: Solid) -> int:
    """IfcExtrudedAreaSolid whose local XY is the sketch plane (u, v)."""
    from .geometry import PLANES

    u, _, _ = PLANES[solid.plane]
    origin = solid.point3((0.0, 0.0), solid.start)
    position = step.placement3d(origin, solid.normal, u)

    def polyline(loop) -> int:
        pts = [step.point(x, y) for x, y in loop]
        return step.add("IFCPOLYLINE", _ref(pts + pts[:1]))

    outer = polyline(solid.outer)
    if solid.holes:
        inner = [polyline(h) for h in solid.holes]
        profile = step.add("IFCARBITRARYPROFILEDEFWITHVOIDS", ".AREA.", "$", f"#{outer}", _ref(inner))
    else:
        profile = step.add("IFCARBITRARYCLOSEDPROFILEDEF", ".AREA.", "$", f"#{outer}")
    return step.add("IFCEXTRUDEDAREASOLID", f"#{profile}", f"#{position}",
                    f"#{step.direction(0.0, 0.0, 1.0)}", _real(solid.depth))


def build_ifc(parts: tuple[Part, ...] = PARTS, author: str = "Malcolm Opondo",
              timestamp: _dt.datetime | None = None) -> str:
    stamp = (timestamp or _dt.datetime(2026, 1, 1)).strftime("%Y-%m-%dT%H:%M:%S")
    s = _Step()
    origin = s.placement3d((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))

    units = [
        s.add("IFCSIUNIT", "*", ".LENGTHUNIT.", ".MILLI.", ".METRE."),
        s.add("IFCSIUNIT", "*", ".AREAUNIT.", "$", ".SQUARE_METRE."),
        s.add("IFCSIUNIT", "*", ".VOLUMEUNIT.", "$", ".CUBIC_METRE."),
        s.add("IFCSIUNIT", "*", ".PLANEANGLEUNIT.", "$", ".RADIAN."),
    ]
    unit_assignment = s.add("IFCUNITASSIGNMENT", _ref(units))
    context = s.add("IFCGEOMETRICREPRESENTATIONCONTEXT", "$", "'Model'", "3", "1.E-05", f"#{origin}", "$")
    body_ctx = s.add("IFCGEOMETRICREPRESENTATIONSUBCONTEXT", "'Body'", "'Model'", "*", "*", "*", "*",
                     f"#{context}", "$", ".MODEL_VIEW.", "$")

    project = s.add("IFCPROJECT", _str(ifc_guid("project")), "$", _str("Hologram VR Cam glasses"),
                    _str("VR display glasses with a POV video camera"), "$", "$", "$",
                    _ref([context]), f"#{unit_assignment}")
    site_pl = s.add("IFCLOCALPLACEMENT", "$", f"#{origin}")
    site = s.add("IFCSITE", _str(ifc_guid("site")), "$", _str("Workshop"), "$", "$", f"#{site_pl}",
                 "$", "$", ".ELEMENT.", "$", "$", "$", "$", "$")
    bldg_pl = s.add("IFCLOCALPLACEMENT", f"#{site_pl}", f"#{origin}")
    building = s.add("IFCBUILDING", _str(ifc_guid("building")), "$", _str("Hologram VR Cam lab"), "$", "$",
                     f"#{bldg_pl}", "$", "$", ".ELEMENT.", "$", "$", "$")
    storey_pl = s.add("IFCLOCALPLACEMENT", f"#{bldg_pl}", f"#{origin}")
    storey = s.add("IFCBUILDINGSTOREY", _str(ifc_guid("storey")), "$", _str("Bench"), "$", "$",
                   f"#{storey_pl}", "$", "$", ".ELEMENT.", "0.")
    for i, (whole, piece) in enumerate(((project, site), (site, building), (building, storey))):
        s.add("IFCRELAGGREGATES", _str(ifc_guid(f"aggregate-{i}")), "$", "$", "$", f"#{whole}", _ref([piece]))

    styles: dict[str, int] = {}
    materials: dict[str, int] = {}
    for key, mat in MATERIALS.items():
        r, g, b = (c / 255.0 for c in mat.rgb)
        colour = s.add("IFCCOLOURRGB", "$", _real(r), _real(g), _real(b))
        shading = s.add("IFCSURFACESTYLESHADING", f"#{colour}", _real(mat.transparency / 100.0))
        styles[key] = s.add("IFCSURFACESTYLE", _str(mat.name), ".BOTH.", _ref([shading]))
        materials[key] = s.add("IFCMATERIAL", _str(mat.name), "$", "$")

    elements: list[int] = []
    by_material: dict[str, list[int]] = {}
    for part in parts:
        items = [_solid(s, solid) for solid in part.solids]
        for item in items:
            s.add("IFCSTYLEDITEM", f"#{item}", _ref([styles[part.material]]), "$")
        rep = s.add("IFCSHAPEREPRESENTATION", f"#{body_ctx}", "'Body'", "'SweptSolid'", _ref(items))
        shape = s.add("IFCPRODUCTDEFINITIONSHAPE", "$", "$", _ref([rep]))
        placement = s.add("IFCLOCALPLACEMENT", f"#{storey_pl}", f"#{origin}")
        element = s.add(part.ifc_class.upper(), _str(ifc_guid(part.id)), "$", _str(part.name),
                        _str(f"{part.group} / {part.id}"), _str(part.name), f"#{placement}",
                        f"#{shape}", _str(part.id), f".{part.ifc_type}.")
        elements.append(element)
        by_material.setdefault(part.material, []).append(element)

    s.add("IFCRELCONTAINEDINSPATIALSTRUCTURE", _str(ifc_guid("contained")), "$", "$", "$",
          _ref(elements), f"#{storey}")
    for key, objs in by_material.items():
        s.add("IFCRELASSOCIATESMATERIAL", _str(ifc_guid(f"material-{key}")), "$", "$", "$",
              _ref(objs), f"#{materials[key]}")

    header = "\n".join((
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('ViewDefinition [ReferenceView_V1.2]'),'2;1');",
        f"FILE_NAME('hologram_glasses.ifc','{stamp}',({_str(author)}),('hologram-vr-cam'),"
        "'hologram-vr-cam cad.ifc_writer','hologram-vr-cam','');",
        "FILE_SCHEMA(('IFC4'));",
        "ENDSEC;",
        "DATA;",
    ))
    return header + "\n" + "\n".join(s.lines) + "\nENDSEC;\nEND-ISO-10303-21;\n"
