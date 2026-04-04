# pages/camera_page.py
# Pi camera live feed via rpicam-vid (or libcamera-vid) MJPEG stream.
#
# Bug fix: subprocess can't find 'rpicam-vid' when running under a
# restricted environment (systemd service / X11 without full PATH).
# Fix: search for the binary in known locations before invoking.
#
# Updated to use rpicam-vid (the newer name for libcamera-vid on Bookworm).
# Falls back to libcamera-vid if rpicam-vid is not found.

import subprocess
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QSizePolicy
)
from PyQt5.QtCore  import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt5.QtGui   import QPixmap, QImage


# Locations to search for camera binaries (rpicam-vid first, then libcamera-vid)
_CAMERA_PATHS = [
    '/usr/bin/rpicam-vid',
    '/usr/local/bin/rpicam-vid',
    '/opt/vc/bin/rpicam-vid',
    '/usr/bin/libcamera-vid',
    '/usr/local/bin/libcamera-vid',
    '/opt/vc/bin/libcamera-vid',
]


def _find_camera_binary():
    """Return the full path to rpicam-vid or libcamera-vid, or None if not found."""
    for p in _CAMERA_PATHS:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    # Also try PATH (works when running manually, may fail under systemd)
    for name in ('rpicam-vid', 'libcamera-vid'):
        try:
            result = subprocess.run(
                ['which', name],
                capture_output=True, text=True, timeout=3
            )
            path = result.stdout.strip()
            if path and os.path.isfile(path):
                return path
        except Exception:
            pass
    return None


class _MjpegThread(QThread):
    frame_ready = pyqtSignal(QImage)
    error       = pyqtSignal(str)

    def __init__(self, binary, width=1920, height=1080, fps=15):
        super().__init__()
        self._bin  = binary
        self._w    = width
        self._h    = height
        self._fps  = fps
        self._proc = None
        self._stop = False

    def stop(self):
        self._stop = True
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                pass

    def run(self):
        cmd = [
            self._bin,
            '--codec',     'mjpeg',
            '--width',     str(self._w),
            '--height',    str(self._h),
            '--framerate', str(self._fps),
            '--timeout',   '0',
            '--nopreview',
            '-o', '-',
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, 'LIBCAMERA_LOG_LEVELS': '*:ERROR'},
            )
        except Exception as e:
            self.error.emit('Failed to start camera: %s' % str(e))
            return

        buf = b''
        while not self._stop:
            chunk = self._proc.stdout.read(4096)
            if not chunk:
                # Process ended
                stderr = self._proc.stderr.read().decode('utf-8', errors='replace')
                if not self._stop:
                    self.error.emit('Camera stream ended. %s' % stderr[:120])
                break
            buf += chunk

            # Extract complete JPEG frames (SOI FF D8 … EOI FF D9)
            while True:
                soi = buf.find(b'\xff\xd8')
                if soi < 0:
                    break
                eoi = buf.find(b'\xff\xd9', soi + 2)
                if eoi < 0:
                    break
                jpeg = buf[soi:eoi + 2]
                buf  = buf[eoi + 2:]
                img  = QImage.fromData(jpeg, 'JPEG')
                if not img.isNull():
                    self.frame_ready.emit(img)


class CameraPage(QWidget):
    def __init__(self, on_back, grbl=None, parent=None):
        super().__init__(parent)
        self._on_back = on_back
        self._grbl    = grbl
        self._thread  = None
        self._binary  = None   # resolved path to camera binary
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        btn_back = QPushButton('◀  Back')
        btn_back.setProperty('role', 'back')
        btn_back.setMinimumHeight(48); btn_back.setMaximumWidth(120)
        btn_back.clicked.connect(self._go_back)
        hdr.addWidget(btn_back)

        hdr.addWidget(QLabel('Camera').setStyleSheet('') or
                      self._lbl('Camera', 16, '#ff8c00'))

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

        # Coordinates display
        coord_layout = QHBoxLayout()
        coord_layout.addWidget(self._lbl('Position:', 12, '#aaa'))
        self._coord_x = QLabel('X: 0.0000')
        self._coord_y = QLabel('Y: 0.0000')
        self._coord_z = QLabel('Z: 0.0000')
        for lbl in [self._coord_x, self._coord_y, self._coord_z]:
            lbl.setStyleSheet('color:#4CAF50; font-size:13px; font-family:monospace;')
        coord_layout.addWidget(self._coord_x)
        coord_layout.addWidget(self._coord_y)
        coord_layout.addWidget(self._coord_z)
        coord_layout.addStretch()
        root.addLayout(coord_layout)

        # Video display
        self._video = QLabel()
        self._video.setAlignment(Qt.AlignCenter)
        self._video.setMinimumHeight(300)
        self._video.setStyleSheet(
            'background:#111; border:1px solid #444; border-radius:8px; color:#555;')
        self._video.setText('Press ▶ Start to open camera')
        root.addWidget(self._video, 1)

        # Status
        self._status = QLabel('Camera idle')
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet('color:#aaa; font-size:13px;')
        root.addWidget(self._status)

        div2 = QFrame(); div2.setFrameShape(QFrame.HLine); root.addWidget(div2)

        # Jog controls - compass style
        jog_area = QWidget()
        jog_layout = QVBoxLayout(jog_area)
        jog_layout.setContentsMargins(12, 12, 12, 8)
        jog_layout.setSpacing(10)

        # X/Y compass grid
        compass = QGridLayout()
        compass.setSpacing(10)

        self._b_y_up = self._jbtn('▲')
        self._b_y_down = self._jbtn('▼')
        self._b_x_left = self._jbtn('◀')
        self._b_x_right = self._jbtn('▶')

        compass.addWidget(self._b_y_up, 0, 1)
        compass.addWidget(self._b_x_left, 1, 0)
        compass.addWidget(self._b_x_right, 1, 2)
        compass.addWidget(self._b_y_down, 2, 1)

        for col in range(3):
            compass.setColumnStretch(col, 1)
        for row in range(3):
            compass.setRowStretch(row, 1)

        jog_layout.addLayout(compass, 1)

        # Z axis controls
        z_row = QHBoxLayout()
        z_row.addStretch()
        z_row.addWidget(self._lbl('Z:', 12, '#aaa'))
        self._b_z_down = self._jbtn('▼')
        self._b_z_down.setMaximumWidth(50)
        self._b_z_up = self._jbtn('▲')
        self._b_z_up.setMaximumWidth(50)
        z_row.addWidget(self._b_z_down)
        z_row.addWidget(self._b_z_up)
        z_row.addStretch()
        jog_layout.addLayout(z_row)

        root.addWidget(jog_area, 2)

        # Connect jog buttons
        self._b_y_up.clicked.connect(lambda: self._jog_axis('Y', -5))
        self._b_y_down.clicked.connect(lambda: self._jog_axis('Y', 5))
        self._b_x_left.clicked.connect(lambda: self._jog_axis('X', -5))
        self._b_x_right.clicked.connect(lambda: self._jog_axis('X', 5))
        self._b_z_down.clicked.connect(lambda: self._jog_axis('Z', -5))
        self._b_z_up.clicked.connect(lambda: self._jog_axis('Z', 5))

        # Connect to grbl position updates
        if self._grbl:
            self._grbl.position_changed.connect(self._on_position_changed)

    def _lbl(self, text, size=14, color='#fff'):
        l = QLabel(text)
        l.setStyleSheet('font-size:%dpx; font-weight:bold; color:%s;' % (size, color))
        return l

    def _jbtn(self, label):
        """Create a jog button matching dashboard style."""
        b = QPushButton(label)
        b.setObjectName('jogBtn')
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return b

    def _resolve_binary(self):
        """Find rpicam-vid or libcamera-vid and cache its path. Returns path or None."""
        if self._binary:
            return self._binary
        self._binary = _find_camera_binary()
        return self._binary

    def _start(self):
        if self._thread and self._thread.isRunning():
            return

        binary = self._resolve_binary()
        if not binary:
            self._status.setText(
                'Camera binary not found.\n'
                'Run:  sudo apt install -y rpicam-apps   (or libcamera-apps)\n'
                'Then check:  which rpicam-vid  or  which libcamera-vid'
            )
            self._status.setStyleSheet('color:#f44336; font-size:13px;')
            return

        self._video.setText('Starting camera…')
        self._status.setText('Using: ' + binary)
        self._status.setStyleSheet('color:#aaa; font-size:12px;')

        self._thread = _MjpegThread(binary, width=3280, height=2464, fps=15)
        self._thread.frame_ready.connect(self._on_frame)
        self._thread.error.connect(self._on_error)
        self._thread.start()

        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)

    def _stop(self):
        if self._thread:
            self._thread.stop()
            self._thread.wait(3000)
            self._thread = None
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
            w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._video.setPixmap(pix)

    @pyqtSlot(str)
    def _on_error(self, msg):
        self._status.setText(msg)
        self._status.setStyleSheet('color:#f44336; font-size:12px;')
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)

    def _jog_axis(self, axis, dist):
        """Send a jog command for the specified axis and distance (mm)."""
        if not self._grbl or not self._grbl.is_connected():
            self._status.setText('Not connected to machine')
            self._status.setStyleSheet('color:#f44336; font-size:12px;')
            return
        # Jog with speed of 2000 mm/min
        self._grbl.jog(axis, dist, 2000)

    @pyqtSlot(float, float, float)
    def _on_position_changed(self, x, y, z):
        """Update the coordinate display with current position."""
        self._coord_x.setText(f'X: {x:8.4f}')
        self._coord_y.setText(f'Y: {y:8.4f}')
        self._coord_z.setText(f'Z: {z:8.4f}')