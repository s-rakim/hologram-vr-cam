#include "battery.h"

namespace hvr {

namespace {
struct Point { float volts, percent; };
// Typical resting curve for a single LiPo cell.
const Point kCurve[] = {
    {3.30f, 0.0f},  {3.40f, 5.0f},  {3.55f, 10.0f}, {3.65f, 20.0f}, {3.70f, 30.0f}, {3.75f, 40.0f},
    {3.80f, 50.0f}, {3.85f, 60.0f}, {3.92f, 70.0f}, {4.00f, 80.0f}, {4.10f, 90.0f}, {4.20f, 100.0f},
};
const int kPoints = sizeof(kCurve) / sizeof(kCurve[0]);
}  // namespace

float lipoPercent(float volts) {
  if (volts <= kCurve[0].volts) return 0.0f;
  if (volts >= kCurve[kPoints - 1].volts) return 100.0f;
  for (int i = 1; i < kPoints; ++i) {
    if (volts <= kCurve[i].volts) {
      const Point& a = kCurve[i - 1];
      const Point& b = kCurve[i];
      return a.percent + (b.percent - a.percent) * (volts - a.volts) / (b.volts - a.volts);
    }
  }
  return 100.0f;
}

int batteryBars(float percent) {
  int bars = static_cast<int>(percent / 25.0f) + 1;
  return bars < 1 ? 1 : (bars > 4 ? 4 : bars);
}

}  // namespace hvr
