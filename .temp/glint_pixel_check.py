# -*- coding: utf-8 -*-
"""流光视觉像素验证：抓取带流光方框相邻两帧，对比同位置像素亮度变化"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint

app = QApplication(sys.argv)

from Utils.anvil_steps_tree import AnvilStepsTree
from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilOptimizer, build_items_from_cards

dm = DataManager()
opt = AnvilOptimizer(dm)


def card(n, *e):
    return {"item_name": n,
            "enchants": [{"id": x[0], "name": x[1], "level": x[2]} for x in e]}


cards = [card("剑", ("sharpness", "锋利", 5)),
         card("附魔书", ("unbreaking", "耐久", 3))]
plan = opt.optimize(build_items_from_cards(cards))

t = AnvilStepsTree()
t.resize(658, 518)
t.show_plan(plan, dm, mode="steps")

# 找到剑框（第一个框）在视口中的位置
box = t.boxes()[0]
vp = t.viewport()

def grab_icon_img():
    """抓取剑框图标区域的图像（相对框中心）"""
    from PySide6.QtGui import QImage
    scene_pos = box.scenePos()
    view_pos = t.mapFromScene(scene_pos)
    # 图标区域在框内偏移 ((68-48)//2, (60-48)//2) = (10, 6)
    origin = view_pos + QPoint(10, 6)
    img = vp.grab().toImage()
    return img.copy(origin.x(), origin.y(), 48, 48)

img1 = grab_icon_img()
for _ in range(6):           # 推进 6 帧（offset 0→6）
    box.advance_glint()
    app.processEvents()
img2 = grab_icon_img()

# 对比两帧同位置像素：流光滚动 → 图标不透明区应有像素变亮/变暗
diff = 0
w, h = img1.width(), img1.height()
for y in range(h):
    for x in range(w):
        p1, p2 = img1.pixelColor(x, y), img2.pixelColor(x, y)
        if abs(p1.red() - p2.red()) + abs(p1.green() - p2.green()) \
                + abs(p1.blue() - p2.blue()) > 10:
            diff += 1

# 另存预览图（视觉参考）
vp.grab().save(r"C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\preview_glint_box.png")

with open(r"C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\glint_pixel_result.txt",
          "w", encoding="utf-8") as f:
    f.write(f"图标区 48x48={w*h}px，两帧差异像素数={diff} "
            f"({'流光在滚动 ✓' if diff > 0 else '无变化 ✗'})")
