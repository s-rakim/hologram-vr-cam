# Hologram VR: build guide

An F1-style VR helmet: two brow-mounted panels project onto curved visor mirrors, a Raspberry Pi 5 renders, and the
ear cups give head-tracked surround sound. Keep these open while you work:

| Sheet | What it shows |
|-------|---------------|
| [01 Assembly (x-ray)](drawings/01_assembly.svg) | where everything sits inside the shell |
| [02 Exploded](drawings/02_exploded.svg) | numbered parts and build order |
| [03 Orthographic](drawings/03_orthographic.svg) | overall size, eye-slot and IPD |
| [04 Wiring](drawings/04_wiring.svg) | every connection, colour-coded |
| [bom.md](bom.md) / [wiring.md](wiring.md) | parts list and pin table, generated from `cad/products/vr.py` |

> **Safety.**
> - **This is not a crash helmet.** It has no impact liner, it is not certified, and it blocks your view. Never wear
>   it to ride, drive, cycle or walk around. Use it seated or standing still in a clear space.
> - **18650 cells store a lot of energy.** Use four identical, new cells from a real supplier. Never mix old and new
>   cells, and don't let the pod's metal parts touch the cell terminals.
> - **Heat.** The Pi 5 throttles at 80 °C. Keep the pod's vents clear.
> - **Fogging.** A closed visor fogs up. The top intake and the gap under the chin bar vent it; don't seal them.
> - **Sunlight.** The concave visor mirrors can focus sunlight that gets in through the neck opening onto the panels,
>   which can burn the panels or scorch the foam. Never leave the helmet in direct sun, especially resting crown-down
>   with the neck opening towards a window. Store it upright on its neck ring, or with a cover over the opening.

## How the optics work

```
            brow  ┌──────────────┐  panel (faces down)
                  │   ▓▓▓▓▓▓▓▓   │
                  │      ╲       │  light goes down and forward ...
   eye  ◉ ────────┼───────╲──────┤
                  │        ╲     │  ... onto the concave visor mirror,
                  │         )    │  which reflects a magnified, distant
                  │        )     │  picture back into the eye
            chin  └──────────────┘
```

Each mirror is a patch of an **ellipsoid** whose first focus is your eye. Any ray that reaches your eye after the
mirror left the panel along a line through the ellipsoid's *second* focus, which sits above your eye in the brow.
So `hologram/vr/optics.py` can work out, exactly and in closed form, which direction every panel pixel appears in. The
renderer pre-warps each frame to match, which is why the picture on the panel looks bent and the one in your eye
doesn't. The same optics model generates the mirror and panel-tray geometry in the CAD, so the two always agree, and
the tests check that the mirrors fit inside the shell and clear your face.

Ray-traced field of view (run `python -m hologram.vr optics` for your settings): about **106° horizontal x 74°
vertical** across both eyes, with 50° of stereo overlap. That is an upper bound. The model is exact for the ray through
the centre of the pupil, but a real 4-5 mm pupil, imperfect mirror surfaces and assembly tolerances blur the edges.
Project North Star builders measure their reflector headset well below its published figures.

## 0. Tools and parts

**Tools:** 3D printer with a 256 mm bed (Bambu X1/P1, Prusa MK4/XL, or similar); access to a resin printer (or a print
service) for the mirrors; soldering iron; heat-set insert tip; M3 heat-set inserts and screws; drill bits up to 12 mm;
two-part epoxy; filler primer and paint; sandpaper 240-2000 grit; multimeter.

**Order the parts** in [bom.md](bom.md). Long-lead items:

- **Dual 2.9in 1440x1440 LCD kit with one HDMI driver board** (Wisecoco and others sell it for DIY VR). Confirm
  with the seller that the board takes a single **2880 x 1440 side-by-side** HDMI signal and offers a **60 Hz** mode.
  One user reported a black screen on a Jetson Nano with one of these boards, so test it on the Pi before you build it
  in.
- **Pi 5 UPS board for 4 x 18650**, e.g. Geekworm X1202. Read its wiki: it uses some GPIOs itself (power-loss detect,
  charge control) and its fuel gauge sits on I2C. The helmet's buttons use GPIO 5, 13, 17, 27 and the display switch
  GPIO 22, chosen to stay clear of the X120x boards' pins, but check yours.

## 1. Print the shell

Files are in `cad/out/vr/stl/`, in assembly position (mm). Rotate each part so its largest open edge is on the bed.

| File | Size (mm) | Notes |
|---|---|---|
| `shell_crown_front.stl` | 248 x 174 x 135 | top front: brow over the eye slot |
| `shell_crown_rear.stl` | 245 x 164 x 135 | top back |
| `shell_rear_lower.stl` | 246 x 165 x 182 | back and neck |
| `shell_chin_bar.stl` | 246 x 173 x 139 | chin bar under the eye slot |
| `shell_cheek_right.stl`, `_left.stl` | 23 x 120 x 41 | the thin strips beside the eye slot |
| `visor.stl` | 233 x 77 x 66 | black PETG for VR |
| `rear_spoiler.stl`, `top_intake.stl` | | glue on after painting |
| `rear_pod.stl`, `rear_pod_cover.stl`, `control_pod.stl` | | PETG (the pod gets warm) |
| `panel_tray_left/right.stl`, `nose_divider.stl` | | black PETG: they must not reflect light |
| `mirror_left.stl`, `mirror_right.stl` | 97 x 53 x 93 | resin, see step 3 |

**Shell material:** LW-PLA (foaming PLA) at about 60 % density keeps the six shell parts around 400 g. PETG is
stronger but about twice as heavy (~780 g). The walls are 2.4 mm: 6 perimeters with a 0.4 mm nozzle, so print with
**no infill and 6 walls**, plus tree supports for the overhangs at the brow and chin.

**Weight:** about 1.2 kg all-in (estimate), close to a real F1 helmet's ~1.25 kg. The rear pod balances the optics at
the front.

## 2. Join, drill and finish the shell

1. Dry-fit the six sections. Glue them with two-part epoxy and 20 mm-wide **joiner strips** (offcuts of 1 mm PETG
   sheet, or 1 mm printed strips) across every seam on the inside. Add M3 heat-set inserts at the seams if you want to
   take it apart again.
2. Drill these holes; they are not modelled:

   | Where | Hole | For |
   |---|---|---|
   | Front centre, 12 mm above the eye slot (about 45 mm above eye level) | 9 mm | passthrough camera lens |
   | Both sides of the eye slot, 115 mm out from the centre line, level with the slot's middle | 4.2 mm | visor pivot screws (M4) |
   | Under the top intake | 3 x 6 mm slots | intake air over the mirrors |
   | Back centre, behind the rear pod | 12 mm | cable bundle from the pod (HDMI, I2C, I2S, buttons) |
   | Left of the chin bar, behind the control pod | 8 mm | control pod wires |

3. Fill, sand and paint your livery. The model is coloured F1 red, but it's your helmet.
4. Glue on the rear spoiler and the top intake.
5. Fit the visor with two M4 screws and nylon washers at the pivots. It should flip up and stay up.

## 3. Make the mirrors (the hard part)

The picture is only as sharp as the mirror surface. Two ways, best first:

1. **Resin print + vacuum metallising (best).** Print `mirror_*.stl` in resin with the concave reflecting side facing
   up (away from the supports) at the finest layer height. Wet-sand the concave side through 400, 800, 1200 and 2000
   grit, then flood it with a thin coat of clear UV resin or a 2K clear coat to get a glossy, ripple-free surface. Send
   it to a vacuum-metallising (chrome PVD) service, or a model-making shop that chrome-plates plastic parts.
2. **Resin print + mirror spray (quick, softer image).** Same print and clear coat, then a "chrome mirror" spray
   (Alclad II Chrome, Spaz Stix Ultimate Mirror Chrome or similar) on the concave side. It gives a usable but hazier
   picture.

Either way the **concave side is the mirror** (light hits it from the panel side, not through the plastic), and you
should handle it only by the edges.

**See-through AR variant (optional):** a 50 % beam-splitter coating, as on Project North Star's combiners, lets you see
the room through the mirrors with the visor up. Half the panel light is lost, so VR gets dimmer; the software works
either way.

## 4. Optics carrier

1. Glue each panel into its tray with the **active (picture) side facing away from the tray**, towards where the mirror
   will be. Run the FPCs out of the tray's inner edge.
2. Glue the two trays to the nose divider; together they form the optics bridge.
3. Glue the IMU (GY-521) flat on top of the bridge between the panels, with its **X axis pointing right and Y forward**.
   Otherwise set `tracking.axis_map`.
4. Mount the bridge to the inside of the crown front with three M3 x 20 mm nylon standoffs, and the mirrors to the
   inside of the shell at their edges, so each sits where the model shows (01 assembly sheet). Hot glue lets you nudge
   them while you calibrate (step 7); use epoxy once everything looks right.
5. Fit the camera behind its 9 mm hole, pointing straight ahead.

## 5. Electronics

Wire everything on the desk first, exactly as in [wiring.md](wiring.md), and run the software (step 6) before anything
goes into the shell.

**Rear pod:** stack the Pi 5 (with the Active Cooler) on the UPS board as its manual describes, fit the 4 cells, then
screw the stack into the pod with the cooler facing the vented cover. Pi pins used: I2C (3, 5), IMU interrupt (7),
display switch (15), buttons (11, 13, 29, 33), I2S (12, 35, 40), 5 V and GND.

**Chin bar:** the dual-panel driver board sits against the inside of the chin bar, with the load switch next to it.
The 50 cm flat micro-HDMI cable runs from the Pi's **HDMI0** (the port next to the USB-C) around inside the liner. The
two MIPI FPCs run up to the panels.

**Ear cups:** a MAX98357A board and a 40 mm driver in each, with the ear cushion over the driver. Both amps share the
I2S lines (BCLK pin 12, LRC pin 35, DIN pin 40). **Channel select:** tie the left amp's SD pin to VIN; connect the right
amp's SD to VIN through a 470 k resistor (on Adafruit-style boards with a 1 M SD pull-up that puts SD at 0.8-1.4 V,
which selects the right channel). Measure SD with a multimeter if your boards differ.

**Control pod:** four buttons (mode, action, volume -, volume +) to GND on GPIO 17, 27, 13 and 5, using the Pi's
internal pull-ups.

**Liner:** glue 10-15 mm foam into the crown and the back so the helmet sits snugly without touching the optics.

## 6. Install the software

1. Flash **Raspberry Pi OS Lite (64-bit, Bookworm)** with Raspberry Pi Imager (set Wi-Fi, SSH and a user).
2. On the Pi:

   ```bash
   git clone https://github.com/s-rakim/hologram-vr-cam.git
   cd hologram-vr-cam
   ./deploy/setup_pi5.sh       # packages, I2C + I2S, HDMI mode, power-off fix, settings, service
   sudo reboot
   ```

3. Check the hardware:
   - `i2cdetect -y 1` shows `68` (IMU) and `36` (UPS fuel gauge)
   - `rpicam-hello --list-cameras` lists the Camera Module 3 Wide
   - `aplay -l` lists `sndrpihifiberry`; `speaker-test -D plughw:CARD=sndrpihifiberry,DEV=0 -c2 -twav` says "front
     left" in the left ear and "front right" in the right one. If they're swapped, swap the amps' SD wiring.
   - the panels light up with the console

Settings are in `/etc/hologram/vr.toml` (a copy of [`config/vr.toml`](../../config/vr.toml)); restart with
`sudo systemctl restart hologram-vr` after editing. Every `python3 -m hologram.vr ...` command below reads that file
too (add `--config FILE` to try another one). Stop the service while you calibrate
(`sudo systemctl stop hologram-vr`) so the commands can use the IMU and displays.

## 7. Calibrate

1. **IMU:** `python3 -m hologram.vr imu-check`. Nod up and pitch should rise; turn left and yaw should rise.
   Otherwise fix `tracking.axis_map`, e.g. `["-y", "x", "z"]`.
2. **Panel orientation:** with no panoramas installed, the helmet shows a grid world with a red post straight ahead
   (green to the right, blue to the left, yellow behind). `python3 -m hologram.vr eye-view` simulates what each eye
   should see through the mirror, for comparison. If one eye's picture is mirrored or upside down, set that
   eye's `reflector.left_flip` / `right_flip` (`[x, y]`). If it's slightly rotated, set that eye's
   `reflector.left_roll_deg` / `right_roll_deg` (degrees; if it gets worse, use the other sign).
3. **Fusion:** the two eyes' grids should merge into one. If they don't, nudge the mirrors (they are still on hot glue)
   until the horizon is level and the red post sits in the same place for both eyes. Then epoxy them.
4. **Distortion:** if straight grid lines still bow, the mirror sits a little off its modelled place. Adjust
   `reflector.mirror_point` / `focus` in small steps (1-2 mm). `python3 -m hologram.vr snapshot --yaw 30` renders the
   pre-warped frame to a PNG you can check on a computer.
5. **Recentre:** hold the action button while looking straight ahead.

## 8. Content

- **360 photos:** 2:1 equirectangular JPEGs (from any 360 camera or phone panorama app) in `~/Pictures/Hologram/360`.
- **Sound for a 360 photo:** put a WAV with the same name next to it (`beach.jpg` + `beach.wav`). 4-channel files are
  treated as first-order ambisonics (AmbiX: W, Y, Z, X with SN3D, which is what 360 cameras and YouTube's spatial-audio
  tools produce); stereo files become two virtual speakers in front of you; mono files a single source ahead. The sound
  is fixed to the scene and follows your head through the ear cups.
- **Photos from the glasses:** copy them to `~/DCIM/Hologram` and use gallery mode.

New files are picked up the next time you switch to that mode; there's no need to restart anything. Files that can't
be read (half-copied, or not really images) are skipped.

## 9. Everyday use

| Button | Tap | Hold |
|---|---|---|
| Mode | next mode: 360 view, gallery, passthrough | 2 s: power off |
| Action | next panorama / photo | recentre the view |
| Volume - / + | ear-cup volume | |

The displays switch off after the helmet has been still for 60 s (put down), and wake when you pick it up or press any
button (that press does nothing else). Without working head tracking they stay on. Battery life is about 4.3-4.8 hours
from four 3500 mAh cells (estimate; see [../battery.md](../battery.md)). It warns at 10 % and shuts down cleanly at 3 %.
Charge through the UPS board's USB-C port with the official 27 W Pi 5 supply.

**Switching on:** after a power-off (mode held for 2 s, or the low-battery shutdown) press the Pi 5's own power button
through the small hole in the rear pod cover. The setup script sets the Pi 5 to switch fully off when it halts, so a
powered-off helmet draws next to nothing. For storage longer than a few weeks, charge it to about half and take one cell
out (or all four).

## Troubleshooting

| Symptom | Check |
|---|---|
| Black panels | The board may not like the forced mode: remove `video=HDMI-A-1:...` from `/boot/firmware/cmdline.txt`, or try `2880x1440@60` without the `M`. Check `gpio=22=op,dh` is in `/boot/firmware/config.txt` (the display board gets power from boot) and the load switch output reads 5 V |
| Picture tears or stutters | Lower `display.render_scale` (e.g. 0.4). Rendering runs on the CPU (numpy): 720 x 720 per eye takes about 14 ms per frame on a desktop CPU core, so expect very roughly 25-40 fps on a Pi 5. A still view isn't re-rendered at all |
| Double image | Mirrors not aligned: see calibration step 3 |
| No sound | `aplay -l` must show `sndrpihifiberry`; check `dtoverlay=hifiberry-dac` in `/boot/firmware/config.txt` and the amp wiring |
| Sound on one side only | That amp's SD voltage selects the wrong channel |
| View drifts sideways | Yaw has no compass: hold the action button to recentre |
