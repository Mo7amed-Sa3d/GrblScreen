# main_window.py
# Portrait 480×800 QStackedWidget application shell.
#
# Screen indices:
#   0 Dashboard
#   1 USB file browser
#   2 Camera feed
#   3 Settings
#   4 Registration marks  (built dynamically; placeholder until first use)

import os
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QStackedWidget, QLabel, QVBoxLayout
)
from PyQt5.QtCore import Qt, QTimer

from grbl_connection         import GrblConnection
from tilt_corrector          import TiltCorrector
from pages.dashboard         import DashboardPage
from pages.usb_page          import UsbPage
from pages.camera_page       import CameraPage
from pages.settings_page     import SettingsPage
from pages.registration_page import RegistrationPage

S_DASH = 0
S_USB  = 1
S_CAM  = 2
S_SET  = 3
S_REG  = 4


def _no_file_placeholder():
    """Widget shown at S_REG when no RegMarks file has been selected yet."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setAlignment(Qt.AlignCenter)
    lbl = QLabel(
        '◎  Alignment\n\n'
        'No registration marks loaded.\n\n'
        'Select a G-code file that contains\n'
        ';RegMarks(x1,y1)(x2,y2)(x3,y3)(x4,y4)\n'
        'from the USB page and press Run.'
    )
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        'color:#aaa; font-size:15px; padding:20px;')
    lay.addWidget(lbl)
    return w


class MainWindow(QMainWindow):
    def __init__(self, grbl: GrblConnection):
        super().__init__()
        self._grbl          = grbl
        self._corrector     = TiltCorrector(grbl)
        self._reg_page      = None    # RegistrationPage, or None
        self._last_design_pts = None  # persisted for dashboard alignment button

        self.setWindowTitle('Cutter Screen')
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setFixedSize(480, 800)
        self.showFullScreen()

        self._build()
        QTimer.singleShot(600, self._auto_connect)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        self._stack = QStackedWidget()
        self._stack.setObjectName('root')
        self.setCentralWidget(self._stack)

        self._dash = DashboardPage(
            grbl            = self._corrector,
            on_usb          = lambda: self._go(S_USB),
            on_camera       = lambda: self._go(S_CAM),
            on_settings     = lambda: self._go(S_SET),
            on_registration = self._on_dashboard_alignment,
        )
        self._usb = UsbPage(
            grbl    = self._corrector,
            on_back = lambda: self._go(S_DASH),
        )
        self._cam = CameraPage(
            grbl    = self._corrector,
            on_back = lambda: self._go(S_DASH),
        )
        self._settings = SettingsPage(
            grbl    = self._corrector,
            on_back = lambda: self._go(S_DASH),
        )

        self._stack.addWidget(self._dash)              # 0
        self._stack.addWidget(self._usb)               # 1
        self._stack.addWidget(self._cam)               # 2
        self._stack.addWidget(self._settings)          # 3
        self._stack.addWidget(_no_file_placeholder())  # 4 — replaced later

        # USB page requests registration before each run
        self._usb.request_registration.connect(self._start_registration)

        self._go(S_DASH)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _go(self, idx):
        self._stack.setCurrentIndex(idx)

    def _replace_reg_slot(self, new_widget):
        """Swap whatever is at index S_REG with new_widget, keeping index stable."""
        old = self._stack.widget(S_REG)
        self._stack.insertWidget(S_REG, new_widget)
        if old is not None:
            self._stack.removeWidget(old)
            old.deleteLater()

    # ── Dashboard alignment button ─────────────────────────────────────────────

    def _on_dashboard_alignment(self):
        """
        Called when the user presses the ◎ Alignment button on the dashboard.

        If design_pts are available from a previously selected file:
          → build a RegistrationPage and show it.
          on_complete goes back to the dashboard (not USB), no file send.

        If no design_pts have ever been loaded:
          → show the placeholder explaining how to use alignment,
            then navigate to USB so the user can select a file.
        """
        if self._last_design_pts:
            self._build_reg_page(
                design_pts  = self._last_design_pts,
                on_complete = self._on_dashboard_alignment_complete,
                on_back     = lambda: self._go(S_DASH),
            )
            self._go(S_REG)
        else:
            # No design_pts known — show placeholder then go to USB
            self._replace_reg_slot(_no_file_placeholder())
            self._reg_page = None
            self._go(S_REG)
            # After a short delay navigate to USB so user knows where to go
            QTimer.singleShot(1800, lambda: self._go(S_USB))

    def _on_dashboard_alignment_complete(self, success):
        """After alignment from dashboard — just go back to dashboard."""
        self._go(S_DASH)

    # ── USB-triggered registration ─────────────────────────────────────────────

    def _start_registration(self, design_pts):
        """
        Called by USB page before each run (every repeat).
        Builds a fresh RegistrationPage, shows it, then calls back into USB.
        """
        self._last_design_pts = design_pts  # persist for dashboard button
        self._build_reg_page(
            design_pts  = design_pts,
            on_complete = self._on_usb_registration_complete,
            on_back     = self._on_usb_registration_skipped,
        )
        self._go(S_REG)

    def _on_usb_registration_complete(self, success):
        self._go(S_USB)
        self._usb.on_registration_complete(success)

    def _on_usb_registration_skipped(self):
        self._go(S_USB)
        self._usb.on_registration_complete(False)

    # ── Registration page builder ──────────────────────────────────────────────

    def _build_reg_page(self, design_pts, on_complete, on_back):
        """Build a new RegistrationPage and install it at S_REG."""
        page = RegistrationPage(
            corrector   = self._corrector,
            design_pts  = design_pts,
            on_complete = on_complete,
            on_back     = on_back,
        )
        self._replace_reg_slot(page)
        self._reg_page = page

    # ── Auto-connect ──────────────────────────────────────────────────────────

    def _auto_connect(self):
        for name, desc in self._grbl.available_ports():
            if any(x in name for x in ('DLC32', 'ttyUSB', 'ttyACM')):
                if self._grbl.connect('/dev/%s' % name):
                    return