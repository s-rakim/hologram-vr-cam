# -*- coding: utf-8 -*-
"""Build a Hologram product (camera glasses or VR headset) as a native Revit family.

How to run (Revit 2019 or newer):
  1. File > New > Family > "Metric Generic Model.rft".
  2. Run this script with pyRevit (drop this folder into a pyRevit extension,
     or use "Run script") or with RevitPythonShell.
  3. Pick the product when asked. The script reads its
     ``hologram_<cam|vr>_model.json`` from this folder (or asks you for the
     file) and creates every part as solid extrusions, one subcategory and
     material per finish, and one model group per part.
  4. Save the family (e.g. ``HologramCam.rfa``) and load it into any project.

The JSON files are generated from cad/products/*.py by
``python -m cad.generate``; edit a model, regenerate, and rerun this script.

Works under IronPython 2.7 (pyRevit default, RevitPythonShell) and CPython 3,
so no f-strings or type hints here.
"""
import glob
import json
import os

import clr

clr.AddReference("RevitAPI")
clr.AddReference("System")
from Autodesk.Revit.DB import (  # noqa: E402
    Color,
    CurveArrArray,
    CurveArray,
    ElementId,
    FilteredElementCollector,
    Line,
    Material,
    Plane,
    SketchPlane,
    Transaction,
    XYZ,
)
from System.Collections.Generic import List  # noqa: E402

__title__ = "Build Hologram\nFamily"
MODEL_PATTERN = "hologram_*_model.json"
MM_PER_FOOT = 304.8  # Revit's internal length unit is the decimal foot


def ft(mm):
    return mm / MM_PER_FOOT


def xyz(p):
    return XYZ(ft(p[0]), ft(p[1]), ft(p[2]))


def _script_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:  # RevitPythonShell runs scripts without __file__
        return os.getcwd()


def _choose(paths):
    """Ask which product to build when more than one model file is present."""
    clr.AddReference("RevitAPIUI")
    from Autodesk.Revit.UI import TaskDialog, TaskDialogCommandLinkId, TaskDialogResult

    links = [TaskDialogCommandLinkId.CommandLink1, TaskDialogCommandLinkId.CommandLink2,
             TaskDialogCommandLinkId.CommandLink3, TaskDialogCommandLinkId.CommandLink4]
    results = [TaskDialogResult.CommandLink1, TaskDialogResult.CommandLink2,
               TaskDialogResult.CommandLink3, TaskDialogResult.CommandLink4]
    dialog = TaskDialog("Hologram")
    dialog.MainInstruction = "Which product should this family contain?"
    names = []
    for i, path in enumerate(paths[:4]):
        with open(path) as fh:
            names.append(json.load(fh)["name"])
        dialog.AddCommandLink(links[i], names[i], os.path.basename(path))
    answer = dialog.Show()
    for i in range(len(names)):
        if answer == results[i]:
            return paths[i]
    raise Exception("Cancelled")


def locate_model():
    paths = sorted(glob.glob(os.path.join(_script_dir(), MODEL_PATTERN)))
    if len(paths) == 1:
        return paths[0]
    if paths:
        return _choose(paths)

    clr.AddReference("System.Windows.Forms")
    from System.Windows.Forms import DialogResult, OpenFileDialog

    dialog = OpenFileDialog()
    dialog.Title = "Select a hologram_*_model.json file"
    dialog.Filter = "Hologram model (*.json)|*.json"
    if dialog.ShowDialog() == DialogResult.OK:
        return dialog.FileName
    raise IOError("No hologram_*_model.json found next to this script")


def get_material(doc, spec):
    for mat in FilteredElementCollector(doc).OfClass(Material):
        if mat.Name == spec["name"]:
            break
    else:
        mat = doc.GetElement(Material.Create(doc, spec["name"]))
    r, g, b = spec["rgb"]
    mat.Color = Color(r, g, b)
    mat.Transparency = int(spec["transparency"])
    return mat


def get_subcategory(doc, name, material):
    parent = doc.OwnerFamily.FamilyCategory
    for sub in parent.SubCategories:
        if sub.Name == name:
            break
    else:
        sub = doc.Settings.Categories.NewSubcategory(parent, name)
    sub.Material = material
    return sub


def make_extrusion(doc, solid):
    loops = solid["loops"]
    plane = Plane.CreateByNormalAndOrigin(XYZ(*solid["normal"]), xyz(loops[0][0]))
    sketch = SketchPlane.Create(doc, plane)
    profile = CurveArrArray()
    for loop in loops:
        curves = CurveArray()
        pts = [xyz(p) for p in loop]
        for i in range(len(pts)):
            curves.Append(Line.CreateBound(pts[i], pts[(i + 1) % len(pts)]))
        profile.Append(curves)
    # Extrudes from the sketch plane along its normal by ``depth``.
    return doc.FamilyCreate.NewExtrusion(True, profile, sketch, ft(solid["depth"]))


def build(doc, model):
    if not doc.IsFamilyDocument:
        raise Exception("Open a Generic Model family first (File > New > Family > Metric Generic Model.rft).")

    subcats = {}
    for key, spec in model["materials"].items():
        subcats[key] = get_subcategory(doc, spec["name"], get_material(doc, spec))

    made, failed = 0, []
    for part in model["parts"]:
        ids = List[ElementId]()
        for solid in part["solids"]:
            try:
                ext = make_extrusion(doc, solid)
            except Exception as err:  # keep going; report at the end
                failed.append("{0}: {1}".format(part["id"], err))
                continue
            ext.Subcategory = subcats[part["material"]]
            ids.Add(ext.Id)
            made += 1
        if ids.Count:
            try:
                group = doc.FamilyCreate.NewGroup(ids)
                group.GroupType.Name = "HVR - " + part["name"]
            except Exception:
                pass  # grouping is cosmetic; the geometry is what matters
    return made, failed


def main():
    doc = __revit__.ActiveUIDocument.Document  # noqa: F821 (injected by pyRevit / RPS)
    with open(locate_model()) as fh:
        model = json.load(fh)

    t = Transaction(doc, "Build " + model["name"])
    t.Start()
    try:
        made, failed = build(doc, model)
        t.Commit()
    except Exception:
        t.RollBack()
        raise

    print("{0}: created {1} extrusions in {2} parts.".format(model["name"], made, len(model["parts"])))
    for line in failed:
        print("  skipped " + line)
    print("Overall size (mm): {0}".format(model["envelope_mm"]))
    print("Save the family (e.g. " + model["name"].replace(" ", "") + ".rfa), then load it into a project.")


main()
