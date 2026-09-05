# -*- coding: utf-8 -*-
"""冒烟测试：验证拖拽图标的样式（淡灰背景/黑字）与分辨率提升（devicePixelRatio）
拖拽图标仅存在于 EnchantListWidget（从下方列表拖入时）；
DropListWidget 自身项不可拖拽，不再有拖拽图标。
用法：python smoke_test_drag_pixmap.py [scale]  # scale 为模拟的屏幕缩放比，默认 1.0"""
import os
import sys

SCALE = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
if SCALE != 1.0:
    os.environ["QT_SCALE_FACTOR"] = str(SCALE)  # 必须在 QApplication 创建前设置
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication(sys.argv)

from Utils.drop_list_widget import DropListWidget
from Utils.enchant_list_widget import EnchantListWidget

lw = DropListWidget()
elw = EnchantListWidget()
print(f"[scale={SCALE}] 控件 devicePixelRatioF: {elw.devicePixelRatioF():.2f}")

# ---------- 前置：DropListWidget 不应再有拖拽图标方法（拖拽删除已移除） ----------
assert not hasattr(lw, "_create_drag_pixmap"), "DropListWidget 不应再有 _create_drag_pixmap"
assert not hasattr(lw, "logical_center"), "DropListWidget 不应再有 logical_center"
assert not lw.dragEnabled(), "DropListWidget 不应开启 dragEnabled"
print("[前置] DropListWidget 拖拽能力已完全移除 ✓")

text = "锋利 (等级 5)"  # 逻辑宽 = max(120, len*10+30) = 120、高 30

# ---------- 分辨率提升验证（EnchantListWidget） ----------
pix = elw._create_drag_pixmap(text)
dpr = pix.devicePixelRatio()
print(f"[scale={SCALE}] EnchantListWidget pixmap: {pix.width()}x{pix.height()} px, dpr={dpr}")
assert abs(dpr - SCALE) < 0.01, f"pixmap dpr 应约等于屏幕缩放 {SCALE}"
logical_w = max(120, len(text) * 10 + 30)  # 与产品代码同一公式
assert pix.width() == int(logical_w * SCALE) and pix.height() == int(30 * SCALE), \
    f"实际像素应为逻辑尺寸×缩放比，期望 {int(logical_w * SCALE)}x{int(30 * SCALE)}，实际 {pix.width()}x{pix.height()}"

# ---------- 样式验证：淡灰背景 + 黑色文字（全图统计，避免采样点落在字隙） ----------
img = pix.toImage()
dark = gray = white = 0
for y in range(img.height()):
    for x in range(img.width()):
        c = img.pixelColor(x, y)
        if c.alpha() == 0:
            continue  # 圆角外的透明区域
        l = c.lightness()
        if l < 80:
            dark += 1
        elif l >= 245:
            white += 1
        elif l > 180:
            gray += 1
assert dark > 50, f"应存在黑色文字笔画，深色像素仅 {dark}"
assert white == 0, f"不应再有白色文字/像素，白色像素 {white}"
assert gray > dark * 2, f"背景应以淡灰为主（gray={gray} vs dark={dark}）"
print(f"[scale={SCALE}] 样式统计：深色(文字/描边)={dark}，淡灰(背景)={gray}，白色={white} ✓")

# ---------- 热点：逻辑中心 ----------
center = elw.logical_center(pix)
lw_, lh_ = pix.width() / dpr, pix.height() / dpr
from PySide6.QtCore import QPoint
assert center == QPoint(int(lw_) // 2, int(lh_) // 2), f"热点应为中心，实际 {center}"
print(f"[scale={SCALE}] 热点=逻辑中心 {center.x()},{center.y()} ✓")

# ---------- 边界：空/超长文本 ----------
p_empty = elw._create_drag_pixmap("")
p_long = elw._create_drag_pixmap("非常长的附魔名称测试文本" * 5)
assert p_empty.width() > 0 and p_long.width() > 0
print(f"[scale={SCALE}] 空/超长文本边界安全 ✓")

print(f"[scale={SCALE}] 全部断言通过\n")
