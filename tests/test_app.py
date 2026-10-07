from dataclasses import replace

import pytest

from hologram.app import HologramApp, Mode
from hologram.capture import MockCamera, State
from hologram.config import Config, load_config
from hologram.display import NullDisplay
from hologram.hardware import Hardware
from hologram.privacy_led import MemoryLed


def make_app(tmp_path, clock, shutdowns=None, **display):
    cfg = Config()
    cfg = replace(cfg, capture=replace(cfg.capture, media_dir=str(tmp_path), min_free_mb=0),
                  display=replace(cfg.display, render_scale=0.05, **display))
    hw = Hardware(camera=MockCamera((64, 36)), led=MemoryLed(), imu=None, display=NullDisplay(),
                  read_temperature=lambda: 40.0, bind_inputs=lambda *a: None)
    sd = shutdowns if shutdowns is not None else []
    return HologramApp(cfg, hw, clock=clock, shutdown=lambda: sd.append(True))


def press(app, clock, which, seconds):
    getattr(app, f"on_{which}")(True)
    app.step()
    clock.advance(seconds)
    app.step()
    getattr(app, f"on_{which}")(False)
    app.step()


def test_ray_ban_style_button(tmp_path, clock):
    app = make_app(tmp_path, clock)
    press(app, clock, "button", 0.1)                     # tap = photo
    assert [k for k, _ in app.history] == ["photo"]
    press(app, clock, "button", 0.7)                     # hold = record
    assert app.capture.state is State.RECORDING and app.hw.led.is_on
    clock.advance(3)
    press(app, clock, "button", 0.1)                     # tap while recording = stop
    assert app.capture.state is State.IDLE and not app.hw.led.is_on
    assert [k for k, _ in app.history] == ["photo", "video_started", "video_stopped"]


def test_touch_cycles_modes_and_sleeps(tmp_path, clock):
    app = make_app(tmp_path, clock)
    assert app.mode is Mode.PANORAMA
    press(app, clock, "touch", 0.1)
    clock.advance(0.5)
    app.step()
    assert app.mode is Mode.PASSTHROUGH
    press(app, clock, "touch", 1.0)                       # hold = display off
    assert app.mode is Mode.OFF and app.render() is None
    press(app, clock, "touch", 1.0)                       # hold again = back on
    assert app.mode is Mode.PASSTHROUGH


def test_double_tap_recenters(tmp_path, clock):
    app = make_app(tmp_path, clock)
    press(app, clock, "touch", 0.05)
    clock.advance(0.1)
    press(app, clock, "touch", 0.05)
    assert ("recentered", None) in app.history
    assert app.mode is Mode.PANORAMA


def test_render_frames_and_rec_dot(tmp_path, clock):
    app = make_app(tmp_path, clock)
    frame = app.render()
    assert frame.shape == (54, 96, 3)
    press(app, clock, "button", 0.7)
    rec = app.render()
    assert (rec[..., 0] == 230).any()


def test_low_battery_stops_recording_and_powers_off(tmp_path, clock):
    shutdowns = []
    app = make_app(tmp_path, clock, shutdowns)
    press(app, clock, "button", 0.7)
    app.on_low_battery()
    app.step()
    assert app.capture.state is State.IDLE and not app.running
    assert shutdowns == []                 # power-off waits until everything is closed
    app.close()
    assert shutdowns == [True]


def test_config_file_overrides(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[capture]\nmax_clip_seconds = 180\n[display]\nstart_mode = "off"\nsize = [1280, 720]\n')
    cfg = load_config(p)
    assert cfg.capture.max_clip_seconds == 180.0
    assert cfg.display.size == (1280, 720)
    p.write_text("[capture]\nmax_clip = 3\n")
    with pytest.raises(ValueError, match="unknown config key capture.max_clip"):
        load_config(p)
    p.write_text("[pins]\ncapture_button = 4.5\n")
    with pytest.raises(ValueError):
        load_config(p)


def test_shipped_config_loads():
    from pathlib import Path

    cfg = load_config(Path(__file__).resolve().parent.parent / "config" / "hologram.toml")
    assert cfg == Config()   # the shipped file documents the defaults
