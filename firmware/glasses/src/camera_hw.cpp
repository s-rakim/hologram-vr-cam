#include "camera_hw.h"

#include <Arduino.h>

#include "pins.h"

namespace camera_hw {

namespace {
bool g_running = false;
hvr::Resolution g_res = hvr::Resolution::HD;
int g_quality = -1;

framesize_t frameSize(hvr::Resolution r) {
  switch (r) {
    case hvr::Resolution::VGA: return FRAMESIZE_VGA;
    case hvr::Resolution::SVGA: return FRAMESIZE_SVGA;
    case hvr::Resolution::HD: return FRAMESIZE_HD;
    case hvr::Resolution::UXGA: return FRAMESIZE_UXGA;
  }
  return FRAMESIZE_HD;
}
}  // namespace

bool start(hvr::Resolution res, int quality) {
  if (g_running) {
    sensor_t* s = esp_camera_sensor_get();
    if (!s) return false;
    const bool changed = res != g_res || quality != g_quality;
    if (res != g_res) s->set_framesize(s, frameSize(res));
    if (quality != g_quality) s->set_quality(s, quality);
    g_res = res;
    g_quality = quality;
    if (changed) settle(2);             // buffered frames still have the old size / quality
    return true;
  }
  camera_config_t c = {};
  c.pin_pwdn = CAM_PIN_PWDN;
  c.pin_reset = CAM_PIN_RESET;
  c.pin_xclk = CAM_PIN_XCLK;
  c.pin_sccb_sda = CAM_PIN_SIOD;
  c.pin_sccb_scl = CAM_PIN_SIOC;
  c.pin_d7 = CAM_PIN_D7;
  c.pin_d6 = CAM_PIN_D6;
  c.pin_d5 = CAM_PIN_D5;
  c.pin_d4 = CAM_PIN_D4;
  c.pin_d3 = CAM_PIN_D3;
  c.pin_d2 = CAM_PIN_D2;
  c.pin_d1 = CAM_PIN_D1;
  c.pin_d0 = CAM_PIN_D0;
  c.pin_vsync = CAM_PIN_VSYNC;
  c.pin_href = CAM_PIN_HREF;
  c.pin_pclk = CAM_PIN_PCLK;
  c.xclk_freq_hz = 20000000;
  c.ledc_timer = LEDC_TIMER_0;
  c.ledc_channel = LEDC_CHANNEL_0;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_UXGA;        // allocate for the largest size, then switch down
  c.jpeg_quality = quality;
  c.fb_count = 2;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;
  if (esp_camera_init(&c) != ESP_OK) return false;
  sensor_t* s = esp_camera_sensor_get();
  if (s) {
    s->set_framesize(s, frameSize(res));
    s->set_quality(s, quality);
  }
  g_res = res;
  g_quality = quality;
  g_running = true;
  return true;
}

void stop() {
  if (!g_running) return;
  esp_camera_deinit();
  g_running = false;
}

bool running() { return g_running; }

camera_fb_t* grab() { return g_running ? esp_camera_fb_get() : nullptr; }

void release(camera_fb_t* fb) {
  if (fb) esp_camera_fb_return(fb);
}

void settle(int frames) {
  for (int i = 0; i < frames; ++i) release(grab());
}

}  // namespace camera_hw
