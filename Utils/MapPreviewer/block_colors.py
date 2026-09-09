# -*- coding: utf-8 -*-
"""JourneyMap 风格方块级俯视渲染（1 方块 = 1 像素）。

输入为噪声格分辨率（1 噪声格 = 4x4 方块）的群系/气候矩阵
（map_sampler.sample_region 输出），输出 4 倍边长的 uint8 RGB 矩阵。
色彩规则参考 Minecraft 原版材质语义与地图类模组（JourneyMap/Xaero）
的俯视观感：

- 草地/树叶：温度 x 湿度双梯度草色（原版 colormap 语义），
  群系系数微调出各群系身份色；热带草原类固定原版草色
  #BFB755（不随气候插值）；
- 水面：按 depth 参数固定物理映射的深浅渐变（深水暗/浅水亮），
  河流固定浅亮蓝、深海加深，冻洋/冻河渲染为冰面；
- 恶地：按 depth 高度分档的陶瓦色带（原版 badlands 条带语义）；
- 山地：石面/雪面/草面按群系与低频 patch 噪声混合；雪坡林地面
  雪底云杉冠；
- 洞穴群系（溶洞/滴水石/深暗之域）：1.18+ 噪声源可能输出，
  按旧版观感渲染（溶洞棕绿苔藓、深暗之域黑底幽匿微光）；
- 全体方块级伪随机颗粒（噪声哈希以 (方块坐标, 种子) 为输入，
  同参数结果可复现），森林类群系叠加树冠斑点、繁花森林点缀花色。

架构：噪声格级（cell）算基色 → 4x 上采样到方块级 → 方块级遮罩
（树冠/泥土/水洼/冰裂等）+ 颗粒扰动。低频 patch 场以全局坐标为
哈希输入，跨渲染块无缝衔接。

群系 id 语义与 cubiomes biomes.h BiomeID 一致（含 +128 变体与
1.18+ 新 id 177~186）；未收录 id 按平原草色兜底，不致渲染失败。
"""

from __future__ import annotations

import numpy as np

# 每噪声格边长对应的方块/像素数
CELL = 4

# 群系分类（LUT 按 bid 0..255 索引）
_CAT_WATER = 0
_CAT_GRASS = 1
_CAT_SNOW = 2
_CAT_SAND = 3
_CAT_STONE = 4
_CAT_BADLAND = 5
_CAT_SWAMP = 6
_CAT_MUSHROOM = 7

# 恶地陶瓦色带（原版 badlands 条带常用色序，高原顶→谷底）
_TERRACOTTA = np.array([
    (216, 151, 74), (186, 133, 35), (167, 104, 48), (161, 83, 37),
    (152, 94, 67), (144, 71, 35), (142, 60, 46), (134, 96, 67),
], dtype=np.float32)

# 草色双梯度四角锚点（近似原版 grass colormap）：
# 行=温度（冷→热），列=湿度（干→湿）
_GRASS_TL = np.array([128, 180, 151], dtype=np.float32)  # 冷干
_GRASS_TR = np.array([110, 172, 128], dtype=np.float32)  # 冷湿
_GRASS_BL = np.array([191, 183, 85], dtype=np.float32)   # 热干（热带草原）
_GRASS_BR = np.array([89, 201, 60], dtype=np.float32)    # 热湿（丛林）

_DIRT_RGB = np.array([134, 96, 67], dtype=np.float32)
_SNOW_RGB = np.array([238, 243, 246], dtype=np.float32)
_ICE_RGB = np.array([168, 196, 238], dtype=np.float32)
_SAND_RGB = np.array([219, 207, 163], dtype=np.float32)
_STONE_RGB = np.array([127, 127, 127], dtype=np.float32)
_GRAVEL_RGB = np.array([136, 126, 126], dtype=np.float32)
_MYCELIUM_RGB = np.array([122, 110, 116], dtype=np.float32)
_SWAMP_GRASS = np.array([106, 112, 57], dtype=np.float32)
_SWAMP_WATER = np.array([89, 125, 105], dtype=np.float32)
_MANGROVE_GRASS = np.array([96, 114, 58], dtype=np.float32)
_BLUE_ICE_RGB = np.array((170, 205, 235), dtype=np.float32)
_WOODED_BAD_TOP = np.array((172, 162, 90), dtype=np.float32)
_MYCELIUM_SPECK = np.array((150, 90, 110), dtype=np.float32)
_CHERRY_CANOPY = np.array([231, 168, 193], dtype=np.float32)
_PALE_CANOPY = np.array([172, 181, 158], dtype=np.float32)
_SNOW_TAIGA_CROWN = np.array([56, 82, 70], dtype=np.float32)

# 洞穴群系（1.18+ 噪声源可能输出，俯视图按旧版观感处理）
_CAVE_LUSH_RGB = np.array([136, 118, 82], dtype=np.float32)
_CAVE_MOSS = np.array([100, 138, 70], dtype=np.float32)
_CAVE_DRIPSTONE = np.array([150, 132, 106], dtype=np.float32)
_CAVE_DEEPDARK = np.array([42, 46, 58], dtype=np.float32)
_SCULK_SPECK = np.array([96, 150, 170], dtype=np.float32)

# 水色锚点（基准≈原版 #3F76E4）
_WATER_SHALLOW = np.array([96, 156, 240], dtype=np.float32)
_WATER_BASE = np.array([63, 118, 228], dtype=np.float32)
_WATER_DEEP = np.array([30, 54, 140], dtype=np.float32)

# 花色点缀（繁花森林/草甸）
_FLOWER_COLORS = np.array([
    (238, 220, 90), (230, 80, 80), (240, 240, 240), (200, 140, 200),
], dtype=np.float32)

# 未收录 id 兜底（平原草色）
_FALLBACK_CELL = np.array((145, 189, 89), dtype=np.float32)

_WATER_IDS = (0, 7, 24, 44, 45, 46, 47, 48, 49)
_FROZEN_WATER_IDS = (10, 11, 50)          # 冰面（含冻河）
_DEEP_WATER_IDS = (24, 47, 48, 49)        # 深海加深
_SNOW_IDS = (12, 13, 26, 140, 178, 179, 180, 181)
_SAND_IDS = (2, 130, 16)
_STONE_IDS = (3, 20, 25, 131, 182)
_BADLAND_IDS = (37, 38, 39, 165)
_SWAMP_IDS = (6, 134, 184)
_MUSHROOM_IDS = (14, 15)
_TAIGA_IDS = (5, 19, 133, 32, 33, 34)     # 云杉类（树冠色偏暗蓝绿）
_SNOW_TAIGA_IDS = (30, 31, 158)           # 雪地+云杉斑点


def _one_hot(ids) -> np.ndarray:
    lut = np.zeros(256, dtype=bool)
    for b in ids:
        if 0 <= b < 256:
            lut[b] = True
    return lut


def _build_luts():
    cat = np.full(256, _CAT_GRASS, dtype=np.uint8)
    for group, c in ((_WATER_IDS, _CAT_WATER), (_FROZEN_WATER_IDS, _CAT_WATER),
                     (_SNOW_IDS, _CAT_SNOW), (_SAND_IDS, _CAT_SAND),
                     (_STONE_IDS, _CAT_STONE), (_BADLAND_IDS, _CAT_BADLAND),
                     (_SWAMP_IDS, _CAT_SWAMP), (_MUSHROOM_IDS, _CAT_MUSHROOM)):
        for b in group:
            cat[b] = c

    # 草色群系系数（乘在双梯度 tint 上）
    mult = np.ones((256, 3), dtype=np.float32)
    for b in (1, 129):            # plains
        mult[b] = (1.10, 1.01, 0.83)
    for b in (4, 18):             # forest
        mult[b] = (0.98, 1.00, 0.90)
    mult[132] = (1.05, 1.02, 0.88)   # flower_forest
    mult[177] = (1.06, 1.04, 0.92)   # meadow
    for b in (27, 28, 155, 156):  # birch
        mult[b] = (1.04, 0.99, 1.00)
    for b in (29, 157):           # dark_forest
        mult[b] = (0.72, 0.82, 0.70)
    for b in (21, 22, 168, 169):  # jungle
        mult[b] = (0.98, 1.05, 0.85)
    mult[23] = (1.02, 1.03, 0.90)    # sparse_jungle
    for b in _TAIGA_IDS:          # taiga / 云杉林
        mult[b] = (0.92, 0.95, 1.02)
    for b in _SNOW_TAIGA_IDS:
        mult[b] = (0.90, 0.94, 1.02)
    for b in (35, 36, 163, 164):  # savanna：基色固定为原版 #BFB755，
        pass                      # 不随气候插值（在 _render_chunk 覆盖）
    for b in (186,):              # pale_garden 灰绿
        mult[b] = (1.02, 1.06, 1.02)

    # 树冠斑点密度
    dens = np.zeros(256, dtype=np.float32)
    dens[4], dens[18], dens[132] = 0.42, 0.38, 0.22
    dens[27], dens[28], dens[155], dens[156] = 0.40, 0.36, 0.42, 0.36
    dens[29], dens[157] = 0.62, 0.60
    dens[21], dens[22], dens[23] = 0.55, 0.50, 0.28
    dens[168], dens[169] = 0.58, 0.55
    for b, d in ((5, 0.45), (19, 0.42), (133, 0.42), (32, 0.50), (33, 0.52)):
        dens[b] = d
    dens[30], dens[31], dens[158] = 0.32, 0.28, 0.30
    dens[178] = 0.50
    dens[34] = 0.30
    dens[35], dens[36], dens[163], dens[164] = 0.10, 0.08, 0.08, 0.06
    dens[3] = 0.12
    dens[186] = 0.45
    dens[185] = 0.55               # 樱花树冠密，粉色要成片

    # 树冠色 = 草 tint x CANOPY_MULT；绝对色模式（樱花/苍白）用 CANOPY_ABS
    cmult = np.ones((256, 3), dtype=np.float32)
    for b in (4, 18, 132):
        cmult[b] = (0.60, 0.66, 0.50)
    for b in (27, 28, 155, 156):
        cmult[b] = (0.82, 0.92, 0.72)
    for b in (29, 157):
        cmult[b] = (0.45, 0.58, 0.42)
    for b in (21, 22, 23, 168, 169):
        cmult[b] = (0.55, 0.78, 0.45)
    for b in _TAIGA_IDS:
        cmult[b] = (0.42, 0.62, 0.50)
    for b in _SNOW_TAIGA_IDS:
        cmult[b] = (0.35, 0.52, 0.45)
    cmult[178] = (0.38, 0.55, 0.48)
    for b in (35, 36, 163, 164):
        cmult[b] = (0.72, 0.82, 0.55)
    cmult[3] = (0.55, 0.70, 0.52)

    cabs = np.zeros((256, 3), dtype=np.float32)
    cabs[185] = _CHERRY_CANOPY
    cabs[186] = _PALE_CANOPY
    abs_mask = _one_hot((185, 186))

    # 泥土斑点密度（草类；非草类为 0）
    dirt = np.full(256, 0.035, dtype=np.float32)
    for b in (35, 36, 163, 164):
        dirt[b] = 0.05
    for group in (_WATER_IDS + _FROZEN_WATER_IDS + _SNOW_IDS + _SAND_IDS
                  + _BADLAND_IDS + _SWAMP_IDS + _MUSHROOM_IDS):
        dirt[group] = 0.0
    dirt[6] = dirt[134] = dirt[184] = 0.0   # 沼泽自绘水洼
    dirt[174] = dirt[175] = dirt[183] = 0.0  # 洞穴群系自绘

    # 石面草 patch 概率（风袭丘陵/疏林山地：灰绿混杂）
    grass_patch = np.zeros(256, dtype=np.float32)
    grass_patch[3] = 0.42
    grass_patch[20] = 0.25
    grass_patch[34] = 0.55
    # 砾质丘陵砾石 patch
    gravel_patch = np.zeros(256, dtype=np.float32)
    gravel_patch[131] = 0.45

    return cat, mult, dens, cmult, cabs, abs_mask, dirt, grass_patch, \
        gravel_patch


(_CAT, _GRASS_MULT, _CANOPY_DENS, _CANOPY_MULT, _CANOPY_ABS, _CANOPY_ABS_M,
 _DIRT_DENS, _GRASS_PATCH, _GRAVEL_PATCH) = _build_luts()


# ---------------------------------------------------------------------------
# 伪随机与上采样（可复现：输入 = 世界坐标 + 种子）
# ---------------------------------------------------------------------------

def _hash01(bx: np.ndarray, bz: np.ndarray, seed: int,
            salt: int) -> np.ndarray:
    """(方块/噪声格 x, z, 种子, salt) -> [0,1) 伪随机（u64 溢出回绕）。"""
    s = np.uint64(seed & 0xFFFFFFFFFFFFFFFF)
    q = (bx.astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)) \
        ^ (bz.astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F)) \
        ^ (s + np.uint64(salt & 0xFFFFFFFFFFFFFFFF))
    q = q ^ (q >> np.uint64(33))
    q = q * np.uint64(0xFF51AFD7ED558CCD)
    q = q ^ (q >> np.uint64(33))
    return (q & np.uint64(0xFFFFFF)).astype(np.float32) / float(0x1000000)


def _up4(a: np.ndarray) -> np.ndarray:
    """(nh, nw[, ...]) -> (nh*4, nw*4[, ...])（前两维逐 4 重复）。"""
    return np.repeat(np.repeat(a, CELL, axis=0), CELL, axis=1)


def _expand_patch(rc: np.ndarray, bh: int, bw: int) -> np.ndarray:
    """噪声格随机场 (nh+2, nw+2) -> 方块级 (bh,bw) 双线性平滑场。

    输入场的索引 = 全局噪声格 - (块原点格) + 1（外圈 1 格 pad），
    由调用方保证；方块 b 落在噪声格 b//4 内、格间位置 (b%4)/4，
    按格整数边界双线性插值，产生 4~8 方块尺度的平滑斑块，供山地
    草/石混合、沙丘明暗、水面波纹使用。纯整数格映射，跨块无缝。
    """
    nh, nw = rc.shape[0] - 2, rc.shape[1] - 2
    zi = np.arange(bh, dtype=np.int64)
    xi = np.arange(bw, dtype=np.int64)
    z0 = zi // CELL
    x0 = xi // CELL
    tz = (zi % CELL).astype(np.float32) / CELL
    tx = (xi % CELL).astype(np.float32) / CELL
    zc = np.clip(z0 + 1, 0, nh + 1)
    xc = np.clip(x0 + 1, 0, nw + 1)
    top = rc[z0][:, x0] * (1 - tx)[None, :] + rc[z0][:, xc] * tx[None, :]
    bot = rc[zc][:, x0] * (1 - tx)[None, :] + rc[zc][:, xc] * tx[None, :]
    return top * (1 - tz)[:, None] + bot * tz[:, None]


# ---------------------------------------------------------------------------
# 主体渲染
# ---------------------------------------------------------------------------


# depth 参数（np6[4]*10000）的物理映射界限（确定性，与视野内容无关）：
# ny=16 时 depth ≈ off 样条值 - 0.019；实测真实种子：海面 0 上下
# （水下全负），河谷/海底极值约 -2500~-2600。水色取 -depth/2400：
# 近岸亮 → 深海暗；河流/冻河改为固定浅亮段；恶地谷底→高原顶条带。
_WATER_SPAN = 2400.0           # 水面（-depth 0→2400）亮→暗映射跨度
_BAD_BASE = -500.0
_BAD_SPAN = 7000.0            # 恶地谷底→高原顶的条带映射跨度


def _norm_fixed(dq: np.ndarray, base: float, span: float,
                invert: bool = False) -> np.ndarray:
    """depth 量化值 -> [0,1] 固定物理映射（确定性，不依赖整图内容）。

    invert=False：depth 越大值越大；invert=True：depth 越大值越小。
    """
    u = (dq - base) / span
    if invert:
        u = 1.0 - u
    return np.clip(u, 0.0, 1.0).astype(np.float32)


def _grass_tint(tq: np.ndarray, hq: np.ndarray) -> np.ndarray:
    """温度/湿度量化值（*10000）-> 草色 tint (...,3) float32。"""
    t = np.clip(tq / 10000.0 * 0.5 + 0.5, 0.0, 1.0).astype(np.float32)
    h = np.clip(hq / 10000.0 * 0.5 + 0.5, 0.0, 1.0).astype(np.float32)
    top = _GRASS_TL * (1 - h[..., None]) + _GRASS_TR * h[..., None]
    bot = _GRASS_BL * (1 - h[..., None]) + _GRASS_BR * h[..., None]
    return top * (1 - t[..., None]) + bot * t[..., None]


def _cell_base(biomes: np.ndarray, temp: np.ndarray, humid: np.ndarray,
               water_u: np.ndarray | None,
               bad_u: np.ndarray | None) -> tuple[np.ndarray, dict]:
    """噪声格级基色层：(nh,nw) 分类/气候 -> (nh,nw,3) float32 + 状态。

    与方块级渲染共用基色规则（群系分类/草色 tint/固定色覆盖/
    水深渐变/恶地色带/洞穴群系自绘）；状态字典带分类掩码与中间量，
    供方块级遮罩与 cell 级快速渲染（render_cell_rgb）复用。
    """
    nh, nw = biomes.shape
    bid = np.clip(biomes, 0, 255)
    cat = _CAT[bid]
    gml = _GRASS_MULT[bid]

    gt = _grass_tint(temp, humid)
    base = gt * gml

    is_water = cat == _CAT_WATER
    is_frozen = is_water & _one_hot(_FROZEN_WATER_IDS)[bid]
    is_deep = is_water & _one_hot(_DEEP_WATER_IDS)[bid]
    liquid = is_water & ~is_frozen
    if liquid.any() and water_u is not None:
        # 海洋：-depth 0→1（近岸亮→深海暗）；深海群系再加一档；
        # 河流固定浅亮段（河床深但水深浅，不用同一映射）
        wu = np.clip(water_u + np.where(is_deep, 0.25, 0.0), 0.0, 1.0)
        wu = np.where((bid == 7) | (bid == 44), 0.12 + 0.18 * water_u, wu)
        w_rgb = (_WATER_SHALLOW * (1 - wu[..., None])
                 + _WATER_DEEP * wu[..., None])
        base[liquid] = (0.75 * w_rgb + 0.25 * _WATER_BASE)[liquid]
    if is_frozen.any():
        base[is_frozen] = _ICE_RGB

    is_snow = cat == _CAT_SNOW
    if is_snow.any():
        base[is_snow] = _SNOW_RGB
    is_sand = cat == _CAT_SAND
    if is_sand.any():
        base[is_sand] = _SAND_RGB
    is_stone = cat == _CAT_STONE
    if is_stone.any():
        base[is_stone] = _STONE_RGB
    is_bad = cat == _CAT_BADLAND
    bad_idx = np.zeros((nh, nw), dtype=np.int64)
    if is_bad.any() and bad_u is not None:
        nb = len(_TERRACOTTA)
        bad_idx = np.clip(np.round(bad_u * (nb - 1)).astype(np.int64),
                          0, nb - 1)
        base[is_bad] = _TERRACOTTA[bad_idx][is_bad]

    is_swamp = cat == _CAT_SWAMP
    if is_swamp.any():
        base[is_swamp] = np.where((bid == 184)[..., None],
                                  _MANGROVE_GRASS, _SWAMP_GRASS)[is_swamp]
    is_mush = cat == _CAT_MUSHROOM
    if is_mush.any():
        base[is_mush] = _MYCELIUM_RGB

    # 热带草原类：固定原版 savanna 草色 #BFB755，不随气候插值
    sav = _one_hot((35, 36, 163, 164))[bid]
    if sav.any():
        base[sav] = _GRASS_BL

    # 洞穴群系（cat 仍是默认 GRASS，不会触发兑底；自绘观感近旧版）
    base[bid == 174] = _CAVE_LUSH_RGB
    base[bid == 175] = _CAVE_DRIPSTONE
    base[bid == 183] = _CAVE_DEEPDARK

    is_grass = cat == _CAT_GRASS
    uncovered = ~(is_water | is_grass | is_snow | is_sand | is_stone
                  | is_bad | is_swamp | is_mush)
    if uncovered.any():
        base[uncovered] = _FALLBACK_CELL

    st = {
        "bid": bid, "cat": cat, "gt": gt, "gml": gml,
        "liquid": liquid, "is_frozen": is_frozen, "is_snow": is_snow,
        "is_sand": is_sand, "is_stone": is_stone, "is_grass": is_grass,
        "is_bad": is_bad, "bad_idx": bad_idx, "is_swamp": is_swamp,
        "is_mush": is_mush,
    }
    return base, st


def _render_chunk(biomes: np.ndarray, temp: np.ndarray, humid: np.ndarray,
                  water_u: np.ndarray | None, bad_u: np.ndarray | None,
                  seed: int, obx: int, obz: int) -> np.ndarray:
    """渲染噪声格行块 -> (nh*4, nw*4, 3) uint8。

    参数矩阵均为本块的 cell 级切片；water_u/bad_u 为整图归一化场的
    本块行切片（可为 None）。
    """
    nh, nw = biomes.shape
    bid = np.clip(biomes, 0, 255)

    # ---- cell 级基色（共用基色层，状态掩码供遮罩复用）----
    base, st = _cell_base(biomes, temp, humid, water_u, bad_u)
    gt, gml = st["gt"], st["gml"]
    liquid = st["liquid"]
    is_frozen = st["is_frozen"]
    is_snow = st["is_snow"]
    is_sand = st["is_sand"]
    is_stone = st["is_stone"]
    is_grass = st["is_grass"]
    is_bad = st["is_bad"]
    bad_idx = st["bad_idx"]
    is_swamp = st["is_swamp"]
    is_mush = st["is_mush"]

    # ---- 方块级随机场（全局方块坐标对齐，跨块无缝可复现）----
    # 注意 obx/obz 为方块坐标（调用方已按行块换算），不再乘 CELL
    bz_ax = ((np.arange(nh, dtype=np.int64) * CELL)[:, None]
             + obz
             + np.arange(CELL, dtype=np.int64)[None, :]).ravel()
    bx_ax = ((np.arange(nw, dtype=np.int64) * CELL)[:, None]
             + obx
             + np.arange(CELL, dtype=np.int64)[None, :]).ravel()
    BZ, BX = np.meshgrid(bz_ax, bx_ax, indexing="ij")
    n0 = _hash01(BX, BZ, seed, 0x11)            # 颗粒抖动
    n1 = _hash01(BX, BZ, seed, 0x22)            # 斑点/花
    n2 = _hash01(BX, BZ, seed, 0x33)            # 树冠/恶地抖动

    # 低频 patch 场：全局噪声格坐标哈希（+1 外圈 pad），双线性到方块级
    gz, gx = np.mgrid[0:nh + 2, 0:nw + 2]
    rc = _hash01(gx.astype(np.int64) + (obx >> 2) - 1,
                 gz.astype(np.int64) + (obz >> 2) - 1, seed, 0x44)
    patch = _expand_patch(rc, nh * CELL, nw * CELL)

    # ---- 方块级细节（在上采样基色上覆盖）----
    base4 = _up4(base)                          # (H,W,3)

    # 水波/沙丘明暗（低频 patch）
    bright = np.ones(patch.shape, dtype=np.float32)
    liq4 = _up4(liquid)
    sand4 = _up4(is_sand)
    bright[liq4] += (patch[liq4] - 0.5) * 0.10
    bright[sand4] += (patch[sand4] - 0.5) * 0.16
    base4 *= bright[..., None]

    # 泥土斑点（草地）
    grass4 = _up4(is_grass)
    dirt4 = grass4 & (n1 < _up4(_DIRT_DENS[bid]))
    base4[dirt4] = _DIRT_RGB

    # 树冠斑点（密度阈值 + 低频成簇）
    crown4 = grass4 & (n2 < _up4(_CANOPY_DENS[bid])) & (patch > 0.30)
    if crown4.any():
        crown_rgb = _up4(gt * (_CANOPY_MULT * _GRASS_MULT)[bid])
        abs4 = _up4(_CANOPY_ABS_M[bid])
        if abs4.any():
            crown_rgb = np.where(abs4[..., None],
                                 _up4(_CANOPY_ABS[bid]), crown_rgb)
        crown_rgb = crown_rgb * (0.88 + 0.24 * n1[..., None])
        base4[crown4] = crown_rgb[crown4]

    # 花色点缀（繁花森林/草甸，避开树冠）
    flower4 = (grass4 & _up4(_one_hot((132, 177))[bid])
               & (n1 > 0.965) & ~crown4)
    if flower4.any():
        nfc = len(_FLOWER_COLORS)
        fidx = (n2[flower4] * nfc).astype(np.int64) % nfc
        base4[flower4] = _FLOWER_COLORS[fidx]

    # 冰面裂纹
    crack4 = _up4(is_frozen) & (patch > 0.78) & (n1 > 0.5)
    base4[crack4] = _ICE_RGB * 0.86

    # 石面草/砾石 patch
    st4 = _up4(is_stone)
    gm4 = st4 & (_up4(_GRASS_PATCH[bid]) > patch)
    if gm4.any():
        base4[gm4] = _up4(gt * gml)[gm4]
    gv4 = st4 & (_up4(_GRAVEL_PATCH[bid]) > (1.0 - patch))
    base4[gv4] = _GRAVEL_RGB

    # 雪面：高峰裸岩碎点 / 冰刺蓝冰
    sn4 = _up4(is_snow)
    rock4 = sn4 & _up4(_one_hot((180, 181))[bid]) & (n1 < 0.12)
    base4[rock4] = _STONE_RGB * 0.9
    ice4 = sn4 & _up4(bid == 140) & (n1 > 0.94)
    base4[ice4] = _BLUE_ICE_RGB

    # 恶地条带方块级抖动 + 繁茂恶地顶部草 patch
    if is_bad.any():
        bad4 = _up4(is_bad)
        if bad_u is not None:
            bidx4 = np.clip(
                _up4(bad_idx)
                + np.round((n2 - 0.5) * 1.4).astype(np.int64),
                0, len(_TERRACOTTA) - 1)
            base4[bad4] = _TERRACOTTA[bidx4][bad4]
        bgm4 = bad4 & _up4(bid == 38) & (patch > 0.62)
        base4[bgm4] = _WOODED_BAD_TOP

    # 沼泽水洼
    sw4 = _up4(is_swamp)
    pud4 = sw4 & (patch < 0.22) & (n1 < 0.85)
    base4[pud4] = _SWAMP_WATER

    # 雪坡林地：雪底上的云杉冠斑（grove 178）
    crown_snow4 = sn4 & _up4(bid == 178) \
        & (n2 < _up4(_CANOPY_DENS[bid])) & (patch > 0.30)
    if crown_snow4.any():
        base4[crown_snow4] = (
            _SNOW_TAIGA_CROWN * (0.88 + 0.24 * n1[..., None]))[crown_snow4]

    # 洞穴群系方块级：溶洞苔藓 patch、深暗之域幽匿微光
    base4[_up4(bid == 174) & (patch > 0.55)] = _CAVE_MOSS
    dd4 = _up4(bid == 183)
    base4[dd4 & (n1 > 0.965)] = _SCULK_SPECK

    # 蘑菇岛菌丝斑点
    mu4 = _up4(is_mush)
    speck4 = mu4 & _up4(bid == 14) & (n1 > 0.95)
    base4[speck4] = _MYCELIUM_SPECK

    # 全体方块级颗粒扰动
    base4 *= (1 + (n0 - 0.5) * 0.08)[..., None]

    return np.clip(base4, 0, 255).astype(np.uint8)


def _norm_fields(biomes: np.ndarray,
                 depth: np.ndarray | None) -> tuple[np.ndarray | None,
                                                    np.ndarray | None]:
    """由 depth 矩阵计算水色/恶地归一化场（整图一次，分块复用）。

    depth 越大 = 地势越高：水面以下 depth 为负且越深越负，水色取
    -depth/2400（近岸 0 亮 → 深海 1 暗）；恶地取反（u→1 高原顶浅橙 / 
    u→0 谷底深棕）。
    """
    bid = np.clip(biomes, 0, 255)
    is_water_m = np.isin(bid, _WATER_IDS + _FROZEN_WATER_IDS)
    is_bad_m = np.isin(bid, _BADLAND_IDS)
    dq = depth.astype(np.float32) if depth is not None \
        else np.zeros(biomes.shape, np.float32)
    water_u = None
    if depth is not None and is_water_m.any():
        water_u = _norm_fixed(-dq, 0.0, _WATER_SPAN)
    bad_u = None
    if depth is not None and is_bad_m.any():
        bad_u = _norm_fixed(dq, _BAD_BASE, _BAD_SPAN, invert=True)
    return water_u, bad_u


def render_block_rgb(biomes: np.ndarray, temp: np.ndarray | None,
                     humid: np.ndarray | None, depth: np.ndarray | None,
                     seed: int = 0, origin_bx: int = 0,
                     origin_bz: int = 0,
                     on_progress=None) -> np.ndarray:
    """方块级渲染主入口（LOD 精细档，1 像素 = 1 方块）。

    Args:
        biomes/temp/humid/depth: (nh, nw) int 矩阵（噪声格分辨率）；
            temp/humid/depth 可为 None（此时退化为按群系 id 的简化配色）。
        seed: 世界种子（方块纹理哈希输入，保证跨次渲染可复现）。
        origin_bx/origin_bz: 区域左上角方块坐标（哈希输入）。
        on_progress: on_progress(done_rows, total_rows)（噪声格行）。

    Returns:
        (nh*4, nw*4, 3) uint8 RGB 矩阵，1 像素 = 1 方块。
    """
    nh, nw = biomes.shape
    tq = np.zeros((nh, nw), np.float32) if temp is None \
        else temp.astype(np.float32)
    hq = np.zeros((nh, nw), np.float32) if humid is None \
        else humid.astype(np.float32)

    water_u, bad_u = _norm_fields(biomes, depth)

    H, W = nh * CELL, nw * CELL
    out = np.empty((H, W, 3), dtype=np.uint8)
    total = nh
    # 控制内存峰值：单块约 2M 方块
    chunk = max(1, int(2_000_000 // max(1, W)))
    for rs in range(0, nh, chunk):
        re = min(nh, rs + chunk)
        out[rs * CELL:re * CELL] = _render_chunk(
            biomes[rs:re], tq[rs:re], hq[rs:re],
            None if water_u is None else water_u[rs:re],
            None if bad_u is None else bad_u[rs:re],
            seed, origin_bx, origin_bz + rs * CELL)
        if on_progress is not None:
            on_progress(re, total)
    return out


def render_cell_rgb(biomes: np.ndarray, temp: np.ndarray | None,
                    humid: np.ndarray | None,
                    depth: np.ndarray | None) -> np.ndarray:
    """cell 级快速渲染（LOD 快速档，1 像素 = 4x4 方块）。

    与方块级渲染共用基色规则（草色 tint/水深渐变/恶地色带/洞穴
    群系自绘），仅省去方块级颗粒/树冠/斑点遮罩与 4x 上采样，色彩
    基调一致；输出 (nh, nw, 3) uint8，展示端再放大到方块尺度。
    """
    nh, nw = biomes.shape
    tq = np.zeros((nh, nw), np.float32) if temp is None \
        else temp.astype(np.float32)
    hq = np.zeros((nh, nw), np.float32) if humid is None \
        else humid.astype(np.float32)
    water_u, bad_u = _norm_fields(biomes, depth)
    base, _ = _cell_base(biomes, tq, hq, water_u, bad_u)
    return np.clip(base, 0, 255).astype(np.uint8)
