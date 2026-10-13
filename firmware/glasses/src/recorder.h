// Camera + microphone -> microSD. Implements the hardware side of hvr::CaptureLogic.
#pragma once
#include <FS.h>

#include "avi.h"
#include "capture.h"
#include "protocol.h"

class Recorder : public hvr::CaptureHardware {
 public:
  bool begin();                               // mount the card, set up the mic, start the writer task

  // hvr::CaptureHardware
  bool ledOn() override;
  void ledOff() override;
  bool openSegment(const char* path) override;
  void closeSegment() override;
  bool savePhoto(const char* path, bool whileRecording) override;
  bool hasSpace() override;
  bool tooHot() override;
  bool segmentFull() override;

  void setVideo(hvr::Resolution res, int quality) { res_ = res; quality_ = quality; }
  void tick(uint32_t now);                    // camera idle power-off, free-space cache
  bool cardOk() const { return cardOk_; }
  uint32_t freeMb();
  uint32_t minutesLeft();
  float fps();
  uint32_t photos() const { return photos_; }
  uint32_t videos() const { return videos_; }
  float temperature();

 private:
  static void taskEntry(void* self);
  void taskLoop();
  void writeAudio();

  SemaphoreHandle_t lock_ = nullptr;
  fs::File file_;
  class SdSink* sink_ = nullptr;
  hvr::AviWriter* writer_ = nullptr;
  hvr::AviIndexEntry* index_ = nullptr;
  int16_t* audioBuf_ = nullptr;
  volatile bool active_ = false;
  bool cardOk_ = false;
  bool hot_ = false;
  hvr::Resolution res_ = hvr::Resolution::HD;
  int quality_ = 12;
  uint32_t segmentStart_ = 0;
  uint32_t lastUse_ = 0;
  uint32_t freeMb_ = 0, freeCheckedAt_ = 0;
  uint32_t photos_ = 0, videos_ = 0;
  float bytesPerSecond_ = 0;
};
