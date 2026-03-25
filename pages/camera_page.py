# pages/camera_page.py
# Raspberry Pi camera feed using libcamera-vid MJPEG stream
# Displays live feed in a QLabel using a background reader thread.

import subprocess
import struct
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame
)
from PyQt5.QtCore  import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt5.QtGui   import QPixmap, QImage


class _MjpegThread(QThread):
    """
    Starts libcamera-vid in MJPEG mode and reads frames as raw JPEG bytes.
    Emits each frame as a QImage.
    libcamera-vid outputs MJPEG stream to stdout.
    """
    frame_ready = pyqtSignal(QImage)
    error       = pyqtSignal(str)

    def __init__(self, width=640, height=480, fps=15):
        super().__init__()
        self._w    = width
        self._h    = height
        self._fps  = fps
        self._proc = None
        self._stop = False

    def stop(self):
        self._stop = True
        if self._proc:
            try: self._proc.terminate()
            except Exception: pass

    def run(self):
        cmd = [
            'libcamera-vid',
            '--codec', 'mjpeg',
            '--width',  str(self._w),
            '--height', str(self._h),
            '--framerate', str(self._fps),
            '--timeout', '0',           # run indefinitely
            '--nopreview',
            '-o', '-',                  # output to stdout
        ]
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            self.error.emit('libcamera-vid not found. Install: sudo apt install libcamera-apps')
            return
        except Exception as e:
            self.error.emit(str(e))
            return

        buf = b''
        while not self._stop:
            chunk = self._proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk

            # Find JPEG boundaries (SOI = FF D8, EOI = FF D9)
            while True:
                soi = buf.find(b'\xff\xd8')
                eoi = buf.find(b'\xff\xd9', soi + 2) if soi >= 0 else -1
                if soi < 0 or eoi < 0:
                    break
                jpeg = buf[soi:eoi + 2]
                buf  = buf[eoi + 2:]
                img  = QImage.fromData(jpeg, 'JPEG')
                if not img.isNull():
                    self.frame_ready.emit(img)

        try: self._proc.wait(timeout=2)
        except Exception: pass


class CameraPage(QWidget):
    def __init__(self, on_back, parent=None):
        super().__init__(parent)
        self._on_back = on_back
        self._thread  = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        btn_back = QPushButton('◀  Back')
        btn_back.setProperty('role', 'back')
        btn_back.setMinimumHeight(48); btn_back.setMaximumWidth(120)
        btn_back.clicked.connect(self._go_back)
        hdr.addWidget(btn_back)

        lbl_title = QLabel('Camera')
        lbl_title.setStyleSheet('font-size:16px; font-weight:bold; color:#ff8c00;')
        hdr.addWidget(lbl_title, 1)

        self._btn_start = QPushButton('▶  Start')
        self._btn_start.setProperty('role', 'success')
        self._btn_start.setMinimumHeight(48); self._btn_start.setMinimumWidth(100)
        self._btn_start.clicked.connect(self._start)
        hdr.addWidget(self._btn_start)

        self._btn_stop = QPushButton('■  Stop')
        self._btn_stop.setProperty('role', 'danger')
        self._btn_stop.setMinimumHeight(48); self._btn_stop.setMinimumWidth(100)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop)
        hdr.addWidget(self._btn_stop)

        root.addLayout(hdr)

        div = QFrame(); div.setFrameShape(QFrame.HLine); root.addWidget(div)

        # ── Video label ───────────────────────────────────────────────────────
        self._video = QLabel()
        self._video.setAlignment(Qt.AlignCenter)
        self._video.setStyleSheet(
            'background:#111; border:1px solid #444; border-radius:8px;'
        )
        self._video.setText('Press ▶ Start to open camera')
        self._video.setMinimumHeight(300)
        root.addWidget(self._video, 1)

        # ── Status ────────────────────────────────────────────────────────────
        self._status = QLabel('Camera idle')
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet('color:#aaa; font-size:13px;')
        root.addWidget(self._status)

    def _start(self):
        if self._thread and self._thread.isRunning():
            return
        self._video.setText('Starting camera…')
        self._thread = _MjpegThread(width=460, height=380, fps=15)
        self._thread.frame_ready.connect(self._on_frame)
        self._thread.error.connect(self._on_error)
        self._thread.start()
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._status.setText('Camera running')

    def _stop(self):
        if self._thread:
            self._thread.stop()
            self._thread.wait(2000)
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._status.setText('Camera stopped')
        self._video.setText('Camera stopped')

    def _go_back(self):
        self._stop()
        self._on_back()

    @pyqtSlot(QImage)
    def _on_frame(self, img):
        w = self._video.width()
        h = self._video.height()
        pix = QPixmap.fromImage(img).scaled(
            w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._video.setPixmap(pix)

    @pyqtSlot(str)
    def _on_error(self, msg):
        self._status.setText('Error: %s' % msg)
        self._status.setStyleSheet('color:#f44336; font-size:13px;')
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._video.setText('Camera error — see status below')