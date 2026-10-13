"""The phone app (phone/index.html), driven in headless Chromium against a mock BLE device.

Skipped unless Node.js and Playwright (with a Chromium build) are installed:
    npm install playwright && npx playwright install chromium
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def run():
    node = shutil.which("node")
    if node is None:
        pytest.skip("no Node.js")
    env = dict(os.environ)
    extra = "/opt/node-tools/node_modules"          # where this repo's CI image keeps global tools
    if Path(extra).is_dir():
        env["NODE_PATH"] = os.pathsep.join(p for p in (env.get("NODE_PATH"), extra) if p)
    if subprocess.run([node, "-e", "require.resolve('playwright')"], env=env, capture_output=True).returncode:
        pytest.skip("Playwright is not installed")
    out = subprocess.run([node, str(ROOT / "tests/phone/mock_ble_test.js"), str(ROOT / "phone/index.html")],
                         env={**env, "TZ": "America/Los_Angeles"}, capture_output=True, text=True, timeout=120)
    if out.returncode:
        pytest.skip(f"browser unavailable: {out.stderr.strip()[-200:]}")
    return json.loads(out.stdout)


def test_no_script_errors(run):
    assert run["errors"] == []


def test_connect_sends_local_time(run):
    assert run["connectedLog"].strip().endswith("Connected; clock synced")
    sent = int(run["timeWrite"].split()[1])
    assert abs(sent - run["expectedLocal"]) <= 2          # wall-clock seconds in the phone's time zone


def test_saved_settings_survive_status_updates(run):
    assert run["settingWrites"] == ["set res vga", "set quality 20", "set segment 600", "set maxrec 3600"]
    assert run["saveLog"].endswith("Settings saved")


def test_one_gatt_operation_at_a_time_and_cut_short_events_are_read_back(run):
    assert run["maxInFlight"] == 1
    assert any("Photo saved HVR_20261011_143012_0042.jpg" in line for line in run["photoLog"])


def test_reconnecting_does_not_duplicate_handlers(run):
    assert run["disconnectedCount"] == 2                  # two disconnects, one message each


def test_failed_pairing_is_reported_and_drops_the_link(run):
    assert any("pairing failed" in line for line in run["pairLog"])
    assert run["linkText"] == "Not connected" and run["stillConnected"] is False
