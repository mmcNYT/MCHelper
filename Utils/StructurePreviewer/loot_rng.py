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
    """rng.h xSetSeed：种子 -> (lo, hi)。"""
    value &= _M64
    l = _mix_stafford13(value ^ _XH)
    h = l + _XL
    l = _mix_stafford13(l)
    h = _mix_stafford13(h)
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
        """xNextLongJ：两次 xNextLong 高 32 位拼接。

        C: int32_t b —— 低 32 位按带符号 int32 参与加法（Java
        nextLong 语义 ((long)next(32)<<32) + next(32) 的符号扩展）。
        """
        a = (self._next_raw() >> 32) & 0xFFFFFFFF
        b = (self._next_raw() >> 32) & 0xFFFFFFFF
        b_s = b - (1 << 32) if b >= (1 << 31) else b
        return ((a << 32) + b_s) & _M64

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
# salt 按版本分档（< _1192 / < _1194 / >= MC_26_3 各档不同）。
# 项目版本线（1.19 = MC_1_19_4，1.20 = MC_1_20_6，1.21）全部落在
# _1194 档，因此默认表取 _1194 值；"1.18" 用 _118 档单独覆盖。
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
}

# 1.18-1.19.1 档（finders.c L316-324 等：_118 后缀）
_SALT_118: dict[str, tuple[int, int]] = {
    "igloo": (4, 4),
    "shipwreck": (4, 5),
    "shipwreck_beached": (4, 6),
    "desert_pyramid": (4, 1),
    "jungle_pyramid": (4, 2),
    "pillager_outpost": (4, 0),
    "ruined_portal": (4, 18),
    "ruined_portal_desert": (4, 19),
    "ruined_portal_jungle": (4, 20),
    "ruined_portal_swamp": (4, 21),
    "ruined_portal_mountain": (4, 22),
    "ruined_portal_ocean": (4, 23),
    "buried_treasure": (3, 2),
}

SALT_CONFIGS = _SALT_1194


def salt_configs_for_version(version_key: str) -> dict[str, tuple[int, int]]:
    """版本键 -> 该版本的 salt 表（当前支持 1.18 与 1.19.4+ 两档）。"""
    if str(version_key).lower() in ("1.18", "1.18.1", "1.18.2"):
        return _SALT_118
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
    version_key 用于选择 salt 分档（1.18 / 1.19.4+）。
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
