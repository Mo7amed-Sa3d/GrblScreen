# tilt_corrector.py
# Transparent G-code correction wrapper around GrblConnection.
# Applies AffineCorrection to all G0/G1 XY coordinates.
# All other commands pass through unchanged.
# All signals forwarded from the underlying connection.

import re
from registration import AffineCorrection

MOTION_RE = re.compile(r'^(G0|G1|G00|G01)\b(.*)', re.IGNORECASE)
WORD_RE   = re.compile(r'([XYZFS])\s*([-+]?\d*\.?\d+)', re.IGNORECASE)


def _apply(line, corr):
    """Apply affine correction to one G-code line. Returns corrected line."""
    if not corr or not corr.active:
        return line
    m = MOTION_RE.match(line.strip())
    if not m:
        return line
    prefix = m.group(1).upper()
    words  = {wm.group(1).upper(): float(wm.group(2))
              for wm in WORD_RE.finditer(m.group(2))}
    if 'X' not in words and 'Y' not in words:
        return line
    nx, ny = corr.apply(words.get('X', 0.0), words.get('Y', 0.0))
    nx = nx -4
    ny = ny + 2
    out = prefix
    for k, v in words.items():
        if k == 'X':   out += ' X%.4f' % nx
        elif k == 'Y': out += ' Y%.4f' % ny
        else:          out += ' %s%.4f' % (k, v)
    return out


class TiltCorrector:
    """
    Drop-in wrapper for GrblConnection.
    Passes everything through, but corrects XY in G0/G1 when armed.
    All signals are forwarded so UI code needs no changes.
    state and mpos are properties so they always reflect the live connection.
    """

    def __init__(self, grbl):
        self._grbl       = grbl
        self._correction = None

        # Forward signals directly
        self.connected        = grbl.connected
        self.disconnected     = grbl.disconnected
        self.state_changed    = grbl.state_changed
        self.position_changed = grbl.position_changed
        self.feed_changed     = grbl.feed_changed
        self.knife_changed    = grbl.knife_changed
        self.message_received = grbl.message_received
        self.alarm_received   = grbl.alarm_received
        self.ok_received      = grbl.ok_received
        self.error_received   = grbl.error_received
        self.raw_received     = grbl.raw_received

    # ── Live properties (always current, not stale copies) ────────────────────
    @property
    def state(self): return self._grbl.state
    @property
    def mpos(self):  return self._grbl.mpos
    @property
    def feed(self):  return self._grbl.feed
    @property
    def knife_down(self):  return self._grbl.knife_down
    @property
    def knife_force(self): return self._grbl.knife_force

    # ── Correction management ─────────────────────────────────────────────────
    def set_correction(self, corr: AffineCorrection):
        self._correction = corr

    def disarm(self):
        if self._correction:
            self._correction.disarm()
        self._correction = None

    @property
    def correction_active(self):
        return self._correction is not None and self._correction.active

    @property
    def correction(self):
        return self._correction

    # ── Send ──────────────────────────────────────────────────────────────────
    def send(self, cmd):
        self._grbl.send(_apply(cmd, self._correction))

    # ── Pass-throughs ─────────────────────────────────────────────────────────
    def all_commands_acknowledged(self):
        return self._grbl.all_commands_acknowledged()

    def connect(self, *a, **kw):     return self._grbl.connect(*a, **kw)
    def disconnect(self):            self._grbl.disconnect()
    def is_connected(self):          return self._grbl.is_connected()
    def available_ports(self):       return self._grbl.available_ports()
    def send_rt(self, b):            self._grbl.send_rt(b)
    def feed_hold(self):             self._grbl.feed_hold()
    def cycle_start(self):           self._grbl.cycle_start()
    def cancel_jog(self):            self._grbl.cancel_jog()
    def reset(self):                 self._grbl.reset()
    def jog(self, *a, **kw):         self._grbl.jog(*a, **kw)
    def knife_down_cmd(self, *a, **kw): self._grbl.knife_down_cmd(*a, **kw)
    def knife_up_cmd(self):          self._grbl.knife_up_cmd()