# -*- coding: utf-8 -*-
"""实体图标查询：assets/CommandGenerator/entities/<id>.png。

215 个全部有图标 —— 来源三层（fetch_entity5.py 下载 140 +
fill_entity_alias.py 别名补全 72 + 手工 3）：
  1. Wiki EntitySprite 直配（villager、zombie、creeper…）
  2. 别名回退（boat->oak_boat 物品、horse->horse_spawn_egg 刷怪蛋、
     子类型 villager.armorer->villager）
  3. 技术实体占位（marker->structure_void、item->chest…）
"""
from __future__ import annotations

import os

_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "assets", "CommandGenerator", "entities")

_cache: dict[str, str | None] = {}


def entity_icon_path(eid: str) -> str | None:
    """实体 id -> 图标路径（无图标返回 None）。"""
    if not eid:
        return None
    if eid in _cache:
        return _cache[eid]
    base = eid.removeprefix("minecraft:").split('.')[0]   # 子类型回退
    p = os.path.join(_DIR, f"{base}.png")
    _cache[eid] = p if os.path.isfile(p) else None
    return _cache[eid]
