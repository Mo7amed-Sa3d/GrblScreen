# pages/console_page.py
# Raw G-code console — send commands and see all responses

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QPlainTextEdit
)
from PyQt5.QtCore    import Qt, pyqtSlot
from PyQt5.QtGui     import QTextCursor, QColor


class ConsolePage(QWidget):
    def __init__(self, grbl, parent=None):
        super().__init__(parent)
        self._grbl = grbl
        self._build_ui()
        self._grbl.raw_received.connect(self._on_line)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 8)
        root.setSpacing(8)

        title = QLabel('Console')
        title.setObjectName('pageTitle')
        root.addWidget(title)

        # Log output
        self._log = QPlainTextEdit()
        self._log.setObjectName('console')
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        root.addWidget(self._log, 1)

        # Input row
        inp_row = QHBoxLayout()

        self._input = QLineEdit()
        self._input.setPlaceholderText('Enter G-code command…')
        self._input.returnPressed.connect(self._send)
        inp_row.addWidget(self._input, 1)

        btn_send = QPushButton('Send')
        btn_send.setMinimumHeight(44)
        btn_send.setProperty('role', 'primary')
        btn_send.clicked.connect(self._send)
        inp_row.addWidget(btn_send)

        btn_clear = QPushButton('Clear')
        btn_clear.setMinimumHeight(44)
        btn_clear.clicked.connect(self._log.clear)
        inp_row.addWidget(btn_clear)

        root.addLayout(inp_row)

        # Quick command buttons
        quick = QHBoxLayout()
        for label, cmd in [
            ('?', '?'), ('$H', '$H'), ('$X', '$X'),
            ('$$', '$$'), ('$#', '$#'), ('$I', '$I'),
        ]:
            b = QPushButton(label)
            b.setMinimumHeight(40)
            b.clicked.connect(lambda checked, c=cmd: self._grbl.send(c))
            quick.addWidget(b)
        quick.addStretch()
        root.addLayout(quick)

    def _send(self):
        cmd = self._input.text().strip()
        if cmd:
            self._append('>> ' + cmd, '#a0c4ff')
            self._grbl.send(cmd)
            self._input.clear()

    @pyqtSlot(str)
    def _on_line(self, line):
        if line.startswith('<'):
            self._append(line, '#555')    # status reports dimmed
        elif line.startswith('ALARM'):
            self._append(line, '#e74c3c')
        elif line.startswith('error'):
            self._append(line, '#f39c12')
        elif line == 'ok':
            self._append(line, '#27ae60')
        else:
            self._append(line, '#58d68d')

    def _append(self, text, colour='#e0e0e0'):
        self._log.moveCursor(QTextCursor.End)
        html = '<span style="color:%s;">%s</span>' % (
            colour, text.replace('<', '&lt;').replace('>', '&gt;')
        )
        self._log.appendHtml(html)
        self._log.moveCursor(QTextCursor.End)
