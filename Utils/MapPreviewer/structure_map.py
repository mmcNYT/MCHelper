# -*- coding: utf-8 -*-
"""MapPreviewer 结构定位与群系校验。

位置计算复用 Utils/SeedReverser 的 structure_math（getStructurePos 精确
复刻，已与 SeedCrackerX 对拍）；群系校验按 cubiomes finders.c
isViableStructurePos 的 1.18+ 分支逐行移植（本文件内注释标注源码行号）。

关键语义（与游戏一致的必要约定）：
    - 1.18+ 所有结构校验都走 1:4 噪声格直接采样（scale=0/4，无 Voronoi
      抖动），因此可用 biome_noise.BiomeSampler 直接采样。
    - getVariant 的采样点公式 (chunkX*32 + 2*sv.x + sv.sx-1) / 2 >> 2 中的
      "/ 2" 是 C 整数除法（向零截断），对负数与算术移位不同，须用 _c_div。
    - chunkGenerateRnd 需要 Java Random.nextLong（两次 next(32) 拼接，注意
      第二次的符号扩展），见 _java_next_long。
    - 前哨站的 setAttemptSeed 异或值 < 2^21，不影响 48 位以上状态，故
      用 48 位结构种与用 64 位世界种子等价（structure_math 已实现）。

仅支持 1.18~1.21 主世界结构（用户明确指示的工具范围）。

下界/末地扩展（2026-09 功能①）：
    - 下界要塞/堡垒遗迹/末地城为区域制，散布公式与主世界一致
      （getFeaturePos / getLargeStructurePos 复用 structure_math），
      但概率门/群系校验按 finders.c isViableStructurePos 的
      DIM_NETHER / DIM_END 分支逐行移植：
        · 1.18+ 要塞 = 同区域堡垒不生成（bastion 概率门失败或群系
          白名单外）；堡垒概率门在 getStructurePos 层用 chunkGenerateRnd
          （48 位结构种）→ nextInt(5) >= 2（finders.c L281-289）
        · 堡垒采样点需 getVariant 尺寸表（4 种 start，L2079-2094）
        · 末地城 = getLargeStructurePos + pos² ≥ 1008²（L247-249）
          + chunk 级群系（scale=16，end_midlands/highlands）
    - 群系采样用 nether_end_sampler（NetherSampler 逐点/EndSampler
      chunk 级），BiomeSampler 仅支持主世界不可混用。

扩展结构（本文件内移植，非 structure_math 区域制）：
    - 埋藏的宝藏/沙漠水井/废弃矿井：getStructurePos 特殊分支与
      getMineshafts 的逐行移植（含上游 rng.h 的 xNextLongJ/xNextFloat/
      xNextIntJ 语义，本地 cubiomes 裁剪未含 rng.h）。
    - 要塞：StrongholdIter 环形序列（initFirstStronghold/nextStronghold）
      + locateBiome 1.18+ 分支。窗口批量采样用 native sample_map（与
      rng 流无关，可安全解耦）；1.18/1.19（btree19 = 1.19.2 线）的
      locateBiome 消耗共享 rnds 流，必须按序全扫 128 窗，不可跳窗。
"""

from __future__ import annotations

import math

import numpy as np

from Utils.SeedReverser import mc_random
from Utils.SeedReverser import structure_params
from Utils.SeedReverser.structure_math import get_structure_pos
from Utils.SeedReverser.biome_noise import (
    BiomeSampler, Xoroshiro, climate_to_biome_dat)
from Utils.MapPreviewer.nether_end_sampler import (
    BASALT_DELTAS,
    CRIMSON_FOREST,
    END_BARRENS,
    END_HIGHLANDS,
    END_MIDLANDS,
    EndSampler,
    NETHER_WASTES,
    NetherSampler,
    SOUL_SAND_VALLEY,
    WARPED_FOREST,
)

_MASK48 = (1 << 48) - 1
_MASK64 = (1 << 64) - 1

# ---------------------------------------------------------------------------
# 群系 id 常量（cubiomes biomes.h，与 biome_colors.py 同源）
# ---------------------------------------------------------------------------

OCEAN = 0
PLAINS = 1
DESERT = 2
TAIGA = 5
SWAMP = 6
RIVER = 7
FROZEN_OCEAN = 10
FROZEN_RIVER = 11
SNOWY_PLAINS = 12            # snowy_tundra
MUSHROOM_FIELDS = 14
MUSHROOM_FIELD_SHORE = 15
BEACH = 16
DESERT_HILLS = 17
JUNGLE = 21
JUNGLE_HILLS = 22
DEEP_OCEAN = 24
STONE_SHORE = 25             # stony_shore
SNOWY_BEACH = 26
DARK_FOREST = 29
SNOWY_TAIGA = 30
OLD_GROWTH_PINE_TAIGA = 32
OLD_GROWTH_SPRUCE_TAIGA = 33
SAVANNA = 35
WARM_OCEAN = 44
LUKEWARM_OCEAN = 45
COLD_OCEAN = 46
DEEP_WARM_OCEAN = 47
DEEP_LUKEWARM_OCEAN = 48
DEEP_COLD_OCEAN = 49
DEEP_FROZEN_OCEAN = 50
BAMBOO_JUNGLE = 168
BAMBOO_JUNGLE_HILLS = 169
MANGROVE_SWAMP = 184
MEADOW = 177
GROVE = 178
SNOWY_SLOPES = 179
JAGGED_PEAKS = 180
FROZEN_PEAKS = 181
STONY_PEAKS = 182
DEEP_DARK = 183
OLD_GROWTH_BIRCH_FOREST = 155
DARK_FOREST_HILLS = 157
CHERRY_GROVE = 185
PALE_GARDEN = 186
# 26.2 硫磺洞穴：MCHelper 封闭系统自定 id（biome_noise.BIOME_ID 同源）
SULFUR_CAVES = 187

# biomes.c isOceanic / isDeepOcean
_OCEANIC = {OCEAN, FROZEN_OCEAN, WARM_OCEAN, LUKEWARM_OCEAN, COLD_OCEAN,
            DEEP_OCEAN, DEEP_WARM_OCEAN, DEEP_LUKEWARM_OCEAN,
            DEEP_COLD_OCEAN, DEEP_FROZEN_OCEAN}
_DEEP_OCEANIC = {DEEP_OCEAN, DEEP_WARM_OCEAN, DEEP_LUKEWARM_OCEAN,
                 DEEP_COLD_OCEAN, DEEP_FROZEN_OCEAN}

# finders.c g_monument_biomes1（areBiomesViable 的 12 种海洋/河流）
_MONUMENT_BIOMES = {OCEAN, DEEP_OCEAN, RIVER, FROZEN_RIVER, FROZEN_OCEAN,
                    DEEP_FROZEN_OCEAN, COLD_OCEAN, DEEP_COLD_OCEAN,
                    LUKEWARM_OCEAN, DEEP_LUKEWARM_OCEAN, WARM_OCEAN,
                    DEEP_WARM_OCEAN}

# isViableFeatureBiome 1.18+ 白名单（finders.c L1182-1234）
_FEATURE_WHITELIST = {
    "desert_pyramid": {DESERT, DESERT_HILLS},
    "jungle_temple": {JUNGLE, JUNGLE_HILLS, BAMBOO_JUNGLE, BAMBOO_JUNGLE_HILLS},
    "swamp_hut": {SWAMP},
    "igloo": {SNOWY_PLAINS, SNOWY_TAIGA, SNOWY_SLOPES},
    "ocean_ruin": _OCEANIC,
    "shipwreck": _OCEANIC | {BEACH, SNOWY_BEACH},
    "ancient_city": {DEEP_DARK},
    "trail_ruins": {TAIGA, SNOWY_TAIGA, OLD_GROWTH_PINE_TAIGA,
                    OLD_GROWTH_SPRUCE_TAIGA, OLD_GROWTH_BIRCH_FOREST, JUNGLE},
    "mansion": {DARK_FOREST, DARK_FOREST_HILLS},
    "buried_treasure": {BEACH, SNOWY_BEACH},   # finders.c L1236-1238
}

# finders.c L1252-1269 Outpost 1.18+ 白名单（12 种）
_OUTPOST_BIOMES = {DESERT, PLAINS, SAVANNA, SNOWY_PLAINS, TAIGA, MEADOW,
                   FROZEN_PEAKS, JAGGED_PEAKS, STONY_PEAKS, SNOWY_SLOPES,
                   GROVE, CHERRY_GROVE}

# MapPreviewer 的版本→结构映射（覆盖全部 21 种，按图上易找程度排序；
# 不同于 SeedReverser 的观测用版本表——前哨站/废弃传送门虽不可逆推
# 但可正向标注；下界要塞/堡垒遗迹/末地城仅对应维度展示）
_PREVIEW_ORDER = ("village", "pillager_outpost", "desert_pyramid",
                  "jungle_temple", "swamp_hut", "igloo", "shipwreck",
                  "ocean_ruin", "monument", "mansion", "ancient_city",
                  "trail_ruins", "trial_chambers", "ruined_portal",
                  "stronghold", "buried_treasure", "mineshaft",
                  "desert_well",
                  # 下界/末地扩展结构（1.16+ / 1.9+；仅对应维度可选）
                  "nether_fortress", "bastion_remnant", "end_city")
_VERSION_NUM = {"1.21": 121, "1.21.11": 1211, "26.2": 262}

# finders.c isViableFeatureBiome 下界/末地白名单（L1287-1299）
_NETHER_FORTRESS_BIOMES = {NETHER_WASTES, SOUL_SAND_VALLEY, WARPED_FOREST,
                           CRIMSON_FOREST, BASALT_DELTAS}
_NETHER_BASTION_BIOMES = {NETHER_WASTES, SOUL_SAND_VALLEY, WARPED_FOREST,
                          CRIMSON_FOREST}
_END_CITY_BIOMES = {END_MIDLANDS, END_HIGHLANDS}

# 堡垒遗迹 getVariant 尺寸表（finders.c L2088-2094，未旋转 sx, sz；
# start = 0:air_base(46x46) / 1:hoglin_stable(30x48) / 2:treasure(38x38)
# / 3:bridge(16x32) 四种起点变体；rotation 1.18+ 无符号平移语义）
_BASTION_TABLES = ((46, 46), (30, 48), (38, 38), (16, 32))


def available_structures(version_key: str,
                         dimension: str = "overworld") -> tuple[str, ...]:
    """返回某版本、某维度可标注的结构键元组（含 min_ver 过滤）。

    Args:
        version_key: 版本键。
        dimension: "overworld"/"nether"/"end"（主世界缺省兼容旧调用）。
    """
    vnum = _VERSION_NUM.get(version_key, 121)
    return tuple(
        k for k in _PREVIEW_ORDER
        if structure_params.STRUCT_PARAMS[k][4] <= vnum
        and structure_params.STRUCT_DIMENSION.get(k, "overworld") == dimension)


# ---------------------------------------------------------------------------
# C / Java 语义辅助
# ---------------------------------------------------------------------------

def _c_div(v: int, d: int) -> int:
    """C 整数除法（向零截断）。Python // 是向负无穷，负数商不同。"""
    q = abs(v) // abs(d)
    return q if (v >= 0) == (d >= 0) else -q


def _java_next_long(state: int) -> tuple[int, int]:
    """Java Random.nextLong（两次 next(32) 拼接，第二次须符号扩展）。

    Java: ((long)next(32) << 32) + next(32)。位级上 (int)hi << 32 的符号
    扩展等价于 hi_raw << 32；lo 须带符号参与加法（负 lo 使高 32 位 -1）。
    """
    s = mc_random.next_state(state)
    hi = s >> 16                    # next(32) raw
    s = mc_random.next_state(s)
    lo = s >> 16                    # next(32) raw
    lo_s = lo - (1 << 32) if lo >= (1 << 31) else lo
    return ((hi << 32) + lo_s) & _MASK64, s


def chunk_generate_rnd(world_seed: int, chunk_x: int, chunk_z: int) -> int:
    """cubiomes chunkGenerateRnd（finders.h L390）。

    返回 48 位 LCG 状态（内部已 setSeed(rnd, rnd)），可直接供 nextInt 用。
    world_seed 须为 64 位（乘法/异或依赖完整宽度）。
    """
    ws = world_seed & _MASK64
    state = mc_random.set_seed(ws)
    a, state = _java_next_long(state)
    b, state = _java_next_long(state)
    cx = chunk_x & _MASK64
    cz = chunk_z & _MASK64
    rnd = ((a * cx) ^ (b * cz) ^ ws) & _MASK64
    return mc_random.set_seed(rnd)


# ---------------------------------------------------------------------------
# getVariant 移植（仅取影响采样点的字段）
# ---------------------------------------------------------------------------

# 村庄变体尺寸表（未旋转 sx, sz；start/abandoned 不影响采样点，略）
_VILLAGE_TABLES = {
    # t 阈值: (sx, sz)
    PLAINS: ((50, 9, 9), (100, 10, 10), (150, 8, 15), (200, 11, 11),
             (201, 9, 9), (202, 10, 10), (203, 8, 15), (204, 11, 11)),
    DESERT: ((98, 17, 9), (196, 12, 12), (245, 15, 15),
             (247, 17, 9), (249, 12, 12), (250, 15, 15)),
    SAVANNA: ((100, 14, 12), (150, 11, 11), (300, 9, 11), (450, 9, 9),
              (452, 14, 12), (453, 11, 11), (456, 9, 11), (459, 9, 9)),
    TAIGA: ((49, 22, 18), (98, 9, 9), (99, 22, 18), (100, 9, 9)),
    SNOWY_PLAINS: ((100, 12, 8), (150, 11, 9), (300, 7, 7),
                   (302, 12, 8), (303, 11, 9), (306, 7, 7)),
}
_VILLAGE_TABLE_MOD = {PLAINS: 204, DESERT: 250, SAVANNA: 459,
                      TAIGA: 100, SNOWY_PLAINS: 306}


def _village_variant(world_seed: int, chunk_x: int, chunk_z: int,
                     biome_id: int):
    """getVariant(Village)（finders.c L2003-2117）→ (vx, vz, vsx, vsz)。

    biome_id 为变体类型（meadow 按 plains 处理）。不适用返回 None。
    """
    if biome_id not in _VILLAGE_TABLE_MOD:
        return None
    rng = chunk_generate_rnd(world_seed, chunk_x, chunk_z)
    rotation, rng = mc_random.next_int(rng, 4)
    t, _ = mc_random.next_int(rng, _VILLAGE_TABLE_MOD[biome_id])
    sx = sz = 0
    for hi, w, d in _VILLAGE_TABLES[biome_id]:
        if t < hi:
            sx, sz = w, d
            break
    else:                                   # UNREACHABLE（防御）
        return None
    if rotation == 0:
        return 0, 0, sx, sz
    if rotation == 1:
        return 1 - sz, 0, sz, sx
    if rotation == 2:
        return 1 - sx, 1 - sz, sx, sz
    return 0, 1 - sx, sz, sx


def _variant_sample_point(chunk_x: int, chunk_z: int, vx: int, vz: int,
                          vsx: int, vsz: int) -> tuple[int, int]:
    """getVariant 采样点公式（finders.c L1622-1623 / L1780-1781）。

    sampleX = (chunkX*32 + 2*sv.x + sv.sx-1) / 2 >> 2 —— "/ 2" 为 C 截断
    除法，">> 2" 为算术移位（floor）。返回噪声格 (x, z)。
    """
    sx_c = _c_div(chunk_x * 32 + 2 * vx + vsx - 1, 2)
    sz_c = _c_div(chunk_z * 32 + 2 * vz + vsz - 1, 2)
    return sx_c >> 2, sz_c >> 2


def _bastion_variant(world_seed: int, chunk_x: int, chunk_z: int):
    """Bastion 的 getVariant（finders.c L2079-2106）→ (vx, vz, vsx, vsz)。

    rotation = nextInt(4)、start = nextInt(4)（1.16.1 交换，不适用）；
    尺寸表 4 种起点；1.18+ 旋转平移无符号修正（与 Village 同式）。
    """
    rng = chunk_generate_rnd(world_seed, chunk_x, chunk_z)
    rotation, rng = mc_random.next_int(rng, 4)
    start, _ = mc_random.next_int(rng, 4)
    sx, sz = _BASTION_TABLES[start]
    if rotation == 0:
        return 0, 0, sx, sz
    if rotation == 1:
        return 1 - sz, 0, sz, sx
    if rotation == 2:
        return 1 - sx, 1 - sz, sx, sz
    return 0, 1 - sx, sz, sx


def _bastion_probability(ws64: int, bx: int, bz: int) -> bool:
    """Bastion 概率门（finders.c getStructurePos L281-289，mc >= 1.18）。

    seed = chunkGenerateRnd(seed, pos.x>>4, pos.z>>4) → nextInt(5) >= 2。
    chunkGenerateRnd 以完整 64 位世界种子参与乘法/异或；getStructurePos
    调用方传 48 位截断值，结果上 setSeed(rnd, rnd) 后 state 相同
    （乘法在 64 位域，48 位截断与 64 位种子高 16 位仅影响高位丢弃——
    保守起见这里用完整 64 位世界种子，与 cubiomes 主流程一致）。
    """
    rnd = chunk_generate_rnd(ws64, bx >> 4, bz >> 4)
    val, _ = mc_random.next_int(rnd, 5)
    return val >= 2


def _jigsaw_variant(struct_key: str, world_seed: int, bx: int, bz: int):
    """Ancient City / Trial Chambers 的 getVariant（L2119-2141 / L2315-2328）。

    Args:
        bx/bz: 结构锚点方块坐标（getFeaturePos 返回值，恒为 16 的倍数）。
            Ancient_City 的旋转平移依赖其符号（finders.c L2125-2128 的
            -(x>0)/(x<0) 修入），Village 1.18+/Trial Chambers 则不依赖。

    返回 (vx, vz, vsx, vsz, y)（y 为方块层，供 sampleY = y >> 2）。
    """
    rng = chunk_generate_rnd(world_seed, bx >> 4, bz >> 4)
    if struct_key == "ancient_city":
        rotation, rng = mc_random.next_int(rng, 4)
        # start = 1 + nextInt(3)（city_center_1..3）不影响包围盒
        mc_random.next_int(rng, 3)
        # finders.c L2123-2129：用传入方块坐标的严格符号修入
        #   case 0: x = -(x>0);    z = -(z>0)
        #   case 1: x = +(x<0)-sz; z = -(z>0)      (sz=41)
        #   case 2: x = +(x<0)-sx; z = +(z<0)-sz   (sx=18, sz=41)
        #   case 3: x = -(x>0);    z = +(z<0)-sx   (sx=18)
        xp = 1 if bx > 0 else 0
        xn = 1 if bx < 0 else 0
        zp = 1 if bz > 0 else 0
        zn = 1 if bz < 0 else 0
        if rotation == 0:
            x2, z2, vsx, vsz = -xp, -zp, 18, 41
        elif rotation == 1:
            x2, z2, vsx, vsz = xn - 41, -zp, 41, 18
        elif rotation == 2:
            x2, z2, vsx, vsz = xn - 18, zn - 41, 18, 41
        else:
            x2, z2, vsx, vsz = -xp, zn - 18, 41, 18
        # city_anchor (13, *, 20) 位移（finders.c L2131-2138，sx=13/sz=20）
        if rotation == 0:
            vx, vz = x2 - 13, z2 - 20
        elif rotation == 1:
            vx, vz = x2 + 20, z2 - 13
        elif rotation == 2:
            vx, vz = x2 + 13, z2 + 20
        else:
            vx, vz = x2 - 20, z2 + 13
        y = -27
    else:   # trial_chambers
        y, rng = mc_random.next_int(rng, 21)
        y -= 40                              # r->y = nextInt(21) - 40
        rotation, rng = mc_random.next_int(rng, 4)
        mc_random.next_int(rng, 2)           # start（不影响包围盒）
        vsx, vsz = 19, 19
        if rotation == 0:
            vx, vz = 0, 0
        elif rotation == 1:
            vx, vz = 1 - vsz, 0
        elif rotation == 2:
            vx, vz = 1 - vsx, 1 - vsz
        else:
            vx, vz = 0, 1 - vsx
    return vx, vz, vsx, vsz, y


# ---------------------------------------------------------------------------
# 各结构的群系校验（isViableStructurePos 1.18+ 分支）
# ---------------------------------------------------------------------------

def _check_feature(struct_key: str, sampler: BiomeSampler, chunk_x: int,
                   chunk_z: int) -> tuple[bool, int]:
    """L_feature 单点校验（finders.c L1541-1558）。

    采样点 (chunkX*4+2, 319>>2, chunkZ*4+2)。
    """
    bid = sampler.biome_at(chunk_x * 4 + 2, 319 >> 2, chunk_z * 4 + 2)
    return bid in _FEATURE_WHITELIST[struct_key], bid


def _check_mansion(sampler: BiomeSampler, chunk_x: int,
                   chunk_z: int) -> tuple[bool, int]:
    """Mansion 1.18+（finders.c L1745-1756）：单点 (chunkX*16+7, 319>>2)。"""
    bid = sampler.biome_at((chunk_x * 16 + 7) >> 2, 319 >> 2,
                           (chunk_z * 16 + 7) >> 2)
    return bid in _FEATURE_WHITELIST["mansion"], bid


def _check_village(sampler: BiomeSampler, world_seed: int, chunk_x: int,
                   chunk_z: int) -> tuple[bool, int]:
    """Village 1.18+（finders.c L1613-1632）：5 变体逐一检查包围盒中心。"""
    last_bid = -1
    for vbiome in (PLAINS, DESERT, SAVANNA, TAIGA, SNOWY_PLAINS):
        var = _village_variant(world_seed, chunk_x, chunk_z, vbiome)
        if var is None:
            continue
        vx, vz, vsx, vsz = var
        nx, nz = _variant_sample_point(chunk_x, chunk_z, vx, vz, vsx, vsz)
        bid = sampler.biome_at(nx, 319 >> 2, nz)
        last_bid = bid
        if bid == vbiome or (bid == MEADOW and vbiome == PLAINS):
            return True, bid
    return False, last_bid


def _check_outpost(sampler: BiomeSampler, world_seed: int, chunk_x: int,
                   chunk_z: int, version_key: str) -> tuple[bool, int]:
    """Outpost 1.18+（finders.c L1634-1696）：概率 + 附近村庄 + 角落采样。"""
    # 1) setAttemptSeed + nextInt(5)==0（setAttemptSeed 异或值 < 2^21，
    #    与 48 位结构种语义等价）
    s = (world_seed ^ ((chunk_x >> 4) & _MASK64)
         ^ (((chunk_z >> 4) << 4) & _MASK64)) & _MASK64
    state = mc_random.next_state(mc_random.set_seed(s))   # next(31)
    val, _ = mc_random.next_int(state, 5)
    if val != 0:
        return False, -1

    # 2) 10 区块内有村庄锚点 → 1.16.1+ 直接不生成
    s48 = world_seed & _MASK48
    cx0, cx1 = chunk_x - 10, chunk_x + 10
    cz0, cz1 = chunk_z - 10, chunk_z + 10
    rx0, rx1 = cx0 // 34, cx1 // 34          # floordiv（区域 34 区块）
    rz0, rz1 = cz0 // 34, cz1 // 34
    for rz in range(rz0, rz1 + 1):
        for rx in range(rx0, rx1 + 1):
            bx, bz = get_structure_pos("village", s48, rx, rz, version_key)
            cx, cz = bx >> 4, bz >> 4
            if cx0 <= cx <= cx1 and cz0 <= cz <= cz1:
                return False, -1

    # 3) 角落采样（chunkGenerateRnd 选角，(chunkX*32±15)/2 >> 2）
    rng = chunk_generate_rnd(world_seed, chunk_x, chunk_z)
    corner, _ = mc_random.next_int(rng, 4)
    dx, dz = ((15, 15), (-15, 15), (-15, -15), (15, -15))[corner]
    nx = _c_div(chunk_x * 32 + dx, 2) >> 2
    nz = _c_div(chunk_z * 32 + dz, 2) >> 2
    bid = sampler.biome_at(nx, 319 >> 2, nz)
    return bid in _OUTPOST_BIOMES, bid


def _check_monument(sampler: BiomeSampler, chunk_x: int,
                    chunk_z: int) -> tuple[bool, int]:
    """Monument 1.18+（finders.c L1699-1731）：中心深海 + 16x16 方格全海洋。"""
    # 中心深海单点（y = 36>>2 = 9，海底层）
    bid = sampler.biome_at((chunk_x * 16 + 8) >> 2, 36 >> 2,
                           (chunk_z * 16 + 8) >> 2)
    if bid not in _DEEP_OCEANIC:
        return False, bid

    # areBiomesViable(x=chunkX*16+8, y=63, z=chunkZ*16+8, rad=29,
    #                 g_monument_biomes1)：y = (63-29)>>2 = 8，
    #                 方格 (x±29)>>2 全量检查（L732-790，1.18+ 全格）
    x = chunk_x * 16 + 8
    z = chunk_z * 16 + 8
    x1, x2 = (x - 29) >> 2, (x + 29) >> 2
    z1, z2 = (z - 29) >> 2, (z + 29) >> 2
    # 先查四角（快速拒绝陆地/浅海区域）
    for cx, cz in ((x1, z1), (x2, z2), (x1, z2), (x2, z1)):
        if sampler.biome_at(cx, 8, cz) not in _MONUMENT_BIOMES:
            return False, -1
    # 全格（areBiomesViable 1.18+ 分支）
    for cx in range(x1, x2 + 1):
        for cz in range(z1, z2 + 1):
            if sampler.biome_at(cx, 8, cz) not in _MONUMENT_BIOMES:
                return False, -1
    return True, bid


def _check_jigsaw(struct_key: str, sampler: BiomeSampler, world_seed: int,
                  bx: int, bz: int) -> tuple[bool, int]:
    """Ancient City / Trial Chambers（finders.c L1770-1787，getVariant 采样点）。"""
    vx, vz, vsx, vsz, y = _jigsaw_variant(struct_key, world_seed, bx, bz)
    chunk_x = bx >> 4
    chunk_z = bz >> 4
    nx, nz = _variant_sample_point(chunk_x, chunk_z, vx, vz, vsx, vsz)
    bid = sampler.biome_at(nx, y >> 2, nz)
    if struct_key == "ancient_city":
        return bid == DEEP_DARK, bid
    # trial_chambers：非深暗之域的主世界群系（采样器只产主世界 id）
    return bid != DEEP_DARK, bid


# ---------------------------------------------------------------------------
# 扩展结构：Xoroshiro Java 包装与人口种子（上游 rng.h 逐行移植）
# ---------------------------------------------------------------------------

def _x_next_long_j(xr: Xoroshiro) -> int:
    """rng.h xNextLongJ：两次取 nextLong 高 32 位，按 Java int 符号拼接。"""
    a = xr.next_long() >> 32
    b = xr.next_long() >> 32
    if a >= 1 << 31:
        a -= 1 << 32
    if b >= 1 << 31:
        b -= 1 << 32
    return ((a << 32) + b) & _MASK64


def _x_next_float(xr: Xoroshiro) -> float:
    """rng.h xNextFloat：nextLong 高 24 位 * 2^-24（消耗整个 64 位）。"""
    return (xr.next_long() >> 40) * 5.9604645E-8


def _x_next_int_pow2(xr: Xoroshiro, n_pow2: int) -> int:
    """rng.h xNextIntJ 的 2 幂特判分支（本工具只用 16）。

    x = n * (nextLong >> 33)；返回 (int)((int64_t)x >> 31)。
    """
    x = (n_pow2 * (xr.next_long() >> 33)) & _MASK64
    if x >= 1 << 63:                  # 转回带符号 int64
        x -= 1 << 64
    return x >> 31                    # Python 算术移位与 int64 >> 一致


def _c_round(v: float) -> int:
    """C round()：半值远离零（Python round 是银行家舍入，负半值不同）。"""
    return int(math.floor(v + 0.5)) if v >= 0 else -int(math.floor(-v + 0.5))


def get_population_seed(world_seed: int, x: int, z: int) -> int:
    """finders.c getPopulationSeed 1.18+ 分支（L27-55）。

    a/b 为 Java nextLong（带符号拼接）且各 | 1；结果 (x*a + z*b) ^ ws。
    """
    ws = world_seed & _MASK64
    xr = Xoroshiro.from_seed(ws)
    a = _x_next_long_j(xr) | 1
    b = _x_next_long_j(xr) | 1
    return ((x * a + z * b) ^ ws) & _MASK64


def _check_desert_well(sampler: BiomeSampler, bx: int, bz: int) -> tuple[bool, int]:
    """Desert_Well 1.18+（finders.c L1560-1577 + isViableFeatureBiome L1243）。"""
    bid = sampler.biome_at(bx >> 2, 319 >> 2, bz >> 2)
    return bid == DESERT, bid


def _stronghold_valid_sets() -> tuple[set[int], set[int]]:
    """isStrongholdBiome（finders.c L798-832）预计算。

    1.18+ 采样器只产主世界 id（不存在/非主世界返回 0 时校验即拒），
    因此只需枚举「允许集合」：非海洋非河流滩非深暗非红树。
    biomeExists 1.18 分支（biomes.c L5-82）确认 1.18 采样器可输出的
    主世界 id 全集无 184 以外的版本差（1.19.2+ 才有红树/深暗，
    由采样器输出端自然处理，此处集合保持全量）。
    """
    excluded = (_OCEANIC
                | {RIVER, FROZEN_RIVER, BEACH, SNOWY_BEACH,
                   STONE_SHORE, MANGROVE_SWAMP, DEEP_DARK, PALE_GARDEN,
                   SULFUR_CAVES})
    return excluded, excluded        # (validB 集合, validM 集合)：同语义


class _StrongholdWinSampler:
    """要塞 locateBiome 窗口批量采样器（性能层）。

    **必须走 Python 带链逐点采样**（MC-241546）：xp locateBiome 的
    climateToBiome 共享 dat 链（上一格搜索终点作下一格起点），候选
    分歧时窗口边缘个别格的群系 id 与无链采样不同——要塞窗口位于
    海洋边缘、候选格极少，水库采样会放大这种差异，导致枚举锚点
    与真实游戏漂移（对拍 probe_sh 已复现）。native sample_map 无
    链语义，此处禁用；与 rng 流无关的顺序消耗仍在 StrongholdIter。
    """

    def __init__(self, seed: int, version_key: str):
        self._py = BiomeSampler(seed, version_key)
        self._btree = self._py._btree
        self._dat = 0

    def window_ids(self, cx: int, cz: int, radius: int) -> np.ndarray:
        """返回 (2r+1, 2r+1) int32 群系矩阵，覆盖噪声格
        [cx-r, cx+r] x [cz-r, cz+r]（噪声格 y=0）。

        扫描顺序 = xp locateBiome（j=z 外层、i=x 内层）；每个窗口
        开始重置链（xp 每次调用 locateBiome 都是新窗口）。"""
        r = radius
        n = 2 * r + 1
        ids = np.empty((n, n), dtype=np.int32)
        cp = self._py.climate_point_xz
        bt = self._btree
        c2b = climate_to_biome_dat
        self._dat = 0
        for j in range(n):
            row = ids[j]
            zz = cz - r + j
            for i in range(n):
                idx, self._dat = c2b(cp(cx - r + i, zz), bt, self._dat)
                row[i] = (int(bt.nodes[idx]) >> 48) & 0xFF
        return ids


class StrongholdIter:
    """cubiomes StrongholdIter 的 1.18~1.21 移植（finders.c L834-936）。

    版本分支：1.19.3+ 环位**不做群系采样**，pos = approx 对齐 16 格
    （finders.c nextStronghold 的 NULL 快路径；Java 1.19.3 起群系
    校验移至 piece 生成期）；≤1.19.2 线 locateBiome 全窗口扫描、
    共享 rnds 流。版本线收敛（26.2/1.21.11/1.21）后恒走 1.19.3+
    快路径（_shared_rng_stream 恒 False，保留判断供旧键兼容）。
    """

    def __init__(self, world_seed: int, version_key: str,
                 win_sampler: "_StrongholdWinSampler | None" = None):
        s48 = world_seed & _MASK48
        self._win = win_sampler
        self._excluded, _ = _stronghold_valid_sets()
        self._shared_rng_stream = version_key in ("1.18", "1.19")
        # initFirstStronghold（L840-849，1.9+ 分支）
        rnds = mc_random.set_seed(s48)
        d1, rnds = mc_random.next_double(rnds)
        self.angle = 2.0 * math.pi * d1
        d2, rnds = mc_random.next_double(rnds)
        dist = 128.0 + (d2 - 0.5) * 80.0
        self.nextapprox = (_c_round(math.cos(self.angle) * dist) * 16 + 8,
                           _c_round(math.sin(self.angle) * dist) * 16 + 8)
        self.pos: tuple[int, int] | None = None
        self.index = 0
        self.ringnum = 0
        self.ringmax = 3
        self.ringidx = 0
        self.dist = dist
        self._rnds = rnds

    def _locate_biome(self, ax: int, az: int) -> tuple[int, int]:
        """locateBiome 1.18+（finders.c L650-675，共享 rnds 流语义）。

        仅 1.18/1.19（≤1.19.2 共享流线）使用；1.19.3+ 环位不采样
        （见 next()）。窗口内 climateToBiome 走 dat 共享链
        （MC-241546，与 xp sampleBiomeNoise(&dat) 一致）。
        """
        out_x, out_z = ax, az
        x, z, r = ax >> 2, az >> 2, 112 >> 2
        ids = self._win.window_ids(x, z, r)
        rng = self._rnds
        found = 0
        excluded = self._excluded
        for j in range(2 * r + 1):
            row = ids[j]
            bj = z - r + j
            for i in range(2 * r + 1):
                if int(row[i]) in excluded:
                    continue
                if found == 0:
                    out_x, out_z = (x + i - r) * 4, bj * 4
                    found = 1
                    continue
                val, rng = mc_random.next_int(rng, found + 1)
                if val == 0:
                    out_x, out_z = (x + i - r) * 4, bj * 4
                found += 1
        self._rnds = rng
        return out_x, out_z

    def next(self) -> bool:
        """nextStronghold 主流程（finders.c L868-936）：定位 → 修正 →
        推进近似坐标。返回 False 表示 128 个已全部产生。

        版本分支（与 xp 对齐）：
        - 1.19.3+（>1.19.2 线）：环位**不做群系采样**——消耗一次
          nextLong（等价原 lbr 播种）后 pos = approx 对齐 ((x&~15)+4,
          (z&~15)+4)（Java 1.19.3 起要塞定位改纯 RNG 环 + 群系校验
          移到 piece 生成期，cubiomes 走 NULL 快路径）；
        - 1.18/1.19（≤1.19.2）：locateBiome 全窗口扫描（共享 rnds 流）。
        """
        if self.index >= 128:
            return False
        if self._shared_rng_stream:
            px, pz = self._locate_biome(*self.nextapprox)
        else:
            _nl, self._rnds = _java_next_long(self._rnds)
            px, pz = self.nextapprox
        self.pos = ((px & ~15) + 4, (pz & ~15) + 4)
        self.ringidx += 1
        self.angle += 2.0 * math.pi / self.ringmax
        if self.ringidx == self.ringmax:
            self.ringnum += 1
            self.ringidx = 0
            self.ringmax = self.ringmax + 2 * self.ringmax // (self.ringnum + 1)
            if self.ringmax > 128 - self.index:
                self.ringmax = 128 - self.index
            d, self._rnds = mc_random.next_double(self._rnds)
            self.angle += d * math.pi * 2.0
        # 1.9+：dist = 128 + 192*ringnum + (nd-0.5)*80
        d, self._rnds = mc_random.next_double(self._rnds)
        self.dist = 128.0 + 192.0 * self.ringnum + (d - 0.5) * 80.0
        self.nextapprox = (
            _c_round(math.cos(self.angle) * self.dist) * 16 + 8,
            _c_round(math.sin(self.angle) * self.dist) * 16 + 8)
        self.index += 1
        return True


def _check_nether(struct_key: str, ws: int, bx: int, bz: int,
                  sampler) -> tuple[bool, int]:
    """下界要塞/堡垒遗迹 1.18+ 判定（finders.c L1449-1486）。

    - 要塞（L1457-1468）：1.18+ 生成在「堡垒不生成处」——
      堡垒 getStructurePos 概率门失败 → 要塞直接 viable；
      否则 viable = NOT 堡垒 viable（变体采样点群系在白名单内）。
    - 堡垒（L1471-1486）：概率门（getStructurePos 层，L281-289）+
      getVariant 尺寸表采样点 + 群系白名单（不含玄武岩三角洲）。
    sampleY = 33 >> 2（1.19.2+），但下界群系不随 Y 变化，采样器忽略 y。

    Args:
        ws: 完整 64 位世界种子（chunkGenerateRnd 乘法域）。
        bx/bz: 结构锚点方块坐标。
        sampler: NetherSampler（该种子）。

    Returns:
        (viable, biome_id)：bid 为判定/展示采样点群系（-1 未采样）。
    """
    cx, cz = bx >> 4, bz >> 4
    if struct_key == "nether_fortress":
        if _bastion_probability(ws, bx, bz):
            vx, vz, vsx, vsz = _bastion_variant(ws, cx, cz)
            nx, nz = _variant_sample_point(cx, cz, vx, vz, vsx, vsz)
            bid = sampler.biome_at(nx, nz)
            if bid in _NETHER_BASTION_BIOMES:
                return False, bid
        # 堡垒不生成 → 要塞在任意下界群系 viable；展示群系取 chunk 中心
        return True, sampler.biome_at(cx * 4 + 2, cz * 4 + 2)
    # bastion_remnant
    if not _bastion_probability(ws, bx, bz):
        return False, -1
    vx, vz, vsx, vsz = _bastion_variant(ws, cx, cz)
    nx, nz = _variant_sample_point(cx, cz, vx, vz, vsx, vsz)
    bid = sampler.biome_at(nx, nz)
    return bid in _NETHER_BASTION_BIOMES, bid


def _check_end(struct_key: str, bx: int, bz: int, sampler) -> tuple[bool, int]:
    """末地城判定（finders.c getStructurePos L247-249 + isViableStructurePos
    L1488-1505）。

    - 距离门：pos² >= 1008²（位置层拒绝，pos 为方块坐标）。
    - 群系：chunk 级 getBiomeAt(scale=16, chunkX, 0, chunkZ) ∈
      {end_midlands, end_highlands}（末地图按 chunk 走 EndSampler）。
    """
    if bx * bx + bz * bz < 1008 * 1008:
        return False, -1
    bid = sampler.biome_at_chunk(bx >> 4, bz >> 4)
    return bid in _END_CITY_BIOMES, bid


def check_structure_at(struct_key: str, world_seed: int, bx: int, bz: int,
                       version_key: str, sampler: BiomeSampler,
                       nether_end=None) -> tuple[bool, int]:
    """判断结构在 (bx, bz) 锚点是否真实生成（群系校验）。

    Args:
        struct_key: 结构键。
        world_seed: 64 位世界种子（有符号或无符号均可，内部按位处理）。
        bx/bz: 结构锚点方块坐标（get_structure_pos 的返回值）。
        version_key: 版本键。
        sampler: 该种子的 BiomeSampler（主世界结构用，调用方复用）。
        nether_end: 下界/末地结构所需的 NetherSampler / EndSampler
            （None 时按维度惰性创建；主世界结构忽略此参数）。

    Returns:
        (viable, biome_id)：bid 为判定采样点群系（-1 表示未采样到）。
    """
    ws = world_seed & _MASK64
    chunk_x = bx >> 4
    chunk_z = bz >> 4
    dim = structure_params.STRUCT_DIMENSION.get(struct_key, "overworld")
    if dim == "nether":
        return _check_nether(struct_key, ws, bx, bz,
                             nether_end if nether_end is not None
                             else NetherSampler(ws))
    if dim == "end":
        return _check_end(struct_key, bx, bz,
                          nether_end if nether_end is not None
                          else EndSampler(ws))
    if struct_key == "village":
        return _check_village(sampler, ws, chunk_x, chunk_z)
    if struct_key == "pillager_outpost":
        return _check_outpost(sampler, ws, chunk_x, chunk_z, version_key)
    if struct_key == "ruined_portal":
        # cubiomes finders.c L1208-1210：Ruined_Portal 的 biome 判定
        # 恒为 true（可生成于任意群系，含地下），无额外 RNG 概率门
        return True, -1
    if struct_key == "monument":
        return _check_monument(sampler, chunk_x, chunk_z)
    if struct_key == "mansion":
        return _check_mansion(sampler, chunk_x, chunk_z)
    if struct_key in ("ancient_city", "trial_chambers"):
        return _check_jigsaw(struct_key, sampler, ws, bx, bz)
    if struct_key == "desert_well":
        return _check_desert_well(sampler, bx, bz)
    if struct_key in ("stronghold", "mineshaft"):
        # getStructurePos 已含概率门/环形序列；isViableStructurePos 对
        # Mineshaft 恒 viable（L1789-1790）；Stronghold 走专用迭代器
        # （不在通用区域循环中，不会到达这里）
        return True, -1
    return _check_feature(struct_key, sampler, chunk_x, chunk_z)


# ---------------------------------------------------------------------------
# 扩展结构专用枚举（getStructurePos 特殊分支的非区域制/逐 chunk 实现）
# ---------------------------------------------------------------------------

def _enum_treasure_well(
    key: str, ws: int,
    viewport: tuple[int, int, int, int],
    sampler: BiomeSampler,
    results: list[dict],
    cancel=None,
) -> None:
    """埋藏的宝藏/沙漠水井：逐 chunk 枚举（region=1，每 chunk 至多一个）。

    Treasure（finders.c L256-261）：seed' = cx*341873128712
    + cz*132897987541 + ws + salt → setSeed → nextFloat < 0.01；
    锚点 (cx*16+9, cz*16+9)；群系校验 L_feature (cx*4+2, 79, cz*4+2)
    ∈ {beach, snowy_beach}（L1532 走 L_feature）。

    Desert_Well（L293-321）：populationSeed = getPopulationSeed(ws,
    cx*16, cz*16)；xSetSeed(pop + 40002) → xNextFloat < 0.001
    → 锦点 += xNextIntJ(16)；群系校验锚点 (x>>2, 79, z>>2) == desert。
    """
    min_bx, min_bz, max_bx, max_bz = viewport
    margin = 96
    cx0 = (min_bx - margin) >> 4
    cx1 = (max_bx + margin + 15) >> 4
    cz0 = (min_bz - margin) >> 4
    cz1 = (max_bz + margin + 15) >> 4
    salt = structure_params.STRUCT_PARAMS[key][0]
    for cz in range(cz0, cz1 + 1):
        if cancel is not None and cancel():
            return
        for cx in range(cx0, cx1 + 1):
            if key == "buried_treasure":
                v = (cx * 341873128712 + cz * 132897987541
                     + ws + salt) & _MASK64
                st = mc_random.set_seed(v)
                f, _ = mc_random.next_float(st)
                if f >= 0.01:
                    continue
                bx, bz = cx * 16 + 9, cz * 16 + 9
            else:
                pop = get_population_seed(ws, cx * 16, cz * 16)
                xr = Xoroshiro.from_seed(pop + salt)
                if _x_next_float(xr) >= 0.001:
                    continue
                bx = cx * 16 + _x_next_int_pow2(xr, 16)
                bz = cz * 16 + _x_next_int_pow2(xr, 16)
            if not (min_bx - margin <= bx <= max_bx + margin
                    and min_bz - margin <= bz <= max_bz + margin):
                continue
            if key == "buried_treasure":
                viable, bid = _check_feature(key, sampler, cx, cz)
            else:
                viable, bid = _check_desert_well(sampler, bx, bz)
            if not viable:
                continue
            results.append({
                "struct": key,
                "name": structure_params.STRUCT_NAMES.get(key, key),
                "x": bx,
                "z": bz,
                "cx": bx >> 4,
                "cz": bz >> 4,
                "biome": bid,
            })


def _enum_mineshafts(
    ws: int,
    viewport: tuple[int, int, int, int],
    results: list[dict],
    cancel=None,
) -> None:
    """废弃矿井：getMineshafts（finders.c L332-386）1.13+ 分支。

    a/b = setSeed(ws) 后两次 Java nextLong；逐 chunk
    setSeed(aix ^ cz*b)（aix = cx*a ^ ws）→ nextDouble < 0.004 →
    锦点 (cx*16, cz*16)。无群系校验。
    """
    min_bx, min_bz, max_bx, max_bz = viewport
    margin = 96
    cx0 = (min_bx - margin) >> 4
    cx1 = (max_bx + margin + 15) >> 4
    cz0 = (min_bz - margin) >> 4
    cz1 = (max_bz + margin + 15) >> 4
    state = mc_random.set_seed(ws)
    a, state = _java_next_long(state)
    b, state = _java_next_long(state)
    for cx in range(cx0, cx1 + 1):
        if cancel is not None and cancel():
            return
        aix = ((cx * a) ^ ws) & _MASK64
        for cz in range(cz0, cz1 + 1):
            st = mc_random.set_seed((aix ^ (cz * b)) & _MASK64)
            pd, _ = mc_random.next_double(st)
            if pd >= 0.004:
                continue
            bx, bz = cx * 16, cz * 16
            results.append({
                "struct": "mineshaft",
                "name": structure_params.STRUCT_NAMES.get("mineshaft",
                                                          "mineshaft"),
                "x": bx,
                "z": bz,
                "cx": bx >> 4,
                "cz": bz >> 4,
                "biome": -1,
            })


def _enum_strongholds(
    ws: int,
    version_key: str,
    viewport: tuple[int, int, int, int],
    results: list[dict],
    on_progress=None,
    cancel=None,
) -> None:
    """要塞：StrongholdIter 全序扫 128 窗（共享流版本不可跳窗）。

    1.19.3+ 环位纯 RNG（每步仅一次 nextLong），pos=approx 对齐；
    共享流版本（1.18/1.19）的 locateBiome 水库采样消耗依赖于窗口
    内容，跳窗会改变后续流状态，必须全序。dist 单调递增做提前终止。
    """
    min_bx, min_bz, max_bx, max_bz = viewport
    margin = 96
    # 窗口采样器仅共享流版本（1.18/1.19）需要；1.19.3+ 环位不采样
    shared = version_key in ("1.18", "1.19")
    win = _StrongholdWinSampler(ws, version_key) if shared else None
    it = StrongholdIter(ws, version_key, win)
    # 终止条件：当前近似点超过视野外扩范围（dist 单调递增，
    # 近似点距原点随环号递增，一超过即可停）
    reach = max(
        max(abs(min_bx), abs(max_bx)),
        max(abs(min_bz), abs(max_bz)),
    ) + margin + 112 + 64
    for _ in range(128):
        if cancel is not None and cancel():
            return
        ax, az = it.nextapprox
        if max(abs(ax), abs(az)) > reach and it.index > 0:
            break
        it.next()
        px, pz = it.pos
        if not (min_bx - margin <= px <= max_bx + margin
                and min_bz - margin <= pz <= max_bz + margin):
            continue
        results.append({
            "struct": "stronghold",
            "name": structure_params.STRUCT_NAMES.get("stronghold",
                                                      "stronghold"),
            "x": px,
            "z": pz,
            "cx": px >> 4,
            "cz": pz >> 4,
            "biome": -1,
        })
    if on_progress is not None:
        on_progress(1, 1, "stronghold")


def enumerate_structures(
    seed: int,
    version_key: str,
    viewport: tuple[int, int, int, int],
    struct_keys=None,
    on_progress=None,
    cancel=None,
    dimension: str = "overworld",
) -> list[dict]:
    """枚举视野内真实生成的结构。

    Args:
        seed: 世界种子（有符号 int64）。
        version_key: 版本键。
        viewport: (min_bx, min_bz, max_bz …) 即 (min_bx, min_bz, max_bx,
                  max_bz) 方块坐标（含端点）。
        struct_keys: 要枚举的结构键列表（None = 该版本+维度全部可标注
            结构）。
        on_progress: on_progress(done, total, stage) 回调（结构粒度）。
        cancel: cancel() -> bool。
        dimension: "overworld"/"nether"/"end"。非主世界时只处理该维度的
            结构（下界要塞/堡垒遗迹/末地城），群系校验走
            nether_end_sampler（主世界 BiomeSampler 不创建，省开销）。

    Returns:
        list[dict]: {struct, name, x, z, cx, cz, biome}（x/z 为结构锚点
        方块坐标，cx/cz 为区块坐标，biome 为判定采样点群系 id）。
    """
    ws = seed & _MASK64
    if struct_keys is None:
        struct_keys = available_structures(version_key, dimension)
    # 维度防御：混入其他维度结构键时按维度过滤（UI 侧不会发生）
    if dimension != "overworld":
        struct_keys = tuple(
            k for k in struct_keys
            if structure_params.STRUCT_DIMENSION.get(k, "overworld")
            == dimension)
    min_bx, min_bz, max_bx, max_bz = viewport

    # 主世界用 BiomeSampler；下界/末地走专用采样器（惰性创建复用）
    if dimension == "nether":
        dim_sampler = NetherSampler(ws)
    elif dimension == "end":
        dim_sampler = EndSampler(ws)
    else:
        dim_sampler = None
    sampler = BiomeSampler(seed, version_key) if dim_sampler is None else None

    # 主世界区域制结构 + treasure/desert_well 的 sampler 池共用；
    # 要塞/矿井走专用枚举
    results = []
    region_keys = []
    for idx, key in enumerate(struct_keys):
        if cancel is not None and cancel():
            break
        done = idx + 1
        if key == "stronghold":
            _enum_strongholds(ws, version_key, viewport, results,
                              on_progress=on_progress, cancel=cancel)
        elif key == "mineshaft":
            _enum_mineshafts(ws, viewport, results, cancel=cancel)
            if on_progress is not None:
                on_progress(done, len(struct_keys), key)
        elif key in ("buried_treasure", "desert_well"):
            _enum_treasure_well(key, ws, viewport, sampler, results,
                                cancel=cancel)
            if on_progress is not None:
                on_progress(done, len(struct_keys), key)
        else:
            region_keys.append(key)

    total = len(region_keys)
    base_done = len(struct_keys) - total
    for idx, key in enumerate(region_keys):
        if cancel is not None and cancel():
            break
        params = structure_params.get_params(key, version_key)
        rs = params["region_size"] * 16            # 区域跨度（方块）
        salt = params["salt"]
        # 覆盖视野的区域范围（锚点总在本区域内，多取一圈容错边缘）
        reg_x0 = (min_bx // rs) - 1
        reg_x1 = (max_bx // rs) + 1
        reg_z0 = (min_bz // rs) - 1
        reg_z1 = (max_bz // rs) + 1
        s48 = ws & _MASK48
        for reg_z in range(reg_z0, reg_z1 + 1):
            if cancel is not None and cancel():
                break
            for reg_x in range(reg_x0, reg_x1 + 1):
                if cancel is not None and cancel():
                    break
                bx, bz = get_structure_pos(key, s48, reg_x, reg_z,
                                           version_key)
                # 锚点在视野内（外扩 96 方块容错大型结构包围盒）
                margin = 96
                if not (min_bx - margin <= bx <= max_bx + margin
                        and min_bz - margin <= bz <= max_bz + margin):
                    continue
                viable, bid = check_structure_at(key, ws, bx, bz,
                                                 version_key, sampler,
                                                 nether_end=dim_sampler)
                if viable:
                    results.append({
                        "struct": key,
                        "name": structure_params.STRUCT_NAMES.get(key, key),
                        "x": bx,
                        "z": bz,
                        "cx": bx >> 4,
                        "cz": bz >> 4,
                        "biome": bid,
                    })
        if on_progress is not None:
            on_progress(base_done + idx + 1, len(struct_keys), key)
    return results
