# -*- coding: utf-8 -*-
"""探针4：二分定位——裸列表+真实卡片，分别测 drop事件触发 与 直接调用 两种路径"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from PySide6.QtWidgets import QApplication, QListWidgetItem
from PySide6.QtCore import Qt, QMimeData
app = QApplication(sys.argv)

from Utils.card_list_widget import CardListWidget
from Utils.enchanted_item_card import EnchantedItemCard
from PySide6.QtGui import QDragEnterEvent, QDropEvent

def build():
    w = CardListWidget()
    w.resize(500, 300)
    w.show()
    for name, ench in (("剑", "sharpness"), ("弓", "power"), ("镐", "efficiency")):
        item = QListWidgetItem(name)
        w.addItem(item)
        w.setItemWidget(item, EnchantedItemCard(name, [{"id": ench, "name": ench, "level": 3}]))
    app.processEvents()
    return w

# 路径 A：drop 事件触发
wa = build()
mime = QMimeData()
mime.setData("application/x-card-reorder", b"1")
pos = wa.visualItemRect(wa.item(0)).center()
app.sendEvent(wa.viewport(), QDragEnterEvent(pos, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier))
app.sendEvent(wa.viewport(), QDropEvent(pos, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier))
app.processEvents()
print("A drop事件触发:", [wa.itemWidget(wa.item(i)) is not None for i in range(3)],
      "顺序:", [wa.item(i).text() for i in range(3)])

# 路径 B：直接调用 _move_item
wb = build()
wb._move_item(1, 0)
app.processEvents()
print("B 直接调用  :", [wb.itemWidget(wb.item(i)) is not None for i in range(3)],
      "顺序:", [wb.item(i).text() for i in range(3)])
