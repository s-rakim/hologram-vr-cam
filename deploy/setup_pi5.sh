#!/usr/bin/env bash
# One-time setup for the Raspberry Pi 5 in the Hologram VR helmet's rear pod.
# Target: Raspberry Pi OS Lite (64-bit, Bookworm). Run from the repo:
#     ./deploy/setup_pi5.sh
# Then reboot. The helmet software starts on boot as the "hologram-vr" service.
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
    python3-pil python3-smbus2 i2c-tools alsa-utils

echo "==> Interfaces: I2C (IMU + fuel gauge), I2S (the two ear-cup amps)"
sudo raspi-config nonint do_i2c 0
add_line() { grep -qxF "$1" "$CONFIG_TXT" || echo "$1" | sudo tee -a "$CONFIG_TXT" >/dev/null; }
add_line "# --- hologram-vr ---"
add_line "dtparam=i2s=on"
add_line "dtoverlay=hifiberry-dac"     # stereo I2S out: left amp = left ear, right amp = right ear
add_line "camera_auto_detect=1"
add_line "usb_max_current_enable=1"    # the UPS board supplies 5 A
add_line "gpio=22=op,dh"               # display board powered from boot (EDID readable, console visible)

echo "==> Display: one 2880x1440 side-by-side signal on HDMI0"
# Most dual-panel driver boards report this mode in their EDID. If yours shows a black
# screen or the wrong size, this forces it (remove it again if the board already works).
if ! grep -q "video=HDMI-A-1:" "$CMDLINE_TXT"; then
    sudo cp "$CMDLINE_TXT" "$CMDLINE_TXT.bak"
    sudo sed -i '1 s/$/ video=HDMI-A-1:2880x1440M@60D/' "$CMDLINE_TXT"
fi

echo "==> Settings and media folders"
sudo mkdir -p /etc/hologram
[ -f /etc/hologram/vr.toml ] || sudo cp "$REPO/config/vr.toml" /etc/hologram/vr.toml
sudo -u "$RUN_AS" mkdir -p "/home/$RUN_AS/Pictures/Hologram/360" "/home/$RUN_AS/DCIM/Hologram"

echo "==> Power off really means off"
# By default a halted Pi 5 keeps its power rails up and draws ~1.2-1.6 W, which would drain the
# cells after a power-off or the 3 % low-battery shutdown. The Pi 5's own power button turns it back on.
EEPROM_CONF="$(mktemp)"
sudo rpi-eeprom-config > "$EEPROM_CONF"
set_eeprom() { grep -q "^$1=" "$EEPROM_CONF" && sed -i "s/^$1=.*/$1=$2/" "$EEPROM_CONF" || echo "$1=$2" >> "$EEPROM_CONF"; }
set_eeprom POWER_OFF_ON_HALT 1
set_eeprom WAKE_ON_GPIO 0
sudo rpi-eeprom-config --apply "$EEPROM_CONF"
rm -f "$EEPROM_CONF"

echo "==> Allow the mode button to shut the Pi down"
echo "$RUN_AS ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff" | sudo tee /etc/sudoers.d/hologram-vr >/dev/null
sudo chmod 440 /etc/sudoers.d/hologram-vr

echo "==> Service"
sed -e "s|@USER@|$RUN_AS|g" -e "s|@REPO@|$REPO|g" "$REPO/deploy/hologram-vr.service" \
    | sudo tee /etc/systemd/system/hologram-vr.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable hologram-vr.service

cat <<DONE

Done. Reboot, then check (to switch the helmet on after a power-off, press the Pi 5's power
button through the hole in the rear pod cover):
  i2cdetect -y 1                  # 68 = IMU, 36 = UPS fuel gauge
  rpicam-hello --list-cameras     # the Camera Module 3 Wide
  aplay -l                        # sndrpihifiberry = the ear-cup amps
  python3 -m hologram.vr optics   # field of view of your settings (reads /etc/hologram/vr.toml)
  journalctl -u hologram-vr -f    # live log of the helmet software
DONE
