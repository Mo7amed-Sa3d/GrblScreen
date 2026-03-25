# pages/usb_page.py
# Browse USB drive for G-code files and send them to GRBL

import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem,
    QFrame, QFileDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot

GCODE_EXTS  = {'.nc', '.gcode', '.gc', '.ngc', '.cnc', '.tap'}
USB_MOUNTS  = ['/media', '/mnt', '/run/media']   # common Pi mount points


def _find_usb_roots():
    """Return a list of likely USB mount directories."""
    roots = []
    for base in USB_MOUNTS:
        if not os.path.isdir(base):
            continue
        for entry in os.scandir(base):
            if entry.is_dir():
                # Check if it has files (quick test for mounted drive)
                try:
                    next(os.scandir(entry.path))
                    roots.append(entry.path)
                except (StopIteration, PermissionError):
                    pass
    return roots


class _SendThread(QThread):
    """Send a G-code file line by line via GRBL connection."""
    progress = pyqtSignal(int, int)   # (lines_sent, total_lines)
    done     = pyqtSignal()
    error    = pyqtSignal(str)

    def __init__(self, grbl, filepath):
        super().__init__()
        self._grbl = grbl
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
                self._grbl.send(line)
                self.progress.emit(i + 1, total)
            self.done.emit()
        except Exception as e:
            self.error.emit(str(e))


class UsbPage(QWidget):
    def __init__(self, grbl, on_back, parent=None):
        super().__init__(parent)
        self._grbl    = grbl
        self._on_back = on_back
        self._current_dir = None
        self._send_thread = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Header row ────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        btn_back = QPushButton('◀  Back')
        btn_back.setProperty('role', 'back')
        btn_back.setMinimumHeight(48)
        btn_back.setMaximumWidth(120)
        btn_back.clicked.connect(self._on_back)
        hdr.addWidget(btn_back)

        self._path_lbl = QLabel('USB Drive')
        self._path_lbl.setStyleSheet('font-size:14px; color:#ff8c00; font-weight:bold;')
        hdr.addWidget(self._path_lbl, 1)

        btn_refresh = QPushButton('⟳')
        btn_refresh.setMaximumWidth(52); btn_refresh.setMinimumHeight(48)
        btn_refresh.clicked.connect(self._refresh)
        hdr.addWidget(btn_refresh)

        root.addLayout(hdr)

        div = QFrame(); div.setFrameShape(QFrame.HLine); root.addWidget(div)

        # ── File list ─────────────────────────────────────────────────────────
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_item_double)
        self._list.itemClicked.connect(      self._on_item_click)
        root.addWidget(self._list, 1)

        # ── Selected file + run button ────────────────────────────────────────
        sel_row = QHBoxLayout()
        self._sel_lbl = QLabel('No file selected')
        self._sel_lbl.setStyleSheet('color:#aaa; font-size:13px;')
        sel_row.addWidget(self._sel_lbl, 1)

        self._btn_run = QPushButton('▶  Run')
        self._btn_run.setProperty('role', 'success')
        self._btn_run.setMinimumHeight(52)
        self._btn_run.setMinimumWidth(110)
        self._btn_run.setEnabled(False)
        self._btn_run.clicked.connect(self._run_file)
        sel_row.addWidget(self._btn_run)

        self._btn_stop = QPushButton('✕  Stop')
        self._btn_stop.setProperty('role', 'danger')
        self._btn_stop.setMinimumHeight(52)
        self._btn_stop.setMinimumWidth(110)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_file)
        sel_row.addWidget(self._btn_stop)

        root.addLayout(sel_row)

        # ── Progress label ────────────────────────────────────────────────────
        self._prog_lbl = QLabel('')
        self._prog_lbl.setStyleSheet('color:#aaa; font-size:13px;')
        self._prog_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self._prog_lbl)

        self._refresh()

    def _refresh(self):
        self._list.clear()
        self._sel_lbl.setText('No file selected')
        self._btn_run.setEnabled(False)
        self._selected_path = None

        roots = _find_usb_roots()
        if not roots:
            item = QListWidgetItem('⚠  No USB drive found')
            item.setData(Qt.UserRole, None)
            self._list.addItem(item)
            self._path_lbl.setText('No USB drive detected')
            return

        # Use the first found USB root
        self._current_dir = roots[0]
        self._path_lbl.setText(self._current_dir)
        self._list_dir(self._current_dir)

    def _list_dir(self, path):
        self._list.clear()

        # Parent directory entry (except at USB root)
        if self._current_dir != path:
            up = QListWidgetItem('📁  ..')
            up.setData(Qt.UserRole, ('dir', os.path.dirname(path)))
            self._list.addItem(up)

        try:
            entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
            for entry in entries:
                if entry.name.startswith('.'):
                    continue
                if entry.is_dir():
                    item = QListWidgetItem('📁  %s' % entry.name)
                    item.setData(Qt.UserRole, ('dir', entry.path))
                elif os.path.splitext(entry.name)[1].lower() in GCODE_EXTS:
                    size = entry.stat().st_size
                    size_str = '%d KB' % (size // 1024) if size > 1024 else '%d B' % size
                    item = QListWidgetItem('📄  %s   (%s)' % (entry.name, size_str))
                    item.setData(Qt.UserRole, ('file', entry.path))
                    self._list.addItem(item)
                    continue
                else:
                    continue
                self._list.addItem(item)
        except PermissionError:
            self._list.addItem(QListWidgetItem('⚠  Permission denied'))

    def _on_item_click(self, item):
        data = item.data(Qt.UserRole)
        if data and data[0] == 'file':
            self._selected_path = data[1]
            self._sel_lbl.setText(os.path.basename(data[1]))
            self._sel_lbl.setStyleSheet('color:#ff8c00; font-weight:bold; font-size:13px;')
            self._btn_run.setEnabled(True)

    def _on_item_double(self, item):
        data = item.data(Qt.UserRole)
        if not data:
            return
        if data[0] == 'dir':
            self._list_dir(data[1])
        elif data[0] == 'file':
            self._selected_path = data[1]
            self._run_file()

    def _run_file(self):
        if not self._selected_path:
            return
        if self._send_thread and self._send_thread.isRunning():
            return

        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._prog_lbl.setText('Sending…')

        self._send_thread = _SendThread(self._grbl, self._selected_path)
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
        self._prog_lbl.setText('Sending: %d / %d lines  (%d%%)' % (sent, total, pct))

    @pyqtSlot()
    def _on_done(self):
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._prog_lbl.setText('Done ✓')

    @pyqtSlot(str)
    def _on_error(self, msg):
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._prog_lbl.setText('Error: %s' % msg)