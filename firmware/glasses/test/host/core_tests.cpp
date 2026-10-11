// Host-side tests for the glasses' hardware-independent logic.
//   g++ -std=c++17 -I../../lib/core/src core_tests.cpp ../../lib/core/src/*.cpp -o core_tests
//   ./core_tests [out.avi frame.jpg]     (tests/test_firmware.py does this and checks the AVI with ffprobe)
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "avi.h"
#include "battery.h"
#include "capture.h"
#include "gestures.h"
#include "protocol.h"

using namespace hvr;

static int failures = 0;
#define CHECK(cond)                                                     \
  do {                                                                  \
    if (!(cond)) {                                                      \
      std::printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond);       \
      ++failures;                                                       \
    }                                                                   \
  } while (0)

// ---------------------------------------------------------------- gestures
static void test_gestures() {
  GestureDetector button(600);
  CHECK(button.press(0).count == 0);
  Gestures g = button.release(100);
  CHECK(g.count == 1 && g.items[0] == Gesture::Tap);

  button.press(1000);
  CHECK(button.poll(1500).count == 0);
  g = button.poll(1601);
  CHECK(g.count == 1 && g.items[0] == Gesture::Hold);
  CHECK(button.release(2000).count == 0);

  GestureDetector touch(3000, 350);
  touch.press(0);
  CHECK(touch.release(80).count == 0);          // waiting for a possible second tap
  touch.press(200);
  g = touch.release(280);
  CHECK(g.count == 1 && g.items[0] == Gesture::DoubleTap);

  touch.press(5000);
  touch.release(5100);
  CHECK(touch.poll(5300).count == 0);
  g = touch.poll(5500);
  CHECK(g.count == 1 && g.items[0] == Gesture::Tap);
}

// ---------------------------------------------------------------- battery
static void test_battery() {
  CHECK(lipoPercent(4.25f) == 100.0f);
  CHECK(lipoPercent(3.2f) == 0.0f);
  CHECK(std::fabs(lipoPercent(3.80f) - 50.0f) < 0.01f);
  CHECK(lipoPercent(3.9f) > lipoPercent(3.8f));
  CHECK(batteryBars(90) == 4 && batteryBars(60) == 3 && batteryBars(30) == 2 && batteryBars(5) == 1);
  BatteryFilter f(0.5f);
  CHECK(f.update(4.0f) == 4.0f);
  CHECK(std::fabs(f.update(3.0f) - 3.5f) < 1e-6f);
}

// ---------------------------------------------------------------- protocol
static void test_protocol() {
  CHECK(parseCommand("photo", 5).cmd == Cmd::Photo);
  CHECK(parseCommand("  Record Start \n", 16).cmd == Cmd::RecordStart);
  CHECK(parseCommand("record", 6).cmd == Cmd::RecordToggle);
  Command c = parseCommand("time 1790000000", 15);
  CHECK(c.cmd == Cmd::SetTime && c.value == 1790000000);
  CHECK(parseCommand("time 12", 7).cmd == Cmd::Invalid);
  c = parseCommand("set res svga", 12);
  CHECK(c.cmd == Cmd::SetResolution && c.res == Resolution::SVGA);
  CHECK(parseCommand("set res 4k", 10).cmd == Cmd::Invalid);
  CHECK(parseCommand("set quality 99", 14).cmd == Cmd::Invalid);
  c = parseCommand("set segment 600", 15);
  CHECK(c.cmd == Cmd::SetSegment && c.value == 600);
  CHECK(parseCommand("set maxrec 0", 12).cmd == Cmd::SetMaxRec);
  CHECK(parseCommand("rm -rf", 6).cmd == Cmd::Invalid);

  Status s;
  s.recording = true;
  s.batteryPct = 76.4f;
  s.wifi = true;
  s.ssid = "HologramCam-1A2B";
  s.password = "pa\"ss";
  s.ip = "192.168.4.1";
  s.version = "1.0.0";
  char buf[512];
  size_t n = formatStatus(s, buf, sizeof(buf));
  CHECK(n > 0 && n == std::strlen(buf));
  CHECK(std::strstr(buf, "\"rec\":true") != nullptr);
  CHECK(std::strstr(buf, "\"bat\":76") != nullptr);
  CHECK(std::strstr(buf, "\"pass\":\"pa\\\"ss\"") != nullptr);
  CHECK(buf[0] == '{' && buf[n - 1] == '}');
  CHECK(formatStatus(s, buf, 20) == 0);          // too small: refuse rather than truncate
  n = formatEvent("photo", "/DCIM/HVR_1.jpg", buf, sizeof(buf));
  CHECK(std::string(buf) == "{\"ev\":\"photo\",\"detail\":\"/DCIM/HVR_1.jpg\"}");
}

// ---------------------------------------------------------------- capture rules
struct FakeHw : CaptureHardware {
  bool led = false, ledBroken = false, space = true, hot = false;
  int opened = 0, closed = 0, photos = 0;
  bool openWhileLedOff = false;
  std::vector<std::string> files;
  bool ledOn() override { if (ledBroken) return false; led = true; return true; }
  void ledOff() override { led = false; }
  bool openSegment(const char* path) override {
    if (!led) openWhileLedOff = true;
    ++opened;
    files.push_back(path);
    return true;
  }
  void closeSegment() override { ++closed; }
  bool savePhoto(const char* path, bool) override { ++photos; files.push_back(path); return true; }
  bool hasSpace() override { return space; }
  bool tooHot() override { return hot; }
};

static void test_capture() {
  char path[64];
  CHECK(std::string((mediaPath(path, sizeof(path), 1790000000, 7, "avi", 1), path)) ==
        "/DCIM/HVR_20260921_141320.avi");
  mediaPath(path, sizeof(path), 0, 7, "avi", 3);
  CHECK(std::string(path) == "/DCIM/HVR_N000007_p03.avi");

  FakeHw hw;
  CaptureLogic cap(hw);
  cap.setSegmentSeconds(300);
  CHECK(cap.startRecording(1000, 1790000000, 1, path, sizeof(path)) == Refusal::None);
  CHECK(hw.led && cap.recording() && !hw.openWhileLedOff);
  CHECK(!cap.tick(1000 + 299000));
  CHECK(cap.tick(1000 + 300000));                // new segment, LED still on
  CHECK(hw.led && hw.opened == 2 && hw.closed == 1 && cap.segment() == 2);
  CHECK(hw.files.back() == "/DCIM/HVR_20260921_141320_p02.avi");
  CHECK(cap.stopRecording(StopReason::User) && !hw.led && hw.closed == 2);

  hw.hot = true;
  CHECK(cap.startRecording(0, 0, 2, path, sizeof(path)) == Refusal::TooHot);
  hw.hot = false;
  hw.space = false;
  CHECK(cap.takePhoto(0, 0, 3, path, sizeof(path)) == Refusal::StorageFull);
  hw.space = true;

  FakeHw broken;
  broken.ledBroken = true;
  CaptureLogic cap2(broken);
  CHECK(cap2.startRecording(0, 0, 1, path, sizeof(path)) == Refusal::LedFault);
  CHECK(!cap2.recording() && broken.opened == 0);

  CHECK(cap.startRecording(0, 0, 4, path, sizeof(path)) == Refusal::None);
  cap.setLowBattery(true);
  CHECK(cap.tick(10) && !cap.recording() && cap.lastStop() == StopReason::LowBattery && !hw.led);

  CaptureLogic cap3(hw);
  cap3.setMaxRecordingSeconds(60);
  cap3.startRecording(0, 0, 5, path, sizeof(path));
  CHECK(cap3.tick(60000) && cap3.lastStop() == StopReason::MaxLength);
}

// ---------------------------------------------------------------- AVI
struct FileSink : ByteSink {
  FILE* f;
  explicit FileSink(FILE* f) : f(f) {}
  bool write(const uint8_t* d, size_t n) override { return std::fwrite(d, 1, n, f) == n; }
  bool seek(uint32_t pos) override { return std::fseek(f, pos, SEEK_SET) == 0; }
  uint32_t position() override { return static_cast<uint32_t>(std::ftell(f)); }
};

static uint32_t rd32(const std::vector<uint8_t>& b, size_t at) {
  return b[at] | (b[at + 1] << 8) | (b[at + 2] << 16) | (uint32_t(b[at + 3]) << 24);
}

static void test_avi(const char* out, const char* jpegPath) {
  std::vector<uint8_t> jpeg;
  if (jpegPath) {
    FILE* j = std::fopen(jpegPath, "rb");
    CHECK(j != nullptr);
    if (!j) return;
    int c;
    while ((c = std::fgetc(j)) != EOF) jpeg.push_back(static_cast<uint8_t>(c));
    std::fclose(j);
  } else {
    jpeg = {0xFF, 0xD8, 0x01, 0x02, 0x03, 0xFF, 0xD9};   // odd length: exercises padding
  }
  FILE* f = std::fopen(out, "w+b");
  CHECK(f != nullptr);
  if (!f) return;
  FileSink sink(f);
  std::vector<AviIndexEntry> index(400);
  AviWriter avi(sink, index.data(), index.size());
  CHECK(avi.begin(64, 48, 16000));
  std::vector<int16_t> pcm(1600);
  for (int frame = 0; frame < 30; ++frame) {          // 3 s at 10 fps with 0.1 s of audio per frame
    for (size_t i = 0; i < pcm.size(); ++i)
      pcm[i] = static_cast<int16_t>(8000 * std::sin(2 * M_PI * 440 * (frame * 1600 + i) / 16000.0));
    CHECK(avi.addVideoFrame(jpeg.data(), jpeg.size()));
    CHECK(avi.addAudio(pcm.data(), pcm.size()));
  }
  CHECK(avi.finish(3000));
  CHECK(avi.frames() == 30 && avi.audioSamples() == 48000);
  std::fseek(f, 0, SEEK_END);
  long size = std::ftell(f);
  std::fclose(f);

  std::vector<uint8_t> b(static_cast<size_t>(size));
  f = std::fopen(out, "rb");
  CHECK(std::fread(b.data(), 1, b.size(), f) == b.size());
  std::fclose(f);
  CHECK(std::memcmp(b.data(), "RIFF", 4) == 0 && std::memcmp(b.data() + 8, "AVI ", 4) == 0);
  CHECK(rd32(b, 4) == b.size() - 8);
  CHECK(rd32(b, 32) == 100000);                        // 10 fps -> 100 ms per frame
  CHECK(rd32(b, 48) == 30);                            // total frames
  CHECK(std::memcmp(b.data() + b.size() - 60 * 16 - 8, "idx1", 4) == 0);
}

int main(int argc, char** argv) {
  test_gestures();
  test_battery();
  test_protocol();
  test_capture();
  test_avi(argc > 1 ? argv[1] : "core_tests.avi", argc > 2 ? argv[2] : nullptr);
  if (failures) {
    std::printf("%d check(s) failed\n", failures);
    return 1;
  }
  std::printf("all core tests passed\n");
  return 0;
}
