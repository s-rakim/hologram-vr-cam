// Turn raw press/release edges into tap, double-tap and hold gestures.
// Pure logic with caller-supplied millisecond timestamps (host-testable).
#pragma once
#include <cstdint>

namespace hvr {

enum class Gesture : uint8_t { Tap, DoubleTap, Hold };

struct Gestures {
  Gesture items[2];
  int count = 0;
  void add(Gesture g) { if (count < 2) items[count++] = g; }
};

class GestureDetector {
 public:
  // doubleTapMs = 0 disables double taps so a tap fires on release with no delay.
  explicit GestureDetector(uint32_t holdMs = 600, uint32_t doubleTapMs = 0)
      : holdMs_(holdMs), doubleTapMs_(doubleTapMs) {}

  Gestures press(uint32_t t);
  Gestures release(uint32_t t);
  Gestures poll(uint32_t t);
  bool pressed() const { return pressed_; }

 private:
  void flushStale(uint32_t t, Gestures& out);
  uint32_t holdMs_, doubleTapMs_;
  bool pressed_ = false;
  bool holdFired_ = false;
  bool pendingTap_ = false;
  uint32_t pressedAt_ = 0;
  uint32_t pendingAt_ = 0;
};

}  // namespace hvr
