# -*- coding: utf-8 -*-
"""按 category 指定顺序重排 enchants.json 条目（类别内部保持原有顺序）"""
import json
import io

PATH = r"C:\maomaochongD\Coding\PythonProject\MCHelper\data\enchants.json"

# 用户指定的类别顺序
ORDER = ["近战武器", "远程武器", "工具", "防具", "三叉戟", "通用附魔", "诅咒"]

with io.open(PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

lst = data["enchants"]

# 校验：所有 category 都在 ORDER 内
unknown = [e.get("category") for e in lst if e.get("category") not in ORDER]
if unknown:
    raise SystemExit("发现未知类别: %s" % set(unknown))

# 稳定排序：按 ORDER 中的索引排序，类别内部保持原相对顺序
lst.sort(key=lambda e: ORDER.index(e["category"]))

with io.open(PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")

print("排序完成，共 %d 条" % len(lst))
for i, e in enumerate(lst):
    print(i, e["id"], "|", e["category"])
