# -*- coding: utf-8 -*-
"""调试三附魔簇场景"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from Utils.conflict_resolver import find_conflict_clusters, resolve_conflicts
from Utils.enchant_data_manager import DataManager

dm = DataManager()

def card(item_name, *enchs):
    return {"item_name": item_name,
            "enchants": [{"id": e[0], "name": e[1], "level": e[2]} for e in enchs]}

cards = [card("剑", ("sharpness", "锋利", 5)),
         card("附魔书", ("blast_protection", "爆炸保护", 4)),
         card("附魔书", ("protection", "保护", 4))]
clusters = find_conflict_clusters(cards, dm)
print("簇数:", len(clusters))
for i, m in enumerate(clusters):
    print(f"  簇{i}: {[x['id'] for x in m]}")
auto, pending = resolve_conflicts(clusters, cards)
print("auto:", auto)
print("pending 簇数:", len(pending))
for m in pending:
    print("  pending:", [x["id"] for x in m])

# 查锋利与保护是否互斥
print("sharpness conflicts:", dm.get_conflicts("sharpness"))
print("protection conflicts:", dm.get_conflicts("protection"))
