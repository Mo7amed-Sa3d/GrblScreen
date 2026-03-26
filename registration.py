# registration.py
# Registration mark detection and 4-point affine skew correction.
#
# G-code comment format (anywhere in the file):
#   ;RegMarks(x1,y1)(x2,y2)(x3,y3)(x4,y4)
#
# (x1,y1) is the job origin — G92 X0 Y0 is set at the actual position
# of mark 1 after scanning.
#
# The 4-point affine transform (6 DOF) corrects for:
#   translation, rotation, X/Y scale error (paper stretch), and shear.
#
# Calibration constants to set once per machine build:
#   CAM_OFFSET_X_MM  — camera centre is this far RIGHT  of knife tip (mm)
#   CAM_OFFSET_Y_MM  — camera centre is this far ABOVE  knife tip (mm)
#   MM_PER_PIXEL     — mm per pixel at paper surface
#     Method: jog exactly 20 mm in X, count pixel shift → 20.0 / pixel_shift
#
# Dependencies:
#   sudo apt-get install -y python3-picamera2 python3-opencv python3-numpy

import re
import math
import logging

# ── Calibration constants — edit for your machine ────────────────────────────
CAM_OFFSET_X_MM = 20.0    # mm camera is RIGHT of knife
CAM_OFFSET_Y_MM =  0.0    # mm camera is ABOVE knife
MM_PER_PIXEL    =  0.094  # mm/pixel at paper surface (calibrate!)

# ── Blob detection ────────────────────────────────────────────────────────────
BLOB_DARK_MAX  = 250     # grayscale threshold for "dark dot"
BLOB_MIN_AREA  = 150    # pixels²
BLOB_MAX_AREA  = 8000   # pixels²
BLOB_MIN_ROUND = 0.45   # 0–1 circularity
MAX_PX_OFFSET  = 130    # reject if dot centre is >130px from image centre

# ── RegMarks parser ───────────────────────────────────────────────────────────
_RM_RE = re.compile(
    r'RegMarks\s*'
    r'\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)\s*'
    r'\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)\s*'
    r'\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)\s*'
    r'\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)',
    re.IGNORECASE
)


def parse_regmarks(filepath):
    """
    Scan G-code file for ;RegMarks(x1,y1)(x2,y2)(x3,y3)(x4,y4) comment.
    Returns list of 4 (x,y) float tuples, or None if not found.
    """
    try:
        with open(filepath, 'r', errors='replace') as f:
            for line in f:
                if not line.strip().startswith(';'):
                    continue
                m = _RM_RE.search(line)
                if m:
                    pts = [(float(m.group(i*2+1)), float(m.group(i*2+2)))
                           for i in range(4)]
                    logging.info('RegMarks found: %s', pts)
                    return pts
    except Exception as e:
        logging.warning('parse_regmarks error: %s', e)
    return None


# ── Scan result ───────────────────────────────────────────────────────────────

class DotScanResult:
    def __init__(self, success, world_x=0.0, world_y=0.0,
                 dx_px=0.0, dy_px=0.0, message=''):
        self.success = success
        self.world_x = world_x
        self.world_y = world_y
        self.dx_px   = dx_px
        self.dy_px   = dy_px
        self.message = message


# ── Affine correction ─────────────────────────────────────────────────────────

class AffineCorrection:
    """
    6-DOF affine: corrected = M * design + t
        new_x = a*x + b*y + tx
        new_y = c*x + d*y + ty
    """
    def __init__(self, a=1.0, b=0.0, tx=0.0,
                       c=0.0, d=1.0, ty=0.0,
                 active=False, residual_mm=0.0):
        self.a = a; self.b = b; self.tx = tx
        self.c = c; self.d = d; self.ty = ty
        self.active      = active
        self.residual_mm = residual_mm

    def apply(self, x, y):
        if not self.active:
            return x, y
        return self.a*x + self.b*y + self.tx, self.c*x + self.d*y + self.ty

    def disarm(self):
        self.active = False

    def summary(self):
        angle = math.degrees(math.atan2(self.c, self.a))
        sx = math.hypot(self.a, self.c)
        sy = math.hypot(self.b, self.d)
        return ('Rot: %+.3f°  Scale: (%.4f, %.4f)  '
                'Offset: (%.2f, %.2f) mm  RMS: %.3f mm'
                % (angle, sx, sy, self.tx, self.ty, self.residual_mm))


def compute_affine_correction(design_pts, actual_pts):
    """
    Least-squares affine fit over 4 point pairs.
    design_pts, actual_pts: each a list of 4 (x,y) tuples.
    Returns (AffineCorrection, warning_message or None).
    """
    try:
        import numpy as np
    except ImportError:
        return None, 'numpy not found: sudo apt-get install python3-numpy'

    A  = np.array([[p[0], p[1], 1.0] for p in design_pts])
    bx = np.array([q[0] for q in actual_pts])
    by = np.array([q[1] for q in actual_pts])

    px, *_ = np.linalg.lstsq(A, bx, rcond=None)
    py, *_ = np.linalg.lstsq(A, by, rcond=None)

    a, b, tx = float(px[0]), float(px[1]), float(px[2])
    c, d, ty = float(py[0]), float(py[1]), float(py[2])

    # RMS residual
    rms = math.sqrt(sum(
        (a*p[0]+b*p[1]+tx-q[0])**2 + (c*p[0]+d*p[1]+ty-q[1])**2
        for p, q in zip(design_pts, actual_pts)
    ) / 4.0)

    corr = AffineCorrection(a=a, b=b, tx=tx, c=c, d=d, ty=ty,
                            active=True, residual_mm=rms)
    logging.info('Affine correction: %s', corr.summary())

    warn = None
    if rms > 2.0:
        warn = 'RMS fit error %.2f mm — consider rescanning marks' % rms
    return corr, warn


# ── Camera capture ────────────────────────────────────────────────────────────

def capture_frame_gray():
    """Capture one frame. Returns (gray_ndarray, error_str)."""
    try:
        from picamera2 import Picamera2
        import numpy as np, cv2, time
        cam = Picamera2()
        cam.configure(cam.create_still_configuration(
            main={'size': (640, 480), 'format': 'RGB888'}))
        cam.start(); time.sleep(0.3)
        frame = cam.capture_array()
        cam.stop(); cam.close()
        return cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), None
    except ImportError:
        return _capture_subprocess()
    except Exception as e:
        return None, str(e)


def _capture_subprocess():
    import subprocess, tempfile, os
    try:
        import cv2
    except ImportError:
        return None, 'python3-opencv not installed'
    tmp = tempfile.mktemp(suffix='.jpg')
    for binary in ('/usr/bin/rpicam-still', '/usr/bin/libcamera-still',
                   '/usr/local/bin/rpicam-still', '/usr/local/bin/libcamera-still'):
        if not (os.path.isfile(binary) and os.access(binary, os.X_OK)):
            continue
        try:
            subprocess.run([binary, '-o', tmp, '--width', '640', '--height', '480',
                            '--nopreview', '--timeout', '500', '-q', '85'],
                           timeout=8, capture_output=True, check=True)
            img = cv2.imread(tmp, cv2.IMREAD_GRAYSCALE)
            os.remove(tmp)
            if img is not None:
                return img, None
            return None, 'Empty image from camera'
        except Exception as e:
            try: os.remove(tmp)
            except: pass
            return None, str(e)
    return None, 'No camera binary found (rpicam-still / libcamera-still)'


# ── Dot detection ─────────────────────────────────────────────────────────────

def find_dot_in_frame(gray):
    """
    Find darkest circular blob in frame.
    Returns (dx_px, dy_px, annotated_bgr, error_str).
      +dx = dot is RIGHT of centre, +dy = dot is BELOW centre.
    """
    try:
        import cv2, numpy as np
    except ImportError:
        return 0, 0, gray, 'OpenCV/numpy not installed'

    h, w = gray.shape
    cx, cy = w // 2, h // 2

    _, thresh = cv2.threshold(gray, BLOB_DARK_MAX, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if not (BLOB_MIN_AREA <= area <= BLOB_MAX_AREA):
            continue
        peri = cv2.arcLength(cnt, True)
        if peri == 0:
            continue
        if 4 * math.pi * area / (peri**2) < BLOB_MIN_ROUND:
            continue
        M = cv2.moments(cnt)
        if M['m00'] == 0:
            continue
        bx = int(M['m10'] / M['m00'])
        by = int(M['m01'] / M['m00'])
        candidates.append((math.hypot(bx-cx, by-cy), bx, by, cnt))

    if not candidates:
        return 0, 0, gray, 'No dot found (threshold=%d). Check lighting.' % BLOB_DARK_MAX

    _, bx, by, cnt = min(candidates, key=lambda c: c[0])
    dx, dy = bx - cx, by - cy

    if abs(dx) > MAX_PX_OFFSET or abs(dy) > MAX_PX_OFFSET:
        return dx, dy, gray, 'Dot too far from centre (%+d, %+d px)' % (dx, dy)

    ann = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    cv2.drawContours(ann, [cnt], -1, (0, 165, 255), 2)
    cv2.circle(ann, (bx, by), 6, (0, 165, 255), -1)
    cv2.line(ann, (cx, 0), (cx, h), (80, 80, 80), 1)
    cv2.line(ann, (0, cy), (w, cy), (80, 80, 80), 1)
    return dx, dy, ann, None


# ── Public: scan one dot ──────────────────────────────────────────────────────

def scan_dot(machine_x, machine_y):
    """
    Capture frame and find dot. machine_x/y = current KNIFE position.
    Returns DotScanResult with dot's actual world position.
    """
    gray, err = capture_frame_gray()
    if gray is None:
        return DotScanResult(False, message=err or 'Capture failed')
    dx_px, dy_px, _, err = find_dot_in_frame(gray)
    if err:
        return DotScanResult(False, message=err)

    # Camera is CAM_OFFSET from knife. Dot world position:
    # camera centre is at (machine_x + CAM_OFFSET_X, machine_y + CAM_OFFSET_Y)
    # dot is at camera centre + pixel offset converted to mm
    # image +Y is downward; machine +Y is upward → negate dy
    world_x = machine_x + CAM_OFFSET_X_MM + dx_px * MM_PER_PIXEL
    world_y = machine_y + CAM_OFFSET_Y_MM - dy_px * MM_PER_PIXEL

    return DotScanResult(True, world_x=world_x, world_y=world_y,
                         dx_px=dx_px, dy_px=dy_px)