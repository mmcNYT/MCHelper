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
"""

from __future__ import annotations

from Utils.SeedReverser import mc_random
from Utils.SeedReverser import structure_params
from Utils.SeedReverser.structure_math import get_structure_pos
from Utils.SeedReverser.biome_noise import BiomeSampler

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
BEACH = 16
DESERT_HILLS = 17
JUNGLE = 21
JUNGLE_HILLS = 22
DEEP_OCEAN = 24
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
}

# finders.c L1252-1269 Outpost 1.18+ 白名单（12 种）
_OUTPOST_BIOMES = {DESERT, PLAINS, SAVANNA, SNOWY_PLAINS, TAIGA, MEADOW,
                   FROZEN_PEAKS, JAGGED_PEAKS, STONY_PEAKS, SNOWY_SLOPES,
                   GROVE, CHERRY_GROVE}

# MapPreviewer 的版本→结构映射（覆盖全部 13 种，按图上易找程度排序；
# 不同于 SeedReverser 的观测用版本表——前哨站虽不可逆推但可正向标注）
_PREVIEW_ORDER = ("village", "pillager_outpost", "desert_pyramid",
                  "jungle_temple", "swamp_hut", "igloo", "shipwreck",
                  "ocean_ruin", "monument", "mansion", "ancient_city",
                  "trail_ruins", "trial_chambers")
_VERSION_NUM = {"1.18": 118, "1.19": 119, "1.20": 120, "1.21": 121}


def available_structures(version_key: str) -> tuple[str, ...]:
    """返回某版本可标注的结构键元组（含 min_ver 过滤）。"""
    vnum = _VERSION_NUM.get(version_key, 121)
    return tuple(k for k in _PREVIEW_ORDER
                 if structure_params.STRUCT_PARAMS[k][4] <= vnum)


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


def check_structure_at(struct_key: str, world_seed: int, bx: int, bz: int,
                       version_key: str, sampler: BiomeSampler) -> tuple[bool, int]:
    """判断结构在 (bx, bz) 锚点是否真实生成（群系校验）。

    Args:
        struct_key: 结构键。
        world_seed: 64 位世界种子（有符号或无符号均可，内部按位处理）。
        bx/bz: 结构锚点方块坐标（get_structure_pos 的返回值）。
        version_key: 版本键。
        sampler: 该种子的 BiomeSampler（调用方复用）。

    Returns:
        (viable, biome_id)：bid 为判定采样点群系（-1 表示未采样到）。
    """
    ws = world_seed & _MASK64
    chunk_x = bx >> 4
    chunk_z = bz >> 4
    if struct_key == "village":
        return _check_village(sampler, ws, chunk_x, chunk_z)
    if struct_key == "pillager_outpost":
        return _check_outpost(sampler, ws, chunk_x, chunk_z, version_key)
    if struct_key == "monument":
        return _check_monument(sampler, chunk_x, chunk_z)
    if struct_key == "mansion":
        return _check_mansion(sampler, chunk_x, chunk_z)
    if struct_key in ("ancient_city", "trial_chambers"):
        return _check_jigsaw(struct_key, sampler, ws, bx, bz)
    return _check_feature(struct_key, sampler, chunk_x, chunk_z)


# ---------------------------------------------------------------------------
# 区域枚举主入口
# ---------------------------------------------------------------------------

def enumerate_structures(
    seed: int,
    version_key: str,
    viewport: tuple[int, int, int, int],
    struct_keys=None,
    on_progress=None,
    cancel=None,
) -> list[dict]:
    """枚举视野内真实生成的结构。

    Args:
        seed: 世界种子（有符号 int64）。
        version_key: 版本键。
        viewport: (min_bx, min_bz, max_bz …) 即 (min_bx, min_bz, max_bx,
                  max_bz) 方块坐标（含端点）。
        struct_keys: 要枚举的结构键列表（None = 该版本全部可标注结构）。
        on_progress: on_progress(done, total, stage) 回调（结构粒度）。
        cancel: cancel() -> bool。

    Returns:
        list[dict]: {struct, name, x, z, cx, cz, biome}（x/z 为结构锚点
        方块坐标，cx/cz 为区块坐标，biome 为判定采样点群系 id）。
    """
    ws = seed & _MASK64
    if struct_keys is None:
        struct_keys = available_structures(version_key)
    min_bx, min_bz, max_bx, max_bz = viewport

    sampler = BiomeSampler(seed, version_key)

    results = []
    total = len(struct_keys)
    for idx, key in enumerate(struct_keys):
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
                                                 version_key, sampler)
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
            on_progress(idx + 1, total, key)
    return results
