# -*- coding: utf-8 -*-
"""诊断3：QGraphicsSimpleTextItem 的方法读取方式"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QGraphicsScene
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGraphicsSimpleTextItem

app = QApplication(sys.argv)

scene = QGraphicsScene()
item = QGraphicsSimpleTextItem("简单文本 世界")
scene.addItem(item)

lines = [f"count={len(scene.items())}",
         f"type={type(item).__name__}"]
for meth in ("toPlainText", "text"):
    lines.append(f"has {meth}={hasattr(item, meth)}")
try:
    lines.append(f"text()={item.text()!r}")
except Exception as e:
    lines.append(f"text() 异常: {e}")

with open(r"C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\debug3_result.txt",
          "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
