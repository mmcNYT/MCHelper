# -*- coding: utf-8 -*-
"""陆地结构渲染：把 jigsaw / 单模板结构还原成真实方块（替代矩形近似）。

MC 26.2 的陆地结构分三类：
  A) jigsaw 型：由 template_pool 递归拼接 —— 村庄、掠夺者前哨、
     远古城市、废墟遗迹、试炼密室、堡垒遗迹。
     复用 village_jigsaw_exact 的拼接器（连接点匹配 + 旋转 + 不重叠）。
  B) 固定模板型：Java 代码把少量模板按固定方式堆叠 ——
     雪屋(igloo: bottom+middle+top)、沉船、废弃传送门。
  C) 纯程序化型：无 NBT 模板，由 Java 逐方块生成 ——
     沙漠神殿、丛林神庙、沼泽小屋、林地府邸（府邸有房间模板但
     组装算法复杂）。这类仍用**按真实尺寸**的 footprint 近似。
"""
from __future__ import annotations

import json

import numpy as np

from Utils.MapPreviewer import village_jigsaw as _vj

# 结构 key -> (类型, 参数)
#   jigsaw: 起始 pool；stack: 模板列表(自下而上)；pick: 模板目录
_JIGSAW_START = {
    "pillager_outpost": "minecraft:pillager_outpost/base_plates",
    "ancient_city": "minecraft:ancient_city/city_center",
    "trail_ruins": "minecraft:trail_ruins/tower",
    "trial_chambers": "minecraft:trial_chambers/chamber/end",
    "bastion_remnant": "minecraft:bastion/starts",
}
# 固定堆叠：自下而上的模板路径
_STACK = {
    "igloo": ["minecraft:igloo/bottom", "minecraft:igloo/middle",
              "minecraft:igloo/top"],
}
# 从目录中按种子挑一个模板
_PICK = {
    "shipwreck": "minecraft:shipwreck/",
    "ruined_portal": "minecraft:ruined_portal/",
}
# 纯程序化结构：(宽, 长) 取自 MC 实际占地
_PROCEDURAL = {
    "desert_pyramid": (21, 21),
    "jungle_temple": (12, 12),
    "swamp_hut": (10, 12),
    "mansion": (20, 30),
}

_SKIP = {"air", "jigsaw", "structure_void", "cave_air", "void_air", ""}


def _pick_one(loc_prefix: str, seed: int, ax: int, az: int) -> str | None:
    """从模板目录里按 (seed, 坐标) 稳定地挑一个模板。"""
    jar = _vj._jar()
    stem = loc_prefix.split(":", 1)[-1].strip("/")
    pre = "data/minecraft/structure/%s/" % stem
    cands = sorted(n[len(pre):-4] for n in jar.namelist()
                   if n.startswith(pre) and n.endswith(".nbt"))
    cands = [c for c in cands if "/" not in c]
    if not cands:
        return None
    # 稳定散列：同一结构每次渲染选同一模板
    h = (seed * 2654435761 ^ ax * 40503 ^ az * 97) & 0x7FFFFFFF
    return "minecraft:%s/%s" % (stem, cands[h % len(cands)])


def _stamp_template(loc: str, ox: int, oy: int, oz: int,
                    out: list, seen: set) -> int:
    """把一个模板放到世界坐标 (ox,oy,oz)（原点=模板最小角）。"""
    tpl = _vj.load_template(loc)
    if tpl is None:
        return 0
    n = 0
    for (x, y, z, nm) in tpl["blocks"]:
        if nm.split(":")[-1] in _SKIP:
            continue
        out.append((ox + x, oy + y, oz + z, nm))
        n += 1
    return n


def structure_blocks(key: str, seed: int, ax: int, az: int,
                     base_y: int, max_blocks: int = 60000) -> list:
    """返回该结构在世界坐标下的实体方块列表 [(x,y,z,name)]。

    空列表表示该结构无模板（调用方应回退到 footprint 近似）。
    """
    out: list = []
    if key in _JIGSAW_START:
        try:
            from Utils.MapPreviewer import village_jigsaw_exact as _vx
            r = _vx.build_jigsaw(seed, ax, az, _JIGSAW_START[key],
                                 base_y=base_y, max_blocks=max_blocks)
            for (x, y, z, nm) in r["blocks"]:
                if nm.split(":")[-1] not in _SKIP:
                    out.append((x, y, z, nm))
        except Exception:
            return []
        return out
    if key in _STACK:
        seen = set()
        y = base_y
        for loc in _STACK[key]:
            tpl = _vj.load_template(loc)
            if tpl is None:
                return []
            _stamp_template(loc, ax - tpl["size"][0] // 2, y,
                            az - tpl["size"][2] // 2, out, seen)
            y += tpl["size"][1]          # 自下而上堆叠
        return out
    if key in _PICK:
        loc = _pick_one(_PICK[key], seed, ax, az)
        if not loc:
            return []
        tpl = _vj.load_template(loc)
        if tpl is None:
            return []
        _stamp_template(loc, ax - tpl["size"][0] // 2, base_y,
                        az - tpl["size"][2] // 2, out, set())
        return out
    return []


def procedural_size(key: str):
    """纯程序化结构的真实占地尺寸（无模板可用）。"""
    return _PROCEDURAL.get(key)


def has_template(key: str) -> bool:
    return (key in _JIGSAW_START or key in _STACK or key in _PICK)
