# -*- coding: utf-8 -*-
"""MC 真实树木摆放（复刻 per-chunk feature 放置算法）。

MC 的植被放置（ChunkGenerator.applyBiomeDecoration）：
  1. 对每个 chunk 的每个 decoration step：
     rng = WorldgenRandom.setPopulationSeed(seed, chunkX*16, chunkZ*16)
     再 setDecorrelatedSeed(step_index)  -- 每个 step 独立随机流
  2. 该 step 内每个 feature 依次执行其 placement modifiers：
     - count(n) / weighted_list：先 nextInt 决定本 chunk 该 feature 的尝试次数
     - in_square：每次 nextFloat*16 决定 chunk 内偏移
     - heightmap / biome filter：位置落在有效地表才算数
  3. 树本身从放置点生长（树干 + 冠层）

本模块复刻 1-2 的随机流与偏移语义，3 用固定冠层形状近似（真实树形
由 TreeFeature 的随机分支决定，逐方块复刻代价极高且视觉差异小）。
"""
from __future__ import annotations

import json
import os

import numpy as np

from Utils.MapPreviewer import vegetation as _veg
from Utils.Public.structure_map import (
    get_population_seed, Xoroshiro, _x_next_int_pow2)

_WG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "_native", "worldgen", "26.2")
_MASK64 = (1 << 64) - 1

# decoration step 里植被所在的索引（VEGETAL_DECORATION）
_VEG_STEP = 9

# 各主导树种的常见混生伙伴（真实森林多树种，也提供色相变化）
_MIX = {
    "oak": ("birch", "oak", "spruce", "dark_oak"),
    "birch": ("oak", "birch", "spruce"),
    "spruce": ("spruce", "pine", "oak"),
    "pine": ("pine", "spruce", "oak"),
    "jungle": ("jungle", "oak"),
    "dark_oak": ("dark_oak", "oak", "birch"),
    "acacia": ("acacia", "oak"),
    "swamp": ("swamp", "oak"),
    "mangrove": ("mangrove", "oak"),
}


class _Rng:
    """Per-chunk feature RNG（Xoroshiro + Java nextInt/nextFloat 语义）。"""

    __slots__ = ("_xr",)

    def __init__(self, seed: int):
        self._xr = Xoroshiro.from_seed(seed & _MASK64)

    def next_int(self, bound: int) -> int:
        """Java Random.nextInt(bound)（Xoroshiro 版本）。"""
        if bound <= 0:
            return 0
        if bound & (bound - 1) == 0:            # 2 的幂走特判
            return _x_next_int_pow2(self._xr, bound)
        # 非 2 幂：取 31 位余数（与 XoroshiroRandomSource.nextInt 一致）
        v = self._xr.next_long() >> 33
        return v % bound

    def next_float(self) -> float:
        return (self._xr.next_long() >> 40) / float(1 << 24)


def _decorrelated(seed: int, cx: int, cz: int, step: int) -> int:
    """chunk (cx,cz) 在 step 的 decorrelated seed。"""
    base = get_population_seed(seed, cx * 16, cz * 16)
    # setDecorrelatedSeed：base XOR (step+1)*黄金比例常数
    return (base ^ ((step + 1) * 0x9E3779B97F4A7C15)) & _MASK64


def chunk_trees(seed: int, cx: int, cz: int, biome_key: str,
                surface_y: np.ndarray):
    """返回该 chunk 的树位置列表 [(bx, bz, species, canopy_radius)]。

    surface_y: (16,16) 该 chunk 的顶块高度；None 表示该列不可放。
    """
    prof = _veg.biome_vegetation(biome_key)
    attempts = prof["tree"] * 256.0     # tree_p 是"每方块概率"，×256 = 每chunk次数
    if attempts <= 0.05:
        return []
    n = int(round(attempts))
    if n <= 0:
        return []
    rng = _Rng(_decorrelated(seed, cx, cz, _VEG_STEP))
    species = prof["species"]
    rad, col = _veg.species_canopy(species)
    mix = _MIX.get(species, ())
    out = []
    for _ in range(n):
        # in_square：nextFloat*16 取整
        dx = int(rng.next_float() * 16.0)
        dz = int(rng.next_float() * 16.0)
        dx = min(max(dx, 0), 15)
        dz = min(max(dz, 0), 15)
        # heightmap filter：该列必须有有效地表
        if surface_y is None or surface_y[dz, dx] < -64:
            continue
        # 混生：按 chunk RNG 以一定概率换成次要树种（真实森林非单一树种），
        # 这也是参考图色相丰富（黄绿/深绿/蓝绿并存）的来源。
        sp2, rad2, col2 = species, rad, col
        if mix and rng.next_float() < 0.45:
            sp2 = mix[int(rng.next_float() * len(mix)) % len(mix)]
            rad2, col2 = _veg.species_canopy(sp2)
        out.append((cx * 16 + dx, cz * 16 + dz, sp2, rad2, col2))
    return out


def place_trees_in_rect(seed: int, x0: int, z0: int, w: int, h: int,
                        heights: np.ndarray, biome_grid: np.ndarray,
                        id2key: dict) -> list:
    """枚举矩形内所有 chunk 的树，返回 [(px,py,species,rad,col)] 屏幕坐标。"""
    trees = []
    cx0, cz0 = x0 >> 4, z0 >> 4
    cx1, cz1 = (x0 + w - 1) >> 4, (z0 + h - 1) >> 4
    for cz in range(cz0, cz1 + 1):
        for cx in range(cx0, cx1 + 1):
            # 该 chunk 中心群系
            sy = (cz * 16 + 8 - z0)
            sx = (cx * 16 + 8 - x0)
            sy = min(max(sy, 0), h - 1)
            sx = min(max(sx, 0), w - 1)
            bkey = id2key.get(int(biome_grid[sy, sx]), "minecraft:plains")
            # 该 chunk 的 16x16 高度子块
            sub = np.full((16, 16), -64, np.int16)
            gx0, gz0 = cx * 16, cz * 16
            ry0 = max(gz0, z0); ry1 = min(gz0 + 16, z0 + h)
            rx0 = max(gx0, x0); rx1 = min(gx0 + 16, x0 + w)
            if ry1 > ry0 and rx1 > rx0:
                sub[ry0 - gz0:ry1 - gz0, rx0 - gx0:rx1 - gx0] = \
                    heights[ry0 - z0:ry1 - z0, rx0 - x0:rx1 - x0]
            for (bx, bz, sp, rad, col) in chunk_trees(seed, cx, cz, bkey, sub):
                px, pz = bx - x0, bz - z0
                if 0 <= px < w and 0 <= pz < h:
                    trees.append((px, pz, sp, rad, col, int(heights[pz, px])))
    return trees
