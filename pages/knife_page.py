# pages/knife_page.py
# Knife solenoid control with force (S-value) slider

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QSpinBox,
    QGroupBox, QFrame
)
from PyQt5.QtCore import Qt, pyqtSlot


class KnifePage(QWidget):
    def __init__(self, grbl, parent=None):
        super().__init__(parent)
        self._grbl = grbl
        self._build_ui()
        # Connect the dedicated knife signal — fires immediately on send
        self._grbl.knife_changed.connect(self._on_knife)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 8)
        root.setSpacing(14)

        title = QLabel('Knife Control')
        title.setObjectName('pageTitle')
        root.addWidget(title)

        # ── Status badge ──────────────────────────────────────────────────────
        self._status = QLabel('Knife: UP')
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet(
            'background:#1e8449; color:white; font-size:22px; '
            'font-weight:bold; padding:10px; border-radius:10px;'
        )
        root.addWidget(self._status)

        # ── Force slider ──────────────────────────────────────────────────────
        force_box = QGroupBox('Knife Force  (S value sent with M3)')
        force_lay = QVBoxLayout(force_box)

        slider_row = QHBoxLayout()
        lbl_min = QLabel('0')
        lbl_min.setStyleSheet('color:#7f8c8d;')
        lbl_max = QLabel('1000')
        lbl_max.setStyleSheet('color:#7f8c8d;')

        self._force_slider = QSlider(Qt.Horizontal)
        self._force_slider.setRange(0, 1000)
        self._force_slider.setValue(1000)
        self._force_slider.setTickInterval(100)
        self._force_slider.setTickPosition(QSlider.TicksBelow)
        self._force_slider.valueChanged.connect(self._on_slider)

        slider_row.addWidget(lbl_min)
        slider_row.addWidget(self._force_slider, 1)
        slider_row.addWidget(lbl_max)

        self._force_lbl = QLabel('Force: 1000')
        self._force_lbl.setAlignment(Qt.AlignCenter)
        self._force_lbl.setStyleSheet(
            'font-size:18px; font-weight:bold; color:#a0c4ff;'
        )

        force_lay.addLayout(slider_row)
        force_lay.addWidget(self._force_lbl)
        root.addWidget(force_box)

        # ── Main knife buttons ────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(16)

        self._btn_down = QPushButton('▼  KNIFE DOWN')
        self._btn_down.setProperty('role', 'knife')
        self._btn_down.setMinimumHeight(90)
        self._btn_down.clicked.connect(self._knife_down)

        self._btn_up = QPushButton('▲  KNIFE UP')
        self._btn_up.setProperty('role', 'knife')
        self._btn_up.setMinimumHeight(90)
        self._btn_up.clicked.connect(self._grbl.knife_up_cmd)

        btn_row.addWidget(self._btn_down)
        btn_row.addWidget(self._btn_up)
        root.addLayout(btn_row)

        div = QFrame(); div.setFrameShape(QFrame.HLine)
        root.addWidget(div)

        # ── Dwell time controls ───────────────────────────────────────────────
        dwell_box = QGroupBox('Dwell Times')
        dwell_lay = QHBoxLayout(dwell_box)

        dwell_lay.addWidget(QLabel('Down dwell (ms):'))
        self._dwell_down = QSpinBox()
        self._dwell_down.setRange(0, 2000)
        self._dwell_down.setValue(50)
        self._dwell_down.setSingleStep(10)
        self._dwell_down.setMinimumHeight(44)
        self._dwell_down.setMinimumWidth(100)
        dwell_lay.addWidget(self._dwell_down)

        dwell_lay.addSpacing(30)
        dwell_lay.addWidget(QLabel('Up dwell (ms):'))
        self._dwell_up = QSpinBox()
        self._dwell_up.setRange(0, 2000)
        self._dwell_up.setValue(30)
        self._dwell_up.setSingleStep(10)
        self._dwell_up.setMinimumHeight(44)
        self._dwell_up.setMinimumWidth(100)
        dwell_lay.addWidget(self._dwell_up)

        dwell_lay.addSpacing(30)

        btn_test = QPushButton('Test Cycle')
        btn_test.setProperty('role', 'warning')
        btn_test.setMinimumHeight(44)
        btn_test.clicked.connect(self._test_cycle)
        dwell_lay.addWidget(btn_test)
        dwell_lay.addStretch()

        root.addWidget(dwell_box)
        root.addStretch()

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_slider(self, val):
        self._force_lbl.setText('Force: %d' % val)

    def _knife_down(self):
        force  = self._force_slider.value()
        dwell  = self._dwell_down.value() / 1000.0
        self._grbl.knife_down_cmd(force)
        if dwell > 0:
            self._grbl.send('G4 P%.3f' % dwell)

    def _test_cycle(self):
        force   = self._force_slider.value()
        down_s  = max(self._dwell_down.value() / 1000.0, 0.3)
        up_s    = max(self._dwell_up.value()   / 1000.0, 0.2)
        self._grbl.knife_down_cmd(force)
        self._grbl.send('G4 P%.3f' % down_s)
        self._grbl.knife_up_cmd()
        self._grbl.send('G4 P%.3f' % up_s)

    @pyqtSlot(bool, int)
    def _on_knife(self, down, force):
        if down:
            self._status.setText('Knife: DOWN  ▼  S%d' % force)
            self._status.setStyleSheet(
                'background:#922b21; color:white; font-size:22px; '
                'font-weight:bold; padding:10px; border-radius:10px;'
            )
        else:
            self._status.setText('Knife: UP  ▲')
            self._status.setStyleSheet(
                'background:#1e8449; color:white; font-size:22px; '
                'font-weight:bold; padding:10px; border-radius:10px;'
            )