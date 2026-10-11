# Hologram Cam: build guide

Ray-Ban-style camera glasses around a Seeed Studio XIAO ESP32-S3 Sense. Keep these open while you work:

| Sheet | What it shows |
|-------|---------------|
| [01 Assembly (x-ray)](drawings/01_assembly.svg) | where every module sits in the frame |
| [02 Exploded](drawings/02_exploded.svg) | numbered parts and build order |
| [03 Orthographic](drawings/03_orthographic.svg) | overall size (146 mm wide), lens and bridge sizes |
| [04 Wiring](drawings/04_wiring.svg) | every connection, colour-coded |
| [bom.md](bom.md) / [wiring.md](wiring.md) | parts list and pin table, generated from `cad/products/cam.py` |
| [ble-protocol.md](ble-protocol.md) | what the phone app sends and receives |

> **Safety and privacy.** LiPo cells can catch fire if punctured, shorted or over-discharged. Use a cell with a
> protection PCB, never pierce it, and keep it away from the soldering iron. The firmware stops recording above
> 75 °C chip temperature because the board sits next to your head; don't raise that. Recording people without their
> knowledge is illegal in many places. The privacy LED lights for every recording and the firmware refuses to record
> if it can't switch it on, so keep it visible.

## 0. Tools and parts

**Tools:** fine-tip soldering iron, flux, 30 AWG silicone wire, Kapton tape, multimeter, 1 / 1.5 / 5 mm drill bits,
needle files, CA glue, M1.4 screwdriver, a USB-C cable.

**Order the parts** in [bom.md](bom.md). The XIAO ESP32-S3 *Sense* comes with an OV2640 camera on a short ribbon. For
the endpiece position you want a camera with a **long (~75 mm) FPC**; an OV5640 with autofocus gives 5 MP photos.

## 1. Print

Print from `cad/out/cam/stl/`. The parts are in assembly position, so lay them flat in your slicer. SLS or MJF PA12
nylon is best (strong at 1.5 mm walls); resin works; FDM is fine for a first fit test.

| File | Notes |
|------|-------|
| `frame_front.stl` | print face-down; the 6 mm camera hole and the LED hole are modelled |
| `wire_channel.stl` | glues along the back of the brow; carries the 4 wires between the temples |
| `temple_housing_right.stl` / `_left.stl` | the outer shells of the temples |
| `temple_lid_right.stl` / `_left.stl` | the head-side lids; the right one has the speaker grille |
| `temple_arm_right.stl` / `_left.stl` | ear pieces; glue them into the end of each housing |

**Drill and cut** these after printing; they are not modelled:

| Where (measured back from the frame's rear face) | Opening | For |
|---|---|---|
| Right temple, top, 40 mm | 5 mm hole | capture button |
| Right temple, underside, 62 mm | 9 x 4 mm slot | magnetic charging contacts |
| Right temple, outer wall, 17 mm, just above the centreline | 1 mm hole | microphone (line it up with the mic on the Sense board) |
| Left temple, underside, 64 mm | 4 x 8 mm slot | power slide switch |
| Both temple front walls, and both ends of the wire channel | 5 x 2 mm slots | wires through the hinges |

## 2. Flash and bench-test first

Wire everything on the desk with short leads, exactly as in [wiring.md](wiring.md), before anything goes into the
frame. Faults are far easier to find now than when the temples are closed.

1. Install [PlatformIO](https://platformio.org/install/cli) (or the VS Code extension).
2. Open `firmware/glasses/include/config.h` and **change `BLE_PASSKEY`**: it is the 6-digit code your phone asks for
   when pairing.
3. Flash over USB-C:

   ```bash
   cd firmware/glasses
   pio run -t upload
   pio device monitor          # optional: watch the log (115200 baud)
   ```

   If the upload doesn't start, hold the XIAO's BOOT button while plugging in USB.
4. Format the microSD card as FAT32 and insert it.
5. Check each part:
   - Tap the capture button: a photo beep, and a JPEG appears in `/DCIM` on the card.
   - Hold the button: the LED lights first, then the start sound plays. Tap to stop, then check the `.avi` plays
     (VLC or any player) with sound.
   - Tap the touch pad: 1-4 beeps for the battery level.
   - Phone app (step 6): connect, pair, take a photo from the phone.

## 3. Front frame

1. Press the lenses into the frame grooves, with a drop of CA glue at the corners.
2. Fit the camera from behind the right endpiece so the lens sits in the 6 mm hole, flush with the front face.
   **Square it to the lens openings before the glue sets**; a crooked camera gives crooked videos.
3. Fit the privacy LED and its 2N7002 driver in the left endpiece.
4. Push in the nose pads and screw on the spring hinges.
5. Glue the wire channel along the back of the brow.

## 4. Right temple: electronics

1. Solder wires straight to the XIAO's castellated pads (no headers, so the temple stays 12 mm thick). Every pin is
   in [wiring.md](wiring.md).
2. Lay the XIAO + Sense board against the outer wall with the USB-C port towards the hinge and the mic under its
   1 mm hole. Put the microSD card in now.
3. Fit the amp behind it and the speaker at the back, facing the grille in the lid.
4. Fit the capture button under its hole and the magnetic contacts in the underside slot.
5. Stick the copper tape touch pad inside the outer wall, behind the board, and solder its lead to `D2`.
6. Run the camera FPC through the right hinge to the camera.

## 5. Left temple: battery

1. Fit the LiPo (with its protection PCB) and the slide switch.
2. Solder the battery's `+` through the switch, and its `-`, to the two wires in the brow channel. On the right side
   they go to the XIAO's `BAT+` / `BAT-` pads on the underside. **Check polarity twice before connecting**: the XIAO
   has no reverse-polarity protection on the battery pads.
3. Fit the 200 k / 200 k divider (with 100 nF to GND) from `BAT+` to `D0`, so the firmware can read the battery.

## 6. Harness through the hinges

| Run | Wires |
|-----|-------|
| Right hinge | camera FPC, BAT+, BAT-, LED CTRL |
| Brow wire channel | BAT+, BAT-, LED CTRL (the LED and its driver take power from BAT+ / BAT- at the left end) |
| Left hinge | BAT+ (switched), BAT- |

Leave a ~15 mm service loop at each hinge so the temples fold without pulling on the joints. Check every wire with the
multimeter, then close the lids (2 x M1.4 screws or a bead of hot glue, so you can reopen them).

## 7. Phone app

The app is the single page `phone/index.html`. Web Bluetooth only works over **https**, so publish it once:

1. Merge to `main` and enable *Settings > Pages > Build and deployment > Source: GitHub Actions*. The workflow in
   `.github/workflows/phone-app.yml` publishes `phone/` on every change.
2. Open the page on your phone: **Chrome** on Android, or the free **Bluefy** browser on iPhone (Safari has no Web
   Bluetooth). *Add to home screen* makes it look like an app.
3. Tap **Connect**, pick *Hologram Cam*, and enter your passkey when asked. The phone remembers the pairing.

The app sets the glasses' clock on connect, so file names get the real date (`HVR_20261011_143012.avi`).

## 8. Getting your files

- **Wi-Fi sync:** double-tap the touch pad (or tap *Wi-Fi sync* in the app). The glasses start a hotspot called
  `HologramCam-XXXX` with a fresh random password, and the app shows both. Join it, open `http://192.168.4.1`, and you
  can download or delete photos and videos. Double-tap again to turn it off; it uses a lot of power.
- **Card reader:** files are in `/DCIM` on the card.
- **On the VR helmet:** copy photos to `~/DCIM/Hologram` on the helmet's Pi and view them in gallery mode on a big
  virtual screen.

**Firmware updates** go through the same Wi-Fi page: build with `pio run` and upload
`firmware/glasses/.pio/build/xiao_esp32s3/firmware.bin` under *Firmware update*.

## 9. Everyday use

| Control | Action |
|---|---|
| Capture button: tap | Photo, or stop recording |
| Capture button: hold 0.6 s | Start recording (the LED lights first) |
| Touch pad: tap | Battery level: 1-4 beeps |
| Touch pad: double tap | Wi-Fi sync on/off |
| Touch pad: hold 3 s | Power off (deep sleep). The capture button wakes it |
| Slide switch | Hard off for storage or travel |

From the phone you can also change the resolution (VGA to 1600 x 1200), JPEG quality, segment length and an optional
maximum recording time, and make the glasses beep so you can find them.

**Long recordings:** video is written in segments (5 minutes by default), each its own AVI file, so you can record for
as long as the battery and card allow. A 32 GB card holds very roughly 7-14 hours at 720p, depending on quality and how
much is moving in the scene. The app shows the minutes left, worked out from your actual bitrate. Charging through the magnetic contacts while recording works,
so a small power bank in a pocket extends recording indefinitely.

**Battery:** about 4-5 hours of mixed use (a 10-minute video every hour plus photos, connected to the phone), or about
1.2-1.5 hours of continuous recording. These are estimates; see [../battery.md](../battery.md).

## Troubleshooting

| Symptom | Check |
|---|---|
| Phone can't find the glasses | Is Bluetooth on, and are you in Chrome (Android) or Bluefy (iOS)? Tap the button to wake them |
| Pairing fails | The passkey is the one in `config.h` when you flashed. Forget the device in the phone's Bluetooth settings and retry |
| "refused: privacy_led_fault" | The LED driver isn't working, so the firmware won't record. Check the LED wiring and the 2N7002 |
| "refused: storage_full" | Card missing, not FAT32, or full (it keeps 64 MB free) |
| "refused: too_hot" / "low_battery" | Let it cool down below 65 °C / charge it |
| Video stops after a while | It stopped because of battery, heat or storage; the app shows the reason |
| Choppy video | Lower the resolution or quality in settings; use a fast (U3/A1) card |
