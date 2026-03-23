# pages/settings_page.py
# Serial connection + GRBL $-settings

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QComboBox, QLineEdit,
    QGroupBox, QFrame, QScrollArea
)
from PyQt5.QtCore import Qt


COMMON_SETTINGS = [
    ('$32',  'Laser mode  (1=on for knife)'),
    ('$100', 'X steps/mm'),
    ('$101', 'Y steps/mm'),
    ('$102', 'Z (feed) steps/mm'),
    ('$110', 'X max rate mm/min'),
    ('$111', 'Y max rate mm/min'),
    ('$112', 'Z max rate mm/min'),
    ('$120', 'X acceleration mm/s²'),
    ('$121', 'Y acceleration mm/s²'),
    ('$122', 'Z acceleration mm/s²'),
    ('$130', 'X max travel mm'),
    ('$131', 'Y max travel mm'),
    ('$132', 'Z max travel mm'),
    ('$20',  'Soft limits  (0=off, 1=on)'),
    ('$21',  'Hard limits  (0=off, 1=on)'),
    ('$22',  'Homing enable  (0=off, 1=on)'),
    ('$23',  'Homing dir invert mask'),
    ('$24',  'Homing feed rate mm/min'),
    ('$25',  'Homing seek rate mm/min'),
    ('$27',  'Homing pull-off mm'),
]

DEFAULT_VALUES = {
    '$32': '1', '$100': '80.0', '$101': '80.0', '$102': '80.0',
    '$110': '6000', '$111': '6000', '$112': '2000',
    '$120': '500', '$121': '500', '$122': '150',
    '$130': '450', '$131': '450', '$132': '9999',
    '$20': '0', '$21': '1', '$22': '1', '$23': '1',
    '$24': '300', '$25': '1000', '$27': '1',
}


class SettingsPage(QWidget):
    def __init__(self, grbl, parent=None):
        super().__init__(parent)
        self._grbl  = grbl
        self._fields = {}
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 8)
        root.setSpacing(10)

        title = QLabel('Machine Settings')
        title.setObjectName('pageTitle')
        root.addWidget(title)

        # ── Connection ────────────────────────────────────────────────────────
        conn_box = QGroupBox('Serial Connection')
        conn_lay = QHBoxLayout(conn_box)

        conn_lay.addWidget(QLabel('Port:'))
        self._port_combo = QComboBox()
        self._port_combo.setMinimumWidth(200)
        self._port_combo.setMinimumHeight(44)
        conn_lay.addWidget(self._port_combo)

        btn_refresh = QPushButton('⟳')
        btn_refresh.setMinimumHeight(44)
        btn_refresh.setMaximumWidth(50)
        btn_refresh.clicked.connect(self._refresh_ports)
        conn_lay.addWidget(btn_refresh)

        self._btn_connect = QPushButton('Connect')
        self._btn_connect.setProperty('role', 'success')
        self._btn_connect.setMinimumHeight(44)
        self._btn_connect.setMinimumWidth(110)
        self._btn_connect.clicked.connect(self._toggle_connect)
        conn_lay.addWidget(self._btn_connect)

        self._conn_status = QLabel('Not connected')
        self._conn_status.setStyleSheet('color:#e74c3c; font-weight:bold;')
        conn_lay.addWidget(self._conn_status)
        conn_lay.addStretch()

        root.addWidget(conn_box)

        # ── GRBL $-settings ───────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        inner = QWidget()
        form  = QFormLayout(inner)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)

        for key, desc in COMMON_SETTINGS:
            le = QLineEdit(DEFAULT_VALUES.get(key, ''))
            le.setMinimumHeight(40)
            le.setMaximumWidth(140)

            btn = QPushButton('Set')
            btn.setMinimumHeight(40)
            btn.setMinimumWidth(56)
            btn.clicked.connect(
                lambda checked, k=key, f=le: self._set_value(k, f)
            )

            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.addWidget(le)
            row_l.addWidget(btn)
            row_l.addStretch()

            form.addRow('%s  %s' % (key, desc), row_w)
            self._fields[key] = le

        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # ── Action buttons ────────────────────────────────────────────────────
        act_row = QHBoxLayout()

        btn_read = QPushButton('Read All ($$)')
        btn_read.setMinimumHeight(48)
        btn_read.clicked.connect(lambda: self._grbl.send('$$'))
        act_row.addWidget(btn_read)

        btn_rst = QPushButton('Reset Defaults  ($RST=$)')
        btn_rst.setProperty('role', 'danger')
        btn_rst.setMinimumHeight(48)
        btn_rst.clicked.connect(lambda: self._grbl.send('$RST=$'))
        act_row.addWidget(btn_rst)
        act_row.addStretch()

        root.addLayout(act_row)

        # Signals
        self._grbl.connected.connect(self._on_connected)
        self._grbl.disconnected.connect(self._on_disconnected)
        self._refresh_ports()

    # ── Port management ───────────────────────────────────────────────────────

    def _refresh_ports(self):
        self._port_combo.clear()
        for name, desc in self._grbl.available_ports():
            label = '%s  (%s)' % (name, desc) if desc else name
            self._port_combo.addItem(label, name)
        if self._port_combo.count() == 0:
            self._port_combo.addItem('No ports found', '')

    def _toggle_connect(self):
        if self._grbl.is_connected():
            self._grbl.disconnect()
        else:
            port = self._port_combo.currentData()
            if port:
                if not self._grbl.connect(port):
                    self._conn_status.setText('Failed: could not open %s' % port)

    def _on_connected(self):
        self._conn_status.setText('Connected ✓')
        self._conn_status.setStyleSheet('color:#27ae60; font-weight:bold;')
        self._btn_connect.setText('Disconnect')
        self._btn_connect.setProperty('role', 'danger')
        self._refresh_style(self._btn_connect)

    def _on_disconnected(self):
        self._conn_status.setText('Not connected')
        self._conn_status.setStyleSheet('color:#e74c3c; font-weight:bold;')
        self._btn_connect.setText('Connect')
        self._btn_connect.setProperty('role', 'success')
        self._refresh_style(self._btn_connect)

    def _set_value(self, key, field):
        val = field.text().strip()
        if val:
            self._grbl.send('%s=%s' % (key, val))

    @staticmethod
    def _refresh_style(widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)