# -*- coding: utf-8 -*-
"""StructurePreviewer：结构构造组合层（composition）。

按世界种子复现 igloo（雪屋）/ shipwreck（沉船）的：
    - 模板变种选择（getVariant，cubiomes chunkGenerateRnd 流）
    - 各部件（pieces）生成锚点与朝向（getStructurePieces）
    - 各箱子的世界坐标与 LootTableSeed

考证基准：xpple/cubiomes fork commit 5815e4f 的 finders.c
    - getVariant Igloo 分支（约 L2855）/ Shipwreck 分支（约 L2873）
    - getStructurePieces Igloo / Shipwreck 分支（L3021-3343）
RNG 消耗序列逐行照抄，函数内注释标注对应 C 源码位置。

版本约束：仅支持 mc >= 1.18（Xoroshiro128++ 流）；1.18-1.21 的
generation_step / decorator_index 对本工具覆盖的结构一致。

显示模型约定（build_display_model）：
    - 体素 dict {(x,y,z): 材质键}，x 东 / y 上 / z 南，
      (0,0,0) = 结构锚点（minBlock 西北角）的地表基准面。
    - igloo：top 顶部 y=0，middle/bottom 向下为负（地下室）。
    - shipwreck：pos y=64 对应模板 y=0。
    - shipwreck 体素做精确旋转（与箱子公式同一 R_raw 变换，自洽）；
      igloo 公式含隐藏的 piece 锚点修正（IglooPieces 源码内 offset），
      反解不唯一，故第一版模型不旋转（示意），箱子高亮取模板内
      chest 方块本身位置；RNG/世界坐标一律以 finders.c 公式为准。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from Utils.MapPreviewer import structure_map
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
    """
    pos: tuple[int, int]
    loot_table: str
    loot_seed: int
    pos_model: tuple[int, int, int] | None = None


@dataclass
class Piece:
    """一个结构部件（对应 finders.c 的 Piece）。"""
    name: str
    pos: tuple[int, int, int]                     # 世界锚点 (x, y, z)
    chests: list[Chest] = field(default_factory=list)


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
# 显示辅助
# ---------------------------------------------------------------------------

# 视口认得的箱子方块材质键（structure_models 的映射名，小写）
_CHEST_MATS = frozenset({"chest", "trapped_chest", "barrel"})


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


def _rotate_voxels(voxels: dict, rotation: int) -> tuple[dict, tuple[int, int]]:
    """体素按 cubiomes 放置旋转精确变换，返回 (旋转后体素, (平移x, 平移z))。

    R_raw（相对模板原点，与箱子世界坐标公式同向）：
        rot0: (x, z)          rot1: (-z, x)
        rot2: (-x, -z)        rot3: (z, -x)
    返回的平移 = min(min_x, min_z)，使体素回到非负象限；调用方用
    startPos - shift 得到模型锚点相对坐标（见 compose_display_model）。
    """
    if rotation == 0:
        return voxels, (0, 0)
    rot = {1: lambda x, z: (-z, x),
           2: lambda x, z: (-x, -z),
           3: lambda x, z: (z, -x)}[rotation]
    out = {}
    for (x, y, z), mat in voxels.items():
        nx, nz = rot(x, z)
        out[(nx, y, nz)] = mat
    mnx = min(p[0] for p in out)
    mnz = min(p[2] for p in out)
    return ({(x - mnx, y, z - mnz): m for (x, y, z), m in out.items()},
            (mnx, mnz))


# ---------------------------------------------------------------------------
# 公共入口 + 显示模型
# ---------------------------------------------------------------------------

def compose(struct_key: str, world_seed: int, block_x: int, block_z: int,
            biome_id: int = -1, version_key: str = "1.21") -> Composition:
    """结构键 -> 构造组合结果（当前支持 igloo / shipwreck）。"""
    if struct_key == "igloo":
        return compose_igloo(world_seed, block_x, block_z, version_key)
    if struct_key == "shipwreck":
        return compose_shipwreck(world_seed, block_x, block_z, biome_id,
                                 version_key)
    raise ValueError(f"composition 未支持的结构键：{struct_key}")


def _load_template_voxels(fname: str) -> dict:
    return structure_models._voxels_from_template_file(
        os.path.join(structure_models.TEMPLATE_DIR, fname))


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

    已知妥协（第一版）：
    - igloo 模型不随 rotation/mirror 旋转（cubiomes 公式含隐藏的
      piece 内偏移，反解不唯一；RNG 坐标不受影响）；
    - shipwreck 非 with_mast 变种暂用 with_mast 模板占位（其余
      19 变种 NBT 待补），degraded 形状同非 degraded。
    """
    if comp.struct_key == "igloo":
        voxels: dict = {}
        for fname, dx, dy, dz in _igloo_model_parts(comp):
            for (x, y, z), m in _load_template_voxels(fname).items():
                voxels[(x + dx, y + dy, z + dz)] = m
        start_off = (0, 0)
    elif comp.struct_key == "shipwreck":
        part = _load_template_voxels(
            structure_models.TEMPLATE_FILES["shipwreck"][0])
        voxels, shift = _rotate_voxels(part, comp.rotation)
        sp = _SW_START_POS[comp.rotation]
        start_off = (sp[0] + shift[0], sp[1] + shift[1])
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
        if mat in _CHEST_MATS:
            chest_voxel_y[(x, z)] = y
    chest_marks = []
    for c in comp.chests:
        mx = c.pos[0] - comp.anchor[0] - start_off[0]
        mz = c.pos[1] - comp.anchor[1] - start_off[1]
        my = chest_voxel_y.get((mx, mz))
        if my is None and comp.struct_key == "igloo" and chest_voxel_y:
            # 雪屋模型未随 rotation/mirror 旋转，RNG 推导坐标与
            # 模型内 chest 块不重合（见已知妥协）；单箱无歧义，
            # 直接用模板内 chest 块作高亮位置。
            (mx, mz), my = next(iter(chest_voxel_y.items()))
        if my is None:
            my = (-3 - 3 * comp.extra["size"]) \
                if comp.struct_key == "igloo" else 0
        chest_marks.append((mx, my, mz))

    anchor_y = 90 if comp.struct_key == "igloo" else 64
    return {
        "key": comp.struct_key,
        "variant": comp.variant_name,
        "voxels": voxels,
        "size": size,
        "min_y": min_y,
        "mesh": None,
        "tex_keys": None,
        "chests": chest_marks,
        "anchor": comp.anchor,
        "anchor_off": start_off,
        "anchor_y": anchor_y,
        "comp": comp,
    }
