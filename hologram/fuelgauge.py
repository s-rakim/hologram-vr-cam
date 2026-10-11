"""Battery state of charge from a MAX17048 (or register-compatible MAX17040/43).

A fuel gauge reports the real charge left, so the device can run the cell
down to a safe cutoff instead of guessing from a fixed voltage.
"""
from __future__ import annotations

from typing import Protocol

from .imu import SMBusLike


class FuelGauge(Protocol):
    def percent(self) -> float: ...
    def volts(self) -> float: ...


class MAX17048:
    VCELL = 0x02
    SOC = 0x04
    VERSION = 0x08
    CONFIG = 0x0C

    def __init__(self, bus: int = 1, address: int = 0x36, alert_percent: int | None = 5,
                 smbus: SMBusLike | None = None) -> None:
        if smbus is None:
            from smbus2 import SMBus  # only needed on the device
            smbus = SMBus(bus)
        self.bus = smbus
        self.addr = address
        version = self._read(self.VERSION)
        if version in (0x0000, 0xFFFF):
            raise OSError(f"no fuel gauge at 0x{address:02x}")
        if alert_percent is not None:
            # CONFIG: keep RCOMP (high byte), ALRT cleared, ATHD = 32 - threshold in percent.
            rcomp = self._read(self.CONFIG) >> 8
            athd = 32 - max(1, min(32, alert_percent))
            self._write(self.CONFIG, (rcomp << 8) | athd)

    def _read(self, reg: int) -> int:
        hi, lo = self.bus.read_i2c_block_data(self.addr, reg, 2)   # registers are big-endian
        return (hi << 8) | lo

    def _write(self, reg: int, value: int) -> None:
        self.bus.write_i2c_block_data(self.addr, reg, [(value >> 8) & 0xFF, value & 0xFF])

    def volts(self) -> float:
        return self._read(self.VCELL) * 78.125e-6

    def percent(self) -> float:
        return min(100.0, self._read(self.SOC) / 256.0)


class MockFuelGauge:
    """A settable battery level for tests and the desktop mock."""

    def __init__(self, start: float = 80.0) -> None:
        self.level = start

    def percent(self) -> float:
        return self.level

    def volts(self) -> float:
        return 3.3 + 0.9 * self.level / 100.0


def battery_bars(percent: float) -> int:
    """1-4 beeps for the battery check: 4 = over 75 %, 1 = under 25 %."""
    return max(1, min(4, int(percent // 25) + 1))
