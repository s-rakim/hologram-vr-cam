// Hologram Cam - pin map for the Seeed Studio XIAO ESP32S3 Sense.
// Must match the wiring in cad/products/cam.py (tests/test_firmware.py checks it).
#pragma once

// Header pins (GPIO numbers)
#define PIN_VBAT_SENSE   1    // D0 / A0: 200k/200k divider from BAT+
#define PIN_BUTTON       2    // D1: capture button to GND, internal pull-up (also wakes from deep sleep)
#define PIN_TOUCH        3    // D2: copper touch pad (touch channel 3)
#define PIN_PRIVACY_LED  4    // D3: 2N7002 gate driving the front LED
#define PIN_I2S_BCLK     5    // D4: MAX98357A BCLK
#define PIN_I2S_LRC      6    // D5: MAX98357A LRC
#define PIN_I2S_DOUT     43   // D6: MAX98357A DIN
#define PIN_AMP_SD       44   // D7: MAX98357A SD (high = on, left channel)

// Wired on the Sense expansion board
#define PIN_SD_CS        21
#define PIN_SD_SCK       7
#define PIN_SD_MISO      8
#define PIN_SD_MOSI      9
#define PIN_MIC_CLK      42   // PDM microphone
#define PIN_MIC_DATA     41

// Camera (DVP) on the Sense expansion board
#define CAM_PIN_PWDN     -1
#define CAM_PIN_RESET    -1
#define CAM_PIN_XCLK     10
#define CAM_PIN_SIOD     40
#define CAM_PIN_SIOC     39
#define CAM_PIN_D7       48
#define CAM_PIN_D6       11
#define CAM_PIN_D5       12
#define CAM_PIN_D4       14
#define CAM_PIN_D3       16
#define CAM_PIN_D2       18
#define CAM_PIN_D1       17
#define CAM_PIN_D0       15
#define CAM_PIN_VSYNC    38
#define CAM_PIN_HREF     47
#define CAM_PIN_PCLK     13
