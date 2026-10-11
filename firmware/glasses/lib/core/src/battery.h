// LiPo state of charge from cell voltage (resting curve), with smoothing.
#pragma once

namespace hvr {

// Percent (0-100) for a single LiPo cell at rest, linear between table points.
float lipoPercent(float volts);

// 1-4 beeps for the battery check: 4 = over 75 %, 1 = under 25 %.
int batteryBars(float percent);

// Exponential moving average so load spikes (camera, SD writes) do not read as a dying battery.
class BatteryFilter {
 public:
  explicit BatteryFilter(float alpha = 0.1f) : alpha_(alpha) {}
  float update(float volts) {
    value_ = primed_ ? value_ + alpha_ * (volts - value_) : volts;
    primed_ = true;
    return value_;
  }
  float value() const { return value_; }

 private:
  float alpha_;
  float value_ = 0.0f;
  bool primed_ = false;
};

}  // namespace hvr
