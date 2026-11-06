# -*- coding: utf-8 -*-
"""官方 26.2 树形逐格直译引擎（TreeFeature / TrunkPlacer / FoliagePlacer /
TreeDecorator / RootPlacer / HugeMushroom / FallenTree）。

与 tree_placement_official.py 组成完整链路：摆位层产出
(x, z, y, feat, cf_name, tree_cf, rng)，本模块在同一 WrapRng 流上继续，
逐位置复刻树的方块形态（26.2 未混淆反编译逐行直译）。

权威源（.temp/mc262_decompile/，行号 26.2）：
  TreeFeature.java            place/doPlace/getMaxFreeTreeHeight/FoliageSetter
  TrunkPlacer.java            getTreeHeight/placeLog/placeLogIfFree/isFree
  StraightTrunkPlacer.java    简单柱 + attachment(origin+h)
  FancyTrunkPlacer.java       cluster 循环(每 cluster 恒 2×nextFloat)/makeLimb
  ForkingTrunkPlacer.java     倾斜主杆 + 二次方向 nextInt(4) 恒消耗
  GiantTrunkPlacer.java       2x2 柱 + 4×placeBelow
  MegaJungleTrunkPlacer.java  Giant + 螺旋枝(branchHeight-=2+nextInt(4))
  DarkOakTrunkPlacer.java     2x2 倾斜 + 12×nextInt(3) 恒消耗 + 顶 attachment
  UpwardsBranchingTrunkPlacer 红树干（placeBranch 每步 attachment）
  FoliagePlacer.java          placeLeavesRow/挂叶(可变 pos 累积移动)/tryPlaceLeaf
  Blob/Spruce/Pine/MegaPine/Bush/Fancy/MegaJungle/Acacia/DarkOak/Cherry/
  RandomSpreadFoliagePlacer   11 种树冠几何（RNG 消耗点逐个核对）
  TreeDecorator.java          Context = Set 复制 + y 升序稳定排序
  Beehive/TrunkVine/LeaveVine/Cocoa/AttachedToLogs/PlaceOnGround/
  AlterGround/AttachedToLeaves/PaleMoss/CreakingHeartDecorator
  Util.java                   getRandom=nextInt(len)/shuffle=Fisher-Yates
                              (for i=size..2: swap(i-1, nextInt(i)), size-1 次消耗)
  WeightedList.java           getRandomOrThrow = nextInt(total) 按插入序累计
  RootPlacer/MangroveRootPlacer  getTrunkOrigin(sample)/根模拟递归
  AbstractHugeMushroomFeature + HugeBrown/RedMushroomFeature
  FallenTreeFeature           桩+倒木（setBlock 无条件，不走 validTreePos）

关键语义落定（防回归）：
  - doPlace 把 clippedTreeHeight（ getMaxFreeTreeHeight 削剪后）传给
    placeTrunk/createFoliage，不是原 treeHeight
  - FoliageSetter.isSet 是 per-tree 的 foliage 集合；level 查询跨树共享
  - REPLACEABLE_BY_TREES 包含 #leaves/vine/leaf_litter/water（树干可穿过
    邻树的叶/藤）；本场景 PERSISTENT 恒 False（无预置 persistent 叶）
  - below_trunk_provider = NOT(cannot_replace_below_tree_trunk) -> dirt：
    草地(grass_block 不在 #dirt)会放 dirt 且该位置进 trunks 集合
    （logs[0] 可能是 y=地面 的 dirt，影响 bee_nest/PlaceOnGround minY）
  - Java yo/2 与 (int) 均向零截断（Python 必须用 int()，不能用 //）
  - float32 语义（Mth.floor(0.5F+i*dx)、Mth.sqrt/cos、(float)(PI*2)）
    经 _f32 逐步模拟，见各处注释

已知近似（记录于 CODEBASE.md）：
  - Java HashSet 迭代序不复刻：trunks/foliage 用插入序近似。影响仅限
    decorators 的 logs/leaves 同 y 遍历顺序（leaf_litter/蘑菇/可可的
    撒点先后），RNG 消耗次数不受影响（shuffle 消耗只依赖 size）
  - updateLeaves 的 distance 属性不建模（渲染色板无关）
  - PaleMoss 的 PALE_MOSS_PATCH 嵌套 feature 不放置方块（pale garden
    不在渲染范围），RNG 消耗按 0 建模
"""
from __future__ import annotations

import functools
import json
import math
import os

from Utils.MapPreviewer.tree_placement_official import (
    _WG,
    _f32,
    _sample_int,
)

# ======================================================================
# 常量与 tag（26.2 tags/block/*.json 展开，只收录本引擎可遇到的方块）
# ======================================================================

# Direction.values() 声明序
_DIRS6 = ("down", "up", "north", "south", "west", "east")
# Direction.Plane.HORIZONTAL 迭代序（getRandomDirection/getClockWise 基准）
_DIRS4_H = ("north", "east", "south", "west")
_STEP = {
    "north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0),
    "up": (0, 1), "down": (0, -1),
}
_OPPOSITE = {"north": "south", "south": "north", "west": "east",
             "east": "west", "up": "down", "down": "up"}
# alongEdge -> getClockWise()（FoliagePlacer 挂叶用）
_CLOCKWISE = {"north": "east", "east": "south", "south": "west", "west": "north"}
# getAxisDirection() == POSITIVE
_POSITIVE_AXIS = {"north": False, "south": True, "west": False, "east": True}

# tags/block/replaceable_by_trees.json（含 #leaves/#small_flowers 展开）
_REPLACABLE_BY_TREES = frozenset((
    "short_grass", "fern", "dead_bush", "vine", "glow_lichen", "sunflower",
    "lilac", "rose_bush", "peony", "tall_grass", "large_fern", "hanging_roots",
    "pitcher_plant", "water", "seagrass", "tall_seagrass", "bush",
    "firefly_bush", "warped_roots", "nether_sprouts", "crimson_roots",
    "leaf_litter", "short_dry_grass", "tall_dry_grass", "pale_moss_carpet",
    "dandelion", "poppy", "blue_orchid", "allium", "azure_bluet",
    "oxeye_daisy", "cornflower", "lily_of_the_valley", "wither_rose",
    "pink_petals", "torchflower", "open_eyeblossom", "closed_eyeblossom",
))
# tags/block/logs.json -> logs_that_burn + crimson/warped stems（树场景子集）
_LOGS_SET = frozenset((
    "oak_log", "spruce_log", "birch_log", "jungle_log", "acacia_log",
    "dark_oak_log", "mangrove_log", "cherry_log", "pale_oak_log",
    "oak_wood", "spruce_wood", "birch_wood", "jungle_wood", "acacia_wood",
    "dark_oak_wood", "mangrove_wood", "cherry_wood", "pale_oak_wood",
    "stripped_oak_log", "stripped_spruce_log", "stripped_birch_log",
    "stripped_jungle_log", "stripped_acacia_log", "stripped_dark_oak_log",
    "stripped_mangrove_log", "stripped_cherry_log", "stripped_pale_oak_log",
    "crimson_stem", "warped_stem", "crimson_stem_stripped", "warped_stem_stripped",
))
# #leaves（REPLACEABLE_BY_TREES 引用，isAirOrLeaves 也用）
_LEAVES_SET = frozenset((
    "oak_leaves", "spruce_leaves", "birch_leaves", "jungle_leaves",
    "acacia_leaves", "dark_oak_leaves", "mangrove_leaves", "cherry_leaves",
    "pale_oak_leaves", "azalea_leaves", "flowering_azalea_leaves",
))
# cannot_replace_below_tree_trunk.json = #dirt + #mud + #moss_blocks + podzol
_CANNOT_REPLACE_BELOW_TRUNK = frozenset((
    "dirt", "coarse_dirt", "rooted_dirt", "mud", "muddy_mangrove_roots",
    "moss_block", "podzol",
))
# substrate_overworld.json = #dirt + #mud + #moss_blocks + #grass_blocks
_SUBSTRATE_OVERWORLD = frozenset((
    "dirt", "coarse_dirt", "rooted_dirt", "mud", "muddy_mangrove_roots",
    "moss_block", "grass_block",
))
# huge_brown/red_mushroom_can_place_on.json = substrate + mycelium + podzol
_MUSHROOM_CAN_PLACE_ON = _SUBSTRATE_OVERWORLD | frozenset(("mycelium", "podzol"))
# replaceable_by_mushrooms.json（蘑菇 placeMushroomBlock 谓词）
_REPLACABLE_BY_MUSHROOMS = _REPLACABLE_BY_TREES | frozenset((
    "brown_mushroom", "red_mushroom", "brown_mushroom_block", "red_mushroom_block",
))
# isSolidRender 近似集合（PlaceOnGround 的地面判定；树写入方块（裸名）。
# 注意 mangrove_roots/leaves/leaf_litter/cocoa/vine 均非 solid render）
_SOLID_RENDER = frozenset((
    "oak_log", "spruce_log", "birch_log", "jungle_log", "acacia_log",
    "dark_oak_log", "mangrove_log", "cherry_log", "pale_oak_log",
    "bee_nest", "podzol", "dirt", "coarse_dirt", "rooted_dirt",
    "mushroom_stem", "brown_mushroom_block", "red_mushroom_block",
    "creaking_heart", "muddy_mangrove_roots",
))
# 地形名（surface_grid 输出，带 minecraft: 前缀）中非 isSolidRender 的
# 薄层/流体（canOcclude=false）：其余地形块（草方块/土/石/沙/毯）满格
_TERRAIN_NON_SOLID = frozenset((
    "snow", "water", "moss_carpet", "pale_moss_carpet", "lava",
))
_MC = "minecraft:"

_TAG_SETS = {
    "minecraft:cannot_replace_below_tree_trunk": _CANNOT_REPLACE_BELOW_TRUNK,
    "minecraft:beneath_tree_podzol_replaceable": _SUBSTRATE_OVERWORLD,
    "minecraft:substrate_overworld": _SUBSTRATE_OVERWORLD,
    "minecraft:huge_brown_mushroom_can_place_on": _MUSHROOM_CAN_PLACE_ON,
    "minecraft:huge_red_mushroom_can_place_on": _MUSHROOM_CAN_PLACE_ON,
    "minecraft:logs": _LOGS_SET,
    "minecraft:leaves": _LEAVES_SET,
}


def _is_leaves(name: str) -> bool:
    return name in _LEAVES_SET


def _rel(pos, direction: str, n: int = 1):
    return (pos[0] + _STEP[direction][0] * n, pos[1] + _STEP[direction][1] * n, pos[2])


def _rel_xz(pos, direction: str, n: int = 1):
    return (pos[0] + _STEP[direction][0] * n, pos[1], pos[2] + _STEP[direction][1] * n)


def _util_shuffle(lst, rng) -> None:
    """Util.shuffle：for i=size..2: swap(i-1, nextInt(i))，size-1 次消耗。"""
    size = len(lst)
    for i in range(size, 1, -1):
        swap_to = rng.next_int(i)
        lst[i - 1], lst[swap_to] = lst[swap_to], lst[i - 1]


def _shuffled_copy(lst, rng):
    """Util.shuffledCopy：复制后 shuffle（空列表零消耗）。"""
    copy = list(lst)
    _util_shuffle(copy, rng)
    return copy


def _dir4(rng) -> str:
    """Direction.Plane.HORIZONTAL.getRandomDirection = array[nextInt(4)]。"""
    return _DIRS4_H[rng.next_int(4)]


# ======================================================================
# SimLevel：WorldGenLevel 最小语义（地形高度图 + 树方块共享字典）
# ======================================================================

class SimLevel:
    """装饰阶段世界快照。

    height_at(x, z)  -> int    地形顶固体 y（OCEAN_FLOOR 语义：最高固体）
    surface_at(x, z) -> str    地形顶方块名（provider 谓词判定用）
    water_top_at(x, z) -> int  水面 y（低于/等于地形时表示无水，可传 None）

    blocks: {(x, y, z): block_name}——本装饰轮所有树共享（先放树对后放树
    的 validTreePos/isFree 可见）。
    """

    __slots__ = ("blocks", "height_at", "surface_at", "water_top_at",
                 "min_y", "max_y", "_col_blocks")

    def __init__(self, height_at, surface_at, water_top_at=None,
                 min_y: int = -64, max_y: int = 319):
        self.blocks = {}
        self.height_at = height_at
        self.surface_at = surface_at
        self.water_top_at = water_top_at
        self.min_y = min_y
        self.max_y = max_y
        self._col_blocks = {}      # {(x, z): {y: name}} 加速列查询

    # -------------------------------------------------- 世界查询
    def block_name(self, pos):
        x, y, z = pos
        col = self._col_blocks.get((x, z))
        if col is not None:
            name = col.get(y)
            if name is not None:
                return name
        if y <= self.height_at(x, z):
            return self.surface_at(x, z)
        if self.water_top_at is not None and y <= self.water_top_at(x, z):
            return "water"
        return "__air__"

    def is_air(self, pos) -> bool:
        return self.block_name(pos) == "__air__"

    def is_air_or_vine(self, pos) -> bool:
        n = self.block_name(pos)
        return n == "__air__" or n == "vine"

    def valid_tree_pos(self, pos) -> bool:
        """TreeFeature.validTreePos（26.2 L52-53）= isAir || REPLACEABLE_BY_TREES。

        注意 26.2 的 #replaceable_by_trees 首项即 #leaves（树叶可被树
        覆写），故等价于旧版 isAirOrLeaves 语义加新植物；_LEAVES_SET
        冗余保留以兼容。"""
        n = self.block_name(pos)
        if n == "__air__":
            return True
        return n in _REPLACABLE_BY_TREES or n in _LEAVES_SET

    def is_free(self, pos) -> bool:
        """TrunkPlacer.isFree = validTreePos || LOGS。"""
        return self.valid_tree_pos(pos) or self.block_name(pos) in _LOGS_SET

    def is_air_or_leaves(self, pos) -> bool:
        n = self.block_name(pos)
        return n == "__air__" or n in _LEAVES_SET

    def is_vine(self, pos) -> bool:
        return self.block_name(pos) == "vine"

    def is_solid_render(self, pos) -> bool:
        """BlockState.isSolidRender（canOcclude 满格）。

        名字空间：地形名带 minecraft: 前缀（surface_grid 输出），
        默认 solid，除 _TERRAIN_NON_SOLID 薄层/流体；树写方块为裸名
        （查 _SOLID_RENDER：log/bee_nest/dirt/podzol/蘑菇块等；树叶/
        植被/leaf_litter 不在集合 -> 非 solid）。"""
        n = self.block_name(pos)
        if n.startswith(_MC):
            return n[len(_MC):] not in _TERRAIN_NON_SOLID
        return n in _SOLID_RENDER

    def is_face_sturdy_up(self, pos) -> bool:
        """isOverSolidGround：below 方块顶面坚固（地形固体或全格原木）。"""
        below = (pos[0], pos[1] - 1, pos[2])
        return self.is_solid_render(below)

    def heightmap_no_leaves_y(self, x, z) -> int:
        """MOTION_BLOCKING_NO_LEAVES firstAvailable = 最高阻挡方块 y+1。

        地形顶必然阻挡；dict 中 solid_render 方块（原木/蜂巢等）可抬高。
        """
        top = self.height_at(x, z)
        col = self._col_blocks.get((x, z))
        if col:
            for y, name in col.items():
                if name in _SOLID_RENDER and y > top:
                    top = y
        return top + 1

    # -------------------------------------------------- 写入
    def set_block(self, pos, name: str) -> None:
        self.blocks[pos] = name
        self._col_blocks.setdefault((pos[0], pos[2]), {})[pos[1]] = name


# ======================================================================
# StateProvider（simple / weighted / rule_based）
# ======================================================================

class _SimpleProvider:
    __slots__ = ("block",)

    def __init__(self, block: str):
        self.block = block

    def get_state(self, level, rng, pos) -> str:
        return self.block

    def get_optional_state(self, level, rng, pos):
        return self.block


class _WeightedProvider:
    """WeightedStateProvider：nextInt(total) 按插入序累计取条目（1 次消耗）。"""

    __slots__ = ("entries", "total")

    def __init__(self, entries):
        self.entries = entries            # [(weight, block_name)] 插入序
        self.total = sum(w for w, _ in entries)

    def get_state(self, level, rng, pos) -> str:
        sel = rng.next_int(self.total)
        acc = 0
        for w, name in self.entries:
            acc += w
            if sel < acc:
                return name
        raise AssertionError("weighted selection out of range")

    def get_optional_state(self, level, rng, pos):
        return self.get_state(level, rng, pos)


class _RandomizedIntProvider:
    """RandomizedIntStateProvider：仅建模 block 名 + values 采样 RNG 消耗。

    Java getState：source.getState 后 setValue(property, values.sample)。目标
    方块（mangrove_propagule）恒有 age 属性 -> 每 get_state 恒消耗 1；
    属性值不入渲染色板，不建模。
    """

    __slots__ = ("name", "values")

    def __init__(self, name, values):
        self.name = name
        self.values = values

    def get_state(self, level, rng, pos) -> str:
        _sample_int(rng, self.values)     # setValue(property, sample)
        return self.name

    def get_optional_state(self, level, rng, pos):
        return self.get_state(level, rng, pos)


class _RuleBasedProvider:
    """RuleBasedStateProvider：逐 rule ifTrue 判定 -> then（零 RNG）。"""

    __slots__ = ("rules",)

    def __init__(self, rules):
        self.rules = rules                # [(pred_fn, provider)]

    def get_state(self, level, rng, pos) -> str:
        s = self.get_optional_state(level, rng, pos)
        return s if s is not None else "__air__"

    def get_optional_state(self, level, rng, pos):
        for pred, then in self.rules:
            if pred(level, pos):
                return then.get_state(level, rng, pos)
        return None


def _parse_pred(j):
    t = j["type"][len(_MC):]
    if t == "matching_block_tag":
        tag = j["tag"]
        tags = _TAG_SETS.get(tag)
        if tags is None:
            # 未知 tag：宽松匹配（不丢放置），记录名便于普查
            tags = frozenset()
        if not tags:
            return lambda level, pos: False
        return lambda level, pos: level.block_name(pos) in tags
    if t == "matching_blocks":
        blocks = frozenset(b[len(_MC):] if b.startswith(_MC) else b
                           for b in j.get("blocks", []))
        return lambda level, pos: level.block_name(pos) in blocks
    if t == "not":
        inner = _parse_pred(j["predicate"])
        return lambda level, pos: not inner(level, pos)
    if t == "always_true":
        return lambda level, pos: True
    # 未知谓词：True（宁可多放置，不静默丢实例）
    return lambda level, pos: True


def _parse_provider(j):
    t = j["type"][len(_MC):]
    if t == "simple_state_provider":
        return _SimpleProvider(j["state"]["Name"][len(_MC):])
    if t == "weighted_state_provider":
        entries = []
        for e in j["entries"]:
            data = e["data"]
            entries.append((e["weight"], data["Name"][len(_MC):]))
        return _WeightedProvider(entries)
    if t == "rule_based_state_provider":
        rules = [(_parse_pred(r["if_true"]), _parse_provider(r["then"]))
                 for r in j["rules"]]
        return _RuleBasedProvider(rules)
    if t == "randomized_int_state_provider":
        src = j["source"]
        if not src["type"].endswith("simple_state_provider"):
            raise ValueError(
                "randomized_int source must be simple (preview scope)")
        return _RandomizedIntProvider(
            src["state"]["Name"][len(_MC):], j["values"])
    raise ValueError(f"unsupported state provider: {t}")


# ======================================================================
# 树状态（per-tree）与 decorator 上下文
# ======================================================================

class _TreeState:
    """place() 的四个位置集合（插入序）+ per-tree foliage 快查集合。"""

    __slots__ = ("roots", "trunks", "foliage", "decorations", "foliage_set")

    def __init__(self):
        self.roots = []
        self.trunks = []
        self.foliage = []
        self.decorations = []
        self.foliage_set = set()


class _DecoCtx:
    """TreeDecorator.Context：Set 复制 + y 升序稳定排序（List.sort 语义）。"""

    __slots__ = ("level", "st", "rng", "logs", "leaves", "roots")

    def __init__(self, level, st, rng):
        self.level = level
        self.st = st
        self.rng = rng
        self.logs = sorted(st.trunks, key=lambda p: p[1])       # TimSort 稳定
        self.leaves = sorted(st.foliage, key=lambda p: p[1])
        self.roots = sorted(st.roots, key=lambda p: p[1])

    def set_block(self, pos, name) -> None:
        self.st.decorations.append(pos)
        self.level.set_block(pos, name)

    def is_air(self, pos) -> bool:
        return self.level.is_air(pos)


def _lowest_trunk_or_root(ctx):
    """TreeFeature.getLowestTrunkOrRootOfTree（逐行直译）。"""
    roots, logs = ctx.roots, ctx.logs
    if not roots:
        return list(logs)
    if logs and roots[0][1] == logs[0][1]:
        return list(logs) + list(roots)
    return list(roots)


# ======================================================================
# FeatureSize（minimum_size）
# ======================================================================

class _TwoLayersFeatureSize:
    """TwoLayersFeatureSize：y < limit ? lower : upper（默认 1/0/1）。"""

    __slots__ = ("limit", "lower", "upper", "min_clipped")

    def __init__(self, limit=1, lower=0, upper=1):
        self.limit = limit
        self.lower = lower
        self.upper = upper
        self.min_clipped = None

    def size_at(self, tree_height: int, y: int) -> int:
        return self.lower if y < self.limit else self.upper


class _ThreeLayersFeatureSize:
    """ThreeLayersFeatureSize：y<limit?lower : y>=h-upperLimit?upper : middle。"""

    __slots__ = ("limit", "upper_limit", "lower", "middle", "upper", "min_clipped")

    def __init__(self, limit=1, upper_limit=1, lower=0, middle=1, upper=1):
        self.limit = limit
        self.upper_limit = upper_limit
        self.lower = lower
        self.middle = middle
        self.upper = upper
        self.min_clipped = None

    def size_at(self, tree_height: int, y: int) -> int:
        if y < self.limit:
            return self.lower
        if y >= tree_height - self.upper_limit:
            return self.upper
        return self.middle


# ======================================================================
# TrunkPlacer 基类与 7 种实现
# ======================================================================

class _TrunkPlacer:
    """TrunkPlacer 基类（getTreeHeight/placeLog/placeLogIfFree/isFree）。"""

    __slots__ = ("base", "ha", "hb")

    def __init__(self, base, ha, hb):
        self.base = base
        self.ha = ha
        self.hb = hb

    def get_tree_height(self, rng) -> int:
        return self.base + rng.next_int(self.ha + 1) + rng.next_int(self.hb + 1)

    def is_free(self, level, pos) -> bool:
        return level.is_free(pos)

    def _place_below(self, level, st, rng, pos, cfg) -> None:
        """placeBelowTrunkBlock：getOptionalState 非 null 才 trunkSetter。"""
        state = cfg.below_provider.get_optional_state(level, rng, pos)
        if state is not None:
            st.trunks.append(pos)
            level.set_block(pos, state)

    def _place_log(self, level, st, rng, pos, cfg) -> bool:
        """placeLog：validTreePos -> trunkSetter（渲染不记 axis 属性）。"""
        if level.valid_tree_pos(pos):
            st.trunks.append(pos)
            level.set_block(pos, cfg.trunk_block)
            return True
        return False

    def _place_log_if_free(self, level, st, rng, pos, cfg) -> None:
        if self.is_free(level, pos):
            self._place_log(level, st, rng, pos, cfg)

    def valid_tree_pos(self, level, pos) -> bool:
        return level.valid_tree_pos(pos)

    def place_trunk(self, level, st, rng, tree_height, origin, cfg):
        raise NotImplementedError


class _StraightTrunkPlacer(_TrunkPlacer):
    """StraightTrunkPlacer：below + y 0..h-1 柱 + attachment(origin+h)。"""

    def place_trunk(self, level, st, rng, tree_height, origin, cfg):
        self._place_below(level, st, rng, _rel(origin, "down"), cfg)
        for y in range(tree_height):
            self._place_log(level, st, rng, _rel(origin, "up", y), cfg)
        return [(_rel(origin, "up", tree_height), 0, False)]


def _tree_shape(height: int, y: int) -> float:
    """FancyTrunkPlacer.treeShape（float32 链）。"""
    if y < _f32(height * 0.3):
        return -1.0
    radius = _f32(height / 2.0)
    adjacent = _f32(radius - y)
    distance = _f32(math.sqrt(_f32(_f32(radius * radius) - _f32(adjacent * adjacent))))
    if adjacent == 0.0:
        distance = radius
    elif abs(adjacent) >= radius:
        return 0.0
    return _f32(distance * 0.5)


class _FancyTrunkPlacer(_TrunkPlacer):
    """FancyTrunkPlacer：大橡树。cluster 每 i 恒消耗 2×nextFloat。"""

    def place_trunk(self, level, st, rng, tree_height, origin, cfg):
        height = tree_height + 2
        trunk_height = int(math.floor(height * 0.618))
        self._place_below(level, st, rng, _rel(origin, "down"), cfg)
        clusters_per_y = min(1, int(math.floor(1.382 + (height / 13.0) ** 2)))
        trunk_top = origin[1] + trunk_height
        relative_y = height - 5
        # FoliageCoords = (attachment_pos, branch_base_y)
        coords = [(_rel(origin, "up", relative_y), trunk_top)]
        while relative_y >= 0:
            shape = _tree_shape(height, relative_y)
            if not shape < 0.0:
                for _ in range(clusters_per_y):
                    radius = 1.0 * shape * (rng.next_float() + 0.328)
                    angle = _f32(rng.next_float() * 2.0) * math.pi
                    x = radius * math.sin(angle) + 0.5
                    z = radius * math.cos(angle) + 0.5
                    check_start = (origin[0] + math.floor(x),
                                   origin[1] + relative_y - 1,
                                   origin[2] + math.floor(z))
                    check_end = (check_start[0], check_start[1] + 5, check_start[2])
                    if self._make_limb(level, st, rng, check_start, check_end,
                                       False, cfg):
                        dx = origin[0] - check_start[0]
                        dz = origin[2] - check_start[2]
                        branch_height = (check_start[1]
                                         - math.sqrt(dx * dx + dz * dz) * 0.381)
                        branch_top = (trunk_top if branch_height > trunk_top
                                      else int(branch_height))
                        check_base = (origin[0], branch_top, origin[2])
                        if self._make_limb(level, st, rng, check_base,
                                           check_start, False, cfg):
                            coords.append((check_start, check_base[1]))
            relative_y -= 1
        self._make_limb(level, st, rng, origin,
                        (origin[0], origin[1] + trunk_height, origin[2]),
                        True, cfg)
        self._make_branches(level, st, rng, height, origin, coords, cfg)
        # Java: FoliageCoords 包装 FoliageAttachment(pos, 0, false)
        #   (FancyTrunkPlacer.java L188-195)
        return [(c[0], 0, False) for c in coords
                if c[1] - origin[1] >= height * 0.2]

    def _make_limb(self, level, st, rng, start, end, do_place, cfg) -> bool:
        if not do_place and start == end:
            return True
        ddx = end[0] - start[0]
        ddy = end[1] - start[1]
        ddz = end[2] - start[2]
        steps = max(abs(ddx), abs(ddy), abs(ddz))
        dx = _f32(ddx / steps) if steps else 0.0     # (float)delta/steps
        dy = _f32(ddy / steps) if steps else 0.0
        dz = _f32(ddz / steps) if steps else 0.0
        for i in range(steps + 1):
            # floor(0.5F + i*dx)（float 乘加链）
            ox = int(math.floor(_f32(0.5 + _f32(i * dx))))
            oy = int(math.floor(_f32(0.5 + _f32(i * dy))))
            oz = int(math.floor(_f32(0.5 + _f32(i * dz))))
            bp = (start[0] + ox, start[1] + oy, start[2] + oz)
            if do_place:
                self._place_log(level, st, rng, bp, cfg)
            elif not self.is_free(level, bp):
                return False
        return True

    def _make_branches(self, level, st, rng, height, origin, coords, cfg):
        for att, branch_base in coords:
            base = (origin[0], branch_base, origin[2])
            if base != att and branch_base - origin[1] >= height * 0.2:
                self._make_limb(level, st, rng, base, att, True, cfg)


class _ForkingTrunkPlacer(_TrunkPlacer):
    """ForkingTrunkPlacer（acacia）：倾斜主杆 + 副枝（direction 恒消耗）。"""

    def place_trunk(self, level, st, rng, tree_height, origin, cfg):
        self._place_below(level, st, rng, _rel(origin, "down"), cfg)
        attachments = []
        lean_dir = _dir4(rng)
        lean_height = tree_height - rng.next_int(4) - 1
        lean_steps = 3 - rng.next_int(3)
        tx, tz = origin[0], origin[2]
        ey = None
        for yo in range(tree_height):
            yy = origin[1] + yo
            if yo >= lean_height and lean_steps > 0:
                tx += _STEP[lean_dir][0]
                tz += _STEP[lean_dir][1]
                lean_steps -= 1
            if self._place_log(level, st, rng, (tx, yy, tz), cfg):
                ey = yy + 1
        if ey is not None:
            attachments.append(((tx, ey, tz), 1, False))

        tx, tz = origin[0], origin[2]
        branch_dir = _dir4(rng)
        if branch_dir != lean_dir:
            branch_pos = lean_height - rng.next_int(2) - 1
            branch_steps = 1 + rng.next_int(3)
            ey = None
            yo = branch_pos
            while yo < tree_height and branch_steps > 0:
                if yo >= 1:
                    yy = origin[1] + yo
                    tx += _STEP[branch_dir][0]
                    tz += _STEP[branch_dir][1]
                    if self._place_log(level, st, rng, (tx, yy, tz), cfg):
                        ey = yy + 1
                yo += 1
                branch_steps -= 1
            if ey is not None:
                attachments.append(((tx, ey, tz), 0, False))
        return attachments


class _GiantTrunkPlacer(_TrunkPlacer):
    """GiantTrunkPlacer：2x2 柱 + below×4 + attachment(origin+h, dt=True)。"""

    def place_trunk(self, level, st, rng, tree_height, origin, cfg):
        below = _rel(origin, "down")
        self._place_below(level, st, rng, below, cfg)
        self._place_below(level, st, rng, _rel_xz(below, "east"), cfg)
        self._place_below(level, st, rng, _rel_xz(below, "south"), cfg)
        self._place_below(level, st, rng,
                          _rel_xz(_rel_xz(below, "south"), "east"), cfg)
        ox, oy, oz = origin
        for hh in range(tree_height):
            self._place_log_if_free(level, st, rng, (ox, oy + hh, oz), cfg)
            if hh < tree_height - 1:
                self._place_log_if_free(level, st, rng, (ox + 1, oy + hh, oz), cfg)
                self._place_log_if_free(level, st, rng, (ox + 1, oy + hh, oz + 1), cfg)
                self._place_log_if_free(level, st, rng, (ox, oy + hh, oz + 1), cfg)
        return [((ox, oy + tree_height, oz), 0, True)]


class _MegaJungleTrunkPlacer(_GiantTrunkPlacer):
    """MegaJungleTrunkPlacer：Giant + 螺旋枝（angle float32 链）。"""

    def place_trunk(self, level, st, rng, tree_height, origin, cfg):
        attachments = list(super().place_trunk(level, st, rng, tree_height,
                                               origin, cfg))
        two_pi_f = _f32(2.0 * math.pi)               # (float)(Math.PI*2)
        branch_height = tree_height - 2 - rng.next_int(4)
        while branch_height > tree_height // 2:
            angle = _f32(rng.next_float() * two_pi_f)
            bx = bz = 0
            for b in range(5):
                bx = int(_f32(1.5 + _f32(_f32(math.cos(angle)) * b)))
                bz = int(_f32(1.5 + _f32(_f32(math.sin(angle)) * b)))
                pos = (origin[0] + bx, origin[1] + branch_height - 3 + b // 2,
                       origin[2] + bz)
                self._place_log(level, st, rng, pos, cfg)
            attachments.append(((origin[0] + bx, origin[1] + branch_height,
                                 origin[2] + bz), -2, False))
            branch_height -= 2 + rng.next_int(4)
        return attachments


class _DarkOakTrunkPlacer(_TrunkPlacer):
    """DarkOakTrunkPlacer：2x2 倾斜 + 四周枝（12×nextInt(3) 恒消耗）。"""

    def place_trunk(self, level, st, rng, tree_height, origin, cfg):
        attachments = []
        below = _rel(origin, "down")
        self._place_below(level, st, rng, below, cfg)
        self._place_below(level, st, rng, _rel_xz(below, "east"), cfg)
        self._place_below(level, st, rng, _rel_xz(below, "south"), cfg)
        self._place_below(level, st, rng,
                          _rel_xz(_rel_xz(below, "south"), "east"), cfg)
        lean_dir = _dir4(rng)
        lean_height = tree_height - rng.next_int(4)
        lean_steps = 2 - rng.next_int(3)
        x, y, z = origin
        tx, tz = x, z
        ey = y + tree_height - 1
        for dy in range(tree_height):
            if dy >= lean_height and lean_steps > 0:
                tx += _STEP[lean_dir][0]
                tz += _STEP[lean_dir][1]
                lean_steps -= 1
            yy = y + dy
            bp = (tx, yy, tz)
            if level.is_air_or_leaves(bp):
                self._place_log(level, st, rng, bp, cfg)
                self._place_log(level, st, rng, _rel_xz(bp, "east"), cfg)
                self._place_log(level, st, rng, _rel_xz(bp, "south"), cfg)
                self._place_log(level, st, rng,
                                _rel_xz(_rel_xz(bp, "south"), "east"), cfg)
        attachments.append(((tx, ey, tz), 0, True))
        for ox in range(-1, 3):
            for oz in range(-1, 3):
                if (ox < 0 or ox > 1 or oz < 0 or oz > 1) and rng.next_int(3) <= 0:
                    length = rng.next_int(3) + 2
                    for branch_y in range(length):
                        self._place_log(level, st, rng,
                                        (x + ox, ey - branch_y - 1, z + oz), cfg)
                    attachments.append(((x + ox, ey, z + oz), 0, False))
        return attachments


class _UpwardsBranchingTrunkPlacer(_TrunkPlacer):
    """UpwardsBranchingTrunkPlacer（红树）：主柱 + 侧枝（每 log 概率分支）。"""

    __slots__ = ("branch_steps_spec", "branch_prob", "branch_len_spec",
                 "can_grow_through")

    def __init__(self, base, ha, hb, branch_steps_spec, branch_prob,
                 branch_len_spec, can_grow_through):
        super().__init__(base, ha, hb)
        self.branch_steps_spec = branch_steps_spec
        self.branch_prob = _f32(branch_prob)
        self.branch_len_spec = branch_len_spec
        self.can_grow_through = frozenset(can_grow_through)

    def valid_tree_pos(self, level, pos) -> bool:
        return (level.valid_tree_pos(pos)
                or level.block_name(pos) in self.can_grow_through)

    def is_free(self, level, pos) -> bool:
        return self.valid_tree_pos(level, pos) or level.block_name(pos) in _LOGS_SET

    def _place_log(self, level, st, rng, pos, cfg) -> bool:
        if self.valid_tree_pos(level, pos):
            st.trunks.append(pos)
            level.set_block(pos, cfg.trunk_block)
            return True
        return False

    def place_trunk(self, level, st, rng, tree_height, origin, cfg):
        attachments = []
        for height_pos in range(tree_height):
            current_height = origin[1] + height_pos
            if (self._place_log(level, st, rng, (origin[0], current_height,
                                                 origin[2]), cfg)
                    and height_pos < tree_height - 1
                    and rng.next_float() < self.branch_prob):
                branch_dir = _dir4(rng)
                branch_len = _sample_int(rng, self.branch_len_spec)
                branch_pos = max(0, branch_len
                                 - _sample_int(rng, self.branch_len_spec) - 1)
                branch_steps = _sample_int(rng, self.branch_steps_spec)
                self._place_branch(level, st, rng, tree_height, cfg,
                                   attachments, origin, current_height,
                                   branch_dir, branch_pos, branch_steps)
            if height_pos == tree_height - 1:
                attachments.append(((origin[0], current_height + 1, origin[2]),
                                    0, False))
        return attachments

    def _place_branch(self, level, st, rng, tree_height, cfg, attachments,
                      log_pos, current_height, branch_dir, branch_pos,
                      branch_steps):
        height_along_branch = current_height + branch_pos
        log_x, log_z = log_pos[0], log_pos[2]
        branch_placement_index = branch_pos
        while branch_placement_index < tree_height and branch_steps > 0:
            if branch_placement_index >= 1:
                placement_height = current_height + branch_placement_index
                log_x += _STEP[branch_dir][0]
                log_z += _STEP[branch_dir][1]
                height_along_branch = placement_height
                if self._place_log(level, st, rng,
                                   (log_x, placement_height, log_z), cfg):
                    height_along_branch += 1
                attachments.append(((log_x, placement_height, log_z), 0, False))
            branch_placement_index += 1
            branch_steps -= 1
        if height_along_branch - current_height > 1:
            foliage_pos = (log_x, height_along_branch, log_z)
            attachments.append((foliage_pos, 0, False))
            attachments.append(((foliage_pos[0], foliage_pos[1] - 2,
                                 foliage_pos[2]), 0, False))


class _CherryTrunkPlacer(_TrunkPlacer):
    """CherryTrunkPlacer（樱花）：1-3 分支 + 每步 nextFloat 的垂直爬升段。"""

    __slots__ = ("branch_count", "branch_horizontal_length", "branch_start",
                 "branch_start2", "branch_end")

    def __init__(self, base, ha, hb, branch_count, branch_horizontal_length,
                 branch_start, branch_end):
        super().__init__(base, ha, hb)
        self.branch_count = branch_count          # weighted_list [1,2,3]
        self.branch_horizontal_length = branch_horizontal_length
        self.branch_start = branch_start          # 裸 uniform spec
        # secondBranchStartOffsetFromTop = UniformInt.of(min, max-1)
        #   (CherryTrunkPlacer.java L62)
        self.branch_start2 = {"min_inclusive": branch_start["min_inclusive"],
                              "max_inclusive":
                                  branch_start["max_inclusive"] - 1}
        self.branch_end = branch_end

    def place_trunk(self, level, st, rng, tree_height, origin, cfg):
        self._place_below(level, st, rng, _rel(origin, "down"), cfg)
        first_off = max(0, tree_height - 1
                        + _sample_int(rng, self.branch_start))
        second_off = max(0, tree_height - 1
                         + _sample_int(rng, self.branch_start2))
        if second_off >= first_off:
            second_off += 1
        branch_count = _sample_int(rng, self.branch_count)
        has_middle = branch_count == 3
        has_both = branch_count >= 2
        if has_middle:
            trunk_height = tree_height
        elif has_both:
            trunk_height = max(first_off, second_off) + 1
        else:
            trunk_height = first_off + 1
        for y in range(trunk_height):
            self._place_log(level, st, rng,
                            (origin[0], origin[1] + y, origin[2]), cfg)
        attachments = []
        if has_middle:
            attachments.append(((origin[0], origin[1] + trunk_height,
                                 origin[2]), 0, False))
        tree_dir = _dir4(rng)             # faces [N,E,S,W] (Direction L577)
        attachments.append(self._generate_branch(
            level, st, rng, tree_height, origin, cfg, tree_dir, first_off,
            first_off < trunk_height - 1))
        if has_both:
            attachments.append(self._generate_branch(
                level, st, rng, tree_height, origin, cfg,
                _OPPOSITE[tree_dir], second_off,
                second_off < trunk_height - 1))
        return attachments

    def _generate_branch(self, level, st, rng, tree_height, origin, cfg,
                         branch_dir, offset_from_origin, middle_continues):
        log_pos = (origin[0], origin[1] + offset_from_origin, origin[2])
        end_y_off = tree_height - 1 + _sample_int(rng, self.branch_end)
        extend = middle_continues or end_y_off < offset_from_origin
        dist_to_trunk = (_sample_int(rng, self.branch_horizontal_length)
                         + (1 if extend else 0))
        end_pos = _rel_xz(origin, branch_dir, dist_to_trunk)
        end_pos = (end_pos[0], origin[1] + end_y_off, end_pos[2])
        for _ in range(2 if extend else 1):        # 先 move 再 placeLog
            log_pos = _rel_xz(log_pos, branch_dir)
            self._place_log(level, st, rng, log_pos, cfg)
        vdir = 1 if end_pos[1] > log_pos[1] else -1   # 循环外定死 (L171)
        while True:
            ddy = end_pos[1] - log_pos[1]
            distance = (abs(end_pos[0] - log_pos[0]) + abs(ddy)
                        + abs(end_pos[2] - log_pos[2]))
            if distance == 0:
                return (end_pos[0], end_pos[1] + 1, end_pos[2]), 0, False
            chance = _f32(abs(ddy) / distance)     # (float)abs/distance
            if rng.next_float() < chance:
                log_pos = (log_pos[0], log_pos[1] + vdir, log_pos[2])
            else:
                log_pos = _rel_xz(log_pos, branch_dir)
            self._place_log(level, st, rng, log_pos, cfg)


# ======================================================================
# FoliagePlacer 基类与 11 种实现
# ======================================================================

class _FoliagePlacer:
    """FoliagePlacer 基类：placeLeavesRow/挂叶/tryPlaceLeaf/shouldSkip。"""

    __slots__ = ("radius_spec", "offset_spec")

    def __init__(self, radius_spec, offset_spec):
        self.radius_spec = radius_spec
        self.offset_spec = offset_spec

    def foliage_height(self, rng, tree_height, cfg) -> int:
        raise NotImplementedError

    def foliage_radius(self, rng, trunk_height) -> int:
        return _sample_int(rng, self.radius_spec)

    def create_foliage(self, level, st, rng, cfg, tree_height, att,
                       foliage_height, leaf_radius) -> None:
        offset = _sample_int(rng, self.offset_spec)   # 每次 attachment 恒消耗
        self._create_foliage(level, st, rng, cfg, tree_height, att,
                             foliage_height, leaf_radius, offset)

    def _create_foliage(self, level, st, rng, cfg, tree_height, att,
                        foliage_height, leaf_radius, offset):
        raise NotImplementedError

    def _should_skip(self, rng, dx, y, dz, current_radius, double_trunk) -> bool:
        raise NotImplementedError

    def _should_skip_signed(self, rng, dx, y, dz, current_radius,
                            double_trunk) -> bool:
        if double_trunk:
            min_dx = min(abs(dx), abs(dx - 1))
            min_dz = min(abs(dz), abs(dz - 1))
        else:
            min_dx = abs(dx)
            min_dz = abs(dz)
        return self._should_skip(rng, min_dx, y, min_dz, current_radius,
                                 double_trunk)

    def _place_leaves_row(self, level, st, rng, cfg, origin, current_radius,
                          y, double_trunk) -> None:
        off = 1 if double_trunk else 0
        for dx in range(-current_radius, current_radius + off + 1):
            for dz in range(-current_radius, current_radius + off + 1):
                if not self._should_skip_signed(rng, dx, y, dz, current_radius,
                                                double_trunk):
                    pos = (origin[0] + dx, origin[1] + y, origin[2] + dz)
                    _try_place_leaf(level, st, rng, cfg, pos)

    def _place_leaves_row_hanging(self, level, st, rng, cfg, origin,
                                  current_radius, y, double_trunk,
                                  hang_chance, ext_chance) -> None:
        self._place_leaves_row(level, st, rng, cfg, origin, current_radius,
                               y, double_trunk)
        off = 1 if double_trunk else 0
        log_pos = (origin[0], origin[1] - 1, origin[2])
        for along in _DIRS4_H:
            to_edge = _CLOCKWISE[along]
            t_off = current_radius + off if _POSITIVE_AXIS[to_edge] else current_radius
            # pos = origin+(0,y-1,0) + toEdge*t_off + along*(-r)（可变累积移动直译）
            px = origin[0] + _STEP[to_edge][0] * t_off - _STEP[along][0] * current_radius
            pz = origin[2] + _STEP[to_edge][1] * t_off - _STEP[along][1] * current_radius
            py = origin[1] + (y - 1)
            n_along = -current_radius
            while n_along < current_radius + off:
                leaves_above = (px, py + 1, pz) in st.foliage_set
                if leaves_above and self._try_extension(
                        level, st, rng, cfg, hang_chance, log_pos, (px, py, pz)):
                    self._try_extension(level, st, rng, cfg, ext_chance,
                                        log_pos, (px, py - 1, pz))
                n_along += 1
                px += _STEP[along][0]
                pz += _STEP[along][1]

    @staticmethod
    def _try_extension(level, st, rng, cfg, chance, log_pos, pos) -> bool:
        if (abs(pos[0] - log_pos[0]) + abs(pos[1] - log_pos[1])
                + abs(pos[2] - log_pos[2]) >= 7):
            return False                      # 无 RNG 短路
        if rng.next_float() > chance:
            return False
        return _try_place_leaf(level, st, rng, cfg, pos)


def _try_place_leaf(level, st, rng, cfg, pos) -> bool:
    """FoliagePlacer.tryPlaceLeaf（isPersistent 本场景恒 False）。"""
    if level.valid_tree_pos(pos):
        st.foliage.append(pos)
        st.foliage_set.add(pos)
        level.set_block(pos, cfg.foliage_block)
        return True
    return False


class _BlobFoliagePlacer(_FoliagePlacer):
    """BlobFoliagePlacer（oak/birch/jungle/swamp 树冠）。"""

    __slots__ = ("height",)

    def __init__(self, radius_spec, offset_spec, height):
        super().__init__(radius_spec, offset_spec)
        self.height = height

    def foliage_height(self, rng, tree_height, cfg) -> int:
        return self.height                    # JSON int 常数 -> 零消耗

    def _create_foliage(self, level, st, rng, cfg, tree_height, att,
                        foliage_height, leaf_radius, offset):
        for yo in range(offset, offset - foliage_height - 1, -1):
            r = max(leaf_radius + att[1] - 1 - _trunc_div2(yo), 0)
            self._place_leaves_row(level, st, rng, cfg, att[0], r, yo, att[2])

    def _should_skip(self, rng, dx, y, dz, current_radius, double_trunk) -> bool:
        # Java: random.nextInt(2) == 0 || y == 0 —— nextInt(2) 在角格恒消耗
        return (dx == current_radius and dz == current_radius
                and (rng.next_int(2) == 0 or y == 0))


class _BushFoliagePlacer(_BlobFoliagePlacer):
    """BushFoliagePlacer（jungle bush）：半径无 /2、角格恒消耗。"""

    def _create_foliage(self, level, st, rng, cfg, tree_height, att,
                        foliage_height, leaf_radius, offset):
        for yo in range(offset, offset - foliage_height - 1, -1):
            r = leaf_radius + att[1] - 1 - yo
            self._place_leaves_row(level, st, rng, cfg, att[0], r, yo, att[2])

    def _should_skip(self, rng, dx, y, dz, current_radius, double_trunk) -> bool:
        return (dx == current_radius and dz == current_radius
                and rng.next_int(2) == 0)


class _FancyFoliagePlacer(_BlobFoliagePlacer):
    """FancyFoliagePlacer（大橡树树冠）：圆形判定，零 RNG。"""

    def _create_foliage(self, level, st, rng, cfg, tree_height, att,
                        foliage_height, leaf_radius, offset):
        for yo in range(offset, offset - foliage_height - 1, -1):
            r = leaf_radius + (1 if (yo != offset and yo != offset - foliage_height)
                               else 0)
            self._place_leaves_row(level, st, rng, cfg, att[0], r, yo, att[2])

    def _should_skip(self, rng, dx, y, dz, current_radius, double_trunk) -> bool:
        return (dx + 0.5) ** 2 + (dz + 0.5) ** 2 > current_radius * current_radius


class _SpruceFoliagePlacer(_FoliagePlacer):
    """SpruceFoliagePlacer：nextIntro(2) 起始 + 锯齿半径循环。"""

    __slots__ = ("trunk_height_spec",)

    def __init__(self, radius_spec, offset_spec, trunk_height_spec):
        super().__init__(radius_spec, offset_spec)
        self.trunk_height_spec = trunk_height_spec

    def foliage_height(self, rng, tree_height, cfg) -> int:
        return max(4, tree_height - _sample_int(rng, self.trunk_height_spec))

    def _create_foliage(self, level, st, rng, cfg, tree_height, att,
                        foliage_height, leaf_radius, offset):
        pos = att[0]
        current_radius = rng.next_int(2)
        max_radius = 1
        min_radius = 0
        for yo in range(offset, -foliage_height - 1, -1):
            self._place_leaves_row(level, st, rng, cfg, pos, current_radius,
                                   yo, att[2])
            if current_radius >= max_radius:
                current_radius = min_radius
                min_radius = 1
                max_radius = min(max_radius + 1, leaf_radius + att[1])
            else:
                current_radius += 1

    def _should_skip(self, rng, dx, y, dz, current_radius, double_trunk) -> bool:
        return (dx == current_radius and dz == current_radius
                and current_radius > 0)


class _PineFoliagePlacer(_FoliagePlacer):
    """PineFoliagePlacer：foliageRadius 覆写（radius.sample + nextInt）。"""

    __slots__ = ("height_spec",)

    def __init__(self, radius_spec, offset_spec, height_spec):
        super().__init__(radius_spec, offset_spec)
        self.height_spec = height_spec

    def foliage_radius(self, rng, trunk_height) -> int:
        return (_sample_int(rng, self.radius_spec)
                + rng.next_int(max(trunk_height + 1, 1)))

    def foliage_height(self, rng, tree_height, cfg) -> int:
        return _sample_int(rng, self.height_spec)

    def _create_foliage(self, level, st, rng, cfg, tree_height, att,
                        foliage_height, leaf_radius, offset):
        current_radius = 0
        for yo in range(offset, offset - foliage_height - 1, -1):
            self._place_leaves_row(level, st, rng, cfg, att[0], current_radius,
                                   yo, att[2])
            if current_radius >= 1 and yo == offset - foliage_height + 1:
                current_radius -= 1
            elif current_radius < leaf_radius + att[1]:
                current_radius += 1

    def _should_skip(self, rng, dx, y, dz, current_radius, double_trunk) -> bool:
        return (dx == current_radius and dz == current_radius
                and current_radius > 0)


class _MegaPineFoliagePlacer(_FoliagePlacer):
    """MegaPineFoliagePlacer：绝对 yy 循环 + jaggedRadius 逐层平滑。"""

    __slots__ = ("crown_height_spec",)

    def __init__(self, radius_spec, offset_spec, crown_height_spec):
        super().__init__(radius_spec, offset_spec)
        self.crown_height_spec = crown_height_spec

    def foliage_height(self, rng, tree_height, cfg) -> int:
        return _sample_int(rng, self.crown_height_spec)

    def _create_foliage(self, level, st, rng, cfg, tree_height, att,
                        foliage_height, leaf_radius, offset):
        fx, fy, fz = att[0]
        prev_radius = 0
        for yy in range(fy - foliage_height + offset, fy + offset + 1):
            yo = fy - yy
            # Mth.floor((float)yo / foliageHeight * 3.5F)（float 除乘链）
            smooth_radius = (leaf_radius + att[1]
                             + int(math.floor(_f32(_f32(yo / foliage_height) * 3.5))))
            if yo > 0 and smooth_radius == prev_radius and (yy & 1) == 0:
                jagged_radius = smooth_radius + 1
            else:
                jagged_radius = smooth_radius
            self._place_leaves_row(level, st, rng, cfg, (fx, yy, fz),
                                   jagged_radius, 0, att[2])
            prev_radius = smooth_radius

    def _should_skip(self, rng, dx, y, dz, current_radius, double_trunk) -> bool:
        return (True if dx + dz >= 7
                else dx * dx + dz * dz > current_radius * current_radius)


class _MegaJungleFoliagePlacer(_FoliagePlacer):
    """MegaJungleFoliagePlacer：单干 attachment 时 1+nextInt(2)。"""

    __slots__ = ("height",)

    def __init__(self, radius_spec, offset_spec, height):
        super().__init__(radius_spec, offset_spec)
        self.height = height

    def foliage_height(self, rng, tree_height, cfg) -> int:
        return self.height

    def _create_foliage(self, level, st, rng, cfg, tree_height, att,
                        foliage_height, leaf_radius, offset):
        leaf_height = foliage_height if att[2] else 1 + rng.next_int(2)
        for yo in range(offset, offset - leaf_height - 1, -1):
            r = leaf_radius + att[1] + 1 - yo
            self._place_leaves_row(level, st, rng, cfg, att[0], r, yo, att[2])

    def _should_skip(self, rng, dx, y, dz, current_radius, double_trunk) -> bool:
        return (True if dx + dz >= 7
                else dx * dx + dz * dz > current_radius * current_radius)


class _AcaciaFoliagePlacer(_FoliagePlacer):
    """AcaciaFoliagePlacer：foliageHeight=0 + 三层盘状。"""

    def foliage_height(self, rng, tree_height, cfg) -> int:
        return 0

    def _create_foliage(self, level, st, rng, cfg, tree_height, att,
                        foliage_height, leaf_radius, offset):
        pos = _rel(att[0], "up", offset)
        dt = att[2]
        self._place_leaves_row(level, st, rng, cfg, pos,
                               leaf_radius + att[1], -1 - foliage_height, dt)
        self._place_leaves_row(level, st, rng, cfg, pos, leaf_radius - 1,
                               -foliage_height, dt)
        self._place_leaves_row(level, st, rng, cfg, pos,
                               leaf_radius + att[1] - 1, 0, dt)

    def _should_skip(self, rng, dx, y, dz, current_radius, double_trunk) -> bool:
        if y == 0:
            return (dx > 1 or dz > 1) and dx != 0 and dz != 0
        return (dx == current_radius and dz == current_radius
                and current_radius > 0)


class _DarkOakFoliagePlacer(_FoliagePlacer):
    """DarkOakFoliagePlacer：foliageHeight=4 + nextBoolean 顶层 + 边缘特判。"""

    def foliage_height(self, rng, tree_height, cfg) -> int:
        return 4

    def _create_foliage(self, level, st, rng, cfg, tree_height, att,
                        foliage_height, leaf_radius, offset):
        pos = _rel(att[0], "up", offset)
        dt = att[2]
        if dt:
            self._place_leaves_row(level, st, rng, cfg, pos, leaf_radius + 2, -1, dt)
            self._place_leaves_row(level, st, rng, cfg, pos, leaf_radius + 3, 0, dt)
            self._place_leaves_row(level, st, rng, cfg, pos, leaf_radius + 2, 1, dt)
            if rng.next_boolean():
                self._place_leaves_row(level, st, rng, cfg, pos, leaf_radius, 2, dt)
        else:
            self._place_leaves_row(level, st, rng, cfg, pos, leaf_radius + 2, -1, dt)
            self._place_leaves_row(level, st, rng, cfg, pos, leaf_radius + 1, 0, dt)

    def _should_skip_signed(self, rng, dx, y, dz, current_radius,
                            double_trunk) -> bool:
        if (y != 0 or not double_trunk
                or (dx != -current_radius and dx < current_radius)
                or (dz != -current_radius and dz < current_radius)):
            return super()._should_skip_signed(rng, dx, y, dz, current_radius,
                                               double_trunk)
        return True

    def _should_skip(self, rng, dx, y, dz, current_radius, double_trunk) -> bool:
        if y == -1 and not double_trunk:
            return dx == current_radius and dz == current_radius
        return dx + dz > current_radius * 2 - 2 if y == 1 else False


class _CherryFoliagePlacer(_FoliagePlacer):
    """CherryFoliagePlacer：宽冠 + 挂叶（shouldSkip 短路消耗敏感）。"""

    __slots__ = ("height_spec", "wide_hole_chance", "corner_hole_chance",
                 "hang_chance", "ext_chance")

    def __init__(self, radius_spec, offset_spec, height_spec,
                 wide_hole_chance, corner_hole_chance, hang_chance, ext_chance):
        super().__init__(radius_spec, offset_spec)
        self.height_spec = height_spec
        self.wide_hole_chance = _f32(wide_hole_chance)
        self.corner_hole_chance = _f32(corner_hole_chance)
        self.hang_chance = _f32(hang_chance)
        self.ext_chance = _f32(ext_chance)

    def foliage_height(self, rng, tree_height, cfg) -> int:
        return _sample_int(rng, self.height_spec)

    def _create_foliage(self, level, st, rng, cfg, tree_height, att,
                        foliage_height, leaf_radius, offset):
        dt = att[2]
        pos = _rel(att[0], "up", offset)
        current_radius = leaf_radius + att[1] - 1
        self._place_leaves_row(level, st, rng, cfg, pos, current_radius - 2,
                               foliage_height - 3, dt)
        self._place_leaves_row(level, st, rng, cfg, pos, current_radius - 1,
                               foliage_height - 4, dt)
        for y in range(foliage_height - 5, -1, -1):
            self._place_leaves_row(level, st, rng, cfg, pos, current_radius,
                                   y, dt)
        self._place_leaves_row_hanging(level, st, rng, cfg, pos,
                                       current_radius, -1, dt,
                                       self.hang_chance, self.ext_chance)
        self._place_leaves_row_hanging(level, st, rng, cfg, pos,
                                       current_radius - 1, -2, dt,
                                       self.hang_chance, self.ext_chance)

    def _should_skip(self, rng, dx, y, dz, current_radius, double_trunk) -> bool:
        if (y == -1 and (dx == current_radius or dz == current_radius)
                and rng.next_float() < self.wide_hole_chance):
            return True
        corner = dx == current_radius and dz == current_radius
        wide_layer = current_radius > 2
        if wide_layer:
            return (corner or (dx + dz > current_radius * 2 - 2
                               and rng.next_float() < self.corner_hole_chance))
        return corner and rng.next_float() < self.corner_hole_chance


class _RandomSpreadFoliagePlacer(_FoliagePlacer):
    """RandomSpreadFoliagePlacer（红树树冠）：attempts×6 次 nextInt。"""

    __slots__ = ("foliage_height_spec", "attempts")

    def __init__(self, radius_spec, offset_spec, foliage_height_spec, attempts):
        super().__init__(radius_spec, offset_spec)
        self.foliage_height_spec = foliage_height_spec
        self.attempts = attempts

    def foliage_height(self, rng, tree_height, cfg) -> int:
        return _sample_int(rng, self.foliage_height_spec)

    def _create_foliage(self, level, st, rng, cfg, tree_height, att,
                        foliage_height, leaf_radius, offset):
        ox, oy, oz = att[0]
        lr = leaf_radius
        for _ in range(self.attempts):
            pos = (ox + rng.next_int(lr) - rng.next_int(lr),
                   oy + rng.next_int(foliage_height) - rng.next_int(foliage_height),
                   oz + rng.next_int(lr) - rng.next_int(lr))
            _try_place_leaf(level, st, rng, cfg, pos)

    def _should_skip(self, rng, dx, y, dz, current_radius, double_trunk) -> bool:
        return False


def _trunc_div2(v: int) -> int:
    """Java yo/2 向零截断（Python // 对负数是 floor，必须区分）。"""
    return v // 2 if v >= 0 else -((-v) // 2)


# ======================================================================
# TreeDecorator 十种
# ======================================================================

class _TreeDecorator:
    def place(self, ctx) -> None:
        raise NotImplementedError


class _TrunkVineDecorator(_TreeDecorator):
    """TrunkVine：logs×[W,E,N,S] 每向 nextInt(3)>0 -> isAir -> vine。"""

    def place(self, ctx) -> None:
        rng = ctx.rng
        for pos in ctx.logs:
            for d in ("west", "east", "north", "south"):
                if rng.next_int(3) > 0:
                    p = _rel_xz(pos, d)
                    if ctx.is_air(p):
                        ctx.set_block(p, "vine")


class _LeaveVineDecorator(_TreeDecorator):
    """LeaveVine：leaves×[W,E,N,S] nextFloat<p -> isAir -> 挂藤向下最多 4。"""

    __slots__ = ("probability",)

    def __init__(self, probability):
        self.probability = _f32(probability)

    def place(self, ctx) -> None:
        rng = ctx.rng
        for pos in ctx.leaves:
            for d in ("west", "east", "north", "south"):
                if rng.next_float() < self.probability:
                    p = _rel_xz(pos, d)
                    if ctx.is_air(p):
                        self._hanging_vine(p, ctx)

    def _hanging_vine(self, pos, ctx) -> None:
        ctx.set_block(pos, "vine")
        cur = (pos[0], pos[1] - 1, pos[2])
        n = 4
        while ctx.is_air(cur) and n > 0:
            ctx.set_block(cur, "vine")
            cur = (cur[0], cur[1] - 1, cur[2])
            n -= 1


class _CocoaDecorator(_TreeDecorator):
    """Cocoa：1 nextFloat 门槛 + logs(y-treeY<=2)×[N,E,S,W] nextFloat<=0.25。"""

    __slots__ = ("probability",)

    def __init__(self, probability):
        self.probability = _f32(probability)

    def place(self, ctx) -> None:
        rng = ctx.rng
        if rng.next_float() >= self.probability:
            return
        logs = ctx.logs
        if not logs:
            return
        tree_y = logs[0][1]
        for pos in logs:
            if pos[1] - tree_y <= 2:
                for d in _DIRS4_H:
                    if rng.next_float() <= 0.25:
                        opp = _OPPOSITE[d]
                        p = (pos[0] + _STEP[opp][0], pos[1],
                             pos[2] + _STEP[opp][1])
                        if ctx.is_air(p):
                            ctx.set_block(p, "cocoa")
                            rng.next_int(3)      # AGE


class _BeehiveDecorator(_TreeDecorator):
    """Beehive：SPAWN_DIRECTIONS=[E,S,W]（排除 NORTH），hiveY 有叶零 RNG。"""

    __slots__ = ("probability",)
    _SPAWN_DIRS = ("east", "south", "west")

    def __init__(self, probability):
        self.probability = _f32(probability)

    def place(self, ctx) -> None:
        leaves, logs = ctx.leaves, ctx.logs
        if not logs:
            return
        rng = ctx.rng
        if rng.next_float() >= self.probability:
            return
        if leaves:
            hive_y = max(leaves[0][1] - 1, logs[0][1] + 1)
        else:
            hive_y = min(logs[0][1] + 1 + rng.next_int(3), logs[-1][1])
        placements = []
        for pos in logs:
            if pos[1] == hive_y:
                for d in self._SPAWN_DIRS:
                    placements.append(_rel_xz(pos, d))
        if not placements:
            return
        _util_shuffle(placements, rng)
        hive_pos = None
        for p in placements:
            if ctx.is_air(p) and ctx.is_air(_rel_xz(p, "south")):
                hive_pos = p
                break
        if hive_pos is not None:
            ctx.set_block(hive_pos, "bee_nest")
            num_bees = 2 + rng.next_int(2)
            for _ in range(num_bees):
                rng.next_int(599)                # 蜂数据（仅消耗）


class _AttachedToLogsDecorator(_TreeDecorator):
    """AttachedToLogs：shuffledCopy(logs)×direction 恒消耗；provider 可能
    是 weighted（fallen tree 的红/棕蘑菇 2:1），place 时才消耗 RNG。"""

    __slots__ = ("probability", "provider", "directions")

    def __init__(self, probability, provider, directions):
        self.probability = _f32(probability)
        self.provider = provider
        self.directions = directions

    def place(self, ctx) -> None:
        rng = ctx.rng
        for pos in _shuffled_copy(ctx.logs, rng):
            d = self.directions[rng.next_int(len(self.directions))]
            p = _rel(pos, d)
            if rng.next_float() <= self.probability and ctx.is_air(p):
                ctx.set_block(p, self.provider.get_state(ctx.level, rng, p))


class _AttachedToLeavesDecorator(_TreeDecorator):
    """AttachedToLeaves：shuffledCopy(leaves) + 排除盒黑名单。"""

    __slots__ = ("probability", "ex_xz", "ex_y", "provider", "empty_blocks",
                 "directions")

    def __init__(self, probability, ex_xz, ex_y, provider, empty_blocks,
                 directions):
        self.probability = _f32(probability)
        self.ex_xz = ex_xz
        self.ex_y = ex_y
        self.provider = provider
        self.empty_blocks = empty_blocks
        self.directions = directions

    def place(self, ctx) -> None:
        rng = ctx.rng
        blacklist = set()
        for leaf in _shuffled_copy(ctx.leaves, rng):
            d = self.directions[rng.next_int(len(self.directions))]
            p = _rel(leaf, d)
            if p in blacklist:
                continue
            if rng.next_float() >= self.probability:
                continue
            ok = True
            for i in range(1, self.empty_blocks + 1):
                if not ctx.is_air(_rel(leaf, d, i)):
                    ok = False
                    break
            if not ok:
                continue
            for xx in range(p[0] - self.ex_xz, p[0] + self.ex_xz + 1):
                for yy in range(p[1] - self.ex_y, p[1] + self.ex_y + 1):
                    for zz in range(p[2] - self.ex_xz, p[2] + self.ex_xz + 1):
                        blacklist.add((xx, yy, zz))
            ctx.set_block(p, self.provider.get_state(ctx.level, rng, p))


class _PlaceOnGroundDecorator(_TreeDecorator):
    """PlaceOnGround：bb 内 tries×3 nextIntBetweenInclusive + 三重条件。"""

    __slots__ = ("tries", "radius", "height", "provider")

    def __init__(self, tries, radius, height, provider):
        self.tries = tries
        self.radius = radius
        self.height = height
        self.provider = provider

    def place(self, ctx) -> None:
        positions = _lowest_trunk_or_root(ctx)
        if not positions:
            return
        origin = positions[0]
        min_y = origin[1]
        min_x = max_x = origin[0]
        min_z = max_z = origin[2]
        for p in positions:
            if p[1] == min_y:
                min_x = min(min_x, p[0])
                max_x = max(max_x, p[0])
                min_z = min(min_z, p[2])
                max_z = max(max_z, p[2])
        rng = ctx.rng
        bx0, bx1 = min_x - self.radius, max_x + self.radius
        by0, by1 = min_y - self.height, min_y + self.height
        bz0, bz1 = min_z - self.radius, max_z + self.radius
        for _ in range(self.tries):
            px = rng.next_int(bx1 - bx0 + 1) + bx0
            py = rng.next_int(by1 - by0 + 1) + by0
            pz = rng.next_int(bz1 - bz0 + 1) + bz0
            self._attempt(ctx, (px, py, pz))

    def _attempt(self, ctx, pos) -> None:
        above = (pos[0], pos[1] + 1, pos[2])
        level = ctx.level
        if not level.is_air_or_vine(above):
            return
        if not level.is_solid_render(pos):
            return
        if level.heightmap_no_leaves_y(pos[0], pos[2]) > above[1]:
            return
        ctx.set_block(above, self.provider.get_state(level, ctx.rng, above))


class _AlterGroundDecorator(_TreeDecorator):
    """AlterGround：4 固定圈 + 5×nextInt(64) 边缘圈；placeBlockAt dy 2..-3。"""

    __slots__ = ("provider",)

    def __init__(self, provider):
        self.provider = provider

    def place(self, ctx) -> None:
        positions = _lowest_trunk_or_root(ctx)
        if not positions:
            return
        min_y = positions[0][1]
        for pos in positions:
            if pos[1] != min_y:
                continue
            self._circle(ctx, (pos[0] - 1, pos[1], pos[2] - 1))
            self._circle(ctx, (pos[0] + 2, pos[1], pos[2] - 1))
            self._circle(ctx, (pos[0] - 1, pos[1], pos[2] + 2))
            self._circle(ctx, (pos[0] + 2, pos[1], pos[2] + 2))
            for _ in range(5):
                placement = ctx.rng.next_int(64)
                xx = placement % 8
                zz = placement // 8
                if xx == 0 or xx == 7 or zz == 0 or zz == 7:
                    self._circle(ctx, (pos[0] - 3 + xx, pos[1], pos[2] - 3 + zz))

    def _circle(self, ctx, pos) -> None:
        for xx in range(-2, 3):
            for zz in range(-2, 3):
                if abs(xx) != 2 or abs(zz) != 2:
                    self._block_at(ctx, (pos[0] + xx, pos[1], pos[2] + zz))

    def _block_at(self, ctx, pos) -> None:
        for dy in range(2, -4, -1):
            cursor = (pos[0], pos[1] + dy, pos[2])
            replace_with = self.provider.get_optional_state(
                ctx.level, ctx.rng, cursor)
            if replace_with is not None:
                ctx.set_block(cursor, replace_with)
                break
            if not ctx.is_air(cursor) and dy < 0:
                break


class _PaleMossDecorator(_TreeDecorator):
    """PaleMoss：PALE_MOSS_PATCH 嵌套不建模（见模块 docstring 近似声明）。"""

    __slots__ = ("leaves_p", "trunk_p", "ground_p")

    def __init__(self, leaves_p, trunk_p, ground_p):
        self.leaves_p = _f32(leaves_p)
        self.trunk_p = _f32(trunk_p)
        self.ground_p = _f32(ground_p)

    def place(self, ctx) -> None:
        rng = ctx.rng
        logs = _shuffled_copy(ctx.logs, rng)
        if not logs:
            return
        if rng.next_float() < self.ground_p:
            pass                              # PALE_MOSS_PATCH 跳过
        for pos in ctx.logs:
            if rng.next_float() < self.trunk_p:
                down = (pos[0], pos[1] - 1, pos[2])
                if ctx.is_air(down):
                    self._hanger(down, ctx)
        for pos in ctx.leaves:
            if rng.next_float() < self.leaves_p:
                down = (pos[0], pos[1] - 1, pos[2])
                if ctx.is_air(down):
                    self._hanger(down, ctx)

    def _hanger(self, pos, ctx) -> None:
        cur = pos
        while ctx.is_air((cur[0], cur[1] - 1, cur[2])) and not (
                ctx.rng.next_float() < 0.5):
            ctx.set_block(cur, "pale_hanging_moss")
            cur = (cur[0], cur[1] - 1, cur[2])
        ctx.set_block(cur, "pale_hanging_moss")


class _CreakingHeartDecorator(_TreeDecorator):
    """CreakingHeart：1 nextFloat 门槛 + shuffle(logs) + 六面全 LOGS。"""

    __slots__ = ("probability",)

    def __init__(self, probability):
        self.probability = _f32(probability)

    def place(self, ctx) -> None:
        logs = ctx.logs
        if not logs:
            return
        if ctx.rng.next_float() >= self.probability:
            return
        hearts = list(logs)
        _util_shuffle(hearts, ctx.rng)
        for p in hearts:
            ok = True
            for d in _DIRS6:
                if ctx.level.block_name(_rel(p, d)) not in _LOGS_SET:
                    ok = False
                    break
            if ok:
                ctx.set_block(p, "creaking_heart")
                break


# ======================================================================
# RootPlacer / MangroveRootPlacer
# ======================================================================

class _RootPlacer:
    """RootPlacer 基类：getTrunkOrigin(sample) + placeRoot。"""

    __slots__ = ("trunk_offset_y", "root_provider", "above_root")

    def __init__(self, trunk_offset_y, root_provider, above_root):
        self.trunk_offset_y = trunk_offset_y
        self.root_provider = root_provider
        self.above_root = above_root      # (provider, chance) or None

    def sample_trunk_offset(self, rng) -> int:
        return _sample_int(rng, self.trunk_offset_y)

    def place_roots(self, level, st, rng, origin, trunk_origin, cfg) -> bool:
        raise NotImplementedError

    def can_place_root(self, level, pos) -> bool:
        return level.valid_tree_pos(pos)

    def place_root(self, level, st, rng, pos, cfg) -> None:
        if self.can_place_root(level, pos):
            st.roots.append(pos)
            level.set_block(pos, self.root_provider.get_state(level, rng, pos))
            if self.above_root is not None:
                above = _rel(pos, "up")
                # nextFloat 先于 isAir（短路顺序敏感）
                if rng.next_float() < self.above_root[1] and level.is_air(above):
                    st.roots.append(above)
                    level.set_block(
                        above, self.above_root[0].get_state(level, rng, above))


class _MangroveRootPlacer(_RootPlacer):
    """MangroveRootPlacer：向上爬柱 + 4 向 simulateRoots 递归。"""

    __slots__ = ("max_root_length", "max_root_width", "skew_chance",
                 "can_grow_through", "muddy_roots_in", "muddy_provider")

    def __init__(self, trunk_offset_y, root_provider, above_root,
                 max_root_length, max_root_width, skew_chance,
                 can_grow_through, muddy_roots_in, muddy_provider):
        super().__init__(trunk_offset_y, root_provider, above_root)
        self.max_root_length = max_root_length
        self.max_root_width = max_root_width
        self.skew_chance = _f32(skew_chance)
        self.can_grow_through = frozenset(can_grow_through)
        self.muddy_roots_in = frozenset(muddy_roots_in)
        self.muddy_provider = muddy_provider

    def can_place_root(self, level, pos) -> bool:
        return (level.valid_tree_pos(pos)
                or level.block_name(pos) in self.can_grow_through)

    def place_roots(self, level, st, rng, origin, trunk_origin, cfg) -> bool:
        column_pos = origin
        while column_pos[1] < trunk_origin[1]:
            if not self.can_place_root(level, column_pos):
                return False
            column_pos = _rel(column_pos, "up")
        root_positions = [(trunk_origin[0], trunk_origin[1] - 1, trunk_origin[2])]
        for d in _DIRS4_H:
            pos = _rel_xz(trunk_origin, d)
            in_dir = []
            if not self._simulate_roots(level, rng, pos, d, trunk_origin,
                                        in_dir, 0):
                return False
            root_positions.extend(in_dir)
            root_positions.append(pos)
        for root_pos in root_positions:
            self._place_root(level, st, rng, root_pos, cfg)
        return True

    def _simulate_roots(self, level, rng, root_pos, prev_dir, root_origin,
                        root_positions, layer) -> bool:
        if layer != self.max_root_length and len(root_positions) <= self.max_root_length:
            for pos in self._potential_positions(root_pos, prev_dir, rng,
                                                 root_origin):
                if self.can_place_root(level, pos):
                    root_positions.append(pos)
                    if not self._simulate_roots(level, rng, pos, prev_dir,
                                                root_origin, root_positions,
                                                layer + 1):
                        return False
            return True
        return False

    def _potential_positions(self, pos, prev_dir, rng, root_origin):
        below = _rel(pos, "down")
        next_to = _rel_xz(pos, prev_dir)
        width = (abs(pos[0] - root_origin[0]) + abs(pos[1] - root_origin[1])
                 + abs(pos[2] - root_origin[2]))
        mrw = self.max_root_width
        if mrw - 3 < width <= mrw:
            if rng.next_float() < self.skew_chance:
                return [below, _rel(next_to, "down")]
            return [below]
        if width > mrw:
            return [below]                     # 无 RNG
        if rng.next_float() < self.skew_chance:
            return [below]
        return [next_to] if rng.next_boolean() else [below]

    def _place_root(self, level, st, rng, pos, cfg) -> None:
        if level.block_name(pos) in self.muddy_roots_in:
            st.roots.append(pos)
            level.set_block(pos, self.muddy_provider.get_state(level, rng, pos))
            if self.above_root is not None:
                above = _rel(pos, "up")
                if rng.next_float() < self.above_root[1] and level.is_air(above):
                    st.roots.append(above)
                    level.set_block(
                        above, self.above_root[0].get_state(level, rng, above))
        else:
            super().place_root(level, st, rng, pos, cfg)


# ======================================================================
# HugeMushroom（brown/red）与 FallenTree
# ======================================================================

def _place_huge_mushroom(level, rng, origin, cap_block, stem_block,
                         foliage_radius, red: bool) -> bool:
    """AbstractHugeMushroomFeature.place（恒 2 次 RNG：nextInt(3)+nextInt(12)）。"""
    tree_height = rng.next_int(3) + 4
    if rng.next_int(12) == 0:
        tree_height *= 2
    # isValidPosition：y 边界 + canPlaceOn(below) + 空间检查
    if not (level.min_y + 1 <= origin[1]
            and origin[1] + tree_height + 1 <= level.max_y):
        return False
    if level.block_name(_rel(origin, "down")) not in _MUSHROOM_CAN_PLACE_ON:
        return False
    for dy in range(tree_height + 1):
        if red:
            r = foliage_radius if tree_height - 3 <= dy <= tree_height else 0
        else:
            r = 0 if dy <= 3 else foliage_radius
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                pos = (origin[0] + dx, origin[1] + dy, origin[2] + dz)
                if not level.is_air(pos) and not _is_leaves(level.block_name(pos)):
                    return False
    # makeCap
    if red:
        center = foliage_radius - 2
        for dy in range(tree_height - 3, tree_height + 1):
            r = foliage_radius if dy < tree_height else foliage_radius - 1
            for dx in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    x_edge = abs(dx) == r
                    z_edge = abs(dz) == r
                    if dy >= tree_height or x_edge != z_edge:
                        pos = (origin[0] + dx, origin[1] + dy, origin[2] + dz)
                        _place_mushroom_block(level, pos, cap_block)
    else:
        r = foliage_radius
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                x_edge = abs(dx) == r
                z_edge = abs(dz) == r
                if not (x_edge and z_edge):
                    pos = (origin[0] + dx, origin[1] + tree_height, origin[2] + dz)
                    _place_mushroom_block(level, pos, cap_block)
    # placeTrunk
    for dy in range(tree_height):
        pos = (origin[0], origin[1] + dy, origin[2])
        _place_mushroom_block(level, pos, stem_block)
    return True


def _place_mushroom_block(level, pos, block) -> None:
    n = level.block_name(pos)
    if n == "__air__" or n in _REPLACABLE_BY_MUSHROOMS:
        level.set_block(pos, block)


def _place_fallen_tree(level, rng, origin, log_block, log_length_spec,
                       log_decorators, stump_decorators) -> bool:
    """FallenTreeFeature.placeFallenTree（place 恒 True；setBlock 无条件）。"""
    # placeStump
    level.set_block(origin, log_block)
    stump_state = _TreeState()
    stump_state.trunks.append(origin)
    if stump_decorators:
        ctx = _DecoCtx(level, stump_state, rng)
        for d in stump_decorators:
            d.place(ctx)
    direction = _dir4(rng)
    log_length = _sample_int(rng, log_length_spec) - 2
    log_start = _rel_xz(origin, direction, 2 + rng.next_int(2))
    # setGroundHeightForFallenLogStartPos：上移 1，最多下移 6 找 mayPlaceOn
    # （找不到也继续，由 canPlaceEntireFallenLog 判定失败）
    cur_y = log_start[1] + 1
    for _ in range(6):
        pos = (log_start[0], cur_y, log_start[2])
        if level.valid_tree_pos(pos) and level.is_face_sturdy_up(pos):
            break
        cur_y -= 1
    log_start = (log_start[0], cur_y, log_start[2])
    # canPlaceEntireFallenLog
    gap = 0
    cursor = log_start
    ok = True
    for _ in range(log_length):
        if not level.valid_tree_pos(cursor):
            ok = False
            break
        if level.is_face_sturdy_up(cursor):
            gap = 0
        else:
            gap += 1
            if gap > 2:
                ok = False
                break
        cursor = _rel_xz(cursor, direction)
    if not ok:
        return False
    # placeFallenLog
    fallen = []
    cursor = log_start
    for _ in range(log_length):
        level.set_block(cursor, log_block)
        fallen.append(cursor)
        cursor = _rel_xz(cursor, direction)
    if log_decorators:
        st = _TreeState()
        st.trunks.extend(fallen)
        ctx = _DecoCtx(level, st, rng)
        for d in log_decorators:
            d.place(ctx)
    return True


# ======================================================================
# 配置解析与主流程
# ======================================================================

@functools.lru_cache(maxsize=None)
def _load_cf_json(cf_name: str):
    if cf_name.startswith(_MC):
        cf_name = cf_name[len(_MC):]      # place_trees_in_rect 返回带命名空间
    path = os.path.join(_WG, "configured_feature", f"{cf_name}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class TreeConfig:
    """TreeConfiguration 解析结果（type=tree）。"""

    __slots__ = ("trunk_block", "foliage_block", "trunk_placer",
                 "foliage_placer", "root_placer", "minimum_size",
                 "decorators", "ignore_vines", "below_provider")

    def __init__(self, trunk_block, foliage_block, trunk_placer,
                 foliage_placer, root_placer, minimum_size, decorators,
                 ignore_vines, below_provider):
        self.trunk_block = trunk_block
        self.foliage_block = foliage_block
        self.trunk_placer = trunk_placer
        self.foliage_placer = foliage_placer
        self.root_placer = root_placer
        self.minimum_size = minimum_size
        self.decorators = decorators
        self.ignore_vines = ignore_vines
        self.below_provider = below_provider


_TRUNK_PLACER_TYPES = {
    "straight_trunk_placer": _StraightTrunkPlacer,
    "fancy_trunk_placer": _FancyTrunkPlacer,
    "forking_trunk_placer": _ForkingTrunkPlacer,
    "giant_trunk_placer": _GiantTrunkPlacer,
    "mega_jungle_trunk_placer": _MegaJungleTrunkPlacer,
    "dark_oak_trunk_placer": _DarkOakTrunkPlacer,
    "upwards_branching_trunk_placer": _UpwardsBranchingTrunkPlacer,
}


def _parse_trunk_placer(j):
    t = j["type"][len(_MC):]
    base, ha, hb = j["base_height"], j["height_rand_a"], j["height_rand_b"]
    if t == "upwards_branching_trunk_placer":
        can_grow = [b[len(_MC):] for b in j["can_grow_through"]]
        return _UpwardsBranchingTrunkPlacer(
            base, ha, hb, j["extra_branch_steps"],
            j["place_branch_per_log_probability"], j["extra_branch_length"],
            can_grow)
    if t == "cherry_trunk_placer":
        return _CherryTrunkPlacer(base, ha, hb, j["branch_count"],
                                  j["branch_horizontal_length"],
                                  j["branch_start_offset_from_top"],
                                  j["branch_end_offset_from_top"])
    return _TRUNK_PLACER_TYPES[t](base, ha, hb)


def _parse_foliage_placer(j):
    t = j["type"][len(_MC):]
    radius, offset = j["radius"], j["offset"]
    if t == "blob_foliage_placer":
        return _BlobFoliagePlacer(radius, offset, j["height"])
    if t == "bush_foliage_placer":
        return _BushFoliagePlacer(radius, offset, j["height"])
    if t == "fancy_foliage_placer":
        return _FancyFoliagePlacer(radius, offset, j["height"])
    if t == "spruce_foliage_placer":
        return _SpruceFoliagePlacer(radius, offset, j["trunk_height"])
    if t == "pine_foliage_placer":
        return _PineFoliagePlacer(radius, offset, j["height"])
    if t == "mega_pine_foliage_placer":
        return _MegaPineFoliagePlacer(radius, offset, j["crown_height"])
    # 注册名即 jungle_foliage_placer（FoliagePlacerType.MEGA_JUNGLE_FOLIAGE_PLACER）
    if t in ("mega_jungle_foliage_placer", "jungle_foliage_placer"):
        return _MegaJungleFoliagePlacer(radius, offset, j["height"])
    if t == "acacia_foliage_placer":
        return _AcaciaFoliagePlacer(radius, offset)
    if t == "dark_oak_foliage_placer":
        return _DarkOakFoliagePlacer(radius, offset)
    if t == "cherry_foliage_placer":
        return _CherryFoliagePlacer(radius, offset, j["height"],
                                    j["wide_bottom_layer_hole_chance"],
                                    j["corner_hole_chance"],
                                    j["hanging_leaves_chance"],
                                    j["hanging_leaves_extension_chance"])
    if t == "random_spread_foliage_placer":
        return _RandomSpreadFoliagePlacer(radius, offset, j["foliage_height"],
                                          j["leaf_placement_attempts"])
    raise ValueError(f"unsupported foliage placer: {t}")


def _parse_decorator(j):
    t = j["type"][len(_MC):]
    if t == "beehive":
        return _BeehiveDecorator(j["probability"])
    if t == "trunk_vine":
        return _TrunkVineDecorator()
    if t == "leave_vine":
        return _LeaveVineDecorator(j["probability"])
    if t == "cocoa":
        return _CocoaDecorator(j["probability"])
    if t == "attached_to_logs":
        return _AttachedToLogsDecorator(
            j["probability"], _parse_provider(j["block_provider"]),
            _strip_mc_list(j["directions"]))
    if t == "attached_to_leaves":
        return _AttachedToLeavesDecorator(
            j["probability"], j["exclusion_radius_xz"], j["exclusion_radius_y"],
            _parse_provider(j["block_provider"]), j["required_empty_blocks"],
            _strip_mc_list(j["directions"]))
    if t == "place_on_ground":
        return _PlaceOnGroundDecorator(j.get("tries", 128),
                                       j.get("radius", 2),
                                       j.get("height", 1),
                                       _parse_provider(j["block_state_provider"]))
    if t == "alter_ground":
        return _AlterGroundDecorator(_parse_provider(j["provider"]))
    if t == "pale_moss":
        return _PaleMossDecorator(j["leaves_probability"],
                                  j["trunk_probability"],
                                  j["ground_probability"])
    if t == "creaking_heart":
        return _CreakingHeartDecorator(j["probability"])
    raise ValueError(f"unsupported tree decorator: {t}")


def _parse_root_placer(j):
    t = j["type"][len(_MC):]
    root_provider = _parse_provider(j["root_provider"])
    above = j.get("above_root_placement")
    above_root = None
    if above:
        above_root = (_parse_provider(above["above_root_provider"]),
                      above["above_root_placement_chance"])
    if t == "mangrove_root_placer":
        mrp = j["mangrove_root_placement"]
        muddy_prov = _parse_provider(mrp["muddy_roots_provider"])
        return _MangroveRootPlacer(
            j["trunk_offset_y"], root_provider, above_root,
            mrp["max_root_length"], mrp["max_root_width"],
            mrp["random_skew_chance"],
            [b[len(_MC):] for b in mrp["can_grow_through"]],
            [b[len(_MC):] for b in mrp["muddy_roots_in"]], muddy_prov)
    raise ValueError(f"unsupported root placer: {t}")


def _parse_minimum_size(j):
    t = j["type"][len(_MC):]
    if t == "two_layers_feature_size":
        return _TwoLayersFeatureSize(j.get("limit", 1), j.get("lower_size", 0),
                                     j.get("upper_size", 1))
    if t == "three_layers_feature_size":
        return _ThreeLayersFeatureSize(
            j.get("limit", 1), j.get("upper_limit", 1), j.get("lower_size", 0),
            j.get("middle_size", 1), j.get("upper_size", 1))
    raise ValueError(f"unsupported feature size: {t}")


def _strip_name(state_json):
    return state_json["Name"][len(_MC):]


def _strip_mc_list(names):
    """方向/方块名列表条件去前缀（"down" 无前缀，无条件切片会得空串）。"""
    return [n[len(_MC):] if n.startswith(_MC) else n for n in names]


@functools.lru_cache(maxsize=None)
def get_tree_config(cf_name: str):
    """解析 configured_feature（tree/huge_*/fallen_tree）为可执行对象。"""
    j = _load_cf_json(cf_name)
    t = j["type"][len(_MC):]
    cfg = j["config"]
    if t == "tree":
        below = cfg.get("below_trunk_provider")
        below_provider = (_parse_provider(below) if below
                          else _SimpleProvider("dirt"))
        decorators = tuple(_parse_decorator(d) for d in cfg.get("decorators", []))
        root = cfg.get("root_placer")
        return ("tree", TreeConfig(
            _strip_name(cfg["trunk_provider"]["state"])
            if cfg["trunk_provider"]["type"].endswith("simple_state_provider")
            else None,
            _strip_name(cfg["foliage_provider"]["state"])
            if cfg["foliage_provider"]["type"].endswith("simple_state_provider")
            else None,
            _parse_trunk_placer(cfg["trunk_placer"]),
            _parse_foliage_placer(cfg["foliage_placer"]),
            _parse_root_placer(root) if root else None,
            _parse_minimum_size(cfg["minimum_size"]),
            decorators, cfg.get("ignore_vines", False), below_provider))
    if t == "huge_brown_mushroom":
        return ("mushroom", False, _strip_name(cfg["cap_provider"]["state"]),
                _strip_name(cfg["stem_provider"]["state"]),
                # HugeMushroomFeatureConfiguration.CODEC:
                #   Codec.INT.optionalFieldOf("foliage_radius", 2)  (L14)
                cfg.get("foliage_radius", 2))
    if t == "huge_red_mushroom":
        return ("mushroom", True, _strip_name(cfg["cap_provider"]["state"]),
                _strip_name(cfg["stem_provider"]["state"]),
                cfg.get("foliage_radius", 2))
    if t == "fallen_tree":
        return ("fallen", _strip_name(cfg["trunk_provider"]["state"]),
                cfg["log_length"],
                tuple(_parse_decorator(d) for d in cfg.get("log_decorators", [])),
                tuple(_parse_decorator(d) for d in cfg.get("stump_decorators", [])))
    raise ValueError(f"unsupported tree-like feature type: {t}")


def _max_free_tree_height(level, max_tree_height, tree_pos, cfg) -> int:
    """TreeFeature.getMaxFreeTreeHeight（逐行直译）。"""
    for y in range(max_tree_height + 2):
        r = cfg.minimum_size.size_at(max_tree_height, y)
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                pos = (tree_pos[0] + dx, tree_pos[1] + y, tree_pos[2] + dz)
                if (not cfg.trunk_placer.is_free(level, pos)
                        or (not cfg.ignore_vines and level.is_vine(pos))):
                    return y - 2
    return max_tree_height


def _do_place(level, rng, origin, st, cfg) -> bool:
    """TreeFeature.doPlace（RNG 顺序链逐行直译）。"""
    tp = cfg.trunk_placer
    fp = cfg.foliage_placer
    tree_height = tp.get_tree_height(rng)
    foliage_height = fp.foliage_height(rng, tree_height, cfg)
    trunk_height = tree_height - foliage_height
    leaf_radius = fp.foliage_radius(rng, trunk_height)
    if cfg.root_placer is not None:
        off = cfg.root_placer.sample_trunk_offset(rng)
        trunk_origin = (origin[0], origin[1] + off, origin[2])
    else:
        trunk_origin = origin
    min_y = min(origin[1], trunk_origin[1])
    max_y = max(origin[1], trunk_origin[1]) + tree_height + 1
    if min_y >= level.min_y + 1 and max_y <= level.max_y + 1:
        clipped_tree_height = _max_free_tree_height(level, tree_height,
                                                    trunk_origin, cfg)
        min_clipped = cfg.minimum_size.min_clipped
        if (clipped_tree_height >= tree_height
                or (min_clipped is not None
                    and clipped_tree_height >= min_clipped)):
            if (cfg.root_placer is not None
                    and not cfg.root_placer.place_roots(level, st, rng, origin,
                                                        trunk_origin, cfg)):
                return False
            attachments = tp.place_trunk(level, st, rng, clipped_tree_height,
                                         trunk_origin, cfg)
            for att in attachments:
                fp.create_foliage(level, st, rng, cfg, clipped_tree_height,
                                  att, foliage_height, leaf_radius)
            return True
    return False


def place_tree(level: SimLevel, rng, origin, cfg: TreeConfig) -> bool:
    """TreeFeature.place 直译：四集合 + decorators + per-tree foliage。

    updateLeaves（distance 属性）与 StructureTemplate.updateShapeAtEdge
    不建模（渲染色板无关）。
    """
    st = _TreeState()
    result = _do_place(level, rng, origin, st, cfg)
    if result and (st.trunks or st.foliage):
        if cfg.decorators:
            ctx = _DecoCtx(level, st, rng)
            for dec in cfg.decorators:
                dec.place(ctx)
        return True
    return False


def place_configured_feature(level: SimLevel, rng, origin, cf_name: str) -> bool:
    """顶层分发：tree / huge_brown_mushroom / huge_red_mushroom / fallen_tree。"""
    parsed = get_tree_config(cf_name)
    kind = parsed[0]
    if kind == "tree":
        return place_tree(level, rng, origin, parsed[1])
    if kind == "mushroom":
        _, red, cap, stem, fr = parsed
        return _place_huge_mushroom(level, rng, origin, cap, stem, fr, red)
    if kind == "fallen":
        _, log_block, log_len, log_deco, stump_deco = parsed
        return _place_fallen_tree(level, rng, origin, log_block, log_len,
                                  log_deco, stump_deco)
    raise ValueError(kind)
