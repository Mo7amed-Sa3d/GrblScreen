# pages/dashboard.py
# Main dashboard — machine state, XYZ position, quick action buttons

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSlot

STATE_MAP = {
    'Idle':         ('IDLE',    '#27ae60'),
    'Run':          ('RUNNING', '#2980b9'),
    'Hold':         ('HOLD',    '#f39c12'),
    'Hold:0':       ('HOLD',    '#f39c12'),
    'Hold:1':       ('HOLD',    '#f39c12'),
    'Home':         ('HOMING',  '#9b59b6'),
    'Alarm':        ('ALARM',   '#e74c3c'),
    'Door':         ('DOOR',    '#e74c3c'),
    'Check':        ('CHECK',   '#f39c12'),
    'Sleep':        ('SLEEP',   '#7f8c8d'),
    'Jog':          ('JOG',     '#2980b9'),
    'Disconnected': ('NO CONN', '#7f8c8d'),
}


class AxisWidget(QWidget):
    def __init__(self, axis_name, parent=None):
        super().__init__(parent)
        self.setObjectName('axisDisplay')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(2)

        lbl = QLabel(axis_name)
        lbl.setObjectName('axisLabel')
        lbl.setAlignment(Qt.AlignCenter)

        self._val = QLabel('0.000')
        self._val.setObjectName('axisValue')
        self._val.setAlignment(Qt.AlignCenter)

        unit = QLabel('mm')
        unit.setObjectName('axisUnit')
        unit.setAlignment(Qt.AlignCenter)

        lay.addWidget(lbl)
        lay.addWidget(self._val)
        lay.addWidget(unit)

    def set_value(self, v):
        self._val.setText('%.3f' % v)


class DashboardPage(QWidget):
    def __init__(self, grbl, parent=None):
        super().__init__(parent)
        self._grbl = grbl
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 8)
        root.setSpacing(10)

        title = QLabel('Dashboard')
        title.setObjectName('pageTitle')
        root.addWidget(title)

        # ── Position row ──────────────────────────────────────────────────────
        pos_row = QHBoxLayout()
        pos_row.setSpacing(10)

        self._ax_x    = AxisWidget('X')
        self._ax_y    = AxisWidget('Y')
        self._ax_z    = AxisWidget('FEED (Z)')
        self._ax_feed = AxisWidget('F mm/min')

        for w in (self._ax_x, self._ax_y, self._ax_z, self._ax_feed):
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            pos_row.addWidget(w)

        root.addLayout(pos_row)

        div = QFrame(); div.setFrameShape(QFrame.HLine)
        root.addWidget(div)

        # ── State / sensor / knife row ────────────────────────────────────────
        info_row = QHBoxLayout()

        self._state_lbl = QLabel('DISCONNECTED')
        self._state_lbl.setObjectName('stateLabel')
        self._state_lbl.setAlignment(Qt.AlignCenter)
        self._state_lbl.setStyleSheet(
            'background:#2c2c3e; color:#7f8c8d; font-size:16px; '
            'font-weight:bold; padding:6px 18px; border-radius:8px;'
        )

        self._knife_lbl = QLabel('Knife: UP')
        self._knife_lbl.setAlignment(Qt.AlignCenter)
        self._knife_lbl.setStyleSheet(
            'background:#1e8449; color:white; font-size:14px; '
            'font-weight:bold; padding:6px 14px; border-radius:8px;'
        )

        self._paper_rear  = self._make_sensor('Rear')
        self._paper_front = self._make_sensor('Front')

        info_row.addWidget(self._state_lbl)
        info_row.addStretch()
        info_row.addWidget(self._paper_rear)
        info_row.addSpacing(10)
        info_row.addWidget(self._paper_front)
        info_row.addStretch()
        info_row.addWidget(self._knife_lbl)

        root.addLayout(info_row)

        # ── Quick action grid ─────────────────────────────────────────────────
        grid = QGridLayout()
        grid.setSpacing(10)

        self._btn_home_all   = self._btn('Home All ($H)',  'primary', lambda: self._grbl.send('$H'))
        self._btn_home_x     = self._btn('Home X',        'primary', lambda: self._grbl.send('$HX'))
        self._btn_hold       = self._btn('Feed Hold',     'warning', self._grbl.feed_hold)
        self._btn_resume     = self._btn('Resume',        'success', self._grbl.cycle_start)
        self._btn_unlock     = self._btn('Unlock ($X)',   'warning', lambda: self._grbl.send('$X'))
        self._btn_knife_down = self._btn('Knife ↓',      'knife',   self._grbl.knife_up_cmd)
        self._btn_knife_up   = self._btn('Knife ↑',      'knife',   self._grbl.knife_up_cmd)

        # Row 0
        grid.addWidget(self._btn_home_all,   0, 0)
        grid.addWidget(self._btn_home_x,     0, 1)
        grid.addWidget(self._btn_hold,       0, 2)
        grid.addWidget(self._btn_resume,     0, 3)
        grid.addWidget(self._btn_unlock,     0, 4)
        # Row 1
        self._btn_knife_down = self._btn('Knife ↓', 'knife',
                                         self._grbl.knife_down_cmd)
        self._btn_knife_up   = self._btn('Knife ↑', 'knife',
                                         self._grbl.knife_up_cmd)
        grid.addWidget(self._btn_knife_down, 1, 0, 1, 2)
        grid.addWidget(self._btn_knife_up,   1, 2, 1, 3)

        root.addLayout(grid)
        root.addStretch()

    def _make_sensor(self, name):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        dot = QLabel()
        dot.setFixedSize(20, 20)
        dot.setStyleSheet('background:#2c2c3e; border-radius:10px;')
        lbl = QLabel(name)
        lbl.setStyleSheet('font-size:13px; color:#7f8c8d;')
        lay.addWidget(dot)
        lay.addWidget(lbl)
        w._dot = dot
        return w

    def _btn(self, label, role, slot):
        b = QPushButton(label)
        b.setProperty('role', role)
        b.setMinimumHeight(60)
        b.clicked.connect(slot)
        return b

    def _connect_signals(self):
        g = self._grbl
        g.state_changed.connect(self._on_state)
        g.position_changed.connect(self._on_position)
        g.feed_changed.connect(self._on_feed)
        g.knife_changed.connect(self._on_knife)
        g.connected.connect(lambda: self._on_state('Idle'))
        g.disconnected.connect(lambda: self._on_state('Disconnected'))

    @pyqtSlot(str)
    def _on_state(self, state):
        label, colour = STATE_MAP.get(state, (state.upper(), '#7f8c8d'))
        self._state_lbl.setText(label)
        self._state_lbl.setStyleSheet(
            'background:%s; color:white; font-size:16px; '
            'font-weight:bold; padding:6px 18px; border-radius:8px;' % colour
        )
        running = state == 'Run'
        held    = 'Hold' in state
        alarm   = state == 'Alarm'
        self._btn_hold.setEnabled(running)
        self._btn_resume.setEnabled(held)
        self._btn_unlock.setEnabled(alarm)

    @pyqtSlot(float, float, float)
    def _on_position(self, x, y, z):
        self._ax_x.set_value(x)
        self._ax_y.set_value(y)
        self._ax_z.set_value(z)

    @pyqtSlot(float, float)
    def _on_feed(self, feed, spindle):
        self._ax_feed.set_value(feed)

    @pyqtSlot(bool, int)
    def _on_knife(self, down, force):
        if down:
            self._knife_lbl.setText('Knife: DOWN  S%d' % force)
            self._knife_lbl.setStyleSheet(
                'background:#922b21; color:white; font-size:14px; '
                'font-weight:bold; padding:6px 14px; border-radius:8px;'
            )
        else:
            self._knife_lbl.setText('Knife: UP')
            self._knife_lbl.setStyleSheet(
                'background:#1e8449; color:white; font-size:14px; '
                'font-weight:bold; padding:6px 14px; border-radius:8px;'
            )

    def update_sensors(self, rear, front):
        on  = 'background:#27ae60; border-radius:10px;'
        off = 'background:#2c2c3e; border-radius:10px;'
        self._paper_rear._dot.setStyleSheet(on  if rear  else off)
        self._paper_front._dot.setStyleSheet(on  if front else off)