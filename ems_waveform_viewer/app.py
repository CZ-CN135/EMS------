# -*- coding: utf-8 -*-
import sys
import os

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "ems_waveform_viewer"

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from .utils import resource_path
from .constants import ICON_FILE
from .ui.main_window import WaveformViewer

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # ★ 设置全局应用图标
    icon_path = resource_path(ICON_FILE)
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    else:
        print(f"⚠️ 未找到图标文件: {icon_path}")

    win = WaveformViewer()
    win.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())