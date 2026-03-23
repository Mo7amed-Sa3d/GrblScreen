# main_window.py
# Main application window — status bar, nav bar, page stack

import os
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui  import QFont

from pages.dashboard     import DashboardPage, STATE_MAP
from pages.jog_page      import JogPage
from pages.knife_page    import KnifePage
from pages.paper_page    import PaperPage
from pages.console_page  import ConsolePage
from pages.settings_page import SettingsPage
from pages.wifi_page     import WifiPage
from pages.system_page   import SystemPage


PAGES = [
    ('Dashboard', '⌂',  DashboardPage),
    ('Jog',       '✛',  JogPage),
    ('Knife',     '⚡',  KnifePage),
    ('Paper',     '↕',  PaperPage),
    ('Console',   '▶',  ConsolePage),
    ('Settings',  '⚙',  SettingsPage),
    ('WiFi',      '📶',  WifiPage),
    ('System',    '🖥',  SystemPage),
]

STYLE_DIR = os.path.join(os.path.dirname(__file__), 'styles')


class MainWindow(QMainWindow):
    def __init__(self, grbl, app):
        super().__init__()
        self._grbl  = grbl
        self._app   = app
        self._dark  = True    # current theme state
        self._nav_buttons = []

        self.setWindowTitle('Cutter Screen')
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.showFullScreen()

        self._build_ui()
        self._connect_signals()
        QTimer.singleShot(500, self._auto_connect)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        central.setObjectName('centralWidget')
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_status_bar())

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        self._pages = {}
        for label, icon, cls in PAGES:
            # WiFi and System pages don't need grbl
            if cls in (WifiPage, SystemPage):
                page = cls()
            else:
                page = cls(grbl=self._grbl)
            self._stack.addWidget(page)
            self._pages[label] = page

        root.addWidget(self._build_nav_bar())
        self._switch_page(0)

    def _build_status_bar(self):
        bar = QWidget()
        bar.setObjectName('statusBar')
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)

        # State badge
        self._state_badge = QLabel('NO CONN')
        self._state_badge.setObjectName('stateLabel')
        self._state_badge.setStyleSheet(
            'background:#2c2c3e; color:#7f8c8d; font-size:15px; '
            'font-weight:bold; padding:4px 14px; border-radius:6px;'
        )
        lay.addWidget(self._state_badge)
        lay.addSpacing(8)

        # Position
        self._pos_label = QLabel('X:  0.000   Y:  0.000   Z:  0.000')
        self._pos_label.setObjectName('posLabel')
        lay.addWidget(self._pos_label, 1)

        # Feed rate
        self._feed_label = QLabel('F:  0')
        self._feed_label.setObjectName('posLabel')
        lay.addWidget(self._feed_label)
        lay.addSpacing(8)

        # Knife badge
        self._knife_badge = QLabel('Knife: UP')
        self._knife_badge.setStyleSheet(
            'background:#1e8449; color:white; font-size:13px; '
            'font-weight:bold; padding:4px 10px; border-radius:6px;'
        )
        lay.addWidget(self._knife_badge)
        lay.addSpacing(8)

        # Dark/light toggle
        self._theme_btn = QPushButton('☀')
        self._theme_btn.setObjectName('themeButton')
        self._theme_btn.setToolTip('Toggle dark/light mode')
        self._theme_btn.clicked.connect(self._toggle_theme)
        lay.addWidget(self._theme_btn)
        lay.addSpacing(8)

        # E-STOP
        estop = QPushButton('E-STOP')
        estop.setObjectName('estopButton')
        estop.clicked.connect(self._do_estop)
        lay.addWidget(estop)

        return bar

    def _build_nav_bar(self):
        bar = QWidget()
        bar.setObjectName('navBar')
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        for idx, (label, icon, _) in enumerate(PAGES):
            btn = QPushButton('%s\n%s' % (icon, label))
            btn.setObjectName('navButton')
            btn.setProperty('active', 'false')
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            btn.clicked.connect(lambda checked, i=idx: self._switch_page(i))
            lay.addWidget(btn)
            self._nav_buttons.append(btn)

        return bar

    # ── Page switching ────────────────────────────────────────────────────────

    def _switch_page(self, idx):
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_buttons):
            btn.setProperty('active', 'true' if i == idx else 'false')
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ── Theme toggle ──────────────────────────────────────────────────────────

    def _toggle_theme(self):
        self._dark = not self._dark
        self._apply_theme()

    def _apply_theme(self):
        name = 'dark.qss' if self._dark else 'light.qss'
        path = os.path.join(STYLE_DIR, name)
        try:
            with open(path) as f:
                self._app.setStyleSheet(f.read())
        except FileNotFoundError:
            pass
        # Update toggle icon
        self._theme_btn.setText('☀' if self._dark else '🌙')

    # ── Signals ───────────────────────────────────────────────────────────────

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
        self._state_badge.setText(label)
        self._state_badge.setStyleSheet(
            'background:%s; color:white; font-size:15px; '
            'font-weight:bold; padding:4px 14px; border-radius:6px;' % colour
        )

    @pyqtSlot(float, float, float)
    def _on_position(self, x, y, z):
        self._pos_label.setText(
            'X: %7.3f   Y: %7.3f   Z: %7.3f' % (x, y, z)
        )

    @pyqtSlot(float, float)
    def _on_feed(self, feed, spindle):
        self._feed_label.setText('F: %5.0f' % feed)

    @pyqtSlot(bool, int)
    def _on_knife(self, down, force):
        """Fires immediately when M3/M5 is queued — no status report lag."""
        if down:
            self._knife_badge.setText('Knife: DOWN  S%d' % force)
            self._knife_badge.setStyleSheet(
                'background:#922b21; color:white; font-size:13px; '
                'font-weight:bold; padding:4px 10px; border-radius:6px;'
            )
        else:
            self._knife_badge.setText('Knife: UP')
            self._knife_badge.setStyleSheet(
                'background:#1e8449; color:white; font-size:13px; '
                'font-weight:bold; padding:4px 10px; border-radius:6px;'
            )

    # ── E-stop ────────────────────────────────────────────────────────────────

    def _do_estop(self):
        self._grbl.reset()        # Ctrl-X, also sets knife_down=False internally
        self._grbl.send('M5')

    # ── Auto-connect ──────────────────────────────────────────────────────────

    def _auto_connect(self):
        for name, desc in self._grbl.available_ports():
            if 'ttyUSB' in name or 'ttyACM' in name or 'DLC32' in desc:
                if self._grbl.connect('/dev/%s' % name):
                    return