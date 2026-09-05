# -*- coding: utf-8 -*-
"""探针3：裸 CardListWidget + 真实 EnchantedItemCard（含QTimer流光）直接 _move_item"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from PySide6.QtWidgets import QApplication, QListWidgetItem
app = QApplication(sys.argv)

from Utils.card_list_widget import CardListWidget
from Utils.enchanted_item_card import EnchantedItemCard

w = CardListWidget()
w.resize(500, 300)
w.show()
for name, ench in (("剑", "sharpness"), ("弓", "power"), ("镐", "efficiency")):
    item = QListWidgetItem(name)
    w.addItem(item)
    card = EnchantedItemCard(name, [{"id": ench, "name": ench, "level": 3}])
    w.setItemWidget(item, card)
app.processEvents()
print("移动前:", [w.itemWidget(w.item(i)) is not None for i in range(3)])

ok = w._move_item(1, 0)
app.processEvents()
print("moved:", ok)
print("移动后绑定:", [w.itemWidget(w.item(i)) is not None for i in range(3)])
# 进一步看卡片实际父对象
print("卡片父对象:", [type(w.itemWidget(w.item(i)).parent()).__name__ if w.itemWidget(w.item(i)) else None for i in range(3)])
