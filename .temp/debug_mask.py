# -*- coding: utf-8 -*-
"""钻石剑纹理的深色像素是否被启发式掩码误判为前景"""
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
heuristic = alpha_mask.createHeuristicMask()
himg = heuristic.toImage()
# 掩码中白色=前景（绘制光效），黑色=背景（被剪掉）
for x, y in [(1,1),(46,1),(1,46),(46,46)]:
    c = himg.pixelColor(x, y)
    print(f"({x},{y}) mask gray={c.red()} (255=前景/光效区, 0=背景/剪掉)")
