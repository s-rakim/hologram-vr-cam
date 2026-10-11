"""Hologram VR: a VR headset built into an F1-style closed-face helmet shell.

How the picture gets to your eyes: two 2.9in 1440x1440 panels sit in the
brow, above your eyes, facing down. Each one projects its picture onto a
curved (ellipsoidal) mirror in the visor, which reflects a magnified,
distant image back into the eye. The mirrors wrap around the face, so the
view is far wider than flat lenses give (the ray-traced figures are in the
callouts; see hologram/vr/optics.py, which this model uses directly so the
CAD and the renderer always agree).

The rest of the helmet is used too: the closed ear cups carry 40 mm drivers
for head-tracked surround sound, the rear aero pod carries the Raspberry Pi 5
and four 18650 cells as a counterweight to the optics, and the flip-up visor
is dark for VR.

NOT A CRASH HELMET: it is a printed enclosure, it blocks your view, and it
must never be worn while riding, driving or walking about.

Coordinates are millimetres: X = wearer's right, Y = forward, Z = up, with
the origin between the eyes at eye level.
"""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from hologram.vr.optics import ReflectorOptics, field_of_view

from .. import helmet as H
from ..geometry import Solid, circle, poly, rect
from ..product import BomLine, Device, Dim, Part, Product, Ribbon, SchematicSpec, Wire, pi_pin, xz, yz

OPTICS = ReflectorOptics()
FOV = field_of_view(OPTICS)
IPD = OPTICS.ipd
EAR_YZ = (-90.0, -30.0)       # ear canal, behind and below the eyes
LINER = 12.0                  # comfort foam inside the shell
MIRROR_THICK = 2.5
PANEL_THICK = 2.5


# --------------------------------------------------------------------------
# Optics geometry, straight from the optics model
# --------------------------------------------------------------------------
def _rising(grid: np.ndarray) -> np.ndarray:
    """Order the rows so z increases along each column (band slicing needs it)."""
    return grid if grid[-1, :, 2].mean() >= grid[0, :, 2].mean() else grid[::-1]


def mirror_grids(side: int, rows: int = 16, cols: int = 22) -> tuple[np.ndarray, np.ndarray]:
    """Reflecting surface and back surface of one mirror, (rows, cols, 3) each."""
    az = np.linspace(*OPTICS.mirror_az_deg, cols)
    el = np.linspace(*OPTICS.mirror_el_deg, rows)
    A, E = np.meshgrid(az, el)
    front = OPTICS.view_hits(A, E, side)
    eye = OPTICS.eye(side)
    out = (front - eye) / np.linalg.norm(front - eye, axis=-1, keepdims=True)
    back = front + out * MIRROR_THICK
    if side < 0:                                   # keep columns running left to right
        front, back = front[:, ::-1], back[:, ::-1]
    return _rising(front), _rising(back)


def mirror_mesh(side: int):
    front, back = mirror_grids(side)
    return H.layer_mesh(back, front)


def _plate(side: int, grow: float, offsets: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    """A plate parallel to one panel: its outline grown by ``grow`` mm, between two
    offsets along the panel normal (+ = towards the mirror)."""
    o = replace(OPTICS, display_mm=(OPTICS.display_mm[0] + 2 * grow, OPTICS.display_mm[1] + 2 * grow))
    corners = o.panel_corners(side)                       # (-,-) (+,-) (+,+) (-,+) in (u, v)
    grid = np.array([[corners[0], corners[1]], [corners[3], corners[2]]])
    centre, u, v = OPTICS.display_frame(side)
    normal = np.cross(u, v)
    _, f2 = OPTICS.foci(side)
    if normal @ (centre - f2) < 0:                        # point the normal at the mirror
        normal = -normal
    a, b = (_rising(grid + normal * off) for off in offsets)
    if side < 0:
        a, b = a[:, ::-1], b[:, ::-1]
    return a, b


def plate_mesh(side: int, grow: float, offsets: tuple[float, float]):
    a, b = _plate(side, grow, offsets)
    return H.layer_mesh(b, a)


def plate_solids(side: int, grow: float, offsets: tuple[float, float]) -> tuple[Solid, ...]:
    a, b = _plate(side, grow, offsets)
    return H.patch_solids(a, b, steps=6)


# --------------------------------------------------------------------------
# Parts
# --------------------------------------------------------------------------
VISOR = H.Section("visor", "Visor", (H.PORT[0] - 5.0, H.PORT[1] + 5.0), (H.PORT_PHI[0] - 3.0, H.PORT_PHI[1] + 3.0))
VISOR_INSETS = (-4.0, -1.5)                    # 2.5 mm thick, 1.5 mm proud of the shell


def _pod_box() -> tuple[float, float]:
    """Rear pod's front face (touching the back of the shell) and back face, in y."""
    y_front = min(H.surface_point(270.0, phi)[1] for phi in (-10.0, 0.0, 10.0))
    return y_front - 46.0, y_front


def _parts() -> tuple[Part, ...]:
    explode = {
        "shell_crown_front": (0.0, 60.0, 130.0), "shell_crown_rear": (0.0, -60.0, 130.0),
        "shell_cheek_right": (110.0, 30.0, 0.0), "shell_cheek_left": (-110.0, 30.0, 0.0),
        "shell_chin_bar": (0.0, 70.0, -120.0), "shell_rear_lower": (0.0, -80.0, -70.0),
    }
    shell = [Part(s.id, s.name, "Shell", "livery", H.section_solids(s), explode=explode[s.id], bom="shell_print")
             for s in H.SECTIONS]
    liner = Part(
        "liner", "Comfort liner (foam)", "Shell", "foam",
        sum((H.section_solids(s, 16.0, (H.SHELL, H.SHELL + LINER)) for s in H.SECTIONS
             if s.id in ("shell_crown_front", "shell_crown_rear", "shell_rear_lower")), ()),
        bom="foam",
    )
    visor = Part("visor", "Flip-up visor (dark for VR)", "Shell", "visor_smoke",
                 H.section_solids(VISOR, 6.0, VISOR_INSETS), explode=(0.0, 150.0, 30.0), bom="visor_print")
    phi_mid = sum(H.PORT_PHI) / 2
    px, py, pz = H.surface_point(H.PORT[0] - 8.0, phi_mid)
    pivot_r = Part("visor_pivot_right", "Visor pivot screw (right)", "Shell", "metal",
                   (yz(circle(py, pz, 6.0), (px - 1.0, px + 5.0)),), explode=(60.0, 150.0, 30.0), bom="hardware")

    # Rear spoiler: a wing on the top of the back, with end plates down to the shell.
    lo, hi = H.surface_point(270.0, 26.0), H.surface_point(270.0, 44.0)
    te = (lo[1] - 30.0, lo[2] + 16.0)
    wing = yz(poly((lo[1] + 2.0, lo[2] - 2.0), te, (te[0] + 3.0, te[1] + 6.0), (hi[1] + 2.0, hi[2] - 2.0)), (-72.0, 72.0))
    side_pt = H.surface_point(270.0 - 33.0, 30.0)
    plate_profile = poly((lo[1] + 2.0, side_pt[2] - 22.0), (te[0] - 4.0, te[1] - 4.0), (te[0] + 2.0, te[1] + 8.0),
                         (hi[1] + 2.0, hi[2] + 2.0))
    spoiler = Part("rear_spoiler", "Rear spoiler with end plates", "Aero", "livery",
                   (wing, yz(plate_profile, (72.0, 75.0)), yz(plate_profile, (-75.0, -72.0))),
                   explode=(0.0, -90.0, 60.0), bom="aero_print")

    # Top air intake above the visor (vents the visor so the mirrors don't fog).
    ix, iy, iz = H.surface_point(90.0, 40.0)
    intake = Part("top_intake", "Top air intake", "Aero", "livery",
                  (xz(rect(0.0, iz + 6.0, 58.0, 18.0, 4.0), (iy - 34.0, iy - 4.0), (rect(0.0, iz + 7.0, 48.0, 9.0, 2.0),)),),
                  explode=(0.0, 40.0, 90.0), bom="aero_print")

    # Optics: brow panels, their trays, the visor mirrors and the nose divider.
    mirror_r = Part("mirror_right", "Visor mirror, ellipsoidal (right eye)", "Optics", "mirror",
                    H.patch_solids(*mirror_grids(+1), steps=10), explode=(40.0, 110.0, -20.0), bom="mirrors")
    mirror_l = Part("mirror_left", "Visor mirror, ellipsoidal (left eye)", "Optics", "mirror",
                    H.patch_solids(*mirror_grids(-1), steps=10), explode=(-40.0, 110.0, -20.0), bom="mirrors")
    panel_r = Part("display_right", "2.9in 1440x1440 panel (right eye)", "Optics", "display",
                   plate_solids(+1, 1.5, (0.0, -PANEL_THICK)), explode=(30.0, 60.0, 90.0),
                   ifc_class="IfcAudioVisualAppliance", ifc_type="DISPLAY", bom="displays")
    panel_l = Part("display_left", "2.9in 1440x1440 panel (left eye)", "Optics", "display",
                   plate_solids(-1, 1.5, (0.0, -PANEL_THICK)), explode=(-30.0, 60.0, 90.0),
                   ifc_class="IfcAudioVisualAppliance", ifc_type="DISPLAY", bom="displays")
    tray_r = Part("panel_tray_right", "Panel tray (right)", "Optics", "frame",
                  plate_solids(+1, 4.0, (-PANEL_THICK - 0.5, -PANEL_THICK - 3.5)), explode=(30.0, 60.0, 110.0),
                  bom="optics_print")
    tray_l = Part("panel_tray_left", "Panel tray (left)", "Optics", "frame",
                  plate_solids(-1, 4.0, (-PANEL_THICK - 0.5, -PANEL_THICK - 3.5)), explode=(-30.0, 60.0, 110.0),
                  bom="optics_print")
    front_r, _ = mirror_grids(+1)
    nasal = front_r[:, 0]                                     # the right mirror's nasal edge, bottom to top
    tray_a, _ = _plate(+1, 4.0, (-PANEL_THICK - 0.5, -PANEL_THICK - 3.5))
    inner_top = [tuple(tray_a[1, 0]), tuple(tray_a[0, 0])]
    divider_pts = [(float(p[1]) + 1.0, float(p[2])) for p in nasal] + [(p[1], p[2]) for p in inner_top]
    divider = Part("nose_divider", "Nose divider / optics bridge", "Optics", "frame",
                   (yz(_hull(divider_pts), (-1.5, 1.5)),), explode=(0.0, 90.0, 40.0), bom="optics_print")
    top_z = float(max(tray_a[..., 2].max(), _plate(+1, 4.0, (-PANEL_THICK - 0.5, -PANEL_THICK - 3.5))[1][..., 2].max()))
    imu = Part("imu", "MPU-6050 IMU (head tracking)", "Electronics", "pcb_blue",
               (Solid("XY", rect(0.0, 48.0, 20.0, 15.0, 1.0), (top_z + 1.0, top_z + 2.6)),
                Solid("XY", rect(0.0, 48.0, 4.0, 4.0), (top_z + 2.6, top_z + 3.5))),
               explode=(0.0, 60.0, 140.0), ifc_class="IfcSensor", ifc_type="USERDEFINED", bom="imu")
    cam_phi = H.PORT_PHI[1] + 4.0
    cx, cy, cz = H.surface_point(90.0, cam_phi, H.SHELL)
    camera = Part("passthrough_camera", "Camera Module 3 Wide (passthrough)", "Electronics", "camera",
                  (xz(rect(0.0, cz, 25.0, 24.0, 1.5), (cy - 9.0, cy - 6.5)), xz(circle(0.0, cz, 4.0), (cy - 6.5, cy + 1.0))),
                  explode=(0.0, 170.0, 70.0), ifc_class="IfcAudioVisualAppliance", ifc_type="CAMERA", bom="camera")

    # Chin bar: the dual-panel driver board and the load switch that powers it.
    _, chin_y, _ = H.surface_point(90.0, -32.0, H.SHELL)
    driver = Part("display_driver", "Dual-panel HDMI driver board", "Electronics", "pcb_blue",
                  (xz(rect(0.0, -78.0, 64.0, 46.0, 2.0), (chin_y - 22.0, chin_y - 20.4)),),
                  explode=(0.0, 110.0, -100.0), bom="displays")
    load_switch = Part("display_switch", "Display power load switch", "Electronics", "pcb_blue",
                       (xz(rect(42.0, -78.0, 14.0, 10.0, 1.0), (chin_y - 30.0, chin_y - 28.4)),),
                       explode=(30.0, 110.0, -100.0), bom="load_switch")

    # Ear cups (right defined, left mirrored).
    ey, ez = EAR_YZ
    ear_x = 80.0
    cushion_r = Part("ear_cushion_right", "Ear cushion (right)", "Audio", "foam",
                     (yz(circle(ey, ez, 32.0), (ear_x, ear_x + 12.0), (circle(ey, ez, 21.0),)),),
                     explode=(50.0, 0.0, 0.0), bom="foam")
    driver40_r = Part("speaker_right", "40 mm speaker driver (right ear)", "Audio", "chip",
                      (yz(circle(ey, ez, 20.0), (ear_x + 12.0, ear_x + 22.0)),), explode=(75.0, 0.0, 0.0),
                      ifc_class="IfcAudioVisualAppliance", ifc_type="SPEAKER", bom="speakers")
    amp_r = Part("amp_right", "MAX98357A amp (right)", "Audio", "pcb_blue",
                 (yz(rect(ey + 40.0, ez, 18.0, 20.0, 1.0), (ear_x + 22.0, ear_x + 23.6)),),
                 explode=(100.0, 0.0, 0.0), bom="amps")

    # Rear aero pod: Pi 5 on a 4 x 18650 UPS board, fan side facing the vents.
    y_back, y_front = _pod_box()
    pod_z = 4.0
    pod = Part("rear_pod", "Rear aero pod", "Rear pod", "livery",
               (xz(rect(0.0, pod_z, 112.0, 104.0, 18.0), (y_back + 3.0, y_front), (rect(0.0, pod_z, 106.0, 98.0, 15.0),)),),
               explode=(0.0, -150.0, 0.0), bom="pod_print")
    vents = tuple(rect(0.0, pod_z + z, 60.0, 3.0) for z in (-20.0, -10.0, 0.0, 10.0, 20.0))
    pod_cover = Part("rear_pod_cover", "Rear pod cover (vents)", "Rear pod", "livery",
                     (xz(rect(0.0, pod_z, 112.0, 104.0, 18.0), (y_back, y_back + 3.0), vents),),
                     explode=(0.0, -200.0, 0.0), bom="pod_print")
    cells = Part("cells", "4 x 18650 Li-ion cells", "Power", "battery",
                 tuple(yz(circle(y_front - 12.0, pod_z + z, 9.25), (-32.5, 32.5)) for z in (-33.0, -12.0, 9.0, 30.0)),
                 explode=(0.0, -40.0, 0.0), ifc_class="IfcElectricFlowStorageDevice", ifc_type="BATTERY", bom="cells")
    ups = Part("ups_board", "Pi 5 UPS board (4 x 18650)", "Power", "pcb_purple",
               (xz(rect(0.0, pod_z, 97.4, 85.0, 3.0), (y_front - 25.0, y_front - 23.4)),),
               explode=(0.0, -75.0, 0.0), bom="ups")
    pi5 = Part("pi5", "Raspberry Pi 5 + active cooler", "Electronics", "pcb_green",
               (xz(rect(0.0, pod_z, 85.0, 56.0, 3.0), (y_front - 30.0, y_front - 28.4)),
                xz(rect(-8.0, pod_z, 40.0, 40.0, 2.0), (y_back + 6.0, y_front - 30.0)),     # active cooler over the SoC
                xz(rect(34.0, pod_z, 17.0, 50.0), (y_back + 4.0, y_front - 30.0))),         # USB / Ethernet block
               explode=(0.0, -110.0, 0.0), ifc_class="IfcController", ifc_type="PROGRAMMABLE", bom="pi5")

    # Control pod on the left of the chin bar, where an F1 helmet's radio plug sits.
    kx, ky, kz = H.surface_point(160.0, -36.0)
    ctrl = Part("control_pod", "Control pod (left side)", "Controls", "frame",
                (yz(rect(ky, kz, 60.0, 30.0, 8.0), (kx - 16.0, kx + 3.0)),), explode=(-60.0, 0.0, 0.0), bom="pod_print")
    buttons = Part("buttons", "Buttons: mode, action, volume -, volume +", "Controls", "metal",
                   tuple(yz(circle(ky + dy, kz, 4.0), (kx - 18.0, kx - 16.0)) for dy in (-21.0, -7.0, 7.0, 21.0)),
                   explode=(-80.0, 0.0, 0.0), ifc_class="IfcSwitchingDevice", ifc_type="MOMENTARYSWITCH", bom="buttons")

    return (
        *shell, liner, visor, pivot_r.mirrored("visor_pivot_left", "Visor pivot screw (left)"), pivot_r,
        spoiler, intake,
        tray_l, tray_r, panel_l, panel_r, mirror_l, mirror_r, divider, imu, camera,
        driver, load_switch,
        cushion_r.mirrored("ear_cushion_left", "Ear cushion (left)"), cushion_r,
        driver40_r.mirrored("speaker_left", "40 mm speaker driver (left ear)"), driver40_r,
        amp_r.mirrored("amp_left", "MAX98357A amp (left)"), amp_r,
        cells, ups, pi5, pod, pod_cover, ctrl, buttons,
    )


def _hull(points: list[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    """Convex hull (counter-clockwise), with points closer than 1 mm merged."""
    pts = sorted(set((round(x, 2), round(y, 2)) for x, y in points))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    upper: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    out: list[tuple[float, float]] = []
    for p in hull:
        if not out or math.dist(p, out[-1]) >= 1.0:
            out.append(p)
    if len(out) > 2 and math.dist(out[0], out[-1]) < 1.0:
        out.pop()
    return tuple(out)


BOM: tuple[BomLine, ...] = (
    BomLine("pi5", "1", "Raspberry Pi 5 (4 GB) + Active Cooler", "Quad Cortex-A76, dual 4K HDMI, VideoCore VII",
            "HDMI0 drives both panels as one 2880 x 1440 side-by-side picture."),
    BomLine("ups", "1", "Pi 5 UPS board for 4 x 18650 (e.g. Geekworm X1202)", "5.1 V / 5 A out, mounts under the Pi",
            "Its fuel gauge sits on I2C (0x36 on the X120x boards). Check its wiki for the GPIOs it uses."),
    BomLine("cells", "4", "18650 Li-ion cells", "3.6 V ~3500 mAh, same model and batch (e.g. Samsung 35E)",
            "About 50 Wh: 4+ hours of VR. Never mix old and new cells."),
    BomLine("sd", "1", "microSD card", "32-128 GB, A2", "Raspberry Pi OS + 360 photos and their sound."),
    BomLine("displays", "1 kit", "Dual 2.9in 1440 x 1440 LCD kit with HDMI driver board",
            "One HDMI input, 2880 x 1440 side by side (e.g. Wisecoco)",
            "Panels in the brow, driver board in the chin bar. Ask the seller for a 60 Hz mode."),
    BomLine("hdmi", "1", "Micro-HDMI to HDMI flat cable", "50 cm FPV ribbon", "Rear pod to chin bar, inside the liner."),
    BomLine("mirrors", "2", "Visor mirrors (ellipsoidal reflectors)", "cad/out/vr/stl/mirror_*.stl",
            "Resin print, sand to 2000 grit, clear coat, then first-surface mirror finish (see the build guide)."),
    BomLine("imu", "1", "MPU-6050 IMU (GY-521)", "I2C 0x68", "On the optics bridge, rigid with the panels."),
    BomLine("camera", "1", "Raspberry Pi Camera Module 3 Wide", "+ 500 mm Pi 5 camera cable",
            "Above the visor, through a 9 mm hole: passthrough view of the room."),
    BomLine("amps", "2", "MAX98357A I2S amp", "3 W class D (Adafruit-style board, 1 M SD pull-up)",
            "Channel select: left amp SD straight to VIN; right amp SD to VIN through 470 k (0.8-1.4 V on SD)."),
    BomLine("speakers", "2", "40 mm helmet speaker drivers", "8 ohm, low profile (~10 mm)", "In the ear cups."),
    BomLine("buttons", "4", "Tactile buttons", "6 x 6 mm, long stem", "Mode, action, volume down, volume up."),
    BomLine("load_switch", "1", "Load switch module", "e.g. TPS22918 / P-MOSFET, 5 V 2 A", "Cuts the display board in sleep."),
    BomLine("foam", "1 set", "Comfort foam", "Liner, cheek pads, ear cushions (10-15 mm PU foam)", ""),
    BomLine("shell_print", "1 set", "Printed F1 shell", "6 sections, 2.4 mm walls, LW-PLA or PETG",
            "cad/out/vr/stl/shell_*.stl (each fits a 256 mm printer). NOT a crash helmet."),
    BomLine("visor_print", "1", "Visor", "cad/out/vr/stl/visor.stl", "Print in black PETG for VR."),
    BomLine("aero_print", "1 set", "Aero parts", "Rear spoiler, top air intake", ""),
    BomLine("optics_print", "1 set", "Optics carrier", "Two panel trays + nose divider (PETG, black)", ""),
    BomLine("pod_print", "1 set", "Printed pods", "Rear aero pod + vented cover, control pod", ""),
    BomLine("hardware", "-", "Hardware", "M3 heat-set inserts + screws, chin strap, VHB tape",
            "Joins the shell sections; two M4 screws are the visor pivots."),
)

DEVICES: dict[str, Device] = {d.id: d for d in (
    Device("cells", "4 x 18650", "Rear pod", ("+", "-")),
    Device("ups", "UPS board", "Rear pod, under the Pi", ("BAT+", "BAT-", "5V", "GND", "SDA", "SCL")),
    Device("dswitch", "Display load switch", "Chin bar", ("CTRL", "VIN", "VOUT", "GND")),
    Device("imu", "MPU-6050 IMU", "Optics bridge", ("VCC", "GND", "SDA", "SCL", "INT")),
    Device("controls", "Control pod", "Left side", ("MODE", "ACTION", "VOL-", "VOL+", "GND")),
    Device("amp_l", "MAX98357A left", "Left ear cup", ("VIN", "GND", "BCLK", "LRC", "DIN", "OUT+", "OUT-")),
    Device("amp_r", "MAX98357A right", "Right ear cup", ("VIN", "GND", "BCLK", "LRC", "DIN", "OUT+", "OUT-")),
    Device("spk_l", "Speaker L", "40 mm, left ear", ("+", "-")),
    Device("spk_r", "Speaker R", "40 mm, right ear", ("+", "-")),
    Device("camera", "Camera Module 3 Wide", "Above the visor", ("CSI",)),
    Device("drv", "Dual-panel driver", "Chin bar", ("HDMI", "5V", "GND", "MIPI_L", "MIPI_R")),
    Device("lcd_l", "2.9in LCD left", "Brow, left eye", ("MIPI",)),
    Device("lcd_r", "2.9in LCD right", "Brow, right eye", ("MIPI",)),
)}

WIRES: tuple[Wire, ...] = (
    Wire("power", ("cells", "+"), ("ups", "BAT+"), "4 cells in parallel, in the board's holders"),
    Wire("ground", ("cells", "-"), ("ups", "BAT-")),
    Wire("power", ("ups", "5V"), pi_pin(2), "pogo pins under the Pi"),
    Wire("ground", ("ups", "GND"), pi_pin(6)),
    Wire("i2c", ("ups", "SDA"), pi_pin(3), "battery fuel gauge"),
    Wire("i2c", ("ups", "SCL"), pi_pin(5)),
    Wire("power", ("imu", "VCC"), pi_pin(1)),
    Wire("ground", ("imu", "GND"), pi_pin(9)),
    Wire("i2c", ("imu", "SDA"), pi_pin(3)),
    Wire("i2c", ("imu", "SCL"), pi_pin(5)),
    Wire("gpio", ("imu", "INT"), pi_pin(7)),
    Wire("gpio", ("dswitch", "CTRL"), pi_pin(15), "high = displays on"),
    Wire("power", ("dswitch", "VIN"), pi_pin(4)),
    Wire("ground", ("dswitch", "GND"), pi_pin(14)),
    Wire("power", ("drv", "5V"), ("dswitch", "VOUT")),
    Wire("ground", ("drv", "GND"), ("dswitch", "GND")),
    Wire("gpio", ("controls", "MODE"), pi_pin(11), "to GND when pressed, internal pull-ups"),
    Wire("gpio", ("controls", "ACTION"), pi_pin(13)),
    Wire("gpio", ("controls", "VOL-"), pi_pin(33)),
    Wire("gpio", ("controls", "VOL+"), pi_pin(29)),
    Wire("ground", ("controls", "GND"), pi_pin(39)),
    Wire("power", ("amp_l", "VIN"), pi_pin(2)),
    Wire("ground", ("amp_l", "GND"), pi_pin(20)),
    Wire("i2s", ("amp_l", "BCLK"), pi_pin(12)),
    Wire("i2s", ("amp_l", "LRC"), pi_pin(35)),
    Wire("i2s", ("amp_l", "DIN"), pi_pin(40), "SD tied to VIN = left channel"),
    Wire("power", ("amp_r", "VIN"), pi_pin(4)),
    Wire("ground", ("amp_r", "GND"), pi_pin(25)),
    Wire("i2s", ("amp_r", "BCLK"), pi_pin(12)),
    Wire("i2s", ("amp_r", "LRC"), pi_pin(35)),
    Wire("i2s", ("amp_r", "DIN"), pi_pin(40), "SD via 470 k to VIN = right channel"),
    Wire("audio", ("amp_l", "OUT+"), ("spk_l", "+")),
    Wire("audio", ("amp_l", "OUT-"), ("spk_l", "-")),
    Wire("audio", ("amp_r", "OUT+"), ("spk_r", "+")),
    Wire("audio", ("amp_r", "OUT-"), ("spk_r", "-")),
    Wire("video", ("camera", "CSI"), ("pi", "CAM0"), "500 mm cable over the crown"),
    Wire("video", ("drv", "HDMI"), ("pi", "HDMI0"), "2880 x 1440, left half = left eye"),
    Wire("video", ("drv", "MIPI_L"), ("lcd_l", "MIPI")),
    Wire("video", ("drv", "MIPI_R"), ("lcd_r", "MIPI")),
)

SCHEMATIC = SchematicSpec(
    layout={
        "cells": (44, 120, 140, {"+": "R", "-": "R"}),
        "ups": (270, 110, 170, {"BAT+": "L", "BAT-": "L", "5V": "R", "GND": "R", "SDA": "R", "SCL": "R"}),
        "imu": (270, 300, 170, {"VCC": "R", "GND": "R", "SDA": "R", "SCL": "R", "INT": "R"}),
        "dswitch": (270, 460, 170, {"CTRL": "R", "VIN": "R", "VOUT": "L", "GND": "R"}),
        "controls": (1180, 110, 220, {}),
        "amp_l": (1180, 270, 220, {"OUT+": "R", "OUT-": "R"}),
        "amp_r": (1180, 470, 220, {"OUT+": "R", "OUT-": "R"}),
        "spk_l": (1452, 370, 104, {"+": "L", "-": "L"}),
        "spk_r": (1452, 570, 104, {"+": "L", "-": "L"}),
    },
    compute_box=(650.0, 250.0, 280.0, 420.0),
    left_pins=(2, 3, 5, 7, 15),
    right_pins=(11, 13, 33, 29, 12, 35, 40),
    drawn_power=frozenset({(("cells", "+"), ("ups", "BAT+")), (("cells", "-"), ("ups", "BAT-")),
                           (("ups", "5V"), ("pi", "2"))}),
    ribbons=(
        Ribbon(((790.0, 168.0), (790.0, 250.0)), "CSI (500 mm)", (802.0, 226.0), "start",
               (700.0, 112.0, 180.0, 56.0, "Camera Module 3 Wide", "Above the visor  |  passthrough")),
        Ribbon(((790.0, 670.0), (790.0, 740.0)), "HDMI0  2880 x 1440", (802.0, 712.0), "start",
               (660.0, 740.0, 260.0, 64.0, "Dual-panel driver (chin bar)", "MIPI to 2 x 2.9in 1440x1440 in the brow")),
    ),
    pin_notes=(("dswitch", "CTRL", "high = displays on"),),
    left_lane_far=530.0,
    right_lane_far=1075.0,
    legend_xy=(44.0, 640.0),
)

PRINTED = (tuple(s.id for s in H.SECTIONS)
           + ("visor", "rear_spoiler", "top_intake", "panel_tray_left", "panel_tray_right", "nose_divider",
              "mirror_left", "mirror_right", "rear_pod", "rear_pod_cover", "control_pod"))

PRODUCT = Product(
    key="vr",
    name="Hologram VR",
    tagline="F1-style VR helmet: brow displays projected onto wrap-around visor mirrors, ear-cup surround sound, 4 h+",
    compute="Raspberry Pi 5",
    compute_location="Rear aero pod",
    parts=_parts(),
    bom=BOM,
    devices=DEVICES,
    wires=WIRES,
    schematic=SCHEMATIC,
    callouts=(
        ("display_right", "Brow displays", "2 x 2.9in 1440x1440, facing down"),
        ("mirror_right", "Visor mirrors", f"Wrap-around: ~{FOV.horizontal:.0f} x {FOV.vertical:.0f} deg (model)"),
        ("visor", "Flip-up visor", "Dark smoke for VR"),
        ("passthrough_camera", "Passthrough camera", "See the room without taking it off"),
        ("speaker_right", "Ear-cup speakers", "Head-tracked surround sound"),
        ("pi5", "Raspberry Pi 5", "Rear aero pod, counterweight"),
        ("cells", "4 x 18650 (~50 Wh)", "4+ hours of VR"),
        ("control_pod", "Control pod", "Mode, action, volume"),
        ("rear_spoiler", "Rear spoiler", "F1-style, printed"),
        ("shell_crown_front", "Printed F1 shell", "6 sections, NOT a crash helmet"),
    ),
    dims=(
        Dim("front", (-IPD / 2, 0.0, -60.0), (IPD / 2, 0.0, -60.0), 20, f"IPD {IPD:.0f}"),
    ),
    notes=(
        "2. NOT A CRASH HELMET. Printed VR enclosure: never ride, drive, cycle or walk around in it.",
        f"3. Shell: 6 sections, {H.SHELL:.1f} mm walls (LW-PLA or PETG), joined with M3 inserts.",
        f"4. Field of view ~{FOV.horizontal:.0f} x {FOV.vertical:.0f} deg, ray-traced model (upper bound).",
    ),
    accessories=("liner",),
    iso=(0.95, 1.0, 0.55),
    exploded_subtitle="Build order: rear pod (Pi 5 + cells) > optics carrier > shell sections > visor > ear cups",
    printed=PRINTED,
    meshes={
        **{s.id: (lambda s=s: H.section_mesh(s)) for s in H.SECTIONS},
        "visor": lambda: H.section_mesh(VISOR, 3.0, VISOR_INSETS),
        "mirror_right": lambda: mirror_mesh(+1),
        "mirror_left": lambda: mirror_mesh(-1),
        "panel_tray_right": lambda: plate_mesh(+1, 4.0, (-PANEL_THICK - 0.5, -PANEL_THICK - 3.5)),
        "panel_tray_left": lambda: plate_mesh(-1, 4.0, (-PANEL_THICK - 0.5, -PANEL_THICK - 3.5)),
    },
)
