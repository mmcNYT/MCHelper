# -*- coding: utf-8 -*-
"""搜索层验证：最优合并树（Dijkstra）+ 保留附魔约束"""
import os
import sys
import time

sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

from Utils.enchant_data_manager import DataManager
from Utils.anvil_optimizer import (AnvilOptimizer, AnvilItem,
                                   build_items_from_cards, AnvilError)

dm = DataManager()
opt = AnvilOptimizer(dm)

# ========== 1. 经典策略：先合书再并入剑 ==========
# 4 本各带 1 个附魔的书 + 1 把剑，最优解应先把书合并（书乘数便宜 + PWP 只算一次）
# 最后一次性并入剑（参考 Wiki"你知道吗"：先合书再并入装备只统计一次惩罚）
items = [
    AnvilItem.make("剑", []),
    AnvilItem.make("附魔书", [("sharpness", 5)]),
    AnvilItem.make("附魔书", [("looting", 3)]),
    AnvilItem.make("附魔书", [("unbreaking", 3)]),
    AnvilItem.make("附魔书", [("sweeping_edge", 3)]),
]
t0 = time.time()
plan = opt.optimize(items)
dt = time.time() - t0
print(f"1. 剑+4书：总花费 {plan.total_cost}，{len(plan.steps)} 步，耗时 {dt:.2f}s")
for i, s in enumerate(plan.steps, 1):
    print(f"   步{i}: [{s.target.label}] + [{s.sacrifice.label}] = {s.cost}级")
print(f"   最终: {plan.final_item.label}")
# 验证：全步骤费用应一致
assert sum(s.cost for s in plan.steps) == plan.total_cost
# 最终应含全部 4 个附魔
fm = plan.final_item.enchant_map()
assert fm == {"sharpness": 5, "looting": 3, "unbreaking": 3,
              "sweeping_edge": 3}, fm
assert plan.final_item.name == "剑"

# ========== 2. 保留附魔约束：附魔书自带互斥附魔时顺序由约束决定 ==========
# 剑(无附魔) + 书(锋利V) + 书(亡灵杀手V)：用户选保留亡灵杀手 →
# 最优解必须让亡灵杀手先抵达剑（否则锋利先上剑会拦截亡灵杀手）
items2 = [
    AnvilItem.make("剑", []),
    AnvilItem.make("附魔书", [("sharpness", 5)]),
    AnvilItem.make("附魔书", [("smite", 5)]),
]
plan2 = opt.optimize(items2, required_enchants={"smite"})
print(f"2. 保留亡灵杀手：总花费 {plan2.total_cost}，最终 {plan2.final_item.label}")
fm2 = plan2.final_item.enchant_map()
assert "smite" in fm2 and fm2["smite"] == 5, fm2
assert "sharpness" not in fm2, "锋利应被亡灵杀手拦截（或根本没合并上去）"
# 剑+亡灵杀手书 必须发生在 剑+锋利书 之前（如果锋利书与剑合并了）
smite_step = next(i for i, s in enumerate(plan2.steps)
                  if "smite" in s.result.enchant_map()
                  and s.result.name == "剑")
for s in plan2.steps[smite_step + 1:]:
    assert not any(e == "sharpness" and lv > 0 for e, lv in s.result.enchants
                   if s.result.name == "剑" and "smite" in s.result.enchant_map()), \
        "亡灵杀手在剑上后，锋利书再合并只应 +1 拦截费"
print("   顺序约束满足：亡灵杀手先上剑，锋利被拦截（+1）")

# 保留锋利 → 对称
plan2b = opt.optimize(items2, required_enchants={"sharpness"})
assert plan2b.final_item.enchant_map().get("sharpness") == 5
assert "smite" not in plan2b.final_item.enchant_map()
print(f"   保留锋利：总花费 {plan2b.total_cost}，最终 {plan2b.final_item.label}")

# ========== 2c. 物品自带互斥附魔 → 约束必然失败（正确报错） ==========
# 剑自带锋利V（物品上的附魔无法移除），要求最终保留亡灵杀手 → 不可能
items2c = [
    AnvilItem.make("剑", [("sharpness", 5)]),
    AnvilItem.make("附魔书", [("smite", 5)]),
]
try:
    opt.optimize(items2c, required_enchants={"smite"})
    raise SystemExit("2c. 应当报错：剑上的锋利会永久拦截亡灵杀手")
except AnvilError as e:
    print(f"2c. 物品自带互斥附魔 → 正确报错：{e}")

# ========== 3. 约束不可满足 → 报错 ==========
# 锋利与亡灵杀手互斥，要求两个都保留 → 必然失败
try:
    opt.optimize(items2, required_enchants={"sharpness", "smite"})
    raise SystemExit("3. 应当报错：互斥附魔不可能同时保留")
except AnvilError as e:
    print(f"3. 互斥附魔同时保留 → 正确报错：{e}")

# ========== 4. 多类型非书物品 → 报错 ==========
items4 = [AnvilItem.make("剑", []), AnvilItem.make("镐", [])]
try:
    opt.optimize(items4)
    raise SystemExit("4. 应当报错：剑+镐不能合并")
except AnvilError as e:
    print(f"4. 多类型物品 → 正确报错：{e}")

# ========== 5. 性能：8 件物品（精确搜索上限） ==========
items5 = [AnvilItem.make("剑", [])] + [
    AnvilItem.make("附魔书", [(eid, lv)])
    for eid, lv in [("sharpness", 5), ("looting", 3), ("unbreaking", 3),
                    ("sweeping_edge", 3), ("fire_aspect", 2), ("knockback", 2),
                    ("mending", 1)]]
t0 = time.time()
plan5 = opt.optimize(items5)
dt = time.time() - t0
print(f"5. 剑+7书（8件，精确搜索）：总花费 {plan5.total_cost}，"
      f"{len(plan5.steps)} 步，耗时 {dt:.2f}s")
assert len(plan5.final_item.enchant_map()) == 7

# ========== 6. 单物品直接返回 ==========
plan6 = opt.optimize([AnvilItem.make("剑", [("sharpness", 5)])])
assert plan6.steps == [] and plan6.total_cost == 0
print("6. 单物品 → 空方案 ✓")

# ========== 7. 卡片数据入口 ==========
cards = [
    {"item_name": "剑", "enchants": [{"id": "sharpness", "name": "锋利", "level": 5}]},
    {"item_name": "附魔书", "enchants": [{"id": "looting", "name": "抢夺", "level": 3}]},
]
items7 = build_items_from_cards(cards)
assert items7[0].label == "剑（锋利V）" and items7[1].label == "附魔书（抢夺III）"
plan7 = opt.optimize(items7)
assert plan7.final_item.enchant_map() == {"sharpness": 5, "looting": 3}
print(f"7. 卡片入口：总花费 {plan7.total_cost}，最终 {plan7.final_item.label}")

print("\n搜索层全部验证通过")
