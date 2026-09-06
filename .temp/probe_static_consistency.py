# -*- coding: utf-8 -*-
"""探针补充：静态卡片 render vs grab 逐像素一致性（排除流光动画干扰）"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QPainter, QRegion

app = QApplication(sys.argv)

from Tools.tool_EnchantCaculator import EnchantCalculatorWidget

widget = EnchantCalculatorWidget()
widget.resize(658, 518)
widget.show()
app.processEvents()
lst = widget.chosenItemList

# 无附魔卡片（静态 QLabel 图标，无动画）+ 多行附魔 tooltip 框
widget.add_item_card({"item_name": "镐", "enchants": [
    {"id": "efficiency", "name": "效率", "level": 5},
    {"id": "fortune", "name": "时运", "level": 3},
    {"id": "unbreaking", "name": "耐久", "level": 3},
]})
app.processEvents()
card = lst.itemWidget(lst.item(0))


def snapshot_render(w):
    img = QImage(w.size(), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    w.render(p, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
    p.end()
    return img.convertToFormat(QImage.Format_ARGB32)


r_img = snapshot_render(card)
g_img = card.grab().toImage().convertToFormat(QImage.Format_ARGB32)
assert (r_img.width(), r_img.height()) == (g_img.width(), g_img.height())

diff = 0
diff_pts = []
opaque_mismatch = 0
for y in range(r_img.height()):
    for x in range(r_img.width()):
        c1, c2 = r_img.pixelColor(x, y), g_img.pixelColor(x, y)
        if c1.alpha() > 0 and c2.alpha() > 0:
            if (c1.red(), c1.green(), c1.blue()) != (c2.red(), c2.green(), c2.blue()):
                diff += 1
                if len(diff_pts) < 5:
                    diff_pts.append((x, y, (c1.red(), c1.green(), c1.blue()),
                                     (c2.red(), c2.green(), c2.blue())))
        elif (c1.alpha() > 0) != (c2.alpha() > 0):
            opaque_mismatch += 1

print(f"静态卡片尺寸 {r_img.width()}x{r_img.height()}")
print(f"双不透明区 RGB 不一致像素: {diff}")
print(f"透明/不透明判定不一致像素: {opaque_mismatch}")
for pt in diff_pts:
    print("  差异点:", pt)

print("\n补充探针完成")
