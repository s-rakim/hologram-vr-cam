// Battery level and power off.
#pragma once

namespace power {

void begin();
float batteryVolts();            // smoothed, from the 200k/200k divider on A0
float batteryPercent();
bool externalPower();            // charging contacts / USB connected (battery reads above 4.15 V and rising)
[[noreturn]] void powerOff();    // deep sleep; the capture button wakes the glasses

}  // namespace power
