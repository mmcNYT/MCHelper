# -*- coding: utf-8 -*-
"""查询：双方均适用于剑的互斥附魔对（用于重构 4b 测试场景）"""
import json
import sys

sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")

with open(r"C:\maomaochongD\Coding\PythonProject\MCHelper\data\enchants.json",
          encoding="utf-8") as f:
    data = json.load(f)

enchants = data["enchants"] if isinstance(data, dict) and "enchants" in data else data
by_id = {e["id"]: e for e in enchants}

print("== 双方均适用于剑的互斥对 ==")
for e in enchants:
    for c in e.get("conflicts", []):
        ce = by_id.get(c)
        if ce and "剑" in ce.get("applicable", []):
            print(f"  {e['id']}({e['name']}) <-> {c}({ce['name']})")

print()
print("== 锋利簇成员与其它适用于剑附魔的互斥性 ==")
sword_group = {"sharpness", "smite", "bane_of_arthropods", "breach", "density"}
for eid in sorted(sword_group):
    e = by_id.get(eid)
    if e:
        print(f"  {eid}({e['name']}): conflicts={e.get('conflicts')}, "
              f"applicable={e.get('applicable')}")
