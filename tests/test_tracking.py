import math

import pytest

from hologram import quaternion as qt
from hologram.fusion import HeadTracker, Madgwick
from hologram.imu import MPU6050, axis_remap


def close(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def test_rotation_about_z_turns_forward_to_the_left():
    q = qt.yaw_quat(math.radians(90))
    assert close(qt.rotate(q, (0, 1, 0)), (-1, 0, 0))
    assert qt.yaw(q) == pytest.approx(math.radians(90))


def test_matrix_matches_rotate():
    q = qt.normalize((0.9, 0.1, -0.3, 0.2))
    m = qt.to_matrix(q)
    v = (0.3, -1.2, 0.5)
    mv = tuple(sum(m[r][c] * v[c] for c in range(3)) for r in range(3))
    assert close(mv, qt.rotate(q, v))


def test_level_and_still_stays_identity():
    f = Madgwick(beta=0.1)
    for _ in range(500):
        f.update((0, 0, 0), (0, 0, 1), 0.005)
    assert close(f.q, qt.IDENTITY, 1e-6)


def test_converges_to_pitch_from_gravity():
    theta = math.radians(20)   # nose up 20 degrees: world-up seen in the device frame
    f = Madgwick(beta=0.5)
    for _ in range(4000):
        f.update((0, 0, 0), (0, math.sin(theta), math.cos(theta)), 0.005)
    assert qt.pitch(f.q) == pytest.approx(theta, abs=math.radians(0.5))


def test_gyro_integrates_yaw():
    f = Madgwick(beta=0.05)
    rate = math.radians(45)
    for _ in range(200):           # 1 s at 200 Hz
        f.update((0, 0, rate), (0, 0, 1), 0.005)
    assert qt.yaw(f.q) == pytest.approx(rate, abs=math.radians(1))


def test_calibration_removes_bias_and_levels():
    t = HeadTracker(beta=0.05)
    bias = (0.01, -0.02, 0.03)
    theta = math.radians(-10)
    gravity = (0.0, math.sin(theta), math.cos(theta))
    t.calibrate([(bias, gravity)] * 50)
    assert qt.pitch(t.orientation()) == pytest.approx(theta, abs=1e-6)
    for i in range(400):
        t.update(bias, gravity, i * 0.005)
    assert abs(qt.yaw(t.orientation())) < math.radians(0.2)


def test_recenter_zeroes_yaw_but_keeps_pitch():
    t = HeadTracker()
    t.set_orientation(qt.mul(qt.yaw_quat(math.radians(70)), qt.from_axis_angle((1, 0, 0), math.radians(15))))
    t.recenter()
    q = t.orientation()
    assert qt.yaw(q) == pytest.approx(0.0, abs=1e-9)
    assert qt.pitch(q) == pytest.approx(math.radians(15), abs=1e-9)


class FakeBus:
    def __init__(self, who=0x68):
        self.who = who
        self.writes = {}
        # ax = +1 g on z, gyro x = +65.5 LSB = 1 deg/s
        self.block = [0, 0, 0, 0, 0x40, 0x00, 0, 0, 0x00, 0x41, 0, 0, 0xFF, 0xBF]

    def read_byte_data(self, addr, reg):
        return self.who

    def write_byte_data(self, addr, reg, value):
        self.writes[reg] = value

    def read_i2c_block_data(self, addr, reg, length):
        assert reg == 0x3B and length == 14
        return self.block


def test_mpu6050_configures_and_scales():
    bus = FakeBus()
    imu = MPU6050(smbus=bus)
    assert bus.writes[MPU6050.PWR_MGMT_1] == 0x01
    assert bus.writes[MPU6050.GYRO_CONFIG] == 0x08
    s = imu.read()
    assert close(s.accel, (0, 0, 1.0))
    assert s.gyro[0] == pytest.approx(math.radians(65 / 65.5))
    assert s.gyro[2] == pytest.approx(math.radians(-65 / 65.5))


def test_mpu6050_rejects_wrong_chip():
    with pytest.raises(OSError):
        MPU6050(smbus=FakeBus(who=0x12))


def test_axis_remap():
    remap = axis_remap(("-y", "x", "z"))
    assert remap((1, 2, 3)) == (-2, 1, 3)
    with pytest.raises(ValueError):
        axis_remap(("x", "x", "z"))
