// Capture rules for the glasses, independent of the camera driver (host-testable).
//
//  * The privacy LED goes on BEFORE a photo or recording starts and the capture is
//    refused if it cannot; it goes off only after the file is closed.
//  * Long recordings continue in back-to-back segment files (FAT32 has a 4 GB
//    file limit and a short file loses less if the battery dies).
//  * Low battery, heat and a full card refuse new captures and stop recordings.
#pragma once
#include <cstddef>
#include <cstdint>

namespace hvr {

class CaptureHardware {
 public:
  virtual ~CaptureHardware() = default;
  virtual bool ledOn() = 0;                       // false if the LED driver failed
  virtual void ledOff() = 0;
  virtual bool openSegment(const char* path) = 0;
  virtual void closeSegment() = 0;
  virtual bool savePhoto(const char* path, bool whileRecording) = 0;
  virtual bool hasSpace() = 0;
  virtual bool tooHot() = 0;
  virtual bool segmentFull() { return false; }    // the file's index is nearly full: roll over now
};

enum class Refusal : uint8_t { None, LowBattery, TooHot, StorageFull, LedFault, CameraError };
enum class StopReason : uint8_t { User, MaxLength, LowBattery, TooHot, StorageFull, Error, Shutdown };

const char* refusalName(Refusal r);
const char* stopReasonName(StopReason r);

// File names: /DCIM/HVR_20261008_153012_0042.avi (local time from the phone + a running
// number, so two captures in the same second never collide), then _p02, _p03 ... for later
// segments. When the clock has not been set, only the running number is used: HVR_N000042.
void mediaPath(char* out, size_t len, int64_t epochSeconds, uint32_t sequence, const char* ext, int part);

class CaptureLogic {
 public:
  explicit CaptureLogic(CaptureHardware& hw) : hw_(hw) {}

  void setSegmentSeconds(uint32_t s) { segmentMs_ = s * 1000; }
  void setMaxRecordingSeconds(uint32_t s) { maxMs_ = s * 1000; }
  void setLowBattery(bool low) { lowBattery_ = low; }

  // `now` in ms; epoch / sequence are used for the file name.
  Refusal takePhoto(uint32_t now, int64_t epoch, uint32_t sequence, char* pathOut, size_t len);
  Refusal startRecording(uint32_t now, int64_t epoch, uint32_t sequence, char* pathOut, size_t len);
  bool stopRecording(StopReason why);

  // Call often. Returns true when something changed (new segment or a stop); the
  // reason is in lastStop() / segment().
  bool tick(uint32_t now);

  bool recording() const { return recording_; }
  uint32_t elapsedMs(uint32_t now) const { return recording_ ? now - startedAt_ : 0; }
  int segment() const { return part_; }
  const char* currentPath() const { return path_; }
  StopReason lastStop() const { return lastStop_; }

 private:
  Refusal check();
  CaptureHardware& hw_;
  bool recording_ = false;
  bool lowBattery_ = false;
  uint32_t segmentMs_ = 300000;
  uint32_t maxMs_ = 0;
  uint32_t startedAt_ = 0, segmentAt_ = 0;
  int part_ = 0;
  int64_t epoch_ = 0;
  uint32_t sequence_ = 0;
  char path_[48] = {0};
  StopReason lastStop_ = StopReason::User;
};

}  // namespace hvr
