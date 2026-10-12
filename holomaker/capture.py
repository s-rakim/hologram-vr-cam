"""Stereo capture on a Raspberry Pi 5 with two cameras (one per CSI port).

Mount two identical camera modules side by side, lenses ``baseline_m`` apart
and pointing the same way. Picamera2 opens each port separately; for still
subjects, grabbing both frames back to back is enough. For moving subjects use
a hardware-synchronised stereo kit (see docs/hologram-machine.md).

Calibration is not done here: with a rigid, carefully aligned mount the
pair is close enough to rectified for the block matcher. If rows don't line up
(vertical offset > 1-2 px), calibrate with OpenCV's ``stereoCalibrate`` and
``stereoRectify`` and rectify the images before passing them on.
"""
from __future__ import annotations

import numpy as np


def capture_pair(width: int = 1280, height: int = 960, exposure_us: int | None = None,
                 gain: float | None = None) -> tuple[np.ndarray, np.ndarray]:  # pragma: no cover - needs a Pi
    """Grab one RGB frame from camera 0 (left) and camera 1 (right).

    Fixing ``exposure_us`` and ``gain`` stops the two cameras' auto-exposure
    from drifting apart, which helps the matcher.
    """
    from picamera2 import Picamera2

    cams = [Picamera2(i) for i in (0, 1)]
    try:
        for cam in cams:
            cam.configure(cam.create_still_configuration(main={"size": (width, height), "format": "RGB888"}))
            controls = {}
            if exposure_us is not None:
                controls["ExposureTime"] = exposure_us
            if gain is not None:
                controls["AnalogueGain"] = gain
            if controls:
                cam.set_controls(controls)
            cam.start()
        # Picamera2's "RGB888" is BGR byte order in memory; flip to RGB.
        left, right = (cam.capture_array("main")[..., ::-1].copy() for cam in cams)
        return left, right
    finally:
        for cam in cams:
            cam.close()
