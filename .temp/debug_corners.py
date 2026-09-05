# -*- coding: utf-8 -*-
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
app = QApplication(sys.argv)

pix = QPixmap("C:/maomaochongD/Coding/PythonProject/MCHelper/assets/icons/diamond_sword.png")
p48 = pix.scaled(48, 48, Qt.KeepAspectRatio, Qt.FastTransformation)
pimg = p48.toImage()
print("item texture corners (scaled 48x48):")
for x, y in [(1,1),(46,1),(1,46),(46,46)]:
    c = pimg.pixelColor(x, y)
    print(f"({x},{y}) rgba=({c.red()},{c.green()},{c.blue()},{c.alpha()})")
