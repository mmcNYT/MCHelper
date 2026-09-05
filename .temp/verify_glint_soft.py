# -*- coding: utf-8 -*-
"""验证加法混合光效效果：与不带光效的静态原图对比亮度，光效应只提亮不压暗"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import Qt
app = QApplication(sys.argv)
from Utils.enchanted_item_card import _GlintIcon

enchants = [{"id": "sharpness", "name": "锋利", "level": 5}]
icon = _GlintIcon("剑", 48)
icon._advance()
icon._advance()
app.processEvents()

# 静态参照：无光效静态图标（同尺寸物品纹理）
ref = QLabel()
ref.setPixmap(icon._item_pix)
ref.setFixedSize(48, 48)
ref_img = ref.grab().toImage()

img = icon.grab().toImage()

# 物品不透明像素：逐像素对比亮度变化
brighter = darker = unchanged = 0
deltas = []
tex_img = icon._item_pix.toImage()
for y in range(48):
    for x in range(48):
        if tex_img.pixelColor(x, y).alpha() == 0:
            continue
        cr, cg = img.pixelColor(x, y), ref_img.pixelColor(x, y)
        lum_a = 0.299 * cr.red() + 0.587 * cr.green() + 0.114 * cr.blue()
        lum_g = 0.299 * cg.red() + 0.587 * cg.green() + 0.114 * cg.blue()
        d = lum_a - lum_g
        if d > 1:
            brighter += 1
            deltas.append(d)
        elif d < -1:
            darker += 1
        else:
            unchanged += 1

n = brighter + darker + unchanged
print(f"物品像素总数 {n}：提亮 {brighter}（{brighter*100//n}%），压暗 {darker}，不变 {unchanged}")
if deltas:
    deltas.sort()
    print(f"提亮幅度：中位 {deltas[len(deltas)//2]:.1f}，最大 {deltas[-1]:.1f}")
# 加法混合核心特征：不允许压暗
assert darker == 0, f"加法混合不应压暗任何像素，压暗 {darker} 个"
assert brighter > n * 0.1, f"应有明显提亮范围（实际 {brighter}/{n}）"
# 透明区仍然零光效（复用剪辑验证）
glint_leak = 0
for y in range(48):
    for x in range(48):
        if tex_img.pixelColor(x, y).alpha() == 0:
            c = img.pixelColor(x, y)
            if c.blue() > c.green() + 40:
                glint_leak += 1
assert glint_leak == 0, f"透明区光效泄漏 {glint_leak} 处"
print(f"透明区泄漏检查：0 处 ✓")
print("验证通过：光效为提亮型微光，不压暗物品原色")
