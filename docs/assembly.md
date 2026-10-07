# Build guide

How to build the Hologram VR Cam glasses from the model in this repo. Keep these open while you work:

| Sheet | What it shows |
|-------|---------------|
| [01 Assembly (x-ray)](drawings/01_assembly.svg) | where every module sits inside the frame |
| [02 Exploded](drawings/02_exploded.svg) | numbered parts and build order |
| [03 Orthographic](drawings/03_orthographic.svg) | overall dimensions, lens and IPD spacing |
| [04 Wiring](drawings/04_wiring.svg) | every connection, colour-coded |
| [bom.md](bom.md) / [wiring.md](wiring.md) | parts list and pin table (generated from `cad/spec.py`) |

> **Safety first.** LiPo cells can catch fire if punctured, shorted or over-discharged: use a cell with a
> protection PCB, never pierce it, and keep it away from the soldering iron. The electronics sit against your
> head, which is why the software stops recording when the Pi gets hot; don't disable that. Don't use VR mode
> (visor on) while walking, cycling or driving. Recording people without their knowledge is illegal in many
> places: the privacy LED is lit for the whole recording, so keep it visible.

## 0. Before you start

**Tools:** fine-tip soldering iron, flux, 30 AWG silicone wire (26 AWG for 5 V/GND), Kapton tape, multimeter,
drill bits (1, 1.5, 3 and 6 mm), needle files, CA glue or 2-part epoxy, M1.4 screwdriver.

**Order the parts** in [bom.md](bom.md). The micro-OLED kit and birdbath optics are the long-lead items. The easiest
source is a salvaged pair of "display glasses", whose optical engine already pairs the panels with the optics.

**Print the frame** from `cad/out/stl/` (SLS/MJF PA12 nylon is best: strong and thin-walled; FDM works for a
first fit test). Parts are exported in assembly position, so lay them flat in your slicer:

| File | Notes |
|------|-------|
| `frame_front.stl` | print face-down |
| `brow_bay.stl` | glues to the back of the frame's top bar |
| `temple_pod_right.stl` + `temple_arm_right.stl` | load both as one object (they overlap by 12 mm) and print as one piece |
| `temple_pod_left.stl` + `temple_arm_left.stl` | same as the right side |
| `pod_lid_right.stl`, `pod_lid_left.stl` | head-side lids, held with 2x M1.4 screws or a bead of hot glue so you can reopen them |
| `optics_housing_left/right.stl` | only if your optics did not come with a housing |
| `visor.stl` | the magnetic blackout shade for VR mode |

**Drill and cut** these openings after printing. They are not modelled, so mark them from the dimensions:

| Where | Opening | For |
|-------|---------|-----|
| Right pod, top, 22 mm behind the pod's front end | 6 mm hole | capture button |
| Right pod lid, 96 mm behind the front end, 3 mm below the centreline | 6x 1.5 mm holes | speaker grille (faces your ear) |
| Left pod, rear wall | 9 x 4 mm slot | micro-USB charging port |
| Left pod, underside, 56 mm behind the front end | 4 x 9 mm slot | power switch |
| Brow bay, top, 42 mm left of centre (wearer's left) | 1 mm hole | microphone port |
| Both pods, front wall, and both ends of the brow bay | 6 x 3 mm slots | wiring through the hinges |

## 1. Bench test everything first

Wire all modules on the desk with jumper leads, exactly as in [wiring.md](wiring.md), *before* anything goes into
the frame. Hidden faults are miserable to find once the pods are closed.

1. Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager (set Wi-Fi, SSH and a user).
2. Copy this repo onto the Pi and run `./deploy/setup_pi.sh`, then reboot.
3. Check each module:
   - `i2cdetect -y 1` shows `68` (IMU)
   - `rpicam-hello --list-cameras` lists the OV5647
   - `arecord -l` lists the I2S microphone; `speaker-test -c1 -twav` plays through the speaker
   - the micro-OLEDs show the Pi console over HDMI
4. `python3 -m hologram run`: tap the button for a photo, hold it to record, tap again to stop. Check
   `~/DCIM/Hologram/` for the files and that the LED was lit while recording.

## 2. Front frame

1. Press the lenses into the frame grooves (a drop of CA glue at the corners).
2. Glue the 4 magnets into the frame face, and the other 4 into the visor. **Check the polarity** so they attract.
3. Fit the camera from behind the right endpiece so the lens sits in the 5.6 mm hole, level with the front face.
   A crooked camera gives crooked videos, so square it to the lens openings before the glue sets.
4. Fit the privacy LED and its MOSFET board into the left endpiece hole.
5. Push in the nose pads and screw on the spring hinges.

## 3. Optics

Each eye gets one birdbath module: the micro-OLED faces down onto the 45 degree beamsplitter, which reflects the
image forward onto the concave combiner and back through the splitter to your eye.

1. Mount each module behind its lens opening with its optical centre **31.5 mm from the frame centre**
   (63 mm IPD). If your IPD differs a lot, shift the modules and set `display.lens_center_shift` later.
2. Route each OLED's FPC up into the brow bay.

## 4. Brow bay

1. Mount the display driver board in the middle of the bay and connect both OLED FPCs.
2. Mount the IMU on the wearer's right side with its **X axis pointing right and Y forward** (the GY-521 has the
   axes printed on it). Otherwise set `tracking.axis_map` (step 8).
3. Mount the microphone on the wearer's left, with its port under the 1 mm hole.
4. Glue the bay to the back of the frame's top bar.

## 5. Right temple: compute pod

1. Solder wires straight to the Pi Zero 2 W's GPIO pads (no header, to keep the pod thin). Pins are in
   [wiring.md](wiring.md).
2. Lay the Pi flat against the pod's outer wall, with the camera connector towards the hinge.
3. Fit the amplifier behind the Pi and the speaker in the rear of the pod, facing the grille in the lid.
4. Fit the capture button under its 6 mm hole and stick the copper touch pad inside the outer wall, with the
   TTP223 module next to it.
5. Run the camera FPC and the flat mini-HDMI ribbon through the right hinge to the camera and the driver board.

## 6. Left temple: power pod

1. Fit the LiPo at the front of the pod and the PowerBoost at the rear, with its USB port at the slot.
2. Solder the slide switch between the PowerBoost `EN` and `GND` pins.
3. Solder the Schottky diode in the `LBO` line: **cathode (band) towards LBO**, anode towards the Pi's GPIO23.
4. Keep the battery leads short and taped. Nothing sharp may touch the cell.

## 7. Harness through the hinges

| Hinge | Wires |
|-------|-------|
| Right | camera FPC, mini-HDMI ribbon, 5 V, GND, 3V3, SDA, SCL, INT, I2S SCK / WS / SD, LED CTRL, LBO |
| Left  | 5 V, GND, LBO |

Bundle each run with Kapton tape and leave a ~15 mm service loop at each hinge so the temples can fold without
pulling on the solder joints. Check every wire with the multimeter, then close the pod lids.

## 8. First boot and calibration

1. Power on with the slide switch. The service starts on boot (`journalctl -u hologram -f` to watch).
2. **IMU axes:** `python3 -m hologram imu-check`. Nod up: pitch should rise. Turn left: yaw should rise. If an
   axis is wrong, edit `tracking.axis_map` in `config/hologram.toml`, e.g. `["-y", "x", "z"]`.
3. **Display alignment:** wear the glasses with the visor on. The 360 grid world should fuse into one image.
   If you see double, adjust `display.lens_center_shift` in steps of 0.02. If straight grid lines bow at the
   edges, tune `display.k1`/`k2`. `python3 -m hologram snapshot` renders a frame to PNG for checking off-device.
4. **Recentre:** double-tap the touch strip while looking straight ahead.

## 9. Everyday use

| Control | Action |
|---------|--------|
| Capture button: tap | Photo (LED double-flashes) |
| Capture button: hold 0.6 s | Start video (LED stays on). Tap to stop; clips stop on their own at 60 s |
| Touch strip: tap | Display mode: 360 view, then camera passthrough, then display off (camera-only glasses) |
| Touch strip: double tap | Recentre the view |
| Touch strip: hold 0.8 s | Display sleep / wake |
| Visor | Clip on for immersive VR, take off for see-through AR |

Copy media off with `scp` or a USB card reader (`~/DCIM/Hologram/`).

## Power budget (rough estimates)

| Load | Typical draw |
|------|--------------|
| Pi Zero 2 W encoding 1080p30 | 1.0 to 1.5 W |
| Two micro-OLEDs + driver | 0.8 to 1.5 W |
| Camera module | ~0.3 W |
| IMU, mic, touch, LED | < 0.1 W |

That is about 2 to 3.5 W in total from a 3.7 Wh cell at ~85% boost efficiency: **roughly an hour of mixed use**,
longer with the display off. Measure your own build with a USB power meter. When the battery runs low,
PowerBoost `LBO` tells the software to finish the clip and shut down cleanly.
