# -*- coding: utf-8 -*-
"""给 enchants.json 所有附魔条目新增 conflicts（互斥）字段
数据来源：中文 Minecraft Wiki「不兼容魔咒」页面（oldid=1459027，2026-08-23）
互斥关系双向冗余存储，便于 O(1) 查询
"""
import json
import io
import copy

PATH = r"C:\maomaochongD\Coding\PythonProject\MCHelper\data\enchants.json"

# 互斥组（组内两两互斥）
GROUPS = [
    ["sharpness", "smite", "bane_of_arthropods"],           # 锋利/亡灵杀手/节肢杀手
    ["smite", "density"],                                    # 亡灵杀手×致密
    ["smite", "breach"],                                     # 亡灵杀手×破甲
    ["bane_of_arthropods", "density"],                       # 节肢杀手×致密
    ["bane_of_arthropods", "breach"],                        # 节肢杀手×破甲
    ["fortune", "silk_touch"],                               # 时运×精准采集
    ["infinity", "mending"],                                 # 无限×经验修补
    ["channeling", "riptide"],                               # 引雷×激流
    ["loyalty", "riptide"],                                  # 忠诚×激流
    ["multishot", "piercing"],                               # 多重射击×穿透
    ["protection", "fire_protection", "blast_protection", "projectile_protection"],  # 四保护
    ["depth_strider", "frost_walker"],                       # 深海探索者×冰霜行者
]

with io.open(PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

# 构建 id -> conflicts 映射
conflict_map = {}
for group in GROUPS:
    for a in group:
        others = [b for b in group if b != a]
        conflict_map.setdefault(a, [])
        for b in others:
            if b not in conflict_map[a]:
                conflict_map[a].append(b)

lst = data["enchants"]
backup = copy.deepcopy(lst)

for ench in lst:
    eid = ench["id"]
    if "conflicts" in ench:
        continue  # 已有则不覆盖
    # 按数据文件顺序（即展示顺序）排列冲突列表，便于阅读
    order = [e["id"] for e in lst]
    ench["conflicts"] = sorted(conflict_map.get(eid, []), key=order.index)

with io.open(PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")

# 校验：双向一致性
id_set = {e["id"] for e in lst}
for e in lst:
    for c in e.get("conflicts", []):
        assert c in id_set, "%s 引用了不存在的冲突 id: %s" % (e["id"], c)
        back = next(x for x in lst if x["id"] == c).get("conflicts", [])
        assert e["id"] in back, "双向不一致: %s -> %s 但 %s 不含 %s" % (e["id"], c, c, e["id"])

print("完成。冲突统计：")
for e in lst:
    print(e["id"], "->", e.get("conflicts", []))
print("备份条数:", len(backup))
