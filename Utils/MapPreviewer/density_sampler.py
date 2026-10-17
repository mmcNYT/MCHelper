# -*- coding: utf-8 -*-
"""MC 26.2 主世界精确地形密度求值器（P0/P1 Python 原型，自包含）。

目标：从官方 worldgen JSON（density_function / noise / noise_settings）
精确复现 MC 26.2 主世界地形密度函数（sloped_cheese -> final_density ->
地表高度），与真实存档（seed=1 的 "Test (1)"）逐格对拍验证。

本模块为独立 Python 原型，不并入现有 _map_sampler.cpp 主链路。所有公式
逐条对照 .temp/mc262_decompile/ 下的反编译官方源码：

  RandomState / Noises / XoroshiroRandomSource / Xoroshiro128PlusPlus /
  RandomSupport / PositionalRandomFactory / DensityFunctions /
  synth.{NormalNoise, PerlinNoise, ImprovedNoise, BlendedNoise, SimplexNoise} /
  util.{Mth, CubicSpline}

关键事实（均已从源码核对）：
  * 世界种子 -> 基态：Xoroshiro128PlusPlus(upgradeSeedTo128bit(seed))，
    再 forkPositional() 取 2 个 nextLong 得世界 PositionalRandomFactory
    (posLo, posHi)。
  * 每个 density 噪声用 独立 派生：random = fromHashOf("minecraft:<名>")，
    即 Xoroshiro128PlusPlus(seedFromHashOf(md5).xor(posLo, posHi))，
    与初始化顺序无关。
  * NormalNoise = first(Perlin) + second(Perlin)，同一噪声随机源 fork 两次。
  * PerlinNoise 新初始化：positional=random.forkPositional()（耗 2 long），
    每个非零 octave 用 positional.fromHashOf("octave_"+octave) 建 ImprovedNoise。
  * ImprovedNoise 用 26.2 新算法（SimplexNoise.GRADIENT 16 项 + smoothstep），
    不等价于 cubiomes 的 samplePerlin。
  * BlendedNoise 用 fromHashOf("minecraft:terrain") 派生，legacy 初始化。
  * 所有 Mapped 类型精确公式见 build 中 _map。
  * spline 全程 float32 Hermite（CubicSpline.Multipoint.sample）。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct

# ---------------------------------------------------------------------------
# 64 位整数工具
# ---------------------------------------------------------------------------
_MASK64 = (1 << 64) - 1
_MASK32 = 0xFFFFFFFF


def _rotl(x: int, n: int) -> int:
    return ((x << n) | (x >> (64 - n))) & _MASK64


def _mix_stafford13(z: int) -> int:
    """RandomSupport.mixStafford13（64 位 wrap 乘法）。"""
    z &= _MASK64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
    return z ^ (z >> 31)


def _upgrade_seed128(seed: int):
    """RandomSupport.upgradeSeedTo128bit。GOLDEN=0x9E3779B97F4A7C15,
    SILVER=0x6A09E667F3BCC909。"""
    seed &= _MASK64
    low = (seed ^ 0x6A09E667F3BCC909) & _MASK64
    high = (low + 0x9E3779B97F4A7C15) & _MASK64
    return _mix_stafford13(low), _mix_stafford13(high)


def _seed_from_hash(name: str):
    """RandomSupport.seedFromHashOf：MD5-128 -> (hashLo, hashHi) 大端。"""
    d = hashlib.md5(name.encode("utf-8")).digest()
    lo = int.from_bytes(d[0:8], "big", signed=True) & _MASK64
    hi = int.from_bytes(d[8:16], "big", signed=True) & _MASK64
    return lo, hi


# ---------------------------------------------------------------------------
# XoroshiroRandomSource（Xoroshiro128PlusPlus）
# ---------------------------------------------------------------------------
class Xoroshiro128:
    """MC 的 XoroshiroRandomSource。状态用无符号 64 位掩码表示。"""

    __slots__ = ("lo", "hi")

    def __init__(self, lo: int, hi: int):
        if (lo | hi) == 0:
            lo, hi = 0x9E3779B97F4A7C15, 0x6A09E667F3BCC909
        self.lo = lo & _MASK64
        self.hi = hi & _MASK64

    @classmethod
    def from_seed(cls, seed: int):
        lo, hi = _upgrade_seed128(seed)
        return cls(lo, hi)

    def next_long(self) -> int:
        s0, s1 = self.lo, self.hi
        result = (_rotl((s0 + s1) & _MASK64, 17) + s0) & _MASK64
        s1 ^= s0
        self.lo = (_rotl(s0, 49) ^ s1 ^ ((s1 << 21) & _MASK64)) & _MASK64
        self.hi = _rotl(s1, 28)
        return result

    def next_int(self) -> int:          # (int) nextLong() -> 低 32 位
        return self.next_long() & _MASK32

    def next_int_bound(self, bound: int) -> int:
        """XoroshiroRandomSource.nextInt(bound) 无偏拒绝采样。"""
        threshold = (1 << 32) % bound
        while True:
            rb = self.next_long() & _MASK32
            mult = rb * bound
            if (mult & _MASK32) >= threshold:
                break
        return (mult >> 32) & _MASK32

    def next_double(self) -> float:
        # nextBits(53) = nextLong() >>> 11，乘 1.1102230246251565e-16
        return (self.next_long() >> 11) * 1.1102230246251565e-16

    def consume(self, n: int) -> None:
        for _ in range(n):
            self.next_long()

    def fork_positional(self):
        """forkPositional()：耗 2 个 nextLong 得 Positional (lo, hi)。"""
        return self.next_long(), self.next_long()

    @staticmethod
    def from_hash_xor(name: str, pos_lo: int, pos_hi: int) -> "Xoroshiro128":
        """fromHashOf(name)：md5 派生后 xor 位置状态。"""
        lo, hi = _seed_from_hash(name)
        return Xoroshiro128(lo ^ pos_lo, hi ^ pos_hi)


# ---------------------------------------------------------------------------
# Mth
# ---------------------------------------------------------------------------
def _ifloor(v: float) -> int:
    return int(math.floor(v))


def _clamp(v, lo, hi):
    return lo if v < lo else min(v, hi)


def _lerp(a, p0, p1):
    return p0 + a * (p1 - p0)


def _lerp3(a1, a2, a3, x000, x100, x010, x110, x001, x101, x011, x111):
    return _lerp(
        a3,
        _lerp(a2, _lerp(a1, x000, x100), _lerp(a1, x010, x110)),
        _lerp(a2, _lerp(a1, x001, x101), _lerp(a1, x011, x111)),
    )


def _smoothstep(x):
    return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)


def _clamped_lerp(f, a, b):
    if f < 0.0:
        return a
    return b if f > 1.0 else _lerp(f, a, b)


def _f32(x: float) -> float:
    """Java float 舍入（MC 样条/导数/location 均为 float32）。"""
    return struct.unpack("<f", struct.pack("<f", float(x)))[0]


# SimplexNoise.GRADIENT（16 项）与 dot
_GRADIENT = [
    [1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0],
    [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
    [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1],
    [1, 1, 0], [0, -1, 1], [-1, 1, 0], [0, -1, -1],
]


def _dot(hash_idx, x, y, z):
    g = _GRADIENT[hash_idx & 15]
    return g[0] * x + g[1] * y + g[2] * z


# ---------------------------------------------------------------------------
# LegacyRandomSource（48 位 LCG）+ SimplexNoise + PerlinSimplexNoise
# 供 Biome.getHeightAdjustedTemperature 与 SurfaceSystem 两个 extension 使用。
# 逐行对照 LegacyRandomSource.java / BitRandomSource.java /
# synth/SimplexNoise.java / synth/PerlinSimplexNoise.java / WorldgenRandom.java
# ---------------------------------------------------------------------------
_LEGACY_MULT = 25214903917
_LEGACY_ADD = 11
_LEGACY_MASK = (1 << 48) - 1


class LegacyRandomSource:
    """BitRandomSource 默认实现（next(bits) 走 48 位 LCG）。"""

    __slots__ = ("seed",)

    def __init__(self, seed):
        self.seed = (int(seed) ^ _LEGACY_MULT) & _LEGACY_MASK

    def set_seed(self, seed):
        self.seed = (int(seed) ^ _LEGACY_MULT) & _LEGACY_MASK

    def next_bits(self, bits):
        self.seed = (self.seed * _LEGACY_MULT + _LEGACY_ADD) & _LEGACY_MASK
        return self.seed >> (48 - bits)

    def next_int_u(self):
        """next(32) 作为无符号 32 位。"""
        return self.next_bits(32) & _MASK32

    def next_int(self):
        """BitRandomSource.nextInt() = next(32)，有符号。"""
        v = self.next_bits(32)
        return v - 0x100000000 if v >= 0x80000000 else v

    def next_int_bound(self, bound):
        """BitRandomSource.nextInt(bound)：2 的幂走移位，否则拒绝采样。"""
        if bound & (bound - 1) == 0:
            return (bound * self.next_bits(31)) >> 31
        while True:
            sample = self.next_bits(31)
            modulo = sample % bound
            if sample - modulo + (bound - 1) >= 0:
                return modulo

    def next_int_between(self, lo, hi):
        return lo + self.next_int_bound(hi - lo + 1)

    def next_long(self):
        upper = self.next_bits(32)
        lower = self.next_bits(32)
        v = ((upper << 32) + lower) & _MASK64
        return v - (1 << 64) if v >= (1 << 63) else v

    def next_bool(self):
        return self.next_bits(1) != 0

    def next_float(self):
        return self.next_bits(24) * 5.9604645e-8

    def next_double(self):
        upper = self.next_bits(26)
        lower = self.next_bits(27)
        return ((upper << 27) + lower) * 1.1102230246251565e-16

    def consume(self, n):
        for _ in range(n):
            self.next_bits(32)


_SQRT_3 = math.sqrt(3.0)
_SIMPLEX_F2 = 0.5 * (_SQRT_3 - 1.0)
_SIMPLEX_G2 = (3.0 - _SQRT_3) / 6.0


class SimplexNoise:
    """synth.SimplexNoise：2D getValue（extension 只用 2D）。"""

    __slots__ = ("xo", "yo", "zo", "p")

    def __init__(self, rng):
        self.xo = rng.next_double() * 256.0
        self.yo = rng.next_double() * 256.0
        self.zo = rng.next_double() * 256.0
        p = list(range(256))
        for i in range(256):
            off = rng.next_int_bound(256 - i)
            p[i], p[i + off] = p[i + off], p[i]
        self.p = p

    def _pp(self, x):
        return self.p[x & 0xFF]

    @staticmethod
    def _corner(index, x, y, z, base):
        t0 = base - x * x - y * y - z * z
        if t0 < 0.0:
            return 0.0
        t0 *= t0
        g = _GRADIENT[index]
        return t0 * t0 * (g[0] * x + g[1] * y + g[2] * z)

    def get_value(self, xin, yin):
        s = (xin + yin) * _SIMPLEX_F2
        i = _ifloor(xin + s)
        j = _ifloor(yin + s)
        t = (i + j) * _SIMPLEX_G2
        x0 = xin - (i - t)
        y0 = yin - (j - t)
        if x0 > y0:
            i1, j1 = 1, 0
        else:
            i1, j1 = 0, 1
        x1 = x0 - i1 + _SIMPLEX_G2
        y1 = y0 - j1 + _SIMPLEX_G2
        x2 = x0 - 1.0 + 2.0 * _SIMPLEX_G2
        y2 = y0 - 1.0 + 2.0 * _SIMPLEX_G2
        ii = i & 0xFF
        jj = j & 0xFF
        gi0 = self._pp(ii + self._pp(jj)) % 12
        gi1 = self._pp(ii + i1 + self._pp(jj + j1)) % 12
        gi2 = self._pp(ii + 1 + self._pp(jj + 1)) % 12
        n0 = self._corner(gi0, x0, y0, 0.0, 0.5)
        n1 = self._corner(gi1, x1, y1, 0.0, 0.5)
        n2 = self._corner(gi2, x2, y2, 0.0, 0.5)
        return 70.0 * (n0 + n1 + n2)


class PerlinSimplexNoise:
    """synth.PerlinSimplexNoise（octaveSet 通常为 [0]）。"""

    __slots__ = ("noise_levels", "highest_freq_value_factor",
                 "highest_freq_input_factor")

    def __init__(self, rng, octave_set):
        octave_set = sorted(set(octave_set))
        if not octave_set:
            raise ValueError("Need some octaves!")
        low_freq = -octave_set[0]
        high_freq = octave_set[-1]
        octaves = low_freq + high_freq + 1
        zero = SimplexNoise(rng)
        zero_idx = high_freq
        levels = [None] * octaves
        if 0 <= zero_idx < octaves and 0 in octave_set:
            levels[zero_idx] = zero
        for i in range(zero_idx + 1, octaves):
            if i >= 0 and (zero_idx - i) in octave_set:
                levels[i] = SimplexNoise(rng)
            else:
                rng.consume(262)
        if high_freq > 0:
            pos_seed = _i64(int(_f32(zero.get_value(zero.xo, zero.yo) * 9.223372e18)))
            hi_rng = LegacyRandomSource(pos_seed)
            for i in range(zero_idx - 1, -1, -1):
                if i < octaves and (zero_idx - i) in octave_set:
                    levels[i] = SimplexNoise(hi_rng)
                else:
                    hi_rng.consume(262)
        self.noise_levels = levels
        self.highest_freq_input_factor = 2.0 ** high_freq
        self.highest_freq_value_factor = 1.0 / (2.0 ** octaves - 1.0)

    def get_value(self, x, y, use_noise_start=False):
        value = 0.0
        factor = self.highest_freq_input_factor
        value_factor = self.highest_freq_value_factor
        for nl in self.noise_levels:
            if nl is not None:
                sx = nl.xo if use_noise_start else 0.0
                sy = nl.yo if use_noise_start else 0.0
                value += nl.get_value(x * factor + sx, y * factor + sy) * value_factor
            factor /= 2.0
            value_factor *= 2.0
        return value


# Biome.java L61-63：固定 seed 1234 的两个全局噪声（全项目共用）
_BIOME_TEMP_NOISE = None
_BIOME_FROZEN_TEMP_NOISE = None


def _biome_temperature_noise():
    global _BIOME_TEMP_NOISE
    if _BIOME_TEMP_NOISE is None:
        _BIOME_TEMP_NOISE = PerlinSimplexNoise(LegacyRandomSource(1234), [0])
    return _BIOME_TEMP_NOISE


def _biome_frozen_temperature_noise():
    global _BIOME_FROZEN_TEMP_NOISE
    if _BIOME_FROZEN_TEMP_NOISE is None:
        _BIOME_FROZEN_TEMP_NOISE = PerlinSimplexNoise(LegacyRandomSource(1234), [0])
    return _BIOME_FROZEN_TEMP_NOISE


# ---------------------------------------------------------------------------
# 噪声类
# ---------------------------------------------------------------------------
class ImprovedNoise:
    """26.0 新版 ImprovedNoise：Simplex GRADIENT + smoothstep。"""

    __slots__ = ("xo", "yo", "zo", "p")

    def __init__(self, rng: Xoroshiro128):
        self.xo = rng.next_double() * 256.0
        self.yo = rng.next_double() * 256.0
        self.zo = rng.next_double() * 256.0
        p = list(range(256))
        for i in range(256):
            off = rng.next_int_bound(256 - i)
            p[i], p[i + off] = p[i + off], p[i]
        self.p = p

    def _pp(self, x: int) -> int:
        return self.p[x & 0xFF]

    def noise(self, _x, _y, _z, yScale=0.0, yFudge=0.0):
        x = _x + self.xo
        y = _y + self.yo
        z = _z + self.zo
        xf = _ifloor(x)
        yf = _ifloor(y)
        zf = _ifloor(z)
        xr = x - xf
        yr = y - yf
        zr = z - zf
        if yScale != 0.0:
            fudgeLimit = yFudge if (0.0 <= yFudge < yr) else yr
            yrFudge = _ifloor(fudgeLimit / yScale + 1.0e-7) * yScale
        else:
            yrFudge = 0.0
        return self._sample_and_lerp(xf, yf, zf, xr, yr - yrFudge, zr, yr)

    def _sample_and_lerp(self, x, y, z, xr, yr, zr, yrOriginal):
        x0 = self._pp(x)
        x1 = self._pp(x + 1)
        xy00 = self._pp(x0 + y)
        xy01 = self._pp(x0 + y + 1)
        xy10 = self._pp(x1 + y)
        xy11 = self._pp(x1 + y + 1)
        d000 = _dot(self._pp(xy00 + z), xr, yr, zr)
        d100 = _dot(self._pp(xy10 + z), xr - 1.0, yr, zr)
        d010 = _dot(self._pp(xy01 + z), xr, yr - 1.0, zr)
        d110 = _dot(self._pp(xy11 + z), xr - 1.0, yr - 1.0, zr)
        d001 = _dot(self._pp(xy00 + z + 1), xr, yr, zr - 1.0)
        d101 = _dot(self._pp(xy10 + z + 1), xr - 1.0, yr, zr - 1.0)
        d011 = _dot(self._pp(xy01 + z + 1), xr, yr - 1.0, zr - 1.0)
        d111 = _dot(self._pp(xy11 + z + 1), xr - 1.0, yr - 1.0, zr - 1.0)
        xAlpha = _smoothstep(xr)
        yAlpha = _smoothstep(yrOriginal)
        zAlpha = _smoothstep(zr)
        return _lerp3(xAlpha, yAlpha, zAlpha,
                      d000, d100, d010, d110, d001, d101, d011, d111)


def _wrap(x):
    return x - math.floor(x / 3.3554432e7 + 0.5) * 3.3554432e7


class PerlinNoise:
    """PerlinNoise（新初始化 与 legacy 初始化两种）。"""

    __slots__ = ("first_octave", "amplitudes", "noise_levels",
                 "lowest_freq_input", "lowest_freq_value")

    def __init__(self, rng, first_octave, amplitudes, new_init):
        self.first_octave = first_octave
        self.amplitudes = list(amplitudes)
        n = len(self.amplitudes)
        zero_octave_idx = -first_octave
        levels = [None] * n
        if new_init:
            plo, phi = rng.fork_positional()
            for i in range(n):
                if self.amplitudes[i] != 0.0:
                    octave = first_octave + i
                    sub = Xoroshiro128.from_hash_xor("octave_%d" % octave, plo, phi)
                    levels[i] = ImprovedNoise(sub)
        else:
            zero_octave = ImprovedNoise(rng)
            if 0 <= zero_octave_idx < n and self.amplitudes[zero_octave_idx] != 0.0:
                levels[zero_octave_idx] = zero_octave
            for i in range(zero_octave_idx - 1, -1, -1):
                if i < n:
                    if self.amplitudes[i] != 0.0:
                        levels[i] = ImprovedNoise(rng)
                    else:
                        rng.consume(262)
                else:
                    rng.consume(262)
        self.noise_levels = levels
        self.lowest_freq_input = 2.0 ** (-zero_octave_idx)
        self.lowest_freq_value = (2.0 ** (n - 1)) / (2.0 ** n - 1.0)

    def get_value(self, x, y, z, yScale=0.0, yFudge=0.0):
        value = 0.0
        factor = self.lowest_freq_input
        value_factor = self.lowest_freq_value
        for i in range(len(self.noise_levels)):
            nl = self.noise_levels[i]
            if nl is not None:
                noise_val = nl.noise(_wrap(x * factor), _wrap(y * factor),
                                     _wrap(z * factor), yScale * factor, yFudge * factor)
                value += self.amplitudes[i] * noise_val * value_factor
            factor *= 2.0
            value_factor /= 2.0
        return value

    def get_octave_noise(self, i):
        return self.noise_levels[len(self.noise_levels) - 1 - i]


def _make_octave_amplitudes(octave_set):
    """makeAmplitudes(IntSortedSet)。返回 (firstOctave, amplitudes)。"""
    lo = min(octave_set)
    hi = max(octave_set)
    low_freq = -lo
    n = low_freq + hi + 1
    amps = [0.0] * n
    for o in octave_set:
        amps[o + low_freq] = 1.0
    return -low_freq, amps


class NormalNoise:
    """NormalNoise：first + second（同一 random fork 两次）。"""

    INPUT_FACTOR = 1.0181268882175227
    __slots__ = ("first", "second", "value_factor")

    def __init__(self, rng, first_octave, amplitudes):
        amps = list(amplitudes)
        self.first = PerlinNoise(rng, first_octave, amps, new_init=True)
        self.second = PerlinNoise(rng, first_octave, amps, new_init=True)
        nz = [i for i, a in enumerate(amps) if a != 0.0]
        span = (max(nz) - min(nz)) if nz else 0
        dev = 0.1 * (1.0 + 1.0 / (span + 1))
        self.value_factor = 0.16666666666666666 / dev

    def get_value(self, x, y, z):
        f = self.INPUT_FACTOR
        return (self.first.get_value(x, y, z)
                + self.second.get_value(x * f, y * f, z * f)) * self.value_factor


class BlendedNoise:
    """BlendedNoise（base_3d_noise）。用 terrain 随机 legacy 初始化。"""

    __slots__ = ("min_limit", "max_limit", "main",
                 "xz_scale", "y_scale", "xz_factor", "y_factor", "smear",
                 "xz_mult", "y_mult")

    def __init__(self, rng, xz_scale, y_scale, xz_factor, y_factor, smear):
        min_set = _make_octave_amplitudes(range(-15, 1))
        main_set = _make_octave_amplitudes(range(-7, 1))
        self.min_limit = PerlinNoise(rng, min_set[0], min_set[1], new_init=False)
        self.max_limit = PerlinNoise(rng, min_set[0], min_set[1], new_init=False)
        self.main = PerlinNoise(rng, main_set[0], main_set[1], new_init=False)
        self.xz_scale = xz_scale
        self.y_scale = y_scale
        self.xz_factor = xz_factor
        self.y_factor = y_factor
        self.smear = smear
        self.xz_mult = 684.412 * xz_scale
        self.y_mult = 684.412 * y_scale

    def compute(self, blockX, blockY, blockZ):
        xz_mult, y_mult = self.xz_mult, self.y_mult
        limitX = blockX * xz_mult
        limitY = blockY * y_mult
        limitZ = blockZ * xz_mult
        mainX = limitX / self.xz_factor
        mainY = limitY / self.y_factor
        mainZ = limitZ / self.xz_factor
        limit_smear = y_mult * self.smear
        main_smear = limit_smear / self.y_factor
        blend_min = 0.0
        blend_max = 0.0
        main_val = 0.0
        pow_ = 1.0
        for i in range(8):
            nl = self.main.get_octave_noise(i)
            if nl is not None:
                main_val += nl.noise(_wrap(mainX * pow_), _wrap(mainY * pow_),
                                     _wrap(mainZ * pow_), main_smear * pow_,
                                     mainY * pow_) / pow_
            pow_ /= 2.0
        factor = (main_val / 10.0 + 1.0) / 2.0
        is_max = factor >= 1.0
        is_min = factor <= 0.0
        pow_ = 1.0
        for i in range(16):
            wx = _wrap(limitX * pow_)
            wy = _wrap(limitY * pow_)
            wz = _wrap(limitZ * pow_)
            y_scale_pow = limit_smear * pow_
            if not is_max:
                nl = self.min_limit.get_octave_noise(i)
                if nl is not None:
                    blend_min += nl.noise(wx, wy, wz, y_scale_pow, limitY * pow_) / pow_
            if not is_min:
                nl = self.max_limit.get_octave_noise(i)
                if nl is not None:
                    blend_max += nl.noise(wx, wy, wz, y_scale_pow, limitY * pow_) / pow_
            pow_ /= 2.0
        return _clamped_lerp(factor, blend_min / 512.0, blend_max / 512.0) / 128.0


# ---------------------------------------------------------------------------
# CubicSpline（float32 Hermite）
# ---------------------------------------------------------------------------
class SplinePoint:
    __slots__ = ("location", "value", "derivative")

    def __init__(self, location, value, derivative):
        self.location = float(location)
        self.value = value  # 常量 float 或子样条
        self.derivative = float(derivative)


def _binary_search(lo, hi, test):
    """Mth.binarySearch(0, to, pred) -> 返回第一个使 pred 为真的下标。"""
    length = hi - lo
    while length > 0:
        half = length // 2
        mid = lo + half
        if test(mid):
            length = half
        else:
            lo = mid + 1
            length -= half + 1
    return lo


def _spline_sample(coord, locations, derivatives, values, c):
    """CubicSpline.Multipoint.sample：坐标已 float32。c = (x,y,z)。"""
    input_ = coord(c[0], c[1], c[2])
    start = _binary_search(0, len(locations),
                           lambda i: input_ < locations[i]) - 1
    last = len(locations) - 1
    if start < 0:
        return _f32(_linear_extend(input_, locations, _spline_eval(values[0], c),
                                   derivatives, 0))
    if start == last:
        return _f32(_linear_extend(input_, locations,
                                   _spline_eval(values[last], c),
                                   derivatives, last))
    x1 = locations[start]
    x2 = locations[start + 1]
    t = _f32((input_ - x1) / (x2 - x1))
    y1 = _spline_eval(values[start], c)
    y2 = _spline_eval(values[start + 1], c)
    d1 = derivatives[start]
    d2 = derivatives[start + 1]
    a = _f32(d1 * (x2 - x1) - (y2 - y1))
    b = _f32(-d2 * (x2 - x1) + (y2 - y1))
    return _f32(_f32(_lerp(t, y1, y2)) + t * (1.0 - t) * _f32(_lerp(t, a, b)))


def _linear_extend(input, locations, value, derivatives, index):
    d = derivatives[index]
    return value if d == 0.0 else value + d * (input - locations[index])


# spline value 可以是常数 float 或嵌套 SplinePoint 列表（子样条）
def _spline_eval(value, xs):
    if isinstance(value, float):
        return value
    # value 为子样条 _SplineObj（values 元素），用其 eval 求值
    return value.eval(xs[0], xs[1], xs[2])


class _SplineObj:
    __slots__ = ("coord", "locations", "derivatives", "values")

    def __init__(self, coord, locations, derivatives, values):
        self.coord = coord
        self.locations = locations
        self.derivatives = derivatives
        self.values = values

    def eval(self, x, y, z):
        return _spline_sample(self.coord, self.locations, self.derivatives,
                              self.values, (x, y, z))


def _make_spline_data(spline_json, sam):
    """spline 节点根：coordinate 的 eval 接收 ctx tuple。"""
    coord_fn = sam._make(spline_json["coordinate"])
    coord = lambda x, y, z: _f32(coord_fn(x, y, z))
    points = spline_json["points"]
    locations = [_f32(p["location"]) for p in points]
    derivatives = [_f32(p.get("derivative", 0.0)) for p in points]
    values = []
    for p in points:
        val = p["value"]
        if isinstance(val, dict) and "coordinate" in val:
            values.append(_make_spline_data(val, sam))
        else:
            values.append(_f32(val))
    return _SplineObj(coord, locations, derivatives, values)


# ---------------------------------------------------------------------------
# 密度函数编译器（Sampler）
# ---------------------------------------------------------------------------
class Sampler:
    """按 seed 编译主世界密度函数。"""

    def __init__(self, seed, version="26.2"):
        self.seed = seed & _MASK64
        self.version = version
        world = Xoroshiro128.from_seed(self.seed)
        self._pos_lo, self._pos_hi = world.fork_positional()
        self._noise_cache = {}
        self._blended_cache = None
        worldgen_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "_native", "worldgen")
        self._df_dir = os.path.join(worldgen_dir, version, "density_function")
        self._noise_dir = os.path.join(worldgen_dir, version, "noise")

    # ---- 资源加载 ----
    def _load_noise_params(self, name):
        short = name.split(":")[-1]
        p = os.path.join(self._noise_dir, short + ".json")
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data["firstOctave"], data["amplitudes"]

    def noise(self, name):
        if name not in self._noise_cache:
            first_octave, amps = self._load_noise_params(name)
            rng = Xoroshiro128.from_hash_xor(name, self._pos_lo, self._pos_hi)
            self._noise_cache[name] = NormalNoise(rng, first_octave, amps)
        return self._noise_cache[name]

    def terrain_rng(self):
        return Xoroshiro128.from_hash_xor("minecraft:terrain",
                                          self._pos_lo, self._pos_hi)

    def blended(self, xz_scale, y_scale, xz_factor, y_factor, smear):
        key = (xz_scale, y_scale, xz_factor, y_factor, smear)
        if self._blended_cache is None:
            self._blended_cache = BlendedNoise(self.terrain_rng(),
                                               xz_scale, y_scale,
                                               xz_factor, y_factor, smear)
        return self._blended_cache

    def _load_df(self, ref):
        # ref 形如 "minecraft:overworld/sloped_cheese"、"minecraft:zero"、
        # "minecraft:overworld/caves/entrances"。"overworld/" 是命名空间分组
        # 前缀，除 caves 等真实子目录外不展开为磁盘路径，故先剥掉该段。
        path = ref.split(":", 1)[-1]           # "overworld/sloped_cheese"
        if path.startswith("overworld/"):
            path = path[len("overworld/"):]     # "sloped_cheese" / "caves/entrances"
        path = path.replace("/", os.sep) + ".json"
        p = os.path.join(self._df_dir, path)
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    # ---- 密度函数编译 ----
    def _const(self, v):
        def fn(x, y, z):
            return float(v)
        return fn

    def _ref(self, ref):
        node = self._load_df(ref)
        return self._make(node)

    def _make(self, node):
        """编译 density JSON 节点 -> fn(x,y,z)->float。"""
        if isinstance(node, bool):
            return self._const(1.0 if node else 0.0)
        if isinstance(node, (int, float)):
            return self._const(node)
        if isinstance(node, str):
            return self._ref(node)

        typ = node.get("type", "")
        kind = typ.split(":")[-1]

        if kind == "add":
            a = self._make(node["argument1"]); b = self._make(node["argument2"])
            return lambda x, y, z: a(x, y, z) + b(x, y, z)
        if kind == "mul":
            a = self._make(node["argument1"]); b = self._make(node["argument2"])
            return lambda x, y, z: (0.0 if a(x, y, z) == 0.0
                                    else a(x, y, z) * b(x, y, z))
        if kind in ("min", "max"):
            a = self._make(node["argument1"]); b = self._make(node["argument2"])
            if kind == "min":
                return lambda x, y, z: min(a(x, y, z), b(x, y, z))
            return lambda x, y, z: max(a(x, y, z), b(x, y, z))

        if kind in ("half_negative", "quarter_negative", "half_positive",
                    "quarter_positive", "abs", "cube", "square", "invert",
                    "squeeze"):
            f = self._make(node["argument"])
            return lambda x, y, z: _apply_map(kind, f(x, y, z))

        if kind == "clamp":
            f = self._make(node["input"]); lo = float(node["min"]); hi = float(node["max"])
            return lambda x, y, z: _clampf(f(x, y, z), lo, hi)

        if kind == "y_clamped_gradient":
            fy, ty = float(node["from_y"]), float(node["to_y"])
            fv, tv = float(node["from_value"]), float(node["to_value"])
            return lambda x, y, z: _y_clamped_map(y, fy, ty, fv, tv)

        if kind == "noise":
            name = node["noise"]; xz = float(node.get("xz_scale", 1.0)); ys = float(node.get("y_scale", 1.0))
            n = self.noise(name)
            return lambda x, y, z: n.get_value(x * xz, y * ys, z * xz)

        if kind == "shifted_noise":
            name = node["noise"]; xz = float(node.get("xz_scale", 1.0)); ys = float(node.get("y_scale", 1.0))
            sx = self._make(node.get("shift_x", 0.0))
            sy = self._make(node.get("shift_y", 0.0))
            sz = self._make(node.get("shift_z", 0.0))
            n = self.noise(name)
            return lambda x, y, z: n.get_value(x * xz + sx(x, y, z),
                                               y * ys + sy(x, y, z),
                                               z * xz + sz(x, y, z))

        if kind in ("shift_a", "shift_b", "shift"):
            noise_ref = node["argument"]
            if isinstance(noise_ref, dict):
                noise_ref = noise_ref.get("noise", noise_ref)
            n = self.noise(noise_ref)
            if kind == "shift_a":
                return lambda x, y, z: n.get_value(x * 0.25, 0.0, z * 0.25) * 4.0
            if kind == "shift_b":
                return lambda x, y, z: n.get_value(z * 0.25, x * 0.25, 0.0) * 4.0
            return lambda x, y, z: n.get_value(x * 0.25, y * 0.25, z * 0.25) * 4.0

        if kind == "old_blended_noise":
            xz = float(node["xz_scale"]); ys = float(node["y_scale"])
            xf = float(node["xz_factor"]); yf = float(node["y_factor"])
            sm = float(node["smear_scale_multiplier"])
            b = self.blended(xz, ys, xf, yf, sm)
            return lambda x, y, z: b.compute(x, y, z)

        if kind == "spline":
            obj = _make_spline_data(node["spline"], self)
            return lambda x, y, z: obj.eval(x, y, z)

        if kind == "range_choice":
            f = self._make(node["input"])
            lo = float(node["min_inclusive"]); hi = float(node["max_exclusive"])
            tin = self._make(node["when_in_range"]); tout = self._make(node["when_out_of_range"])
            return lambda x, y, z: (tin(x, y, z) if lo <= f(x, y, z) < hi
                                    else tout(x, y, z))

        if kind == "interval_select":
            f = self._make(node["input"])
            thresholds = [float(t) for t in node["thresholds"]]
            funcs = [self._make(fn) for fn in node["functions"]]
            def ev(x, y, z):
                v = f(x, y, z)
                for i, t in enumerate(thresholds):
                    if v < t:
                        return funcs[i](x, y, z)
                return funcs[-1](x, y, z)
            return ev

        # interpolated：MC 区块按 4x4x8 cell（size_horizontal=1, size_vertical=2）
        # 在 8 个角点采样 argument，再做 trilinear 插值（对应 NoiseChunk 的密度生成）。
        if kind == "interpolated":
            arg = self._make(node["argument"])
            return self._interpolated_cell(arg)

        # 缓存/标记类（对应 NoiseChunk.wrapNew 的 Marker 包装语义）。
        # cache_2d: NoiseChunk.Cache2D —— 按 (x,z) 列缓存（求值用调用 y；内容 y 无关）。
        # cache_once: 单次求值缓存（按 (x,y,z)）。
        if kind == "cache_2d" or kind == "cache_once":
            f = self._make(node["argument"])
            if kind == "cache_2d":
                col = {}
                def cf(x, y, z):
                    k = (x, z)
                    v = col.get(k)
                    if v is None:
                        v = f(x, y, z)
                        col[k] = v
                    return v
            else:
                key = [-1 << 62, -1 << 62, -1 << 62]
                val = [0.0]
                def cf(x, y, z):
                    if key[0] != x or key[1] != y or key[2] != z:
                        key[0], key[1], key[2], val[0] = x, y, z, f(x, y, z)
                    return val[0]
            return cf
        # flat_cache: NoiseChunk.FlatCache —— 经实测核对 26.2 NoiseChunk.wrap/mapAll
        # 数据流：sloped_cheese 等经 HolderHolder 引用，NoiseChunk.wrapNew 对
        # HolderHolder 直接解引用（L398）且 mapAll 不递归其内部，故 flat_cache
        # Marker 从未被实例化为 FlatCache，全程为纯透传（与 cache_all_in_cell /
        # blend_density 一致；blend_density 在 blender 为空时同样透传，L393）。
        if kind in ("flat_cache", "cache_all_in_cell", "blend_density"):
            return self._make(node["argument"])
        if kind == "blend_alpha":
            return self._const(1.0)
        if kind == "blend_offset":
            return self._const(0.0)
        if kind == "beardifier":
            return self._const(0.0)
        if kind == "find_top_surface":
            return self._find_top(node)

        raise NotImplementedError(f"未支持的 density 类型: {typ}")

    def _find_top(self, node):
        """find_top_surface：从 upper_bound 顶向下扫描，返回首个 density>0 的 y。

        对应 DensityFunctions.FindTopSurface.compute：upper 用原 context y（调用处
        传 blockY=0），density 用步进 cell_height 的扫描 y。"""
        dens = self._make(node["density"])
        upper = self._make(node["upper_bound"])
        lower = int(node["lower_bound"])
        cell = int(node["cell_height"])

        def fn(x, y, z):
            top_y = _ifloor(upper(x, y, z) / cell) * cell
            if top_y <= lower:
                return float(lower)
            b = top_y
            while b >= lower:
                if dens(x, b, z) > 0.0:
                    return float(b)
                b -= cell
            return float(lower)

        return fn

    # ---- interpolated：4x4x8 cell 采样 + trilinear 插值 ----
    def _interpolated_cell(self, arg):
        """模拟 MC NoiseChunk 的密度插值（size_horizontal=1, size_vertical=2）。

        cell = 4(x) x 4(z) x 8(y)。角点在 floor(cell) 处，方块在 cell 内用
        trilinear 插值得到密度。负坐标用 floor（//）。"""

        def f(x, y, z):
            cx = x // 4 * 4
            cy = y // 8 * 8
            cz = z // 4 * 4
            dx = _f32((x - cx) / 4.0)
            dy = _f32((y - cy) / 8.0)
            dz = _f32((z - cz) / 4.0)
            c000 = arg(cx, cy, cz)
            c100 = arg(cx + 4, cy, cz)
            c010 = arg(cx, cy, cz + 4)
            c110 = arg(cx + 4, cy, cz + 4)
            c001 = arg(cx, cy + 8, cz)
            c101 = arg(cx + 4, cy + 8, cz)
            c011 = arg(cx, cy + 8, cz + 4)
            c111 = arg(cx + 4, cy + 8, cz + 4)
            i00 = _lerp(dx, c000, c100)
            i10 = _lerp(dx, c010, c110)
            i01 = _lerp(dx, c001, c101)
            i11 = _lerp(dx, c011, c111)
            j0 = _lerp(dz, i00, i10)
            j1 = _lerp(dz, i01, i11)
            return _lerp(dy, j0, j1)

        return f

    # ---- 对外便捷接口 ----
    def build(self, ref):
        return self._ref(ref)

    def build_final_density(self):
        overworld = os.path.join(
            os.path.dirname(self._df_dir), "noise_settings", "overworld.json")
        with open(overworld, encoding="utf-8") as f:
            data = json.load(f)
        node = data["noise_router"]["final_density"]
        return self._make(node)


# ---------------------------------------------------------------------------
# Mapped 运算（含 squeeze）
# ---------------------------------------------------------------------------
def _apply_map(kind, v):
    if kind == "half_negative":
        return v if v > 0.0 else v * 0.5
    if kind == "quarter_negative":
        return v if v > 0.0 else v * 0.25
    if kind == "half_positive":
        return v if v < 0.0 else v * 0.5
    if kind == "quarter_positive":
        return v if v < 0.0 else v * 0.25
    if kind == "abs":
        return abs(v)
    if kind == "square":
        return v * v
    if kind == "cube":
        return v * v * v
    if kind == "invert":
        return 1.0 / v
    if kind == "squeeze":
        c = _clamp(v, -1.0, 1.0)
        return c / 2.0 - c * c * c / 24.0
    raise ValueError(kind)


def _clampf(v, lo, hi):
    return lo if v < lo else min(v, hi)


def _y_clamped_map(y, fy, ty, fv, tv):
    if y <= fy:
        return fv
    if y >= ty:
        return tv
    return fv + (tv - fv) * (y - fy) / (ty - fy)


# ---------------------------------------------------------------------------
# 便捷：单点求值 + 地表高度扫描
# ---------------------------------------------------------------------------
def build_sampler(seed, version="26.2"):
    return Sampler(seed, version)


def surface_height(sampler, density_fn, x, z, min_y=-64, max_y=320, sea_level=63):
    """在 (x,z) 列找最高一个 density>0 的整数 Y（近似地表）。

    说明：真实世界是 NoiseChunk 在网格上插值后定块，此处为单点直接扫描，
    用于数值核对 / 展示；精确到块需要插值阶段（下一阶段实现）。
    """
    for y in range(max_y, min_y - 1, -1):
        if density_fn(x, y, z) > 0.0:
            return y
    return min_y


# ---------------------------------------------------------------------------
# Surface 覆盖层（SurfaceSystem + SurfaceRules + NoiseChunk.preliminary）
# 逐条对照 26.2 反编译源码：SurfaceSystem / SurfaceRules / NoiseChunk /
# DensityFunctions.FindTopSurface / VerticalAnchor / XoroshiroRandomSource /
# Mth.getSeed。全程 float32 语义与 Density 引擎一致。
# ---------------------------------------------------------------------------
_SURFACE_SEA_LEVEL = 63          # 主世界海平面（NoiseGeneratorSettings 无 sea_level，
                                 # 由维度类型给出 overworld sea_level=63）
_SURFACE_MIN_Y = -64               # 主世界 min_y
_SURFACE_GEN_DEPTH = 384           # 主世界 height
_SURFACE_TOP_BLOCK_Y = _SURFACE_MIN_Y + _SURFACE_GEN_DEPTH - 1  # 319
_DEFAULT_BLOCK = "minecraft:stone"   # noise_settings.default_block


def _i32(v):
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


def _i64(v):
    v &= _MASK64
    return v - (1 << 64) if v >= (1 << 63) else v


def _get_seed(x, y, z):
    """Mth.getSeed(x,y,z)（26.2 反编译 331-336 行）。

    26.2 变更：末尾 `seed >> 16`（1.21 及以前直接返回 seed）。
    x 项 int32 溢出后符号扩展为 long；>> 为算术右移（floor 语义）。"""
    x32 = _i32(x * 3129871)
    seed = (x32 ^ (z * 116129781) ^ y) & _MASK64
    seed = _i64(_i64(_i64(seed * seed) * 42317861) + _i64(seed * 11))
    return seed >> 16


def _surface_random_double(pos_lo, pos_hi, x, y, z):
    """XoroshiroRandomSource.at(x,y,z).nextDouble()。"""
    seed = (_get_seed(x, y, z) ^ pos_lo) & _MASK64
    rng = Xoroshiro128(seed, pos_hi)
    return (rng.next_long() >> 11) * 1.1102230246251565e-16


def _surface_random_float(pos_lo, pos_hi, x, y, z):
    """XoroshiroRandomSource.at(x,y,z).nextFloat()。"""
    seed = (_get_seed(x, y, z) ^ pos_lo) & _MASK64
    rng = Xoroshiro128(seed, pos_hi)
    return (rng.next_long() >> 40) * 5.9604645e-8


class _SurfaceRandomSource:
    """等价 XoroshiroRandomSource（Java RandomSource），包 Xoroshiro128PlusPlus。"""

    __slots__ = ("rng",)

    def __init__(self, lo, hi):
        self.rng = Xoroshiro128(lo, hi)

    def next_long(self):
        return self.rng.next_long()

    def next_int(self):
        return self.rng.next_long() & _MASK32

    def next_int_bound(self, bound):
        return self.rng.next_int_bound(bound)

    def next_bool(self):
        return (self.rng.next_long() & 1) != 0

    def next_float(self):
        return (self.rng.next_long() >> 40) * 5.9604645e-8

    def next_double(self):
        return (self.rng.next_long() >> 11) * 1.1102230246251565e-16

    def next_int_between(self, lo, hi):
        return lo + self.next_int_bound(hi - lo + 1)


class SurfaceRulesEngine:
    """编译主世界 surface_rule，对给定 (x,z) 列求顶层覆盖方块。

    biome 判定需外部提供 biome_at(x,y,z)->"minecraft:<key>"；表面高度需
    surface_top(x,z)->int（用于 steep）；stoneBelowDepth 需 solid_at
    (x,y,z)->bool（fill 语义的"石实心"判定，用于 ceiling 规则 lookahead，
    SurfaceSystem.buildSurface 的 isStone=非空非流体）。缺 solid_at 时
    按 1 处理（无洞浅近似）。sea/min_y/gen_depth 固定为主世界值。"""

    def __init__(self, sampler, biome_at, surface_top=None, solid_at=None):
        self.trace = None  # 调试：None 关闭；非空则记录 (depth, 类型, 结果)
        self.s = sampler
        self.pos_lo, self.pos_hi = sampler._pos_lo, sampler._pos_hi
        self.biome_at = biome_at
        self.surface_top = surface_top or (lambda x, z: _SURFACE_MIN_Y)
        self.solid_at = solid_at
        ow = os.path.join(os.path.dirname(sampler._df_dir),
                          "noise_settings", "overworld.json")
        with open(ow, encoding="utf-8") as f:
            data = json.load(f)
        self.rule_root = self._compile_surface(data["surface_rule"])
        # 预编译 preliminary_surface_level（find_top_surface）
        self._preliminary = sampler._make(
            data["noise_router"]["preliminary_surface_level"])
        _cb = Xoroshiro128.from_hash_xor("minecraft:clay_bands",
                                         self.pos_lo, self.pos_hi)
        self._clay = self._generate_bands(_SurfaceRandomSource(_cb.lo, _cb.hi))
        self._clay_off = None  # clay_bands_offset 噪声惰性
        # 两个 extension 用的 badlands/iceberg 噪声（SurfaceSystem L58-63）
        self._nb = {}
        # 可变状态
        self.block_x = 0
        self.block_z = 0
        self.block_y = 0
        self.surface_depth = 0
        self.stone_above = 0
        self.stone_below = 0
        self.water_height = -(1 << 62)
        self._sec = None
        self._biome = None
        self._seq = 0  # DFS 节点序号（用于 trace 定位）

    def _n(self, key):
        """按需取 NormalNoise（extension 用）。"""
        n = self._nb.get(key)
        if n is None:
            n = self.s.noise("minecraft:" + key)
            self._nb[key] = n
        return n

    # ---- SurfaceSystem.erodedBadlandsExtension（L205-233） ----
    def eroded_badlands_extension(self, x, z, height):
        """返回该列 extension 从 startY 向下垫的 defaultBlock y 列表（降序）或 None。

        官方语义（L216-231）：
          扫描 a：y 从 startY 降，遇 defaultBlock(stone) 停止；遇 WATER 立即
                  放弃整列（return，不垫任何块）。
          扫描 b：y 从 startY 降，只要该格是 air（且未到 minY）就写 defaultBlock；
                  遇到任何非 air 即停。
        注意：扫描 a 不因红沙/陶土等"非 stone 的实心块"停止（只有 defaultBlock
        才停），所以扫描 b 常被这些块挡住而只填极少数格。"""
        if self.solid_at is None:
            return None
        pillar_buffer = min(
            abs(self._n("badlands_surface").get_value(x, 0.0, z) * 8.25),
            self._n("badlands_pillar").get_value(x * 0.2, 0.0, z * 0.2) * 15.0)
        if pillar_buffer <= 0.0:
            return None
        pillar_floor = abs(self._n("badlands_pillar_roof").get_value(
            x * 0.75, 0.0, z * 0.75) * 1.5)
        extension_top = 64.0 + min(pillar_buffer * pillar_buffer * 2.5,
                                   math.ceil(pillar_floor * 50.0) + 24.0)
        start_y = _ifloor(extension_top)
        if height > start_y:
            return None

        fill = getattr(self, "_fill_block_at", None)

        def is_default_block(y):
            if fill is None:
                return False
            solid, blk = fill(x, y, z)
            return solid    # fill 阶段实心 == defaultBlock（fluid 例外见下）

        def is_water(y):
            if fill is None:
                return False
            solid, blk = fill(x, y, z)
            return blk == "minecraft:water"

        # 扫描 a
        yy = start_y
        while yy >= _SURFACE_MIN_Y:
            if is_default_block(yy):
                break
            if is_water(yy):
                return None
            yy -= 1

        # 扫描 b
        filled = []
        yy = start_y
        while yy >= _SURFACE_MIN_Y:
            solid, blk = (fill(x, yy, z) if fill is not None else (False, None))
            if solid or (blk not in (None, "minecraft:air")):
                break
            filled.append(yy)
            yy -= 1
        return filled or None

    def _substance(self, x, y, z):
        """(is_solid, block)；无 solid_at 时退化。"""
        if self.solid_at is None:
            return False, "minecraft:air"
        # solid_at 只给 bool；block 需要额外查询，故用 fill_block_at
        f = getattr(self, "_fill_block_at", None)
        if f is not None:
            return f(x, y, z)
        solid = self.solid_at(x, y, z)
        return solid, (None if solid else "minecraft:air")

    # ---- SurfaceSystem.frozenOceanExtension（L235-284） ----
    def frozen_ocean_extension(self, x, z, height, min_surface_level, sea_level,
                               melt_slightly):
        """"返回 (ice_blocks dict y->block, snow_depth) 或 None。

        melt_slightly = Biome.shouldMeltFrozenOceanIcebergSlightly（>0.1F）。"""
        pillar_scale = 1.28
        iceberg = min(
            abs(self._n("iceberg_surface").get_value(x, 0.0, z) * 8.25),
            self._n("iceberg_pillar").get_value(x * pillar_scale, 0.0,
                                                z * pillar_scale) * 15.0)
        if iceberg <= 1.8:
            return None
        roof_scale = 1.17
        iceberg_roof = abs(self._n("iceberg_pillar_roof").get_value(
            x * roof_scale, 0.0, z * roof_scale) * 1.5)
        top = min(iceberg * iceberg * 1.2, math.ceil(iceberg_roof * 40.0) + 14.0)
        if melt_slightly:
            top -= 2.0
        if top > 2.0:
            extension_bottom = sea_level - top - 7.0
            top += sea_level
        else:
            top = 0.0
            extension_bottom = 0.0
        extension_top = top
        rnd = _SurfaceRandomSource(*self._xz_seed(x, z))
        max_snow_depth = 2 + rnd.next_int_bound(4)
        min_snow_height = sea_level + 18 + rnd.next_int_bound(10)
        snow_depth = 0
        blocks = {}
        y = max(height, int(extension_top) + 1)
        while y >= min_surface_level:
            solid, blk = self._substance(x, y, z)
            is_air = (not solid) and blk in (None, "minecraft:air")
            is_water = blk == "minecraft:water"
            if (is_air and y < int(extension_top) and rnd.next_double() > 0.01) or \
               (is_water and y > extension_bottom and y < sea_level
                    and extension_bottom != 0.0 and rnd.next_double() > 0.15):
                if snow_depth <= max_snow_depth and y > min_snow_height:
                    blocks[y] = "minecraft:snow_block"
                    snow_depth += 1
                else:
                    blocks[y] = "minecraft:packed_ice"
            y -= 1
        return (blocks, snow_depth) if blocks else None

    def _xz_seed(self, x, z):
        """SurfaceSystem.noiseRandom.at(x,0,z) -> (seedLo^getSeed, seedHi)。"""
        lo = (_get_seed(x, 0, z) ^ self.pos_lo) & _MASK64
        return lo, self.pos_hi

    # ---- Biome.getHeightAdjustedTemperature（L112-121） ----
    def biome_temperature(self, biome_key, x, y, z, sea_level=_SURFACE_SEA_LEVEL):
        """冷/暖判定用的高度修正温度（frozen_ocean 冰 melts 判定）。"""
        base = _BIOME_BASE_TEMP.get(_block_short(biome_key), 0.5)
        snow_level = sea_level + 17
        if y > snow_level:
            v = _biome_temperature_noise().get_value(x / 8.0, z / 8.0) * 8.0
            return base - (v + y - snow_level) * 0.05 / 40.0
        return base

    # ---- Bandlands（SurfaceSystem.generateBands/getBand，逐行对照） ----
    _BAND_TERRACOTTA = "minecraft:terracotta"
    _BAND_COLORS = {
        "ORANGE": "minecraft:orange_terracotta",
        "YELLOW": "minecraft:yellow_terracotta",
        "BROWN": "minecraft:brown_terracotta",
        "RED": "minecraft:red_terracotta",
        "WHITE": "minecraft:white_terracotta",
        "LIGHT_GRAY": "minecraft:light_gray_terracotta",
    }

    @staticmethod
    def _generate_bands(rng):
        """SurfaceSystem.generateBands：192 长彩带表（随机消耗顺序严格一致）。"""
        bands = [SurfaceRulesEngine._BAND_TERRACOTTA] * 192
        i = 0
        while i < 192:
            i += rng.next_int_bound(5) + 1
            if i < 192:
                bands[i] = SurfaceRulesEngine._BAND_COLORS["ORANGE"]
            i += 1

        def make_bands(base_width, state):
            count = rng.next_int_between(6, 15)
            for _ in range(count):
                width = base_width + rng.next_int_bound(3)
                start = rng.next_int_bound(192)
                p = 0
                while start + p < 192 and p < width:
                    bands[start + p] = state
                    p += 1

        make_bands(1, SurfaceRulesEngine._BAND_COLORS["YELLOW"])
        make_bands(2, SurfaceRulesEngine._BAND_COLORS["BROWN"])
        make_bands(1, SurfaceRulesEngine._BAND_COLORS["RED"])
        white_count = rng.next_int_between(9, 15)
        i = 0
        start = 0
        while i < white_count and start < 192:
            bands[start] = SurfaceRulesEngine._BAND_COLORS["WHITE"]
            if start - 1 > 0 and rng.next_bool():
                bands[start - 1] = SurfaceRulesEngine._BAND_COLORS["LIGHT_GRAY"]
            if start + 1 < 192 and rng.next_bool():
                bands[start + 1] = SurfaceRulesEngine._BAND_COLORS["LIGHT_GRAY"]
            i += 1
            start += rng.next_int_bound(16) + 4
        return bands

    def get_band(self, x, y, z):
        """SurfaceSystem.getBand：y 层彩带色（clay_bands_offset 噪声偏移）。"""
        if self._clay_off is None:
            self._clay_off = self.s.noise("minecraft:clay_bands_offset")
        off = math.floor(self._clay_off.get_value(x, 0.0, z) * 4.0 + 0.5)  # Math.round
        return self._clay[(y + off + 192) % 192]

    # ---- 状态推进（对应 Context.updateXZ / updateY） ----
    def _update_xz(self, x, z):
        self.block_x, self.block_z = x, z
        self.surface_depth = int(
            self.s.noise("minecraft:surface").get_value(x, 0.0, z) * 2.75
            + 3.0 + _surface_random_double(self.pos_lo, self.pos_hi, x, 0, z) * 0.25)
        self._sec = None
        self._min = None
        self._biome = None

    def _update_y(self, stone_above, stone_below, water_height, block_y):
        self.stone_above, self.stone_below = stone_above, stone_below
        self.water_height = water_height
        self.block_y = block_y
        self._biome = None

    def _get_surface_secondary(self):
        if self._sec is None:
            self._sec = self.s.noise(
                "minecraft:surface_secondary").get_value(self.block_x, 0.0, self.block_z)
        return self._sec

    def _get_biome_key(self):
        if self._biome is None:
            self._biome = self.biome_at(self.block_x, self.block_y, self.block_z)
        return self._biome

    def _prelim_surface(self, x, z):
        """NoiseChunk.preliminarySurfaceLevel（坐标先量化为 4 的倍数）。"""
        qx = (x >> 2) << 2
        qz = (z >> 2) << 2
        return math.floor(self._preliminary(qx, 0, qz))

    def _min_surface_level(self, x, z):
        cell_x, cell_z = x >> 4, z >> 4
        b0, b1 = cell_x << 4, (cell_x + 1) << 4
        c0, c1 = cell_z << 4, (cell_z + 1) << 4
        p00 = self._prelim_surface(b0, c0)
        p10 = self._prelim_surface(b1, c0)
        p01 = self._prelim_surface(b0, c1)
        p11 = self._prelim_surface(b1, c1)
        dx = (x & 15) / 16.0
        dz = (z & 15) / 16.0
        return math.floor(_lerp(dz, _lerp(dx, p00, p10),
                                _lerp(dx, p01, p11))) + self.surface_depth - 8

    # ---- 条件编译 ----
    def _compile_cond(self, node):
        typ = node.get("type", "").split(":")[-1]
        tag = typ

        def _tag(fn):
            fn.__name__ = f"cond_{tag}"
            return fn

        if typ == "not":
            sub = self._compile_cond(node["invert"])
            def _nf(): return not sub()
            return _tag(_nf)

        if typ == "biome":
            raw = node["biome_is"]
            names = {n if n.startswith("minecraft:") else "minecraft:" + n
                     for n in (raw if isinstance(raw, list) else [raw])}
            def bio():
                return self._get_biome_key() in names
            return bio

        if typ == "noise_threshold":
            noise = node["noise"]
            lo = float(node["min_threshold"]); hi = float(node["max_threshold"])
            is3d = node.get("is_3d", False)
            n = self.s.noise(noise)
            def nt():
                v = (n.get_value(self.block_x, self.block_y, self.block_z) if is3d
                     else n.get_value(self.block_x, 0.0, self.block_z))
                return lo <= v <= hi
            return nt

        if typ == "vertical_gradient":
            rnd = node["random_name"]
            true_at = _vertical_anchor(node["true_at_and_below"])
            false_at = _vertical_anchor(node["false_at_and_above"])
            def vg():
                y = self.block_y
                if y <= true_at:
                    return True
                if y >= false_at:
                    return False
                prob = 1.0 - (y - true_at) / (false_at - true_at)
                return _surface_random_float(
                    self.pos_lo, self.pos_hi, self.block_x, y, self.block_z) < prob
            return vg

        if typ == "above_preliminary_surface":
            return lambda: self.block_y >= self._min_surface_level(
                self.block_x, self.block_z)

        if typ == "stone_depth":
            add = node["add_surface_depth"]
            offset = int(node["offset"])
            rng = int(node["secondary_depth_range"])
            ceiling = node["surface_type"] == "ceiling"
            def sd():
                depth = self.stone_below if ceiling else self.stone_above
                sdep = self.surface_depth if add else 0
                sec = (int(_map_lerp(self._get_surface_secondary(), -1.0, 1.0, 0.0, rng))
                       if rng else 0)
                return depth <= 1 + offset + sdep + sec
            return sd

        if typ == "y_above":
            add = node["add_stone_depth"]
            mult = int(node["surface_depth_multiplier"])
            anchor = _vertical_anchor(node["anchor"])
            def ya():
                return (self.block_y
                        + (self.stone_above if add else 0)) >= anchor + self.surface_depth * mult
            return ya

        if typ == "water":
            add = node["add_stone_depth"]
            offset = int(node["offset"])
            mult = int(node["surface_depth_multiplier"])
            def wa():
                if self.water_height == -(1 << 62):
                    return True
                return (self.block_y
                        + (self.stone_above if add else 0)) >= self.water_height + offset + self.surface_depth * mult
            wa.__name__ = f"water(a{int(add)},o{offset},m{mult})"
            return wa

        if typ == "hole":
            return lambda: self.surface_depth <= 0

        if typ == "steep":
            def st():
                x, z = self.block_x, self.block_z
                cx, cz = x & 15, z & 15
                z_n = (z - 1) if cz > 0 else z
                z_s = (z + 1) if cz < 15 else z
                h_n = self.surface_top(x, z_n)
                h_s = self.surface_top(x, z_s)
                if h_s >= h_n + 4:
                    return True
                x_w = (x - 1) if cx > 0 else x
                x_e = (x + 1) if cx < 15 else x
                h_w = self.surface_top(x_w, z)
                h_e = self.surface_top(x_e, z)
                return h_w >= h_e + 4
            return st

        if typ == "temperature":
            return self._temperature

        raise NotImplementedError(f"未支持的 surface 条件: {typ}")

    # ---- 规则编译 ----
    def _compile_surface(self, node):
        typ = node.get("type", "").split(":")[-1]

        if typ == "block":
            rs = node["result_state"]
            name = rs["Name"]
            props = tuple(sorted(rs.get("Properties", {}).items()))
            def blk():
                if self.trace is not None:
                    self.trace.append((self.block_y, "BLOCK", name))
                return (name, props)
            return blk

        if typ == "sequence":
            subs = [self._compile_surface(s) for s in node["sequence"]]
            def seq():
                for sub in subs:
                    r = sub()
                    if r is not None:
                        return r
                return None
            return seq

        if typ == "condition":
            cond = self._compile_cond(node["if_true"])
            cond_tag = cond.__name__
            then = self._compile_surface(node["then_run"])
            def cnd():
                c = cond()
                if self.trace is not None:
                    self.trace.append((self.block_y, "COND", c, cond_tag))
                return then() if c else None
            return cnd

        if typ == "bandlands":
            def bl():
                nm = self.get_band(self.block_x, self.block_y, self.block_z)
                if self.trace is not None:
                    self.trace.append((self.block_y, "BLOCK", nm))
                return (nm, ())
            return bl

        raise NotImplementedError(f"未支持的 surface 规则: {typ}")

    def _temperature(self):
        # SurfaceRules.TemperatureCondition：coldEnoughToSnow = temperature < 0.15F
        # 温度 = Biome.getHeightAdjustedTemperature(blockPos, seaLevel)
        key = self._get_biome_key()
        t = self.biome_temperature(key, self.block_x, self.block_y, self.block_z)
        return t < 0.15

    def surface_column(self, x, z, fill_top, first_water_y=None):
        """整列 surface 结果（顶层方块 + 最终顶 y）。

        设计取舍：单点 top_block 已在 1536 列 ×3 seed 上与官方 100% 一致
        （1600+ 列 fill+surface 全绿），故这里保持单点主路径不变，只在
        两者会改变列顶的地方追加：
          * eroded_badlands extension：抬高列顶后重跑单点规则；
          * frozen_ocean extension：冰面/雪覆盖。

        返回 (final_top_y, final_top_block)。"""
        biome_key = self._get_biome_key_at(x, fill_top, z)
        short = _block_short(biome_key)
        fill = getattr(self, "_fill_block_at", None)

        # ---- 1) eroded badlands：先抬高列顶 ----
        top_y = fill_top
        if short == "eroded_badlands" and fill is not None:
            got = self.eroded_badlands_extension(x, z, fill_top + 1)
            if got:
                top_y = max(got)

        # ---- 2) 单点规则（已验证路径） ----
        first_water = first_water_y if (first_water_y is not None
                                        and first_water_y > top_y) else None
        top_block = self._rule_block_at(x, top_y, z, first_water,
                                        column_top=top_y)

        # ---- 3) frozen ocean：冰面/雪覆盖 ----
        if short in ("frozen_ocean", "deep_frozen_ocean") and fill is not None:
            melt = self.biome_temperature(biome_key, x, _SURFACE_SEA_LEVEL,
                                          z) > 0.1
            res = self.frozen_ocean_extension(
                x, z, fill_top + 1, self._min_surface_level(x, z),
                _SURFACE_SEA_LEVEL, melt)
            if res:
                ice_blocks, _ = res
                topmost = max(ice_blocks)
                if topmost > top_y:
                    top_y = topmost
                    top_block = ice_blocks[topmost]
        return top_y, top_block

    def _get_biome_key_at(self, x, y, z):
        """按 (x,y,z) 查群系键（不改 self 状态，纯函数式）。"""
        return self.biome_at(x, y, z)

    def _rule_block_at(self, x, y, z, first_water_y, column_top=None):
        """在 y 处套 surface 规则。

        stoneAboveDepth（L121/129/148）：自列顶向下遍历时，每遇一个
        "非空气且非流体"块 +1，遇空气清零。故在 y 处 = column_top - y + 1
        （column_top 为遍历起点 height，扩展抬高后随之变化）。
        stoneBelowDepth（L149）：y - nextCeilingStoneY + 1，nextCeilingStoneY
        为 y 下方第一个非石段的下一个石行。
        """
        self._update_xz(x, z)
        under_water = first_water_y is not None and first_water_y > y
        top = column_top if column_top is not None else y
        stone_above = max(1, top - y + 1)
        if self.solid_at is not None:
            ny = y - 1
            while ny >= _SURFACE_MIN_Y and self.solid_at(x, ny, z):
                ny -= 1
            next_ceiling = ny + 1
            stone_below = y - next_ceiling + 1
        else:
            stone_below = 1
        water_height = (_SURFACE_SEA_LEVEL if under_water else -(1 << 62))
        self._update_y(stone_above, stone_below, water_height, y)
        r = self.root_apply()
        return r[0] if r else _DEFAULT_BLOCK

    # ---- 顶层方块（topMaterial 语义） ----
    def top_block(self, x, y, z, under_water):
        """返回顶层方块 BlockState 元组 (name, props) 或 None。

        waterHeight 语义（SurfaceSystem 列构建）：
        列遍历遇水块设 waterHeight = y+1（水面块顶部），且自顶部向下保持，
        故海底块上方水体时的 waterHeight = 海平面高度（_SURFACE_SEA_LEVEL）。
        under_water = 该块顶部上方存在水体（被海水淹没）。

        stoneBelowDepth 语义（buildSurface L136-149）：自 y-1 向下 lookahead
        到第一个非石（空气/流体，越界=空气）行 nc，stoneBelow = y-nc+1。
        顶层块 stoneAbove 恒 1（进规则时 old=石）。"""
        self._update_xz(x, z)
        water_height = (_SURFACE_SEA_LEVEL if under_water else -(1 << 62))
        stone_below = 1
        if self.solid_at is not None:
            ny = y - 1
            while ny >= _SURFACE_MIN_Y and self.solid_at(x, ny, z):
                ny -= 1
            # ny = 第一个非石行（或 _SURFACE_MIN_Y-1 若全实心）
            stone_below = y - (ny + 1) + 1 if ny + 1 <= y else 1
        self._update_y(1, stone_below, water_height, y)
        return self.root_apply()

    def root_apply(self):
        return self.rule_root()


def _map_lerp(v, lo, hi, tlo, thi):
    return tlo + (thi - tlo) * (v - lo) / (hi - lo)


def _map_lin(value, from_min, from_max, to_min, to_max):
    """Mth.map：线性映射（分母为 0 时返回 to_min）。"""
    if from_max == from_min:
        return to_min
    t = (value - from_min) / (from_max - from_min)
    return to_min + t * (to_max - to_min)


def _map_clamped(value, from_min, from_max, to_min, to_max):
    """Mth.clampedMap：t 钳制到 [0,1] 后线性映射。"""
    if from_max == from_min:
        return to_min
    t = _clamp((value - from_min) / (from_max - from_min), 0.0, 1.0)
    return to_min + t * (to_max - to_min)


def _quantize(value, q):
    return math.floor(value / q) * q


_WAY_BELOW_MIN_Y = -32512   # DimensionType.WAY_BELOW_MIN_Y = MIN_Y(-2032) << 4
                            # （26.2 Y_SIZE 扩大；1.18~1.21 时代为 -192<<4 = -3072）


def _vertical_anchor(anchor):
    if "absolute" in anchor:
        return int(anchor["absolute"])
    if "above_bottom" in anchor:
        return _SURFACE_MIN_Y + int(anchor["above_bottom"])
    if "below_top" in anchor:
        return _SURFACE_MIN_Y + _SURFACE_GEN_DEPTH - 1 - int(anchor["below_top"])
    raise ValueError(f"未知 VerticalAnchor: {anchor}")


def _block_short(name):
    return name.split(":")[-1]


# 群系 base 温度 ClimateSettings.temperature（26.2 官方 biome JSON 全量提取，
# 见 _BIOME_BASE_TEMP_FILE）。手写表仅作兜底，缺失时按 0.8（vanilla 默认）。
_BIOME_BASE_TEMP_FALLBACK = {
    "frozen_ocean": 0.0, "deep_frozen_ocean": 0.5, "frozen_river": 0.0,
    "snowy_plains": 0.0, "snowy_beach": 0.05, "snowy_taiga": -0.5,
    "snowy_slopes": -0.3, "jagged_peaks": -0.7, "frozen_peaks": -0.7,
    "grove": -0.2, "ice_spikes": 0.0, "ocean": 0.5, "lukewarm_ocean": 0.5,
    "warm_ocean": 0.5, "cold_ocean": 0.5, "deep_ocean": 0.5,
    "deep_cold_ocean": 0.5, "deep_lukewarm_ocean": 0.5, "deep_warm_ocean": 0.5,
    "beach": 0.8, "desert": 2.0, "plains": 0.8, "forest": 0.7,
    "taiga": 0.25, "windswept_hills": 0.2, "windswept_gravelly_hills": 0.2,
    "windswept_savanna": 2.0, "stony_peaks": 1.0, "stony_shore": 0.2,
    "mangrove_swamp": 0.9, "swamp": 0.8, "mushroom_fields": 0.9,
}
_BIOME_BASE_TEMP_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_native", "worldgen", "26.2",
    "biome_temps.json")


def _load_biome_temps():
    """官方 biome temperature 全量表（优先磁盘 JSON，缺失回退手写表）。"""
    table = dict(_BIOME_BASE_TEMP_FALLBACK)
    try:
        with open(_BIOME_BASE_TEMP_FILE, encoding="utf-8") as f:
            table.update(json.load(f))
    except Exception:
        pass
    return table


_BIOME_BASE_TEMP = _load_biome_temps()


# ---------------------------------------------------------------------------
# NoiseBasedAquifer（MC 26.2 主世界含水层）
# 逐条对照 Aquifer.java / NoiseBasedAquifer.java 反编译源码。
# 含水层是在 final density<=0 时判定"放空气/流体/还是判为维度初始方块(实心)"
# 的系统，唯一能把 density 略负位置垫实成地表的环节。
# 本实现完全独立于 surface 覆盖层；只复用已独立验证的密度场/router。
# ---------------------------------------------------------------------------
_AQ_SURF_OFFSETS = [(0, 0), (-2, -1), (-1, -1), (0, -1), (1, -1),
                    (-3, 0), (-2, 0), (-1, 0), (1, 0),
                    (-2, 1), (-1, 1), (0, 1), (1, 1)]
_AQ_WAY_BELOW = _WAY_BELOW_MIN_Y


class NoiseBasedAquifer:
    """主世界含水层：compute_substance(x,y,z,density)->(is_solid, block)。
    block 仅在非实心时为流体名/空气。

    依赖 router：barrier / fluid_level_floodedness / fluid_level_spread /
    lava / erosion / depth / preliminary_surface_level（均用引擎已编译函数）。
    """

    def __init__(self, sampler):
        self.s = sampler
        self.pos_lo, self.pos_hi = sampler._pos_lo, sampler._pos_hi
        ow = os.path.join(os.path.dirname(sampler._df_dir),
                          "noise_settings", "overworld.json")
        with open(ow, encoding="utf-8") as f:
            self._router = json.load(f)["noise_router"]
        self._sea = _SURFACE_SEA_LEVEL
        # 缓存
        self._loc_cache = {}
        self._status_cache = {}
        self._prelim_cache = {}
        self._skip_cache = {}

    # ---- router 函数（惰性） ----
    def _r(self, key):
        v = getattr(self, "_r_" + key, None)
        if v is None:
            v = self.s._make(self._router[key])
            setattr(self, "_r_" + key, v)
        return v

    def barrier(self):            return self._r("barrier")
    def flooded(self):            return self._r("fluid_level_floodedness")
    def spread(self):             return self._r("fluid_level_spread")
    def lava(self):               return self._r("lava")
    def erosion(self):            return self._r("erosion")
    def depth(self):              return self._r("depth")
    def prelim(self):             return self._r("preliminary_surface_level")

    # ---- 网格辅助 ----
    def _grid_x(self, c): return c >> 4
    def _grid_y(self, c): return math.floor(c / 12)
    def _grid_z(self, c): return c >> 4
    def _from_grid_x(self, g, o): return (g << 4) + o
    def _from_grid_y(self, g, o): return g * 12 + o
    def _from_grid_z(self, g, o): return (g << 4) + o

    def _cell_loc(self, gx, gy, gz):
        key = (gx, gy, gz)
        loc = self._loc_cache.get(key)
        if loc is None:
            rng = Xoroshiro128(_get_seed(gx, gy, gz) ^ self._aq_lo(), self._aq_hi())
            loc = (self._from_grid_x(gx, rng.next_int_bound(10)),
                   self._from_grid_y(gy, rng.next_int_bound(9)),
                   self._from_grid_z(gz, rng.next_int_bound(10)))
            self._loc_cache[key] = loc
        return loc

    def _aq_lo(self):
        lo = getattr(self, "_aqlo", None)
        if lo is None:
            self._aqlo, self._aqhi = Xoroshiro128.from_hash_xor(
                "minecraft:aquifer", self.pos_lo, self.pos_hi).fork_positional()
        return self._aqlo
    def _aq_hi(self):
        self._aq_lo()
        return self._aqhi

    def _prelim_surface(self, x, z):
        qx = x // 4 * 4
        qz = z // 4 * 4
        key = (qx, qz)
        v = self._prelim_cache.get(key)
        if v is None:
            v = math.floor(self.prelim()(qx, 0, qz))
            self._prelim_cache[key] = v
        return v

    @staticmethod
    def _adjust_surface(s):
        return s + 8

    # ---- 26.2 新增：chunk 级 skipSamplingAboveY ----
    # Aquifer.NoiseBasedAquifer 构造函数 L134-138 / computeSubstance L159-162：
    # 取本 chunk 含水格网四角扩样的最大 preliminarySurfaceLevel(+8)，
    # 高于该 skip 线的方块一律不做压力垫装（直接 globalFluid.at(y)）。
    def _chunk_skip_y(self, x, z):
        key = (x >> 4, z >> 4)
        v = self._skip_cache.get(key)
        if v is None:
            cx, cz = key
            min_gx = (cx * 16 - 5) >> 4
            max_gx = (((cx * 16 + 15) - 5) >> 4) + 1
            min_gz = (cz * 16 - 5) >> 4
            max_gz = (((cz * 16 + 15) - 5) >> 4) + 1
            x0, x1 = min_gx << 4, (max_gx << 4) + 9
            z0, z1 = min_gz << 4, (max_gz << 4) + 9
            mx = -2147483648
            zz = z0
            while zz <= z1:
                xx = x0
                while xx <= x1:
                    lv = self._prelim_surface(xx, zz)
                    if lv > mx:
                        mx = lv
                    xx += 4
                zz += 4
            skip_grid_y = math.floor((mx + 8 + 12) / 12) + 1
            v = skip_grid_y * 12 + 11 - 1
            self._skip_cache[key] = v
        return v

    def _is_deep_dark(self, x, y, z):
        return self.erosion()(x, y, z) < -0.225 and self.depth()(x, y, z) > 0.9

    def _compute_random_fluid_surface(self, x, y, z, lowest_prelim):
        cx = math.floor(x / 16); cy = math.floor(y / 40); cz = math.floor(z / 16)
        mid = cy * 40 + 20
        q = _quantize(self.spread()(cx, cy, cz) * 10.0, 3)
        target = mid + q
        return min(lowest_prelim, target)

    def _compute_fluid_type(self, x, y, z, global_fluid, fluid_surface):
        ftype = global_fluid[1]
        if (fluid_surface <= -10 and fluid_surface != _AQ_WAY_BELOW
                and global_fluid[1] != "minecraft:lava"):
            cx = math.floor(x / 64); cy = math.floor(y / 40); cz = math.floor(z / 64)
            if abs(self.lava()(cx, cy, cz)) > 0.3:
                ftype = "minecraft:lava"
        return ftype

    def _pick_fluid(self, x, y, z):
        """基础流体选择器：返回 (level, block)。"""
        if y < min(-54, self._sea):
            return (-54, "minecraft:lava")
        return (self._sea, "minecraft:water")

    @staticmethod
    def _status_at(status, y):
        """FluidStatus.at(y)：流体仅在 y<level 时填充。"""
        level, block = status
        return block if y < level else "minecraft:air"

    def _compute_fluid(self, x, y, z):
        """返回流体状况 (level, block)。"""
        global_fluid = self._pick_fluid(x, y, z)
        lowest_prelim = 1 << 31
        top = y + 12; bottom = y - 12
        center_under_global = False
        for off in _AQ_SURF_OFFSETS:
            sx = x + (off[0] << 4); sz = z + (off[1] << 4)
            prelim_level = self._prelim_surface(sx, sz)
            adj = self._adjust_surface(prelim_level)
            start = (off[0] == 0 and off[1] == 0)
            if start and bottom > adj:
                return global_fluid
            top_pokes = top > adj
            if top_pokes or start:
                gf = self._pick_fluid(sx, adj, sz)
                if self._status_at(gf, adj) != "minecraft:air":
                    if start:
                        center_under_global = True
                    if top_pokes:
                        return gf
            lowest_prelim = min(lowest_prelim, prelim_level)
        fluid_surface = self._compute_surface_level(
            x, y, z, global_fluid, lowest_prelim, center_under_global)
        return (fluid_surface, self._compute_fluid_type(x, y, z, global_fluid, fluid_surface))

    def _compute_surface_level(self, x, y, z, global_fluid, lowest_prelim, center_at_under):
        if self._is_deep_dark(x, y, z):
            partially = -1.0; fully = -1.0
        else:
            dist_below = lowest_prelim + 8 - y
            factor = _map_clamped(dist_below, 0.0, 64.0, 1.0, 0.0) if center_at_under else 0.0
            fnoise = _clampf(self.flooded()(x, y, z), -1.0, 1.0)
            fully_thresh = _map_lin(factor, 1.0, 0.0, -0.3, 0.8)
            partially_thresh = _map_lin(factor, 1.0, 0.0, -0.8, 0.4)
            partially = fnoise - partially_thresh
            fully = fnoise - fully_thresh
        if fully > 0.0:
            return global_fluid[0]
        if partially > 0.0:
            return self._compute_random_fluid_surface(x, y, z, lowest_prelim)
        return _AQ_WAY_BELOW

    def _get_status(self, gx, gy, gz):
        key = (gx, gy, gz)
        st = self._status_cache.get(key)
        if st is None:
            loc = self._cell_loc(gx, gy, gz)
            st = self._compute_fluid(loc[0], loc[1], loc[2])
            self._status_cache[key] = st
        return st

    @staticmethod
    def _similarity(d1, d2):
        return 1.0 - (d2 - d1) / 25.0

    def _calculate_pressure(self, x, y, z, s1, s2, barrier_val):
        t1 = self._status_at(s1, y); t2 = self._status_at(s2, y)
        mix = ((t1 == "minecraft:lava" and t2 == "minecraft:water") or
               (t1 == "minecraft:water" and t2 == "minecraft:lava"))
        if not mix:
            ydiff = abs(s1[0] - s2[0])
            if ydiff == 0:
                return 0.0
            avg = 0.5 * (s1[0] + s2[0])
            how_far = y + 0.5 - avg
            base = ydiff / 2.0
            dist = base - abs(how_far)
            if how_far > 0.0:
                cp = 0.0 + dist
                gradient = cp / 1.5 if cp > 0.0 else cp / 2.5
            else:
                cp = 3.0 + dist
                gradient = cp / 3.0 if cp > 0.0 else cp / 10.0
            if -2.0 <= gradient <= 2.0:
                noise_val = barrier_val if barrier_val is not None else self.barrier()(x, y, z)
            else:
                noise_val = 0.0
            return 2.0 * (noise_val + gradient)
        return 2.0

    def compute_substance(self, x, y, z, density):
        """返回 (is_solid, block)；block 仅当非实心时为流体/空气。"""
        if density > 0.0:
            return (True, None)
        global_fluid = self._pick_fluid(x, y, z)
        # 26.2: 地表带之上跳过含水层压力（skipSamplingAboveY）
        if y > self._chunk_skip_y(x, z):
            return (False, self._status_at(global_fluid, y))
        if self._status_at(global_fluid, y) == "minecraft:lava":
            return (False, "minecraft:lava")
        xa = self._grid_x(x + (-5)); ya = self._grid_y(y + 1); za = self._grid_z(z + (-5))
        ds1 = ds2 = ds3 = ds4 = (1 << 30)
        ci1 = ci2 = ci3 = ci4 = None
        for dx in (0, 1):
            for dy in (-1, 0, 1):
                for dz in (0, 1):
                    gx = xa + dx; gy = ya + dy; gz = za + dz
                    loc = self._cell_loc(gx, gy, gz)
                    ndx = loc[0] - x; ndy = loc[1] - y; ndz = loc[2] - z
                    newd = ndx * ndx + ndy * ndy + ndz * ndz
                    key = (gx, gy, gz)
                    if ds1 >= newd:
                        ds4, ci4, ds3, ci3, ds2, ci2 = ds3, ci3, ds2, ci2, ds1, ci1
                        ds1, ci1 = newd, key
                    elif ds2 >= newd:
                        ds4, ci4, ds3, ci3 = ds3, ci3, ds2, ci2
                        ds2, ci2 = newd, key
                    elif ds3 >= newd:
                        ds4, ci4 = ds3, ci3
                        ds3, ci3 = newd, key
                    elif ds4 >= newd:
                        ds4, ci4 = newd, key
        s1 = self._get_status(*ci1)
        sim12 = self._similarity(ds1, ds2)
        fluid_state = self._status_at(s1, y)
        if sim12 <= 0.0:
            return (False, fluid_state)
        if (fluid_state == "minecraft:water"
                and self._status_at(self._pick_fluid(x, y - 1, z), y - 1) == "minecraft:lava"):
            return (False, fluid_state)
        s2 = self._get_status(*ci2)
        bval = None
        barrier12 = sim12 * self._calculate_pressure(x, y, z, s1, s2, bval)
        if density + barrier12 > 0.0:
            return (True, None)
        s3 = self._get_status(*ci3)
        sim13 = self._similarity(ds1, ds3)
        if sim13 > 0.0:
            bar13 = sim12 * sim13 * self._calculate_pressure(x, y, z, s1, s3, bval)
            if density + bar13 > 0.0:
                return (True, None)
        sim23 = self._similarity(ds2, ds3)
        if sim23 > 0.0:
            bar23 = sim12 * sim23 * self._calculate_pressure(x, y, z, s2, s3, bval)
            if density + bar23 > 0.0:
                return (True, None)
        return (False, fluid_state)


# ---------------------------------------------------------------------------
# fill 块级主循环（对应 NoiseBasedChunkGenerator.doFill + NoiseChunk.blockStateRule）
# ---------------------------------------------------------------------------
def fill_chunk_3d(sampler, chunk_x, chunk_z, min_y=-64, height=384,
                  final_density=None, aquifer=None):
    """补全 fill 阶段主循环：对给定区块逐块判定实心/流体，生成完整 3D 方块场。

    等价于真实 NoiseBasedChunkGenerator.doFill：
      density = cacheAllInCell(finalDensity + beardifier).compute(ctx)  # 引擎 build_final_density
      state   = aquifer.computeSubstance(ctx, density)
         density>0            -> 实心（默认方块）
         否则                  -> 含水层判流体/空气（barrier 加压可垫为实心）

    返回 dict: {(x,y,z): block_name}，仅含非空气方块。block_name 形如
    "minecraft:stone"/"minecraft:water" 等；实心未指定时用 default_block（overworld 为 stone）。

    参数：
      final_density: 若传 None 则自动 sampler.build_final_density()。
      aquifer:       若传 None 则自动 NoiseBasedAquifer(sampler)。
    """
    import json as _json
    if final_density is None:
        final_density = sampler.build_final_density()
    if aquifer is None:
        aquifer = NoiseBasedAquifer(sampler)

    ow = os.path.join(os.path.dirname(sampler._df_dir),
                      "noise_settings", "overworld.json")
    with open(ow, encoding="utf-8") as _f:
        _settings = _json.load(_f)
    default_block = _settings.get("default_block", {}).get("Name", "minecraft:stone")

    cx0, cz0 = chunk_x * 16, chunk_z * 16
    top_y = min_y + height
    blocks = {}
    for x in range(cx0, cx0 + 16):
        for z in range(cz0, cz0 + 16):
            for y in range(min_y, top_y):
                d = final_density(x, y, z)
                is_solid, block = aquifer.compute_substance(x, y, z, d)
                if is_solid:
                    blocks[(x, y, z)] = default_block
                elif block and block != "minecraft:air":
                    blocks[(x, y, z)] = block
    return blocks


def surface_height_fill(sampler, final_density, aquifer, x, z,
                        min_y=-64, max_y=320):
    """fill 主循环语义下的地表高度：最高一个 compute_substance 判实心的 y。

    与真实地表定义一致：fill 阶段最高实心块 = compute_substance(density) 判实心的最高 y。
    """
    for y in range(max_y, min_y - 1, -1):
        d = final_density(x, y, z)
        solid, _ = aquifer.compute_substance(x, y, z, d)
        if solid:
            return y
    return min_y


if __name__ == "__main__":
    s = build_sampler(1)
    sloped = s.build("minecraft:overworld/sloped_cheese")
    final = s.build_final_density()
    for (x, z) in [(0, 0), (8, 8), (100, 100), (-100, -100)]:
        sv = sloped(x, 64, z)
        print(f"({x},{z}) sloped_cheese@64={sv:.6f} final@64={final(x,64,z):.6f}")