# -*- coding: utf-8 -*-
"""MaskInColor 方向验证：Qt.transparent 作为 MaskInColor 应剪掉透明像素"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
app = QApplication(sys.argv)

pix = QPixmap("C:/maomaochongD/Coding/PythonProject/MCHelper/assets/icons/diamond_sword.png")
p48 = pix.scaled(48, 48, Qt.KeepAspectRatio, Qt.FastTransformation)

# MaskInColor：把指定颜色创建为掩码（1=匹配该颜色的像素）
m_in = p48.createMaskFromColor(Qt.transparent, Qt.MaskInColor)
img_in = m_in.toImage()
vals = {}
for y in range(48):
    for x in range(48):
        c = img_in.pixelColor(x, y)
        key = c.red()
        vals[key] = vals.get(key, 0) + 1
print("MaskInColor vals:", vals)
# (1,1) 应为 255（匹配透明→掩码1），剑身应为 0
for x, y in [(1,1),(46,1),(24,24)]:
    print(f"({x},{y})={img_in.pixelColor(x,y).red()}")
