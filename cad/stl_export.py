"""Binary STL files of the printed parts, for SLS / FDM printing.

Needs ifcopenshell (pip install ifcopenshell) to triangulate the IFC model:

    python -m cad.stl_export          # writes cad/out/stl/*.stl

Parts are exported in assembly position, in millimetres; rotate them flat in
your slicer. Openings that need a cutting tool (button, USB, mic port) are
listed in docs/assembly.md rather than modelled.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from .generate import ROOT

PRINTED = (
    "frame_front", "brow_bay", "visor",
    "temple_pod_right", "temple_pod_left", "pod_lid_right", "pod_lid_left",
    "temple_arm_right", "temple_arm_left",
    "optics_housing_right", "optics_housing_left",
)


def write_binary_stl(path: Path, name: str, verts: list[float], faces: list[int]) -> int:
    tris = [faces[i:i + 3] for i in range(0, len(faces), 3)]
    out = bytearray(name.encode("ascii")[:80].ljust(80, b" "))
    out += struct.pack("<I", len(tris))
    for a, b, c in tris:
        p = [tuple(verts[3 * i + k] * 1000.0 for k in range(3)) for i in (a, b, c)]   # m -> mm
        u = [p[1][k] - p[0][k] for k in range(3)]
        v = [p[2][k] - p[0][k] for k in range(3)]
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        length = sum(c * c for c in n) ** 0.5 or 1.0
        out += struct.pack("<3f", *(c / length for c in n))
        for q in p:
            out += struct.pack("<3f", *q)
        out += b"\x00\x00"
    path.write_bytes(bytes(out))
    return len(tris)


def main() -> int:
    try:
        import ifcopenshell
        import ifcopenshell.geom
    except ImportError:
        print("STL export needs ifcopenshell: pip install ifcopenshell", file=sys.stderr)
        return 1
    model = ifcopenshell.open(str(ROOT / "cad/out/hologram_glasses.ifc"))
    settings = ifcopenshell.geom.settings()
    out_dir = ROOT / "cad/out/stl"
    out_dir.mkdir(parents=True, exist_ok=True)
    for element in model.by_type("IfcElement"):
        if element.Tag not in PRINTED:
            continue
        geom = ifcopenshell.geom.create_shape(settings, element).geometry
        n = write_binary_stl(out_dir / f"{element.Tag}.stl", f"Hologram VR Cam {element.Tag}",
                             list(geom.verts), list(geom.faces))
        print(f"{element.Tag}.stl: {n} triangles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
