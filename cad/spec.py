"""Single source of truth for the Hologram VR Cam glasses hardware.

Geometry, materials, bill of materials and wiring all live here. Every
exporter (IFC for Revit, the pyRevit family builder, the SVG drawings and
the generated docs) reads from this module, and the software's default pin
map is tested against :data:`WIRES`.

Coordinates are millimetres: X = wearer's right, Y = forward, Z = up, with
the origin at the centre of the bridge on the back face of the front frame.
Right-hand parts are defined once and mirrored for the left.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .geometry import Loop, Solid, Vec3, arc, circle, dedupe, poly, rect

# --------------------------------------------------------------------------
# Key dimensions
# --------------------------------------------------------------------------
FRAME_HALF_WIDTH = 75.0       # front frame is 150 mm wide
FRAME_Z = (-24.0, 22.0)       # bottom / top of the front frame
FRAME_Y = (0.0, 7.0)          # front frame thickness
LENS_CENTER_X = 35.0          # lens openings (48 mm lens, 22 mm bridge)
LENS_CENTER_Z = -1.5
LENS_W, LENS_H = 48.0, 37.0
IPD = 63.0                    # optical centres of the two birdbath modules
OPTIC_X = IPD / 2
OPTIC_Z = -3.0
OPTIC_Y = (-17.0, 0.0)
CAMERA_XZ = (67.0, 12.0)      # right endpiece (wearer's right)
LED_XZ = (-67.0, 12.0)        # left endpiece, opposite the camera
TEMPLE_OUTER_X = 74.5
POD_Y = (-112.0, -8.0)        # electronics pods on each temple
POD_Z = (-17.5, 15.5)
POD_X = (63.5, 74.5)          # 11 mm thick, 1.5 mm walls


def front_outline(half_w: float, z_bot: float, z_top: float,
                  r_top: float, r_bot: float, nose_r: float) -> Loop:
    """Wayfarer-style front outline with a nose arch, counter-clockwise."""
    pts: list[tuple[float, float]] = [(nose_r, z_bot)]
    pts += arc(half_w - r_bot, z_bot + r_bot, r_bot, -math.pi / 2, 0.0)
    pts += arc(half_w - r_top, z_top - r_top, r_top, 0.0, math.pi / 2)
    pts += arc(-half_w + r_top, z_top - r_top, r_top, math.pi / 2, math.pi)
    pts += arc(-half_w + r_bot, z_bot + r_bot, r_bot, math.pi, 1.5 * math.pi)
    pts += arc(0.0, z_bot, nose_r, math.pi, 0.0)  # nose arch, over the top
    return tuple(dedupe(pts))


TEMPLE_ARM_PROFILE: Loop = poly(  # (y, z) on the YZ plane, from inside the pod to the ear bend
    (-100, -5), (-118, -3), (-132, -9), (-145, -21), (-150, -22),
    (-152, -18), (-140, -6), (-125, 3), (-110, 6), (-100, 7),
)


# --------------------------------------------------------------------------
# Materials (used for Revit subcategories/materials and IFC colours)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Material:
    name: str
    rgb: tuple[int, int, int]
    transparency: int = 0          # 0..100 (Revit convention)
    shell: bool = False            # drawn see-through in the x-ray view


MATERIALS: dict[str, Material] = {
    "frame": Material("HVR Frame - PA12 nylon matte black", (40, 40, 46), shell=True),
    "lens": Material("HVR Lens - polycarbonate smoke", (96, 118, 140), 65, shell=True),
    "optic_housing": Material("HVR Optics housing - PC-ABS", (88, 92, 104), 30, shell=True),
    "glass": Material("HVR Optics - beamsplitter and combiner", (150, 205, 235), 45),
    "display": Material("HVR Micro-OLED panel", (24, 26, 34)),
    "pcb_green": Material("HVR PCB - FR4 green", (34, 120, 64)),
    "pcb_blue": Material("HVR PCB - FR4 blue", (38, 86, 168)),
    "pcb_purple": Material("HVR PCB - FR4 purple", (106, 64, 150)),
    "chip": Material("HVR IC package", (30, 30, 30)),
    "battery": Material("HVR LiPo cell", (214, 178, 64)),
    "metal": Material("HVR Stainless steel", (176, 178, 184)),
    "silicone": Material("HVR Silicone", (226, 226, 222), 20),
    "led": Material("HVR Privacy LED", (250, 250, 255), 10),
    "camera": Material("HVR Camera module", (22, 22, 24)),
    "copper": Material("HVR Copper tape", (196, 120, 60)),
    "visor": Material("HVR Blackout visor - ABS", (16, 16, 18)),
    "magnet": Material("HVR Neodymium magnet", (150, 150, 158)),
}


# --------------------------------------------------------------------------
# Parts
# --------------------------------------------------------------------------
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


def _xz(outer: Loop, y: tuple[float, float], holes: tuple[Loop, ...] = ()) -> Solid:
    return Solid("XZ", outer, y, holes)


def _yz(outer: Loop, x: tuple[float, float], holes: tuple[Loop, ...] = ()) -> Solid:
    return Solid("YZ", outer, x, holes)


def _xy(outer: Loop, z: tuple[float, float], holes: tuple[Loop, ...] = ()) -> Solid:
    return Solid("XY", outer, z, holes)


def _pod_outline() -> Loop:
    return rect(sum(POD_Y) / 2, sum(POD_Z) / 2, POD_Y[1] - POD_Y[0], POD_Z[1] - POD_Z[0], 6.0)


POD_WALL = 1.5


def _pod_shell() -> tuple[Solid, ...]:
    """Temple pod: a ring around the cavity plus the outer wall. The head-side
    lid is a separate part so the electronics can go in."""
    cy, cz = sum(POD_Y) / 2, sum(POD_Z) / 2
    w, h = POD_Y[1] - POD_Y[0], POD_Z[1] - POD_Z[0]
    x0, x1 = POD_X
    return (
        _yz(_pod_outline(), (x0 + POD_WALL, x1 - POD_WALL),
            (rect(cy, cz, w - 2 * POD_WALL, h - 2 * POD_WALL, 4.5),)),
        _yz(_pod_outline(), (x1 - POD_WALL, x1)),
    )


def _pod_lid() -> tuple[Solid, ...]:
    return (_yz(_pod_outline(), (POD_X[0], POD_X[0] + POD_WALL)),)


def _build_parts() -> tuple[Part, ...]:
    lens_holes = tuple(rect(sx * LENS_CENTER_X, LENS_CENTER_Z, LENS_W, LENS_H, 10.0) for sx in (-1, 1))
    frame = Part(
        "frame_front", "Front frame", "Frame", "frame",
        (_xz(front_outline(FRAME_HALF_WIDTH, FRAME_Z[0], FRAME_Z[1], 8.0, 9.0, 10.0), FRAME_Y,
             lens_holes + (circle(*CAMERA_XZ, 2.8), circle(*LED_XZ, 1.8))),),
        bom="frame_print",
    )
    brow = Part(
        "brow_bay", "Brow electronics bay", "Frame", "frame",
        (_xz(rect(0.0, 18.5, 112.0, 7.0, 2.0), (-16.5, 0.0), (rect(0.0, 18.5, 109.0, 4.0, 1.0),)),
         _xz(rect(0.0, 18.5, 112.0, 7.0, 2.0), (-18.0, -16.5))),
        explode=(0.0, -24.0, 30.0), bom="frame_print",
    )
    visor = Part(
        "visor", "Magnetic blackout visor (VR mode)", "Frame", "visor",
        (_xz(front_outline(70.0, -21.5, 19.5, 7.0, 8.0, 11.5), (7.5, 9.5)),),
        explode=(0.0, 100.0, 0.0), bom="frame_print",
    )
    magnets = Part(
        "magnets", "Visor magnets (4x 3x1 mm)", "Frame", "magnet",
        tuple(_xz(circle(sx * 62.0, sz * 16.0, 1.5), (6.0, 7.0)) for sx in (-1, 1) for sz in (-1, 1)),
        explode=(0.0, 70.0, 0.0), bom="magnets",
    )
    lenses = [Part(
        f"lens_{side}", f"Front lens ({side})", "Frame", "lens",
        (_xz(rect(sx * LENS_CENTER_X, LENS_CENTER_Z, LENS_W + 1.0, LENS_H + 1.0, 10.5), (2.5, 4.5)),),
        explode=(0.0, 30.0, 0.0), bom="lenses",
    ) for side, sx in (("left", -1), ("right", 1))]
    nose_r = Part(
        "nose_pad_right", "Nose pad (right)", "Frame", "silicone",
        (_yz(rect(-7.0, -15.0, 10.0, 14.0, 4.0), (7.0, 10.0)),),
        explode=(6.0, -12.0, -10.0), bom="nose_pads",
    )
    hinge_r = Part(
        "hinge_right", "Spring hinge (right)", "Frame", "metal",
        (_xz(rect(71.0, 0.0, 7.0, 10.0, 1.5), (-6.0, 0.0)),),
        explode=(14.0, -10.0, 0.0), bom="hinges",
    )

    # Birdbath optics, one module per eye (right defined, left mirrored).
    ox = OPTIC_X
    housing_r = Part(
        "optics_housing_right", "Birdbath optics housing (right)", "Optics", "optic_housing",
        (_xz(rect(ox, OPTIC_Z, 42.0, 34.0, 4.0), OPTIC_Y, (rect(ox, OPTIC_Z, 39.0, 31.0, 3.0),)),),
        explode=(0.0, -64.0, 0.0), bom="optics",
    )
    combiner_r = Part(
        "combiner_right", "Concave combiner mirror (right)", "Optics", "glass",
        (_yz(tuple(dedupe(arc(-40.0, OPTIC_Z, 38.5, math.radians(-22), math.radians(22))
                          + arc(-40.0, OPTIC_Z, 37.0, math.radians(22), math.radians(-22)))),
             (ox - 18.0, ox + 18.0)),),
        explode=(0.0, -20.0, 0.0), bom="optics",
    )
    splitter_r = Part(
        "beamsplitter_right", "45 deg beamsplitter (right)", "Optics", "glass",
        (_yz(poly((-15.0, 3.0), (-6.0, -6.0), (-6.0, -4.6), (-15.0, 4.4)), (ox - 18.0, ox + 18.0)),),
        explode=(0.0, -42.0, 0.0), bom="optics",
    )
    oled_r = Part(
        "oled_right", "0.49in 1080p micro-OLED (right eye)", "Optics", "display",
        (_xy(rect(ox, -10.5, 15.0, 11.0, 1.0), (9.5, 11.5)),),
        explode=(0.0, -42.0, 30.0), ifc_class="IfcAudioVisualAppliance", ifc_type="DISPLAY",
        bom="display_kit",
    )

    # Front electronics.
    camera = Part(
        "camera", "OV5647 spy camera (5 MP, 1080p30)", "Electronics", "camera",
        (_xz(circle(*CAMERA_XZ, 2.5), (0.0, 6.8)),
         _xz(rect(*CAMERA_XZ, 8.5, 8.5, 0.6), (-5.0, 0.0))),
        explode=(16.0, 28.0, 12.0), ifc_class="IfcAudioVisualAppliance", ifc_type="CAMERA",
        bom="camera",
    )
    led = Part(
        "privacy_led", "Privacy / recording LED", "Electronics", "led",
        (_xz(circle(*LED_XZ, 1.5), (0.0, 6.9)),
         _xz(rect(*LED_XZ, 6.0, 6.0, 0.5), (-1.5, 0.0))),
        explode=(-16.0, 28.0, 12.0), ifc_class="IfcLightFixture", ifc_type="POINTSOURCE",
        bom="privacy_led",
    )
    driver = Part(
        "display_driver", "Dual micro-OLED HDMI driver board", "Electronics", "pcb_blue",
        (_xy(rect(0.0, -9.0, 56.0, 14.0, 1.0), (16.5, 18.0)),
         _xy(rect(-8.0, -9.0, 12.0, 10.0), (18.0, 19.2))),
        explode=(0.0, -24.0, 50.0), bom="display_kit",
    )
    imu = Part(
        "imu", "MPU-6050 IMU (head tracking)", "Electronics", "pcb_blue",
        (_xy(rect(42.0, -9.0, 20.0, 15.0, 1.0), (16.5, 18.0)),
         _xy(rect(42.0, -9.0, 4.0, 4.0), (18.0, 18.9))),
        explode=(0.0, -24.0, 50.0), ifc_class="IfcSensor", ifc_type="USERDEFINED", bom="imu",
    )
    mic = Part(
        "microphone", "INMP441 I2S MEMS microphone", "Audio", "pcb_purple",
        (_xy(circle(-42.0, -9.0, 6.5), (16.5, 17.7)),),
        explode=(0.0, -24.0, 50.0), ifc_class="IfcAudioVisualAppliance", ifc_type="MICROPHONE",
        bom="microphone",
    )

    # Temples: arm + pod shell, mirrored left/right.
    arm_r = Part(
        "temple_arm_right", "Temple arm (right)", "Frame", "frame",
        (_yz(TEMPLE_ARM_PROFILE, (TEMPLE_OUTER_X - 5.0, TEMPLE_OUTER_X)),),
        explode=(44.0, -26.0, 0.0), bom="frame_print",
    )
    pod_r = Part(
        "temple_pod_right", "Compute pod shell (right temple)", "Frame", "frame",
        _pod_shell(),
        explode=(44.0, -26.0, 0.0), bom="frame_print",
    )
    lid_r = Part(
        "pod_lid_right", "Pod lid, head side (right)", "Frame", "frame", _pod_lid(),
        explode=(16.0, -26.0, 0.0), bom="frame_print",
    )
    pi = Part(
        "pi_zero_2w", "Raspberry Pi Zero 2 W", "Electronics", "pcb_green",
        (_yz(rect(-46.5, -1.0, 65.0, 30.0, 3.0), (65.0, 66.2)),
         _yz(rect(-46.5, -1.0, 12.0, 12.0), (66.2, 67.6)),           # RP3A0 SiP
         _yz(rect(-75.0, 2.0, 7.0, 12.0), (66.2, 67.6)),             # microSD
         _yz(rect(-16.0, -1.0, 4.0, 17.0), (66.2, 67.4))),           # CSI connector
        explode=(60.0, -26.0, 52.0), ifc_class="IfcController", ifc_type="PROGRAMMABLE",
        bom="pi",
    )
    amp = Part(
        "amp", "MAX98357A I2S amplifier", "Audio", "pcb_blue",
        (_yz(rect(-89.0, 0.0, 17.8, 19.6, 1.0), (65.0, 66.6)),),
        explode=(60.0, -26.0, 52.0), bom="amp",
    )
    speaker = Part(
        "speaker", "1510 open-ear speaker", "Audio", "chip",
        (_yz(rect(-104.0, -3.0, 11.0, 15.0, 1.5), (65.0, 68.0)),),
        explode=(60.0, -26.0, 52.0), ifc_class="IfcAudioVisualAppliance", ifc_type="SPEAKER",
        bom="speaker",
    )
    button = Part(
        "capture_button", "Capture button", "Electronics", "metal",
        (_xy(circle(68.5, -30.0, 3.0), (15.5, 17.0)),),
        explode=(44.0, -26.0, 14.0), ifc_class="IfcSwitchingDevice", ifc_type="MOMENTARYSWITCH",
        bom="button",
    )
    touch = Part(
        "touch_strip", "Touch strip (TTP223 + copper pad)", "Electronics", "copper",
        (_yz(rect(-56.0, 2.0, 40.0, 10.0, 2.0), (72.7, 73.0)),
         _yz(rect(-82.0, 2.0, 15.0, 11.0, 1.0), (71.5, 72.7))),
        explode=(44.0, -26.0, -46.0), ifc_class="IfcSensor", ifc_type="USERDEFINED", bom="touch",
    )

    # Left pod contents (defined directly on the left side).
    battery = Part(
        "battery", "LiPo 803040 3.7 V 1000 mAh", "Power", "battery",
        (_yz(rect(-40.0, -1.0, 40.0, 30.0, 2.0), (-73.0, -65.0)),),
        explode=(-78.0, -26.0, 0.0), ifc_class="IfcElectricFlowStorageDevice", ifc_type="BATTERY",
        bom="battery",
    )
    boost = Part(
        "powerboost", "PowerBoost 1000C charger + 5 V boost", "Power", "pcb_blue",
        (_yz(rect(-93.0, -1.0, 36.2, 22.9, 1.5), (-66.6, -65.0)),
         _yz(rect(-108.5, -1.0, 6.0, 8.0), (-69.0, -66.6))),          # USB port
        explode=(-78.0, -26.0, 0.0), bom="powerboost",
    )
    switch = Part(
        "power_switch", "Power slide switch", "Power", "metal",
        (_xy(rect(-69.0, -64.0, 4.0, 9.0, 0.5), (-19.0, -17.5)),),
        explode=(-44.0, -26.0, -14.0), ifc_class="IfcSwitchingDevice", ifc_type="TOGGLESWITCH",
        bom="switch",
    )

    return (
        frame, brow, visor, magnets, *lenses,
        nose_r, nose_r.mirrored("nose_pad_left", "Nose pad (left)"),
        hinge_r, hinge_r.mirrored("hinge_left", "Spring hinge (left)"),
        housing_r.mirrored("optics_housing_left", "Birdbath optics housing (left)"), housing_r,
        combiner_r.mirrored("combiner_left", "Concave combiner mirror (left)"), combiner_r,
        splitter_r.mirrored("beamsplitter_left", "45 deg beamsplitter (left)"), splitter_r,
        oled_r.mirrored("oled_left", "0.49in 1080p micro-OLED (left eye)"), oled_r,
        camera, led, driver, imu, mic,
        arm_r, arm_r.mirrored("temple_arm_left", "Temple arm (left)"),
        pod_r, pod_r.mirrored("temple_pod_left", "Power pod shell (left temple)"),
        lid_r, lid_r.mirrored("pod_lid_left", "Pod lid, head side (left)"),
        pi, amp, speaker, button, touch, battery, boost, switch,
    )


PARTS: tuple[Part, ...] = _build_parts()


# --------------------------------------------------------------------------
# Bill of materials
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class BomLine:
    key: str
    qty: str
    item: str
    spec: str
    notes: str = ""


BOM: tuple[BomLine, ...] = (
    BomLine("pi", "1", "Raspberry Pi Zero 2 W", "Quad Cortex-A53, H.264 1080p30 hardware encoder, Wi-Fi/BT",
            "No GPIO header - solder 30 AWG wires straight to the pads to keep the pod thin."),
    BomLine("sd", "1", "microSD card 64 GB", "A2 / U3 / V30", "Holds the OS and every photo and video."),
    BomLine("camera", "1", "OV5647 'spy' camera for Pi Zero", "5 MP, ~8.5 mm lens board, 22-pin 0.5 mm FPC",
            "Mounted in the right endpiece; the lens sits in the 5.6 mm hole in the frame."),
    BomLine("display_kit", "1 kit", "Dual micro-OLED display kit", "2x 0.39-0.49 in 1920x1080 micro-OLED + HDMI driver",
            "Driver takes one HDMI 1920x1080 side-by-side signal and splits it per eye."),
    BomLine("optics", "2", "Birdbath optics set", "45 deg beamsplitter + concave combiner, ~45 deg FOV",
            "Easiest source: a salvaged display-glasses optical engine."),
    BomLine("imu", "1", "MPU-6050 6-axis IMU (GY-521)", "I2C 0x68, 3.3 V", "3DoF head tracking."),
    BomLine("microphone", "1", "INMP441 I2S MEMS microphone", "24-bit I2S, 3.3 V", "Records the video's audio."),
    BomLine("amp", "1", "MAX98357A I2S class-D amp", "3 W, 4-8 ohm, 5 V", "Shares the I2S clock with the mic."),
    BomLine("speaker", "1", "1510 micro speaker", "15x10x3 mm, 8 ohm, 0.5-1 W", "Open-ear, points at the ear canal."),
    BomLine("button", "1", "Tactile switch", "6x6 mm or 3x6 mm side-actuated", "Capture button on top of the right temple."),
    BomLine("touch", "1", "TTP223 capacitive touch module", "+ 40x10 mm copper tape pad", "Tap / double tap / hold gestures."),
    BomLine("privacy_led", "1 set", "Privacy LED driver", "White 0603 LED, 100 ohm, 2N7002 MOSFET, 100 k pull-down",
            "Lights whenever the camera records. Do not remove or cover it."),
    BomLine("battery", "1", "LiPo cell 803040", "3.7 V 1000 mAh with protection PCB", "Left temple pod."),
    BomLine("powerboost", "1", "Adafruit PowerBoost 1000C (or equivalent)", "LiPo charger + 5 V/1 A boost with LBO pin",
            "LBO goes low below ~3.2 V so the software can save the clip and shut down."),
    BomLine("diode", "1", "Schottky diode", "1N5817 or BAT85", "Isolates LBO (battery voltage) from the 3.3 V GPIO."),
    BomLine("switch", "1", "Mini slide switch", "SPDT, 3 mm travel", "Pulls PowerBoost EN to GND = off."),
    BomLine("hdmi", "1", "Flat mini-HDMI FPV ribbon cable", "10-20 cm + mini-HDMI / driver adapters", "Pi to display driver via the right hinge."),
    BomLine("wire", "-", "Wiring consumables", "30 AWG silicone wire, Kapton tape, 22-pin FPC extension", ""),
    BomLine("magnets", "8", "Neodymium magnets", "3 mm x 1 mm discs", "4 in the frame, 4 in the visor."),
    BomLine("frame_print", "1 set", "Printed frame parts", "SLS PA12 nylon (or MJF), 1.5 mm walls",
            "Front frame, brow bay, 2 pods + lids, 2 arms, 2 optics housings, visor: cad/out/stl/."),
    BomLine("lenses", "2", "Front lenses", "2 mm polycarbonate, smoke tint, cut to the lens outline", ""),
    BomLine("hinges", "2", "Eyewear spring hinges", "7 mm, with M1.4 screws", ""),
    BomLine("nose_pads", "2", "Silicone nose pads", "Push-in type", ""),
)


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------
PI_HEADER: dict[int, str] = {
    1: "3V3", 2: "5V", 3: "GPIO2 SDA", 4: "5V", 5: "GPIO3 SCL", 6: "GND", 7: "GPIO4",
    9: "GND", 11: "GPIO17", 12: "GPIO18 PCM_CLK", 13: "GPIO27", 14: "GND", 15: "GPIO22",
    16: "GPIO23", 17: "3V3", 20: "GND", 25: "GND", 30: "GND", 34: "GND",
    35: "GPIO19 PCM_FS", 38: "GPIO20 PCM_DIN", 39: "GND", 40: "GPIO21 PCM_DOUT",
}


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    location: str
    pins: tuple[str, ...]


DEVICES: dict[str, Device] = {d.id: d for d in (
    Device("imu", "MPU-6050 IMU", "Brow bay", ("VCC", "GND", "SDA", "SCL", "INT")),
    Device("mic", "INMP441 mic", "Brow bay", ("VDD", "GND", "SCK", "WS", "SD", "L/R")),
    Device("touch", "TTP223 touch", "Right temple", ("VCC", "GND", "OUT")),
    Device("button", "Capture button", "Right temple", ("A", "B")),
    Device("led", "Privacy LED driver", "Left endpiece", ("CTRL", "5V", "GND")),
    Device("amp", "MAX98357A amp", "Right temple", ("VIN", "GND", "BCLK", "LRC", "DIN", "OUT+", "OUT-")),
    Device("speaker", "1510 speaker", "Right temple", ("+", "-")),
    Device("boost", "PowerBoost 1000C", "Left temple", ("BAT", "GND", "5V", "LBO", "EN")),
    Device("battery", "LiPo 1000 mAh", "Left temple", ("+", "-")),
    Device("switch", "Power switch", "Left temple", ("COM", "NO")),
    Device("camera", "OV5647 camera", "Right endpiece", ("CSI",)),
    Device("driver", "Micro-OLED driver", "Brow bay", ("HDMI", "5V", "GND", "OLED-L", "OLED-R")),
    Device("oled_l", "Micro-OLED left", "Left optics", ("MIPI",)),
    Device("oled_r", "Micro-OLED right", "Right optics", ("MIPI",)),
)}


@dataclass(frozen=True)
class Wire:
    kind: str                    # power | ground | i2c | i2s | gpio | video | audio
    a: tuple[str, str]           # (device id or "pi", pin name or header number)
    b: tuple[str, str]
    note: str = ""


def _pi(pin: int) -> tuple[str, str]:
    return ("pi", str(pin))


WIRES: tuple[Wire, ...] = (
    # IMU on I2C1
    Wire("power", ("imu", "VCC"), _pi(1)),
    Wire("ground", ("imu", "GND"), _pi(9)),
    Wire("i2c", ("imu", "SDA"), _pi(3)),
    Wire("i2c", ("imu", "SCL"), _pi(5)),
    Wire("gpio", ("imu", "INT"), _pi(7), "optional data-ready interrupt"),
    # Inputs
    Wire("gpio", ("button", "A"), _pi(11), "internal pull-up, active low"),
    Wire("ground", ("button", "B"), _pi(14)),
    Wire("power", ("touch", "VCC"), _pi(17)),
    Wire("ground", ("touch", "GND"), _pi(20)),
    Wire("gpio", ("touch", "OUT"), _pi(13), "active high"),
    # Privacy LED
    Wire("gpio", ("led", "CTRL"), _pi(15), "2N7002 gate, 100 k pull-down"),
    Wire("power", ("led", "5V"), _pi(4), "via 100 ohm to LED anode"),
    Wire("ground", ("led", "GND"), _pi(25)),
    # I2S: mic (capture) and amp (playback) share BCLK/LRCLK
    Wire("power", ("mic", "VDD"), _pi(1)),
    Wire("ground", ("mic", "GND"), _pi(30)),
    Wire("ground", ("mic", "L/R"), _pi(30), "selects the left channel"),
    Wire("i2s", ("mic", "SCK"), _pi(12)),
    Wire("i2s", ("mic", "WS"), _pi(35)),
    Wire("i2s", ("mic", "SD"), _pi(38)),
    Wire("power", ("amp", "VIN"), _pi(4)),
    Wire("ground", ("amp", "GND"), _pi(34)),
    Wire("i2s", ("amp", "BCLK"), _pi(12)),
    Wire("i2s", ("amp", "LRC"), _pi(35)),
    Wire("i2s", ("amp", "DIN"), _pi(40)),
    Wire("audio", ("amp", "OUT+"), ("speaker", "+")),
    Wire("audio", ("amp", "OUT-"), ("speaker", "-")),
    # Power
    Wire("power", ("battery", "+"), ("boost", "BAT"), "JST-PH"),
    Wire("ground", ("battery", "-"), ("boost", "GND")),
    Wire("power", ("boost", "5V"), _pi(2), "through the left hinge and brow bay"),
    Wire("ground", ("boost", "GND"), _pi(6)),
    Wire("gpio", ("boost", "LBO"), _pi(16), "via Schottky (cathode to LBO), pull-up on the Pi"),
    Wire("gpio", ("boost", "EN"), ("switch", "COM"), "EN low = off"),
    Wire("ground", ("switch", "NO"), ("boost", "GND")),
    Wire("power", ("driver", "5V"), ("boost", "5V")),
    Wire("ground", ("driver", "GND"), ("boost", "GND")),
    # Video
    Wire("video", ("camera", "CSI"), ("pi", "CSI"), "22-pin 0.5 mm FPC through the right hinge"),
    Wire("video", ("driver", "HDMI"), ("pi", "mini-HDMI"), "flat FPV ribbon, 1920x1080 side-by-side"),
    Wire("video", ("driver", "OLED-L"), ("oled_l", "MIPI")),
    Wire("video", ("driver", "OLED-R"), ("oled_r", "MIPI")),
)


def gpio_of(device: str, pin: str) -> int:
    """BCM GPIO number wired to ``device.pin`` (used to check software config)."""
    for w in WIRES:
        for here, there in ((w.a, w.b), (w.b, w.a)):
            if here == (device, pin) and there[0] == "pi" and there[1].isdigit():
                label = PI_HEADER[int(there[1])]
                if label.startswith("GPIO"):
                    return int(label.split()[0][4:])
    raise KeyError(f"{device}.{pin} is not wired to a Pi GPIO")


@dataclass(frozen=True)
class Envelope:
    width: float
    depth: float
    height: float


def overall_envelope() -> Envelope:
    from .geometry import bbox_union

    worn = [p for p in PARTS if p.id not in ("visor", "magnets")]
    lo, hi = bbox_union([s.bbox() for p in worn for s in p.solids])
    return Envelope(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])


__all__ = [
    "BOM", "DEVICES", "MATERIALS", "PARTS", "PI_HEADER", "WIRES",
    "BomLine", "Device", "Envelope", "Material", "Part", "Wire",
    "gpio_of", "overall_envelope",
]
