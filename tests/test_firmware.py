"""The glasses firmware: pin map matches the CAD wiring, and the portable core logic passes its tests.

The core (gestures, battery curve, phone protocol, capture rules, AVI writer)
is plain C++17 with no Arduino headers, so it builds and runs on the host.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from cad.products import BY_KEY

ROOT = Path(__file__).resolve().parent.parent
FW = ROOT / "firmware/glasses"


def pin_defines() -> dict[str, int]:
    text = (FW / "include/pins.h").read_text()
    return {m[1]: int(m[2]) for m in re.finditer(r"^#define\s+(PIN_\w+)\s+(-?\d+)", text, re.M)}


def test_firmware_pins_match_the_wiring():
    cam, pins = BY_KEY["cam"], pin_defines()
    assert cam.gpio_of("vsense", "OUT") == pins["PIN_VBAT_SENSE"]
    assert cam.gpio_of("button", "A") == pins["PIN_BUTTON"]
    assert cam.gpio_of("touch", "PAD") == pins["PIN_TOUCH"]
    assert cam.gpio_of("led", "CTRL") == pins["PIN_PRIVACY_LED"]
    assert cam.gpio_of("amp", "BCLK") == pins["PIN_I2S_BCLK"]
    assert cam.gpio_of("amp", "LRC") == pins["PIN_I2S_LRC"]
    assert cam.gpio_of("amp", "DIN") == pins["PIN_I2S_DOUT"]
    assert cam.gpio_of("amp", "SD") == pins["PIN_AMP_SD"]


def test_header_pins_are_not_reused():
    pins = pin_defines()
    header = [v for k, v in pins.items() if not k.startswith(("PIN_SD_", "PIN_MIC_"))]
    assert len(header) == len(set(header))
    assert not set(header) & {pins["PIN_SD_CS"], pins["PIN_SD_SCK"], pins["PIN_SD_MISO"], pins["PIN_SD_MOSI"],
                              pins["PIN_MIC_CLK"], pins["PIN_MIC_DATA"]}


def test_phone_app_and_firmware_share_the_ble_uuids():
    config = (FW / "include/config.h").read_text()
    app = (ROOT / "phone/index.html").read_text().lower()
    uuids = re.findall(r'"([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})"', config)
    assert len(uuids) >= 4
    for uuid in uuids:
        assert uuid.lower() in app, uuid


@pytest.fixture(scope="module")
def core_tests(tmp_path_factory) -> Path:
    cxx = shutil.which("g++") or shutil.which("clang++")
    if cxx is None:
        pytest.skip("no C++ compiler")
    exe = tmp_path_factory.mktemp("fw") / "core_tests"
    sources = sorted(str(p) for p in (FW / "lib/core/src").glob("*.cpp"))
    subprocess.run([cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-O1", f"-I{FW / 'lib/core/src'}",
                    str(FW / "test/host/core_tests.cpp"), *sources, "-o", str(exe)], check=True)
    return exe


def test_firmware_core_logic(core_tests, tmp_path):
    avi = tmp_path / "clip.avi"
    run = subprocess.run([str(core_tests), str(avi)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "all core tests passed" in run.stdout


def test_recorded_avi_plays(core_tests, tmp_path):
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        pytest.skip("no ffprobe")
    avi = tmp_path / "clip.avi"
    subprocess.run([str(core_tests), str(avi)], check=True, capture_output=True)
    probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=codec_name,sample_rate,nb_frames",
                            "-of", "csv=p=0", str(avi)], capture_output=True, text=True, check=True).stdout
    assert "mjpeg" in probe and "pcm_s16le,16000" in probe
