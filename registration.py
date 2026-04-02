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
CAM_OFFSET_X_MM = 0.0     # mm camera is RIGHT of knife (calibrate: measure then set)
CAM_OFFSET_Y_MM = 0.0     # mm camera is ABOVE knife (calibrate: measure then set)
MM_PER_PIXEL    =  0.0099 # mm/pixel — calculated from 5mm dot diameter
                           # at 1920×1920: 5mm dot ≈ 504px diameter → 5/504
                           # Calibrate: measure actual vs expected position
                           # and adjust until marks align perfectly

# ── Blob detection — from confirmed working regdetect.py ─────────────────────
# Camera captures at 1920×1920 XRGB; dots are large printed circles.
BLOB_DARK_MAX  = 100    # grayscale threshold (matches regdetect.py)
BLOB_MIN_AREA  = 100000 # pixels² minimum   (matches regdetect.py)
BLOB_MAX_AREA  = 400000 # pixels² maximum   (matches regdetect.py)
BLOB_MIN_ROUND = 0.7    # circularity 0-1   (matches regdetect.py)
BLUR_KERNEL    = (5, 5) # GaussianBlur before threshold
MAX_PX_OFFSET  = 800    # pixels - allow larger offset for 1920px frame

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
                 dx_px=0.0, dy_px=0.0, message='', frame=None):
        self.success = success
        self.world_x = world_x
        self.world_y = world_y
        self.dx_px   = dx_px
        self.dy_px   = dy_px
        self.message = message
        self._frame  = frame  # annotated frame for display


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


# ── Camera capture — matching regdetect.py format ────────────────────────────

def capture_frame():
    """
    Capture one frame using picamera2 with XRGB8888 format at 1920x1920.
    Returns (bgr_frame, gray_frame, error_str).
    Matches the format used in the working regdetect.py script.
    """
    try:
        from picamera2 import Picamera2
        import cv2
        import time

        picam2 = Picamera2()
        config = picam2.create_preview_configuration(
            main={"format": "XRGB8888", "size": (1920, 1920)}
        )
        picam2.configure(config)
        picam2.start()
        time.sleep(0.5)   # allow AE/AWB to settle

        frame = picam2.capture_array()
        picam2.stop()
        picam2.close()

        # Same conversion as regdetect.py: BGRA -> BGR -> GRAY
        bgr  = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        return bgr, gray, None

    except ImportError:
        return None, None, 'picamera2 not installed: sudo apt install python3-picamera2'
    except Exception as e:
        return None, None, 'Camera error: %s' % str(e)


# Keep for backward compatibility
def capture_frame_gray():
    """Returns (gray_ndarray, error_str) — backward compat wrapper."""
    _, gray, err = capture_frame()
    return gray, err


# ── Dot detection — matching regdetect.py algorithm ──────────────────────────

def find_dot_in_frame(gray, bgr=None):
    """
    Find a dark circular registration mark using the same algorithm as regdetect.py.

    Parameters match the working detection script:
      - GaussianBlur before threshold
      - BLOB_DARK_MAX = 100
      - area range 100000-400000 pixels²
      - circularity >= 0.7

    Returns (dx_px, dy_px, annotated_bgr, error_str).
      dx_px positive = dot is RIGHT of image centre
      dy_px positive = dot is BELOW image centre
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return 0, 0, None, 'OpenCV/numpy not installed: sudo apt install python3-opencv python3-numpy'

    h, w = gray.shape
    cx, cy = w // 2, h // 2

    # Step 1: Blur (same as regdetect.py)
    blurred = cv2.GaussianBlur(gray, BLUR_KERNEL, 0)

    # Step 2: Threshold (same as regdetect.py)
    _, thresh = cv2.threshold(blurred, BLOB_DARK_MAX, 255, cv2.THRESH_BINARY_INV)

    # Step 3: Find contours (same as regdetect.py)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Step 4: Filter by area and circularity (same as regdetect.py)
    best_cnt  = None
    best_dist = float('inf')
    best_cx   = best_cy = 0

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < BLOB_MIN_AREA or area > BLOB_MAX_AREA:
            continue

        perimeter = cv2.arcLength(contour, True)
        if perimeter == 0:
            continue
        circularity = 4 * math.pi * area / (perimeter * perimeter)
        if circularity < BLOB_MIN_ROUND:
            continue

        M = cv2.moments(contour)
        if M["m00"] == 0:
            continue
        bx = int(M["m10"] / M["m00"])
        by = int(M["m01"] / M["m00"])

        dist = math.hypot(bx - cx, by - cy)
        if dist < best_dist:
            best_dist = dist
            best_cnt  = contour
            best_cx   = bx
            best_cy   = by

    if best_cnt is None:
        # Annotate with failure info
        output = bgr.copy() if bgr is not None else cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        cv2.putText(output, 'No dot found (T=%d, A=%d-%d, C>=%.1f)' % (
                    BLOB_DARK_MAX, BLOB_MIN_AREA, BLOB_MAX_AREA, BLOB_MIN_ROUND),
                    (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        return 0, 0, output, (
            'No dot found. Check: threshold=%d, area=%d-%d, circularity>=%.1f'
            % (BLOB_DARK_MAX, BLOB_MIN_AREA, BLOB_MAX_AREA, BLOB_MIN_ROUND)
        )

    dx = best_cx - cx
    dy = best_cy - cy

    if abs(dx) > MAX_PX_OFFSET or abs(dy) > MAX_PX_OFFSET:
        return dx, dy, bgr, (
            'Dot found at (%+d, %+d) px from centre — '
            'too far. Move head closer.' % (dx, dy)
        )

    # Annotate output — same style as regdetect.py
    output = bgr.copy() if bgr is not None else cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    area   = cv2.contourArea(best_cnt)
    radius = int(math.sqrt(area / math.pi))

    cv2.drawContours(output, [best_cnt], -1, (0, 255, 0), 3)

    # Filled overlay (same as regdetect.py)
    overlay = output.copy()
    cv2.circle(overlay, (best_cx, best_cy), radius, (255, 255, 0), -1)
    cv2.addWeighted(overlay, 0.3, output, 0.7, 0, output)

    # Crosshair at centre (same as regdetect.py)
    cv2.line(output, (best_cx - 30, best_cy), (best_cx + 30, best_cy), (0, 0, 255), 2)
    cv2.line(output, (best_cx, best_cy - 30), (best_cx, best_cy + 30), (0, 0, 255), 2)

    # Image centre crosshair
    cv2.line(output, (cx, 0), (cx, h), (80, 80, 80), 1)
    cv2.line(output, (0, cy), (w, cy), (80, 80, 80), 1)

    # Offset arrow
    cv2.arrowedLine(output, (cx, cy), (best_cx, best_cy), (0, 255, 0), 2)

    # Info text
    peri = cv2.arcLength(best_cnt, True)
    circ = 4 * math.pi * area / (peri * peri) if peri > 0 else 0
    cv2.putText(output, 'A:%.0f C:%.2f' % (area, circ),
                (best_cx + 10, best_cy - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(output, '(%d,%d) off:(%+d,%+d)' % (best_cx, best_cy, dx, dy),
                (best_cx + 10, best_cy + 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    return dx, dy, output, None



# ── Public: scan one dot ──────────────────────────────────────────────────────

def scan_dot(machine_x, machine_y):
    """
    Capture frame using working regdetect.py format and find dot.
    machine_x/y = current KNIFE position (mm).
    Returns DotScanResult with dot actual world position and annotated frame.
    """
    bgr, gray, err = capture_frame()
    if gray is None:
        return DotScanResult(False, message=err or 'Capture failed')

    dx_px, dy_px, annotated_frame, err = find_dot_in_frame(gray, bgr=bgr)
    if err and annotated_frame is not None:
        # Detection failed but we have an annotated frame showing why
        return DotScanResult(False, message=err, frame=annotated_frame)
    if err:
        return DotScanResult(False, message=err)

    # Camera is CAM_OFFSET from knife tip.
    # dot world pos = camera_centre + pixel_offset_in_mm
    # image +Y is downward; machine +Y is upward → negate dy
    world_x = machine_x + CAM_OFFSET_X_MM + dx_px * MM_PER_PIXEL
    world_y = machine_y + CAM_OFFSET_Y_MM - dy_px * MM_PER_PIXEL

    logging.info('scan_dot: machine(%.2f,%.2f) px(%+d,%+d) world(%.3f,%.3f)',
                 machine_x, machine_y, dx_px, dy_px, world_x, world_y)

    return DotScanResult(True, world_x=world_x, world_y=world_y,
                         dx_px=dx_px, dy_px=dy_px, frame=annotated_frame)