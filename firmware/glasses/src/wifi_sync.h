// Wi-Fi sync mode: the glasses become a password-protected hotspot with a small
// web page to browse, download and delete media, send commands, and update the
// firmware. Off by default: Wi-Fi is the biggest optional power draw.
#pragma once
#include <cstddef>

namespace wifi_sync {

using CommandHandler = void (*)(const char* text, size_t len);

void start(CommandHandler onCommand);
void stop();
bool active();
void loop();
const char* ssid();
const char* password();
const char* ip();

}  // namespace wifi_sync
