"""The CAD model, drawings and Revit/IFC exports stay valid and consistent."""
import ast
import json
import math
from pathlib import Path

import pytest

from cad import generate
from cad.geometry import MIN_EDGE_MM, Solid, rect, signed_area
from cad.spec import BOM, DEVICES, PARTS, PI_HEADER, WIRES, gpio_of, overall_envelope
from hologram.config import PinConfig

ROOT = Path(__file__).resolve().parent.parent


def test_every_part_is_valid_revit_geometry():
    ids = set()
    for part in PARTS:
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


def test_holes_lie_inside_their_outline():
    for part in PARTS:
        for solid in part.solids:
            xs = [x for x, _ in solid.outer]
            ys = [y for _, y in solid.outer]
            for hole in solid.holes:
                for x, y in hole:
                    assert min(xs) < x < max(xs) and min(ys) < y < max(ys), part.id


def test_overall_size_is_wearable():
    env = overall_envelope()
    assert 140 <= env.width <= 160
    assert 150 <= env.depth <= 170
    assert env.height < 50


def test_mirror_and_translate():
    s = Solid("XZ", rect(10, 0, 4, 2), (0, 3))
    m = s.mirrored_x()
    assert m.bbox()[0][0] == pytest.approx(-12)
    t = Solid("YZ", rect(0, 0, 4, 2), (1, 2)).translated((5, 1, 0))
    assert t.span == (6, 7)
    assert t.bbox()[0][1] == pytest.approx(-1)


def test_bom_and_wiring_reference_real_things():
    keys = {line.key for line in BOM}
    for part in PARTS:
        assert part.bom is None or part.bom in keys, part.id
    for wire in WIRES:
        for dev, pin in (wire.a, wire.b):
            if dev == "pi":
                assert pin in ("CSI", "mini-HDMI") or int(pin) in PI_HEADER
            else:
                assert pin in DEVICES[dev].pins, f"{dev}.{pin}"


def test_software_pins_match_the_wiring():
    pins = PinConfig()
    assert gpio_of("button", "A") == pins.capture_button
    assert gpio_of("touch", "OUT") == pins.touch
    assert gpio_of("led", "CTRL") == pins.privacy_led
    assert gpio_of("boost", "LBO") == pins.low_battery
    assert gpio_of("imu", "INT") == pins.imu_interrupt


def test_generated_files_are_up_to_date():
    assert generate.main(["--check"]) == 0, "run: python -m cad.generate"


def test_revit_model_json_loops_are_planar_and_closed():
    model = json.loads((ROOT / "cad/revit/hologram_glasses_model.json").read_text())
    assert len(model["parts"]) == len(PARTS)
    for part in model["parts"]:
        for solid in part["solids"]:
            n = solid["normal"]
            origin = solid["loops"][0][0]
            for loop in solid["loops"]:
                assert len(loop) >= 3
                for p in loop:   # every point on the sketch plane
                    assert abs(sum((p[i] - origin[i]) * n[i] for i in range(3))) < 1e-3


def test_revit_script_runs_on_ironpython_2_7():
    src = (ROOT / "cad/revit/build_hologram_glasses.py").read_text()
    tree = ast.parse(src)
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)], "no f-strings in IronPython 2.7"
    assert not [n for n in ast.walk(tree) if isinstance(n, (ast.AnnAssign,))]
    assert "NewExtrusion" in src and "Generic Model" in src


def test_ifc_is_valid_ifc4():
    pytest.importorskip("ifcopenshell")
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.validate

    f = ifcopenshell.open(str(ROOT / "cad/out/hologram_glasses.ifc"))
    assert f.schema == "IFC4"
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, logger, express_rules=True)
    assert logger.statements == []

    settings = ifcopenshell.geom.settings()
    elements = f.by_type("IfcElement")
    assert len(elements) == len(PARTS)
    frame = next(e for e in elements if e.Tag == "frame_front")
    verts = ifcopenshell.geom.create_shape(settings, frame).geometry.verts
    xs = verts[0::3]
    assert (max(xs) - min(xs)) * 1000 == pytest.approx(150, abs=0.01)   # geometry comes back in metres


def test_printable_stls_are_well_formed():
    import struct

    from cad.stl_export import PRINTED

    for name in PRINTED:
        data = (ROOT / "cad/out/stl" / f"{name}.stl").read_bytes()
        (count,) = struct.unpack("<I", data[80:84])
        assert count > 0 and len(data) == 84 + 50 * count, name
