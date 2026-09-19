# -*- coding: utf-8 -*-
"""1.18+ 群系噪声生成器（纯 Python 位级实现，参数逐项对齐 cubiomes 源码）。

用途：
    世界种子精化（SeedReverser 二期）：给定 48 位结构种候选与若干群系
    观测点，枚举高位 16 bit 得到完整 64 位世界种子（见 world_seed_refine.py）。

实现范围（仅本文件用到的子集，全部逐行核对自 cubiomes）：
    - rng.h          L185-248  Xoroshiro128+ / SplitMix64（xSetSeed）
    - noise.c        L79-107   xPerlinInit（3 次 xNextDouble + Fisher-Yates 256）
    - noise.c        L391-446  xOctaveInit（参数级状态 + md5("octave_-N")）
    - noise.c        L538-572  xDoublePerlinInit / sampleDoublePerlin（337/331）
    - biomenoise.c   L844-907  6 个气候参数的 MD5 种子常量与八度参数
    - biomenoise.c   L946-1133 depth 样条（initBiomeNoise 系列构建函数）
    - biomenoise.c   L1141-1191 sampleBiomeNoise（shift 采样 + np 量化）
    - biomenoise.c   L1369-1484 climateToBiome（btree 最近邻 R 树搜索）
    - tables/btree*.h          1.18 / 1.19 / 1.20 / 1.21 群系树数据表

浮点精度说明（与 cubiomes bit 级一致的必要约定）：
    - Minecraft 原实现中气候参数噪声在 float(32 位) 下累加；本文件在
      对应位置用 np.float32 截断模拟，其余运算用 float64。
    - 样条构建/求值全程 float32；depth 的常量运算是 double。
    - np 量化：(int64)(10000.0F * v) —— 先 float32 乘法再向零截断。

纯 Python 版本用于正确性基准与回归测试；生产枚举走 _native C 扩展
（_biome_refine），本模块在纯 Python 下亦完整可用。
"""

import os

import numpy as np

# ======================================================================
# 版本映射与 btree 数据表（数据由 extract 脚本从 cubiomes tables/ 生成）
# ======================================================================

# MCHelper 版本键 -> cubiomes btree（climateToBiome 的版本分界：
# >=1.21_WD -> 21wd；版本线收敛为 26.2 / 1.21.11 / 1.21 三档；
# npz 内 btree18/19/20 数据保留供 native 槽表加载，Python 层不再引用）
VERSION_TO_BTREE = {
    "1.21": "btree21wd",
    "1.21.11": "btree21wd",  # 1.21.x 线共用 21wd 群系树（MapPreviewer 坐标地图版本键）
    "26.2": "btree262",  # 26.2 混沌更新：仅新增硫磺洞穴群系，其余继承 21wd
}

_BTREE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "btree_tables.npz")


class BTree:
    """一个版本的群系树（最近邻搜索数据）。"""

    __slots__ = ("name", "order", "steps", "param", "nodes", "len")

    def __init__(self, name, order, steps, param, nodes):
        self.name = name
        self.order = int(order)
        self.steps = np.asarray(steps, dtype=np.uint32)
        self.param = np.asarray(param, dtype=np.int64)
        self.nodes = np.asarray(nodes, dtype=np.uint64)
        self.len = len(self.nodes)


_BTREES: dict[str, BTree] = {}


def _load_btree(name: str) -> BTree:
    tree = _BTREES.get(name)
    if tree is None:
        with np.load(_BTREE_FILE) as z:
            # npz 键：{name}_order（R 树分支因子）/ _steps / _param / _nodes
            tree = BTree(name, int(z[f"{name}_order"]), z[f"{name}_steps"],
                         z[f"{name}_param"], z[f"{name}_nodes"])
        _BTREES[name] = tree
    return tree


def get_btree(version_key: str) -> BTree:
    try:
        return _load_btree(VERSION_TO_BTREE[version_key])
    except KeyError:
        raise ValueError(f"版本 {version_key} 不支持群系精化"
                         f"（仅 {' / '.join(VERSION_TO_BTREE)}）")


# ======================================================================
# Xoroshiro128+ 与 SplitMix64（rng.h L185-248）
# ======================================================================

_M64 = (1 << 64) - 1
_XL = 0x9E3779B97F4A7C15   # 黄金比率 gamma（SplitMix64 步进）
_XH = 0x6A09E667F3BCC909   # md5 待定常量（xSetSeed 初值异或）
_MUL_A = 0xBF58476D1CE4E5B9
_MUL_B = 0x94D049BB133111EB

# MD5 常量核对：math.sqrt(5)*(1+sqrt(5))/4 与 2^64/(1+sqrt(5)) 截断值
assert _XL == 0x9E3779B97F4A7C15


def _rotl64(x: int, k: int) -> int:
    return ((x << k) | (x >> (64 - k))) & _M64


def _rotr64(x: int, k: int) -> int:
    return ((x >> k) | (x << (64 - k))) & _M64


def _mul_inv(a: int) -> int:
    """模 2^64 乘法逆元（Newton-Raphson）。"""
    x = a  # 初值任意奇数位正确即可，3 轮收敛（2^5 -> 2^64）
    for _ in range(6):
        x = (x * (2 - a * x)) & _M64
    return x


def splitmix64(x: int) -> int:
    """SplitMix64 正向（等价 xSetSeed 内部管线，rng.h L191-198）。"""
    x = (x + _XL) & _M64
    z = x
    z = ((z ^ (z >> 30)) * _MUL_A) & _M64
    z = ((z ^ (z >> 27)) * _MUL_B) & _M64
    return z ^ (z >> 31)


def splitmix64_inverse(y: int) -> int:
    """SplitMix64 逆向：由输出恢复输入（完全可逆）。"""
    z = y
    z ^= z >> 31
    z = (z * _mul_inv(_MUL_B)) & _M64
    z ^= z >> 27
    z = (z * _mul_inv(_MUL_A)) & _M64
    z ^= z >> 30
    return (z - _XL) & _M64


def x_set_seed(value: int) -> tuple[int, int]:
    """rng.h xSetSeed：世界种子 -> Xoroshiro 初始状态 (lo, hi)。"""
    l = (value ^ _XH) & _M64
    h = (l + _XL) & _M64
    l = ((l ^ (l >> 30)) * _MUL_A) & _M64
    h = ((h ^ (h >> 30)) * _MUL_A) & _M64
    l = ((l ^ (l >> 27)) * _MUL_B) & _M64
    h = ((h ^ (h >> 27)) * _MUL_B) & _M64
    l = l ^ (l >> 31)
    h = h ^ (h >> 31)
    return l, h


def _xor_shift_inv(y: int, k: int) -> int:
    """逆 x ^= x >> k：x = y ^ (y>>k) ^ (y>>2k) ^ ...（直到移位 >= 64）。"""
    x = y
    shift = k
    while shift < 64:
        x ^= y >> shift
        shift += k
    return x & _M64


def x_set_seed_inverse(lo: int, hi: int) -> int:
    """xSetSeed 逆向：由最终状态 (lo, hi) 恢复世界种子。

    推导（xSetSeed 各步皆可逆）：
        lo/hi 侧各自逆序撤 ^>>31、乘 B、^>>27、乘 A、^>>30；
        hi -= lo 撤 h = l + XL；lo ^ XH 即原种子。
    注意 ^>>k 的逆是多项式迭代（_xor_shift_inv），单次异或不够。
    """
    l = _xor_shift_inv(lo, 31)
    l = (l * _mul_inv(_MUL_B)) & _M64
    l = _xor_shift_inv(l, 27)
    l = (l * _mul_inv(_MUL_A)) & _M64
    l = _xor_shift_inv(l, 30)

    h = _xor_shift_inv(hi, 31)
    h = (h * _mul_inv(_MUL_B)) & _M64
    h = _xor_shift_inv(h, 27)
    h = (h * _mul_inv(_MUL_A)) & _M64
    h = _xor_shift_inv(h, 30)

    h = (h - l) & _M64          # 撤 h = l + XL
    return (l ^ _XH) & _M64


def x_set_seed_inverse_world(value_state: tuple[int, int]) -> int:
    """由 (lo, hi) 恢复世界种子（与 x_set_seed_inverse 等价，供测试）。"""
    return x_set_seed_inverse(value_state[0], value_state[1])


class Xoroshiro:
    """可变状态 Xoroshiro128+（rng.h L180-241）。"""

    __slots__ = ("lo", "hi")

    def __init__(self, lo: int, hi: int):
        self.lo = lo & _M64
        self.hi = hi & _M64

    @classmethod
    def from_seed(cls, value: int) -> "Xoroshiro":
        lo, hi = x_set_seed(value)
        return cls(lo, hi)

    def next_long(self) -> int:
        l = self.lo
        h = self.hi
        n = (_rotl64((l + h) & _M64, 17) + l) & _M64
        h ^= l
        self.lo = _rotl64(l, 49) ^ h ^ ((h << 21) & _M64)
        self.hi = _rotl64(h, 28)
        return n

    def next_int(self, n: int) -> int:
        """rng.h xNextInt：bound 取 32 位乘法高位（Lemon 风格拒绝采样）。"""
        if n <= 0:
            raise ValueError("bound must be positive")
        r = (self.next_long() & 0xFFFFFFFF) * n
        threshold = ((~n + 1) & 0xFFFFFFFF) % n
        while (r & 0xFFFFFFFF) < threshold:
            r = (self.next_long() & 0xFFFFFFFF) * n
        return r >> 32

    def next_double(self) -> float:
        return (self.next_long() >> (64 - 53)) * 1.1102230246251565E-16


def x_next_double(xr: "Xoroshiro") -> float:
    """rng.h xNextDouble（模块级函数，供 x_perlin_init 用）。"""
    return xr.next_double()


def x_next_long_state(lo: int, hi: int) -> tuple[int, int, int]:
    """无状态版 xNextLong：返回 (输出, 新 lo, 新 hi)。"""
    n = (_rotl64((lo + hi) & _M64, 17) + lo) & _M64
    h = hi ^ lo
    new_lo = _rotl64(lo, 49) ^ h ^ ((h << 21) & _M64)
    new_hi = _rotl64(h, 28)
    return n, new_lo, new_hi


# ======================================================================
# md5("octave_-N") 常量表与八度参数（noise.c L394-415）
# ======================================================================

# md5_octave_n[i] 对应 octave_(i-12)，索引 12+omin+i
MD5_OCTAVE_N = (
    (0xb198de63a8012672, 0x7b84cad43ef7b5a8),  # "octave_-12"
    (0x0fd787bfbc403ec3, 0x74a4a31ca21b48b8),  # "octave_-11"
    (0x36d326eed40efeb2, 0x5be9ce18223c636a),  # "octave_-10"
    (0x082fe255f8be6631, 0x4e96119e22dedc81),  # "octave_-9"
    (0x0ef68ec68504005e, 0x48b6bf93a2789640),  # "octave_-8"
    (0xf11268128982754f, 0x257a1d670430b0aa),  # "octave_-7"
    (0xe51c98ce7d1de664, 0x5f9478a733040c45),  # "octave_-6"
    (0x6d7b49e7e429850a, 0x2e3063c622a24777),  # "octave_-5"
    (0xbd90d5377ba1b762, 0xc07317d419a7548d),  # "octave_-4"
    (0x53d39c6752dac858, 0xbcd1c5a80ab65b3e),  # "octave_-3"
    (0xb4a24d7a84e7677b, 0x023ff9668e89b5c4),  # "octave_-2"
    (0xdffa22b534c5f608, 0xb9b67517d3665ca9),  # "octave_-1"
    (0xd50708086cef4d7c, 0x6e1651ecc7f43309),  # "octave_0"
)

# lacuna_ini[-omin]（omin ∈ -12..0）
LACUNA_INI = (1.0, 0.5, 0.25, 1.0 / 8, 1.0 / 16, 1.0 / 32, 1.0 / 64,
              1.0 / 128, 1.0 / 256, 1.0 / 512, 1.0 / 1024, 1.0 / 2048,
              1.0 / 4096)

# persist_ini[len]（len ∈ 0..9）
PERSIST_INI = (0.0, 1.0, 2.0 / 3, 4.0 / 7, 8.0 / 15, 16.0 / 31, 32.0 / 63,
               64.0 / 127, 128.0 / 255, 256.0 / 511)

# amp_ini[len]（xDoublePerlinInit 修零后长度 0..9 的归一化幅值）
AMP_INI = (0.0, 5.0 / 6, 10.0 / 9, 15.0 / 12, 20.0 / 15, 25.0 / 18,
           30.0 / 21, 35.0 / 24, 40.0 / 27, 45.0 / 30)

# ======================================================================
# 气候参数常量（biomenoise.c L844-907，MD5 常量与八度参数逐项核对）
# ======================================================================

# 参数索引（biomenoise.h L118-127）
NP_TEMPERATURE = 0
NP_HUMIDITY = 1
NP_CONTINENTALNESS = 2
NP_EROSION = 3
NP_SHIFT = 4          # 不是真气候参数，用于局部扰动
NP_WEIRDNESS = 5
NP_MAX = 6

# (md5_lo, md5_hi, amplitudes, omin) ；large 变体单独列出
_CLIMATE_SMALL = {
    NP_SHIFT: ((0x080518cf6af25384, 0x3f3dfb40a54febd5),
               (1.0, 1.0, 1.0, 0.0), -3),
    NP_TEMPERATURE: ((0x5c7e6b29735f0d7f, 0xf7d86f1bbc734988),
                     (1.5, 0.0, 1.0, 0.0, 0.0, 0.0), -10),
    NP_HUMIDITY: ((0x81bb4d22e8dc168e, 0xf1c8b4bea16303cd),
                  (1.0, 1.0, 0.0, 0.0, 0.0, 0.0), -8),
    NP_CONTINENTALNESS: ((0x83886c9d0ae3a662, 0xafa638a61b42e8ad),
                         (1.0, 1.0, 2.0, 2.0, 2.0, 1.0, 1.0, 1.0, 1.0), -9),
    NP_EROSION: ((0xd02491e6058f6fd8, 0x4792512c94c17a80),
                 (1.0, 1.0, 0.0, 1.0, 1.0), -9),
    NP_WEIRDNESS: ((0xefc8ef4d36102b34, 0x1beeeb324a0f24ea),
                   (1.0, 2.0, 1.0, 0.0, 0.0, 0.0), -7),
}

_CLIMATE_LARGE = {
    NP_TEMPERATURE: ((0x944b0073edf549db, 0x4ff44347e9d22b96),
                     (1.5, 0.0, 1.0, 0.0, 0.0, 0.0), -12),
    NP_HUMIDITY: ((0x71b8ab943dbd5301, 0xbb63ddcf39ff7a2b),
                  (1.0, 1.0, 0.0, 0.0, 0.0, 0.0), -10),
    NP_CONTINENTALNESS: ((0x9a3f51a113fce8dc, 0xee2dbd157e5dcdad),
                         (1.0, 1.0, 2.0, 2.0, 2.0, 1.0, 1.0, 1.0, 1.0), -11),
    NP_EROSION: ((0x8c984b1f8702a951, 0xead7b1f92bae535f),
                 (1.0, 1.0, 0.0, 1.0, 1.0), -11),
}


# ======================================================================
# Perlin 噪声（noise.c L79-107 初始化 / L109-208 采样）
# ======================================================================

class Perlin:
    """单个 Perlin 八度（xPerlinInit 产物）。"""

    __slots__ = ("a", "b", "c", "d", "h2", "d2", "t2")

    def __init__(self):
        self.d = list(range(256)) + [0]  # 257 字节（idx[256]=idx[0]）


def x_perlin_init(xr: Xoroshiro) -> Perlin:
    """noise.c xPerlinInit：3 次 xNextDouble 偏移 + Fisher-Yates 洗牌。"""
    p = Perlin()
    p.a = xr.next_double() * 256.0
    p.b = xr.next_double() * 256.0
    p.c = xr.next_double() * 256.0
    d = p.d
    for i in range(256):
        j = xr.next_int(256 - i) + i
        d[i], d[j] = d[j], d[i]
    d[256] = d[0]
    i2 = np.floor(p.b)
    d2 = p.b - float(i2)
    p.h2 = int(i2)
    p.d2 = d2
    p.t2 = d2 * d2 * d2 * (d2 * (d2 * 6.0 - 15.0) + 10.0)
    return p


def _indexed_lerp(idx: int, a: float, b: float, c: float) -> float:
    """noise.c indexedLerp（梯度点积）。"""
    return (
        (a + b, -a + b, a - b, -a - b,
         a + c, -a + c, a - c, -a - c,
         b + c, -b + c, b - c, -b - c,
         a + b, -b + c, -a + b, -b - c)[idx & 0xF]
    )


def sample_perlin(p: Perlin, d1: float, d2: float, d3: float) -> float:
    """noise.c samplePerlin（yamp=0 路径：气候采样恒 y=0）。"""
    if d2 == 0.0:
        d2 = p.d2
        h2 = p.h2
        t2 = p.t2
    else:
        d2 += p.b
        i2 = np.floor(d2)
        d2 = d2 - float(i2)
        h2 = int(i2)
        t2 = d2 * d2 * d2 * (d2 * (d2 * 6.0 - 15.0) + 10.0)

    d1 += p.a
    d3 += p.c
    i1 = np.floor(d1)
    i3 = np.floor(d3)
    d1 = d1 - float(i1)
    d3 = d3 - float(i3)
    h1 = int(i1)
    h3 = int(i3)
    t1 = d1 * d1 * d1 * (d1 * (d1 * 6.0 - 15.0) + 10.0)
    t3 = d3 * d3 * d3 * (d3 * (d3 * 6.0 - 15.0) + 10.0)

    idx = p.d
    # 查找链对齐 noise.c L152-171 的 vec2 语义：
    # v1a/v1b = idx[h1]/idx[h1+1] + h2（x 层/y 层），再 +h3（z 层）
    # v2a/v2b、v3a/v3b 是两个 x 层各自的 z 角，g1..g8 对应 C 的 v4..v7
    v1a = (idx[h1 & 0xFF] + h2) & 0xFF
    v1b = (idx[(h1 + 1) & 0xFF] + h2) & 0xFF
    v2a = (idx[v1a] + h3) & 0xFF
    v2b = (idx[v1a + 1] + h3) & 0xFF
    v3a = (idx[v1b] + h3) & 0xFF
    v3b = (idx[v1b + 1] + h3) & 0xFF
    g1 = idx[v2a]       # C v4.a：x=0, y=0, z=0 -> l1
    g2 = idx[v2a + 1]   # C v4.b：x=0, y=0, z=1 -> l5
    g3 = idx[v2b]       # C v5.a：x=0, y=1, z=0 -> l3
    g4 = idx[v2b + 1]   # C v5.b：x=0, y=1, z=1 -> l7
    g5 = idx[v3a]       # C v6.a：x=1, y=0, z=0 -> l2
    g6 = idx[v3a + 1]   # C v6.b：x=1, y=0, z=1 -> l6
    g7 = idx[v3b]       # C v7.a：x=1, y=1, z=0 -> l4
    g8 = idx[v3b + 1]   # C v7.b：x=1, y=1, z=1 -> l8

    l1 = _indexed_lerp(g1, d1, d2, d3)
    l5 = _indexed_lerp(g2, d1, d2, d3 - 1.0)
    l2 = _indexed_lerp(g5, d1 - 1.0, d2, d3)
    l6 = _indexed_lerp(g6, d1 - 1.0, d2, d3 - 1.0)
    l3 = _indexed_lerp(g3, d1, d2 - 1.0, d3)
    l7 = _indexed_lerp(g4, d1, d2 - 1.0, d3 - 1.0)
    l4 = _indexed_lerp(g7, d1 - 1.0, d2 - 1.0, d3)
    l8 = _indexed_lerp(g8, d1 - 1.0, d2 - 1.0, d3 - 1.0)

    l1 = l1 + t1 * (l2 - l1)
    l3 = l3 + t1 * (l4 - l3)
    l5 = l5 + t1 * (l6 - l5)
    l7 = l7 + t1 * (l8 - l7)
    l1 = l1 + t2 * (l3 - l1)
    l5 = l5 + t2 * (l7 - l5)
    return l1 + t3 * (l5 - l1)


class OctaveNoise:
    __slots__ = ("octaves",)

    def __init__(self, octaves):
        self.octaves = octaves  # list[(Perlin, amplitude, lacunarity)]


def x_octave_init(xr: Xoroshiro, amplitudes, omin: int) -> OctaveNoise:
    """noise.c xOctaveInit：消费 2 次 xNextLong 得参数级状态，再逐八度派生。"""
    lacuna = LACUNA_INI[-omin]
    persist = PERSIST_INI[len(amplitudes)]
    xlo = xr.next_long()
    xhi = xr.next_long()
    octaves = []
    i = 0
    lac = lacuna
    per = persist
    while i < len(amplitudes):
        if amplitudes[i] != 0.0:
            lo, hi = MD5_OCTAVE_N[12 + omin + i]
            pxr = Xoroshiro(xlo ^ lo, xhi ^ hi)
            p = x_perlin_init(pxr)
            octaves.append((p, amplitudes[i] * per, lac))
        i += 1
        lac *= 2.0
        per *= 0.5
    return OctaveNoise(octaves)


def sample_octave(octn: OctaveNoise, x: float, y: float, z: float) -> float:
    """noise.c sampleOctave（maintainPrecision 为恒等，noise.h L38-45）。"""
    v = 0.0
    for p, amp, lac in octn.octaves:
        v += amp * sample_perlin(p, x * lac, y * lac, z * lac)
    return v


class DoublePerlin:
    __slots__ = ("oct_a", "oct_b", "amplitude")


def x_double_perlin_init(xr: Xoroshiro, amplitudes, omin: int) -> DoublePerlin:
    """noise.c xDoublePerlinInit：两组八度 + 幅值归一。"""
    dpn = DoublePerlin()
    dpn.oct_a = x_octave_init(xr, amplitudes, omin)
    dpn.oct_b = x_octave_init(xr, amplitudes, omin)
    # 修零后的有效长度
    lo_i = 0
    hi_i = len(amplitudes)
    while hi_i > 0 and amplitudes[hi_i - 1] == 0.0:
        hi_i -= 1
    while lo_i < hi_i and amplitudes[lo_i] == 0.0:
        lo_i += 1
    dpn.amplitude = AMP_INI[hi_i - lo_i]
    return dpn


def sample_double_perlin(dpn: DoublePerlin, x: float, y: float, z: float) -> float:
    """noise.c sampleDoublePerlin（L562-572）：全程 double 运算。

    v = octA(x,y,z) + octB(x*f, y*f, z*f)，f = 337/331；
    返回 double * amplitude。与 C 一致无 float32 截断。
    """
    f = 337.0 / 331.0
    v = sample_octave(dpn.oct_a, x, y, z)
    v += sample_octave(dpn.oct_b, x * f, y * f, z * f)
    return v * dpn.amplitude


# ======================================================================
# depth 样条（biomenoise.c L944-1133；全程 float32）
# ======================================================================

_SP_CONTINENTALNESS, _SP_EROSION, _SP_RIDGES, _SP_WEIRDNESS = 0, 1, 2, 3


def _f32(v) -> np.float32:
    return np.float32(v)


def _get_offset_value(weirdness: np.float32, continentalness: np.float32) -> np.float32:
    """biomenoise.c getOffsetValue（L966-976）。"""
    f0 = _f32(1.0 - _f32(_f32(1.0 - continentalness) * 0.5))
    f1 = _f32(0.5 * _f32(1.0 - continentalness))
    f2 = _f32(_f32(weirdness + 1.17) * _f32(0.46082947))
    off = _f32(f2 * f0 - f1)
    if weirdness < _f32(-0.7):
        return off if off > _f32(-0.2222) else _f32(-0.2222)
    return off if off > 0 else np.float32(0.0)


def _build_splines():
    """照抄 initBiomeNoise（L1112-1137）与四个构建函数（L978-1072）。

    表示法：("fix", val) 或 (typ, [(loc, val, der), ...])；全程 float32。
    """
    fix_stack = []

    def fix(v) -> tuple:
        node = ("fix", _f32(v))
        fix_stack.append(node)
        return node

    def create_spline_38219(f: np.float32, bl: bool):
        pts = []
        i_v = _get_offset_value(_f32(-1.0), f)
        k_v = _get_offset_value(_f32(1.0), f)
        u_v = _f32(0.5 * _f32(1.0 - f))
        l_v = _f32(u_v / _f32(_f32(0.46082947) * _f32(1.0 - _f32(_f32(1.0 - f) * 0.5))) - _f32(1.17))
        if _f32(-0.65) < l_v < _f32(1.0):
            u2 = _get_offset_value(_f32(-0.65), f)
            p_v = _get_offset_value(_f32(-0.75), f)
            q = _f32(_f32(p_v - i_v) * 4.0)
            r_v = _get_offset_value(l_v, f)
            s = _f32(_f32(k_v - r_v) / _f32(1.0 - l_v))
            pts.append((_f32(-1.0), fix(i_v), q))
            pts.append((_f32(-0.75), fix(p_v), _f32(0)))
            pts.append((_f32(-0.65), fix(u2), _f32(0)))
            pts.append((_f32(l_v - _f32(0.01)), fix(r_v), _f32(0)))
            pts.append((l_v, fix(r_v), s))
            pts.append((_f32(1.0), fix(k_v), s))
        else:
            u2 = _f32(_f32(k_v - i_v) * 0.5)
            if bl:
                v = i_v if i_v > _f32(0.2) else _f32(0.2)
                pts.append((_f32(-1.0), fix(v), _f32(0)))
                # C: lerp(0.5F, i, k) double 运算后截为 float32
                mid = np.float32(float(i_v) + 0.5 * (float(k_v) - float(i_v)))
                pts.append((_f32(0.0), fix(mid), u2))
            else:
                pts.append((_f32(-1.0), fix(i_v), u2))
            pts.append((_f32(1.0), fix(k_v), u2))
        return (_SP_RIDGES, pts)

    def create_flat_offset_spline(f, g, h, i, j, k):
        pts = []
        l_v = _f32(_f32(g - f) * 0.5)
        if l_v < k:
            l_v = k
        m = _f32(_f32(h - g) * 5.0)   # C: m = 5.0F * (h - g)
        pts.append((_f32(-1.0), fix(f), l_v))
        pts.append((_f32(-0.4), fix(g), l_v if l_v < m else m))
        pts.append((_f32(0.0), fix(h), m))
        pts.append((_f32(0.4), fix(i), _f32(_f32(i - h) * 2.0)))
        pts.append((_f32(1.0), fix(j), _f32(_f32(j - i) * 0.7)))
        return (_SP_RIDGES, pts)

    def create_land_spline(f, g, h, i, j, k, bl):
        # C: lerp(i, 0.6F, 1.5F) —— rng.h lerp 是 double 函数：
        # double(0.6F) + i*(1.5 - double(0.6F)) 全程 double，传参时截为 float32
        f_06 = float(np.float32(0.6))
        sp1 = create_spline_38219(np.float32(f_06 + float(i) * (1.5 - f_06)), bl)
        sp2 = create_spline_38219(np.float32(f_06 + float(i) * (1.0 - f_06)), bl)
        sp3 = create_spline_38219(i, bl)
        ih = _f32(i * 0.5)
        sp4 = create_flat_offset_spline(_f32(f - _f32(0.15)), ih, ih, ih,
                                        _f32(i * 0.6), _f32(0.5))
        sp5 = create_flat_offset_spline(_f32(f), _f32(j * i), _f32(g * i), ih,
                                        _f32(i * 0.6), _f32(0.5))
        sp6 = create_flat_offset_spline(_f32(f), _f32(j), _f32(j), _f32(g),
                                        _f32(h), _f32(0.5))
        sp9 = create_flat_offset_spline(_f32(-0.02), _f32(k), _f32(k), _f32(g),
                                        _f32(h), _f32(0.0))
        pts8 = [(_f32(-1.0), fix(_f32(f)), _f32(0.0)),
                (_f32(-0.4), sp6, _f32(0.0)),
                (_f32(0.0), fix(_f32(h + 0.07)), _f32(0.0))]
        sp8 = (_SP_RIDGES, pts8)
        pts = [(_f32(-0.85), sp1, _f32(0.0)),
               (_f32(-0.7), sp2, _f32(0.0)),
               (_f32(-0.4), sp3, _f32(0.0)),
               (_f32(-0.35), sp4, _f32(0.0)),
               (_f32(-0.1), sp5, _f32(0.0)),
               (_f32(0.2), sp6, _f32(0.0))]
        if bl:
            pts.append((_f32(0.4), sp6, _f32(0.0)))
            pts.append((_f32(0.45), sp8, _f32(0.0)))
            pts.append((_f32(0.55), sp8, _f32(0.0)))
            pts.append((_f32(0.58), sp6, _f32(0.0)))
        pts.append((_f32(0.7), sp9, _f32(0.0)))
        return (_SP_EROSION, pts)

    # initBiomeNoise 主体（L1119-1133）
    sp1 = create_land_spline(_f32(-0.15), _f32(0.00), _f32(0.0), _f32(0.1),
                             _f32(0.00), _f32(-0.03), 0)
    sp2 = create_land_spline(_f32(-0.10), _f32(0.03), _f32(0.1), _f32(0.1),
                             _f32(0.01), _f32(-0.03), 0)
    sp3 = create_land_spline(_f32(-0.10), _f32(0.03), _f32(0.1), _f32(0.7),
                             _f32(0.01), _f32(-0.03), 1)
    sp4 = create_land_spline(_f32(-0.05), _f32(0.03), _f32(0.1), _f32(1.0),
                             _f32(0.01), _f32(0.01), 1)
    main_pts = [
        (_f32(-1.10), fix(_f32(0.044)), _f32(0.0)),
        (_f32(-1.02), fix(_f32(-0.2222)), _f32(0.0)),
        (_f32(-0.51), fix(_f32(-0.2222)), _f32(0.0)),
        (_f32(-0.44), fix(_f32(-0.12)), _f32(0.0)),
        (_f32(-0.18), fix(_f32(-0.12)), _f32(0.0)),
        (_f32(-0.16), sp1, _f32(0.0)),
        (_f32(-0.15), sp1, _f32(0.0)),
        (_f32(-0.10), sp2, _f32(0.0)),
        (_f32(0.25), sp3, _f32(0.0)),
        (_f32(1.00), sp4, _f32(0.0)),
    ]
    return (_SP_CONTINENTALNESS, main_pts)


_SPLINE_ROOT = None


def _spline_root():
    global _SPLINE_ROOT
    if _SPLINE_ROOT is None:
        _SPLINE_ROOT = _build_splines()
    return _SPLINE_ROOT


def _lerp_f32(part: np.float32, a: np.float32, b: np.float32) -> np.float32:
    return _f32(a + _f32(part * _f32(b - a)))


def get_spline(sp, vals) -> np.float32:
    """biomenoise.c getSpline（L1074-1110）：中间运算 float32；
    最终插值 r = lerp(k, n, o) + k*(1-k)*lerp(k, p, q) 为 double 函数
    （rng.h lerp 是 double，C 编译器把参数提升为 double 算）。"""
    if sp[0] == "fix":
        return sp[1]
    typ, pts = sp
    f = _f32(vals[typ])
    n = len(pts)
    i = 0
    while i < n:
        if pts[i][0] >= f:
            break
        i += 1
    if i == 0 or i == n:
        if i:
            i -= 1
        loc, val, der = pts[i]
        return _f32(get_spline(val, vals) + _f32(der * _f32(f - loc)))
    g = pts[i - 1][0]
    h = pts[i][0]
    k = _f32(_f32(f - g) / _f32(h - g))
    der_l = pts[i - 1][2]
    der_m = pts[i][2]
    nv = get_spline(pts[i - 1][1], vals)
    o = get_spline(pts[i][1], vals)
    p_v = _f32(_f32(der_l * _f32(h - g)) - _f32(o - nv))
    q = _f32(_f32(-der_m * _f32(h - g)) + _f32(o - nv))
    # lerp(k, n, o) 与 lerp(k, p, q)：double 乘加（rng.h lerp 是 double）
    # 但 k*(1.0F-k) 是 float 域乘法（两个 float 相乘先舍入到 float32）
    kf = float(k)
    a = float(nv) + kf * (float(o) - float(nv))
    b1 = float(np.float32(k) * np.float32(np.float32(1.0) - k))
    b2 = float(p_v) + kf * (float(q) - float(p_v))
    return np.float32(a + b1 * b2)


# ======================================================================
# BiomeSampler：世界种子 -> 群系（顶层接口）
# ======================================================================

class BiomeSampler:
    """单个世界种子的 1.18+ 主世界群系采样器（等价 setBiomeSeed + 采样）。"""

    def __init__(self, seed: int, version_key: str = "1.21", large: bool = False):
        if large:
            raise ValueError("large biomes 暂不支持")
        self.seed = seed & _M64
        xr = Xoroshiro.from_seed(self.seed)
        xlo = xr.next_long()
        xhi = xr.next_long()
        self.climate: list[DoublePerlin | None] = [None] * NP_MAX
        for nptype in (NP_SHIFT, NP_TEMPERATURE, NP_HUMIDITY,
                       NP_CONTINENTALNESS, NP_EROSION, NP_WEIRDNESS):
            # C: init_climate_seed 中仅 T/H/C/E 四参数区分 large；
            # SHIFT 与 WEIRDNESS 的 MD5 常量/八度参数固定（biomenoise.c L854-899）
            if large and nptype in _CLIMATE_LARGE:
                (md5_lo, md5_hi), amps, omin = _CLIMATE_LARGE[nptype]
            else:
                (md5_lo, md5_hi), amps, omin = _CLIMATE_SMALL[nptype]
            pxr = Xoroshiro(xlo ^ md5_lo, xhi ^ md5_hi)
            self.climate[nptype] = x_double_perlin_init(pxr, amps, omin)
        self._btree = get_btree(version_key)

    def climate_point(self, x: int, y: int, z: int) -> tuple[int, ...]:
        """采样 6 参数 np 值（int64 量化；x/y/z 均为噪声格坐标）。

        等价 sampleBiomeNoise（biomenoise.c L1141-1191），含 shift 扰动、
        depth 样条与 float32 量化。
        """
        return self.climate_point_xz(x, z, y)

    def climate_point_xz(self, x, z, ny: float = 0.0) -> tuple[int, ...]:
        """按 (噪声格 x, 噪声格 z, 噪声格 y) 采样 6 参数 np 值。

        与 climate_point 等价（ny 即其中的 y），供精化引擎按
        观测点高度采样：地表方块层 ny = blockY >> 2（约 16~24），
        与游戏 F3 群系判定一致；缺省 0（深层噪声层，旧行为）。
        """
        x = float(x)
        z = float(z)
        shift = self.climate[NP_SHIFT]
        # shift 采样（L1156-1157）：第二次传 (z, x, 0) —— y=x, z=0
        px = x + sample_double_perlin(shift, x, 0.0, z) * 4.0
        pz = z + sample_double_perlin(shift, z, x, 0.0) * 4.0

        c = self._sample_dpn(self.climate[NP_CONTINENTALNESS], px, 0.0, pz)
        e = self._sample_dpn(self.climate[NP_EROSION], px, 0.0, pz)
        w = self._sample_dpn(self.climate[NP_WEIRDNESS], px, 0.0, pz)

        # depth（L1164-1173）：-3.0F*(fabsf(fabsf(w)-0.6666667F)-0.33333334F)
        # 全程 float32（fabsf/减法/乘法都在 float 域），off 样条值 + 0.015F
        c_f, e_f, w_f = np.float32(c), np.float32(e), np.float32(w)
        ridge = np.float32(np.float32(-3.0) * np.float32(
            np.float32(abs(np.float32(abs(w_f) - np.float32(0.6666667))))
            - np.float32(0.33333334)))
        off = get_spline(_spline_root(), (c_f, e_f, ridge, w_f))
        # C: double off = getSpline(...) + 0.015F —— 0.015F 先提升为 double
        off = float(off) + float(np.float32(0.015))
        d = 1.0 - (ny * 4) / 128.0 - 83.0 / 160.0 + off   # double（C: float d = 表达式）

        t = self._sample_dpn(self.climate[NP_TEMPERATURE], px, 0.0, pz)
        h = self._sample_dpn(self.climate[NP_HUMIDITY], px, 0.0, pz)

        def quant(v) -> int:
            # C: (int64_t)(10000.0F * v)：10000.0F 与 v 都提升为 double 相乘，
            # 再向零截断。10000 是 2 的幂次精确值，乘法结果与 float32 域一致。
            return int(np.float32(np.float32(10000.0) * np.float32(v)))

        return (quant(t), quant(h), quant(c), quant(e), quant(d), quant(w))

    @staticmethod
    def _sample_dpn(dpn: DoublePerlin, x: float, y: float, z: float) -> float:
        return sample_double_perlin(dpn, x, y, z)

    def biome_at(self, x: int, y: int, z: int) -> int:
        """返回 1:4 噪声格 (x, y, z) 处的群系 id。"""
        return climate_to_biome(self.climate_point(x, y, z), self._btree)


# ----------------------------------------------------------------------
# climateToBiome（biomenoise.c L1369-1484，btree 最近邻搜索）
# ----------------------------------------------------------------------

def _get_np_dist(np6, bt: BTree, idx: int) -> int:
    """节点 idx 的参数盒到 np 的平方距离（uint64 算术，不溢出）。"""
    node = int(bt.nodes[idx])
    ds = 0
    for i in range(6):
        pidx = (node >> (8 * i)) & 0xFF
        lo = int(bt.param[pidx][0])
        hi = int(bt.param[pidx][1])
        a = np6[i] - hi
        b = lo - np6[i]
        if a > 0:
            d = a
        elif b > 0:
            d = b
        else:
            d = 0
        ds += d * d
    return ds


def _resulting_node(np6, bt: BTree, idx: int, alt: int, ds: int, depth: int) -> int:
    steps = bt.steps
    if int(steps[depth]) == 0:
        return idx
    step = int(steps[depth])
    depth += 1
    while idx + step >= bt.len:
        step = int(steps[depth])
        depth += 1
    node = int(bt.nodes[idx])
    inner = (node >> 48) & 0xFFFF
    leaf = alt
    order = bt.order
    for _ in range(order):
        ds_inner = _get_np_dist(np6, bt, inner)
        if ds_inner < ds:
            leaf2 = _resulting_node(np6, bt, inner, leaf, ds, depth)
            ds_leaf2 = ds_inner if inner == leaf2 else _get_np_dist(np6, bt, leaf2)
            if ds_leaf2 < ds:
                ds = ds_leaf2
                leaf = leaf2
        inner += step
        if inner >= bt.len:
            break
    return leaf


def climate_to_biome(np6, bt: BTree) -> int:
    """biomenoise.c climateToBiome（dat=NULL 路径）。"""
    idx = _resulting_node(np6, bt, 0, 0, (1 << 64) - 1, 0)
    return (int(bt.nodes[idx]) >> 48) & 0xFF


def climate_to_biome_dat(np6, bt: BTree, dat: int) -> tuple[int, int]:
    """biomenoise.c climateToBiome 的 dat 共享路径（MC-241546）。

    alt = 上一次搜索的终点节点（跨格传递）；ds 以 alt 节点距离
    初始化（剪枝下界），搜索结果与新 ds 回写给调用方链式传递。

    Args:
        np6: 6 参数量化值。
        bt: 版本 btree。
        dat: 上一次 climateToBiome 的返回节点 idx（首个调用传 0）。

    Returns:
        (idx, dat)：idx 为节点（>>48 为群系 id），dat 为新链状态。
    """
    ds = _get_np_dist(np6, bt, dat)
    idx = _resulting_node(np6, bt, 0, dat, ds, 0)
    return idx, idx


# ======================================================================
# 群系 id / 名称表（biomes.h BiomeID；1.18+ 主世界 1:4 可出现集合）
# ======================================================================

BIOME_ID = {
    "ocean": 0, "plains": 1, "desert": 2, "windswept_hills": 3,
    "forest": 4, "taiga": 5, "swamp": 6, "river": 7,
    "frozen_ocean": 10, "frozen_river": 11, "snowy_plains": 12,
    "mushroom_fields": 14, "mushroom_field_shore": 15,
    "beach": 16, "desert_hills": 17, "wooded_hills": 18, "taiga_hills": 19,
    "jungle": 21, "sparse_jungle": 23, "deep_ocean": 24,
    "stony_shore": 25, "snowy_beach": 26, "birch_forest": 27,
    "birch_forest_hills": 28, "dark_forest": 29,
    "snowy_taiga": 30, "giant_tree_taiga": 32, "giant_tree_taiga_hills": 33,
    "windswept_forest": 34, "savanna": 35, "savanna_plateau": 36,
    "badlands": 37, "wooded_badlands": 38,
    "warm_ocean": 44, "lukewarm_ocean": 45, "cold_ocean": 46,
    "deep_warm_ocean": 47, "deep_lukewarm_ocean": 48,
    "deep_cold_ocean": 49, "deep_frozen_ocean": 50,
    "sunflower_plains": 129, "ice_spikes": 140,
    "eroded_badlands": 165, "shattered_savanna": 163,
    "gravelly_mountains": 131, "windswept_gravelly_hills": 131,
    "bamboo_jungle": 168, "dripstone_caves": 174, "lush_caves": 175,
    "meadow": 177, "grove": 178, "snowy_slopes": 179,
    "jagged_peaks": 180, "frozen_peaks": 181, "stony_peaks": 182,
    "deep_dark": 183, "mangrove_swamp": 184, "cherry_grove": 185,
    "pale_garden": 186,
    # 26.2 硫磺洞穴：官方 187 被其他 id 占用，MCHelper 封闭系统自定（btree262 叶编码↔此表自洽）
    "sulfur_caves": 187,
}

BIOME_NAME_ZH = {
    "ocean": "海洋", "plains": "平原", "desert": "沙漠",
    "windswept_hills": "风袭丘陵", "forest": "森林", "taiga": "针叶林",
    "swamp": "沼泽", "river": "河流", "frozen_ocean": "冻洋",
    "frozen_river": "冻河", "snowy_plains": "雪原",
    "mushroom_fields": "蘑菇岛", "mushroom_field_shore": "蘑菇岛岸",
    "beach": "海滩", "snowy_beach": "积雪海滩", "stony_shore": "石岸",
    "jungle": "丛林", "sparse_jungle": "稀疏丛林", "deep_ocean": "深海",
    "birch_forest": "桦木森林", "dark_forest": "黑森林",
    "snowy_taiga": "积雪针叶林", "giant_tree_taiga": "原始松木针叶林",
    "giant_tree_taiga_hills": "原始松木针叶林丘陵",
    "windswept_forest": "风袭森林", "savanna": "热带草原",
    "savanna_plateau": "热带高原", "badlands": "恶地",
    "wooded_badlands": "繁茂恶地", "warm_ocean": "温水海洋",
    "lukewarm_ocean": "温和海洋", "cold_ocean": "冷水海洋",
    "deep_warm_ocean": "温水深海", "deep_lukewarm_ocean": "温和深海",
    "deep_cold_ocean": "冷水深海", "deep_frozen_ocean": "冰冻深海",
    "sunflower_plains": "向日葵平原", "ice_spikes": "冰刺之地",
    "eroded_badlands": "风蚀丘陵（恶地）", "shattered_savanna": "风袭热带草原（破碎）",
    "windswept_gravelly_hills": "风袭砂砾丘陵",
    "bamboo_jungle": "竹林", "dripstone_caves": "溶洞",
    "lush_caves": "繁茂洞穴", "meadow": "草甸", "grove": "雪林",
    "snowy_slopes": "雪坡", "jagged_peaks": "尖峭山峰",
    "frozen_peaks": "冰封山峰", "stony_peaks": "裸岩山峰",
    "deep_dark": "深暗之域", "mangrove_swamp": "红树林沼泽",
    "cherry_grove": "樱花树林", "pale_garden": "苍白花园",
    "sulfur_caves": "硫磺洞穴",
}

# F3 调试屏显示名 -> 内部键（别名归一）
_F3_ALIASES = {
    "snowy_tundra": "snowy_plains", "ice_plains": "snowy_plains",
    "mountains": "windswept_hills", "extreme_hills": "windswept_hills",
    "wooded_mountains": "windswept_forest",
    "gravelly_mountains": "windswept_gravelly_hills",
    "mountain_edge": "windswept_hills",
    "shattered_savanna": "shattered_savanna",
    "jungle_edge": "sparse_jungle",
    "stone_shore": "stony_shore",
    "giant_tree_taiga": "giant_tree_taiga",
    "mushroom_field_shore": "mushroom_field_shore",
    "mesa": "badlands", "wooded_mesaplateau": "wooded_badlands",
    "tall_birch_forest": "birch_forest",
}

# 中文别名（部分常见叫法）
_ZH_ALIASES = {
    "雪原": "snowy_plains", "冰原": "snowy_plains",
    "雪山": "snowy_slopes", "雪林": "grove",
    "恶地": "badlands", "平顶山": "badlands", "黏土山": "badlands",
    "樱花": "cherry_grove", "樱树": "cherry_grove",
    "蘑菇岛岸": "mushroom_field_shore", "蘑菇岛海岸": "mushroom_field_shore",
    "繁茂洞窟": "lush_caves", "繁茂洞穴": "lush_caves",
    "滴水石": "dripstone_caves", "钟乳石": "dripstone_caves",
    "苍园": "pale_garden", "苍白之园": "pale_garden",
}


def biome_key_to_id(key: str) -> int | None:
    """群系键名（含别名）-> id；未知返回 None。"""
    k = key.strip().lower().replace(" ", "_").replace("-", "_")
    k = _F3_ALIASES.get(k, k)
    return BIOME_ID.get(k)


def biome_display_name(key_or_id) -> str:
    """内部键或 id -> 显示名（中文优先）。"""
    if isinstance(key_or_id, int):
        for k, v in BIOME_ID.items():
            if v == key_or_id:
                return f"{BIOME_NAME_ZH.get(k, k)}"
        return str(key_or_id)
    return BIOME_NAME_ZH.get(key_or_id, key_or_id)


def resolve_biome_input(text: str) -> int | None:
    """把用户输入（英文键 / 中文名 / F3 名）解析为群系 id。"""
    s = text.strip()
    if not s:
        return None
    # 先按 id 数字
    if s.lstrip("-").isdigit():
        return int(s)
    # 中文精确
    zh = _ZH_ALIASES.get(s)
    if zh:
        return BIOME_ID[zh]
    for k, v in BIOME_NAME_ZH.items():
        if v == s:
            return BIOME_ID[k]
    # 英文键 / 别名
    ident = biome_key_to_id(s)
    if ident is not None:
        return ident
    # 模糊：输入是某键/中文名的子串
    sl = s.lower()
    for k, v in _F3_ALIASES.items():
        if sl in k or k in sl:
            return BIOME_ID[v]
    for k in BIOME_ID:
        if sl in k:
            return BIOME_ID[k]
    for k, v in BIOME_NAME_ZH.items():
        if s in v:
            return BIOME_ID[k]
    return None


def block_to_noise(v: int) -> int:
    """方块坐标 -> 噪声格坐标（1:4，向下取整除 4）。"""
    return int(v) >> 2
