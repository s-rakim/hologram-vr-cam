#include "gestures.h"

namespace hvr {

void GestureDetector::flushStale(uint32_t t, Gestures& out) {
  if (pendingTap_ && t - pendingAt_ > doubleTapMs_) {
    pendingTap_ = false;
    out.add(Gesture::Tap);
  }
}

Gestures GestureDetector::press(uint32_t t) {
  Gestures out;
  flushStale(t, out);
  pressed_ = true;
  holdFired_ = false;
  pressedAt_ = t;
  return out;
}

Gestures GestureDetector::release(uint32_t t) {
  Gestures out;
  if (!pressed_) return out;
  Gestures held = poll(t);  // a hold may have matured just before release
  for (int i = 0; i < held.count; ++i) out.add(held.items[i]);
  pressed_ = false;
  if (holdFired_) return out;
  if (doubleTapMs_ == 0) {
    out.add(Gesture::Tap);
  } else if (pendingTap_) {
    pendingTap_ = false;
    out.add(Gesture::DoubleTap);
  } else {
    pendingTap_ = true;
    pendingAt_ = t;
  }
  return out;
}

Gestures GestureDetector::poll(uint32_t t) {
  Gestures out;
  if (pressed_) {
    if (!holdFired_ && t - pressedAt_ >= holdMs_) {
      holdFired_ = true;
      pendingTap_ = false;
      out.add(Gesture::Hold);
    }
  } else {
    flushStale(t, out);
  }
  return out;
}

}  // namespace hvr
