# -*- coding: utf-8 -*-
"""诊断剪辑区域失效根因：纹理 alpha / MaskInColor 掩码位 / QRegion 包含关系三对照"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPixmap, QRegion
app = QApplication(sys.argv)

pix = QPixmap("C:/maomaochongD/Coding/PythonProject/MCHelper/assets/icons/diamond_sword.png")
p48 = pix.scaled(48, 48, Qt.KeepAspectRatio, Qt.FastTransformation)
img = p48.toImage()

pts = [(1, 1), (46, 1), (1, 46), (46, 46), (24, 24)]
print("== 纹理像素 ==")
for x, y in pts:
    c = img.pixelColor(x, y)
    print(f"({x},{y}) rgba=({c.red()},{c.green()},{c.blue()},{c.alpha()})")

print("== MaskInColor(Qt.transparent) 掩码图像 ==")
m_in = p48.createMaskFromColor(Qt.transparent, Qt.MaskInColor)
mi = m_in.toImage()
for x, y in pts:
    print(f"({x},{y}) red={mi.pixelColor(x, y).red()}")

print("== 掩码值分布与透明像素匹配统计 ==")
vals = {}
total_t = bad_t = 0
for y in range(48):
    for x in range(48):
        v = mi.pixelColor(x, y).red()
        vals[v] = vals.get(v, 0) + 1
        if img.pixelColor(x, y).alpha() == 0:
            total_t += 1
            if v != 255:
                bad_t += 1
print("mask vals:", vals)
print(f"纹理透明像素共 {total_t}，其中掩码值!=255（未匹配）的 {bad_t} 个")

print("== QRegion(掩码) 包含关系 ==")
r = QRegion(m_in)
br = r.boundingRect()
print("bounding:", br.x(), br.y(), br.width(), br.height())
for x, y in pts:
    print(f"({x},{y}) in QRegion(mask): {r.contains(QPoint(x, y))}")

print("== QRegion(全图) - QRegion(掩码) 包含关系 ==")
sub = QRegion(0, 0, 48, 48) - r
for x, y in pts:
    print(f"({x},{y}) in full-mask: {sub.contains(QPoint(x, y))}")
