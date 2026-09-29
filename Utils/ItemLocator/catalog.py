# -*- coding: utf-8 -*-
"""物品目录：物品全名 -> 可能产出该物品的结构类型列表。

数据来源：Utils/StructurePreviewer/data/loot 下的战利品表快照。
- 每个结构类型声明其可能用到的表（短名，与快照文件名一致）；
- 对每张表（含其引用的子表）遍历 JSON 里的 item 条目，收集物品全名
  （minecraft:xxx），并集为「该结构可能产出的物品集合」；
- 反向建物品 -> 结构集合，供「选择物品后只显示该物品可能生成的结构」
  的 UI 过滤与「留空则找最近命中实例」的全候选遍历。

一致性：表名集合需与 StructurePreviewer 实际可生成的表对齐——
不在快照目录里的表无法被 _loot_table 加载，也不应进入目录（否则
候选结构被错误过滤掉）。故此处按快照可用表声明，缺失表不列举。
"""

import json
import os

from Utils.Public.item_names import ITEM_CN

# 项目根目录（Utils/ItemLocator/ -> MCHelper/）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_LOOT_DIR = os.path.join(_ROOT, "Utils", "StructurePreviewer",
                         "data", "loot")

# 结构类型（与 StructurePreviewer 工具支持集一致）
ALL_STRUCT_KEYS = ("igloo", "shipwreck", "ocean_ruin", "stronghold",
                   "nether_fortress", "bastion_remnant", "end_city",
                   "trial_chambers", "ancient_city", "village",
                   "pillager_outpost", "woodland_mansion",
                   "desert_pyramid", "jungle_temple",
                   "ruined_portal", "buried_treasure")

# UI 键 -> 枚举/校验链路键（cubiomes 键名差异桥接，与预览器同款）
UI_TO_ENUM = {"woodland_mansion": "mansion"}

# 结构 -> 可用的战利品表（快照短名；含各自引用的子表）。
# 说明：堡垒遗迹仅 bridge/other 两表快照（其余表缺失，无法求值，
# 不进结构，避免候选过滤出现「能查但永远无结果」的空结构）。
_STRUCT_TABLES = {
    "igloo": ("igloo_chest",),
    "shipwreck": ("shipwreck_supply", "shipwreck_map", "shipwreck_treasure"),
    "ocean_ruin": ("underwater_ruin_big", "underwater_ruin_small"),
    "stronghold": ("stronghold_corridor", "stronghold_crossing",
                   "stronghold_library"),
    "nether_fortress": ("nether_bridge",),
    "bastion_remnant": ("bastion_bridge", "bastion_other"),
    "end_city": ("end_city_treasure",),
    # trial_chambers 的 NBT 实际引用 chests/trial_chambers/<子表>，
    # 快照按子表短名分文件（reward/corridor/entrance/supply/
    # intersection/intersection_barrel 及其子表 reward_common 等）
    "trial_chambers": ("reward", "corridor", "entrance", "supply",
                       "intersection", "intersection_barrel"),
    "ancient_city": ("ancient_city", "ancient_city_ice_box"),
    "village": ("village_armorer", "village_butcher",
                "village_cartographer", "village_desert_house",
                "village_fisher", "village_fletcher", "village_mason",
                "village_plains_house", "village_savanna_house",
                "village_shepherd", "village_snowy_house",
                "village_taiga_house", "village_tannery", "village_temple",
                "village_toolsmith", "village_weaponsmith"),
    "pillager_outpost": ("pillager_outpost",),
    "woodland_mansion": ("woodland_mansion",),
    "desert_pyramid": ("desert_pyramid",),
    "jungle_temple": ("jungle_temple", "jungle_temple_dispenser"),
    "ruined_portal": ("ruined_portal",),
    "buried_treasure": ("buried_treasure",),
}

# 表短名 -> 该表（含子表）可产出物品全名集合（懒加载缓存）
_table_items: dict[str, frozenset] = {}
# 物品全名 -> 结构键集合（懒构建）
_item_to_structs: "dict[str, frozenset] | None" = None


def enum_key(ui_key: str) -> str:
    """UI 键 -> 枚举/校验链路键（cubiomes 键）。"""
    return UI_TO_ENUM.get(ui_key, ui_key)


def struct_name(ui_key: str) -> str:
    """结构键 -> 中文显示名（结构名称表兜底）。"""
    try:
        from Utils.Public import structure_params
        return structure_params.STRUCT_NAMES.get(enum_key(ui_key), ui_key)
    except Exception:
        return ui_key


def _table_paths(name: str) -> list:
    """表短名 -> 该表全部快照文件路径。

    主文件 <name>.json + 全部 <name>.<档>.json（分档表以及
    stronghold_corridor.1_13/1_18/1_21_9 等非标准档名一并纳入）。
    """
    base = os.path.join(_LOOT_DIR, name)
    out = [base + ".json"]
    prefix = name + "."
    if os.path.isdir(_LOOT_DIR):
        for f in os.listdir(_LOOT_DIR):
            if f.startswith(prefix) and f.endswith(".json"):
                p = os.path.join(_LOOT_DIR, f)
                if p not in out:
                    out.append(p)
    return [p for p in out if os.path.exists(p)]


def _collect_from_data(data, out: set, visited: set) -> None:
    """从单份表 JSON 递归收集 item 全名与子表引用。

    - 条目字段 name：minecraft:xxx 物品全名 -> 收集；
    - 条目 type=minecraft:loot_table 的 value：子表引用 ->
      解析短名后递归加载对应快照文件；
    - grouped 条目的 children 列表继续递归。
    """
    if isinstance(data, dict):
        name = data.get("name")
        if isinstance(name, str) and name.startswith("minecraft:"):
            out.add(name)
        if data.get("type") == "minecraft:loot_table":
            value = data.get("value")
            if isinstance(value, str):
                short = value.split("/")[-1]
                _expand_subtable(short, out, visited)
        children = data.get("children")
        if isinstance(children, list):
            for c in children:
                _collect_from_data(c, out, visited)
        for v in data.values():
            _collect_from_data(v, out, visited)
    elif isinstance(data, list):
        for it in data:
            _collect_from_data(it, out, visited)


def _expand_subtable(short: str, out: set, visited: set) -> None:
    """展开一张子表（短名）：加载其全部版本快照收集物品（防环）。"""
    if short in visited:
        return
    visited.add(short)
    for p in _table_paths(short):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        _collect_from_data(data, out, visited)


def _possible_items_short(short: str) -> frozenset:
    """表短名（含全部版本快照 + 子表）-> 可产出物品全名集合。"""
    cached = _table_items.get(short)
    if cached is not None:
        return cached
    out: set = set()
    visited = {short}
    for p in _table_paths(short):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        _collect_from_data(data, out, visited)
    result = frozenset(out)
    _table_items[short] = result
    return result


def build_item_to_structs() -> dict:
    """物品全名 -> 可产出它的结构键集合（一次性构建并缓存）。"""
    global _item_to_structs
    if _item_to_structs is not None:
        return _item_to_structs
    mapping: dict[str, set] = {}
    for key, tables in _STRUCT_TABLES.items():
        for short in tables:
            for item in _possible_items_short(short):
                mapping.setdefault(item, set()).add(key)
    _item_to_structs = {k: frozenset(v) for k, v in mapping.items()}
    return _item_to_structs


def structures_for_item(item_full: str) -> tuple[str, ...]:
    """物品全名 -> 可能产出的结构键（按 ALL_STRUCT_KEYS 顺序）。"""
    s = build_item_to_structs().get(item_full, frozenset())
    return tuple(k for k in ALL_STRUCT_KEYS if k in s)


def all_items() -> list[tuple[str, str]]:
    """全部可搜索物品 -> [(显示名, 物品全名), ...]（按显示名排序）。

    显示名 = 中文名（无中文名回退短名）。舍弃英文短名后缀，避免
    物品下拉图标旁显示英文与中文混杂、观感冲突；英文短名仍可
    作为输入匹配键（target_item_dialog._resolve_item 支持）。
    """
    seen: set = set()
    for key, tables in _STRUCT_TABLES.items():
        for short in tables:
            seen.update(_possible_items_short(short))
    items = []
    for item in sorted(seen):
        short = item.split(":", 1)[-1]
        cn = ITEM_CN.get(short)
        label = cn if cn else short
        items.append((label, item))
    return items