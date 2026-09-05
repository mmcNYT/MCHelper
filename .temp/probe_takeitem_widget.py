# -*- coding: utf-8 -*-
"""探测：QListWidget takeItem 后重新 insertItem，itemWidget 是否存活"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QLabel
app = QApplication(sys.argv)

w = QListWidget()
w.resize(400, 100)
w.show()
item = QListWidgetItem("A")
w.addItem(item)
lbl = QLabel("CARD_A")
w.setItemWidget(item, lbl)
app.processEvents()

print("before take: itemWidget =", w.itemWidget(item))
taken = w.takeItem(0)
app.processEvents()
print("after take : itemWidget =", w.itemWidget(taken), "| lbl.parent() =", lbl.parent())
w.insertItem(0, taken)
app.processEvents()
print("after insert: itemWidget =", w.itemWidget(taken), "| lbl.parent() =", lbl.parent())
print("lbl is alive:", lbl.isVisible() if lbl.parent() else "no parent")
