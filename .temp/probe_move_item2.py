# -*- coding: utf-8 -*-
"""探针2：完整复现冒烟测试序列，定位 itemWidget 丢失的环节"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from PySide6.QtWidgets import QApplication, QListWidgetItem, QLabel
from PySide6.QtCore import Qt, QPoint, QMimeData
app = QApplication(sys.argv)

from Utils.card_list_widget import CardListWidget

w = CardListWidget()
w.resize(500, 300)
w.show()

def add(name):
    item = QListWidgetItem(name)
    w.addItem(item)
    lbl = QLabel(f"CARD_{name}")
    w.setItemWidget(item, lbl)
    app.processEvents()

# 序列复现：加3 → Del删1 → Backspace删1 → clear → 加3 → 鼠标点击若干 → drop
for n in ("A", "B", "C"):
    add(n)
from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import QEvent
w.setCurrentRow(1)
app.sendEvent(w, QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
w.setCurrentRow(0)
app.sendEvent(w, QKeyEvent(QEvent.KeyPress, Qt.Key_Backspace, Qt.NoModifier))
w.clear_cards()
print("清空后 count:", w.count())
for n in ("A", "B", "C"):
    add(n)
app.processEvents()
print("重建后绑定:", [w.itemWidget(w.item(i)).text() if w.itemWidget(w.item(i)) else None for i in range(3)])

# 模拟点击序列（冒烟测试步骤 3）
from PySide6.QtGui import QMouseEvent
r0 = w.visualItemRect(w.item(0)).center()
r1 = w.visualItemRect(w.item(1)).center()
for pos in (r0, r0, r0, r1):
    app.sendEvent(w.viewport(), QMouseEvent(QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    app.sendEvent(w.viewport(), QMouseEvent(QEvent.MouseButtonRelease, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
app.processEvents()
print("点击后绑定:", [w.itemWidget(w.item(i)).text() if w.itemWidget(w.item(i)) else None for i in range(3)])

# 在 _move_item 里打印 widget 获取情况
orig = w._move_item
def traced_move(from_row, to_row):
    item = w.item(from_row)
    wid = w.itemWidget(item) if item else None
    print(f"_move_item({from_row}->{to_row}): item={item.text() if item else None}, widget={wid.text() if wid else None}")
    return orig(from_row, to_row)
w._move_item = traced_move

# drop 事件
mime = QMimeData()
mime.setData("application/x-card-reorder", b"1")
from PySide6.QtGui import QDropEvent
pos_drop = w.visualItemRect(w.item(0)).center()
drop = QDropEvent(pos_drop, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
app.sendEvent(w.viewport(), drop)
app.processEvents()
print("drop后顺序:", [w.item(i).text() for i in range(3)])
print("drop后绑定:", [w.itemWidget(w.item(i)).text() if w.itemWidget(w.item(i)) else None for i in range(3)])
