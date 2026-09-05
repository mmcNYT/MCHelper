# -*- coding: utf-8 -*-
"""对比 alpha 掩码与启发式掩码的边界差异（启发式把剑柄/剑尖外深色像素并入前景）"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainterPath, QRegion, QPainter, QColor
app = QApplication(sys.argv)

pix = QPixmap("C:/maomaochongD/Coding/PythonProject/MCHelper/assets/icons/diamond_sword.png")
p48 = pix.scaled(48, 48, Qt.KeepAspectRatio, Qt.FastTransformation)
alpha_mask = p48.createMaskFromColor(Qt.transparent, Qt.MaskOutColor)
heuristic = alpha_mask.createHeuristicMask()
himg = heuristic.toImage()
aimg = alpha_mask.toImage()
diff = 0
for y in range(48):
    for x in range(48):
        hv = himg.pixelColor(x, y).red() > 127
        av = aimg.pixelColor(x, y).red() > 127  # BinaryMask 转灰度后用红色通道判断
        if hv != av:
            diff += 1
print(f"heuristic vs alpha mask diff pixels = {diff}")
