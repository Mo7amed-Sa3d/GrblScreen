# pages/system_page.py
# System settings — hostname, timezone, display brightness, reboot/shutdown

import subprocess
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QLineEdit, QComboBox,
    QSlider, QGroupBox, QFrame, QMessageBox
)
from PyQt5.QtCore import Qt


def _run(cmd, **kwargs):
    """Run a shell command, return (returncode, stdout, stderr)."""
    r = subprocess.run(cmd, shell=isinstance(cmd, str),
                       capture_output=True, text=True,
                       timeout=10, **kwargs)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


class SystemPage(QWidget):
    def __init__(self, grbl=None, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load_current()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 8)
        root.setSpacing(14)

        title = QLabel('System')
        title.setObjectName('pageTitle')
        root.addWidget(title)

        # ── Hostname ──────────────────────────────────────────────────────────
        host_box = QGroupBox('Hostname')
        host_lay = QHBoxLayout(host_box)

        self._hostname_input = QLineEdit()
        self._hostname_input.setMinimumHeight(44)
        self._hostname_input.setMinimumWidth(260)

        btn_hostname = QPushButton('Apply')
        btn_hostname.setProperty('role', 'primary')
        btn_hostname.setMinimumHeight(44)
        btn_hostname.clicked.connect(self._set_hostname)

        host_lay.addWidget(self._hostname_input)
        host_lay.addWidget(btn_hostname)
        host_lay.addStretch()

        root.addWidget(host_box)

        # ── Timezone ──────────────────────────────────────────────────────────
        tz_box = QGroupBox('Timezone')
        tz_lay = QHBoxLayout(tz_box)

        self._tz_combo = QComboBox()
        self._tz_combo.setMinimumHeight(44)
        self._tz_combo.setMinimumWidth(280)
        self._populate_timezones()

        btn_tz = QPushButton('Apply')
        btn_tz.setProperty('role', 'primary')
        btn_tz.setMinimumHeight(44)
        btn_tz.clicked.connect(self._set_timezone)

        tz_lay.addWidget(self._tz_combo)
        tz_lay.addWidget(btn_tz)
        tz_lay.addStretch()

        root.addWidget(tz_box)

        # ── Display brightness ────────────────────────────────────────────────
        bright_box = QGroupBox('Display Brightness')
        bright_lay = QHBoxLayout(bright_box)

        bright_lay.addWidget(QLabel('0'))
        self._bright_slider = QSlider(Qt.Horizontal)
        self._bright_slider.setRange(20, 255)
        self._bright_slider.setValue(200)
        self._bright_slider.valueChanged.connect(self._set_brightness)
        bright_lay.addWidget(self._bright_slider, 1)
        bright_lay.addWidget(QLabel('255'))

        self._bright_lbl = QLabel('200')
        self._bright_lbl.setMinimumWidth(40)
        self._bright_lbl.setAlignment(Qt.AlignCenter)
        bright_lay.addWidget(self._bright_lbl)

        root.addWidget(bright_box)

        div = QFrame(); div.setFrameShape(QFrame.HLine)
        root.addWidget(div)

        # ── About ─────────────────────────────────────────────────────────────
        about_box = QGroupBox('About')
        about_lay = QFormLayout(about_box)

        self._lbl_os      = QLabel('…')
        self._lbl_ip      = QLabel('…')
        self._lbl_uptime  = QLabel('…')
        self._lbl_version = QLabel('Cutter Screen 1.0')

        about_lay.addRow('OS:',      self._lbl_os)
        about_lay.addRow('IP:',      self._lbl_ip)
        about_lay.addRow('Uptime:',  self._lbl_uptime)
        about_lay.addRow('Version:', self._lbl_version)

        root.addWidget(about_box)
        root.addStretch()

        # ── Power buttons ─────────────────────────────────────────────────────
        power_row = QHBoxLayout()

        btn_reboot = QPushButton('⟳  Reboot')
        btn_reboot.setProperty('role', 'warning')
        btn_reboot.setMinimumHeight(56)
        btn_reboot.clicked.connect(self._reboot)

        btn_shutdown = QPushButton('⏻  Shutdown')
        btn_shutdown.setProperty('role', 'danger')
        btn_shutdown.setMinimumHeight(56)
        btn_shutdown.clicked.connect(self._shutdown)

        power_row.addWidget(btn_reboot)
        power_row.addWidget(btn_shutdown)
        power_row.addStretch()

        root.addLayout(power_row)

    # ── Load current system state ─────────────────────────────────────────────

    def _load_current(self):
        # Hostname
        rc, out, _ = _run(['hostname'])
        self._hostname_input.setText(out)

        # Current timezone
        try:
            tz = os.readlink('/etc/localtime').split('zoneinfo/')[-1]
            idx = self._tz_combo.findText(tz)
            if idx >= 0:
                self._tz_combo.setCurrentIndex(idx)
        except Exception:
            pass

        # OS info
        rc, out, _ = _run(['cat', '/etc/os-release'])
        for line in out.splitlines():
            if line.startswith('PRETTY_NAME='):
                self._lbl_os.setText(line.split('=', 1)[1].strip('"'))
                break

        # IP address
        rc, out, _ = _run(['hostname', '-I'])
        self._lbl_ip.setText(out.split()[0] if out else 'No IP')

        # Uptime
        rc, out, _ = _run(['uptime', '-p'])
        self._lbl_uptime.setText(out)

        # Current brightness
        self._bright_slider.setValue(self._read_brightness())

    def _populate_timezones(self):
        common = [
            'Africa/Cairo', 'America/New_York', 'America/Chicago',
            'America/Denver', 'America/Los_Angeles', 'America/Sao_Paulo',
            'Asia/Dubai', 'Asia/Kolkata', 'Asia/Shanghai', 'Asia/Tokyo',
            'Australia/Sydney', 'Europe/Berlin', 'Europe/Istanbul',
            'Europe/London', 'Europe/Moscow', 'Europe/Paris',
            'Pacific/Auckland',
        ]
        try:
            rc, all_tz, _ = _run(['timedatectl', 'list-timezones'])
            zones = all_tz.splitlines() if rc == 0 else common
        except Exception:
            zones = common
        self._tz_combo.addItems(zones)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _set_hostname(self):
        name = self._hostname_input.text().strip()
        if not name:
            return
        _run(['sudo', 'hostnamectl', 'set-hostname', name])

    def _set_timezone(self):
        tz = self._tz_combo.currentText()
        _run(['sudo', 'timedatectl', 'set-timezone', tz])

    def _set_brightness(self, value):
        self._bright_lbl.setText(str(value))
        # Raspberry Pi DSI display brightness via rpi-backlight or sysfs
        paths = [
            '/sys/class/backlight/rpi_backlight/brightness',
            '/sys/class/backlight/10-0045/brightness',
        ]
        for path in paths:
            try:
                with open(path, 'w') as f:
                    f.write(str(value))
                return
            except Exception:
                pass

    def _read_brightness(self):
        paths = [
            '/sys/class/backlight/rpi_backlight/brightness',
            '/sys/class/backlight/10-0045/brightness',
        ]
        for path in paths:
            try:
                with open(path) as f:
                    return int(f.read().strip())
            except Exception:
                pass
        return 200

    def _reboot(self):
        reply = QMessageBox.question(
            self, 'Reboot', 'Reboot the Raspberry Pi?',
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            _run(['sudo', 'reboot'])

    def _shutdown(self):
        reply = QMessageBox.question(
            self, 'Shutdown', 'Shut down the Raspberry Pi?',
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            _run(['sudo', 'shutdown', '-h', 'now'])