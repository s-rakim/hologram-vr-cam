// OV2640 / OV5640 on the XIAO ESP32S3 Sense, powered only while it is needed.
#pragma once
#include "esp_camera.h"
#include "protocol.h"

namespace camera_hw {

bool start(hvr::Resolution res, int quality);   // no-op if already running at that size
void stop();                                     // frees the sensor clock and frame buffers
bool running();
camera_fb_t* grab();
void release(camera_fb_t* fb);
// Let auto exposure settle after a cold start.
void settle(int frames);

}  // namespace camera_hw
