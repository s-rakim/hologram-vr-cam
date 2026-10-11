"""Both product models, their drawings and Revit/IFC exports stay valid and consistent."""
import ast
import json
import math
import struct
from pathlib import Path

import pytest

from cad import generate
from cad.geometry import MIN_EDGE_MM, Solid, rect, signed_area
from cad.products import BY_KEY, PRODUCTS

ROOT = Path(__file__).resolve().parent.parent
products = pytest.mark.parametrize("product", PRODUCTS, ids=[p.key for p in PRODUCTS])


@products
def test_every_part_is_valid_revit_geometry(product):
    ids = set()
    for part in product.parts:
        assert part.id not in ids
        ids.add(part.id)
        for solid in part.solids:
            assert solid.depth > 0
            assert signed_area(solid.outer) > 0
            for loop in solid.loops():
                for i, p in enumerate(loop):
                    q = loop[(i + 1) % len(loop)]
                    # Revit's ShortCurveTolerance is ~0.8 mm
                    assert math.dist(p, q) >= 0.8 * MIN_EDGE_MM, f"{part.id}: edge {p}->{q} too short"


@products
def test_holes_lie_inside_their_outline(product):
    for part in product.parts:
        for solid in part.solids:
            xs = [x for x, _ in solid.outer]
            ys = [y for _, y in solid.outer]
            for hole in solid.holes:
                for x, y in hole:
                    assert min(xs) < x < max(xs) and min(ys) < y < max(ys), part.id


@products
def test_bom_wiring_and_callouts_reference_real_things(product):
    keys = {line.key for line in product.bom}
    part_ids = {p.id for p in product.parts}
    for part in product.parts:
        assert part.bom is None or part.bom in keys, part.id
    for wire in product.wires:
        for dev, pin in (wire.a, wire.b):
            if dev == "pi":
                assert not pin.isdigit() or int(pin) in product.header
            else:
                assert pin in product.devices[dev].pins, f"{dev}.{pin}"
    for pid, *_ in product.callouts:
        assert pid in part_ids
    assert set(product.accessories) <= part_ids and set(product.printed) <= part_ids
    assert set(product.schematic.layout) <= set(product.devices)


@products
def test_schematic_shows_every_header_pin_it_wires(product):
    used = {int(end[1]) for w in product.wires for end in (w.a, w.b)
            if end[0] == "pi" and end[1].isdigit() and w.kind not in ("power", "ground")}
    shown = set(product.schematic.left_pins) | set(product.schematic.right_pins)
    assert used <= shown


def test_cam_glasses_size_is_wearable():
    env = BY_KEY["cam"].envelope()
    assert 140 <= env.width <= 160 and 150 <= env.depth <= 170 and env.height < 50


def test_mirror_and_translate():
    s = Solid("XZ", rect(10, 0, 4, 2), (0, 3))
    assert s.mirrored_x().bbox()[0][0] == pytest.approx(-12)
    t = Solid("YZ", rect(0, 0, 4, 2), (1, 2)).translated((5, 1, 0))
    assert t.span == (6, 7)
    assert t.bbox()[0][1] == pytest.approx(-1)


def test_generated_files_are_up_to_date():
    assert generate.main(["--check"]) == 0, "run: python -m cad.generate"


@products
def test_revit_model_json_loops_are_planar(product):
    model = json.loads((ROOT / f"cad/revit/hologram_{product.key}_model.json").read_text())
    assert len(model["parts"]) == len(product.parts)
    for part in model["parts"]:
        for solid in part["solids"]:
            n = solid["normal"]
            origin = solid["loops"][0][0]
            for loop in solid["loops"]:
                assert len(loop) >= 3
                for p in loop:   # every point on the sketch plane
                    assert abs(sum((p[i] - origin[i]) * n[i] for i in range(3))) < 1e-3


def test_revit_script_runs_on_ironpython_2_7():
    src = (ROOT / "cad/revit/build_hologram_family.py").read_text()
    tree = ast.parse(src)
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)], "no f-strings in IronPython 2.7"
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.AnnAssign)]
    assert "NewExtrusion" in src and "hologram_*_model.json" in src


@products
def test_ifc_is_valid_ifc4(product):
    pytest.importorskip("ifcopenshell")
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.validate

    f = ifcopenshell.open(str(ROOT / f"cad/out/{product.key}/hologram_{product.key}.ifc"))
    assert f.schema == "IFC4"
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, logger, express_rules=True)
    assert logger.statements == []

    settings = ifcopenshell.geom.settings()
    elements = f.by_type("IfcElement")
    assert len(elements) == len(product.parts)
    for e in elements:   # every part tessellates; sizes come back in metres
        verts = ifcopenshell.geom.create_shape(settings, e).geometry.verts
        assert verts, e.Tag
    lo, hi = zip(*[s.bbox() for s in product.parts[0].solids])
    first = next(e for e in elements if e.Tag == product.parts[0].id)
    xs = ifcopenshell.geom.create_shape(settings, first).geometry.verts[0::3]
    width = max(h[0] for h in hi) - min(lo_[0] for lo_ in lo)
    assert (max(xs) - min(xs)) * 1000 == pytest.approx(width, abs=0.01)


@products
def test_printable_stls_are_well_formed(product):
    for name in product.printed:
        data = (ROOT / f"cad/out/{product.key}/stl/{name}.stl").read_bytes()
        (count,) = struct.unpack("<I", data[80:84])
        assert count > 0 and len(data) == 84 + 50 * count, name
