# -*- coding: utf-8 -*-
"""alpha 掩码 toImage 后的实际灰度值检查（可能全是 0/255 之外的问题）"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
app = QApplication(sys.argv)

pix = QPixmap("C:/maomaochongD/Coding/PythonProject/MCHelper/assets/icons/diamond_sword.png")
p48 = pix.scaled(48, 48, Qt.KeepAspectRatio, Qt.FastTransformation)
alpha_mask = p48.createMaskFromColor(Qt.transparent, Qt.MaskOutColor)
aimg = alpha_mask.toImage()
print(f"mask format={aimg.format()} size={aimg.width()}x{aimg.height()}")
vals = {}
for y in range(48):
    for x in range(48):
        c = aimg.pixelColor(x, y)
        key = (c.red(), c.green(), c.blue(), c.alpha())
        vals[key] = vals.get(key, 0) + 1
print("mask pixel values:", vals)
