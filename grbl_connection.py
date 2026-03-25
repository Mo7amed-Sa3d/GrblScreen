# grbl_connection.py
# Fixed flow control: track per-command byte lengths so each 'ok' frees
# the exact number of bytes that command occupied in GRBL's RX buffer.

import re
from collections import deque
from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from PyQt5.QtSerialPort import QSerialPort, QSerialPortInfo

STATUS_INTERVAL = 200
RX_BUFFER_SIZE  = 128   # GRBL serial RX buffer (bytes)

STATE_MAP = {
    'Idle':         ('IDLE',    'stateIdle'),
    'Run':          ('RUNNING', 'stateRun'),
    'Hold':         ('HOLD',    'stateHold'),
    'Hold:0':       ('HOLD',    'stateHold'),
    'Hold:1':       ('HOLD',    'stateHold'),
    'Home':         ('HOMING',  'stateIdle'),
    'Alarm':        ('ALARM',   'stateAlarm'),
    'Door':         ('DOOR',    'stateAlarm'),
    'Check':        ('CHECK',   'stateHold'),
    'Sleep':        ('SLEEP',   'stateNone'),
    'Jog':          ('JOG',     'stateRun'),
    'Disconnected': ('NO CONN', 'stateNone'),
}

STATUS_RE = re.compile(
    r'<(\w+)(?::\d+)?\|MPos:([-\d.]+),([-\d.]+),([-\d.]+)'
    r'(?:\|FS:([\d.]+),([\d.]+))?'
)
M3_RE = re.compile(r'\bM3\b.*?S\s*([\d.]+)', re.IGNORECASE)


class GrblConnection(QObject):
    connected        = pyqtSignal()
    disconnected     = pyqtSignal()
    state_changed    = pyqtSignal(str)
    position_changed = pyqtSignal(float, float, float)
    feed_changed     = pyqtSignal(float, float)
    knife_changed    = pyqtSignal(bool, int)
    message_received = pyqtSignal(str)
    alarm_received   = pyqtSignal(str)
    ok_received      = pyqtSignal()
    error_received   = pyqtSignal(str)
    raw_received     = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._port       = QSerialPort(self)
        self._rx_buf     = ''

        # Pending queue: lines not yet sent to serial
        self._cmd_q      = deque()   # deque of str (with \n)

        # Sent queue: byte lengths of commands already written to serial,
        # waiting for their 'ok' response.
        # Each 'ok' pops the front entry and frees that many bytes.
        self._sent_lens  = deque()
        self._in_flight  = 0        # total bytes currently inside GRBL RX buffer

        self.knife_down  = False
        self.knife_force = 0
        self.state = 'Disconnected'
        self.mpos  = (0.0, 0.0, 0.0)
        self.feed  = (0.0, 0.0)

        self._port.readyRead.connect(self._on_data)
        self._port.errorOccurred.connect(self._on_error)

        self._poll = QTimer(self)
        self._poll.setInterval(STATUS_INTERVAL)
        # '?' is a real-time command — not queued, not counted
        self._poll.timeout.connect(
            lambda: self._port.isOpen() and self._port.write(b'?'))

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self, port_name, baud=115200):
        if self._port.isOpen():
            self._port.close()
        self._port.setPortName(port_name)
        self._port.setBaudRate(baud)
        if self._port.open(QSerialPort.ReadWrite):
            self._poll.start()
            self.state = 'Idle'
            self.connected.emit()
            return True
        return False

    def disconnect(self):
        self._poll.stop()
        if self._port.isOpen():
            self._port.close()
        self._cmd_q.clear()
        self._sent_lens.clear()
        self._in_flight = 0
        self.state = 'Disconnected'
        self.disconnected.emit()

    def is_connected(self):
        return self._port.isOpen()

    @staticmethod
    def available_ports():
        return [(i.portName(), i.description())
                for i in QSerialPortInfo.availablePorts()]

    # ── Send API ──────────────────────────────────────────────────────────────

    def send(self, cmd):
        """
        Queue a G-code command.  Must be called from the Qt main thread.
        Intercepts M3/M5 for immediate knife state tracking.
        """
        u = cmd.strip().upper()
        if u.startswith('M5'):
            self.knife_down = False; self.knife_force = 0
            self.knife_changed.emit(False, 0)
        elif u.startswith('M3'):
            m = M3_RE.search(cmd)
            f = max(0, min(1000, int(float(m.group(1))) if m else 1000))
            self.knife_down = True; self.knife_force = f
            self.knife_changed.emit(True, f)

        line = cmd.strip() + '\n'
        self._cmd_q.append(line)
        self._flush()

    def send_rt(self, byte):
        """Send a real-time single-byte command immediately (not queued, not counted)."""
        if self._port.isOpen():
            self._port.write(bytes([byte]))

    def feed_hold(self):    self.send_rt(0x21)   # '!'
    def cycle_start(self):  self.send_rt(0x7E)   # '~'
    def cancel_jog(self):   self.send_rt(0x85)

    def reset(self):
        """Ctrl-X — clears all queues and resets GRBL."""
        self._cmd_q.clear()
        self._sent_lens.clear()
        self._in_flight = 0
        self.send_rt(0x18)
        self.knife_down = False; self.knife_force = 0
        self.knife_changed.emit(False, 0)

    def jog(self, axis, dist, speed):
        self.send('$J=G91 G21 %s%.4f F%.1f' % (axis, dist, speed))

    def knife_down_cmd(self, force=1000):
        self.send('M3 S%d' % max(0, min(1000, force)))

    def knife_up_cmd(self):
        self.send('M5')

    # ── Queue flush ───────────────────────────────────────────────────────────

    def _flush(self):
        """
        Write as many pending lines as will fit in GRBL's RX buffer.
        Called every time a new command is queued or an 'ok' frees space.
        """
        while self._cmd_q:
            line = self._cmd_q[0]
            n    = len(line.encode())
            if self._in_flight + n > RX_BUFFER_SIZE:
                break                      # won't fit — wait for more 'ok's
            self._cmd_q.popleft()
            self._sent_lens.append(n)      # remember this command's byte count
            self._in_flight += n
            self._port.write(line.encode())

    # ── Receive ───────────────────────────────────────────────────────────────

    def _on_data(self):
        self._rx_buf += self._port.readAll().data().decode('utf-8', errors='replace')
        while '\n' in self._rx_buf:
            line, self._rx_buf = self._rx_buf.split('\n', 1)
            line = line.strip()
            if line:
                self._parse(line)

    def _parse(self, line):
        self.raw_received.emit(line)

        # Status report — real-time, not queued, no 'ok'
        if line.startswith('<'):
            m = STATUS_RE.match(line)
            if m:
                ns = m.group(1)
                x, y, z = float(m.group(2)), float(m.group(3)), float(m.group(4))
                fr = float(m.group(5)) if m.group(5) else self.feed[0]
                sp = float(m.group(6)) if m.group(6) else self.feed[1]
                if ns != self.state:
                    self.state = ns; self.state_changed.emit(ns)
                self.mpos = (x, y, z)
                self.position_changed.emit(x, y, z)
                if (fr, sp) != self.feed:
                    self.feed = (fr, sp); self.feed_changed.emit(fr, sp)
                if m.group(6) is not None:
                    d = sp > 0
                    if d != self.knife_down:
                        self.knife_down = d
                        self.knife_force = int(sp) if d else 0
                        self.knife_changed.emit(d, self.knife_force)
            return

        # 'ok' — one command has been accepted and processed by GRBL.
        # Free exactly the bytes that command used.
        if line == 'ok':
            if self._sent_lens:
                freed = self._sent_lens.popleft()
                self._in_flight = max(0, self._in_flight - freed)
            self._flush()           # room freed — try to send next command
            self.ok_received.emit()
            return

        # 'error:N' — command rejected; still frees its buffer slot
        if line.startswith('error:'):
            if self._sent_lens:
                freed = self._sent_lens.popleft()
                self._in_flight = max(0, self._in_flight - freed)
            self._flush()
            self.error_received.emit(line.split(':', 1)[1].strip())
            return

        if line.startswith('ALARM:'):
            self.alarm_received.emit(line)
            self.state = 'Alarm'; self.state_changed.emit('Alarm')
            return

        if line.startswith('[MSG:'):
            self.message_received.emit(line[5:].rstrip(']'))

    def _on_error(self, err):
        if err != QSerialPort.NoError:
            self.disconnect()