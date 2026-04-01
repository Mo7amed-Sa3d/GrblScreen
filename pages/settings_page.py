# pages/settings_page.py
# Settings screen — MCU connection + WiFi + System + Terminal (4 tabs)

import subprocess, os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QComboBox, QLineEdit,
    QListWidget, QListWidgetItem, QFrame,
    QTabWidget, QSlider, QProgressBar,
    QMessageBox, QScrollArea, QPlainTextEdit, QSpinBox,
    QGridLayout, QSizePolicy
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QEvent
from PyQt5.QtGui  import QColor, QGuiApplication


# ── WiFi threads ──────────────────────────────────────────────────────────────
class _ScanThread(QThread):
    done = pyqtSignal(list)
    def run(self):
        try:
            subprocess.run(['nmcli','dev','wifi','rescan'], timeout=8, capture_output=True)
            out = subprocess.check_output(
                ['nmcli','-t','-f','IN-USE,SSID,SIGNAL,SECURITY','dev','wifi','list'],
                timeout=8).decode('utf-8', errors='replace')
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
        except Exception: self.done.emit([])


class _ConnThread(QThread):
    result = pyqtSignal(bool, str)
    def __init__(self, ssid, pwd=None):
        super().__init__(); self._ssid=ssid; self._pwd=pwd
    def run(self):
        try:
            cmd = ['nmcli','dev','wifi','connect', self._ssid]
            if self._pwd: cmd += ['password', self._pwd]
            out = subprocess.check_output(cmd, timeout=30,
                stderr=subprocess.STDOUT).decode('utf-8', errors='replace').strip()
            self.result.emit('successfully' in out.lower(), out)
        except subprocess.CalledProcessError as e:
            self.result.emit(False, e.output.decode('utf-8', errors='replace').strip())
        except Exception as e: self.result.emit(False, str(e))


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception: return 1, '', ''


class _TerminalLineEdit(QLineEdit):
    def __init__(self, *args, on_focus=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._on_focus = on_focus

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if self._on_focus:
            self._on_focus()


class _OnScreenKeyboard(QWidget):
    def __init__(self, target, on_enter=None, parent=None):
        super().__init__(parent)
        self._target = target
        self._on_enter = on_enter
        self.setVisible(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(
            'background:#222; border:1px solid #444; padding:6px;'
            'QPushButton { min-height:36px; min-width:32px; font-size:14px; color:#eee; background:#333; border:1px solid #555; border-radius:3px; }'
            'QPushButton:pressed { background:#555; }'
        )
        # Main vertical layout for rows
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        rows = [
            '1234567890-=',
            'qwertyuiop$&',
            'asdfghjkl;\'',
            'zxcvbnm,./'
        ]

        for keys in rows:
            row = QHBoxLayout()
            row.setSpacing(2)
            for ch in keys:
                btn = QPushButton(ch.upper())
                btn.clicked.connect(lambda _, c=ch: self._type(c))
                btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)   # <-- fixed vertical size
                btn.setFixedHeight(36)  # ensure consistent height
                row.addWidget(btn)
            layout.addLayout(row)

        # Bottom control row
        row = QHBoxLayout()
        row.setSpacing(6)
        for label, action in (('⌫', 'BACK'),('Space', ' '), ('Enter', 'ENTER'), ('Hide', 'HIDE')):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, a=action: self._special(a))
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setFixedHeight(36)
            row.addWidget(btn)
        layout.addLayout(row)

    def _type(self, ch):
        text = self._target.text()
        pos = self._target.cursorPosition()
        self._target.setText(text[:pos] + ch + text[pos:])
        self._target.setCursorPosition(pos + 1)

    def _special(self, action):
        if action == ' ':
            self._type(' ')
        elif action == 'BACK':
            text = self._target.text()
            pos = self._target.cursorPosition()
            if pos > 0:
                self._target.setText(text[:pos-1] + text[pos:])
                self._target.setCursorPosition(pos-1)
        elif action == 'ENTER':
            if self._on_enter:
                self._on_enter()
        elif action == 'HIDE':
            self.setVisible(False)

# ── Settings page ─────────────────────────────────────────────────────────────
class SettingsPage(QWidget):
    def __init__(self, grbl, on_back, parent=None):
        super().__init__(parent)
        self._grbl   = grbl
        self._on_back = on_back
        self._scan_t = self._conn_t = None
        self._kbd_proc = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        btn_back = QPushButton('◀  Back')
        btn_back.setProperty('role', 'back')
        btn_back.setMinimumHeight(48); btn_back.setMaximumWidth(120)
        btn_back.clicked.connect(self._on_back)
        hdr.addWidget(btn_back)
        title = QLabel('Settings')
        title.setStyleSheet('font-size:18px; font-weight:bold; color:#ff8c00;')
        hdr.addWidget(title, 1)
        root.addLayout(hdr)

        # Tabs
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_mcu(),    '⟳  MCU')
        self._tabs.addTab(self._build_wifi(),   '📶  WiFi')
        self._tabs.addTab(self._build_system(), '🖥  System')
        self._tabs.addTab(self._build_terminal(), '⌨  Terminal')
        root.addWidget(self._tabs, 1)

        # Hide keyboard when switching tabs
        self._tabs.currentChanged.connect(self._hide_keyboard)

        self._grbl.connected.connect(   self._on_connected)
        self._grbl.disconnected.connect(self._on_disconnected)

    # ── MCU tab (connection + settings) ──────────────────────────────────────
    def _build_mcu(self):
        w = QWidget()
        w.setObjectName("MCUTab")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)

        # Port selection
        pr = QHBoxLayout()
        pr.addWidget(QLabel('Port:'))
        self._port = QComboBox()
        self._port.setMinimumHeight(48); self._port.setMinimumWidth(180)
        pr.addWidget(self._port, 1)
        b_ref = QPushButton('⟳')
        b_ref.setMaximumWidth(52); b_ref.setMinimumHeight(48)
        b_ref.clicked.connect(self._refresh_ports)
        pr.addWidget(b_ref)
        lay.addLayout(pr)

        # Connect / disconnect
        cr = QHBoxLayout()
        self._btn_conn = QPushButton('Connect')
        self._btn_conn.setProperty('role', 'success')
        self._btn_conn.setMinimumHeight(52)
        self._btn_conn.clicked.connect(self._toggle_conn)
        cr.addWidget(self._btn_conn)
        self._conn_lbl = QLabel('Not connected')
        self._conn_lbl.setStyleSheet('color:#f44336; font-weight:bold;')
        cr.addWidget(self._conn_lbl)
        cr.addStretch()
        lay.addLayout(cr)

        lay.addWidget(self._lbl('GRBL Settings', '#aaa'))

        # Scrollable $-settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        form = QFormLayout(inner)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)

        SETTINGS = [
            ('$32', 'Laser mode (1=knife)', '1'),
            ('$100','X steps/mm',           '80'),
            ('$101','Y steps/mm',           '80'),
            ('$102','Z steps/mm',           '80'),
            ('$110','X max rate',           '6000'),
            ('$111','Y max rate',           '6000'),
            ('$112','Z max rate',           '2000'),
            ('$120','X accel',              '500'),
            ('$121','Y accel',              '500'),
            ('$122','Z accel',              '150'),
            ('$21', 'Hard limits',          '1'),
            ('$22', 'Homing enable',        '1'),
        ]
        self._fields = {}
        for key, desc, default in SETTINGS:
            le = QLineEdit(default); le.setMaximumWidth(110); le.setMinimumHeight(40)
            btn = QPushButton('Set'); btn.setMinimumHeight(40); btn.setMaximumWidth(60)
            btn.clicked.connect(lambda _, k=key, f=le: self._grbl.send('%s=%s' % (k, f.text().strip())))
            rw = QWidget(); rl = QHBoxLayout(rw); rl.setContentsMargins(0,0,0,0); rl.setSpacing(4)
            rl.addWidget(le); rl.addWidget(btn); rl.addStretch()
            form.addRow('%s %s' % (key, desc), rw)
            self._fields[key] = le
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        # Buttons for $$, $X, $RST=$
        ar = QHBoxLayout()
        b1 = QPushButton('$$'); b1.setMinimumHeight(46); b1.clicked.connect(lambda: self._grbl.send('$$'))
        b2 = QPushButton('$X'); b2.setMinimumHeight(46); b2.clicked.connect(lambda: self._grbl.send('$X'))
        b3 = QPushButton('$RST=$'); b3.setProperty('role','danger'); b3.setMinimumHeight(46)
        b3.clicked.connect(lambda: self._grbl.send('$RST=$'))
        ar.addWidget(b1); ar.addWidget(b2); ar.addWidget(b3); ar.addStretch()
        lay.addLayout(ar)

        self._refresh_ports()
        return w

    # ── Terminal tab ─────────────────────────────────────────────────────────
    def _build_terminal(self):
        w = QWidget()
        w.setObjectName("TerminalTab")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)

        # Terminal display
        self._terminal = QPlainTextEdit()
        self._terminal.setReadOnly(True)
        self._terminal.setMinimumHeight(200)
        self._terminal.setStyleSheet('background:#121212; color:#eee;')
        lay.addWidget(self._terminal, 1)

        # Input row
        tr = QHBoxLayout()
        self._term_input = _TerminalLineEdit(on_focus=self._show_keyboard)
        self._term_input.setMinimumHeight(44)
        self._term_input.setPlaceholderText('Type GRBL command and press Send')
        self._term_input.returnPressed.connect(self._send_terminal)
        btn_send = QPushButton('Send')
        btn_send.setMinimumHeight(44); btn_send.setProperty('role','accent')
        btn_send.clicked.connect(self._send_terminal)
        btn_clear = QPushButton('Clear')
        btn_clear.setMinimumHeight(44); btn_clear.clicked.connect(self._terminal.clear)
        tr.addWidget(self._term_input, 1)
        tr.addWidget(btn_send); tr.addWidget(btn_clear)
        lay.addLayout(tr)

        # Keyboard (initially hidden)
        self._keyboard = _OnScreenKeyboard(self._term_input, on_enter=self._send_terminal)
        self._keyboard.setVisible(False)
        lay.addWidget(self._keyboard)

        # Install event filter to hide keyboard on outside click
        w.installEventFilter(self)
        # Connect raw_received to terminal
        self._grbl.raw_received.connect(self._on_raw_received)
        return w

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            # For Terminal tab: hide keyboard when clicking outside input or keyboard
            if obj.objectName() == "TerminalTab" and hasattr(self, '_keyboard') and self._keyboard.isVisible():
                kbd_rect = self._keyboard.geometry()
                input_rect = self._term_input.geometry()
                # Convert global coordinates to local of the terminal tab
                pos = self._keyboard.mapFromGlobal(event.globalPos())
                if not kbd_rect.contains(pos) and not input_rect.contains(self._term_input.mapFromGlobal(event.globalPos())):
                    self._keyboard.setVisible(False)
                    # Force layout update
                    if self.parentWidget():
                        self.parentWidget().layout().activate()
        return super().eventFilter(obj, event)

    # ── Helpers (shared) ─────────────────────────────────────────────────────
    def _lbl(self, text, color='#aaa'):
        l = QLabel(text); l.setStyleSheet('color:%s; font-size:13px; font-weight:bold;' % color)
        return l

    def _refresh_ports(self):
        self._port.clear()
        for name, desc in self._grbl.available_ports():
            lbl = '%s  (%s)' % (name, desc) if desc else name
            self._port.addItem(lbl, name)
        if not self._port.count(): self._port.addItem('No ports found', '')

    def _send_terminal(self):
        text = self._term_input.text().strip()
        if not text:
            return
        self._term_input.clear()
        self._append_terminal('> %s' % text)
        self._grbl.send(text)
        self._hide_keyboard()

    @pyqtSlot(str)
    def _on_raw_received(self, line):
        if line.startswith('<'):
            return
        self._append_terminal(line)

    def _append_terminal(self, text):
        if hasattr(self, '_terminal'):
            self._terminal.appendPlainText(text)
            self._terminal.verticalScrollBar().setValue(
                self._terminal.verticalScrollBar().maximum())

    def _show_keyboard(self):
        if hasattr(self, '_keyboard') and not self._keyboard.isVisible():
            self._keyboard.setVisible(True)
            self._keyboard.raise_()
            if self.parentWidget():
                self.parentWidget().layout().activate()

    def _hide_keyboard(self):
        if hasattr(self, '_keyboard') and self._keyboard.isVisible():
            self._keyboard.setVisible(False)
            if self.parentWidget():
                self.parentWidget().layout().activate()

    def _toggle_conn(self):
        if self._grbl.is_connected(): self._grbl.disconnect()
        else:
            p = self._port.currentData()
            if p and not self._grbl.connect(p):
                self._conn_lbl.setText('Failed: %s' % p)

    def _on_connected(self):
        self._conn_lbl.setText('Connected ✓')
        self._conn_lbl.setStyleSheet('color:#4caf50; font-weight:bold;')
        self._btn_conn.setText('Disconnect'); self._btn_conn.setProperty('role','danger')
        self._restyle(self._btn_conn)

    def _on_disconnected(self):
        self._conn_lbl.setText('Not connected')
        self._conn_lbl.setStyleSheet('color:#f44336; font-weight:bold;')
        self._btn_conn.setText('Connect'); self._btn_conn.setProperty('role','success')
        self._restyle(self._btn_conn)

    def _restyle(self, w):
        w.style().unpolish(w); w.style().polish(w)

    # ── WiFi tab (unchanged) ─────────────────────────────────────────────────
    def _build_wifi(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)

        # Current
        cur = QHBoxLayout()
        self._cur_ssid = QLabel('—')
        self._cur_ssid.setStyleSheet('font-size:15px; font-weight:bold; color:#ff8c00;')
        self._cur_ip = QLabel('')
        self._cur_ip.setStyleSheet('color:#aaa; font-size:12px;')
        b_disc = QPushButton('Disconnect'); b_disc.setProperty('role','danger')
        b_disc.setMinimumHeight(44); b_disc.setMaximumWidth(130)
        b_disc.clicked.connect(self._wifi_disconnect)
        cur.addWidget(self._cur_ssid); cur.addWidget(self._cur_ip)
        cur.addStretch(); cur.addWidget(b_disc)
        lay.addLayout(cur)

        # Scan row
        sr = QHBoxLayout()
        sr.addWidget(self._lbl('Networks'))
        sr.addStretch()
        self._scan_btn = QPushButton('⟳ Scan')
        self._scan_btn.setProperty('role','accent')
        self._scan_btn.setMinimumHeight(40); self._scan_btn.setMinimumWidth(100)
        self._scan_btn.clicked.connect(self._scan)
        sr.addWidget(self._scan_btn)
        lay.addLayout(sr)

        self._progress = QProgressBar()
        self._progress.setRange(0,0); self._progress.setVisible(False)
        lay.addWidget(self._progress)

        self._net_list = QListWidget()
        self._net_list.itemClicked.connect(self._on_net_click)
        self._net_list.itemDoubleClicked.connect(self._wifi_connect_item)
        lay.addWidget(self._net_list, 1)

        pr = QHBoxLayout()
        self._sel_ssid = QLabel('Select a network')
        self._sel_ssid.setStyleSheet('color:#aaa; font-size:13px;')
        pr.addWidget(self._sel_ssid, 1)
        pr.addWidget(QLabel('Password:'))
        self._pwd = QLineEdit(); self._pwd.setEchoMode(QLineEdit.Password)
        self._pwd.setMinimumHeight(44); self._pwd.setMinimumWidth(150)
        self._pwd.setPlaceholderText('blank=open')
        pr.addWidget(self._pwd)
        self._btn_join = QPushButton('Join')
        self._btn_join.setProperty('role','success')
        self._btn_join.setMinimumHeight(44); self._btn_join.setEnabled(False)
        self._btn_join.clicked.connect(self._wifi_connect)
        pr.addWidget(self._btn_join)
        self._wifi_msg = QLabel('')
        pr.addWidget(self._wifi_msg)
        lay.addLayout(pr)

        self._refresh_wifi_cur()
        return w

    def _bars(self, s):
        if s>=75: return '████'
        if s>=50: return '███░'
        if s>=25: return '██░░'
        return '█░░░'

    def _refresh_wifi_cur(self):
        try:
            out = subprocess.check_output(
                ['nmcli','-t','-f','ACTIVE,SSID,IP4','dev','wifi'],
                timeout=5).decode('utf-8', errors='replace')
            for line in out.splitlines():
                p = line.split(':')
                if p[0]=='yes':
                    self._cur_ssid.setText(p[1] if len(p)>1 else '—')
                    self._cur_ip.setText(p[2] if len(p)>2 else '')
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
            text = '%s%s%s  %s  %d%%' % ('✓ ' if active else '  ',
                '🔒 ' if secure else '   ', ssid, self._bars(sig), sig)
            item = QListWidgetItem(text); item.setData(Qt.UserRole, ssid)
            if active: item.setForeground(QColor('#4caf50'))
            self._net_list.addItem(item)
        if not nets: self._net_list.addItem('No networks found')
        self._refresh_wifi_cur()

    def _on_net_click(self, item):
        ssid = item.data(Qt.UserRole)
        if ssid:
            self._sel_ssid.setText(ssid)
            self._sel_ssid.setStyleSheet('color:#ff8c00; font-weight:bold; font-size:13px;')
            self._btn_join.setEnabled(True)
            self._wifi_msg.setText('')

    def _wifi_connect_item(self, item):
        self._on_net_click(item); self._wifi_connect()

    def _wifi_connect(self):
        ssid = self._sel_ssid.text()
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
            self._wifi_msg.setText('✓')
            self._wifi_msg.setStyleSheet('color:#4caf50; font-weight:bold;')
            self._refresh_wifi_cur()
        else:
            self._wifi_msg.setText('✗ Failed')
            self._wifi_msg.setStyleSheet('color:#f44336;')

    def _wifi_disconnect(self):
        try: subprocess.run(['nmcli','dev','disconnect','wlan0'], timeout=10, capture_output=True)
        except Exception: pass
        self._refresh_wifi_cur()

    # ── System tab (unchanged) ────────────────────────────────────────────────
    def _build_system(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(12)

        form = QFormLayout(); form.setSpacing(10); form.setLabelAlignment(Qt.AlignRight)

        # Hostname
        hn_r = QHBoxLayout()
        self._hostname = QLineEdit(); self._hostname.setMinimumHeight(44)
        btn_hn = QPushButton('Apply'); btn_hn.setMinimumHeight(44)
        btn_hn.clicked.connect(self._set_hostname)
        hn_r.addWidget(self._hostname); hn_r.addWidget(btn_hn)
        form.addRow('Hostname:', hn_r)

        # Timezone
        tz_r = QHBoxLayout()
        self._tz = QComboBox(); self._tz.setMinimumHeight(44)
        self._populate_tz()
        btn_tz = QPushButton('Apply'); btn_tz.setMinimumHeight(44)
        btn_tz.clicked.connect(self._set_tz)
        tz_r.addWidget(self._tz, 1); tz_r.addWidget(btn_tz)
        form.addRow('Timezone:', tz_r)

        # Brightness
        br_r = QHBoxLayout()
        self._bright = QSlider(Qt.Horizontal); self._bright.setRange(20, 255); self._bright.setValue(200)
        self._bright_lbl = QLabel('200'); self._bright_lbl.setMinimumWidth(36)
        self._bright.valueChanged.connect(lambda v: (self._bright_lbl.setText(str(v)), self._set_brightness(v)))
        br_r.addWidget(self._bright, 1); br_r.addWidget(self._bright_lbl)
        form.addRow('Brightness:', br_r)

        lay.addLayout(form)

        # Info
        for attr, label in [('_lbl_os','OS'), ('_lbl_ip','IP'), ('_lbl_uptime','Uptime')]:
            lbl = QLabel('—'); lbl.setStyleSheet('color:#aaa; font-size:13px;')
            setattr(self, attr, lbl)
            r = QHBoxLayout()
            r.addWidget(self._lbl(label + ':', '#666')); r.addWidget(lbl); r.addStretch()
            lay.addLayout(r)

        lay.addStretch()

        # Power
        pw = QHBoxLayout()
        b_rb = QPushButton('⟳ Reboot'); b_rb.setProperty('role','warning'); b_rb.setMinimumHeight(54)
        b_rb.clicked.connect(self._reboot)
        b_sd = QPushButton('⏻ Shutdown'); b_sd.setProperty('role','danger'); b_sd.setMinimumHeight(54)
        b_sd.clicked.connect(self._shutdown)
        pw.addWidget(b_rb); pw.addWidget(b_sd); pw.addStretch()
        lay.addLayout(pw)

        self._load_sys()
        return w

    def _populate_tz(self):
        common = ['Africa/Cairo','America/New_York','America/Los_Angeles',
                  'Asia/Dubai','Asia/Kolkata','Asia/Shanghai','Asia/Tokyo',
                  'Australia/Sydney','Europe/Berlin','Europe/Istanbul',
                  'Europe/London','Europe/Moscow','Europe/Paris']
        try:
            rc, out, _ = _run(['timedatectl','list-timezones'])
            zones = out.splitlines() if rc==0 else common
        except Exception: zones = common
        self._tz.addItems(zones)

    def _load_sys(self):
        rc, out, _ = _run(['hostname']); self._hostname.setText(out)
        try:
            tz = os.readlink('/etc/localtime').split('zoneinfo/')[-1]
            idx = self._tz.findText(tz)
            if idx >= 0: self._tz.setCurrentIndex(idx)
        except Exception: pass
        rc, out, _ = _run(['cat','/etc/os-release'])
        for line in out.splitlines():
            if line.startswith('PRETTY_NAME='):
                self._lbl_os.setText(line.split('=',1)[1].strip('"'))
        rc, out, _ = _run(['hostname','-I'])
        self._lbl_ip.setText(out.split()[0] if out else 'No IP')
        rc, out, _ = _run(['uptime','-p'])
        self._lbl_uptime.setText(out)
        for p in ['/sys/class/backlight/rpi_backlight/brightness',
                  '/sys/class/backlight/10-0045/brightness']:
            try:
                with open(p) as f: self._bright.setValue(int(f.read().strip())); break
            except Exception: pass

    def _set_hostname(self):
        n = self._hostname.text().strip()
        if n: _run(['sudo','hostnamectl','set-hostname', n])

    def _set_tz(self):
        _run(['sudo','timedatectl','set-timezone', self._tz.currentText()])

    def _set_brightness(self, v):
        for p in ['/sys/class/backlight/rpi_backlight/brightness',
                  '/sys/class/backlight/10-0045/brightness']:
            try:
                with open(p,'w') as f: f.write(str(v)); return
            except Exception: pass

    def _reboot(self):
        if QMessageBox.question(self,'Reboot','Reboot?',
                QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
            _run(['sudo','reboot'])

    def _shutdown(self):
        if QMessageBox.question(self,'Shutdown','Shut down?',
                QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
            _run(['sudo','shutdown','-h','now'])