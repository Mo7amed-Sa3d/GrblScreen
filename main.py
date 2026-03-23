#!/usr/bin/env python3
# main.py — Cutter Screen entry point

import sys
import os

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore    import Qt
from PyQt5.QtGui     import QFont

from grbl_connection import GrblConnection
from main_window     import MainWindow

STYLE_DIR = os.path.join(os.path.dirname(__file__), 'styles')


def load_stylesheet(app, name='dark.qss'):
    path = os.path.join(STYLE_DIR, name)
    try:
        with open(path) as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        print('Warning: stylesheet not found at', path)


def main():
    os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')

    app = QApplication(sys.argv)
    app.setApplicationName('CutterScreen')
    app.setFont(QFont('DejaVu Sans', 11))

    # Start in dark mode
    load_stylesheet(app, 'dark.qss')

    grbl = GrblConnection()
    win  = MainWindow(grbl, app)   # app passed so MainWindow can swap stylesheet
    win.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()