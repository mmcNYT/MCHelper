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
# 注意：grass_block 用**草色 tint**，不属于 foliage，不能压暗 0.8。
# （JourneyMap 的 isFoliage() 只对树叶类返回真）
_FOLIAGE_KEYS = ("leaves", "vine", "lily_pad", "azalea", "moss_carpet",
                 "bush", "crop", "fern")


def adjust_brightness(rgb: np.ndarray, factor: float) -> np.ndarray:
    """对应 JourneyMap RGB.adjustBrightness：各通道乘系数并 clamp。"""
    return np.clip(rgb.astype(np.float32) * factor, 0, 255).astype(np.uint8)


def is_foliage(block_name: str) -> bool:
    n = block_name.split(":")[-1]
    return any(k in n for k in _FOLIAGE_KEYS)


# 官方 JourneyMap 瓦片实测基色（族内最高频，对应平地 slope=1.0）
_OFFICIAL_BASE = {
    "snow_block": (255, 255, 255),
    "powder_snow": (255, 255, 255),
    "sand": (232, 219, 173),
    "red_sand": (232, 219, 173),
    "gravel": (138, 131, 121),
    "stone": (160, 160, 160),
}


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
        # 非 tint 类方块按官方瓦片实测基色校正（贴图均值系统性偏暗 1.06x）
        _short = nm.split(":")[-1]
        _fix = _OFFICIAL_BASE.get(_short)
        if _fix is not None:
            rgb = np.array(_fix, np.uint8)
        out[nm] = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    return out

# ---- 灰度贴图 -> 群系 tint（对应 JourneyMap 的 biome color 逻辑）----
# MC 的 grass/water/foliage 贴图是灰度图，真实颜色 = 灰度 * 群系 tint。
# JourneyMap 在 mapBiome/mapWaterBiomeColors 开启时也走这条路径。
_GRASS_TINT = (0x91, 0xBD, 0x59)      # MC 平原草地基准（vanilla grass color）
_FOLIAGE_TINT = (0x77, 0xA8, 0x4A)    # vanilla foliage
_WATER_TINT = (0x3F, 0x76, 0xE4)      # vanilla water

# 群系 -> 草色 tint（26.2 官方语义全量生成，勿手改单值）：
#   effects.grass_color 显式值优先；否则 Biome.getGrassColor 的
#   clamp(temp,0,1)/clamp(downfall,0,1) -> ColorMapColorUtil.get:
#   rain=downfall*temp; x=(int)((1-temp)*255); y=(int)((1-rain)*255);
#   grass.png[y,x] 单像素。
#   dark_forest 另叠 modifier 混合 ((base&0xFEFEFE)+0x28340A)>>1（常数）；
#   swamp/mangrove_swamp 草色是逐坐标噪声二值（BIOME_INFO_NOISE seed
#   2345，<-0.1 取 (76,96,60) 否则 (106,112,57)，JM 再叠 5×5 平均），
#   表值 (106,112,57) 仅 fallback，渲染侧 block_render 逐坐标复刻。
#   生成脚本 .temp/gen_tint_tables.py。
_BIOME_TINTS = {
    "badlands": (144, 129, 77), "bamboo_jungle": (89, 201, 60), "basalt_deltas": (191, 183, 85),
    "beach": (145, 189, 89), "birch_forest": (136, 187, 103), "cherry_grove": (182, 219, 97),
    "cold_ocean": (142, 185, 113), "crimson_forest": (191, 183, 85), "dark_forest": (80, 122, 50),
    "deep_cold_ocean": (142, 185, 113), "deep_dark": (145, 189, 89), "deep_frozen_ocean": (142, 185, 113),
    "deep_lukewarm_ocean": (142, 185, 113), "deep_ocean": (142, 185, 113), "desert": (191, 183, 85),
    "dripstone_caves": (145, 189, 89), "end_barrens": (142, 185, 113), "end_highlands": (142, 185, 113),
    "end_midlands": (142, 185, 113), "eroded_badlands": (144, 129, 77), "flower_forest": (121, 192, 90),
    "forest": (121, 192, 90), "frozen_ocean": (128, 180, 151), "frozen_peaks": (128, 180, 151),
    "frozen_river": (128, 180, 151), "grove": (128, 180, 151), "ice_spikes": (128, 180, 151),
    "jagged_peaks": (128, 180, 151), "jungle": (89, 201, 60), "lukewarm_ocean": (142, 185, 113),
    "lush_caves": (142, 185, 113), "mangrove_swamp": (106, 112, 57), "meadow": (131, 187, 109),
    "mushroom_fields": (85, 201, 63), "nether_wastes": (191, 183, 85), "ocean": (142, 185, 113),
    "old_growth_birch_forest": (136, 187, 103), "old_growth_pine_taiga": (134, 184, 127), "old_growth_spruce_taiga": (134, 183, 131),
    "pale_garden": (119, 130, 114), "plains": (145, 189, 89), "river": (142, 185, 113),
    "savanna": (191, 183, 85), "savanna_plateau": (191, 183, 85), "small_end_islands": (142, 185, 113),
    "snowy_beach": (131, 181, 147), "snowy_plains": (128, 180, 151), "snowy_slopes": (128, 180, 151),
    "snowy_taiga": (128, 180, 151), "soul_sand_valley": (191, 183, 85), "sparse_jungle": (100, 199, 63),
    "stony_peaks": (154, 190, 75), "stony_shore": (138, 182, 137), "sulfur_caves": (171, 166, 79),
    "sunflower_plains": (145, 189, 89), "swamp": (106, 112, 57), "taiga": (134, 183, 131),
    "the_end": (142, 185, 113), "the_void": (142, 185, 113), "warm_ocean": (142, 185, 113),
    "warped_forest": (191, 183, 85), "windswept_forest": (138, 182, 137), "windswept_gravelly_hills": (138, 182, 137),
    "windswept_hills": (138, 182, 137), "windswept_savanna": (191, 183, 85), "wooded_badlands": (144, 129, 77),
}
# 群系 -> 树叶 tint（26.2 官方语义全量生成，勿手改单值）：
#   effects.foliage_color 显式值优先；否则同上用 foliage.png[y,x]。
#   生成脚本 .temp/gen_tint_tables.py。
_BIOME_FOLIAGE_TINTS = {
    "badlands": (158, 129, 77), "bamboo_jungle": (48, 187, 11), "basalt_deltas": (174, 164, 42),
    "beach": (119, 171, 47), "birch_forest": (107, 169, 65), "cherry_grove": (182, 219, 97),
    "cold_ocean": (113, 167, 77), "crimson_forest": (174, 164, 42), "dark_forest": (89, 174, 48),
    "deep_cold_ocean": (113, 167, 77), "deep_dark": (119, 171, 47), "deep_frozen_ocean": (113, 167, 77),
    "deep_lukewarm_ocean": (113, 167, 77), "deep_ocean": (113, 167, 77), "desert": (174, 164, 42),
    "dripstone_caves": (119, 171, 47), "end_barrens": (113, 167, 77), "end_highlands": (113, 167, 77),
    "end_midlands": (113, 167, 77), "eroded_badlands": (158, 129, 77), "flower_forest": (89, 174, 48),
    "forest": (89, 174, 48), "frozen_ocean": (96, 161, 123), "frozen_peaks": (96, 161, 123),
    "frozen_river": (96, 161, 123), "grove": (96, 161, 123), "ice_spikes": (96, 161, 123),
    "jagged_peaks": (96, 161, 123), "jungle": (48, 187, 11), "lukewarm_ocean": (113, 167, 77),
    "lush_caves": (113, 167, 77), "mangrove_swamp": (141, 177, 39), "meadow": (100, 169, 72),
    "mushroom_fields": (43, 187, 15), "nether_wastes": (174, 164, 42), "ocean": (113, 167, 77),
    "old_growth_birch_forest": (107, 169, 65), "old_growth_pine_taiga": (104, 165, 95), "old_growth_spruce_taiga": (104, 164, 100),
    "pale_garden": (135, 141, 118), "plains": (119, 171, 47), "river": (113, 167, 77),
    "savanna": (174, 164, 42), "savanna_plateau": (174, 164, 42), "small_end_islands": (113, 167, 77),
    "snowy_beach": (100, 162, 120), "snowy_plains": (96, 161, 123), "snowy_slopes": (96, 161, 123),
    "snowy_taiga": (96, 161, 123), "soul_sand_valley": (174, 164, 42), "sparse_jungle": (62, 184, 15),
    "stony_peaks": (130, 172, 30), "stony_shore": (109, 163, 107), "sulfur_caves": (119, 171, 47),
    "sunflower_plains": (119, 171, 47), "swamp": (106, 112, 57), "taiga": (104, 164, 100),
    "the_end": (113, 167, 77), "the_void": (113, 167, 77), "warm_ocean": (113, 167, 77),
    "warped_forest": (174, 164, 42), "windswept_forest": (109, 163, 107), "windswept_gravelly_hills": (109, 163, 107),
    "windswept_hills": (109, 163, 107), "windswept_savanna": (174, 164, 42), "wooded_badlands": (158, 129, 77),
}
# 群系 -> 水色 tint（26.2 官方语义全量生成，勿手改单值）：
#   effects.water_color 即 JM 实际 tint 真值（反编译：BiomeMD 构造
#   透传 biome.getWaterColor()，ColorManager 默认色板同源；最终色 =
#   贴图 × water_color/255，无其他处理）。旧表部分键由官方瓦片反推，
#   与源码有偏差（5 处不一致 + 5 群系缺键错走默认，已全量按源码重建）。
#   deep_warm_ocean 群系 26.2 已移除，键保留兼容旧 id2key。
#   生成脚本 .temp/gen_water_table.py（源：_native/worldgen/26.2/biome，
#   共 66 群系 + 1 兼容键）。
_BIOME_WATER_TINTS = {
    "badlands": (63, 118, 228), "bamboo_jungle": (63, 118, 228), "basalt_deltas": (63, 118, 228),
    "beach": (63, 118, 228), "birch_forest": (63, 118, 228), "cherry_grove": (93, 183, 239),
    "cold_ocean": (61, 87, 214), "crimson_forest": (63, 118, 228), "dark_forest": (63, 118, 228),
    "deep_cold_ocean": (61, 87, 214), "deep_dark": (63, 118, 228), "deep_frozen_ocean": (57, 56, 201),
    "deep_lukewarm_ocean": (69, 173, 242), "deep_ocean": (63, 118, 228), "desert": (63, 118, 228),
    "dripstone_caves": (63, 118, 228), "end_barrens": (63, 118, 228), "end_highlands": (63, 118, 228),
    "end_midlands": (63, 118, 228), "eroded_badlands": (63, 118, 228), "flower_forest": (63, 118, 228),
    "forest": (63, 118, 228), "frozen_ocean": (57, 56, 201), "frozen_peaks": (63, 118, 228),
    "frozen_river": (57, 56, 201), "grove": (63, 118, 228), "ice_spikes": (63, 118, 228),
    "jagged_peaks": (63, 118, 228), "jungle": (63, 118, 228), "lukewarm_ocean": (69, 173, 242),
    "lush_caves": (63, 118, 228), "mangrove_swamp": (58, 122, 106), "meadow": (14, 78, 207),
    "mushroom_fields": (63, 118, 228), "nether_wastes": (63, 118, 228), "ocean": (63, 118, 228),
    "old_growth_birch_forest": (63, 118, 228), "old_growth_pine_taiga": (63, 118, 228), "old_growth_spruce_taiga": (63, 118, 228),
    "pale_garden": (118, 136, 157), "plains": (63, 118, 228), "river": (63, 118, 228),
    "savanna": (63, 118, 228), "savanna_plateau": (63, 118, 228), "small_end_islands": (63, 118, 228),
    "snowy_beach": (61, 87, 214), "snowy_plains": (63, 118, 228), "snowy_slopes": (63, 118, 228),
    "snowy_taiga": (61, 87, 214), "soul_sand_valley": (63, 118, 228), "sparse_jungle": (63, 118, 228),
    "stony_peaks": (63, 118, 228), "stony_shore": (63, 118, 228), "sulfur_caves": (52, 191, 137),
    "sunflower_plains": (63, 118, 228), "swamp": (97, 123, 100), "taiga": (63, 118, 228),
    "the_end": (63, 118, 228), "the_void": (63, 118, 228), "warm_ocean": (67, 213, 238),
    "warped_forest": (63, 118, 228), "windswept_forest": (63, 118, 228), "windswept_gravelly_hills": (63, 118, 228),
    "windswept_hills": (63, 118, 228), "windswept_savanna": (63, 118, 228), "wooded_badlands": (63, 118, 228),
    "deep_warm_ocean": (67, 213, 238),  # 26.2 已移除，保留兼容
}
_BIOME_FOLIAGE_DEFAULT = (119, 171, 73)
_BIOME_WATER_DEFAULT = (63, 118, 228)

# 树叶 tint 官方名单（26.2 反编译 client/color/block/BlockColors.java
# createDefault L26-36）：
#   biome foliage 色表: oak/jungle/acacia/dark_oak/mangrove（另有 vine）；
#   固定色: spruce=0x619961、birch=0x80A755（不随群系）；
#   无 tint（贴图原色）: cherry/azalea/flowering_azalea/pale_oak
#   （pale_oak 是 UntintedParticleLeavesBlock，BlockColors 无注册）。
# 不能按"贴图灰度"判定是否 tint：jungle_leaves 贴图自带绿基色
# （均值极差 13.1>8），被误判彩色后整片输出贴图灰 (166,164,156)
# ——竹林/稀疏丛林树叶全灰（2026-10-31 画廊实证，用户对照游戏截图报告）。
_LEAVES_BIOME_TINT = frozenset((
    "oak_leaves", "jungle_leaves", "acacia_leaves", "dark_oak_leaves",
    "mangrove_leaves",
))
_LEAVES_FIXED_TINT = {
    "spruce_leaves": (0x61, 0x99, 0x61),
    "birch_leaves": (0x80, 0xA7, 0x55),
}
# 官方无 tint 注册、且贴图近灰度（pale_oak 极差 7.3 会踩灰度判定）的
# 树叶：一律贴图原色，不得进入下方灰度分支被 tint
_LEAVES_NO_TINT = frozenset((
    "cherry_leaves", "azalea_leaves", "flowering_azalea_leaves",
    "pale_oak_leaves",
))


_BIOME_TINT_DEFAULT = (0x91, 0xBD, 0x59)


def tint_for_biome(kind: str, biome_short: str) -> tuple:
    """取某类（grass/foliage/water）在指定群系的 tint（MC 官方色表）。"""
    if kind == "water":
        return _BIOME_WATER_TINTS.get(biome_short, _BIOME_WATER_DEFAULT)
    if kind == "foliage":
        return _BIOME_FOLIAGE_TINTS.get(biome_short, _BIOME_FOLIAGE_DEFAULT)
    return _BIOME_TINTS.get(biome_short, _BIOME_TINT_DEFAULT)


def tinted_color(block_name: str, biome_short: str,
                 palette: dict) -> tuple:
    """返回方块在某群系下的最终颜色（灰度贴图 * tint）。

    树叶按官方 BlockColors 名单驱动：biome foliage 名单乘群系
    foliage tint，固定名单乘常量色，名单外（樱花/杜鹃/苍白橡木）
    贴图原色；其余方块灰度贴图按 grass/water/foliage 类 tint，
    彩色贴图直接返回调色板色。树叶等 foliage 统一压暗 0.8。
    """
    base = palette.get(block_name)
    if base is None:
        return None
    n = block_name.split(":")[-1]

    def _emit(col, darken):
        if darken and is_foliage(block_name):
            col = tuple(c * FOLIAGE_BRIGHTNESS for c in col)
        return tuple(int(min(255, max(0, round(c)))) for c in col)

    # 树叶：官方名单驱动（见 _LEAVES_* 注释），不依赖贴图灰度判定
    if n in _LEAVES_NO_TINT:
        return base
    if n in _LEAVES_FIXED_TINT:
        tr, tg, tb = _LEAVES_FIXED_TINT[n]
        g = float(base[1]) / 255.0
        return _emit((tr * g, tg * g, tb * g), True)
    if n in _LEAVES_BIOME_TINT:
        tr, tg, tb = tint_for_biome("foliage", biome_short)
        g = float(base[1]) / 255.0
        return _emit((tr * g, tg * g, tb * g), True)
    # 其余方块：是否 tint 由贴图实测决定——灰度图（R≈G≈B）才需要
    # 群系 tint；本身彩色的（如樱花叶 (229,173,194)）直接返回。
    _mx, _mn = max(base), min(base)
    is_gray = (_mx - _mn) <= 8
    if not is_gray:
        return base
    if n == "water":
        kind = "water"
    elif "leaves" in n:
        kind = "foliage"
    else:
        kind = "grass"
    tr, tg, tb = tint_for_biome(kind, biome_short)
    g = float(base[1]) / 255.0
    return _emit((tr * g, tg * g, tb * g), True)

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


# JourneyMap BaseRenderer 构造函数的精确偏移集合（反编译提取）：
#   primary   3 个：西北 1 格环
#   secondary 5 个：西北 2 格环
# 全部朝西北（负 x / 负 z）——对应固定西北光源，非双向对称。
PRIMARY_SLOPE_OFFSETS = ((0, -1), (-1, -1), (-1, 0))
SECONDARY_SLOPE_OFFSETS = ((-1, -2), (-2, -1), (-2, -2), (-2, 0), (0, -2))


def _calc_slope(h, offs, min_y):
    """复刻 calculateSlope：给定偏移集合，累加后取平均。"""
    hh, ww = h.shape
    min_y_f = float(min_y)
    depth = h - min_y_f
    acc = np.zeros((hh, ww), np.float32)
    for (dz, dx) in offs:
        ys = np.clip(np.arange(hh) + dz, 0, hh - 1)
        xs = np.clip(np.arange(ww) + dx, 0, ww - 1)
        off = h[np.ix_(ys, xs)]
        # 分支条件实为 `offH >= 0`（offH 是邻列**绝对**顶高，主世界几乎
        # 恒 >=0），而非"是否下坡"。故实际永远走 (currY+depth)/(offH+depth)
        # 一支：邻列更低 -> 比值>1（山脊提亮），邻列更高 -> <1（洼地压暗）。
        # 此前按 dh<0 分流用错了公式，导致坡度被压在 [0.61,1.54]。
        with np.errstate(divide="ignore", invalid="ignore"):
            term = np.where(off >= 0.0,
                            (h + depth) / (off + depth),
                            (off - depth) / (h - depth))
        acc += term.astype(np.float32)
    return acc / float(len(offs))


def _apply_mult(v, down_mul, up_mul):
    """对应 populateSlopes 的系数应用：<1 用下坡系数，>1 用上坡系数。"""
    return np.where(v < 1.0, v * down_mul,
                    np.where(v > 1.0, v * up_mul, v)).astype(np.float32)


def slope_from_heights(heights: np.ndarray, x0: int = 0, z0: int = 0,
                       min_y: int = -64, antialiasing: bool = True):
    """复刻 BaseRenderer.populateSlopes（两遍法，非 8 偏移平均）。

    反编译确认的真实流程：
      1) slope = calculateSlope(primarySlopeOffsets)   // 只 3 个主偏移
      2) slope<1 *= 0.65(primaryDown) ; slope>1 *= 1.2(primaryUp)
      3) 若开启 mapAntialiasing **且 slope 恰为 1.0**（完全平坦）：
           sec = calculateSlope(secondarySlopeOffsets)  // 5 个次偏移
           sec>slope *= 1.05 ; sec<slope *= 0.95
      4) NaN -> 1.0，最后 clamp 到 [shadingSlopeMin, shadingSlopeMax]
    此前把 8 个偏移一起平均是错的：secondary 只在完全平坦处启用。
    """
    h = heights.astype(np.float32)
    pri = _calc_slope(h, PRIMARY_SLOPE_OFFSETS, min_y)
    slope = _apply_mult(pri, SHADING_PRIMARY_DOWNSLOPE, SHADING_PRIMARY_UPSLOPE)
    if antialiasing:
        flat = np.isclose(pri, 1.0)
        if flat.any():
            sec = _calc_slope(h, SECONDARY_SLOPE_OFFSETS, min_y)
            up = sec > pri
            dn = sec < pri
            adj = np.where(up, slope * SHADING_SECONDARY_UPSLOPE,
                           np.where(dn, slope * SHADING_SECONDARY_DOWNSLOPE,
                                    slope))
            slope = np.where(flat, adj, slope)
    slope = np.where(np.isfinite(slope), slope, 1.0)
    return np.clip(slope, SHADING_SLOPE_MIN, SHADING_SLOPE_MAX).astype(np.float32)
