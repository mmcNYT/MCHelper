# -*- coding: utf-8 -*-
"""StructurePreviewer：结构构造组合层（composition）。

按世界种子复现 igloo（雪屋）/ shipwreck（沉船）/
nether_fortress（下界要塞）/ bastion_remnant（猪灵堡垒）/
end_city（末地城）/ trial_chambers（试炼密室，1.21+）的：
    - 模板变种选择（getVariant，cubiomes chunkGenerateRnd 流）
    - 各部件（pieces）生成锚点与朝向（getStructurePieces）
    - 各箱子的世界坐标与 LootTableSeed

考证基准：xpple/cubiomes fork commit 5815e4f 的 finders.c
    - getVariant Igloo 分支（约 L2855）/ Shipwreck 分支（约 L2873）
    - getStructurePieces Igloo / Shipwreck 分支（L3021-3343）
    - getStructurePieces Fortress 分支（L3351-3396）/
      Bastion 分支（L3397-3505）；要塞 piece 布局在 xp fork
      features/fortress.c（getFortressPieces，主 fork 的同族函数
      与其存在拐角箱子判定差异，对拍必须以 xp fork 为准）
RNG 消耗序列逐行照抄，函数内注释标注对应 C 源码位置。

版本约束：仅支持 mc >= 1.18（Xoroshiro128++ 流）；本项目版本线
收敛到 1.21 / 1.21.11（salt 均落 _SALT_1194 档，见 loot_rng）。

显示模型约定（build_display_model）：
    - 体素 dict {(x,y,z): 材质键}，x 东 / y 上 / z 南，
      (0,0,0) = 结构锚点（minBlock 西北角）的地表基准面。
    - igloo：top 顶部 y=0，middle/bottom 向下为负（地下室）。
    - shipwreck：pos y=64 对应模板 y=0。
    - shipwreck 体素做精确旋转（与箱子公式同一 R_raw 变换，自洽）；
      igloo 公式含隐藏的 piece 锚点修正（IglooPieces 源码内 offset），
      反解不唯一，故第一版模型不旋转（示意），箱子高亮取模板内
      chest 方块本身位置；RNG/世界坐标一律以 finders.c 公式为准。
    - 下界结构无整体模板 NBT（piece 程序化拼装）：fortress 按
      NetherFortressPieces.java postProcess 精确逐方块展开
      （fortress_pieces.py 转写，含楼梯/栅栏/箱子/刷怪笼/岩浆/
      地狱疣等方向性与特殊方块）；bastion 仍为足迹示意体。
      箱子标注匹配模型内 chest 体素（近邻兜底，xp 与 Java 坐标
      有已知偏差）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from Utils.Public import structure_map
from Utils.SeedReverser import block_shapes as bs
from Utils.SeedReverser import mc_random, structure_models
from . import loot_rng

# ---------------------------------------------------------------------------
# isOceanic（cubiomes/biomes.c L420）：沉船搁浅（beached）判定
# 群系 id 见 cubiomes biomes.h 枚举
# ---------------------------------------------------------------------------

OCEANIC_BIOMES = frozenset({
    0,   # ocean
    10,  # frozen_ocean
    24,  # deep_ocean
    44,  # warm_ocean
    45,  # lukewarm_ocean
    46,  # cold_ocean
    47,  # deep_warm_ocean
    48,  # deep_lukewarm_ocean
    49,  # deep_cold_ocean
    50,  # deep_frozen_ocean
})

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class Chest:
    """一个箱子：世界坐标 + 战利品表 + LootTableSeed。

    pos        世界 (x, z)，getStructurePieces 公式值（RNG 用这一坐标）
    loot_table 如 "chests/igloo_chest"
    loot_seed  无符号 64 位 LootTableSeed（Java 显示用 signed_seed 转换）
    pos_model  显示模型内的 (x, y, z)，build_display_model 时填充
    pos3       世界 (x, y, z) 三维坐标（可选；bastion 全箱子预测
               填充——同 (x,z) 不同 y 的叠柱箱显示匹配需要 y）
    """
    pos: tuple[int, int]
    loot_table: str
    loot_seed: int
    pos_model: tuple[int, int, int] | None = None
    pos3: tuple[int, int, int] | None = None


@dataclass
class Piece:
    """一个结构部件（对应 finders.c 的 Piece）。

    type/rot/depth/bb/chest_count 仅下界结构（fortress）填充；
    igloo/shipwreck 的部件无这些字段（保持默认 None）。
    """
    name: str
    pos: tuple[int, int, int]                     # 世界锚点 (x, y, z)
    chests: list[Chest] = field(default_factory=list)
    type: int | None = None                       # fortress：piece 类型号
    rot: int | None = None                        # fortress：部件朝向（起始件即结构 rotation）
    depth: int | None = None                      # fortress：生成深度（起始件为 0）
    bb: tuple[tuple[int, int, int],
              tuple[int, int, int]] | None = None  # fortress：AABB（bb0 最小角；bb1 = 含端点最大方块角，Java maxX 语义，占用闭区间 [bb0, bb1]，NeStart 的 18 实占 19 格）
    chest_count: int | None = None                # fortress：拐角 piece 是否带箱（nextInt(3)==0）
    self_seed: int | None = None                  # fortress：FORTRESS_END 生成时捕获的
                                                  #   32 位 RNG 输出（Java nextInt()）；
                                                  #   BridgeEndFiller 重建随机填桥用


@dataclass
class Composition:
    """一次 compose 的完整结果。"""
    struct_key: str                # "igloo" / "shipwreck"
    variant_name: str              # 模板名（如 "shipwreck/with_mast"）
    rotation: int                  # cubiomes 放置旋转（igloo 为 0/1）
    mirror: bool                   # 仅 igloo（cubiomes 用 mirror 编码 180°）
    anchor: tuple[int, int]        # 结构锚点 = (minBlockX, minBlockZ)
    pieces: list[Piece]
    extra: dict = field(default_factory=dict)

    @property
    def chests(self) -> list[Chest]:
        return [c for p in self.pieces for c in p.chests]


# ---------------------------------------------------------------------------
# igloo（雪屋）
# ---------------------------------------------------------------------------

# getVariant Igloo：nextInt(4) 的 4 个初值 -> (rotation, mirror)
#   t0 -> (rot0, mir0)  t1 -> (rot1, mir0)  t2 -> (rot0, mir1)  t3 -> (rot1, mir1)
_IGLOO_ORIENT = ((0, False), (1, False), (0, True), (1, True))

# getStructurePieces Igloo：bottom 箱子偏移按 (rotation << 1) | mirror
#   0b00: (8-7, 8-4)  0b01: (8-3, 8-2)  0b10: (8-4, 8-5)  0b11: (8-6, 8-1)
_IGLOO_CHEST_SUB = {0b00: (7, 4), 0b01: (3, 2), 0b10: (4, 5), 0b11: (6, 1)}

_IGLOO_LOOT_TABLE = "chests/igloo_chest"


def compose_igloo(world_seed: int, block_x: int, block_z: int,
                  version_key: str = "1.21") -> Composition:
    """雪屋：变种（旋转/有无地下室/竖井段数）+ 部件布局 + 箱子 LootTableSeed。

    block_x/block_z 为方块坐标（结构锚点；内部 &~15 取区块角）。
    """
    min_bx = block_x & ~15
    min_bz = block_z & ~15

    # finders.c getVariant Igloo：rng = chunkGenerateRnd(seed, x>>4, z>>4)
    state = structure_map.chunk_generate_rnd(world_seed,
                                             block_x >> 4, block_z >> 4)
    rot_raw, state = mc_random.next_int(state, 4)        # r->rotation = nextInt(4)
    basement, state = mc_random.next_double(state)       # basement = nextDouble < 0.5
    basement = basement < 0.5
    size, state = mc_random.next_int(state, 8)           # size = nextInt(8) + 4
    size += 4
    rotation, mirror = _IGLOO_ORIENT[rot_raw]

    # finders.c getStructurePieces Igloo
    pieces = [Piece("igloo/top", (min_bx, 90, min_bz), [])]
    if not basement:
        return Composition("igloo", "igloo/top", rotation, mirror,
                           (min_bx, min_bz), pieces,
                           {"basement": False, "size": size,
                            "rotation_raw": rot_raw})
    for i in range(1, size + 1):
        pieces.append(Piece("igloo/middle",
                            (min_bx + 2, 90 - i * 3, min_bz + 4), []))
    bottom = Piece("igloo/bottom",
                   (min_bx, 90 - 3 - size * 3, min_bz - 2), [])
    sub_x, sub_z = _IGLOO_CHEST_SUB[(rotation << 1) | (1 if mirror else 0)]
    chest_world = (min_bx + 8 - sub_x, min_bz + 8 - sub_z)

    # LootTableSeed：箱子在结构区块流中，先 skip 1 个 nextLong
    #   （placeInWorld 写入的 LootTableSeed 未被使用）
    seed2 = loot_rng.loot_seed_for_chest(world_seed, min_bx, min_bz,
                                         "igloo", skips=1, version_key=version_key)
    bottom.chests = [Chest(chest_world, _IGLOO_LOOT_TABLE, seed2)]
    pieces.append(bottom)

    return Composition("igloo", "igloo/top", rotation, mirror,
                       (min_bx, min_bz), pieces,
                       {"basement": True, "size": size,
                        "rotation_raw": rot_raw})


# ---------------------------------------------------------------------------
# shipwreck（沉船）
# ---------------------------------------------------------------------------

# sw_info 表（finders.c L3138-3158）：
#   名称 / (sx, sy, sz) / 箱数 / loot 表 / 箱相对坐标（模板局部，x 东 z 南）
_SW_INFO = (
    ("shipwreck/with_mast", 9, 21, 28, 3,
     ("chests/shipwreck_supply", "chests/shipwreck_map",
      "chests/shipwreck_treasure"),
     ((4, 9), (5, 18), (6, 24))),
    ("shipwreck/upsidedown_full", 9, 9, 28, 3,
     ("chests/shipwreck_treasure", "chests/shipwreck_map",
      "chests/shipwreck_supply"),
     ((2, 24), (3, 17), (4, 8))),
    ("shipwreck/upsidedown_fronthalf", 9, 9, 22, 2,
     ("chests/shipwreck_map", "chests/shipwreck_supply"),
     ((3, 17), (4, 8))),
    ("shipwreck/upsidedown_backhalf", 9, 9, 16, 2,
     ("chests/shipwreck_treasure", "chests/shipwreck_map"),
     ((2, 12), (3, 5))),
    ("shipwreck/sideways_full", 9, 9, 28, 3,
     ("chests/shipwreck_treasure", "chests/shipwreck_supply",
      "chests/shipwreck_map"),
     ((3, 24), (5, 8), (6, 19))),
    ("shipwreck/sideways_fronthalf", 9, 9, 24, 1,
     ("chests/shipwreck_supply",), ((5, 8),)),
    ("shipwreck/sideways_backhalf", 9, 9, 17, 2,
     ("chests/shipwreck_treasure", "chests/shipwreck_map"),
     ((3, 13), (6, 8))),
    ("shipwreck/rightsideup_full", 9, 9, 28, 3,
     ("chests/shipwreck_supply", "chests/shipwreck_map",
      "chests/shipwreck_treasure"),
     ((4, 8), (5, 18), (6, 24))),
    ("shipwreck/rightsideup_fronthalf", 9, 9, 24, 1,
     ("chests/shipwreck_supply",), ((4, 8),)),
    ("shipwreck/rightsideup_backhalf", 9, 9, 16, 2,
     ("chests/shipwreck_map", "chests/shipwreck_treasure"),
     ((5, 6), (6, 12))),
    # ---- degraded 变种（结构区块随机决定，sw_info 索引 10-19）----
    ("shipwreck/with_mast_degraded", 9, 21, 28, 3,
     ("chests/shipwreck_supply", "chests/shipwreck_map",
      "chests/shipwreck_treasure"),
     ((4, 9), (5, 18), (6, 24))),
    ("shipwreck/upsidedown_full_degraded", 9, 9, 28, 3,
     ("chests/shipwreck_treasure", "chests/shipwreck_map",
      "chests/shipwreck_supply"),
     ((2, 24), (3, 17), (4, 8))),
    ("shipwreck/upsidedown_fronthalf_degraded", 9, 9, 22, 2,
     ("chests/shipwreck_map", "chests/shipwreck_supply"),
     ((3, 17), (4, 8))),
    ("shipwreck/upsidedown_backhalf_degraded", 9, 9, 16, 2,
     ("chests/shipwreck_treasure", "chests/shipwreck_map"),
     ((2, 12), (3, 5))),
    ("shipwreck/sideways_full_degraded", 9, 9, 28, 3,
     ("chests/shipwreck_treasure", "chests/shipwreck_supply",
      "chests/shipwreck_map"),
     ((3, 24), (5, 8), (6, 19))),
    ("shipwreck/sideways_fronthalf_degraded", 9, 9, 24, 1,
     ("chests/shipwreck_supply",), ((5, 8),)),
    ("shipwreck/sideways_backhalf_degraded", 9, 9, 17, 2,
     ("chests/shipwreck_treasure", "chests/shipwreck_map"),
     ((3, 13), (6, 8))),
    ("shipwreck/rightsideup_full_degraded", 9, 9, 28, 3,
     ("chests/shipwreck_supply", "chests/shipwreck_map",
      "chests/shipwreck_treasure"),
     ((4, 8), (5, 18), (6, 24))),
    ("shipwreck/rightsideup_fronthalf_degraded", 9, 9, 24, 1,
     ("chests/shipwreck_supply",), ((4, 8),)),
    ("shipwreck/rightsideup_backhalf_degraded", 9, 9, 16, 2,
     ("chests/shipwreck_map", "chests/shipwreck_treasure"),
     ((5, 6), (6, 12))),
)

# beached（搁浅）时 start=nextInt(11) -> sw_typ 映射（finders.c L3165-3180）
_SW_BEACHED_TYPES = (0, 4, 5, 6, 7, 8, 9, 10, 17, 18, 19)

# getVariant Shipwreck：pivot (4,15) 按 rotation 得 pos 相对偏移（L2873-2896）
#   rot0 (0,0)  rot1 (19,11)  rot2 (8,30)  rot3 (-11,19)
_SW_START_POS = ((0, 0), (19, 11), (8, 30), (-11, 19))


def compose_shipwreck(world_seed: int, block_x: int, block_z: int,
                      biome_id: int,
                      version_key: str = "1.21") -> Composition:
    """沉船：变种（含 degraded）、旋转、pos 偏移、各箱坐标与 LootTableSeed。

    block_x/block_z 为方块坐标（结构锚点；内部 &~15 取区块角）。
    biome_id 为结构锚点处群系 id（isOceanic 判定搁浅）。
    """
    min_bx = block_x & ~15
    min_bz = block_z & ~15
    is_beached = biome_id not in OCEANIC_BIOMES

    # finders.c getVariant Shipwreck：rng = chunkGenerateRnd(seed, x>>4, z>>4)
    state = structure_map.chunk_generate_rnd(world_seed,
                                             block_x >> 4, block_z >> 4)
    rotation, state = mc_random.next_int(state, 4)   # NONE/CW90/CW180/CCW90
    if is_beached:
        start, state = mc_random.next_int(state, 11)
        sw_typ = _SW_BEACHED_TYPES[start]
        salt_key = "shipwreck_beached"               # decorator 18
    else:
        start, state = mc_random.next_int(state, 20)
        sw_typ = start
        salt_key = "shipwreck"                       # decorator 17
    name, _sx, _sy, _sz, n_chests, tables, rel = _SW_INFO[sw_typ]
    sx0, sz0 = _SW_START_POS[rotation]

    # finders.c getStructurePieces Shipwreck：
    #   p->pos = (minBlockX + sv->x, 64, minBlockZ + sv->z)
    pos_x = min_bx + sx0
    pos_z = min_bz + sz0

    # 箱子世界坐标（相对 pos，按 rotation 变换，L3196-3203）
    chests_world = []
    for cx, cz in rel[:n_chests]:
        if rotation == 0:
            wx, wz = pos_x + cx, pos_z + cz
        elif rotation == 1:
            wx, wz = pos_x - cz, pos_z + cx
        elif rotation == 2:
            wx, wz = pos_x - cx, pos_z - cz
        else:
            wx, wz = pos_x + cz, pos_z - cx
        chests_world.append((wx, wz))

    # LootTableSeed（L3210-3339）：按同区块箱分组，组内按序消耗 nextLong
    loot_seeds = _shipwreck_loot_seeds(world_seed, chests_world,
                                       is_beached, salt_key, version_key)

    pieces = [Piece(name, (pos_x, 64, pos_z), [])]
    for i, (wpos, table, seed) in enumerate(
            zip(chests_world, tables[:n_chests], loot_seeds)):
        pieces[0].chests.append(Chest(wpos, table, seed))

    return Composition("shipwreck", name, rotation, False,
                       (min_bx, min_bz), pieces,
                       {"beached": is_beached, "start": start,
                        "sw_typ": sw_typ})


def _shipwreck_loot_seeds(world_seed: int, chest_world,
                          is_beached: bool, salt_key: str,
                          version_key: str = "1.21") -> list[int]:
    """沉船 LootTableSeed（finders.c L3210-3339 六分支照抄）。

    分组规则：全部同区块 -> 一个流 skip 箱数后按序取；
    否则按 (0,1)/(1,2)/(0,2) 顺序找同区块对 -> 对组流 skip2 取2、
    剩余单箱自己区块流 skip1 取1；全异 -> 每箱独立流 skip1 取1。
    """
    step, decorator = loot_rng.salt_configs_for_version(version_key)[salt_key]

    def _flow(cx: int, cz: int):
        pop = loot_rng.get_population_seed(world_seed, cx & ~15, cz & ~15)
        rng = loot_rng.XoroshiroJava(pop + decorator + 10000 * step)
        if is_beached:
            rng.next_int(3)                          # updateHeight 消耗
        return rng

    n = len(chest_world)
    seeds = [0] * n
    c = chest_world
    if n == 1:
        rng = _flow(c[0][0], c[0][1])
        rng.next_long()
        seeds[0] = rng.next_long()
    elif n == 2:
        if (c[0][0] >> 4) == (c[1][0] >> 4) and \
                (c[0][1] >> 4) == (c[1][1] >> 4):
            rng = _flow(c[0][0], c[0][1])
            rng.next_long()
            rng.next_long()
            seeds[0] = rng.next_long()
            seeds[1] = rng.next_long()
        else:
            rng = _flow(c[0][0], c[0][1])
            rng.next_long()
            seeds[0] = rng.next_long()
            rng = _flow(c[1][0], c[1][1])
            rng.next_long()
            seeds[1] = rng.next_long()
    else:  # n == 3
        same01 = (c[0][0] >> 4) == (c[1][0] >> 4) and \
                 (c[0][1] >> 4) == (c[1][1] >> 4)
        same12 = (c[1][0] >> 4) == (c[2][0] >> 4) and \
                 (c[1][1] >> 4) == (c[2][1] >> 4)
        same02 = (c[0][0] >> 4) == (c[2][0] >> 4) and \
                 (c[0][1] >> 4) == (c[2][1] >> 4)
        if same01 and same12:                        # 全部同区块
            rng = _flow(c[0][0], c[0][1])
            for _ in range(3):
                rng.next_long()
            seeds[0] = rng.next_long()
            seeds[1] = rng.next_long()
            seeds[2] = rng.next_long()
        elif same01:                                 # (0,1) 同区块
            rng = _flow(c[0][0], c[0][1])
            rng.next_long()
            rng.next_long()
            seeds[0] = rng.next_long()
            seeds[1] = rng.next_long()
            rng = _flow(c[2][0], c[2][1])
            rng.next_long()
            seeds[2] = rng.next_long()
        elif same12:                                 # (1,2) 同区块
            rng = _flow(c[0][0], c[0][1])
            rng.next_long()
            seeds[0] = rng.next_long()
            rng = _flow(c[1][0], c[1][1])
            rng.next_long()
            rng.next_long()
            seeds[1] = rng.next_long()
            seeds[2] = rng.next_long()
        elif same02:                                 # (0,2) 同区块
            rng = _flow(c[0][0], c[0][1])
            rng.next_long()
            rng.next_long()
            seeds[0] = rng.next_long()
            seeds[2] = rng.next_long()
            rng = _flow(c[1][0], c[1][1])
            rng.next_long()
            seeds[1] = rng.next_long()
        else:                                        # 全部异区块
            for i in range(3):
                rng = _flow(c[i][0], c[i][1])
                rng.next_long()
                seeds[i] = rng.next_long()
    return seeds


# ---------------------------------------------------------------------------
# nether_fortress（下界要塞）
# ---------------------------------------------------------------------------

# piece 类型号 = xp feat_fortress.h 枚举序（extendFortress 的
# typ0/typ1 桥段/走廊区间依赖此序，不可改动）
(_FORTRESS_START, _BRIDGE_STRAIGHT, _BRIDGE_CROSSING,
 _BRIDGE_FORTIFIED_CROSSING, _BRIDGE_STAIRS, _BRIDGE_SPAWNER,
 _BRIDGE_CORRIDOR_ENTRANCE, _CORRIDOR_STRAIGHT, _CORRIDOR_CROSSING,
 _CORRIDOR_TURN_RIGHT, _CORRIDOR_TURN_LEFT, _CORRIDOR_STAIRS,
 _CORRIDOR_T_CROSSING, _CORRIDOR_NETHER_WART, _FORTRESS_END) = range(15)

# fortress_info 表（xp fork features/fortress.c L15-37，主 fork 同值；
# 主 fork 多出的 skip 列恒 0，xp fork 在 addFortressPiece 内改用
# chestCount/skipNextN 显式消耗，见 _fortress_add 注释）：
#   ((off_x, off_y, off_z), (size_x, size_y, size_z),
#    repeatable, weight, max, name)
_FORTRESS_INFO = (
    ((0, 0, 0), (18, 9, 18), 0, 0, 0, "NeStart"),   # 0  FORTRESS_START
    ((-1, -3, 0), (4, 9, 18), 1, 30, 0, "NeBS"),    # 1  BRIDGE_STRAIGHT
    ((-8, -3, 0), (18, 9, 18), 0, 10, 4, "NeBCr"),  # 2  BRIDGE_CROSSING
    ((-2, 0, 0), (6, 8, 6), 0, 10, 4, "NeRC"),      # 3  BRIDGE_FORTIFIED_CROSSING
    ((-2, 0, 0), (6, 10, 6), 0, 10, 3, "NeSR"),     # 4  BRIDGE_STAIRS
    ((-2, 0, 0), (6, 7, 8), 0, 5, 2, "NeMT"),       # 5  BRIDGE_SPAWNER
    ((-5, -3, 0), (12, 13, 12), 0, 5, 1, "NeCE"),   # 6  BRIDGE_CORRIDOR_ENTRANCE
    ((-1, 0, 0), (4, 6, 4), 1, 25, 0, "NeSC"),      # 7  CORRIDOR_STRAIGHT
    ((-1, 0, 0), (4, 6, 4), 0, 15, 5, "NeSCSC"),    # 8  CORRIDOR_CROSSING
    ((-1, 0, 0), (4, 6, 4), 0, 5, 10, "NeSCRT"),    # 9  CORRIDOR_TURN_RIGHT
    ((-1, 0, 0), (4, 6, 4), 0, 5, 10, "NeSCLT"),    # 10 CORRIDOR_TURN_LEFT
    ((-1, -7, 0), (4, 13, 9), 1, 10, 3, "NeCCS"),   # 11 CORRIDOR_STAIRS
    ((-3, 0, 0), (8, 6, 8), 0, 7, 2, "NeCTB"),      # 12 CORRIDOR_T_CROSSING
    ((-5, -3, 0), (12, 13, 12), 0, 5, 2, "NeCSR"),  # 13 CORRIDOR_NETHER_WART
    ((-1, -3, 0), (4, 9, 7), 0, 0, 0, "NeBEF"),     # 14 FORTRESS_END
)

_FORTRESS_LOOT_TABLE = "chests/nether_bridge"

# 拐角箱子偏移（xp finders.c L3364-3367 / L3378-3381，以 pos-1 为基按 rot）
_FORTRESS_CHEST_OFF = {
    _CORRIDOR_TURN_LEFT:  ((3, 3), (-3, 3), (-3, -3), (3, -3)),
    _CORRIDOR_TURN_RIGHT: ((1, 3), (-3, 1), (-1, -3), (3, -1)),
}

# 防御上限（真实要塞 piece 数在数百级；防实现 bug 死循环）
_FORTRESS_MAX_STEPS = 100000


class _FortressEnv:
    """getFortressPieces 的生成环境（对应 FortressPieceEnv）。

    accepted: 已接受的 piece（含起始件，碰撞检测全集）；
    queue:    待处理队列（C 的 list->next 链，FIFO 追加、随机序号取出）；
    ntyp:     各类型已接受计数；typlast: 最近接受的非 END 类型。
    """

    __slots__ = ("state", "accepted", "queue", "ntyp", "typlast")

    def __init__(self, state: int) -> None:
        self.state = state
        self.accepted: list[dict] = []
        self.queue: list[dict] = []
        self.ntyp = [0] * 15
        self.typlast = 0


def _fortress_piece_aabb(pos: tuple[int, int, int], typ: int,
                         facing: int) -> tuple[tuple, tuple]:
    """addFortressPiece 的包围盒（xp features/fortress.c L42-65）。

    返回 (bb0, bb1)，与 C 相同：bb1 为"最大角"闭边界语义（碰撞
    比较用 >=/<=，与 C 逐行一致）。
    """
    (d0x, d0y, d0z), (d1x, d1y, d1z) = _FORTRESS_INFO[typ][0], \
        _FORTRESS_INFO[typ][1]
    x, y, z = pos
    b0x, b0y, b0z = x, y + d0y, z
    b1x, b1y, b1z = x, y + d0y + d1y, z
    if facing == 0:      # north
        b0x += d0x
        b0z += d0z - d1z
        b1x += d0x + d1x
        b1z += d0z
    elif facing == 1:    # east
        b0x += d0z
        b0z += d0x
        b1x += d0z + d1z
        b1z += d0x + d1x
    elif facing == 2:    # south
        b0x += d0x
        b0z += d0z
        b1x += d0x + d1x
        b1z += d0z + d1z
    else:                # west（facing == 3）
        b0x += d0z - d1z
        b0z += d0x
        b1x += d0z
        b1z += d0x + d1x
    return (b0x, b0y, b0z), (b1x, b1y, b1z)


def _fortress_add(env: _FortressEnv, typ: int, x: int, y: int, z: int,
                  depth: int, facing: int, pending: bool):
    """xp fork addFortressPiece（features/fortress.c L39-107）逐行照抄。

    与主 fork 的差异（对拍基准取 xp fork，finders.c 同此逻辑）：
    拐角 piece 在碰撞检测通过后真实消耗 chestCount = nextInt(3) == 0
    （主 fork 用 skip 列近似：CORRIDOR_TURN_* skip=1 / FORTRESS_END
    skip=1，对 piece 序列的影响不同）；FORTRESS_END 用
    skipNextN(rng, 1)。碰撞失败不消耗 RNG，返回 None。
    pending=True 时接受入队并更新 ntyp/typlast。
    """
    state = env.state
    b0, b1 = _fortress_piece_aabb((x, y, z), typ, facing)
    for q in env.accepted:
        q0, q1 = q["bb0"], q["bb1"]
        if (q1[0] >= b0[0] and q0[0] <= b1[0] and
                q1[1] >= b0[1] and q0[1] <= b1[1] and
                q1[2] >= b0[2] and q0[2] <= b1[2]):
            return None                                   # collision
    chest_count = None
    self_seed = None
    if typ in (_CORRIDOR_TURN_LEFT, _CORRIDOR_TURN_RIGHT):
        v, state = mc_random.next_int(state, 3)
        chest_count = 1 if v == 0 else 0
    elif typ == _FORTRESS_END:
        # skipNextN(rng, 1)：流演进不变，但捕获该步的 32 位输出
        # （Java nextInt()，等价 BridgeEndFiller 的 selfSeed）。
        self_seed = mc_random.next_bits(state, 32)
    piece = {"typ": typ, "pos": (x, y, z), "rot": facing, "depth": depth,
             "bb0": b0, "bb1": b1, "chest_count": chest_count}
    if typ == _FORTRESS_END:
        piece["self_seed"] = self_seed
    if pending:
        env.accepted.append(piece)
        if typ != _FORTRESS_END:
            env.ntyp[typ] += 1
            env.typlast = typ
        env.queue.append(piece)
    env.state = state
    return piece


def _fortress_extend(env: _FortressEnv, p: dict, offh: int, offv: int,
                     turn: int, corridor: int) -> None:
    """extendFortress（xp features/fortress.c L110-175）逐行照抄。"""
    depth = p["depth"] + 1
    facing = p["rot"]
    typ0 = _CORRIDOR_STRAIGHT if corridor else _BRIDGE_STRAIGHT
    typ1 = typ0 + (7 if corridor else 6)
    y = p["bb0"][1] + offv

    if turn == 0:        # forward
        if facing == 0:
            x, z = p["bb0"][0] + offh, p["bb0"][2] - 1
        elif facing == 1:
            x, z = p["bb1"][0] + 1, p["bb0"][2] + offh
        elif facing == 2:
            x, z = p["bb0"][0] + offh, p["bb1"][2] + 1
        else:
            x, z = p["bb0"][0] - 1, p["bb0"][2] + offh
    elif turn == -1:     # left
        if facing & 1:
            x, z = p["bb0"][0] + offh, p["bb0"][2] - 1
            facing = 0
        else:
            x, z = p["bb0"][0] - 1, p["bb0"][2] + offh
            facing = 3
    else:                # right（turn == +1）
        if facing & 1:
            x, z = p["bb0"][0] + offh, p["bb1"][2] + 1
            facing = 2
        else:
            x, z = p["bb1"][0] + 1, p["bb0"][2] + offh
            facing = 1

    anchor0 = env.accepted[0]["bb0"]                      # env->list->bb0
    if abs(x - anchor0[0]) > 112 or abs(z - anchor0[2]) > 112:
        _fortress_add(env, _FORTRESS_END, x, y, z, depth, facing, False)
        return

    valid = 0
    weight_tot = 0
    for t in range(typ0, typ1):
        max_t = _FORTRESS_INFO[t][4]
        if max_t > 0 and env.ntyp[t] >= max_t:
            continue
        if max_t > 0:
            valid = 1
        weight_tot += _FORTRESS_INFO[t][3]

    if valid == 0 or weight_tot <= 0 or depth > 30:
        _fortress_add(env, _FORTRESS_END, x, y, z, depth, facing, True)
        return

    for _ in range(5):
        n, env.state = mc_random.next_int(env.state, weight_tot)
        for t in range(typ0, typ1):
            max_t = _FORTRESS_INFO[t][4]
            if max_t > 0 and env.ntyp[t] >= max_t:
                continue
            n -= _FORTRESS_INFO[t][3]
            if n >= 0:
                continue
            if env.typlast == t and not _FORTRESS_INFO[t][2]:
                break
            if _fortress_add(env, t, x, y, z, depth, facing, True) is not None:
                return
    _fortress_add(env, _FORTRESS_END, x, y, z, depth, facing, True)


def _fortress_extend_piece(env: _FortressEnv, p: dict) -> None:
    """extendFortressPiece（xp features/fortress.c L177-213）逐行照抄。

    FORTRESS_END 无分支（C 无 default），处理时不消耗 RNG。
    """
    t = p["typ"]
    if t == _BRIDGE_STRAIGHT:
        _fortress_extend(env, p, 1, 3, 0, 0)
    elif t in (_BRIDGE_CROSSING, _FORTRESS_START):
        _fortress_extend(env, p, 8, 3, 0, 0)
        _fortress_extend(env, p, 8, 3, -1, 0)
        _fortress_extend(env, p, 8, 3, 1, 0)
    elif t == _BRIDGE_FORTIFIED_CROSSING:
        _fortress_extend(env, p, 2, 0, 0, 0)
        _fortress_extend(env, p, 2, 0, -1, 0)
        _fortress_extend(env, p, 2, 0, 1, 0)
    elif t == _BRIDGE_STAIRS:
        _fortress_extend(env, p, 2, 6, 1, 0)
    elif t == _BRIDGE_CORRIDOR_ENTRANCE:
        _fortress_extend(env, p, 5, 3, 0, 1)
    elif t == _CORRIDOR_STRAIGHT:
        _fortress_extend(env, p, 1, 0, 0, 1)
    elif t == _CORRIDOR_CROSSING:
        _fortress_extend(env, p, 1, 0, 0, 1)
        _fortress_extend(env, p, 1, 0, -1, 1)
        _fortress_extend(env, p, 1, 0, 1, 1)
    elif t == _CORRIDOR_TURN_RIGHT:
        _fortress_extend(env, p, 1, 0, 1, 1)
    elif t == _CORRIDOR_TURN_LEFT:
        _fortress_extend(env, p, 1, 0, -1, 1)
    elif t == _CORRIDOR_STAIRS:
        _fortress_extend(env, p, 1, 0, 0, 1)
    elif t == _CORRIDOR_T_CROSSING:
        h = 5 if p["rot"] in (0, 3) else 1
        v, env.state = mc_random.next_int(env.state, 8)
        _fortress_extend(env, p, h, 0, -1, 0 if v == 0 else 1)
        v, env.state = mc_random.next_int(env.state, 8)
        _fortress_extend(env, p, h, 0, 1, 0 if v == 0 else 1)
    elif t == _CORRIDOR_NETHER_WART:
        _fortress_extend(env, p, 5, 3, 0, 1)
        _fortress_extend(env, p, 5, 11, 0, 1)


def compose_nether_fortress(world_seed: int, block_x: int, block_z: int,
                            version_key: str = "1.21") -> Composition:
    """下界要塞：piece 生成（getFortressPieces）+ 拐角箱子 + LootTableSeed。

    block_x/block_z 为方块坐标（结构锚点；内部 >>4 取区块坐标）。
    RNG 与序列照抄 xp fork features/fortress.c getFortressPieces
    （1.16+ 分支；主 fork 同构，拐角箱子判定以 xp fork 为准）。
    主循环每轮 nextInt(队列长度) 随机取一个待处理 piece（与 Java
    NetherFortressPieces 的 queue.remove(randomIndex) 一致）。
    """
    cx = block_x >> 4
    cz = block_z >> 4
    # getFortressPieces：rng = chunkGenerateRnd(seed, posX>>4, posZ>>4)
    state = structure_map.chunk_generate_rnd(world_seed, cx, cz)

    # 起始 piece（C L241-260）：pos = (chunkX*16+2, 64, chunkZ*16+2)，
    # bb = pos..pos+size(18,9,18)，rot = nextInt(4)（1.16+ 分支）
    sx = cx * 16 + 2
    sz = cz * 16 + 2
    rot, state = mc_random.next_int(state, 4)
    start = {"typ": _FORTRESS_START, "pos": (sx, 64, sz), "rot": rot,
             "depth": 0, "chest_count": None,
             "bb0": (sx, 64, sz), "bb1": (sx + 18, 64 + 9, sz + 18)}

    env = _FortressEnv(state)
    env.accepted.append(start)
    env.ntyp[_FORTRESS_START] = 1
    env.typlast = 0
    _fortress_extend_piece(env, start)

    steps = 0
    while env.queue:
        steps += 1
        if steps > _FORTRESS_MAX_STEPS:                   # 防御（不可达）
            break
        idx, env.state = mc_random.next_int(env.state, len(env.queue))
        cur = env.queue.pop(idx)
        _fortress_extend_piece(env, cur)

    # 箱子与 LootTableSeed（xp finders.c L3351-3396）：仅拐角 piece
    # 且 chestCount 的有箱，表 chests/nether_bridge；每箱独立区块流
    # skip 0（C 注释：假设无两 piece 的箱子同区块）。
    min_bx = block_x & ~15
    min_bz = block_z & ~15
    pieces: list[Piece] = []
    for q in env.accepted:
        name = _FORTRESS_INFO[q["typ"]][5]
        piece = Piece(name, q["pos"], [], type=q["typ"], rot=q["rot"],
                      depth=q["depth"], bb=(q["bb0"], q["bb1"]),
                      chest_count=q["chest_count"],
                      self_seed=q.get("self_seed"))
        if q["typ"] in _FORTRESS_CHEST_OFF and q["chest_count"]:
            dx, dz = _FORTRESS_CHEST_OFF[q["typ"]][q["rot"]]
            wx = q["pos"][0] - 1 + dx
            wz = q["pos"][2] - 1 + dz
            seed = loot_rng.loot_seed_for_chest(
                world_seed, wx, wz, "nether_fortress", 0, version_key)
            piece.chests.append(Chest((wx, wz), _FORTRESS_LOOT_TABLE, seed))
        pieces.append(piece)

    return Composition("nether_fortress", "nether_fortress", rot, False,
                       (min_bx, min_bz), pieces,
                       {"n_pieces": len(pieces),
                        "n_chests": sum(len(p.chests) for p in pieces)})


# ---------------------------------------------------------------------------
# bastion_remnant（猪灵堡垒）
# ---------------------------------------------------------------------------

# getStructurePieces Bastion（xp finders.c L3397-3505）的 xp 近似
# 起始件信息：start -> (具体件名, 箱1 (dx,dz)×4rot, 箱2 或 None,
# loot 表键)。坐标以 minBlock 为基（dx 直接加在 minBlockX/minBlockZ
# 上）。
# 注意：真实 jigsaw 拼装里 start 池选中的是 air_base 占位件，箱子
# 在展开后的具体件里（见 compose_bastion_remnant）。xp 的固定偏移
# 是近似估计：仅 units/treasure 两型与真实拼装坐标同区块且 seed 全
# 等（reg 探针 d=0/EQ），hoglin_stable/bridge 两型跨区块（偏差
# 15~29 格）已弃用。本表保留作回归对照（test_nether_compose 对拍
# xp 公式）。
_BASTION_STARTS = (
    ("bastion/units/walls/wall_base",                    # 0 units/air_base
     ((-6, 20), (-20, -6), (6, -20), (20, 6)),
     ((-6, 21), (-21, -6), (6, -21), (21, 6)),
     "bastion_other"),
    ("bastion/hoglin_stable/ramparts/ramparts_3",        # 1 hoglin_stable
     ((-4, 29), (-29, -4), (4, -29), (29, 4)),
     None,
     "bastion_other"),
    ("bastion/treasure/ramparts/mid_wall_main",          # 2 treasure
     ((17, -23), (23, 17), (-17, 23), (-23, -17)),
     ((19, -25), (25, 19), (-19, 25), (-25, -19)),
     "bastion_other"),
    ("bastion/bridge/starting_pieces/entrance",          # 3 bridge
     ((9, 4), (-4, 9), (-9, -4), (4, -9)),
     None,
     "bastion_bridge"),
)


def compose_bastion_remnant(world_seed: int, block_x: int, block_z: int,
                            version_key: str = "1.21") -> Composition:
    """猪灵堡垒：start/rotation 变种 + 全箱子战利品预测。

    箱子全集 = 真实 jigsaw 拼装（assemble_bastion，与游戏同 RNG 流，
    reg3 已对拍 6/6）展开出的每个 piece 内的每个 chest 方块（模板
    NBT 扫描，含起始件）；LootTableSeed 按游戏放置语义（ent 字节码
    实证）：
      - 每 piece 按模板 blocks (Y,X,Z) 升序放置；带 NBT 且是
        RandomizableContainer 的方块写 LootTableSeed = 流.nextLong()
        （每箱恰好一次；盒外方块被跳过不消耗）；
      - 每个箱子所在区块的流 = getPopulationSeed(world, 该区块角)
        + decorator(0) + 10000*step(4)；同一 piece 内多箱恒同区块
        （模板内相邻），按块内 (Y,X,Z) 连抽。

    rotation/start 取自 getVariant Bastion 流（与
    structure_map._bastion_variant 同流：nextInt(4)、nextInt(4)）。
    extra["start"]/extra["xp_variant"]/extra["xp_rot"] 保持 xp 变种
    流口径（UI 起点类型显示与回归对照用）；variant_name 为拼装
    起始 air_base 件名。

    性能：拼装 ~100 piece + 模板 NBT 扫描（缓存）≈ 数十 ms，
    与显示渲染（_bastion_jigsaw_voxels 同源拼装）同量级。
    """
    min_bx = block_x & ~15
    min_bz = block_z & ~15
    # getVariant Bastion（finders.c L2079-2106，1.18+：先 rotation 后 start）
    state = structure_map.chunk_generate_rnd(world_seed, block_x >> 4,
                                             block_z >> 4)
    rotation, state = mc_random.next_int(state, 4)
    start, state = mc_random.next_int(state, 4)
    xp_rot = rotation                       # finders.c getVariant 的 sv->rotation

    name = _BASTION_START_AIR_BASE[start]
    piece = Piece(name, (min_bx, 64, min_bz), [])

    # ---- 真实拼装：全箱子按放置顺序收集，按所在区块分组 ----
    from Utils.SeedReverser.jigsaw_assembly import assemble_bastion
    res = assemble_bastion(world_seed, min_bx >> 4, min_bz >> 4)
    step, decorator = loot_rng.salt_configs_for_version(
        version_key)["bastion_remnant"]

    chest_records: list[tuple[tuple[int, int, int], str, int]] = []
    by_chunk: dict[tuple[int, int], list] = {}
    for pi, jp in enumerate(res.pieces):
        for wpos, table in _piece_chests_world(jp):
            chest_records.append((wpos, table, pi))
            by_chunk.setdefault((wpos[0] >> 4, wpos[2] >> 4),
                                []).append(len(chest_records) - 1)

    # ---- 每区块 population 流：块内按消耗顺序连抽 nextLong ----
    for ckey in sorted(by_chunk):
        pcx, pcz = ckey
        rng = loot_rng.XoroshiroJava(
            loot_rng.get_population_seed(world_seed, pcx * 16, pcz * 16)
            + decorator + 10000 * step)
        for idx in by_chunk[ckey]:
            wpos, table, pi = chest_records[idx]
            seed = rng.next_long()
            piece.chests.append(Chest((wpos[0], wpos[2]),
                                      table[len("minecraft:"):], seed,
                                      pos3=wpos))

    return Composition("bastion_remnant", name, rotation, False,
                       (min_bx, min_bz), [piece],
                       {"start": start, "world_seed": world_seed,
                        "xp_variant": _BASTION_START_XP[start],
                        "xp_rot": xp_rot,
                        "n_pieces": len(res.pieces),
                        "n_chests": len(piece.chests)})


# start 池 air_base 占位件名（拼装起始件，本身无箱子）
_BASTION_START_AIR_BASE = (
    "bastion/units/air_base",
    "bastion/hoglin_stable/air_base",
    "bastion/treasure/big_air_full",
    "bastion/bridge/starting_pieces/entrance_base",
)
# xp 近似起始具体件名（原 _BASTION_STARTS 的 name 列，回归对照用）
_BASTION_START_XP = (
    "bastion/units/walls/wall_base",
    "bastion/hoglin_stable/ramparts/ramparts_3",
    "bastion/treasure/ramparts/mid_wall_main",
    "bastion/bridge/starting_pieces/entrance",
)


def _piece_chests_world(piece):
    """jigsaw piece 内全部 chest 方块 -> 世界坐标（块内 (Y,X,Z) 序）。

    模板 NBT 直扫（_BASTION_RAW_CACHE 无 loot 表信息，单独走
    parse_nbt + 缓存）；旋转用 jigsaw_assembly.rot_piece_pos（与
    渲染体素同一变换）。返回 [(世界 (x,y,z), "minecraft:chests/…")]。
    """
    from Utils.SeedReverser.jigsaw_assembly import rot_piece_pos
    key = piece.template.key
    cached = _BASTION_CHESTS_CACHE.get(key)
    if cached is None:
        cached = _template_chests(key)
    sx = piece.template.size_x
    sz = piece.template.size_z
    px, py, pz = piece.piece_pos
    out = []
    for (lx, ly, lz), table in cached:
        rx, ry, rz = rot_piece_pos(piece.rot, (lx, ly, lz), sx, sz)
        out.append(((px + rx, py + ry, pz + rz), table))
    out.sort(key=lambda t: (t[0][1], t[0][0], t[0][2]))
    return out


_BASTION_CHESTS_CACHE: dict = {}


def _template_chests(key: str) -> tuple:
    """模板 NBT 内全部 chest 方块：(局部 (x,y,z), loot 表) 升序 tuple。

    只取 minecraft:chest（jigsaw/spawner 非 RandomizableContainer，
    不消耗流）；loot 表取 nbt.LootTable（37/37 全有）。
    """
    cached = _BASTION_CHESTS_CACHE.get(key)
    if cached is not None:
        return cached
    tpl_path = os.path.join(structure_models.TEX_DIR, "..", "..",
                            "bastion", "templates",
                            *key.split("/")[1:]) + ".nbt"
    with open(tpl_path, "rb") as f:
        root = structure_models.parse_nbt(f.read())
    pr = root.get("palette")
    if pr is None:
        palettes = root.get("palettes")
        palette = (palettes[1][0][1] if palettes else []) \
            if isinstance(palettes, tuple) else []
    else:
        palette = pr[1]
    names = {i: structure_models._palette_entry_name(e)
             for i, e in enumerate(palette)}
    blocks = root.get("blocks")
    lst: list = []
    if blocks:
        for item in blocks[1]:
            pos_raw = item.get("pos")
            pos = pos_raw[1] if isinstance(pos_raw, tuple) else pos_raw
            if not isinstance(pos, list) or len(pos) != 3:
                continue
            st = item.get("state", 0)
            if not (0 <= st < len(names)):
                continue
            if names[st] != "minecraft:chest":
                continue
            nbt = item.get("nbt")
            table = None
            if nbt is not None:
                payload = nbt[1] if isinstance(nbt, tuple) else nbt
                lt = payload.get("LootTable") if hasattr(payload, "get") \
                    else None
                if lt is not None:
                    table = str(lt[1] if isinstance(lt, tuple) else lt)
            lst.append(((int(pos[0]), int(pos[1]), int(pos[2])), table))
    out = tuple(lst)
    _BASTION_CHESTS_CACHE[key] = out
    return out


# ---------------------------------------------------------------------------
# end_city（末地城）
# ---------------------------------------------------------------------------

def compose_end_city(world_seed: int, block_x: int, block_z: int,
                     version_key: str = "1.21") -> Composition:
    """末地城：piece 树逐 seed 精确生成 + 箱子 LootTableSeed。

    piece 树与箱子/loot 流全部在 end_city_pieces 模块（cubiomes
    finders.c L2336-2595 + xp fork End_City 分支逐行转写，详见其
    模块注释）；本层仅做 EndPiece -> Piece/Chest 数据结构转换。
    piece y 为相对高度（首件 y=0），anchor_y 显示基准面取 64。
    """
    from . import end_city_pieces as ecp
    res = ecp.build_end_city(world_seed, block_x, block_z, version_key)
    pieces: list[Piece] = []
    for q in res.pieces:
        piece = Piece(q.name, q.pos, [], type=q.type, rot=q.rot,
                      depth=q.depth, bb=(q.bb0, q.bb1))
        for (cx, cz, table, seed) in q.chests:
            piece.chests.append(Chest((cx, cz), table, seed))
        pieces.append(piece)
    return Composition("end_city", "end_city", res.rotation, False,
                       res.anchor, pieces,
                       {"ship": res.ship, "n_pieces": len(pieces),
                        "n_chests": sum(len(p.chests) for p in pieces),
                        "world_seed": world_seed})


# ---------------------------------------------------------------------------
# trial_chambers（试炼密室，1.21+）
# ---------------------------------------------------------------------------

_TRIAL_RAW_CACHE: dict = {}
_TRIAL_CONTAINERS_CACHE: dict = {}
_TRIAL_CONTAINER_MATS = frozenset({"minecraft:chest", "minecraft:barrel"})


def compose_trial_chambers(world_seed: int, block_x: int, block_z: int,
                           version_key: str = "1.21") -> Composition:
    """试炼密室：jigsaw 拼装 + 全容器战利品预测（1.21+）。

    起点流（structure_map._jigsaw_variant trial 分支同流）：
        y = nextInt(21) - 40（start_height uniform）
        rotation = nextInt(4)
        start    = nextInt(2)（chamber/end 池 end_1/end_2 等权）
    alias 流（fhc.create）不耗主流，trial_assembly.resolve_aliases
    独立重建；拼装由 assemble_trial_chambers 复刻（fhp.a + fgs.a，
    skip_y_bound=21 补位，详见其模块注释）。

    容器口径（1.21.11 jar 实证，probe_fill2/3 + 池 JSON 全量扫描）：
        - 30 chest + 3 barrel 中仅 14 个模板 NBT 带 LootTable 字段；
          19 个无字段 chest 游戏内为空箱（RandomizableContainer
          postProcess 只认 NBT 字段，无字段不写 LootTableSeed 不消
          耗流；1.21 jar 无任何给 trial 箱填表的 Java 代码，池 JSON
          45/47 张 0 处 loot_table 引用，fnv 的 13 处 chests/trial
          _chambers = 表注册常量、ri 的 3 处 = 池 key 前缀巧合）。
        - 2 个 vault 无 LootTable 字段且开箱走交互系统（试炼宝库），
          不进预测列表（渲染走 stone 风格体素）。
        - LootTableSeed 每区块 population 流 = get_population_seed
          + decorator(4) + 10000*step(3)（salt 表
          trial_chambers=(3,4)，cl_salts_1_21_5.txt L6），同区块内
          按放置序（piece 序 × 块内 (Y,X,Z)）连抽 nextLong。
    """
    min_bx = block_x & ~15
    min_bz = block_z & ~15
    # 起点流：y -> rotation -> start（structure_map._jigsaw_variant 同序）
    state = structure_map.chunk_generate_rnd(world_seed, block_x >> 4,
                                             block_z >> 4)
    y_raw, state = mc_random.next_int(state, 21)
    start_y = y_raw - 40
    rotation, state = mc_random.next_int(state, 4)

    from Utils.StructurePreviewer import trial_assembly as ta
    res = ta.assemble_trial_chambers(world_seed, min_bx >> 4, min_bz >> 4,
                                     start_y)
    step, decorator = loot_rng.salt_configs_for_version(
        version_key)["trial_chambers"]

    # ---- 容器收集：有 LootTable 字段的 chest/barrel，按放置序 ----
    records: list[tuple[tuple[int, int, int], str, int]] = []
    by_chunk: dict[tuple[int, int], list] = {}
    for pi, jp in enumerate(res.pieces):
        for wpos, table in _piece_containers_world(jp):
            records.append((wpos, table, pi))
            by_chunk.setdefault((wpos[0] >> 4, wpos[2] >> 4),
                                []).append(len(records) - 1)

    start_name = res.pieces[0].template.key
    piece = Piece(start_name, (min_bx, start_y, min_bz), [])
    for ckey in sorted(by_chunk):
        pcx, pcz = ckey
        rng = loot_rng.XoroshiroJava(
            loot_rng.get_population_seed(world_seed, pcx * 16, pcz * 16)
            + decorator + 10000 * step)
        for idx in by_chunk[ckey]:
            wpos, table, _pi = records[idx]
            seed = rng.next_long()
            piece.chests.append(Chest((wpos[0], wpos[2]),
                                      table[len("minecraft:"):], seed,
                                      pos3=wpos))

    return Composition("trial_chambers", "trial_chambers/" + start_name,
                       rotation, False, (min_bx, min_bz), [piece],
                       {"start": res.start_index, "world_seed": world_seed,
                        "start_y": start_y,
                        "n_pieces": len(res.pieces),
                        "n_chests": len(piece.chests)})


def _piece_containers_world(piece):
    """jigsaw piece 内带 LootTable 的容器 -> 世界坐标（世界 (Y,X,Z) 序）。

    trial 模板 NBT 直扫（_TRIAL_CONTAINERS_CACHE 缓存）；容器 =
    chest/barrel（均 RandomizableContainer 同 postProcess 写种子
    路径），仅模板 NBT 有 LootTable 字段的进列表（19 个无字段
    chest 游戏内空箱，见 compose_trial_chambers docstring）；旋转
    用 jigsaw_assembly.rot_piece_pos（与渲染体素同一变换）。
    返回 [(世界 (x,y,z), "minecraft:chests/trial_chambers/…")]。
    """
    from Utils.SeedReverser.jigsaw_assembly import rot_piece_pos
    key = piece.template.key
    cached = _TRIAL_CONTAINERS_CACHE.get(key)
    if cached is None:
        cached = _trial_template_containers(key)
    sx = piece.template.size_x
    sz = piece.template.size_z
    px, py, pz = piece.piece_pos
    out = []
    for (lx, ly, lz), table in cached:
        rx, ry, rz = rot_piece_pos(piece.rot, (lx, ly, lz), sx, sz)
        out.append(((px + rx, py + ry, pz + rz), table))
    out.sort(key=lambda t: (t[0][1], t[0][0], t[0][2]))
    return out


def _trial_template_containers(key: str) -> tuple:
    """trial 模板 NBT 内带 LootTable 字段的容器：(局部 (x,y,z), 表名)。

    chest/barrel 同扫（barrel 也走 RandomizableContainer）；无
    LootTable 字段的不入列表。key 为剥前缀模板 key，路径经
    trial_assembly.ASSET_DIR（assets/SeedReverser/trial_chambers/）。
    """
    cached = _TRIAL_CONTAINERS_CACHE.get(key)
    if cached is not None:
        return cached
    from Utils.StructurePreviewer import trial_assembly as ta
    path = ta.ASSET_DIR.joinpath("templates",
                                 *ta._split_key(key)).with_suffix(".nbt")
    with open(path, "rb") as f:
        root = structure_models.parse_nbt(f.read())
    pr = root.get("palette")
    if pr is None:
        palettes = root.get("palettes")
        palette = (palettes[1][0][1] if palettes else []) \
            if isinstance(palettes, tuple) else []
    else:
        palette = pr[1]
    names = {i: structure_models._palette_entry_name(e)
             for i, e in enumerate(palette)}
    blocks = root.get("blocks")
    lst: list = []
    if blocks:
        for item in blocks[1]:
            pos_raw = item.get("pos")
            pos = pos_raw[1] if isinstance(pos_raw, tuple) else pos_raw
            if not isinstance(pos, list) or len(pos) != 3:
                continue
            st = item.get("state", 0)
            if not (0 <= st < len(names)):
                continue
            if names[st] not in _TRIAL_CONTAINER_MATS:
                continue
            nbt = item.get("nbt")
            table = None
            if nbt is not None:
                payload = nbt[1] if isinstance(nbt, tuple) else nbt
                lt = payload.get("LootTable") if hasattr(payload, "get") \
                    else None
                if lt is not None:
                    table = str(lt[1] if isinstance(lt, tuple) else lt)
            if table is None:
                continue
            lst.append(((int(pos[0]), int(pos[1]), int(pos[2])), table))
    out = tuple(lst)
    _TRIAL_CONTAINERS_CACHE[key] = out
    return out


# ---------------------------------------------------------------------------
# pillager_outpost（掠夺者前哨站）
# ---------------------------------------------------------------------------

_OUTPOST_RAW_CACHE: dict = {}
_OUTPOST_CONTAINERS_CACHE: dict = {}


def compose_pillager_outpost(world_seed: int, block_x: int, block_z: int,
                             version_key: str = "1.21") -> Composition:
    """掠夺者前哨站：jigsaw 拼装 + 战利品预测（1.21.11 语义）。

    起点流（structure_map._check_outpost 落点在先；拼装变量流与
    bastion 同序）：rotation = nextInt(4)（start pool 单元素 base_plate
    仍有 nextInt(1) 消耗，引擎内完成）；start_height absolute(0) 零
    消耗；起点底面 = 地表高度（getFirstFreeHeight(中心)，预览平坦
    基准 63，拼装拓扑与 RNG 不受影响）。

    容器口径（.temp/outpost 探针实证）：
        - watchtower 系模板无 chest 方块：箱子由 DATA 标记
          （ChestSouth @(9,14,10)）在 handleDataMarker 放置，
          createChest 消耗装饰流 nextLong() 作 LootTableSeed；
        - towers 池 list 元素依序放置 watchtower + overgrown 两个
          子模板，同位各 1 箱：先 watchtower（腐蚀判定前，恒消耗），
          后 overgrown（其方块 95% 被 outpost_rot 蚀掉——被蚀则
          不写箱子不消耗；保留（~5%）则后写覆盖并消耗一次）；
        - 结构线（布局）与装饰线（箱子种子）独立：箱子种子按
          世界坐标所在区块的 population 流连抽（salt=(4,9)），
          按 (子模板放置序 × 块内 (Y,X,Z)) 排序。
    """
    min_bx = block_x & ~15
    min_bz = block_z & ~15
    # getVariant Outpost（finders.c L1634-1696 拼装变量部分：nextInt(4)）
    state = structure_map.chunk_generate_rnd(world_seed, block_x >> 4,
                                             block_z >> 4)
    rotation, state = mc_random.next_int(state, 4)

    from Utils.StructurePreviewer import outpost_assembly as oa
    res = oa.assemble_outpost(world_seed, min_bx >> 4, min_bz >> 4)
    step, decorator = loot_rng.salt_configs_for_version(
        version_key)["pillager_outpost"]

    # ---- 容器收集：list piece 依子模板序展开 DATA 标记箱子 ----
    records: list[tuple[tuple[int, int, int], str, int]] = []
    by_chunk: dict[tuple[int, int], list] = {}
    for pi, jp in enumerate(res.pieces):
        for wpos, table, _si in _outpost_piece_containers_world(jp):
            records.append((wpos, table, pi))
            by_chunk.setdefault((wpos[0] >> 4, wpos[2] >> 4),
                                []).append(len(records) - 1)

    start_name = res.pieces[0].template.key
    piece = Piece(start_name, (min_bx, 63, min_bz), [])
    # 同 pos3 后写覆盖（游戏语义：overgrown 箱保留时替换 watchtower
    # 箱方块，容器内容以后消耗的种子为准；两条记录都真实消耗装饰流，
    # 去重仅作用于呈现层，不影响消耗序与后续箱子种子偏移）。
    chests_by_pos: dict[tuple[int, int, int], Chest] = {}
    for ckey in sorted(by_chunk):
        pcx, pcz = ckey
        rng = loot_rng.XoroshiroJava(
            loot_rng.get_population_seed(world_seed, pcx * 16, pcz * 16)
            + decorator + 10000 * step)
        for idx in by_chunk[ckey]:
            wpos, table, _pi = records[idx]
            seed = rng.next_long()
            chests_by_pos[wpos] = Chest(
                (wpos[0], wpos[2]), table[len("minecraft:"):], seed,
                pos3=wpos)
    piece.chests.extend(chests_by_pos.values())

    return Composition("pillager_outpost",
                       "pillager_outpost/" + start_name,
                       rotation, False, (min_bx, min_bz), [piece],
                       {"start": 0, "world_seed": world_seed,
                        "n_pieces": len(res.pieces),
                        "n_chests": len(piece.chests)})


def _outpost_piece_containers_world(piece):
    """前哨站 piece 的箱子（DATA 标记语义）-> [(世界 (x,y,z), 表, 子序)]。

    - 单模板 piece（base_plate/feature_plate/features）：模板 NBT 内
      的 chest 方块（features 均无；防御式扫描，与 bastion 同路）。
    - list piece（towers）：watchtower + overgrown 依序放置，DATA
      标记 Chest* 在 watchtower @(9,14,10)；overgrown 的箱子先经
      outpost_rot 腐蚀判定（95% 删除 → 不写不消耗），保留则后写
      同位覆盖（记录保留两箱，后写者排序在后排消耗在后）。
    块内放置序 (Y,X,Z)；list 子模板先于排序键（Java 依序两次
    placeInWorld，每个子模板内 (Y,X,Z)）。
    """
    from Utils.SeedReverser.jigsaw_assembly import rot_piece_pos
    from Utils.StructurePreviewer import outpost_assembly as oa
    out: list[tuple[tuple[int, int, int], str, int]] = []
    sx = piece.template.size_x
    sz = piece.template.size_z
    px, py, pz = piece.piece_pos
    subs = piece.sub_templates or [piece.template.key]
    procs = piece.sub_processors or [None] * len(subs)
    for si, sub in enumerate(subs):
        for (lx, ly, lz), table in _outpost_template_containers(sub):
            rx, ry, rz = rot_piece_pos(piece.rot, (lx, ly, lz), sx, sz)
            wpos = (px + rx, py + ry, pz + rz)
            # overgrown 子元素：outpost_rot 腐蚀判定（逐方块独立流）
            if procs[si] == "outpost_rot" and oa.apply_outpost_rot(
                    "minecraft:chest", *wpos) is None:
                continue
            out.append((wpos, table, si))
    # 放置序：子模板序 -> (Y,X,Z)
    out.sort(key=lambda t: (t[2], t[0][1], t[0][0], t[0][2]))
    return out


def _outpost_template_containers(key: str) -> tuple:
    """前哨站模板 NBT 内 chest 方块（含 DATA 标记位）：(局部 (x,y,z), 表)。

    watchtower 系无 chest 方块但有 DATA 标记 jigsaw（Chest* name，
    nbt.final_state = minecraft:chest）→ 按标记位产出箱子记录；
    普通模板（防御式）仍扫真实 chest 方块的 nbt.LootTable。
    """
    cached = _OUTPOST_CONTAINERS_CACHE.get(key)
    if cached is not None:
        return cached
    from Utils.StructurePreviewer import outpost_assembly as oa
    path = oa.ASSET_DIR.joinpath("templates",
                                 *oa._split_key(key)).with_suffix(".nbt")
    with open(path, "rb") as f:
        root = structure_models.parse_nbt(f.read())
    pr = root.get("palette")
    if pr is None:
        palettes = root.get("palettes")
        palette = (palettes[1][0][1] if palettes else []) \
            if isinstance(palettes, tuple) else []
    else:
        palette = pr[1]
    names = {i: structure_models._palette_entry_name(e)
             for i, e in enumerate(palette)}
    blocks = root.get("blocks")
    lst: list = []
    if blocks:
        for item in blocks[1]:
            pos_raw = item.get("pos")
            pos = pos_raw[1] if isinstance(pos_raw, tuple) else pos_raw
            if not isinstance(pos, list) or len(pos) != 3:
                continue
            st = item.get("state", 0)
            if not (0 <= st < len(names)):
                continue
            nm = names[st]
            nbt = item.get("nbt")
            payload = None
            if nbt is not None:
                payload = nbt[1] if isinstance(nbt, tuple) else nbt
            if nm == "minecraft:chest":
                table = None
                if payload is not None and hasattr(payload, "get"):
                    lt = payload.get("LootTable")
                    if lt is not None:
                        table = str(lt[1] if isinstance(lt, tuple) else lt)
                if table is not None:
                    lst.append(((int(pos[0]), int(pos[1]), int(pos[2])),
                                table))
            elif nm == "minecraft:jigsaw" and payload is not None \
                    and hasattr(payload, "get"):
                # DATA 标记（handleDataMarker 语义）：name=Chest*、
                # final_state 为容器方块 → 该位置运行时放置容器
                jname = str(payload.get("name", "") or "")
                if not jname.startswith("Chest"):
                    continue
                final = str(payload.get("final_state", "") or "")
                if final != "minecraft:chest":
                    continue
                lt = payload.get("LootTable")
                table = str(lt[1] if isinstance(lt, tuple) else lt) \
                    if lt is not None else "minecraft:chests/pillager_outpost"
                lst.append(((int(pos[0]), int(pos[1]), int(pos[2])), table))
    out = tuple(lst)
    _OUTPOST_CONTAINERS_CACHE[key] = out
    return out


# ---------------------------------------------------------------------------
# 显示辅助
# ---------------------------------------------------------------------------

# 视口认得的箱子方块材质键（structure_models 的映射名，小写）
_CHEST_MATS = frozenset({"chest", "trapped_chest", "barrel"})


def _is_chest_value(v) -> bool:
    """体素值是否箱子方块（兼容纯字符串与 (纹理, 形状) 元组）。"""
    if isinstance(v, tuple):
        return v[0] in _CHEST_MATS
    return v in _CHEST_MATS

# 下界结构键（显示模型箱子标注 y 抬升逻辑用）
_NETHER_KEYS = frozenset({"nether_fortress", "bastion_remnant"})


def _igloo_model_parts(comp: Composition) -> list[tuple[str, int, int, int]]:
    """雪屋模型部件清单 [(模板文件名, dx, dy, dz)]（显示用）。

    部件锚点偏移直接照抄 finders.c getStructurePieces Igloo
    （相对 minBlock）：top (0,0,0)、middle i (+2, -3i, +4)、
    bottom (0, -3-3size, -2)。无地下室时仅 top。
    """
    files = structure_models.TEMPLATE_FILES["igloo"]
    if not comp.extra.get("basement"):
        return [(files[0], 0, 0, 0)]
    parts = [(files[0], 0, 0, 0)]
    size = comp.extra["size"]
    for i in range(1, size + 1):
        parts.append((files[1], 2, -3 * i, 4))
    parts.append((files[2], 0, -3 - 3 * size, -2))
    return parts


def _rotate_voxels(voxels: dict, rotation: int,
                   nominal: tuple[int, int] | None = None) -> tuple[dict, tuple[int, int]]:
    """体素按 cubiomes 放置旋转精确变换，返回 (旋转后体素, (平移x, 平移z))。

    R_raw（相对模板原点，与箱子世界坐标公式同向）：
        rot0: (x, z)          rot1: (-z, x)
        rot2: (-x, -z)        rot3: (z, -x)
    非完整方块体素（(纹理, 形状) 元组）同步旋转形状码朝向：
    rot1 时模板 z+（南）缘转到 x+（东）缘，与坐标映射
    (x, z) -> (-z, x) 一致（等价 cubiomes rot 换向表 n->e）。
    返回的平移 = min(min_x, min_z)，使体素回到非负象限；调用方用
    startPos + shift 得到模型锚点相对坐标（见 compose_display_model）。

    nominal=(sx, sz) 名义包围盒：shift 按完整格点算。用于边缘方块
    可被降级风化缺失的模板（沉船 degraded）：实际体素 min 会大于
    名义 min，按体素算 shift 会把模型整体错位、区块网格相位偏移；
    名义口径缺失端留空缺（正是风化样子），世界对齐恒等式
    anchor + start_off + model = anchor + startPos + rot(p) 不变。
    缺省按实际体素算（igloo 等完整模板不受影响）。
    """
    if rotation == 0:
        return voxels, (0, 0)
    rot = {1: lambda x, z: (-z, x),
           2: lambda x, z: (-x, -z),
           3: lambda x, z: (z, -x)}[rotation]
    out = {}
    for (x, y, z), mat in voxels.items():
        if isinstance(mat, tuple) and len(mat) == 2 \
                and isinstance(mat[1], str):
            mat = (mat[0], bs.shape_rotation(mat[1], rotation))
        nx, nz = rot(x, z)
        out[(nx, y, nz)] = mat
    if nominal is not None:
        sx, sz = nominal
        # 名义完整格点 [0,sx-1]x[0,sz-1] 旋转后的 min（解析式，
        # 与实际体素无关，防缺失端拉偏平移量）
        mnx, mnz = {1: (-(sz - 1), 0),
                    2: (-(sx - 1), -(sz - 1)),
                    3: (0, -(sx - 1))}[rotation]
    else:
        mnx = min(p[0] for p in out)
        mnz = min(p[2] for p in out)
    return ({(x - mnx, y, z - mnz): m for (x, y, z), m in out.items()},
            (mnx, mnz))


# ---------------------------------------------------------------------------
# stronghold（要塞）
# ---------------------------------------------------------------------------

def compose_stronghold(world_seed: int, block_x: int, block_z: int,
                       version_key: str = "1.21") -> Composition:
    """要塞：逐 seed 拼装（piece 树 + Java Y 沉降）+ 全箱子战利品预测。

    block_x/block_z 为方块坐标（该 chunk 处生成的首要塞锚点）。
    拼装/loot 流照抄 xp fork features/stronghold.c
    （getStrongholdPieces + getStrongholdLoot，对拍 probe_sh 8 案例
    checks=4206 FAILS=0）；几何 = StrongholdPieces.java postProcess
    逐段转写（stronghold_pieces.build_stronghold_voxels）。
    表名按 C loot_tables.c 分档写入 Chest.loot_table（crossing 恒
    1_13、library/corridor 见 loot_table_for_version）。
    """
    from Utils.StructurePreviewer import stronghold_pieces as sp
    cx = block_x >> 4
    cz = block_z >> 4
    raw = sp.compose_stronghold_pieces(world_seed, cx, cz, version_key)

    pieces: list[Piece] = []
    portal_eyes = 0
    for i, p in enumerate(raw):
        name = sp.SH_NAMES[p["type"]]
        piece = Piece(name, (p["pos"][0], p["pos"][1], p["pos"][2]), [],
                      type=p["type"], rot=p["rot"], depth=p["depth"],
                      bb=(p["bb0"], p["bb1"]))
        for ch in p.get("chests", []):
            table = sp.loot_table_for_version(ch["table"], version_key)
            piece.chests.append(Chest((ch["x"], ch["z"]), table,
                                      ch["seed"] & loot_rng._M64,
                                      pos3=(ch["x"], ch.get("y", 0),
                                            ch["z"])))
        if p["type"] == sp.SH_PORTAL_ROOM:
            portal_eyes = p.get("eyes", 0)
        pieces.append(piece)

    anchor = (min(p["bb0"][0] for p in raw),
              min(p["bb0"][2] for p in raw))
    return Composition("stronghold", "stronghold", 0, False, anchor,
                       pieces,
                       {"world_seed": world_seed,
                        "chunk": (cx, cz),
                        "n_pieces": len(pieces),
                        "n_chests": sum(len(pc.chests) for pc in pieces),
                        "portal_eyes": portal_eyes})


def _stronghold_voxels(comp: Composition) -> tuple[dict, set]:
    """要塞显示：逐 piece postProcess 转写（stronghold_pieces）。

    模型 (x,z) = 世界 - anchor、y = 世界 - 64（沉降后可为负，
    display_model 统一 min 平移）。箱子标注：RNG 箱子与几何同源
    （同 piece 序 + 同 rot_pos 变换），返回箱 (x,z) 集合供 display
    exact 匹配（含 chest 体素落点核对，漏配走通用路径）。
    """
    from Utils.StructurePreviewer import stronghold_pieces as sp
    scx, scz = comp.extra["chunk"]
    raw = sp.assemble_stronghold(comp.extra["world_seed"], scx, scz,
                                 sink_y=True)
    vox = sp.build_stronghold_voxels(raw, comp.anchor)
    chest_offs: set = set()
    for p in raw:
        for c in p.get("chests", []):
            chest_offs.add((c["x"] - comp.anchor[0],
                            c["z"] - comp.anchor[1]))
    return vox, chest_offs


# ---------------------------------------------------------------------------
# woodland_mansion（林地府邸）
# ---------------------------------------------------------------------------

def compose_mansion(world_seed: int, block_x: int, block_z: int,
                    version_key: str = "1.21") -> Composition:
    """林地府邸：逐 seed 拼装（MansionGrid + createMansion 转写）+
    全箱子战利品预测。

    block_x/block_z 为方块坐标（生成 chunk；内部 >>4 取区块角）。
    拼装/装饰线全部在 mansion_pieces.assemble_mansion（对拍 probe
    6 案例：ROT/COUNT/grid×6/pieces 全量一致，test_mansion_grid.out
    ALL PASS）。loot salt 用 _SALT_1194 档（4,5）。
    """
    from Utils.StructurePreviewer import mansion_pieces as mp
    cx = block_x >> 4
    cz = block_z >> 4
    pieces_raw, chests_raw, rot_name = mp.assemble_mansion(world_seed, cx, cz)

    # anchor = 全 piece bb 的 min (x, z)（与 stronghold 同口径）
    anchor = (min(pc["pos"][0] for pc in pieces_raw),
              min(pc["pos"][2] for pc in pieces_raw))

    piece = Piece("woodland_mansion", (anchor[0], 64, anchor[1]), [])
    for c in chests_raw:
        piece.chests.append(Chest((c["pos"][0], c["pos"][2]),
                                  c["loot_table"],
                                  c["loot_seed"] & loot_rng._M64,
                                  pos3=c["pos"]))

    return Composition("woodland_mansion", "woodland_mansion",
                       mp._ROT_NAMES.index(rot_name), False, anchor,
                       [piece],
                       {"world_seed": world_seed, "chunk": (cx, cz),
                        "rot_name": rot_name,
                        "n_pieces": len(pieces_raw),
                        "n_chests": len(chests_raw)})


def _mansion_voxels(comp: Composition) -> tuple[dict, set]:
    """府邸显示：逐 piece 模板 NBT 精确拼装（mansion_pieces 转写）。

    重新跑 assemble_mansion（确定性 RNG，与 compose_mansion 结果
    一致），逐 piece 加载模板体素（_load_template：air/structure_void/
    structure_block 不入），经 transform_pos(mirror, rot) 变换 +
    shape_mirror + shape_rotation（与 transform 同序：镜像先、
    旋转后；torch/panel/chest/door 等朝向类形状码同步换向）。
    随机箱（DATA 标记）由容器记录补写 chest 体素（DATA 标记不产出
    NBT 方块）；模板自带固定 Items 装饰箱在模板方块内正常渲染。

    模型口径同 fortress/bastion：(x,z) = 世界 - anchor、y = 世界 -
    64。箱子标注走 pos3 3D exact 匹配（同源预测 + 同变换，逐项
    重合），chest_offs 仅为接口形状。
    """
    from Utils.SeedReverser import block_shapes as _bs
    from Utils.StructurePreviewer import mansion_pieces as mp
    pieces_raw, chests_raw, _rot = mp.assemble_mansion(
        comp.extra["world_seed"], *comp.extra["chunk"])
    ax, az = comp.anchor
    vox: dict = {}
    for pc in pieces_raw:
        tpl = mp._load_template(pc["name"])
        rot_idx = mp._ROT_NAMES.index(pc["rot"])
        px, py, pz = pc["pos"]
        for (lx, ly, lz), (nm, shp) in tpl["blocks"].items():
            wx, wy, wz = mp.transform_pos((lx, ly, lz), pc["mirror"],
                                          pc["rot"])
            wx += px
            wy += py
            wz += pz
            mat = structure_models._map_block(nm, "half")
            if mat is None:
                continue
            if shp is not None:
                # transform 先镜像后旋转，形状码同步两步换向
                shp = _bs.shape_mirror(shp, pc["mirror"])
                shp = _bs.shape_rotation(shp, rot_idx)
            base = mat[len("halfheight:"):] \
                if mat.startswith("halfheight:") else mat
            if shp is None and mat.startswith("halfheight:"):
                shp = _bs.SHAPE_SLAB_BOT
            vox[(wx - ax, wy - 64, wz - az)] = \
                (base, shp) if shp is not None else base
    # 随机箱补写（DATA 标记位置 = 箱子位置，handleDataMarker 实证）
    chest_offs: set = set()
    for c in comp.chests:
        if c.pos3 is None:
            continue
        vox[(c.pos3[0] - ax, c.pos3[1] - 64, c.pos3[2] - az)] = "chest"
        chest_offs.add((c.pos[0] - ax, c.pos[1] - az))
    return vox, chest_offs


# ---------------------------------------------------------------------------
# ocean_ruin（海底废墟）
# ---------------------------------------------------------------------------

# biome tag has_structure/ocean_ruin_{cold,warm}.json（1.21.11 jar 实证）
# -> cubiomes 群系 id：cold = 海洋/冷水系 6 种；warm = 暖水系 3 种
_OCEAN_COLD_BIOMES = frozenset({0, 10, 24, 46, 49, 50})
_OCEAN_WARM_BIOMES = frozenset({44, 45, 48})

# cold big 三表（BIG_RUINS_BRICK/CRACKED/MOSSY 各 4 元素：1,2,3,8）
_OCEAN_BIG_COLD_IDX = (1, 2, 3, 8)

# allPositions 的 8 候选偏移规则（OceanRuinPieces.java L181-188 逐行照抄）：
#   ((x_base, x_lo, x_hi), (z_base, z_lo, z_hi))
#   offset = base + Mth.nextInt(rng, lo, hi)，相对主盒 min 角
_OCEAN_ALLPOS_RULES = (
    ((-16, 1, 8), (16, 1, 7)),
    ((-16, 1, 8), (0, 1, 7)),
    ((-16, 1, 8), (-16, 4, 8)),
    ((0, 1, 7), (16, 1, 7)),
    ((0, 1, 7), (-16, 4, 6)),
    ((16, 1, 7), (16, 3, 8)),
    ((16, 1, 7), (0, 1, 7)),
    ((16, 1, 7), (-16, 4, 8)),
)

# chest DATA 标记局部坐标（48 模板 NBT 扫描实证，每模板 0/1 个；
# mossy_1 无 chest 仅 drowned）。键 = 模板短名。
_OCEAN_CHEST_MARKERS = {
    "big_brick_1": (5, 0, 4), "big_brick_2": (9, 1, 10),
    "big_brick_3": (12, 2, 2), "big_brick_8": (5, 0, 4),
    "big_cracked_1": (5, 0, 4), "big_cracked_2": (9, 1, 10),
    "big_cracked_3": (12, 2, 2), "big_cracked_8": (5, 0, 4),
    "big_mossy_1": (5, 0, 4), "big_mossy_2": (9, 1, 10),
    "big_mossy_3": (12, 2, 2), "big_mossy_8": (5, 0, 4),
    "big_warm_4": (11, 0, 8), "big_warm_5": (7, 0, 7),
    "big_warm_6": (10, 0, 9), "big_warm_7": (11, 0, 7),
    "brick_1": (3, 1, 5), "brick_2": (2, 0, 1), "brick_3": (1, 0, 5),
    "brick_4": (1, 1, 4), "brick_5": (4, 0, 4), "brick_6": (2, 0, 2),
    "brick_7": (1, 0, 3), "brick_8": (3, 1, 4),
    "cracked_1": (3, 1, 5), "cracked_2": (2, 0, 1), "cracked_3": (1, 0, 5),
    "cracked_4": (1, 1, 4), "cracked_5": (4, 0, 4), "cracked_6": (2, 0, 2),
    "cracked_7": (1, 0, 3), "cracked_8": (3, 1, 4),
    "mossy_2": (2, 0, 1), "mossy_3": (1, 0, 5), "mossy_4": (1, 1, 4),
    "mossy_5": (4, 0, 4), "mossy_6": (2, 0, 2), "mossy_7": (1, 0, 3),
    "mossy_8": (3, 1, 4),                      # mossy_1：无 chest
    "warm_1": (3, 1, 1), "warm_2": (3, 1, 4), "warm_3": (3, 0, 4),
    "warm_4": (1, 0, 2), "warm_5": (3, 0, 4), "warm_6": (4, 1, 4),
    "warm_7": (3, 0, 3), "warm_8": (3, 0, 3),
}

_OCEAN_LOOT_BIG = "chests/underwater_ruin_big"
_OCEAN_LOOT_SMALL = "chests/underwater_ruin_small"


def _ocean_rot_xz(x: int, z: int, rot: int) -> tuple[int, int]:
    """Java StructureTemplate.transform（mirror=NONE、pivot=0）x/z 分量
    （与 _rotate_voxels 的 R_raw 同向，y 不变）。"""
    return ((x, z), (-z, x), (-x, -z), (z, -x))[rot & 3]


def _mth_next_int(state: int, lo: int, hi: int) -> tuple[int, int]:
    """Java Mth.nextInt(random, min, max)（min>=max 返回 min 不消耗）。"""
    if lo >= hi:
        return lo, state
    v, state = mc_random.next_int(state, hi - lo + 1)
    return v + lo, state


def _ocean_piece_bbox(p: dict) -> tuple[int, int, int, int]:
    """piece 世界平面 bbox（StructureTemplate.getBoundingBox：对角
    = transform(size-1, rot)，fromCorners 取 min/max；x/z 闭区间）。"""
    short = p["name"].split("/")[-1]
    sx, sz = (16, 16) if short.startswith("big_") else (6, 7)
    tx, tz = _ocean_rot_xz(sx - 1, sz - 1, p["rot"])
    x0, x1 = sorted((p["pos"][0], p["pos"][0] + tx))
    z0, z1 = sorted((p["pos"][2], p["pos"][2] + tz))
    return x0, x1, z0, z1


def _ocean_piece_in_chunk(p: dict, pcx: int, pcz: int) -> bool:
    """piece bbox 与区块 [16cx, 16cx+15]² 相交判定（闭区间，与
    BoundingBox.intersects 同义；postProcess 触发条件）。"""
    x0, x1, z0, z1 = _ocean_piece_bbox(p)
    return (x0 <= 16 * pcx + 15 and x1 >= 16 * pcx
            and z0 <= 16 * pcz + 15 and z1 >= 16 * pcz)


def compose_ocean_ruin(world_seed: int, block_x: int, block_z: int,
                       biome_id: int = -1,
                       version_key: str = "1.21") -> Composition:
    """海底废墟：大型/簇件拼装（OceanRuinPieces 转写）+ 全箱子预测。

    block_x/block_z 为方块坐标（结构区块；内部 &~15 取区块角）。
    biome_id 为结构锚点处群系 id（冷/暖水判定；未知 -1 按 cold）。

    内部流 = 区块 LCG（chunk_generate_rnd，与 igloo/shipwreck 同款），
    消耗序（OceanRuinPieces.java 逐行照抄）：
        nextFloat<=0.3 大型判定 -> 主件模板选择（warm nextInt(4|8)、
        cold nextInt(4|8) 选 idx 后 brick/cracked/mossy 三件套连放）
        -> 大型时 nextFloat<=0.9 簇判定（&& 短路：small 不消耗）
        -> addClusterRuins：16 次 Mth.nextInt 候选位 + Mth.nextInt(4,8)
        数量 + 每轮 nextInt(size) 取点、nextInt(4) 朝向，候选盒与主盒
        （对角盒，非主件 bbox）相交也照常消耗、只是不放 piece。

    箱子语义（handleDataMarker L261-268）：模板无真实容器方块，箱子
    全部由 "chest" DATA 标记运行时放置，每标记恰消耗所在区块装饰流
    1 发 nextLong（large 表/big、small 表/small 按件 isLarge 定）；
    placeInChunk 按 pieces 序对 bbox 相交区块触发 postProcess，
    filterBlocks 按区块 bbox 过滤标记（区块外标记不消耗）；drowned
    标记实体化与风化/调色板消耗均走 pos 独立流，不影响装饰流。
    cold 三件套同位叠放（brick/cracked/mossy 同 n 的标记坐标一致，
    仅 mossy_1 无标记）：同组多标记全部消耗，但方块后写覆盖，
    世界最终只一个箱子（组内最后 piece 的种子生效，幽灵消耗不
    出箱）——见生效箱过滤段。

    版本：loot salt 用 _SALT_1194 档。
    """
    min_bx = block_x & ~15
    min_bz = block_z & ~15
    temp = "warm" if biome_id in _OCEAN_WARM_BIOMES else "cold"
    salt_key = "ocean_ruin_warm" if temp == "warm" else "ocean_ruin_cold"

    # OceanRuinStructure.generatePieces（L42-46）：锚点 = 区块角 y90
    state = structure_map.chunk_generate_rnd(world_seed,
                                             block_x >> 4, block_z >> 4)
    rotation, state = mc_random.next_int(state, 4)   # Rotation.getRandom

    pieces_raw: list[dict] = []   # {name, pos, rot, large}（生成序）

    def _add_piece(pos: tuple[int, int, int], rot: int,
                   is_large: bool) -> None:
        """OceanRuinPieces.addPiece（L192-210）：模板选择消耗本流。"""
        nonlocal state
        if temp == "warm":
            if is_large:                      # Util.getRandom(BIG_WARM)
                idx, state = mc_random.next_int(state, 4)
                name = f"underwater_ruin/big_warm_{4 + idx}"
            else:                             # Util.getRandom(WARM_RUINS)
                idx, state = mc_random.next_int(state, 8)
                name = f"underwater_ruin/warm_{1 + idx}"
            pieces_raw.append({"name": name, "pos": pos, "rot": rot,
                               "large": is_large})
        else:
            ln = 4 if is_large else 8
            idx, state = mc_random.next_int(state, ln)
            n = (_OCEAN_BIG_COLD_IDX if is_large
                 else tuple(range(1, 9)))[idx]
            pre = "big_" if is_large else ""
            for part in ("brick", "cracked", "mossy"):
                pieces_raw.append({
                    "name": f"underwater_ruin/{pre}{part}_{n}",
                    "pos": pos, "rot": rot, "large": is_large})

    anchor90 = (min_bx, 90, min_bz)
    large_f, state = mc_random.next_float(state)      # L147 大型判定
    large = large_f <= 0.3
    _add_piece(anchor90, rotation, large)             # L149 主件
    cluster = False
    n_cluster = 0
    if large:
        cluster_f, state = mc_random.next_float(state)   # L150（&&短路）
        cluster = cluster_f <= 0.9
        if cluster:
            # addClusterRuins（L155-177）：主盒 = anchor 到
            # transform((15,0,15), rot) 对角盒（fromCorners 取 min/max）
            d15x, d15z = _ocean_rot_xz(15, 15, rotation)
            mx = min(min_bx, min_bx + d15x)
            mz = min(min_bz, min_bz + d15z)
            mbx0, mbx1 = sorted((min_bx, min_bx + d15x))
            mbz0, mbz1 = sorted((min_bz, min_bz + d15z))
            # allPositions（L179-190）：8 候选，各 2 次 Mth.nextInt
            cands: list[tuple[int, int]] = []
            for (xb, xl, xh), (zb, zl, zh) in _OCEAN_ALLPOS_RULES:
                ox, state = _mth_next_int(state, xl, xh)
                oz, state = _mth_next_int(state, zl, zh)
                cands.append((mx + xb + ox, mz + zb + oz))
            count, state = _mth_next_int(state, 4, 8)    # L163
            for _ in range(count):                        # L165-176
                if not cands:
                    continue
                ci, state = mc_random.next_int(state, len(cands))
                cpos = cands.pop(ci)
                crot, state = mc_random.next_int(state, 4)
                # 候选盒 = cpos 到 cpos+transform((5,0,6), crot)
                ex, ez = _ocean_rot_xz(5, 6, crot)
                cbx0, cbx1 = sorted((cpos[0], cpos[0] + ex))
                cbz0, cbz1 = sorted((cpos[1], cpos[1] + ez))
                intersects = (cbx0 <= mbx1 and cbx1 >= mbx0
                              and cbz0 <= mbz1 and cbz1 >= mbz0)
                if not intersects:                        # 相交也耗过 RNG
                    _add_piece((cpos[0], 90, cpos[1]), crot, False)
                    n_cluster += 1

    # ---- 箱子记录：chest DATA 标记 -> 世界坐标（transform 同件 rot）----
    chest_recs: list[dict] = []
    for pi, p in enumerate(pieces_raw):
        short = p["name"].split("/")[-1]
        mk = _OCEAN_CHEST_MARKERS.get(short)
        if mk is None:
            continue
        rx, rz = _ocean_rot_xz(mk[0], mk[2], p["rot"])
        wpos = (p["pos"][0] + rx, p["pos"][1] + mk[1], p["pos"][2] + rz)
        chest_recs.append({
            "pi": pi, "pos3": wpos,
            "table": _OCEAN_LOOT_BIG if p["large"] else _OCEAN_LOOT_SMALL,
            "seed": None})

    # ---- LootTableSeed：按区块分组，装饰流消耗序 = 相交 pieces 序 ----
    step, decorator = loot_rng.salt_configs_for_version(version_key)[salt_key]
    by_chunk: dict[tuple[int, int], list[dict]] = {}
    for rec in chest_recs:
        ckey = (rec["pos3"][0] >> 4, rec["pos3"][2] >> 4)
        by_chunk.setdefault(ckey, []).append(rec)
    for ckey, recs in by_chunk.items():
        pcx, pcz = ckey
        recs.sort(key=lambda r: r["pi"])   # piece 序（每件至多 1 箱）
        rng = loot_rng.XoroshiroJava(
            loot_rng.get_population_seed(world_seed, pcx * 16, pcz * 16)
            + decorator + 10000 * step)
        pending = {r["pi"]: r for r in recs}
        for pi, p in enumerate(pieces_raw):
            if pi not in pending:
                continue
            # 该 piece 必须与区块相交才 postProcess（其 chest 必在本
            # 区块，因记录按 chest 世界坐标归块）；相交才消耗。
            if _ocean_piece_in_chunk(p, pcx, pcz):
                pending[pi]["seed"] = rng.next_long()

    # ---- 生效箱过滤（cold 同位三件套）----
    # 三件套（brick/cracked/mossy 同 n）pos/rot 相同且 chest 标记局
    # 部坐标一致（48 模板扫描实证，仅 mossy_1 无标记）→ 同 pos3 多
    # 条记录。postProcess 按 pieces 序后写覆盖，世界最终只有一个箱
    # 子方块 = 组内最后放置 piece 的 LootTableSeed；同组其余标记照
    # 常消耗装饰流 nextLong（幽灵消耗）但方块被覆盖不生效。
    live_by_pos3: dict[tuple, dict] = {}
    for rec in chest_recs:
        prev = live_by_pos3.get(rec["pos3"])
        if prev is None or rec["pi"] > prev["pi"]:
            live_by_pos3[rec["pos3"]] = rec

    # ---- Composition 组装 ----
    pieces = [Piece(p["name"], p["pos"], [], rot=p["rot"])
              for p in pieces_raw]
    main_short = pieces_raw[0]["name"].split("/")[-1]
    for rec in sorted(live_by_pos3.values(), key=lambda r: r["pi"]):
        pieces[rec["pi"]].chests.append(
            Chest((rec["pos3"][0], rec["pos3"][2]), rec["table"],
                  rec["seed"] & loot_rng._M64, pos3=rec["pos3"]))

    return Composition("ocean_ruin", f"ocean_ruin/{main_short}",
                       rotation, False, (min_bx, min_bz), pieces,
                       {"temp": temp, "large": large, "cluster": cluster,
                        "world_seed": world_seed,
                        "n_pieces": len(pieces_raw),
                        "n_cluster": n_cluster,
                        "n_chests": len(live_by_pos3)})


def _ocean_ruin_voxels(comp: Composition) -> tuple[dict, set]:
    """海底废墟显示：逐 piece 模板 NBT 拼装（世界坐标组装）。

    逐件加载模板体素（_load_template_voxels），经 _ocean_rot_xz 旋转
    （形状码同步 shape_rotation，与箱子变换同一 R_raw）+ piece pos
    平移到世界，再减 anchor/y90 得模型坐标；遍历顺序 = pieces 序 =
    Java addPiece 序（后写覆盖先写，cold 三件套同位叠放：mossy 完整
    覆盖上层、brick/cracked 露出其空位）。
    未做 BlockRotProcessor 风化转写（integrity 判定流 =
    RandomSource.create(Mth.getSeed(世界 pos))，y 为运行时海床沉降
    值，平坦预览不可精确复现——故 cold big 三件套显示为三层并集
    示意）。DATA 标记箱子由容器记录补写 chest 体素（标记不产出
    方块），与 RNG 预测同源，pos3 3D exact 匹配。
    模型口径同 fortress/bastion：(x,z) = 世界 - anchor、y = 世界 - 90。
    """
    from Utils.SeedReverser import block_shapes as _bs
    ax, az = comp.anchor
    vox: dict = {}
    for p in comp.pieces:
        short = p.name.split("/")[-1]
        part = _load_template_voxels(f"underwater_ruin__{short}.nbt")
        rot = p.rot or 0
        px, py, pz = p.pos
        for (x, y, z), m in part.items():
            rx, rz = _ocean_rot_xz(x, z, rot)
            if isinstance(m, tuple) and len(m) == 2 \
                    and isinstance(m[1], str):
                m = (m[0], _bs.shape_rotation(m[1], rot))
            vox[(px + rx - ax, py + y - 90, pz + rz - az)] = m
    chest_offs: set = set()
    for c in comp.chests:
        if c.pos3 is None:
            continue
        vox[(c.pos3[0] - ax, c.pos3[1] - 90, c.pos3[2] - az)] = "chest"
        chest_offs.add((c.pos[0] - ax, c.pos[1] - az))
    return vox, chest_offs


# ---------------------------------------------------------------------------
# ancient_city（远古城市）
# ---------------------------------------------------------------------------

_AC_RAW_CACHE: dict = {}


def compose_ancient_city(world_seed: int, block_x: int, block_z: int,
                         version_key: str = "1.21") -> Composition:
    """远古城市：jigsaw 拼装（含 anchor 重定位）+ 全箱子战利品预测。

    起点流（structure_map._jigsaw_variant ancient_city 分支同流）：
        y = -27（start_height absolute 零消耗）
        rotation = nextInt(4)
        start    = nextInt(3)（city_center 池三件等权，拼装引擎内消耗）
    拼装由 assemble_ancient_city 复刻（fhp.a + fgs.a，主流额外含
    起点模板 jigsaw 标记洗牌 4 次 + city_anchor 重定位，详见其
    模块注释）。

    容器口径（probe_containers/probe_tables 实证，58 模板全扫）：
        - 15 个 minecraft:chest（无 barrel，ice_box 也是 chest）；
          14 个 NBT 带 LootTable（13 chests/ancient_city +
          1 chests/ancient_city_ice_box）进预测；city_center_2 的
          1 个无字段（游戏内空箱，不消耗流）。
        - LootTableSeed 每区块 population 流 = get_population_seed
          + decorator(0) + 10000*step(7)（salt=(7,0)，
          cl_salts_1_21_5.txt L33），同区块按放置序（piece 序 ×
          块内 (Y,X,Z)）连抽 nextLong。
    """
    min_bx = block_x & ~15
    min_bz = block_z & ~15
    # 起点流：y 零消耗 → rotation（structure_map._jigsaw_variant 同序；
    # 其内部 nextInt(3) 为包围盒推算消耗，不影响 rotation 值）
    state = structure_map.chunk_generate_rnd(world_seed, block_x >> 4,
                                             block_z >> 4)
    rotation, state = mc_random.next_int(state, 4)

    from Utils.StructurePreviewer import ancient_city_assembly as aca
    res = aca.assemble_ancient_city(world_seed, min_bx >> 4, min_bz >> 4)
    step, decorator = loot_rng.salt_configs_for_version(
        version_key)["ancient_city"]

    # ---- 容器收集：有 LootTable 字段的 chest，按放置序 ----
    records: list[tuple[tuple[int, int, int], str, int]] = []
    by_chunk: dict[tuple[int, int], list] = {}
    for pi, jp in enumerate(res.pieces):
        for wpos, table, _si in _piece_ac_containers_world(jp):
            records.append((wpos, table, pi))
            by_chunk.setdefault((wpos[0] >> 4, wpos[2] >> 4),
                                []).append(len(records) - 1)

    start_name = res.pieces[0].template.key
    piece = Piece(start_name, (min_bx, 64, min_bz), [])
    for ckey in sorted(by_chunk):
        pcx, pcz = ckey
        rng = loot_rng.XoroshiroJava(
            loot_rng.get_population_seed(world_seed, pcx * 16, pcz * 16)
            + decorator + 10000 * step)
        for idx in by_chunk[ckey]:
            wpos, table, _pi = records[idx]
            seed = rng.next_long()
            piece.chests.append(Chest((wpos[0], wpos[2]),
                                      table[len("minecraft:"):], seed,
                                      pos3=wpos))

    # 起点件底面世界 y（显示基准；anchor 重定位 + dy 后真实值）
    start_y0 = res.pieces[0].box.y0
    return Composition("ancient_city", "ancient_city/" + start_name,
                       rotation, False, (min_bx, min_bz), [piece],
                       {"start": res.start_index, "world_seed": world_seed,
                        "start_y": start_y0,
                        "n_pieces": len(res.pieces),
                        "n_chests": len(piece.chests)})


def _piece_ac_containers_world(piece):
    """jigsaw piece 内带 LootTable 的容器 -> 世界坐标（世界 (Y,X,Z) 序）。

    ancient_city 模板 NBT 直扫（_AC_CONTAINERS_CACHE 缓存）；容器
    = chest（全结构无 barrel，ice_box 也是 chest），仅模板 NBT 有
    LootTable 字段的进列表（city_center_2 空箱不消耗流）；旋转用
    jigsaw_assembly.rot_piece_pos（与渲染体素同一变换）。list
    piece（ice_box_1 单子件 / camp 三子件）逐子模板展开，子序
    先于块内排序（Java 依序 placeInWorld）；list 子模板无处理器
    降解（ice_box processors 为空 dict，且 chest 不在
    #ancient_city_replaceable，永不蚀空）。
    返回 [(世界 (x,y,z), "minecraft:chests/…", 子序)]。
    """
    from Utils.SeedReverser.jigsaw_assembly import rot_piece_pos
    subs = piece.sub_templates or [piece.template.key]
    sx = piece.template.size_x
    sz = piece.template.size_z
    px, py, pz = piece.piece_pos
    out = []
    for si, sub in enumerate(subs):
        cached = _AC_CONTAINERS_CACHE.get(sub)
        if cached is None:
            cached = _ac_template_containers(sub)
        for (lx, ly, lz), table in cached:
            rx, ry, rz = rot_piece_pos(piece.rot, (lx, ly, lz), sx, sz)
            out.append(((px + rx, py + ry, pz + rz), table, si))
    out.sort(key=lambda t: (t[2], t[0][1], t[0][0], t[0][2]))
    return out


_AC_CONTAINERS_CACHE: dict = {}


def _ac_template_containers(key: str) -> tuple:
    """ancient_city 模板 NBT 内带 LootTable 字段的 chest：
    (局部 (x,y,z), 表名) tuple；无字段不入列表。key 保留
    ancient_city/ 前缀，路径经 ancient_city_assembly.ASSET_DIR。"""
    cached = _AC_CONTAINERS_CACHE.get(key)
    if cached is not None:
        return cached
    from Utils.StructurePreviewer import ancient_city_assembly as aca
    path = aca.ASSET_DIR.joinpath("templates",
                                  Path(*key.split("/"))).with_suffix(".nbt")
    with open(path, "rb") as f:
        root = structure_models.parse_nbt(f.read())
    pr = root.get("palette")
    if pr is None:
        palettes = root.get("palettes")
        palette = (palettes[1][0][1] if palettes else []) \
            if isinstance(palettes, tuple) else []
    else:
        palette = pr[1]
    names = {i: structure_models._palette_entry_name(e)
             for i, e in enumerate(palette)}
    blocks = root.get("blocks")
    lst: list = []
    if blocks:
        for item in blocks[1]:
            pos_raw = item.get("pos")
            pos = pos_raw[1] if isinstance(pos_raw, tuple) else pos_raw
            if not isinstance(pos, list) or len(pos) != 3:
                continue
            st = item.get("state", 0)
            if not (0 <= st < len(names)):
                continue
            if names[st] not in ("minecraft:chest",
                                 "minecraft:trapped_chest"):
                continue
            nbt = item.get("nbt")
            table = None
            if nbt is not None:
                payload = nbt[1] if isinstance(nbt, tuple) else nbt
                lt = payload.get("LootTable") if hasattr(payload, "get") \
                    else None
                if lt is not None:
                    table = str(lt[1] if isinstance(lt, tuple) else lt)
            if table is None:
                continue
            lst.append(((int(pos[0]), int(pos[1]), int(pos[2])), table))
    out = tuple(lst)
    _AC_CONTAINERS_CACHE[key] = out
    return out


def _ancient_city_raw_blocks(key: str) -> dict:
    """ancient_city 模板 NBT -> 原始方块名体素 dict（缓存，trial 同范式）。

    key 保留 ancient_city/ 前缀（资产目录同构）；palette 条目
    Properties（台阶/楼梯朝向等）经 block_shapes.shape_from_palette
    转形状码，供 _ROT_IDX 旋转同步朝向。
    """
    cached = _AC_RAW_CACHE.get(key)
    if cached is not None:
        return cached
    from Utils.SeedReverser import block_shapes as _bs
    from Utils.StructurePreviewer import ancient_city_assembly as aca
    path = aca.ASSET_DIR.joinpath("templates",
                                  Path(*key.split("/"))).with_suffix(".nbt")
    with open(path, "rb") as f:
        root = structure_models.parse_nbt(f.read())
    pr = root.get("palette")
    if pr is None:
        palettes = root.get("palettes")
        palette = (palettes[1][0][1] if palettes else []) \
            if isinstance(palettes, tuple) else []
    else:
        palette = pr[1]
    names = []
    for entry in palette:
        name = structure_models._palette_entry_name(entry)
        props = structure_models._palette_entry_props(entry)
        shape = _bs.shape_from_palette(name, props)
        names.append((name, shape))
    out = {}
    blocks = root.get("blocks")
    if blocks:
        for item in blocks[1]:
            pos_raw = item.get("pos")
            pos = pos_raw[1] if isinstance(pos_raw, tuple) else pos_raw
            if not isinstance(pos, list) or len(pos) != 3:
                continue
            st = item.get("state", 0)
            if not (0 <= st < len(names)):
                continue
            nm, shp = names[st]
            out[(int(pos[0]), int(pos[1]), int(pos[2]))] = (nm, shp)
    _AC_RAW_CACHE[key] = out
    return out


def _ancient_city_jigsaw_voxels(comp: Composition) -> tuple[dict, set]:
    """Ancient City 显示：逐 seed 精确 jigsaw 拼装体素（真实结构布局）。

    assemble_ancient_city 生成 piece 序列（与游戏同一 RNG 流，含
    city_anchor 重定位）；逐 piece 加载模板原始方块名，经
    rot_piece_pos 局部旋转（形状码朝向同步 shape_rotation）、
    piece_pos 平移到世界坐标，逐方块
    apply_ancient_city_degradation（block_rot 0.95 + rule 链，每
    方块独立 Mth.getSeed 随机源，variant 按模板 key 定案）。材质
    映射 _map_block（深板岩系/幽匿系已核）。模型口径同 trial：
    (x,z) = 世界 - anchor、y = 世界 - 起点件底面（extra["start_y"]）。

    方块覆盖顺序 = pieces 列表顺序（Java postProcess 同序，后写
    覆盖先写）。箱子标注走 pos3 3D exact 匹配（见
    compose_display_model ancient_city 分支），chest_offs 仅为
    接口形状。
    """
    from Utils.SeedReverser import block_shapes as _bs
    from Utils.SeedReverser.jigsaw_assembly import rot_piece_pos
    from Utils.StructurePreviewer import ancient_city_assembly as aca
    res = aca.assemble_ancient_city(comp.extra["world_seed"],
                                    comp.anchor[0] >> 4,
                                    comp.anchor[1] >> 4)
    ax, az = comp.anchor
    y0 = comp.extra["start_y"]
    vox: dict = {}
    chest_offs: set = set()
    for p in res.pieces:
        subs = p.sub_templates or [p.template.key]
        sx = p.template.size_x
        sz = p.template.size_z
        px, py, pz = p.piece_pos
        for sub in subs:
            raw = _ancient_city_raw_blocks(sub)
            if not raw:
                continue
            variant = aca.degradation_variant(sub)
            for (x, y, z), val in raw.items():
                nm, shp = val if isinstance(val, tuple) else (val, None)
                if nm == "minecraft:jigsaw":
                    continue          # jigsaw/DATA 占位不渲染
                rx, ry, rz = rot_piece_pos(p.rot, (x, y, z), sx, sz)
                wx, wy, wz = px + rx, py + ry, pz + rz
                state = aca.apply_ancient_city_degradation(
                    nm, wx, wy, wz, variant)
                if state is None:
                    continue          # block_rot 蚀空
                mat = structure_models._map_block(state, "half")
                if mat is None:
                    continue
                if shp is not None:
                    shp = _bs.shape_rotation(shp, _ROT_IDX[p.rot])
                base = mat[len("halfheight:"):] \
                    if mat.startswith("halfheight:") else mat
                if shp is None and mat.startswith("halfheight:"):
                    shp = _bs.SHAPE_SLAB_BOT
                vox[(wx - ax, wy - y0, wz - az)] = \
                    (base, shp) if shp is not None else base
    for c in comp.chests:
        chest_offs.add((c.pos[0] - comp.anchor[0],
                        c.pos[1] - comp.anchor[1]))
    return vox, chest_offs


# ---------------------------------------------------------------------------
# village（村庄，1.14+；jigsaw/template_pool 机制）
# ---------------------------------------------------------------------------

_VILLAGE_RAW_CACHE: dict = {}
_VILLAGE_CONTAINERS_CACHE: dict = {}

# 模板局部朝向属性 -> 世界朝向（Block.rotate 语义，顺时针 rot 次）：
# facing 循环 n->e->s->w、axis x<->z、连接布尔 north->east->south->
# west（村庄处理器 blockstate_match 的 glass_pane 连接态匹配用）。
_FACE_CYCLE = ("n", "e", "s", "w")


def _rotate_props(name: str, props: dict, rot_idx: int) -> dict:
    """模板 palette props -> 按放置旋转 rot_idx（0..3 顺时针）世界化。

    处理器在世界坐标作用（placeInWorld 先 rotate palette state 再进
    处理器链），blockstate_match 规则匹配的是旋转后 props。仅处理
    结构处理器涉及的属性类：facing/axis/水平连接布尔/rotation_*
    环值；其余属性透传。"""
    if not props or rot_idx == 0:
        return props
    out = {}
    for k, v in props.items():
        if k == "facing":
            if v in _FACE_CYCLE:
                out[k] = _FACE_CYCLE[(_FACE_CYCLE.index(v) + rot_idx) % 4]
            elif v in ("up", "down"):
                out[k] = v
            else:
                out[k] = v
        elif k == "axis":
            out[k] = v if rot_idx % 2 == 0 else ("z" if v == "x" else "x")
        elif k in ("north", "east", "south", "west"):
            # 水平连接布尔（pane/fence/stairs 边）环转 rot_idx 位
            order = ["north", "east", "south", "west"]
            out[order[(order.index(k) + rot_idx) % 4]] = v
        elif k == "rotation" and v.isdigit():
            # 0..15 环值（旗帜/告示牌），顺时针 +4/格
            out[k] = str((int(v) + 4 * rot_idx) % 16)
        else:
            out[k] = v
    return out


def _village_raw_blocks(key: str) -> dict:
    """村庄模板 NBT -> {(x,y,z): (name, props_dict)} 原始体素（缓存）。

    key 保留 village/ 前缀（templates/ 目录同构层级）。props 原样
    保留（zombie 处理器的 blockstate_match 需完整连接态比较；
    世界化旋转在 _village_jigsaw_voxels 内做）。"""
    cached = _VILLAGE_RAW_CACHE.get(key)
    if cached is not None:
        return cached
    from Utils.StructurePreviewer import village_assembly as va
    path = va.ASSET_DIR.joinpath("templates",
                                 Path(*key.split("/"))).with_suffix(".nbt")
    root = structure_models.parse_nbt(path.read_bytes())
    pr = root.get("palette")
    if pr is None:
        palettes = root.get("palettes")
        palette = (palettes[1][0][1] if palettes else []) \
            if isinstance(palettes, tuple) else []
    else:
        palette = pr[1]
    entries = []
    for entry in palette:
        nm = structure_models._palette_entry_name(entry)
        pr2 = structure_models._palette_entry_props(entry)
        entries.append((nm, pr2))
    out = {}
    blocks = root.get("blocks")
    if blocks:
        for item in blocks[1]:
            pos_raw = item.get("pos")
            pos = pos_raw[1] if isinstance(pos_raw, tuple) else pos_raw
            if not isinstance(pos, list) or len(pos) != 3:
                continue
            st = item.get("state", 0)
            if not (0 <= st < len(entries)):
                continue
            nm, props = entries[st]
            if nm == "minecraft:jigsaw":
                continue          # jigsaw/DATA 占位不渲染
            out[(int(pos[0]), int(pos[1]), int(pos[2]))] = (nm, dict(props))
    _VILLAGE_RAW_CACHE[key] = out
    return out


def _village_template_containers(key: str) -> tuple:
    """村庄模板 NBT 内带 LootTable 字段的容器：(局部 (x,y,z), 表名)。

    chest/trapped_chest/barrel 同扫（RandomizableContainer 同路）；
    无 LootTable 字段（村庄空桶等装饰容器）不入列表、不消耗流。"""
    cached = _VILLAGE_CONTAINERS_CACHE.get(key)
    if cached is not None:
        return cached
    from Utils.StructurePreviewer import village_assembly as va
    path = va.ASSET_DIR.joinpath("templates",
                                 Path(*key.split("/"))).with_suffix(".nbt")
    root = structure_models.parse_nbt(path.read_bytes())
    pr = root.get("palette")
    if pr is None:
        palettes = root.get("palettes")
        palette = (palettes[1][0][1] if palettes else []) \
            if isinstance(palettes, tuple) else []
    else:
        palette = pr[1]
    names = {i: structure_models._palette_entry_name(e)
             for i, e in enumerate(palette)}
    blocks = root.get("blocks")
    lst: list = []
    if blocks:
        for item in blocks[1]:
            pos_raw = item.get("pos")
            pos = pos_raw[1] if isinstance(pos_raw, tuple) else pos_raw
            if not isinstance(pos, list) or len(pos) != 3:
                continue
            st = item.get("state", 0)
            if not (0 <= st < len(names)):
                continue
            nm = names[st]
            if nm not in ("minecraft:chest", "minecraft:trapped_chest",
                          "minecraft:barrel"):
                continue
            nbt = item.get("nbt")
            table = None
            if nbt is not None:
                payload = nbt[1] if isinstance(nbt, tuple) else nbt
                lt = payload.get("LootTable") if hasattr(payload, "get") \
                    else None
                if lt is not None:
                    table = str(lt[1] if isinstance(lt, tuple) else lt)
            if table is None:
                continue
            lst.append(((int(pos[0]), int(pos[1]), int(pos[2])), table))
    out = tuple(lst)
    _VILLAGE_CONTAINERS_CACHE[key] = out
    return out


def compose_village(world_seed: int, block_x: int, block_z: int,
                    biome_id: int = -1, version_key: str = "1.21"
                    ) -> Composition:
    """村庄：jigsaw 拼装（五变体 + 起点池僵尸元素）+ 全箱子战利品。

    变体由锚点群系决定（structure_map._check_village 命中的群系 id；
    meadow 按 plains）。起点流（_village_variant 同流）：
        rotation = nextInt(4)
        start pick = nextInt(总权重)（plains 204：4 普通 x50 + 4 僵尸
        x1；僵尸起点 street 标记指向 <variant>/zombie/streets 池 ->
        完整僵尸链）
    拼装由 assemble_village 复刻（fhp.a + fgs.a，size=6 /
    max_dist=80 / start_y=地表平坦基准 63 / expansion_hack=true）。

    容器口径（483 模板扫描实证）：62 chest 全带 LootTable（16 张
    chests/village/* 表）；18 barrel 全无字段（空桶不消耗流）。
    LootTableSeed 每区块 population 流 = get_population_seed +
    decorator + 10000*step（salt=(4, 22..26) 按变体），同区块按
    放置序（piece 序 x 块内 (Y,X,Z)）连抽 nextLong。
    """
    from Utils.StructurePreviewer import village_assembly as va
    variant = va.variant_from_biome(biome_id)
    min_bx = block_x & ~15
    min_bz = block_z & ~15
    # 起点流：rotation（structure_map._village_variant 同序）
    state = structure_map.chunk_generate_rnd(world_seed, block_x >> 4,
                                             block_z >> 4)
    rotation, state = mc_random.next_int(state, 4)

    res = va.assemble_village(world_seed, min_bx >> 4, min_bz >> 4, variant)
    step, decorator = loot_rng.salt_configs_for_version(
        version_key)[f"village_{variant}"]

    # ---- 容器收集：有 LootTable 字段的容器，按放置序 ----
    records: list[tuple[tuple[int, int, int], str, int]] = []
    by_chunk: dict[tuple[int, int], list] = {}
    for pi, jp in enumerate(res.pieces):
        for wpos, table, _si in _village_piece_containers_world(jp):
            records.append((wpos, table, pi))
            by_chunk.setdefault((wpos[0] >> 4, wpos[2] >> 4),
                                []).append(len(records) - 1)

    start_name = res.pieces[0].template.key
    piece = Piece(start_name, (min_bx, 63, min_bz), [])
    for ckey in sorted(by_chunk):
        pcx, pcz = ckey
        rng = loot_rng.XoroshiroJava(
            loot_rng.get_population_seed(world_seed, pcx * 16, pcz * 16)
            + decorator + 10000 * step)
        for idx in by_chunk[ckey]:
            wpos, table, _pi = records[idx]
            seed = rng.next_long()
            piece.chests.append(Chest((wpos[0], wpos[2]),
                                      table[len("minecraft:"):], seed,
                                      pos3=wpos))

    start_y0 = res.pieces[0].box.y0
    is_zombie = "/zombie/" in start_name
    return Composition(
        "village", f"village/{variant}" + ("/zombie" if is_zombie else ""),
        rotation, False, (min_bx, min_bz), [piece],
        {"variant": variant, "zombie": is_zombie,
         "start": res.start_index, "world_seed": world_seed,
         "start_y": start_y0, "n_pieces": len(res.pieces),
         "n_chests": len(piece.chests)})


def _village_piece_containers_world(piece):
    """jigsaw piece 内带 LootTable 的容器 -> 世界坐标（世界 (Y,X,Z) 序）。

    旋转用 jigsaw_assembly.rot_piece_pos（与渲染体素同一变换）；
    全部池元素为 single/legacy（无 list），无处理器蚀箱（chest 不在
    村庄处理器规则输入集，永不蚀空）。返回 [(世界 (x,y,z),
    "minecraft:chests/village/…", 子序)]。"""
    from Utils.SeedReverser.jigsaw_assembly import rot_piece_pos
    sx = piece.template.size_x
    sz = piece.template.size_z
    px, py, pz = piece.piece_pos
    out = []
    for (lx, ly, lz), table in _village_template_containers(
            piece.template.key):
        rx, ry, rz = rot_piece_pos(piece.rot, (lx, ly, lz), sx, sz)
        out.append(((px + rx, py + ry, pz + rz), table, 0))
    out.sort(key=lambda t: (t[0][1], t[0][0], t[0][2]))
    return out


def _village_jigsaw_voxels(comp: Composition) -> tuple[dict, set]:
    """村庄显示：逐 seed 精确 jigsaw 拼装体素（真实结构布局）。

    assemble_village 生成 piece 序列（与游戏同一 RNG 流）；逐 piece
    加载模板原始方块（name + props），props 先按放置旋转世界化
    （处理器在世界坐标作用），逐方块 apply_processor（mossify/
    farm/street/zombie RuleProcessor，每方块独立 Mth.getSeed 流），
    材质映射 _map_block。模型口径同 ancient_city：(x,z) = 世界 -
    anchor、y = 世界 - 起点件底面（extra["start_y"]）。

    方块覆盖顺序 = pieces 列表顺序（Java postProcess 同序，后写
    覆盖先写）。箱子标注走 pos3 3D exact 匹配。
    """
    from Utils.SeedReverser.jigsaw_assembly import rot_piece_pos
    from Utils.StructurePreviewer import village_assembly as va
    res = va.assemble_village(comp.extra["world_seed"],
                              comp.anchor[0] >> 4,
                              comp.anchor[1] >> 4,
                              comp.extra["variant"])
    ax, az = comp.anchor
    y0 = comp.extra["start_y"]
    vox: dict = {}
    chest_offs: set = set()
    for p in res.pieces:
        sx = p.template.size_x
        sz = p.template.size_z
        px, py, pz = p.piece_pos
        rot_idx = _ROT_IDX[p.rot]
        pid = p.processor
        for (x, y, z), (nm, props) in _village_raw_blocks(
                p.template.key).items():
            rx, ry, rz = rot_piece_pos(p.rot, (x, y, z), sx, sz)
            wx, wy, wz = px + rx, py + ry, pz + rz
            wprops = _rotate_props(nm, props, rot_idx)
            state = va.apply_processor(pid, nm, wprops, wx, wy, wz)
            if state is None:
                continue          # 处理器蚀空（air）
            nm2, props2 = state
            if nm2 != nm:
                # 处理器换方块（mossy/cobweb/作物替换等）：世界 props
                # 重求形状（pane 连接态等方向属性已在 wprops 内）
                shp = bs.shape_from_palette(nm2, props2)
            else:
                shp = bs.shape_from_palette(nm, props)
                if shp is not None:
                    shp = bs.shape_rotation(shp, rot_idx)
            # 作物动态 age stage 优先（wheat/carrots/potatoes/beetroots
            # 官方 blockstates 映射；zombie 处理器输出的 carrots 等经
            # 此渲染），非作物回退静态映射
            mat = structure_models.crop_stage_mat(nm2, props2) \
                or structure_models._map_block(nm2, "half")
            if mat is None:
                continue
            base = mat[len("halfheight:"):] \
                if mat.startswith("halfheight:") else mat
            if shp is None and mat.startswith("halfheight:"):
                shp = bs.SHAPE_SLAB_BOT
            vox[(wx - ax, wy - y0, wz - az)] = \
                (base, shp) if shp is not None else base
    for c in comp.chests:
        chest_offs.add((c.pos[0] - comp.anchor[0],
                        c.pos[1] - comp.anchor[1]))
    return vox, chest_offs


# ---------------------------------------------------------------------------
# 公共入口 + 显示模型
# ---------------------------------------------------------------------------

def compose(struct_key: str, world_seed: int, block_x: int, block_z: int,
            biome_id: int = -1, version_key: str = "1.21") -> Composition:
    """结构键 -> 构造组合结果（igloo / shipwreck / nether_fortress /
    bastion_remnant / end_city）。"""
    if struct_key == "igloo":
        return compose_igloo(world_seed, block_x, block_z, version_key)
    if struct_key == "shipwreck":
        return compose_shipwreck(world_seed, block_x, block_z, biome_id,
                                 version_key)
    if struct_key == "nether_fortress":
        return compose_nether_fortress(world_seed, block_x, block_z,
                                       version_key)
    if struct_key == "bastion_remnant":
        return compose_bastion_remnant(world_seed, block_x, block_z,
                                       version_key)
    if struct_key == "end_city":
        return compose_end_city(world_seed, block_x, block_z, version_key)
    if struct_key == "trial_chambers":
        return compose_trial_chambers(world_seed, block_x, block_z,
                                      version_key)
    if struct_key == "pillager_outpost":
        return compose_pillager_outpost(world_seed, block_x, block_z,
                                        version_key)
    if struct_key == "stronghold":
        return compose_stronghold(world_seed, block_x, block_z,
                                  version_key)
    if struct_key == "woodland_mansion":
        return compose_mansion(world_seed, block_x, block_z,
                               version_key)
    if struct_key == "ocean_ruin":
        return compose_ocean_ruin(world_seed, block_x, block_z,
                                  biome_id, version_key)
    if struct_key == "ancient_city":
        return compose_ancient_city(world_seed, block_x, block_z,
                                    version_key)
    if struct_key == "village":
        return compose_village(world_seed, block_x, block_z, biome_id,
                               version_key)
    raise ValueError(f"composition 未支持的结构键：{struct_key}")


@lru_cache(maxsize=32)
def _load_template_voxels(fname: str) -> dict:
    """模板 NBT -> 体素 dict（lru 缓存：返回值只读遍历/复制，不改内部态）。

    大视野批量 compose_display_model 时同一模板只解析一次。
    """
    return structure_models._voxels_from_template_file(
        os.path.join(structure_models.TEMPLATE_DIR, fname))


def _fortress_solid_voxels(comp: Composition) -> tuple[dict, set]:
    """Fortress 显示：逐 piece 精确方块布局（fortress_pieces 转写）。

    按 NetherFortressPieces.java postProcess 逐段转写展开（坐标映射
    /朝向变换/箱刷怪笼岩浆等特殊块全部字节码级核对），遍历顺序 =
    accepted 顺序 = Java postProcess 顺序（后写覆盖先写）。模型
    (x,z) = 世界 - anchor、y = 世界 - 64。
    箱子标注：返回有箱拐角 piece 的 (x,z) 集合（chest_offs），供
    compose_display_model 抬高/近邻匹配兜底（xp 箱子坐标与 Java
    布局坐标存在已知偏差，exact miss 时近邻找 chest 体素）。
    """
    from . import fortress_pieces
    vox = fortress_pieces.build_fortress_voxels(comp)
    chest_offs: set = set()
    for p in comp.pieces:
        if p.chests:
            for c in p.chests:
                chest_offs.add((c.pos[0] - comp.anchor[0],
                                c.pos[1] - comp.anchor[1]))
    return vox, chest_offs


# bastion 模板原始方块名体素缓存（key -> {(x,y,z): 方块名}）。
# 降解须在材质映射前按世界坐标判定，故绕过 _MAT_MAP 直取 NBT Name。
_BASTION_RAW_CACHE: dict = {}

# jigsaw 旋转名 -> block_shapes.shape_rotation 的 0-3 索引
# （与 cubiomes/cubiomes 注释同序：0=NONE 1=CW90 2=CW180 3=CCW90）
_ROT_IDX = {"NONE": 0, "CLOCKWISE_90": 1, "CLOCKWISE_180": 2,
            "COUNTERCLOCKWISE_90": 3}


def _trial_raw_blocks(key: str) -> dict:
    """trial 模板 NBT -> 原始方块名体素 dict（缓存）。

    key 同 trial_assembly 约定（剥 trial_chambers/ 前缀，映射
    assets/SeedReverser/trial_chambers/templates/<key>.nbt）。
    palette 条目 Name -> 名字串；Properties（台阶/楼梯朝向等）经
    block_shapes.shape_from_props 转形状码，供 _ROT_IDX 旋转同步朝向。
    """
    cached = _TRIAL_RAW_CACHE.get(key)
    if cached is not None:
        return cached
    from Utils.SeedReverser import block_shapes as _bs
    from Utils.StructurePreviewer import trial_assembly as ta
    path = ta.ASSET_DIR.joinpath("templates",
                                 *ta._split_key(key)).with_suffix(".nbt")
    with open(path, "rb") as f:
        root = structure_models.parse_nbt(f.read())
    pr = root.get("palette")
    if pr is None:
        palettes = root.get("palettes")
        palette = (palettes[1][0][1] if palettes else []) \
            if isinstance(palettes, tuple) else []
    else:
        palette = pr[1]
    names = []
    for entry in palette:
        name = structure_models._palette_entry_name(entry)
        props = structure_models._palette_entry_props(entry)
        shape = _bs.shape_from_palette(name, props)
        names.append((name, shape))
    out = {}
    blocks = root.get("blocks")
    if blocks:
        for item in blocks[1]:
            pos_raw = item.get("pos")
            pos = pos_raw[1] if isinstance(pos_raw, tuple) else pos_raw
            if not isinstance(pos, list) or len(pos) != 3:
                continue
            st = item.get("state", 0)
            if not (0 <= st < len(names)):
                continue
            nm, shp = names[st]
            out[(pos[0], pos[1], pos[2])] = (nm, shp) if shp else nm
    _TRIAL_RAW_CACHE[key] = out
    return out


def _bastion_raw_blocks(key: str) -> dict:
    """jigsaw 模板 NBT -> 原始方块名体素 dict（缓存）。

    key 同 jigsaw_assembly 约定（"bastion/xxx"，剥前缀映射
    templates/xxx.nbt）。palette 条目 Name -> 名字串；Properties
    （台阶/楼梯朝向等）经 block_shapes.shape_from_props 转形状码，
    供后续 _rotate_voxels 同步旋转朝向。
    """
    cached = _BASTION_RAW_CACHE.get(key)
    if cached is not None:
        return cached
    from Utils.SeedReverser import block_shapes as _bs
    tpl_path = os.path.join(structure_models.TEX_DIR, "..", "..",
                            "bastion", "templates",
                            *key.split("/")[1:]) + ".nbt"
    with open(tpl_path, "rb") as f:
        root = structure_models.parse_nbt(f.read())
    pr = root.get("palette")
    if pr is None:
        palettes = root.get("palettes")
        palette = (palettes[1][0][1] if palettes else []) \
            if isinstance(palettes, tuple) else []
    else:
        palette = pr[1]
    names = []
    for entry in palette:
        name = structure_models._palette_entry_name(entry)
        props = structure_models._palette_entry_props(entry)
        shape = _bs.shape_from_palette(name, props)
        names.append((name, shape))
    out = {}
    blocks = root.get("blocks")
    if blocks:
        for item in blocks[1]:
            pos_raw = item.get("pos")
            pos = pos_raw[1] if isinstance(pos_raw, tuple) else pos_raw
            if not isinstance(pos, list) or len(pos) != 3:
                continue
            st = item.get("state", 0)
            if not (0 <= st < len(names)):
                continue
            nm, shp = names[st]
            out[(pos[0], pos[1], pos[2])] = (nm, shp) if shp else nm
    _BASTION_RAW_CACHE[key] = out
    return out


def _bastion_jigsaw_voxels(comp: Composition) -> tuple[dict, set]:
    """Bastion 显示：逐 seed 精确 jigsaw 拼装体素（真实结构布局）。

    assemble_bastion 生成 piece 序列（与游戏同一 RNG 流，已对拍
    structure_map 变种流 6/6 一致）；逐 piece 加载模板原始方块名，
    经 jigsaw_assembly.rot_piece_pos 做局部旋转（形状码朝向同步
    shape_rotation）、piece_pos 平移到世界坐标，再逐方块
    apply_degradation（bastion_generic_degradation，每方块独立
    Mth.getSeed 随机源）。材质映射沿用 structure_models._MAT_MAP
    （黑石系→stone 系风格化映射）。最终模型口径同 fortress：
    (x,z) = 世界 - anchor、y = 世界 - 64。

    方块覆盖顺序 = pieces 列表顺序（Java postProcess 同序，后写
    覆盖先写）。箱子标注沿用示意版口径：(x,z) 并入返回集合，
    compose_display_model 抬到所在柱顶层。
    """
    from Utils.SeedReverser import block_shapes as _bs
    from Utils.SeedReverser.jigsaw_assembly import (
        apply_degradation, assemble_bastion, rot_piece_pos)
    res = assemble_bastion(comp.extra["world_seed"],
                           comp.anchor[0] >> 4, comp.anchor[1] >> 4)
    ax, az = comp.anchor
    vox: dict = {}
    chest_offs: set = set()
    for p in res.pieces:
        raw = _bastion_raw_blocks(p.template.key)
        if not raw:
            continue
        sx = p.template.size_x
        sz = p.template.size_z
        px, py, pz = p.piece_pos
        for (x, y, z), val in raw.items():
            nm, shp = val if isinstance(val, tuple) else (val, None)
            rx, ry, rz = rot_piece_pos(p.rot, (x, y, z), sx, sz)
            wx, wy, wz = px + rx, py + ry, pz + rz
            state = apply_degradation(nm, wx, wy, wz)
            mat = structure_models._map_block(state, "half")
            if mat is None:
                continue
            if shp is not None:
                shp = _bs.shape_rotation(shp, _ROT_IDX[p.rot])
            base = mat[len("halfheight:"):] \
                if mat.startswith("halfheight:") else mat
            if shp is None and mat.startswith("halfheight:"):
                # 无 Properties 形状的旧前缀材质按底半格
                # （与 _voxels_from_template_file 同语义）
                shp = _bs.SHAPE_SLAB_BOT
            vox[(wx - ax, wy - 64, wz - az)] = \
                (base, shp) if shp is not None else base
    for c in comp.chests:
        chest_offs.add((c.pos[0] - comp.anchor[0],
                        c.pos[1] - comp.anchor[1]))
    return vox, chest_offs


def _trial_jigsaw_voxels(comp: Composition) -> tuple[dict, set]:
    """Trial 显示：逐 seed 精确 jigsaw 拼装体素（真实结构布局）。

    assemble_trial_chambers 生成 piece 序列（与游戏同一 RNG 流，含
    pool_aliases 解析与铜灯降解）；逐 piece 加载 trial 模板原始方块
    名，经 rot_piece_pos 做局部旋转（形状码朝向同步 shape_rotation）、
    piece_pos 平移到世界坐标，逐方块 apply_trial_degradation（仅
    waxed_copper_bulb 消耗方块随机流，其它方块零消耗），材质映射
    _map_block（凝灰岩系/铜灯系/vault→stone 均已核）。模型口径：
    (x,z) = 世界 - anchor、y = 世界 - start_y（起始件底面，模型
    y >= 0 从起点件底起算）。

    方块覆盖顺序 = pieces 列表顺序（Java postProcess 同序，后写
    覆盖先写）。箱子标注走 pos3 3D exact 匹配（见
    compose_display_model trial 分支），chest_offs 仅为接口形状。
    """
    from Utils.SeedReverser import block_shapes as _bs
    from Utils.SeedReverser.jigsaw_assembly import rot_piece_pos
    from Utils.StructurePreviewer import trial_assembly as ta
    res = ta.assemble_trial_chambers(comp.extra["world_seed"],
                                     comp.anchor[0] >> 4,
                                     comp.anchor[1] >> 4,
                                     comp.extra["start_y"])
    ax, az = comp.anchor
    y0 = comp.extra["start_y"]
    vox: dict = {}
    chest_offs: set = set()
    for p in res.pieces:
        raw = _trial_raw_blocks(p.template.key)
        if not raw:
            continue
        sx = p.template.size_x
        sz = p.template.size_z
        px, py, pz = p.piece_pos
        for (x, y, z), val in raw.items():
            nm, shp = val if isinstance(val, tuple) else (val, None)
            rx, ry, rz = rot_piece_pos(p.rot, (x, y, z), sx, sz)
            wx, wy, wz = px + rx, py + ry, pz + rz
            state = ta.apply_trial_degradation(nm, wx, wy, wz)
            mat = structure_models._map_block(state, "half")
            if mat is None:
                continue
            if shp is not None:
                shp = _bs.shape_rotation(shp, _ROT_IDX[p.rot])
            base = mat[len("halfheight:"):] \
                if mat.startswith("halfheight:") else mat
            if shp is None and mat.startswith("halfheight:"):
                shp = _bs.SHAPE_SLAB_BOT
            vox[(wx - ax, wy - y0, wz - az)] = \
                (base, shp) if shp is not None else base
    for c in comp.chests:
        chest_offs.add((c.pos[0] - comp.anchor[0],
                        c.pos[1] - comp.anchor[1]))
    return vox, chest_offs


def _outpost_raw_blocks(key: str) -> dict:
    """前哨站模板 NBT -> 原始方块名体素 dict（缓存，trial 同范式）。

    key 同 outpost_assembly 约定（剥 pillager_outpost/ 前缀）。
    """
    cached = _OUTPOST_RAW_CACHE.get(key)
    if cached is not None:
        return cached
    from Utils.SeedReverser import block_shapes as _bs
    from Utils.StructurePreviewer import outpost_assembly as oa
    path = oa.ASSET_DIR.joinpath("templates",
                                 *oa._split_key(key)).with_suffix(".nbt")
    with open(path, "rb") as f:
        root = structure_models.parse_nbt(f.read())
    pr = root.get("palette")
    if pr is None:
        palettes = root.get("palettes")
        palette = (palettes[1][0][1] if palettes else []) \
            if isinstance(palettes, tuple) else []
    else:
        palette = pr[1]
    names = []
    for entry in palette:
        name = structure_models._palette_entry_name(entry)
        props = structure_models._palette_entry_props(entry)
        shape = _bs.shape_from_palette(name, props)
        names.append((name, shape))
    out = {}
    blocks = root.get("blocks")
    if blocks:
        for item in blocks[1]:
            pos_raw = item.get("pos")
            pos = pos_raw[1] if isinstance(pos_raw, tuple) else pos_raw
            if not isinstance(pos, list) or len(pos) != 3:
                continue
            st = item.get("state", 0)
            if not (0 <= st < len(names)):
                continue
            nm, shp = names[st]
            out[(pos[0], pos[1], pos[2])] = (nm, shp) if shp else nm
    _OUTPOST_RAW_CACHE[key] = out
    return out


def _outpost_jigsaw_voxels(comp: Composition) -> tuple[dict, set]:
    """前哨站显示：逐 seed 精确 jigsaw 拼装体素（1.21.11 语义）。

    assemble_outpost 生成 piece 序列；逐 piece 展开子模板（list
    piece = watchtower + overgrown 依序放置，后写覆盖先写），方块
    经 rot_piece_pos 旋转 + piece_pos 平移到世界坐标。watchtower
    子元素无处理器；overgrown 子元素逐方块 apply_outpost_rot
    （95% 蚀空）。DATA 标记 jigsaw（Chest*/Banner*）不在 NBT 方块
    输出里渲染真实容器/旗帜——箱子体素由容器记录补写（ LootTable
    标注），旗帜按游戏语义渲染为白色旗帜（不挡视线）。

    模型口径同 fortress/bastion：(x,z) = 世界 - anchor、y = 世界 -
    64（起点底面平坦基准 63 → 模型 y 从 1 起，与地表贴合）。
    """
    from Utils.SeedReverser import block_shapes as _bs
    from Utils.SeedReverser.jigsaw_assembly import rot_piece_pos
    from Utils.StructurePreviewer import outpost_assembly as oa
    res = oa.assemble_outpost(comp.extra["world_seed"],
                              comp.anchor[0] >> 4, comp.anchor[1] >> 4)
    ax, az = comp.anchor
    vox: dict = {}
    chest_offs: set = set()
    for p in res.pieces:
        subs = p.sub_templates or [p.template.key]
        procs = p.sub_processors or [None] * len(subs)
        sx = p.template.size_x
        sz = p.template.size_z
        px, py, pz = p.piece_pos
        for si, sub in enumerate(subs):
            raw = _outpost_raw_blocks(sub)
            degrade = procs[si] == "outpost_rot"
            for (x, y, z), val in raw.items():
                nm, shp = val if isinstance(val, tuple) else (val, None)
                if nm == "minecraft:jigsaw":
                    continue        # DATA 标记：不渲染占位方块
                rx, ry, rz = rot_piece_pos(p.rot, (x, y, z), sx, sz)
                wx, wy, wz = px + rx, py + ry, pz + rz
                if degrade and oa.apply_outpost_rot(nm, wx, wy, wz) is None:
                    continue        # 被蚀：不写不渲染
                mat = structure_models._map_block(nm, "half")
                if mat is None:
                    continue
                if shp is not None:
                    shp = _bs.shape_rotation(shp, _ROT_IDX[p.rot])
                base = mat[len("halfheight:"):] \
                    if mat.startswith("halfheight:") else mat
                if shp is None and mat.startswith("halfheight:"):
                    shp = _bs.SHAPE_SLAB_BOT
                vox[(wx - ax, wy - 64, wz - az)] = \
                    (base, shp) if shp is not None else base
        # 容器记录补写箱子体素（DATA 标记不产出 NBT 方块）
        for wpos, _table, _si in _outpost_piece_containers_world(p):
            vox[(wpos[0] - ax, wpos[1] - 64, wpos[2] - az)] = "chest"
            chest_offs.add((wpos[0] - comp.anchor[0],
                            wpos[1] - comp.anchor[1]))
    return vox, chest_offs


def compose_display_model(comp: Composition) -> dict:
    """Composition -> 3D 视口显示模型（structure_3dview.set_model 格式）。

    返回 {"key", "variant", "voxels", "size", "mesh", "tex_keys",
          "chests", "anchor", "anchor_y", "comp"}。

    坐标约定：模型 (x, z) = 世界坐标 - anchor - start_off，其中
    start_off 为部件锚点相对结构锚点的偏移（igloo=(0,0)；shipwreck=
    startPos-旋转平移，与 finders.c pos=minBlock+startPos 同基）。
    y 向上，(0,0,0) = 部件锚点基准面（igloo top y=90 /
    shipwreck pos y=64）。

    箱子标注顺序与 comp.chests 一致（供箱子列表行高亮联动）：
    优先按 RNG 预测的模型 xz 匹配模板内 chest 方块（取其实际 y）；
    匹配不到（模板缺失/位置偏差）时按 RNG xz 落在基准面。
    同时回填每个 Chest.pos_model（模型内坐标），供 UI 直接消费。

    已知妥协：
    - igloo 模型不随 rotation/mirror 旋转（cubiomes 公式含隐藏的
      piece 内偏移，反解不唯一；RNG 坐标不受影响）；
    - fortress 为逐 piece AABB 转写（RNG 箱子近邻匹配）；bastion
      为逐 seed 真实 jigsaw 拼装，RNG 箱子与拼装几何同源精确重合
      （全箱子预测后 exact 匹配，无兜底）。
    """
    nether_chest_offs: set = set()
    if comp.struct_key == "igloo":
        voxels: dict = {}
        for fname, dx, dy, dz in _igloo_model_parts(comp):
            for (x, y, z), m in _load_template_voxels(fname).items():
                voxels[(x + dx, y + dy, z + dz)] = m
        start_off = (0, 0)
    elif comp.struct_key == "shipwreck":
        # 变种显示模板：shipwreck/<名> -> shipwreck__<名>.nbt（20 个
        # 变种一一就位）。按 compose_shipwreck 已定的 RNG 变种索引
        # （extra["sw_typ"]）取 _SW_INFO 名称后缀加载对应模板，
        # 尺寸/箱子相对坐标与 _SW_INFO 逐项吻合（材质映射已核）。
        # 旋转平移传名义尺寸：degraded 模板边缘方块被风化缺失，
        # shift 必须按完整格点算，否则模型/区块相位错位（见
        # _rotate_voxels docstring）。
        _name, _sx, _sy, _sz = _SW_INFO[comp.extra["sw_typ"]][:4]
        sw_suffix = _name.split("/", 1)[1]
        part = _load_template_voxels(f"shipwreck__{sw_suffix}.nbt")
        voxels, shift = _rotate_voxels(part, comp.rotation,
                                       nominal=(_sx, _sz))
        sp = _SW_START_POS[comp.rotation]
        start_off = (sp[0] + shift[0], sp[1] + shift[1])
    elif comp.struct_key == "nether_fortress":
        voxels, nether_chest_offs = _fortress_solid_voxels(comp)
        start_off = (0, 0)
    elif comp.struct_key == "bastion_remnant":
        voxels, nether_chest_offs = _bastion_jigsaw_voxels(comp)
        start_off = (0, 0)
    elif comp.struct_key == "end_city":
        # 末地城：逐 seed 真实 jigsaw 拼装（模板 NBT，无降级）。
        # RNG 箱子公式坐标与拼装 chest 体素严格重合（模板 NBT 实
        # 锚点 (1,y,1) + 无修正旋转 R，43/43 实测命中），走通用
        # exact 匹配路径，无需近邻兑底。
        from . import end_city_pieces as _ecp
        voxels = _ecp.end_city_voxels(comp.pieces, comp.anchor)
        start_off = (0, 0)
    elif comp.struct_key == "trial_chambers":
        # 试炼密室：逐 seed 真实 jigsaw 拼装（模板 NBT + 铜灯降解）。
        # RNG 预测容器与拼装几何同源（同一 piece 序 + 同一变换），
        # pos3 3D exact 匹配（同 (x,z) 不同 y 可区分），无兑底。
        voxels, nether_chest_offs = _trial_jigsaw_voxels(comp)
        start_off = (0, 0)
    elif comp.struct_key == "pillager_outpost":
        # 前哨站：逐 seed 真实 jigsaw 拼装（list 双子模板 + 腐蚀），
        # 箱子体素由容器记录补写（DATA 标记语义），与 RNG 预测
        # 同源，pos3 3D exact 匹配，y 基准 = 64（平坦基准）。
        voxels, nether_chest_offs = _outpost_jigsaw_voxels(comp)
        start_off = (0, 0)
    elif comp.struct_key == "stronghold":
        # 要塞：逐 piece postProcess 转写（无模板 NBT）。RNG 箱子与
        # 几何同源（同 piece 序 + 同 rot_pos 变换），pos3 3D exact
        # 匹配（同 (x,z) 不同 y 可区分，叠加层走廊箱/阁楼箱）。
        voxels, nether_chest_offs = _stronghold_voxels(comp)
        start_off = (0, 0)
    elif comp.struct_key == "woodland_mansion":
        # 林地府邸：逐 piece 模板 NBT 精确拼装（mansion_pieces
        # 转写，对拍 ALL PASS）。RNG 随机箱（DATA 标记语义）与
        # 几何同源，pos3 3D exact 匹配，y 基准 = 64。
        voxels, nether_chest_offs = _mansion_voxels(comp)
        start_off = (0, 0)
    elif comp.struct_key == "ocean_ruin":
        # 海底废墟：逐 piece 模板 NBT 拼装（OceanRuinPieces 转写）。
        # RNG 箱子（DATA 标记语义）与几何同源，pos3 3D exact 匹配，
        # y 基准 = 90（Java 锚点高度，平坦预览不做海床沉降）。
        voxels, nether_chest_offs = _ocean_ruin_voxels(comp)
        start_off = (0, 0)
    elif comp.struct_key == "ancient_city":
        # 远古城市：逐 seed 真实 jigsaw 拼装（模板 NBT + block_rot/
        # rule 降解 + city_anchor 重定位）。RNG 预测容器与拼装几何
        # 同源（同一 piece 序 + 同一变换），pos3 3D exact 匹配
        # （同 (x,z) 不同 y 可区分），无兑底；y 基准 = 起点件底面
        # （extra["start_y"]）。
        voxels, nether_chest_offs = _ancient_city_jigsaw_voxels(comp)
        start_off = (0, 0)
    elif comp.struct_key == "village":
        # 村庄：逐 seed 真实 jigsaw 拼装（模板 NBT + RuleProcessor
        # 数据驱动处理器：mossify/farm/street/zombie）。RNG 预测容器
        # 与拼装几何同源，pos3 3D exact 匹配；y 基准 = 起点件底面
        # （extra["start_y"]，地表平坦基准）。
        voxels, nether_chest_offs = _village_jigsaw_voxels(comp)
        start_off = (0, 0)
    else:
        raise ValueError(f"display 未支持的结构键：{comp.struct_key}")

    if voxels:
        xs = [p[0] for p in voxels]
        ys = [p[1] for p in voxels]
        zs = [p[2] for p in voxels]
        min_x = min(xs)
        min_z = min(zs)
        if min_x < 0 or min_z < 0:
            voxels = {(x - min_x, y, z - min_z): m
                      for (x, y, z), m in voxels.items()}
            start_off = (start_off[0] + min_x, start_off[1] + min_z)
        size = (max(p[0] for p in voxels) + 1,
                max(p[1] for p in voxels) - min(p[1] for p in voxels) + 1,
                max(p[2] for p in voxels) + 1)
        min_y = min(p[1] for p in voxels)
    else:
        size, min_y = (1, 1, 1), 0

    # 箱子标注：RNG 世界坐标 -> 模型坐标；匹配模板内 chest 方块的 y
    chest_voxel_y = {}
    for (x, y, z), mat in voxels.items():
        if _is_chest_value(mat):
            chest_voxel_y[(x, z)] = y
    if comp.struct_key == "nether_fortress" and chest_voxel_y:
        # 要塞：RNG 箱子公式坐标与拼装布局坐标有已知偏差（实测达
        # 7 格），全局 1:1 贪心分配（切比雪夫 <=8）：近距离优先、
        # 互斥认领；exact 命中距离 0 恒最先锁定。分配后未认领的
        # 箱子走下方兜底。
        max_d = 8
        pairs = []
        for ci, c0 in enumerate(comp.chests):
            bx = c0.pos[0] - comp.anchor[0] - start_off[0]
            bz = c0.pos[1] - comp.anchor[1] - start_off[1]
            for (vx, vz), vy in chest_voxel_y.items():
                d = max(abs(vx - bx), abs(vz - bz))
                if d <= max_d:
                    pairs.append((d, ci, vx, vy, vz))
        pairs.sort()
        taken_v: set = set()
        assign: dict = {}
        for _d, ci, vx, vy, vz in pairs:
            if ci in assign or (vx, vz) in taken_v:
                continue
            assign[ci] = (vx, vy, vz)
            taken_v.add((vx, vz))
        for ci, (vx, vy, vz) in assign.items():
            comp.chests[ci].pos_model = (vx, vy, vz)
        assigned = set(assign)
    elif comp.struct_key == "bastion_remnant" and chest_voxel_y:
        # 堡垒：RNG 箱子 = 拼装引擎同一几何（piece 序 + rot_piece_pos
        # 同变换），预测箱与渲染 chest 体素 3D 精确重合（用 pos3
        # 匹配：同 (x,z) 不同 y 的叠柱箱可区分）。pos_model = 模型
        # 三维坐标（-anchor、y-64，再叠加 min_x/min_z 归一化平移，
        # 与体素同一坐标系）。
        assigned = set()
        for ci, c0 in enumerate(comp.chests):
            if c0.pos3 is None:
                continue
            bx = c0.pos3[0] - comp.anchor[0] - start_off[0]
            by = c0.pos3[1] - 64
            bz = c0.pos3[2] - comp.anchor[1] - start_off[1]
            if voxels.get((bx, by, bz)) is not None \
                    and _is_chest_value(voxels[(bx, by, bz)]):
                c0.pos_model = (bx, by, bz)
                assigned.add(ci)
    elif comp.struct_key == "trial_chambers" and chest_voxel_y:
        # 试炼密室：同 bastion，pos3 3D exact 匹配，但 y 基准 =
        # start_y（extra["start_y"]）而非 64（预测容器与渲染体素
        # 同一拼装同一变换，逐项重合；含 barrel 容器，
        # _is_chest_value 已含）。
        y0 = comp.extra["start_y"]
        assigned = set()
        for ci, c0 in enumerate(comp.chests):
            if c0.pos3 is None:
                continue
            bx = c0.pos3[0] - comp.anchor[0] - start_off[0]
            by = c0.pos3[1] - y0
            bz = c0.pos3[2] - comp.anchor[1] - start_off[1]
            if voxels.get((bx, by, bz)) is not None \
                    and _is_chest_value(voxels[(bx, by, bz)]):
                c0.pos_model = (bx, by, bz)
                assigned.add(ci)
    elif comp.struct_key == "ancient_city" and chest_voxel_y:
        # 远古城市：同 trial，pos3 3D exact 匹配，y 基准 = 起点件
        # 底面（extra["start_y"]，anchor 重定位 + dy 后真实值）。
        y0 = comp.extra["start_y"]
        assigned = set()
        for ci, c0 in enumerate(comp.chests):
            if c0.pos3 is None:
                continue
            bx = c0.pos3[0] - comp.anchor[0] - start_off[0]
            by = c0.pos3[1] - y0
            bz = c0.pos3[2] - comp.anchor[1] - start_off[1]
            if voxels.get((bx, by, bz)) is not None \
                    and _is_chest_value(voxels[(bx, by, bz)]):
                c0.pos_model = (bx, by, bz)
                assigned.add(ci)
    elif comp.struct_key == "village" and chest_voxel_y:
        # 村庄：同 trial/ancient_city，pos3 3D exact 匹配，y 基准 =
        # 起点件底面（_village_jigsaw_voxels 与 RNG 箱子同源，
        # 理论全命中）。
        y0 = comp.extra["start_y"]
        assigned = set()
        for ci, c0 in enumerate(comp.chests):
            if c0.pos3 is None:
                continue
            bx = c0.pos3[0] - comp.anchor[0] - start_off[0]
            by = c0.pos3[1] - y0
            bz = c0.pos3[2] - comp.anchor[1] - start_off[1]
            if voxels.get((bx, by, bz)) is not None \
                    and _is_chest_value(voxels[(bx, by, bz)]):
                c0.pos_model = (bx, by, bz)
                assigned.add(ci)
    elif comp.struct_key == "stronghold" and chest_voxel_y:
        # 要塞：同 bastion/trial，pos3 3D exact 匹配，y 基准 = 64
        # （_stronghold_voxels 与 RNG 箱子同源，逐项重合；漏配
        # （理论无）走通用路径兑底）。
        assigned = set()
        for ci, c0 in enumerate(comp.chests):
            if c0.pos3 is None:
                continue
            bx = c0.pos3[0] - comp.anchor[0] - start_off[0]
            by = c0.pos3[1] - 64
            bz = c0.pos3[2] - comp.anchor[1] - start_off[1]
            if voxels.get((bx, by, bz)) is not None \
                    and _is_chest_value(voxels[(bx, by, bz)]):
                c0.pos_model = (bx, by, bz)
                assigned.add(ci)
    elif comp.struct_key == "pillager_outpost" and chest_voxel_y:
        # 前哨站：同 bastion/trial，pos3 3D exact 匹配，y 基准 = 64。
        assigned = set()
        for ci, c0 in enumerate(comp.chests):
            if c0.pos3 is None:
                continue
            bx = c0.pos3[0] - comp.anchor[0] - start_off[0]
            by = c0.pos3[1] - 64
            bz = c0.pos3[2] - comp.anchor[1] - start_off[1]
            if voxels.get((bx, by, bz)) is not None \
                    and _is_chest_value(voxels[(bx, by, bz)]):
                c0.pos_model = (bx, by, bz)
                assigned.add(ci)
    elif comp.struct_key == "woodland_mansion" and chest_voxel_y:
        # 林地府邸：同前哨站，pos3 3D exact 匹配，y 基准 = 64。
        # 随机箱体素由 _mansion_voxels 按容器记录补写（同源预测，
        # 理论全命中，无兑底漏配）。
        assigned = set()
        for ci, c0 in enumerate(comp.chests):
            if c0.pos3 is None:
                continue
            bx = c0.pos3[0] - comp.anchor[0] - start_off[0]
            by = c0.pos3[1] - 64
            bz = c0.pos3[2] - comp.anchor[1] - start_off[1]
            if voxels.get((bx, by, bz)) is not None \
                    and _is_chest_value(voxels[(bx, by, bz)]):
                c0.pos_model = (bx, by, bz)
                assigned.add(ci)
    elif comp.struct_key == "ocean_ruin" and chest_voxel_y:
        # 海底废墟：同前哨站/府邸，pos3 3D exact 匹配，y 基准 = 90
        # （_ocean_ruin_voxels 与 RNG 箱子同源：同一 piece 序、
        # 同一 _ocean_rot_xz 变换，标记坐标补写 chest 体素，
        # 理论全命中）。
        assigned = set()
        for ci, c0 in enumerate(comp.chests):
            if c0.pos3 is None:
                continue
            bx = c0.pos3[0] - comp.anchor[0] - start_off[0]
            by = c0.pos3[1] - 90
            bz = c0.pos3[2] - comp.anchor[1] - start_off[1]
            if voxels.get((bx, by, bz)) is not None \
                    and _is_chest_value(voxels[(bx, by, bz)]):
                c0.pos_model = (bx, by, bz)
                assigned.add(ci)
    else:
        assigned = None
    chest_marks = []
    for ci, c in enumerate(comp.chests):
        if assigned is not None and ci in assigned:
            # 已 1:1 分配到 chest 体素（见上方要塞近邻匹配）。
            chest_marks.append(c.pos_model)
            continue
        mx = c.pos[0] - comp.anchor[0] - start_off[0]
        mz = c.pos[1] - comp.anchor[1] - start_off[1]
        my = chest_voxel_y.get((mx, mz))
        if my is None and comp.struct_key == "igloo" and chest_voxel_y:
            # 雪屋模型未随 rotation/mirror 旋转，RNG 推导坐标与
            # 模型内 chest 块不重合（见已知妥协）；单箱无歧义，
            # 直接用模板内 chest 块作高亮位置。
            (mx, mz), my = next(iter(chest_voxel_y.items()))
        if my is not None:
            # 已匹配到模型内 chest 体素：用体素真实位置（要塞精确
            # 布局下即箱子方块本身）。
            c.pos_model = (mx, my, mz)
            chest_marks.append((mx, my, mz))
            continue
        my = (-3 - 3 * comp.extra["size"]) \
            if comp.struct_key == "igloo" else 0
        if comp.struct_key in _NETHER_KEYS and \
                (c.pos[0] - comp.anchor[0],
                 c.pos[1] - comp.anchor[1]) in nether_chest_offs:
            # 下界兜底（无 chest 体素可匹配，bastion 示意体恒走
            # 此路）：抬到所在柱顶层（避免标注沉在地面下被遮挡）。
            col = [yy for (vx, yy, vz) in voxels if vx == mx and vz == mz]
            if col:
                my = max(col)
        c.pos_model = (mx, my, mz)
        chest_marks.append((mx, my, mz))

    if comp.struct_key in ("igloo",):
        anchor_y = 90
    elif comp.struct_key == "shipwreck":
        anchor_y = 64
    elif comp.struct_key in ("trial_chambers", "ancient_city", "village"):
        # y 基准 = 起点件底面世界 y（模型 y0 平面即城市底面，
        # chunk 网格/锚点红线与其同面）
        anchor_y = comp.extra["start_y"]
    elif comp.struct_key == "ocean_ruin":
        anchor_y = 90    # Java 锚点 y（OceanRuinStructure L42-46）
    else:
        # bastion/fortress/outpost/mansion：平坦基准 64
        anchor_y = 64
    # 渲染体素里的全部容器方块（= bastion RNG 预测箱全集）——3D
    # 开箱准星的交互全集；预测映射关系由 comp.chests[i].pos_model
    # 提供（bastion 全箱子 exact 匹配后 chest_blocks 与 pos_model
    # 一一对应，开箱全走预测战利品；fortress 渲染箱可能多于预测
    # 箱，未预测的开箱走提示）。
    chest_blocks = sorted((x, y, z)
                          for (x, y, z), m in voxels.items()
                          if _is_chest_value(m))
    tex_keys = sorted({(m[0] if isinstance(m, tuple) else m)
                       for m in voxels.values()})
    # 注入模式低层覆盖：锚点（=其所在区块西北角）在模型内坐标为
    # -start_off（世界锚点 + start_off = 模型原点）；区块黄框相位
    # 与锚点同源（cubiomes 语义，网格原点随锚点平移）。
    anchor_local = (-start_off[0], -start_off[1])
    chunk_origin = (anchor_local[0] % 16.0, anchor_local[1] % 16.0)
    return {
        "key": comp.struct_key,
        "variant": comp.variant_name,
        "voxels": voxels,
        "size": size,
        "min_y": min_y,
        "mesh": structure_models.build_mesh(voxels),
        "tex_keys": tex_keys,
        "chests": chest_marks,
        "chest_blocks": chest_blocks,
        "anchor": comp.anchor,
        "anchor_off": start_off,
        "anchor_y": anchor_y,
        "anchor_local": anchor_local,
        "chunk_origin": chunk_origin,
        "comp": comp,
    }
