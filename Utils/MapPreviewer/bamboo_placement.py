# -*- coding: utf-8 -*-
"""官方 26.2 竹子放置链复刻（noise_based_count → in_square → heightmap →
biome → BambooFeature），替代旧"纯度场代理 + 逐格哈希"方案。

源码依据（.temp/mc262_decompile 26.2 反编译，行号为该文件行）：

- placed_feature/bamboo.json:
    placement = [noise_based_count(noise_to_count_ratio=160, noise_factor=80.0,
    noise_offset=0.3), in_square, heightmap(WORLD_SURFACE_WG), biome]
    feature = bamboo_some_podzol（configured_feature/bamboo_some_podzol.json:
    {"type": "minecraft:bamboo", "config": {"probability": 0.2}}）
- NoiseBasedCountPlacement.count（L34-37）:
    count = (int)Math.ceil((BIOME_INFO_NOISE.getValue(x/80, z/80, false)+0.3)*160)
    origin = chunk 角点 (cx*16, cz*16)；count 为负 -> IntStream.range(0,neg) = 空
    （RepeatingPlacement L13）。count 本身不消耗放置 RNG。
- Biome.BIOME_INFO_NOISE（Biome.java L66）:
    PerlinSimplexNoise(WorldgenRandom(LegacyRandomSource(2345L)), [0])
    -> 全局静态、种子固定 2345（LCG，非 Xoroshiro）、**与世界种子无关**。
    单 octave（PerlinSimplexNoise L20-61：highestFreqInputFactor=2^0=1、
    highestFreqValueFactor=1/(2^1-1)=1、useNoiseStart=false 不加 xo/yo）
    -> getValue(x,z,false) == SimplexNoise.getValue(x, z)。
- WorldgenRandom.setDecorationSeed（L44-51）:
    setSeed(levelSeed); xScale=nextLong()|1; zScale=nextLong()|1;
    result=((cx*xScale)+(cz*zScale))^levelSeed; setSeed(result)
- ChunkGenerator.applyBiomeDecoration（L386-389）:
    setFeatureSeed(decorationSeed, globalIndexOfFeature, stepIndex)
    -> bamboo 种子 = decorationSeed + 全局序号 + 10000*9
    全局序号由 FeatureSorter.buildFeaturesPerStep 推导，26.2 原版数据下
    "minecraft:bamboo" 在 step9 排序列表（106 项）中的位置 = 2
    （推导脚本 .temp/derive_bamboo_index.py，转录 OverworldBiomeBuilder
    群系顺序 + 66 个 biome JSON features + FeatureSorter 首遇序/链式边/DFS）。
- RNG 语义：WorldgenRandom extends LegacyRandomSource（L6）且**不覆写**
    nextLong()/nextInt(bound) -> 走 BitRandomSource 的 Java 默认
    （BitRandomSource.java L17-60）；next(bits) 被覆写为
    "(int)(inner.nextLong() >>> (64-bits))"（L30-35，inner=Xoroshiro 时）。
    故 nextInt(16)=(16*next(31))>>31（1 次 nextLong）、
    nextInt(12) 走 31 位拒绝采样、nextFloat()=next(24)*2^-24、
    nextLong()=两次 next(32)（各消耗一次 inner.nextLong()）。
- BambooFeature.place（L31-75）:
    仅当 origin 空且 canSurvive 才消耗 RNG，顺序：
    height=nextInt(12)+5 -> nextFloat()<0.2 -> r=nextInt(4)+1；
    灰化土盘先于竹秆；盘扫描 (x±r, z±r) 方形、保留 xd²+zd²≤r²、
    podzol 放在 WORLD_SURFACE-1 且仅替换 BENEATH_BAMBOO_PODZOL_REPLACEABLE。
    canSurvive = 底面 ∈ SUPPORTS_BAMBOO（BambooStalkBlock L130-132）。
- 官方 tag（26.2-NeoForge.jar data/minecraft/tags/block/）：
    SUPPORTS_BAMBOO = #sand + #substrate_overworld + bamboo + bamboo_sapling
    + gravel + suspicious_gravel；
    BENEATH_BAMBOO_PODZOL_REPLACEABLE = #substrate_overworld；
    #substrate_overworld = #dirt + #mud + #moss_blocks + #grass_blocks。

渲染近似（与游戏唯一不可消差的差异）：
- empty/canSurvive 用「顶块 ∈ SUPPORTS_BAMBOO 且高于海平面且不在树冠下」
  近似（渲染层没有逐方块体数据）；未通过者与游戏一致地不消耗后续 RNG。
- 窗口外列无地表数据：按可存活近似消耗 height/probability（每 chunk
  独立子流，误差不跨 chunk；不影响窗口内已成图格子）。
- 竹高（5..16）不参与俯视配色（JM 竹 NoShadow 不抬高度），仅消耗 RNG。
"""
from __future__ import annotations

import json
import math
import os

import numpy as np

from Utils.MapPreviewer import vegetation as _veg
from Utils.Public.structure_map import Xoroshiro, _x_next_long_j
from Utils.SeedReverser import mc_random as _mc

_M64 = (1 << 64) - 1
_WG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "_native", "worldgen", "26.2")

_NOISE_SEED = 2345
_NOISE_FACTOR = 80.0
_NOISE_OFFSET = 0.3
_NOISE_RATIO = 160.0
_BAMBOO_PROBABILITY = 0.2          # bamboo_some_podzol.json
_VEG_STEP = 9                      # GenerationStep.Decoration.VEGETAL_DECORATION
_BAMBOO_GLOBAL_INDEX = 2           # FeatureSorter 推导（见模块 docstring）

# 官方 tag 展开后的渲染侧方块名集合（top_name 为 "minecraft:xxx"）
_SUPPORTS_BAMBOO = frozenset((
    "minecraft:sand", "minecraft:red_sand", "minecraft:suspicious_sand",
    "minecraft:dirt", "minecraft:coarse_dirt", "minecraft:rooted_dirt",
    "minecraft:mud", "minecraft:muddy_mangrove_roots",
    "minecraft:moss_block", "minecraft:pale_moss_block",
    "minecraft:grass_block", "minecraft:podzol", "minecraft:mycelium",
    "minecraft:bamboo", "minecraft:bamboo_sapling",
    "minecraft:gravel", "minecraft:suspicious_gravel",
))
_PODZOL_REPLACEABLE = frozenset((
    "minecraft:dirt", "minecraft:coarse_dirt", "minecraft:rooted_dirt",
    "minecraft:mud", "minecraft:muddy_mangrove_roots",
    "minecraft:moss_block", "minecraft:pale_moss_block",
    "minecraft:grass_block", "minecraft:podzol", "minecraft:mycelium",
))


# ---------------------------------------------------------------------------
# 1) BIOME_INFO_NOISE：LCG(2345) + 单 octave SimplexNoise 2D
# ---------------------------------------------------------------------------

class _Lcg:
    """WorldgenRandom(LegacyRandomSource) —— 标准 Java Random（mc_random）。"""

    __slots__ = ("state",)

    def __init__(self, seed: int):
        self.state = _mc.set_seed(seed)

    def next_double(self) -> float:
        v, self.state = _mc.next_double(self.state)
        return v

    def next_int(self, bound: int) -> int:
        v, self.state = _mc.next_int(self.state, bound)
        return v


class SimplexNoise2D:
    """SimplexNoise 2D getValue 逐行转录（synth/SimplexNoise.java）。"""

    _F2 = 0.5 * (math.sqrt(3.0) - 1.0)
    _G2 = (3.0 - math.sqrt(3.0)) / 6.0
    _GRADIENT = (
        (1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0),
        (1, 0, 1), (-1, 0, 1), (1, 0, -1), (-1, 0, -1),
        (0, 1, 1), (0, -1, 1), (0, 1, -1), (0, -1, -1),
        (1, 1, 0), (0, -1, 1), (-1, 1, 0), (0, -1, -1),
    )

    def __init__(self, rand: _Lcg):
        # L33-36：xo/yo/zo = 3 次 nextDouble()*256
        self.xo = rand.next_double() * 256.0
        self.yo = rand.next_double() * 256.0
        self.zo = rand.next_double() * 256.0
        # L37-48：p[256] 前向 Fisher-Yates，256 次 nextInt(256-ix)
        p = list(range(256))
        for ix in range(256):
            offset = rand.next_int(256 - ix)
            p[ix], p[offset + ix] = p[offset + ix], p[ix]
        self._p = p

    def get_value(self, xin: float, yin: float) -> float:
        # L72-104（2D 入口；base=0.5、scale=70）
        F2 = self._F2
        G2 = self._G2
        s = (xin + yin) * F2
        i = int(math.floor(xin + s))
        j = int(math.floor(yin + s))
        t = (i + j) * G2
        x0 = xin - (i - t)
        y0 = yin - (j - t)
        if x0 > y0:
            i1, j1 = 1, 0
        else:
            i1, j1 = 0, 1
        x1 = x0 - i1 + G2
        y1 = y0 - j1 + G2
        x2 = x0 - 1.0 + 2.0 * G2
        y2 = y0 - 1.0 + 2.0 * G2
        p = self._p
        ii = i & 0xFF
        jj = j & 0xFF
        gi0 = p[(ii + p[jj]) & 0xFF] % 12
        gi1 = p[(ii + i1 + p[(jj + j1) & 0xFF]) & 0xFF] % 12
        gi2 = p[(ii + 1 + p[(jj + 1) & 0xFF]) & 0xFF] % 12
        grad = self._GRADIENT

        def corner(gi, x, y):
            t0 = 0.5 - x * x - y * y
            if t0 < 0.0:
                return 0.0
            t0 *= t0
            g = grad[gi]
            return t0 * t0 * (g[0] * x + g[1] * y)

        return 70.0 * (corner(gi0, x0, y0) + corner(gi1, x1, y1)
                       + corner(gi2, x2, y2))


_BIOME_INFO_NOISE = SimplexNoise2D(_Lcg(_NOISE_SEED))


def noise_count(cx: int, cz: int) -> int:
    """NoiseBasedCountPlacement.count（与世界种子无关，只看 chunk 坐标）。"""
    v = _BIOME_INFO_NOISE.get_value(cx * 16.0 / _NOISE_FACTOR,
                                    cz * 16.0 / _NOISE_FACTOR)
    c = math.ceil((v + _NOISE_OFFSET) * _NOISE_RATIO)
    return c if c > 0 else 0


# ---------------------------------------------------------------------------
# 2) 放置流 RNG：WorldgenRandom(XoroshiroRandomSource) 语义
# ---------------------------------------------------------------------------

class _PlacementRng:
    """next(bits)=inner.nextLong()>>>(64-bits)，其余走 Java 默认。"""

    __slots__ = ("_xr",)

    def __init__(self, seed64: int):
        self._xr = Xoroshiro.from_seed(seed64 & _M64)

    def _bits(self, n: int) -> int:
        return (self._xr.next_long() >> (64 - n)) & ((1 << n) - 1)

    def next_int(self, bound: int) -> int:
        if bound <= 0:
            raise ValueError(bound)
        if bound & (bound - 1) == 0:
            return (bound * self._bits(31)) >> 31
        m = bound - 1
        while True:
            s = self._bits(31)
            val = s % bound
            # BitRandomSource L31：sample - modulo + (bound-1) < 0 重试
            if ((s - val + m) & 0xFFFFFFFF) < 0x80000000:
                return val

    def next_float(self) -> float:
        return self._bits(24) / float(1 << 24)


def _next_long_wrapped(rng: _PlacementRng) -> int:
    """BitRandomSource.nextLong = (next(32)<<32) + next(32)（64 位回绕）。"""
    upper = rng._bits(32)
    lower = rng._bits(32)
    if lower >= 1 << 31:
        lower -= 1 << 32
    return ((upper << 32) + lower) & _M64


def decoration_seed(world_seed: int, cx: int, cz: int) -> int:
    """WorldgenRandom.setDecorationSeed（L44-51，加法组合 + |1）。"""
    ws = world_seed & _M64
    xr = Xoroshiro.from_seed(ws)
    # WorldgenRandom.nextLong() 未被覆写 -> 两次 next(32)（各一次
    # inner.nextLong()），等价于 structure_map._x_next_long_j（已对拍）。
    x_scale = _x_next_long_j(xr) | 1
    z_scale = _x_next_long_j(xr) | 1
    return ((cx * x_scale + cz * z_scale) ^ ws) & _M64


def _feature_seed(world_seed: int, cx: int, cz: int) -> int:
    """decorationSeed + bamboo 全局序号 + 10000*step（setFeatureSeed）。"""
    return ((decoration_seed(world_seed, cx, cz) + _BAMBOO_GLOBAL_INDEX
             + 10000 * _VEG_STEP) & _M64)


# ---------------------------------------------------------------------------
# 3) 群系特征表：step9 含 "minecraft:bamboo" 的群系（精确判定）
# ---------------------------------------------------------------------------

_BAMBOO_BIOMES: set[str] | None = None


def _bamboo_biome_names() -> set[str]:
    """step9 特征表含 placed "minecraft:bamboo" 的群系短名（26.2 仅竹林）。"""
    global _BAMBOO_BIOMES
    if _BAMBOO_BIOMES is None:
        names = set()
        bdir = os.path.join(_WG, "biome")
        for fn in os.listdir(bdir):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(bdir, fn), "r", encoding="utf-8") as f:
                    feats = json.load(f).get("features", [])
                if (len(feats) > _VEG_STEP
                        and "minecraft:bamboo" in feats[_VEG_STEP]):
                    names.add(fn[:-5])
            except (OSError, ValueError):
                continue
        _BAMBOO_BIOMES = names
    return _BAMBOO_BIOMES


# ---------------------------------------------------------------------------
# 4) 矩形放置主入口
# ---------------------------------------------------------------------------

def bamboo_placements(seed: int, x0: int, z0: int, w: int, h: int,
                      heights: np.ndarray, top_name: np.ndarray,
                      biome_grid: np.ndarray, id2key: dict,
                      canopy: np.ndarray | None = None,
                      sea_level: int = 63):
    """官方 26.2 竹子放置链，返回 (disk_cells, dot_cells)。

    - disk_cells: [(py, px)] 灰化土盘格（画进 blocks 通道，4d 按 podzol 配色）
    - dot_cells:  [(py, px)] 竹子格（4d 后覆盖 rgb 为竹色）
    仅覆盖 step9 特征表含 "minecraft:bamboo" 的群系（26.2 = bamboo_jungle）。
    """
    bamboo_bids = []
    for bid in np.unique(biome_grid):
        key = id2key.get(int(bid), "")
        if key.split(":")[-1] in _bamboo_biome_names():
            bamboo_bids.append(int(bid))
    if not bamboo_bids:
        return [], []
    bmask = np.isin(biome_grid, bamboo_bids)
    if not bmask.any():
        return [], []
    # empty+canSurvive 的渲染近似（不通过则与游戏一致不消耗后续 RNG）
    sup = np.isin(top_name, list(_SUPPORTS_BAMBOO)) & (heights >= sea_level)
    if canopy is not None:
        sup &= ~canopy

    disk_cells: list = []
    dot_cells: list = []
    cx0, cx1 = x0 >> 4, (x0 + w - 1) >> 4
    cz0, cz1 = z0 >> 4, (z0 + h - 1) >> 4
    x1w, z1w = x0 + w, z0 + h
    for cz in range(cz0, cz1 + 1):
        for cx in range(cx0, cx1 + 1):
            n = noise_count(cx, cz)
            if n <= 0:
                continue
            rng = _PlacementRng(_feature_seed(seed, cx, cz))
            for _ in range(n):
                dx = rng.next_int(16)          # InSquare（恒消耗，x 先 z 后）
                dz = rng.next_int(16)
                px = cx * 16 + dx
                pz = cz * 16 + dz
                if not (x0 <= px < x1w and z0 <= pz < z1w):
                    # 窗外列：按可存活近似消耗后续 RNG（见模块 docstring）
                    rng.next_int(12)
                    if rng.next_float() < _BAMBOO_PROBABILITY:
                        rng.next_int(4)
                    continue
                ry = pz - z0
                rx = px - x0
                if not bmask[ry, rx]:          # BiomeFilter（无 RNG）
                    continue
                if not sup[ry, rx]:            # empty + canSurvive（无 RNG）
                    continue
                _height = rng.next_int(12) + 5     # 5..16，仅消耗
                if rng.next_float() < _BAMBOO_PROBABILITY:
                    r = rng.next_int(4) + 1
                    lim = r * r
                    for ddy in range(-r, r + 1):
                        yy = ry + ddy
                        if yy < 0 or yy >= h:
                            continue
                        for ddx in range(-r, r + 1):
                            xx = rx + ddx
                            if xx < 0 or xx >= w:
                                continue
                            if ddx * ddx + ddy * ddy > lim:
                                continue
                            if canopy is not None and canopy[yy, xx]:
                                continue
                            if top_name[yy, xx] in _PODZOL_REPLACEABLE:
                                disk_cells.append((yy, xx))
                dot_cells.append((ry, rx))
    return disk_cells, dot_cells
