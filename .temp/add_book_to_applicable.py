# -*- coding: utf-8 -*-
# 一次性脚本：为 enchants.json 中所有附魔的 applicable 列表追加 "附魔书"
import json

PATH = r"C:\maomaochongD\Coding\PythonProject\MCHelper\data\enchants.json"

with open(PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

changed = 0
for ench in data.get("enchants", []):
    applicable = ench.get("applicable", [])
    if "附魔书" not in applicable:
        applicable.append("附魔书")  # 追加到列表末尾
        changed += 1

with open(PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"共 {len(data.get('enchants', []))} 条附魔，其中 {changed} 条被追加 '附魔书'")

# 验证：重新读取并统计
with open(PATH, "r", encoding="utf-8") as f:
    check = json.load(f)
total = len(check["enchants"])
ok = sum(1 for e in check["enchants"] if "附魔书" in e.get("applicable", []))
print(f"验证：{ok}/{total} 条附魔的 applicable 已包含 '附魔书'")
