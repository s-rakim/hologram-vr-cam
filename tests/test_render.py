import math

import numpy as np
import pytest

from hologram import quaternion as qt
from hologram.vr.optics import LensOptics, ReflectorOptics, eye_grid, field_of_view, stereo_tables
from hologram.vr.render import PanoramaRenderer, PassthroughRenderer, VirtualScreenRenderer, grid_world

PINHOLE = LensOptics(fov_deg=20.0, k1=0.0, k2=0.0)


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


def test_lens_cant_turns_each_eye_outward():
    left, right = stereo_tables(LensOptics(fov_deg=60, k1=0, k2=0, cant_deg=10), 33, 33)
    centre = right.rays[16, 16]
    assert math.degrees(math.atan2(centre[0], centre[1])) == pytest.approx(10, abs=0.5)
    assert left.rays[16, 16, 0] == pytest.approx(-centre[0], abs=1e-6)


def _pano_with_marker():
    pano = np.zeros((180, 360, 3), np.uint8)
    pano[85:95, 175:185] = (255, 0, 0)       # straight ahead (lon 0, lat 0)
    pano[85:95, 85:95] = (0, 255, 0)         # 90 degrees to the left (lon -90)
    return pano


def test_panorama_forward_shows_the_forward_marker():
    r = PanoramaRenderer(_pano_with_marker(), stereo_tables(PINHOLE, 40, 40))
    frame = r.render(rot(qt.IDENTITY))
    assert frame.shape == (40, 80, 3)
    assert tuple(frame[20, 20]) == (255, 0, 0)
    assert tuple(frame[20, 60]) == (255, 0, 0)      # right eye too


def test_turning_left_brings_left_marker_into_view():
    r = PanoramaRenderer(_pano_with_marker(), stereo_tables(PINHOLE, 40, 40))
    frame = r.render(rot(qt.yaw_quat(math.radians(90))))
    assert tuple(frame[20, 20]) == (0, 255, 0)


def test_looking_up_raises_the_horizon_out_of_view():
    r = PanoramaRenderer(grid_world(360, 180), stereo_tables(LensOptics(fov_deg=30, k1=0, k2=0), 32, 32))
    up = r.render(rot(qt.from_axis_angle((1, 0, 0), math.radians(60))))
    sky_blue = up[..., 2].astype(int) - up[..., 0].astype(int)
    assert (sky_blue > 40).mean() > 0.7


def test_virtual_screen_shows_the_photo_straight_ahead():
    photo = np.full((90, 160, 3), (10, 200, 30), np.uint8)
    r = VirtualScreenRenderer(grid_world(360, 180), photo, stereo_tables(PINHOLE, 40, 40))
    frame = r.render(rot(qt.IDENTITY))
    assert tuple(frame[20, 20]) == (10, 200, 30)
    behind = r.render(rot(qt.yaw_quat(math.radians(180))))
    assert tuple(behind[20, 20]) != (10, 200, 30)


def test_passthrough_maps_true_directions():
    src = np.zeros((90, 160, 3), np.uint8)
    src[40:50, 75:85] = 200                              # the camera's centre
    r = PassthroughRenderer(160, 90, stereo_tables(LensOptics(fov_deg=120, k1=0, k2=0), 64, 72), hfov_deg=90)
    frame = r.render(src)
    assert frame.shape == (72, 128, 3)
    assert frame[36, 32, 0] == 200 and frame[36, 96, 0] == 200
    assert frame[36, 0].sum() == 0                      # 60 deg off-axis: outside the camera's 45 deg
    with pytest.raises(ValueError):
        r.render(np.zeros((10, 10, 3), np.uint8))


# -- reflector (brow display + visor mirror) optics ------------------------------------------
REFLECTOR = ReflectorOptics()


def test_mirror_points_lie_on_the_ellipsoid():
    d = REFLECTOR.display_points(30, 30)
    p = REFLECTOR.mirror_points(d)
    f1, f2 = REFLECTOR.foci()
    total = np.linalg.norm(p - f1, axis=-1) + np.linalg.norm(p - f2, axis=-1)
    assert np.allclose(total, REFLECTOR.major_axis(), atol=1e-6)


def test_reflection_law_holds_at_every_mirror_point():
    """Display -> mirror -> eye obeys angle in = angle out about the ellipsoid normal."""
    d = REFLECTOR.display_points(25, 25).reshape(-1, 3)
    p = REFLECTOR.mirror_points(d)
    f1, f2 = REFLECTOR.foci()
    before = np.linalg.norm(p - f2, axis=1) > np.linalg.norm(d - f2, axis=1)   # the rest are masked off
    assert before.mean() > 0.9
    d, p = d[before], p[before]
    to_eye = (f1 - p) / np.linalg.norm(f1 - p, axis=1, keepdims=True)
    to_display = (d - p) / np.linalg.norm(d - p, axis=1, keepdims=True)
    to_f2 = (f2 - p) / np.linalg.norm(f2 - p, axis=1, keepdims=True)
    assert np.allclose(to_display, to_f2, atol=1e-6)        # the display lies on the line to F2
    normal = to_eye + to_f2
    normal /= np.linalg.norm(normal, axis=1, keepdims=True)
    assert np.allclose(np.sum(to_eye * normal, 1), np.sum(to_display * normal, 1), atol=1e-6)


def test_reflector_eyes_are_mirror_images_and_see_forward():
    left, right = stereo_tables(REFLECTOR, 48, 48)
    assert right.valid.mean() > 0.6
    assert (right.rays[right.valid][:, 1] > 0).all()
    assert np.allclose(left.rays[..., 0], -right.rays[:, ::-1, 0], atol=1e-6)
    assert np.array_equal(left.valid, right.valid[:, ::-1])
    for t in (left, right):                                 # some pixel looks straight ahead
        ahead = t.rays[t.valid] @ np.array([0, 1, 0], np.float32)
        assert math.degrees(math.acos(min(1.0, ahead.max()))) < 2.0


def test_reflector_field_of_view_is_wide():
    fov = field_of_view(REFLECTOR, 121)
    assert fov.horizontal > 100 and fov.vertical > 60
    assert 40 < fov.overlap < fov.per_eye_horizontal
    assert fov.temporal > fov.nasal


def test_reflector_panorama_puts_the_forward_marker_where_the_eye_looks_ahead():
    tables = stereo_tables(REFLECTOR, 96, 96)
    pano = np.zeros((360, 720, 3), np.uint8)
    pano[170:190, 350:370] = (255, 0, 0)
    frame = PanoramaRenderer(pano, tables).render(rot(qt.IDENTITY))
    for eye, t in enumerate(tables):
        ahead = np.where(t.valid, t.rays @ np.array([0, 1, 0], np.float32), -1)
        i, j = np.unravel_index(np.argmax(ahead), ahead.shape)
        assert tuple(frame[i, j + eye * 96]) == (255, 0, 0)
    assert (frame[:, :96][~tables[0].valid] == 0).all()     # unseen pixels stay dark


def test_reflector_panels_fit_between_face_and_mirror():
    o = REFLECTOR
    assert o.panel_clearance() > 4.0                        # the panel never touches its mirror
    corners = o.panel_corners()
    assert corners[:, 1].min() > 20 and corners[:, 2].min() > 10   # clear of the brow and eyelids
    assert corners[:, 0].min() > 5                          # the two panels don't meet in the middle
