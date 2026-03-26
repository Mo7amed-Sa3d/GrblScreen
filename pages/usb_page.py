# pages/usb_page.py
# USB G-code file browser with:
#   • Repeat count (run same file N times)
#   • Automatic ;RegMarks detection → triggers registration before first run
#   • Wait for GRBL Idle between repeats before starting next run
#   • File lines emitted as signals to main thread (QSerialPort safety)

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
    """
    Reads G-code file from disk, emits each line as a signal.
    Serial writes happen in the main thread via the connected slot.
    """
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
                self.msleep(1)   # yield to Qt's signal dispatcher
            self.done.emit()
        except Exception as e:
            self.error.emit(str(e))


class UsbPage(QWidget):
    # Emitted when a ;RegMarks file is selected and Run is pressed.
    # Main window intercepts this to show registration page.
    request_registration = pyqtSignal(list)   # list of 4 (x,y) design tuples

    def __init__(self, grbl, on_back, parent=None):
        super().__init__(parent)
        self._grbl           = grbl
        self._on_back        = on_back
        self._selected_path  = None
        self._send_thread    = None
        self._current_repeat = 0
        self._total_repeats  = 1
        self._registered     = False   # True after registration completed

        # Timer: polls GRBL Idle between repeats
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(500)
        self._idle_timer.timeout.connect(self._check_idle_for_next_repeat)

        self._build()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        btn_back = QPushButton('◀  Back')
        btn_back.setProperty('role', 'back')
        btn_back.setMinimumHeight(48); btn_back.setMaximumWidth(120)
        btn_back.clicked.connect(self._on_back)
        hdr.addWidget(btn_back)

        self._path_lbl = QLabel('USB Drive')
        self._path_lbl.setStyleSheet('font-size:14px; color:#ff8c00; font-weight:bold;')
        hdr.addWidget(self._path_lbl, 1)

        btn_ref = QPushButton('⟳')
        btn_ref.setMaximumWidth(52); btn_ref.setMinimumHeight(48)
        btn_ref.clicked.connect(self._refresh)
        hdr.addWidget(btn_ref)
        root.addLayout(hdr)

        div = QFrame(); div.setFrameShape(QFrame.HLine); root.addWidget(div)

        # File list
        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_click)
        self._list.itemDoubleClicked.connect(self._on_double)
        root.addWidget(self._list, 1)

        # Selected file row
        sel_row = QHBoxLayout()
        self._sel_lbl = QLabel('No file selected')
        self._sel_lbl.setStyleSheet('color:#aaa; font-size:13px;')
        sel_row.addWidget(self._sel_lbl, 1)
        root.addLayout(sel_row)

        # Repeat count + run/stop row
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

        self._repeat_lbl = QLabel('time(s)')
        self._repeat_lbl.setStyleSheet('color:#aaa; font-size:13px;')
        run_row.addWidget(self._repeat_lbl)

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

        # Progress label
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
            self._list.addItem('⚠  No USB drive found — plug in drive and press ⟳')
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
        if not d: return
        if d[0] == 'dir':
            self._list_dir(d[1])
        elif d[0] == 'file':
            self._select_file(d[1])
            self._on_run_pressed()

    def _select_file(self, path):
        self._selected_path = path
        self._registered    = False   # new file = need re-registration

        self._sel_lbl.setText(os.path.basename(path))
        self._sel_lbl.setStyleSheet('color:#ff8c00; font-weight:bold; font-size:13px;')
        self._btn_run.setEnabled(True)

        # Check for ;RegMarks comment
        from registration import parse_regmarks
        pts = parse_regmarks(path)
        if pts:
            self._regmarks_badge.setText('◎ RegMarks found')
            self._regmarks_badge.setStyleSheet(
                'font-size:12px; color:#ff8c00; font-weight:bold; padding:3px 8px;')
            self._design_pts = pts
        else:
            self._regmarks_badge.setText('')
            self._design_pts = None

    # ── Run logic ─────────────────────────────────────────────────────────────

    def _on_run_pressed(self):
        if not self._selected_path: return
        if self._send_thread and self._send_thread.isRunning(): return

        self._total_repeats  = self._repeat_spin.value()
        self._current_repeat = 0

        # If file has RegMarks and we haven't registered this session:
        if self._design_pts and not self._registered:
            self.request_registration.emit(self._design_pts)
            # Actual file start is triggered by on_registration_complete()
            return

        # No RegMarks or already registered — start directly
        self._start_first_run()

    def on_registration_complete(self, success):
        """Called by main window after registration page finishes."""
        if success:
            self._registered = True
        # Start the file regardless (user can skip registration)
        self._start_first_run()

    def _start_first_run(self):
        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._start_send()

    def _start_send(self):
        """Start streaming the file for the current repeat."""
        n     = self._current_repeat + 1
        total = self._total_repeats
        self._prog_lbl.setText(
            'Run %d / %d — sending…' % (n, total)
            if total > 1 else 'Sending…'
        )

        self._send_thread = _FileLoaderThread(self._selected_path)
        self._send_thread.send_line.connect(self._grbl.send)   # main-thread send
        self._send_thread.progress.connect(self._on_progress)
        self._send_thread.done.connect(self._on_file_streamed)
        self._send_thread.error.connect(self._on_error)
        self._send_thread.start()

    # ── Progress / done ───────────────────────────────────────────────────────

    @pyqtSlot(int, int)
    def _on_progress(self, sent, total):
        n = self._current_repeat + 1
        t = self._total_repeats
        pct = int(sent / total * 100) if total else 0
        if t > 1:
            self._prog_lbl.setText('Run %d/%d — %d/%d lines (%d%%)' % (n, t, sent, total, pct))
        else:
            self._prog_lbl.setText('%d/%d lines (%d%%)' % (sent, total, pct))

    @pyqtSlot()
    def _on_file_streamed(self):
        """
        All lines have been queued into GrblConnection.
        GRBL is still cutting. Poll for Idle to know when it's truly finished.
        If more repeats remain, wait for Idle then start next run.
        """
        n = self._current_repeat + 1
        t = self._total_repeats
        if t > 1:
            self._prog_lbl.setText(
                'Run %d/%d queued ✓ — waiting for machine to finish…' % (n, t))
        else:
            self._prog_lbl.setText('File queued ✓ — machine is cutting')

        if self._current_repeat + 1 < self._total_repeats:
            # More repeats — wait for GRBL to become Idle
            self._idle_timer.start()
        else:
            # Last (or only) repeat — just show status, enable Run
            # but keep stop available until machine actually finishes
            self._idle_timer.start()   # still poll to update UI when done

    def _check_idle_for_next_repeat(self):
        """Polls GRBL state to detect when machine finishes current run."""
        if self._grbl.state not in ('Idle',):
            return   # still running, keep polling

        self._idle_timer.stop()
        self._current_repeat += 1

        if self._current_repeat < self._total_repeats:
            # Start next repeat
            self._prog_lbl.setText(
                'Starting run %d / %d…' % (self._current_repeat + 1, self._total_repeats))
            self._start_send()
        else:
            # All repeats done
            t = self._total_repeats
            self._prog_lbl.setText(
                'All %d run%s complete ✓' % (t, 's' if t > 1 else ''))
            self._btn_run.setEnabled(True)
            self._btn_stop.setEnabled(False)
            self._current_repeat = 0

    def _stop_all(self):
        self._idle_timer.stop()
        if self._send_thread:
            self._send_thread.stop()
        self._grbl.reset()
        self._grbl.send('M5')
        self._current_repeat = 0
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._prog_lbl.setText('Stopped.')

    @pyqtSlot(str)
    def _on_error(self, msg):
        self._idle_timer.stop()
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._prog_lbl.setText('Error: ' + msg)