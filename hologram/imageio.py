"""Tiny image helpers so the core needs only numpy (Pillow is optional)."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np


def write_png(path: str | Path, rgb: np.ndarray) -> None:
    """Write an (H, W, 3) RGB or (H, W, 4) RGBX uint8 array as an 8-bit RGB PNG."""
    if rgb.ndim != 3 or rgb.shape[2] not in (3, 4):
        raise ValueError("expected an (H, W, 3) or (H, W, 4) array")
    rgb = np.ascontiguousarray(rgb[..., :3], dtype=np.uint8)
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    Path(path).write_bytes(png)


def load_image(path: str | Path) -> np.ndarray:
    """Load any image Pillow understands (JPEG/PNG panoramas) as (H, W, 3) uint8."""
    try:
        from PIL import Image
    except ImportError as err:  # pragma: no cover - depends on the system
        raise RuntimeError("Install Pillow (sudo apt install python3-pil) to load panoramas") from err
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))
