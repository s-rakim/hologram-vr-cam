"""Configuration pieces that are not specific to one device, and the TOML loader.

The VR helmet's top-level config lives in ``hologram.vr.config``; this module
holds the generic parts and the strict loader that applies a TOML file on
top of the defaults (unknown keys and wrong types are errors, so a typo in
the file can't silently do nothing).
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields, is_dataclass, replace
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ThermalConfig:
    sensor_path: str = "/sys/class/thermal/thermal_zone0/temp"
    stop_recording_c: float = 80.0
    resume_c: float = 70.0


@dataclass(frozen=True)
class PowerConfig:
    fuel_gauge: bool = True              # MAX17048/MAX17043 on the UPS board (I2C)
    i2c_bus: int = 1
    fuel_gauge_address: int = 0x36
    warn_percent: float = 10.0           # warning sound
    shutdown_percent: float = 3.0        # save, then power off
    shutdown_on_low_battery: bool = True


def _merge(obj: Any, data: dict[str, Any], where: str) -> Any:
    known = {f.name: f for f in fields(obj)}
    changes: dict[str, Any] = {}
    for key, value in data.items():
        if key not in known:
            raise ValueError(f"unknown config key {where}{key}")
        current = getattr(obj, key)
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ValueError(f"{where}{key} must be a table")
            changes[key] = _merge(current, value, f"{where}{key}.")
        elif isinstance(current, tuple):
            if not isinstance(value, (list, tuple)) or len(value) != len(current):
                raise ValueError(f"{where}{key} must be a list of {len(current)} items")
            changes[key] = tuple(value)
        elif isinstance(current, bool):
            if not isinstance(value, bool):
                raise ValueError(f"{where}{key} must be true or false")
            changes[key] = value
        elif isinstance(current, float) and isinstance(value, (int, float)) and not isinstance(value, bool):
            changes[key] = float(value)
        elif isinstance(current, int) and isinstance(value, int) and not isinstance(value, bool):
            changes[key] = value
        elif isinstance(current, str) and isinstance(value, str):
            changes[key] = value
        else:
            raise ValueError(f"{where}{key} has the wrong type")
    return replace(obj, **changes)


def load_toml(defaults: T, path: str | Path | None) -> T:
    """``defaults`` overridden by the TOML file at ``path`` (unknown keys are errors)."""
    if path is None:
        return defaults
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    cfg = _merge(defaults, data, "")
    thermal = getattr(cfg, "thermal", None)
    if thermal is not None and thermal.resume_c >= thermal.stop_recording_c:
        raise ValueError("thermal.resume_c must be below thermal.stop_recording_c")
    return cfg
