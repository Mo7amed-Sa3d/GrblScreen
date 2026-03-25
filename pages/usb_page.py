# pages/usb_page.py
# Browse USB drive for G-code files and send them to GRBL.
#
# Bug fix: QSerialPort.write() must be called from the Qt main thread.
# The old _SendThread called grbl.send() from a background thread, causing
# silent drops.  Fix: the thread only reads the file (disk I/O); it emits
# each line as a signal which is received in the main thread and queued via
# grbl.send().  The flow-control queue in GrblConnection handles pacing.

import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot

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
    Reads a G-code file from disk and emits each line as a signal.
    The connected slot (in the main thread) calls grbl.send() — safe.
    """
    send_line = pyqtSignal(str)     # emitted for each G-code line
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
                self.send_line.emit(line)   # → main thread → grbl.send()
                self.progress.emit(i + 1, total)
                # Small sleep to avoid flooding the signal queue faster
                # than Qt can dispatch.  The flow control queue in
                # GrblConnection handles the actual serial pacing.
                self.msleep(1)
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
        hdr.addWidget(btn_ref)
        root.addLayout(hdr)

        div = QFrame(); div.setFrameShape(QFrame.HLine); root.addWidget(div)

        # File list
        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_click)
        self._list.itemDoubleClicked.connect(self._on_double)
        root.addWidget(self._list, 1)

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

    # ── File sending ──────────────────────────────────────────────────────────

    def _run_file(self):
        if not self._selected_path: return
        if self._send_thread and self._send_thread.isRunning(): return

        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._prog_lbl.setText('Sending…')

        self._send_thread = _FileLoaderThread(self._selected_path)

        # send_line signal → main-thread slot → grbl.send()
        # This is the key fix: serial write happens in main thread.
        self._send_thread.send_line.connect(self._grbl.send)
        self._send_thread.progress.connect(self._on_progress)
        self._send_thread.done.connect(self._on_done)
        self._send_thread.error.connect(self._on_error)
        self._send_thread.start()

    def _stop_file(self):
        if self._send_thread:
            self._send_thread.stop()
        self._grbl.reset()
        self._grbl.send('M5')
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._prog_lbl.setText('Stopped.')

    @pyqtSlot(int, int)
    def _on_progress(self, sent, total):
        pct = int(sent / total * 100) if total else 0
        self._prog_lbl.setText('%d / %d lines  (%d%%)' % (sent, total, pct))

    @pyqtSlot()
    def _on_done(self):
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._prog_lbl.setText('File queued ✓  — machine is cutting')

    @pyqtSlot(str)
    def _on_error(self, msg):
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._prog_lbl.setText('Error: ' + msg)