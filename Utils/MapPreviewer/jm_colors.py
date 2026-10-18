# -*- coding: utf-8 -*-
"""按 JourneyMap 的实现思路做方块配色（单色/方块，天然不破碎）。

JourneyMap 5.9 的实测结论（反编译 journeymap-1.20.1-5.9.18-forge.jar）：
  - BlockMD.getTextureColor() 把每种方块（含 state）解析成一个 int 颜色，
    并缓存在 BlockMD.color 字段 -> 与坐标无关，同方块必同色
  - VanillaBlockColorProxy.deriveBlockColor():
      * LiquidBlock -> getSpriteColor(固定 12369084) 流体色
      * 其它       -> getSpriteColor() 取贴图平均色，
                      失败则 setBlockColorToMaterial() 按材质兜底
      * 树叶(isFoliage) -> RGB.adjustBrightness(color, 0.8f) 统一压暗 80%
  - RGB.adjustBrightness(c, f) = 每个通道 * f 后 clamp
  - 渲染时 Strata 取每列最上方的不透明方块作该列颜色

即：**颜色是"方块类型"的函数，不是"坐标"的函数**。这正是"同层同色、
不破碎"的根本原因。本模块据此构建调色板：颜色只查表，绝不逐点随机。
"""
from __future__ import annotations

import os

import numpy as np

from Utils.MapPreviewer import block_textures as _btex

# JourneyMap 的树叶压暗系数（VanillaBlockColorProxy 里硬编码 0.8f）
FOLIAGE_BRIGHTNESS = 0.8

# JourneyMap 的流体基准色（LiquidBlock 分支 12369084 = 0xBCBFBC ?）
# 实际为 water 的 sprite 基准，这里以 jar 贴图均值为准并保留该常量语义
WATER_BASE = 12369084

# 需要按"树叶"处理（压暗 0.8）的方块短名关键字
_FOLIAGE_KEYS = ("leaves", "vine", "grass_block", "fern", "grass",
                 "lily_pad", "azalea", "moss", "flower", "bush")


def adjust_brightness(rgb: np.ndarray, factor: float) -> np.ndarray:
    """对应 JourneyMap RGB.adjustBrightness：各通道乘系数并 clamp。"""
    return np.clip(rgb.astype(np.float32) * factor, 0, 255).astype(np.uint8)


def is_foliage(block_name: str) -> bool:
    n = block_name.split(":")[-1]
    return any(k in n for k in _FOLIAGE_KEYS)


def build_block_palette(block_names: list[str]) -> dict[str, tuple]:
    """构建 {方块名: (r,g,b)}：取 16x16 顶面贴图平均色（JourneyMap 同法）。

    颜色只与方块类型相关 -> 同方块必同色，绝不破碎。
    """
    atlas = _btex.load_atlas(list(block_names))
    out: dict[str, tuple] = {}
    for nm in block_names:
        art = atlas.get(nm)
        if art is None:
            continue
        # 取不透明像素均值（JourneyMap getSpriteColor 亦为均值思路）
        mean = art.reshape(-1, 3).mean(axis=0)
        rgb = np.clip(mean, 0, 255).astype(np.uint8)
        # 注意：foliage 压暗统一在 tinted_color() 里做一次，此处不做，
        # 否则灰度贴图会双重压暗（实测草地因此偏暗 36%）。
        out[nm] = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    return out

# ---- 灰度贴图 -> 群系 tint（对应 JourneyMap 的 biome color 逻辑）----
# MC 的 grass/water/foliage 贴图是灰度图，真实颜色 = 灰度 * 群系 tint。
# JourneyMap 在 mapBiome/mapWaterBiomeColors 开启时也走这条路径。
_GRASS_TINT = (0x91, 0xBD, 0x59)      # MC 平原草地基准（vanilla grass color）
_FOLIAGE_TINT = (0x77, 0xA8, 0x4A)    # vanilla foliage
_WATER_TINT = (0x3F, 0x76, 0xE4)      # vanilla water

# 群系 -> 草色 tint（量化，保证同群系同色）
_BIOME_TINTS = {
    "forest": (0x84, 0xB4, 0x60), "birch_forest": (0x8C, 0xBC, 0x66),
    "dark_forest": (0x72, 0xA4, 0x54), "taiga": (0x7A, 0xAA, 0x66),
    "jungle": (0x6C, 0xC0, 0x50), "savanna": (0xC0, 0xC0, 0x72),
    "desert": (0xCC, 0xC4, 0x7C), "swamp": (0x74, 0x86, 0x50),
    "snowy_plains": (0xA8, 0xC0, 0xA8), "plains": (0x91, 0xBD, 0x59),
}
_BIOME_TINT_DEFAULT = (0x91, 0xBD, 0x59)


def tint_for_biome(kind: str, biome_short: str) -> tuple:
    """取某类（grass/foliage/water）在指定群系的 tint。"""
    if kind == "water":
        return _WATER_TINT
    if kind == "foliage":
        return _FOLIAGE_TINT
    return _BIOME_TINTS.get(biome_short, _BIOME_TINT_DEFAULT)


def tinted_color(block_name: str, biome_short: str,
                 palette: dict) -> tuple:
    """返回方块在某群系下的最终颜色（灰度贴图 * tint）。

    非灰度方块直接返回调色板色；草/叶/水按群系 tint 着色后，
    树叶再压暗 0.8（JourneyMap 同法）。
    """
    base = palette.get(block_name)
    if base is None:
        return None
    n = block_name.split(":")[-1]
    is_gray = n in ("grass_block", "water", "oak_leaves", "birch_leaves",
                    "spruce_leaves", "jungle_leaves", "acacia_leaves",
                    "dark_oak_leaves", "mangrove_leaves", "cherry_leaves")
    if not is_gray:
        return base
    if n == "water":
        kind = "water"
    elif "leaves" in n:
        kind = "foliage"
    else:
        kind = "grass"
    tr, tg, tb = tint_for_biome(kind, biome_short)
    # base 是灰度均值 b；tint 色 = tint * (b/255)
    g = min(1.0, float(base[1]) / 150.0)   # 灰度贴图均值约 150
    col = (tr * g, tg * g, tb * g)
    if is_foliage(block_name):
        col = tuple(c * FOLIAGE_BRIGHTNESS for c in col)
    return tuple(int(min(255, max(0, round(c)))) for c in col)
