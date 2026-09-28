# -*- coding: utf-8 -*-
"""C++ jigsaw 引擎桥接层（M3 集成）。

在 keep 与 Python 引擎 `jigsaw_assembly.assemble_jigsaw` 字节级一致的
前提下，把 C++ 扩展 `_jigsaw_engine.assemble` 的结果无缝转回
`jigsaw_assembly.JigsawPiece` 对象，供 StructurePreviewer 的
`composition` / `_piece_containers_world` 等既有 Python 层直接消费。

对外接口：
    marshal(load_pool_fn, load_template_fn, start_pool_id)
        -> (tl, pl)  模板/池 -> C++ 可接收的扁平结构
    assemble(seed, cx, cz, *, start_pool_id, max_depth, start_y,
             start_y_is_offset, max_dist, pad_bottom, pad_top,
             skip_y_bound, expansion_hack, start_jigsaw_name,
             load_pool_fn, load_template_fn)
        -> jigsaw_assembly.AssemblyResult（C++ 引擎结果转回 Python 对象）

marshal 一次性收集从 start_pool 可达的池与模板全集（BFS，闭包语义与
jigsaw_assembly.expanded_pool / _Placer 的池引用完全一致）；C++ 扩展
内部对模板按 key 做跨调用缓存（模板内容跨 chunk 固定，见 jigsaw_engine.cpp
的 g_tpl_cache），池随 alias 逐 chunk 变化每次传入，保证字节级对拍不变。

正确性约定：
  - 只对已通过 _m2_parity 逐字节对拍的结构走 C++（当前仅 trial_chambers）；
    其余结构仍走 Python 引擎（调用方显式选择）。接入新结构前必须先
    完成该结构的 C++ vs Python 对拍。
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

from . import jigsaw_assembly as JA
from .mc_rng import ROTATIONS

# C++ 扩展位于本模块同目录的 cpp/ 子目录，主动加入 import 路径。
_cpp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cpp")
if _cpp_dir not in sys.path:
    sys.path.insert(0, _cpp_dir)

# 方向字符串 -> C++ 数值（与 jigsaw_engine.cpp 的 DIRC 一致）
_DIRC = {"down": 0, "up": 1, "north": 2, "south": 3, "west": 4, "east": 5}


def _joint(v):
    return 0 if v == "aligned" else (1 if v == "rollable" else -1)


def _strip(rid):
    if rid is None:
        return ""
    return rid.split(":", 1)[-1] if ":" in rid else rid


def _marshal(load_pool_fn, load_template_fn, start_pool_id):
    """从 start_pool 出发闭包收集全部可达池与模板 -> (tl, pl)。"""
    pools: Dict[str, dict] = {}
    templates: Dict[str, dict] = {}
    pool_keys = {start_pool_id}
    tpl_keys: set = set()
    changed = True
    while changed:
        changed = False
        for pid in list(pool_keys):
            if pid in pools:
                continue
            if pid == "empty":
                pools[pid] = {"id": pid, "elements": [], "fallback": ""}
                continue
            rp = load_pool_fn(pid)
            if rp is None:
                pools[pid] = {"id": pid, "elements": [], "fallback": ""}
                continue
            es = []
            for el in rp.elements:
                if isinstance(el, JA.ListPoolElementSpec):
                    es.append([el.location, "", el.projection, el.weight, "",
                               True, list(el.sub_locations),
                               list(el.sub_processors)])
                    for loc in el.sub_locations:
                        if loc and loc not in tpl_keys:
                            tpl_keys.add(loc); changed = True
                else:
                    es.append([el.location, el.element_type, el.projection,
                               el.weight, el.processors or "", False, [], []])
                    if el.location and el.location not in tpl_keys:
                        tpl_keys.add(el.location); changed = True
            fb = rp.fallback or ""
            pools[pid] = {"id": pid, "elements": es, "fallback": fb}
            if fb and fb not in pool_keys:
                pool_keys.add(fb); changed = True
        for tkey in list(tpl_keys):
            if tkey in templates:
                continue
            try:
                t = load_template_fn(tkey)
            except Exception:
                t = None
            if t is None:
                continue
            ms = []
            for m in t.markers:
                ms.append([m.local_pos[0], m.local_pos[1], m.local_pos[2],
                           _DIRC[m.front], _DIRC[m.top], _joint(m.joint),
                           m.name, m.target, m.pool, m.placement_priority])
                mp = _strip(m.pool)
                if mp and mp not in pool_keys:
                    pool_keys.add(mp); changed = True
            templates[tkey] = {"key": tkey,
                               "size": [t.size_x, t.size_y, t.size_z],
                               "markers": ms}
    tl = [[v["key"], v["size"], v["markers"]] for v in templates.values()]
    pl = [[p["id"], p["elements"], p["fallback"]] for p in pools.values()]
    return tl, pl


def assemble(seed: int, chunk_x: int, chunk_z: int, *,
             start_pool_id: str, max_depth: int, start_y: int,
             start_y_is_offset: bool, max_dist: int,
             pad_bottom: int = 0, pad_top: int = 0,
             skip_y_bound: Optional[int] = None,
             expansion_hack: bool = False,
             start_jigsaw_name: Optional[str] = None,
             load_pool_fn=None, load_template_fn=None) -> JA.AssemblyResult:
    """C++ 引擎入口（仅对已对拍结构使用）。

    与 jigsaw_assembly.assemble_jigsaw 同签名约定；返回同样式
    AssemblyResult（pieces 为 JigsawPiece 对象）。
    """
    import _jigsaw_engine as ENG
    tl, pl = _marshal(load_pool_fn, load_template_fn, start_pool_id)
    res = ENG.assemble(
        seed, chunk_x, chunk_z, max_depth, start_y, max_dist,
        pad_bottom, pad_top, skip_y_bound or 0,
        1 if start_y_is_offset else 0,
        1 if expansion_hack else 0,
        start_pool_id, start_jigsaw_name or "", tl, pl)
    cpp_pieces, start_index = res
    pieces = []
    for raw in cpp_pieces:
        key, pos, rot, box, depth, subls, subpr = raw
        tpl = load_template_fn(key)
        p = JA.JigsawPiece(
            template=tpl, rot=ROTATIONS[rot],
            piece_pos=(pos[0], pos[1], pos[2]),
            box=JA.BBox(*box), depth=depth, projection="rigid",
            sub_templates=list(subls) if subls else None,
            sub_processors=list(subpr) if subpr else None)
        pieces.append(p)
    return JA.AssemblyResult(pieces=pieces, start_index=start_index,
                             rng_calls=[])