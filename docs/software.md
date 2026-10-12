# Software reference

The repo has three Python packages and a few support folders:

| Folder | What it is | Runs on |
|---|---|---|
| [`hologram/`](../hologram) | Firmware for the Hologram VR Cam glasses | Pi Zero 2 W (or a desktop with mock hardware) |
| [`holomaker/`](../holomaker) | Hologram Maker: stereo photos -> depth -> 3D outputs | Pi 5 or any computer |
| [`cad/`](../cad) | The glasses' 3D model, drawings, BOM and wiring, generated from one spec | Any computer |
| [`config/`](../config) | `hologram.toml`: every glasses setting with its default | |
| [`deploy/`](../deploy) | Pi setup script and systemd service | Pi |
| [`tests/`](../tests) | pytest suite for all three packages | Any computer |

Everything needs only **numpy** at its core. Pillow, pygame, Picamera2, gpiozero, smbus2 and
ifcopenshell are optional and loaded only where needed.

```bash
pip install -e ".[dev]"      # numpy + pytest + ifcopenshell
pytest                       # whole suite
```

---

## `hologram/`: the glasses

Command line: `python -m hologram {run,demo,snapshot,imu-check}`, also installed as `hologram`.

| Command | Does |
|---|---|
| `run [--config F] [--mock] [--window]` | Runs the glasses. `--mock` uses fake hardware; `--window` shows output in a desktop window (SPACE = capture button, T = touch strip, B = low battery, ESC = quit) |
| `demo [--out DIR]` | Headless walk-through with mock hardware: photo, video, mode switch, with preview PNGs |
| `snapshot [--mode panorama\|passthrough] [--yaw D] [--pitch D] [--out F]` | Renders one side-by-side frame to a PNG, for checking optics settings off the device |
| `imu-check` | Prints live yaw and pitch from the real MPU-6050 |

### Modules

| Module | Responsibility | Main names |
|---|---|---|
| `app.py` | Main loop: inputs -> gestures -> capture and display modes; safety shutdowns | `HologramApp`, `Mode` (panorama / passthrough / off), `system_poweroff` |
| `capture.py` | Photo and video capture rules. The privacy LED goes on **before** the encoder starts, and recording is refused if the LED fails. Also enforces the clip-length cap and thermal and storage guards, and muxes mic audio into each clip with ffmpeg | `CaptureController`, `State`, `Refusal`, `Picamera2Backend`, `MockCamera`, `mux_command` |
| `privacy_led.py` | Outward-facing recording LED | `PrivacyLed`, `LedOutput`, `MemoryLed` (test double) |
| `gestures.py` | Raw press/release edges -> tap, double tap, hold | `GestureDetector`, `Gesture` |
| `imu.py` | MPU-6050 I2C driver, axis remapping for a rotated board, and a mock that fakes head motion | `MPU6050`, `MockImu`, `axis_remap`, `ImuSample` |
| `fusion.py` | Madgwick gyro + accelerometer filter; thread-safe tracker with gyro-bias calibration and yaw recentring | `Madgwick`, `HeadTracker` |
| `quaternion.py` | Unit quaternions as `(w, x, y, z)` tuples | `mul`, `rotate`, `to_matrix`, `yaw`, `pitch`, `yaw_quat` |
| `render.py` | Side-by-side stereo renderer. Per-eye sample grids (with barrel pre-distortion) are built once; each frame only rotates rays into a 360° image or gathers camera pixels | `PanoramaRenderer`, `PassthroughRenderer`, `eye_grid`, `stereo_grids`, `grid_world`, `draw_rec_indicator` |
| `display.py` | Output to the HDMI driver (pygame on KMS/DRM), a desktop window, or nowhere | `PygameDisplay`, `NullDisplay` |
| `hardware.py` | Builds the real or mock hardware set from a config | `build_pi`, `build_mock`, `Hardware`, `GpioLed` |
| `config.py` | Typed defaults, overridden by a TOML file; wrong types are rejected | `load_config`, `Config` and its sections |
| `storage.py` | Media folder, file naming, free-space checks | `MediaStore` |
| `thermal.py` | SoC temperature with stop/resume hysteresis | `ThermalGuard`, `soc_temperature` |
| `imageio.py` | Dependency-free PNG writer; Pillow-based loader | `write_png`, `load_image` |

### Configuration

[`config/hologram.toml`](../config/hologram.toml) lists every setting with its default. Sections:
`[pins]` (BCM GPIO numbers, which must match [wiring.md](wiring.md); a test checks this), `[capture]`,
`[display]` (FOV, lens distortion `k1`/`k2`, render scale, start mode, panorama path), `[tracking]`
(I2C bus and address, filter gain, axis map), `[thermal]` and `[power]`.

### Deployment

`deploy/setup_pi.sh` installs packages, enables I2C and I2S (`googlevoicehat-soundcard` overlay),
forces 1920x1080 HDMI and installs `deploy/hologram.service`, which runs
`python3 -m hologram run --config config/hologram.toml` at boot as the invoking user.

---

## `holomaker/`: the Hologram Maker

Command line: `python -m holomaker {demo,stereo,rgbd,capture}`, also installed as `holomaker`. Flags
and hardware are covered in [hologram-machine.md](hologram-machine.md).

Data flow: `stereo pair -> stereo_disparity -> disparity_to_depth -> fill_from_background -> RGB-D ->
{to_points/write_ply, shift_view/view_sweep -> quilt / pepper_ghost / side_by_side / anaglyph,
volume_slices}`.

| Module | Responsibility | Main names |
|---|---|---|
| `camera.py` | Pinhole intrinsics | `Intrinsics.from_fov`, `Intrinsics.scaled` |
| `depth.py` | Block-matching stereo (mean-subtracted SAD over a box window, integral images, sub-pixel parabola fit, left/right consistency and texture checks); disparity <-> metres; background-side hole filling | `stereo_disparity`, `disparity_to_depth`, `depth_to_disparity`, `fill_from_background`, `box_sum`, `to_gray` |
| `pointcloud.py` | RGB-D -> points (X right, Y up, camera looking down -Z); binary PLY read and write | `backproject`, `to_points`, `write_ply`, `read_ply` |
| `views.py` | Depth-image-based rendering: re-render the RGB-D from a sideways-shifted camera with a z-buffer and hole filling | `shift_view`, `view_sweep` |
| `outputs.py` | Display formats | `pepper_ghost`, `quilt`, `quilt_name`, `volume_slices`, `contact_sheet`, `side_by_side`, `anaglyph`, `isolate`, `fit`, `depth_preview` |
| `pipeline.py` | One call from inputs to every output file plus a JSON manifest | `MakerSettings`, `make_from_stereo`, `make_outputs`, `depth_from_stereo` |
| `scene.py` | Synthetic textured scene (wall, box, ball) with exact depth, and its stereo pair | `demo_scene`, `demo_stereo_pair` |
| `capture.py` | Two-camera capture on a Pi 5 through Picamera2 | `capture_pair` |

Conventions: images are `(H, W, 3)` uint8 RGB. Depth is `(H, W)` float32 in metres, with NaN for
unknown. Disparity is in pixels, positive when the right camera sees the point further left.

---

## `cad/`: the glasses model

`cad/spec.py` is the single source of truth: part geometry, materials, BOM, devices, pins and wires.
Every other output is generated from it:

```bash
python -m cad.generate     # IFC4 model, Revit JSON, 4 SVG drawings, docs/bom.md, docs/wiring.md
python -m cad.stl_export   # printable STLs in cad/out/stl (needs ifcopenshell)
```

| Module | Responsibility |
|---|---|
| `spec.py` | Parts (`Part`, `Material`), BOM (`BomLine`), electronics (`Device`, `Wire`, `gpio_of`), overall size (`Envelope`) |
| `geometry.py` | Dependency-free profiles (`rect`, `circle`, `arc`, `poly`) and extruded `Solid`s |
| `ifc_writer.py` | Minimal IFC4 STEP writer with deterministic GUIDs (`build_ifc`, `ifc_guid`) |
| `svg_draw.py` | X-ray isometric, exploded and orthographic sheets with title block (`draw_assembly`, `draw_exploded`, `draw_orthographic`) |
| `schematic.py` | Wiring schematic sheet from `spec.WIRES` (`draw_schematic`) |
| `stl_export.py` | Binary STL writer for the printed parts |
| `generate.py` | Regenerates every output; the tests fail if a generated file is out of date |
| `revit/build_hologram_glasses.py` | pyRevit / RevitPythonShell script that builds a native Generic Model family from `hologram_glasses_model.json` |

---

## Tests

| File | Covers |
|---|---|
| `test_app.py` | Main loop: button and touch gestures to actions, mode cycling, recentring, low-battery shutdown, config file loading |
| `test_capture.py` | LED lit for the whole recording, LED failure blocks recording, clip cap, thermal and storage guards, low battery, file naming, audio mux |
| `test_gestures.py` | Tap, double tap and hold timing |
| `test_tracking.py` | Quaternions, Madgwick convergence, bias calibration, recentring, MPU-6050 driver, axis remap |
| `test_render.py` | Distortion grids, lens shift, panorama orientation, passthrough letterboxing, REC indicator |
| `test_cad.py` | Revit-valid geometry and edge lengths, wearable size, BOM and wiring references, pins vs wiring, generated files up to date, Revit JSON and IronPython 2.7 script, IFC4 validation, STL well-formedness |
| `test_holomaker.py` | Stereo matching against ground truth, depth conversion, hole filling, view synthesis, PLY round trip, pyramid orientation, quilt order, slice partitioning, CLI end to end |
