# pages/wifi_page.py
# WiFi management using nmcli (NetworkManager CLI)
# nmcli is available on Raspberry Pi OS when NetworkManager is installed.
# Install if missing:  sudo apt-get install network-manager

import subprocess
import re
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem,
    QLineEdit, QGroupBox, QFrame, QProgressBar
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt5.QtGui  import QColor


# ── Background thread: run nmcli scan + list ──────────────────────────────────

class WifiScanThread(QThread):
    scan_done = pyqtSignal(list)   # list of (ssid, signal, secured, connected)

    def run(self):
        try:
            # Trigger a fresh scan (may take a couple seconds)
            subprocess.run(['nmcli', 'dev', 'wifi', 'rescan'],
                           timeout=8, capture_output=True)
            # List results
            out = subprocess.check_output(
                ['nmcli', '-t', '-f',
                 'IN-USE,SSID,SIGNAL,SECURITY',
                 'dev', 'wifi', 'list'],
                timeout=8
            ).decode('utf-8', errors='replace')
            networks = self._parse(out)
            self.scan_done.emit(networks)
        except Exception as e:
            self.scan_done.emit([])

    def _parse(self, text):
        networks = []
        seen = set()
        for line in text.strip().splitlines():
            parts = line.split(':')
            if len(parts) < 4:
                continue
            in_use   = parts[0].strip() == '*'
            ssid     = parts[1].strip()
            signal   = parts[2].strip()
            security = parts[3].strip()
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            try:
                sig = int(signal)
            except ValueError:
                sig = 0
            secured = bool(security and security != '--')
            networks.append((ssid, sig, secured, in_use))
        # Sort: connected first, then by signal strength
        networks.sort(key=lambda n: (not n[3], -n[1]))
        return networks


class WifiConnectThread(QThread):
    result = pyqtSignal(bool, str)   # (success, message)

    def __init__(self, ssid, password=None):
        super().__init__()
        self._ssid     = ssid
        self._password = password

    def run(self):
        try:
            if self._password:
                cmd = ['nmcli', 'dev', 'wifi', 'connect',
                       self._ssid, 'password', self._password]
            else:
                cmd = ['nmcli', 'dev', 'wifi', 'connect', self._ssid]
            out = subprocess.check_output(
                cmd, timeout=30, stderr=subprocess.STDOUT
            ).decode('utf-8', errors='replace').strip()
            success = 'successfully' in out.lower()
            self.result.emit(success, out)
        except subprocess.CalledProcessError as e:
            msg = e.output.decode('utf-8', errors='replace').strip()
            self.result.emit(False, msg)
        except Exception as e:
            self.result.emit(False, str(e))


# ── Page widget ───────────────────────────────────────────────────────────────

class WifiPage(QWidget):
    def __init__(self, grbl=None, parent=None):
        super().__init__(parent)
        self._scan_thread    = None
        self._connect_thread = None
        self._networks       = []
        self._build_ui()
        self._refresh_current()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 8)
        root.setSpacing(12)

        title = QLabel('WiFi')
        title.setObjectName('pageTitle')
        root.addWidget(title)

        # ── Current connection ────────────────────────────────────────────────
        curr_box = QGroupBox('Current Connection')
        curr_lay = QHBoxLayout(curr_box)

        self._curr_ssid = QLabel('Scanning…')
        self._curr_ssid.setStyleSheet(
            'font-size:16px; font-weight:bold; color:#a0c4ff;'
        )
        self._curr_ip = QLabel('')
        self._curr_ip.setStyleSheet('font-size:14px; color:#7f8c8d;')

        btn_disconnect = QPushButton('Disconnect')
        btn_disconnect.setProperty('role', 'danger')
        btn_disconnect.setMinimumHeight(44)
        btn_disconnect.clicked.connect(self._disconnect)

        curr_lay.addWidget(self._curr_ssid)
        curr_lay.addSpacing(16)
        curr_lay.addWidget(self._curr_ip)
        curr_lay.addStretch()
        curr_lay.addWidget(btn_disconnect)

        root.addWidget(curr_box)

        # ── Network list ──────────────────────────────────────────────────────
        list_header = QHBoxLayout()
        list_header.addWidget(QLabel('Available Networks'))
        list_header.addStretch()

        self._scan_btn = QPushButton('⟳  Scan')
        self._scan_btn.setMinimumHeight(40)
        self._scan_btn.setProperty('role', 'primary')
        self._scan_btn.clicked.connect(self._scan)
        list_header.addWidget(self._scan_btn)
        root.addLayout(list_header)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # indeterminate
        self._progress.setMaximumHeight(6)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._list = QListWidget()
        self._list.setMinimumHeight(180)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        root.addWidget(self._list, 1)

        # ── Password / connect ────────────────────────────────────────────────
        conn_box = QGroupBox('Connect')
        conn_lay = QHBoxLayout(conn_box)

        self._selected_lbl = QLabel('Select a network above')
        self._selected_lbl.setStyleSheet('color:#7f8c8d;')
        conn_lay.addWidget(self._selected_lbl)

        conn_lay.addSpacing(10)
        conn_lay.addWidget(QLabel('Password:'))

        self._pwd_input = QLineEdit()
        self._pwd_input.setPlaceholderText('Leave blank for open networks')
        self._pwd_input.setEchoMode(QLineEdit.Password)
        self._pwd_input.setMinimumHeight(44)
        self._pwd_input.setMinimumWidth(220)
        conn_lay.addWidget(self._pwd_input)

        self._conn_btn = QPushButton('Connect')
        self._conn_btn.setProperty('role', 'success')
        self._conn_btn.setMinimumHeight(44)
        self._conn_btn.setEnabled(False)
        self._conn_btn.clicked.connect(self._connect)
        conn_lay.addWidget(self._conn_btn)

        self._conn_status = QLabel('')
        self._conn_status.setStyleSheet('color:#a0c4ff;')
        conn_lay.addWidget(self._conn_status)
        conn_lay.addStretch()

        root.addWidget(conn_box)

        self._list.itemClicked.connect(self._on_select)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _signal_bars(self, strength):
        if strength >= 75: return '████'
        if strength >= 50: return '███░'
        if strength >= 25: return '██░░'
        return '█░░░'

    def _refresh_current(self):
        """Show current SSID and IP without a full scan."""
        try:
            out = subprocess.check_output(
                ['nmcli', '-t', '-f', 'ACTIVE,SSID,IP4',
                 'dev', 'wifi'],
                timeout=5
            ).decode('utf-8', errors='replace')
            for line in out.splitlines():
                parts = line.split(':')
                if parts[0] == 'yes':
                    self._curr_ssid.setText(parts[1] if len(parts) > 1 else '—')
                    self._curr_ip.setText(parts[2] if len(parts) > 2 else '')
                    return
            self._curr_ssid.setText('Not connected')
            self._curr_ip.setText('')
        except Exception:
            self._curr_ssid.setText('nmcli not available')
            self._curr_ip.setText('')

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _scan(self):
        self._scan_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._list.clear()
        self._scan_thread = WifiScanThread()
        self._scan_thread.scan_done.connect(self._on_scan_done)
        self._scan_thread.start()

    @pyqtSlot(list)
    def _on_scan_done(self, networks):
        self._networks = networks
        self._list.clear()
        self._progress.setVisible(False)
        self._scan_btn.setEnabled(True)

        for ssid, signal, secured, connected in networks:
            bars   = self._signal_bars(signal)
            lock   = '🔒 ' if secured else '   '
            star   = '✓ ' if connected else '  '
            text   = '%s%s%s  %s  %d%%' % (star, lock, ssid, bars, signal)
            item   = QListWidgetItem(text)
            item.setData(Qt.UserRole, ssid)
            if connected:
                item.setForeground(QColor('#27ae60'))
            self._list.addItem(item)

        if not networks:
            self._list.addItem('No networks found — try scanning again')

        self._refresh_current()

    # ── Selection ─────────────────────────────────────────────────────────────

    def _on_select(self, item):
        ssid = item.data(Qt.UserRole)
        if ssid:
            self._selected_lbl.setText(ssid)
            self._selected_lbl.setStyleSheet(
                'font-weight:bold; color:#a0c4ff;'
            )
            self._conn_btn.setEnabled(True)
            self._pwd_input.clear()
            self._conn_status.setText('')

    def _on_double_click(self, item):
        self._on_select(item)
        self._connect()

    # ── Connect ───────────────────────────────────────────────────────────────

    def _connect(self):
        ssid = self._selected_lbl.text()
        if not ssid or ssid == 'Select a network above':
            return
        pwd = self._pwd_input.text().strip() or None

        self._conn_btn.setEnabled(False)
        self._conn_status.setText('Connecting…')
        self._progress.setVisible(True)

        self._connect_thread = WifiConnectThread(ssid, pwd)
        self._connect_thread.result.connect(self._on_connect_result)
        self._connect_thread.start()

    @pyqtSlot(bool, str)
    def _on_connect_result(self, success, message):
        self._progress.setVisible(False)
        self._conn_btn.setEnabled(True)
        if success:
            self._conn_status.setText('Connected ✓')
            self._conn_status.setStyleSheet('color:#27ae60; font-weight:bold;')
            self._refresh_current()
        else:
            short = message.split('\n')[0][:60]
            self._conn_status.setText('Failed: %s' % short)
            self._conn_status.setStyleSheet('color:#e74c3c;')

    # ── Disconnect ────────────────────────────────────────────────────────────

    def _disconnect(self):
        try:
            subprocess.run(
                ['nmcli', 'dev', 'disconnect', 'wlan0'],
                timeout=10, capture_output=True
            )
        except Exception:
            pass
        self._refresh_current()