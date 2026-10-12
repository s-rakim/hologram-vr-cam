import json

import numpy as np
import pytest

from holomaker.__main__ import main
from holomaker.camera import Intrinsics
from holomaker.depth import (
    box_sum,
    depth_to_disparity,
    disparity_to_depth,
    fill_from_background,
    stereo_disparity,
)
from holomaker.outputs import anaglyph, fit, pepper_ghost, quilt, quilt_name, side_by_side, volume_slices
from holomaker.pointcloud import read_ply, to_points, write_ply
from holomaker.scene import demo_scene, demo_stereo_pair
from holomaker.views import shift_view, view_sweep

K = Intrinsics.from_fov(160, 120, 66.0)


def test_intrinsics_from_fov():
    k = Intrinsics.from_fov(640, 480, 90.0)
    assert k.fx == pytest.approx(320.0)
    assert (k.cx, k.cy) == (320.0, 240.0)
    half = k.scaled(320, 240)
    assert half.fx == pytest.approx(160.0) and half.cy == pytest.approx(120.0)


def test_box_sum_matches_brute_force():
    rng = np.random.default_rng(0)
    img = rng.random((9, 11))
    r = 2
    padded = np.pad(img, r, mode="edge")
    brute = np.array([[padded[y:y + 5, x:x + 5].sum() for x in range(11)] for y in range(9)])
    assert np.allclose(box_sum(img, r), brute)


def test_disparity_depth_round_trip():
    depth = np.array([[1.0, 2.0], [4.0, np.nan]], np.float32)
    back = disparity_to_depth(depth_to_disparity(depth, 500, 0.06), 500, 0.06)
    assert np.allclose(back[np.isfinite(depth)], depth[np.isfinite(depth)])
    assert np.isnan(back[1, 1])
    assert np.isnan(disparity_to_depth(np.array([0.0, -1.0]), 500, 0.06)).all()


def test_stereo_matcher_recovers_known_disparity():
    k = Intrinsics.from_fov(240, 180, 66.0)
    left, right, truth = demo_stereo_pair(k, baseline_m=0.063)
    disp = stereo_disparity(left, right, max_disp=32)
    true_disp = depth_to_disparity(truth, k.fx, 0.063)
    ok = np.isfinite(disp)
    assert ok.mean() > 0.85
    assert np.median(np.abs(disp[ok] - true_disp[ok])) < 0.6
    # The ball is nearer than the box, which is nearer than the wall.
    ball, box, wall = disp[90, 80], disp[90, 180], disp[20, 120]
    assert ball > box > wall


def test_matcher_rejects_flat_regions_and_bad_input():
    flat = np.full((40, 60, 3), 128, np.uint8)
    assert np.isnan(stereo_disparity(flat, flat, max_disp=8)).all()
    with pytest.raises(ValueError):
        stereo_disparity(flat, flat[:, :50], max_disp=8)
    with pytest.raises(ValueError):
        stereo_disparity(flat, flat, max_disp=60)


def test_fill_from_background_uses_the_far_side():
    depth = np.array([[1.0, np.nan, np.nan, 3.0]], np.float32)
    rgb = np.array([[[10, 0, 0], [0, 0, 0], [0, 0, 0], [30, 0, 0]]], np.uint8)
    z, img = fill_from_background(depth, rgb)
    assert z.tolist() == [[1.0, 3.0, 3.0, 3.0]]
    assert img[0, 1, 0] == 30
    with pytest.raises(ValueError):
        fill_from_background(np.full((2, 2), np.nan))


def test_shift_view_moves_near_pixels_more_and_occludes():
    depth = np.full((1, 20), 4.0, np.float32)
    depth[0, 10] = 1.0
    rgb = np.zeros((1, 20, 3), np.uint8)
    rgb[0, 10] = (255, 0, 0)
    fx, tx = 100.0, 0.04           # near pixel shifts 4 px left, far pixels 1 px
    out, z = shift_view(rgb, depth, fx, tx)
    assert tuple(out[0, 6]) == (255, 0, 0) and z[0, 6] == pytest.approx(1.0)
    assert np.isfinite(z).all()
    _, zraw = shift_view(rgb, depth, fx, tx, fill=False)
    assert np.isnan(zraw[0, -1])   # the far plane shifted left, leaving a hole


def test_view_sweep_is_centred_and_ordered():
    rgb, depth = demo_scene(K)
    views = view_sweep(rgb, depth, K.fx, 5, 0.1)
    assert len(views) == 5
    assert np.array_equal(views[2], shift_view(rgb, depth, K.fx, 0.0)[0])
    assert view_sweep(rgb, depth, K.fx, 1, 0.1)[0].shape == rgb.shape


def test_point_cloud_axes_and_ply_round_trip(tmp_path):
    depth = np.full((2, 2), 2.0, np.float32)
    depth[1, 1] = np.nan
    rgb = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)
    k = Intrinsics(2, 2, 1.0, 1.0, 1.0, 1.0)
    pts, cols = to_points(rgb, depth, k)
    assert len(pts) == 3
    assert (pts[:, 2] == -2.0).all()                # camera looks down -Z
    assert pts[0, 1] > 0                            # top row is up (+Y)
    write_ply(tmp_path / "c.ply", pts, cols)
    p2, c2 = read_ply(tmp_path / "c.ply")
    assert np.allclose(p2, pts) and np.array_equal(c2, cols)
    assert to_points(rgb, depth, k, max_depth=1.0)[0].shape == (0, 3)


def test_fit_keeps_aspect():
    img = np.full((10, 20, 3), 200, np.uint8)
    out = fit(img, 40, 40)
    assert out.shape == (40, 40, 3)
    assert out[20, 20, 0] == 200 and out[2, 20, 0] == 0   # letterboxed top and bottom


def test_pepper_ghost_faces_point_outwards():
    img = np.zeros((30, 30, 3), np.uint8)
    img[:5] = (255, 255, 255)                      # mark the top edge
    out = pepper_ghost(img, size=90)
    assert out[30:60, 30:60].max() == 0            # centre stays black for the pyramid tip
    assert out[0:5, 30:60].min() == 255            # top copy: top edge at the screen's top
    assert out[85:90, 30:60].min() == 255          # bottom copy: top edge at the screen's bottom
    assert out[30:60, 0:5].min() == 255            # left copy: top edge at the left
    assert out[30:60, 85:90].min() == 255          # right copy: top edge at the right


def test_quilt_order_and_name():
    views = [np.full((4, 6, 3), i, np.uint8) for i in range(6)]
    q = quilt(views, cols=3, rows=2)
    assert q.shape == (8, 18, 3)
    assert q[7, 0, 0] == 0          # view 0 bottom-left
    assert q[7, 17, 0] == 2         # view 2 bottom-right
    assert q[0, 0, 0] == 3          # view 3 top-left
    assert quilt_name("x", 3, 2, 6, 4) == "x_qs3x2a1.50.png"
    with pytest.raises(ValueError):
        quilt(views, 2, 2)


def test_volume_slices_partition_the_scene():
    rgb, depth = demo_scene(K)
    slices, edges = volume_slices(rgb, depth, 8)
    assert slices.shape == (8, K.height, K.width, 3) and len(edges) == 9
    lit = (slices.max(axis=-1) > 0).sum(axis=0)
    assert lit.max() <= 1                           # every pixel lands in at most one slice
    assert slices[-1].any()                         # the back wall is in the last slice


def test_stereo_helpers():
    a = np.zeros((2, 2, 3), np.uint8)
    b = np.full((2, 2, 3), 9, np.uint8)
    a[..., 0] = 5
    assert side_by_side(a, b).shape == (2, 4, 3)
    assert anaglyph(a, b)[0, 0].tolist() == [5, 9, 9]


def test_cli_demo_writes_every_output(tmp_path, capsys):
    assert main(["demo", "--out", str(tmp_path), "--quilt", "4", "2", "--slices", "4"]) == 0
    meta = json.loads((tmp_path / "demo.json").read_text())
    for name in meta["files"].values():
        assert (tmp_path / name).exists(), name
    assert len(list((tmp_path / "demo_slices").glob("slice_*.png"))) == 4
    assert (tmp_path / "demo_qs4x2a1.33.png").exists()
    assert meta["stats"]["matched_fraction"] > 0.85
    assert "median_depth_error_pct" in capsys.readouterr().out


def test_cli_rgbd_checks_sizes(tmp_path):
    from hologram.imageio import write_png

    rgb, depth = demo_scene(K)
    write_png(tmp_path / "img.png", rgb)
    np.save(tmp_path / "d.npy", depth)
    np.save(tmp_path / "bad.npy", depth[:10])
    pytest.importorskip("PIL")
    assert main(["rgbd", str(tmp_path / "img.png"), str(tmp_path / "bad.npy"), "--out", str(tmp_path)]) == 1
    assert main(["rgbd", str(tmp_path / "img.png"), str(tmp_path / "d.npy"), "--out", str(tmp_path / "o"),
                 "--quilt", "2", "2"]) == 0
    assert (tmp_path / "o" / "hologram.ply").exists()
