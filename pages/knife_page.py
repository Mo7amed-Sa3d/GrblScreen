# pages/knife_page.py
# Knife control — force slider, down/up buttons, status badge

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QSpinBox, QSizePolicy, QFrame
)
from PyQt5.QtCore import Qt, pyqtSlot


class KnifePage(QWidget):
    def __init__(self, grbl, parent=None):
        super().__init__(parent)
        self.setObjectName('page')
        self._grbl = grbl
        self._build()
        self._grbl.knife_changed.connect(self._on_knife)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 8)
        root.setSpacing(12)

        # Title
        title = QLabel('Knife Control')
        title.setObjectName('pageTitle')
        root.addWidget(title)

        # Status badge
        self._badge = QLabel('▲  KNIFE  UP')
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setMinimumHeight(70)
        self._badge.setStyleSheet(
            'background:#2e7d32; color:white; font-size:22px; '
            'font-weight:bold; border-radius:10px;'
        )
        root.addWidget(self._badge)

        # Force slider
        force_card = QWidget()
        force_card.setObjectName('card')
        fc = QVBoxLayout(force_card)
        fc.setContentsMargins(14, 10, 14, 10)
        fc.setSpacing(8)

        force_top = QHBoxLayout()
        lbl_force = QLabel('Knife Force')
        lbl_force.setObjectName('cardTitle')
        self._force_val = QLabel('1000')
        self._force_val.setStyleSheet(
            'font-size:20px; font-weight:bold; color:#ff8c00;'
        )
        force_top.addWidget(lbl_force)
        force_top.addStretch()
        force_top.addWidget(self._force_val)
        fc.addLayout(force_top)

        slider_row = QHBoxLayout()
        lbl0 = QLabel('0');   lbl0.setStyleSheet('color:#666;')
        lbl1 = QLabel('1000'); lbl1.setStyleSheet('color:#666;')
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.setValue(1000)
        self._slider.setTickInterval(200)
        self._slider.setTickPosition(QSlider.TicksBelow)
        self._slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._slider.valueChanged.connect(
            lambda v: self._force_val.setText(str(v))
        )
        slider_row.addWidget(lbl0)
        slider_row.addWidget(self._slider, 1)
        slider_row.addWidget(lbl1)
        fc.addLayout(slider_row)

        root.addWidget(force_card)

        div = QFrame(); div.setFrameShape(QFrame.HLine)
        root.addWidget(div)

        # Down / Up buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self._b_down = QPushButton('▼  KNIFE DOWN')
        self._b_down.setProperty('role', 'knife')
        self._b_down.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._b_down.setMinimumHeight(90)
        self._b_down.clicked.connect(self._knife_down)

        self._b_up = QPushButton('▲  KNIFE UP')
        self._b_up.setProperty('role', 'knife')
        self._b_up.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._b_up.setMinimumHeight(90)
        self._b_up.setStyleSheet(
            'QPushButton { background:#1b5e20; border:1px solid #4caf50; '
            'color:white; font-size:16px; font-weight:bold; '
            'min-height:90px; border-radius:10px; }'
            'QPushButton:hover { background:#2e7d32; }'
            'QPushButton:pressed { background:#4caf50; }'
        )
        self._b_up.clicked.connect(self._knife_up)

        btn_row.addWidget(self._b_down)
        btn_row.addWidget(self._b_up)
        root.addLayout(btn_row)

        # Dwell controls
        dwell_row = QHBoxLayout()
        dwell_row.setSpacing(16)

        dwell_row.addWidget(QLabel('Down dwell (ms):'))
        self._dwell_dn = QSpinBox()
        self._dwell_dn.setRange(0, 2000); self._dwell_dn.setValue(50)
        self._dwell_dn.setSingleStep(10); self._dwell_dn.setMinimumWidth(100)
        dwell_row.addWidget(self._dwell_dn)

        dwell_row.addSpacing(10)
        dwell_row.addWidget(QLabel('Up dwell (ms):'))
        self._dwell_up = QSpinBox()
        self._dwell_up.setRange(0, 2000); self._dwell_up.setValue(30)
        self._dwell_up.setSingleStep(10); self._dwell_up.setMinimumWidth(100)
        dwell_row.addWidget(self._dwell_up)

        dwell_row.addStretch()

        b_test = QPushButton('Test Cycle')
        b_test.setProperty('role', 'warning')
        b_test.setMinimumHeight(46)
        b_test.clicked.connect(self._test)
        dwell_row.addWidget(b_test)

        root.addLayout(dwell_row)
        root.addStretch()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _knife_down(self):
        f = self._slider.value()
        self._grbl.knife_down_cmd(f)
        d = self._dwell_dn.value()
        if d: self._grbl.send('G4 P%.3f' % (d / 1000.0))

    def _knife_up(self):
        self._grbl.knife_up_cmd()
        d = self._dwell_up.value()
        if d: self._grbl.send('G4 P%.3f' % (d / 1000.0))

    def _test(self):
        f  = self._slider.value()
        dn = max(self._dwell_dn.value() / 1000.0, 0.3)
        up = max(self._dwell_up.value() / 1000.0, 0.2)
        self._grbl.knife_down_cmd(f)
        self._grbl.send('G4 P%.3f' % dn)
        self._grbl.knife_up_cmd()
        self._grbl.send('G4 P%.3f' % up)

    @pyqtSlot(bool, int)
    def _on_knife(self, down, force):
        if down:
            self._badge.setText('▼  KNIFE  DOWN   S%d' % force)
            self._badge.setStyleSheet(
                'background:#b71c1c; color:white; font-size:22px; '
                'font-weight:bold; border-radius:10px;'
            )
        else:
            self._badge.setText('▲  KNIFE  UP')
            self._badge.setStyleSheet(
                'background:#2e7d32; color:white; font-size:22px; '
                'font-weight:bold; border-radius:10px;'
            )