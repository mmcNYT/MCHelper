# -*- coding: utf-8 -*-
"""调试 4b 场景：为何优化失败"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilOptimizer, build_items_from_cards, AnvilError

dm = DataManager()

def card(item_name, *enchs):
    return {"item_name": item_name,
            "enchants": [{"id": e[0], "name": e[1], "level": e[2]} for e in enchs]}

cards = [
    card("剑", ("sharpness", "锋利", 5)),
    card("附魔书", ("smite", "亡灵杀手", 5), ("protection", "保护", 4)),
    card("附魔书", ("blast_protection", "爆炸保护", 4),
         ("bane_of_arthropods", "节肢杀手", 5)),
]
opt = AnvilOptimizer(dm)
try:
    plan = opt.optimize(build_items_from_cards(cards),
                        required_enchants=frozenset(["sharpness", "protection"]))
    print("成功，总花费", plan.total_cost)
    for s in plan.steps:
        print(f"  {s.target.name}{dict(s.target.enchants)} + "
              f"{s.sacrifice.name}{dict(s.sacrifice.enchants)} -> "
              f"{s.result.name}{dict(s.result.enchants)} 花费{s.cost}")
except AnvilError as e:
    print("AnvilError:", e)
