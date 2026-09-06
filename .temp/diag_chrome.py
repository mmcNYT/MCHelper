# -*- coding: utf-8 -*-
"""诊断脚本：检查窗口 chrome 构成，定位高度偏差来源。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

def main():
    app = QApplication(sys.argv)
    from main_window import MainWindow

    win = MainWindow()
    win.move(60, 60)
    win.show()
    for _ in range(5):
        app.processEvents()

    lines = []

    def log(s):
        lines.append(s)

    log(f"初始(未选tab): frame={win.frameGeometry().width()}x{win.frameGeometry().height()} "
        f"client={win.width()}x{win.height()} "
        f"menuBar={win.menuBar().height()} tabW={win.tabWidget.width()}x{win.tabWidget.height()}")

    win.tabWidget.setCurrentIndex(1)
    for _ in range(8):
        app.processEvents()

    w1 = win.tabWidget.widget(1)
    log(f"切附魔后: frame={win.frameGeometry().width()}x{win.frameGeometry().height()} "
        f"client={win.width()}x{win.height()} menuBar={win.menuBar().height()} "
        f"tabWidget={win.tabWidget.width()}x{win.tabWidget.height()} "
        f"tool={w1.width()}x{w1.height()}")

    log(f"  chrome_w(frame-tool) = {win.frameGeometry().width() - w1.width()}")
    log(f"  chrome_h(frame-tool) = {win.frameGeometry().height() - w1.height()}")
    log(f"  分解: client-frame_h={win.height() - win.frameGeometry().height()} "
        f"menuBar_h={win.menuBar().height()} "
        f"tabWidget_h-tool_h={win.tabWidget.height() - w1.height()}")

    win.tabWidget.setCurrentIndex(0)
    for _ in range(8):
        app.processEvents()

    w0 = win.tabWidget.widget(0)
    log(f"切备份后: frame={win.frameGeometry().width()}x{win.frameGeometry().height()} "
        f"tool={w0.width()}x{w0.height()} "
        f"chrome_h={win.frameGeometry().height() - w0.height()}")

    report = "\n".join(lines)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "diag_chrome_result.txt"),
              "w", encoding="utf-8") as f:
        f.write(report + "\n")


if __name__ == "__main__":
    main()
