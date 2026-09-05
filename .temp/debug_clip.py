# -*- coding: utf-8 -*-
"""验证 MaskInColor 反转掩码 + clipPath 剪辑后透明区实际渲染颜色"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainterPath, QRegion, QPainter, QTransform
app = QApplication(sys.argv)
from Utils.enchanted_item_card import _GlintIcon

icon = _GlintIcon("剑", 48)
for _ in range(6):
    icon._advance()
    app.processEvents()
img = icon.grab().toImage()
# 四角（1,1)/(46,46) 在物品纹理中 alpha=0 → 光效应被剪掉 → 应渲染为控件背景（透明/灰）
for x, y in [(1,1),(46,1),(1,46),(46,46)]:
    c = img.pixelColor(x, y)
    print(f"({x},{y}) rgba=({c.red()},{c.green()},{c.blue()},{c.alpha()})")
