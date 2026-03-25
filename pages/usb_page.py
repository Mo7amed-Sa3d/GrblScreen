# pages/usb_page.py
# Browse USB drive for G-code files and send them to GRBL.
# Enhanced: user can specify number of repeats for the selected file.
# Repeats are triggered by detecting the GRBL idle state after a file finishes.

import os
import sys
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QFrame,
    QSpinBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QTimer

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
            if not self._stop:
                self.done.emit()
        except Exception as e:
            self.error.emit(str(e))


class UsbPage(QWidget):
    def __init__(self, grbl, on_back, parent=None):
        super().__init__(parent)
        self._grbl    = grbl
        self._on_back = on_back
        self._current_dir   = None
        self._send_thread   = None
        self._selected_path = None
        self._repeats_total = 1
        self._repeats_remaining = 0
        self._waiting_for_idle = False
        self._idle_timeout = QTimer()
        self._idle_timeout.setSingleShot(True)
        self._idle_timeout.timeout.connect(self._on_idle_timeout)
        self._build()

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
        self._path_lbl.setStyleSheet(
            'font-size:14px; color:#ff8c00; font-weight:bold;')
        hdr.addWidget(self._path_lbl, 1)

        btn_ref = QPushButton('⟳')
        btn_ref.setMaximumWidth(52); btn_ref.setMinimumHeight(48)
        btn_ref.clicked.connect(self._refresh)
        self._btn_refresh = btn_ref
        hdr.addWidget(btn_ref)
        root.addLayout(hdr)

        div = QFrame(); div.setFrameShape(QFrame.HLine); root.addWidget(div)

        # File list
        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_click)
        self._list.itemDoubleClicked.connect(self._on_double)
        root.addWidget(self._list, 1)

        # Repeat count spinbox
        repeat_row = QHBoxLayout()
        repeat_row.addWidget(QLabel('Repeat:'))
        self._repeat_spinbox = QSpinBox()
        self._repeat_spinbox.setMinimum(1)
        self._repeat_spinbox.setMaximum(999)
        self._repeat_spinbox.setValue(1)
        self._repeat_spinbox.setToolTip('Number of times to run the selected file')
        repeat_row.addWidget(self._repeat_spinbox)
        repeat_row.addStretch()
        root.addLayout(repeat_row)

        # Selected file + buttons
        sel_row = QHBoxLayout()
        self._sel_lbl = QLabel('No file selected')
        self._sel_lbl.setStyleSheet('color:#aaa; font-size:13px;')
        sel_row.addWidget(self._sel_lbl, 1)

        self._btn_run = QPushButton('▶  Run')
        self._btn_run.setProperty('role', 'success')
        self._btn_run.setMinimumHeight(52); self._btn_run.setMinimumWidth(100)
        self._btn_run.setEnabled(False)
        self._btn_run.clicked.connect(self._run_file)
        sel_row.addWidget(self._btn_run)

        self._btn_stop = QPushButton('✕  Stop')
        self._btn_stop.setProperty('role', 'danger')
        self._btn_stop.setMinimumHeight(52); self._btn_stop.setMinimumWidth(100)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_file)
        sel_row.addWidget(self._btn_stop)
        root.addLayout(sel_row)

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

        roots = _find_usb_roots()
        if not roots:
            self._list.addItem('⚠  No USB drive found — plug in drive and press ⟳')
            self._path_lbl.setText('No USB drive detected')
            return

        self._current_dir = roots[0]
        self._path_lbl.setText(self._current_dir)
        self._list_dir(self._current_dir)

    def _list_dir(self, path):
        self._list.clear()
        try:
            entries = sorted(os.scandir(path),
                             key=lambda e: (not e.is_dir(), e.name.lower()))
            for entry in entries:
                if entry.name.startswith('.'):
                    continue
                if entry.is_dir():
                    item = QListWidgetItem('📁  ' + entry.name)
                    item.setData(Qt.UserRole, ('dir', entry.path))
                    self._list.addItem(item)
                elif os.path.splitext(entry.name)[1].lower() in GCODE_EXTS:
                    size = entry.stat().st_size
                    s = ('%d KB' % (size // 1024)) if size > 1024 else ('%d B' % size)
                    item = QListWidgetItem('📄  %s   (%s)' % (entry.name, s))
                    item.setData(Qt.UserRole, ('file', entry.path))
                    self._list.addItem(item)
        except PermissionError:
            self._list.addItem('⚠  Permission denied')

    def _on_click(self, item):
        d = item.data(Qt.UserRole)
        if d and d[0] == 'file':
            self._selected_path = d[1]
            self._sel_lbl.setText(os.path.basename(d[1]))
            self._sel_lbl.setStyleSheet(
                'color:#ff8c00; font-weight:bold; font-size:13px;')
            self._btn_run.setEnabled(True)

    def _on_double(self, item):
        d = item.data(Qt.UserRole)
        if not d: return
        if d[0] == 'dir':
            self._list_dir(d[1])
        elif d[0] == 'file':
            self._selected_path = d[1]
            self._run_file()

    # ── File sending with repeats ─────────────────────────────────────────────

    def _run_file(self):
        if not self._selected_path:
            return
        if self._send_thread and self._send_thread.isRunning():
            return

        self._repeats_total = self._repeat_spinbox.value()
        self._repeats_remaining = self._repeats_total
        print(f"[DEBUG] _run_file: total repeats = {self._repeats_total}", file=sys.stderr)

        # Disable UI during sending
        self._repeat_spinbox.setEnabled(False)
        self._list.setEnabled(False)
        self._btn_refresh.setEnabled(False)
        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)

        self._start_send()

    def _start_send(self):
        """Create and start a new thread to send the selected file."""
        if self._send_thread:
            self._send_thread.stop()
            self._send_thread.wait(1000)
            self._send_thread.deleteLater()
            self._send_thread = None

        self._send_thread = _FileLoaderThread(self._selected_path)
        self._send_thread.send_line.connect(self._grbl.send)
        self._send_thread.progress.connect(self._on_progress)
        self._send_thread.done.connect(self._on_file_done)
        self._send_thread.error.connect(self._on_error)
        self._send_thread.finished.connect(self._on_thread_finished)
        self._send_thread.start()
        print("[DEBUG] _start_send: thread started", file=sys.stderr)

    @pyqtSlot(int, int)
    def _on_progress(self, sent, total):
        pct = int(sent / total * 100) if total else 0
        if self._repeats_total > 1:
            completed = self._repeats_total - self._repeats_remaining
            self._prog_lbl.setText(
                f'Repeat {completed+1} of {self._repeats_total}: '
                f'{sent} / {total} lines ({pct}%)'
            )
        else:
            self._prog_lbl.setText(f'{sent} / {total} lines  ({pct}%)')

    @pyqtSlot()
    def _on_file_done(self):
        """One file reading finished. Decrement repeats and start waiting for idle."""
        self._repeats_remaining -= 1
        print(f"[DEBUG] _on_file_done: repeats remaining = {self._repeats_remaining}", file=sys.stderr)
        if self._repeats_remaining > 0:
            # Start monitoring for machine idle
            self._waiting_for_idle = True
            self._grbl.state_changed.connect(self._on_state_changed)
            self._idle_timeout.start(30000)   # 30 sec max wait
            print("[DEBUG] Started waiting for idle state", file=sys.stderr)
        else:
            self._finalize_send(completed=True)

    @pyqtSlot()
    def _on_thread_finished(self):
        """Thread finished. Clean up."""
        if self._send_thread:
            self._send_thread.deleteLater()
            self._send_thread = None

    def _on_state_changed(self, state):
        """Called when GRBL state changes. Check if we are waiting for idle."""
        if not self._waiting_for_idle:
            return
        print(f"[DEBUG] _on_state_changed: {state}", file=sys.stderr)
        if state == 'Idle':
            self._waiting_for_idle = False
            self._grbl.state_changed.disconnect(self._on_state_changed)
            self._idle_timeout.stop()
            print("[DEBUG] Idle detected, starting next repeat", file=sys.stderr)
            # Clean up old thread
            if self._send_thread:
                self._send_thread.deleteLater()
                self._send_thread = None
            self._start_send()

    def _on_idle_timeout(self):
        """Fallback: if idle never detected, force next repeat."""
        if self._waiting_for_idle:
            self._waiting_for_idle = False
            try:
                self._grbl.state_changed.disconnect(self._on_state_changed)
            except:
                pass
            print("[DEBUG] Idle wait timeout, forcing next repeat", file=sys.stderr)
            if self._send_thread:
                self._send_thread.deleteLater()
                self._send_thread = None
            self._start_send()

    @pyqtSlot(str)
    def _on_error(self, msg):
        self._finalize_send(completed=False, error_msg=msg)

    def _finalize_send(self, completed=True, error_msg=None):
        """Re-enable UI and show final status."""
        self._waiting_for_idle = False
        try:
            self._grbl.state_changed.disconnect(self._on_state_changed)
        except:
            pass
        self._idle_timeout.stop()
        if self._send_thread:
            self._send_thread.stop()
            self._send_thread.wait(1000)
            self._send_thread.deleteLater()
            self._send_thread = None

        # Re-enable UI
        self._repeat_spinbox.setEnabled(True)
        self._list.setEnabled(True)
        self._btn_refresh.setEnabled(True)
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)

        if error_msg:
            self._prog_lbl.setText(f'Error: {error_msg}')
        elif completed:
            if self._repeats_total > 1:
                self._prog_lbl.setText(f'All {self._repeats_total} repeats completed ✓')
            else:
                self._prog_lbl.setText('File queued ✓  — machine is cutting')
        else:
            self._prog_lbl.setText('Stopped.')

        self._repeats_remaining = 0

    def _stop_file(self):
        """Stop sending and cancel any pending repeats."""
        self._repeats_remaining = 0
        self._waiting_for_idle = False
        try:
            self._grbl.state_changed.disconnect(self._on_state_changed)
        except:
            pass
        self._idle_timeout.stop()
        if self._send_thread:
            self._send_thread.stop()
        self._grbl.reset()
        self._grbl.send('M5')
        QTimer.singleShot(200, lambda: self._finalize_send(completed=False))