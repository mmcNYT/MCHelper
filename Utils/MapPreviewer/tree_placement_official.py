# -*- coding: utf-8 -*-
"""官方 26.2 树木摆位（ChunkGenerator.applyBiomeDecoration 逐行复刻）。

与旧 tree_placement.py 的三处偏差修正（26.2 反编译实证）：
  1. RNG 派生：setFeatureSeed(decorationSeed, globalIndex, step) = 纯加法
     （旧版 decorrelated XOR 黄金比例是 1.8-1.17 语义，26.2 已无此函数）
  2. in_square：nextInt(16) x 2（Java Random 语义，先 x 后 z）
     （旧版 nextFloat*16）
  3. 数量/树种：per-feature IntProvider + placed JSON 数据驱动
     （旧版群系树概率 x 256 + 手工混生表）

权威源（.temp/mc262_decompile/，行号 26.2）：
  ChunkGenerator.applyBiomeDecoration L318-401
      decorationSeed = setDecorationSeed(seed, origin.getX(), origin.getZ())
      每 feature 前 setFeatureSeed(deco, globalIndex, step) 重置流
      possibleBiomes = 3x3 chunk 群系（L329 rangeClosed(chunk,1)）
  WorldgenRandom L30-56：next(bits) 对 Xoroshiro = nextLong()>>>(64-bits)，
      未覆写 nextInt/nextLong/nextFloat -> 走 BitRandomSource Java 语义
  BitRandomSource L17-60：nextInt(bound) 2 幂 = bound*next(31)>>31，
      非幂拒绝循环；nextLong = 两次 next(32) 高位拼接；nextFloat = next(24)*2^-24
  PlacedFeature.placeWithContext L43-61：placements 逐修饰器 flatMap，同流
  CountPlacement/RepeatingPlacement：先 sample count，origin 重复 n 次
  InSquarePlacement L17-21：nextInt(16)+origin，先 x 后 z
  RarityFilter L22：nextFloat() < 1.0F/chance（float32 比较）
  SurfaceWaterDepthFilter L25-28：WORLD_SURFACE - OCEAN_FLOOR <= max
  HeightmapPlacement L25-30：y = getHeight(OCEAN_FLOOR)（firstAvailable）
  BiomeFilter L21-25：位置群系须引用该 placed_feature（无 RNG）
  WeightedList.getRandomOrThrow L85-92：nextInt(totalWeight) 累减选取
   WeightedListInt.sample L34-36：先抽条目再抽条目值（树链均为常数，零消耗）
   Mth.randomBetweenInclusive L690-692：nextInt(max-min+1)+min

树种解析（RandomSelectorFeature L16-30 逐行复刻，逐位置共享流）：
   for WeightedPlacedFeature f : config.features():
       if random.nextFloat() < f.chance(): return f.place(...)   # 子项链照跑
   return config.defaultFeature().value().place(...)             # default 无额外 RNG
   WeightedPlacedFeature.place L19-21 -> PlacedFeature.place（无 biome check）；
   子项链普查（25 特性，selector_census.txt）：全部为
   [] / [would_survive] / [environment_scan, would_survive]，唯一非树
   子项 = bamboo_vegetation default（grass_jungle simple_block，链
   count 32 + random_offset(trapezoid ±7/±3) + 过滤，零树实例但 RNG
   消耗必须精确模拟，否则后续位置树种错位）。
   TrapezoidInt L40-52：三角特例（plateau==0 且 max==-min）=
   nextInt(max+1)-nextInt(max+1)；否则均匀/梯形公式。
   RandomOffsetPlacement L46-51：scatterX=xz.sample、scatterY=y.sample、
   scatterZ=xz.sample（xz 抽两次！）。
   EnvironmentScanPlacement L48-71：零 RNG；grove 子项链
   target=not powder_snow 在 origin（OCEAN_FLOOR 上方空气格）恒真 ->
   近似恒返回 origin（粉雪坑罕见，误差可忽略，阶段 2 再精化）。
   子项链谓词仅支持精确 y-1 顶块近似（matching_blocks），其余保留：
   未知谓词返回 True（不丢实例），worst case 仅多保留草/树。

globalIndex 表来源：.temp/extract_veg_index.py（OverworldBiomeBuilder
调用树直译 + FeatureSorter 拓扑模拟，已逐字核对官方 TreeMap/TreeSet
升序 + 后序 DFS + reverse 语义），固化于 _native/worldgen/26.2/veg_feature_index.json。
"""
from __future__ import annotations

import functools
import json
import os
import struct

import numpy as np

from Utils.Public.structure_map import (
    get_population_seed, Xoroshiro, _x_next_long_j)

_WG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "_native", "worldgen", "26.2")
_MASK64 = (1 << 64) - 1
_INT32 = 1 << 31
_VEGETAL_STEP = 9
_STEP_BASIS = 10000      # setFeatureSeed: seed + index + 10000 * step
# 树特性子项 configured type 白名单（selector_census.txt 普查全集）。
# simple_block（grass_jungle 等）消耗链上 RNG 但不产生树实例。
_TREE_CF_TYPES = frozenset((
    "tree", "fallen_tree", "huge_brown_mushroom", "huge_red_mushroom"))


def _f32(v: float) -> float:
    """Java float 舍入（float32 比较/RNG 乘法语义）。"""
    return struct.unpack("f", struct.pack("f", v))[0]


class WrapRng:
    """WorldgenRandom(new XoroshiroRandomSource(...)) 的摆位原语。

    所有 nextInt/nextLong/nextFloat 走 BitRandomSource 默认（Java Random
    语义）经 WorldgenRandom.next(bits) = (int)(nextLong() >>> (64-bits))。
    """

    __slots__ = ("_xr",)

    def __init__(self, seed: int):
        self._xr = Xoroshiro.from_seed(seed & _MASK64)

    def next_bits(self, bits: int) -> int:
        """WorldgenRandom.next(bits)，值域 [0, 2^bits)。消耗一次内部步进。"""
        return self._xr.next_long() >> (64 - bits)

    def next_int(self, bound: int) -> int:
        """BitRandomSource.nextInt(bound)（Java Random 语义，非 Lemire）。"""
        if bound <= 0:
            raise ValueError(f"bound must be positive: {bound}")
        if bound & (bound - 1) == 0:
            return self.next_bits(31) >> (31 - (bound.bit_length() - 1))
        while True:
            sample = self.next_bits(31)
            modulo = sample % bound
            # Java: do{..}while(sample - modulo + (bound-1) < 0)（int 溢出为负）
            if sample - modulo + (bound - 1) < _INT32:
                return modulo

    def next_float(self) -> float:
        """BitRandomSource.nextFloat = next(24) * 2^-24（k/2^24 精确值）。"""
        return (self._xr.next_long() >> 40) * 5.9604645E-8

    def next_boolean(self) -> bool:
        """BitRandomSource.nextBoolean = next(1) != 0（取流最高 1 位）。"""
        return (self._xr.next_long() >> 63) != 0

    def next_long(self) -> int:
        """BitRandomSource.nextLong：两次 next(32) 高位带符号拼接。"""
        return _x_next_long_j(self._xr)


def _sample_int(rng: WrapRng, spec) -> int:
    """IntProvider.sample（IntProviders.java 树链实际用到的三型）。"""
    if isinstance(spec, int):
        return spec                       # codec 内嵌常数 -> ConstantInt，零消耗
    if "type" not in spec:
        # UniformInt.MAP_CODEC.codec() 压缩格式（无 type，如 cherry
        # branch_start_offset_from_top {min_inclusive, max_inclusive}）
        lo = spec["min_inclusive"]
        hi = spec["max_inclusive"]
        return rng.next_int(hi - lo + 1) + lo     # Mth.randomBetweenInclusive
    t = spec["type"][10:]                 # 去 "minecraft:"
    if t == "constant":
        return spec["value"]
    if t == "uniform":
        lo = spec["min_inclusive"]
        hi = spec["max_inclusive"]
        return rng.next_int(hi - lo + 1) + lo     # Mth.randomBetweenInclusive
    if t == "weighted_list":
        dist = spec["distribution"]
        total = sum(item["weight"] for item in dist)
        sel = rng.next_int(total)                 # WeightedList.getRandomOrThrow
        acc = 0
        for item in dist:
            acc += item["weight"]
            if sel < acc:                          # Compact/Flat 同语义
                return _sample_int(rng, item["data"])
        raise AssertionError("weighted_list selection out of range")
    if t == "trapezoid":                       # TrapezoidInt.sample L40-52
        lo, hi, pl = spec["min"], spec["max"], spec.get("plateau", 0)
        if pl == 0 and hi == -lo:              # 三角特例（树链实际形态）
            return rng.next_int(hi + 1) - rng.next_int(hi + 1)
        span = hi - lo
        if pl == span:
            return rng.next_int(span + 1) + lo
        ps = (span - pl) // 2
        pe = span - ps
        return lo + rng.next_int(pe + 1) + rng.next_int(ps + 1)
    if t == "clamped":                         # ClampedInt.sample：
        v = _sample_int(rng, spec["source"])   # Mth.clamp(source.sample)
        return max(spec["min_inclusive"], min(spec["max_inclusive"], v))
    raise NotImplementedError(f"IntProvider type: {spec['type']}")


def _is_tree_placed(spec, pf_cache: dict, cf_cache: dict) -> bool:
    """placed_feature 项是否引用树（26.2 random_selector 子项形态）。

    str = placed registry 引用（如 spruce_checked，JSON 在 placed_feature/）；
    内嵌 dict = {feature: configured名, placement: [...]}。
    """
    if isinstance(spec, dict):
        return _is_tree_cf(spec["feature"][10:], cf_cache)
    pf_name = spec[10:]
    if pf_name in pf_cache:
        return pf_cache[pf_name]
    path = os.path.join(_WG, "placed_feature", pf_name + ".json")
    if not os.path.exists(path):
        pf_cache[pf_name] = False
        return False
    with open(path, encoding="utf-8") as f:
        pf = json.load(f)
    r = _is_tree_cf(pf["feature"][10:], cf_cache)
    pf_cache[pf_name] = r
    return r


def _is_tree_cf(name: str, cf_cache: dict) -> bool:
    """configured_feature type 链是否引用 minecraft:tree。

    26.2 JSON 形态（实测 trees_plains/trees_taiga/bamboo_vegetation）：
      random_selector = {default: str(placed)|内嵌placed,
                         features: [{chance, feature: str(placed)|内嵌placed}]}
    """
    if name in cf_cache:
        return cf_cache[name]
    path = os.path.join(_WG, "configured_feature", name + ".json")
    if not os.path.exists(path):
        cf_cache[name] = False
        return False
    with open(path, encoding="utf-8") as f:
        cf = json.load(f)
    t = cf["type"][10:]
    if t == "tree":
        cf_cache[name] = True
    elif t == "random_selector":
        c = cf["config"]
        pf_cache: dict = {}
        items = [c["default"]] + [d["feature"] for d in c.get("features", [])]
        cf_cache[name] = any(_is_tree_placed(x, pf_cache, cf_cache)
                             for x in items)
    else:
        cf_cache[name] = False
    return cf_cache[name]


@functools.lru_cache(maxsize=1)
def _load_tables():
    """树类摆位表：{feat: (gi, chain, cf_name, biomes frozenset, sel)}。

    树类判定：biome features[9] 收集候选 -> configured type 链含 tree。
    sel = (features, default)（random_selector）或 None（直接 tree 型，
    trees_cherry/swamp）；features 为 ((f32(chance), sub), ...) 声明序。
    """
    with open(os.path.join(_WG, "veg_feature_index.json"), encoding="utf-8") as f:
        index = json.load(f)["index"]          # placed 名 -> step9 拓扑序位

    feat_biomes = {}
    biome_dir = os.path.join(_WG, "biome")
    for fn in os.listdir(biome_dir):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(biome_dir, fn), encoding="utf-8") as f:
            data = json.load(f)
        feats = data.get("features", [])
        if len(feats) <= _VEGETAL_STEP:
            continue
        biome = fn[:-5]
        for nm in feats[_VEGETAL_STEP]:
            feat_biomes.setdefault(nm, set()).add("minecraft:" + biome)

    cf_cache: dict = {}
    tables = {}
    for feat, biomes in feat_biomes.items():
        if feat not in index:
            continue                            # 废弃/无人引用（如 trees_forest）
        pf_path = os.path.join(_WG, "placed_feature", feat[10:] + ".json")
        with open(pf_path, encoding="utf-8") as f:
            pf = json.load(f)
        cf_name = pf["feature"]
        if not _is_tree_cf(cf_name[10:], cf_cache):
            continue
        cf_path = os.path.join(_WG, "configured_feature", cf_name[10:] + ".json")
        with open(cf_path, encoding="utf-8") as f:
            cf = json.load(f)
        sel = (_build_selector(cf) if cf["type"][10:] == "random_selector"
               else None)                      # 直接 tree：trees_cherry/swamp
        tables[feat] = (index[feat], pf["placement"], cf_name,
                        frozenset(biomes), sel)
    return tables


@functools.lru_cache(maxsize=256)
def _cf_type(name: str):
    """configured_feature type（缺失返回 None）。"""
    path = os.path.join(_WG, "configured_feature", name + ".json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        cf = json.load(f)
    return cf["type"][10:]


def _resolve_sub(spec):
    """选择器子项 -> (chain(tuple), cf_name, is_tree)。

    str = placed registry 引用；内嵌 dict = {feature, placement}。
    """
    if isinstance(spec, dict):
        cf_name = spec["feature"]
        chain = tuple(spec.get("placement", []))
    else:
        path = os.path.join(_WG, "placed_feature", spec[10:] + ".json")
        with open(path, encoding="utf-8") as f:
            pf = json.load(f)
        cf_name = pf["feature"]
        chain = tuple(pf.get("placement", []))
    t = _cf_type(cf_name[10:])
    return chain, cf_name, t in _TREE_CF_TYPES


def _build_selector(cf):
    """random_selector config -> (features, default)。

    features: ((f32(chance), sub), ...) 按声明顺序（RandomSelectorFeature
    L23 顺序遍历）；default 无 chance（L29 全未命中时直接 place）。
    """
    c = cf["config"]
    feats = tuple((_f32(d["chance"]), _resolve_sub(d["feature"]))
                  for d in c.get("features", []))
    return feats, _resolve_sub(c["default"])


def _pred_ok(pred, px: int, pz: int, lookup) -> bool:
    """子项链 BlockPredicate 近似判定；无法判定时保留（True）。

    仅精确支持 y-1 = 最高方块（顶块近似）：子项链无 heightmap，
    origin.y-1 即该列最高方块。matching_block_tag / 含 air 检查等
    无法判定时保留（不丢实例，worst case 多保留草/树）。
    """
    t = pred["type"][10:]
    if t in ("always_true", "would_survive"):    # would_survive 由 ground_ok 外层处理
        return True
    if t == "not":
        return not _pred_ok(pred["predicate"], px, pz, lookup)
    if t == "all_of":
        return all(_pred_ok(q, px, pz, lookup)
                   for q in pred["predicates"])
    if t == "any_of":
        return any(_pred_ok(q, px, pz, lookup)
                   for q in pred["predicates"])
    if t in ("matching_blocks", "matching_block_tag"):
        if pred.get("offset", [0, 0, 0])[1] != -1 or lookup is None:
            return True
        g = lookup(px, pz)
        if g is None:
            return True
        if t == "matching_blocks":
            blocks = pred["blocks"]
            if isinstance(blocks, str):
                blocks = [blocks]
            return g in blocks
        return True                             # tag 集合展开未实现，保留
    return True


def _sub_positions(rng: WrapRng, chain, px: int, pz: int, py: int,
                   ground_ok, lookup) -> list:
    """子项链执行（RandomSelectorFeature 命中子项后的 placeWithContext）。"""
    positions = [(px, pz, py)]
    for mod in chain:
        t = mod["type"][10:]
        if t == "count":
            n = _sample_int(rng, mod["count"])
            positions = positions * n if n else []
        elif t == "random_offset":              # RandomOffsetPlacement L46-51
            xs = mod["xz_spread"]
            ys = mod["y_spread"]
            out = []
            for q in positions:
                sx = _sample_int(rng, xs)
                sy = _sample_int(rng, ys)
                sz = _sample_int(rng, xs)       # xz 抽两次
                out.append((q[0] + sx, q[1], q[2] + sz))
            positions = out
        elif t == "environment_scan":
            # 近似（docstring）：grove target=not powder_snow 在 origin
            # （OCEAN_FLOOR 上方空气格）恒真，恒返回 origin，零 RNG。
            pass
        elif t == "block_predicate_filter":
            pred = mod["predicate"]
            if pred["type"][10:] == "would_survive":
                if ground_ok is not None:
                    positions = [p for p in positions
                                 if ground_ok(p[0], p[1], p[2])]
            else:
                positions = [p for p in positions
                             if _pred_ok(pred, p[0], p[1], lookup)]
        else:
            raise NotImplementedError(f"sub placement {mod['type']}")
    return positions


def _place_one(rng: WrapRng, sel, cf_name: str, px: int, pz: int,
               py: int, ground_ok, lookup) -> list:
    """RandomSelectorFeature.place / 直接 tree 的逐位置入口。

    返回 [(y, tree_cf), ...]（树实例，一般 0 或 1 个）；非树子项
    （grass_jungle）返回 [] 但链上 RNG 已精确消耗。chance 抽样在
    子链执行之前，与 L24-25 顺序一致。
    """
    if sel is None:                             # cf 直接 tree（零消耗）
        return [(py, cf_name)]
    feats, default = sel
    sub = default
    for ch, s in feats:
        if rng.next_float() < ch:
            sub = s
            break
    chain, sub_cf, is_tree = sub
    positions = _sub_positions(rng, chain, px, pz, py, ground_ok, lookup)
    if not is_tree:
        return []
    return [(q[2], sub_cf) for q in positions]


def _hm(arr: np.ndarray, px: int, pz: int, x0: int, z0: int,
        w: int, h: int):
    """区域局部高度图查询；越界返回 None（区域外不渲染，不影响流）。"""
    lx = px - x0
    lz = pz - z0
    if 0 <= lx < w and 0 <= lz < h:
        return int(arr[lz, lx])
    return None


def place_trees_in_rect(seed: int, x0: int, z0: int, w: int, h: int,
                        hm_ocean: np.ndarray, hm_surface: np.ndarray,
                        biome_grid: np.ndarray, id2key: dict,
                        ground_ok=None, top_block_grid=None,
                        block_names=None) -> list:
    """矩形区域官方摆位，返回树实例列表。

    hm_ocean / hm_surface: (h, w) 高度图（含结构后）：
      OCEAN_FLOOR   = 最上 blocksMotion 方块 y+1（固体，不含水/空气）
      WORLD_SURFACE = 最上非空气方块 y+1（含水）
    biome_grid: (h, w) int 群系 id；id2key: id -> "minecraft:xxx"
    ground_ok: callable(wx, wz, y) -> bool，would_survive 等价判定
               （树苗 canSurvive：下方方块为 dirt 类）；None 跳过。
    top_block_grid: (h, w) 顶块色板索引（surface_grid 的 blocks 输出，
               含结构后），配合 block_names 提供 y-1 顶块谓词判定
               （grove 雪 filter 等）；None 时相关谓词全部保留。
    返回 [(wx, wz, y, feat_name, cf_name, tree_cf, rng)]：
      tree_cf = 树种最终 configured_feature 名（RandomSelectorFeature
      解析后，阶段 2 树形生成用）；rng 为摆位链+树种解析消耗后的
      WrapRng（同特性全部位置共享同一流，树形生成续用，TreeFeature
      复用传入 random）。
    """
    tables = _load_tables()
    if top_block_grid is not None and block_names is not None:
        def lookup(wx: int, wz: int):
            lx = wx - x0
            lz = wz - z0
            if 0 <= lx < w and 0 <= lz < h:
                return block_names[int(top_block_grid[lz, lx])]
            return None
    else:
        lookup = None
    out = []
    cx0, cz0 = x0 >> 4, z0 >> 4
    cx1, cz1 = (x0 + w - 1) >> 4, (z0 + h - 1) >> 4
    for cz in range(cz0, cz1 + 1):
        for cx in range(cx0, cx1 + 1):
            gx0 = cx << 4
            gz0 = cz << 4
            # 3x3 chunk 群系集合（ChunkGenerator L328-336）。区域外的部分
            # 缺失只会漏跑「仅界外群系引用」的特性，而这类特性即使跑了
            # 也必被 biome filter 拒（in_square 恒在本 chunk），结果等价。
            rx0, rz0 = max(gx0 - 16, x0), max(gz0 - 16, z0)
            rx1, rz1 = min(gx0 + 32, x0 + w), min(gz0 + 32, z0 + h)
            keys3 = set()
            if rx1 > rx0 and rz1 > rz0:
                for bid in np.unique(
                        biome_grid[rz0 - z0:rz1 - z0, rx0 - x0:rx1 - x0]):
                    keys3.add(id2key.get(int(bid)))
            keys3.discard(None)
            if not keys3:
                continue
            decoration_seed = get_population_seed(seed, gx0, gz0)
            for feat in sorted(tables, key=lambda n: tables[n][0]):
                gi, chain, cf_name, biomes, sel = tables[feat]
                if not (keys3 & biomes):
                    continue
                rng = WrapRng((decoration_seed + gi
                               + _STEP_BASIS * _VEGETAL_STEP) & _MASK64)
                positions = [(gx0, gz0, 0)]          # chunk origin（y 占位）
                try:
                    for mod in chain:
                        t = mod["type"][10:]
                        if t == "count":
                            n = _sample_int(rng, mod["count"])
                            positions = positions * n if n else []
                        elif t == "in_square":
                            positions = [
                                (rng.next_int(16) + px,
                                 rng.next_int(16) + pz, py)
                                for (px, pz, py) in positions]
                        elif t == "rarity_filter":
                            thr = _f32(1.0 / mod["chance"])
                            positions = [p for p in positions
                                         if rng.next_float() < thr]
                        elif t == "surface_water_depth_filter":
                            mx = mod["max_water_depth"]
                            positions = [
                                p for p in positions
                                if (hs := _hm(hm_surface, p[0], p[1],
                                              x0, z0, w, h)) is not None
                                and (ho := _hm(hm_ocean, p[0], p[1],
                                               x0, z0, w, h)) is not None
                                and hs - ho <= mx]
                        elif t == "heightmap":
                            positions = [
                                (p[0], p[1], y)
                                for p in positions
                                if (y := _hm(hm_ocean, p[0], p[1],
                                             x0, z0, w, h)) is not None
                                and y > -64]
                        elif t == "block_predicate_filter":
                            if mod["predicate"]["type"][10:] == "would_survive":
                                if ground_ok is not None:
                                    positions = [
                                        p for p in positions
                                        if ground_ok(p[0], p[1], p[2])]
                            else:
                                raise NotImplementedError(
                                    f"predicate {mod['predicate']['type']}")
                        elif t == "biome":
                            positions = [
                                p for p in positions
                                if 0 <= p[0] - x0 < w
                                and 0 <= p[1] - z0 < h
                                and id2key.get(
                                    int(biome_grid[p[1] - z0, p[0] - x0]))
                                in biomes]          # 越界不渲染，丢弃
                        else:
                            raise NotImplementedError(
                                f"placement {mod['type']}（feat={feat}）")
                except NotImplementedError:
                    continue                # 未支持的修饰器：跳过该特性
                for (px, pz, py) in positions:
                    try:
                        inst = _place_one(rng, sel, cf_name, px, pz, py,
                                          ground_ok, lookup)
                    except NotImplementedError:
                        inst = []           # 子链未支持修饰器：该位置无树
                    for (ty, sub_cf) in inst:
                        out.append((px, pz, ty, feat, cf_name, sub_cf, rng))
    return out
