// Feedback sounds through the MAX98357A amp (the glasses have no screen).
#pragma once

namespace sounds {

enum class Sound { Boot, Photo, RecordStart, RecordStop, Refused, BatteryLow, Beep, WifiOn, WifiOff, PowerOff, Find };

void begin();
// Queue a sound (non-blocking). `repeat` plays it several times (battery bars).
void play(Sound s, int repeat = 1);

}  // namespace sounds
