# -*- coding: utf-8 -*-
"""探针5：真实 QDrag.exec_() 流程验证——在拖放阻塞循环内程序化推进 drop"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from PySide6.QtWidgets import QApplication, QListWidgetItem
from PySide6.QtCore import Qt, QMimeData, QTimer, QPoint
app = QApplication(sys.argv)

from Utils.card_list_widget import CardListWidget
from Utils.enchanted_item_card import EnchantedItemCard
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QDrag

w = CardListWidget()
w.resize(500, 300)
w.show()
for name, ench in (("剑", "sharpness"), ("弓", "power"), ("镐", "efficiency")):
    item = QListWidgetItem(name)
    w.addItem(item)
    w.setItemWidget(item, EnchantedItemCard(name, [{"id": ench, "name": ench, "level": 3}]))
app.processEvents()

mime = QMimeData()
mime.setData("application/x-card-reorder", b"1")
pos = w.visualItemRect(w.item(0)).center()

# 在 exec_ 阻塞的事件循环里向 viewport 投递 enter+drop
def do_drop():
    app.sendEvent(w.viewport(), QDragEnterEvent(pos, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier))
    app.sendEvent(w.viewport(), QDropEvent(pos, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier))

QTimer.singleShot(0, do_drop)
drag = QDrag(w)
drag.setMimeData(mime)
result = drag.exec_(Qt.MoveAction)  # 真实拖放循环
app.processEvents()
print("exec_ 返回:", result)
print("真实拖放后绑定:", [w.itemWidget(w.item(i)) is not None for i in range(3)])
print("顺序:", [w.item(i).text() for i in range(3)])
