# -*- coding: utf-8 -*-
"""诊断2：直接构造标签项进场景，验证 toPlainText 可读性"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QGraphicsScene
from PySide6.QtGui import QFont

app = QApplication(sys.argv)

scene = QGraphicsScene()
t = scene.addText("hello 世界")
f = QFont()
f.setPointSize(9)
t.setFont(f)

lines = []
lines.append(f"count={len(scene.items())}")
for it in scene.items():
    lines.append(f"type={type(it).__name__} has_attr={hasattr(it, 'toPlainText')} "
                 f"text={getattr(it, 'toPlainText', lambda: '<none>')()!r}")

with open(r"C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\debug2_result.txt",
          "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
