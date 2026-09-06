# -*- coding: utf-8 -*-
"""生成步骤树实际渲染预览图（offscreen），供用户查看图形化效果"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF

app = QApplication(sys.argv)

from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilOptimizer, AnvilItem, MergeStep, AnvilPlan, AnvilMechanics
from Utils.anvil_steps_tree import AnvilStepsTree, _BOX_W, _BOX_H, _MARGIN, _ROW_H
from Utils.enchanted_item_card import TOOLTIP_HEADER, TOOLTIP_TEXT

dm = DataManager()
opt = AnvilOptimizer(dm)

# 场景 1：5 物品多步树（含剑+3本书，递归嵌套）
tree = AnvilStepsTree()
items = [
    AnvilItem.make("剑", []),
    AnvilItem.make("附魔书", [("sharpness", 5)]),
    AnvilItem.make("附魔书", [("looting", 3)]),
    AnvilItem.make("附魔书", [("unbreaking", 3)]),
    AnvilItem.make("附魔书", [("sweeping_edge", 3)]),
]
plan = opt.optimize(items)
tree.show_plan(plan, dm)
app.processEvents()
tree.grab().save(
    r"C:\Users\NYT\.local\share\TeleAgent\TeleAgent的工作空间\.temp\preview_steps_tree.png")

# 场景 2：带「过于昂贵」警告 + tooltip 显示状态
t = AnvilItem.make("剑", [("sharpness", 5)], 31)
s = AnvilItem.make("附魔书", [("unbreaking", 3)], 7)
res, cost, detail = AnvilMechanics(dm).merge(t, s)
plan2 = AnvilPlan(steps=[MergeStep(t, s, res, cost, detail)],
                  total_cost=cost, final_item=res, too_expensive_steps=[1])
tree.show_plan(plan2, dm)
app.processEvents()
# 手动把 tooltip 放到一个可见位置（模拟悬停物品框）
fb = tree.final_box()
c = tree.cost_circles()[0]
tree.show_tooltip(c._tooltip_lines())
tp = tree._tooltip
# 移到视口中部固定位置便于查看
tp.move(60, 60)
app.processEvents()
tree.grab().save(
    r"C:\Users\NYT\.local\share\TeleAgent\TeleAgent的工作空间\.temp\preview_steps_tree_expensive.png")
tree.hide_tooltip()
print("预览图已生成")
