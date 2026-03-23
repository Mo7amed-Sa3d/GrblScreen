#!/bin/bash
# install.sh — Cutter Screen installation script
# Run as: sudo bash install.sh
#
# What this does:
#   1. Installs PyQt5 and pyserial
#   2. Adds current user to dialout group (serial port access)
#   3. Configures BTT TFT70 DSI display rotation (landscape)
#   4. Creates a systemd service to start Cutter Screen on boot
#   5. Creates a udev rule so /dev/ttyUSB0 is always the DLC32

set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$(whoami)}"
SERVICE_FILE="/etc/systemd/system/cutter-screen.service"

echo "=== Cutter Screen Installer ==="
echo "App directory : $APP_DIR"
echo "Running as    : $USER_NAME"
echo ""

# ── 1. System dependencies ───────────────────────────────────────────────────
echo "[1/6] Installing system packages..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3-pyqt5 \
    python3-pyqt5.qtserialport \
    python3-serial \
    python3-pip \
    libqt5serialport5 \
    xorg \
    openbox \
    x11-xserver-utils \
    unclutter \
    fonts-roboto

# ── 2. Serial port permissions ───────────────────────────────────────────────
echo "[2/6] Adding $USER_NAME to dialout group..."
usermod -aG dialout "$USER_NAME"

# ── 3. BTT TFT70 DSI display configuration ───────────────────────────────────
echo "[3/6] Configuring BTT TFT70 DSI display..."

# /boot/config.txt entries for BTT TFT70 (7 inch, 1024x600)
CONFIG=/boot/firmware/config.txt
[ -f /boot/config.txt ] && CONFIG=/boot/config.txt

if ! grep -q 'cutter_screen_display' "$CONFIG" 2>/dev/null; then
    cat >> "$CONFIG" << 'EOF'

# === Cutter Screen — BTT TFT70 DSI 7" 1024x600 ===
# cutter_screen_display
ignore_lcd=0
display_auto_detect=1
dtoverlay=vc4-kms-v3d
max_framebuffers=2
EOF
    echo "    Added display config to $CONFIG"
else
    echo "    Display config already present in $CONFIG"
fi

# ── 4. Touch input (GT911 I2C touch controller) ──────────────────────────────
echo "[4/6] Configuring GT911 touch controller..."

# Create X11 touchscreen calibration config
mkdir -p /etc/X11/xorg.conf.d
cat > /etc/X11/xorg.conf.d/99-touch.conf << 'EOF'
Section "InputClass"
    Identifier      "BTT TFT70 Touch"
    MatchProduct    "Goodix"
    MatchIsTouchscreen "on"
    Option "TransformationMatrix" "1 0 0 0 1 0 0 0 1"
    Option "SwapAxes" "0"
EndSection
EOF

# ── 5. Autostart via systemd ──────────────────────────────────────────────────
echo "[5/6] Creating systemd service..."

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Cutter Screen UI
After=multi-user.target

[Service]
User=$USER_NAME
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/$USER_NAME/.Xauthority
Environment=QT_QPA_PLATFORM=xcb
Environment=HOME=/home/$USER_NAME

ExecStartPre=/bin/sleep 3
ExecStart=/usr/bin/python3 $APP_DIR/main.py

Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF

# Auto-start X if not already running
XINITRC="/home/$USER_NAME/.xinitrc"
if [ ! -f "$XINITRC" ]; then
    cat > "$XINITRC" << 'EOF'
#!/bin/sh
# Hide cursor after 1 second of inactivity
unclutter -idle 1 &
# Disable screen blanking
xset s off
xset -dpms
xset s noblank
# Start openbox WM (lightweight)
exec openbox-session
EOF
    chown "$USER_NAME:$USER_NAME" "$XINITRC"
    chmod +x "$XINITRC"
fi

# Auto-login and auto-start X
AUTOLOGIN_DIR="/etc/systemd/system/getty@tty1.service.d"
mkdir -p "$AUTOLOGIN_DIR"
cat > "$AUTOLOGIN_DIR/autologin.conf" << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $USER_NAME --noclear %I linux
EOF

PROFILE="/home/$USER_NAME/.bash_profile"
if ! grep -q 'startx' "$PROFILE" 2>/dev/null; then
    cat >> "$PROFILE" << 'EOF'

# Auto-start X on tty1
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    startx
fi
EOF
    chown "$USER_NAME:$USER_NAME" "$PROFILE"
fi

# Enable and start service
systemctl daemon-reload
systemctl enable cutter-screen.service

# ── 6. udev rule for DLC32 serial port ────────────────────────────────────────
echo "[6/6] Creating udev rule for DLC32..."

cat > /etc/udev/rules.d/99-dlc32.rules << 'EOF'
# BTT MKS DLC32 — always appears as /dev/ttyDLC32
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", \
    SYMLINK+="ttyDLC32", MODE="0666"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", \
    SYMLINK+="ttyDLC32", MODE="0666"
EOF

udevadm control --reload-rules

echo ""
echo "=== Installation complete ==="
echo ""
echo "Next steps:"
echo "  1. Reboot the Pi:            sudo reboot"
echo "  2. After reboot, test with:  python3 $APP_DIR/main.py"
echo "  3. Connect DLC32 USB cable — it will appear as /dev/ttyDLC32"
echo "  4. In the Settings page, select the port and press Connect"
echo ""
echo "Logs: journalctl -u cutter-screen -f"
