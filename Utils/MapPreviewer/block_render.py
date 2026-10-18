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
    "minecraft:stone": (125, 125, 125),
    "minecraft:cobblestone": (127, 123, 122),
    "minecraft:deepslate": (80, 80, 86),
    "minecraft:dirt": (134, 96, 67),
    "minecraft:coarse_dirt": (119, 85, 59),
    "minecraft:podzol": (91, 63, 24),
    "minecraft:mycelium": (111, 99, 105),
    "minecraft:farmland": (120, 85, 56),
    "minecraft:sand": (219, 207, 163),
    "minecraft:red_sand": (190, 102, 33),
    "minecraft:gravel": (131, 127, 126),
    "minecraft:clay": (160, 166, 179),
    "minecraft:sandstone": (218, 203, 155),
    "minecraft:red_sandstone": (169, 84, 33),
    "minecraft:mud": (60, 57, 55),
    "minecraft:terracotta": (152, 94, 67),
    "minecraft:white_terracotta": (208, 176, 163),
    "minecraft:light_gray_terracotta": (135, 106, 97),
    "minecraft:yellow_terracotta": (186, 133, 35),
    "minecraft:orange_terracotta": (128, 60, 25),
    "minecraft:red_terracotta": (143, 61, 46),
    "minecraft:brown_terracotta": (77, 51, 35),
    "minecraft:moss_block": (89, 109, 45),
    "minecraft:snow_block": (240, 250, 250),
    "minecraft:powder_snow": (250, 255, 255),
    "minecraft:ice": (145, 179, 245),
    "minecraft:packed_ice": (120, 162, 240),
    "minecraft:blue_ice": (106, 154, 235),
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

    pack = {
        "ctx": ctx, "sblob": sblob,
        "block_names": block_names,
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


def _hillshade(heights: np.ndarray, water_mask: np.ndarray) -> np.ndarray:
    """逐方块山体阴影（horn 公式，西北光源 315°/高度角 40°），按高度分层。

    关键：不做低频平滑——先把高度量化到整方块层，坡向/坡度取"层与层之间"
    的突变，从而使阴影每层分明、同层内平坦（对齐参考图台阶观感）。
    返回 [0,~1.3]；水面（water_mask）恒 1。
    """
    # 高度量化：同一方块层内高度完全相同 -> 同层亮度一致（平台）
    hq = np.round(heights.astype(np.float32) / np.float32(_FHS_STEP))
    h = hq * np.float32(_FHS_STEP) * np.float32(_FHS_ZSCALE)
    p = np.pad(h, 1, mode="edge")
    p[0, 1:-1] = 2.0 * h[0] - h[1]
    p[-1, 1:-1] = 2.0 * h[-1] - h[-2]
    p[1:-1, 0] = 2.0 * h[:, 0] - h[:, 1]
    p[1:-1, -1] = 2.0 * h[:, -1] - h[:, -2]
    p[0, 0] = 2.0 * p[0, 1] - p[0, 2]
    p[0, -1] = 2.0 * p[0, -2] - p[0, -3]
    p[-1, 0] = 2.0 * p[-1, 1] - p[-1, 2]
    p[-1, -1] = 2.0 * p[-1, -2] - p[-1, -3]
    sum_e = p[:-2, 2:] + 2.0 * p[1:-1, 2:] + p[2:, 2:]
    sum_w = p[:-2, :-2] + 2.0 * p[1:-1, :-2] + p[2:, :-2]
    sum_n = p[:-2, :-2] + 2.0 * p[:-2, 1:-1] + p[:-2, 2:]
    sum_s = p[2:, :-2] + 2.0 * p[2:, 1:-1] + p[2:, 2:]
    dzdx = (sum_e - sum_w) / 8.0
    dzdy = (sum_n - sum_s) / 8.0
    slope = np.arctan(np.sqrt(dzdx * dzdx + dzdy * dzdy))
    aspect = np.arctan2(-dzdx, -dzdy)
    shade = (np.cos(_HS_ZEN) * np.cos(slope)
             + np.sin(_HS_ZEN) * np.sin(slope) * np.cos(_HS_AZ - aspect))
    shade = np.clip(shade / np.cos(_HS_ZEN), 0.0, 1.3).astype(np.float32)
    # 分级量化：参考图山地只有约 7 个亮度级、|ΔL|<1 占 88%，说明其阴影是
    # 严格分层的。把 shade 量化到 N 级，使同层完全一致、层间跳变分明。
    shade = np.round(shade * np.float32(_FHS_LEVELS)) / np.float32(_FHS_LEVELS)
    # 刻意不做空间平滑：平滑会把台阶抹成连续渐变，与层状观感相反。
    shade[water_mask] = 1.0
    return shade

def _grain(seed: int, x0: int, z0: int, h: int, w: int) -> np.ndarray:
    """逐方块亮度抖动因子（确定性、跨块无缝）：0.94~1.06 微颗粒质感。"""
    rr = np.arange(h, dtype=np.int64)[:, None] + z0
    cc = np.arange(w, dtype=np.int64)[None, :] + x0
    hv = (cc * 73856093) ^ (rr * 19349663) ^ (int(seed) * 83492791)
    hv = (hv ^ (hv >> 13)) * 1274126177
    u = ((hv ^ (hv >> 16)) & 0xFFFF) / 65535.0
    return (0.94 + 0.12 * u).astype(np.float32)


def render_block_region(seed: int, cx_blocks: int, cz_blocks: int,
                        width_blocks: int, height_blocks: int,
                        on_progress=None, cancel=None,
                        want_surface: bool = True,
                        hillshade: bool = False,
                        structures: bool = True) -> dict:
    """渲染一块「1 像素 = 1 方块」的精细俯视图（以 (cx,cz) 为中心）。"""
    w = max(16, (int(width_blocks) // 16) * 16)
    h = max(16, (int(height_blocks) // 16) * 16)
    x0 = ((int(cx_blocks) - w // 2) // 16) * 16
    z0 = ((int(cz_blocks) - h // 2) // 16) * 16
    return _render_rect(seed, x0, z0, w, h, want_surface, hillshade,
                        structures, on_progress, cancel)


def render_tile(seed: int, fx: int, fz: int, ts: int,
                want_surface: bool = True, hillshade: bool = False,
                structures: bool = True, margin: int = 4) -> dict:
    """渲染一个对齐世界网格的精细瓦片：瓦片格 (fx,fz) 覆盖方块
    [fx*ts,(fx+1)*ts)×[fz*ts,(fz+1)*ts)。供视口逐块渐进渲染复用。

    margin：向外多渲染再裁回的边距（方块）。树冠半径最大 3，取 4 覆盖；
    相邻瓦片各自铺满同一棵全局确定性树冠再裁互补半 → 接缝不再切断树木。"""
    x0 = fx * ts
    z0 = fz * ts
    return _render_rect(seed, x0, z0, ts, ts, want_surface, hillshade,
                        structures, None, None, margin=margin)


def _render_rect(seed: int, x0: int, z0: int, w: int, h: int,
                 want_surface: bool, hillshade: bool, structures: bool,
                 on_progress=None, cancel=None, margin: int = 0) -> dict:
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
    rgb = _colorize_blocks(blocks, heights, tq, hq, biome_grid, pack)

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
        # 影调压缩（对齐参考 mean 88）：γ 压低中间调 + 高光软膝点
        t = np.clip(rgb, 0.0, 255.0) / 255.0
        t = np.power(t, 1.40)
        knee = 0.52
        hi = t > knee
        t = np.where(hi, knee + (0.74 - knee)
                     * (1.0 - np.exp(-(t - knee) / (0.74 - knee))), t)
        rgb = t * 255.0
    # 颗粒：振幅调小（±3%），避免破坏层内一致性
    rgb *= (0.970 + 0.060 * _grain(seed, x0, z0, h, w))[..., None]
    if hillshade:
        water_mask = heights < _SEA
        shade = _hillshade(heights.astype(np.int32), water_mask)
        # 最后乘分级 shade：同层完全一致 -> 平台；层间跳变 -> 分明台阶
        rgb *= (0.10 + 0.90 * shade)[..., None]
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)

    block_names = pack["block_names"]
    top_block = np.asarray(block_names, dtype=object)[
        np.clip(blocks, 0, len(block_names) - 1)]

    return {"rgb": _crop(rgb), "heights": _crop(heights),
            "top_block": _crop(top_block),
            "origin_bx": tx0, "origin_bz": tz0, "engine": "native",
            "elapsed": time.perf_counter() - t0, "cancelled": False}


def _grass_tint(tq: np.ndarray, hq: np.ndarray) -> np.ndarray:
    """温度/湿度量化值（*10000）-> (H,W,3) 草色 float32（同主图公式）。"""
    t = np.clip(tq / 10000.0 * 0.5 + 0.5, 0.0, 1.0).astype(np.float32)
    h = np.clip(hq / 10000.0 * 0.5 + 0.5, 0.0, 1.0).astype(np.float32)
    top = _GRASS_TL * (1 - h[..., None]) + _GRASS_TR * h[..., None]
    bot = _GRASS_BL * (1 - h[..., None]) + _GRASS_BR * h[..., None]
    return top * (1 - t[..., None]) + bot * t[..., None]


def _colorize_blocks(blocks: np.ndarray, heights: np.ndarray,
                     tq: np.ndarray, hq: np.ndarray,
                     biome_grid: np.ndarray, pack: dict) -> np.ndarray:
    h, w = blocks.shape
    colors = _load_colors()
    block_names = pack["block_names"]
    # 方块名 -> RGB 查找表（按 surface blob 顺序）
    lut = np.array([colors.get(nm, (255, 0, 255)) for nm in block_names],
                   dtype=np.float32)                    # (nb,3)
    idx = np.clip(blocks, 0, len(block_names) - 1)
    rgb = lut[idx]                                       # (h,w,3)

    name_arr = np.asarray(block_names, dtype=object)
    nm = name_arr[idx]

    # 草色 tint：随温度/湿度真实变色
    gmask = np.isin(nm, list(_GRASS_BLOCKS))
    if gmask.any():
        rgb[gmask] = _grass_tint(tq, hq)[gmask]

    # 冰/雪：固有色（冰雪偏亮，冰偏蓝），不受水深/草色影响
    for bset, col in ((_ICE_BLOCKS, _ICE_RGB),
                      (_SNOW_BLOCKS, np.array([242, 250, 250], np.float32))):
        m = np.isin(nm, list(bset))
        if m.any():
            rgb[m] = col

    # 水面：水下列（未结冰）画海平面水体，按水深渐变（近岸亮→深海暗）
    ice_or_snow = np.isin(nm, list(_ICE_BLOCKS | _SNOW_BLOCKS))
    water_mask = (heights < _SEA) & ~ice_or_snow
    if water_mask.any():
        u = np.clip((_SEA - heights) / 45.0, 0.0, 1.0).astype(np.float32)
        wr = _WATER_SHALLOW * (1 - u[..., None]) + _WATER_DEEP * u[..., None]
        rgb[water_mask] = wr[water_mask]

    return rgb


# 可生长植被的地表（水/冰/裸岩上不放）
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
    # 植被只长在陆地（顶面 y >= 海平面）且可生长地表上；排除水下沙/砾
    growable = np.isin(top_name, list(_GROWABLE)) & (heights >= _SEA)

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

    # 树干命中 -> 冠层（按半径膨胀，逐树干 stamp 圆盘 + 逐像素叶纹 stipple）
    trunk = growable & (_hash01_grid(seed, x0, z0, h, w, 1) < tree_p)
    fol = _hash01_grid(seed, x0, z0, h, w, 7)          # 叶面亮度噪声
    tvar = _hash01_grid(seed, x0, z0, h, w, 8)         # 逐棵树明暗变化
    shap = _hash01_grid(seed, x0, z0, h, w, 9)         # 冠层轮廓扰动
    canopy = np.zeros((h, w), bool)
    ys, xs = np.nonzero(trunk)
    for y, x in zip(ys, xs):
        rad = int(radius[y, x])
        base = canopy_col[y, x] * np.float32(0.90 + 0.20 * tvar[y, x])
        # 每棵树独立的轮廓扰动相位，避免所有冠层都是同一个圆
        ph = np.float32(6.2831853 * tvar[y, x])
        for dy in range(-rad, rad + 1):
            yy = y + dy
            if yy < 0 or yy >= h:
                continue
            for dx in range(-rad, rad + 1):
                xx = x + dx
                if xx < 0 or xx >= w:
                    continue
                r2 = dx * dx + dy * dy
                lim = rad * rad + rad
                if r2 > lim:
                    continue
                # 边界按角度做噪声扰动：不规则树冠轮廓（而非完美圆盘）
                ang = np.arctan2(float(dy), float(dx)) + ph
                wob = 0.80 + 0.34 * (0.5 + 0.5 * np.sin(ang * 3.0)
                                     * np.sin(ang * 2.0 + 1.7))
                if r2 > lim * wob:
                    continue
                if growable[yy, xx]:
                    canopy[yy, xx] = True
                    edge = 1.0 - 0.24 * (r2 / max(lim, 1))
                    rgb[yy, xx] = base * edge \
                        * np.float32(0.88 + 0.24 * fol[yy, xx])

    # 作物（不在冠层下）
    crop = growable & ~canopy & (_hash01_grid(seed, x0, z0, h, w, 4) < crop_p)
    if crop.any():
        for kind in ("cactus", "sugar_cane", "pumpkin", "melon", "bamboo", "berry"):
            m = crop & (crop_kind == kind)
            if m.any():
                rgb[m] = _veg.crop_color(kind)
        m = crop & (crop_kind == "")
        if m.any():
            rgb[m] = (100, 150, 60)

    # 花（不在冠层/作物下）
    flower = growable & ~canopy & ~crop & (_hash01_grid(seed, x0, z0, h, w, 2) < flower_p)
    if flower.any():
        fc = np.array([_veg.flower_color(i) for i in range(7)], dtype=np.float32)
        pick = (_hash01_grid(seed, x0, z0, h, w, 5) * 7).astype(np.int32).clip(0, 6)
        fy, fx = np.nonzero(flower)
        rgb[fy, fx] = fc[pick[fy, fx]]

    # 草（微弱绿调，覆盖剩余可生长地）
    grass = growable & ~canopy & ~crop & ~flower & \
        (_hash01_grid(seed, x0, z0, h, w, 3) < grass_p)
    if grass.any():
        tuft = np.array([70, 120, 52], np.float32)
        rgb[grass] = rgb[grass] * 0.82 + tuft * 0.18


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


def _stamp_village(rgb, heights, ax, az, h, w, seed, wx, wz):
    """村庄：锚点周围散布若干房屋矩形（陆地，确定性）。"""
    from Utils.SeedReverser.biome_noise import BiomeSampler
    try:
        bio = BiomeSampler(seed, "26.2").biome_at(wx >> 2, 64 >> 2, wz >> 2)
    except Exception:
        bio = -1
    house = _VILLAGE_HOUSE["plains"]
    rng = np.random.default_rng((seed * 2654435761 ^ wx * 40503 ^ wz) & 0xffffffff)
    for _ in range(10):
        hx = ax + int(rng.integers(-20, 21))
        hz = az + int(rng.integers(-20, 21))
        hw = int(rng.integers(5, 9)); hl = int(rng.integers(5, 9))
        _stamp_rect(rgb, heights, hx, hz, hw, hl, house, (90, 80, 70), h, w, True)


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
