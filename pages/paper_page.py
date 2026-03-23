# pages/paper_page.py
# Paper feed controls — manual feed/retract and M100 sequence

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QDoubleSpinBox,
    QGroupBox, QFrame
)
from PyQt5.QtCore import Qt


class PaperPage(QWidget):
    def __init__(self, grbl, parent=None):
        super().__init__(parent)
        self._grbl = grbl
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 8)
        root.setSpacing(14)

        title = QLabel('Paper Feed')
        title.setObjectName('pageTitle')
        root.addWidget(title)

        # ── Sensor indicators ─────────────────────────────────────────────────
        sens_row = QHBoxLayout()
        self._rear_ind  = self._sensor_indicator('Rear sensor  (P1.28)')
        self._front_ind = self._sensor_indicator('Front sensor (P1.27)')
        sens_row.addWidget(self._rear_ind)
        sens_row.addSpacing(20)
        sens_row.addWidget(self._front_ind)
        sens_row.addStretch()
        root.addLayout(sens_row)

        div = QFrame(); div.setFrameShape(QFrame.HLine)
        root.addWidget(div)

        # ── Manual feed ───────────────────────────────────────────────────────
        manual_box = QGroupBox('Manual Feed / Retract')
        manual_lay = QHBoxLayout(manual_box)
        manual_lay.setSpacing(12)

        manual_lay.addWidget(QLabel('Distance (mm):'))
        self._feed_dist = QDoubleSpinBox()
        self._feed_dist.setRange(1, 5000)
        self._feed_dist.setValue(50)
        self._feed_dist.setSingleStep(10)
        self._feed_dist.setMinimumHeight(44)
        self._feed_dist.setMinimumWidth(110)
        manual_lay.addWidget(self._feed_dist)

        manual_lay.addWidget(QLabel('Speed (mm/min):'))
        self._feed_speed = QDoubleSpinBox()
        self._feed_speed.setRange(10, 5000)
        self._feed_speed.setValue(1000)
        self._feed_speed.setSingleStep(100)
        self._feed_speed.setMinimumHeight(44)
        self._feed_speed.setMinimumWidth(110)
        manual_lay.addWidget(self._feed_speed)

        btn_fwd = QPushButton('Feed ▶▶')
        btn_fwd.setProperty('role', 'success')
        btn_fwd.setMinimumHeight(56)
        btn_fwd.clicked.connect(self._do_feed)

        btn_rev = QPushButton('◀◀ Retract')
        btn_rev.setProperty('role', 'warning')
        btn_rev.setMinimumHeight(56)
        btn_rev.clicked.connect(self._do_retract)

        manual_lay.addWidget(btn_fwd)
        manual_lay.addWidget(btn_rev)
        manual_lay.addStretch()

        root.addWidget(manual_box)

        # ── M100 auto-feed ────────────────────────────────────────────────────
        auto_box = QGroupBox('Auto Feed  (M100)')
        auto_lay = QHBoxLayout(auto_box)
        auto_lay.setSpacing(12)

        auto_lay.addWidget(QLabel('Advance (mm):'))
        self._m100_dist = QDoubleSpinBox()
        self._m100_dist.setRange(1, 2000)
        self._m100_dist.setValue(50)
        self._m100_dist.setSingleStep(10)
        self._m100_dist.setMinimumHeight(44)
        self._m100_dist.setMinimumWidth(110)
        auto_lay.addWidget(self._m100_dist)

        auto_lay.addWidget(QLabel('Feed speed:'))
        self._m100_fspeed = QDoubleSpinBox()
        self._m100_fspeed.setRange(10, 5000)
        self._m100_fspeed.setValue(1000)
        self._m100_fspeed.setSingleStep(100)
        self._m100_fspeed.setMinimumHeight(44)
        self._m100_fspeed.setMinimumWidth(110)
        auto_lay.addWidget(self._m100_fspeed)

        auto_lay.addWidget(QLabel('Transport speed:'))
        self._m100_yspeed = QDoubleSpinBox()
        self._m100_yspeed.setRange(10, 5000)
        self._m100_yspeed.setValue(3000)
        self._m100_yspeed.setSingleStep(100)
        self._m100_yspeed.setMinimumHeight(44)
        self._m100_yspeed.setMinimumWidth(110)
        auto_lay.addWidget(self._m100_yspeed)

        btn_m100 = QPushButton('Run M100')
        btn_m100.setProperty('role', 'primary')
        btn_m100.setMinimumHeight(56)
        btn_m100.clicked.connect(self._do_m100)
        auto_lay.addWidget(btn_m100)
        auto_lay.addStretch()

        root.addWidget(auto_box)
        root.addStretch()

    # ── Sensor indicator helper ───────────────────────────────────────────────

    def _sensor_indicator(self, name):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        dot = QLabel()
        dot.setFixedSize(20, 20)
        dot.setStyleSheet('background:#2c2c3e; border-radius:10px;')

        lbl = QLabel(name)
        lbl.setStyleSheet('font-size:14px; color:#a0c4ff;')

        lay.addWidget(dot)
        lay.addWidget(lbl)
        w._dot = dot
        return w

    def set_sensor_states(self, rear, front):
        """Update sensor indicator colours. Call from main window."""
        on  = 'background:#27ae60; border-radius:10px;'
        off = 'background:#2c2c3e; border-radius:10px;'
        self._rear_ind._dot.setStyleSheet(on  if rear  else off)
        self._front_ind._dot.setStyleSheet(on  if front else off)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _do_feed(self):
        d = self._feed_dist.value()
        f = self._feed_speed.value()
        self._grbl.send('G91')
        self._grbl.send('G1 Z%.3f F%.1f' % (d, f))
        self._grbl.send('G90')

    def _do_retract(self):
        d = self._feed_dist.value()
        f = self._feed_speed.value()
        self._grbl.send('G91')
        self._grbl.send('G1 Z-%.3f F%.1f' % (d, f))
        self._grbl.send('G90')

    def _do_m100(self):
        d  = self._m100_dist.value()
        f  = self._m100_fspeed.value()
        y  = self._m100_yspeed.value()
        self._grbl.send('M100 D%.3f F%.1f Y%.1f' % (d, f, y))
