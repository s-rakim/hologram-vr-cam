from datetime import datetime

import pytest

from hologram.capture import CaptureController, MockCamera, Refusal, State
from hologram.config import CaptureConfig
from hologram.privacy_led import MemoryLed, PrivacyLed
from hologram.storage import MediaStore
from hologram.thermal import ThermalGuard


class OrderCheckingCamera(MockCamera):
    """Fails the test if video starts while the privacy LED is off."""

    def __init__(self, led: MemoryLed):
        super().__init__()
        self.led = led

    def start_video(self, path):
        assert self.led.is_on, "recording started before the privacy LED was on"
        super().start_video(path)

    def stop_video(self):
        assert self.led.is_on, "LED went off before the encoder stopped"
        super().stop_video()


def make(tmp_path, clock, temp=45.0, free_mb=10_000, led=None, max_clip=60.0):
    led_out = led or MemoryLed()
    temps = {"c": temp}
    store = MediaStore(tmp_path, min_free_mb=500,
                       disk_usage=lambda p: (0, 0, int(free_mb * 1_000_000)),
                       clock=lambda: datetime(2026, 5, 1, 12, 0, 0))
    events = []
    ctl = CaptureController(OrderCheckingCamera(led_out), PrivacyLed(led_out), store,
                            ThermalGuard(lambda: temps["c"], 80, 70),
                            CaptureConfig(max_clip_seconds=max_clip), clock,
                            on_event=lambda kind, info: events.append((kind, info)))
    return ctl, led_out, temps, events


def test_video_lights_led_for_whole_recording(tmp_path, clock):
    ctl, led, _, events = make(tmp_path, clock)
    path = ctl.start_video()
    assert ctl.state is State.RECORDING and led.is_on
    clock.advance(5)
    assert ctl.stop_video() == path
    assert not led.is_on
    assert path.read_bytes() == b"mock video"
    assert [k for k, _ in events] == ["video_started", "video_stopped"]


def test_led_failure_blocks_recording(tmp_path, clock):
    ctl, led, _, events = make(tmp_path, clock, led=MemoryLed(fail=True))
    assert ctl.start_video() is None
    assert ctl.state is State.IDLE
    assert events == [("refused", Refusal.LED_FAULT)]


def test_clip_length_is_capped(tmp_path, clock):
    ctl, led, _, events = make(tmp_path, clock, max_clip=60)
    ctl.start_video()
    clock.advance(59)
    ctl.tick()
    assert ctl.state is State.RECORDING
    clock.advance(1.5)
    ctl.tick()
    assert ctl.state is State.IDLE and not led.is_on
    assert events[-1][1][1] == "max_length"


def test_overheating_stops_and_refuses_until_cool(tmp_path, clock):
    ctl, _, temps, events = make(tmp_path, clock)
    ctl.start_video()
    temps["c"] = 81
    ctl.tick()
    assert ctl.state is State.IDLE
    temps["c"] = 75                      # cooler, but not below the resume threshold
    assert ctl.start_video() is None
    assert events[-1] == ("refused", Refusal.TOO_HOT)
    temps["c"] = 65
    assert ctl.start_video() is not None


def test_storage_full_refuses_photo(tmp_path, clock):
    ctl, led, _, events = make(tmp_path, clock, free_mb=100)
    assert ctl.take_photo() is None
    assert events == [("refused", Refusal.STORAGE_FULL)]
    assert "blink x3" in led.history


def test_low_battery_saves_clip_and_blocks_capture(tmp_path, clock):
    ctl, _, _, events = make(tmp_path, clock)
    ctl.start_video()
    ctl.set_low_battery()
    assert ctl.state is State.IDLE
    assert events[-1][1][1] == "low_battery"
    assert ctl.take_photo() is None


def test_photos_get_unique_names(tmp_path, clock):
    ctl, led, _, _ = make(tmp_path, clock)
    a, b = ctl.take_photo(), ctl.take_photo()
    assert a.name == "HVR_20260501_120000.jpg"
    assert b.name == "HVR_20260501_120000_2.jpg"
    assert led.history.count("blink x2") == 2


def test_thermal_guard_validates_thresholds():
    with pytest.raises(ValueError):
        ThermalGuard(lambda: 50.0, stop_c=70, resume_c=75)


def test_audio_mux_copies_video_and_encodes_left_mic_channel(tmp_path):
    from hologram.capture import mux_command

    cmd = mux_command(tmp_path / "v.mp4", tmp_path / "a.wav", tmp_path / "out.mp4")
    assert cmd[0] == "ffmpeg" and cmd[-1].endswith("out.mp4")
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert "pan=mono|c0=c0" in cmd
