# -*- coding: utf-8 -*-
"""按用户指定的 category 内顺序重排 enchants.json"""
import json
import io

PATH = r"C:\maomaochongD\Coding\PythonProject\MCHelper\data\enchants.json"

# category 间顺序沿用现有文件（近战武器→远程武器→工具→防具→三叉戟→通用附魔→诅咒）
# category 内按用户指定顺序
ORDER = {
    "近战武器": [
        "sharpness",        # 锋利
        "smite",            # 亡灵杀手
        "bane_of_arthropods",  # 节肢杀手
        "fire_aspect",      # 火焰附加
        "looting",          # 抢夺
        "knockback",        # 击退
        "sweeping_edge",    # 横扫之刃
        "breach",           # 破甲
        "density",          # 致密
        "wind_burst",       # 风爆
        "lunge",            # 突进
    ],
    "远程武器": [
        "power",            # 力量
        "punch",            # 冲击
        "flame",            # 火矢
        "infinity",         # 无限
        "piercing",         # 穿透
        "multishot",        # 多重射击
        "quick_charge",     # 快速装填
    ],
    "工具": [
        "efficiency",       # 效率
        "fortune",          # 时运
        "silk_touch",       # 精准采集
        "lure",             # 饵钓
        "luck_of_the_sea",  # 海之眷顾
    ],
    "防具": [
        "protection",             # 保护
        "fire_protection",        # 火焰保护
        "blast_protection",       # 爆炸保护
        "projectile_protection",  # 弹射物保护
        "thorns",                 # 荆棘
        "feather_falling",        # 摔落缓冲
        "soul_speed",             # 灵魂疾行
        "frost_walker",           # 冰霜行者
        "depth_strider",          # 深海探索者
        "swift_sneak",            # 迅捷潜行
        "respiration",            # 水下呼吸
        "aqua_affinity",          # 水下速掘
    ],
    # 三叉戟/通用附魔/诅咒 未指定内部顺序，保持现状
    "三叉戟": ["channeling", "impaling", "loyalty", "riptide"],
    "通用附魔": ["mending", "unbreaking"],
    "诅咒": ["binding_curse", "vanishing_curse"],
}

CAT_ORDER = list(ORDER.keys())

with io.open(PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

lst = data["enchants"]

# 校验：全部 43 条 id 均被覆盖，无遗漏无多余
all_ids = set()
for ids in ORDER.values():
    for i in ids:
        assert i not in all_ids, "重复 id: %s" % i
        all_ids.add(i)
current_ids = {e["id"] for e in lst}
missing = current_ids - all_ids
extra = all_ids - current_ids
if missing or extra:
    raise SystemExit("清单与数据不匹配 | 数据中缺失: %s | 清单中多余: %s" % (missing, extra))

# 校验：每条数据的 category 与清单归属一致
for e in lst:
    cat = e["category"]
    if e["id"] not in ORDER[cat]:
        raise SystemExit("类别不一致: %s 数据标记为 %s，但清单不在该类" % (e["id"], cat))

# 重排：按清单索引稳定排序
lst.sort(key=lambda e: (CAT_ORDER.index(e["category"]), ORDER[e["category"]].index(e["id"])))

with io.open(PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")

print("排序完成，共 %d 条" % len(lst))
for i, e in enumerate(lst):
    print(i, e["category"], "|", e["id"], "|", e["name"])
