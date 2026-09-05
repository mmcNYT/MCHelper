# -*- coding: utf-8 -*-
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout
from PySide6.QtGui import QColor
app = QApplication(sys.argv)
from Utils.enchanted_item_card import EnchantedItemCard

w = QWidget()
w.setAutoFillBackground(True)
pal = w.palette()
pal.setColor(w.backgroundRole(), QColor(40, 40, 45))
w.setPalette(pal)
w.resize(560, 260)
lay = QHBoxLayout(w)
data1 = ("剑", [("sharpness", "锋利", 5), ("unbreaking", "耐久", 3), ("mending", "经验修补", 1), ("looting", "抢夺", 3)])
data2 = ("弓", [("power", "力量", 5), ("flame", "火矢", 1), ("infinity", "无限", 1)])
data3 = ("头盔", [("protection", "保护", 4), ("respiration", "水下呼吸", 3), ("aqua_affinity", "水下速掘", 1)])
for name, enchs in (data1, data2, data3):
    lay.addWidget(EnchantedItemCard(name, [{"id":i,"name":n,"level":l} for i,n,l in enchs]))
w.show()
app.processEvents()
w.grab().save(r"C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\card_preview.png")
print("saved")
