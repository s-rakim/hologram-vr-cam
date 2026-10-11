// Hologram Cam - build-time settings. Most of these can also be changed from the phone app.
#pragma once

// ---- Change these before flashing your own glasses ----
#define BLE_DEVICE_NAME      "Hologram Cam"
#define BLE_PASSKEY          246810      // 6-digit pairing code your phone asks for (change it!)
#define WIFI_SSID_PREFIX     "HologramCam-"

// ---- Capture ----
#define DEFAULT_SEGMENT_S    300         // long recordings are split into files of this many seconds
#define DEFAULT_MAX_REC_S    0           // 0 = record until stopped (or battery / heat / storage stops it)
#define DEFAULT_JPEG_QUALITY 12          // 0-63, lower = better quality and bigger files
#define AUDIO_RATE_HZ        16000       // PDM mic, mono 16-bit PCM in the AVI
#define MIN_FREE_MB          64
#define CAMERA_IDLE_OFF_MS   20000       // power the camera down this long after the last capture

// ---- Power ----
#define BATTERY_WARN_PCT     10
#define BATTERY_OFF_PCT      4           // save the clip and power off
#define TEMP_STOP_C          75.0f       // ESP32-S3 die temperature
#define TEMP_RESUME_C        65.0f

// ---- Controls (ms) ----
#define BUTTON_HOLD_MS       600
#define TOUCH_HOLD_MS        3000
#define TOUCH_DOUBLE_MS      350

// ---- BLE GATT (also used by phone/index.html) ----
#define BLE_SERVICE_UUID     "7a1e0001-5c3b-4d8e-9f21-0c4a6b8d2e10"
#define BLE_COMMAND_UUID     "7a1e0002-5c3b-4d8e-9f21-0c4a6b8d2e10"
#define BLE_STATUS_UUID      "7a1e0003-5c3b-4d8e-9f21-0c4a6b8d2e10"
#define BLE_EVENT_UUID       "7a1e0004-5c3b-4d8e-9f21-0c4a6b8d2e10"
