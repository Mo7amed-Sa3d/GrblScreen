# pages/settings_page.py
# Settings — Serial connection, WiFi, System

import subprocess
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QComboBox, QLineEdit,
    QListWidget, QListWidgetItem, QFrame,
    QTabWidget, QSlider, QProgressBar, QSizePolicy,
    QMessageBox, QScrollArea
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt5.QtGui  import QColor


# ── WiFi scan thread ──────────────────────────────────────────────────────────
class _ScanThread(QThread):
    done = pyqtSignal(list)

    def run(self):
        try:
            subprocess.run(['nmcli', 'dev', 'wifi', 'rescan'],
                           timeout=8, capture_output=True)
            out = subprocess.check_output(
                ['nmcli', '-t', '-f', 'IN-USE,SSID,SIGNAL,SECURITY',
                 'dev', 'wifi', 'list'], timeout=8
            ).decode('utf-8', errors='replace')
            nets, seen = [], set()
            for line in out.strip().splitlines():
                p = line.split(':')
                if len(p) < 4: continue
                in_use = p[0].strip() == '*'
                ssid   = p[1].strip()
                if not ssid or ssid in seen: continue
                seen.add(ssid)
                try: sig = int(p[2].strip())
                except: sig = 0
                secure = bool(p[3].strip() and p[3].strip() != '--')
                nets.append((ssid, sig, secure, in_use))
            nets.sort(key=lambda n: (not n[3], -n[1]))
            self.done.emit(nets)
        except Exception:
            self.done.emit([])


class _ConnThread(QThread):
    result = pyqtSignal(bool, str)

    def __init__(self, ssid, pwd=None):
        super().__init__()
        self._ssid = ssid
        self._pwd  = pwd

    def run(self):
        try:
            cmd = ['nmcli', 'dev', 'wifi', 'connect', self._ssid]
            if self._pwd:
                cmd += ['password', self._pwd]
            out = subprocess.check_output(
                cmd, timeout=30, stderr=subprocess.STDOUT
            ).decode('utf-8', errors='replace').strip()
            self.result.emit('successfully' in out.lower(), out)
        except subprocess.CalledProcessError as e:
            self.result.emit(False, e.output.decode('utf-8', errors='replace').strip())
        except Exception as e:
            self.result.emit(False, str(e))


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception:
        return 1, '', ''


# ── Settings page ─────────────────────────────────────────────────────────────
class SettingsPage(QWidget):
    def __init__(self, grbl, parent=None):
        super().__init__(parent)
        self.setObjectName('page')
        self._grbl = grbl
        self._scan_t = self._conn_t = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)

        title = QLabel('Settings')
        title.setObjectName('pageTitle')
        root.addWidget(title)

        tabs = QTabWidget()
        tabs.setStyleSheet(
            'QTabWidget::pane { border:none; background:#1a1a1a; }'
            'QTabBar::tab { background:#2d2d2d; color:#aaa; padding:10px 20px;'
            '               border-radius:6px; margin:2px; font-size:14px; }'
            'QTabBar::tab:selected { background:#383838; color:#ff8c00; '
            '                        border-bottom:2px solid #ff8c00; }'
        )

        tabs.addTab(self._build_connection(), '⟳  Connection')
        tabs.addTab(self._build_wifi(),       '📶  WiFi')
        tabs.addTab(self._build_system(),     '🖥  System')

        root.addWidget(tabs, 1)

        self._grbl.connected.connect(self._on_connected)
        self._grbl.disconnected.connect(self._on_disconnected)

    # ── Connection tab ────────────────────────────────────────────────────────
    def _build_connection(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        # Port row
        row = QHBoxLayout()
        row.addWidget(QLabel('Port:'))
        self._port = QComboBox()
        self._port.setMinimumHeight(48)
        self._port.setMinimumWidth(220)
        row.addWidget(self._port)

        btn_r = QPushButton('⟳')
        btn_r.setMaximumWidth(52); btn_r.setMinimumHeight(48)
        btn_r.clicked.connect(self._refresh_ports)
        row.addWidget(btn_r)

        self._btn_conn = QPushButton('Connect')
        self._btn_conn.setProperty('role', 'success')
        self._btn_conn.setMinimumHeight(48)
        self._btn_conn.setMinimumWidth(120)
        self._btn_conn.clicked.connect(self._toggle_conn)
        row.addWidget(self._btn_conn)

        self._conn_lbl = QLabel('Not connected')
        self._conn_lbl.setStyleSheet('color:#f44336; font-weight:bold; font-size:14px;')
        row.addWidget(self._conn_lbl)
        row.addStretch()
        lay.addLayout(row)

        div = QFrame(); div.setFrameShape(QFrame.HLine); lay.addWidget(div)

        # GRBL settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        form  = QFormLayout(inner)
        form.setSpacing(8); form.setLabelAlignment(Qt.AlignRight)

        SETTINGS = [
            ('$32', 'Laser mode  (1=knife)', '1'),
            ('$100','X steps/mm',            '80'),
            ('$101','Y steps/mm',            '80'),
            ('$102','Z feed steps/mm',       '80'),
            ('$110','X max rate mm/min',     '6000'),
            ('$111','Y max rate mm/min',     '6000'),
            ('$112','Z max rate mm/min',     '2000'),
            ('$120','X accel mm/s²',         '500'),
            ('$121','Y accel mm/s²',         '500'),
            ('$122','Z accel mm/s²',         '150'),
            ('$21', 'Hard limits',           '1'),
            ('$22', 'Homing enable',         '1'),
            ('$23', 'Homing dir mask',       '1'),
        ]
        self._fields = {}
        for key, desc, default in SETTINGS:
            le = QLineEdit(default)
            le.setMaximumWidth(120); le.setMinimumHeight(40)
            btn = QPushButton('Set')
            btn.setMinimumHeight(40); btn.setMinimumWidth(56)
            btn.clicked.connect(lambda _, k=key, f=le: self._grbl.send('%s=%s' % (k, f.text().strip())))
            rw = QWidget()
            rl = QHBoxLayout(rw); rl.setContentsMargins(0,0,0,0); rl.setSpacing(6)
            rl.addWidget(le); rl.addWidget(btn); rl.addStretch()
            form.addRow('%s  %s' % (key, desc), rw)
            self._fields[key] = le
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        ar = QHBoxLayout()
        b1 = QPushButton('Read All ($$)')
        b1.setMinimumHeight(46); b1.clicked.connect(lambda: self._grbl.send('$$'))
        b2 = QPushButton('Reset ($RST=$)')
        b2.setProperty('role','danger'); b2.setMinimumHeight(46)
        b2.clicked.connect(lambda: self._grbl.send('$RST=$'))
        ar.addWidget(b1); ar.addWidget(b2); ar.addStretch()
        lay.addLayout(ar)

        self._refresh_ports()
        return w

    def _refresh_ports(self):
        self._port.clear()
        for name, desc in self._grbl.available_ports():
            lbl = '%s  (%s)' % (name, desc) if desc else name
            self._port.addItem(lbl, name)
        if not self._port.count():
            self._port.addItem('No ports found', '')

    def _toggle_conn(self):
        if self._grbl.is_connected():
            self._grbl.disconnect()
        else:
            p = self._port.currentData()
            if p and not self._grbl.connect(p):
                self._conn_lbl.setText('Failed: %s' % p)

    def _on_connected(self):
        self._conn_lbl.setText('Connected ✓')
        self._conn_lbl.setStyleSheet('color:#4caf50; font-weight:bold; font-size:14px;')
        self._btn_conn.setText('Disconnect')
        self._btn_conn.setProperty('role', 'danger')
        self._btn_conn.style().unpolish(self._btn_conn)
        self._btn_conn.style().polish(self._btn_conn)

    def _on_disconnected(self):
        self._conn_lbl.setText('Not connected')
        self._conn_lbl.setStyleSheet('color:#f44336; font-weight:bold; font-size:14px;')
        self._btn_conn.setText('Connect')
        self._btn_conn.setProperty('role', 'success')
        self._btn_conn.style().unpolish(self._btn_conn)
        self._btn_conn.style().polish(self._btn_conn)

    # ── WiFi tab ──────────────────────────────────────────────────────────────
    def _build_wifi(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # Current
        cur_row = QHBoxLayout()
        self._cur_ssid = QLabel('—')
        self._cur_ssid.setStyleSheet('font-size:16px; font-weight:bold; color:#ff8c00;')
        self._cur_ip = QLabel('')
        self._cur_ip.setStyleSheet('color:#aaa; font-size:13px;')
        btn_disc = QPushButton('Disconnect')
        btn_disc.setProperty('role', 'danger')
        btn_disc.setMinimumHeight(44)
        btn_disc.clicked.connect(self._wifi_disconnect)
        cur_row.addWidget(self._cur_ssid)
        cur_row.addSpacing(12)
        cur_row.addWidget(self._cur_ip)
        cur_row.addStretch()
        cur_row.addWidget(btn_disc)
        lay.addLayout(cur_row)

        # Scan row
        scan_row = QHBoxLayout()
        scan_lbl = QLabel('Networks')
        scan_lbl.setObjectName('cardTitle')
        scan_row.addWidget(scan_lbl)
        scan_row.addStretch()
        self._scan_btn = QPushButton('⟳  Scan')
        self._scan_btn.setMinimumHeight(40)
        self._scan_btn.setProperty('role','accent')
        self._scan_btn.clicked.connect(self._scan)
        scan_row.addWidget(self._scan_btn)
        lay.addLayout(scan_row)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0); self._progress.setMaximumHeight(6)
        self._progress.setVisible(False)
        lay.addWidget(self._progress)

        self._net_list = QListWidget()
        self._net_list.setMinimumHeight(150)
        self._net_list.itemClicked.connect(self._on_net_select)
        self._net_list.itemDoubleClicked.connect(self._wifi_connect)
        lay.addWidget(self._net_list, 1)

        # Password row
        pwd_row = QHBoxLayout()
        self._sel_lbl = QLabel('Select a network')
        self._sel_lbl.setStyleSheet('color:#aaa;')
        pwd_row.addWidget(self._sel_lbl)
        pwd_row.addStretch()
        pwd_row.addWidget(QLabel('Password:'))
        self._pwd = QLineEdit()
        self._pwd.setEchoMode(QLineEdit.Password)
        self._pwd.setPlaceholderText('blank = open')
        self._pwd.setMinimumHeight(44)
        self._pwd.setMinimumWidth(180)
        pwd_row.addWidget(self._pwd)
        self._btn_join = QPushButton('Join')
        self._btn_join.setProperty('role', 'success')
        self._btn_join.setMinimumHeight(44)
        self._btn_join.setEnabled(False)
        self._btn_join.clicked.connect(self._wifi_connect)
        pwd_row.addWidget(self._btn_join)
        self._wifi_msg = QLabel('')
        self._wifi_msg.setStyleSheet('color:#aaa;')
        pwd_row.addWidget(self._wifi_msg)
        lay.addLayout(pwd_row)

        self._refresh_wifi_current()
        return w

    def _bars(self, s):
        if s >= 75: return '████'
        if s >= 50: return '███░'
        if s >= 25: return '██░░'
        return '█░░░'

    def _refresh_wifi_current(self):
        try:
            out = subprocess.check_output(
                ['nmcli', '-t', '-f', 'ACTIVE,SSID,IP4', 'dev', 'wifi'],
                timeout=5
            ).decode('utf-8', errors='replace')
            for line in out.splitlines():
                p = line.split(':')
                if p[0] == 'yes':
                    self._cur_ssid.setText(p[1] if len(p) > 1 else '—')
                    self._cur_ip.setText(p[2] if len(p) > 2 else '')
                    return
            self._cur_ssid.setText('Not connected'); self._cur_ip.setText('')
        except Exception:
            self._cur_ssid.setText('nmcli unavailable'); self._cur_ip.setText('')

    def _scan(self):
        self._scan_btn.setEnabled(False); self._progress.setVisible(True)
        self._net_list.clear()
        self._scan_t = _ScanThread()
        self._scan_t.done.connect(self._on_scan)
        self._scan_t.start()

    @pyqtSlot(list)
    def _on_scan(self, nets):
        self._progress.setVisible(False); self._scan_btn.setEnabled(True)
        self._net_list.clear()
        for ssid, sig, secure, active in nets:
            text = '%s %s%s  %s  %d%%' % (
                '✓ ' if active else '  ',
                '🔒 ' if secure else '   ',
                ssid, self._bars(sig), sig
            )
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, ssid)
            if active: item.setForeground(QColor('#4caf50'))
            self._net_list.addItem(item)
        if not nets:
            self._net_list.addItem('No networks found')
        self._refresh_wifi_current()

    def _on_net_select(self, item):
        ssid = item.data(Qt.UserRole)
        if ssid:
            self._sel_lbl.setText(ssid)
            self._sel_lbl.setStyleSheet('color:#ff8c00; font-weight:bold;')
            self._btn_join.setEnabled(True)
            self._wifi_msg.setText('')

    def _wifi_connect(self, item=None):
        ssid = self._sel_lbl.text()
        if ssid in ('Select a network', ''): return
        pwd = self._pwd.text().strip() or None
        self._btn_join.setEnabled(False); self._progress.setVisible(True)
        self._wifi_msg.setText('Connecting…')
        self._conn_t = _ConnThread(ssid, pwd)
        self._conn_t.result.connect(self._on_wifi_result)
        self._conn_t.start()

    @pyqtSlot(bool, str)
    def _on_wifi_result(self, ok, msg):
        self._progress.setVisible(False); self._btn_join.setEnabled(True)
        if ok:
            self._wifi_msg.setText('Connected ✓')
            self._wifi_msg.setStyleSheet('color:#4caf50; font-weight:bold;')
            self._refresh_wifi_current()
        else:
            self._wifi_msg.setText('Failed')
            self._wifi_msg.setStyleSheet('color:#f44336;')

    def _wifi_disconnect(self):
        try:
            subprocess.run(['nmcli', 'dev', 'disconnect', 'wlan0'],
                           timeout=10, capture_output=True)
        except Exception: pass
        self._refresh_wifi_current()

    # ── System tab ────────────────────────────────────────────────────────────
    def _build_system(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(10); form.setLabelAlignment(Qt.AlignRight)

        # Hostname
        hn_row = QHBoxLayout()
        self._hostname = QLineEdit()
        self._hostname.setMinimumHeight(44)
        btn_hn = QPushButton('Apply')
        btn_hn.setMinimumHeight(44)
        btn_hn.clicked.connect(self._set_hostname)
        hn_row.addWidget(self._hostname); hn_row.addWidget(btn_hn)
        form.addRow('Hostname:', hn_row)

        # Timezone
        tz_row = QHBoxLayout()
        self._tz = QComboBox()
        self._tz.setMinimumHeight(44); self._tz.setMinimumWidth(240)
        self._populate_tz()
        btn_tz = QPushButton('Apply')
        btn_tz.setMinimumHeight(44)
        btn_tz.clicked.connect(self._set_tz)
        tz_row.addWidget(self._tz); tz_row.addWidget(btn_tz)
        form.addRow('Timezone:', tz_row)

        # Brightness
        br_row = QHBoxLayout()
        self._bright = QSlider(Qt.Horizontal)
        self._bright.setRange(20, 255); self._bright.setValue(200)
        self._bright.valueChanged.connect(self._set_brightness)
        self._bright_lbl = QLabel('200')
        self._bright_lbl.setMinimumWidth(36)
        self._bright.valueChanged.connect(lambda v: self._bright_lbl.setText(str(v)))
        br_row.addWidget(self._bright, 1); br_row.addWidget(self._bright_lbl)
        form.addRow('Brightness:', br_row)

        lay.addLayout(form)

        # Info labels
        self._lbl_os     = QLabel('—')
        self._lbl_ip     = QLabel('—')
        self._lbl_uptime = QLabel('—')
        for label, lbl in [('OS:', self._lbl_os),
                            ('IP:', self._lbl_ip),
                            ('Uptime:', self._lbl_uptime)]:
            lbl.setStyleSheet('color:#aaa; font-size:13px;')
            r = QHBoxLayout()
            l = QLabel(label); l.setStyleSheet('color:#666; font-size:13px; min-width:60px;')
            r.addWidget(l); r.addWidget(lbl); r.addStretch()
            lay.addLayout(r)

        lay.addStretch()

        # Power buttons
        pw = QHBoxLayout()
        b_reboot = QPushButton('⟳  Reboot')
        b_reboot.setProperty('role', 'warning')
        b_reboot.setMinimumHeight(56)
        b_reboot.clicked.connect(self._reboot)
        b_shutdown = QPushButton('⏻  Shutdown')
        b_shutdown.setProperty('role', 'danger')
        b_shutdown.setMinimumHeight(56)
        b_shutdown.clicked.connect(self._shutdown)
        pw.addWidget(b_reboot); pw.addWidget(b_shutdown); pw.addStretch()
        lay.addLayout(pw)

        self._load_system_info()
        return w

    def _populate_tz(self):
        common = ['Africa/Cairo','America/New_York','America/Los_Angeles',
                  'Asia/Dubai','Asia/Kolkata','Asia/Shanghai','Asia/Tokyo',
                  'Australia/Sydney','Europe/Berlin','Europe/Istanbul',
                  'Europe/London','Europe/Moscow','Europe/Paris','Pacific/Auckland']
        try:
            rc, out, _ = _run(['timedatectl','list-timezones'])
            zones = out.splitlines() if rc == 0 else common
        except Exception:
            zones = common
        self._tz.addItems(zones)

    def _load_system_info(self):
        rc, out, _ = _run(['hostname']); self._hostname.setText(out)
        try:
            tz = os.readlink('/etc/localtime').split('zoneinfo/')[-1]
            idx = self._tz.findText(tz)
            if idx >= 0: self._tz.setCurrentIndex(idx)
        except Exception: pass
        rc, out, _ = _run(['cat', '/etc/os-release'])
        for line in out.splitlines():
            if line.startswith('PRETTY_NAME='):
                self._lbl_os.setText(line.split('=',1)[1].strip('"'))
        rc, out, _ = _run(['hostname','-I'])
        self._lbl_ip.setText(out.split()[0] if out else 'No IP')
        rc, out, _ = _run(['uptime','-p'])
        self._lbl_uptime.setText(out)
        # Brightness
        for p in ['/sys/class/backlight/rpi_backlight/brightness',
                  '/sys/class/backlight/10-0045/brightness']:
            try:
                with open(p) as f:
                    self._bright.setValue(int(f.read().strip())); break
            except Exception: pass

    def _set_hostname(self):
        n = self._hostname.text().strip()
        if n: _run(['sudo','hostnamectl','set-hostname', n])

    def _set_tz(self):
        _run(['sudo','timedatectl','set-timezone', self._tz.currentText()])

    def _set_brightness(self, v):
        self._bright_lbl.setText(str(v))
        for p in ['/sys/class/backlight/rpi_backlight/brightness',
                  '/sys/class/backlight/10-0045/brightness']:
            try:
                with open(p,'w') as f: f.write(str(v)); return
            except Exception: pass

    def _reboot(self):
        if QMessageBox.question(self, 'Reboot', 'Reboot?',
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            _run(['sudo','reboot'])

    def _shutdown(self):
        if QMessageBox.question(self, 'Shutdown', 'Shut down?',
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            _run(['sudo','shutdown','-h','now'])