# pages/dashboard.py
# Portrait dashboard:
#   Top half  — position strip + jog compass (X/Y arrows + home centre)
#   Bottom half — 8 action buttons in 4×2 grid

import re

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QSizePolicy, QButtonGroup
)
from PyQt5.QtCore import Qt, pyqtSlot

# Default jog step sizes (mm)
STEPS = ['0.1', '1', '10', '50']
DEFAULT_STEP = 2        # index into STEPS → 10mm
DEFAULT_SPEED = 2000.0  # mm/min


class DashboardPage(QWidget):
    # Signals to main window for navigation
    def __init__(self, grbl, on_usb, on_camera, on_settings, on_registration, parent=None):
        super().__init__(parent)
        self._grbl             = grbl
        self._on_usb           = on_usb
        self._on_camera        = on_camera
        self._on_settings      = on_settings
        self._on_registration  = on_registration
        self._step_idx    = DEFAULT_STEP
        self._paused      = False
        self._build()
        self._wire()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._mk_pos_strip())
        root.addWidget(self._mk_jog_area(), 5)      # top half
        root.addWidget(self._mk_divider())
        root.addWidget(self._mk_action_area(), 4)   # bottom half

    # ── Position strip ────────────────────────────────────────────────────────

    def _mk_pos_strip(self):
        bar = QWidget()
        bar.setObjectName('posStrip')
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)

        self._state_lbl = QLabel('NO CONN')
        self._state_lbl.setObjectName('stateNone')
        lay.addWidget(self._state_lbl)

        lay.addSpacing(6)

        self._x_lbl = QLabel('X  —')
        self._x_lbl.setObjectName('posLabel')
        self._y_lbl = QLabel('Y  —')
        self._y_lbl.setObjectName('posLabel')
        lay.addWidget(self._x_lbl)
        lay.addWidget(self._y_lbl)

        lay.addStretch()

        self._knife_lbl = QLabel('Knife: UP')
        self._knife_lbl.setObjectName('knifeUp')
        lay.addWidget(self._knife_lbl)

        return bar

    # ── Jog compass ───────────────────────────────────────────────────────────

    def _mk_jog_area(self):
        area = QWidget()
        area.setObjectName('jogArea')
        outer = QVBoxLayout(area)
        outer.setContentsMargins(12, 12, 12, 8)
        outer.setSpacing(10)

        # ── Step chips ────────────────────────────────────────────────────────
        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        chip_row.addWidget(QLabel('Step:'))
        self._chips = []
        self._chip_grp = QButtonGroup(self)
        self._chip_grp.setExclusive(True)
        for i, s in enumerate(STEPS):
            b = QPushButton(s + ' mm')
            b.setCheckable(True)
            b.setObjectName('chipActive' if i == DEFAULT_STEP else 'chip')
            b.setMinimumHeight(36)
            b.clicked.connect(lambda _, idx=i: self._set_step(idx))
            self._chip_grp.addButton(b, i)
            chip_row.addWidget(b)
            self._chips.append(b)
        chip_row.addStretch()
        outer.addLayout(chip_row)

        # ── Compass grid ──────────────────────────────────────────────────────
        compass = QGridLayout()
        compass.setSpacing(10)

        self._b_up    = self._jbtn('▲')
        self._b_down  = self._jbtn('▼')
        self._b_left  = self._jbtn('◀')
        self._b_right = self._jbtn('▶')
        self._b_home  = self._hbtn('⌂\nHome')

        # Row / col layout:
        #       [▲]
        # [◀]  [⌂]  [▶]
        #       [▼]
        compass.addWidget(self._b_up,    0, 1)
        compass.addWidget(self._b_left,  1, 0)
        compass.addWidget(self._b_home,  1, 1)
        compass.addWidget(self._b_right, 1, 2)
        compass.addWidget(self._b_down,  2, 1)

        # Make each cell square and equal
        for col in range(3):
            compass.setColumnStretch(col, 1)
        for row in range(3):
            compass.setRowStretch(row, 1)

        outer.addLayout(compass, 1)

        self._b_up.clicked.connect(   lambda: self._jog('Y', +1))
        self._b_down.clicked.connect( lambda: self._jog('Y', -1))
        self._b_left.clicked.connect( lambda: self._jog('X', -1))
        self._b_right.clicked.connect(lambda: self._jog('X', +1))
        self._b_home.clicked.connect( lambda: self._grbl.send('$H'))

        return area

    def _jbtn(self, label):
        b = QPushButton(label)
        b.setObjectName('jogBtn')
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return b

    def _hbtn(self, label):
        b = QPushButton(label)
        b.setObjectName('homeBtn')
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return b

    # ── Orange divider ────────────────────────────────────────────────────────

    def _mk_divider(self):
        f = QFrame()
        f.setObjectName('divider')
        f.setFrameShape(QFrame.HLine)
        return f

    # ── Action button grid ────────────────────────────────────────────────────

    def _mk_action_area(self):
        area = QWidget()
        area.setObjectName('actionArea')
        grid = QGridLayout(area)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setSpacing(10)

        # Row 0 — navigation/utility buttons
        self._b_testcut      = self._abtn('✂\nTest Cut',       'actionBtn')
        self._b_usb          = self._abtn('💾\nUSB Files',      'actionBtn')
        self._b_camera       = self._abtn('📷\nCamera',         'actionBtn')
        self._b_settings     = self._abtn('⚙\nSettings',       'actionBtn')

        # Row 1 — registration mark alignment
        self._b_registration = self._abtn('◎\nAlignment',      'actionBtn')
        self._b_knife_up     = self._abtn('▲\nKnife Up',       'actionBtnKnifeUp')
        self._b_knife_down   = self._abtn('▼\nKnife Down',     'actionBtnKnifeDown')
        self._b_testcut2     = self._abtn('✂\nTest 10×10',     'actionBtn')

        # Row 2 — job control
        self._b_pause        = self._abtn('',          'actionBtnPause')
        self._b_cancel       = self._abtn('✕\nCancel',         'actionBtnCancel')

        grid.addWidget(self._b_testcut,       0, 0)
        grid.addWidget(self._b_usb,           0, 1)
        grid.addWidget(self._b_camera,        0, 2)
        grid.addWidget(self._b_settings,      0, 3)
        grid.addWidget(self._b_registration,  1, 0)
        grid.addWidget(self._b_knife_up,      1, 1)
        grid.addWidget(self._b_knife_down,    1, 2)
        grid.addWidget(self._b_testcut2,      1, 3)
        grid.addWidget(self._b_pause,         2, 0, 1, 2)
        grid.addWidget(self._b_cancel,        2, 2, 1, 2)

        for col in range(4):
            grid.setColumnStretch(col, 1)
        for row in range(3):
            grid.setRowStretch(row, 1)

        # Wire actions
        self._b_testcut.clicked.connect(       self._test_cut)
        self._b_testcut2.clicked.connect(      self._test_cut)
        self._b_usb.clicked.connect(           self._on_usb)
        self._b_camera.clicked.connect(        self._on_camera)
        self._b_settings.clicked.connect(      self._on_settings)
        self._b_registration.clicked.connect(  self._on_registration)
        self._b_knife_up.clicked.connect(      self._grbl.knife_up_cmd)
        self._b_knife_down.clicked.connect(    self._knife_down)
        self._b_pause.clicked.connect(         self._toggle_pause)
        self._b_cancel.clicked.connect(        self._cancel)

        return area


    def _abtn(self, label, obj_name):
        emoji_pattern = re.compile(
            "[\U0001F300-\U0001FAFF\u2600-\u27BF]+",
            flags=re.UNICODE
        )

        def replace_emoji(match):
            return f'<span style="font-size:20px;">{match.group(0)}</span>'

        styled_label = emoji_pattern.sub(replace_emoji, label)
        styled_label = styled_label.replace("\n", "<br>")

        b = QPushButton()
        layout = QVBoxLayout(b)

        lbl = QLabel(styled_label)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setTextFormat(Qt.RichText)

        lbl.setAttribute(Qt.WA_TransparentForMouseEvents)

        layout.addWidget(lbl)
        layout.setContentsMargins(0, 0, 0, 0)

        b.setObjectName(obj_name)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        return b

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def _wire(self):
        g = self._grbl
        g.position_changed.connect(self._on_pos)
        g.state_changed.connect(   self._on_state)
        g.knife_changed.connect(   self._on_knife)
        g.connected.connect(    lambda: self._on_state('Idle'))
        g.disconnected.connect( lambda: self._on_state('Disconnected'))

    # ── Slots ─────────────────────────────────────────────────────────────────

    @pyqtSlot(float, float, float)
    def _on_pos(self, x, y, z):
        self._x_lbl.setText('X  %+.2f' % x)
        self._y_lbl.setText('Y  %+.2f' % y)

    @pyqtSlot(str)
    def _on_state(self, state):
        from grbl_connection import STATE_MAP
        label, obj = STATE_MAP.get(state, (state.upper(), 'stateNone'))
        self._state_lbl.setText(label)
        self._state_lbl.setObjectName(obj)
        self._state_lbl.style().unpolish(self._state_lbl)
        self._state_lbl.style().polish(self._state_lbl)

        # Reset pause button if machine returns to idle
        if state in ('Idle', 'Disconnected'):
            self._paused = False
            self._b_pause.setText('⏸\nPause')

    @pyqtSlot(bool, int)
    def _on_knife(self, down, force):
        if down:
            self._knife_lbl.setText('Knife: DN')
            self._knife_lbl.setObjectName('knifeDown')
        else:
            self._knife_lbl.setText('Knife: UP')
            self._knife_lbl.setObjectName('knifeUp')
        self._knife_lbl.style().unpolish(self._knife_lbl)
        self._knife_lbl.style().polish(self._knife_lbl)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _set_step(self, idx):
        self._step_idx = idx
        for i, chip in enumerate(self._chips):
            chip.setObjectName('chipActive' if i == idx else 'chip')
            chip.style().unpolish(chip)
            chip.style().polish(chip)

    def _jog(self, axis, direction):
        dist  = float(STEPS[self._step_idx]) * direction
        self._grbl.jog(axis, dist, DEFAULT_SPEED)

    def _test_cut(self):
        """Cut a 10×10 mm rectangle from current position."""
        cmds = [
            'G91',           # relative
            'M3 S1000',      # knife down
            'G4 P0.05',      # dwell 50ms
            'G1 X10 F2000',  # right 10mm
            'G1 Y10 F2000',  # up 10mm
            'G1 X-10 F2000', # left 10mm
            'G1 Y-10 F2000', # down 10mm
            'M5',            # knife up
            'G4 P0.03',
            'G90',           # back to absolute
        ]
        for c in cmds:
            self._grbl.send(c)

    def _knife_down(self):
        self._grbl.knife_down_cmd(1000)
        self._grbl.send('G4 P0.05')

    def _toggle_pause(self):
        if self._paused:
            self._grbl.cycle_start()
            self._b_pause.setText('⏸\nPause')
            self._paused = False
        else:
            self._grbl.feed_hold()
            self._b_pause.setText('▶\nResume')
            self._paused = True

    def _cancel(self):
        self._grbl.reset()
        self._grbl.send('M5')
        self._paused = False
        self._b_pause.setText('⏸\nPause')