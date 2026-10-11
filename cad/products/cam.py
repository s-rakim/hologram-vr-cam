"""Hologram Cam: slim Ray-Ban-style camera glasses, controlled from a phone over Bluetooth.

Everything runs on a thumb-sized Seeed Studio XIAO ESP32S3 Sense (camera
connector, PDM microphone, microSD slot, LiPo charger, Wi-Fi + BLE), so the
frame stays close to a normal Wayfarer: 146 mm wide, temples 21 mm tall at
the hinge tapering to 12 mm at the ear.

Coordinates are millimetres: X = wearer's right, Y = forward, Z = up, with
the origin at the centre of the bridge on the back face of the front frame.
Right temple: XIAO board, amp, speaker, capture button, touch pad, charge
contacts. Left temple: battery and power switch. Front: camera in the right
endpiece, privacy LED in the left endpiece.
"""
from __future__ import annotations

import math

from ..geometry import Loop, arc, circle, dedupe, offset_convex, poly, rect
from ..product import BomLine, Device, Dim, Part, Product, Ribbon, SchematicSpec, Wire, pi_pin, xy, xz, yz

# --------------------------------------------------------------------------
# Key dimensions
# --------------------------------------------------------------------------
FRAME_HALF_WIDTH = 73.0       # 146 mm wide, like a Wayfarer 50-20
FRAME_Z = (-24.0, 22.0)
FRAME_Y = (0.0, 6.0)
LENS_CENTER_X = 35.0          # 50 mm lenses, 20 mm bridge
LENS_CENTER_Z = -1.0
LENS_W, LENS_H = 50.0, 38.0
CAMERA_XZ = (66.5, 13.0)      # right endpiece
LED_XZ = (-66.5, 13.0)        # left endpiece, opposite the camera
TEMPLE_X = (61.0, 73.0)       # 12 mm thick housing: lid 1.5 | cavity 9 | outer wall 1.5
WALL = 1.5

# Temple housing side profile (y, z), counter-clockwise: 21 mm tall at the hinge,
# tapering to 9 mm where it meets the ear piece.
HOUSING_PROFILE: Loop = poly(
    (-4.0, 11.0), (-60.0, 11.0), (-100.0, 6.0), (-104.0, 4.0),
    (-104.0, -5.0), (-100.0, -7.0), (-60.0, -10.0), (-4.0, -10.0),
)
ARM_PROFILE: Loop = poly(   # ear piece behind the housing
    (-98.0, 5.0), (-118.0, 4.0), (-131.0, -1.0), (-143.0, -12.0), (-149.0, -21.0),
    (-146.0, -24.0), (-138.0, -16.0), (-127.0, -7.0), (-116.0, -4.0), (-98.0, -5.0),
)
BATTERY_NAME = "LiPo 701845 3.7 V ~400 mAh"
XIAO_CENTER = (-17.0, 0.0)    # (y, z) of the XIAO ESP32S3 Sense stack


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


def _housing(right: bool, outer_holes: tuple[Loop, ...] = ()) -> tuple:
    """Temple housing shell: a ring around the cavity plus the outer wall (lid is separate)."""
    x0, x1 = TEMPLE_X
    inner = offset_convex(HOUSING_PROFILE, WALL)
    solids = (
        yz(HOUSING_PROFILE, (x0 + WALL, x1 - WALL), (inner,)),
        yz(HOUSING_PROFILE, (x1 - WALL, x1), outer_holes),
    )
    return solids if right else tuple(s.mirrored_x() for s in solids)


def _lid(right: bool, holes: tuple[Loop, ...] = ()) -> tuple:
    solid = yz(HOUSING_PROFILE, (TEMPLE_X[0], TEMPLE_X[0] + WALL), holes)
    return (solid,) if right else (solid.mirrored_x(),)


def _parts() -> tuple[Part, ...]:
    lens_holes = tuple(rect(sx * LENS_CENTER_X, LENS_CENTER_Z, LENS_W, LENS_H, 11.0) for sx in (-1, 1))
    frame = Part(
        "frame_front", "Front frame", "Frame", "frame",
        (xz(front_outline(FRAME_HALF_WIDTH, FRAME_Z[0], FRAME_Z[1], 8.0, 9.0, 10.0), FRAME_Y,
            lens_holes + (circle(*CAMERA_XZ, 3.0), circle(*LED_XZ, 1.8))),),
        bom="frame_print",
    )
    channel = Part(
        "wire_channel", "Brow wire channel cover", "Frame", "frame",
        (xz(rect(0.0, 19.5, 110.0, 3.0, 1.0), (-1.5, 0.0)),),
        explode=(0.0, -22.0, 18.0), bom="frame_print",
    )
    lenses = [Part(
        f"lens_{side}", f"Lens ({side})", "Frame", "lens",
        (xz(rect(sx * LENS_CENTER_X, LENS_CENTER_Z, LENS_W + 1.0, LENS_H + 1.0, 11.5), (2.0, 4.0)),),
        explode=(0.0, 30.0, 0.0), bom="lenses",
    ) for side, sx in (("left", -1), ("right", 1))]
    nose_r = Part(
        "nose_pad_right", "Nose pad (right)", "Frame", "silicone",
        (yz(rect(-6.0, -14.0, 9.0, 12.0, 3.5), (7.0, 9.5)),),
        explode=(6.0, -12.0, -10.0), bom="nose_pads",
    )
    hinge_r = Part(
        "hinge_right", "Spring hinge (right)", "Frame", "metal",
        (xz(rect(69.0, 0.0, 7.0, 9.0, 1.5), (-4.0, 0.0)),),
        explode=(14.0, -10.0, 0.0), bom="hinges",
    )
    camera = Part(
        "camera", "Camera module (OV2640 / OV5640, long FPC)", "Electronics", "camera",
        (xz(circle(*CAMERA_XZ, 2.8), (0.0, 5.8)),
         xz(rect(*CAMERA_XZ, 8.5, 8.5), (-4.0, 0.0))),
        explode=(16.0, 28.0, 12.0), ifc_class="IfcAudioVisualAppliance", ifc_type="CAMERA", bom="camera",
    )
    led = Part(
        "privacy_led", "Privacy / recording LED", "Electronics", "led",
        (xz(circle(*LED_XZ, 1.5), (0.0, 5.9)),
         xz(rect(*LED_XZ, 6.0, 6.0), (-1.5, 0.0))),
        explode=(-16.0, 28.0, 12.0), ifc_class="IfcLightFixture", ifc_type="POINTSOURCE", bom="privacy_led",
    )

    # Temples.
    grille = tuple(circle(-92.0 + dy, -0.5 + dz, 1.0) for dy in (-4.0, 0.0, 4.0) for dz in (-2.5, 2.5))
    housing_r = Part("temple_housing_right", "Temple housing (right, electronics)", "Frame", "frame",
                     _housing(True), explode=(40.0, -24.0, 0.0), bom="frame_print")
    housing_l = Part("temple_housing_left", "Temple housing (left, battery)", "Frame", "frame",
                     _housing(False), explode=(-40.0, -24.0, 0.0), bom="frame_print")
    lid_r = Part("temple_lid_right", "Temple lid, head side (right)", "Frame", "frame", _lid(True, grille),
                 explode=(14.0, -24.0, 0.0), bom="frame_print")
    lid_l = Part("temple_lid_left", "Temple lid, head side (left)", "Frame", "frame", _lid(False),
                 explode=(-14.0, -24.0, 0.0), bom="frame_print")
    arm_r = Part("temple_arm_right", "Ear piece (right)", "Frame", "frame",
                 (yz(ARM_PROFILE, (TEMPLE_X[1] - 5.0, TEMPLE_X[1])),), explode=(40.0, -40.0, 0.0), bom="frame_print")

    xc, zc = XIAO_CENTER
    xiao = Part(
        "xiao_esp32s3", "XIAO ESP32S3 Sense", "Electronics", "pcb_blue",
        (yz(rect(xc, zc, 21.0, 17.8, 1.5), (63.0, 64.2)),          # main board
         yz(rect(xc - 0.5, zc, 14.0, 12.0), (64.2, 66.6)),          # ESP32-S3 module can
         yz(rect(xc, zc, 21.0, 17.8, 1.5), (66.8, 68.0)),          # Sense expansion board
         yz(rect(xc + 4.0, zc - 3.0, 11.0, 10.0), (68.0, 69.8))),   # microSD slot + camera connector
        explode=(66.0, -24.0, 40.0), ifc_class="IfcController", ifc_type="PROGRAMMABLE", bom="xiao",
    )
    amp = Part(
        "amp", "MAX98357A I2S amp (mini)", "Audio", "pcb_purple",
        (yz(rect(-41.0, 0.0, 14.0, 12.0, 1.0), (63.0, 64.6)),),
        explode=(66.0, -24.0, 40.0), bom="amp",
    )
    speaker = Part(
        "speaker", "1510 open-ear speaker", "Audio", "chip",
        (yz(rect(-92.0, -0.5, 15.0, 10.0, 1.5), (62.5, 65.5)),),
        explode=(66.0, -24.0, 40.0), ifc_class="IfcAudioVisualAppliance", ifc_type="SPEAKER", bom="speaker",
    )
    touch = Part(
        "touch_pad", "Touch pad (copper tape, ESP32 touch pin)", "Electronics", "copper",
        (yz(rect(-52.0, 1.0, 30.0, 12.0, 2.0), (71.2, 71.5)),),
        explode=(84.0, -24.0, 0.0), ifc_class="IfcSensor", ifc_type="USERDEFINED", bom="touch",
    )
    button = Part(
        "capture_button", "Capture button", "Electronics", "metal",
        (xy(circle(67.0, -40.0, 2.5), (11.0, 12.5)),),
        explode=(40.0, -24.0, 16.0), ifc_class="IfcSwitchingDevice", ifc_type="MOMENTARYSWITCH", bom="button",
    )
    pads = Part(
        "charge_contacts", "Magnetic charging contacts (5 V)", "Power", "metal",
        (xy(rect(67.0, -62.0, 9.0, 4.0), (-11.0, -9.9)),),
        explode=(40.0, -24.0, -16.0), bom="charge",
    )
    battery = Part(
        "battery", BATTERY_NAME, "Power", "battery",
        (yz(rect(-33.0, 0.5, 45.0, 17.0, 2.0), (-70.0, -63.0)),),
        explode=(-66.0, -24.0, 40.0), ifc_class="IfcElectricFlowStorageDevice", ifc_type="BATTERY", bom="battery",
    )
    switch = Part(
        "power_switch", "Power slide switch", "Power", "metal",
        (xy(rect(-67.0, -64.0, 4.0, 8.0), (-11.0, -9.8)),),
        explode=(-40.0, -24.0, -16.0), ifc_class="IfcSwitchingDevice", ifc_type="TOGGLESWITCH", bom="switch",
    )

    return (
        frame, channel, *lenses,
        nose_r, nose_r.mirrored("nose_pad_left", "Nose pad (left)"),
        hinge_r, hinge_r.mirrored("hinge_left", "Spring hinge (left)"),
        camera, led,
        housing_r, housing_l, lid_r, lid_l, arm_r, arm_r.mirrored("temple_arm_left", "Ear piece (left)"),
        xiao, amp, speaker, touch, button, pads, battery, switch,
    )


# XIAO ESP32S3 pins (physical pin number -> label). D8-D10 are taken by the Sense board's microSD.
XIAO_HEADER: dict[int, str] = {
    1: "GPIO1 D0 A0", 2: "GPIO2 D1", 3: "GPIO3 D2 TOUCH3", 4: "GPIO4 D3", 5: "GPIO5 D4", 6: "GPIO6 D5",
    7: "GPIO43 D6", 8: "GPIO44 D7", 9: "GPIO7 D8 SD-SCK", 10: "GPIO8 D9 SD-MISO", 11: "GPIO9 D10 SD-MOSI",
    12: "3V3", 13: "GND", 14: "5V",
}

BOM: tuple[BomLine, ...] = (
    BomLine("xiao", "1", "Seeed Studio XIAO ESP32S3 Sense", "ESP32-S3 240 MHz, 8 MB PSRAM, Wi-Fi + BLE 5, camera, PDM mic, "
            "microSD, LiPo charger", "The whole brain of the glasses. Flash firmware/glasses before assembly."),
    BomLine("camera", "1", "Camera module with long FPC", "OV2640 (2 MP, comes with the Sense) or OV5640 (5 MP AF), 75 mm FPC",
            "Right endpiece; the lens sits in the 6 mm hole in the frame."),
    BomLine("sd", "1", "microSD card", "32 GB, FAT32, A1 / U3", "Long recordings are split into 5-minute files."),
    BomLine("amp", "1", "MAX98357A I2S amp, mini module", "3 W class D, ~14 x 12 mm", "Capture and notification sounds."),
    BomLine("speaker", "1", "1510 micro speaker", "15 x 10 x 3 mm, 8 ohm", "Faces the ear through the lid grille."),
    BomLine("button", "1", "Tactile switch", "3 x 6 mm side-actuated", "Capture button on top of the right temple."),
    BomLine("touch", "1", "Copper tape touch pad", "30 x 12 mm + 30 AWG lead", "Read by the ESP32-S3's built-in touch sensor."),
    BomLine("privacy_led", "1 set", "Privacy LED driver", "White 0603 LED, 47 ohm, 2N7002 MOSFET, 100 k pull-down",
            "Lights whenever the camera records. Do not remove or cover it."),
    BomLine("battery", "1", BATTERY_NAME, "7 x 17 x 45 mm pouch with protection PCB (check the real capacity)",
            "Left temple; charged by the XIAO's on-board charger."),
    BomLine("divider", "1 set", "Battery voltage divider", "2 x 200 k + 100 nF", "Lets the firmware read the battery level."),
    BomLine("switch", "1", "Mini slide switch", "SPDT, 2-3 mm travel", "In series with the battery: hard off."),
    BomLine("charge", "1", "2-pin magnetic pogo connector", "+ matching USB cable", "Charging without opening the temple."),
    BomLine("wire", "-", "Wiring consumables", "30 AWG silicone wire, Kapton tape", "4 wires run through the brow channel."),
    BomLine("frame_print", "1 set", "Printed frame parts", "SLS PA12 nylon (or resin), 1.5 mm walls",
            "Front frame, brow channel, 2 temple housings + lids, 2 ear pieces: cad/out/cam/stl/."),
    BomLine("lenses", "2", "Lenses", "2 mm polycarbonate (sun, clear or prescription), cut to the outline", ""),
    BomLine("hinges", "2", "Eyewear spring hinges", "7 mm, with M1.4 screws", ""),
    BomLine("nose_pads", "2", "Silicone nose pads", "Push-in type", ""),
)

DEVICES: dict[str, Device] = {d.id: d for d in (
    Device("battery", "LiPo cell", "Left temple", ("+", "-")),
    Device("switch", "Power switch", "Left temple", ("IN", "OUT")),
    Device("vsense", "Battery divider", "200 k / 200 k + 100 nF", ("IN", "OUT", "GND")),
    Device("led", "Privacy LED driver", "Left endpiece", ("CTRL", "VBAT", "GND")),
    Device("button", "Capture button", "Right temple", ("A", "B")),
    Device("touch", "Touch pad", "Right temple", ("PAD",)),
    Device("amp", "MAX98357A amp", "Right temple", ("VIN", "GND", "BCLK", "LRC", "DIN", "SD", "OUT+", "OUT-")),
    Device("speaker", "1510 speaker", "Right temple", ("+", "-")),
    Device("charge", "Charge contacts", "Right temple", ("+", "-")),
    Device("camera", "Camera module", "Right endpiece", ("FPC",)),
)}

WIRES: tuple[Wire, ...] = (
    Wire("power", ("battery", "+"), ("switch", "IN"), "JST-SH or direct solder"),
    Wire("power", ("switch", "OUT"), ("pi", "BAT+"), "through the left hinge and the brow channel"),
    Wire("ground", ("battery", "-"), ("pi", "BAT-"), "through the brow channel"),
    Wire("power", ("vsense", "IN"), ("pi", "BAT+")),
    Wire("analog", ("vsense", "OUT"), pi_pin(1), "200 k / 200 k divider, 100 nF to GND"),
    Wire("ground", ("vsense", "GND"), pi_pin(13)),
    Wire("gpio", ("led", "CTRL"), pi_pin(4), "2N7002 gate, 100 k pull-down"),
    Wire("power", ("led", "VBAT"), ("pi", "BAT+"), "via 47 ohm to the LED anode"),
    Wire("ground", ("led", "GND"), pi_pin(13)),
    Wire("gpio", ("button", "A"), pi_pin(2), "internal pull-up, active low"),
    Wire("ground", ("button", "B"), pi_pin(13)),
    Wire("touch", ("touch", "PAD"), pi_pin(3), "ESP32-S3 capacitive touch channel 3"),
    Wire("power", ("amp", "VIN"), ("pi", "BAT+")),
    Wire("ground", ("amp", "GND"), pi_pin(13)),
    Wire("i2s", ("amp", "BCLK"), pi_pin(5)),
    Wire("i2s", ("amp", "LRC"), pi_pin(6)),
    Wire("i2s", ("amp", "DIN"), pi_pin(7)),
    Wire("gpio", ("amp", "SD"), pi_pin(8), "low = amp off (saves power when silent)"),
    Wire("audio", ("amp", "OUT+"), ("speaker", "+")),
    Wire("audio", ("amp", "OUT-"), ("speaker", "-")),
    Wire("power", ("charge", "+"), pi_pin(14), "charges the LiPo through the XIAO"),
    Wire("ground", ("charge", "-"), pi_pin(13)),
    Wire("video", ("camera", "FPC"), ("pi", "CAM"), "24-pin camera FPC through the right hinge"),
)

SCHEMATIC = SchematicSpec(
    layout={
        "battery": (44, 160, 140, {"+": "R", "-": "R"}),
        "switch": (270, 120, 170, {"IN": "L", "OUT": "R"}),
        "vsense": (270, 250, 170, {"IN": "R", "OUT": "R", "GND": "R"}),
        "led": (270, 400, 170, {"CTRL": "R", "VBAT": "R", "GND": "R"}),
        "button": (1180, 130, 220, {}),
        "touch": (1180, 230, 220, {}),
        "amp": (1180, 320, 220, {"OUT+": "R", "OUT-": "R"}),
        "speaker": (1452, 440, 104, {"+": "L", "-": "L"}),
        "charge": (1180, 560, 220, {}),
    },
    compute_box=(650.0, 250.0, 280.0, 400.0),
    left_pins=("BAT+", "BAT-", 1, 4),
    right_pins=(2, 3, 5, 6, 7, 8),
    drawn_power=frozenset({(("battery", "+"), ("switch", "IN")), (("switch", "OUT"), ("pi", "BAT+")),
                           (("battery", "-"), ("pi", "BAT-"))}),
    ribbons=(
        Ribbon(((790.0, 168.0), (790.0, 250.0)), "camera FPC (24-pin)", (802.0, 226.0), "start",
               (700.0, 112.0, 180.0, 56.0, "Camera module", "Right endpiece  |  OV2640 / OV5640")),
    ),
    pin_notes=(("led", "CTRL", "2N7002 gate, 100 k to GND"),),
    left_lane_far=470.0,
    right_lane_far=1075.0,
    legend_xy=(44.0, 620.0),
    power_notes=("Power pins", "3V3 out: 12", "5V in (USB / charging): 14", "GND: 13",
                 "BAT+ / BAT-: pads under the board"),
)

PRODUCT = Product(
    key="cam",
    name="Hologram Cam",
    tagline="Slim Ray-Ban-style camera glasses: POV photo and video, phone control over Bluetooth",
    compute="XIAO ESP32S3 Sense",
    compute_location="Right temple, by the hinge",
    parts=_parts(),
    bom=BOM,
    devices=DEVICES,
    wires=WIRES,
    schematic=SCHEMATIC,
    callouts=(
        ("camera", "POV camera", "Photos + MJPEG video to microSD"),
        ("privacy_led", "Privacy LED", "Lit for the whole recording"),
        ("xiao_esp32s3", "XIAO ESP32S3 Sense", "Bluetooth, Wi-Fi, mic, microSD"),
        ("battery", "Battery (left temple)", BATTERY_NAME),
        ("capture_button", "Capture button", "Press = photo, hold = video"),
        ("touch_pad", "Touch pad", "Tap = battery, hold = Wi-Fi sync"),
        ("speaker", "Open-ear speaker", "Capture sounds and alerts"),
        ("charge_contacts", "Charging contacts", "Magnetic 5 V pogo pins"),
    ),
    dims=(
        Dim("front", (LENS_CENTER_X + LENS_W / 2, 0, 22), (LENS_CENTER_X - LENS_W / 2, 0, 22), -16, f"lens {LENS_W:.0f}"),
        Dim("front", (LENS_CENTER_X - LENS_W / 2, 0, 22), (-(LENS_CENTER_X - LENS_W / 2), 0, 22), -16,
            f"{2 * (LENS_CENTER_X - LENS_W / 2):.0f}"),
        Dim("side", (-FRAME_HALF_WIDTH, -4.0, 11.0), (-FRAME_HALF_WIDTH, -4.0, -10.0), 30, "21", vertical=True),
    ),
    notes=(
        "2. Frame, channel, temple housings, lids, ear pieces: SLS PA12 or resin, 1.5 mm walls.",
        f"3. Lens {LENS_W:.0f} mm, bridge {2 * (LENS_CENTER_X - LENS_W / 2):.0f} mm; temples 12 mm thick, "
        "21 mm tall at the hinge.",
        "4. Temples flex ~5 deg outward when worn; model shows them parallel.",
    ),
    exploded_subtitle="Build order: frame + camera + LED > right temple (XIAO, amp, speaker) > left temple (battery) > lids",
    printed=("frame_front", "wire_channel", "temple_housing_right", "temple_housing_left",
             "temple_lid_right", "temple_lid_left", "temple_arm_right", "temple_arm_left"),
    header=XIAO_HEADER,
)
