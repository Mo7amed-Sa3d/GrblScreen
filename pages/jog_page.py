# pages/jog_page.py
# Jogging — XY compass + Z feed, speed/distance chip selectors

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QButtonGroup, QSizePolicy, QFrame
)
from PyQt5.QtCore import Qt


# Distance chips (mm)
DISTANCES = ['0.1', '1', '10', '50', '100']
# Speed chips (mm/min)
XY_SPEEDS = ['500', '1000', '3000', '6000']
Z_SPEEDS  = ['200', '500', '1000', '2000']


class _ChipBar(QWidget):
    """Horizontal row of exclusive toggle buttons ('chips')."""
    def __init__(self, options, default_idx=1, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._grp = QButtonGroup(self)
        self._grp.setExclusive(True)

        for i, text in enumerate(options):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setMinimumHeight(40)
            b.setMinimumWidth(64)
            b.setStyleSheet(self._style(False))
            self._grp.addButton(b, i)
            lay.addWidget(b)

        lay.addStretch()
        self._grp.buttons()[default_idx].setChecked(True)
        self._grp.buttonToggled.connect(self._on_toggle)
        self._update_styles()

    def _style(self, active):
        if active:
            return ('QPushButton { background:#ff8c00; color:#1a1a1a; '
                    'border:1px solid #ff8c00; border-radius:6px; '
                    'font-weight:bold; font-size:13px; }')
        return ('QPushButton { background:#2d2d2d; color:#aaaaaa; '
                'border:1px solid #505050; border-radius:6px; '
                'font-size:13px; }')

    def _on_toggle(self):
        self._update_styles()

    def _update_styles(self):
        for b in self._grp.buttons():
            b.setStyleSheet(self._style(b.isChecked()))

    @property
    def value(self):
        return float(self._grp.checkedButton().text())


class JogPage(QWidget):
    def __init__(self, grbl, parent=None):
        super().__init__(parent)
        self.setObjectName('page')
        self._grbl = grbl
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(10)

        title = QLabel('Jog')
        title.setObjectName('pageTitle')
        root.addWidget(title)

        # Distance chips
        dc = QHBoxLayout()
        dc.addWidget(QLabel('Step:'))
        dc.addSpacing(8)
        self._dist = _ChipBar(DISTANCES, default_idx=2)
        dc.addWidget(self._dist)
        root.addLayout(dc)

        div = QFrame(); div.setFrameShape(QFrame.HLine)
        root.addWidget(div)

        # Jog panels
        panels = QHBoxLayout()
        panels.setSpacing(16)
        panels.addWidget(self._build_xy(), 3)
        panels.addWidget(self._build_z(),  1)
        root.addLayout(panels, 1)

    def _jbtn(self, label):
        b = QPushButton(label)
        b.setProperty('role', 'jog')
        b.setMinimumSize(80, 80)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return b

    def _build_xy(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setSpacing(8)
        outer.setContentsMargins(0, 0, 0, 0)

        # Speed chips
        sc = QHBoxLayout()
        sc.addWidget(QLabel('XY:'))
        sc.addSpacing(6)
        self._xy_spd = _ChipBar(XY_SPEEDS, default_idx=2)
        sc.addWidget(self._xy_spd)
        outer.addLayout(sc)

        # Compass grid
        g = QGridLayout()
        g.setSpacing(8)

        b_yp = self._jbtn('▲')
        b_ym = self._jbtn('▼')
        b_xm = self._jbtn('◀')
        b_xp = self._jbtn('▶')

        centre = QLabel('XY')
        centre.setAlignment(Qt.AlignCenter)
        centre.setStyleSheet(
            'color:#555; font-size:14px; font-weight:bold;'
        )

        g.addWidget(b_yp,    0, 1)
        g.addWidget(b_xm,    1, 0)
        g.addWidget(centre,  1, 1)
        g.addWidget(b_xp,    1, 2)
        g.addWidget(b_ym,    2, 1)

        # Stretch rows and columns evenly
        g.setRowStretch(0, 1)
        g.setRowStretch(1, 1)
        g.setRowStretch(2, 1)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(2, 1)

        outer.addLayout(g)

        # Zero buttons row
        zr = QHBoxLayout()
        zr.setSpacing(8)
        for label, cmd in [('Zero X', 'G92 X0'),
                            ('Zero Y', 'G92 Y0'),
                            ('Zero XY','G92 X0 Y0')]:
            b = QPushButton(label)
            b.setMinimumHeight(46)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(lambda _, c=cmd: self._grbl.send(c))
            zr.addWidget(b)
        outer.addLayout(zr)

        # Connect arrows
        b_yp.clicked.connect(lambda: self._grbl.jog('Y', +self._dist.value, self._xy_spd.value))
        b_ym.clicked.connect(lambda: self._grbl.jog('Y', -self._dist.value, self._xy_spd.value))
        b_xm.clicked.connect(lambda: self._grbl.jog('X', -self._dist.value, self._xy_spd.value))
        b_xp.clicked.connect(lambda: self._grbl.jog('X', +self._dist.value, self._xy_spd.value))

        return w

    def _build_z(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        lay.setContentsMargins(0, 0, 0, 0)

        # Speed chips
        sc = QHBoxLayout()
        sc.addWidget(QLabel('Z:'))
        sc.addSpacing(6)
        self._z_spd = _ChipBar(Z_SPEEDS, default_idx=1)
        sc.addWidget(self._z_spd)
        lay.addLayout(sc)

        lbl = QLabel('FEED\n(Z)')
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet('color:#aaa; font-size:13px; font-weight:bold;')
        lay.addWidget(lbl)

        bfwd = self._jbtn('▲\n+')
        brev = self._jbtn('▼\n−')
        bfwd.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        brev.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        bfwd.clicked.connect(lambda: self._grbl.jog('Z', +self._dist.value, self._z_spd.value))
        brev.clicked.connect(lambda: self._grbl.jog('Z', -self._dist.value, self._z_spd.value))

        lay.addWidget(bfwd, 1)
        lay.addWidget(brev, 1)

        bz = QPushButton('Zero Z')
        bz.setMinimumHeight(46)
        bz.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bz.clicked.connect(lambda: self._grbl.send('G92 Z0'))
        lay.addWidget(bz)

        return w