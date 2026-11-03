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
    # JM 语义：podzol 颜色 = podzol_top 贴图全像素均值（反编译确认
    # calculateAverageColor = 所有 sprite 全部 alpha>0 像素的 R/G/B 简单平均；
    # podzol 不在 grass/foliage/water tint 列表 -> 原色）。jar 实测 (92,63,24)
    "minecraft:podzol": (92, 63, 24),
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
    table.setdefault("minecraft:air", (0, 0, 0))
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

# native 群系扩展（_biome_refine）已推入的 btree 版本名（避免重复推数据）
_BRT_BTREES: set = set()


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

    # 真俯视需要把「非地表方块」也纳入 id 空间（树叶、建筑材质等），
    # 否则 blocks 数组无法表示它们。
    _EXTRA = [
        "minecraft:oak_leaves", "minecraft:birch_leaves",
        "minecraft:spruce_leaves", "minecraft:jungle_leaves",
        "minecraft:acacia_leaves", "minecraft:dark_oak_leaves",
        "minecraft:mangrove_leaves", "minecraft:cherry_leaves",
        "minecraft:azalea_leaves", "minecraft:flowering_azalea_leaves",
        "minecraft:oak_stairs", "minecraft:spruce_stairs",
        "minecraft:oak_slab", "minecraft:oak_planks", "minecraft:cobblestone",
        "minecraft:glass_pane", "minecraft:oak_fence", "minecraft:oak_log",
        "minecraft:dirt_path", "minecraft:wheat", "minecraft:torch",
        # 冰山 feature（IcebergFeature）出水主块：blue_ice 不在 surface
        # blob 的 id 空间（packed_ice 已有），需补录才能参与最高方块竞争
        "minecraft:blue_ice",
    ] + _STRUCTURE_MATERIALS
    _have = set(block_names)
    for _nm in _EXTRA:
        if _nm not in _have:
            block_names.append(_nm)
            _have.add(_nm)
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
    # native 群系网格加速（SeedReverser 二期 C++ 扩展，对拍 3000 点逐位一致）：
    # biome 循环逐格一次拿到 np6 + bid（Python 路径每格要算两遍 climate）；
    # 扩展缺失或推树失败时为 None，走纯 Python 降级路径。
    try:
        from Utils.SeedReverser._native import _biome_refine as _brt
        _bt = bn.get_btree("26.2")
        if _bt.name not in _BRT_BTREES:
            _brt.set_btree(
                _bt.name,
                np.ascontiguousarray(_bt.steps, dtype=np.uint32),
                np.ascontiguousarray(_bt.param, dtype=np.int64),
                np.ascontiguousarray(_bt.nodes, dtype=np.uint64),
                _bt.order,
            )
            _BRT_BTREES.add(_bt.name)
        pack["brt"] = _brt
        pack["brt_name"] = _bt.name
    except Exception:
        pack["brt"] = None
        pack["brt_name"] = ""
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
            ctx, x0, z0 + r0, w, r1 - r0, -64, 320, _NATIVE_THREADS)
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
    brt = pack.get("brt")
    brt_name = pack.get("brt_name", "")
    seed64 = seed & 0xFFFFFFFFFFFFFFFF
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
            if brt is not None:
                # C++ 单点采样（与 biome_noise.py 对拍 3000 点逐位一致），
                # np6 与 bid 一次拿到（Python 路径每格要算两遍 climate）
                r = brt.sample_point(seed64, brt_name, x >> 2, ny, z >> 2)
                np6 = r["np6"]
                qbid[qr, qc] = r["biome_id"]
                qt[qr, qc] = np6[0]
                qh2[qr, qc] = np6[1]
            else:
                cp = bs.climate_point_xz(x >> 2, z >> 2, ny)
                qbid[qr, qc] = bs.biome_at(x >> 2, ny, z >> 2)
                qt[qr, qc] = cp[0]
                qh2[qr, qc] = cp[1]
    biome_grid = np.repeat(np.repeat(qbid, 4, axis=0), 4, axis=1)[:h, :w]
    tq = np.repeat(np.repeat(qt, 4, axis=0), 4, axis=1)[:h, :w]
    hq = np.repeat(np.repeat(qh2, 4, axis=0), 4, axis=1)[:h, :w]

    # ---- 3) native surface：顶块 id + 最终顶 y ----
    tops, blocks = _native.surface_grid(ctx, pack["sblob"], heights,
                                        biome_grid, x0, z0, 63, _NATIVE_THREADS)
    heights = tops
    if on_progress is not None:
        on_progress(h, h, "surface")

    # ---- 4) 配色（向量化）----
    # 真水掩码：由 native 逐列检查「地表到海平面之间是否为水」，
    # 这比顶块类型/高度启发式都可靠（海底顶块是 gravel、低洼陆地也是 dirt）。
    # 水面判定 = 天空朝向的地表高度低于海平面。
    # heights 来自 fill_top_grid（从世界顶部向下扫），**洞穴安全**；
    # 不能像之前的 native 版那样从 seaLevel+1 向下找首个实心——
    # 那会在山体内部的洞穴停下，把海拔 80+ 的山地误判成水
    # （实测 808 列地表>=海平面被判为水，山地上出现大片白斑）。
    wet = heights < _SEA
    rgb = _colorize_blocks(blocks, heights, tq, hq, biome_grid, pack,
                           x0, z0, wet=wet)

    # ---- 4a+) 冰山：官方 IcebergFeature 复刻（frozen_ocean/
    # deep_frozen_ocean，features[2] LOCAL_MODIFICATIONS，官方装饰顺序在
    # 树 step=9 之前）----
    # 出水部分写入 blocks/heights 参与「每列最高方块」竞争（JM 语义：
    # packed_ice/blue_ice/snow_block 均 motion blocking，正常显示冰色/雪帽
    # + heightmap 台阶 bevel；海面冰层 ice/snow layer 被 JM Ignore 穿透
    # 显示水色，见 _colorize_blocks 冰面注释）。
    if want_surface:
        from Utils.MapPreviewer import iceberg_placement as _ibp
        _bergs = _ibp.iceberg_placements(seed, x0, z0, w, h, heights,
                                         biome_grid, pack["id2key"], _SEA)
        for _bx, _bz, _by, _bn in _bergs:
            _gy = _bz - z0
            _gx = _bx - x0
            _nid = pack["name2bid"].get(_bn)
            if _nid is not None and _by > heights[_gy, _gx]:
                heights[_gy, _gx] = _by
                blocks[_gy, _gx] = _nid

    # ---- 4b) 结构：官方装饰顺序 SURFACE_STRUCTURES(step=4) 在树
    # VEGETAL_DECORATION(step=9) 之前，同为参与「每列最高方块」竞争 ----
    # 画在植被之前的官方语义：树在结构之后放置，树放置的土壤检查在
    # 木板/石砖等结构材质上失败 -> 树不会长在结构上（26.2 官方行为）。
    # 此前结构画在植被之后，府邸周边树冠越过屋顶边缘（用户实证）。
    # footprint 近似结构（府邸/海底神殿等）无真实方块 id 进不了 blocks
    # 通道，在 4d 统一配色里会被整体冲掉——此处只收集，4d 之后由
    # _flush_footprints 盖章（同竹点 4e 移到配色之后的原因）。
    fp_queue: list = []
    if structures and want_surface:
        _apply_structures(rgb, heights, blocks, x0, z0, h, w, seed, "26.2",
                          pack=pack, footprints_out=fp_queue)

    # ---- 4c) 植被：写入 blocks/heights 参与「每列最高方块」竞争 ----
    # 真俯视图的语义：树叶高于地面 -> 该列顶块变成 leaves。
    # 不再"覆盖颜色"，而是改变该列的最高方块，最后统一配色。
    # 树冠的 growable 材质检查基于**此时**的 blocks 快照：4b 已写入结构
    # 材质（planks/石砖等不在 _GROWABLE），树冠天然不长上结构。
    if _veg is not None and want_surface:
        bamboo_cells = _apply_vegetation(rgb, heights, blocks, biome_grid, pack, seed, x0, z0,
                          out_blocks=blocks, out_heights=heights)
    else:
        bamboo_cells = None

    # ---- 4d) 统一配色：按最终 blocks（每列最高方块）重新上色 ----
    # wet 必须按**最终 heights** 重算：结构（岸边的沉船/废弃传送门）会把
    # 原本水下的列抬出水面（heights>=海平面），若沿用结构前的旧 wet，
    # 第二次配色会把这些列按水色重画——且 dep=_SEA-heights=0 恰好触发
    # 近岸白 (201,236,255)，表现为岸线上断续的 1px 白条（沉船露出部分）。
    wet = heights < _SEA
    rgb = _colorize_blocks(blocks, heights, tq, hq, biome_grid, pack,
                           x0, z0, wet=wet)

    # ---- 4e') footprint 结构覆盖：必须在 4d 之后（同竹点 4e 的原因，
    # 否则被统一配色整体冲掉——mansion/monument/desert_pyramid 等全灭
    # 的实证见 probe_footprint_ab：mansion 窗口 A/B diff=0）。之后仍吃
    # hillshade 坡度阴影。
    if fp_queue:
        _flush_footprints(rgb, heights, fp_queue)

    # ---- 5) 影调 → 颗粒 → 山体阴影（分级）----
    # 顺序很重要：影调和颗粒必须在乘法式阴影之前完成，否则会把已量化的
    # shade 层级重新打散，失去"每层分明"的平台感。
    rgb = rgb.astype(np.float32)
    # ---- 4e) 竹子点缀（竹林专属）：竹子不在 block_names，只能在此
    # （4d 统一配色之后）直接覆盖 rgb；之后仍会吃 hillshade 坡度阴影。
    if bamboo_cells is not None:
        _apply_bamboo_dots(rgb, bamboo_cells[1])
    if hillshade:
        # 影调：参考实测方块亮度范围 32~207、色阶 158 级，说明亮部要拉高、
        # 色阶要丰富。仅做轻微 γ 与高光软膝（膝点上移到 0.86，不再压扁）。
        # 水列不做 γ：4d 的水色是按 JM 源码精确合成的绝对色（官方深水
        # 实测三群系闭合），JM 渲染链没有这一步整体提亮——吃 γ 会使深水
        # (46,87,168) 偏亮到 (51,93,172)。排除集=真实水列(heights<=61)
        # +海面单层冰列(heights==62 顶块 ice)，再剔除 footprint 盖章列
        # （海底神殿/海底废墟等水下矩形色的亮度是含 γ 拟合的既有验证值，
        # 保持原处理）。
        _wgamma = (heights < _SEA - 1) | ((heights == _SEA - 1)
                                          & (blocks == pack["name2bid"]
                                             .get("minecraft:ice", -1)))
        for _fk, _fax, _faz, _fland in fp_queue:
            _fw, _fl = _FOOTPRINTS[_fk][:2]
            _rx0 = max(0, _fax - _fw // 2)
            _rz0 = max(0, _faz - _fl // 2)
            _hr = heights[_rz0:_rz0 + _fl, _rx0:_rx0 + _fw]
            _sub = _wgamma[_rz0:_rz0 + _fl, _rx0:_rx0 + _fw].copy()
            if _fland:
                _sub &= _hr >= _SEA
            else:
                _sub &= _hr < _SEA
            _wgamma[_rz0:_rz0 + _fl, _rx0:_rx0 + _fw] = _sub
        t = np.clip(rgb, 0.0, 255.0) / 255.0
        t = np.where(_wgamma[..., None], t, np.power(t, 0.94))
        # 不做高光压缩：官方瓦片实测平地雪保持 (255,255,255)
        # （132220 像素为纯白，占已探索像素的第三位），
        # 原来的 knee 会把 249 压到 238，使雪面发灰。
        rgb = t * 255.0
    # 方块材质纹理：±11%（参考实测每方块内亮度极差约 23），
    # 同块内一致 -> 保持方块分明，同时产生 MC 材质的色阶多样性。
    # 地表完全不做色彩抖动：同一地形层必须同色，否则画面破碎。
    # 亮度变异只来自坡度（JM bevelSlope，树冠台阶见 _veg.crown_step）与树种混生。
    if hillshade:
        # JourneyMap 斜坡阴影：按邻列高度差算坡度因子，再对 RGB 做
        # bevel（R/G 额外 *0.85、B 只乘 slope）-> 斜坡变暗且偏蓝。
        # 坡度纯由地形决定，同坡同色，不随机。
        # 显示高度修复（接壤配色差异数值根因）：JM calculateSlope 的输入
        # 是 getBlockHeight（SurfaceRenderer L142-196），mapBathymetry=
        # false 时水列停在**水面顶方块 y=62**，与海床深度无关——水面内
        # 部恒平（slope=1），岸线坡度只来自真实地形高差。此前直接传海床
        # heights，把水下深度梯度当坡度，岸线一圈出现 JM 没有的强 bevel。
        # heights 语义=顶方块 y（fill_top_grid 返回 top=y），故水列显示
        # 高度=np.maximum(heights, 62)。
        from Utils.MapPreviewer import jm_colors as _jm
        disp = np.maximum(heights.astype(np.float32), float(_SEA - 1))
        slope = _jm.slope_from_heights(disp, x0, z0)
        # （旧「水列强制 slope=1」已删：水列 slope 由水面平齐语义自然给
        # 出；岸线水列相对更高陆地 <1 -> bevelSlope 生效，与 JM
        # paintStrata L265-273 对合成后水色应用 bevel 的顺序一致。）
        # 竹点 NoShadow（VanillaBlockHandler：竹 NoShadow 旗标）-> JM
        # showSlope=false（SurfaceRenderer L103：顶块带 NoShadow 的列不加
        # bevel），竹色保持平涂
        if bamboo_cells and bamboo_cells[1]:
            _dy = np.fromiter((c[0] for c in bamboo_cells[1]), np.int64,
                              len(bamboo_cells[1]))
            _dx = np.fromiter((c[1] for c in bamboo_cells[1]), np.int64,
                              len(bamboo_cells[1]))
            slope[np.clip(_dy, 0, h - 1), np.clip(_dx, 0, w - 1)] = 1.0
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


def _grass_tint_by_biome(biome_grid: np.ndarray, pack: dict,
                         gray: float = None, x0: int = 0, z0: int = 0) -> np.ndarray:
    """按群系给出草色（同群系同色，不随温湿度逐点渐变）。

    统一走 MC 官方公式：final = biome_grass_tint * texture_gray / 255。
    色表来自 jm_colors._BIOME_TINTS（26.2 官方语义全量生成）。
    例外：swamp/mangrove_swamp 草色是官方 SWAMP modifier 的逐坐标
    噪声二值（BiomeSpecialEffects.GrassColorModifier.SWAMP，BIOME_INFO_NOISE
    seed 2345），JM 再叠 biomeBlendRadius² 网格平均（JmBlockAccess
    method_23752，用户 biomeBlendRadius=2 -> 5×5），无法用表值，
    由 _swamp_grass_field 逐方块复刻。
    """
    from Utils.MapPreviewer import jm_colors as _jm
    h, w = biome_grid.shape
    out = np.empty((h, w, 3), np.float32)
    id2key = pack["id2key"]
    if gray is None:
        pal = pack.get("jm_palette") or {}
        gb = pal.get("minecraft:grass_block")
        gray = float(gb[1]) if gb else 147.0
    cache: dict[int, tuple] = {}
    swamp_bids = {bid for bid, k in id2key.items()
                  if k.split(":")[-1] in ("swamp", "mangrove_swamp")}
    swamp_field = None
    for r in range(h):
        for c in range(w):
            bid = int(biome_grid[r, c])
            # swamp 系是逐坐标噪声场，严禁按 bid 缓存（同 bid 不同位
            # 置颜色不同），逐像素取场值（同样乘贴图灰度）
            if bid in swamp_bids:
                if swamp_field is None:
                    swamp_field = _swamp_grass_field(
                        biome_grid, id2key, x0, z0)
                out[r, c] = swamp_field[r, c] * (gray / 255.0)
                continue
            col = cache.get(bid)
            if col is None:
                k = id2key.get(bid, "")
                t = _jm.tint_for_biome("grass", k.split(":")[-1])
                col = tuple(int(round(v * gray / 255.0)) for v in t)
                cache[bid] = col
            out[r, c] = col
    return out


# 官方 SWAMP modifier 二值色（BiomeSpecialEffects.java L87-92：
# groundValue < -0.1 ? -11766212 : -9801671，即 0x4C603C / 0x6A7039）
_SWAMP_COLD = (76, 96, 60)      # noise < -0.1
_SWAMP_WARM = (106, 112, 57)    # noise >= -0.1
_SWAMP_BLEND = 2                # 用户 biomeBlendRadius=2 -> 5×5 网格


def _swamp_grass_field(biome_grid: np.ndarray, id2key: dict,
                       x0: int, z0: int) -> np.ndarray:
    """swamp/mangrove_swamp 草色场：官方 SWAMP modifier + JM blend。

    每方块 (bx,bz)：noise(bx*0.0225, bz*0.0225) < -0.1 ?
    (76,96,60) : (106,112,57)（BIOME_INFO_NOISE = PerlinSimplexNoise
    seed 2345 octave [0]，与世界种子无关），再对以该方块为中心的
    (2*dist+1)² 网格逐通道整除平均（JmBlockAccess.method_23752）。
    为性能预计算掩码 bbox 外扩 dist 的噪声图，滑窗求和向量化。
    """
    from Utils.MapPreviewer.density_sampler import _biome_info_noise
    noise = _biome_info_noise()
    h, w = biome_grid.shape
    d = _SWAMP_BLEND
    # swamp 系掩码 bbox（全像素精确判定，与其他段一致）
    mask = np.zeros((h, w), bool)
    for r in range(h):
        for c in range(w):
            if id2key.get(int(biome_grid[r, c]), "").split(":")[-1] in (
                    "swamp", "mangrove_swamp"):
                mask[r, c] = True
    out = np.zeros((h, w, 3), np.float32)
    rs, cs = np.nonzero(mask)
    if rs.size == 0:
        return out
    r0, r1 = int(rs.min()), int(rs.max())
    c0, c1 = int(cs.min()), int(cs.max())
    hh, ww = r1 - r0 + 1, c1 - c0 + 1
    # bbox 外扩 d 的噪声图：row=世界 z、col=世界 x
    nh, nw = hh + 2 * d, ww + 2 * d
    vals = np.empty((nh, nw), np.float32)
    for rr in range(nh):
        bz = z0 + r0 - d + rr
        bx = x0 + c0 - d
        for cc in range(nw):
            vals[rr, cc] = noise.get_value(
                (bx + cc) * 0.0225, bz * 0.0225, False)
    below = (vals < -0.1).astype(np.int32)
    # 滑窗 (2d+1)² 计数：s[r,c] = 邻域内 <-0.1 的点数
    s = np.zeros((hh, ww), np.int32)
    total = (2 * d + 1) ** 2
    for dy in range(2 * d + 1):
        for dx in range(2 * d + 1):
            s += below[dy:dy + hh, dx:dx + ww]
    # 逐通道整除平均（Java 整除语义）
    for i in range(3):
        out[r0:r1 + 1, c0:c1 + 1, i] = (
            (_SWAMP_COLD[i] * s + _SWAMP_WARM[i] * (total - s)) // total
        )
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
                     x0: int = 0, z0: int = 0,
                     wet=None) -> np.ndarray:
    h, w = blocks.shape
    # 配色改走 JourneyMap 方案：每方块一个固定色（贴图均值 * 群系 tint），
    # 颜色只是"方块类型+群系"的函数，与坐标无关 -> 同层必然同色。
    colors = pack.get("jm_palette") or _load_colors()
    block_names = pack["block_names"]
    # 方块名 -> RGB 查找表（按 surface blob 顺序）
    _miss = [nm for nm in block_names if nm not in colors]
    if _miss and not getattr(_colorize_blocks, "_warned", False):
        _colorize_blocks._warned = True
        print("[block_render] 缺配色的方块:", _miss[:8])
    lut = np.array([colors.get(nm, (255, 0, 255)) for nm in block_names],
                   dtype=np.float32)                    # (nb,3)
    idx = np.clip(blocks, 0, len(block_names) - 1)
    rgb = lut[idx]                                       # (h,w,3)

    name_arr = np.asarray(block_names, dtype=object)
    nm = name_arr[idx]
    # 树叶按群系 tint 着色：leaves 贴图是**灰度图**，直接取均值是灰色，
    # 必须乘群系 foliage tint 才是绿色（JourneyMap 同法）。
    _leaf_names = [b for b in block_names if "leaves" in b.split(":")[-1]]
    if _leaf_names:
        from Utils.MapPreviewer import jm_colors as _jm2
        _lm = np.isin(nm, _leaf_names)
        if _lm.any():
            _leafcols = {}
            for _b in _leaf_names:
                _leafcols[_b] = {}
            _rows = np.nonzero(_lm.any(axis=1))[0]
            for _r in _rows[::4]:
                for _c in range(0, w, 4):
                    _bk = pack["id2key"].get(
                        int(biome_grid[_r, _c]), "minecraft:plains"
                    ).split(":")[-1]
                    for _b in _leaf_names:
                        _cc = _leafcols[_b].get(_bk)
                        if _cc is None:
                            _cc = _jm2.tinted_color(_b, _bk, colors)
                            _leafcols[_b][_bk] = _cc
                        if _cc is None:
                            continue
                        _sub = _lm[_r:_r + 4, _c:_c + 4] & (nm[_r:_r + 4, _c:_c + 4] == _b)
                        if _sub.any():
                            rgb[_r:_r + 4, _c:_c + 4][_sub] = _cc


    # 草色 tint：按群系量化取色（同群系同色），不做逐点温湿度渐变。
    # 逐点 tint 会让同一高度层出现上百种绿，画面破碎（实测同层 143 色）。
    # swamp/mangrove_swamp 由 _grass_tint_by_biome 内部逐坐标复刻
    # 官方 SWAMP modifier（噪声二值 + 5×5 平均），不再硬编码经验色。
    gmask = np.isin(nm, list(_GRASS_BLOCKS))
    if gmask.any():
        _gt = _grass_tint_by_biome(biome_grid, pack, x0=x0, z0=z0)
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

    # 冰/雪：走色表固有色（参考截图为冷蓝灰，非亮白），不受水深/草色影响
    for bset, dflt in ((_ICE_BLOCKS, (126, 146, 186)),
                       (_SNOW_BLOCKS, (176, 184, 200))):
        m = np.isin(nm, list(bset))
        if m.any():
            for bname in bset:
                mm = (nm == bname)
                if mm.any():
                    rgb[mm] = colors.get(bname, dflt)

    # 水面判定（两源合并，缺一不可）：
    #   a) 顶块本身就是水/冰方块（浅水/水面未被 surface 规则替换时）
    #   b) 该列 fill 顶低于海平面（海床是 gravel/sand，但上方覆盖水体）
    # 只用 a) 会漏掉整片海洋（海床顶块是砾石）；只用 b) 会把低洼陆地
    # 误判成水。故必须结合「是否低于海平面」+「排除冰/雪」。
    # 判别只看**顶块类型**，不看高度：
    #   顶块是 water/冰 -> 水；其余（gravel/sand/dirt，哪怕低于海平面）
    #   -> 陆地。低洼陆地的顶块是土/砾石，绝不会是 water。
    # （高度不能作判据：整片内陆低地的高度都 < SEA）
    # 水面判别（三分法，避免此前两个方向的误判）：
    #   a) 顶块就是 water                        -> 水
    #   b) 顶块是海床材质(gravel/sand/clay) 且高度远低于海平面 -> 被水覆盖
    #   c) 其余（含低洼但顶块是土/草的陆地）      -> 陆地
    # 关键：低洼陆地的顶块是 dirt/grass，绝不会有 gravel/sand 海床特征，
    # 且高度通常贴近海平面；真正海底则深达 -20 以下。
    _WATER_BLOCKS = {"minecraft:water"}
    _SEABED = {"minecraft:gravel", "minecraft:sand", "minecraft:clay",
               "minecraft:dirt", "minecraft:suspicious_sand",
               "minecraft:suspicious_gravel"}
    is_water_blk = np.isin(nm, list(_WATER_BLOCKS))
    is_seabed = np.isin(nm, list(_SEABED))
    # 冻结海面：冰/浮冰之下的水体在 MC 里仍属海洋，JourneyMap 也按水色
    # 显示（官方 frozen_ocean 瓦片实测为深蓝 (42,41,148)）。
    # 故 _ICE_BLOCKS 不排除水面判定，只排除雪（雪是真正的地表覆盖）。
    # ---- 寒冷群系覆雪判定（freeze_top_layer）+ JM 冰面穿透语义 ----
    # 官方语义链（26.2 反编译 + JM 反编译）：
    #   MC blocksMotion() = 碰撞 bounds>=0.729 或满块（BlockBehaviour
    #   L502-545）-> 1 层 snow layer(0.125) 不算、ice 算；MOTION_BLOCKING
    #   = blocksMotion() || 流体（Heightmap L151）。
    #   JM VanillaBlockHandler L67-68 把 ice/frosted_ice 标 BlockFlag.Ignore
    #   （冰在 JM 地图从不显示）；SurfaceRenderer.getBlockHeight L143-179
    #   从 precipitationHeight 向下扫遇 Ignore 穿透 -> 冻洋/冻河冰面列
    #   （ice+snow layer）穿透冰停在水面 -> 按 mapBathymetry=false 显示
    #   水色（官方 frozen_ocean 瓦片深蓝 (42,41,148)）。故水面一律走
    #   水色，不再平涂冰色（旧版 _ice_mask 平涂是错的）。
    #   冰山（IcebergFeature，4a+ 已写入 blocks/heights）出水的
    #   packed_ice/blue_ice/snow_block 是 motion blocking 满块，其列
    #   heights>=海平面不在 water_mask，正常显示冰色/雪帽 + bevel 台阶。
    _frz = np.zeros((h, w), bool)
    if wet is not None:
        # 逐列判定群系是否触发 freeze_top_layer（用于下方覆雪）
        _id2key = pack["id2key"]
        for _r in range(h):
            for _c in range(w):
                _bk = _id2key.get(
                    int(biome_grid[_r, _c]), "").split(":")[-1]
                if _bk in _FREEZE_BIOMES:
                    _frz[_r, _c] = True

    if wet is not None:
        # 真实水列（heights 语义=顶方块 y，fill_top_grid/surface 均返回
        # top=y，seed=1 跨海剖面实证水列=海床 25~45）：海面顶方块 y=62
        # -> heights<=61 才有水覆盖；heights==62 是恰好海平面的实心滩涂
        # （无水），旧 heights<_SEA 会把这 1px 误判成水。
        water_mask = np.asarray(wet, bool) & (heights < _SEA - 1)
        # 海面单层冰列：JM VanillaBlockHandler L67-68 把 ice/frosted_ice
        # 标 BlockFlag.Ignore -> SurfaceRenderer.getBlockHeight 穿透冰停
        # 在水面 -> 水色链。仅限 minecraft:ice（1 层海冰/冻河冰）；
        # packed_ice/blue_ice（冰山）不 Ignore，正常冰色。冰面列
        # heights==62 无海厚信息 -> 归入纯水色近似（冰下水深普遍 >7）。
        _ice_bid = (pack or {}).get("name2bid", {}).get("minecraft:ice", -1)
        if _ice_bid >= 0:
            water_mask = water_mask | ((blocks == _ice_bid)
                                       & (heights == _SEA - 1))
    else:
        # 兜底启发式（wet=None 时；冰/雪列不算水）
        deep = heights < (_SEA - 6)
        _ice_snow = np.isin(nm, list(_ICE_BLOCKS | _SNOW_BLOCKS))
        water_mask = (is_water_blk | (is_seabed & deep)) & ~_ice_snow
    if water_mask.any():
        # ==== JM 水色精确复刻（源码链 + 官方深水实测三群系闭合）====
        # 源码链（mapTransparency=true、mapBathymetry=false、
        # tweakWaterColorBlend=0.5、tweakBrightenDaylightDiff=0.06，
        # 用户 26.2-NeoForge 实例配置与默认值逐项一致）：
        #   buildStrata（SurfaceRenderer L198-229）：自水面 y=62 向下最多
        #   push maxDepth=8 层，遇不透明海床 break -> 水层数 n<=7 时海床
        #   入栈，n>=8 栈内全水。
        #   nextUp（Strata L117-139）：中间水层被 ignoreMiddleFluid 跳过，
        #   只处理海床（lightAttenuation=n）与顶层水（=0）。
        #   setStratumColors（BaseRenderer L117-166）：
        #     海床 var8=(15-n)/15+0.06 -> day=blendWith(bed*var8, wc, 0.5)
        #     顶层水 var8=1.06          -> day=wc*1.06
        #   paintStrata（SurfaceRenderer L237-252）：
        #     render=blendWith(海床day, 顶层水day, alpha=0.7)
        #   展开：result = 0.892*wc + 0.15*bed*((15-n)/15+0.06)
        #   n>=8（及冰面列）: result = wc*1.06（纯水色）
        # wc = water_still 贴图均值 x biome water tint(5x5 整除平均)。
        # 贴图 1.21.11 jar 实测为纯灰 (177.09,177.09,177.09)（32 帧全帧
        # 平均，alpha=180 恒定）：
        #   ocean 深水=(46.4,86.9,167.8)   <-> 官方 (47,87,167)
        #   frozen_ocean=(42.0,41.2,148.0) <-> 官方 (42,41,148)
        #   cold_ocean=(44.9,64.0,157.7)   <-> 官方 (45,64,158)
        # 旧 188/255 系数恰为 177.09*1.06 的近似（把顶层水亮度吸进基色），
        # 且旧 0.55 逐层叠加把 cold_ocean 深水误当深度梯度拟合、浅水海床
        # 权重 45% 远超 JM 的 15%——一并废弃。
        # 浅水透底（用户主诉）：n<=7 海床以 15% 权重混入且亮度 (15-n)/15
        # 递减 -> 7 级渐进色阶；n>=8 纯水（JM mapBathymetry=false 语义）。
        from Utils.MapPreviewer import jm_colors as _jm2
        # 水色 tint 混合（复刻 JM mapBlendWater=true，用户 core config
        # 实测 "mapBlendWater": "true"）：VanillaBlockColorProxy
        # getColorMultiplier L86-89 水分支 -> BiomeColors
        # .getAverageWaterColor(blockPos)（WATER_COLOR_RESOLVER
        # = biome.getWaterColor()，无坐标依赖）-> JmBlockAccess
        # method_23752 L196-230：以方块为中心取 (2r+1)^2 网格（r = MC
        # 视频设置 biomeBlendRadius，用户 options.txt = 2 -> 5x5=25 点），
        # 逐点取该点群系的 water_color，逐通道求和**整除实际点数**
        # （地图边缘缺失 biome 不计入，对应 count<25）。
        # tint 原值（整数）整除平均后再乘贴图灰度、round 成 int
        # （getBlockColor 的 RGB.multiply->toInteger 量化语义）——
        # method_23752 的整数截断在 tint 域发生，顺序不可交换。
        _maxbid = max(pack["id2key"].keys()) + 1
        _wlut = np.empty((_maxbid, 3), np.int32)
        _wlut[:] = _jm2._BIOME_WATER_DEFAULT
        for _bid, _key in pack["id2key"].items():
            _wlut[_bid] = _jm2.tint_for_biome("water", _key.split(":")[-1])
        _px = _wlut[np.clip(biome_grid, 0, _maxbid - 1)]     # (h,w,3)
        _pad = np.full((h + 4, w + 4, 3), -1, np.int32)
        _pad[2:2 + h, 2:2 + w] = _px
        _sum = np.zeros((h, w, 3), np.int32)
        _cnt = np.zeros((h, w), np.int32)
        for _dy in range(-2, 3):
            for _dx in range(-2, 3):
                _win = _pad[2 + _dy:2 + _dy + h, 2 + _dx:2 + _dx + w]
                _ok = _win[..., 0] >= 0
                _sum += np.where(_ok[..., None], _win, 0)
                _cnt += _ok
        _WCg = np.round((_sum // np.maximum(_cnt, 1)[..., None])
                        * (177.09 / 255.0))
        # n=水层数=62-heights（水面顶块 y=62、水列海床 heights<=61 ->
        # n>=1）；冰面列 heights==62 -> n=0 归入纯水分支。
        _n = np.clip((62 - heights).astype(np.float32), 0.0, 7.0)
        _shallow = water_mask & (heights >= 55)  # n in [1,7] <=> h in [55,61]
        # 逐级 int 量化复刻（adjustBrightness/blendWith 每步 toInteger，
        # 四舍五入）：bevelSlope 不在此处——JM 顺序是先合成后 bevel
        #（paintStrata L265-273），由 _render_rect 的坡度段统一应用。
        _b = ((15.0 - _n) / 15.0 + 0.06)[..., None]
        _wc1 = np.round(_WCg * 1.06)                     # 顶层水 day
        _bed_adj = np.round(rgb[_shallow].astype(np.float32)
                            * _b[_shallow])              # 海床亮度
        _bed_day = np.round(_bed_adj * 0.5 + _WCg[_shallow] * 0.5)
        _wr_sh = np.round(_wc1[_shallow] * 0.7 + _bed_day * 0.3)
        wr = np.broadcast_to(_wc1, (h, w, 3)).copy()
        wr[_shallow] = _wr_sh
        rgb[water_mask] = wr[water_mask].astype(np.uint8)

    # ---- 积雪：树冠上表面覆雪（freeze_top_layer 的另一半）----
    # MC 的 freeze_top_layer 只在「上方为空气」的方块顶面放雪层，包括树叶。
    # 水下列上方是水不是空气 -> 海床不覆雪。water_mask 含全部真实水列
    # （heights<=61）与海面单层冰列（JM Ignore 穿透语义），
    # & ~water_mask 恰好同时排除水下列与冰面列；heights==62 的海平面
    # 滩涂列不算水 -> 寒冷群系下可正常覆雪（JM：顶块 sand 上方是空气，
    # freeze_top_layer 放雪）。修复此前
    # 冻洋水下海床被覆雪洗白（174373 px gravel 死白）的 bug。
    if _frz.any():
        _leaf_like = np.isin(nm, list(_SNOW_COVERABLE))
        _snow_mask = _frz & _leaf_like & ~water_mask
        if _snow_mask.any():
            # 覆雪不是纯白：薄雪层会透出底色，按底色 0.72 白 + 0.28 底
            _base = colors.get("minecraft:snow_block") or (249, 254, 254)
            _sb = np.array(_base, np.float32)
            _keep2 = 0.28
            rgb[_snow_mask] = (rgb[_snow_mask].astype(np.float32) * _keep2
                               + _sb * (1.0 - _keep2))


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

# 会触发 freeze_top_layer 的寒冷群系（MC biome features[10] 含该特征；
# 生效条件温度 <= 0.15——26.2 全部群系实测：cold_ocean/deep_cold_ocean
# 温度 0.5，官方不结冰不覆雪，此前误含导致冷水海洋水面/海床被涂白）
_FREEZE_BIOMES = {
    "frozen_river", "frozen_ocean", "deep_frozen_ocean", "ice_spikes",
    "snowy_plains", "snowy_taiga", "snowy_beach", "snowy_slopes",
    "frozen_peaks", "jagged_peaks", "grove",
}

# 寒冷群系里会被 freeze_top_layer 覆雪的方块（上方为空气时积雪层）
_SNOW_COVERABLE = {
    "minecraft:oak_leaves", "minecraft:birch_leaves",
    "minecraft:spruce_leaves", "minecraft:jungle_leaves",
    "minecraft:acacia_leaves", "minecraft:dark_oak_leaves",
    "minecraft:mangrove_leaves", "minecraft:cherry_leaves",
    "minecraft:azalea_leaves", "minecraft:flowering_azalea_leaves",
    "minecraft:grass_block", "minecraft:coarse_dirt",
    "minecraft:podzol", "minecraft:mycelium", "minecraft:moss_block",
    "minecraft:sand", "minecraft:gravel", "minecraft:stone",
    "minecraft:andesite", "minecraft:diorite", "minecraft:granite",
    "minecraft:cobblestone", "minecraft:short_grass", "minecraft:fern",
}

# 陆地/水下结构用到的材质（144 项，由 structure_render 汇总实测得到；
# 后 5 项为废弃传送门官方全链新引入：fiq 降解输出 mossy_stairs/slab、
# stone_slab、obsidian 0.15 哭泣、postProcess 藤；海底神殿程序化
# 结构引入 prismarine 全系 + sea_lantern——不在自然 surface 生成，
# 不补录则 _stamp_real_blocks 拿不到 bid，beard=False 只抬 heights
# 不写 blocks 通道，4d 按海床块渲染且 top_block 丢失（monu_verify
# 实证：top_block 全 "."、heights 抬升到 _SEA 而非块顶）。必须预先
# 纳入 id 空间，否则结构方块无法参与「每列最高」竞争。
_STRUCTURE_MATERIALS = [
    "minecraft:barrel", "minecraft:basalt", "minecraft:blackstone",
    "minecraft:blackstone_stairs", "minecraft:blue_terracotta",
    "minecraft:brick_stairs", "minecraft:bricks",
    "minecraft:carved_pumpkin", "minecraft:chest", "minecraft:candle",
    "minecraft:chiseled_deepslate", "minecraft:chiseled_polished_blackstone",
    "minecraft:chiseled_sandstone",
    "minecraft:chiseled_stone_bricks", "minecraft:chiseled_tuff",
    "minecraft:chiseled_tuff_bricks", "minecraft:cobbled_deepslate",
    "minecraft:cobblestone_stairs", "minecraft:cobweb", "minecraft:crying_obsidian",
    "minecraft:cracked_deepslate_bricks",
    "minecraft:cracked_deepslate_tiles",
    "minecraft:cracked_polished_blackstone_bricks",
    "minecraft:cracked_stone_bricks", "minecraft:crafting_table",
    "minecraft:cut_sandstone",
    "minecraft:cyan_terracotta", "minecraft:dark_oak_fence",
    "minecraft:dark_oak_log", "minecraft:dark_oak_planks",
    "minecraft:dark_oak_slab", "minecraft:dark_oak_stairs",
    "minecraft:dark_prismarine",
    "minecraft:deepslate", "minecraft:deepslate_brick_slab",
    "minecraft:deepslate_brick_stairs", "minecraft:deepslate_brick_wall",
    "minecraft:deepslate_bricks", "minecraft:deepslate_tile_stairs",
    "minecraft:deepslate_tile_wall", "minecraft:deepslate_tiles",
    "minecraft:dispenser", "minecraft:furnace", "minecraft:gilded_blackstone",
    "minecraft:glass", "minecraft:gold_block", "minecraft:gray_carpet",
    "minecraft:gray_wool", "minecraft:hay_block", "minecraft:hopper",
    "minecraft:infested_stone_bricks", "minecraft:iron_bars",
    "minecraft:iron_chain", "minecraft:ladder", "minecraft:lectern",
    "minecraft:light_blue_carpet", "minecraft:light_blue_wool",
    "minecraft:light_gray_carpet", "minecraft:light_gray_glazed_terracotta",
    "minecraft:light_gray_terracotta", "minecraft:magma_block",
    "minecraft:mossy_cobblestone", "minecraft:mossy_stone_brick_slab",
    "minecraft:mossy_stone_brick_stairs",
    "minecraft:mossy_stone_bricks", "minecraft:mud_brick_slab",
    "minecraft:mud_brick_stairs", "minecraft:mud_bricks",
    "minecraft:netherrack", "minecraft:oak_button", "minecraft:oak_trapdoor",
    "minecraft:obsidian", "minecraft:orange_terracotta",
    "minecraft:packed_mud", "minecraft:polished_andesite",
    "minecraft:polished_blackstone_brick_stairs",
    "minecraft:polished_blackstone_bricks", "minecraft:polished_deepslate",
    "minecraft:polished_deepslate_stairs", "minecraft:polished_deepslate_wall",
    "minecraft:polished_tuff", "minecraft:pumpkin", "minecraft:red_bed",
    "minecraft:prismarine", "minecraft:prismarine_bricks",
    "minecraft:red_carpet", "minecraft:red_terracotta",
    "minecraft:redstone_block", "minecraft:redstone_lamp",
    "minecraft:redstone_torch", "minecraft:reinforced_deepslate",
    "minecraft:sand", "minecraft:sandstone", "minecraft:sandstone_slab",
    "minecraft:sandstone_stairs",
    "minecraft:sculk_sensor", "minecraft:sea_lantern", "minecraft:soul_lantern", "minecraft:soul_sand",
    "minecraft:spruce_fence", "minecraft:spruce_planks", "minecraft:spruce_slab",
    "minecraft:spruce_stairs", "minecraft:stone_brick_slab",
    "minecraft:stone_brick_stairs", "minecraft:stone_bricks",
    "minecraft:stone_slab", "minecraft:tnt", "minecraft:vine",
    "minecraft:tuff_bricks", "minecraft:wall_torch",
    "minecraft:waxed_copper_block", "minecraft:waxed_cut_copper",
    "minecraft:waxed_oxidized_cut_copper",
    "minecraft:waxed_oxidized_cut_copper_stairs",
    "minecraft:white_carpet", "minecraft:white_terracotta",
    "minecraft:white_wool", "minecraft:yellow_glazed_terracotta",
    "minecraft:yellow_terracotta",
]

# 原生调用的线程预算。实测单瓦片(72x72=5184 列) fill_top_grid：
#   threads=1 -> 0.921s, 2 -> 0.146s, 4 -> 0.155s, 8 -> 0.198s, 32 -> 0.277s
# 线程创建/join 开销压过并行收益，故默认 2；上层瓦片并发时由
# set_native_threads() 按 cpu/并发数 调整。
_NATIVE_THREADS = 2


def set_native_threads(n: int) -> None:
    """设置原生 fill/surface 调用的线程数（供瓦片线程池按并发度调整）。"""
    global _NATIVE_THREADS
    _NATIVE_THREADS = max(1, int(n))


_LEAF_BID: dict[str, int] = {}
_CURRENT_NAME2BID: dict[str, int] = {}
_CURRENT_PACK: dict = {}

_GROWABLE = {
    "minecraft:grass_block", "minecraft:dirt", "minecraft:coarse_dirt",
    "minecraft:podzol", "minecraft:mycelium", "minecraft:moss_block",
    "minecraft:snow_block", "minecraft:sand", "minecraft:terracotta",
    "minecraft:mud",
}

# 竹下灰化土与竹子的官方放置链见 bamboo_placement.py（26.2 反编译
# 逐行复刻：SUPPORTS_BAMBOO / BENEATH_BAMBOO_PODZOL_REPLACEABLE 官方
# tag 已展开为该模块内的方块名集合）。


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


def _apply_vegetation(rgb, heights, blocks, biome_grid, pack, seed, x0, z0,
                      out_blocks=None, out_heights=None):
    """按官方放置链做确定性植被叠加（就地改 rgb float32 / blocks / heights）。

    树：官方 per-chunk 摆位（tree_placement_official）+ 官方逐格树形
    （tree_shape_official，26.2 反编译直译：树干/树冠/装饰器/根系/巨型
    蘑菇/倒木全链），写入 blocks/heights 参与「每列最高方块」竞争；
    竹子：官方 BambooFeature 放置链（podzol 盘 + 竹点）。返回
    (disk_cells, dot_cells)。
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
    _n2b = pack.get("name2bid") or {}
    global _LEAF_BID
    if not _LEAF_BID and _n2b:
        for _k, _v in _n2b.items():
            if _k.endswith("_leaves"):
                _LEAF_BID[_k] = _v
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

    # 真实树摆放：官方惰性流装饰（tree_placement_dynamic）——26.2
    # ChunkGenerator.applyBiomeDecoration 语义：逐位置串行 + 树形内联
    # （摆位↔树形 RNG 同流交织）+ 树冠实时抬高 OCEAN_FLOOR 高度图（树叶
    # blocksMotion=true）→ 落在冠投影列的后续尝试被 would_survive 砍掉、
    # 山坡树被 getMaxFreeTreeHeight 砍掉（渲染树数与游戏一致：纯樱花区块
    # ~3.5 棵，静态批处理版为 9.8）。hm_ocean/hm_surface 为动态高度图的
    # 静态回退基线；静态版 place_trees_in_rect 保留作对拍基准。
    from Utils.MapPreviewer import tree_placement_dynamic as _tpd
    hm_ocean = heights.astype(np.int32) + 1
    hm_surface = np.where(heights < _SEA, _SEA, heights + 1).astype(np.int32)
    heights_i = hm_ocean - 1            # 顶方块 y（int32 视图）

    def h_at(x, z):
        lx, lz = x - x0, z - z0
        if 0 <= lx < w and 0 <= lz < h:
            return int(heights_i[lz, lx])
        return 63                        # 区域外中性值（同探针）

    def s_at(x, z):
        lx, lz = x - x0, z - z0
        if 0 <= lx < w and 0 <= lz < h:
            return names[int(blocks[lz, lx])]
        return "grass_block"

    def w_at(x, z):
        lx, lz = x - x0, z - z0
        if 0 <= lx < w and 0 <= lz < h:
            hg = int(heights_i[lz, lx])
            return (_SEA - 1) if hg < _SEA else hg
        return 62

    canopy = np.zeros((h, w), bool)
    level = _tpd.decorate_trees_in_rect(
        seed, x0, z0, w, h, h_at, s_at, w_at, hm_ocean, hm_surface,
        biome_grid, pack["id2key"])
    n2b = pack.get("name2bid") or {}
    for (bx, by, bz), name in level.blocks.items():
        gx = bx - x0
        gz = bz - z0
        if not (0 <= gx < w and 0 <= gz < h):
            continue
        bid2 = n2b.get("minecraft:" + name)
        if bid2 is not None and by > out_heights[gz, gx]:
            out_heights[gz, gx] = by
            out_blocks[gz, gx] = bid2
            if name.endswith("_leaves"):
                canopy[gz, gx] = True

    # ---- 官方竹子放置链（26.2 BambooFeature；bamboo_placement.py 逐行
    # 复刻 noise_based_count/in_square/heightmap/biome + 逐尝试 RNG）----
    # placed bamboo = bamboo_some_podzol(probability 0.2)：每株竹 20% 概率
    # 在脚下打半径 1~4 的 podzol 圆盘（官方先盘后竹）。盘走方块通道
    # （blocks=podzol id，高度不变：podzol 与地表同层），4d 统一配色会按
    # podzol 上色；竹点在 4d 后覆盖回竹色（盘心必有竹，与官方几何一致：
    # 竹秆列顶高于 podzol）。
    from Utils.MapPreviewer import bamboo_placement as _bp
    disk_cells, dot_cells = _bp.bamboo_placements(
        seed, x0, z0, w, h, heights, top_name, biome_grid,
        pack["id2key"], canopy=canopy, sea_level=_SEA)
    pid = _n2b.get("minecraft:podzol")
    if pid is not None:
        for yy, xx in disk_cells:
            out_blocks[yy, xx] = pid
    return disk_cells, dot_cells


def official_canopy_mask(seed: int, x0: int, z0: int, w: int, h: int):
    """主预览（block_colors block 档）用的官方树冠掩码。

    跑官方惰性流树装饰（tree_placement_dynamic.decorate_trees_in_rect，
    与精细瓦片视图同一条链），返回:
      (canopy, canopy_bid):
        canopy: (h, w) bool——树冠列（存在树叶方块的列）；
        canopy_bid: (h, w) int32——冠列应显示的群系 id。樱花冠强制
          cherry_grove（跨群系伸入邻群系的冠仍显粉色），其余取列群系。
    调用方需保证 26.2 + native 可用（is_available），异常时降级概率树。
    """
    from Utils.MapPreviewer import tree_placement_dynamic as _tpd
    pack = _get_pack(seed)
    ctx = pack["ctx"]
    id2key = pack["id2key"]
    seed64 = seed & 0xFFFFFFFFFFFFFFFF
    brt = pack.get("brt")
    brt_name = pack.get("brt_name", "")
    heights = _native.fill_top_grid(ctx, x0, z0, w, h, -64, 320,
                                    _NATIVE_THREADS)
    qh, qw = (h + 3) // 4, (w + 3) // 4
    qbid = np.zeros((qh, qw), dtype=np.int32)
    for qr in range(qh):
        z = z0 + qr * 4
        for qc in range(qw):
            x = x0 + qc * 4
            top = int(heights[min(qr * 4, h - 1), min(qc * 4, w - 1)])
            ny = max(-64, min(319, top)) >> 2
            if brt is not None:
                qbid[qr, qc] = brt.sample_point(
                    seed64, brt_name, x >> 2, ny, z >> 2)["biome_id"]
            else:
                qbid[qr, qc] = pack["bs"].biome_at(x >> 2, ny, z >> 2)
    biome_grid = np.repeat(np.repeat(qbid, 4, 0), 4, 1)[:h, :w]
    tops, blocks = _native.surface_grid(ctx, pack["sblob"], heights,
                                        biome_grid, x0, z0, 63,
                                        _NATIVE_THREADS)
    tops = tops.astype(np.int32)
    hm_ocean = tops + 1
    hm_surface = np.where(tops < 63, 63, tops + 1).astype(np.int32)
    heights_i = hm_ocean - 1            # 顶方块 y

    def h_at(x, z):
        lx, lz = x - x0, z - z0
        if 0 <= lx < w and 0 <= lz < h:
            return int(heights_i[lz, lx])
        return 63

    def s_at(x, z):
        lx, lz = x - x0, z - z0
        if 0 <= lx < w and 0 <= lz < h:
            return pack["block_names"][int(blocks[lz, lx])]
        return "grass_block"

    def w_at(x, z):
        lx, lz = x - x0, z - z0
        if 0 <= lx < w and 0 <= lz < h:
            hg = int(heights_i[lz, lx])
            return (_SEA - 1) if hg < _SEA else hg
        return 62

    level = _tpd.decorate_trees_in_rect(
        seed, x0, z0, w, h, h_at, s_at, w_at, hm_ocean, hm_surface,
        biome_grid, id2key)
    bid_cherry = [b for b, k in id2key.items()
                  if k == "minecraft:cherry_grove"][0]
    canopy = np.zeros((h, w), dtype=bool)
    canopy_bid = biome_grid.astype(np.int32).copy()
    for (bx, by, bz), nm in level.blocks.items():
        if not nm.endswith("_leaves"):
            continue
        gx = bx - x0
        gz = bz - z0
        if not (0 <= gx < w and 0 <= gz < h):
            continue
        canopy[gz, gx] = True
        if nm == "cherry_leaves":
            canopy_bid[gz, gx] = bid_cherry
    return canopy, canopy_bid


def _apply_bamboo_dots(rgb, cells):
    """竹林竹子格（必须在 4d 统一配色之后调用：直接覆盖最终 rgb）。

    JM 语义（反编译 VanillaBlockHandler/VanillaBlockColorProxy）：竹子 =
    Plant 旗标、alpha=1.0 -> 俯视整格显示自身颜色；NoShadow -> 不抬地图
    高度；不在 grass/foliage/water tint 列表 -> 颜色 = bamboo_stalk 贴图
    全像素均值 (94,144,20)，无 tint 无随机抖动（JM 同 sprite 同群系同色，
    格间明暗只来自坡度 bevel）。位置由 bamboo_placement.官方链计算
    （_apply_vegetation 返回值传入），盘心与竹点同格：竹秆列顶高于
    podzol，俯视显示竹色。
    """
    if not cells:
        return
    base = np.asarray((94, 144, 20), np.float32)   # bamboo_stalk 贴图均值
    for yy, xx in cells:
        rgb[yy, xx] = base


# ---- 结构 footprint 近似（占地尺寸/材质为代表性近似）----
# key: (宽, 长, 主体色, 边框/屋顶色)；村庄单独按房屋簇渲染。
# 盖章时机：4d 统一配色之后（_flush_footprints）——此前在 4b 直接写
# rgb 会被 4d 整体重画冲掉（mansion/monument/desert_pyramid 等全部
# 不可见，probe_footprint_ab 实证 diff=0）。
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


# 有真实 NBT 模板、可按方块还原的结构（其余用 footprint 矩形近似）
_TEMPLATE_STRUCTURES = {
    "pillager_outpost", "igloo", "shipwreck", "ruined_portal",
    "ancient_city", "trail_ruins",
}

# 地下结构（官方 step=underground_decoration/underground_structures，
# terrain_adaptation=beard_box/bury，start_height 在地表之下）：
#   ancient_city: start_height=-27，生成于 deep_dark 洞穴层；
#   trail_ruins:  start_height=-15，project WORLD_SURFACE_WG 后整体掩埋。
# 俯视地图上它们被地表完整覆盖，不可见。此前误共用地表结构的
# base_y 逻辑（锚点 fill_top 地表高度且强制 ≥65），把整座远古城市
# 拼接到地表 stamping（stony_peaks 画廊 (-2816,0) 实证）。渲染中排除。
_UNDERGROUND_STRUCTURES = {"ancient_city", "trail_ruins"}

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


def _flush_footprints(rgb, heights, queue):
    """4d 统一配色之后的 footprint 近似矩形盖章（含边框色）。

    4d 按最终 blocks 通道整体重画 rgb，任何在 4b 写入 rgb 的 footprint
    都会被冲掉（竹林竹点为此移到 4e，同因）。footprint 结构（林地府邸/
    海底神殿/沙漠神殿/沼泽小屋/沙漠水井/海底废墟等纯程序化或无模板
    回退）没有真实方块 id 可进 blocks 通道，只能在最终 rgb 上直接盖章。
    """
    h, w = rgb.shape[:2]
    for key, ax, az, land in queue:
        wl, ll, fill, border = _FOOTPRINTS[key]
        _stamp_rect(rgb, heights, ax, az, wl, ll, fill, border, h, w, land)


def _apply_structures(rgb, heights, blocks, x0, z0, h, w, seed, version,
                      pack=None, footprints_out=None):
    """枚举区域结构：真实模板/jigsaw/全链结构在此 stamp（参与每列最高
    方块竞争）；footprint 近似结构只收集到 footprints_out，由 4d 之后的
    _flush_footprints 统一盖章（否则会被统一配色冲掉）。"""
    try:
        from Utils.Public import structure_map as smap
    except Exception:
        return
    # 枚举键必须同时包含 footprint 近似与真实模板结构，
    # 否则 bastion 根本不会被枚举到。地下结构不渲染，也不枚举。
    keys = sorted((set(_FOOTPRINTS) | _TEMPLATE_STRUCTURES | {"village"})
                  - _UNDERGROUND_STRUCTURES)
    # 结构会跨越瓦片边界：村庄实测可达 115x80，远超 _FINE_TILE(64)。
    # 若只在本瓦片矩形内枚举，则「锚点在别的瓦片、但主体伸进本瓦片」的
    # 结构完全不会画出来 -> 村庄被截断。故枚举范围外扩 _STRUCT_PAD。
    _STRUCT_PAD = 96
    try:
        structs = smap.enumerate_structures(
            seed, version,
            (x0 - _STRUCT_PAD, z0 - _STRUCT_PAD,
             x0 + w - 1 + _STRUCT_PAD, z0 + h - 1 + _STRUCT_PAD),
            struct_keys=keys)
    except Exception:
        return
    global _CURRENT_NAME2BID, _CURRENT_PACK
    _CURRENT_PACK = pack or {}
    _CURRENT_NAME2BID = (pack or {}).get("name2bid") or {}
    for st in structs:
        key = st.get("struct")
        if key in _UNDERGROUND_STRUCTURES:
            continue   # 防御：地下结构绝不参与地表 stamping
        ax = int(st.get("x", 0)) - x0
        az = int(st.get("z", 0)) - z0
        land = key not in _WATER_STRUCTURES
        if key == "village":
            _stamp_village(rgb, heights, blocks, ax, az, h, w, seed,
                          int(st.get("x", 0)), int(st.get("z", 0)),
                          x0=x0, z0=z0)
            continue
        # 其余陆地结构：有真实模板的按模板还原，失败的才回退矩形近似
        sx = int(st.get("x", 0))
        sz = int(st.get("z", 0))
        if key == "ruined_portal":
            # 官方全链：变体选择 + 处理器链 + 菱形土堆/滴柱/藤叶
            #（structure_render.ruined_portal_blocks，地面以下方块已滤除）。
            # 模拟抛错才回退 footprint 近似；成功但空（如完全掩埋的
            # underground 变体）不画矩形。
            try:
                from Utils.MapPreviewer import structure_render as _srender
                wb = _srender.ruined_portal_blocks(
                    seed, sx, sz, pack, threads=_NATIVE_THREADS)
            except Exception:
                wb = None
            if wb is not None:
                if wb:
                    _stamp_real_blocks(rgb, heights, blocks, wb,
                                       x0, z0, h, w, pack)
                continue
        if key == "mansion":
            # 官方全链：MansionGrid 拼装 + 模板体素（真实屋顶俯视），
            # y = 5×5 盒 4 角 WORLD_SURFACE_WG 最低值（随 rotation 偏移，
            # y<60 官方拒绝生成 => 空不画，也不回退 footprint）。
            # beard=False：地形高于结构顶的列保持地形（官方俯视语义），
            # 避免 beard=True 在山坡把 heights 压出凹坑。
            try:
                from Utils.MapPreviewer import structure_render as _srender
                wb = _srender.mansion_blocks(seed, sx, sz, pack,
                                             threads=_NATIVE_THREADS)
            except Exception:
                wb = None
            if wb is not None:
                if wb:
                    _stamp_real_blocks(rgb, heights, blocks, wb,
                                       x0, z0, h, w, pack, beard=False)
                continue
        if key == "jungle_temple":
            # 官方全链：ScatteredFeaturePiece postProcess 逐行转写
            #（structure_render.jungle_temple_blocks，复用
            # pyramid_pieces._sim_jungle）+ 变体流朝向 +
            # updateAverageGroundHeight 官方 y（全足迹 MBNL 平均）。
            # 模拟抛错才回退 footprint 近似。
            try:
                from Utils.MapPreviewer import structure_render as _srender
                wb = _srender.jungle_temple_blocks(seed, sx, sz, pack,
                                                   threads=_NATIVE_THREADS)
            except Exception:
                wb = None
            if wb is not None:
                if wb:
                    _stamp_real_blocks(rgb, heights, blocks, wb,
                                       x0, z0, h, w, pack, beard=False)
                continue
        if key == "desert_pyramid":
            # 官方全链：ScatteredFeaturePiece postProcess 逐行转写
            #（structure_render.desert_pyramid_blocks，复用
            # pyramid_pieces._sim_desert）+ 变体流朝向 +
            # updateHeightPositionToLowestGroundHeight 官方 y
            #（全足迹 MBNL 最低值 − nextInt(3)，1.21.11/26.2 同）。
            # 模拟抛错才回退 footprint 近似。
            # 胜出列已由 desert_pyramid_blocks 做官方逐列裁决
            #（S_top>=fill_top 或 air_top>=fill_top），beard=True
            # 无条件落盘：等高替换（r=1 基座/顶尖蓝陶瓦）与
            # AIR 挖掘列 heights 压低到结构实心顶均在列内完成。
            try:
                from Utils.MapPreviewer import structure_render as _srender
                wb = _srender.desert_pyramid_blocks(seed, sx, sz, pack,
                                                    threads=_NATIVE_THREADS)
            except Exception:
                wb = None
            if wb is not None:
                if wb:
                    _stamp_real_blocks(rgb, heights, blocks, wb,
                                       x0, z0, h, w, pack, beard=True)
                continue
        if key == "swamp_hut":
            # 官方全链：SwampHutPiece L56-95 逐行转写
            #（structure_render.swamp_hut_blocks，复用
            # pyramid_pieces._sim_hut，无 RNG 流）+ 同丛林朝向口径 +
            # updateAverageGroundHeight(level, chunkBB, 0) 官方 y
            #（同丛林公式）。逐列官方竞争后 beard=True 落盘
            #（等高替换语义，同沙漠）。模拟抛错才回退 footprint。
            try:
                from Utils.MapPreviewer import structure_render as _srender
                wb = _srender.swamp_hut_blocks(seed, sx, sz, pack,
                                               threads=_NATIVE_THREADS)
            except Exception:
                wb = None
            if wb is not None:
                if wb:
                    _stamp_real_blocks(rgb, heights, blocks, wb,
                                       x0, z0, h, w, pack, beard=True)
                continue
        if key == "ocean_ruin":
            # 官方全链：OceanRuinStructure/OceanRuinPieces 26.2 逐行复刻
            #（structure_render.ocean_ruin_blocks）：rotation → isLarge
            # → 模板选择（cold 三模板同位叠加）→ cluster 子废墟群 →
            # 逐 piece OCEAN_FLOOR_WG y（fill_top+1）+ 官方下沉判定 →
            # BlockRotProcessor 逐方块蚀除 → chest/drowned 数据标记。
            # beard=False：模板无块列地形保留（山脊/沙脊穿出官方语义），
            # 水列 depths 由水色公式自然处理（深水纯水色、浅水混入）。
            # 模拟抛错才回退 footprint 近似。
            try:
                from Utils.MapPreviewer import structure_render as _srender
                wb = _srender.ocean_ruin_blocks(seed, sx, sz, pack,
                                                threads=_NATIVE_THREADS)
            except Exception:
                wb = None
            if wb is not None:
                if wb:
                    _stamp_real_blocks(rgb, heights, blocks, wb,
                                       x0, z0, h, w, pack, beard=False)
                continue
        if key == "monument":
            # 官方全链：OceanMonumentStructure + MonumentBuilding 26.2 逐行
            # 复刻（structure_render.ocean_monument_blocks）：nextInt(4) 朝向
            # → 房间图（46 房 + Util.shuffle + 关门循环 findSource 保连通）
            # → fitter 顺序分配 → wings/penthouse → postProcess 全序
            # （主水盒/两翼/拱门/入口墙/顶件/三墙/7×7 柱网 fill_down/外圈
            # 阶梯水盒/子 piece）。水盒清海床：caps={col: 盒底-1} 先把
            # heights 压低（min 语义，盒底以下地形未动故精确），清空列由
            # 4d 第二次配色按 n=62-38>=8 纯深水色渲染；结构列由真实块
            # 竞争（beard=False：地形高于结构顶的列保持地形，官方俯视语义）。
            # 模拟抛错才回退 footprint 近似。
            try:
                from Utils.MapPreviewer import structure_render as _srender
                _mw = _srender.ocean_monument_blocks(
                    seed, sx, sz, pack, threads=_NATIVE_THREADS)
            except Exception:
                _mw = None
            if _mw is not None:
                _mblks, _mcaps = _mw
                for (_cwx, _cwz), _cap in _mcaps.items():
                    _cpx = _cwx - x0
                    _cpz = _cwz - z0
                    if 0 <= _cpx < w and 0 <= _cpz < h:
                        if heights[_cpz, _cpx] > _cap:
                            heights[_cpz, _cpx] = _cap
                if _mblks:
                    _stamp_real_blocks(rgb, heights, blocks, _mblks,
                                       x0, z0, h, w, pack, beard=False)
                continue
        if key in _TEMPLATE_STRUCTURES:
            try:
                from Utils.MapPreviewer import structure_render as _srender
                _by = 64
                _ctx = (pack or {}).get("ctx")
                if _ctx is not None:
                    _by = int(_native.fill_top_grid(
                        _ctx, sx, sz, 1, 1, -64, 320, 1)[0, 0])
                _by = max(_by, _SEA + 1)
                wb = _srender.structure_blocks(key, seed, sx, sz, base_y=_by)
            except Exception:
                wb = []
            if wb and _stamp_real_blocks(rgb, heights, blocks, wb,
                                         x0, z0, h, w, pack):
                continue
        if key in _FOOTPRINTS:
            if footprints_out is not None:
                # 延后到 4d 统一配色之后盖章（_flush_footprints）
                footprints_out.append((key, ax, az, land))
            else:
                wl, ll, fill, border = _FOOTPRINTS[key]
                _stamp_rect(rgb, heights, ax, az, wl, ll, fill, border,
                            h, w, land)



def _stamp_real_blocks(rgb, heights, blocks, world_blocks, gx0, gz0, h, w,
                       pack, beard=True):
    """把结构的实体方块写入图：真俯视 + beard 地形适配。

    与 _stamp_village 共用语义：
      - 逐列取结构内最高实体方块
      - 屋顶优先（_ROOF_BLOCKS 不被后放模板的地面盖掉）
      - 结构一律以自身 y 覆盖 heights（对应 terrain_adaptation）
    返回 True 表示写入了至少一个方块。
    """
    try:
        from Utils.MapPreviewer import jm_colors as _jm
        from Utils.MapPreviewer import village_jigsaw as _vj
    except Exception:
        return False
    if not world_blocks:
        return False
    vgrid = np.empty((h, w), dtype=object)
    vgrid[:] = None
    vtop = np.full((h, w), -9999, np.int32)
    skip = ("air", "jigsaw", "structure_void", "cave_air", "void_air", "")
    for (bx, by, bz, nm) in world_blocks:
        px, pz = bx - gx0, bz - gz0
        if not (0 <= px < w and 0 <= pz < h):
            continue
        if nm.split(":")[-1] in skip:
            continue
        if by > vtop[pz, px]:
            vtop[pz, px] = by
            vgrid[pz, px] = nm
    names = {nm for row in vgrid for nm in row if nm}
    if not names:
        return False
    pal = _jm.build_block_palette(sorted(names))
    # 屋顶优先
    roof_y = np.full((h, w), -9999, np.int32)
    roof_nm = np.empty((h, w), dtype=object)
    roof_nm[:] = None
    for (bx, by, bz, nm) in world_blocks:
        px, pz = bx - gx0, bz - gz0
        if not (0 <= px < w and 0 <= pz < h):
            continue
        sh = nm.split(":")[-1]
        if sh in skip:
            continue
        if _vj._ROOF_BLOCKS.__contains__(sh) and by > roof_y[pz, px]:
            roof_y[pz, px] = by
            roof_nm[pz, px] = nm
    # 屋顶优先只在屋顶确实处于该列最高处（或与最高处齐平）时生效。
    # 无条件覆盖会出错：雪屋的 stone_bricks 属屋顶材质，但它上方的
    # snow_block 圆顶（94 格）会被顶掉，导致雪屋看起来没有雪。
    has_roof = (roof_nm != None) & (roof_y >= vtop)
    vgrid[has_roof] = roof_nm[has_roof]
    vtop[has_roof] = np.maximum(vtop[has_roof], roof_y[has_roof])

    n2b = (pack or {}).get("name2bid") or {}
    # 向量化：材质只有 ~20 种，按材质分组做掩码批量赋值，
    # 取代 72x72 的 Python 逐像素双重循环（实测占结构瓦片主要耗时）。
    _v = vtop.astype(np.int32)
    for nm in {x for row in vgrid for x in row if x}:
        m = vgrid == nm
        col = pal.get(nm)
        if col is not None:
            rgb[m] = col
        bid = n2b.get(nm)
        if bid is not None:
            if beard:
                heights[m] = _v[m]
                blocks[m] = bid
            else:
                keep = m & (_v > heights)
                heights[keep] = _v[keep]
                blocks[keep] = bid
        else:
            low = m & (heights < _SEA)
            heights[low] = _SEA
    return True


def _stamp_village(rgb, heights, blocks, ax, az, h, w, seed, wx, wz,
                   colors=None, x0=0, z0=0):
    """用真实 jigsaw 还原的村庄，并让建筑方块参与「每列最高方块」竞争。

    读 jar 内村庄模板 NBT（town_centers/houses/streets/decor），按权重
    拼出整座村庄，取每列最高实体方块 —— 房屋外形、门窗、草径(dirt_path)、
    农田、水井都是模板里的真实布局。

    真俯视语义：建筑的 y 高于地表时，该列顶块变成建筑的方块（屋顶），
    因此只能看到屋顶，看不到房屋内部。
    """
    try:
        from Utils.MapPreviewer import village_jigsaw as _vj
        from Utils.MapPreviewer import jm_colors as _jm
    except Exception:
        return
    try:
        from Utils.MapPreviewer import village_jigsaw_exact as _vx
        # 地形适配：村庄贴到锚点处地表；低于海平面则抬到 SEA+1
        # base_y 必须与「哪块瓦片来画」无关，否则同一个村庄在不同瓦片里
        # 高度不同 -> 拼接处断裂。故直接用锚点世界坐标算地表高度，
        # 而不是用当前瓦片的 heights（其 ax/az 是相对偏移且常越界）。
        _by = 64
        try:
            _ctx = _CURRENT_PACK.get("ctx")
            if _ctx is not None:
                _h = _native.fill_top_grid(_ctx, wx, wz, 1, 1, -64, 320, 1)
                _by = int(_h[0, 0])
        except Exception:
            _by = 64
        _by = max(_by, _SEA + 1)
        fp = _vx.build_village(seed, wx, wz, base_y=_by)
    except Exception:
        try:
            fp = _vj.village_footprint(seed, wx, wz)
        except Exception:
            return
    if not fp["blocks"]:
        return

    # 逐列取村庄的最高实体方块 + 其世界 y
    # 注意：grid 原点必须是**当前渲染区域的世界原点** (x0,z0)，
    # 不是 (wx-ax, wz-az)。后者只在锚点恰好落在本区域时相等；
    # 村庄跨瓦片时（锚点在别块）会整体错位，导致本瓦片画不出村庄。
    gx0, gz0 = x0, z0
    vgrid = np.empty((h, w), dtype=object)
    vgrid[:] = None
    vtop = np.full((h, w), -9999, np.int32)
    skip = ("air", "jigsaw", "structure_void", "cave_air", "void_air")
    for (bx, by, bz, nm) in fp["blocks"]:
        px, pz = bx - gx0, bz - gz0
        if not (0 <= px < w and 0 <= pz < h):
            continue
        if nm.split(":")[-1] in skip:
            continue
        if by > vtop[pz, px]:
            vtop[pz, px] = by
            vgrid[pz, px] = nm

    names = set()
    for row in vgrid:
        for nm in row:
            if nm:
                names.add(nm)
    if not names:
        return
    pal = _jm.build_block_palette(sorted(names))
    n2b = _CURRENT_NAME2BID or {}

    # 村庄底座铺平（含房屋间洼地），对应 terrain_adaptation=beard_thin
    covered = vgrid != None
    pad = np.zeros_like(covered)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            ys = np.clip(np.arange(h) + dy, 0, h - 1)
            xs = np.clip(np.arange(w) + dx, 0, w - 1)
            pad |= covered[np.ix_(ys, xs)]
    ground_nm = "minecraft:dirt_path"
    if ground_nm not in n2b:
        ground_nm = "minecraft:dirt"
    ground_col = pal.get(ground_nm) or (139, 112, 76)
    ground_bid = n2b.get(ground_nm)

    # 向量化（同上：避免逐像素 Python 循环）
    _v = vtop.astype(np.int32)
    for nm in {x for row in vgrid for x in row if x}:
        m = vgrid == nm
        col = pal.get(nm)
        if col is not None:
            rgb[m] = col
        bid = n2b.get(nm)
        if bid is not None:
            heights[m] = _v[m]
            blocks[m] = bid
        else:
            low = m & (heights < _SEA)
            heights[low] = _SEA
    gap = (vgrid == None) & pad & (heights < _SEA)
    if gap.any():
        rgb[gap] = ground_col
        heights[gap] = _SEA
        if ground_bid is not None:
            blocks[gap] = ground_bid


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
