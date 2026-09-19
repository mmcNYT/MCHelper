# -*- coding: utf-8 -*-
"""Python 复刻 Minecraft 1.21 jigsaw 拼装随机机制（基于 1.21.1 官方混淆字节码考证）。

对应关系（混淆名 -> 原名）：
- dyz  LegacyRandomSource : Java 48 位 LCG
- dyn  BitRandomSource    : nextInt/nextLong/nextFloat 默认实现
- dzx  WorldgenRandom     : setLargeFeatureSeed (c(J,II))
- ad   Util               : shuffle(c) / getRandom(a)
- dmm  Rotation           : getShuffled(b)
- ayo  Mth                : getSeed(BlockPos) (b(III))
- enm  RuleProcessor      : 逐方块降解（每方块按坐标重播种，规则间共享随机流）
- ekv$b JigsawPlacement$Placer : tryPlacingChildren

所有乘加运算按 Java long（mod 2^64）/int（mod 2^32）回绕语义模拟。
"""
from __future__ import annotations

from typing import List, Sequence, TypeVar

T = TypeVar("T")

MASK_32 = 0xFFFFFFFF
MASK_48 = (1 << 48) - 1
MASK_64 = 0xFFFFFFFFFFFFFFFF
MULT = 25214903917
ADD = 11

# dmm: NONE=0, CLOCKWISE_90=1, CLOCKWISE_180=2, COUNTERCLOCKWISE_90=3
ROTATIONS = ("NONE", "CLOCKWISE_90", "CLOCKWISE_180", "COUNTERCLOCKWISE_90")


def java_int(v: int) -> int:
    """Python 整数 -> Java int（有符号 32 位）。"""
    v &= MASK_32
    return v - (1 << 32) if v >= (1 << 31) else v


def java_long(v: int) -> int:
    """Python 整数 -> Java long（有符号 64 位）。"""
    v &= MASK_64
    return v - (1 << 64) if v >= (1 << 63) else v


def _u(v: int) -> int:
    """有符号/任意整数 -> 64 位无符号表示。"""
    return v & MASK_64


class LegacyRandomSource:
    """net.minecraft.world.level.levelgen.LegacyRandomSource (dyz)。

    Java 48 位 LCG：state = (state * 25214903917 + 11) & (2^48-1)
    next(bits) = state >> (48 - bits)   （dyz.c(I)）
    """

    __slots__ = ("state",)

    def __init__(self, seed: int) -> None:
        self.set_seed(seed)

    def set_seed(self, seed: int) -> None:
        # dyz.b(J)：state = (seed ^ 25214903917) & (2^48-1)
        self.state = (_u(seed) ^ MULT) & MASK_48

    def next_bits(self, bits: int) -> int:
        # dyz.c(I)
        self.state = (self.state * MULT + ADD) & MASK_48
        return self.state >> (48 - bits)

    def next_int_bits(self, bits: int) -> int:
        """next(bits) 的 Java int 版（l2i，bits<=32 时取低 32 位即本身，有符号）。"""
        return java_int(self.next_bits(bits))

    def next_long(self) -> int:
        # dyn.g()：h = next(32)（有符号 int），l = next(32)（有符号 int）
        #          return ((long)h << 32) + (long)l
        h = java_int(self.next_bits(32))
        l = java_int(self.next_bits(32))
        return java_long((h << 32) + l)

    def next_int(self, bound: int) -> int:
        # dyn.a(I)（nextInt(bound)）：
        #   pow2: return (int)((bound * (long)next(31)) >>> 31)
        #   else: do { r = next(31); val = r % bound; } while (r - val + bound - 1 < 0)
        if bound <= 0:
            raise ValueError("Bound must be positive")
        r = self.next_bits(31)  # 0..2^31-1，非负
        if (bound & (bound - 1)) == 0:
            # bound * r < 2^62，lushr 31 无回绕问题
            return (bound * r) >> 31
        while True:
            val = r % bound
            # Java int 溢出：r - val + bound - 1 若超过 2^31-1 则变负 → 继续循环
            if r - val + (bound - 1) > 0x7FFFFFFF:
                r = self.next_bits(31)
                continue
            return val

    def next_float(self) -> float:
        # dyn.i()：next(24) * 2^-24
        return self.next_bits(24) / float(1 << 24)

    def next_boolean(self) -> bool:
        return self.next_bits(1) != 0


def shuffle_list(rng: LegacyRandomSource, items: Sequence[T]) -> List[T]:
    """ad.c(List, ayw)：Fisher-Yates，i 从 size 递减到 2，j=nextInt(i)，交换 i-1 与 j。"""
    out = list(items)
    i = len(out)
    while i > 1:
        j = rng.next_int(i)
        out[i - 1], out[j] = out[j], out[i - 1]
        i -= 1
    return out


def get_random_of(rng: LegacyRandomSource, items: Sequence[T]) -> T:
    """ad.a(T[], ayw)：items[nextInt(len)]。"""
    return items[rng.next_int(len(items))]


def rotation_shuffled(rng: LegacyRandomSource) -> List[str]:
    """dmm.b(ayw)：tryPlacingChildren 每个候选元素调用一次。"""
    return shuffle_list(rng, ROTATIONS)


def rotation_get_random(rng: LegacyRandomSource) -> str:
    """dmm.a(ayw)：拼装起点调用一次。"""
    return get_random_of(rng, ROTATIONS)


def set_large_feature_seed(rng: LegacyRandomSource, level_seed: int,
                           chunk_x: int, chunk_z: int) -> None:
    """dzx.c(J,II)（setLargeFeatureSeed）：GenerationContext 布局随机源播种。

    setSeed(levelSeed)
    l1 = nextLong()                      -- 1.21.1 无 |1（dzx.c 字节码实证）
    l2 = nextLong()
    setSeed((chunkX*l1) ^ (chunkZ*l2) ^ levelSeed)   -- 全部 Java long 回绕
    （dzx.c 字节码 L130-156：无 lor 指令、lxor 组合；调用点 ejr$a.a 压栈
      dcd.e(=x, 低32位) → 第一个 int、dcd.f(=z) → 第二个。
      同参数的 dzx.a(JII) 才有 |1 + ladd（散点结构概率用），勿混。
      本式与 cubiomes chunkGenerateRnd 恒等——结构布局流与
      getVariant 变种流是同一条流，对拍 cross_check_rng_streams.py
      6/6 全一致验证。）
    """
    rng.set_seed(level_seed)
    l1 = _u(rng.next_long())
    l2 = _u(rng.next_long())
    v = (_u(java_int(chunk_x)) * l1) ^ (_u(java_int(chunk_z)) * l2) ^ _u(level_seed)
    rng.set_seed(java_long(v & MASK_64))


def mth_get_seed(x: int, y: int, z: int) -> int:
    """ayo.b(III)（Mth.getSeed）：逐方块降解种子。

    l = (long)(x * 3129871 /*imul 32 位*/) ^ ((long)z * 116129781) ^ (long)y
    l = l * l * 42317861 + l * 11      -- Java long 回绕
    return l >> 16                     -- 算术右移
    """
    t = _u(java_int(java_int(x) * 3129871))          # imul 先 32 位回绕再 i2l
    l = (t ^ (_u(java_int(z)) * 116129781) ^ _u(java_int(y))) & MASK_64
    l = (l * l * 42317861 + l * 11) & MASK_64
    return java_long(l) >> 16                        # 算术右移（有符号）


class DegradationRandom:
    """enm.a（RuleProcessor.processBlock）的逐方块随机源。

    语义：对每个方块 random.setSeed(Mth.getSeed(pos))，然后把同一条流
    依次传给各条规则评估（输入谓词短路不匹配时不消耗随机数）。
    """

    def __init__(self) -> None:
        self._rng = LegacyRandomSource(0)

    def reseed_for(self, x: int, y: int, z: int) -> None:
        self._rng.set_seed(mth_get_seed(x, y, z))

    def next_float(self) -> float:
        return self._rng.next_float()


def make_layout_rng(level_seed: int, chunk_x: int, chunk_z: int) -> LegacyRandomSource:
    """ejr$a.a(J, dcd)：new WorldgenRandom(new LegacyRandomSource(0)) + 播种。"""
    rng = LegacyRandomSource(0)
    set_large_feature_seed(rng, level_seed, chunk_x, chunk_z)
    return rng
