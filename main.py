#!/usr/bin/env python3
# main.py

import sys, os
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui     import QFont
from PyQt5.QtCore    import Qt

from grbl_connection import GrblConnection
from main_window     import MainWindow


def main():
    # Portrait display rotation for BTT TFT70 DSI
    os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')

    app = QApplication(sys.argv)
    app.setApplicationName('CutterScreen')
    app.setFont(QFont('DejaVu Sans', 12))

    # Load stylesheet
    qss = os.path.join(os.path.dirname(__file__), 'style.qss')
    try:
        with open(qss) as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print('Warning: style.qss not found')

    grbl = GrblConnection()
    win  = MainWindow(grbl)
    win.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()