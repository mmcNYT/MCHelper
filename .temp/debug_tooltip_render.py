# -*- coding: utf-8 -*-
"""调试：offscreen 下 _GameTooltip grab 渲染排查"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor

app = QApplication(sys.argv)

from Utils.enchanted_item_card import TOOLTIP_HEADER, TOOLTIP_TEXT, TOOLTIP_BG_TOP
from Utils.anvil_steps_tree import AnvilStepsTree, _GameTooltip

tree = AnvilStepsTree()
tree.resize(760, 560)
tree.show()
app.processEvents()

tp = tree._tooltip
print("tooltip 初始可见性:", tp.isVisible(), "hidden:", tp.isHidden())
print("viewport 大小:", tree.viewport().width(), tree.viewport().height())

tree.show_tooltip([("附魔书", TOOLTIP_HEADER), ("锋利 V", TOOLTIP_TEXT)])
app.processEvents()
print("popup 后 hidden:", tp.isHidden())
print("tooltip 几何:", tp.geometry(), "尺寸:", tp.width(), "x", tp.height())

img = tp.grab().toImage()
print("grab 尺寸:", img.width(), "x", img.height())
colors = {}
for y in range(img.height()):
    for x in range(img.width()):
        c = img.pixelColor(x, y).name()
        colors[c] = colors.get(c, 0) + 1
top = sorted(colors.items(), key=lambda kv: -kv[1])[:6]
print("颜色分布 top6:", top)

# 手动直接 render 到 QPixmap 再看
from PySide6.QtGui import QPixmap, QPainter
pm = QPixmap(tp.size())
p = QPainter(pm)
tp.render(p)
p.end()
img2 = pm.toImage()
colors2 = {}
for y in range(img2.height()):
    for x in range(img2.width()):
        c = img2.pixelColor(x, y).name()
        colors2[c] = colors2.get(c, 0) + 1
top2 = sorted(colors2.items(), key=lambda kv: -kv[1])[:6]
print("render() 颜色分布 top6:", top2)
print("期望背景:", QColor(16, 0, 16, 240).name())
