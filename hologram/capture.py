"""Photo and video capture: the Ray-Ban-style part of the glasses.

:class:`CaptureController` owns the rules (privacy LED, clip length cap,
thermal and storage guards); camera backends only move pixels.
"""
from __future__ import annotations

import logging
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Protocol

import numpy as np

from .config import CaptureConfig
from .privacy_led import PrivacyLed
from .storage import MediaStore
from .thermal import ThermalGuard

log = logging.getLogger(__name__)


class CameraBackend(Protocol):
    def start_video(self, path: Path) -> None: ...
    def stop_video(self) -> None: ...
    def take_photo(self, path: Path, recording: bool) -> None: ...
    def preview_frame(self) -> np.ndarray | None: ...
    def close(self) -> None: ...


class State(Enum):
    IDLE = "idle"
    RECORDING = "recording"


class Refusal(Enum):
    TOO_HOT = "too_hot"
    STORAGE_FULL = "storage_full"
    LOW_BATTERY = "low_battery"
    LED_FAULT = "privacy_led_fault"


class CaptureController:
    def __init__(self, camera: CameraBackend, led: PrivacyLed, store: MediaStore, thermal: ThermalGuard,
                 cfg: CaptureConfig, clock: Callable[[], float] = time.monotonic,
                 on_event: Callable[[str, object], None] | None = None) -> None:
        self.camera = camera
        self.led = led
        self.store = store
        self.thermal = thermal
        self.cfg = cfg
        self.clock = clock
        self.on_event = on_event or (lambda kind, info: None)
        self.state = State.IDLE
        self.low_battery = False
        self.current: Path | None = None
        self._started_at = 0.0
        self._lock = threading.RLock()

    # -- guards -------------------------------------------------------------
    def _refusal(self) -> Refusal | None:
        if self.low_battery:
            return Refusal.LOW_BATTERY
        if self.thermal.update():
            return Refusal.TOO_HOT
        if not self.store.has_space():
            return Refusal.STORAGE_FULL
        return None

    def _refuse(self, why: Refusal) -> None:
        log.warning("capture refused: %s", why.value)
        self.led.warn()
        self.on_event("refused", why)

    # -- actions ------------------------------------------------------------
    def take_photo(self) -> Path | None:
        with self._lock:
            why = self._refusal()
            if why is not None:
                self._refuse(why)
                return None
            path = self.store.new_path("photo")
            self.led.photo_flash()
            self.camera.take_photo(path, recording=self.state is State.RECORDING)
            self.on_event("photo", path)
            return path

    def start_video(self) -> Path | None:
        with self._lock:
            if self.state is State.RECORDING:
                return self.current
            why = self._refusal()
            if why is not None:
                self._refuse(why)
                return None
            try:
                self.led.set_recording(True)          # LED first: never record unannounced
            except Exception:
                log.exception("privacy LED failed; not recording")
                self.on_event("refused", Refusal.LED_FAULT)
                return None
            path = self.store.new_path("video")
            try:
                self.camera.start_video(path)
            except Exception:
                self.led.set_recording(False)
                raise
            self.state = State.RECORDING
            self.current = path
            self._started_at = self.clock()
            self.on_event("video_started", path)
            return path

    def stop_video(self, reason: str = "user") -> Path | None:
        with self._lock:
            if self.state is not State.RECORDING:
                return None
            try:
                self.camera.stop_video()
            finally:
                self.state = State.IDLE
                self.led.set_recording(False)     # LED off only once the encoder has stopped
            path, self.current = self.current, None
            self.on_event("video_stopped", (path, reason))
            return path

    def toggle_video(self) -> Path | None:
        with self._lock:
            return self.stop_video() if self.state is State.RECORDING else self.start_video()

    def elapsed(self) -> float:
        return self.clock() - self._started_at if self.state is State.RECORDING else 0.0

    def tick(self) -> None:
        """Call regularly: enforces clip length, heat, storage and battery."""
        with self._lock:
            if self.state is not State.RECORDING:
                return
            if self.elapsed() >= self.cfg.max_clip_seconds:
                self.stop_video("max_length")
            elif self.low_battery:
                self.stop_video("low_battery")
            elif self.thermal.update():
                self.stop_video("too_hot")
            elif not self.store.has_space():
                self.stop_video("storage_full")

    def set_low_battery(self) -> None:
        with self._lock:
            self.low_battery = True
            self.stop_video("low_battery")

    def close(self) -> None:
        with self._lock:
            self.stop_video("shutdown")
            self.camera.close()


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
def mux_command(video: Path, audio: Path, out: Path) -> list[str]:
    """ffmpeg: copy the H.264 stream, take the mic's left channel as mono AAC."""
    return ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio),
            "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", "pan=mono|c0=c0",
            "-c:a", "aac", "-b:a", "128k", "-shortest", str(out)]


class Picamera2Backend:
    """OV5647 via libcamera/Picamera2 (hardware H.264), plus the I2S mic via ALSA.

    Audio is recorded with ``arecord`` next to the video and muxed in when the
    clip ends, because Picamera2's built-in audio path needs PulseAudio, which
    Raspberry Pi OS Lite does not run.
    """

    def __init__(self, cfg: CaptureConfig) -> None:
        from picamera2 import Picamera2  # imported lazily: only exists on the Pi

        self.cfg = cfg
        self.cam = Picamera2()
        self.video_config = self.cam.create_video_configuration(
            main={"size": tuple(cfg.video_size)},
            controls={"FrameRate": cfg.framerate},
        )
        self.still_config = self.cam.create_still_configuration()
        self.cam.configure(self.video_config)
        self.cam.start()
        self._clip: tuple[Path, Path, Path] | None = None    # final, video-only, wav
        self._arecord: subprocess.Popen | None = None
        self._muxers: list[threading.Thread] = []

    def start_video(self, path: Path) -> None:
        from picamera2.encoders import H264Encoder
        from picamera2.outputs import FfmpegOutput

        video, wav = path.with_suffix(".video.mp4"), path.with_suffix(".wav")
        if self.cfg.record_audio:
            self._arecord = subprocess.Popen(
                ["arecord", "-q", "-D", self.cfg.audio_device, "-f", "S32_LE", "-c", "2", "-r", "48000", str(wav)])
        self.cam.start_encoder(H264Encoder(bitrate=self.cfg.bitrate), FfmpegOutput(str(video)))
        self._clip = (path, video, wav)

    def stop_video(self) -> None:
        self.cam.stop_encoder()
        if self._clip is None:
            return
        path, video, wav = self._clip
        self._clip = None
        audio_ok = False
        if self._arecord is not None:
            self._arecord.send_signal(signal.SIGINT)        # arecord finalises the WAV header on SIGINT
            try:
                audio_ok = self._arecord.wait(timeout=3) in (0, 1, -signal.SIGINT) and wav.exists()
            except subprocess.TimeoutExpired:
                self._arecord.kill()
            self._arecord = None
        if not audio_ok:
            video.replace(path)
            return
        t = threading.Thread(target=self._mux, args=(path, video, wav), name="mux", daemon=True)
        t.start()
        self._muxers = [m for m in self._muxers if m.is_alive()] + [t]

    def _mux(self, path: Path, video: Path, wav: Path) -> None:
        result = subprocess.run(mux_command(video, wav, path), capture_output=True, text=True)
        if result.returncode == 0:
            video.unlink(missing_ok=True)
            wav.unlink(missing_ok=True)
        else:   # keep the picture even if the sound failed
            log.error("audio mux failed (%s); saving video without sound", result.stderr.strip())
            video.replace(path)

    def take_photo(self, path: Path, recording: bool) -> None:
        if recording:
            self.cam.capture_file(str(path))          # 1080p still from the running video stream
        else:
            self.cam.switch_mode_and_capture_file(self.still_config, str(path))   # full 5 MP

    def preview_frame(self) -> np.ndarray | None:
        frame = self.cam.capture_array("main")        # XBGR8888 -> [R, G, B, X] per pixel
        return frame[::3, ::3, :3]

    def close(self) -> None:
        for t in self._muxers:                        # let the last clip finish before power-off
            t.join(timeout=60)
        self.cam.stop()
        self.cam.close()


class MockCamera:
    """Writes small placeholder files and produces a moving test pattern."""

    def __init__(self, size: tuple[int, int] = (640, 360)) -> None:
        self.size = size
        self.recording_to: Path | None = None
        self.photos: list[Path] = []
        self.videos: list[Path] = []
        self._t0 = time.monotonic()

    def start_video(self, path: Path) -> None:
        self.recording_to = path
        path.write_bytes(b"")       # real backend streams MP4 here

    def stop_video(self) -> None:
        if self.recording_to is not None:
            self.recording_to.write_bytes(b"mock video")
            self.videos.append(self.recording_to)
        self.recording_to = None

    def take_photo(self, path: Path, recording: bool) -> None:
        path.write_bytes(b"mock photo")
        self.photos.append(path)

    def preview_frame(self) -> np.ndarray:
        w, h = self.size
        t = time.monotonic() - self._t0
        x = np.linspace(0, 1, w, dtype=np.float32)[None, :]
        y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        r = (np.sin(2 * np.pi * (x * 3 + t * 0.2)) * 0.5 + 0.5) * 255
        g = np.broadcast_to(y * 255, (h, w))
        b = np.full((h, w), 140.0)
        return np.stack(np.broadcast_arrays(r, g, b), axis=-1).astype(np.uint8)

    def close(self) -> None:
        self.stop_video()
