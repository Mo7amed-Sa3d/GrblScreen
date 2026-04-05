# pages/registration_page.py
#
# Industrial 4-point registration workflow
# =========================================
#
# Full sequence (runs in _RegistrationThread):
#
#   Step 0  ── Home machine: $H
#               Wait until all_commands_acknowledged() — up to 90 s
#
#   Step 1  ── Feed paper: M100 F8000 D<paper_length>
#               Wait until all_commands_acknowledged() — up to 180 s
#
#   Steps 2-5 (one per mark, repeated 4 times):
#     a. COARSE MOVE
#          target_x = design_x - CAM_OFFSET_X_MM   (clamp ≥ 0.5 mm)
#          target_y = design_y - CAM_OFFSET_Y_MM   (clamp ≥ 0.5 mm)
#          If already at target (< 0.1 mm away) → nudge +0.1 mm in X
#          G90  +  G0 X{target_x} Y{target_y}
#          Wait position ≤ 0.15 mm from target — timeout 30 s
#
#     b. AUTO-CENTERING LOOP  (up to 5 iterations)
#          For each iteration:
#            1. capture_frame()       → bgr, gray
#            2. find_dot_in_frame()   → dx_px, dy_px  (pixels from image centre)
#            3. Convert:
#                 dx_mm =  dx_px * MM_PER_PIXEL   (+X machine if dot is right)
#                 dy_mm = -dy_px * MM_PER_PIXEL   (+Y machine if dot is above)
#            4. error = hypot(dx_mm, dy_mm)
#            5. If error < 0.05 mm → converged, stop
#            6. Apply correction:
#                 G91  G0  X{dx_mm:.4f}  Y{dy_mm:.4f}  G90
#                 Wait for position to settle (position-tolerance, NOT GRBL state)
#
#     c. STORE WORLD POSITION
#          world_x = knife_x + CAM_OFFSET_X_MM
#          world_y = knife_y + CAM_OFFSET_Y_MM
#
#   After all 4 marks → compute affine correction → show "Apply & Cut" button
#
# APPLY & CUT (user presses button):
#   compute_affine_correction(design_pts, actual_pts)  → AffineCorrection
#   corrector.set_correction(corr)
#   G0 X{wx_mark1} Y{wy_mark1}    (move knife to actual mark 1)
#   G92 X0 Y0                     (job origin = centre of mark 1)
#   on_complete(True)
#
# Motion detection rules (GRBL state is never used for motion completion):
#   _wait_position(tx, ty, tol, timeout):
#       poll mpos every 50 ms; done when hypot(pos - target) < tol
#   _wait_settle(start_pos, timeout):
#       Phase 1: detect that position left start_pos  (movement began)
#       Phase 2: detect that drift < 0.005 mm / 50 ms (movement stopped)
#       Fall through after timeout — never blocks forever
#
# Thread safety:
#   ALL grbl.send() calls go through send_cmd signal → main thread slot
#   mpos and all_commands_acknowledged() read atomically under Python GIL

import math
import time

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QProgressBar,
)
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui  import QPixmap, QImage

import registration as reg


# ─────────────────────────────────────────────────────────────────────────────
# Registration thread
# ─────────────────────────────────────────────────────────────────────────────

class _RegistrationThread(QThread):
    """
    Executes the complete registration sequence off the Qt main thread.
    Serial commands are forwarded to the main thread via send_cmd signal.
    """

    # ── Signals ───────────────────────────────────────────────────────────────
    # serial commands → connect to corrector._grbl.send in main thread
    send_cmd    = pyqtSignal(str)

    # UI updates
    status_msg  = pyqtSignal(str, str)           # message, hex-colour
    step_update = pyqtSignal(int, str, str)      # step_idx(0-5), label, colour
    iter_update = pyqtSignal(int, int, float, float, float)
                                                 # mark_idx, iter, dx_mm, dy_mm, err
    frame_ready = pyqtSignal(bytes, int, int)    # jpeg_bytes, width, height
    prog_val    = pyqtSignal(int)                # 0-100

    done_ok     = pyqtSignal(list)   # [(wx,wy)×4] actual world positions
    done_fail   = pyqtSignal(str)    # error message

    # ── Tuning constants ──────────────────────────────────────────────────────
    CENTER_TOL_MM    = 0.05   # centering convergence threshold (mm)
    CENTER_MAX_ITER  = 5      # max centering iterations per mark
    COARSE_TOL_MM    = 0.15   # coarse move arrival tolerance (mm)
    SETTLE_MOVE_MIN  = 0.010  # min position change to count as "started moving"
    SETTLE_STABLE    = 0.005  # max drift per 50 ms to count as "settled"
    SETTLE_STABLE_N  = 3      # consecutive stable readings needed

    def __init__(self, corrector, design_pts, paper_length):
        super().__init__()
        self._corrector   = corrector
        self._design      = design_pts       # list of 4 (x, y) tuples
        self._paper_len   = float(paper_length) if paper_length else 300.0
        self._stop_flag   = False

    def stop(self):
        self._stop_flag = True

    # ── Entry ─────────────────────────────────────────────────────────────────

    def run(self):
        try:
            self._sequence()
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            self.done_fail.emit('Internal error: %s\n%s' % (exc, tb[:600]))

    # ── Full sequence ─────────────────────────────────────────────────────────

    def _sequence(self):

        # ── Step 0: Home ──────────────────────────────────────────────────────
        self._set_step(0, 'HOMING…', '#2196f3')
        self._status('Sending $H — homing machine…', '#aaa')
        self.prog_val.emit(2)

        self.send_cmd.emit('$H')
        time.sleep(0.5)   # give Qt event loop time to deliver the signal

        if not self._wait_queue_clear(timeout=90.0):
            self.done_fail.emit(
                'Homing timed out after 90 s.\n'
                'Check end-stops, wiring, and GRBL $H settings.')
            return

        self._set_step(0, 'HOMED ✓', '#4caf50')
        self.prog_val.emit(10)
        if self._stop_flag: return

        # ── Step 1: Paper feed ────────────────────────────────────────────────
        cmd = 'M100 F8000 D%.1f' % self._paper_len
        self._set_step(1, 'FEEDING…', '#2196f3')
        self._status('Feeding paper: %s' % cmd, '#aaa')

        self.send_cmd.emit(cmd)
        time.sleep(0.5)

        if not self._wait_queue_clear(timeout=180.0):
            self.done_fail.emit(
                'Paper feed timed out after 180 s.\n'
                'Check sensors, motors, and M100 firmware.')
            return

        self._set_step(1, 'FED ✓', '#4caf50')
        self.prog_val.emit(18)
        time.sleep(0.5)   # let paper come to rest
        if self._stop_flag: return

        # ── Steps 2-5: Scan each mark ─────────────────────────────────────────
        actual_pts = []

        for mark_idx in range(4):
            if self._stop_flag: return

            self._set_step(mark_idx + 2, 'MOVING…', '#2196f3')
            result = self._scan_one_mark(mark_idx)

            if result is None:
                return   # error already emitted inside _scan_one_mark

            wx, wy = result
            actual_pts.append((wx, wy))
            self._set_step(mark_idx + 2,
                           '(%.2f, %.2f) ✓' % (wx, wy),
                           '#4caf50')
            self.prog_val.emit(18 + (mark_idx + 1) * 19)   # 37 55 74 93 → ~100

        # ── Finished ──────────────────────────────────────────────────────────
        self.prog_val.emit(100)
        self._status('All 4 marks scanned.  Press Apply & Cut.', '#4caf50')
        self.done_ok.emit(actual_pts)

    # ── One mark: coarse move + centering loop ────────────────────────────────

    def _scan_one_mark(self, idx):
        """
        Returns (world_x, world_y) on success, None on failure.
        Emits done_fail on unrecoverable error.
        """
        design_x, design_y = self._design[idx]

        # ── Coarse move ───────────────────────────────────────────────────────
        # Position camera over nominal mark location.
        target_x = design_x - reg.CAM_OFFSET_X_MM
        target_y = design_y - reg.CAM_OFFSET_Y_MM

        # Safety clamp: keep both axes in positive machine space
        target_x = max(0.5, target_x)

        # If the knife is already within 0.1 mm of the target, add a tiny
        # nudge so GRBL actually executes a move (zero-distance moves are
        # silently ignored by GRBL-ESP32 and the position never updates).
        kx, ky = self._corrector.mpos[0], self._corrector.mpos[1]
        if math.hypot(kx - target_x, ky - target_y) < 0.1:
            target_x += 0.1

        self._status(
            'Mark %d: coarse move → (%.3f, %.3f) mm' % (idx+1, target_x, target_y),
            '#aaa')

        # Send via main-thread signal (QSerialPort is NOT thread-safe)
        self.send_cmd.emit('G90')
        self.send_cmd.emit('G0 X%.4f Y%.4f' % (target_x, target_y))
        time.sleep(0.25)   # let Qt deliver the queued signals

        ok = self._wait_position(target_x, target_y,
                                 tol=self.COARSE_TOL_MM, timeout=30.0)
        if not ok:
            self._status(
                'Mark %d: coarse move timeout — proceeding with centering' % (idx+1),
                '#ff9800')
        else:
            self._status(
                'Mark %d: arrived at (%.3f, %.3f). Centering…' % (
                    idx+1, self._corrector.mpos[0], self._corrector.mpos[1]),
                '#aaa')

        # ── Auto-centering loop ───────────────────────────────────────────────
        return self._center_loop(idx)

    def _center_loop(self, idx):
        """
        Iterative sub-mm centering.  Returns (world_x, world_y) or None.

        Sign convention (consistent with registration.scan_dot):
            dx_px > 0  ⟹  dot is RIGHT of image centre
                       ⟹  knife must move RIGHT (+X)
                       ⟹  dx_mm = +dx_px × MM_PER_PIXEL
            dy_px > 0  ⟹  dot is BELOW image centre (image Y axis is down)
                       ⟹  knife must move DOWN (−Y in machine coordinates)
                       ⟹  dy_mm = −dy_px × MM_PER_PIXEL
        Correction command:  G91 G0 X{dx_mm} Y{dy_mm} G90
        """
        last_error = None

        for iteration in range(self.CENTER_MAX_ITER):
            if self._stop_flag:
                return None

            self._set_step(idx + 2,
                           'SCAN %d/%d' % (iteration+1, self.CENTER_MAX_ITER),
                           '#e65100')

            # ── Capture ───────────────────────────────────────────────────────
            bgr, gray, cap_err = reg.capture_frame()
            if gray is None:
                self.done_fail.emit(
                    'Mark %d, iter %d: camera error: %s'
                    % (idx+1, iteration+1, cap_err or 'unknown'))
                return None

            # ── Detect dot ────────────────────────────────────────────────────
            dx_px, dy_px, annotated, det_err = reg.find_dot_in_frame(gray, bgr=bgr)

            # Always show the latest frame (success or failure annotation)
            if annotated is not None:
                self._emit_frame(annotated)

            if det_err:
                self.done_fail.emit(
                    'Mark %d, iter %d: %s' % (idx+1, iteration+1, det_err))
                return None

            # ── Convert pixel offset → machine mm ─────────────────────────────
            dx_mm   =  dx_px * reg.MM_PER_PIXEL   # positive = move knife right
            dy_mm   = -dy_px * reg.MM_PER_PIXEL   # positive = move knife up (+Y)
            error   = math.hypot(dx_mm, dy_mm)
            last_error = error

            self.iter_update.emit(idx, iteration+1, dx_mm, -dy_mm, error)
            self._status(
                'Mark %d  iter %d/%d  err=%.4f mm  Δx=%.4f  Δy=%.4f' % (
                    idx+1, iteration+1, self.CENTER_MAX_ITER,
                    error, dx_mm, dy_mm),
                '#4caf50' if error <= self.CENTER_TOL_MM else '#ffb74d')

            # ── Convergence check ─────────────────────────────────────────────
            if error <= self.CENTER_TOL_MM:
                self._status(
                    'Mark %d converged in %d iters (err=%.4f mm)' % (
                        idx+1, iteration+1, error),
                    '#4caf50')
                break

            # ── Correction move ───────────────────────────────────────────────
            # Sub-noise suppression: skip axis corrections below 0.002 mm
            # (smaller than GRBL step resolution at typical steps/mm)
            if abs(dx_mm) < 0.002: dx_mm = 0.0
            if abs(dy_mm) < 0.002: dy_mm = 0.0
            if dx_mm == 0.0 and dy_mm == 0.0:
                break   # numerically zero — no point moving

            start_pos = self._corrector.mpos[:2]

            self.send_cmd.emit('G91')
            self.send_cmd.emit('G0 X%.4f Y%.4f' % (dx_mm, dy_mm))
            self.send_cmd.emit('G90')
            time.sleep(0.20)   # let Qt deliver queued signals before polling

            self._wait_settle(start_pos, timeout=8.0)
            time.sleep(0.05)   # brief mechanical settle

        # ── Compute final world position ──────────────────────────────────────
        # Camera is now centred on dot (within tolerance).
        # Dot position in machine coordinates:
        #   world = knife_position + camera_offset_from_knife
        kx, ky  = self._corrector.mpos[0], self._corrector.mpos[1]
        world_x = kx + reg.CAM_OFFSET_X_MM
        world_y = ky + reg.CAM_OFFSET_Y_MM

        self._status(
            'Mark %d stored: knife=(%.3f, %.3f)  world=(%.3f, %.3f)  '
            'final_err=%.4f mm' % (idx+1, kx, ky, world_x, world_y,
                                   last_error if last_error is not None else 0.0),
            '#4caf50')

        return world_x, world_y

    # ── Motion helpers (position-based, never GRBL state) ─────────────────────

    def _wait_queue_clear(self, timeout=60.0):
        """
        Block until GrblConnection has both:
          – written every command to serial  (_cmd_q empty)
          – received 'ok' for every command  (_in_flight == 0)

        Used for blocking firmware commands ($H, M100) where the firmware
        only sends 'ok' after the entire operation completes.
        """
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self._stop_flag:
                return False
            if self._corrector.all_commands_acknowledged():
                return True
            time.sleep(0.1)
        return False

    def _wait_position(self, tx, ty, tol=0.15, timeout=30.0):
        """
        Poll mpos every 50 ms until within tol mm of (tx, ty).
        Returns True if arrived, False on timeout.
        Does NOT read GRBL state.
        """
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self._stop_flag:
                return False
            mx, my = self._corrector.mpos[0], self._corrector.mpos[1]
            if math.hypot(mx - tx, my - ty) < tol:
                return True
            time.sleep(0.05)
        return False

    def _wait_settle(self, start_pos, timeout=8.0):
        """
        Wait for a small correction move to complete.

        Phase 1 — detect that the machine LEFT start_pos (move has begun).
                   Handles fast sub-mm moves: waits up to 1.5 s or position
                   changes by > SETTLE_MOVE_MIN.
                   If position never changes: move was zero-distance or
                   GRBL-rejected → return immediately (already at target).

        Phase 2 — wait for position to STOP CHANGING.
                   Needs SETTLE_STABLE_N consecutive readings with drift
                   < SETTLE_STABLE mm per 50 ms interval.

        Never blocks longer than timeout.
        Does NOT read GRBL state.
        """
        sx, sy = start_pos
        t0     = time.time()

        # Phase 1
        moved = False
        deadline1 = t0 + min(timeout, 1.5)
        while time.time() < deadline1:
            if self._stop_flag:
                return False
            mx, my = self._corrector.mpos[0], self._corrector.mpos[1]
            if math.hypot(mx - sx, my - sy) > self.SETTLE_MOVE_MIN:
                moved = True
                break
            time.sleep(0.05)

        if not moved:
            # Sub-resolution move or zero-distance: nothing to wait for
            return True

        # Phase 2
        prev      = self._corrector.mpos[:2]
        stable_n  = 0
        time.sleep(0.05)

        while time.time() - t0 < timeout:
            if self._stop_flag:
                return False
            cur   = self._corrector.mpos[:2]
            drift = math.hypot(cur[0] - prev[0], cur[1] - prev[1])
            if drift < self.SETTLE_STABLE:
                stable_n += 1
                if stable_n >= self.SETTLE_STABLE_N:
                    return True
            else:
                stable_n = 0
            prev = cur
            time.sleep(0.05)

        return True   # timeout — proceed anyway

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _status(self, text, colour='#aaa'):
        self.status_msg.emit(text, colour)

    def _set_step(self, idx, label, colour):
        self.step_update.emit(idx, label, colour)

    def _emit_frame(self, bgr_frame):
        """Encode OpenCV BGR frame as JPEG and emit (safe across thread boundary)."""
        try:
            import cv2
            ok, buf = cv2.imencode('.jpg', bgr_frame,
                                   [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                h, w = bgr_frame.shape[:2]
                self.frame_ready.emit(bytes(buf), w, h)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# RegistrationPage — Qt widget
# ─────────────────────────────────────────────────────────────────────────────

# Step labels (6 steps total: Home, Feed, Mark 1-4)
_STEPS = ['Home', 'Feed Paper', 'Mark 1', 'Mark 2', 'Mark 3', 'Mark 4']


class RegistrationPage(QWidget):
    """
    Full-screen registration workflow page.

    Parameters
    ----------
    corrector    : TiltCorrector  (wraps GrblConnection)
    design_pts   : list[tuple]    4 × (x, y) from ;RegMarks comment
    paper_length : float          paper length in mm from G-code line 1
    on_complete  : callable(bool) called when Apply is pressed or skipped
    on_back      : callable()     called when Skip / Cancel is pressed
    """

    def __init__(self, corrector, design_pts, paper_length,
                 on_complete, on_back, parent=None):
        super().__init__(parent)
        self._corrector    = corrector
        self._design       = design_pts
        self._paper_length = float(paper_length) if paper_length else 300.0
        self._on_complete  = on_complete
        self._on_back      = on_back

        self._thread  = None
        self._actual  = []   # [(wx,wy)×4] filled by done_ok slot

        self._build()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(6)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        self._btn_back = QPushButton('✕  Skip / Cancel')
        self._btn_back.setProperty('role', 'back')
        self._btn_back.setMinimumHeight(46)
        self._btn_back.clicked.connect(self._skip)
        hdr.addWidget(self._btn_back)

        title = QLabel('Registration Marks')
        title.setStyleSheet('font-size:16px; font-weight:bold; color:#ff8c00;')
        hdr.addWidget(title, 1)

        self._badge = QLabel('WAITING')
        self._badge.setStyleSheet(
            'background:#444; color:#aaa; font-size:11px; '
            'font-weight:bold; padding:3px 8px; border-radius:5px;')
        hdr.addWidget(self._badge)
        root.addLayout(hdr)

        # Info strip
        info = QLabel(
            'Paper: %.0f mm   ·   Marks: %d   ·   Tol: %.2f mm' % (
                self._paper_length, len(self._design),
                _RegistrationThread.CENTER_TOL_MM))
        info.setStyleSheet('color:#666; font-size:11px; padding:0 2px;')
        root.addWidget(info)

        # Progress bar
        self._prog = QProgressBar()
        self._prog.setRange(0, 100)
        self._prog.setValue(0)
        self._prog.setMaximumHeight(9)
        root.addWidget(self._prog)

        div = QFrame(); div.setFrameShape(QFrame.HLine); root.addWidget(div)

        # ── Step rows ─────────────────────────────────────────────────────────
        self._step_rows = []
        for i, label in enumerate(_STEPS):
            row = self._mk_step_row(i, label)
            root.addWidget(row)
            self._step_rows.append(row)

        div2 = QFrame(); div2.setFrameShape(QFrame.HLine); root.addWidget(div2)

        # ── Camera preview ────────────────────────────────────────────────────
        self._cam = QLabel()
        self._cam.setAlignment(Qt.AlignCenter)
        self._cam.setMinimumHeight(175)
        self._cam.setStyleSheet(
            'background:#111; border:1px solid #333; '
            'border-radius:6px; color:#555;')
        self._cam.setText('Camera preview appears here during scanning')
        root.addWidget(self._cam, 1)

        # ── Status / iteration detail ─────────────────────────────────────────
        self._msg = QLabel('Press ▶ Start Scan to begin.')
        self._msg.setAlignment(Qt.AlignCenter)
        self._msg.setWordWrap(True)
        self._msg.setStyleSheet('font-size:11px; color:#aaa;')
        self._msg.setMaximumHeight(52)
        root.addWidget(self._msg)

        # ── Buttons ───────────────────────────────────────────────────────────
        act = QHBoxLayout(); act.setSpacing(8)

        self._btn_start = QPushButton('▶  Start Scan')
        self._btn_start.setProperty('role', 'accent')
        self._btn_start.setMinimumHeight(54)
        self._btn_start.clicked.connect(self._start)
        act.addWidget(self._btn_start)

        self._btn_apply = QPushButton('✓  Apply && Cut')
        self._btn_apply.setProperty('role', 'success')
        self._btn_apply.setMinimumHeight(54)
        self._btn_apply.setEnabled(False)
        self._btn_apply.clicked.connect(self._apply)
        act.addWidget(self._btn_apply)

        root.addLayout(act)

    def _mk_step_row(self, idx, label):
        row = QWidget()
        row.setStyleSheet('background:#2a2a2a; border-radius:6px;')
        rl  = QHBoxLayout(row)
        rl.setContentsMargins(10, 4, 10, 4)
        rl.setSpacing(8)

        num = QLabel('' if idx < 2 else str(idx - 1))
        num.setFixedWidth(18)
        num.setAlignment(Qt.AlignCenter)
        num.setStyleSheet('color:#555; font-size:11px;')

        lbl = QLabel(label)
        lbl.setStyleSheet('font-size:13px; color:#888;')

        st = QLabel('PENDING')
        st.setMinimumWidth(115)
        st.setAlignment(Qt.AlignCenter)
        st.setStyleSheet(
            'background:#333; color:#555; font-size:11px; '
            'padding:2px 8px; border-radius:4px;')

        rl.addWidget(num)
        rl.addWidget(lbl, 1)
        rl.addWidget(st)

        row._st = st
        return row

    # ── Start ─────────────────────────────────────────────────────────────────

    def _start(self):
        if not self._corrector.is_connected():
            self._show_msg('Machine not connected.', '#f44336')
            return

        self._btn_start.setEnabled(False)
        self._btn_apply.setEnabled(False)
        self._btn_back.setEnabled(False)
        self._actual = []

        for row in self._step_rows:
            self._set_row(row, 'PENDING', '#555', '#333')
        self._prog.setValue(0)
        self._cam.clear()
        self._cam.setText('Starting…')
        self._update_badge('RUNNING', '#ff8c00')

        self._thread = _RegistrationThread(
            corrector    = self._corrector,
            design_pts   = self._design,
            paper_length = self._paper_length,
        )

        # Route all serial commands through the main thread (QSerialPort is not thread-safe)
        self._thread.send_cmd.connect(self._corrector._grbl.send)

        self._thread.status_msg.connect(self._on_status)
        self._thread.step_update.connect(self._on_step)
        self._thread.iter_update.connect(self._on_iter)
        self._thread.frame_ready.connect(self._on_frame)
        self._thread.prog_val.connect(self._prog.setValue)
        self._thread.done_ok.connect(self._on_done_ok)
        self._thread.done_fail.connect(self._on_done_fail)

        self._thread.start()

    # ── Apply & Cut ───────────────────────────────────────────────────────────

    def _apply(self):
        """
        1. Compute 6-DOF affine correction from design vs actual positions.
        2. Arm the TiltCorrector.
        3. Move knife to actual position of mark 1.
        4. G92 X0 Y0 — job origin = centre of mark 1.
        5. Call on_complete(True).
        """
        if len(self._actual) < 4:
            self._show_msg('Scan not complete — need all 4 marks.', '#f44336')
            return

        self._btn_apply.setEnabled(False)
        self._update_badge('COMPUTING', '#9c27b0')

        corr, warn = reg.compute_affine_correction(self._design, self._actual)

        if corr is None:
            self._show_msg('Affine computation failed: %s' % warn, '#f44336')
            self._update_badge('FAILED', '#f44336')
            self._btn_apply.setEnabled(True)
            return

        # Arm the corrector — all future G0/G1 coordinates will be transformed
        self._corrector.set_correction(corr)

        # Move knife to actual mark 1 world position (bypass corrector — raw coords)
        wx1, wy1 = self._actual[0]
        self._corrector._grbl.send('G0 X%.4f Y%.4f' % (wx1, wy1))

        # Set job origin: centre of mark 1 = (0, 0)
        self._corrector._grbl.send('G92 X0 Y0')

        rms_str = '%.3f mm' % corr.residual_mm
        self._update_badge('ARMED  RMS ' + rms_str, '#4caf50')

        summary = corr.summary()
        if warn:
            summary += '  ⚠ ' + warn
        self._show_msg(summary, '#4caf50')

        # Small delay so GRBL processes the G92 before the cutting starts
        QTimer.singleShot(700, lambda: self._on_complete(True))

    def _skip(self):
        """Skip registration — proceed without correction."""
        if self._thread and self._thread.isRunning():
            self._thread.stop()
        self._on_back()

    # ── Thread signal slots ───────────────────────────────────────────────────

    @pyqtSlot(str, str)
    def _on_status(self, text, colour):
        self._show_msg(text, colour)

    @pyqtSlot(int, str, str)
    def _on_step(self, idx, label, colour):
        if 0 <= idx < len(self._step_rows):
            bg = ('#2e7d32' if '✓' in label else
                  '#7f0000' if '✗' in label else
                  '#1565c0' if any(c in label for c in
                                   ('…', 'SCAN', 'FEED', 'HOM', 'MOV')) else
                  '#333')
            self._set_row(self._step_rows[idx], label, '#fff', bg)

    @pyqtSlot(int, int, float, float, float)
    def _on_iter(self, mark_idx, iteration, dx_mm, dy_mm, error):
        """Update the mark's step row with centering iteration metrics."""
        step_idx = mark_idx + 2
        if 0 <= step_idx < len(self._step_rows):
            label = 'i%d  err=%.3f' % (iteration, error)
            colour = '#4caf50' if error <= _RegistrationThread.CENTER_TOL_MM else '#ff8c00'
            self._set_row(self._step_rows[step_idx], label, '#fff', '#1565c0')

    @pyqtSlot(bytes, int, int)
    def _on_frame(self, jpeg_bytes, w, h):
        """Decode JPEG bytes and display in camera label."""
        try:
            q_img = QImage.fromData(jpeg_bytes, 'JPEG')
            if not q_img.isNull():
                lw = self._cam.width()  or w
                lh = self._cam.height() or h
                pix = QPixmap.fromImage(q_img).scaled(
                    lw - 6, lh - 6,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._cam.setPixmap(pix)
        except Exception:
            pass

    @pyqtSlot(list)
    def _on_done_ok(self, actual_pts):
        self._actual = actual_pts
        self._update_badge('READY TO APPLY', '#ff8c00')
        self._show_msg(
            'All 4 marks found.  Review positions, then press Apply && Cut.',
            '#ff8c00')
        self._btn_apply.setEnabled(True)
        self._btn_back.setEnabled(True)

    @pyqtSlot(str)
    def _on_done_fail(self, msg):
        self._update_badge('FAILED', '#f44336')
        self._show_msg('FAILED: ' + msg, '#f44336')
        self._btn_start.setEnabled(True)
        self._btn_back.setEnabled(True)

    # ── Display helpers ───────────────────────────────────────────────────────

    def _show_msg(self, text, colour='#aaa'):
        self._msg.setText(text)
        self._msg.setStyleSheet('font-size:11px; color:%s;' % colour)

    def _update_badge(self, text, colour='#444'):
        self._badge.setText(text)
        self._badge.setStyleSheet(
            'background:%s; color:white; font-size:11px; '
            'font-weight:bold; padding:3px 8px; border-radius:5px;' % colour)

    def _set_row(self, row, text, fg, bg):
        row._st.setText(text)
        row._st.setStyleSheet(
            'background:%s; color:%s; font-size:11px; '
            'padding:2px 8px; border-radius:4px;' % (bg, fg))

    def refresh_badge(self):
        """Sync badge when page becomes visible."""
        if self._corrector.correction_active:
            c = self._corrector.correction
            self._update_badge('ARMED  RMS %.3f mm' % c.residual_mm, '#4caf50')
        else:
            self._update_badge('WAITING', '#444')