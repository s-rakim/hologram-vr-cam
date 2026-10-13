# Battery: how both devices reach 4 hours

The target was **4 hours** for each device. These are estimates from published component figures, not measurements
of a finished build. Measure yours with a USB power meter (glasses) or the UPS board's fuel gauge (helmet) and adjust.

## Hologram Cam (glasses)

**Battery:** one 701845 LiPo, nominally ~400 mAh at 3.7 V = **1.48 Wh**. The firmware stops at 4 % and the cell's last
part of the curve is hard to use, so count on about **1.2 Wh**. Pouch cells often deliver less than the label says;
check yours.

| State | Draw (estimate) | Basis |
|---|---|---|
| Recording video + sound to microSD | ~0.75-1.0 W | Seeed lists ~154-212 mA at 3.8 V for camera streaming, plus ~54 mA for mic + SD writing |
| Idle, connected to the phone, camera powered down, CPU at 80 MHz | ~0.1-0.2 W | Seeed lists ~56 mA in modem sleep with camera and card fitted; the firmware powers the camera off after 20 s |
| Power off (deep sleep, wakes on the button) | ~0.015 W | ~4 mA deep-sleep figure for the board |
| Wi-Fi sync on | ~0.5-0.8 W | ESP32-S3 soft AP; only while you copy files |

**What that gives:**

| Use | Runtime |
|---|---|
| **Mixed: a 10-minute video every hour, some photos, phone connected** | **about 4-5 hours** |
| Continuous recording | about 1.2-1.5 hours |
| Standby, connected | 6-12 hours |

**Why it reaches 4 h mixed:** the camera is powered down when it isn't capturing (it is the biggest load); the CPU
drops to 80 MHz when idle; the amp is switched off between sounds; and BLE, not Wi-Fi, carries the phone link.

**Recording longer than the battery:** the magnetic charging contacts work while recording, so a small power bank in a
pocket (USB to the magnetic cable) keeps a recording going for as long as the card has space. A 32 GB card holds very
roughly 7-14 hours of 720p.

## Hologram VR (helmet)

**Battery:** four 18650 cells in parallel on the UPS board: 4 x 3500 mAh x 3.6 V = **50.4 Wh**. After the board's boost
conversion to 5 V (~90 %) and the 3 % shutdown reserve, about **43 Wh** reaches the Pi.

| Load | Draw (estimate) | Basis |
|---|---|---|
| Raspberry Pi 5 (4 GB), rendering on the CPU at 30-60 fps | ~5.5-7 W | ~3.3 W idle (4 GB board), ~6 W at full load in published tests |
| Dual 2.9in LCDs + driver board (backlights on) | ~2.5-3.5 W | no datasheet found; typical for two small VR LCDs with backlight boost |
| Two MAX98357A amps + 40 mm drivers at listening level | ~0.2-0.5 W | class-D amps, low volume inside closed ear cups |
| IMU, fuel gauge | < 0.05 W | |
| Camera Module 3 (passthrough mode only) | ~1 W | only powered in passthrough |

| Use | Average draw | Runtime |
|---|---|---|
| 360 photos with sound (typical) | ~9-10 W | **about 4.3-4.8 hours** |
| Passthrough most of the time | ~10.5-11.5 W | about 3.7-4.1 hours |
| Put down (displays off, idle) | ~3.5 W | ~12 hours |
| Powered off (Pi 5 set to switch off fully on halt) | ~0.01 W + the UPS board's own standby | weeks |

**What keeps it above 4 h:**

- **Use 3500 mAh cells** (Samsung 35E, LG MJ1 or similar). 2500 mAh "high-drain" cells give only ~3 hours.
- **Render on motion:** a still view is not re-rendered, which saves CPU (and heat) whenever you hold your head still.
- **Sleep when put down:** after 60 s without movement the load switch cuts power to the display board, the
  passthrough camera stops, and the scene sound pauses.
- **Render scale:** the Pi renders 720 x 720 per eye and the GPU scales it up. `display.render_scale = 0.4` saves CPU
  power at some sharpness.
- **Thermal throttle:** above 80 °C the frame rate halves, which also cuts power.
- **Off means off:** by default a halted Pi 5 keeps drawing ~1.2-1.6 W, which would drain the pack in about a day
  after a power-off. `deploy/setup_pi5.sh` sets `POWER_OFF_ON_HALT=1` (and `WAKE_ON_GPIO=0`) in the Pi 5's EEPROM,
  as in Jeff Geerling's article below; the Pi's power button turns it back on.

**More capacity:** a UPS board with 21700 cells (~4500-5000 mAh each) would give ~6 hours, but needs a deeper rear pod
(edit `_pod_box` and the cell geometry in `cad/products/vr.py`).

## Sources

- Seeed Studio XIAO ESP32S3 Sense power figures, as published by resellers:
  [The Pi Hut](https://thepihut.com/collections/seeed/products/seeed-studio-xiao-esp32s3-sense),
  [Elektor](https://elektor.com/products/seeed-studio-xiao-esp32s3-sense),
  [Ameridroid](https://ameridroid.com/products/xiao-esp32-s3-sense)
- Raspberry Pi 5 idle power by board revision:
  [Jeff Geerling, "New 2GB Pi 5 has 33% smaller die, 30% idle power savings"](https://www.jeffgeerling.com/blog/2024/new-2gb-pi-5-has-33-smaller-die-30-idle-power-savings/),
  [Electromaker summary](https://www.electromaker.io/blog/article/why-the-raspberry-pi-5-2gb-is-ideal-for-low-power-projects)
- Pi 5 power while shut down, and the fix:
  [Jeff Geerling, "Reducing Raspberry Pi 5's power consumption by 140x"](https://www.jeffgeerling.com/blog/2023/reducing-raspberry-pi-5s-power-consumption-140x/)
- Geekworm X1202 UPS board: [product page](https://geekworm.com/collections/raspberry-pi/products/x1202)
