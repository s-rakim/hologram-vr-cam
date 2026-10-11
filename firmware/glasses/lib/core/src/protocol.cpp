#include "protocol.h"

#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace hvr {

namespace {

// Lower-cased copy with surrounding whitespace removed.
size_t normalise(const char* text, size_t len, char* out, size_t cap) {
  while (len && std::isspace(static_cast<unsigned char>(*text))) { ++text; --len; }
  while (len && std::isspace(static_cast<unsigned char>(text[len - 1]))) --len;
  size_t n = len < cap - 1 ? len : cap - 1;
  for (size_t i = 0; i < n; ++i) out[i] = static_cast<char>(std::tolower(static_cast<unsigned char>(text[i])));
  out[n] = '\0';
  return n;
}

bool startsWith(const char* s, const char* prefix, const char** rest) {
  size_t n = std::strlen(prefix);
  if (std::strncmp(s, prefix, n) != 0) return false;
  *rest = s + n;
  while (**rest == ' ') ++*rest;
  return true;
}

bool parseInt(const char* s, int64_t* out) {
  if (!*s) return false;
  char* end = nullptr;
  long long v = std::strtoll(s, &end, 10);
  if (*end != '\0') return false;
  *out = v;
  return true;
}

// JSON string escaping for the few characters that can appear in names.
size_t putString(char* buf, size_t len, size_t pos, const char* s) {
  if (pos < len) buf[pos] = '"';
  ++pos;
  for (; *s; ++s) {
    if (*s == '"' || *s == '\\') {
      if (pos < len) buf[pos] = '\\';
      ++pos;
    }
    if (pos < len) buf[pos] = *s;
    ++pos;
  }
  if (pos < len) buf[pos] = '"';
  return pos + 1;
}

}  // namespace

Command parseCommand(const char* text, size_t len) {
  char s[64];
  normalise(text, len, s, sizeof(s));
  Command c;
  const char* rest = nullptr;
  if (!std::strcmp(s, "photo")) c.cmd = Cmd::Photo;
  else if (!std::strcmp(s, "record start")) c.cmd = Cmd::RecordStart;
  else if (!std::strcmp(s, "record stop")) c.cmd = Cmd::RecordStop;
  else if (!std::strcmp(s, "record toggle") || !std::strcmp(s, "record")) c.cmd = Cmd::RecordToggle;
  else if (!std::strcmp(s, "wifi on")) c.cmd = Cmd::WifiOn;
  else if (!std::strcmp(s, "wifi off")) c.cmd = Cmd::WifiOff;
  else if (!std::strcmp(s, "find")) c.cmd = Cmd::Find;
  else if (!std::strcmp(s, "off")) c.cmd = Cmd::PowerOff;
  else if (!std::strcmp(s, "status")) c.cmd = Cmd::Status;
  else if (startsWith(s, "time", &rest)) {
    if (parseInt(rest, &c.value) && c.value > 1600000000) c.cmd = Cmd::SetTime;   // after 2020
  } else if (startsWith(s, "set res", &rest)) {
    c.cmd = Cmd::SetResolution;
    if (!std::strcmp(rest, "vga")) c.res = Resolution::VGA;
    else if (!std::strcmp(rest, "svga")) c.res = Resolution::SVGA;
    else if (!std::strcmp(rest, "hd") || !std::strcmp(rest, "720p")) c.res = Resolution::HD;
    else if (!std::strcmp(rest, "uxga")) c.res = Resolution::UXGA;
    else c.cmd = Cmd::Invalid;
  } else if (startsWith(s, "set quality", &rest)) {
    if (parseInt(rest, &c.value) && c.value >= 4 && c.value <= 63) c.cmd = Cmd::SetQuality;
  } else if (startsWith(s, "set segment", &rest)) {
    if (parseInt(rest, &c.value) && c.value >= 30 && c.value <= 1800) c.cmd = Cmd::SetSegment;
  } else if (startsWith(s, "set maxrec", &rest)) {
    if (parseInt(rest, &c.value) && c.value >= 0 && c.value <= 24 * 3600) c.cmd = Cmd::SetMaxRec;
  }
  return c;
}

const char* resolutionName(Resolution r) {
  switch (r) {
    case Resolution::VGA: return "vga";
    case Resolution::SVGA: return "svga";
    case Resolution::HD: return "hd";
    case Resolution::UXGA: return "uxga";
  }
  return "hd";
}

void resolutionSize(Resolution r, uint16_t* w, uint16_t* h) {
  switch (r) {
    case Resolution::VGA: *w = 640; *h = 480; return;
    case Resolution::SVGA: *w = 800; *h = 600; return;
    case Resolution::HD: *w = 1280; *h = 720; return;
    case Resolution::UXGA: *w = 1600; *h = 1200; return;
  }
}

size_t formatStatus(const Status& s, char* buf, size_t len) {
  char head[384];
  int n = std::snprintf(
      head, sizeof(head),
      "{\"rec\":%s,\"t\":%lu,\"seg\":%u,\"bat\":%.0f,\"v\":%.2f,\"chg\":%s,\"free_mb\":%lu,\"left_min\":%lu,"
      "\"photos\":%lu,\"videos\":%lu,\"res\":\"%s\",\"q\":%u,\"seg_s\":%u,\"maxrec\":%lu,\"fps\":%.1f,"
      "\"temp\":%.0f,"
      "\"clock\":%s,\"wifi\":%s",
      s.recording ? "true" : "false", static_cast<unsigned long>(s.recSeconds), s.segment, s.batteryPct,
      s.batteryVolts, s.charging ? "true" : "false", static_cast<unsigned long>(s.freeMb),
      static_cast<unsigned long>(s.minutesLeft), static_cast<unsigned long>(s.photos),
      static_cast<unsigned long>(s.videos), resolutionName(s.res), s.quality, s.segmentS,
      static_cast<unsigned long>(s.maxRecS), s.fps, s.tempC,
      s.clockSet ? "true" : "false", s.wifi ? "true" : "false");
  if (n < 0 || static_cast<size_t>(n) >= sizeof(head)) return 0;
  size_t pos = 0;
  for (int i = 0; i < n; ++i, ++pos)
    if (pos < len) buf[pos] = head[i];
  if (s.wifi) {
    const char* keys[] = {",\"ssid\":", ",\"pass\":", ",\"ip\":"};
    const char* vals[] = {s.ssid, s.password, s.ip};
    for (int k = 0; k < 3; ++k) {
      for (const char* p = keys[k]; *p; ++p, ++pos)
        if (pos < len) buf[pos] = *p;
      pos = putString(buf, len, pos, vals[k]);
    }
  }
  const char* tail = ",\"ver\":";
  for (const char* p = tail; *p; ++p, ++pos)
    if (pos < len) buf[pos] = *p;
  pos = putString(buf, len, pos, s.version);
  if (pos < len) buf[pos] = '}';
  ++pos;
  if (pos >= len) return 0;
  buf[pos] = '\0';
  return pos;
}

size_t formatEvent(const char* name, const char* detail, char* buf, size_t len) {
  size_t pos = 0;
  const char* a = "{\"ev\":";
  for (const char* p = a; *p; ++p, ++pos)
    if (pos < len) buf[pos] = *p;
  pos = putString(buf, len, pos, name);
  const char* b = ",\"detail\":";
  for (const char* p = b; *p; ++p, ++pos)
    if (pos < len) buf[pos] = *p;
  pos = putString(buf, len, pos, detail ? detail : "");
  if (pos < len) buf[pos] = '}';
  ++pos;
  if (pos >= len) return 0;
  buf[pos] = '\0';
  return pos;
}

}  // namespace hvr
