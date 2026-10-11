"""Short interface sounds (the headset has no other way to say "done").

Tones are synthesised with numpy at whatever rate the audio output runs at
and mixed into the ear-cup stream by ``hologram.vr.audio.AudioEngine``.
"""
from __future__ import annotations

import numpy as np

# name -> list of (frequency Hz, milliseconds); 0 Hz = silence
PATTERNS: dict[str, list[tuple[float, int]]] = {
    "beep": [(1046, 70), (0, 40)],
    "mode": [(880, 60), (0, 30), (1175, 80)],
    "recentred": [(1320, 50), (0, 30), (1320, 50)],
    "refused": [(220, 260)],
    "battery_low": [(990, 120), (0, 60), (740, 120), (0, 60), (550, 200)],
    "wake": [(660, 60), (990, 90)],
    "power_off": [(880, 150), (660, 150), (440, 300)],
}
LEVEL = 0.6          # before the master volume


def synth(pattern: list[tuple[float, int]], rate: int = 48000) -> np.ndarray:
    """Mono float32 samples in [-LEVEL, LEVEL] with 5 ms fades (no clicks)."""
    chunks = []
    for freq, ms in pattern:
        n = int(rate * ms / 1000)
        t = np.arange(n, dtype=np.float32) / rate
        tone = np.sin(2 * np.pi * freq * t, dtype=np.float32) if freq else np.zeros(n, np.float32)
        fade = min(n // 2, int(rate * 0.005))
        if fade:
            env = np.ones(n, np.float32)
            env[:fade] = np.linspace(0, 1, fade, dtype=np.float32)
            env[-fade:] = np.linspace(1, 0, fade, dtype=np.float32)
            tone = tone * env
        chunks.append(tone)
    return (np.concatenate(chunks) * LEVEL).astype(np.float32)
