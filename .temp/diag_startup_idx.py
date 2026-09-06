# -*- coding: utf-8 -*-
"""诊断：主窗口启动后 tabWidget.currentIndex 的实际值与各阶段窗口尺寸"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

out = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "diag_startup_idx.txt"), "w", encoding="utf-8")

app = QApplication(sys.argv)
try:
    from main_window import MainWindow
    win = MainWindow()

    out.write(f"构造完成(未show) currentIndex={win.tabWidget.currentIndex()} count={win.tabWidget.count()}\n")
    out.write(f"构造完成(未show) 窗口尺寸={win.width()}x{win.height()}\n")

    win.show()
    for _ in range(10):
        app.processEvents()
    out.write(f"show后 currentIndex={win.tabWidget.currentIndex()} count={win.tabWidget.count()}\n")
    out.write(f"show后 窗口尺寸={win.width()}x{win.height()}\n")

    w0 = win.tabWidget.widget(0)
    out.write(f"show后 工具页0尺寸={w0.width()}x{w0.height()}\n")

    # 模拟 singleShot(0) 之后再读一次
    from PySide6.QtCore import QTimer
    fired = []
    QTimer.singleShot(0, lambda: fired.append(("singleShot", win.tabWidget.currentIndex(), win.width(), win.height())))
    for _ in range(10):
        app.processEvents()
    out.write(f"singleShot触发: {fired}\n")

    out.write("OK\n")
except Exception as e:
    import traceback
    out.write("EXCEPTION:\n" + traceback.format_exc() + "\n")

out.close()
