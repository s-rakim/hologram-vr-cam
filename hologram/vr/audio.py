"""Head-tracked surround sound for the helmet's two ear-cup speakers.

Everything is mixed here and streamed to one ``aplay`` process (the I2S card
has one stereo output: the left amp drives the left ear cup, the right amp
the right one):

* **Scene sound**: a WAV file next to the current panorama
  (``beach.jpg`` + ``beach.wav``). 4-channel files are first-order
  ambisonics (AmbiX: ACN order W, Y, Z, X with SN3D gains, what 360 cameras
  and Spatial Media tools write). Stereo files become two virtual speakers
  30 degrees either side of the panorama's front, mono files one source
  straight ahead. The sound field is fixed to the world, so when you turn
  your head the sound stays where it belongs.
* **Interface sounds** (beeps), centred in the head.
* **Master volume** (the volume buttons).

Decoding: each ear is a virtual cardioid microphone pointing out of that
side of the head, re-aimed with the head orientation every block (~21 ms).
The closed ear cups keep the two channels apart, which is what makes this
simple decoder work well.
"""
from __future__ import annotations

import logging
import math
import struct
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import numpy as np

from ..sounds import PATTERNS, synth

log = logging.getLogger(__name__)
DEFAULT_RATE = 48000
BLOCK = 1024                       # frames per block: 21 ms at 48 kHz
STEREO_SPREAD_DEG = 30.0
SOUND_TYPES = (".wav",)

Rotation = Callable[[], np.ndarray]   # device -> world rotation matrix (3 x 3)


# ---------------------------------------------------------------------------
# WAV reading (PCM 8/16/24/32-bit, float 32/64, WAVE_FORMAT_EXTENSIBLE)
# ---------------------------------------------------------------------------
class WavReader:
    """Streams a WAV file from disk (memory-mapped, loops at the end)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        with open(self.path, "rb") as fh:
            head = fh.read(12)
            if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                raise ValueError(f"{self.path.name}: not a WAV file")
            fmt = None
            offset = 12
            while True:
                fh.seek(offset)
                hdr = fh.read(8)
                if len(hdr) < 8:
                    raise ValueError(f"{self.path.name}: no data chunk")
                cid, size = hdr[:4], struct.unpack("<I", hdr[4:])[0]
                if cid == b"fmt ":
                    fmt = fh.read(size)
                elif cid == b"data":
                    data_offset, data_size = offset + 8, size
                    break
                offset += 8 + size + (size & 1)
        if fmt is None or len(fmt) < 16:
            raise ValueError(f"{self.path.name}: no fmt chunk")
        tag, self.channels, self.rate, _, block_align, bits = struct.unpack("<HHIIHH", fmt[:16])
        if tag == 0xFFFE and len(fmt) >= 26:          # WAVE_FORMAT_EXTENSIBLE: sub-format GUID
            tag = struct.unpack("<H", fmt[24:26])[0]
        if tag not in (1, 3) or self.channels < 1 or block_align != self.channels * bits // 8:
            raise ValueError(f"{self.path.name}: unsupported WAV format (tag {tag}, {bits} bit)")
        self.float = tag == 3
        self.bits = bits
        total = Path(self.path).stat().st_size
        data_size = min(data_size, total - data_offset)
        self.frames = data_size // block_align
        if self.frames == 0:
            raise ValueError(f"{self.path.name}: empty")
        if self.float:
            dtype = {32: "<f4", 64: "<f8"}.get(bits)
        else:
            dtype = {8: "u1", 16: "<i2", 24: "u1", 32: "<i4"}.get(bits)
        if dtype is None:
            raise ValueError(f"{self.path.name}: unsupported sample size {bits}")
        count = self.frames * block_align // np.dtype(dtype).itemsize
        self._raw = np.memmap(self.path, dtype=dtype, mode="r", offset=data_offset, shape=(count,))
        self.pos = 0

    def _convert(self, start: int, n: int) -> np.ndarray:
        ch = self.channels
        if self.bits == 24 and not self.float:
            b = np.asarray(self._raw[start * ch * 3:(start + n) * ch * 3]).reshape(n, ch, 3).astype(np.int32)
            v = b[..., 0] | (b[..., 1] << 8) | (b[..., 2] << 16)
            v = np.where(v >= 1 << 23, v - (1 << 24), v)
            return (v / float(1 << 23)).astype(np.float32)
        block = np.asarray(self._raw[start * ch:(start + n) * ch]).reshape(n, ch)
        if self.float:
            return block.astype(np.float32)
        if self.bits == 8:
            return ((block.astype(np.float32) - 128.0) / 128.0)
        return (block / float(1 << (self.bits - 1))).astype(np.float32)

    def read(self, n: int) -> np.ndarray:
        """The next ``n`` frames as float32 (n, channels), wrapping to the start."""
        out = np.empty((n, self.channels), np.float32)
        done = 0
        while done < n:
            take = min(n - done, self.frames - self.pos)
            out[done:done + take] = self._convert(self.pos, take)
            done += take
            self.pos = (self.pos + take) % self.frames
        return out


# ---------------------------------------------------------------------------
# Ambisonics. Internally a sound field is 4 channels [W, Dx, Dy, Dz] in the
# headset's axes (X = right, Y = forward, Z = up): a plane wave s arriving
# from unit direction d has W = s and D = s * d (first order, SN3D).
# ---------------------------------------------------------------------------
def encode(signal: np.ndarray, direction: tuple[float, float, float]) -> np.ndarray:
    """Mono (n,) -> sound field (n, 4) for a source in ``direction``."""
    d = np.asarray(direction, np.float32)
    d = d / np.linalg.norm(d)
    return np.concatenate([signal[:, None], signal[:, None] * d[None, :]], axis=1)


def from_ambix(block: np.ndarray) -> np.ndarray:
    """AmbiX (ACN W, Y, Z, X; SN3D; x front, y left, z up) -> [W, Dx, Dy, Dz]."""
    w, y, z, x = block[:, 0], block[:, 1], block[:, 2], block[:, 3]
    return np.stack([w, -y, x, z], axis=1)


def to_field(block: np.ndarray) -> np.ndarray:
    """Any supported channel layout -> sound field (n, 4), fixed to the world."""
    ch = block.shape[1]
    if ch == 4:
        return from_ambix(block)
    if ch == 2:
        s = math.sin(math.radians(STEREO_SPREAD_DEG))
        c = math.cos(math.radians(STEREO_SPREAD_DEG))
        return encode(block[:, 0], (-s, c, 0.0)) + encode(block[:, 1], (s, c, 0.0))
    if ch == 1:
        return encode(block[:, 0], (0.0, 1.0, 0.0))
    raise ValueError(f"{ch}-channel audio is not supported (use mono, stereo or 4-channel AmbiX)")


def decode_ears(field: np.ndarray, rotation: np.ndarray, pattern: float = 0.5) -> np.ndarray:
    """Sound field -> (n, 2) left/right ear signals for a head with this orientation.

    ``pattern`` is the virtual microphone shape: 1 = omni (no direction),
    0.5 = cardioid (default), 0 = figure-of-eight."""
    r = np.asarray(rotation, np.float32)
    ears = np.stack([r @ np.array([-1.0, 0.0, 0.0], np.float32),     # left ear's axis, in the world
                     r @ np.array([1.0, 0.0, 0.0], np.float32)])
    gains = np.concatenate([np.full((2, 1), pattern, np.float32), (1.0 - pattern) * ears], axis=1)   # (2, 4)
    return field @ gains.T


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
class Sink(Protocol):
    def write(self, frames: np.ndarray) -> None: ...      # (n, 2) int16, blocks until accepted
    def close(self) -> None: ...


class AplaySink:
    """Raw 16-bit stereo into ``aplay`` (the pipe paces the mixer in real time)."""

    def __init__(self, device: str, rate: int) -> None:
        self.proc = subprocess.Popen(
            ["aplay", "-q", "-D", device, "-t", "raw", "-f", "S16_LE", "-c", "2", "-r", str(rate),
             "--buffer-time=100000"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def write(self, frames: np.ndarray) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(np.ascontiguousarray(frames, "<i2").tobytes())

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()


class MemorySink:
    """Keeps the last few seconds of output (tests, desktop mock)."""

    def __init__(self, rate: int, realtime: bool = False, keep_s: float = 5.0) -> None:
        self.rate = rate
        self.realtime = realtime
        self.blocks: list[np.ndarray] = []
        self.keep = int(keep_s * rate)
        self.closed = False

    def write(self, frames: np.ndarray) -> None:
        self.blocks.append(frames.copy())
        while sum(len(b) for b in self.blocks) > self.keep:
            self.blocks.pop(0)
        if self.realtime:
            time.sleep(len(frames) / self.rate)

    def close(self) -> None:
        self.closed = True

    def samples(self) -> np.ndarray:
        return np.concatenate(self.blocks) if self.blocks else np.zeros((0, 2), np.int16)


def aplay_factory(device: str) -> Callable[[int], Sink]:
    return lambda rate: AplaySink(device, rate)


class AudioEngine:
    """Mixer thread: scene sound (head-tracked) + interface sounds -> one stereo stream.

    When nothing is playing the output is closed, so an idle headset costs
    no CPU for audio.
    """

    def __init__(self, sink_factory: Callable[[int], Sink], rotation: Rotation,
                 volume: float = 0.35, pattern: float = 0.5, enabled: bool = True,
                 idle_close_s: float = 2.0) -> None:
        self.sink_factory = sink_factory
        self.rotation = rotation
        self.volume = min(1.0, max(0.0, volume))
        self.pattern = pattern
        self.enabled = enabled
        self.idle_close_s = idle_close_s
        self.rate = DEFAULT_RATE
        self.played: list[str] = []
        self._scene: WavReader | None = None
        self._cues: list[np.ndarray] = []          # pending interface sounds (mono float)
        self._cache: dict[tuple[str, int], np.ndarray] = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._sink: Sink | None = None
        self._sink_rate = 0

    # -- control (any thread) --------------------------------------------------------------
    def set_scene(self, path: str | Path | None) -> bool:
        """Play ``path`` as the world-fixed scene sound (None = silence). False if it can't be used."""
        reader = None
        if path is not None:
            try:
                reader = WavReader(path)
                to_field(np.zeros((1, reader.channels), np.float32))       # layout check
            except (OSError, ValueError) as err:
                log.warning("scene sound %s skipped: %s", path, err)
                reader = None
        with self._lock:
            self._scene = reader
            if reader is not None:
                self.rate = reader.rate
        self._wake.set()
        return reader is not None or path is None

    @property
    def scene(self) -> Path | None:
        return self._scene.path if self._scene is not None else None

    def play(self, name: str, repeat: int = 1) -> None:
        if name not in PATTERNS:
            raise KeyError(name)
        self.played += [name] * repeat
        if not self.enabled:
            return
        with self._lock:
            key = (name, self.rate)
            if key not in self._cache:
                self._cache[key] = synth(PATTERNS[name], self.rate)
            self._cues.extend([self._cache[key]] * repeat)
        self._wake.set()

    def set_volume(self, volume: float) -> float:
        self.volume = round(min(1.0, max(0.0, volume)), 3)
        return self.volume

    def step_volume(self, delta: float) -> float:
        v = self.set_volume(self.volume + delta)
        self.play("beep")
        return v

    # -- mixing ---------------------------------------------------------------------------
    def active(self) -> bool:
        return self.enabled and (self._scene is not None or bool(self._cues))

    def render_block(self, n: int = BLOCK) -> np.ndarray:
        """The next ``n`` stereo frames as int16 (n, 2)."""
        out = np.zeros((n, 2), np.float32)
        with self._lock:
            scene = self._scene
            if scene is not None:
                out += decode_ears(to_field(scene.read(n)), self.rotation(), self.pattern)
            filled = 0
            while self._cues and filled < n:
                cue = self._cues[0]
                take = min(len(cue), n - filled)
                out[filled:filled + take] += cue[:take, None]
                if take == len(cue):
                    self._cues.pop(0)
                else:
                    self._cues[0] = cue[take:]
                filled += take
        np.clip(out * self.volume, -1.0, 1.0, out=out)
        return (out * 32767).astype(np.int16)

    # -- thread ---------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is None and self.enabled:
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="audio", daemon=True)
            self._thread.start()

    def _open(self) -> Sink | None:
        if self._sink is not None and self._sink_rate == self.rate:
            return self._sink
        self._close_sink()
        try:
            self._sink, self._sink_rate = self.sink_factory(self.rate), self.rate
        except OSError as err:          # no aplay / no sound card: sound is nice to have, not essential
            log.warning("audio output unavailable: %s", err)
            self.enabled = False
        return self._sink

    def _close_sink(self) -> None:
        if self._sink is not None:
            self._sink.close()
            self._sink = None

    def _loop(self) -> None:
        idle_since: float | None = None
        while self._running:
            if not self.active():
                if idle_since is None:
                    idle_since = time.monotonic()
                elif time.monotonic() - idle_since > self.idle_close_s:
                    self._close_sink()
                self._wake.wait(0.25)
                self._wake.clear()
                continue
            idle_since = None
            sink = self._open()
            if sink is None:
                continue
            try:
                sink.write(self.render_block())
            except (OSError, ValueError) as err:     # aplay died (card removed?): retry with a new one
                log.warning("audio write failed: %s", err)
                self._sink = None
                time.sleep(0.5)

    def close(self) -> None:
        self._running = False
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._close_sink()


def scene_sound_for(image: Path) -> Path | None:
    """``pano.jpg`` -> ``pano.wav`` beside it, if there is one."""
    if not image.parent.is_dir():
        return None
    for p in sorted(image.parent.iterdir()):
        if p.stem == image.stem and p.suffix.lower() in SOUND_TYPES:
            return p
    return None
