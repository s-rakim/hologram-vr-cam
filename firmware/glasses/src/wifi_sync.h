// Wi-Fi sync mode: the glasses become a password-protected hotspot with a small
// web page to browse, download and delete media, send commands, and update the
// firmware. Off by default: Wi-Fi is the biggest optional power draw.
//
// The web server runs in its own task, so a long download never stalls the
// buttons, BLE or the battery and heat checks in loop().
#pragma once
#include <cstddef>

namespace wifi_sync {

using CommandHandler = void (*)(const char* text, size_t len);   // must be thread-safe (queues the command)

void start(CommandHandler onCommand);
void stop();
bool active();
// The file being recorded right now ("" = none): it can't be downloaded, deleted
// or interrupted by a firmware update.
void setBusyFile(const char* path);
const char* ssid();
const char* password();
const char* ip();

}  // namespace wifi_sync
