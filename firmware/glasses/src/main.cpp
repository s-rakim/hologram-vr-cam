// Hologram Cam glasses firmware (XIAO ESP32S3 Sense).
//
// Controls on the glasses:
//   capture button  tap = photo (or stop recording) | hold = start recording | press = wake from power off
//   touch pad       tap = battery level (1-4 beeps) | double tap = Wi-Fi sync on/off | hold 3 s = power off
// Phone: everything above plus settings, over Bluetooth LE (phone/index.html), or the Wi-Fi sync page.
#include <Arduino.h>
#include <Preferences.h>
#include <sys/time.h>
#include <time.h>

#include "battery.h"
#include "ble_link.h"
#include "capture.h"
#include "config.h"
#include "gestures.h"
#include "pins.h"
#include "power.h"
#include "protocol.h"
#include "recorder.h"
#include "sounds.h"
#include "wifi_sync.h"

#define FIRMWARE_VERSION "1.0.0"

namespace {

Recorder recorder;
hvr::CaptureLogic capture(recorder);
hvr::GestureDetector button(BUTTON_HOLD_MS);
hvr::GestureDetector touch(TOUCH_HOLD_MS, TOUCH_DOUBLE_MS);
Preferences prefs;
QueueHandle_t commands;          // text commands from BLE / Wi-Fi, handled in loop()

struct Settings {
  hvr::Resolution res = hvr::Resolution::HD;
  uint8_t quality = DEFAULT_JPEG_QUALITY;
  uint16_t segmentS = DEFAULT_SEGMENT_S;
  uint32_t maxRecS = DEFAULT_MAX_REC_S;
} settings;

struct CommandText {
  char text[64];
  uint8_t len;
};

bool buttonDown = false, touchDown = false;
uint32_t buttonChangedAt = 0;
uint32_t touchBaseline = 0;
uint32_t lastStatusAt = 0, lastBatteryAt = 0;
bool batteryWarned = false;

// ---------------------------------------------------------------- helpers
int64_t epochNow() { return static_cast<int64_t>(time(nullptr)); }

uint32_t nextSequence() {
  const uint32_t seq = prefs.getUInt("seq", 0) + 1;
  prefs.putUInt("seq", seq);
  return seq;
}

void event(const char* name, const char* detail = "") {
  char buf[128];
  const size_t n = hvr::formatEvent(name, detail, buf, sizeof(buf));
  if (n) ble_link::sendEvent(buf, n);
}

void sendStatus() {
  hvr::Status s;
  const uint32_t now = millis();
  s.recording = capture.recording();
  s.recSeconds = capture.elapsedMs(now) / 1000;
  s.segment = capture.recording() ? capture.segment() : 0;
  s.batteryVolts = power::batteryVolts();
  s.batteryPct = power::batteryPercent();
  s.charging = power::externalPower();
  s.freeMb = recorder.freeMb();
  s.minutesLeft = recorder.minutesLeft();
  s.photos = recorder.photos();
  s.videos = recorder.videos();
  s.wifi = wifi_sync::active();
  s.ssid = wifi_sync::ssid();
  s.password = wifi_sync::password();
  s.ip = wifi_sync::ip();
  s.res = settings.res;
  s.quality = settings.quality;
  s.segmentS = settings.segmentS;
  s.maxRecS = settings.maxRecS;
  s.fps = recorder.fps();
  s.tempC = recorder.temperature();
  s.clockSet = epochNow() > 1600000000;
  s.version = FIRMWARE_VERSION;
  char buf[512];
  const size_t n = hvr::formatStatus(s, buf, sizeof(buf));
  if (n) ble_link::sendStatus(buf, n);
  lastStatusAt = now;
}

void saveSettings() {
  prefs.putUChar("res", static_cast<uint8_t>(settings.res));
  prefs.putUChar("q", settings.quality);
  prefs.putUShort("seg", settings.segmentS);
  prefs.putUInt("maxrec", settings.maxRecS);
}

void applySettings() {
  recorder.setVideo(settings.res, settings.quality);
  capture.setSegmentSeconds(settings.segmentS);
  capture.setMaxRecordingSeconds(settings.maxRecS);
}

// ---------------------------------------------------------------- actions
void refused(hvr::Refusal r) {
  sounds::play(r == hvr::Refusal::LowBattery ? sounds::Sound::BatteryLow : sounds::Sound::Refused);
  event("refused", hvr::refusalName(r));
}

void takePhoto() {
  char path[48];
  const hvr::Refusal r = capture.takePhoto(millis(), epochNow(), nextSequence(), path, sizeof(path));
  if (r != hvr::Refusal::None) return refused(r);
  if (!capture.recording()) {                       // two quick LED flashes for a photo
    digitalWrite(PIN_PRIVACY_LED, HIGH); delay(80); digitalWrite(PIN_PRIVACY_LED, LOW); delay(60);
    digitalWrite(PIN_PRIVACY_LED, HIGH); delay(80); digitalWrite(PIN_PRIVACY_LED, LOW);
  }
  sounds::play(sounds::Sound::Photo);
  event("photo", path);
}

void startRecording() {
  if (capture.recording()) return;
  char path[48];
  const hvr::Refusal r = capture.startRecording(millis(), epochNow(), nextSequence(), path, sizeof(path));
  if (r != hvr::Refusal::None) return refused(r);
  sounds::play(sounds::Sound::RecordStart);
  event("recording", path);
}

void stopRecording(hvr::StopReason why) {
  if (!capture.stopRecording(why)) return;
  sounds::play(why == hvr::StopReason::LowBattery ? sounds::Sound::BatteryLow : sounds::Sound::RecordStop);
  event("stopped", hvr::stopReasonName(why));
}

void setWifi(bool on);

void handleCommandText(const char* text, size_t len);

void shutdown() {
  stopRecording(hvr::StopReason::Shutdown);
  sounds::play(sounds::Sound::PowerOff);
  event("power_off");
  delay(900);
  wifi_sync::stop();
  ble_link::stop();
  power::powerOff();
}

void setWifi(bool on) {
  if (on == wifi_sync::active()) return;
  if (on) {
    setCpuFrequencyMhz(240);
    wifi_sync::start(handleCommandText);
  } else {
    wifi_sync::stop();
  }
  sounds::play(on ? sounds::Sound::WifiOn : sounds::Sound::WifiOff);
  event(on ? "wifi_on" : "wifi_off", on ? wifi_sync::ssid() : "");
  sendStatus();
}

void handle(const hvr::Command& c) {
  switch (c.cmd) {
    case hvr::Cmd::Photo: takePhoto(); break;
    case hvr::Cmd::RecordStart: startRecording(); break;
    case hvr::Cmd::RecordStop: stopRecording(hvr::StopReason::User); break;
    case hvr::Cmd::RecordToggle:
      if (capture.recording()) stopRecording(hvr::StopReason::User);
      else startRecording();
      break;
    case hvr::Cmd::WifiOn: setWifi(true); break;
    case hvr::Cmd::WifiOff: setWifi(false); break;
    case hvr::Cmd::Find: sounds::play(sounds::Sound::Find); break;
    case hvr::Cmd::PowerOff: shutdown(); break;
    case hvr::Cmd::SetTime: {
      timeval tv = {static_cast<time_t>(c.value), 0};
      settimeofday(&tv, nullptr);
      break;
    }
    case hvr::Cmd::SetResolution: settings.res = c.res; saveSettings(); applySettings(); break;
    case hvr::Cmd::SetQuality: settings.quality = static_cast<uint8_t>(c.value); saveSettings(); applySettings(); break;
    case hvr::Cmd::SetSegment: settings.segmentS = static_cast<uint16_t>(c.value); saveSettings(); applySettings(); break;
    case hvr::Cmd::SetMaxRec: settings.maxRecS = static_cast<uint32_t>(c.value); saveSettings(); applySettings(); break;
    case hvr::Cmd::Status: break;
    case hvr::Cmd::Invalid: event("error", "unknown command"); return;
  }
  sendStatus();
}

// Called from the BLE host task or the web server: queue it for loop().
void handleCommandText(const char* text, size_t len) {
  CommandText ct;
  ct.len = static_cast<uint8_t>(len < sizeof(ct.text) ? len : sizeof(ct.text) - 1);
  memcpy(ct.text, text, ct.len);
  ct.text[ct.len] = '\0';
  xQueueSend(commands, &ct, 0);
}

// ---------------------------------------------------------------- gestures
void onButton(const hvr::Gestures& gs) {
  for (int i = 0; i < gs.count; ++i) {
    if (gs.items[i] == hvr::Gesture::Tap) {
      if (capture.recording()) stopRecording(hvr::StopReason::User);
      else takePhoto();
    } else if (gs.items[i] == hvr::Gesture::Hold && !capture.recording()) {
      startRecording();
    }
  }
}

void onTouch(const hvr::Gestures& gs) {
  for (int i = 0; i < gs.count; ++i) {
    switch (gs.items[i]) {
      case hvr::Gesture::Tap: sounds::play(sounds::Sound::Beep, hvr::batteryBars(power::batteryPercent())); break;
      case hvr::Gesture::DoubleTap: setWifi(!wifi_sync::active()); break;
      case hvr::Gesture::Hold: shutdown(); break;
    }
  }
}

void readInputs(uint32_t now) {
  const bool b = digitalRead(PIN_BUTTON) == LOW;
  if (b != buttonDown && now - buttonChangedAt > 20) {        // 20 ms debounce
    buttonDown = b;
    buttonChangedAt = now;
    onButton(b ? button.press(now) : button.release(now));
  }
  onButton(button.poll(now));

  const bool t = touchRead(PIN_TOUCH) > touchBaseline * 13 / 10;   // S3 readings rise when touched
  if (t != touchDown) {
    touchDown = t;
    onTouch(t ? touch.press(now) : touch.release(now));
  }
  onTouch(touch.poll(now));
}

void checkBattery(uint32_t now) {
  if (now - lastBatteryAt < 5000) return;
  lastBatteryAt = now;
  if (power::batteryVolts() < 2.5f) return;          // no divider fitted / USB only: nothing to judge
  const float pct = power::batteryPercent();
  if (power::externalPower()) {
    capture.setLowBattery(false);
    return;
  }
  if (pct <= BATTERY_OFF_PCT) {
    capture.setLowBattery(true);
    stopRecording(hvr::StopReason::LowBattery);
    event("battery_empty");
    delay(1500);
    shutdown();
  } else if (pct <= BATTERY_WARN_PCT && !batteryWarned) {
    batteryWarned = true;
    sounds::play(sounds::Sound::BatteryLow);
    event("battery_low");
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  setCpuFrequencyMhz(80);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  commands = xQueueCreate(8, sizeof(CommandText));

  prefs.begin("hvr", false);
  settings.res = static_cast<hvr::Resolution>(prefs.getUChar("res", static_cast<uint8_t>(settings.res)));
  settings.quality = prefs.getUChar("q", settings.quality);
  settings.segmentS = prefs.getUShort("seg", settings.segmentS);
  settings.maxRecS = prefs.getUInt("maxrec", settings.maxRecS);

  uint32_t sum = 0;
  for (int i = 0; i < 16; ++i) sum += touchRead(PIN_TOUCH);
  touchBaseline = sum / 16;

  power::begin();
  sounds::begin();
  if (!recorder.begin()) Serial.println("microSD missing: capture disabled");
  applySettings();
  ble_link::begin(BLE_DEVICE_NAME, BLE_PASSKEY, handleCommandText);
  sounds::play(sounds::Sound::Boot);
}

void loop() {
  const uint32_t now = millis();
  readInputs(now);

  CommandText ct;
  while (xQueueReceive(commands, &ct, 0) == pdTRUE) handle(hvr::parseCommand(ct.text, ct.len));

  if (capture.tick(now)) {
    if (capture.recording()) event("segment", capture.currentPath());
    else event("stopped", hvr::stopReasonName(capture.lastStop()));
  }
  recorder.tick(now);
  checkBattery(now);
  wifi_sync::loop();

  if (ble_link::connected() && now - lastStatusAt > (capture.recording() ? 1000u : 3000u)) sendStatus();
  delay(10);
}
