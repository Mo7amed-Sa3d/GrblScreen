# main_window.py
# Application shell — header, 4 tabs, E-stop

import os
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot, QTime
from PyQt5.QtGui  import QFont

from grbl_connection import STATE_MAP
from pages.status_page   import StatusPage
from pages.jog_page      import JogPage
from pages.knife_page    import KnifePage
from pages.settings_page import SettingsPage


# (label, icon, page class)
TABS = [
    ('Status',   '⊙', StatusPage),
    ('Jog',      '✛', JogPage),
    ('Knife',    '⚡', KnifePage),
    ('Settings', '⚙', SettingsPage),
]


class MainWindow(QMainWindow):
    def __init__(self, grbl):
        super().__init__()
        self._grbl = grbl
        self._tabs = []

        self.setWindowTitle('Cutter Screen')
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.showFullScreen()

        self._build()
        self._wire()
        QTimer.singleShot(600, self._auto_connect)

        # Clock timer
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        root_w = QWidget()
        root_w.setObjectName('root')
        self.setCentralWidget(root_w)

        root = QVBoxLayout(root_w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._mk_header())

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        for label, icon, cls in TABS:
            page = cls(grbl=self._grbl)
            self._stack.addWidget(page)

        root.addWidget(self._mk_tabbar())
        self._switch(0)

    def _mk_header(self):
        hdr = QWidget()
        hdr.setObjectName('header')
        hdr.setFixedHeight(58)
        lay = QHBoxLayout(hdr)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(10)

        # Machine name
        name = QLabel('✂  CUTTER')
        name.setObjectName('machineLabel')
        lay.addWidget(name)

        lay.addSpacing(12)

        # State badge
        self._state_lbl = QLabel('NO CONN')
        self._state_lbl.setObjectName('stateNone')
        lay.addWidget(self._state_lbl)

        lay.addSpacing(10)

        # Position mini-display
        self._pos_lbl = QLabel('X  —      Y  —      Z  —')
        self._pos_lbl.setStyleSheet(
            'font-family:"Roboto Mono","Courier New",monospace;'
            'font-size:13px; color:#aaaaaa;'
        )
        lay.addWidget(self._pos_lbl, 1)

        # Knife badge
        self._knife_lbl = QLabel('Knife: UP')
        self._knife_lbl.setObjectName('knifeUp')
        lay.addWidget(self._knife_lbl)

        lay.addSpacing(8)

        # Clock
        self._clock_lbl = QLabel('00:00')
        self._clock_lbl.setStyleSheet('color:#666; font-size:13px; min-width:44px;')
        lay.addWidget(self._clock_lbl)

        lay.addSpacing(6)

        # E-STOP
        estop = QPushButton('E\nSTOP')
        estop.setObjectName('estop')
        estop.setFixedSize(64, 48)
        estop.clicked.connect(self._estop)
        lay.addWidget(estop)

        return hdr

    def _mk_tabbar(self):
        bar = QWidget()
        bar.setObjectName('tabBar')
        bar.setFixedHeight(76)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        for idx, (label, icon, _) in enumerate(TABS):
            btn = QPushButton('%s\n%s' % (icon, label))
            btn.setObjectName('tab')
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            btn.clicked.connect(lambda _, i=idx: self._switch(i))
            lay.addWidget(btn)
            self._tabs.append(btn)

        return bar

    def _switch(self, idx):
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tabs):
            name = 'tabActive' if i == idx else 'tab'
            btn.setObjectName(name)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ── Signals ───────────────────────────────────────────────────────────────

    def _wire(self):
        g = self._grbl
        g.state_changed.connect(self._on_state)
        g.position_changed.connect(self._on_pos)
        g.knife_changed.connect(self._on_knife)
        g.connected.connect(lambda: self._on_state('Idle'))
        g.disconnected.connect(lambda: self._on_state('Disconnected'))

    @pyqtSlot(str)
    def _on_state(self, state):
        label, obj = STATE_MAP.get(state, (state.upper(), 'stateNone'))
        self._state_lbl.setText(label)
        self._state_lbl.setObjectName(obj)
        self._state_lbl.style().unpolish(self._state_lbl)
        self._state_lbl.style().polish(self._state_lbl)

    @pyqtSlot(float, float, float)
    def _on_pos(self, x, y, z):
        self._pos_lbl.setText(
            'X %+7.2f   Y %+7.2f   Z %+7.2f' % (x, y, z)
        )

    @pyqtSlot(bool, int)
    def _on_knife(self, down, force):
        if down:
            self._knife_lbl.setText('Knife: DN  S%d' % force)
            self._knife_lbl.setObjectName('knifeDown')
        else:
            self._knife_lbl.setText('Knife: UP')
            self._knife_lbl.setObjectName('knifeUp')
        self._knife_lbl.style().unpolish(self._knife_lbl)
        self._knife_lbl.style().polish(self._knife_lbl)

    def _tick_clock(self):
        self._clock_lbl.setText(QTime.currentTime().toString('HH:mm'))

    # ── E-stop ────────────────────────────────────────────────────────────────

    def _estop(self):
        self._grbl.reset()
        self._grbl.send('M5')

    # ── Auto-connect ──────────────────────────────────────────────────────────

    def _auto_connect(self):
        for name, desc in self._grbl.available_ports():
            if any(x in name for x in ('DLC32', 'ttyUSB', 'ttyACM')):
                if self._grbl.connect('/dev/%s' % name):
                    return