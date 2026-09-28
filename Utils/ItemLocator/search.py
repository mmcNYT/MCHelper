# -*- coding: utf-8 -*-
"""最近命中物品搜索：从「物品 -> 可能产出结构」候选里枚举实例，
逐箱用 RNG 生成战利品，校验是否真实产出目标物品，返回最近命中实例。

依赖：
- catalog.structures_for_item / struct_name / enum_key / ALL_STRUCT_KEYS
- structure_map.enumerate_structures（实例枚举，含维度路由）
- composition.compose（变种/旋转/箱子坐标/LootTableSeed）
- loot_engine.generate_loot（箱子战利品 RNG 求值）

返回值（命中）：
    {"struct_key": UI键, "struct_name": 中文名, "anchor": (x, z),
     "x": x, "z": z, "biome": 群系 id, "variant": 变体名,
     "distance": 距起点平方距离, "hits": [{"index": 箱序, "chest_num",
     "table", "pos": (x, z), "seed_signed", "items": [...]}...]}
未命中返回 None；取消/异常上抛对应异常。
"""

import os

from Utils.Public import structure_params
from Utils.Public.structure_map import enumerate_structures
from Utils.StructurePreviewer import composition, loot_engine, loot_rng
from . import catalog

# 战利品快照目录（与预览器同源）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_LOOT_DIR = os.path.join(_ROOT, "Utils", "StructurePreviewer",
                         "data", "loot")

# 实例枚举半径（方块；与预览器 _LOCATE_RADIUS 一致）
DEFAULT_RADIUS = 4096

# loot 表缓存 {(表名, era): LootTable}
_loot_cache: dict = {}


class FindCancelled(Exception):
    """搜索被取消。"""


def _loot_table(table_name: str, era: int):
    key = (table_name, era)
    if key not in _loot_cache:
        _loot_cache[key] = loot_engine.load_loot_snapshot(
            table_name, era, snapshot_dir=_LOOT_DIR)
    return _loot_cache[key]


def find_nearest(seed: int, version: str, struct_key: str | None,
                 item_full: str, cx: int, cz: int,
                 radius: int = DEFAULT_RADIUS,
                 on_progress=None, cancel=None) -> dict | None:
    """搜索离 (cx,cz) 最近、且箱子真实产出目标物品的结构实例。

    Args:
        seed: 世界种子。
        version: 版本键（VERSION_KEYS 之一）。
        struct_key: 指定结构键（None = 全候选结构里找最近的）。
        item_full: 目标物品全名（minecraft:xxx）。
        cx, cz: 起始中心坐标。
        radius: 枚举半径。
        on_progress: on_progress(done, total, 阶段文案)。
        cancel: cancel() -> bool；为 True 时中止（抛 FindCancelled）。
    """
    if struct_key:
        candidates = [struct_key]
    else:
        candidates = list(catalog.structures_for_item(item_full))
    if not candidates:
        raise ValueError("该物品在已支持的结构战利品中未出现，无法定位")

    era = loot_engine.era_for_version(version)
    total = len(candidates)
    best: dict | None = None

    for idx, ui_key in enumerate(candidates):
        if cancel is not None and cancel():
            raise FindCancelled()
        enum_k = catalog.enum_key(ui_key)
        if on_progress is not None:
            on_progress(idx + 1, total, f"枚举{catalog.struct_name(ui_key)}")
        viewport = (cx - radius, cz - radius, cx + radius, cz + radius)
        instances = enumerate_structures(
            seed, version, viewport, [enum_k],
            dimension=structure_params.STRUCT_DIMENSION.get(ui_key,
                                                            "overworld"))
        # 距中心升序（近的优先，命中即当前结构最近）
        instances.sort(key=lambda t: (t["x"] - cx) ** 2 + (t["z"] - cz) ** 2)
        for it in instances:
            if cancel is not None and cancel():
                raise FindCancelled()
            x, z = it["x"], it["z"]
            d2 = (x - cx) ** 2 + (z - cz) ** 2
            if best is not None and d2 > best["_d2"]:
                # 已排序升序：后续实例更远，不可能刷新全局最近，跳过
                break
            try:
                comp = composition.compose(
                    ui_key, seed, x, z,
                    biome_id=int(it.get("biome", -1)),
                    version_key=version)
            except Exception:
                continue  # 该实例不可预览（跳过，不计为候选）
            hits = []
            for ci, chest in enumerate(comp.chests):
                try:
                    table = _loot_table(chest.loot_table, era)
                    items = loot_engine.generate_loot(table, chest.loot_seed)
                except Exception:
                    continue
                if any(st.item == item_full for st in items):
                    hits.append({
                        "index": ci,
                        "chest_num": ci + 1,
                        "table": chest.loot_table,
                        "pos": (chest.pos[0], chest.pos[1]),
                        "seed_signed": loot_rng.signed_seed(chest.loot_seed),
                        "items": [st for st in items
                                  if st.item == item_full],
                    })
            if hits:
                best = {
                    "struct_key": ui_key,
                    "struct_name": catalog.struct_name(ui_key),
                    "anchor": (x, z),
                    "x": x, "z": z,
                    "biome": int(it.get("biome", -1)),
                    "variant": comp.variant_name,
                    "distance": d2,
                    "_d2": d2,
                    "hits": hits,
                }

    if best is None:
        return None
    best.pop("_d2", None)
    return best