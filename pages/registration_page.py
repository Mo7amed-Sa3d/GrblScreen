# pages/registration_page.py
# 4-point registration mark auto-scan workflow.
#
# State machine (all in main thread, event-driven):
#   IDLE → MOVING[1-4] → SCANNING[1-4] → COMPUTING → ARMED
#
# The page receives the 4 design positions parsed from the G-code file.
# It moves the machine to each nominal mark position automatically
# (offset so the camera is over the dot), scans each one, computes
# the affine correction, arms the corrector, then calls on_complete(True/False).
#
# Usage:
#   page = RegistrationPage(corrector, design_pts, on_complete, on_back)
#   # design_pts: list of 4 (x,y) tuples from parse_regmarks()
#   # on_complete(success): called when done or cancelled

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QProgressBar, QSizePolicy
)
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui  import QPixmap, QImage

import registration as reg


# States
IDLE        = 'idle'
MOVING      = 'moving'    # moving to mark i
SCANNING    = 'scanning'  # camera capturing
COMPUTING   = 'computing'
ARMED       = 'armed'


class _ScanThread(QThread):
    """Runs camera capture + dot detection off the main thread."""
    # Emit world_x, world_y, dx_px, dy_px, success, message
    # Avoids pyqtSignal(object) which is unreliable on some PyQt5 builds.
    scan_ok   = pyqtSignal(float, float, float, float)   # world_x, world_y, dx_px, dy_px
    scan_fail = pyqtSignal(str)                          # error message
    frame_captured = pyqtSignal(object)                  # opencv BGR frame (numpy array)

    def __init__(self, mx, my):
        super().__init__()
        self._mx = mx; self._my = my

    def run(self):
        result = reg.scan_dot(self._mx, self._my)
        # Emit the annotated frame if available
        if hasattr(result, '_frame') and result._frame is not None:
            self.frame_captured.emit(result._frame)
        if result.success:
            self.scan_ok.emit(result.world_x, result.world_y,
                              result.dx_px, result.dy_px)
        else:
            self.scan_fail.emit(result.message)


class RegistrationPage(QWidget):

    def __init__(self, corrector, design_pts, on_complete, on_back, parent=None):
        """
        corrector   : TiltCorrector
        design_pts  : list of 4 (x,y) tuples (from ;RegMarks comment)
        on_complete : callable(success: bool) — called when done
        on_back     : callable() — called when user presses Back/Skip
        """
        super().__init__(parent)
        self._corrector   = corrector
        self._design      = design_pts   # 4 (x,y) design positions
        self._on_complete = on_complete
        self._on_back     = on_back

        # Runtime state
        self._state       = IDLE
        self._current     = 0          # which mark (0-3)
        self._results     = [None]*4   # DotScanResult per mark
        self._scan_thread = None

        # Poll timer — detects when GRBL returns to Idle after a move
        self._move_timer  = QTimer(self)
        self._move_timer.setInterval(150)
        self._move_timer.timeout.connect(self._on_move_poll)

        self._build()
        # Wire state changes for move completion detection
        self._corrector.state_changed.connect(self._on_grbl_state)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        self._btn_back = QPushButton('✕  Skip / Cancel')
        self._btn_back.setProperty('role', 'back')
        self._btn_back.setMinimumHeight(48)
        self._btn_back.clicked.connect(self._skip)
        hdr.addWidget(self._btn_back)

        title = QLabel('Registration Marks')
        title.setStyleSheet('font-size:17px; font-weight:bold; color:#ff8c00;')
        hdr.addWidget(title, 1)

        self._badge = QLabel('WAITING')
        self._badge.setStyleSheet(
            'background:#444; color:#aaa; font-size:12px; '
            'font-weight:bold; padding:3px 10px; border-radius:5px;')
        hdr.addWidget(self._badge)
        root.addLayout(hdr)

        # Overall progress bar
        self._overall_bar = QProgressBar()
        self._overall_bar.setRange(0, 4)
        self._overall_bar.setValue(0)
        self._overall_bar.setMaximumHeight(10)
        root.addWidget(self._overall_bar)

        div = QFrame(); div.setFrameShape(QFrame.HLine); root.addWidget(div)

        # Mark status rows (one per mark)
        self._mark_rows = []
        for i in range(4):
            x, y = self._design[i]
            row  = self._mk_mark_row(i, x, y)
            root.addWidget(row)
            self._mark_rows.append(row)

        div2 = QFrame(); div2.setFrameShape(QFrame.HLine); root.addWidget(div2)

        # Camera feed display (shows during scanning)
        self._camera_label = QLabel()
        self._camera_label.setAlignment(Qt.AlignCenter)
        self._camera_label.setMinimumHeight(250)
        self._camera_label.setStyleSheet(
            'background:#1a1a1a; border:2px solid #444; border-radius:8px; color:#666;')
        self._camera_label.setText('Camera feed will appear here during scan')
        root.addWidget(self._camera_label, 1)

        div3 = QFrame(); div3.setFrameShape(QFrame.HLine); root.addWidget(div3)

        # Status / result message
        self._msg = QLabel('Press Start to begin automatic scan')
        self._msg.setAlignment(Qt.AlignCenter)
        self._msg.setStyleSheet('font-size:13px; color:#aaa;')
        self._msg.setWordWrap(True)
        root.addWidget(self._msg)

        # Action buttons
        act = QHBoxLayout(); act.setSpacing(10)

        self._btn_start = QPushButton('▶  Start Scan')
        self._btn_start.setProperty('role', 'accent')
        self._btn_start.setMinimumHeight(56)
        self._btn_start.clicked.connect(self._start)
        act.addWidget(self._btn_start)

        self._btn_retry = QPushButton('↺  Retry Mark')
        self._btn_retry.setProperty('role', 'warning')
        self._btn_retry.setMinimumHeight(56)
        self._btn_retry.setEnabled(False)
        self._btn_retry.clicked.connect(self._retry_current)
        act.addWidget(self._btn_retry)

        self._btn_apply = QPushButton('✓  Apply && Cut')
        self._btn_apply.setProperty('role', 'success')
        self._btn_apply.setMinimumHeight(56)
        self._btn_apply.setEnabled(False)
        self._btn_apply.clicked.connect(self._apply)
        act.addWidget(self._btn_apply)

        root.addLayout(act)

    def _mk_mark_row(self, idx, dx, dy):
        """Create the status row widget for one mark."""
        w = QWidget()
        w.setStyleSheet('background:#2d2d2d; border-radius:8px;')
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        # Number circle
        num = QLabel(str(idx + 1))
        num.setFixedSize(36, 36)
        num.setAlignment(Qt.AlignCenter)
        num.setStyleSheet('background:#444; border-radius:18px; '
                          'font-size:15px; font-weight:bold; color:#aaa;')
        lay.addWidget(num)
        w._num = num

        # Design position label
        pos = QLabel('Design: (%.1f, %.1f)' % (dx, dy))
        pos.setStyleSheet('font-size:13px; color:#888;')
        lay.addWidget(pos)

        lay.addStretch()

        # Scan result label
        res = QLabel('—')
        res.setMinimumWidth(150)
        res.setAlignment(Qt.AlignCenter)
        res.setStyleSheet('background:#383838; color:#666; font-size:12px; '
                          'padding:3px 10px; border-radius:5px;')
        lay.addWidget(res)
        w._res = res

        return w

    # ── Start / retry ─────────────────────────────────────────────────────────

    def _start(self):
        if not self._corrector.is_connected():
            self._show_msg('Not connected to machine.', '#f44336')
            return
        self._btn_start.setEnabled(False)
        self._btn_retry.setEnabled(False)
        self._btn_apply.setEnabled(False)
        self._btn_back.setEnabled(False)
        self._current = 0
        self._results = [None]*4
        self._reset_mark_displays()
        self._move_to(self._current)

    def _retry_current(self):
        """Retry scan for the mark that failed."""
        self._btn_retry.setEnabled(False)
        self._btn_apply.setEnabled(False)
        self._results[self._current] = None
        self._update_mark_display(self._current, None)
        self._move_to(self._current)

    # ── Auto-scan state machine ───────────────────────────────────────────────

    def _move_to(self, idx):
        """Move camera over mark idx."""
        self._state   = MOVING
        self._current = idx
        self._update_badge('MOVING TO %d' % (idx+1), '#2196f3')
        self._show_msg('Moving to mark %d…' % (idx+1), '#aaa')
        self._mark_row_highlight(idx, 'moving')

        dx, dy = self._design[idx]
        # Position the knife at (design - cam_offset) so the camera sees the dot
        target_x = dx - reg.CAM_OFFSET_X_MM
        target_y = dy - reg.CAM_OFFSET_Y_MM

        # Send the move — bypasses correction (we're aligning, not cutting)
        self._corrector._grbl.send('G90')
        self._corrector._grbl.send('G0 X%.4f Y%.4f' % (target_x, target_y))

        # Start polling for Idle
        self._move_timer.start()

    def _on_move_poll(self):
        """Called every 150ms while waiting for move to complete."""
        if self._state != MOVING:
            self._move_timer.stop()
            return
        # GRBL reports Idle when the move is complete
        if self._corrector.state in ('Idle', 'idle'):
            self._move_timer.stop()
            self._do_scan()

    @pyqtSlot(str)
    def _on_grbl_state(self, state):
        """Backup detection for Idle after move (in case poll misses it)."""
        if self._state == MOVING and state == 'Idle':
            self._move_timer.stop()
            self._do_scan()

    def _do_scan(self):
        """Trigger camera scan for current mark."""
        self._state = SCANNING
        self._update_badge('SCANNING %d' % (self._current+1), '#ff8c00')
        self._show_msg('Scanning mark %d…' % (self._current+1), '#aaa')
        self._mark_row_highlight(self._current, 'scanning')

        mx, my = self._corrector.mpos[0], self._corrector.mpos[1]
        self._scan_thread = _ScanThread(mx, my)
        self._scan_thread.scan_ok.connect(self._on_scan_ok)
        self._scan_thread.scan_fail.connect(self._on_scan_fail)
        self._scan_thread.frame_captured.connect(self._on_frame_captured)
        self._scan_thread.start()

    @pyqtSlot(object)
    def _on_frame_captured(self, bgr_frame):
        """Display captured frame with opencv markings."""
        try:
            import cv2
            import numpy as np
            # Convert BGR frame to RGB for Qt display
            if bgr_frame is not None:
                h, w = bgr_frame.shape[:2]
                # Convert BGR to RGB
                rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
                # Ensure contiguous memory layout
                rgb = np.ascontiguousarray(rgb)
                # Convert to QImage
                bytes_per_line = 3 * w
                q_img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
                # Scale to fit label
                label_w = self._camera_label.width()
                label_h = self._camera_label.height()
                if label_w > 0 and label_h > 0:
                    pix = QPixmap.fromImage(q_img).scaled(
                        label_w - 10, label_h - 10, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self._camera_label.setPixmap(pix)
                else:
                    # If label size not yet known, just show the raw image
                    pix = QPixmap.fromImage(q_img)
                    self._camera_label.setPixmap(pix)
        except Exception as e:
            self._camera_label.setText('Frame display error: %s' % str(e))

    @pyqtSlot(float, float, float, float)
    def _on_scan_ok(self, world_x, world_y, dx_px, dy_px):
        """Called in main thread when camera scan succeeds."""
        result = reg.DotScanResult(True, world_x=world_x, world_y=world_y,
                                   dx_px=dx_px, dy_px=dy_px)
        self._handle_scan_result(result)

    @pyqtSlot(str)
    def _on_scan_fail(self, message):
        """Called in main thread when camera scan fails."""
        result = reg.DotScanResult(False, message=message)
        self._handle_scan_result(result)

    def _handle_scan_result(self, result):
        """Process scan result — called from both _on_scan_ok and _on_scan_fail."""
        self._results[self._current] = result

        if result.success:
            self._update_mark_display(self._current, result)
            self._mark_row_highlight(self._current, 'ok')
            self._overall_bar.setValue(self._current + 1)

            if self._current < 3:
                self._current += 1
                self._move_to(self._current)
            else:
                self._state = COMPUTING
                self._all_scanned()
        else:
            self._mark_row_highlight(self._current, 'fail')
            self._update_mark_display(self._current, None,
                                      error=result.message)
            self._show_msg('Mark %d failed: %s\n'
                           'Press Retry or adjust machine position.'
                           % (self._current+1, result.message), '#f44336')
            self._btn_retry.setEnabled(True)
            self._btn_back.setEnabled(True)
            self._state = IDLE
            self._update_badge('SCAN FAILED', '#f44336')

    # ── After all 4 scanned ───────────────────────────────────────────────────

    def _all_scanned(self):
        self._update_badge('COMPUTING', '#9c27b0')
        self._show_msg('Computing affine correction…', '#aaa')

        actual = [(r.world_x, r.world_y) for r in self._results]
        corr, warn = reg.compute_affine_correction(self._design, actual)

        if corr is None:
            self._show_msg('Computation failed: %s' % warn, '#f44336')
            self._update_badge('FAILED', '#f44336')
            self._btn_start.setEnabled(True)
            self._btn_back.setEnabled(True)
            self._state = IDLE
            return

        self._pending_corr = corr

        msg = corr.summary()
        if warn:
            msg += '\n⚠ ' + warn
        self._show_msg(msg, '#4caf50')
        self._update_badge('READY', '#4caf50')
        self._state = ARMED
        self._btn_apply.setEnabled(True)
        self._btn_back.setEnabled(True)

    # ── Apply ─────────────────────────────────────────────────────────────────

    def _apply(self):
        """Arm correction, set work origin at mark 1, call on_complete."""
        self._corrector.set_correction(self._pending_corr)

        # Set work origin: mark 1 design position = (x1,y1) from ;RegMarks
        # After G92, machine reports design_x1,y1 when knife is at mark 1
        x1, y1 = self._design[0]
        # First move knife to where mark 1 actually is
        self._corrector._grbl.send('G0 X%.4f Y%.4f'
                                   % (self._results[0].world_x,
                                      self._results[0].world_y))
        # Then set that as the job origin
        self._corrector._grbl.send('G92 X%.4f Y%.4f' % (x1, y1))

        self._update_badge('ARMED', '#4caf50')
        self._btn_apply.setEnabled(False)
        self._on_complete(True)

    def _skip(self):
        """Skip registration — cut without correction."""
        self._move_timer.stop()
        if self._scan_thread and self._scan_thread.isRunning():
            self._scan_thread.quit()
        self._state = IDLE
        self._on_back()

    # ── Display helpers ───────────────────────────────────────────────────────

    def _show_msg(self, text, color='#aaa'):
        self._msg.setText(text)
        self._msg.setStyleSheet('font-size:13px; color:%s;' % color)

    def _update_badge(self, text, color='#444'):
        self._badge.setText(text)
        self._badge.setStyleSheet(
            'background:%s; color:white; font-size:12px; '
            'font-weight:bold; padding:3px 10px; border-radius:5px;' % color)

    def _update_mark_display(self, idx, result, error=None):
        row = self._mark_rows[idx]
        if result and result.success:
            row._res.setText('(%.2f, %.2f) mm' % (result.world_x, result.world_y))
            row._res.setStyleSheet(
                'background:#2e7d32; color:#fff; font-size:12px; '
                'padding:3px 10px; border-radius:5px;')
        elif error:
            short = error[:30]
            row._res.setText('✗ ' + short)
            row._res.setStyleSheet(
                'background:#b71c1c; color:#fff; font-size:12px; '
                'padding:3px 10px; border-radius:5px;')
        else:
            row._res.setText('—')
            row._res.setStyleSheet(
                'background:#383838; color:#666; font-size:12px; '
                'padding:3px 10px; border-radius:5px;')

    def _mark_row_highlight(self, idx, state):
        colours = {
            'idle':    '#444',
            'moving':  '#1565c0',
            'scanning':'#e65100',
            'ok':      '#1b5e20',
            'fail':    '#b71c1c',
        }
        row = self._mark_rows[idx]
        row._num.setStyleSheet(
            'background:%s; border-radius:18px; font-size:15px; '
            'font-weight:bold; color:white;' % colours.get(state, '#444'))

    def _reset_mark_displays(self):
        for i in range(4):
            self._mark_row_highlight(i, 'idle')
            self._update_mark_display(i, None)
        self._overall_bar.setValue(0)
        self._camera_label.setText('Camera feed will appear here during scan')
        self._camera_label.setPixmap(QPixmap())

    def refresh_badge(self):
        """Sync badge with corrector state (called when page becomes visible)."""
        if self._corrector.correction_active:
            c = self._corrector.correction
            self._update_badge('ARMED  RMS:%.2fmm' % c.residual_mm, '#4caf50')
        else:
            self._update_badge('OFF', '#444')