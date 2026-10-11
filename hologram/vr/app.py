"""The VR helmet's main loop: buttons -> modes, head tracking -> stereo frames and sound.

Controls (control pod on the left of the chin bar):
    mode button    tap          next mode: 360 view -> photo gallery -> camera passthrough
                   hold 2 s     power off
    action button  tap          next panorama (360 view) or next photo (gallery)
                   hold 0.6 s   recentre: straight ahead = where you are looking now
    volume - / +   tap          ear-cup volume down / up

Sound: a panorama ``beach.jpg`` with a ``beach.wav`` beside it plays that
sound around you, fixed to the scene, through the ear cups (see audio.py).

Power saving: a still view is not re-rendered, the passthrough camera is only
powered in passthrough mode, and the displays and scene sound switch off
when the helmet has been sitting still (put down) for ``sleep_after_still_s``.
"""
from __future__ import annotations

import logging
import math
import queue
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from enum import Enum
from pathlib import Path

import numpy as np

from .. import quaternion as qt
from ..fusion import HeadTracker
from ..gestures import Gesture, GestureDetector
from ..imageio import load_image
from ..thermal import ThermalGuard
from .audio import AudioEngine, scene_sound_for
from .config import VrConfig
from .hardware import BUTTONS, VrHardware
from .optics import RayTable, stereo_tables
from .render import PanoramaRenderer, PassthroughRenderer, VirtualScreenRenderer, grid_world

log = logging.getLogger(__name__)
BATTERY_POLL_S = 30.0
IMAGE_TYPES = {".jpg", ".jpeg", ".png"}


class Mode(Enum):
    PANORAMA = "panorama"
    GALLERY = "gallery"
    PASSTHROUGH = "passthrough"


def system_poweroff() -> None:
    subprocess.run(["sudo", "systemctl", "poweroff"], check=False)


def angle_between(a: qt.Quat, b: qt.Quat) -> float:
    """Rotation angle between two orientations, degrees."""
    d = abs(sum(x * y for x, y in zip(a, b)))
    return math.degrees(2 * math.acos(min(1.0, d)))


def list_images(folder: str) -> list[Path]:
    root = Path(folder).expanduser()
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.suffix.lower() in IMAGE_TYPES)


class VrApp:
    def __init__(self, cfg: VrConfig, hw: VrHardware, clock: Callable[[], float] = time.monotonic,
                 shutdown: Callable[[], None] | None = None) -> None:
        self.cfg = cfg
        self.hw = hw
        self.clock = clock
        self.shutdown = shutdown
        self.tracker = HeadTracker(cfg.tracking.beta)
        self.thermal = ThermalGuard(hw.read_temperature, cfg.thermal.throttle_c, cfg.thermal.resume_c)
        self.audio = AudioEngine(hw.audio_sink, self.head_rotation, volume=cfg.sound.volume,
                                 pattern=cfg.sound.ear_pattern, enabled=cfg.sound.enabled)
        self.buttons = {"mode": GestureDetector(hold_s=2.0), "action": GestureDetector(hold_s=0.6),
                        "volume_down": GestureDetector(), "volume_up": GestureDetector()}
        self.handlers = {"mode": self._mode_gesture, "action": self._action_gesture,
                         "volume_down": lambda g: self._volume_gesture(g, -1),
                         "volume_up": lambda g: self._volume_gesture(g, +1)}
        self.modes = [m for m in Mode if m is not Mode.PASSTHROUGH or hw.camera is not None]
        start = Mode(cfg.display.start_mode)
        self.mode = start if start in self.modes else Mode.PANORAMA
        self.history: deque[tuple[str, object]] = deque(maxlen=500)
        self.events: queue.SimpleQueue[tuple[str, bool, float]] = queue.SimpleQueue()
        self.running = True
        self.poweroff_requested = False
        self.asleep = False
        self.battery_percent: float | None = None
        self._battery_warned = False
        self._next_battery_check = 0.0
        self._panoramas = list_images(cfg.media.panoramas)
        self._photos = list_images(cfg.media.photos)
        self._pano_index = 0
        self._photo_index = 0
        self._tables: tuple[RayTable, RayTable] | None = None
        self._renderer: PanoramaRenderer | None = None
        self._passthrough: PassthroughRenderer | None = None
        self._dirty = True
        self._last_q: qt.Quat | None = None
        self._still_ref = qt.IDENTITY
        self._still_since = clock()
        hw.bind_inputs({name: (lambda pressed, n=name: self.press(n, pressed)) for name in BUTTONS})
        self._enter(self.mode)

    def head_rotation(self) -> np.ndarray:
        return np.array(qt.to_matrix(self.tracker.orientation()), dtype=np.float32)

    # -- inputs ---------------------------------------------------------------------------
    def press(self, button: str, pressed: bool) -> None:
        """Button edge from any thread (GPIO callback, window key)."""
        self.events.put((button, pressed, self.clock()))

    def _mode_gesture(self, g: Gesture) -> None:
        if g is Gesture.TAP:
            self.set_mode(self.modes[(self.modes.index(self.mode) + 1) % len(self.modes)])
            self.audio.play("mode")
        elif g is Gesture.HOLD:
            self.audio.play("power_off")
            self.history.append(("power_off", None))
            self.poweroff_requested = self.shutdown is not None
            self.running = False

    def _action_gesture(self, g: Gesture) -> None:
        if g is Gesture.TAP:
            if self.mode is Mode.PANORAMA and len(self._panoramas) > 1:
                self._pano_index = (self._pano_index + 1) % len(self._panoramas)
                self._renderer = None
            elif self.mode is Mode.GALLERY and self._photos:
                self._photo_index = (self._photo_index + 1) % len(self._photos)
                self._renderer = None
            self._dirty = True
            self.history.append(("next", self.mode.value))
        elif g is Gesture.HOLD:
            self.tracker.recenter()
            self._dirty = True
            self.audio.play("recentred")
            self.history.append(("recentred", None))

    def _volume_gesture(self, g: Gesture, direction: int) -> None:
        if g is Gesture.TAP:
            v = self.audio.step_volume(direction * self.cfg.sound.volume_step)
            self.history.append(("volume", v))

    # -- modes ----------------------------------------------------------------------------
    def _enter(self, mode: Mode) -> None:
        if self.hw.camera is not None:   # the passthrough camera is only powered when it is used
            if mode is Mode.PASSTHROUGH:
                self.hw.camera.start()
            else:
                self.hw.camera.stop()
        self._update_scene_sound()

    def _update_scene_sound(self) -> None:
        sound = None
        if not self.asleep and self.mode is Mode.PANORAMA and self._panoramas:
            sound = scene_sound_for(self._panoramas[self._pano_index])
        if sound != self.audio.scene:
            self.audio.set_scene(sound)

    def set_mode(self, mode: Mode) -> None:
        self.mode = mode
        self._renderer = None
        self._dirty = True
        self._enter(mode)
        self.history.append(("mode", mode.value))

    # -- sleep / battery ----------------------------------------------------------------------
    def _update_sleep(self, q: qt.Quat) -> None:
        now = self.clock()
        if angle_between(q, self._still_ref) > self.cfg.display.wake_threshold_deg:
            self._still_ref, self._still_since = q, now
            if self.asleep:
                self.asleep = False
                self.hw.set_display_power(True)
                self._enter(self.mode)
                self._dirty = True
                self.audio.play("wake")
                self.history.append(("wake", None))
        elif not self.asleep and now - self._still_since > self.cfg.display.sleep_after_still_s:
            self.asleep = True
            self.hw.set_display_power(False)
            if self.hw.camera is not None:
                self.hw.camera.stop()
            self._update_scene_sound()
            self.history.append(("sleep", None))

    def _check_battery(self) -> None:
        now = self.clock()
        if self.hw.gauge is None or now < self._next_battery_check:
            return
        self._next_battery_check = now + BATTERY_POLL_S
        try:
            self.battery_percent = self.hw.gauge.percent()
        except OSError as err:
            log.warning("fuel gauge read failed: %s", err)
            return
        if self.battery_percent <= self.cfg.power.shutdown_percent and self.cfg.power.shutdown_on_low_battery:
            self.audio.play("battery_low")
            self.history.append(("low_battery", self.battery_percent))
            self.poweroff_requested = self.shutdown is not None
            self.running = False
        elif self.battery_percent <= self.cfg.power.warn_percent and not self._battery_warned:
            self._battery_warned = True
            self.audio.play("battery_low")
            self.history.append(("battery_warning", self.battery_percent))

    def step(self) -> None:
        for name, pressed in self.hw.display.poll_keys():
            if name == "quit":
                self.running = False
            elif name in self.buttons:
                self.press(name, pressed)
        while True:
            try:
                name, pressed, t = self.events.get_nowait()
            except queue.Empty:
                break
            detector = self.buttons[name]
            for g in (detector.press(t) if pressed else detector.release(t)):
                self.handlers[name](g)
        now = self.clock()
        for name, detector in self.buttons.items():
            for g in detector.poll(now):
                self.handlers[name](g)
        self._update_sleep(self.tracker.orientation())
        self._check_battery()

    # -- rendering ----------------------------------------------------------------------------
    def eye_size(self) -> tuple[int, int]:
        return self.cfg.display.eye_size()

    def tables(self) -> tuple[RayTable, RayTable]:
        if self._tables is None:
            self._tables = stereo_tables(self.cfg.optics(), *self.eye_size())
        return self._tables

    def _scene(self) -> PanoramaRenderer:
        if self._renderer is None:
            m = self.cfg.media
            if self.mode is Mode.GALLERY:
                photo = load_image(self._photos[self._photo_index]) if self._photos else _no_photos_card()
                self._renderer = VirtualScreenRenderer(grid_world(), photo, self.tables(),
                                                       width=m.screen_width_m, distance=m.screen_distance_m)
            else:
                pano = load_image(self._panoramas[self._pano_index]) if self._panoramas else grid_world()
                self._renderer = PanoramaRenderer(pano, self.tables())
                self._update_scene_sound()
        return self._renderer

    def render(self) -> np.ndarray | None:
        """The next side-by-side RGBX frame, or None when nothing on screen needs to change."""
        if self.asleep:
            return None
        if self.mode is Mode.PASSTHROUGH and self.hw.camera is not None:
            src = self.hw.camera.frame()
            if src is None:
                return None
            h, w = src.shape[:2]
            r = self._passthrough
            if r is None or (r.src_w, r.src_h) != (w, h):
                p = self.cfg.passthrough
                r = self._passthrough = PassthroughRenderer(w, h, self.tables(), p.hfov_deg, p.zoom)
            return r.render(src)
        q = self.tracker.orientation()
        moved = self._last_q is None or angle_between(q, self._last_q) > self.cfg.display.motion_threshold_deg
        if not (moved or self._dirty):
            return None                       # still head, static scene: keep the last frame, save power
        self._last_q, self._dirty = q, False
        return self._scene().render(np.array(qt.to_matrix(q), dtype=np.float32))

    # -- loops ----------------------------------------------------------------------------
    def track_forever(self) -> None:
        imu = self.hw.imu
        if imu is None:
            return
        period = 1.0 / self.cfg.tracking.rate_hz
        samples = []
        for _ in range(self.cfg.tracking.calibration_samples):
            s = imu.read()
            samples.append((s.gyro, s.accel))
            time.sleep(period)
        self.tracker.calibrate(samples)
        while self.running:
            t0 = self.clock()
            try:
                s = imu.read()
            except OSError as err:          # a loose I2C wire should not kill the headset
                log.warning("IMU read failed: %s", err)
                time.sleep(0.1)
                continue
            self.tracker.update(s.gyro, s.accel, t0)
            time.sleep(max(0.0, period - (self.clock() - t0)))

    def run(self) -> None:
        threading.Thread(target=self.track_forever, name="imu", daemon=True).start()
        self.audio.start()
        log.info("running: mode=%s, %d panoramas, %d photos", self.mode.value, len(self._panoramas), len(self._photos))
        try:
            while self.running:
                t0 = self.clock()
                self.step()
                hot = self.thermal.update()
                fps = 2 if self.asleep else (30 if hot else self.cfg.display.fps)   # throttle when hot
                frame = self.render()
                if frame is not None:
                    self.hw.display.show(frame)
                time.sleep(max(0.0, 1.0 / fps - (self.clock() - t0)))
        except KeyboardInterrupt:
            pass
        finally:
            self.close()

    def close(self) -> None:
        self.running = False
        if self.hw.camera is not None:
            self.hw.camera.stop()
        if self.poweroff_requested:
            time.sleep(0.8)                  # let the power-off sound finish
        self.audio.close()
        self.hw.display.close()
        if self.poweroff_requested and self.shutdown is not None:
            self.shutdown()


def _no_photos_card() -> np.ndarray:
    """Placeholder screen when no photos have been copied over yet."""
    card = np.full((540, 960, 3), (34, 38, 48), np.uint8)
    card[250:290, 200:760] = (80, 140, 240)
    return card
