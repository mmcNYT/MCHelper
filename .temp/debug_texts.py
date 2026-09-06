# -*- coding: utf-8 -*-
"""诊断：步骤图场景文本项内容（结果写文件）"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from Utils.anvil_steps_tree import AnvilStepsTree
from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilOptimizer, build_items_from_cards

dm = DataManager()
opt = AnvilOptimizer(dm)


def card(n, *e):
    return {"item_name": n,
            "enchants": [{"id": x[0], "name": x[1], "level": x[2]} for x in e]}


cards = [card("剑"),
         card("附魔书", ("sharpness", "锋利", 5)),
         card("附魔书", ("unbreaking", "耐久", 3))]
plan = opt.optimize(build_items_from_cards(cards))
t = AnvilStepsTree()
t.show_plan(plan, dm, mode="steps")

out = []
for it in t._scene.items():
    if hasattr(it, "toPlainText"):
        out.append(repr(it.toPlainText()))

with open(r"C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\debug_texts_result.txt",
          "w", encoding="utf-8") as f:
    f.write("\n".join(out))
