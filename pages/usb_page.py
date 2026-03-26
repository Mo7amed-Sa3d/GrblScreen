# pages/usb_page.py

import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem,
    QFrame, QSpinBox
)
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal, pyqtSlot

GCODE_EXTS = {'.nc', '.gcode', '.gc', '.ngc', '.cnc', '.tap'}
USB_MOUNTS = ['/media', '/mnt', '/run/media']


def _find_usb_roots():
    roots = []
    for base in USB_MOUNTS:
        if not os.path.isdir(base):
            continue
        for entry in os.scandir(base):
            if entry.is_dir():
                try:
                    next(os.scandir(entry.path))
                    roots.append(entry.path)
                except (StopIteration, PermissionError):
                    pass
    return roots


class _FileLoaderThread(QThread):
    send_line = pyqtSignal(str)
    progress  = pyqtSignal(int, int)
    done      = pyqtSignal()
    error     = pyqtSignal(str)

    def __init__(self, filepath):
        super().__init__()
        self._path = filepath
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            with open(self._path, 'r', errors='replace') as f:
                lines = [l.strip() for l in f
                         if l.strip() and not l.strip().startswith(';')]
            total = len(lines)
            for i, line in enumerate(lines):
                if self._stop:
                    break
                self.send_line.emit(line)
                self.progress.emit(i + 1, total)
                self.msleep(1)
            # ── Bug fix: only emit done when NOT manually stopped ──
            # Without this check, done fires even after stop(), which
            # re-triggers _on_file_streamed and restarts the idle timer,
            # causing the repeat loop to continue after the user pressed Stop.
            if not self._stop:
                self.done.emit()
        except Exception as e:
            self.error.emit(str(e))


class UsbPage(QWidget):
    # Emitted to request registration before a run.
    # Main window shows RegistrationPage, then calls on_registration_complete().
    request_registration = pyqtSignal(list)   # list of 4 (x,y) design tuples

    def __init__(self, grbl, on_back, parent=None):
        super().__init__(parent)
        self._grbl          = grbl
        self._on_back       = on_back
        self._selected_path = None
        self._design_pts    = None
        self._send_thread   = None
        self._current_repeat = 0
        self._total_repeats  = 1

        # ── Hard stop flag ────────────────────────────────────────────────────
        # Set True in _stop_all(); checked in every async continuation
        # (_on_file_streamed, _check_idle_for_next_repeat) so no further
        # repeat steps execute after the user presses Stop or Cancel.
        self._stopped = False

        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(500)
        self._idle_timer.timeout.connect(self._check_idle_for_next_repeat)

        self._build()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        btn_back = QPushButton('◀  Back')
        btn_back.setProperty('role', 'back')
        btn_back.setMinimumHeight(48); btn_back.setMaximumWidth(120)
        btn_back.clicked.connect(self._on_back)
        hdr.addWidget(btn_back)

        self._path_lbl = QLabel('USB Drive')
        self._path_lbl.setStyleSheet(
            'font-size:14px; color:#ff8c00; font-weight:bold;')
        hdr.addWidget(self._path_lbl, 1)

        btn_ref = QPushButton('⟳')
        btn_ref.setMaximumWidth(52); btn_ref.setMinimumHeight(48)
        btn_ref.clicked.connect(self._refresh)
        hdr.addWidget(btn_ref)
        root.addLayout(hdr)

        div = QFrame(); div.setFrameShape(QFrame.HLine); root.addWidget(div)

        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_click)
        self._list.itemDoubleClicked.connect(self._on_double)
        root.addWidget(self._list, 1)

        sel_row = QHBoxLayout()
        self._sel_lbl = QLabel('No file selected')
        self._sel_lbl.setStyleSheet('color:#aaa; font-size:13px;')
        sel_row.addWidget(self._sel_lbl, 1)
        root.addLayout(sel_row)

        run_row = QHBoxLayout()
        run_row.setSpacing(10)
        run_row.addWidget(QLabel('Repeat:'))

        self._repeat_spin = QSpinBox()
        self._repeat_spin.setRange(1, 999)
        self._repeat_spin.setValue(1)
        self._repeat_spin.setMinimumHeight(48)
        self._repeat_spin.setMinimumWidth(90)
        self._repeat_spin.setStyleSheet(
            'font-size:16px; font-weight:bold; color:#ff8c00;')
        run_row.addWidget(self._repeat_spin)

        lbl = QLabel('time(s)')
        lbl.setStyleSheet('color:#aaa; font-size:13px;')
        run_row.addWidget(lbl)
        run_row.addStretch()

        self._regmarks_badge = QLabel('')
        self._regmarks_badge.setStyleSheet(
            'font-size:12px; color:#aaa; padding:3px 8px;')
        run_row.addWidget(self._regmarks_badge)

        self._btn_run = QPushButton('▶  Run')
        self._btn_run.setProperty('role', 'success')
        self._btn_run.setMinimumHeight(52); self._btn_run.setMinimumWidth(100)
        self._btn_run.setEnabled(False)
        self._btn_run.clicked.connect(self._on_run_pressed)
        run_row.addWidget(self._btn_run)

        self._btn_stop = QPushButton('✕  Stop')
        self._btn_stop.setProperty('role', 'danger')
        self._btn_stop.setMinimumHeight(52); self._btn_stop.setMinimumWidth(100)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_all)
        run_row.addWidget(self._btn_stop)
        root.addLayout(run_row)

        self._prog_lbl = QLabel('')
        self._prog_lbl.setAlignment(Qt.AlignCenter)
        self._prog_lbl.setStyleSheet('color:#aaa; font-size:13px;')
        root.addWidget(self._prog_lbl)

        self._refresh()

    # ── Directory browsing ────────────────────────────────────────────────────

    def _refresh(self):
        self._list.clear()
        self._sel_lbl.setText('No file selected')
        self._btn_run.setEnabled(False)
        self._selected_path = None
        self._regmarks_badge.setText('')

        roots = _find_usb_roots()
        if not roots:
            self._list.addItem(
                '⚠  No USB drive found — plug in drive and press ⟳')
            self._path_lbl.setText('No USB drive')
            return

        self._path_lbl.setText(roots[0])
        self._list_dir(roots[0])

    def _list_dir(self, path):
        self._list.clear()
        try:
            entries = sorted(os.scandir(path),
                             key=lambda e: (not e.is_dir(), e.name.lower()))
            for e in entries:
                if e.name.startswith('.'):
                    continue
                if e.is_dir():
                    item = QListWidgetItem('📁  ' + e.name)
                    item.setData(Qt.UserRole, ('dir', e.path))
                    self._list.addItem(item)
                elif os.path.splitext(e.name)[1].lower() in GCODE_EXTS:
                    sz = e.stat().st_size
                    s  = ('%d KB' % (sz // 1024)) if sz > 1024 else ('%d B' % sz)
                    item = QListWidgetItem('📄  %s   (%s)' % (e.name, s))
                    item.setData(Qt.UserRole, ('file', e.path))
                    self._list.addItem(item)
        except PermissionError:
            self._list.addItem('⚠  Permission denied')

    def _on_click(self, item):
        d = item.data(Qt.UserRole)
        if d and d[0] == 'file':
            self._select_file(d[1])

    def _on_double(self, item):
        d = item.data(Qt.UserRole)
        if not d:
            return
        if d[0] == 'dir':
            self._list_dir(d[1])
        elif d[0] == 'file':
            self._select_file(d[1])
            self._on_run_pressed()

    def _select_file(self, path):
        self._selected_path = path
        self._sel_lbl.setText(os.path.basename(path))
        self._sel_lbl.setStyleSheet(
            'color:#ff8c00; font-weight:bold; font-size:13px;')
        self._btn_run.setEnabled(True)

        from registration import parse_regmarks
        pts = parse_regmarks(path)
        if pts:
            self._design_pts = pts
            self._regmarks_badge.setText('◎ RegMarks — aligns before each run')
            self._regmarks_badge.setStyleSheet(
                'font-size:12px; color:#ff8c00; font-weight:bold; padding:3px 8px;')
        else:
            self._design_pts = None
            self._regmarks_badge.setText('')

    # ── Run logic ─────────────────────────────────────────────────────────────

    def _on_run_pressed(self):
        if not self._selected_path:
            return
        if self._send_thread and self._send_thread.isRunning():
            return

        self._stopped        = False
        self._total_repeats  = self._repeat_spin.value()
        self._current_repeat = 0

        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)

        # Every run (including first) goes through _begin_repeat()
        # which handles optional registration before each run.
        self._begin_repeat()

    def _begin_repeat(self):
        """
        Start one repeat: do registration first (if RegMarks exist),
        then start the file send.
        Registration is done before EVERY repeat so alignment is fresh each time.
        """
        if self._stopped:
            return
        n = self._current_repeat + 1
        t = self._total_repeats
        self._prog_lbl.setText(
            'Run %d / %d — aligning…' % (n, t) if self._design_pts
            else 'Run %d / %d — starting…' % (n, t)
        )

        if self._design_pts:
            # Emit signal → main window builds & shows RegistrationPage
            self.request_registration.emit(self._design_pts)
            # _start_send() is called from on_registration_complete()
        else:
            self._start_send()

    def on_registration_complete(self, success):
        """
        Called by main window after each RegistrationPage finishes
        (success=True) or is skipped (success=False).
        Either way, proceed with the file send for this repeat.
        """
        if self._stopped:
            return
        self._start_send()

    def _start_send(self):
        if self._stopped:
            return
        n = self._current_repeat + 1
        t = self._total_repeats
        self._prog_lbl.setText(
            'Run %d / %d — sending…' % (n, t) if t > 1 else 'Sending…')

        # Disconnect previous thread's signals to prevent double-firing
        # when a new thread is created for each repeat.
        if self._send_thread is not None:
            try:
                self._send_thread.send_line.disconnect()
                self._send_thread.progress.disconnect()
                self._send_thread.done.disconnect()
                self._send_thread.error.disconnect()
            except Exception:
                pass

        self._send_thread = _FileLoaderThread(self._selected_path)
        self._send_thread.send_line.connect(self._grbl.send)
        self._send_thread.progress.connect(self._on_progress)
        self._send_thread.done.connect(self._on_file_streamed)
        self._send_thread.error.connect(self._on_error)
        self._send_thread.start()

    # ── Progress / completion ─────────────────────────────────────────────────

    @pyqtSlot(int, int)
    def _on_progress(self, sent, total):
        if self._stopped:
            return
        n   = self._current_repeat + 1
        t   = self._total_repeats
        pct = int(sent / total * 100) if total else 0
        if t > 1:
            self._prog_lbl.setText(
                'Run %d/%d — %d/%d lines (%d%%)' % (n, t, sent, total, pct))
        else:
            self._prog_lbl.setText('%d/%d lines (%d%%)' % (sent, total, pct))

    @pyqtSlot()
    def _on_file_streamed(self):
        """
        All lines queued. Machine is still cutting.
        Poll for Idle, then either start next repeat or finish.
        Guard: if _stopped, do nothing.
        """
        if self._stopped:
            return
        n = self._current_repeat + 1
        t = self._total_repeats
        if t > 1:
            self._prog_lbl.setText(
                'Run %d/%d queued ✓ — waiting for machine…' % (n, t))
        else:
            self._prog_lbl.setText('File queued ✓ — machine is cutting')

        # Always poll — whether more repeats remain or not (to update UI)
        self._idle_timer.start()

    def _check_idle_for_next_repeat(self):
        """Poll GRBL Idle. When machine finishes, start next repeat or finish."""
        # Hard stop check — belt-and-braces guard
        if self._stopped:
            self._idle_timer.stop()
            return

        if self._grbl.state != 'Idle':
            return   # still running, keep polling

        self._idle_timer.stop()
        self._current_repeat += 1

        if self._current_repeat >= self._total_repeats:
            # All repeats done
            t = self._total_repeats
            self._prog_lbl.setText(
                'All %d run%s complete ✓' % (t, 's' if t > 1 else ''))
            self._btn_run.setEnabled(True)
            self._btn_stop.setEnabled(False)
            self._current_repeat = 0
        else:
            # More repeats — go back through alignment + send
            self._begin_repeat()

    # ── Stop ─────────────────────────────────────────────────────────────────

    def _stop_all(self):
        """
        Immediately stop everything. The _stopped flag blocks every
        async continuation so no further repeats can be triggered.
        """
        self._stopped = True          # ← blocks _on_file_streamed + timer
        self._idle_timer.stop()

        if self._send_thread is not None:
            self._send_thread.stop()  # sets _stop flag; thread won't emit done

        self._grbl.reset()            # Ctrl-X: clears GRBL queue
        self._grbl.send('M5')         # knife up

        self._current_repeat = 0
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._prog_lbl.setText('Stopped.')

    @pyqtSlot(str)
    def _on_error(self, msg):
        if self._stopped:
            return
        self._idle_timer.stop()
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._prog_lbl.setText('Error: ' + msg)