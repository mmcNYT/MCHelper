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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

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

# loot 表缓存 {(表名, era): LootTable}（多线程读，构建时加锁）
_loot_cache: dict = {}
_loot_lock = threading.Lock()


class FindCancelled(Exception):
    """搜索被取消。"""


def _loot_table(table_name: str, era: int):
    key = (table_name, era)
    with _loot_lock:
        cached = _loot_cache.get(key)
    if cached is not None:
        return cached
    table = loot_engine.load_loot_snapshot(
        table_name, era, snapshot_dir=_LOOT_DIR)
    with _loot_lock:
        _loot_cache[key] = table
    return table


def _probe_instance(ui_key, enum_k, seed, x, z, biome, version, era,
                    item_full):
    """求值单个结构实例：compose + 逐箱战利品，返回命中列表。

    线程 worker（C++ 引擎拼装阶段释放 GIL，多线程并行生效）。
    """
    comp = composition.compose(
        ui_key, seed, x, z, biome_id=biome, version_key=version)
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
                "items": [st for st in items if st.item == item_full],
            })
    return comp, hits


def find_nearest(seed: int, version: str, struct_key: str | None,
                 item_full: str, cx: int, cz: int,
radius: int = DEFAULT_RADIUS,
                 on_progress=None, cancel=None,
                 first_hit: bool = False) -> dict | None:
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
        first_hit: True 时找到第一个命中立即返回（不追求最近，更快）。
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

    # 并行 worker 数：C++ 引擎释放 GIL 后线程并行真正生效，
    # 取物理/逻辑核上限（避免过度开线程）。
    workers = os.cpu_count() or 4

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
        # 距中心升序（近的优先；命中即可用当前结构最近候选，无需遍历更远）
        instances.sort(key=lambda t: (t["x"] - cx) ** 2 + (t["z"] - cz) ** 2)
        if not instances:
            continue

        # 该结构首个候选比全局最近命中更远 → 该结构不可能刷新 best，跳过
        first_d2 = ((instances[0]["x"] - cx) ** 2
                    + (instances[0]["z"] - cz) ** 2)
        if best is not None and first_d2 > best["_d2"]:
            continue

        with ThreadPoolExecutor(max_workers=workers) as ex:
            fut_to_it = {}
            for it in instances:
                if cancel is not None and cancel():
                    raise FindCancelled()
                x, z = it["x"], it["z"]
                fut = ex.submit(
                    _probe_instance, ui_key, enum_k, seed, x, z,
                    int(it.get("biome", -1)), version, era, item_full)
                fut_to_it[fut] = it
            if first_hit:
                # 找到第一个命中立即返回（不追求最近，更快）
                for fut in as_completed(fut_to_it):
                    if cancel is not None and cancel():
                        raise FindCancelled()
                    it = fut_to_it[fut]
                    try:
                        comp, hits = fut.result()
                    except Exception:
                        continue
                    if not hits:
                        continue
                    x, z = it["x"], it["z"]
                    d2 = (x - cx) ** 2 + (z - cz) ** 2
                    return {
                        "struct_key": ui_key,
                        "struct_name": catalog.struct_name(ui_key),
                        "anchor": (x, z),
                        "x": x, "z": z,
                        "biome": int(it.get("biome", -1)),
                        "variant": comp.variant_name,
                        "distance": d2,
                        "hits": hits,
                    }
            else:
                done: list = []
                for fut in fut_to_it:
                    it = fut_to_it[fut]
                    try:
                        comp, hits = fut.result()
                    except Exception:
                        continue
                    done.append((it, comp, hits))

                # 结构内取最近命中
                for it, comp, hits in done:
                    if not hits:
                        continue
                    x, z = it["x"], it["z"]
                    d2 = (x - cx) ** 2 + (z - cz) ** 2
                    if best is not None and d2 > best["_d2"]:
                        continue
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