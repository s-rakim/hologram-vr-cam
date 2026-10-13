import math
import struct
import time
import wave

import numpy as np
import pytest

from hologram import quaternion as qt
from hologram.sounds import PATTERNS, synth
from hologram.vr.audio import (
    AudioEngine,
    MemorySink,
    Pacer,
    WavReader,
    decode_ears,
    encode,
    from_ambix,
    scene_sound_for,
    to_field,
)

FORWARD = np.eye(3, dtype=np.float32)


def rot(q):
    return np.array(qt.to_matrix(q), dtype=np.float32)


def tone(n=4800, rate=48000, f=440.0):
    return (0.5 * np.sin(2 * np.pi * f * np.arange(n) / rate)).astype(np.float32)


def rms(x):
    return float(np.sqrt(np.mean(np.square(x.astype(np.float64)))))


def write_pcm16(path, data, rate=48000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(data.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(data, -1, 1) * 32767).astype("<i2").tobytes())


def write_extensible(path, data, rate=48000, bits=32, float_=True):
    """WAVE_FORMAT_EXTENSIBLE file, as 360 cameras write for 4-channel AmbiX."""
    ch = data.shape[1]
    if float_:
        payload = data.astype("<f4").tobytes()
    else:
        ints = np.round(np.clip(data, -1, 1) * (2 ** 23 - 1)).astype("<i4")
        payload = b"".join(struct.pack("<i", int(v))[:3] for v in ints.ravel())
    sub = (3 if float_ else 1).to_bytes(2, "little") + bytes(14)
    fmt = struct.pack("<HHIIHHHHI", 0xFFFE, ch, rate, rate * ch * bits // 8, ch * bits // 8, bits, 22, bits, 0) + sub
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(payload)) + payload
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


def test_source_on_the_left_is_louder_in_the_left_ear():
    ears = decode_ears(encode(tone(), (-1.0, 0.0, 0.0)), FORWARD)
    assert rms(ears[:, 0]) > 10 * rms(ears[:, 1])


def test_turning_towards_a_source_centres_it():
    field = encode(tone(), (-1.0, 0.0, 0.0))           # fixed in the world, to your left
    ears = decode_ears(field, rot(qt.yaw_quat(math.radians(90))))   # head turned left: now straight ahead
    assert rms(ears[:, 0]) == pytest.approx(rms(ears[:, 1]), rel=1e-3)
    behind = decode_ears(field, rot(qt.yaw_quat(math.radians(-90))))   # turned right: it is behind you
    assert rms(behind[:, 0]) == pytest.approx(rms(behind[:, 1]), rel=1e-3)
    turned_away = decode_ears(field, rot(qt.yaw_quat(math.radians(180))))
    assert rms(turned_away[:, 1]) > 10 * rms(turned_away[:, 0])     # facing backwards: now on your right


def test_ambix_left_wave_maps_to_the_left():
    s = tone()
    ambix = np.stack([s, s, np.zeros_like(s), np.zeros_like(s)], axis=1)   # W, Y (left), Z, X
    field = from_ambix(ambix)
    assert np.allclose(field, encode(s, (-1.0, 0.0, 0.0)))


def test_stereo_keeps_left_on_the_left():
    s = tone()
    ears = decode_ears(to_field(np.stack([s, np.zeros_like(s)], axis=1)), FORWARD)
    assert rms(ears[:, 0]) > 2 * rms(ears[:, 1])
    with pytest.raises(ValueError):
        to_field(np.zeros((4, 3), np.float32))


def test_wav_reader_formats_and_looping(tmp_path):
    data = np.stack([tone(1000), -tone(1000)], axis=1)
    write_pcm16(tmp_path / "a.wav", data)
    r = WavReader(tmp_path / "a.wav")
    assert (r.channels, r.rate, r.frames) == (2, 48000, 1000)
    first = r.read(1500)                                 # wraps around
    assert np.allclose(first[:1000], data, atol=1e-4)
    assert np.allclose(first[1000:], data[:500], atol=1e-4)

    amb = np.stack([tone(256)] * 4, axis=1) * np.array([1, 0.5, -0.25, 0.1], np.float32)
    write_extensible(tmp_path / "f.wav", amb)
    assert np.allclose(WavReader(tmp_path / "f.wav").read(256), amb, atol=1e-6)
    write_extensible(tmp_path / "i24.wav", amb, bits=24, float_=False)
    r24 = WavReader(tmp_path / "i24.wav")
    assert r24.channels == 4 and np.allclose(r24.read(256), amb, atol=1e-5)

    (tmp_path / "bad.wav").write_bytes(b"RIFF\0\0\0\0WAVEjunk")
    with pytest.raises(ValueError):
        WavReader(tmp_path / "bad.wav")


def test_scene_sound_is_found_beside_the_panorama(tmp_path):
    (tmp_path / "beach.jpg").write_bytes(b"")
    assert scene_sound_for(tmp_path / "beach.jpg") is None
    write_pcm16(tmp_path / "beach.WAV", np.zeros((10, 1), np.float32))
    assert scene_sound_for(tmp_path / "beach.jpg") == tmp_path / "beach.WAV"


def test_engine_mixes_cues_and_scales_by_volume(tmp_path):
    engine = AudioEngine(lambda rate: MemorySink(rate), lambda: FORWARD, volume=0.5)
    assert not engine.active()
    engine.play("beep")
    assert engine.active() and engine.played == ["beep"]
    cue = synth(PATTERNS["beep"], engine.rate)
    out = np.concatenate([engine.render_block() for _ in range(math.ceil(len(cue) / 1024))])
    assert not engine.active()
    assert np.allclose(out[:len(cue), 0] / 32767, cue * 0.5, atol=2e-4)
    assert np.array_equal(out[:, 0], out[:, 1])          # interface sounds are centred
    assert engine.step_volume(0.7) == 1.0 and engine.step_volume(-2) == 0.0
    with pytest.raises(KeyError):
        engine.play("nope")


def test_engine_scene_follows_the_head(tmp_path):
    write_pcm16(tmp_path / "pano.wav", np.stack([tone(4800)] * 4, axis=1) * np.array([1, 1, 0, 0]))  # AmbiX, left
    head = {"r": FORWARD}
    engine = AudioEngine(lambda rate: MemorySink(rate), lambda: head["r"], volume=1.0)
    assert engine.set_scene(tmp_path / "pano.wav") and engine.scene == tmp_path / "pano.wav"
    block = engine.render_block(2048)
    assert rms(block[:, 0]) > 10 * rms(block[:, 1])
    head["r"] = rot(qt.yaw_quat(math.radians(90)))
    block = engine.render_block(2048)
    assert rms(block[:, 0]) == pytest.approx(rms(block[:, 1]), rel=0.02)
    assert not engine.set_scene(tmp_path / "missing.wav") and engine.scene is None
    assert engine.set_scene(None)


def test_engine_thread_streams_and_closes_when_idle():
    sinks = []

    def factory(rate):
        sinks.append(MemorySink(rate, realtime=True))
        return sinks[-1]

    engine = AudioEngine(factory, lambda: FORWARD, idle_close_s=0.1)
    engine.start()
    engine.play("beep")
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not (sinks and sinks[0].closed):
        time.sleep(0.02)
    engine.close()
    assert sinks and sinks[0].closed
    assert np.abs(sinks[0].samples()).max() > 1000


def test_pacer_keeps_the_mixer_close_to_real_time():
    t = [0.0]

    def sleep(s):
        t[0] += s

    pacer = Pacer(48000, max_ahead_s=0.06, clock=lambda: t[0], sleep=sleep)
    for _ in range(200):                           # a mixer that renders instantly
        pacer.wait(1024)
        assert pacer.ahead() <= 0.06 + 1024 / 48000 + 1e-9
    assert t[0] == pytest.approx(200 * 1024 / 48000 - 0.06 - 1024 / 48000, abs=0.03)
    t[0] += 5.0                                    # fell far behind (stall): restart instead of bursting
    pacer.wait(1024)
    assert pacer.ahead() <= 1024 / 48000 + 1e-9
