"""The VR helmet: the printed shell, the optics inside it, and the software that runs it."""
import math
import wave
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from cad import helmet as H
from cad.products import BY_KEY
from cad.products import vr as vr_model
from hologram import quaternion as qt
from hologram.vr import app as app_module
from hologram.vr.app import Mode, VrApp
from hologram.vr.config import VrConfig, load_config
from hologram.vr.hardware import build_mock

ROOT = Path(__file__).resolve().parent.parent
VR = BY_KEY["vr"]
OPTICS = vr_model.OPTICS
PRINT_BED_MM = 250.0


def head_points() -> np.ndarray:
    """A 99th-percentile-ish adult head (ellipsoid, 206 x 156 x 256 mm) above the jaw line."""
    centre, axes = np.array([0.0, -92.0, 5.0]), np.array([78.0, 103.0, 128.0])
    th, ph = np.meshgrid(np.linspace(0, 2 * np.pi, 121), np.linspace(-np.pi / 2, np.pi / 2, 61))
    d = np.stack([np.cos(ph) * np.cos(th), np.cos(ph) * np.sin(th), np.sin(ph)], -1)
    pts = centre + d * axes
    return pts[pts[..., 2] > -105]


# -- the printed shell --------------------------------------------------------------------------
@pytest.mark.parametrize("part_id", sorted(VR.meshes))
def test_smooth_meshes_are_watertight_and_printable(part_id):
    verts, tris = VR.meshes[part_id]()
    assert H.is_watertight(tris), part_id
    assert H.signed_volume(verts, tris) > 0, part_id            # normals face outward
    v = np.array(verts)
    assert (v.max(0) - v.min(0)).max() <= PRINT_BED_MM, part_id  # fits a 256 mm printer


def test_helmet_has_f1_proportions():
    env = VR.envelope()
    shell = np.concatenate([np.array(H.section_mesh(s, 6.0)[0]) for s in H.SECTIONS])
    length, width, height = (shell.max(0) - shell.min(0))[[1, 0, 2]]
    assert 300 < length < 360 and 230 < width < 260 and 290 < height < 330
    port_mm = math.radians(H.PORT_PHI[1] - H.PORT_PHI[0]) * H.FRONT
    assert port_mm < 55                                           # a narrow eye slot, not an open face
    assert env.depth < 400                                        # with the rear pod and spoiler


def test_the_head_fits_with_room_for_the_liner():
    assert H.inside_margin(head_points()).min() > vr_model.LINER + 5


def test_lower_edge_is_level_from_the_side():
    theta = np.radians(np.linspace(0, 360, 73))
    z = H.CENTER[2] + H.radius(theta, H.bottom_phi(theta)) * np.sin(H.bottom_phi(theta))
    assert np.allclose(z, H.bottom_z(theta), atol=0.05)


def test_stepped_solids_follow_the_mesh():
    s = H.SECTIONS[0]
    mesh = np.array(H.section_mesh(s)[0])
    lo, hi = zip(*[sol.bbox() for sol in H.section_solids(s)])
    lo, hi = np.min(lo, axis=0), np.max(hi, axis=0)
    assert np.allclose(lo[:2], mesh.min(0)[:2], atol=6) and np.allclose(hi[:2], mesh.max(0)[:2], atol=6)


# -- optics inside the shell ------------------------------------------------------------------------
def test_cad_uses_the_softwares_optics():
    assert OPTICS == VrConfig().reflector


@pytest.mark.parametrize("side", [1, -1])
def test_mirrors_and_panels_fit_inside_the_shell(side):
    front, back = vr_model.mirror_grids(side)
    assert H.inside_margin(front).min() > 4.0
    assert H.inside_margin(back).min() > 1.5
    for grow, offsets in ((1.5, (0.0, -vr_model.PANEL_THICK)), (4.0, (-3.0, -6.0))):
        a, b = vr_model._plate(side, grow, offsets)
        assert H.inside_margin(a).min() > 3.0 and H.inside_margin(b).min() > 3.0


@pytest.mark.parametrize("side", [1, -1])
def test_optics_clear_the_face(side):
    front, _ = vr_model.mirror_grids(side)
    p = front.reshape(-1, 3)
    assert (side * p[:, 0] > 1.0).all()                         # each mirror stays on its own side
    assert (p[:, 1] > OPTICS.forward_min - 1).all()             # in front of the eyes
    nose = (np.abs(p[:, 0]) < 16) & (p[:, 2] < -5) & (p[:, 2] > -50)
    assert not nose.any() or p[nose, 1].min() > 30              # clear of the nose tip
    corners = OPTICS.panel_corners(side)
    assert corners[:, 1].min() > 20 and corners[:, 2].min() > 10


def test_mirror_covers_every_pixel_the_eye_can_see():
    t = OPTICS.ray_table(64, 64)
    r = t.rays[t.valid]
    az = np.degrees(np.arctan2(r[:, 0], r[:, 1]))
    el = np.degrees(np.arcsin(r[:, 2]))
    (a0, a1), (e0, e1) = OPTICS.mirror_az_deg, OPTICS.mirror_el_deg
    assert az.min() >= a0 - 1e-6 and az.max() <= a1 + 1e-6 and el.min() >= e0 - 1e-6 and el.max() <= e1 + 1e-6
    assert t.valid.mean() > 0.85


# -- software matches the hardware ----------------------------------------------------------------
def test_software_pins_match_the_wiring():
    pins = VrConfig().pins
    assert VR.gpio_of("controls", "MODE") == pins.mode_button
    assert VR.gpio_of("controls", "ACTION") == pins.action_button
    assert VR.gpio_of("controls", "VOL-") == pins.volume_down
    assert VR.gpio_of("controls", "VOL+") == pins.volume_up
    assert VR.gpio_of("dswitch", "CTRL") == pins.display_power
    assert VR.gpio_of("imu", "INT") == pins.imu_interrupt


def test_buttons_avoid_the_i2c_and_i2s_pins():
    pins = VrConfig().pins
    used = {pins.mode_button, pins.action_button, pins.volume_down, pins.volume_up, pins.display_power,
            pins.imu_interrupt}
    assert len(used) == 6 and not used & {2, 3, 18, 19, 21}


def test_shipped_config_file_is_the_defaults():
    assert load_config(ROOT / "config/vr.toml") == VrConfig()


def test_config_rejects_typos_and_bad_values(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[display]\nopticks = 'lens'\n")
    with pytest.raises(ValueError, match="unknown config key display.opticks"):
        load_config(bad)
    bad.write_text("[display]\noptics = 'hologram'\n")
    with pytest.raises(ValueError):
        load_config(bad)
    ok = tmp_path / "ok.toml"
    ok.write_text("[display]\noptics = 'lens'\n[lens]\nfov_deg = 100\n")
    assert load_config(ok).optics().fov_deg == 100.0


# -- the app, on mock hardware --------------------------------------------------------------------
class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def make_app(tmp_path, clock, **display):
    cfg = VrConfig()
    cfg = replace(cfg, display=replace(cfg.display, render_scale=0.05, **display),
                  media=replace(cfg.media, panoramas=str(tmp_path / "360"), photos=str(tmp_path / "photos")))
    hw = build_mock(cfg)
    powered = hw.keep[0]
    shutdowns = []
    app = VrApp(cfg, hw, clock=clock, shutdown=lambda: shutdowns.append(True))
    return app, hw, powered, shutdowns


def tap(app, clock, button, hold=0.1):
    app.press(button, True)
    app.step()
    clock.t += hold
    app.press(button, False)
    app.step()


def test_mode_button_cycles_modes_and_hold_powers_off(tmp_path):
    clock = Clock()
    app, hw, _, shutdowns = make_app(tmp_path, clock)
    assert app.mode is Mode.PANORAMA
    tap(app, clock, "mode")
    assert app.mode is Mode.GALLERY and app.audio.played[-1] == "mode"
    tap(app, clock, "mode")
    assert app.mode is Mode.PASSTHROUGH and hw.camera.running        # camera only powered in passthrough
    tap(app, clock, "mode")
    assert app.mode is Mode.PANORAMA and not hw.camera.running
    tap(app, clock, "mode", hold=2.5)
    assert not app.running and app.poweroff_requested
    app.close()
    assert shutdowns == [True]


def test_volume_buttons(tmp_path):
    clock = Clock()
    app, *_ = make_app(tmp_path, clock)
    start = app.audio.volume
    tap(app, clock, "volume_up")
    tap(app, clock, "volume_up")
    assert app.audio.volume == pytest.approx(start + 0.10)
    tap(app, clock, "volume_down")
    assert app.audio.volume == pytest.approx(start + 0.05)
    assert ("volume", app.audio.volume) in app.history


def test_still_view_is_not_rerendered_and_sleep_saves_power(tmp_path):
    clock = Clock()
    app, _, powered, _ = make_app(tmp_path, clock)
    app.tracking_live = True                                          # as if the IMU thread were running
    frame = app.render()
    w, h = app.eye_size()
    assert frame.shape == (h, 2 * w, 4)
    assert app.render() is None                                       # nothing moved
    app.tracker.set_orientation(qt.yaw_quat(math.radians(5)))
    assert app.render() is not None
    app.step()                                                        # the head moved just now ...
    clock.t += app.cfg.display.sleep_after_still_s + 1                # ... then stayed still
    app.step()
    assert app.asleep and powered[-1] is False and app.render() is None
    app.tracker.set_orientation(qt.yaw_quat(math.radians(20)))
    app.step()
    assert not app.asleep and powered[-1] is True and app.audio.played[-1] == "wake"


def test_action_hold_recentres(tmp_path):
    clock = Clock()
    app, *_ = make_app(tmp_path, clock)
    app.tracker.set_orientation(qt.yaw_quat(math.radians(40)))
    tap(app, clock, "action", hold=1.0)
    assert abs(math.degrees(qt.yaw(app.tracker.orientation()))) < 1e-6
    assert ("recentred", None) in app.history


def test_panorama_sound_plays_around_you_only_in_the_360_view(tmp_path, monkeypatch):
    pano_dir = tmp_path / "360"
    pano_dir.mkdir()
    (pano_dir / "beach.jpg").write_bytes(b"")
    with wave.open(str(pano_dir / "beach.wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(bytes(4 * 4800))
    monkeypatch.setattr(app_module, "load_image", lambda path: np.zeros((64, 128, 3), np.uint8))
    clock = Clock()
    app, *_ = make_app(tmp_path, clock)
    app.tracking_live = True
    assert app.render() is not None
    assert app.audio.scene == pano_dir / "beach.wav"
    tap(app, clock, "mode")                                           # gallery: no scene sound
    assert app.audio.scene is None
    tap(app, clock, "mode")
    tap(app, clock, "mode")
    assert app.audio.scene == pano_dir / "beach.wav"
    clock.t += app.cfg.display.sleep_after_still_s + 1                # put down: silence too
    app.step()
    assert app.asleep and app.audio.scene is None


def test_low_battery_warns_then_shuts_down(tmp_path):
    clock = Clock()
    app, hw, _, _ = make_app(tmp_path, clock)
    hw.gauge.level = 9.0
    app.step()
    assert ("battery_warning", 9.0) in app.history and app.running
    hw.gauge.level = 2.0
    clock.t += 31
    app.step()
    assert not app.running and app.poweroff_requested


def test_passthrough_renders_the_camera(tmp_path):
    clock = Clock()
    app, *_ = make_app(tmp_path, clock, start_mode="passthrough")
    frame = app.render()
    assert frame is not None and frame.any()


def test_without_head_tracking_the_helmet_never_sleeps(tmp_path):
    clock = Clock()
    app, _, powered, _ = make_app(tmp_path, clock)
    assert not app.tracking_live                                      # no IMU thread in the tests
    clock.t += app.cfg.display.sleep_after_still_s * 3
    app.step()
    assert not app.asleep and False not in powered


def test_any_button_wakes_the_helmet_without_acting(tmp_path):
    clock = Clock()
    app, _, powered, _ = make_app(tmp_path, clock)
    app.tracking_live = True
    clock.t += app.cfg.display.sleep_after_still_s + 1
    app.step()
    assert app.asleep
    mode = app.mode
    tap(app, clock, "mode")
    assert not app.asleep and powered[-1] is True and app.mode is mode   # woke up, didn't change mode
    tap(app, clock, "mode")
    assert app.mode is not mode                                       # the next tap works normally


def test_unreadable_images_are_skipped(tmp_path, monkeypatch):
    pano_dir = tmp_path / "360"
    pano_dir.mkdir()
    for name in ("._beach.jpg", "broken.jpg", "good.jpg"):
        (pano_dir / name).write_bytes(b"")

    def fake_load(path):
        if path.name == "broken.jpg":
            raise OSError("image file is truncated")
        return np.full((64, 128, 3), 200, np.uint8)

    monkeypatch.setattr(app_module, "load_image", fake_load)
    clock = Clock()
    app, *_ = make_app(tmp_path, clock)
    assert [p.name for p in app._panoramas] == ["broken.jpg", "good.jpg"]   # hidden files never listed
    frame = app.render()
    assert frame is not None and frame[..., :3].max() == 200
    assert [p.name for p in app._panoramas] == ["good.jpg"]


def test_photos_copied_later_show_up(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "load_image", lambda path: np.zeros((32, 32, 3), np.uint8))
    clock = Clock()
    app, *_ = make_app(tmp_path, clock)
    assert app._photos == []
    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "HVR_20261011_143012_0042.jpg").write_bytes(b"")
    tap(app, clock, "mode")                                           # into gallery
    assert app.mode is Mode.GALLERY and [p.name for p in app._photos] == ["HVR_20261011_143012_0042.jpg"]


def test_heat_halves_the_frame_rate(tmp_path, monkeypatch):
    clock = Clock()
    app, *_ = make_app(tmp_path, clock, fps=30)
    sleeps = []
    monkeypatch.setattr(app_module.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(app.thermal, "update", lambda: True)
    monkeypatch.setattr(app, "track_forever", lambda: None)
    calls = {"n": 0}

    def step():
        calls["n"] += 1
        if calls["n"] > 3:
            app.running = False

    monkeypatch.setattr(app, "step", step)
    monkeypatch.setattr(app, "render", lambda: None)
    app.run()
    assert sleeps and max(sleeps) == pytest.approx(1 / 15, rel=1e-3)   # 30 fps -> 15 fps when hot
