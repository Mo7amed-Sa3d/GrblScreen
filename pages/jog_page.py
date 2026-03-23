# pages/jog_page.py
# Jog controls for X, Y, and Feed (Z) axes

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSlot


# Available jog distances (mm) and speeds (mm/min)
JOG_DISTANCES = ['0.1', '1', '10', '50', '100']
JOG_SPEEDS_XY = ['500', '1000', '2000', '3000', '5000']
JOG_SPEEDS_Z  = ['200', '500', '1000', '2000']


class JogPage(QWidget):
    def __init__(self, grbl, parent=None):
        super().__init__(parent)
        self._grbl = grbl
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 8)
        root.setSpacing(10)

        title = QLabel('Jog')
        title.setObjectName('pageTitle')
        root.addWidget(title)

        # ── Speed / distance selectors ────────────────────────────────────────
        sel_row = QHBoxLayout()
        sel_row.setSpacing(12)

        sel_row.addWidget(QLabel('Distance (mm):'))
        self._dist_combo = QComboBox()
        self._dist_combo.addItems(JOG_DISTANCES)
        self._dist_combo.setCurrentIndex(2)   # default 10mm
        self._dist_combo.setMinimumWidth(100)
        sel_row.addWidget(self._dist_combo)

        sel_row.addSpacing(20)
        sel_row.addWidget(QLabel('XY Speed:'))
        self._xy_speed = QComboBox()
        self._xy_speed.addItems(JOG_SPEEDS_XY)
        self._xy_speed.setCurrentIndex(2)     # default 2000
        self._xy_speed.setMinimumWidth(110)
        sel_row.addWidget(self._xy_speed)

        sel_row.addSpacing(20)
        sel_row.addWidget(QLabel('Feed Speed:'))
        self._z_speed = QComboBox()
        self._z_speed.addItems(JOG_SPEEDS_Z)
        self._z_speed.setCurrentIndex(1)      # default 500
        self._z_speed.setMinimumWidth(110)
        sel_row.addWidget(self._z_speed)

        sel_row.addStretch()
        root.addLayout(sel_row)

        div = QFrame(); div.setFrameShape(QFrame.HLine)
        root.addWidget(div)

        # ── Jog panels row ────────────────────────────────────────────────────
        panels = QHBoxLayout()
        panels.setSpacing(20)

        panels.addWidget(self._build_xy_panel(), 3)
        panels.addWidget(self._build_z_panel(),  1)

        root.addLayout(panels)
        root.addStretch()

    # ── XY jog panel ──────────────────────────────────────────────────────────

    def _build_xy_panel(self):
        w = QWidget()
        grid = QGridLayout(w)
        grid.setSpacing(8)

        def jb(label, slot):
            b = QPushButton(label)
            b.setProperty('role', 'jog')
            b.setMinimumSize(72, 72)
            b.clicked.connect(slot)
            return b

        # Arrow layout:
        #       [Y+]
        # [X-]  [·]  [X+]
        #       [Y-]
        grid.addWidget(jb('▲', self._jog_y_plus),  0, 1)
        grid.addWidget(jb('◀', self._jog_x_minus), 1, 0)

        centre = QLabel('XY')
        centre.setAlignment(Qt.AlignCenter)
        centre.setStyleSheet('color:#555; font-size:14px;')
        grid.addWidget(centre, 1, 1)

        grid.addWidget(jb('▶', self._jog_x_plus),  1, 2)
        grid.addWidget(jb('▼', self._jog_y_minus), 2, 1)

        # Zero buttons
        z_row = QHBoxLayout()
        bx = QPushButton('Zero X')
        bx.clicked.connect(lambda: self._grbl.send('G92 X0'))
        by = QPushButton('Zero Y')
        by.clicked.connect(lambda: self._grbl.send('G92 Y0'))
        ba = QPushButton('Zero XY')
        ba.clicked.connect(lambda: self._grbl.send('G92 X0 Y0'))
        for b in (bx, by, ba):
            b.setMinimumHeight(44)
            z_row.addWidget(b)

        outer = QVBoxLayout()
        outer.addWidget(w)
        outer.addLayout(z_row)

        container = QWidget()
        container.setLayout(outer)
        return container

    # ── Feed (Z) jog panel ────────────────────────────────────────────────────

    def _build_z_panel(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignTop)

        title = QLabel('Feed (Z)')
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet('color:#a0c4ff; font-size:15px; font-weight:bold;')
        lay.addWidget(title)

        def jb(label, slot):
            b = QPushButton(label)
            b.setProperty('role', 'jog')
            b.setMinimumSize(72, 72)
            b.clicked.connect(slot)
            return b

        lay.addWidget(jb('▲\nFeed+', self._jog_z_plus))
        lay.addSpacing(10)
        lay.addWidget(jb('▼\nFeed−', self._jog_z_minus))
        lay.addSpacing(14)

        bz = QPushButton('Zero Z')
        bz.setMinimumHeight(44)
        bz.clicked.connect(lambda: self._grbl.send('G92 Z0'))
        lay.addWidget(bz)

        return w

    # ── Jog helpers ───────────────────────────────────────────────────────────

    @property
    def _dist(self):
        return float(self._dist_combo.currentText())

    @property
    def _xy_spd(self):
        return float(self._xy_speed.currentText())

    @property
    def _z_spd(self):
        return float(self._z_speed.currentText())

    def _jog_x_plus(self):
        self._grbl.jog('X', +self._dist, self._xy_spd)

    def _jog_x_minus(self):
        self._grbl.jog('X', -self._dist, self._xy_spd)

    def _jog_y_plus(self):
        self._grbl.jog('Y', +self._dist, self._xy_spd)

    def _jog_y_minus(self):
        self._grbl.jog('Y', -self._dist, self._xy_spd)

    def _jog_z_plus(self):
        self._grbl.jog('Z', +self._dist, self._z_spd)

    def _jog_z_minus(self):
        self._grbl.jog('Z', -self._dist, self._z_spd)
