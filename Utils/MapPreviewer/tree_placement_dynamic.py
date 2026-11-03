# -*- coding: utf-8 -*-
"""官方惰性流树装饰（26.2 ChunkGenerator.applyBiomeDecoration 语义）。

place_trees_in_rect（静态批处理）的语义升级版，三处官方行为差异：

1. 惰性流逐位置：PlacedFeature.placeWithContext（26.2 L43-61）的
   forEach 逐位置调 feature.place()——位置 k 的 heightmap/would_survive
   过滤发生在前 k-1 棵树放置之后；树形 RNG 消耗与摆位同流交织（同一
   RandomSource，与 Java 惰性流一致）。
2. 动态 OCEAN_FLOOR 高度图：Heightmap.Types.OCEAN_FLOOR 的 predicate =
   blocksMotion（Heightmap.java L31/L150）；树叶碰撞满格 →
   BlockBehaviour.calculateSolid（L484-504）判 blocksMotion=true；
   装饰阶段 chunk 持 FINAL_HEIGHTMAPS（ChunkStatus.java L18-28），
   ProtoChunk.setBlockState（L165-166）实时更新 → 每棵树冠抬高
   OCEAN_FLOOR / WORLD_SURFACE。后续落在冠投影列的 origin 跳到冠顶 →
   would_survive（下方=树叶）砍掉。
3. TreeFeature 层动态世界：getMaxFreeTreeHeight / placeLog 的
   validTreePos 看得到前树方块（树叶 ∈ replaceable_by_trees、树干 ∈
   LOGS 豁免 → 树间不取消；地形实体块 → 削高/取消——山坡树被砍）。

26.2 数据依据：would_survive(cherry_sapling) → SaplingBlock →
VegetationBlock.canSurvive（L44-47）→ 下方 ∈ supports_vegetation
（tags/block/supports_vegetation.json = #substrate_overworld +
farmland，含 grass_block、不含树叶）；树底 grass_block ∉
cannot_replace_below_tree_trunk → 被 below_trunk_provider 换成 dirt。

窗口语义：与 place_trees_in_rect 相同——覆盖窗口的 chunk 全量装饰
（每 chunk 的 count 次尝试完整跑，origin 在窗口外时按旧版同款丢弃）；
装饰顺序为 chunk 行序（官方为调度拓扑序，单 chunk 内语义一致，跨
chunk 竞争差异仅影响窗口边缘树）。

用法（block_render._apply_vegetation）：
    level = decorate_trees_in_rect(seed, x0, z0, w, h, h_at, s_at, w_at,
                                   hm_ocean, hm_surface, biome_grid, id2key)
    # 树方块在 level.blocks（含窗口外溢出列，写回时按需裁剪）
"""
from Utils.MapPreviewer import tree_placement_official as _tpo
from Utils.MapPreviewer import tree_shape_official as _tso

_MC = "minecraft:"
# supports_vegetation = #substrate_overworld + farmland（tag 实测提取）
_SUPPORTS_VEGETATION = _tso._SUBSTRATE_OVERWORLD | frozenset(("farmland",))
_TABLES_CACHE = None


class TrackingSim(_tso.SimLevel):
    """SimLevel + 写入追踪 + 动态高度图（装饰循环用）。"""

    __slots__ = ("new_writes", "_dyn_ocean", "_dyn_surface", "_dyn_motion")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.new_writes = []
        self._dyn_ocean = {}      # (x,z) -> OCEAN_FLOOR firstAvailable
        self._dyn_surface = {}    # (x,z) -> WORLD_SURFACE firstAvailable
        self._dyn_motion = {}     # (x,z) -> MOTION_BLOCKING firstAvailable

    def set_block(self, pos, name):
        super().set_block(pos, name)
        self.new_writes.append((pos, name))

    def set_block_quiet(self, pos, name):
        """写入但不入 new_writes（植被预铺用：不进树的回写统计）。"""
        _tso.SimLevel.set_block(self, pos, name)


def _get_tables():
    """树类摆位表（模块级缓存：tile 渲染免重复读盘）。"""
    global _TABLES_CACHE
    if _TABLES_CACHE is None:
        _TABLES_CACHE = _tpo._load_tables()
    return _TABLES_CACHE


# ---------------------------------------------------------------------
# step9 植被预铺（simple_block 类非树特征）
#
# 官方机制（26.2）：step9 特征按 FeatureSorter 拓扑 gi 升序跑，植被特征
# （如 cherry_grove 的 patch_tall_grass_2 gi26 / patch_grass_plain gi54 /
# flower_cherry gi55）先于树（trees_cherry gi56）铺 short_grass /
# pink_petals，抬 OCEAN_FLOOR（非空气谓词含植被）但不抬 MOTION_BLOCKING
# （植被无碰撞）→ 后续树 origin 的 y 跳到植被上，would_survive
# （下方须 supports_vegetation）被砍。这是逐区块树数低于旧模型的主因。
# ---------------------------------------------------------------------

_VEG_TABLES_CACHE = None
_BIOME_F9_CACHE = {}


def _parse_veg_chain(placement):
    """植被 placed chain -> 执行计划 dict；含不支持的修饰器返回 None。"""
    plan = {"noise": None, "rarity": None, "hm": None, "count": 1,
            "off_xz": None, "off_y": None}
    for mod in placement:
        t = mod["type"][len(_MC):]
        if t == "noise_threshold_count":
            plan["noise"] = (mod["noise_level"], mod["below_noise"],
                             mod["above_noise"])
        elif t == "rarity_filter":
            plan["rarity"] = mod["chance"]
        elif t == "in_square":
            pass
        elif t == "heightmap":
            plan["hm"] = mod["heightmap"]
        elif t == "biome":
            pass
        elif t == "count":
            cnt = mod["count"]
            if not isinstance(cnt, int):
                return None          # 非 ConstantInt 不支持
            plan["count"] = cnt
        elif t == "random_offset":
            plan["off_xz"] = mod["xz_spread"]
            plan["off_y"] = mod["y_spread"]
        elif t == "block_predicate_filter":
            pred = mod["predicate"]
            if not (pred["type"][len(_MC):] == "matching_block_tag"
                    and str(pred.get("tag", "")).endswith(":air")):
                return None
        else:
            return None
    if plan["hm"] is None or plan["off_xz"] is None:
        return None
    return plan


def _biome_features9(biome_key):
    """biome json features[9] 集合（26.2 数据均为直接 placed 名，无 tag）。"""
    v = _BIOME_F9_CACHE.get(biome_key)
    if v is None:
        import os
        p = os.path.join(_tpo._WG, "biome", biome_key[len(_MC):] + ".json")
        try:
            import json
            d = json.load(open(p, encoding="utf-8"))
            v = frozenset(d["features"][9])
        except (OSError, KeyError, IndexError, ValueError):
            v = frozenset()
        _BIOME_F9_CACHE[biome_key] = v
    return v


def _get_veg_tables():
    """step9 非树植被摆位表：{placed 全名: (gi, plan, cf_json) | None}。

    只收录 configured=simple_block 且 to_place 为 weighted/simple
    state provider 的特征（26.2 step9 植被全集形态）；其余置 None
    （如 glow_lichen 水下石面，对树判定无影响）。
    """
    global _VEG_TABLES_CACHE
    if _VEG_TABLES_CACHE is not None:
        return _VEG_TABLES_CACHE
    import json
    import os
    trees = _get_tables()
    veg_dir = os.path.join(_tpo._WG, "placed_feature")
    cfg_dir = os.path.join(_tpo._WG, "configured_feature")
    idx = json.load(open(os.path.join(_tpo._WG, "veg_feature_index.json"),
                         encoding="utf-8"))
    order = idx["step9_order"]
    tree_names = set(trees)
    out = {}
    for gi, full in enumerate(order):
        if full in tree_names:
            continue
        pf = os.path.join(veg_dir, full[len(_MC):] + ".json")
        cf_ref = None
        if os.path.exists(pf):
            pj = json.load(open(pf, encoding="utf-8"))
            plan = _parse_veg_chain(pj.get("placement", []))
            if plan is not None:
                ref = pj.get("feature")
                if isinstance(ref, str):
                    cf_ref = ref
        if cf_ref is None:
            out[full] = None
            continue
        cfp = os.path.join(cfg_dir, cf_ref[len(_MC):] + ".json")
        if not os.path.exists(cfp):
            out[full] = None
            continue
        cj = json.load(open(cfp, encoding="utf-8"))
        if cj.get("type") != _MC + "simple_block":
            out[full] = None
            continue
        tp = cj["config"]["to_place"]
        if tp["type"][len(_MC):] not in ("weighted_state_provider",
                                          "simple_state_provider"):
            out[full] = None
            continue
        out[full] = (gi, plan, cj)
    _VEG_TABLES_CACHE = out
    return out


def _place_simple_block(level, rng, cf, x, y, z):
    """SimpleBlockFeature.place（26.2 L17-47）：state 采样（消耗）→
    canSurvive → DoublePlantBlock 上格检查 → 写入。返回写入方块列表。"""
    tp = cf["config"]["to_place"]
    tt = tp["type"][len(_MC):]
    if tt == "weighted_state_provider":
        entries = tp["entries"]
        total = sum(int(e["weight"]) for e in entries)
        sel = rng.next_int(total)
        acc = 0
        st = None
        for e in entries:
            acc += int(e["weight"])
            if sel < acc:
                st = e["data"]
                break
        if st is None:
            return []
        name = st["Name"][len(_MC):]
    else:
        name = tp["state"]["Name"][len(_MC):]
    below = level.block_name((x, y - 1, z))
    if below.startswith(_MC):
        below = below[len(_MC):]
    if below not in _SUPPORTS_VEGETATION:
        return []
    if name == "tall_grass":
        if not level.is_air((x, y + 1, z)):
            return []
        level.set_block_quiet((x, y, z), name)
        level.set_block_quiet((x, y + 1, z), name)
        return [((x, y, z), name), ((x, y + 1, z), name)]
    level.set_block_quiet((x, y, z), name)
    return [((x, y, z), name)]


def decorate_trees_in_rect(seed: int, x0: int, z0: int, w: int, h: int,
                           h_at, s_at, w_at, hm_ocean, hm_surface,
                           biome_grid, id2key: dict,
                           debug_stat=None) -> TrackingSim:
    """官方惰性流树装饰；返回 level（树方块在 level.blocks）。

    h_at/s_at/w_at: SimLevel 地形闭包（OCEAN_FLOOR 顶固体 y / 顶块名 /
    水面 y），与 block_render._apply_vegetation 现有闭包同构。
    hm_ocean/hm_surface: (h, w) 窗口静态高度图（动态 dict 的缺省回退）。
    biome_grid: (h, w) 群系 id；id2key: id -> "minecraft:xxx"。
    debug_stat: 可选 Counter，回填 attempt/reach_place/place_ok 等诊断。
    """
    level = TrackingSim(h_at, s_at, w_at)
    tables = _get_tables()
    cx0, cz0 = x0 >> 4, z0 >> 4
    cx1, cz1 = (x0 + w - 1) >> 4, (z0 + h - 1) >> 4
    stat = debug_stat if debug_stat is not None else None

    def _bump(key):
        if stat is not None:
            stat[key] = stat.get(key, 0) + 1

    def dyn_get(d, x, z, base):
        v = d.get((x, z))
        if v is not None:
            return v
        lx = x - x0
        lz = z - z0
        if 0 <= lx < w and 0 <= lz < h:
            return int(base[lz, lx])
        return None

    def biome_at(x, z):
        lx = x - x0
        lz = z - z0
        if 0 <= lx < w and 0 <= lz < h:
            return id2key.get(int(biome_grid[lz, lx]))
        return None

    def hm_veg(hm_type, x, z):
        """HeightmapPlacement：类型 -> 实时高度（窗口外 None）。
        WORLD_SURFACE_WG = surface 快照（装饰期不随特征更新）；
        MOTION_BLOCKING 不含植被碰撞（初值=顶固体+1）；
        OCEAN_FLOOR/WORLD_SURFACE 含植被（非空气谓词）。"""
        if hm_type == "WORLD_SURFACE_WG":
            lx = x - x0
            lz = z - z0
            if 0 <= lx < w and 0 <= lz < h:
                return int(hm_surface[lz, lx])
            return None
        if hm_type == "MOTION_BLOCKING":
            return dyn_get(level._dyn_motion, x, z, hm_ocean)
        if hm_type == "OCEAN_FLOOR":
            return dyn_get(level._dyn_ocean, x, z, hm_ocean)
        if hm_type == "WORLD_SURFACE":
            return dyn_get(level._dyn_surface, x, z, hm_surface)
        return None

    def run_veg(gi, plan, cf, biomes):
        """step9 植被特征完整流（chain flatMap 顺序逐层）。"""
        rng = _tpo.WrapRng(
            (deco + gi + _tpo._STEP_BASIS * _tpo._VEGETAL_STEP)
            & _tpo._MASK64)
        noise = plan["noise"]
        c0 = 1
        if noise is not None:
            # NoiseThresholdCountPlacement.count（零 RNG）：
            # Biome.BIOME_INFO_NOISE.getValue(x/200, z/200, false)
            from Utils.MapPreviewer.density_sampler import _biome_info_noise
            nz = _biome_info_noise().get_value(xo / 200.0, zo / 200.0,
                                               False)
            c0 = noise[2] if nz >= noise[0] else noise[1]
            if c0 <= 0:
                return
        # rarity/位置采样/place 消耗同流交织（flatMap 逐元素）
        for _ in range(c0):
            if plan["rarity"] is not None \
                    and rng.next_float() >= 1.0 / plan["rarity"]:
                continue
            px = rng.next_int(16) + xo
            pz = rng.next_int(16) + zo
            yb = hm_veg(plan["hm"], px, pz)
            if yb is None:
                continue
            if biome_at(px, pz) not in biomes:
                continue
            for _ in range(plan["count"]):
                dx = _tpo._sample_int(rng, plan["off_xz"])
                dy = _tpo._sample_int(rng, plan["off_y"])
                dz = _tpo._sample_int(rng, plan["off_xz"])
                x, y, z = px + dx, yb + dy, pz + dz
                if not level.is_air((x, y, z)):
                    continue
                wr = _place_simple_block(level, rng, cf, x, y, z)
                # 植被 = 非空气非流体 -> 抬 OCEAN_FLOOR/WORLD_SURFACE；
                # 无碰撞 -> 不抬 MOTION_BLOCKING
                for (bx, by, bz), _nm in wr:
                    cur = dyn_get(level._dyn_ocean, bx, bz, hm_ocean)
                    if cur is not None and by + 1 > cur:
                        level._dyn_ocean[(bx, bz)] = by + 1
                    cur2 = dyn_get(level._dyn_surface, bx, bz, hm_surface)
                    if cur2 is not None and by + 1 > cur2:
                        level._dyn_surface[(bx, bz)] = by + 1

    for cz in range(cz0, cz1 + 1):
        for cx in range(cx0, cx1 + 1):
            xo = cx << 4
            zo = cz << 4
            # 3x3 chunk 群系集合（窗口交集近似，等价性论证见
            # tree_placement_official.place_trees_in_rect L447-457）
            lx0, lz0 = max(xo - 16 - x0, 0), max(zo - 16 - z0, 0)
            lx1, lz1 = min(xo + 32 - x0, w), min(zo + 32 - z0, h)
            keys3 = set()
            if lx1 > lx0 and lz1 > lz0:
                for bid in biome_grid[lz0:lz1, lx0:lx1].reshape(-1).tolist():
                    keys3.add(id2key.get(bid))
            keys3.discard(None)
            if not keys3:
                continue
            deco = _tpo.get_population_seed(seed, xo, zo)
            # 树 + 植被特征按官方拓扑 gi 升序交织（植被先铺会砍树位）
            veg = _get_veg_tables()
            jobs = []
            for n in tables:
                if keys3 & tables[n][3]:
                    jobs.append((tables[n][0], 0, n))
            for n, vt in veg.items():
                if vt is None:
                    continue
                gi_v, plan_v, cf_v = vt
                fb = {k for k in keys3 if n in _biome_features9(k)}
                if not fb:
                    continue
                jobs.append((gi_v, 1, n))
            jobs.sort()
            for gi, kind, name in jobs:
                if kind == 1:
                    run_veg(gi, veg[name][1], veg[name][2],
                            {k for k in keys3
                             if name in _biome_features9(k)})
                    continue
                feat = name
                gi, chain, cf_name, biomes, sel = tables[feat]
                rng = _tpo.WrapRng(
                    (deco + gi + _tpo._STEP_BASIS * _tpo._VEGETAL_STEP)
                    & _tpo._MASK64)
                # count 采样（每 chunk 每特性恰好一次，RepeatingPlacement
                # 首位置流过时求值）+ 主链修饰器类型检查
                n = 1
                bad = False
                mx_water = None
                for mod in chain:
                    t = mod["type"][len(_MC):]
                    if t == "count":
                        n = _tpo._sample_int(rng, mod["count"])
                    elif t == "surface_water_depth_filter":
                        mx_water = mod["max_water_depth"]
                    elif t in ("in_square", "heightmap", "biome"):
                        pass
                    elif t == "block_predicate_filter":
                        # would_survive 的判定与树苗种类无关（只查下方
                        # 方块 tag），主链统一在逐位置步处理；其它谓词
                        # 未支持（与旧版 NotImplementedError 同行为）
                        if (mod["predicate"]["type"][len(_MC):]
                                != "would_survive"):
                            bad = True
                            break
                    else:
                        bad = True
                        break
                if bad:
                    continue
                for _ in range(n):
                    _bump("attempt")
                    px = rng.next_int(16) + xo
                    pz = rng.next_int(16) + zo
                    # surface_water_depth_filter（树冠同抬两图，差值不变）
                    ho = dyn_get(level._dyn_ocean, px, pz, hm_ocean)
                    hs = dyn_get(level._dyn_surface, px, pz, hm_surface)
                    if ho is None or hs is None:
                        continue          # 窗口外（旧版越界丢弃同语义）
                    if mx_water is not None and hs - ho > mx_water:
                        continue
                    # heightmap（动态 OCEAN_FLOOR = 首个空气 y，含前树冠）
                    y = ho
                    if y <= -64:
                        continue
                    lx = px - x0
                    lz = pz - z0
                    if not (0 <= lx < w and 0 <= lz < h):
                        continue
                    if id2key.get(int(biome_grid[lz, lx])) not in biomes:
                        continue
                    # would_survive（动态：origin 下方方块名；SimLevel
                    # 名字空间树写方块=裸名、地形=带前缀名，统一剥前缀）
                    below = level.block_name((px, y - 1, pz))
                    if below.startswith(_MC):
                        below = below[len(_MC):]
                    if below not in _SUPPORTS_VEGETATION:
                        _bump("cut_ground")
                        continue
                    # TreeFeature.place 内联（树形 RNG 与摆位同流交织，
                    # 方块写入 level 后对后续尝试可见）
                    _bump("reach_place")
                    level.new_writes.clear()
                    placed = False
                    try:
                        inst = _tpo._place_one(rng, sel, cf_name, px, pz, y,
                                               None, None)
                        for (ty, sub_cf) in inst:
                            if _tso.place_configured_feature(
                                    level, rng, (px, ty, pz), sub_cf):
                                placed = True
                    except NotImplementedError:
                        placed = False
                    if placed:
                        _bump("place_ok")
                    else:
                        _bump("place_fail")
                    # 动态高度图更新：树写入方块均 motion blocking / 非
                    # 空气（log/leaves/bee_nest/dirt），等价 Heightmap.
                    # update 的 firstAvailable = max(firstAvailable, y+1)
                    for (pos, nm) in level.new_writes:
                        bx, by, bz = pos
                        key = (bx, bz)
                        cur = dyn_get(level._dyn_ocean, bx, bz, hm_ocean)
                        if cur is not None and by + 1 > cur:
                            level._dyn_ocean[key] = by + 1
                        cur2 = dyn_get(level._dyn_surface, bx, bz, hm_surface)
                        if cur2 is not None and by + 1 > cur2:
                            level._dyn_surface[key] = by + 1
                        cur3 = dyn_get(level._dyn_motion, bx, bz, hm_ocean)
                        if cur3 is not None and by + 1 > cur3:
                            level._dyn_motion[key] = by + 1
    return level
