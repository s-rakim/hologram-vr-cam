"""Binary STL files of the printed parts, for FDM / resin / SLS printing.

    python -m cad.stl_export          # writes cad/out/<product>/stl/*.stl

Curved parts (the helmet shell, visor, mirrors) come from their smooth
meshes; the rest are triangulated from the IFC model, which needs
ifcopenshell (pip install ifcopenshell). Parts are exported in assembly
position, in millimetres; lay them flat in your slicer. Openings that need
a drill (buttons, camera, USB) are listed in each product's build guide.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from .generate import ROOT
from .products import PRODUCTS


def write_binary_stl(path: Path, name: str, verts: list[float], faces: list[int], unit: float = 1000.0) -> int:
    """``verts`` flat xyz list (metres by default, as ifcopenshell gives them); ``faces`` flat index list."""
    tris = [faces[i:i + 3] for i in range(0, len(faces), 3)]
    out = bytearray(name.encode("ascii")[:80].ljust(80, b" "))
    out += struct.pack("<I", len(tris))
    for a, b, c in tris:
        p = [tuple(verts[3 * i + k] * unit for k in range(3)) for i in (a, b, c)]
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


def write_mesh(path: Path, name: str, mesh) -> int:
    verts, tris = mesh
    return write_binary_stl(path, name, [c for v in verts for c in v], [i for t in tris for i in t], unit=1.0)


def main() -> int:
    try:
        import ifcopenshell
        import ifcopenshell.geom
    except ImportError:
        ifcopenshell = None
    for product in PRODUCTS:
        out_dir = ROOT / f"cad/out/{product.key}/stl"
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("*.stl"):
            if old.stem not in product.printed:
                old.unlink()
        for part_id, make in product.meshes.items():
            if part_id in product.printed:
                n = write_mesh(out_dir / f"{part_id}.stl", f"{product.name} {part_id}", make())
                print(f"{product.key}/{part_id}.stl: {n} triangles (smooth)")
        rest = [p for p in product.printed if p not in product.meshes]
        if not rest:
            continue
        if ifcopenshell is None:
            print("the flat parts need ifcopenshell: pip install ifcopenshell", file=sys.stderr)
            return 1
        settings = ifcopenshell.geom.settings()
        model = ifcopenshell.open(str(ROOT / f"cad/out/{product.key}/hologram_{product.key}.ifc"))
        for element in model.by_type("IfcElement"):
            if element.Tag not in rest:
                continue
            geom = ifcopenshell.geom.create_shape(settings, element).geometry
            n = write_binary_stl(out_dir / f"{element.Tag}.stl", f"{product.name} {element.Tag}",
                                 list(geom.verts), list(geom.faces))
            print(f"{product.key}/{element.Tag}.stl: {n} triangles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
