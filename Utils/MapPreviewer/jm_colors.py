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

# ===========================================================================
# JourneyMap BaseRenderer.setStratumColors 的参数与合成（实测默认值）
# ===========================================================================
TWEAK_MOONLIGHT_LEVEL = 0.20
TWEAK_BRIGHTEN_DAYLIGHT_DIFF = 0.06
TWEAK_BRIGHTEN_LIGHTSOURCE_BLOCK = 1.2
TWEAK_BLEND_SHALLOW_WATER = 0.15
TWEAK_MINIMUM_DARKEN_NIGHT_WATER = 0.25
TWEAK_WATER_COLOR_BLEND = 0.5
TWEAK_SURFACE_AMBIENT_COLOR = 26

# 头顶是全亮天空时的光照级别（MC max light）
_MAX_LIGHT = 15.0


def blend_with(under, over, alpha: float):
    """对应 RGB.blendWith：c = under*(1-a) + over*a。"""
    if alpha >= 1.0:
        return over
    if alpha <= 0.0:
        return under
    return tuple(int(round(u * (1.0 - alpha) + o * alpha))
                 for u, o in zip(under, over))


def stratom_colors(block_color, light_level: int, light_attenuation: int = 0,
                   is_water: bool = False, water_color=None,
                   underwater: bool = False):
    """复刻 BaseRenderer.setStratumColors：按光照计算 day/night 两套颜色。

    light_level: 0..15（我方可由高度/深度近似）
    light_attenuation: 水下每格衰减（水深）
    underwater: 是否在水下（走水色混合分支）
    返回 (dayColor, nightColor) 两个 (r,g,b)。
    """
    base = float(block_color[0]), float(block_color[1]), float(block_color[2])
    # 日间亮度：光照 / 15，叠加 tweakBrightenDaylightDiff
    day_b = max(1.0, max(light_level - light_attenuation, 0.0)) / _MAX_LIGHT
    day_b = day_b + TWEAK_BRIGHTEN_DAYLIGHT_DIFF
    # 夜间亮度：moonlight 衰减后 / 15
    night_b = max(TWEAK_MOONLIGHT_LEVEL,
                  max(light_level - TWEAK_MOONLIGHT_LEVEL - light_attenuation,
                      0.0)) / _MAX_LIGHT

    day = tuple(min(255.0, c * day_b) for c in base)
    if underwater and water_color is not None:
        day = blend_with(day, water_color, TWEAK_WATER_COLOR_BLEND)
    night = tuple(min(255.0, c * night_b) for c in day)
    return (tuple(int(round(c)) for c in day),
            tuple(int(round(c)) for c in night))


def light_from_sky(block_y: int, surface_y: int, sea_level: int = 63):
    """用高度近似 MC 天空光：地表及以上全亮，水下沉降。"""
    if block_y >= surface_y:
        return 15
    depth = surface_y - block_y
    return max(0, 15 - depth)

# ===========================================================================
# JourneyMap 斜坡阴影（BaseRenderer.shading* + RGB.bevelSlope）
# ===========================================================================
SHADING_SLOPE_MIN = 0.2
SHADING_SLOPE_MAX = 1.7
SHADING_PRIMARY_DOWNSLOPE = 0.65
SHADING_PRIMARY_UPSLOPE = 1.2
SHADING_SECONDARY_DOWNSLOPE = 0.95
SHADING_SECONDARY_UPSLOPE = 1.05
BEVEL_DARKEN = 0.85        # RGB.bevelSlope 里对 R/G 的额外压暗


def bevel_slope(color, slope: float):
    """对应 RGB.bevelSlope：斜坡同时变暗并偏蓝（R/G 额外 *0.85）。"""
    f = BEVEL_DARKEN if slope < 1.0 else 1.0
    r, g, b = color
    return (int(min(255, round(r * f * slope))),
            int(min(255, round(g * f * slope))),
            int(min(255, round(b * slope))))


def slope_from_heights(heights: np.ndarray, x0: int, z0: int):
    """按 JourneyMap 的 primary/secondary 偏移算每列坡度因子。

    JourneyMap 用相对邻列的**高度差**（主/次两个方向，各自有上下坡系数），
    夹到 [slopeMin, slopeMax] -> 纯地形驱动、确定性、不随机。
    """
    h = heights.astype(np.float32)
    hh, ww = h.shape
    # 主方向（西北）与次方向（东南）的偏移
    def shift(a, dy, dx):
        out = np.empty_like(a)
        ys = np.clip(np.arange(hh) + dy, 0, hh - 1)
        xs = np.clip(np.arange(ww) + dx, 0, ww - 1)
        out[:] = a[np.ix_(ys, xs)]
        return out

    # 主：向北(-z)、向西(-x)；次：向南(+z)、向东(+x)
    hn = shift(h, -1, 0)
    hw = shift(h, 0, -1)
    hs = shift(h, 1, 0)
    he = shift(h, 0, 1)
    d_primary = ((hn - h) + (hw - h)) * 0.5      # >0 表示上坡
    d_second = ((hs - h) + (he - h)) * 0.5
    slope = np.ones_like(h)
    slope += np.where(d_primary > 0, d_primary * (SHADING_PRIMARY_UPSLOPE - 1.0),
                      d_primary * (1.0 - SHADING_PRIMARY_DOWNSLOPE))
    slope += np.where(d_second > 0, d_second * (SHADING_SECONDARY_UPSLOPE - 1.0),
                      d_second * (1.0 - SHADING_SECONDARY_DOWNSLOPE))
    return np.clip(slope, SHADING_SLOPE_MIN, SHADING_SLOPE_MAX)
