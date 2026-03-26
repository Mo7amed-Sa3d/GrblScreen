# main_window.py
# Portrait 480×800 QStackedWidget application shell.
#
# Screen indices:
#   0 Dashboard
#   1 USB file browser
#   2 Camera feed
#   3 Settings
#   4 Registration marks  (dynamically configured per file)

import os
from PyQt5.QtWidgets import QMainWindow, QWidget, QStackedWidget
from PyQt5.QtCore    import Qt, QTimer

from grbl_connection              import GrblConnection
from tilt_corrector               import TiltCorrector
from pages.dashboard              import DashboardPage
from pages.usb_page               import UsbPage
from pages.camera_page            import CameraPage
from pages.settings_page          import SettingsPage
from pages.registration_page      import RegistrationPage

S_DASH  = 0
S_USB   = 1
S_CAM   = 2
S_SET   = 3
S_REG   = 4


class MainWindow(QMainWindow):
    def __init__(self, grbl: GrblConnection):
        super().__init__()
        self._grbl      = grbl
        self._corrector = TiltCorrector(grbl)
        self._reg_page  = None   # created dynamically when design_pts are known

        self.setWindowTitle('Cutter Screen')
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setFixedSize(480, 800)
        self.showFullScreen()

        self._build()
        QTimer.singleShot(600, self._auto_connect)

    def _build(self):
        self._stack = QStackedWidget()
        self._stack.setObjectName('root')
        self.setCentralWidget(self._stack)

        self._dash = DashboardPage(
            grbl            = self._corrector,
            on_usb          = lambda: self._go(S_USB),
            on_camera       = lambda: self._go(S_CAM),
            on_settings     = lambda: self._go(S_SET),
            on_registration = lambda: self._go(S_REG),
        )
        self._usb = UsbPage(
            grbl    = self._corrector,
            on_back = lambda: self._go(S_DASH),
        )
        self._cam = CameraPage(
            on_back = lambda: self._go(S_DASH),
        )
        self._settings = SettingsPage(
            grbl    = self._corrector,
            on_back = lambda: self._go(S_DASH),
        )

        # Placeholder for registration page (replaced when file is selected)
        self._reg_placeholder = QWidget()

        self._stack.addWidget(self._dash)             # 0
        self._stack.addWidget(self._usb)              # 1
        self._stack.addWidget(self._cam)              # 2
        self._stack.addWidget(self._settings)         # 3
        self._stack.addWidget(self._reg_placeholder)  # 4

        # USB page requests registration when a RegMarks file is selected
        self._usb.request_registration.connect(self._start_registration)

        self._go(S_DASH)

    def _go(self, idx):
        if idx == S_REG and self._reg_page:
            self._reg_page.refresh_badge()
        self._stack.setCurrentIndex(idx)

    # ── Registration ──────────────────────────────────────────────────────────

    def _start_registration(self, design_pts):
        """
        Build a fresh RegistrationPage for these design positions and show it.
        Uses a stable swap at index S_REG=4 so stack indices never shift.
        """
        # Build new registration page
        new_page = RegistrationPage(
            corrector   = self._corrector,
            design_pts  = design_pts,
            on_complete = self._on_registration_complete,
            on_back     = self._on_registration_skipped,
        )

        # Replace whatever is currently at slot S_REG with the new page
        old = self._stack.widget(S_REG)
        self._stack.insertWidget(S_REG, new_page)  # inserts at S_REG, pushes old to S_REG+1
        if old is not None:
            self._stack.removeWidget(old)
            old.deleteLater()

        self._reg_page = new_page
        self._go(S_REG)

    def _on_registration_complete(self, success):
        """Registration done — go back to USB page and start the file."""
        self._go(S_USB)
        self._usb.on_registration_complete(success)

    def _on_registration_skipped(self):
        """User pressed Skip on registration page."""
        self._go(S_USB)
        self._usb.on_registration_complete(False)   # False = no correction armed

    # ── Auto-connect ──────────────────────────────────────────────────────────

    def _auto_connect(self):
        for name, desc in self._grbl.available_ports():
            if any(x in name for x in ('DLC32', 'ttyUSB', 'ttyACM')):
                if self._grbl.connect('/dev/%s' % name):
                    return