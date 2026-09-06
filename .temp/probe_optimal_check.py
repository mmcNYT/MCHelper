# -*- coding: utf-8 -*-
"""对照验证 v2：修正穷举对照（终态约束=剑），复算两条路线"""
import sys

sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import AnvilOptimizer, AnvilItem

dm = DataManager()
opt = AnvilOptimizer(dm)
mech = opt.mech

items = [
    AnvilItem.make("剑", []),
    AnvilItem.make("附魔书", [("sharpness", 5)]),
    AnvilItem.make("附魔书", [("looting", 3)]),
    AnvilItem.make("附魔书", [("unbreaking", 3)]),
    AnvilItem.make("附魔书", [("sweeping_edge", 3)]),
]
plan = opt.optimize(items)
print(f"Dijkstra 结果: {plan.total_cost} 级")

cache = {}

def best_cost(pool):
    if len(pool) == 1:
        return 0 if pool[0].name == "剑" else None  # 终态必须是剑
    key = tuple(sorted(pool, key=repr))
    if key in cache:
        return cache[key]
    result = None
    n = len(pool)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if not mech.can_merge(pool[i], pool[j]):
                continue
            r, fee, _ = mech.merge(pool[i], pool[j])
            # 终态可行性剪枝：非书类型只剩一件且不是剑 → 死路（书可并入剑）
            rest = tuple(pool[k] for k in range(n) if k not in (i, j)) + (r,)
            sub = best_cost(rest)
            if sub is None:
                continue
            total = fee + sub
            if result is None or total < result:
                result = total
    cache[key] = result
    return result

brute = best_cost(tuple(items))
print(f"穷举对照结果: {brute} 级")
assert brute is not None, "穷举也未找到可行解？"
if plan.total_cost != brute:
    print(f"!!! 不一致：Dijkstra={plan.total_cost} 穷举={brute}")
else:
    print("两者一致，最优性确认 ✓")
