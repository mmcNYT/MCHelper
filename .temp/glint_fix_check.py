# -*- coding: utf-8 -*-
"""验证流光修复：多相位采样图标亮度，检查是否存在周期性亮斑突刺"""
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
box = t.boxes()[0]   # 剑（带附魔）
vp = t.viewport()

view_pos = t.mapFromScene(box.scenePos())
origin = view_pos + QPoint(10, 6)   # 图标区在框内偏移 (10, 6)


def icon_stats():
    img = vp.grab().toImage().copy(origin.x(), origin.y(), 48, 48)
    total = 0
    mx = 0
    for y in range(48):
        for x in range(48):
            p = img.pixelColor(x, y)
            v = p.red() + p.green() + p.blue()
            total += v
            mx = max(mx, v)
    return total / (48 * 48), mx


rows = []
for off in range(0, 48, 4):   # 采样 12 个相位
    box._offset_fast = off
    box._offset_slow = off
    box.update()
    app.processEvents()
    mean, mx = icon_stats()
    rows.append(f"offset={off:2d}  平均亮度={mean:7.2f}  最大亮度={mx:3d}")

with open(r"C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\glint_fix_result.txt",
          "w", encoding="utf-8") as f:
    f.write("\n".join(rows))
