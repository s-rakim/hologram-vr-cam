#!/usr/bin/env bash
# One-time setup for the Raspberry Pi Zero 2 W inside the glasses.
# Tested target: Raspberry Pi OS Lite (64-bit, Bookworm). Run from the repo:
#     ./deploy/setup_pi.sh
# Then reboot. The glasses software starts on boot as the "hologram" service.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
RUN_AS="${SUDO_USER:-$USER}"
BOOT=/boot/firmware
[ -d "$BOOT" ] || BOOT=/boot
CONFIG_TXT="$BOOT/config.txt"
CMDLINE_TXT="$BOOT/cmdline.txt"

echo "==> Packages"
sudo apt-get update
sudo apt-get install -y python3-picamera2 python3-gpiozero python3-numpy python3-pygame \
    python3-pil python3-smbus2 ffmpeg i2c-tools alsa-utils

echo "==> Interfaces (I2C for the IMU, I2S for the mic + amp)"
sudo raspi-config nonint do_i2c 0
add_line() { grep -qxF "$1" "$CONFIG_TXT" || echo "$1" | sudo tee -a "$CONFIG_TXT" >/dev/null; }
add_line "# --- hologram-vr-cam ---"
add_line "dtparam=i2s=on"
add_line "dtoverlay=googlevoicehat-soundcard"   # INMP441 capture + MAX98357A playback on one I2S bus
add_line "camera_auto_detect=1"                 # if the OV5647 is not found, replace with dtoverlay=ov5647
add_line "gpu_mem=128"

echo "==> Force 1920x1080 on HDMI (micro-OLED driver boards often have odd EDIDs)"
if ! grep -q "video=HDMI-A-1:" "$CMDLINE_TXT"; then
    sudo cp "$CMDLINE_TXT" "$CMDLINE_TXT.bak"
    sudo sed -i '1 s/$/ video=HDMI-A-1:1920x1080M@60D/' "$CMDLINE_TXT"
fi

echo "==> Media folder"
sudo -u "$RUN_AS" mkdir -p "/home/$RUN_AS/DCIM/Hologram"

echo "==> Service"
sed -e "s|@USER@|$RUN_AS|g" -e "s|@REPO@|$REPO|g" "$REPO/deploy/hologram.service" \
    | sudo tee /etc/systemd/system/hologram.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable hologram.service

cat <<EOF

Done. Reboot, then check:
  i2cdetect -y 1             # the IMU should show up at 68
  rpicam-hello --list-cameras # the OV5647 should be listed
  arecord -l                 # the I2S microphone should be listed
  journalctl -u hologram -f  # live log of the glasses software
EOF
