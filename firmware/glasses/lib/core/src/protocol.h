// Phone <-> glasses protocol (BLE GATT and the Wi-Fi sync page share it).
//
// Commands are short UTF-8 strings written to the command characteristic:
//   photo | record start | record stop | record toggle | wifi on | wifi off |
//   find | off | time <unix seconds> | set res <uxga|hd|svga|vga> |
//   set quality <4-63> | set segment <seconds> | set maxrec <seconds, 0 = none> | status
// Status and events are JSON objects sent as notifications.
#pragma once
#include <cstddef>
#include <cstdint>

namespace hvr {

enum class Cmd : uint8_t {
  Invalid, Photo, RecordStart, RecordStop, RecordToggle, WifiOn, WifiOff, Find, PowerOff, SetTime,
  SetResolution, SetQuality, SetSegment, SetMaxRec, Status,
};

enum class Resolution : uint8_t { VGA, SVGA, HD, UXGA };

struct Command {
  Cmd cmd = Cmd::Invalid;
  int64_t value = 0;                 // seconds, quality, ...
  Resolution res = Resolution::HD;
};

Command parseCommand(const char* text, size_t len);
const char* resolutionName(Resolution r);
void resolutionSize(Resolution r, uint16_t* w, uint16_t* h);

struct Status {
  bool recording = false;
  uint32_t recSeconds = 0;
  uint16_t segment = 0;
  float batteryPct = 0;
  float batteryVolts = 0;
  bool charging = false;
  uint32_t freeMb = 0;
  uint32_t minutesLeft = 0;          // recording time that fits on the card
  uint32_t photos = 0;
  uint32_t videos = 0;
  bool wifi = false;
  const char* ssid = "";
  const char* password = "";
  const char* ip = "";
  Resolution res = Resolution::HD;
  uint8_t quality = 12;
  uint16_t segmentS = 300;
  uint32_t maxRecS = 0;
  float fps = 0;
  float tempC = 0;
  bool clockSet = false;
  const char* version = "";
};

// Writes a compact JSON object; returns the length (0 if buf was too small).
size_t formatStatus(const Status& s, char* buf, size_t len);
// {"ev":"<name>","detail":"<detail>"}; detail may be empty.
size_t formatEvent(const char* name, const char* detail, char* buf, size_t len);

}  // namespace hvr
