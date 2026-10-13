#include "recorder.h"

#include <Arduino.h>
#include <SD.h>
#include <SPI.h>
#include <driver/i2s.h>

#include "camera_hw.h"
#include "config.h"
#include "pins.h"

namespace {
constexpr i2s_port_t kMicPort = I2S_NUM_0;   // PDM RX is only available on I2S0
constexpr size_t kIndexEntries = 16000;       // ~8000 frames; segments roll over before it fills
constexpr size_t kIndexMargin = 256;          // ~10 s of frames + audio at 12 fps
constexpr size_t kAudioChunk = 2048;          // samples read per video frame at most

uint32_t countFiles(const char* ext) {
  uint32_t n = 0;
  File dir = SD.open("/DCIM");
  if (!dir) return 0;
  for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
    String name = f.name();
    if (!f.isDirectory() && name.endsWith(ext)) ++n;
  }
  return n;
}
}  // namespace

class SdSink : public hvr::ByteSink {
 public:
  explicit SdSink(fs::File* f) : f_(f) {}
  bool write(const uint8_t* d, size_t n) override { return f_->write(d, n) == n; }
  bool seek(uint32_t pos) override { return f_->seek(pos); }
  uint32_t position() override { return static_cast<uint32_t>(f_->position()); }

 private:
  fs::File* f_;
};

bool Recorder::begin() {
  pinMode(PIN_PRIVACY_LED, OUTPUT);           // OUTPUT keeps the input buffer on, so it reads back
  digitalWrite(PIN_PRIVACY_LED, LOW);
  lock_ = xSemaphoreCreateMutex();

  SPI.begin(PIN_SD_SCK, PIN_SD_MISO, PIN_SD_MOSI, PIN_SD_CS);
  cardOk_ = SD.begin(PIN_SD_CS, SPI, 25000000);
  if (cardOk_) {
    if (!SD.exists("/DCIM")) SD.mkdir("/DCIM");
    photos_ = countFiles(".jpg");
    videos_ = countFiles(".avi");
  }

  index_ = static_cast<hvr::AviIndexEntry*>(ps_malloc(kIndexEntries * sizeof(hvr::AviIndexEntry)));
  audioBuf_ = static_cast<int16_t*>(ps_malloc(kAudioChunk * sizeof(int16_t)));
  sink_ = new SdSink(&file_);
  writer_ = new hvr::AviWriter(*sink_, index_, kIndexEntries);

  i2s_config_t cfg = {};
  cfg.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_PDM);
  cfg.sample_rate = AUDIO_RATE_HZ;
  cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  cfg.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;
  cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  cfg.dma_buf_count = 8;
  cfg.dma_buf_len = 512;                      // 8 x 512 samples = 256 ms of slack between frames
  i2s_driver_install(kMicPort, &cfg, 0, nullptr);
  i2s_pin_config_t pins = {};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;
  pins.bck_io_num = I2S_PIN_NO_CHANGE;
  pins.ws_io_num = PIN_MIC_CLK;
  pins.data_out_num = I2S_PIN_NO_CHANGE;
  pins.data_in_num = PIN_MIC_DATA;
  i2s_set_pin(kMicPort, &pins);
  i2s_stop(kMicPort);

  // Same priority as Arduino's loop task on the same core, so the two share it even
  // when the SD card can't keep up with the camera.
  xTaskCreatePinnedToCore(taskEntry, "recorder", 6144, this, 1, nullptr, 1);
  return cardOk_ && index_ && audioBuf_;
}

bool Recorder::ledOn() {
  digitalWrite(PIN_PRIVACY_LED, HIGH);
  return digitalRead(PIN_PRIVACY_LED) == HIGH;   // catches a pin shorted to ground
}

void Recorder::ledOff() { digitalWrite(PIN_PRIVACY_LED, LOW); }

bool Recorder::openSegment(const char* path) {
  if (!cardOk_) return false;
  if (!camera_hw::start(res_, quality_)) return false;
  setCpuFrequencyMhz(240);
  uint16_t w, h;
  hvr::resolutionSize(res_, &w, &h);
  xSemaphoreTake(lock_, portMAX_DELAY);
  file_ = SD.open(path, FILE_WRITE);
  bool ok = file_ && writer_->begin(w, h, AUDIO_RATE_HZ);
  if (ok) {
    i2s_zero_dma_buffer(kMicPort);
    i2s_start(kMicPort);
    segmentStart_ = millis();
    active_ = true;
  } else if (file_) {
    file_.close();
  }
  xSemaphoreGive(lock_);
  return ok;
}

void Recorder::closeSegment() {
  xSemaphoreTake(lock_, portMAX_DELAY);
  if (active_) {
    active_ = false;
    writeAudio();                             // whatever the mic still holds
    i2s_stop(kMicPort);
    const uint32_t ms = millis() - segmentStart_;
    writer_->finish(ms);
    if (ms) bytesPerSecond_ = writer_->bytesWritten() * 1000.0f / ms;
    file_.close();
    ++videos_;
    freeCheckedAt_ = 0;                       // re-read free space soon
  }
  lastUse_ = millis();
  xSemaphoreGive(lock_);
}

void Recorder::writeAudio() {
  size_t got = 0;
  while (i2s_read(kMicPort, audioBuf_, kAudioChunk * sizeof(int16_t), &got, 0) == ESP_OK && got) {
    writer_->addAudio(audioBuf_, got / sizeof(int16_t));
    if (got < kAudioChunk * sizeof(int16_t)) break;
  }
}

void Recorder::taskEntry(void* self) { static_cast<Recorder*>(self)->taskLoop(); }

void Recorder::taskLoop() {
  for (;;) {
    if (!active_) {
      vTaskDelay(pdMS_TO_TICKS(20));
      continue;
    }
    camera_fb_t* fb = camera_hw::grab();      // blocks until the next frame
    xSemaphoreTake(lock_, portMAX_DELAY);
    if (active_ && fb && !writer_->full()) {
      writer_->addVideoFrame(fb->buf, fb->len);
      writeAudio();
    }
    xSemaphoreGive(lock_);
    camera_hw::release(fb);
    vTaskDelay(1);                            // let loop() run (buttons, BLE, safety checks)
  }
}

bool Recorder::segmentFull() { return active_ && writer_->nearlyFull(kIndexMargin); }

bool Recorder::savePhoto(const char* path, bool whileRecording) {
  if (!cardOk_) return false;
  if (!whileRecording) {
    const bool cold = !camera_hw::running();
    setCpuFrequencyMhz(240);
    if (!camera_hw::start(hvr::Resolution::UXGA, 10)) return false;
    if (cold) camera_hw::settle(4);           // auto exposure after power-up
  }
  xSemaphoreTake(lock_, portMAX_DELAY);
  camera_fb_t* fb = camera_hw::grab();
  bool ok = false;
  if (fb) {
    File f = SD.open(path, FILE_WRITE);
    ok = f && f.write(fb->buf, fb->len) == fb->len;
    f.close();
  }
  xSemaphoreGive(lock_);
  camera_hw::release(fb);
  if (ok) ++photos_;
  lastUse_ = millis();
  freeCheckedAt_ = 0;
  return ok;
}

uint32_t Recorder::freeMb() {
  if (!cardOk_) return 0;
  const uint32_t now = millis();
  if (!freeCheckedAt_ || now - freeCheckedAt_ > 10000) {   // the FAT free-space scan is slow
    freeMb_ = static_cast<uint32_t>((SD.totalBytes() - SD.usedBytes()) / (1024 * 1024));
    freeCheckedAt_ = now;
  }
  return freeMb_;
}

bool Recorder::hasSpace() { return freeMb() > MIN_FREE_MB; }

float Recorder::temperature() { return temperatureRead(); }

bool Recorder::tooHot() {
  const float t = temperature();
  if (hot_ && t < TEMP_RESUME_C) hot_ = false;
  else if (!hot_ && t >= TEMP_STOP_C) hot_ = true;
  return hot_;
}

uint32_t Recorder::minutesLeft() {
  float rate = bytesPerSecond_;
  if (rate <= 0) {   // estimates for ~15 fps until a real recording has been measured
    static const float kRate[] = {350e3f, 500e3f, 800e3f, 1300e3f};  // VGA, SVGA, HD, UXGA bytes/s
    rate = kRate[static_cast<int>(res_)];
  }
  return static_cast<uint32_t>(freeMb() * 1048576.0f / rate / 60.0f);
}

float Recorder::fps() {
  if (!active_) return 0;
  const uint32_t ms = millis() - segmentStart_;
  return ms ? writer_->frames() * 1000.0f / ms : 0;
}

void Recorder::tick(uint32_t now) {
  if (!active_ && camera_hw::running() && now - lastUse_ > CAMERA_IDLE_OFF_MS) {
    camera_hw::stop();                       // the sensor is a big idle load
    setCpuFrequencyMhz(80);
  }
}
