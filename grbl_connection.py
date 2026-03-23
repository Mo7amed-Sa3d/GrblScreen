# grbl_connection.py
# Async GRBL serial communication using QSerialPort.
#
# Knife status fix:
#   In GRBL laser mode ($32=1) the FS spindle field is often omitted from
#   status reports when spindle speed is 0, so we cannot rely on it.
#   Instead, knife state is tracked CLIENT-SIDE: every time M3 or M5 is
#   sent we emit knife_changed immediately. The status FS field is used
#   as a secondary confirmation when present.

import re
from collections import deque
from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from PyQt5.QtSerialPort import QSerialPort, QSerialPortInfo

STATUS_INTERVAL = 200    # ms between '?' polls
RX_BUFFER_SIZE  = 128    # GRBL serial RX buffer bytes

STATE_MAP = {
    'Idle':         ('IDLE',    '#27ae60'),
    'Run':          ('RUNNING', '#2980b9'),
    'Hold':         ('HOLD',    '#f39c12'),
    'Hold:0':       ('HOLD',    '#f39c12'),
    'Hold:1':       ('HOLD',    '#f39c12'),
    'Home':         ('HOMING',  '#9b59b6'),
    'Alarm':        ('ALARM',   '#e74c3c'),
    'Door':         ('DOOR',    '#e74c3c'),
    'Check':        ('CHECK',   '#f39c12'),
    'Sleep':        ('SLEEP',   '#7f8c8d'),
    'Jog':          ('JOG',     '#2980b9'),
    'Disconnected': ('NO CONN', '#7f8c8d'),
}

STATUS_RE = re.compile(
    r'<(\w+)(?::\d+)?\|MPos:([-\d.]+),([-\d.]+),([-\d.]+)'
    r'(?:\|FS:([\d.]+),([\d.]+))?'
)

# Matches M3 with optional S word, e.g. "M3 S1000" or "M3S500"
M3_RE = re.compile(r'\bM3\b.*?S\s*([\d.]+)', re.IGNORECASE)


class GrblConnection(QObject):
    # ── Signals ───────────────────────────────────────────────────────────────
    connected        = pyqtSignal()
    disconnected     = pyqtSignal()
    state_changed    = pyqtSignal(str)
    position_changed = pyqtSignal(float, float, float)
    feed_changed     = pyqtSignal(float, float)
    knife_changed    = pyqtSignal(bool, int)   # (is_down, force 0-1000)
    message_received = pyqtSignal(str)
    alarm_received   = pyqtSignal(str)
    ok_received      = pyqtSignal()
    error_received   = pyqtSignal(str)
    raw_received     = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._port      = QSerialPort(self)
        self._rx_buf    = ''
        self._cmd_q     = deque()
        self._in_flight = 0

        # Knife state — tracked from sent commands
        self.knife_down  = False
        self.knife_force = 0      # 0-1000

        self._port.readyRead.connect(self._on_data)
        self._port.errorOccurred.connect(self._on_error)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(STATUS_INTERVAL)
        self._poll_timer.timeout.connect(self._send_status_request)

        self.state = 'Disconnected'
        self.mpos  = (0.0, 0.0, 0.0)
        self.feed  = (0.0, 0.0)

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self, port_name, baud=115200):
        if self._port.isOpen():
            self._port.close()
        self._port.setPortName(port_name)
        self._port.setBaudRate(baud)
        if self._port.open(QSerialPort.ReadWrite):
            self._poll_timer.start()
            self.state = 'Idle'
            self.connected.emit()
            return True
        return False

    def disconnect(self):
        self._poll_timer.stop()
        if self._port.isOpen():
            self._port.close()
        self.state = 'Disconnected'
        self.disconnected.emit()

    def is_connected(self):
        return self._port.isOpen()

    @staticmethod
    def available_ports():
        return [(i.portName(), i.description())
                for i in QSerialPortInfo.availablePorts()]

    # ── Sending ───────────────────────────────────────────────────────────────

    def send(self, cmd):
        """Queue a G-code line. Intercepts M3/M5 for immediate knife tracking."""
        upper = cmd.strip().upper()

        # Track knife state the moment the command is queued —
        # don't wait for the status report which may never include spindle.
        if upper.startswith('M5'):
            self.knife_down  = False
            self.knife_force = 0
            self.knife_changed.emit(False, 0)

        elif upper.startswith('M3'):
            m = M3_RE.search(cmd)
            force = int(float(m.group(1))) if m else 1000
            force = max(0, min(1000, force))
            self.knife_down  = True
            self.knife_force = force
            self.knife_changed.emit(True, force)

        line = cmd.strip() + '\n'
        self._cmd_q.append(line)
        self._flush_queue()

    def send_realtime(self, byte):
        if self._port.isOpen():
            self._port.write(bytes([byte]))

    def feed_hold(self):   self.send_realtime(0x21)
    def cycle_start(self): self.send_realtime(0x7E)
    def cancel_jog(self):  self.send_realtime(0x85)

    def reset(self):
        self._cmd_q.clear()
        self._in_flight = 0
        self.send_realtime(0x18)
        # Reset also raises the knife in GRBL, so track it
        self.knife_down  = False
        self.knife_force = 0
        self.knife_changed.emit(False, 0)

    def jog(self, axis, dist, speed):
        self.send('$J=G91 G21 %s%.4f F%.1f' % (axis, dist, speed))

    def knife_down_cmd(self, force=1000):
        """Convenience: send M3 with given force (0-1000)."""
        self.send('M3 S%d' % max(0, min(1000, force)))

    def knife_up_cmd(self):
        """Convenience: send M5."""
        self.send('M5')

    # ── Queue management ──────────────────────────────────────────────────────

    def _flush_queue(self):
        while self._cmd_q:
            line = self._cmd_q[0]
            if self._in_flight + len(line) > RX_BUFFER_SIZE:
                break
            self._cmd_q.popleft()
            self._in_flight += len(line)
            self._port.write(line.encode())

    def _send_status_request(self):
        if self._port.isOpen():
            self._port.write(b'?')

    # ── Receive parsing ───────────────────────────────────────────────────────

    def _on_data(self):
        data = self._port.readAll().data().decode('utf-8', errors='replace')
        self._rx_buf += data
        while '\n' in self._rx_buf:
            line, self._rx_buf = self._rx_buf.split('\n', 1)
            line = line.strip()
            if line:
                self._parse_line(line)

    def _parse_line(self, line):
        self.raw_received.emit(line)

        if line.startswith('<'):
            m = STATUS_RE.match(line)
            if m:
                new_state = m.group(1)
                x = float(m.group(2))
                y = float(m.group(3))
                z = float(m.group(4))
                feed_rate = float(m.group(5)) if m.group(5) else self.feed[0]
                spindle   = float(m.group(6)) if m.group(6) else self.feed[1]

                if new_state != self.state:
                    self.state = new_state
                    self.state_changed.emit(new_state)

                self.mpos = (x, y, z)
                self.position_changed.emit(x, y, z)

                if (feed_rate, spindle) != self.feed:
                    self.feed = (feed_rate, spindle)
                    self.feed_changed.emit(feed_rate, spindle)

                # Secondary knife confirmation from status FS field.
                # Only update if it disagrees with our tracked state —
                # this handles cases where another sender changed knife state.
                if m.group(6) is not None:
                    status_down = spindle > 0
                    if status_down != self.knife_down:
                        self.knife_down  = status_down
                        self.knife_force = int(spindle) if status_down else 0
                        self.knife_changed.emit(self.knife_down, self.knife_force)
            return

        if line == 'ok':
            self._in_flight = max(0, self._in_flight - 1)
            self._flush_queue()
            self.ok_received.emit()
            return

        if line.startswith('error:'):
            self._in_flight = max(0, self._in_flight - 1)
            self._flush_queue()
            self.error_received.emit(line.split(':', 1)[1].strip())
            return

        if line.startswith('ALARM:'):
            self.alarm_received.emit(line)
            self.state = 'Alarm'
            self.state_changed.emit('Alarm')
            return

        if line.startswith('[MSG:'):
            self.message_received.emit(line[5:].rstrip(']'))
            return

    def _on_error(self, error):
        if error != QSerialPort.NoError:
            self.disconnect()