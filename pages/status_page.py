# pages/status_page.py
# Machine Status & Homing

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSlot
from grbl_connection import STATE_MAP


class _AxisCard(QWidget):
    """Single axis position card: NAME / VALUE / UNIT."""
    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.setObjectName('card')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(0)

        n = QLabel(name)
        n.setObjectName('axisName')
        n.setAlignment(Qt.AlignCenter)

        self._v = QLabel('0.000')
        self._v.setObjectName('axisVal')
        self._v.setAlignment(Qt.AlignCenter)

        u = QLabel('mm')
        u.setObjectName('axisUnit')
        u.setAlignment(Qt.AlignCenter)

        lay.addWidget(n)
        lay.addWidget(self._v)
        lay.addWidget(u)

    def set(self, v: float):
        self._v.setText('%+.3f' % v)


class StatusPage(QWidget):
    def __init__(self, grbl, parent=None):
        super().__init__(parent)
        self.setObjectName('page')
        self._grbl = grbl
        self._build()
        self._wire()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(10)

        # Title row
        top = QHBoxLayout()
        title = QLabel('Status & Homing')
        title.setObjectName('pageTitle')
        top.addWidget(title)
        top.addStretch()

        # Feed rate badge
        self._feed_lbl = QLabel('F  0 mm/min')
        self._feed_lbl.setStyleSheet(
            'color:#aaa; font-size:13px; padding:3px 10px;'
            'background:#2d2d2d; border-radius:5px;'
        )
        top.addWidget(self._feed_lbl)
        root.addLayout(top)

        # Position cards
        pos = QHBoxLayout()
        pos.setSpacing(8)
        self._ax_x = _AxisCard('X')
        self._ax_y = _AxisCard('Y')
        self._ax_z = _AxisCard('FEED  Z')
        for w in (self._ax_x, self._ax_y, self._ax_z):
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            w.setMinimumHeight(90)
            pos.addWidget(w)
        root.addLayout(pos)

        # Divider
        div = QFrame(); div.setFrameShape(QFrame.HLine)
        root.addWidget(div)

        # Action buttons grid
        grid = QGridLayout()
        grid.setSpacing(8)

        def btn(label, role, cb):
            b = QPushButton(label)
            b.setProperty('role', role)
            b.setMinimumHeight(72)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            b.clicked.connect(cb)
            return b

        self._b_home_all = btn('⌂  Home All\n($H)',    'accent',   self._home_all)
        self._b_home_x   = btn('⌂  Home X\n($HX)',     '',         self._home_x)
        self._b_hold     = btn('⏸  Feed Hold',          'warning',  self._grbl.feed_hold)
        self._b_resume   = btn('▶  Resume',              'success',  self._grbl.cycle_start)
        self._b_unlock   = btn('🔓  Unlock\n($X)',       'warning',  lambda: self._grbl.send('$X'))
        self._b_zero_xy  = btn('✕  Zero XY',             '',         lambda: self._grbl.send('G92 X0 Y0'))
        self._b_zero_z   = btn('✕  Zero Z',              '',         lambda: self._grbl.send('G92 Z0'))
        self._b_reset    = btn('⟳  Reset\n(Ctrl-X)',     'danger',   self._grbl.reset)

        grid.addWidget(self._b_home_all, 0, 0)
        grid.addWidget(self._b_home_x,   0, 1)
        grid.addWidget(self._b_hold,     0, 2)
        grid.addWidget(self._b_resume,   0, 3)
        grid.addWidget(self._b_unlock,   1, 0)
        grid.addWidget(self._b_zero_xy,  1, 1)
        grid.addWidget(self._b_zero_z,   1, 2)
        grid.addWidget(self._b_reset,    1, 3)

        # Stretch rows and columns to fill available space evenly
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)

        root.addLayout(grid)
        root.addStretch()

    def _wire(self):
        g = self._grbl
        g.position_changed.connect(self._on_pos)
        g.feed_changed.connect(self._on_feed)
        g.state_changed.connect(self._on_state)
        g.connected.connect(lambda: self._on_state('Idle'))
        g.disconnected.connect(lambda: self._on_state('Disconnected'))

    @pyqtSlot(float, float, float)
    def _on_pos(self, x, y, z):
        self._ax_x.set(x); self._ax_y.set(y); self._ax_z.set(z)

    @pyqtSlot(float, float)
    def _on_feed(self, feed, _):
        self._feed_lbl.setText('F  %d mm/min' % feed)

    @pyqtSlot(str)
    def _on_state(self, state):
        running = state == 'Run'
        held    = 'Hold' in state
        alarm   = state == 'Alarm'
        self._b_hold.setEnabled(running)
        self._b_resume.setEnabled(held)
        self._b_unlock.setEnabled(alarm)

    def _home_all(self): self._grbl.send('$H')
    def _home_x(self):   self._grbl.send('$HX')