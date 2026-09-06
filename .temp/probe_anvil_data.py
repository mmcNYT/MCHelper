# -*- coding: utf-8 -*-
"""数据验证：确认测试用例依赖的附魔数值（乘数表/冲突/applicable/最大等级）"""
import json

with open(r"C:\maomaochongD\Coding\PythonProject\MCHelper\data\enchants.json",
          encoding="utf-8") as f:
    data = json.load(f)

by_id = {e["id"]: e for e in data["enchants"]}

# 关注的附魔 ID
ids = ["sharpness", "smite", "bane_of_arthropods", "looting", "knockback",
       "unbreaking", "protection", "fire_protection", "blast_protection",
       "projectile_protection", "fortune", "silk_touch", "power", "infinity",
       "mending", "efficiency", "aqua_affinity", "respiration", "loyalty",
       "piercing", "multishot", "quick_charge", "thorns", "feather_falling",
       "depth_strider", "frost_walker", "impaling", "riptide", "channeling",
       "sweeping_edge", "fire_aspect", "lure", "luck_of_the_sea",
       "binding_curse", "vanishing_curse", "dense", "wind_burst", "breach",
       "density", "wind_charge"]

for eid in ids:
    e = by_id.get(eid)
    if not e:
        print(f"{eid:24s} 不存在!")
        continue
    print(f"{e['id']:24s} {e['name']:6s} max={e['max_level']} "
          f"items={e.get('level_cost_from_items')} book={e.get('level_cost_from_book')} "
          f"conflicts={e.get('conflicts')}")

# applicable 集合统计
app_set = set()
for e in data["enchants"]:
    app_set.update(e.get("applicable", []))
print("\n全部 applicable 物品类型:", sorted(app_set))
print("\n附魔总数:", len(data["enchants"]))
