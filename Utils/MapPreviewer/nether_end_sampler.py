# -*- coding: utf-8 -*-
"""MapPreviewer 下界/末地群系采样器（legacy Random 线）。

与 biome_noise.py 的 Xoroshiro 线（1.18+ 主世界）不同，下界群系
（1.16+）与末地群系（1.9+）的噪声完全由 legacy Java Random 流驱动，
本模块按 cubiomes biomenoise.c / noise.c 逐行移植并 numpy 向量化。

=== 下界（biomenoise.c L164-212，1.16+）===
    setNetherSeed：
        setSeed(seed)     → doublePerlinInit(temperature, omin=-7, len=2)
        setSeed(seed + 1) → doublePerlinInit(humidity,   omin=-7, len=2)
    getNetherBiome：y 强制 0，temp/humid 各一次 sampleDoublePerlin
    （坐标 = 噪声格 1:4，scale=4 无 Voronoi），5 点最近邻（float 域）：
        nether_wastes(0,0)  soul_sand_valley(0,-0.5)  crimson_forest(0.4,0)
        warped_forest(0,0.5,常数0.375²)  basalt_deltas(-0.5,0,常数0.175²)
    genNetherScaled scale=4 直接逐格采样；mapNether3D 的 fillRad3D
    是纯加速优化（noisedelta 保证半径内群系不变），逐点采样结果等价。

=== 末地（biomenoise.c L370-515，1.9+）===
    setEndSeed：setSeed(seed) → skipNextN(17292) → perlinInit（单 Perlin）
    mapEndBiome（单位 = 16 方块 chunk，1.13+）：
        hmap 尺寸 (w+26)×(h+26)，元素 rx=x+i-12, rz=z+j-12，
        rsq>4096 且 sampleSimplex2D(perlin,rx,rz) < -0.9 的格子
        v = ((|rx|·3439 + |rz|·147) % 13 + 9)²（float32 乘法 +
        (unsigned int) 截断，uint16 域平方）；
        主循环 rsq≤4096 → the_end；否则 hx/hz = 2h+1，
        1.13+ 若 (int32)(hx²+hz²) < 0 → end_barrens；
        getEndBiome：h 初值 |hx|,|hz|≤15 → 64·(hx²+hz²) 否则 14401，
        25×25 窗 elev 非 0 时 h = min(h, (ds[±i]+ds[±j])·elev)，
        h<3600 → end_highlands；≤10000 → end_midlands；
        ≤14400 → end_barrens；else small_end_islands。
    mapEnd（scale=4）：chunk 网格算完后按 (x+i)>>2 最近邻展开到
    4 方块像素 —— 本模块 sample_region_end 即此路径（与主世界
    1 像素 = 4 方块观感一致）。

=== 位级细节（与 C 严格对应）===
    - perlinInit（noise.c L49-77）：a/b/c = nextDouble·256；256 次
      洗牌 j = nextInt(256-i) + i（rng.h 完整版 nextInt，含拒绝采样，
      i=0 时 256 为 2 幂走 pow2 分支）；idx[256]=idx[0]；
      预计算 h2=(int)floor(b)、d2=b-floor(b)、t2=fade(d2)。
    - octaveInit（L333-373）omin=-7, len=2：end=-6 < 0 →
      skipNextN(1572)；persist=1/3、lacuna=2⁻⁶ 起逐 octave 翻倍/减半。
    - doublePerlinInit（L519-525）：amplitude=(10/6)·len/(len+1)=10/9；
      octA、octB 在同一条流上顺序初始化。
    - samplePerlin（L109-208）y=0 快速路径：d2==0 时用预计算的
      d2/h2/t2 常数；h1/h3 为 uint8 截断（C 中 (int)floor 存入
      uint8_t 即 mod 256），idx 索引链全部在 uint8 域回绕（&0xff）。
    - indexedLerp（L23-46）16 case 编码为 (16,3) 符号表向量化。
    - lerp(t,a,b) = a + t·(b-a)（本地裁剪版未含 rng.h，公式标准）。
    - maintainPrecision 为恒等函数（noise.h L38-45）。
    - 末地 hmap 的 float 单精度：|rx|·3439.0f + |rz|·147.0f 用
      float32 计算 + (unsigned int) 截断，与 C 位级一致。
    - (int)rsq < 0 的 32 位截断：rsq & 0xFFFFFFFF ≥ 2³¹。
    - 窗起点 (hz/2 - z)、(hx/2 - x) 的 "/2" 是 C 向零截断除法：
      负 chunk 坐标时窗起点偏 +1（奇偶不对称），必须精确复刻。

=== 结构校验支撑 ===
    finders.c 的下界/末地结构群系校验（isViableStructurePos
    L1449-1506）直接调用本模块单点采样：
        - 下界：getBiomeAt(g, 4, sampleX, 0, sampleZ)（y 无效）
        - 末地：getBiomeAt(g, 16, chunkX, 0, chunkZ)（chunk 级）
    bastion 的 getVariant 采样点、fortress = NOT bastion 等规则
    在 structure_map.py 侧实现（复用本模块采样器）。

仅支持 1.16+ 下界与 1.13+ 末地语义（项目版本线 1.18~1.21）。
"""

from __future__ import annotations

import math
import time

import numpy as np

from Utils.SeedReverser import mc_random
from Utils.MapPreviewer.biome_colors import biome_color

_MASK48 = (1 << 48) - 1
_MASK64 = (1 << 64) - 1

# ---------------------------------------------------------------------------
# 群系 id（cubiomes biomes.h，与 biome_colors.py 同源）
# ---------------------------------------------------------------------------

NETHER_WASTES = 8
SOUL_SAND_VALLEY = 170
CRIMSON_FOREST = 171
WARPED_FOREST = 172
BASALT_DELTAS = 173

THE_END = 9
SMALL_END_ISLANDS = 40
END_MIDLANDS = 41
END_HIGHLANDS = 42
END_BARRENS = 43

# 下界 5 点最近邻表（getNetherBiome L177-183；[dx, dy, 常数项, id]）
_NETHER_PTS = np.array(
    [[0.0, 0.0, 0.0],
     [0.0, -0.5, 0.0],
     [0.4, 0.0, 0.0],
     [0.0, 0.5, 0.375 * 0.375],
     [-0.5, 0.0, 0.175 * 0.175]],
    dtype=np.float32,
)
_NETHER_IDS = np.array(
    [NETHER_WASTES, SOUL_SAND_VALLEY, CRIMSON_FOREST, WARPED_FOREST,
     BASALT_DELTAS], dtype=np.int32)

# getEndBiome 距离表 ds[26] = (25-2i)²（L382-387）
_END_DS = np.array(
    [625, 529, 441, 361, 289, 225, 169, 121, 81, 49, 25, 9, 1,
     1, 9, 25, 49, 81, 121, 169, 225, 289, 361, 441, 529, 625],
    dtype=np.int32)


# ---------------------------------------------------------------------------
# legacy Random 流封装（含 rng.h 完整版 nextInt / nextDouble / skipNextN）
# ---------------------------------------------------------------------------

class _Rand:
    """单条 legacy Random 流：48 位状态 + 完整版取数接口。

    perlinInit 的洗牌用 rng.h 完整版 nextInt（拒绝采样，i=0 时
    n=256 走 2 幂分支），mc_random.next_int 已是该语义。
    """

    __slots__ = ("s",)

    def __init__(self, seed64: int):
        self.s = mc_random.set_seed(seed64 & _MASK64)

    def next_int(self, n: int) -> int:
        v, self.s = mc_random.next_int(self.s, n)
        return v

    def next_double(self) -> float:
        v, self.s = mc_random.next_double(self.s)
        return v


def _skip_next_n(rnd: _Rand, n: int) -> None:
    """rng.h skipNextN：纯状态推进 n 次（无输出）。"""
    s = rnd.s
    for _ in range(n):
        s = (s * 0x5DEECE66D + 0xB) & _MASK48
    rnd.s = s


# ---------------------------------------------------------------------------
# legacy Perlin：标量初始化 + y=0 向量化采样
# ---------------------------------------------------------------------------

def _perlin_init(rnd: _Rand):
    """perlinInit（noise.c L49-77）→ (a, b, c, idx, d2, h2, t2)。

    idx 为 257 项（idx[256]=idx[0]），洗牌消耗 legacy 流
    （256 次 nextInt(256-i)，毫秒级；每条流只初始化一次）。
    """
    a = rnd.next_double() * 256.0
    b = rnd.next_double() * 256.0
    c = rnd.next_double() * 256.0
    idx = list(range(256))
    for i in range(256):
        j = rnd.next_int(256 - i) + i
        idx[i], idx[j] = idx[j], idx[i]
    idx.append(idx[0])                       # idx[256] = idx[0]
    i2 = math.floor(b)
    d2 = b - i2
    h2 = int(i2)                             # b∈[0,256) → h2∈[0,255]
    t2 = d2 * d2 * d2 * (d2 * (d2 * 6.0 - 15.0) + 10.0)
    return a, b, c, np.asarray(idx, dtype=np.int32), d2, h2, t2


def _octave_pair(rnd: _Rand):
    """octaveInit(omin=-7, len=2)（noise.c L333-373）。

    end = -6 < 0 → skipNextN(6·262 = 1572)；persist=1/(2²-1)=1/3，
    lacuna=2⁻⁶，逐 octave：persist×2、lacuna×0.5。
    返回 [(perlin, amplitude, lacunarity) × 2]。
    """
    _skip_next_n(rnd, 6 * 262)
    octs = []
    persist = 1.0 / 3.0
    lacuna = 2.0 ** -6
    for _ in range(2):
        p = _perlin_init(rnd)
        octs.append((p, persist, lacuna))
        persist *= 2.0
        lacuna *= 0.5
    return octs


def _double_perlin(rnd: _Rand):
    """doublePerlinInit（noise.c L519-525，omin=-7, len=2）。

    octA / octB 在同一条流上顺序初始化（L523-524）。
    返回 (amplitude=10/9, octA, octB)。
    """
    amplitude = (10.0 / 6.0) * 2 / 3         # len=2 → (10/6)·2/3 = 10/9
    oct_a = _octave_pair(rnd)
    oct_b = _octave_pair(rnd)
    return amplitude, oct_a, oct_b


# indexedLerp 16 case 符号表（noise.c L27-42）：(sa, sb, sc)
_LERP_SIG = np.zeros((16, 3), dtype=np.float64)
for _k, _s in enumerate([
        (1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0),
        (1, 0, 1), (-1, 0, 1), (1, 0, -1), (-1, 0, -1),
        (0, 1, 1), (0, -1, 1), (0, 1, -1), (0, -1, -1),
        (1, 1, 0), (0, -1, 1), (-1, 1, 0), (0, -1, -1)]):
    _LERP_SIG[_k] = _s


def _sample_perlin_y0(p, xs: np.ndarray, zs: np.ndarray) -> np.ndarray:
    """samplePerlin 的 y=0 快速路径（noise.c L109-208），向量化。

    d2 == 0.0 → 用初始化预计算的 d2/h2/t2 常数（L115-120）；
    h1/h3 uint8 截断（(int)floor 存入 uint8_t = mod 256），
    idx 索引链加法全部 & 0xff 回绕（uint8 域）。
    """
    a, _b, c, idx, d2c, h2, t2 = p
    d1 = xs + a
    d3 = zs + c
    i1 = np.floor(d1)
    i3 = np.floor(d3)
    f1 = d1 - i1
    f3 = d3 - i3
    h1 = i1.astype(np.int64) & 0xFF          # uint8 截断
    h3 = i3.astype(np.int64) & 0xFF
    t1 = f1 * f1 * f1 * (f1 * (f1 * 6.0 - 15.0) + 10.0)
    t3 = f3 * f3 * f3 * (f3 * (f3 * 6.0 - 15.0) + 10.0)

    # 索引链（noise.c #else 分支 L181-187，与 #if 1 分支等价）
    a1 = (idx[h1] + h2) & 0xFF
    b1 = (idx[h1 + 1] + h2) & 0xFF
    a2 = (idx[a1] + h3) & 0xFF
    b2 = (idx[b1] + h3) & 0xFF
    a3 = (idx[a1 + 1] + h3) & 0xFF
    b3 = (idx[b1 + 1] + h3) & 0xFF

    # indexedLerp：g&15 → 符号表点积（d2 用常数 d2c，y=0 层）
    def ilerp(g, da, db, dc):
        sig = _LERP_SIG[g & 15]
        return sig[:, 0] * da + sig[:, 1] * db + sig[:, 2] * dc

    # 8 角梯度值（noise.c L189-196）：C 中 d1/d3 已减去 floor，
    # 点积用的是小数部分 f1/f3（f1-1 / f3-1 对应 d1-1 / d3-1）
    l1 = ilerp(idx[a2], f1, d2c, f3)
    l2 = ilerp(idx[b2], f1 - 1.0, d2c, f3)
    l3 = ilerp(idx[a3], f1, d2c - 1.0, f3)
    l4 = ilerp(idx[b3], f1 - 1.0, d2c - 1.0, f3)
    l5 = ilerp(idx[a2 + 1], f1, d2c, f3 - 1.0)
    l6 = ilerp(idx[b2 + 1], f1 - 1.0, d2c, f3 - 1.0)
    l7 = ilerp(idx[a3 + 1], f1, d2c - 1.0, f3 - 1.0)
    l8 = ilerp(idx[b3 + 1], f1 - 1.0, d2c - 1.0, f3 - 1.0)

    # 三轴 lerp 合并（L199-207；lerp(t,a,b) = a + t·(b-a)）
    l1 = l1 + t1 * (l2 - l1)
    l3 = l3 + t1 * (l4 - l3)
    l5 = l5 + t1 * (l6 - l5)
    l7 = l7 + t1 * (l8 - l7)
    l1 = l1 + t2 * (l3 - l1)
    l5 = l5 + t2 * (l7 - l5)
    return l1 + t3 * (l5 - l1)


def _sample_octaves(octs, xs: np.ndarray, zs: np.ndarray) -> np.ndarray:
    """sampleOctave（noise.c L467-482）：y=0，maintainPrecision=恒等。"""
    v = np.zeros(xs.shape, dtype=np.float64)
    for p, amp, lac in octs:
        v += amp * _sample_perlin_y0(p, xs * lac, zs * lac)
    return v


def _sample_double_perlin(dp, xs: np.ndarray, zs: np.ndarray) -> np.ndarray:
    """sampleDoublePerlin（noise.c L562-572）：f = 337/331。"""
    amplitude, oct_a, oct_b = dp
    f = 337.0 / 331.0
    return (_sample_octaves(oct_a, xs, zs)
            + _sample_octaves(oct_b, xs * f, zs * f)) * amplitude


# ---------------------------------------------------------------------------
# simplex 2D（noise.c L294-331，末地小岛高度场）
# ---------------------------------------------------------------------------

_SKEW = 0.5 * (math.sqrt(3.0) - 1.0)
_UNSKEW = (3.0 - math.sqrt(3.0)) / 6.0


def _sample_simplex2d(p, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """sampleSimplex2D 向量化（返回 ×70 后的值）。"""
    _a, _b, _c, idx, _d2, _h2, _t2 = p
    hf = (xs + ys) * _SKEW
    hx = np.floor(xs + hf).astype(np.int64)
    hz = np.floor(ys + hf).astype(np.int64)
    mhxz = (hx + hz) * _UNSKEW
    x0 = xs - (hx - mhxz)
    y0 = ys - (hz - mhxz)
    offx = (x0 > y0)
    offz = ~offx
    x1 = x0 - offx + _UNSKEW
    y1 = y0 - offz + _UNSKEW
    x2 = x0 - 1.0 + 2.0 * _UNSKEW
    y2 = y0 - 1.0 + 2.0 * _UNSKEW

    def grad(gi, gx, gy):
        # simplexGrad(idx%12, x, y, 0, 0.5)（L294-301）：con=0.5-x²-y²
        con = 0.5 - gx * gx - gy * gy
        con = np.where(con < 0, 0.0, con)
        con4 = con * con
        con4 = con4 * con4
        # indexedLerp(gi%12, x, y, 0)：z 分量为 0
        sig = _LERP_SIG[(gi % 12) & 15]
        return con4 * (sig[..., 0] * gx + sig[..., 1] * gy)

    gi0 = idx[0xFF & hz]
    gi1 = idx[0xFF & (hz + offz)]
    gi2 = idx[0xFF & (hz + 1)]
    gi0 = idx[0xFF & (gi0 + hx)]
    gi1 = idx[0xFF & (gi1 + hx + offx)]
    gi2 = idx[0xFF & (gi2 + hx + 1)]
    t = (grad(gi0, x0, y0) + grad(gi1, x1, y1) + grad(gi2, x2, y2))
    return 70.0 * t


# ---------------------------------------------------------------------------
# 下界采样器
# ---------------------------------------------------------------------------

class NetherSampler:
    """下界群系采样器（1.16+）：温度/湿度双 DoublePerlin + 5 点最近邻。

    两条独立流：setSeed(seed) → temperature；setSeed(seed+1) → humidity
    （biomenoise.c L164-171）。y 无效（getNetherBiome 强制 y=0）。
    """

    def __init__(self, seed: int):
        ws = seed & _MASK64
        rnd = _Rand(ws)
        self._temp = _double_perlin(rnd)
        rnd2 = _Rand((ws + 1) & _MASK64)
        self._humid = _double_perlin(rnd2)

    def biome_matrix(self, nx0: int, nz0: int, w: int, h: int) -> np.ndarray:
        """噪声格矩形采样 → (h, w) int32 群系矩阵（行 = z 方向）。"""
        xs = (nx0 + np.arange(w, dtype=np.float64))[None, :]
        zs = (nz0 + np.arange(h, dtype=np.float64))[:, None]
        xs, zs = np.broadcast_arrays(xs, zs)
        temp = _sample_double_perlin(self._temp, xs.ravel(), zs.ravel())
        humid = _sample_double_perlin(self._humid, xs.ravel(), zs.ravel())
        return _nether_nearest(temp, humid).reshape(h, w)

    def biome_at(self, nx: int, nz: int) -> int:
        """单点采样（噪声格坐标；结构校验用）。"""
        t = _sample_double_perlin(self._temp,
                                  np.array([float(nx)]),
                                  np.array([float(nz)]))
        h = _sample_double_perlin(self._humid,
                                  np.array([float(nx)]),
                                  np.array([float(nz)]))
        return int(_nether_nearest(t, h)[0])


def _nether_nearest(temp: np.ndarray, humid: np.ndarray) -> np.ndarray:
    """5 点最近邻（getNetherBiome L189-211）。

    C 中 temp/humidity 存为 float，距离计算在 float 域；
    严格小于（dsq < dmin）→ 平局取先出现者 = argmin 最小索引。
    """
    t = temp.astype(np.float32)[:, None]
    h = humid.astype(np.float32)[:, None]
    dx = _NETHER_PTS[None, :, 0] - t
    dy = _NETHER_PTS[None, :, 1] - h
    dsq = dx * dx + dy * dy + _NETHER_PTS[None, :, 2]
    idx = np.argmin(dsq, axis=1)
    return _NETHER_IDS[idx]


# ---------------------------------------------------------------------------
# 末地采样器
# ---------------------------------------------------------------------------

def _c_div2(v: np.ndarray) -> np.ndarray:
    """C 整数除法 v/2（向零截断）。负奇数与算术移位不同：-5/2 = -2。"""
    return np.where(v >= 0, v >> 1, -((-v) >> 1))


class EndSampler:
    """末地群系采样器（1.13+ 语义）：单 Perlin simplex 小岛高度场。

    setEndSeed（L370-377）：setSeed(seed) → skipNextN(17292) → perlinInit。
    mapEndBiome 单位 = chunk（16 方块）；mapEnd（scale 4 像素）按
    (x+i)>>2 最近邻展开。
    """

    def __init__(self, seed: int):
        rnd = _Rand(seed & _MASK64)
        _skip_next_n(rnd, 17292)
        self._perlin = _perlin_init(rnd)

    # -- chunk 级核心（mapEndBiome L430-488）---------------------------

    def biome_matrix_chunk(self, x: int, z: int, w: int, h: int) -> np.ndarray:
        """mapEndBiome：(h, w) int32，输入输出均为 chunk 单位。"""
        hw = w + 26
        hh = h + 26

        # ---- hmap：外圈小岛高度场（L437-455）----
        jj, ii = np.mgrid[0:hh, 0:hw]
        rx = (x + ii - 12).astype(np.int64)
        rz = (z + jj - 12).astype(np.int64)
        rsq = rx * rx + rz * rz
        simplex = _sample_simplex2d(
            self._perlin, rx.astype(np.float64), rz.astype(np.float64))
        cond = (rsq > 4096) & (simplex < -0.9)
        # v = (unsigned int)(fabsf(rx)·3439.0f + fabsf(rz)·147.0f) % 13 + 9
        # （float32 乘法 + 截断），v *= v（uint16 域，≤441 无溢出）
        fr = (np.abs(rx).astype(np.float32) * np.float32(3439.0)
              + np.abs(rz).astype(np.float32) * np.float32(147.0))
        v = fr.astype(np.uint32) % np.uint32(13) + np.uint32(9)
        v = (v * v).astype(np.int64)
        hmap = np.where(cond, v, 0).astype(np.int32)

        # ---- 主循环（L457-484）----
        hx0 = (x + np.arange(w, dtype=np.int64))[None, :]
        hz0 = (z + np.arange(h, dtype=np.int64))[:, None]
        hx0, hz0 = np.broadcast_arrays(hx0, hz0)
        hx0 = hx0.astype(np.int64)
        hz0 = hz0.astype(np.int64)
        rsq0 = hx0 * hx0 + hz0 * hz0
        out = np.full(rsq0.shape, END_MIDLANDS, dtype=np.int32)  # 占位

        # the_end：rsq0 ≤ 4096（中心岛）
        end_mask = rsq0 <= 4096
        # 1.13+ 外圈：(int32)(hx²+hz²) < 0 → end_barrens（hx/hz 已 +1）
        hx1 = 2 * hx0 + 1
        hz1 = 2 * hz0 + 1
        rsq1 = hx1 * hx1 + hz1 * hz1
        barrens_mask = (~end_mask) & ((rsq1 & 0xFFFFFFFF) >= 0x80000000)
        # 其余走 getEndBiome
        todo = ~(end_mask | barrens_mask)
        out[end_mask] = THE_END
        out[barrens_mask] = END_BARRENS
        if not todo.any():
            return out

        # ---- getEndBiome（L379-428）：25×25 窗最低 u ----
        rows_t, cols_t = np.nonzero(todo)
        out = _end_get_biome_batch(
            out, hmap, hw, x, z, hx0, hz0, rows_t, cols_t)
        return out

    def biome_at_chunk(self, cx: int, cz: int) -> int:
        """单 chunk 采样（结构校验用，getBiomeAt scale=16 语义）。"""
        return int(self.biome_matrix_chunk(cx, cz, 1, 1)[0, 0])

    # -- scale=4 像素展开（mapEnd L490-515）---------------------------

    def map_region(self, origin_nx: int, origin_nz: int,
                   nw: int, nh: int) -> np.ndarray:
        """scale-4 噪声格矩形 → (nh, nw) 群系矩阵（每像素 = 4 方块）。

        像素 i 的群系 = chunk ((origin_nx+i)>>2, (origin_nz+j)>>2)。
        """
        # chunk 网格覆盖（起点对齐 origin & ~3）
        pad_x = origin_nx & 3
        pad_z = origin_nz & 3
        cx0 = (origin_nx - pad_x) >> 2
        cz0 = (origin_nz - pad_z) >> 2
        cnx = (pad_x + nw + 3) >> 2
        cnz = (pad_z + nh + 3) >> 2
        chunk_mat = self.biome_matrix_chunk(cx0, cz0, cnx, cnz)
        # 每 chunk 覆盖 4×4 像素，最近邻展开后裁剪
        big = np.repeat(np.repeat(chunk_mat, 4, axis=0), 4, axis=1)
        return big[pad_z:pad_z + nh, pad_x:pad_x + nw]


def _end_get_biome_batch(out: np.ndarray, hmap: np.ndarray, hw: int,
                         x: int, z: int,
                         hx0: np.ndarray, hz0: np.ndarray,
                         rows_t: np.ndarray, cols_t: np.ndarray) -> np.ndarray:
    """getEndBiome 批量向量化（按 64 行分块控制峰值内存）。

    h 初值 |hx|≤15 且 |hz|≤15 → 64·(hx²+hz²)，否则 14401；
    窗起点 (hz/2 - z)、(hx/2 - x) 为 C 向零截断除法；
    u = (ds[(hx<0)+i] + ds[(hz<0)+j])·elev（elev=0 不参与）；
    h<3600 → highlands；≤10000 → midlands；≤14400 → barrens；
    else small_end_islands。
    """
    blk = 64
    n = rows_t.size
    hx1_all = 2 * hx0 + 1
    hz1_all = 2 * hz0 + 1
    for lo in range(0, n, blk):
        hi = min(lo + blk, n)
        rr = rows_t[lo:hi]
        cc = cols_t[lo:hi]
        hx1 = hx1_all[rr, cc]
        hz1 = hz1_all[rr, cc]
        h0 = np.where((np.abs(hx1) <= 15) & (np.abs(hz1) <= 15),
                      64 * (hx1 * hx1 + hz1 * hz1), 14401)
        # 窗起点（C 截断除法：负坐标偏 +1）
        win_r = _c_div2(hz1) - z                 # (B,)
        win_c = _c_div2(hx1) - x                 # (B,)
        # gather 25×25 窗 → (B, 25, 25)
        jr = np.arange(25)
        elev = hmap[win_r[:, None, None] + jr[None, :, None],
                    win_c[:, None, None] + jr[None, None, :]]
        # ds 偏移表：ds[(hx<0)+i]（x 方向）/ ds[(hz<0)+j]（z 方向）
        dsi = _END_DS[(hx1 < 0)[:, None] + jr[None, :]]          # (B, 25) i
        dsj = _END_DS[(hz1 < 0)[:, None] + jr[None, :]]          # (B, 25) j
        u = dsi[:, None, :] + dsj[:, :, None]                    # (B, 25j, 25i)
        u = u * elev                                             # e=0 → u=0
        u = np.where(elev != 0, u, 1 << 30)
        h = np.minimum(h0, u.min(axis=(1, 2)))
        res = np.where(
            h < 3600, END_HIGHLANDS,
            np.where(h <= 10000, END_MIDLANDS,
                     np.where(h <= 14400, END_BARRENS,
                              SMALL_END_ISLANDS)))
        out[rr, cc] = res
    return out


# ---------------------------------------------------------------------------
# 区域采样入口（契约与 map_sampler.sample_region 对齐）
# ---------------------------------------------------------------------------

def _colors_for(biomes: np.ndarray) -> np.ndarray:
    """int32 群系矩阵 → uint8 RGB（与 map_sampler 同一查表）。"""
    table = np.zeros(256, dtype=np.uint8)
    rgb = np.empty((biomes.shape[0], biomes.shape[1], 3), dtype=np.uint8)
    for ch in range(3):
        lut = table
        for bid in range(256):
            lut[bid] = biome_color(bid)[ch]
        rgb[:, :, ch] = lut[np.clip(biomes, 0, 255)]
    return rgb


def _align_dims(cx_blocks: int, cz_blocks: int,
                width_blocks: int, height_blocks: int):
    """宽高对齐 4 的倍数 + 左上角噪声格（与 map_sampler 相同约定）。"""
    w = max(16, (int(width_blocks) // 4) * 4)
    h = max(16, (int(height_blocks) // 4) * 4)
    nw = w >> 2
    nh = h >> 2
    origin_nx = (int(cx_blocks) - w // 2) >> 2
    origin_nz = (int(cz_blocks) - h // 2) >> 2
    return w, h, nw, nh, origin_nx, origin_nz


def sample_region_nether(seed: int,
                         cx_blocks: int, cz_blocks: int,
                         width_blocks: int, height_blocks: int,
                         on_progress=None, cancel=None) -> dict:
    """下界矩形区域采样（1 像素 = 1 噪声格 = 4 方块，scale=4 无 Voronoi）。

    返回 dict 契约与 map_sampler.sample_region 一致（无 depth/
    temp/humid；ny=0、surface_mode=False、engine="python"）。
    """
    t0 = time.perf_counter()
    w, h, nw, nh, origin_nx, origin_nz = _align_dims(
        cx_blocks, cz_blocks, width_blocks, height_blocks)

    sampler = NetherSampler(seed)
    biomes = np.empty((nh, nw), dtype=np.int32)
    cancelled = False
    done_rows = 0
    row_blk = 64
    for r0 in range(0, nh, row_blk):
        if cancel is not None and cancel():
            cancelled = True
            break
        r1 = min(r0 + row_blk, nh)
        biomes[r0:r1] = sampler.biome_matrix(
            origin_nx, origin_nz + r0, nw, r1 - r0)
        done_rows = r1
        if on_progress is not None:
            on_progress(done_rows, nh, "nether")

    out = {
        "rgb": _colors_for(biomes),
        "biomes": biomes,
        "origin_bx": origin_nx << 2,
        "origin_bz": origin_nz << 2,
        "ny": 0,
        "surface_mode": False,
        "engine": "python",
        "elapsed": time.perf_counter() - t0,
        "cancelled": cancelled,
        "rows_done": done_rows,
    }
    return out


def sample_region_end(seed: int,
                      cx_blocks: int, cz_blocks: int,
                      width_blocks: int, height_blocks: int,
                      on_progress=None, cancel=None) -> dict:
    """末地矩形区域采样（1 像素 = 4 方块；chunk 级计算 + 最近邻展开）。

    返回 dict 契约与 map_sampler.sample_region 一致。
    """
    t0 = time.perf_counter()
    w, h, nw, nh, origin_nx, origin_nz = _align_dims(
        cx_blocks, cz_blocks, width_blocks, height_blocks)

    sampler = EndSampler(seed)
    biomes = np.empty((nh, nw), dtype=np.int32)
    cancelled = False
    done_rows = 0
    row_blk = 64
    for r0 in range(0, nh, row_blk):
        if cancel is not None and cancel():
            cancelled = True
            break
        r1 = min(r0 + row_blk, nh)
        biomes[r0:r1] = sampler.map_region(
            origin_nx, origin_nz + r0, nw, r1 - r0)
        done_rows = r1
        if on_progress is not None:
            on_progress(done_rows, nh, "end")

    out = {
        "rgb": _colors_for(biomes),
        "biomes": biomes,
        "origin_bx": origin_nx << 2,
        "origin_bz": origin_nz << 2,
        "ny": 0,
        "surface_mode": False,
        "engine": "python",
        "elapsed": time.perf_counter() - t0,
        "cancelled": cancelled,
        "rows_done": done_rows,
    }
    return out
