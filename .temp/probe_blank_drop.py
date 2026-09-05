# -*- coding: utf-8 -*-
"""探针6：空白处 drop 的 indexAt 行为——横排 IconMode 下的坑"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from PySide6.QtWidgets import QApplication, QListWidgetItem
from PySide6.QtCore import Qt, QMimeData, QPoint
app = QApplication(sys.argv)

from Utils.card_list_widget import CardListWidget
from PySide6.QtGui import QDropEvent

w = CardListWidget()
w.resize(500, 300)
w.show()
for name in ("A", "B", "C"):
    w.addItem(QListWidgetItem(name))
app.processEvents()

# 用visualItemRect第一项检查左上角起点
first = w.visualItemRect(w.item(0))
print("item0 rect:", first)

# 空白点1：第一项左上方（x=2,y=2，第一项rect之外？）
for label, pt in [("左上(2,2)", QPoint(2, 2)),
                  ("上边缘中点", QPoint(w.viewport().width()//2, 2)),
                  ("右下角-4", QPoint(w.viewport().width()-4, w.viewport().height()-4))]:
    idx = w.indexAt(pt)
    print(f"{label}: indexAt valid={idx.isValid()}, row={idx.row()}")
