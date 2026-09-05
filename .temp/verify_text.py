# -*- coding: utf-8 -*-
"""像素级验证：tooltip 方框文字是否真实渲染（统计深紫背景上的浅色文字像素）"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from Utils.enchanted_item_card import _TooltipBox

box = _TooltipBox("剑", [{"id":"sharpness","name":"锋利","level":5},
                          {"id":"unbreaking","name":"耐久","level":3}])
img = box.grab().toImage()
w, h = img.width(), img.height()
light_px = 0  # 浅色像素（文字）：R>120 且 G>120
for y in range(h):
    for x in range(w):
        c = img.pixelColor(x, y)
        if c.red() > 120 and c.green() > 120:
            light_px += 1
print(f"box {w}x{h}, light(text) pixels = {light_px}")
print("TEXT_OK" if light_px > 50 else "TEXT_MISSING")
