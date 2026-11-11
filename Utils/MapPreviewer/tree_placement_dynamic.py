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
（每 chunk 的 count 次尝试完整跑，origin 在窗口外时按旧版同款丢弃）。

跨 chunk 顺序与官方不确定性（2026-11 服务器实验实测）：
官方 vanilla 26.2 同 seed 连续 3 次生成同一窗口，cherry 区树干
柱总量 267/299/251（±7.3%），20% 块发生漂移，单块比率 0.52~1.37，
spawn 区 ±4%。根因：ChunkPyramid.java L34 FEATURES 只依赖邻居
CARVERS（range 1）——邻居的树与本 chunk 的树并发竞态，谁先写完
树冠谁影响对方 swdf/origin 判定，官方每次生成都在“调度骰子”下
落在树-植被互锁级联的不同解。本实现 chunk 行序（raster）是对该
解空间的一次确定性采样：非 cherry 群系与官方 run 均值一致
（全存档 other 1.001）；cherry 区因植被密度极高（swdf 砍率对
植被列覆盖敏感）对序最敏感，窗口口径下较官方均值偏多约 16%，
处于官方 run 间方差带边缘。

用法（block_render._apply_vegetation）：
    level = decorate_trees_in_rect(seed, x0, z0, w, h, h_at, s_at, w_at,
                                   hm_ocean, hm_surface, biome_grid, id2key,
                                   biome3d_at=...)
    # 树方块在 level.blocks（含窗口外溢出列，写回时按需裁剪）
"""
from Utils.MapPreviewer import tree_placement_official as _tpo
from Utils.MapPreviewer import tree_shape_official as _tso

_MC = "minecraft:"
# supports_vegetation = #substrate_overworld + farmland（tag 实测提取）
_SUPPORTS_VEGETATION = _tso._SUBSTRATE_OVERWORLD | frozenset(("farmland",))
_TABLES_CACHE = None


class TrackingSim(_tso.SimLevel):
    """SimLevel + 写入追踪 + 动态高度图（装饰循环用）。

    active_chunk 非 None 时为「隔离判定」模式：决策层（block_name /
    heightmap_no_leaves_y / new_writes / 动态高度图）只看到本区块的
    写入，跨块溢写仅入显示层 blocks（不影响后续 attempt 判定）——
    用于对拍实验；None = 全部写入可见（旧行为）。

    committed 非 None 时为「中心圈层」模式（center 装饰序）：
    (cols, ocean, surface, motion) 四元组 = 上一圈轮次全部写入快照。
    决策层可见性 = 本轮已写入（_decision_cols）+ committed；同圈
    邻块竞态写入不可见。对齐官方机制：WorldGenRegion.getChunk
    返回 CARVERS 下标 future 的同一 ProtoChunk 对象（原地推进），
    先跑完特征且离生成中心更近的邻居溢写可见，反之不可见。
    """

    __slots__ = ("new_writes", "_dyn_ocean", "_dyn_surface", "_dyn_motion",
                 "active_chunk", "_decision_cols", "committed")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.new_writes = []
        self._dyn_ocean = {}      # (x,z) -> OCEAN_FLOOR firstAvailable
        self._dyn_surface = {}    # (x,z) -> WORLD_SURFACE firstAvailable
        self._dyn_motion = {}     # (x,z) -> MOTION_BLOCKING firstAvailable
        self.active_chunk = None  # None = 不隔离（跨块溢写可见）
        self._decision_cols = {}  # {(x,z): {y: name}} 仅当前装饰区块
        self.committed = None     # center 模式圈层快照，见类 docstring

    def set_block(self, pos, name):
        super().set_block(pos, name)
        if self.active_chunk is None:
            self.new_writes.append((pos, name))
        elif self.committed is not None:
            # center 模式：本装饰轮所有写入（含溢出邻块的树冠）对
            # 本轮后续判定可见（官方同 pass 立即可见）
            self._decision_cols.setdefault(
                (pos[0], pos[2]), {})[pos[1]] = name
            self.new_writes.append((pos, name))
        elif (pos[0] >> 4, pos[2] >> 4) == self.active_chunk:
            self._decision_cols.setdefault(
                (pos[0], pos[2]), {})[pos[1]] = name
            self.new_writes.append((pos, name))

    def set_block_quiet(self, pos, name):
        """写入但不入 new_writes（植被预铺用：不进树的回写统计）。"""
        _tso.SimLevel.set_block(self, pos, name)
        if self.active_chunk is None:
            return
        if self.committed is not None:
            self._decision_cols.setdefault(
                (pos[0], pos[2]), {})[pos[1]] = name
        elif (pos[0] >> 4, pos[2] >> 4) == self.active_chunk:
            self._decision_cols.setdefault(
                (pos[0], pos[2]), {})[pos[1]] = name

    def block_name(self, pos):
        x, y, z = pos
        if self.active_chunk is None:
            return _tso.SimLevel.block_name(self, pos)
        col = self._decision_cols.get((x, z))
        if col is not None:
            nm = col.get(y)
            if nm is not None:
                return nm
        if self.committed is None:
            return _tso.SimLevel.block_name(self, pos)
        ccol = self.committed[0].get((x, z))
        if ccol is not None:
            nm = ccol.get(y)
            if nm is not None:
                return nm
        # terrain 尾段与 SimLevel.block_name L219-223 同构
        if y <= self.height_at(x, z):
            return self.surface_at(x, z)
        if self.water_top_at is not None and y <= self.water_top_at(x, z):
            return "water"
        return "__air__"

    def heightmap_no_leaves_y(self, x, z):
        if self.active_chunk is None:
            return _tso.SimLevel.heightmap_no_leaves_y(self, x, z)
        top = self.height_at(x, z)
        if self.committed is not None:
            ccol = self.committed[0].get((x, z))
            if ccol:
                for yy, nm in ccol.items():
                    if nm in _tso._SOLID_RENDER and yy > top:
                        top = yy
        col = self._decision_cols.get((x, z))
        if col:
            for yy, nm in col.items():
                if nm in _tso._SOLID_RENDER and yy > top:
                    top = yy
        return top + 1


def _get_tables():
    """树类摆位表（模块级缓存：tile 渲染免重复读盘）。"""
    global _TABLES_CACHE
    if _TABLES_CACHE is None:
        _TABLES_CACHE = _tpo._load_tables()
    return _TABLES_CACHE


# ---------------------------------------------------------------------
# step9 植被预铺（simple_block 类非树特征）
#
# 官方机制（26.2 源码核实）：装饰期 setBlockState 实时更新
# FINAL_HEIGHTMAPS 四张图（ChunkStatus.java L18-28 + ProtoChunk.java
# L165-167）。谓词（Heightmap.java L146-157）：OCEAN_FLOOR =
# blocksMotion（植被无碰撞不抬，树叶/树干抬）；WORLD_SURFACE =
# NOT_AIR（植被/树都抬）；MOTION_BLOCKING = blocksMotion||fluid
# （植被不抬）。故植被不改变树 origin（OCEAN_FLOOR 不被植被抬），
# 树干直接替换植被层（植被 ∈ replaceable_by_trees）。
# WORLD_SURFACE_WG 自 SURFACE 阶段后不再更新（CARVERS 起
# heightmapsAfter=FINAL_HEIGHTMAPS）→ gi54 基点 = SURFACE 后静态快照。
# ---------------------------------------------------------------------

_VEG_TABLES_CACHE = None
_BIOME_F9_CACHE = {}

# DoublePlantBlock 子类（26.2）：两格花，SimpleBlockFeature 走
# DoublePlant 分支（origin+above 同名，canSurvive 查 below）
_DOUBLE_PLANTS = frozenset((
    "tall_grass", "large_fern", "lilac", "rose_bush", "peony",
    "sunflower"))

# 植被流中有碰撞的方块（PumpkinBlock 满格碰撞）：写入除 WORLD_SURFACE
# 外还抬 OCEAN_FLOOR/MOTION_BLOCKING（Heightmap.java L150-151）
_VEG_MOTION_BLOCKS = frozenset(("pumpkin",))


def _veg_pred_collect(pred, plan):
    """block_predicate_filter 谓词收集（全部零 RNG；False = 不支持）。

    支持：matching_block_tag air（run_veg 隐式 air 检查）、
    matching_blocks offset [0,-1,0]（收进 plan["below_blocks"]）、
    all_of 组合、not(matching_blocks-below)（收进
    plan["below_blocks_not"]）。其余（would_survive/matching_fluids/
    非 below 偏移/any_of 等）不支持 → 调用方判 None（链保持 veg=None）。
    """
    t = pred["type"][len(_MC):]
    if t == "matching_block_tag":
        return str(pred.get("tag", "")).endswith(":air")
    if t == "matching_blocks":
        off = pred.get("offset", [0, 0, 0])
        if off != [0, -1, 0]:
            return False
        blocks = pred["blocks"]
        if isinstance(blocks, str):
            blocks = [blocks]
        bb = plan["below_blocks"]
        if bb is None:
            bb = plan["below_blocks"] = set()
        bb.update(n[len(_MC):] if n.startswith(_MC) else n for n in blocks)
        return True
    if t == "all_of":
        return all(_veg_pred_collect(q, plan) for q in pred["predicates"])
    if t == "not":
        inner = pred["predicate"]
        if inner["type"][len(_MC):] != "matching_blocks":
            return False
        off = inner.get("offset", [0, 0, 0])
        if off != [0, -1, 0]:
            return False
        blocks = inner["blocks"]
        if isinstance(blocks, str):
            blocks = [blocks]
        bbn = plan["below_blocks_not"]
        if bbn is None:
            bbn = plan["below_blocks_not"] = set()
        bbn.update(n[len(_MC):] if n.startswith(_MC) else n for n in blocks)
        return True
    return False


def _parse_veg_chain(placement, require_offset=True):
    """植被 placed chain -> 执行计划 dict；含不支持的修饰器返回 None。

    链形泛化：count 修饰器可为常数或 spec dict（clamped/uniform 等，
    由 _sample_int 采样）。链中最后一个 count = 内层 offset 重试数；
    之前出现的 count = 外层基点数（连乘，见 plan["outer"]）。
    outer_pre_biome：外层 count 出现在 biome 修饰器之前时（官方
    flatMap 序：biome fail 也消耗 outer 采样）为 True。
    require_offset=False：simple_random_selector 父链（本层无
    random_offset，子项链各自携带）。
    """
    plan = {"noise": None, "rarity": None, "hm": None, "count": 1,
            "outer": 1, "outer_pre_biome": False, "off_xz": None,
            "off_y": None, "selector": None, "below_blocks": None,
            "below_blocks_not": None}
    counts = []
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
            if counts:
                plan["outer_pre_biome"] = True
        elif t == "count":
            counts.append(mod["count"])
        elif t == "random_offset":
            plan["off_xz"] = mod["xz_spread"]
            plan["off_y"] = mod["y_spread"]
        elif t == "block_predicate_filter":
            if not _veg_pred_collect(mod["predicate"], plan):
                return None
        else:
            return None
    if counts:
        # 最后一个 count = 内层 offset 重试数；其余 = 外层基点数连乘
        plan["count"] = counts[-1]
        outer = 1
        for spec in counts[:-1]:
            if not isinstance(spec, int):
                return None      # 外层非常数暂无案例，保守拒绝
            outer *= spec
        plan["outer"] = outer
    if plan["hm"] is None:
        return None
    if plan["off_xz"] is None and require_offset \
            and plan["selector"] is None:
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

    支持两类 configured：
    - simple_block（to_place weighted/simple state provider）
    - simple_random_selector（子项 = simple_block + 内嵌子链，
      SimpleRandomSelectorFeature L23：nextInt(n) 选子项后跑子链）
    其余置 None（如 glow_lichen 水下石面，对树判定无影响）。
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
            plan = _parse_veg_chain(pj.get("placement", []),
                                    require_offset=False)
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
        if cj.get("type") == _MC + "simple_random_selector":
            # 子项解析：simple_block + 内嵌子链（count/random_offset/
            # air；子链无 heightmap——父链已定基点 y，biome 由父链查）
            sel_items = []
            ok = True
            for sub in cj["config"]["features"]:
                sub_feat = sub["feature"]
                if sub_feat.get("type") != _MC + "simple_block":
                    ok = False
                    break
                tp = sub_feat["config"]["to_place"]
                if tp["type"][len(_MC):] not in (
                        "weighted_state_provider",
                        "simple_state_provider"):
                    ok = False
                    break
                sub_plan = {"count": 1, "off_xz": None, "off_y": None}
                for smod in sub["placement"]:
                    st = smod["type"][len(_MC):]
                    if st == "count":
                        sub_plan["count"] = smod["count"]
                    elif st == "random_offset":
                        sub_plan["off_xz"] = smod["xz_spread"]
                        sub_plan["off_y"] = smod["y_spread"]
                    elif st == "block_predicate_filter":
                        pred = smod["predicate"]
                        if not (pred["type"][len(_MC):] == "matching_block_tag"
                                and str(pred.get("tag", "")).endswith(":air")):
                            ok = False
                            break
                    else:
                        ok = False
                        break
                if not ok or sub_plan["off_xz"] is None:
                    ok = False
                    break
                sel_items.append((sub_feat, sub_plan))
            if not ok or not sel_items:
                out[full] = None
                continue
            plan["selector"] = sel_items
            out[full] = (gi, plan, cj)
            continue
        if cj.get("type") != _MC + "simple_block":
            out[full] = None
            continue
        if plan["off_xz"] is None:
            out[full] = None          # simple_block 型必须带 random_offset
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
    if name in ("brown_mushroom", "red_mushroom"):
        # MushroomBlock.canSurvive（L83-87）：below ∈
        # #overrides_mushroom_light_requirement（mycelium/podzol/
        # crimson_nylium/warped_nylium，后两者为下界块不适用）恒真；
        # 否则 getRawBrightness(pos, 0) < 13 且 mayPlaceOn（L78-80）=
        # below.isSolidRender()。装饰期在 INITIALIZE_LIGHT 之前
        # （ChunkPyramid FEATURES 先于 LIGHT），光照查询恒 0 → 只查
        # isSolidRender（SimLevel.is_solid_render 名字空间感知）
        if below not in ("mycelium", "podzol") \
                and not level.is_solid_render((x, y - 1, z)):
            return []
    elif name == "leaf_litter":
        # LeafLitterBlock.canSurvive（L54-57）：below.isFaceSturdy(UP)
        # ≈ isSolidRender（满格方块两者一致；patch 链 below_blocks
        # 已限定 grass_block，恒通过）
        if not level.is_solid_render((x, y - 1, z)):
            return []
    elif below not in _SUPPORTS_VEGETATION:
        return []
    if name in _DOUBLE_PLANTS:
        # DoublePlantBlock：origin + above 同名（SimpleBlockFeature L27-32）
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
                           debug_stat=None, isolate: bool = False,
                           chunk_order: str = "raster",
                           ring_center=(0, 0), trace_chunk=None,
                           biome3d_at=None) -> TrackingSim:
    """官方惰性流树装饰；返回 level（树方块在 level.blocks）。

    isolate=True：隔离判定实验模式——每个区块装饰时决策层只看本区块
    写入（邻块溢写不影响判定，只保留显示）；用于验证官方装饰顺序
    语义，不作为默认。
    chunk_order："raster"（z 外层 x 内层）| "ring"（按离 ring_center
    的 Chebyshev 环序，环内 (cz,cx) 升序，全部已写入可见）|
    "center"（同 ring 排序 + 圈层可见性：每圈开始快照 committed，
    决策层只看 committed + 本块/本轮已写入，同圈竞态写入不可见）。
    center 语义依据：ChunkGenerator.applyBiomeDecoration 无 shuffle、
    只放中心块；WorldGenRegion.getChunkIfPresentUnchecked 返回
    CARVERS 下标 future 的同一 ProtoChunk（原地推进）→ 先跑完且
    离生成中心更近的邻居溢写可见，同圈/外圈不可见。

    h_at/s_at/w_at: SimLevel 地形闭包（OCEAN_FLOOR 顶固体 y / 顶块名 /
    水面 y），与 block_render._apply_vegetation 现有闭包同构。
    hm_ocean/hm_surface: (h, w) 窗口静态高度图（动态 dict 的缺省回退）。
    biome_grid: (h, w) 群系 id；id2key: id -> "minecraft:xxx"。
    biome3d_at: 可选 (x, y, z) -> "minecraft:xxx"。官方 BiomeFilter
    用 origin 完整坐标的 3D 群系（BiomeFilter.java L24）；传入后
    树/植被 origin 群系检查与 keys3 特征调度集均用 3D 采样
    （keys3 稀疏采样 3×3 块地表附近 y 剖面，近似官方全 y
    possibleBiomes）；None = 用 2D 地形顶群系近似（旧行为）。
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
        WORLD_SURFACE_WG = SURFACE 后静态快照（CARVERS 起不再更新，
        ChunkStatus.java L27）；MOTION_BLOCKING 不含植被碰撞（初值=
        顶固体+1，无水区与 OCEAN_FLOOR 初值相同）；OCEAN_FLOOR /
        WORLD_SURFACE 动态（被装饰期写入实时更新，ProtoChunk L165-167）。"""
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
        sel_items = plan["selector"]
        outer_spec = plan["outer"]
        outer_pre = plan["outer_pre_biome"]
        # rarity/位置采样/place 消耗同流交织（flatMap 逐元素）
        for _ in range(c0):
            outer_n = _tpo._sample_int(rng, outer_spec)
            for _ in range(outer_n):
                if plan["rarity"] is not None \
                        and rng.next_float() >= 1.0 / plan["rarity"]:
                    continue
                px = rng.next_int(16) + xo
                pz = rng.next_int(16) + zo
                yb = hm_veg(plan["hm"], px, pz)
                if yb is None:
                    continue
                if not outer_pre:
                    # 外层 count 在 biome 下游（罕见链形）：biome
                    # fail 不消耗外层采样
                    pass
                # 官方 BiomeFilter：基点 origin (px, yb, pz) 处群系
                if biome3d_at is not None:
                    bpos = biome3d_at(px, yb, pz)
                else:
                    bpos = biome_at(px, pz)
                if bpos not in biomes:
                    continue
                if sel_items is not None:
                    # SimpleRandomSelectorFeature L23：nextInt(n) 选
                    # 子项后跑子链（子链 count/random_offset/air）
                    idx = rng.next_int(len(sel_items))
                    sub_cf, sub_plan = sel_items[idx]
                    n_inner = _tpo._sample_int(rng, sub_plan["count"])
                    off_xz = sub_plan["off_xz"]
                    off_y = sub_plan["off_y"]
                    bb = sub_plan.get("below_blocks")
                    bbn = sub_plan.get("below_blocks_not")
                else:
                    sub_cf = cf
                    n_inner = _tpo._sample_int(rng, plan["count"])
                    off_xz = plan["off_xz"]
                    off_y = plan["off_y"]
                    bb = plan["below_blocks"]
                    bbn = plan["below_blocks_not"]
                for _ in range(n_inner):
                    dx = _tpo._sample_int(rng, off_xz)
                    dy = _tpo._sample_int(rng, off_y)
                    dz = _tpo._sample_int(rng, off_xz)
                    x, y, z = px + dx, yb + dy, pz + dz
                    if not level.is_air((x, y, z)):
                        continue
                    # block_predicate_filter 谓词（all_of：air +
                    # matching_blocks below 等）在 feature.place 之前
                    # 判定（状态采样之前，无 RNG）
                    if bb or bbn:
                        bn = level.block_name((x, y - 1, z))
                        if bn.startswith(_MC):
                            bn = bn[len(_MC):]
                        if bb and bn not in bb:
                            continue
                        if bbn and bn in bbn:
                            continue
                    wr = _place_simple_block(level, rng, sub_cf, x, y, z)
                    # 植被只抬 WORLD_SURFACE（NOT_AIR 谓词）；OCEAN_FLOOR /
                    # MOTION_BLOCKING = blocksMotion，植被无碰撞不抬
                    # （Heightmap.java L150-151）；例外 _VEG_MOTION_BLOCKS
                    # （pumpkin 满格碰撞，三张全抬）
                    for (bx, by, bz), _nm in wr:
                        cur2 = dyn_get(level._dyn_surface, bx, bz, hm_surface)
                        if cur2 is not None and by + 1 > cur2:
                            level._dyn_surface[(bx, bz)] = by + 1
                        if _nm in _VEG_MOTION_BLOCKS:
                            cur = dyn_get(level._dyn_ocean, bx, bz, hm_ocean)
                            if cur is not None and by + 1 > cur:
                                level._dyn_ocean[(bx, bz)] = by + 1
                            cur3 = dyn_get(level._dyn_motion, bx, bz, hm_ocean)
                            if cur3 is not None and by + 1 > cur3:
                                level._dyn_motion[(bx, bz)] = by + 1

    chunk_list = [(cx, cz)
                  for cz in range(cz0, cz1 + 1)
                  for cx in range(cx0, cx1 + 1)]
    if chunk_order == "ring" or chunk_order == "center":
        scx, scz = ring_center
        chunk_list.sort(key=lambda cc: (max(abs(cc[0] - scx),
                                            abs(cc[1] - scz)),
                                        cc[1], cc[0]))
    round_dist = None
    for cx, cz in chunk_list:
        xo = cx << 4
        zo = cz << 4
        if chunk_order == "center" and isolate:
            raise ValueError("isolate 与 chunk_order='center' 互斥")
        if chunk_order == "center":
            _d = max(abs(cx - ring_center[0]), abs(cz - ring_center[1]))
            if _d != round_dist:
                round_dist = _d
                level.committed = (
                    {k: dict(v) for k, v in level._col_blocks.items()},
                    dict(level._dyn_ocean), dict(level._dyn_surface),
                    dict(level._dyn_motion))
        if isolate:
            # 决策层清场：本区块判定只看本轮写入
            level.active_chunk = (cx, cz)
            level._decision_cols.clear()
            for lz in range(16):
                for lx in range(16):
                    _k = (xo + lx, zo + lz)
                    level._dyn_ocean.pop(_k, None)
                    level._dyn_surface.pop(_k, None)
                    level._dyn_motion.pop(_k, None)
        elif chunk_order == "center":
            # 决策层 = committed 快照 + 本块已写入；本块 256 列动态
            # 高度图重置为 committed 值（同圈邻块本轮溢写被抹除）
            level.active_chunk = (cx, cz)
            level._decision_cols.clear()
            _co, _cs, _cm = level.committed[1], level.committed[2], \
                level.committed[3]
            for lz in range(16):
                for lx in range(16):
                    _k = (xo + lx, zo + lz)
                    level._dyn_ocean.pop(_k, None)
                    level._dyn_surface.pop(_k, None)
                    level._dyn_motion.pop(_k, None)
                    _v = _co.get(_k)
                    if _v is not None:
                        level._dyn_ocean[_k] = _v
                    _v = _cs.get(_k)
                    if _v is not None:
                        level._dyn_surface[_k] = _v
                    _v = _cm.get(_k)
                    if _v is not None:
                        level._dyn_motion[_k] = _v
        else:
            level.active_chunk = None
        # 3x3 chunk 群系集合（窗口交集近似，等价性论证见
        # tree_placement_official.place_trees_in_rect L447-457）。
        # biome3d_at 提供时用 3×3 块地表附近 y 剖面稀疏采样，近似官方
        # possibleBiomes（全 y 层 3D 群系）；否则 2D 近似。
        lx0, lz0 = max(xo - 16 - x0, 0), max(zo - 16 - z0, 0)
        lx1, lz1 = min(xo + 32 - x0, w), min(zo + 32 - z0, h)
        keys3 = set()
        if lx1 > lx0 and lz1 > lz0:
            if biome3d_at is not None:
                for lz in range(lz0, lz1, 4):
                    for lx in range(lx0, lx1, 4):
                        gx = x0 + lx
                        gz = z0 + lz
                        t = h_at(gx, gz)
                        y_lo = max(-64, t - 20) >> 2
                        y_hi = min(319, t + 60) >> 2
                        for ny in range(y_lo, y_hi + 1):
                            keys3.add(biome3d_at(gx, ny * 4, gz))
            else:
                for bid in biome_grid[lz0:lz1, lx0:lx1].reshape(-1).tolist():
                    keys3.add(id2key.get(bid))
        keys3.discard(None)
        if not keys3:
            continue
        deco = _tpo.get_population_seed(seed, xo, zo)
        do_trace = stat is not None and trace_chunk == (cx, cz)
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
                if do_trace:
                    stat.setdefault("trace", []).append(
                        ("attempt", px, pz))
                # surface_water_depth_filter（树冠同抬两图，差值不变）
                ho = dyn_get(level._dyn_ocean, px, pz, hm_ocean)
                hs = dyn_get(level._dyn_surface, px, pz, hm_surface)
                if ho is None or hs is None:
                    continue          # 窗口外（旧版越界丢弃同语义）
                if mx_water is not None and hs - ho > mx_water:
                    continue
                # heightmap（动态 OCEAN_FLOOR = 首个空气 y，含前树冠）
                y = ho
                if do_trace:
                    stat["trace"].append(
                        ("y", px, pz, y, int(hs) - int(ho),
                         int(hs) if hs is not None else -1,
                         int(ho) if ho is not None else -1))
                if y <= -64:
                    continue
                lx = px - x0
                lz = pz - z0
                if not (0 <= lx < w and 0 <= lz < h):
                    continue
                # 官方 BiomeFilter：origin (px, y, pz) 处 3D 群系
                if biome3d_at is not None:
                    bpos = biome3d_at(px, y, pz)
                else:
                    bpos = id2key.get(int(biome_grid[lz, lx]))
                if bpos not in biomes:
                    continue
                # would_survive（动态：origin 下方方块名；SimLevel
                # 名字空间树写方块=裸名、地形=带前缀名，统一剥前缀）
                below = level.block_name((px, y - 1, pz))
                if below.startswith(_MC):
                    below = below[len(_MC):]
                if below not in _SUPPORTS_VEGETATION:
                    _bump("cut_ground")
                    if do_trace:
                        stat["trace"].append(
                            ("cut_ground", px, pz, y, below))
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
                    if do_trace:
                        stat["trace"].append(("ok", px, pz, y))
                else:
                    _bump("place_fail")
                    if do_trace:
                        stat["trace"].append(("fail", px, pz, y))
                # 动态高度图更新（Heightmap.update 的 firstAvailable =
                # max(firstAvailable, y+1)）：树叶/log/bee_nest/dirt 均
                # blocksMotion 且非空气（抬三张）；leaf_litter（
                # place_on_ground decorator 写入）无碰撞、仅 NOT_AIR →
                # 只抬 WORLD_SURFACE（Heightmap.java L150-151）；_dyn_motion
                # 初值回退用 hm_ocean 仅在无水区与官方初值一致
                for (pos, nm) in level.new_writes:
                    bx, by, bz = pos
                    key = (bx, bz)
                    if nm != "leaf_litter":
                        cur = dyn_get(level._dyn_ocean, bx, bz, hm_ocean)
                        if cur is not None and by + 1 > cur:
                            level._dyn_ocean[key] = by + 1
                        cur3 = dyn_get(level._dyn_motion, bx, bz, hm_ocean)
                        if cur3 is not None and by + 1 > cur3:
                            level._dyn_motion[key] = by + 1
                    cur2 = dyn_get(level._dyn_surface, bx, bz, hm_surface)
                    if cur2 is not None and by + 1 > cur2:
                        level._dyn_surface[key] = by + 1
    level.active_chunk = None
    level.committed = None
    return level
