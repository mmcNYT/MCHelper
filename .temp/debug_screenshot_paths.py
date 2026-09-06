# -*- coding: utf-8 -*-
"""验证截图场景：剑(锋利IV,耐久III) + 书(亡灵杀手V,经验修补I) + 书(击退II,锋利IV)

问题：锋利在剑上（按旧规则自动保留锋利），但用户指出保留亡灵杀手
或许也可行——穷举全部合并路径验证。
"""
import os
import sys
import itertools

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import (AnvilMechanics, AnvilItem,
                                   build_items_from_cards)

dm = DataManager()
mech = AnvilMechanics(dm)


def card(item_name, *enchs):
    return {"item_name": item_name,
            "enchants": [{"id": e[0], "name": e[1], "level": e[2]} for e in enchs]}


cards = [
    card("剑", ("sharpness", "锋利", 4), ("unbreaking", "耐久", 3)),
    card("附魔书", ("smite", "亡灵杀手", 5), ("mending", "经验修补", 1)),
    card("附魔书", ("knockback", "击退", 2), ("sharpness", "锋利", 4)),
]
items = build_items_from_cards(cards)
print("输入：")
for it in items:
    print("  ", it.display_label(dm))

# 穷举全部有序合并序列（3 物品只有 2 步，6 种两两有序对 × 剩余 2 种 = 12 棵树）
def search(pool, path):
    """pool: 当前物品列表; path: 已执行步骤 [(target_idx, sacrifice_idx, step)]"""
    results = []
    if len(pool) == 1:
        results.append((path, pool[0]))
        return results
    for i in range(len(pool)):
        for j in range(len(pool)):
            if i == j:
                continue
            t, s = pool[i], pool[j]
            if not mech.can_merge(t, s):
                continue
            result, fee, detail = mech.merge(t, s)
            nxt = [pool[k] for k in range(len(pool)) if k not in (i, j)] + [result]
            results.extend(search(nxt, path + [(t, s, result, fee)]))
    return results


all_paths = search(items, [])
print(f"\n共 {len(all_paths)} 条合法合并路径：\n")

for idx, (path, final) in enumerate(all_paths, 1):
    total = sum(fee for *_, fee in path)
    ench = dict(final.enchants)
    has_smite = "smite" in ench
    has_sharp = "sharpness" in ench
    print(f"路径 {idx}：总花费 {total}")
    for t, s, r, fee in path:
        print(f"    {t.display_label(dm)} + {s.display_label(dm)}")
        print(f"      -> {r.display_label(dm)}  （本步 {fee} 级）")
    print(f"    终态：{final.display_label(dm)}"
          f"  [亡灵杀手={'有' if has_smite else '无'}, 锋利={'有' if has_sharp else '无'}]")
    print()
