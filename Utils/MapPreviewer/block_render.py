# -*- coding: utf-8 -*-
"""MapPreviewer 逐方块精细渲染（native 加速）。

语义基准：density_sampler.py 的 fill + surface 链路（已与 26.2 官方 jar
对拍：fill 层 100%，surface 层 98.6%）。
性能：native fill 2ms/列 + surface 0.6ms/列（纯 Python ~400ms/列）。

配色复用主图同一套视觉语言（block_colors：水深渐变/草色温度湿度
tint/冰色/JourneyMap 式西北光源山体阴影），保证精细档与群系底图观感
一致。

对外:
    render_block_region(seed, cx, cz, width, height,
                        on_progress, cancel, want_surface, hillshade)
        -> dict {rgb, heights, top_block, origin_bx, origin_bz, engine,
                 elapsed, cancelled}
    is_available() -> bool    native 扩展是否可用
"""
from __future__ import annotations

import os

import numpy as np

from Utils.MapPreviewer import density_sampler as ds

try:
    from Utils.MapPreviewer._native import _density_sampler as _native
except Exception:
    _native = None

try:
    from Utils.MapPreviewer import native_density as _ndm
except Exception:
    _ndm = None

try:
    from Utils.MapPreviewer import native_surface as _nsurf
except Exception:
    _nsurf = None

try:
    from Utils.MapPreviewer import vegetation as _veg
except Exception:
    _veg = None

# 主图调色板 + 光源参数复用（同包私有，保证视觉一致）
from Utils.MapPreviewer.block_colors import (
    _GRASS_TL, _GRASS_TR, _GRASS_BL, _GRASS_BR,
    _WATER_SHALLOW, _WATER_DEEP, _ICE_RGB,
    _HS_AZ, _HS_ZEN,
)

_COLORS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "block_top_colors.json")

# 可产出方块顶面精确色（30 种全量，杜绝品红兜底）；
# 纹理平均色文件若存在会覆盖（更贴近真实材质），再叠加本表兜底。
_TOP_COLORS: dict[str, tuple[int, int, int]] = {
    "minecraft:stone": (140, 136, 128),
    "minecraft:cobblestone": (140, 134, 128),
    "minecraft:deepslate": (88, 86, 84),
    "minecraft:dirt": (142, 106, 76),
    "minecraft:coarse_dirt": (130, 96, 68),
    "minecraft:podzol": (98, 78, 42),
    "minecraft:mycelium": (112, 102, 104),
    "minecraft:farmland": (120, 85, 56),
    "minecraft:sand": (228, 214, 170),
    "minecraft:red_sand": (178, 106, 50),
    "minecraft:gravel": (138, 134, 128),
    "minecraft:clay": (162, 166, 172),
    "minecraft:sandstone": (224, 212, 170),
    "minecraft:red_sandstone": (176, 96, 46),
    "minecraft:mud": (66, 62, 46),
    "minecraft:terracotta": (144, 96, 64),
    "minecraft:white_terracotta": (214, 196, 180),
    "minecraft:light_gray_terracotta": (156, 136, 124),
    "minecraft:yellow_terracotta": (176, 140, 58),
    "minecraft:orange_terracotta": (170, 92, 44),
    "minecraft:red_terracotta": (146, 80, 58),
    "minecraft:brown_terracotta": (80, 58, 42),
    "minecraft:moss_block": (78, 100, 42),
    "minecraft:snow_block": (150, 158, 176),
    "minecraft:powder_snow": (158, 166, 184),
    "minecraft:ice": (140, 176, 232),
    "minecraft:packed_ice": (120, 160, 228),
    "minecraft:blue_ice": (98, 122, 168),
    "minecraft:obsidian": (21, 18, 30),
    "minecraft:granite": (149, 103, 85),
    "minecraft:diorite": (188, 188, 190),
    "minecraft:andesite": (136, 136, 137),
    "minecraft:tuff": (108, 109, 102),
    "minecraft:calcite": (223, 224, 220),
    "minecraft:smooth_stone": (158, 158, 158),
    "minecraft:bedrock": (85, 85, 85),
    "minecraft:sulfur": (198, 188, 66),
    "minecraft:cinnabar": (138, 62, 62),
    "minecraft:lava": (207, 91, 19),
    "minecraft:water": (63, 118, 228),
    "minecraft:air": (0, 0, 0),
}

# 需要群系草色 tint 的方块（顶面随温度/湿度变色的植被方块）
_GRASS_BLOCKS = {"minecraft:grass_block"}
# 冰/雪面（不参与水深渐变，直接固有色）
_ICE_BLOCKS = {"minecraft:ice", "minecraft:packed_ice", "minecraft:blue_ice"}
_SNOW_BLOCKS = {"minecraft:snow_block", "minecraft:powder_snow"}

_SEA = 63


_COLORS: dict[str, tuple[int, int, int]] | None = None


def _load_colors() -> dict[str, tuple[int, int, int]]:
    """顶面色表：手工精确色为底，纹理平均色文件覆盖（更贴近材质）。"""
    global _COLORS
    if _COLORS is not None:
        return _COLORS
    table = dict(_TOP_COLORS)
    try:
        import json
        with open(_COLORS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        for k, v in raw.items():
            if not k.startswith("minecraft:") or not isinstance(v, list) \
                    or len(v) < 3:
                continue
            r, g, b = int(v[0]), int(v[1]), int(v[2])
            # 仅采纳「可信」的纹理平均色：解码失败的黑块/近黑块丢弃，
            # 保留手工精确色（避免橙/黄/棕陶瓦等被覆盖成纯黑）。
            if max(r, g, b) < 24 or (r + g + b) < 72:
                continue
            table[k] = (r, g, b)
    except Exception:
        pass
    _COLORS = table
    return table


def is_available() -> bool:
    """native 扩展是否可用于精细渲染。"""
    return _native is not None and _ndm is not None and _nsurf is not None


_PACK_CACHE: dict[int, dict] = {}


def _get_pack(seed: int) -> dict:
    """构建并缓存 native 渲染包：密度 ctx + surface blob + 方块名表 + biome 采样器。"""
    pack = _PACK_CACHE.get(seed)
    if pack is not None:
        return pack

    import json
    from Utils.SeedReverser import biome_noise as bn
    from Utils.SeedReverser.biome_noise import BiomeSampler

    smp = ds.build_sampler(seed)
    id2key: dict[int, str] = {}
    for k, v in bn.BIOME_ID.items():
        id2key.setdefault(v, "minecraft:" + k)

    sblob, block_names, _, comp_noises = _nsurf.build_surface_blob(smp, id2key)
    snb = _nsurf.build_surface_noise_blob(comp_noises)

    comp = _ndm.Compiler(smp)
    ow = os.path.join(os.path.dirname(smp._df_dir), "noise_settings",
                      "overworld.json")
    with open(ow, encoding="utf-8") as f:
        router = json.load(f)["noise_router"]
    root = comp.compile(router["final_density"])
    rids = [comp.compile(router[k]) for k in
            ("barrier", "fluid_level_floodedness", "fluid_level_spread",
             "lava", "erosion", "depth", "preliminary_surface_level")]
    th = ds._seed_from_hash("minecraft:terrain")
    thu = (th[0] & ds._MASK64, th[1] & ds._MASK64)
    bnj = smp._load_df("minecraft:overworld/base_3d_noise")
    blend = tuple(float(bnj[x]) for x in
                  ("xz_scale", "y_scale", "xz_factor", "y_factor",
                   "smear_scale_multiplier"))
    dblob = comp.to_blob(root, rids, 63, blend, thu, snb)
    ctx = _native.build_from_blob(seed, dblob)

    try:
        from Utils.MapPreviewer import jm_colors as _jm
        _jmpal = _jm.build_block_palette(block_names)
    except Exception:
        _jmpal = None
    try:
        from Utils.MapPreviewer import block_textures as _btex
        # 地表方块 + 各树种叶片（树冠需要叶片材质）
        _need = list(block_names) + [
            "minecraft:%s_leaves" % sp for sp in
            ("oak", "birch", "spruce", "jungle", "acacia", "dark_oak",
             "mangrove", "cherry", "azalea", "flowering_azalea")
        ]
        _tex = _btex.load_atlas(_need)
    except Exception:
        _tex = {}
    pack = {
        "ctx": ctx, "sblob": sblob,
        "block_names": block_names,
        "tex": _tex,
        "jm_palette": _jmpal,
        "name2bid": {nm: i for i, nm in enumerate(block_names)},
        "id2key": id2key,
        "bs": BiomeSampler(seed, "26.2"),
    }
    _PACK_CACHE.clear()          # 只缓存一个 seed（切 seed 重建）
    _PACK_CACHE[seed] = pack
    return pack


# 精细档 hillshade：高度量化台阶（分层）。参考真实地图的阴影是"每层分明"的
# 台阶状——同一层高度平面内亮度一致，层与层之间突然跳变（实测参考图山地
# |ΔL|<1 占 88%、|ΔL|>12 占 12%）。故先量化高度再算坡向，得到分明的层。
_FHS_ZSCALE = 1.0
_FHS_STEP = 1      # 高度量化步长（方块）：1 = 逐方块一层（MC 地形天然台阶）
_FHS_LEVELS = 7    # shade 分级数：参考图山地约 7 个亮度级
_FHS_SHADE_MIN = 0.42   # 阴影下限：防背光陡坡乘深色方块后变纯黑

# 树冠球面光照用的光源方向（西北 315°、高度角 40°，与地形 hillshade 同源）
_HS_LIGHT_X = float(np.sin(_HS_AZ) * np.cos(_HS_ZEN))
_HS_LIGHT_Y = float(-np.cos(_HS_AZ) * np.cos(_HS_ZEN))
_HS_LIGHT_Z = float(np.sin(_HS_ZEN))


def _hillshade(heights: np.ndarray, water_mask: np.ndarray) -> np.ndarray:
    """按 JourneyMap 的光照模型给出亮度系数（同层同色，不破碎）。

    JourneyMap 的亮度来自 方块真实 lightLevel/15（BaseRenderer.setStratumColors）。
    我方可用的近似：地表及以上 = 全亮 15，水面下按深度衰减。
    结果只与"该列顶是否在水下/多深"有关 -> 同层仍同色。
    """
    depth = np.maximum(0, _SEA - heights.astype(np.float32))
    lvl = np.clip(15.0 - depth, 1.0, 15.0)
    # 对应 day_b = light/15 + tweakBrightenDaylightDiff
    shade = (lvl / 15.0 + 0.06).astype(np.float32)
    shade = np.clip(shade, _FHS_SHADE_MIN, 1.30)
    shade[water_mask] = 1.0
    return shade



def _grain(seed: int, x0: int, z0: int, h: int, w: int) -> np.ndarray:
    """逐方块色彩变异：高频亮度纹理 + 低频成片色相/饱和漂移。

    参考实测密林：色相 std=0.163、饱和度 std=0.144、色相直方跨 4 桶
    （黄绿/正绿/蓝绿并存）。若只做高频亮度抖动，色相仍是单一绿。
    故分两层：高频 hash 给逐方块亮度纹理，低频平滑噪声给成片色相漂移。
    返回 (h,w,3) RGB 乘子。
    """
    rr = np.arange(h, dtype=np.int64)[:, None] + z0
    cc = np.arange(w, dtype=np.int64)[None, :] + x0
    base = (cc * 73856093) ^ (rr * 19349663) ^ (int(seed) * 83492791)

    def _u(salt):
        hv = base ^ (salt * 2654435761)
        hv2 = (hv ^ (hv >> 13)) * 1274126177
        return (((hv2 ^ (hv2 >> 16)) & 0xFFFF).astype(np.float32) / 65535.0)

    lum = 0.89 + 0.22 * _u(1)

    GS = 8
    gh = max(2, h // GS + 2)
    gw = max(2, w // GS + 2)
    gr = (np.arange(gh, dtype=np.int64)[:, None] + (z0 // GS))
    gc = (np.arange(gw, dtype=np.int64)[None, :] + (x0 // GS))
    gbase = (gc * 374761393) ^ (gr * 668265263) ^ (int(seed) * 1274126177)

    def _g(salt):
        hv = gbase ^ (salt * 2654435761)
        hv2 = (hv ^ (hv >> 13)) * 1274126177
        return (((hv2 ^ (hv2 >> 16)) & 0xFFFF).astype(np.float32) / 65535.0)

    def _bilinear(g):
        zz = (np.arange(h, dtype=np.float32) / GS)
        xx = (np.arange(w, dtype=np.float32) / GS)
        z0i = zz.astype(np.int32)
        x0i = xx.astype(np.int32)
        fz = (zz - z0i)[:, None]
        fx = (xx - x0i)[None, :]
        z1i = np.minimum(z0i + 1, gh - 1)
        x1i = np.minimum(x0i + 1, gw - 1)
        z0i = np.minimum(z0i, gh - 1)
        x0i = np.minimum(x0i, gw - 1)
        a = g[z0i][:, x0i]
        b = g[z0i][:, x1i]
        c = g[z1i][:, x0i]
        d = g[z1i][:, x1i]
        top = a * (1 - fx) + b * fx
        bot = c * (1 - fx) + d * fx
        return top * (1 - fz) + bot * fz

    warm = _bilinear(_g(2)) - 0.5
    satv = _bilinear(_g(3)) - 0.5

    mul = np.empty((h, w, 3), np.float32)
    mul[..., 0] = lum * (1.0 + 0.58 * warm) * (1.0 + 0.30 * satv)
    mul[..., 1] = lum
    mul[..., 2] = lum * (1.0 - 0.52 * warm) * (1.0 + 0.30 * satv)
    return mul



def render_block_region(seed: int, cx_blocks: int, cz_blocks: int,
                        width_blocks: int, height_blocks: int,
                        on_progress=None, cancel=None,
                        want_surface: bool = True,
                        hillshade: bool = False,
                        structures: bool = True,
                        scale: int = 1) -> dict:
    """渲染精细俯视图（以 (cx,cz) 为中心）。scale=N 表示每方块 N×N 像素，
    N>1 时可见方块材质纹理（对应参考截图的 1方块=4像素）。"""
    w = max(16, (int(width_blocks) // 16) * 16)
    h = max(16, (int(height_blocks) // 16) * 16)
    x0 = ((int(cx_blocks) - w // 2) // 16) * 16
    z0 = ((int(cz_blocks) - h // 2) // 16) * 16
    return _render_rect(seed, x0, z0, w, h, want_surface, hillshade,
                        structures, on_progress, cancel, margin=0,
                        scale=scale)


def render_tile(seed: int, fx: int, fz: int, ts: int,
                want_surface: bool = True, hillshade: bool = False,
                structures: bool = True, margin: int = 4,
                scale: int = 1) -> dict:
    """渲染一个对齐世界网格的精细瓦片：瓦片格 (fx,fz) 覆盖方块
    [fx*ts,(fx+1)*ts)×[fz*ts,(fz+1)*ts)。供视口逐块渐进渲染复用。

    margin：向外多渲染再裁回的边距（方块）。树冠半径最大 3，取 4 覆盖；
    相邻瓦片各自铺满同一棵全局确定性树冠再裁互补半 → 接缝不再切断树木。"""
    x0 = fx * ts
    z0 = fz * ts
    return _render_rect(seed, x0, z0, ts, ts, want_surface, hillshade,
                        structures, None, None, margin=margin, scale=scale)


def _render_rect(seed: int, x0: int, z0: int, w: int, h: int,
                 want_surface: bool, hillshade: bool, structures: bool,
                 on_progress=None, cancel=None, margin: int = 0,
                 scale: int = 1) -> dict:
    """核心：渲染方块矩形 [x0,x0+w)×[z0,z0+h)。margin>0 时向外多渲染再裁回，
    消除跨瓦片的树冠/结构接缝。"""
    import time
    t0 = time.perf_counter()

    # 目标瓦片（裁回范围）
    tw, th = w, h
    tx0, tz0 = x0, z0
    if margin > 0:
        x0 -= margin; z0 -= margin
        w += 2 * margin; h += 2 * margin

    def _crop(arr):
        if margin <= 0 or arr is None:
            return arr
        return arr[margin:margin + th, margin:margin + tw]

    pack = _get_pack(seed)
    ctx = pack["ctx"]

    # ---- 1) native fill 层：每列最高实心 y ----
    heights = np.zeros((h, w), dtype=np.int16)
    CHUNK_ROWS = 64
    for r0 in range(0, h, CHUNK_ROWS):
        if cancel is not None and cancel():
            return {"rgb": np.zeros((0, 0, 3), dtype=np.uint8),
                    "heights": heights, "top_block": None,
                    "origin_bx": x0, "origin_bz": z0, "engine": "native",
                    "elapsed": time.perf_counter() - t0, "cancelled": True}
        r1 = min(r0 + CHUNK_ROWS, h)
        heights[r0:r1, :] = _native.fill_top_grid(
            ctx, x0, z0 + r0, w, r1 - r0, -64, 320, 0)
        if on_progress is not None:
            on_progress(r1, h, "fill")

    if not want_surface:
        rgb = _colorize_height(heights, hillshade)
        return {"rgb": _crop(rgb), "heights": _crop(heights),
                "top_block": None,
                "origin_bx": tx0, "origin_bz": tz0, "engine": "native",
                "elapsed": time.perf_counter() - t0, "cancelled": False}

    # ---- 2) biome 网格（列顶处，4x4 量化后广播）----
    bs = pack["bs"]
    qh, qw = (h + 3) // 4, (w + 3) // 4
    qbid = np.zeros((qh, qw), dtype=np.int32)
    qt = np.zeros((qh, qw), dtype=np.float32)
    qh2 = np.zeros((qh, qw), dtype=np.float32)
    for qr in range(qh):
        z = z0 + qr * 4
        for qc in range(qw):
            x = x0 + qc * 4
            top = int(heights[min(qr * 4, h - 1), min(qc * 4, w - 1)])
            ny = max(-64, min(319, top)) >> 2
            cp = bs.climate_point_xz(x >> 2, z >> 2, ny)
            qbid[qr, qc] = bs.biome_at(x >> 2, ny, z >> 2)
            qt[qr, qc] = cp[0]
            qh2[qr, qc] = cp[1]
    biome_grid = np.repeat(np.repeat(qbid, 4, axis=0), 4, axis=1)[:h, :w]
    tq = np.repeat(np.repeat(qt, 4, axis=0), 4, axis=1)[:h, :w]
    hq = np.repeat(np.repeat(qh2, 4, axis=0), 4, axis=1)[:h, :w]

    # ---- 3) native surface：顶块 id + 最终顶 y ----
    tops, blocks = _native.surface_grid(ctx, pack["sblob"], heights,
                                        biome_grid, x0, z0, 63, 0)
    heights = tops
    if on_progress is not None:
        on_progress(h, h, "surface")

    # ---- 4) 配色（向量化）----
    rgb = _colorize_blocks(blocks, heights, tq, hq, biome_grid, pack, x0, z0)

    # ---- 4b) 植被散布（树冠/花/草/作物，密度精确近似）----
    if _veg is not None and want_surface:
        _apply_vegetation(rgb, heights, blocks, biome_grid, pack, seed, x0, z0)

    # ---- 4c) 结构 footprint（逐方块近似，覆盖植被）----
    if structures and want_surface:
        _apply_structures(rgb, heights, x0, z0, h, w, seed, "26.2")

    # ---- 5) 影调 → 颗粒 → 山体阴影（分级）----
    # 顺序很重要：影调和颗粒必须在乘法式阴影之前完成，否则会把已量化的
    # shade 层级重新打散，失去"每层分明"的平台感。
    rgb = rgb.astype(np.float32)
    if hillshade:
        # 影调：参考实测方块亮度范围 32~207、色阶 158 级，说明亮部要拉高、
        # 色阶要丰富。仅做轻微 γ 与高光软膝（膝点上移到 0.86，不再压扁）。
        t = np.clip(rgb, 0.0, 255.0) / 255.0
        t = np.power(t, 0.94)
        knee = 0.86
        hi = t > knee
        t = np.where(hi, knee + (0.97 - knee)
                     * (1.0 - np.exp(-(t - knee) / (0.97 - knee))), t)
        rgb = t * 255.0
    # 方块材质纹理：±11%（参考实测每方块内亮度极差约 23），
    # 同块内一致 -> 保持方块分明，同时产生 MC 材质的色阶多样性。
    # 地表完全不做色彩抖动：同一地形层必须同色，否则画面破碎。
    # 色相/亮度变异只保留在树冠（_apply_vegetation 的球面光照 + 树种混生）。
    if hillshade:
        # JourneyMap 斜坡阴影：按邻列高度差算坡度因子，再对 RGB 做
        # bevel（R/G 额外 *0.85、B 只乘 slope）-> 斜坡变暗且偏蓝。
        # 坡度纯由地形决定，同坡同色，不随机。
        from Utils.MapPreviewer import jm_colors as _jm
        slope = _jm.slope_from_heights(heights, x0, z0)
        water_mask = heights < _SEA
        slope = np.where(water_mask, 1.0, slope).astype(np.float32)
        rb = slope < 1.0
        f = np.where(rb, _jm.BEVEL_DARKEN, 1.0).astype(np.float32)
        rgb = rgb.astype(np.float32)
        rgb[..., 0] *= f * slope
        rgb[..., 1] *= f * slope
        rgb[..., 2] *= slope
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)

    block_names = pack["block_names"]
    top_block = np.asarray(block_names, dtype=object)[
        np.clip(blocks, 0, len(block_names) - 1)]

    rgb = _crop(rgb)
    heights = _crop(heights)
    top_block = _crop(top_block)

    # scale>1：每方块展开成 N×N 像素，并在块内按材质贴图取不同位置，
    # 从而呈现参考图那种"1方块=4像素、块内有花纹"的观感。
    if scale > 1:
        rgb = _upscale_blocks(rgb, _crop(blocks), pack, scale)
        heights = np.repeat(np.repeat(heights, scale, axis=0), scale, axis=1)
        top_block = np.repeat(np.repeat(top_block, scale, axis=0),
                              scale, axis=1)

    return {"rgb": rgb, "heights": heights,
            "top_block": top_block,
            "origin_bx": tx0, "origin_bz": tz0, "engine": "native",
            "elapsed": time.perf_counter() - t0, "cancelled": False}


# 群系 -> 草色（量化取色，保证同群系同色；避免逐点温湿度渐变造成破碎）
_BIOME_GRASS = {
    "plains": (110, 146, 78), "sunflower_plains": (110, 146, 78),
    "meadow": (116, 150, 82), "forest": (96, 134, 70),
    "flower_forest": (104, 140, 74), "birch_forest": (108, 144, 76),
    "old_growth_birch_forest": (108, 144, 76),
    "dark_forest": (82, 120, 60), "taiga": (88, 122, 70),
    "old_growth_pine_taiga": (86, 120, 68),
    "old_growth_spruce_taiga": (84, 118, 66),
    "snowy_taiga": (96, 128, 84), "jungle": (66, 138, 52),
    "sparse_jungle": (86, 138, 62), "bamboo_jungle": (74, 136, 56),
    "savanna": (140, 136, 74), "savanna_plateau": (140, 136, 74),
    "windswept_savanna": (138, 134, 72),
    "swamp": (68, 82, 48), "mangrove_swamp": (68, 82, 48),
    "grove": (104, 132, 88), "snowy_plains": (118, 138, 106),
    "windswept_hills": (104, 138, 76), "windswept_forest": (100, 134, 72),
    "windswept_gravelly_hills": (104, 138, 76),
    "jagged_peaks": (110, 132, 96), "frozen_peaks": (116, 136, 104),
    "snowy_slopes": (112, 134, 98), "ice_spikes": (118, 138, 106),
    "stony_peaks": (108, 134, 92), "badlands": (128, 132, 66),
    "eroded_badlands": (128, 132, 66), "wooded_badlands": (124, 130, 66),
}
_BIOME_GRASS_DEFAULT = (108, 142, 76)


def _grass_tint_by_biome(biome_grid: np.ndarray, pack: dict) -> np.ndarray:
    """按群系给出草色（同群系同色，不随温湿度逐点渐变）。"""
    h, w = biome_grid.shape
    out = np.empty((h, w, 3), np.float32)
    id2key = pack["id2key"]
    cache: dict[int, tuple] = {}
    for r in range(h):
        for c in range(w):
            bid = int(biome_grid[r, c])
            col = cache.get(bid)
            if col is None:
                k = id2key.get(bid, "")
                col = _BIOME_GRASS.get(k.split(":")[-1], _BIOME_GRASS_DEFAULT)
                cache[bid] = col
            out[r, c] = col
    return out


def _grass_tint(tq: np.ndarray, hq: np.ndarray) -> np.ndarray:
    """温度/湿度量化值（*10000）-> (H,W,3) 草色 float32（同主图公式）。"""
    t = np.clip(tq / 10000.0 * 0.5 + 0.5, 0.0, 1.0).astype(np.float32)
    h = np.clip(hq / 10000.0 * 0.5 + 0.5, 0.0, 1.0).astype(np.float32)
    top = _GRASS_TL * (1 - h[..., None]) + _GRASS_TR * h[..., None]
    bot = _GRASS_BL * (1 - h[..., None]) + _GRASS_BR * h[..., None]
    return top * (1 - t[..., None]) + bot * t[..., None]


def _upscale_blocks(rgb: np.ndarray, blocks: np.ndarray, pack: dict,
                    scale: int) -> np.ndarray:
    """把 1px/方块 结果展开成 scale×scale，块内按材质贴图加纹理花纹。

    rgb: (h,w,3) 每方块一色（已含 tint/阴影）
    blocks: (h,w) 方块 id
    返回 (h*scale, w*scale, 3) uint8
    """
    h, w = blocks.shape
    names = pack["block_names"]
    tex = pack.get("tex") or {}
    # 块内采样索引（把 16x16 纹理按 scale 均匀取点）
    ii = ((np.arange(scale) * 16) // scale).astype(np.int32)
    ii = np.clip(ii, 0, 15)

    # 预取每个 id 的贴图与其均值
    art_by_id = {}
    for bi, bname in enumerate(names):
        art = tex.get(bname)
        if art is None:
            continue
        am = art.reshape(-1, 3).mean(axis=0)
        am = np.where(am < 1e-3, 1.0, am)
        art_by_id[bi] = (art, am.astype(np.float32))

    out = np.empty((h * scale, w * scale, 3), np.float32)
    base = rgb.astype(np.float32)
    for r in range(h):
        for c in range(w):
            bi = int(blocks[r, c])
            blk = base[r, c]                      # (3)
            ao = art_by_id.get(bi)
            if ao is None:
                out[r*scale:(r+1)*scale, c*scale:(c+1)*scale] = blk
                continue
            art, am = ao
            # 该方块内 scale×scale 的纹理采样（含世界坐标相位，跨块连续）
            sx = (ii + (c * 16 // max(scale, 1))) & 15
            sy = (ii + (r * 16 // max(scale, 1))) & 15
            sub = art[np.ix_(sy, sx)].astype(np.float32)   # (scale,scale,3)
            out[r*scale:(r+1)*scale, c*scale:(c+1)*scale] = sub * (blk / am)
    return np.clip(out, 0, 255).astype(np.uint8)


def _colorize_blocks(blocks: np.ndarray, heights: np.ndarray,
                     tq: np.ndarray, hq: np.ndarray,
                     biome_grid: np.ndarray, pack: dict,
                     x0: int = 0, z0: int = 0) -> np.ndarray:
    h, w = blocks.shape
    # 配色改走 JourneyMap 方案：每方块一个固定色（贴图均值 * 群系 tint），
    # 颜色只是"方块类型+群系"的函数，与坐标无关 -> 同层必然同色。
    colors = pack.get("jm_palette") or _load_colors()
    block_names = pack["block_names"]
    # 方块名 -> RGB 查找表（按 surface blob 顺序）
    lut = np.array([colors.get(nm, (255, 0, 255)) for nm in block_names],
                   dtype=np.float32)                    # (nb,3)
    idx = np.clip(blocks, 0, len(block_names) - 1)
    rgb = lut[idx]                                       # (h,w,3)

    name_arr = np.asarray(block_names, dtype=object)
    nm = name_arr[idx]

    # 草色 tint：按群系量化取色（同群系同色），不做逐点温湿度渐变。
    # 逐点 tint 会让同一高度层出现上百种绿，画面破碎（实测同层 143 色）。
    gmask = np.isin(nm, list(_GRASS_BLOCKS))
    if gmask.any():
        _gt = _grass_tint_by_biome(biome_grid, pack)
        rgb[gmask] = _gt[gmask]

    # 寒冷群系覆雪：MC 的雪由 biome 的 freeze_top_layer feature 实现，
    # 顶块仍是 grass_block 但上面覆雪层。故按群系给草地覆雪
    # （参考截图雪原是冷蓝白而非绿色）。
    if gmask.any():
        cold = np.zeros((h, w), bool)
        for r in range(0, h, 4):
            for c in range(0, w, 4):
                k = pack["id2key"].get(int(biome_grid[r, c]), "")
                if k.split(":")[-1] in _SNOWY_BIOMES:
                    cold[r:r + 4, c:c + 4] = True
        sc = gmask & cold
        if sc.any():
            rgb[sc] = colors.get("minecraft:snow_block", (150, 158, 176))

    # 沼泽/红树林草地：参考实测暗黄绿 (64,74,44)，比通用草 tint 更暗偏黄
    if gmask.any():
        sw = np.zeros((h, w), bool)
        for r in range(0, h, 4):
            for c in range(0, w, 4):
                k = pack["id2key"].get(int(biome_grid[r, c]), "")
                if k.split(":")[-1] in ("swamp", "mangrove_swamp"):
                    sw[r:r + 4, c:c + 4] = True
        swm = gmask & sw
        if swm.any():
            rgb[swm] = (68, 82, 48)

    # 冰/雪：走色表固有色（参考截图为冷蓝灰，非亮白），不受水深/草色影响
    for bset, dflt in ((_ICE_BLOCKS, (126, 146, 186)),
                       (_SNOW_BLOCKS, (176, 184, 200))):
        m = np.isin(nm, list(bset))
        if m.any():
            for bname in bset:
                mm = (nm == bname)
                if mm.any():
                    rgb[mm] = colors.get(bname, dflt)

    # 水面：**必须是水/冰方块**才算水，不能只看高度——
    # 低洼的陆地（dirt/gravel/沙）顶块不是水，误判会把陆地涂成蓝色。
    _WATER_BLOCKS = {"minecraft:water", "minecraft:ice",
                     "minecraft:packed_ice", "minecraft:blue_ice",
                     "minecraft:frosted_ice"}
    is_water_blk = np.isin(nm, list(_WATER_BLOCKS))
    ice_or_snow = np.isin(nm, list(_ICE_BLOCKS | _SNOW_BLOCKS))
    water_mask = (heights < _SEA) & is_water_blk & ~ice_or_snow
    if water_mask.any():
        u = np.clip((_SEA - heights) / 45.0, 0.0, 1.0).astype(np.float32)
        wr = _WATER_SHALLOW * (1 - u[..., None]) + _WATER_DEEP * u[..., None]
        rgb[water_mask] = wr[water_mask]

    # 地表不做贴图逐像素采样：贴图会让同一高度层出现上百种颜色（破碎）。
    # 地形配色 = 方块固有色（+ 群系草色），整层统一；材质细节只保留给树冠。
    return rgb



# 可生长植被的地表（水/冰/裸岩上不放）
# 顶块被雪覆盖的寒冷群系（freeze_top_layer 生效）
_SNOWY_BIOMES = {
    "snowy_plains", "snowy_taiga", "snowy_beach", "snowy_slopes",
    "ice_spikes", "frozen_peaks", "jagged_peaks", "grove",
    "frozen_river", "frozen_ocean", "deep_frozen_ocean",
}

# 几乎不长植被的极寒/裸岩群系
_NO_VEG_BIOMES = {
    "ice_spikes", "frozen_peaks", "jagged_peaks", "snowy_slopes",
    "stony_peaks", "stony_shore", "badlands", "eroded_badlands",
    "wooded_badlands", "desert",
}

_GROWABLE = {
    "minecraft:grass_block", "minecraft:dirt", "minecraft:coarse_dirt",
    "minecraft:podzol", "minecraft:mycelium", "minecraft:moss_block",
    "minecraft:snow_block", "minecraft:sand", "minecraft:terracotta",
    "minecraft:mud",
}


def _hash01_grid(seed: int, x0: int, z0: int, h: int, w: int, salt: int):
    rr = (np.arange(h, dtype=np.int64)[:, None] + z0).astype(np.uint64)
    cc = (np.arange(w, dtype=np.int64)[None, :] + x0).astype(np.uint64)
    U = np.uint64
    M = (1 << 64) - 1
    # seed/salt 项用 Python int 先算并掩码，避免 numpy 标量乘溢出告警
    sbase = ((int(seed) & M) * 0x165667B19E3779F9 ^ (salt * 0x27D4EB2F165667C5)) & M
    hv = (cc * U(0x9E3779B97F4A7C15) ^ rr * U(0xC2B2AE3D27D4EB4F) ^ U(sbase))
    hv ^= hv >> U(33)
    hv *= U(0xFF51AFD7ED558CCD)
    hv ^= hv >> U(29)
    hv *= U(0xC4CEB9FE1A85EC53)
    hv ^= hv >> U(32)
    return (hv.astype(np.float64) / float(1 << 64)).astype(np.float32)


def _apply_vegetation(rgb, heights, blocks, biome_grid, pack, seed, x0, z0):
    """按 biome 密度做确定性植被叠加（就地改 rgb float32）。

    树：trunk 概率=tree_p，命中处按树种半径铺冠层（深色覆盖）；
    花/作物：单块色点；草：微弱绿调。优先级 冠层>作物>花>草>地表。
    """
    h, w = rgb.shape[:2]
    names = pack["block_names"]
    idx = np.clip(blocks, 0, len(names) - 1)
    top_name = np.asarray(names, dtype=object)[idx]
    # 植被只长在陆地（顶面 y >= 海平面）且可生长地表上；排除水下沙/砾。
    # 极寒群系（雪原/冰刺）地面覆雪，不长植被（参考截图冰刺几乎无植被）。
    growable = np.isin(top_name, list(_GROWABLE)) & (heights >= _SEA)
    if growable.any():
        cold = np.zeros((h, w), bool)
        for r in range(0, h, 4):
            for c in range(0, w, 4):
                k = pack["id2key"].get(int(biome_grid[r, c]), "")
                if k.split(":")[-1] in _NO_VEG_BIOMES:
                    cold[r:r + 4, c:c + 4] = True
        growable &= ~cold

    id2key = pack["id2key"]
    tree_p = np.zeros((h, w), np.float32)
    flower_p = np.zeros((h, w), np.float32)
    grass_p = np.zeros((h, w), np.float32)
    crop_p = np.zeros((h, w), np.float32)
    radius = np.zeros((h, w), np.int8)
    canopy_col = np.zeros((h, w, 3), np.float32)
    crop_kind = np.empty((h, w), dtype=object)
    crop_kind[:] = ""
    prof_cache: dict[int, dict] = {}
    for r in range(h):
        for c in range(w):
            bid = int(biome_grid[r, c])
            pr = prof_cache.get(bid)
            if pr is None:
                pr = _veg.biome_vegetation(id2key.get(bid, "minecraft:plains"))
                prof_cache[bid] = pr
            tree_p[r, c] = pr["tree"]; flower_p[r, c] = pr["flower"]
            grass_p[r, c] = pr["grass"]; crop_p[r, c] = pr["crop"]
            rad, col = _veg.species_canopy(pr["species"])
            radius[r, c] = rad; canopy_col[r, c] = col
            crop_kind[r, c] = pr["crop_kind"]

    # 真实树摆放：按 MC per-chunk feature 放置算法（population seed +
    # in_square 偏移），替代原来的逐像素概率散布。
    from Utils.MapPreviewer import tree_placement as _tp
    trees = _tp.place_trees_in_rect(seed, x0, z0, w, h, heights,
                                    biome_grid, pack["id2key"])
    canopy = np.zeros((h, w), bool)
    fol = _hash01_grid(seed, x0, z0, h, w, 7)      # 叶面亮度噪声
    tvar = _hash01_grid(seed, x0, z0, h, w, 8)     # 逐棵树明暗
    # 叶片材质（按树种取对应 leaves 贴图）
    _tex = pack.get("tex") or {}
    leaf_art = None
    leaf_mean = 1.0
    for (_tx, _tz, _sp, _r, _c, _y) in trees[:1]:
        _ln = "minecraft:%s_leaves" % _sp
        leaf_art = _tex.get(_ln)
        if leaf_art is None:
            leaf_art = _tex.get("minecraft:oak_leaves")
        if leaf_art is not None:
            leaf_mean = max(float(leaf_art.mean()), 1.0)
        break

    for (tx, tz, sp, rad, col, top_y) in trees:
        # JourneyMap 的树冠是**每方块单色**（取叶片贴图均值 * 群系 tint），
        # 不做球面光照渐变。立体感由地形坡度(bevelSlope)提供，树冠保持纯色。
        # 之前加的球面梯度会让相邻像素 |dL| p50 高达 11.6，而参考图仅 0.6。
        base = np.asarray(col, np.float32)
        lum_t = np.float32(0.90 + 0.20 * tvar[tz, tx])
        ccol = base * lum_t
        lim = rad * rad + rad
        for dy in range(-rad, rad + 1):
            yy = tz + dy
            if yy < 0 or yy >= h:
                continue
            for dx in range(-rad, rad + 1):
                xx = tx + dx
                if xx < 0 or xx >= w:
                    continue
                r2 = dx * dx + dy * dy
                if r2 > lim:
                    continue
                if not growable[yy, xx]:
                    continue
                canopy[yy, xx] = True
                rgb[yy, xx] = ccol

# ---- 结构 footprint 近似（逐方块；占地尺寸/材质为代表性近似）----
# key: (宽, 长, 主体色, 边框/屋顶色)；村庄单独按房屋簇渲染。
_FOOTPRINTS = {
    "pillager_outpost": (9, 9, (70, 52, 34), (110, 110, 112)),
    "mansion":          (22, 28, (58, 42, 30), (40, 30, 24)),
    "monument":         (20, 26, (44, 86, 80), (30, 60, 58)),
    "desert_pyramid":   (20, 20, (222, 208, 158), (196, 178, 120)),
    "jungle_temple":    (12, 12, (96, 104, 84), (70, 78, 62)),
    "swamp_hut":        (9, 9, (58, 48, 38), (44, 36, 28)),
    "igloo":            (8, 8, (238, 246, 248), (200, 210, 220)),
    "shipwreck":        (10, 4, (122, 92, 52), (90, 66, 38)),
    "ocean_ruin":       (5, 5, (120, 122, 120), (96, 98, 96)),
    "ruined_portal":    (7, 11, (30, 24, 40), (120, 60, 160)),
    "desert_well":      (3, 3, (210, 196, 150), (170, 156, 110)),
}
# 村庄房屋主体色随生物群系变体
_VILLAGE_HOUSE = {
    "plains": (188, 180, 168), "desert": (222, 208, 158), "taiga": (96, 78, 58),
    "savanna": (176, 140, 86), "snowy": (70, 60, 52), "temperate": (150, 118, 78),
}
_VILLAGE_ROAD = (120, 108, 92)


# 水上结构（其余按陆地结构处理）
_WATER_STRUCTURES = {"monument", "ocean_ruin", "shipwreck", "buried_treasure"}


def _stamp_rect(rgb, heights, cx, cy, w, l, fill, border, h, wd, land=True):
    x0 = cx - w // 2; z0 = cy - l // 2
    for zz in range(z0, z0 + l):
        if zz < 0 or zz >= h:
            continue
        for xx in range(x0, x0 + w):
            if xx < 0 or xx >= wd:
                continue
            is_land = heights[zz, xx] >= _SEA
            if is_land != land:
                continue
            edge = (xx == x0 or xx == x0 + w - 1 or zz == z0 or zz == z0 + l - 1)
            rgb[zz, xx] = border if edge else fill


def _apply_structures(rgb, heights, x0, z0, h, w, seed, version):
    """枚举区域结构并按 footprint 近似逐方块 stamp（覆盖地表/植被）。"""
    try:
        from Utils.Public import structure_map as smap
    except Exception:
        return
    keys = list(_FOOTPRINTS.keys()) + ["village"]
    try:
        structs = smap.enumerate_structures(
            seed, version, (x0, z0, x0 + w - 1, z0 + h - 1), struct_keys=keys)
    except Exception:
        return
    for st in structs:
        key = st.get("struct")
        ax = int(st.get("x", 0)) - x0
        az = int(st.get("z", 0)) - z0
        land = key not in _WATER_STRUCTURES
        if key == "village":
            _stamp_village(rgb, heights, ax, az, h, w, seed,
                          int(st.get("x", 0)), int(st.get("z", 0)))
        elif key in _FOOTPRINTS:
            wl, ll, fill, border = _FOOTPRINTS[key]
            _stamp_rect(rgb, heights, ax, az, wl, ll, fill, border, h, w, land)


def _stamp_village(rgb, heights, ax, az, h, w, seed, wx, wz, colors=None):
    """用真实 jigsaw 还原的村庄方块替换矩形近似。

    读 jar 内村庄模板 NBT（town_centers/houses/streets/decor），按权重
    拼出整座村庄，取每列最高实体方块的颜色落到图上 —— 房屋外形、门窗、
    草径(dirt_path)、农田、水井都是模板里的真实布局。
    """
    try:
        from Utils.MapPreviewer import village_jigsaw as _vj
        from Utils.MapPreviewer import jm_colors as _jm
    except Exception:
        return
    try:
        from Utils.MapPreviewer import village_jigsaw_exact as _vx
        # 地形适配：MC 用 project_start_to_heightmap=WORLD_SURFACE_WG 把
        # 村庄贴到锚点处地表，故 base_y 取该列实测地表高度。
        # 若地表低于海平面（村庄在水边），抬到海平面以上 1 格，
        # 对应 terrain_adaptation=beard_thin 的填平效果。
        _by = int(heights[az, ax]) if (0 <= az < h and 0 <= ax < w) else 64
        _by = max(_by, _SEA + 1)
        fp = _vx.build_village(seed, wx, wz, base_y=_by)
    except Exception:
        try:
            fp = _vj.village_footprint(seed, wx, wz)
        except Exception:
            return
    if not fp["blocks"]:
        return
    grid = _vj.footprint_to_grid(fp, wx - ax, wz - az, w, h)
    names = set()
    for row in grid:
        for nm in row:
            if nm:
                names.add(nm)
    if not names:
        return
    pal = _jm.build_block_palette(sorted(names))
    # 村庄整体占地（含房屋之间的空地）：用方块聚集的包围盒 + 逐列膨胀，
    # 对应 MC terrain_adaptation=beard_thin 把村庄底座铺平的效果。
    covered = grid != None
    pad = np.zeros_like(covered)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            ys = np.clip(np.arange(h) + dy, 0, h - 1)
            xs = np.clip(np.arange(w) + dx, 0, w - 1)
            pad |= covered[np.ix_(ys, xs)]
    ground = pal.get("minecraft:dirt_path") or pal.get("minecraft:dirt") \
        or (139, 112, 76)
    for r in range(h):
        for c in range(w):
            nm = grid[r, c]
            if nm:
                col = pal.get(nm)
                if col is not None:
                    rgb[r, c] = col
                    if heights[r, c] < _SEA:
                        heights[r, c] = _SEA
            elif pad[r, c] and heights[r, c] < _SEA:
                # 房屋之间/边缘的洼地：铺村庄地面色，避免露出水面
                rgb[r, c] = ground
                heights[r, c] = _SEA
def _colorize_height(heights: np.ndarray, hillshade: bool = False) -> np.ndarray:
    """纯海拔快速档：水蓝、陆地按高度渐绿灰，可选阴影。"""
    h, w = heights.shape
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    land = heights > _SEA
    depth = np.clip(_SEA - heights, 0, 40).astype(np.float32)
    f = np.clip(1.0 - depth / 45.0, 0.30, 1.0)
    rgb[..., 0] = 40 * f
    rgb[..., 1] = 70 * f + 20
    rgb[..., 2] = 170 * (0.55 + 0.45 * f)
    t = np.clip((heights.astype(np.float32) - _SEA) / 120.0, 0.0, 1.0)
    rgb[land, 0] = 100 + 140 * t[land]
    rgb[land, 1] = 150 + 100 * t[land]
    rgb[land, 2] = 90 + 160 * t[land]
    if hillshade:
        shade = _hillshade(heights.astype(np.int32), heights < _SEA)
        rgb *= (0.30 + 0.70 * shade)[..., None]
    return np.clip(rgb, 0, 255).astype(np.uint8)


def block_color(name, biome_key=None):
    """单个方块名 -> RGB（供其它模块复用）。"""
    if name in _GRASS_BLOCKS:
        return (145, 178, 148)
    return _load_colors().get(name, (255, 0, 255))
