import math

import numpy as np
import pytest

from hologram import quaternion as qt
from hologram.render import (
    PanoramaRenderer,
    PassthroughRenderer,
    draw_rec_indicator,
    eye_grid,
    grid_world,
    stereo_grids,
)


def rot(q):
    return np.array(qt.to_matrix(q), dtype=np.float32)


def test_zero_distortion_grid_is_linear_and_centred():
    g = eye_grid(100, 80)
    assert g.sx[0, 0] == pytest.approx(-0.99)
    assert g.sx[0, -1] == pytest.approx(0.99)
    assert abs(g.sy.mean()) < 1e-6
    assert g.sy.max() == pytest.approx(0.79, abs=1e-6)   # same scale as x


def test_barrel_predistortion_samples_further_out_at_edges():
    plain, barrel = eye_grid(64, 64), eye_grid(64, 64, k1=0.2)
    assert abs(barrel.sx[32, 0]) > abs(plain.sx[32, 0])
    assert barrel.sx[32, 32] == pytest.approx(plain.sx[32, 32], abs=1e-3)


def test_lens_shift_moves_centres_towards_nose():
    left, right = stereo_grids(64, 32, 0, 0, shift=0.1)
    # The left eye's optical centre (sx == 0) sits right of its image centre.
    assert left.sx[16, 32] < 0 < right.sx[16, 32]


def _pano_with_marker():
    pano = np.zeros((180, 360, 3), np.uint8)
    pano[85:95, 175:185] = (255, 0, 0)       # straight ahead (lon 0, lat 0)
    pano[85:95, 85:95] = (0, 255, 0)         # 90 degrees to the left (lon -90)
    return pano


def test_panorama_forward_shows_the_forward_marker():
    r = PanoramaRenderer(_pano_with_marker(), 40, 40, fov_deg=20)
    frame = r.render(rot(qt.IDENTITY))
    assert frame.shape == (40, 80, 3)
    assert tuple(frame[20, 20]) == (255, 0, 0)
    assert tuple(frame[20, 60]) == (255, 0, 0)      # right eye too


def test_turning_left_brings_left_marker_into_view():
    r = PanoramaRenderer(_pano_with_marker(), 40, 40, fov_deg=20)
    frame = r.render(rot(qt.yaw_quat(math.radians(90))))
    assert tuple(frame[20, 20]) == (0, 255, 0)


def test_looking_up_raises_the_horizon_out_of_view():
    pano = grid_world(360, 180)
    r = PanoramaRenderer(pano, 32, 32, fov_deg=30)
    up = r.render(rot(qt.from_axis_angle((1, 0, 0), math.radians(60))))
    sky_blue = up[..., 2].astype(int) - up[..., 0].astype(int)
    assert (sky_blue > 40).mean() > 0.7


def test_passthrough_maps_centre_to_centre_and_letterboxes():
    src = np.zeros((90, 160, 3), np.uint8)
    src[40:50, 75:85] = 200
    r = PassthroughRenderer(160, 90, 64, 72)
    frame = r.render(src)
    assert frame.shape == (72, 128, 3)
    assert frame[36, 32, 0] == 200 and frame[36, 96, 0] == 200
    assert frame[0, 32].sum() == 0                      # outside the camera's view is black
    with pytest.raises(ValueError):
        r.render(np.zeros((10, 10, 3), np.uint8))


def test_rec_indicator_marks_both_eyes():
    frame = np.zeros((120, 240, 3), np.uint8)
    draw_rec_indicator(frame, 0.0)
    reds = np.argwhere(frame[..., 0] == 230)
    assert reds[:, 1].min() < 120 <= reds[:, 1].max()
