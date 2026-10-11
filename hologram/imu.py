"""MPU-6050 driver (I2C) plus a mock that fakes head motion on a desktop."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Protocol

Vec = tuple[float, float, float]

GRAVITY_LSB = 16384.0          # +/-2 g range
GYRO_LSB_PER_DPS = 65.5        # +/-500 deg/s range


@dataclass(frozen=True)
class ImuSample:
    accel: Vec    # in g, device frame
    gyro: Vec     # rad/s, device frame


class Imu(Protocol):
    def read(self) -> ImuSample: ...


class SMBusLike(Protocol):
    def read_byte_data(self, addr: int, reg: int) -> int: ...
    def write_byte_data(self, addr: int, reg: int, value: int) -> None: ...
    def read_i2c_block_data(self, addr: int, reg: int, length: int) -> list[int]: ...
    def write_i2c_block_data(self, addr: int, reg: int, data: list[int]) -> None: ...


def axis_remap(axis_map: tuple[str, str, str]):
    """Build a function mapping sensor axes to device axes, e.g. ("-y", "x", "z")."""
    picks = []
    for spec in axis_map:
        sign = -1.0 if spec.startswith("-") else 1.0
        name = spec.lstrip("+-")
        if name not in ("x", "y", "z"):
            raise ValueError(f"bad axis {spec!r}")
        picks.append(("xyz".index(name), sign))
    if sorted(i for i, _ in picks) != [0, 1, 2]:
        raise ValueError(f"axis_map must use x, y and z once each: {axis_map}")

    def remap(v: Vec) -> Vec:
        return tuple(v[i] * s for i, s in picks)  # type: ignore[return-value]

    return remap


def _s16(hi: int, lo: int) -> int:
    v = (hi << 8) | lo
    return v - 65536 if v & 0x8000 else v


class MPU6050:
    PWR_MGMT_1 = 0x6B
    SMPLRT_DIV = 0x19
    CONFIG = 0x1A
    GYRO_CONFIG = 0x1B
    ACCEL_CONFIG = 0x1C
    ACCEL_XOUT_H = 0x3B
    WHO_AM_I = 0x75

    def __init__(self, bus: int = 1, address: int = 0x68, axis_map: tuple[str, str, str] = ("x", "y", "z"),
                 smbus: SMBusLike | None = None) -> None:
        if smbus is None:
            from smbus2 import SMBus  # only needed on the Pi
            smbus = SMBus(bus)
        self.bus = smbus
        self.addr = address
        self.remap = axis_remap(axis_map)
        who = self.bus.read_byte_data(self.addr, self.WHO_AM_I)
        if who not in (0x68, 0x70, 0x71, 0x73):   # 6050, and the register-compatible 6500/9250 clones
            raise OSError(f"no MPU-6050 at 0x{address:02x} (WHO_AM_I=0x{who:02x})")
        self.bus.write_byte_data(self.addr, self.PWR_MGMT_1, 0x01)    # wake, PLL on gyro X
        time.sleep(0.05)
        self.bus.write_byte_data(self.addr, self.CONFIG, 0x03)        # DLPF ~44 Hz
        self.bus.write_byte_data(self.addr, self.SMPLRT_DIV, 4)       # 1 kHz / 5 = 200 Hz
        self.bus.write_byte_data(self.addr, self.GYRO_CONFIG, 0x08)   # +/-500 deg/s
        self.bus.write_byte_data(self.addr, self.ACCEL_CONFIG, 0x00)  # +/-2 g

    def read(self) -> ImuSample:
        d = self.bus.read_i2c_block_data(self.addr, self.ACCEL_XOUT_H, 14)
        accel = tuple(_s16(d[i], d[i + 1]) / GRAVITY_LSB for i in (0, 2, 4))
        gyro = tuple(math.radians(_s16(d[i], d[i + 1]) / GYRO_LSB_PER_DPS) for i in (8, 10, 12))
        return ImuSample(self.remap(accel), self.remap(gyro))  # type: ignore[arg-type]


class MockImu:
    """Slow side-to-side head turn with a little nod, so the VR view moves."""

    def __init__(self, yaw_amplitude_deg: float = 35.0, period_s: float = 8.0) -> None:
        self.amp = math.radians(yaw_amplitude_deg)
        self.period = period_s
        self.t0 = time.monotonic()
        self.still = False

    def read(self) -> ImuSample:
        if self.still:
            return ImuSample((0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
        t = time.monotonic() - self.t0
        w = 2 * math.pi / self.period
        yaw_rate = self.amp * w * math.cos(w * t)
        pitch_rate = 0.2 * self.amp * 2 * w * math.cos(2 * w * t)
        return ImuSample((0.0, 0.0, 1.0), (pitch_rate, 0.0, yaw_rate))
