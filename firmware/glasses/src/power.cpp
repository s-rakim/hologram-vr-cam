#include "power.h"

#include <Arduino.h>
#include <driver/rtc_io.h>
#include <esp_sleep.h>

#include "battery.h"
#include "pins.h"

namespace power {

namespace {
hvr::BatteryFilter g_filter(0.05f);
float g_previous = 0;
bool g_charging = false;
}  // namespace

void begin() {
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_VBAT_SENSE, ADC_11db);
  for (int i = 0; i < 8; ++i) batteryVolts();
}

float batteryVolts() {
  const float v = analogReadMilliVolts(PIN_VBAT_SENSE) * 2.0f / 1000.0f;   // divider halves the cell voltage
  const float smooth = g_filter.update(v);
  g_charging = smooth > 4.15f && smooth >= g_previous;
  g_previous = smooth;
  return smooth;
}

float batteryPercent() { return hvr::lipoPercent(g_filter.value()); }

bool externalPower() { return g_charging; }

void powerOff() {
  digitalWrite(PIN_PRIVACY_LED, LOW);
  digitalWrite(PIN_AMP_SD, LOW);
  rtc_gpio_pullup_en(static_cast<gpio_num_t>(PIN_BUTTON));
  rtc_gpio_pulldown_dis(static_cast<gpio_num_t>(PIN_BUTTON));
  esp_sleep_enable_ext0_wakeup(static_cast<gpio_num_t>(PIN_BUTTON), 0);   // press = wake
  esp_deep_sleep_start();
}

}  // namespace power
