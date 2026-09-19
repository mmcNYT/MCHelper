# -*- coding: utf-8 -*-
"""StructurePreviewer：按世界种子预测结构内部构造与箱子战利品。

数据流：
    世界种子 --structure_map--> 结构实例锚点
             --composition--> 模板/旋转/箱子世界坐标 + 各箱子 LootTableSeed
             --loot_engine---> 每个箱子开箱前的槽位物品列表

LootTableSeed 派生规则（考证自 xpple/cubiomes fork finders.c:
getStructurePieces / getStructureSaltConfig，mc >= 1.18，Xoroshiro128++）：
    1. population_seed = getPopulationSeed(world_seed, chest_chunk_x, chest_chunk_z)
       （世界种子 -> Xoroshiro 连抽两个 xNextLongJ 作 a/b，|1，
         (x*a + z*b) ^ world_seed，x/z 为区块世界坐标）
    2. state = population_seed + decorator_index + 10000 * generation_step
       （各结构的 (step, index) 见 SALT_CONFIGS，沉船在沙滩上有额外
         absNextInt(3) 消耗）
    3. 按箱子顺序在该流中依次 nextLong 取 LootTableSeed（同区块多箱
       按放置顺序；隔区块的箱子从各自区块流取）。

各结构具体的 RNG 消耗序列直接照抄 finders.c 的 getStructurePieces
switch 分支，逐行见本模块各 compose_* 函数。
"""
from __future__ import annotations

import os

_M64 = (1 << 64) - 1

# ---------------------------------------------------------------------------
# Xoroshiro128++ 基础（rng.h 语义，注意 xNextLongJ 的 Java 包装）
# ---------------------------------------------------------------------------

_XL = 0x9E3779B97F4A7C15
_XH = 0x6A09E667F3BCC909
_MUL_A = 0xBF58476D1CE4E5B9
_MUL_B = 0x94D049BB133111EB


def _rotl(v: int, k: int) -> int:
    return ((v << k) | (v >> (64 - k))) & _M64


def _mix_stafford13(v: int) -> int:
    v = (v ^ (v >> 30)) * _MUL_A & _M64
    v = (v ^ (v >> 27)) * _MUL_B & _M64
    return v ^ (v >> 31)


def x_set_seed(value: int) -> tuple[int, int]:
    """rng.h xSetSeed：种子 -> (lo, hi)。

    注意顺序：h = (value ^ XH) + XL 必须用未混合的 l（与
    Utils/SeedReverser/biome_noise.py x_set_seed 同口径）。
    """
    value &= _M64
    l0 = value ^ _XH
    h0 = (l0 + _XL) & _M64
    l = _mix_stafford13(l0)
    h = _mix_stafford13(h0)
    return l & _M64, h & _M64


class XoroshiroJava:
    """Xoroshiro128++ 的 Java 包装（RandomSource.type = XOROSHIRO_J）。

    next_long  : xNextLongJ  —— 两次 xNextLong 的高 32 位拼接
    next_int   : xNextIntJ   —— xNextLong >> 33 的模除拒绝采样
    next_float : xNextFloat  —— xNextLong >> 40 * 2^-24
    next_double: xNextDoubleJ —— 高 26/27 位拼接
    skip_n     : 逐次推进状态（数量级小，无需矩阵跳转）
    """

    __slots__ = ("lo", "hi")

    def __init__(self, seed: int) -> None:
        self.lo, self.hi = x_set_seed(seed)

    def _next_raw(self) -> int:
        l = self.lo
        h = self.hi
        n = (_rotl((l + h) & _M64, 17) + l) & _M64
        h ^= l
        self.lo = (_rotl(l, 49) ^ h ^ ((h << 21) & _M64)) & _M64
        self.hi = _rotl(h, 28)
        return n

    # -- Java 包装 ----------------------------------------------------------

    def next_long(self) -> int:
        """xNextLongJ：两次 xNextLong 高 32 位，各按带符号 int32 拼接。

        与 structure_map._x_next_long_j 同口径（a/b 都符号扩展，
        Java nextLong 的 ((long)next(32)<<32) + (int)next(32) 语义）。
        """
        a = (self._next_raw() >> 32) & 0xFFFFFFFF
        b = (self._next_raw() >> 32) & 0xFFFFFFFF
        a_s = a - (1 << 32) if a >= (1 << 31) else a
        b_s = b - (1 << 32) if b >= (1 << 31) else b
        return ((a_s << 32) + b_s) & _M64

    def next_int(self, n: int) -> int:
        if n <= 0:
            raise ValueError("bound must be positive")
        m = n - 1
        if (m & n) == 0:  # 2 的幂
            x = n * (self._next_raw() >> 33)
            return (x & _M64) >> 31
        while True:
            bits = self._next_raw() >> 33
            val = bits % n
            # Java: while ((int)(bits - val + m) < 0) 用 int32 溢出语义
            if ((bits - val + m) & 0xFFFFFFFF) < 0x80000000:
                return val

    def next_int_between(self, min_v: int, max_v: int) -> int:
        """xNextIntBetween：xNextIntJ(max-min+1) + min。"""
        return self.next_int(max_v - min_v + 1) + min_v

    def next_float(self) -> float:
        return (self._next_raw() >> 40) * 5.960464477539063e-08

    def next_double(self) -> float:
        a = self._next_raw()
        b = self._next_raw()
        return (((a >> 38) << 27) + (b >> 37)) * 1.1102230246251565e-16

    def skip_n(self, count: int) -> None:
        for _ in range(count):
            self._next_raw()


# ---------------------------------------------------------------------------
# Java Random（java.util.Random / rng.h JAVA_RANDOM 语义）
# ---------------------------------------------------------------------------

# Java LCG 常量
_JR_MUL = 0x5DEECE66D
_JR_ADD = 0xB
_JR_MASK = (1 << 48) - 1
_MASK32 = 0xFFFFFFFF


class JavaRandom:
    """java.util.Random 精确复刻（rng.h JAVA_RANDOM 分支语义）。

    1.18+ 的箱子战利品求值用标准 Java LCG
    （C: RandomSource.create(lootSeed) = LegacyRandomSource；
      与 LootTableSeed 推导用的 Xoroshiro 分属两条 RNG 线，勿混用）。

    rng.h 对应关系：
        setSeed        : (value ^ 0x5DEECE66D) & (2^48-1)
        next(bits)     : 状态推进一次，返回高 bits 位（有符号 int32）
        nextLong       : ((int64)next(32) << 32) + next(32)（各按符号拼接）
        nextInt(n)     : 2 幂走无符号乘特判，否则拒绝采样
                         （判定位用 uint32 截断 + int32 符号检查）
        nextFloat      : next(24) / 2^24
        nextDouble     : ((int64)next(26) << 27) + next(27)) / 2^53
        skipNextN      : 矩阵快速幂跳进（小数量逐次推进等价）
    """

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        # rng.h setSeed: (value ^ 0x5DEECE66D) & (2^48-1)
        self._state = ((seed & _M64) ^ _JR_MUL) & _JR_MASK

    def _next(self, bits: int) -> int:
        """rng.h next(bits)：推进一次状态，返回高 bits 位。

        C: return (int)((int64_t)state >> (48 - bits))：
        状态 < 2^48 恒为正，右移得 0~2^bits-1；仅 bits=32 时
        (int) 强转可能为负（值域超出 int31 上界），bits<=31 恒非负。
        """
        self._state = (self._state * _JR_MUL + _JR_ADD) & _JR_MASK
        v = self._state >> (48 - bits)
        if bits == 32 and v >= 0x80000000:
            return v - 0x100000000
        return v

    def next_long(self) -> int:
        """rng.h nextLong：((uint64)(int64)next(32) << 32) + next(32)。

        高 32 位按 int32 符号扩展，低 32 位按 int32 无符号相加
        （与 Java ((long)next(32)<<32) + (int)next(32) 语义一致）。
        """
        hi = self._next(32)
        lo = self._next(32)
        return ((hi << 32) + lo) & _M64

    def next_int(self, n: int) -> int:
        """rng.h nextInt(n)：2 幂特判 + 拒绝采样（与 Java 完全一致）。"""
        if n <= 0:
            raise ValueError("bound must be positive")
        m = n - 1
        if (m & n) == 0:
            # 2 幂：x = n * next(31) < 2^61 恒非负，(int64)x >> 31 即 x >> 31
            return (n * self._next(31)) >> 31
        while True:
            bits = self._next(31)
            val = bits % n
            # C: while ((int32_t)((uint32_t)bits - val + m) < 0) 重抽
            if ((bits - val + m) & _MASK32) < 0x80000000:
                return val

    def next_int_between(self, min_v: int, max_v: int) -> int:
        """rng.h nextIntBetween：nextInt(max-min+1) + min。"""
        return self.next_int(max_v - min_v + 1) + min_v

    def next_float(self) -> float:
        """rng.h nextFloat：next(24) / 2^24（消耗一次 next(24)）。"""
        return self._next(24) / float(1 << 24)

    def next_double(self) -> float:
        """rng.h nextDouble：((int64)next(26)<<27 + next(27)) / 2^53。"""
        hi = self._next(26) & _M64
        lo = self._next(27) & _M64
        x = (hi << 27) + lo
        return (x - (1 << 53) if x >= (1 << 53) else x) / float(1 << 53)

    def skip_n(self, count: int) -> None:
        """推进 count 次 next(1) 等价的状态步进（小数量直接迭代）。"""
        for _ in range(count):
            self._state = (self._state * _JR_MUL + _JR_ADD) & _JR_MASK


# ---------------------------------------------------------------------------
# population seed（finders.c getPopulationSeed，mc >= 1.18 分支）
# ---------------------------------------------------------------------------

def get_population_seed(world_seed: int, block_x: int, block_z: int) -> int:
    """以方块坐标为参数（finders.c 各调用处传 minBlockX/minBlockZ
    或 chestPosX/chestPosZ，即箱子所在结构的区块角/箱子方块坐标）。"""
    xr = XoroshiroJava(world_seed)
    a = xr.next_long() | 1
    b = xr.next_long() | 1
    return ((block_x * a + block_z * b) & _M64) ^ (world_seed & _M64)


# ---------------------------------------------------------------------------
# 各结构的 (generation_step, decorator_index)（finders.c getStructureSaltConfig）
# 首列 = generation_step，次列 = decorator_index
#
# salt 按版本分档：版本线收敛后仅 _1194 档（1.19.4+ 语义覆盖
# 1.21/1.21.11/26.2 三键）。
# ---------------------------------------------------------------------------

_SALT_1194: dict[str, tuple[int, int]] = {
    "igloo": (4, 3),
    "shipwreck": (4, 17),
    "shipwreck_beached": (4, 18),
    "desert_pyramid": (4, 1),
    "jungle_pyramid": (4, 4),
    "pillager_outpost": (4, 9),
    "ruined_portal": (4, 10),
    "ruined_portal_desert": (4, 11),
    "ruined_portal_jungle": (4, 12),
    "ruined_portal_swamp": (4, 16),
    "ruined_portal_mountain": (4, 13),
    "ruined_portal_ocean": (4, 15),
    "buried_treasure": (3, 0),
    # 下界结构（cl_salts_1_21_5.txt 交叉验证：4 0 bastion / 7 1 fortress）
    "nether_fortress": (7, 1),     # Fortress（finders.c getStructureSaltConfig L413-417）
    "bastion_remnant": (4, 0),     # Bastion（L502-505）
    "end_city": (4, 2),            # EndCity（xp finders.c ss_end_city_1194{4,2}）
    # 试炼密室（cl_salts_1_21_5.txt L6：3 4 minecraft:trial_chambers；
    # underground_structures step=3, decorator=4；1.21+ 新增，仅 _1194 档）
    "trial_chambers": (3, 4),
    # 远古城市（cl_salts_1_21_5.txt L33：7 0 minecraft:ancient_city；
    # underground_decoration step=7、decorator=0；1.19+ 新增，
    # 仅 _1194 档）
    "ancient_city": (7, 0),
    # 要塞（xp finders.c L360/L493：ss_stronghold_1194={4,19}）
    "stronghold": (4, 19),
    # 林地府邸（cl_salts_1_21_5.txt L12：4 5 minecraft:mansion；
    # SURFACE_STRUCTURES 内注册序 5）。
    "mansion": (4, 5),
    # 村庄（1.19+ 拆五结构键，共用 placement；decorator index =
    # SURFACE_STRUCTURES 内注册序（1.21.11 jar step 字段逐键核对，
    # trail_ruins 实为 underground_structures 不占 surface 序）：
    # village_desert/plains/savanna/snowy/taiga = 21..25。
    "village_desert": (4, 21),
    "village_plains": (4, 22),
    "village_savanna": (4, 23),
    "village_snowy": (4, 24),
    "village_taiga": (4, 25),
    # 海底废墟（cl_salts_1_21_5.txt L14-15：4 7 minecraft:ocean_ruin_cold、
    # 4 8 minecraft:ocean_ruin_warm；与 jar 字母序推算、xp fork
    # 六处已知值三方交叉验证一致）。
    "ocean_ruin_cold": (4, 7),
    "ocean_ruin_warm": (4, 8),
}

# 版本线收敛为 26.2 / 1.21.11 / 1.21（全部落 _SALT_1194 档）；
# 原 _SALT_118（1.18-1.19.1）档随旧版本下线删除。
SALT_CONFIGS = _SALT_1194


def salt_configs_for_version(version_key: str) -> dict[str, tuple[int, int]]:
    """版本键 -> salt 表（版本线收敛后唯一档 = _SALT_1194；保留
    version_key 参数维持既有调用签名）。"""
    return _SALT_1194


def loot_seed_for_chest(
    world_seed: int,
    chest_x: int,
    chest_z: int,
    salt_key: str,
    skips: int = 0,
    version_key: str = "1.21",
) -> int:
    """求单个箱子的 LootTableSeed（mc >= 1.18）。

    chest_x/chest_z 为方块坐标（内部 &~15 取区块角，兼容 igloo 传
    minBlock 与 outpost 传 chestPosX 两种 C 调用口径）；
    skips: 同一流中该箱子前面消耗的 nextLong 次数（含已取走的
    其它箱子种子；beached 沉船的 nextInt(3) 前置消耗不含在内）。
    version_key 兼容既有调用签名（收敛后仅 _SALT_1194 单档；
    _SALT_1194 内未收录的表如 mansion 的旧版注释一并随旧档下线）。
    """
    step, decorator = salt_configs_for_version(version_key)[salt_key]
    pop = get_population_seed(world_seed, chest_x & ~15, chest_z & ~15)
    rng = XoroshiroJava(pop + decorator + 10000 * step)
    for _ in range(skips):
        rng.next_long()
    return rng.next_long()


def signed_seed(value: int) -> int:
    """无符号 64 位 -> Java long（有符号），用于 UI 显示/输入。"""
    value &= _M64
    return value - (1 << 64) if value >= (1 << 63) else value
