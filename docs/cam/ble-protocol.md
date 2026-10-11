# Hologram Cam: phone protocol (Bluetooth LE)

The glasses are a BLE peripheral named **Hologram Cam** with one GATT service. The phone app
([`phone/index.html`](../../phone/index.html)) uses it through Web Bluetooth, but any BLE app can (nRF Connect is
handy for testing). The source of truth is `firmware/glasses/lib/core/src/protocol.cpp`, and the host tests in
`firmware/glasses/test/host/core_tests.cpp` exercise it.

| Characteristic | UUID | Properties |
|---|---|---|
| Service | `7a1e0001-5c3b-4d8e-9f21-0c4a6b8d2e10` | |
| Command | `7a1e0002-5c3b-4d8e-9f21-0c4a6b8d2e10` | write (encrypted) |
| Status | `7a1e0003-5c3b-4d8e-9f21-0c4a6b8d2e10` | read + notify (encrypted): JSON, every 1 s while recording, every 3 s otherwise |
| Event | `7a1e0004-5c3b-4d8e-9f21-0c4a6b8d2e10` | notify (encrypted): JSON, when something happens |

**Security:** characteristics need an encrypted, authenticated link: LE Secure Connections with bonding and MITM
protection. The glasses show no screen, so they use a fixed 6-digit passkey (`BLE_PASSKEY` in
`firmware/glasses/include/config.h`); change it before you flash. The MTU is negotiated up to 517 bytes so a status
fits in one notification.

## Commands

UTF-8 text written to the command characteristic:

| Command | Effect |
|---|---|
| `photo` | Take a photo |
| `record start` / `record stop` / `record toggle` | Video (the LED lights before recording starts) |
| `wifi on` / `wifi off` | Wi-Fi sync hotspot + web page |
| `find` | Play a loud beep pattern |
| `off` | Power off (deep sleep; the capture button wakes it) |
| `time <unix seconds>` | Set the clock, used for file names. The app sends it on connect |
| `set res <vga\|svga\|hd\|uxga>` | 640x480, 800x600, 1280x720 (`hd`, also accepts `720p`), 1600x1200 |
| `set quality <4-63>` | JPEG quality, lower = better and bigger |
| `set segment <30-1800>` | Seconds per video file |
| `set maxrec <0-86400>` | Stop recording after this many seconds; 0 = no limit |
| `status` | Send a status notification now |

Settings are saved in flash and survive power-off. An unknown command answers with an `error` event.

## Status

```json
{"rec":true,"t":754,"seg":3,"bat":71,"v":3.92,"chg":false,"free_mb":28410,"left_min":610,
 "photos":42,"videos":7,"res":"hd","q":12,"seg_s":300,"maxrec":0,"fps":12.4,"temp":51,
 "clock":true,"wifi":false,"ver":"1.0.0"}
```

| Key | Meaning |
|---|---|
| `rec`, `t`, `seg` | recording now; seconds recorded; current segment number |
| `bat`, `v`, `chg` | battery percent and volts; on the charger |
| `free_mb`, `left_min` | free card space; recording minutes that fit at the current bitrate |
| `photos`, `videos` | files on the card |
| `res`, `q`, `seg_s`, `maxrec` | current settings |
| `fps`, `temp` | measured recording frame rate; chip temperature in °C |
| `clock` | the clock has been set (otherwise files are numbered instead of dated) |
| `wifi` (+ `ssid`, `pass`, `ip`) | Wi-Fi sync is on, and how to join it |
| `ver` | firmware version |

## Events

`{"ev":"<name>","detail":"<detail>"}`

| Event | Detail |
|---|---|
| `photo` | file path |
| `recording` | file path of the first segment |
| `segment` | file path of the next segment (long recordings) |
| `stopped` | why: `user`, `max_length`, `low_battery`, `too_hot`, `storage_full`, `error`, `shutdown` |
| `refused` | why a capture was refused: `low_battery`, `too_hot`, `storage_full`, `privacy_led_fault`, `camera_error` |
| `battery_low` | battery at 10 % |
| `battery_empty` | battery at 4 %: the recording is saved and the glasses power off |
| `power_off` | going to sleep |
| `error` | e.g. `unknown command` |
