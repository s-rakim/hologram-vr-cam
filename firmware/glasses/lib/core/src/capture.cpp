#include "capture.h"

#include <cstdio>

namespace hvr {

const char* refusalName(Refusal r) {
  switch (r) {
    case Refusal::None: return "none";
    case Refusal::LowBattery: return "low_battery";
    case Refusal::TooHot: return "too_hot";
    case Refusal::StorageFull: return "storage_full";
    case Refusal::LedFault: return "privacy_led_fault";
    case Refusal::CameraError: return "camera_error";
  }
  return "none";
}

const char* stopReasonName(StopReason r) {
  switch (r) {
    case StopReason::User: return "user";
    case StopReason::MaxLength: return "max_length";
    case StopReason::LowBattery: return "low_battery";
    case StopReason::TooHot: return "too_hot";
    case StopReason::StorageFull: return "storage_full";
    case StopReason::Error: return "error";
    case StopReason::Shutdown: return "shutdown";
  }
  return "user";
}

namespace {
// Days since 1970-01-01 -> civil date (Howard Hinnant's algorithm).
void civil(int64_t days, int* y, unsigned* m, unsigned* d) {
  days += 719468;
  const int64_t era = (days >= 0 ? days : days - 146096) / 146097;
  const unsigned doe = static_cast<unsigned>(days - era * 146097);
  const unsigned yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
  const unsigned doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
  const unsigned mp = (5 * doy + 2) / 153;
  *d = doy - (153 * mp + 2) / 5 + 1;
  *m = mp < 10 ? mp + 3 : mp - 9;
  *y = static_cast<int>(yoe + era * 400 + (*m <= 2));
}
}  // namespace

void mediaPath(char* out, size_t len, int64_t epoch, uint32_t sequence, const char* ext, int part) {
  char stem[32];
  if (epoch > 1600000000) {
    int y;
    unsigned mo, d;
    civil(epoch / 86400, &y, &mo, &d);
    const unsigned secs = static_cast<unsigned>(epoch % 86400);
    std::snprintf(stem, sizeof(stem), "HVR_%04d%02u%02u_%02u%02u%02u_%04lu", y, mo, d, secs / 3600,
                  (secs / 60) % 60, secs % 60, static_cast<unsigned long>(sequence % 10000));
  } else {
    std::snprintf(stem, sizeof(stem), "HVR_N%06lu", static_cast<unsigned long>(sequence));
  }
  if (part > 1)
    std::snprintf(out, len, "/DCIM/%s_p%02d.%s", stem, part, ext);
  else
    std::snprintf(out, len, "/DCIM/%s.%s", stem, ext);
}

Refusal CaptureLogic::check() {
  if (lowBattery_) return Refusal::LowBattery;
  if (hw_.tooHot()) return Refusal::TooHot;
  if (!hw_.hasSpace()) return Refusal::StorageFull;
  return Refusal::None;
}

Refusal CaptureLogic::takePhoto(uint32_t now, int64_t epoch, uint32_t sequence, char* pathOut, size_t len) {
  (void)now;
  Refusal r = check();
  if (r != Refusal::None) return r;
  if (!recording_ && !hw_.ledOn()) return Refusal::LedFault;   // lit while the picture is taken
  mediaPath(pathOut, len, epoch, sequence, "jpg", 1);
  const bool ok = hw_.savePhoto(pathOut, recording_);
  if (!recording_) hw_.ledOff();
  return ok ? Refusal::None : Refusal::CameraError;
}

Refusal CaptureLogic::startRecording(uint32_t now, int64_t epoch, uint32_t sequence, char* pathOut, size_t len) {
  if (recording_) {
    std::snprintf(pathOut, len, "%s", path_);
    return Refusal::None;
  }
  Refusal r = check();
  if (r != Refusal::None) return r;
  if (!hw_.ledOn()) return Refusal::LedFault;          // LED first: never record unannounced
  epoch_ = epoch;
  sequence_ = sequence;
  part_ = 1;
  mediaPath(path_, sizeof(path_), epoch_, sequence_, "avi", part_);
  if (!hw_.openSegment(path_)) {
    hw_.ledOff();
    return Refusal::CameraError;
  }
  recording_ = true;
  startedAt_ = segmentAt_ = now;
  std::snprintf(pathOut, len, "%s", path_);
  return Refusal::None;
}

bool CaptureLogic::stopRecording(StopReason why) {
  if (!recording_) return false;
  hw_.closeSegment();
  recording_ = false;
  lastStop_ = why;
  hw_.ledOff();                                        // only once the file is closed
  return true;
}

bool CaptureLogic::tick(uint32_t now) {
  if (!recording_) return false;
  if (maxMs_ && now - startedAt_ >= maxMs_) return stopRecording(StopReason::MaxLength);
  if (lowBattery_) return stopRecording(StopReason::LowBattery);
  if (hw_.tooHot()) return stopRecording(StopReason::TooHot);
  if (!hw_.hasSpace()) return stopRecording(StopReason::StorageFull);
  if (now - segmentAt_ >= segmentMs_ || hw_.segmentFull()) {   // roll over; the LED stays on
    hw_.closeSegment();
    ++part_;
    mediaPath(path_, sizeof(path_), epoch_, sequence_, "avi", part_);
    if (!hw_.openSegment(path_)) return stopRecording(StopReason::Error);
    segmentAt_ = now;
    return true;
  }
  return false;
}

}  // namespace hvr
