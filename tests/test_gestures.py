from hologram.gestures import Gesture, GestureDetector


def test_tap_fires_on_release_without_double_tap():
    g = GestureDetector(hold_s=0.6)
    assert g.press(0.0) == []
    assert g.release(0.1) == [Gesture.TAP]


def test_hold_fires_while_held_and_not_again_on_release():
    g = GestureDetector(hold_s=0.6)
    g.press(0.0)
    assert g.poll(0.5) == []
    assert g.poll(0.61) == [Gesture.HOLD]
    assert g.poll(0.9) == []
    assert g.release(1.0) == []


def test_hold_detected_at_release_if_never_polled():
    g = GestureDetector(hold_s=0.6)
    g.press(0.0)
    assert g.release(0.7) == [Gesture.HOLD]


def test_double_tap():
    g = GestureDetector(hold_s=0.8, double_tap_s=0.35)
    g.press(0.0)
    assert g.release(0.08) == []          # waiting to see if a second tap follows
    g.press(0.2)
    assert g.release(0.28) == [Gesture.DOUBLE_TAP]
    assert g.poll(2.0) == []


def test_single_tap_confirmed_after_window():
    g = GestureDetector(hold_s=0.8, double_tap_s=0.35)
    g.press(0.0)
    g.release(0.1)
    assert g.poll(0.3) == []
    assert g.poll(0.5) == [Gesture.TAP]


def test_late_second_press_flushes_first_tap():
    g = GestureDetector(hold_s=0.8, double_tap_s=0.35)
    g.press(0.0)
    g.release(0.1)
    assert g.press(1.0) == [Gesture.TAP]
    assert g.release(1.1) == []
    assert g.poll(2.0) == [Gesture.TAP]
