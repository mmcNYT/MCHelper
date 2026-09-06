# -*- coding: utf-8 -*-
"""补充验证：白板剑（无锋利）+ 锋利书 + 亡灵杀手书 → 现有逻辑是否弹窗让用户选"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from Utils.conflict_resolver import find_conflict_clusters, resolve_conflicts
from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilOptimizer, build_items_from_cards

dm = DataManager()


def card(item_name, *enchs):
    return {"item_name": item_name,
            "enchants": [{"id": e[0], "name": e[1], "level": e[2]} for e in enchs]}


# 场景：剑只有耐久（无锋利）+ 锋利书 + 亡灵杀手书
cards = [
    card("剑", ("unbreaking", "耐久", 3)),
    card("附魔书", ("sharpness", "锋利", 5)),
    card("附魔书", ("smite", "亡灵杀手", 5)),
]
clusters = find_conflict_clusters(cards, dm)
auto, pending = resolve_conflicts(clusters, cards)
print("簇:", [[m["id"] for m in c] for c in clusters])
print("自动决策:", auto, "| 待决策:", len(pending), "个簇 →", "弹窗让用户选" if pending else "不弹窗")

# 用户选保留亡灵杀手 → 优化器能否给出方案？
opt = AnvilOptimizer(dm)
items = build_items_from_cards(cards)
plan = opt.optimize(items, required_enchants=frozenset(["smite"]))
print(f"\n选保留亡灵杀手：可行！总花费 {plan.total_cost} 级")
for s in plan.steps:
    print(f"  {s.target.display_label(dm)} + {s.sacrifice.display_label(dm)}")
    print(f"    -> {s.result.display_label(dm)}（{s.cost} 级）")
