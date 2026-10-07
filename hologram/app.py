"""The glasses' main loop: inputs -> gestures -> capture / display modes.

Controls (Ray-Ban style on the capture button, plus a touch strip):
    capture button  tap          photo (or stop recording, if recording)
                    hold 0.6 s   start video
    touch strip     tap          next display mode: 360 view -> camera passthrough -> off
                    double tap   recentre the view (straight ahead = where you look now)
                    hold 0.8 s   display sleep / wake
"""
from __future__ import annotations

import logging
import queue
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from enum import Enum

import numpy as np

from . import quaternion as qt
from .capture import CaptureController, State
from .config import Config
from .fusion import HeadTracker
from .gestures import Gesture, GestureDetector
from .hardware import Hardware
from .imageio import load_image
from .privacy_led import PrivacyLed
from .render import PanoramaRenderer, PassthroughRenderer, draw_rec_indicator, grid_world
from .storage import MediaStore
from .thermal import ThermalGuard

log = logging.getLogger(__name__)


class Mode(Enum):
    PANORAMA = "panorama"
    PASSTHROUGH = "passthrough"
    OFF = "off"


MODE_CYCLE = (Mode.PANORAMA, Mode.PASSTHROUGH, Mode.OFF)


def system_poweroff() -> None:
    subprocess.run(["sudo", "systemctl", "poweroff"], check=False)


class HologramApp:
    def __init__(self, cfg: Config, hw: Hardware, clock: Callable[[], float] = time.monotonic,
                 shutdown: Callable[[], None] | None = None) -> None:
        self.cfg = cfg
        self.hw = hw
        self.clock = clock
        self.shutdown = shutdown
        self.store = MediaStore(cfg.capture.media_dir, cfg.capture.min_free_mb)
        self.thermal = ThermalGuard(hw.read_temperature, cfg.thermal.stop_recording_c, cfg.thermal.resume_c)
        self.led = PrivacyLed(hw.led)
        self.history: deque[tuple[str, object]] = deque(maxlen=200)
        self.capture = CaptureController(hw.camera, self.led, self.store, self.thermal, cfg.capture,
                                         clock, self._on_capture_event)
        self.tracker = HeadTracker(cfg.tracking.beta)
        self.button = GestureDetector(hold_s=0.6)
        self.touch = GestureDetector(hold_s=0.8, double_tap_s=0.35)
        self.mode = Mode(cfg.display.start_mode)
        self._awake_mode = self.mode if self.mode is not Mode.OFF else Mode.PANORAMA
        self.events: queue.SimpleQueue[tuple[str, bool, float]] = queue.SimpleQueue()
        self.running = True
        self.poweroff_requested = False
        self._blanked = False
        self._panorama: PanoramaRenderer | None = None
        self._passthrough: PassthroughRenderer | None = None
        hw.bind_inputs(self.on_button, self.on_touch, self.on_low_battery)

    # -- inputs (may be called from GPIO threads) ---------------------------------
    def on_button(self, pressed: bool) -> None:
        self.events.put(("button", pressed, self.clock()))

    def on_touch(self, pressed: bool) -> None:
        self.events.put(("touch", pressed, self.clock()))

    def on_low_battery(self) -> None:
        self.events.put(("low_battery", True, self.clock()))

    def _on_capture_event(self, kind: str, info: object) -> None:
        log.info("%s: %s", kind, info)
        self.history.append((kind, info))

    # -- gesture handling -------------------------------------------------------------
    def _button_gesture(self, g: Gesture) -> None:
        recording = self.capture.state is State.RECORDING
        if g is Gesture.TAP:
            if recording:
                self.capture.stop_video()
            else:
                self.capture.take_photo()
        elif g is Gesture.HOLD and not recording:
            self.capture.start_video()

    def _touch_gesture(self, g: Gesture) -> None:
        if g is Gesture.TAP:
            self.set_mode(MODE_CYCLE[(MODE_CYCLE.index(self.mode) + 1) % len(MODE_CYCLE)])
        elif g is Gesture.DOUBLE_TAP:
            self.tracker.recenter()
            self.history.append(("recentered", None))
        elif g is Gesture.HOLD:
            self.set_mode(self._awake_mode if self.mode is Mode.OFF else Mode.OFF)

    def set_mode(self, mode: Mode) -> None:
        if mode is not Mode.OFF:
            self._awake_mode = mode
        self.mode = mode
        self._blanked = False
        self.history.append(("mode", mode.value))

    def step(self) -> None:
        """Handle pending input and housekeeping. Cheap; call every frame."""
        for name, pressed in self.hw.display.poll_keys():
            if name == "quit":
                self.running = False
            elif name == "low_battery":
                if pressed:
                    self.on_low_battery()
            elif name == "button":
                self.on_button(pressed)
            elif name == "touch":
                self.on_touch(pressed)

        while True:
            try:
                source, pressed, t = self.events.get_nowait()
            except queue.Empty:
                break
            if source == "low_battery":
                self._low_battery()
                continue
            detector, handler = ((self.button, self._button_gesture) if source == "button"
                                 else (self.touch, self._touch_gesture))
            for g in (detector.press(t) if pressed else detector.release(t)):
                handler(g)

        now = self.clock()
        for g in self.button.poll(now):
            self._button_gesture(g)
        for g in self.touch.poll(now):
            self._touch_gesture(g)
        self.capture.tick()

    def _low_battery(self) -> None:
        if self.capture.low_battery:
            return
        log.warning("battery low: saving and shutting down")
        self.capture.set_low_battery()
        self.led.warn()
        self.history.append(("low_battery", None))
        if self.cfg.power.shutdown_on_low_battery and self.shutdown is not None:
            self.poweroff_requested = True    # close() powers off once the clip is saved
            self.running = False

    # -- rendering --------------------------------------------------------------------
    def eye_size(self) -> tuple[int, int]:
        w, h = self.cfg.display.size
        s = self.cfg.display.render_scale
        return max(8, int(w / 2 * s)), max(8, int(h * s))

    def _panorama_renderer(self) -> PanoramaRenderer:
        if self._panorama is None:
            d = self.cfg.display
            pano = load_image(d.panorama) if d.panorama else grid_world()
            self._panorama = PanoramaRenderer(pano, *self.eye_size(), d.eye_fov_deg, d.k1, d.k2, d.lens_center_shift)
        return self._panorama

    def _passthrough_renderer(self, frame: np.ndarray) -> PassthroughRenderer:
        h, w = frame.shape[:2]
        r = self._passthrough
        if r is None or (r.src_w, r.src_h) != (w, h):
            d = self.cfg.display
            r = self._passthrough = PassthroughRenderer(w, h, *self.eye_size(), d.k1, d.k2,
                                                        d.lens_center_shift, d.passthrough_zoom)
        return r

    def render(self) -> np.ndarray | None:
        """Next side-by-side frame, or None when the display is off."""
        if self.mode is Mode.OFF:
            return None
        if self.mode is Mode.PANORAMA:
            rotation = np.array(qt.to_matrix(self.tracker.orientation()), dtype=np.float32)
            frame = self._panorama_renderer().render(rotation)
        else:
            src = self.hw.camera.preview_frame()
            if src is None:
                return None
            frame = self._passthrough_renderer(src).render(src)
        if self.capture.state is State.RECORDING:
            frame = draw_rec_indicator(frame, self.capture.elapsed())
        return frame

    # -- loops ------------------------------------------------------------------------
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
        bias = self.tracker.calibrate(samples)
        log.info("gyro bias (rad/s): %.4f %.4f %.4f", *bias)
        while self.running:
            t0 = self.clock()
            try:
                s = imu.read()
            except OSError as err:          # a loose I2C wire should not kill the glasses
                log.warning("IMU read failed: %s", err)
                time.sleep(0.1)
                continue
            self.tracker.update(s.gyro, s.accel, t0)
            time.sleep(max(0.0, period - (self.clock() - t0)))

    def run(self) -> None:
        threading.Thread(target=self.track_forever, name="imu", daemon=True).start()
        frame_period = 1.0 / self.cfg.display.fps
        black = np.zeros((self.cfg.display.size[1], self.cfg.display.size[0], 3), np.uint8)
        log.info("running: mode=%s, media in %s", self.mode.value, self.store.root)
        try:
            while self.running:
                t0 = self.clock()
                self.step()
                frame = self.render()
                if frame is not None:
                    self.hw.display.show(frame)
                elif not self._blanked:
                    self.hw.display.show(black)   # blank the OLEDs once when switching off
                    self._blanked = True
                time.sleep(max(0.0, frame_period - (self.clock() - t0)))
        except KeyboardInterrupt:
            pass
        finally:
            self.close()

    def close(self) -> None:
        self.running = False
        self.capture.close()
        self.hw.display.close()
        if self.poweroff_requested and self.shutdown is not None:
            self.shutdown()
