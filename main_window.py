# main_window.py
# Portrait 480×800 — single QStackedWidget
# Screen 0: Dashboard (always the home screen)
# Screen 1: USB file browser
# Screen 2: Camera feed
# Screen 3: Settings

import os
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QStackedWidget
)
from PyQt5.QtCore import Qt, QTimer

from pages.dashboard    import DashboardPage
from pages.usb_page     import UsbPage
from pages.camera_page  import CameraPage
from pages.settings_page import SettingsPage

SCREEN_DASHBOARD = 0
SCREEN_USB       = 1
SCREEN_CAMERA    = 2
SCREEN_SETTINGS  = 3


class MainWindow(QMainWindow):
    def __init__(self, grbl):
        super().__init__()
        self._grbl = grbl

        self.setWindowTitle('Cutter Screen')
        self.setWindowFlags(Qt.FramelessWindowHint)

        # Portrait 480×800
        self.setFixedSize(480, 800)
        self.showFullScreen()

        self._build()
        QTimer.singleShot(600, self._auto_connect)

    def _build(self):
        self._stack = QStackedWidget()
        self._stack.setObjectName('root')
        self.setCentralWidget(self._stack)

        # Build all screens, passing back-navigation callbacks
        self._dash = DashboardPage(
            grbl        = self._grbl,
            on_usb      = lambda: self._go(SCREEN_USB),
            on_camera   = lambda: self._go(SCREEN_CAMERA),
            on_settings = lambda: self._go(SCREEN_SETTINGS),
        )
        self._usb = UsbPage(
            grbl    = self._grbl,
            on_back = lambda: self._go(SCREEN_DASHBOARD),
        )
        self._cam = CameraPage(
            on_back = lambda: self._go(SCREEN_DASHBOARD),
        )
        self._settings = SettingsPage(
            grbl    = self._grbl,
            on_back = lambda: self._go(SCREEN_DASHBOARD),
        )

        self._stack.addWidget(self._dash)       # index 0
        self._stack.addWidget(self._usb)        # index 1
        self._stack.addWidget(self._cam)        # index 2
        self._stack.addWidget(self._settings)   # index 3

        self._go(SCREEN_DASHBOARD)

    def _go(self, idx):
        self._stack.setCurrentIndex(idx)

    def _auto_connect(self):
        for name, desc in self._grbl.available_ports():
            if any(x in name for x in ('DLC32', 'ttyUSB', 'ttyACM')):
                if self._grbl.connect('/dev/%s' % name):
                    return