# Research: building a device that outputs 3D visual data

*Malcolm Opondo, October 2026*

**Question.** What is the most practical way to build a device that captures the world and outputs 3D
visual data, with depth in the data itself rather than only a flat picture, and plays it back on
displays that look 3D? This repo's starting point is the Hologram VR Cam glasses: one OV5647 camera, two
micro-OLEDs and a Pi Zero 2 W. It already outputs stereo to the wearer, but it captures only 2D.

**Short answer.**

1. **Capture:** two synchronised cameras on a Raspberry Pi 5 (stereo), or a depth camera with on-board
   matching (OAK-D Lite). Add an AI accelerator running a monocular depth model when video-rate depth
   matters more than metric accuracy.
2. **Intermediate format:** an **RGB-D image** (colour + metric depth). Point clouds, multi-view
   images and depth slices can all be derived from it.
3. **Outputs:** PLY point clouds for 3D tools; a **quilt** for light field displays; a four-sided
   layout for a **Pepper's-ghost pyramid**; depth **slices** for swept-volume displays; and side-by-side
   stereo for headsets, including these glasses.

This repo builds exactly that pipeline: [`holomaker`](../../holomaker), with hardware choices in
[hologram-machine.md](../hologram-machine.md).

---

## 1. Capturing depth

### 1.1 Passive stereo (two cameras)

Two cameras a known distance apart see near objects shift more than far ones. Depth is
`Z = f * B / d` (focal length in pixels x baseline / disparity).

* **Raspberry Pi 5** has two CSI camera ports. Picamera2 can open both, but in separate processes, so
  **sensor framing and auto-exposure are not synchronised** [R1][R2]. Stereo needs capture starts within
  about 50 µs, matched exposure and white balance, a rigid mount and calibration [R3]. libcamera has a
  software sync mode in which one camera broadcasts timing and the others adjust their frame durations
  [R1]. I didn't confirm Picamera2 support for it; test it on your own hardware.
* **Arducam AR0234 x2 stereo kit**: synchronised colour global-shutter pair for Pi 5/4B. Modes include
  2560x720 at 94 fps and 3840x1200 at 38 fps. Adjustable baseline, $259.99. Needs the current Pi OS and
  the `arducam-pivariety` driver [R4]. Arducam also sells a 2x OV2311 mono global-shutter module [R5].
* **Compute:** no published StereoSGBM benchmark for the Pi 5 turned up [R6]. On Jetson TX1, SGBM ran at
  about 11.8 fps on quarter-resolution data and was the slowest method tested [R6]. Plan for
  seconds-per-frame numpy/OpenCV matching on a Pi for stills, or offload the matching.

### 1.2 Stereo cameras with on-board depth

* **Luxonis OAK-D Lite**: 75 mm baseline, ideal range 40 cm-8 m, vendor-stated error under 2% from
  0.4-3 m, under 4% from 3-6 m and under 6% from 6-8 m. OV7251 640x480 stereo pair at up to 120 fps,
  13 MP IMX214 colour camera, RVC2 with 4 TOPS (1.4 for neural nets), up to 5 W over one USB-C. Retail
  prices range from $123 (retired listings) to $269 (Luxonis store). Sources disagree on whether
  current units include an IMU [R7].
* **Intel RealSense**: spun out of Intel as a standalone company in July 2025 with a $50 M Series A
  [R8]. Cognex agreed in September 2026 to acquire it for about $500 M, expected to close in Q4 2026 [R9].
  The D435 is still listed; the newer D555 shipped in late 2025 [R8]. Usable, but the platform's
  direction depends on the acquisition.

### 1.3 Time of flight (active)

* **Arducam ToF for Raspberry Pi**: 240x180 depth at 30 fps (4-phase), 2 m near and 4 m far modes,
  940 nm VCSEL, 70° diagonal, $30 Kickstarter / $50 MSRP [R10]. CNX Software concluded the resolution is
  too low for 3D scanning but fine for robotics [R11].
* **ST VL53L8CX**: 8x8 zones, up to 4 m in the dark (about 2.8 m in 5000 lux), 65° diagonal,
  6.4 x 3.0 x 1.75 mm package, 1.6 mW in low-power mode [R12][R13]. Small enough for glasses, but far too
  coarse for imagery. Use it as a metric anchor for AI depth.

### 1.4 AI (monocular) depth

* **Depth Anything V2 Small**: the Small checkpoint is **Apache-2.0**; Base, Large and Giant are
  CC-BY-NC-4.0 [R14]. That matters for anything you might sell.
* A ready **Hailo-8** build exists (Seeed, CM5 + Hailo-8): 224x224 input, 24.2 M parameters, about
  35 MB [R15]. No FPS figure is published. On Luxonis RVC4, INT8 runs at about 12.6 inferences/s at
  560x420 and about 96/s at 336x252 [R16].
* **Raspberry Pi AI HAT+ 2**: Hailo-10H, 40 TOPS (INT4), 8 GB on-board RAM, PCIe to the Pi 5,
  US$130 [R17]. One retailer says vision performance is similar to the 26 TOPS AI HAT+ ($110) [R17].
* Caveat: the output is **relative** depth. Scale it with one known measurement (ToF, stereo or a tape
  measure) before treating it as metres.

### 1.5 What shipping smart glasses do

None of the camera glasses checked record stereo or spatial video. The **XREAL Eye** is a single 12 MP
camera (1080p60) [R18]. **Snap Spectacles 5** have two RGB cameras but record 10-second clips to a phone,
with stereo only on the display side [R19]. The 2026 **Snap Specs** ($2,195, announced at AWE in June
2026) list 2 RGB + 2 IR cameras, but nothing confirms stereo capture [R19][R20]. A stereo-capture pair
of glasses would be unusual.

---

## 2. Formats for 3D visual data

| Format | What it holds | Tooling | Notes |
|---|---|---|---|
| **RGB-D** (image + depth) | One viewpoint with per-pixel depth | Anything with numpy | Best working format; everything below is derived from it |
| **PLY point cloud** | Coloured 3D points | MeshLab, CloudCompare, Blender, three.js | Simple, uncompressed |
| **Draco** | Compressed meshes and point clouds | Google, Apache-2.0, WASM decoders in three.js | Static assets; repo activity slowed (last push Oct 2024) [R21] |
| **MPEG V-PCC** (ISO/IEC 23090-5) | Dynamic point clouds as 3 video streams (geometry, occupancy, texture) | Real-time decode shown on mobile hardware | Uses existing video decoders [R22] |
| **MPEG G-PCC** | Point clouds, geometry-based | Reference software | Not video-based [R22] |
| **Side-by-side stereo + `st3d`** | Two views | YouTube, VR players | Inject with Spatial Media Metadata Injector (`-s left-right`) or FFmpeg; some editors strip it [R23] |
| **MV-HEVC** | Two views in one HEVC stream | Apple Compressor (Apple silicon), MainConcept SDK, NVIDIA Video Codec SDK 13 | FFmpeg 7.1 **decodes** only; no mature open-source encoder found [R24] |
| **Light field quilt** | Grid of N views | Looking Glass software | Layout encoded in the file name |
| **3D Gaussian splats** | View-dependent radiance primitives | Research code | Streaming dynamic splats is 2025-26 research (SwinGS, CAGS, SAGA, InterGS); no standard format yet [R25] |

A V-PCC-style comparison study suggests choosing the codec per situation: V-PCC, G-PCC or Draco,
depending on bandwidth and decoder power [R22].

---

## 3. Displaying 3D

### 3.1 Stereo head-mounted displays

The Hologram VR Cam glasses already display side-by-side stereo. Feeding them true stereo or RGB-D
content (rather than the same mono frame to both eyes) is the cheapest way to show this project's 3D
output.

### 3.2 Light field displays

**Looking Glass 27" 5K** (announced April 2025): 5120x2880 panel, 45-100 simultaneous views over 53°,
about 2.5 cm thick, 40 cm virtual depth, $8,000 pre-order and $10,000 after. The 16" was about $4,000
on promotion, and the **Looking Glass Go** costs $300 [R26]. A newer "Hololuminescent" (HLD) line
reportedly starts at $1,500, but I found only one source for that [R27].

### 3.3 Volumetric (swept-surface) displays

Swept-surface displays rely on persistence of vision to merge a series of slices projected onto a
moving surface [R28]. **Voxon VX1**: 18 x 18 x 8 cm volume, up to 500 million voxels/s, high-speed DLP
synced to a reciprocating screen. Content comes from Unity or OBJ/STL/DICOM [R29]. A Voxon patent
describes a screen reciprocating at about 20 Hz on a resonant mount, driven by electromagnetic coils or
bass shakers [R30]. DIY builds include a DLP projector with the colour wheel removed plus a sub-1 ms LCD
shutter (Mac70), a spinning 16x16 LED panel with an ESP32 on the rotor, and a membrane display [R31].
The binding constraint is frame rate, since every depth position needs its own refresh [R31].

### 3.4 Pepper's-ghost pyramids

Not a separate web search; this comes from well-known optics. A clear pyramid with 45° faces stands
point-down on a screen showing four rotated copies of the subject. Each face reflects one copy into the
pyramid's centre. It is cheap and striking, but needs a black background and a dim room. The geometry
is worked out in [hologram-machine.md](../hologram-machine.md#1-peppers-ghost-pyramid-build-this-first).

### 3.5 Computer-generated holography

Phase-only SLMs are preferred because they don't absorb light, and each SLM pixel contributes to many
image points [R32]. Coherent lasers cause speckle; LEDs reduce it but blur the image [R32]. A June 2025
paper from the University of the Andes demonstrates CGH on a **low-cost** phase-only SLM [R33]. Fast
SLMs offer very coarse phase steps, which needs special optimisation (from a 2025 preprint
the search surfaced; I didn't keep its link). A 2025 research bench used a
Jasper JD7714 SLM (2400x4094, 3.74 µm pitch) with a three-line laser [R34]. This is a research route,
not a weekend build.

---

## 4. Recommendation for this project

| Step | Choice | Why |
|---|---|---|
| Prototype | Pi 5 + 2x Camera Module 3, 63 mm bar | Cheapest; numpy stereo is enough for stills |
| Moving subjects | Arducam AR0234 stereo kit, or OAK-D Lite | Hardware sync / on-device depth |
| Video-rate depth | AI HAT+ 2 + Depth Anything V2 Small (Apache-2.0) | Single camera, scale with ToF |
| First display | Pepper's-ghost pyramid on a tablet | ~$5, instantly reads as a "hologram" |
| Best display | Looking Glass Go ($300) via quilt | True parallax, multiple viewers |
| Stretch | DIY swept-volume display | Real volume; mechanical and frame-rate heavy |
| Glasses tie-in | SBS output to the Hologram VR Cam glasses | Already supported |

**Open questions to test on hardware**

1. Whether libcamera's software camera sync is good enough on a Pi 5 for moving subjects.
2. Real Hailo-8/10H FPS for Depth Anything V2 Small, including pre- and post-processing.
3. Which quilt layouts and view counts each Looking Glass model wants (check its documentation).
4. Whether the OAK-D Lite currently ships with an IMU (sources conflict).

---

## Sources

* [R1] Raspberry Pi documentation PR on camera sync — https://github.com/raspberrypi/documentation/pull/4049/files
* [R2] Tom's Hardware, dual cameras on Pi 5 — https://www.tomshardware.com/raspberry-pi/how-to-use-dual-cameras-on-the-raspberry-pi-5 ; Little Bird guide — https://littlebirdelectronics.com.au/projects/how-to-connect-two-cameras-to-the-raspberry-pi-5
* [R3] Open Robotics Discourse, Raspberry Pi 5 stereo vision — https://discourse.openrobotics.org/t/raspberry-pi-5-stereo-vision/45187 ; StereoPi forum — https://forum.stereopi.com/viewtopic.php?p=3230
* [R4] Arducam AR0234 stereo kit — https://www.arducam.com/product/arducam-2-3mp2-ar0234-color-global-shutter-synchronized-stereo-camera-bundle-kit-for-raspberry-pi/ ; https://www.arducam.com/?p=101194
* [R5] Arducam stereo for Raspberry Pi — https://www.arducam.com/blog/?p=13337 ; OV2311 listing — https://stgaws.robu.in/?p=869365
* [R6] StereoPi C++ vs Python — https://stereopi.com/node/131 ; StereoPi depth map tutorial — https://www.stereopi.com/node/130 ; Jetson SGBM tables — https://jivp-eurasipjournals.springeropen.com/articles/10.1186/s13640-018-0253-2/tables/5
* [R7] Luxonis OAK-D Lite docs — https://docs.luxonis.com/projects/hardware/en/latest/pages/DM9095 ; store — https://shop.luxonis.com/products/oak-d-lite-1 ; SparkFun — https://www.sparkfun.com/luxonis-oak-d-lite.html ; PyImageSearch — https://pyimagesearch.com/?p=35009
* [R8] RealSense (Wikipedia) — https://en.wikipedia.org/wiki/RealSense ; RealSense support forum, D555 — https://support.realsenseai.com/hc/en-us/community/posts/42475759693459-D555-release-and-SDK
* [R9] Robotics 24/7, Cognex acquires RealSense — https://www.robotics247.com/article/cognex-acquires-realsense-for-500m ; Cognex release — https://s2.q4cdn.com/773500753/files/doc_news/Cognex-to-Acquire-RealSense-Expanding-Machine-Vision-Leadership-into-High-Growth-Robotic-Perception-Market-2026.pdf
* [R10] Arducam ToF documentation — https://docs.arducam.com/Raspberry-Pi-Camera/Tof-camera/TOF-Camera/
* [R11] CNX Software on the Arducam ToF — https://www.cnx-software.com/2022/09/01/arducam-tof-camera-adds-depth-sensing-to-raspberry-pi/
* [R12] ST VL53L8CX — https://www.st.com/en/product/vl53l8cx ; datasheet — https://www.st.com/resource/en/datasheet/vl53l8cx.pdf
* [R13] Pololu VL53L8CX carrier — https://pololu.com/product/3419 ; ST community release — https://community.st.com/other-hardware-and-tools-166/next-generation-multizone-time-of-flight-sensor-boosts-ranging-performance-and-power-saving-135631
* [R14] Depth Anything V2 — https://github.com/DepthAnything/Depth-Anything-V2
* [R15] Seeed SenseCraft, Depth Anything V2 ViT-S on Hailo — https://sensecraft.seeed.cc/ai-lab/en/models/depth_anything_v2_vits
* [R16] Luxonis model zoo, Depth Anything V2 — https://models.luxonis.com/luxonis/depth-anything-v2/aim_DJHwf6Qjh12Rb8f962aw7x?backTo=%2F
* [R17] Raspberry Pi AI HAT+ 2 — https://tecnoblog.net/noticias/raspberry-pi-anuncia-placa-ai-hat-2-com-40-tops-para-ia-preco-e-alto/ ; https://buyzero.de/en/products/raspberry-pi-ai-hat-2-hailo-10h-ki-beschleuniger-8-gb-ram
* [R18] XREAL Eye — https://www.bestbuy.ca/en-ca/product/xreal-eye-a-add-on-camera-for-xreal-one-series-glasses/19831800 ; https://www.currys.co.uk/products/xreal-eye-smart-glasses-module-12-mp-camera-black-10300962.html
* [R19] Spectacles (Wikipedia) — https://en.wikipedia.org/wiki/Spectacles_(product)
* [R20] Snap Specs tracker — https://idevice.com/smart-glasses/snap-spectacles/roadmap ; Reality Atlas — https://www.reality-atlas.com/blog/best-smart-glasses-companies
* [R21] Google Draco — https://google.github.io/draco/ ; CNX Software — https://www.cnx-software.com/2017/01/14/google-introduces-draco-open-source-3d-mesh-compression-tool/
* [R22] ITU Journal, point cloud codec selection for streaming — https://itu.int/pub/S-JNL-VOL4.ISSUE4-2023-A42 ; IBC, real-time V-PCC decoding — https://ibc.org/real-time-decoding-and-ar-playback-of-the-emerging-mpeg-video-based-point-cloud-compression-standard/5062.article ; SMPTE V-PCC evaluation — https://journal.smpte.org/periodicals/SMPTE%20Motion%20Imaging%20Journal/130/4/15/
* [R23] YouTube help, 3D video — https://support.google.com/youtube/answer/7278886 ; Spatial Media tools — https://sourceforge.net/mirror/spatial-media/ ; Eric Cheng — https://www.echeng.com/journal/how-to-upload-3d-180-vr-video-to-facebook
* [R24] MainConcept MV-HEVC — https://mainconcept.com/mv-hevc ; Bitmovin — https://bitmovin.com/blog/mv-hevc-encoding ; FFmpeg 7.1 — https://linuxiac.com/ffmpeg-7-1-promises-major-improvements-in-video-processing/ ; FOSDEM 2025 multiview decoding — https://fosdem.org/schedule/event/fosdem-2025-6023-multiview-decoding-in-libavcodec-and-ffmpeg-cli ; Apple Compressor — https://support.apple.com/guide/compressor/cpsr9b545a4e/mac ; Doom9 — https://forum.doom9.org/archive/index.php/t-185127.html
* [R25] Adaptive 3DGS streaming — https://arxiv.org/abs/2507.14432v1 ; https://arxiv.org/pdf/2507.14454 ; CAGS — https://radiancefields.com/papers/cags-color-adaptive-volumetric-video-streaming-with-dynamic-3d-gaussian-splatting ; SwinGS — https://radiancefields.com/papers/swings-sliding-window-gaussian-splatting-for-volumetric-video-streaming-with-arbitrary-length ; SAGA — https://radiancefields.com/papers/gaussian-splatting-based-volumetric-video-compression-with-sparse-4d-anchors
* [R26] Hardware.com.br on the Looking Glass 27" — https://www.hardware.com.br/hardware/monitor-3d-quase-60-mil-mostra-imagens-saltando-tela-sem-precisar-oculos/ ; Mezha — https://mezha.ua/en/news/looking-glass-predstavila-27-dyuymoviy-5k-3d-monitor-dlya-yakogo-ne-potribni-okulyari-301300/amp/ ; 3DNews, Looking Glass Go — https://3dnews.ru/1109192/looking-glass-predstavila-kompaktniy-golograficheskiy-6dyuymoviy-displey-go-za-300/print
* [R27] ITC.ua on Looking Glass HLD — https://itc.ua/news/looking-glass-predstavlyaet-gololyumynestsentnye-dyspley-hld-obemnoe-yzobrazhenye-bez-otslezhyvanyya-vzglyada-ot-1500/
* [R28] Volumetric display (Wikipedia) — https://en.wikipedia.org/wiki/Volumetric_display
* [R29] Laser Focus World, Voxiebox — https://laserfocusworld.com/detectors-imaging/article/16558067/voxiebox-3d-hologram-viewable-without-special-glasses-or-headsets ; Voxon Z3D — https://www.retrorefurbs.com/voxon-photonics-releases-the-z3d-volumetric-display-home-arcade-machine/
* [R30] US10401636B2, Volumetric 3D display — https://patents.google.com/patent/US10401636 ; Voxon patents — https://patents.justia.com/assignee/voxon-co
* [R31] Hackster, DIY volumetric display under $50 — https://www.hackster.io/news/build-your-own-3d-volumetric-display-for-under-50-9709a9b0a892 ; Arduino blog — https://blog.arduino.cc/2023/06/19/this-star-wars-inspired-display-shows-volumetric-objects-in-3d-space/ ; Hackster — https://hackster.io/news/diy-volumetric-display-produces-amazing-3d-visuals-e7b505127556 ; survey of alternative displays — https://blair-neal.gitbook.io/survey-of-alternative-displays/alternative-displays/volumetric
* [R32] US patent 9715215, 2D/3D holographic display system — https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/9715215
* [R33] Universidad de los Andes, CGH with a low-cost phase-only SLM — https://opticacuantica.uniandes.edu.co/images/documents/teaching/proy_exp/arias.pdf
* [R34] Complex-valued 2D Gaussian representation for CGH — https://arxiv.org/pdf/2511.15022
