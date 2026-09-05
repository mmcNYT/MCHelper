# -*- coding: utf-8 -*-
"""探针：隔离 _move_item 的 itemWidget 重绑问题（不经拖放事件）"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from PySide6.QtWidgets import QApplication, QListWidgetItem, QLabel
from PySide6.QtCore import Qt
app = QApplication(sys.argv)

from Utils.card_list_widget import CardListWidget

w = CardListWidget()
w.resize(400, 120)
w.show()
labels = []
for name in ("A", "B", "C"):
    item = QListWidgetItem(name)
    w.addItem(item)
    lbl = QLabel(f"CARD_{name}")
    w.setItemWidget(item, lbl)
    labels.append(lbl)
app.processEvents()

print("移动前:", [w.itemWidget(w.item(i)).text() for i in range(3)])
ok = w._move_item(1, 0)   # B 移到 A 之前
app.processEvents()
print("moved:", ok)
print("移动后顺序:", [w.item(i).text() for i in range(3)])
print("移动后绑定:", [w.itemWidget(w.item(i)).text() if w.itemWidget(w.item(i)) else None for i in range(3)])
print("labels 存活:", [lbl.parent() is not None for lbl in labels])
