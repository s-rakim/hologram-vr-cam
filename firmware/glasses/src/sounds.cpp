#include "sounds.h"

#include <Arduino.h>
#include <driver/i2s.h>

#include "pins.h"

namespace sounds {

namespace {
constexpr i2s_port_t kPort = I2S_NUM_1;   // I2S0 is the PDM microphone
constexpr int kRate = 16000;
QueueHandle_t g_queue = nullptr;

struct Tone { uint16_t hz, ms; };
struct Request { Sound sound; int repeat; };

int pattern(Sound s, Tone* t) {
  switch (s) {
    case Sound::Boot: t[0] = {660, 80}; t[1] = {990, 120}; return 2;
    case Sound::Photo: t[0] = {2400, 25}; t[1] = {0, 30}; t[2] = {1600, 35}; return 3;
    case Sound::RecordStart: t[0] = {880, 90}; t[1] = {0, 40}; t[2] = {1320, 120}; return 3;
    case Sound::RecordStop: t[0] = {1320, 90}; t[1] = {0, 40}; t[2] = {880, 120}; return 3;
    case Sound::Refused: t[0] = {220, 260}; return 1;
    case Sound::BatteryLow: t[0] = {990, 120}; t[1] = {0, 60}; t[2] = {740, 120}; t[3] = {0, 60}; t[4] = {550, 200}; return 5;
    case Sound::Beep: t[0] = {1046, 70}; t[1] = {0, 110}; return 2;
    case Sound::WifiOn: t[0] = {660, 80}; t[1] = {990, 80}; t[2] = {1320, 80}; return 3;
    case Sound::WifiOff: t[0] = {1320, 80}; t[1] = {990, 80}; t[2] = {660, 80}; return 3;
    case Sound::PowerOff: t[0] = {880, 150}; t[1] = {660, 150}; t[2] = {440, 300}; return 3;
    case Sound::Find: t[0] = {1760, 100}; t[1] = {0, 80}; t[2] = {1760, 100}; t[3] = {0, 80}; t[4] = {1760, 300}; return 5;
  }
  return 0;
}

void writeTone(const Tone& t) {
  static int16_t buf[256];
  const int total = kRate * t.ms / 1000;
  const int fade = kRate / 200;   // 5 ms ramps avoid clicks
  for (int done = 0; done < total;) {
    const int n = min(256, total - done);
    for (int i = 0; i < n; ++i) {
      const int k = done + i;
      float env = 1.0f;
      if (k < fade) env = float(k) / fade;
      if (total - k < fade) env = float(total - k) / fade;
      buf[i] = t.hz ? int16_t(9000 * env * sinf(2 * PI * t.hz * k / kRate)) : 0;
    }
    size_t written = 0;
    i2s_write(kPort, buf, n * sizeof(int16_t), &written, portMAX_DELAY);
    done += n;
  }
}

void task(void*) {
  Request r;
  Tone tones[6];
  for (;;) {
    if (xQueueReceive(g_queue, &r, portMAX_DELAY) != pdTRUE) continue;
    digitalWrite(PIN_AMP_SD, HIGH);            // amp on only while sound plays
    i2s_start(kPort);
    for (;;) {
      const int n = pattern(r.sound, tones);
      for (int rep = 0; rep < r.repeat; ++rep)
        for (int i = 0; i < n; ++i) writeTone(tones[i]);
      if (xQueueReceive(g_queue, &r, 0) != pdTRUE) break;
    }
    writeTone({0, 40});                        // flush the DMA buffers with silence
    i2s_stop(kPort);
    digitalWrite(PIN_AMP_SD, LOW);
  }
}
}  // namespace

void begin() {
  pinMode(PIN_AMP_SD, OUTPUT);
  digitalWrite(PIN_AMP_SD, LOW);
  i2s_config_t cfg = {};
  cfg.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_TX);
  cfg.sample_rate = kRate;
  cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  cfg.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;
  cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  cfg.dma_buf_count = 4;
  cfg.dma_buf_len = 256;
  cfg.tx_desc_auto_clear = true;
  i2s_driver_install(kPort, &cfg, 0, nullptr);
  i2s_pin_config_t pins = {};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;
  pins.bck_io_num = PIN_I2S_BCLK;
  pins.ws_io_num = PIN_I2S_LRC;
  pins.data_out_num = PIN_I2S_DOUT;
  pins.data_in_num = I2S_PIN_NO_CHANGE;
  i2s_set_pin(kPort, &pins);
  i2s_stop(kPort);
  g_queue = xQueueCreate(8, sizeof(Request));
  xTaskCreatePinnedToCore(task, "sounds", 3072, nullptr, 1, nullptr, 0);
}

void play(Sound s, int repeat) {
  if (!g_queue) return;
  Request r{s, repeat < 1 ? 1 : repeat};
  xQueueSend(g_queue, &r, 0);
}

}  // namespace sounds
