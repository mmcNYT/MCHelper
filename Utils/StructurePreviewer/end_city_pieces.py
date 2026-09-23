# -*- coding: utf-8 -*-
"""StructurePreviewer：末地城（End City）逐 piece 精确生成。

RNG 权威基准：cubiomes finders.c getEndCityPieces（L2336-2595）逐行转写：
    - addEndCityPiece：20 种 piece 名义尺寸表（索引即类型号）、
      AABB 扩展（rot0: bb1.x+=sx / bb1.z+=sz，其余 rot 同族）、
      相对偏移按 prev.rot 变换（0:+px,+pz / 1:-pz,+px / 2:-px,-pz /
      3:+pz,-px）
    - genPiecesRecusively：先在局部列表生成（失败整批不加入，但
      RNG 消耗保留），随后 next(rng,32) 取批深度（Java int 有符号，
      可为负——无符号值会破坏 depth>8 判断），再对局部每个 piece
      与主列表全体做 AABB 闭区间相交检查：与 current.depth 不同的
      相交 piece 令整批弃置；同 depth 相交放行；通过后整批加入并
      写 depth=gendepth
    - genTower / genBridge / genHouseTower / genFatTower 四个递归
      生成器（END_SHIP 的 nextInt(10-depth) 短路：ship 已置位时
      不消耗该 RNG）

RNG 语义（xp fork rng.h）：
    - nextInt(n) = mc_random.next_int（完整拒绝采样）
    - next(rng,bits) = mc_random.next_bits；bits=32 时按 Java int
      转有符号

箱子与战利品（xp fork finders.c End_City 分支 L3506-3607）：
    - 有箱 piece：FAT_TOWER_TOP（2 箱）/ END_SHIP（2 箱）/
      THIRD_FLOOR_2（1 箱）；箱子世界坐标 = (pos-1) + R(偏移)，
      R 为无修正旋转（已对模板 NBT 箱子坐标四旋转逐一吻合验证）
    - salt 档 end_city = (4, 2)（1.19.4+）/ (4, 11)（1.18）
    - loot 流：pop = get_population_seed(seed, 箱子x&~15, z&~15)，
      XoroshiroJava(pop + decorator + 10000*step)；单箱 skip1 取1；
      同 piece 双箱同区块 → 同流 skip2 取2，跨区块 → 各自流 skip1
      取1（skip 的 nextLong = placeInWorld 写入的未使用
      LootTableSeed；模板 NBT 中箱子上方 DATA 结构方块实锤：
      固定 1 消耗 + 每箱 1 消耗）

几何模型（模板 NBT 实测，与 20 个 endcity__*.nbt 尺寸核对）：
    piece 锚点 = 模板局部 (1, y, 1) 格，即模板原点 = piece_pos -
    (1,0,1)；方块世界坐标 = piece_pos - (1,0,1) + R(local)，R 为
    无修正旋转（0 恒等 / 1 (x,z)->(-z,x) / 2 (-x,-z) / 3 (z,-x)）。
    fat_tower_top 的 AABB 用名义 16x5x16（含端点格语义见
    composition.Piece），渲染用真实模板 17x6x17（含悬挑）；ship
    同理（名义 12x23x28，模板 13x24x29）。

显示体素（end_city_voxels）：模板原始方块名经
structure_models._map_block（材质映射，air/structure_block 映射为
None 自动剔除）+ block_shapes.shape_rotation（朝向随 piece 旋转
同步，与 R 同族），模型口径同 fortress/bastion：
(x,z) = 世界 - anchor、y = 世界 - 64（piece y=0 为相对高度，
anchor_y 取 64 示意基准面）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from Utils.Public import structure_map
from Utils.SeedReverser import mc_random
from . import loot_rng

# ---------------------------------------------------------------------------
# piece 枚举（addEndCityPiece info[]，索引 = 类型号，顺序不可动）
# ---------------------------------------------------------------------------

(BASE_FLOOR, BASE_ROOF, BRIDGE_END, BRIDGE_GENTLE_STAIRS, BRIDGE_PIECE,
 BRIDGE_STEEP_STAIRS, FAT_TOWER_BASE, FAT_TOWER_MIDDLE, FAT_TOWER_TOP,
 SECOND_FLOOR_1, SECOND_FLOOR_2, SECOND_ROOF, END_SHIP, THIRD_FLOOR_1,
 THIRD_FLOOR_2, THIRD_ROOF, TOWER_BASE, TOWER_FLOOR, TOWER_PIECE,
 TOWER_TOP) = range(20)

# (名称, sx, sy, sz)（finders.c L2338-2359）
_PIECE_INFO = (
    ("base_floor", 9, 3, 9),
    ("base_roof", 11, 1, 11),
    ("bridge_end", 4, 5, 1),
    ("bridge_gentle_stairs", 4, 6, 7),
    ("bridge_piece", 4, 5, 3),
    ("bridge_steep_stairs", 4, 6, 3),
    ("fat_tower_base", 12, 3, 12),
    ("fat_tower_middle", 12, 7, 12),
    ("fat_tower_top", 16, 5, 16),
    ("second_floor_1", 11, 7, 11),
    ("second_floor_2", 11, 7, 11),
    ("second_roof", 13, 1, 13),
    ("ship", 12, 23, 28),
    ("third_floor_1", 13, 7, 13),
    ("third_floor_2", 13, 7, 13),
    ("third_roof", 15, 1, 15),
    ("tower_base", 6, 6, 6),
    ("tower_floor", 6, 3, 6),          # unused（Java 亦未生成）
    ("tower_piece", 6, 3, 6),
    ("tower_top", 8, 4, 8),
)

PIECE_NAMES = tuple(info[0] for info in _PIECE_INFO)

# genTower 桥接方向表（finders.c L2453-2458：rot偏移, px, py, pz）
_TOWER_BINFO = ((0, 1, -1, 0), (1, 6, -1, 1), (3, 0, -1, 5), (2, 5, -1, 6))
# genFatTower 桥接方向表（finders.c L2553-2558）
_FAT_BINFO = ((0, 4, -1, 0), (1, 12, -1, 4), (3, 0, -1, 8), (2, 8, -1, 12))

_LOOT_TABLE = "chests/end_city_treasure"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class EndPiece:
    """一个末地城 piece（对应 finders.c 的 Piece）。

    pos   世界锚点 (x, y, z)（首件为绝对坐标，其余为链式累积）
    bb0/bb1  AABB 最小角 / 含端点最大角（Java maxX 语义，占用闭区间）
    chests   [(世界x, 世界z, loot_table, loot_seed)]（_assign_chests 填充）
    """
    name: str
    type: int
    rot: int
    pos: tuple[int, int, int]
    bb0: tuple[int, int, int]
    bb1: tuple[int, int, int]
    depth: int = 0
    chests: list = field(default_factory=list)


@dataclass
class EndCityResult:
    """build_end_city 的完整结果。"""
    anchor: tuple[int, int]        # 结构锚点 = (minBlockX, minBlockZ)
    rotation: int                  # 起始件 rot = nextInt(4)
    pieces: list[EndPiece]
    ship: bool                     # 本城是否生成了 End Ship
    rng_state: int                 # piece 流最终 48 位状态（备用）


class _Env:
    """PieceEnv：pieces 列表 + RNG 状态 + ship 旗标 + y 寄存器。

    rng 为 48 位 LCG 状态整数（不可变，赋值回写推进）；ship 用单
    元素列表模拟 C 指针共享（genBridge 置位须穿透局部 env，对应
    env_local = *env 后 env_local.ship 与外层同指针）；y 为值拷贝
    （genBridge 写、genHouseTower 读，C 中 env_local 拷贝同语义：
    批被弃置时外层 y 不回传）。
    """

    __slots__ = ("pieces", "rng", "ship", "y")

    def __init__(self, rng: int, ship: list):
        self.pieces: list[EndPiece] = []
        self.rng = rng
        self.ship = ship
        self.y = 0


# ---------------------------------------------------------------------------
# RNG 原语
# ---------------------------------------------------------------------------

def _next(state: int, bits: int) -> tuple[int, int]:
    """C next(rng, bits)：推进一次取高 bits 位；32 位按 Java int 转
    有符号（cubiomes next() 宏 + (int) 强转）。"""
    state = mc_random.next_state(state)
    v = state >> (48 - bits)
    if bits == 32 and v >= 0x80000000:
        v -= 0x100000000
    return v, state


# ---------------------------------------------------------------------------
# piece 树算法（finders.c L2336-2595 逐行转写）
# ---------------------------------------------------------------------------

def _add_piece(env: _Env, prev: EndPiece | None, rot: int,
               px: int, py: int, pz: int, typ: int) -> EndPiece:
    """addEndCityPiece（finders.c L2336-2398）。"""
    name, sx, sy, sz = _PIECE_INFO[typ]
    pos = (px, py, pz) if prev is None else prev.pos
    bb0 = [pos[0], pos[1], pos[2]]
    bb1 = [pos[0], pos[1] + sy, pos[2]]
    if rot == 0:
        bb1[0] += sx
        bb1[2] += sz
    elif rot == 1:
        bb0[0] -= sz
        bb1[2] += sx
    elif rot == 2:
        bb0[0] -= sx
        bb0[2] -= sz
    else:
        bb1[0] += sz
        bb0[2] -= sx
    if prev is not None:
        dx = dz = 0
        pr = prev.rot
        if pr == 0:
            dx += px
            dz += pz
        elif pr == 1:
            dx -= pz
            dz += px
        elif pr == 2:
            dx -= px
            dz -= pz
        else:
            dx += pz
            dz -= px
        pos = (pos[0] + dx, pos[1] + py, pos[2] + dz)
        bb0 = [bb0[0] + dx, bb0[1] + py, bb0[2] + dz]
        bb1 = [bb1[0] + dx, bb1[1] + py, bb1[2] + dz]
    p = EndPiece(name, typ, rot, pos, tuple(bb0), tuple(bb1))
    env.pieces.append(p)
    return p


def _gen_recursively(gen, env: _Env, current: EndPiece, depth: int) -> int:
    """genPiecesRecusively（finders.c L2400-2431）。

    局部 env 生成（ship 指针共享、rng 成败都同步回写）；批深度
    next(rng,32) 有符号；AABB 闭区间相交检查与 current.depth 不同
    的 piece 令整批弃置（RNG 消耗保留）。
    """
    if depth > 8:
        return 0
    local = _Env(env.rng, env.ship)
    local.y = env.y
    ok = gen(local, current, depth)
    env.rng = local.rng
    if not ok:
        return 0
    gendepth, env.rng = _next(env.rng, 32)
    for p in local.pieces:
        p.depth = gendepth
        for q in env.pieces:
            if (q.bb1[0] >= p.bb0[0] and q.bb0[0] <= p.bb1[0]
                    and q.bb1[2] >= p.bb0[2] and q.bb0[2] <= p.bb1[2]
                    and q.bb1[1] >= p.bb0[1] and q.bb0[1] <= p.bb1[1]):
                if current.depth != q.depth:
                    return 0
                break
    env.pieces.extend(local.pieces)
    return 1


def _gen_tower(env: _Env, current: EndPiece, depth: int) -> int:
    """genTower（finders.c L2433-2476）。"""
    rot = current.rot
    x, env.rng = mc_random.next_int(env.rng, 2)
    x += 3
    z, env.rng = mc_random.next_int(env.rng, 2)
    z += 3
    base = current
    base = _add_piece(env, base, rot, x, -3, z, TOWER_BASE)
    base = _add_piece(env, base, rot, 0, 7, 0, TOWER_PIECE)
    t, env.rng = mc_random.next_int(env.rng, 3)
    floor = base if t == 0 else None
    floorcnt, env.rng = mc_random.next_int(env.rng, 3)
    floorcnt += 1
    for i in range(floorcnt):
        base = _add_piece(env, base, rot, 0, 4, 0, TOWER_PIECE)
        if i < floorcnt - 1:
            b, env.rng = _next(env.rng, 1)
            if b:
                floor = base
    if floor is not None:
        for i in range(4):
            b, env.rng = _next(env.rng, 1)
            if not b:
                continue
            brot = (rot + _TOWER_BINFO[i][0]) & 3
            bridge = _add_piece(env, base, brot, _TOWER_BINFO[i][1],
                                _TOWER_BINFO[i][2], _TOWER_BINFO[i][3],
                                BRIDGE_END)
            _gen_recursively(_gen_bridge, env, bridge, depth + 1)
    elif depth != 7:
        return _gen_recursively(_gen_fat_tower, env, base, depth + 1)
    _add_piece(env, base, rot, -1, 4, -1, TOWER_TOP)
    return 1


def _gen_bridge(env: _Env, current: EndPiece, depth: int) -> int:
    """genBridge（finders.c L2478-2516）。"""
    rot = current.rot
    floorcnt, env.rng = mc_random.next_int(env.rng, 4)
    floorcnt += 1
    base = current
    base = _add_piece(env, base, rot, 0, 0, -4, BRIDGE_PIECE)
    base.depth = -1
    y = 0
    for _ in range(floorcnt):
        b, env.rng = _next(env.rng, 1)
        if b:
            base = _add_piece(env, base, rot, 0, y, -4, BRIDGE_PIECE)
            y = 0
            continue
        b2, env.rng = _next(env.rng, 1)
        if b2:
            base = _add_piece(env, base, rot, 0, y, -4, BRIDGE_STEEP_STAIRS)
        else:
            base = _add_piece(env, base, rot, 0, y, -8, BRIDGE_GENTLE_STAIRS)
        y = 4
    do_ship = False
    if not env.ship[0]:                    # 短路：ship 已置位不消耗
        t, env.rng = mc_random.next_int(env.rng, 10 - depth)
        do_ship = (t == 0)
    if do_ship:
        xs, env.rng = mc_random.next_int(env.rng, 8)
        zs, env.rng = mc_random.next_int(env.rng, 10)
        base = _add_piece(env, base, rot, xs - 8, y, zs - 70, END_SHIP)
        env.ship[0] = 1
    else:
        env.y = y + 1
        if not _gen_recursively(_gen_house_tower, env, base, depth + 1):
            return 0
    base = _add_piece(env, base, (rot + 2) & 3, 4, y, 0, BRIDGE_END)
    base.depth = -1
    return 1


def _gen_house_tower(env: _Env, current: EndPiece, depth: int) -> int:
    """genHouseTower（finders.c L2518-2543）。"""
    if depth > 8:
        return 0
    rot = current.rot
    base = current
    base = _add_piece(env, base, rot, -3, env.y, -11, BASE_FLOOR)
    size, env.rng = mc_random.next_int(env.rng, 3)
    if size == 0:
        _add_piece(env, base, rot, -1, 4, -1, BASE_ROOF)
        return 1
    base = _add_piece(env, base, rot, -1, 0, -1, SECOND_FLOOR_2)
    if size == 1:
        base = _add_piece(env, base, rot, -1, 8, -1, SECOND_ROOF)
    else:
        base = _add_piece(env, base, rot, -1, 4, -1, THIRD_FLOOR_2)
        base = _add_piece(env, base, rot, -1, 8, -1, THIRD_ROOF)
    _gen_recursively(_gen_tower, env, base, depth + 1)
    return 1


def _gen_fat_tower(env: _Env, current: EndPiece, depth: int) -> int:
    """genFatTower（finders.c L2545-2574）。"""
    rot = current.rot
    base = current
    base = _add_piece(env, base, rot, -3, 4, -3, FAT_TOWER_BASE)
    base = _add_piece(env, base, rot, 0, 4, 0, FAT_TOWER_MIDDLE)
    j = 0
    while j < 2:
        t, env.rng = mc_random.next_int(env.rng, 3)
        if t == 0:
            break
        base = _add_piece(env, base, rot, 0, 8, 0, FAT_TOWER_MIDDLE)
        for i in range(4):
            b, env.rng = _next(env.rng, 1)
            if not b:
                continue
            brot = (rot + _FAT_BINFO[i][0]) & 3
            bridge = _add_piece(env, base, brot, _FAT_BINFO[i][1],
                                _FAT_BINFO[i][2], _FAT_BINFO[i][3],
                                BRIDGE_END)
            _gen_recursively(_gen_bridge, env, bridge, depth + 1)
        j += 1
    _add_piece(env, base, rot, -2, 8, -2, FAT_TOWER_TOP)
    return 1


# ---------------------------------------------------------------------------
# 箱子与 LootTableSeed（xp fork finders.c End_City 分支 L3506-3607）
# ---------------------------------------------------------------------------

def _rot_xz(rot: int, x: int, z: int) -> tuple[int, int]:
    """无修正旋转 R（0 恒等 / 1 (x,z)->(-z,x) / 2 (-x,-z) / 3 (z,-x)）。"""
    if rot == 0:
        return x, z
    if rot == 1:
        return -z, x
    if rot == 2:
        return -x, -z
    return z, -x


def _assign_chests(pieces: list[EndPiece], world_seed: int,
                   version_key: str) -> None:
    """按 xp End_City 分支逐 piece 填箱子坐标 + LootTableSeed。

    流分组（xp 原文注释：假设无跨 piece 同区块箱）：单箱独立流
    skip1 取1；双箱同 piece 同区块 → 同流 skip2 取2，跨区块 →
    各自流 skip1 取1。step/decorator 见 loot_rng._SALT_1194/118 的
    end_city 条目。
    """
    step, decorator = loot_rng.salt_configs_for_version(version_key)["end_city"]

    def _flow(cx: int, cz: int):
        pop = loot_rng.get_population_seed(world_seed, cx & ~15, cz & ~15)
        return loot_rng.XoroshiroJava(pop + decorator + 10000 * step)

    for p in pieces:
        if p.type == FAT_TOWER_TOP:
            offs = ((3, 11), (5, 13))
        elif p.type == END_SHIP:
            offs = ((5, 7), (7, 7))
        elif p.type == THIRD_FLOOR_2:
            offs = ((6, 2),)
        else:
            continue
        bx = p.pos[0] - 1
        bz = p.pos[2] - 1
        coords = []
        for ox, oz in offs:
            rx, rz = _rot_xz(p.rot, ox, oz)
            coords.append((bx + rx, bz + rz))
        seeds = []
        if len(coords) == 1:
            (x1, z1), = coords
            rng = _flow(x1, z1)
            rng.next_long()                # placeInWorld 写入的种子，未使用
            seeds.append(rng.next_long())
        else:
            (x1, z1), (x2, z2) = coords
            if (x1 >> 4) == (x2 >> 4) and (z1 >> 4) == (z2 >> 4):
                rng = _flow(x1, z1)
                rng.next_long()
                rng.next_long()
                seeds.append(rng.next_long())
                seeds.append(rng.next_long())
            else:
                rng = _flow(x1, z1)
                rng.next_long()
                seeds.append(rng.next_long())
                rng = _flow(x2, z2)
                rng.next_long()
                seeds.append(rng.next_long())
        for (cx, cz), sd in zip(coords, seeds):
            p.chests.append((cx, cz, _LOOT_TABLE, sd))


# ---------------------------------------------------------------------------
# 公共入口
# ---------------------------------------------------------------------------

def build_end_city(world_seed: int, block_x: int, block_z: int,
                   version_key: str = "1.21") -> EndCityResult:
    """getEndCityPieces + xp End_City loot 流 -> EndCityResult。

    block_x/block_z 为方块坐标（内部 &~15 取区块角；cubiomes 以
    chunkX=blockX>>4 调 getEndCityPieces）；piece 坐标为世界绝对
    坐标（y 为相对高度，首件 y=0）。
    """
    min_bx = block_x & ~15
    min_bz = block_z & ~15
    rng = structure_map.chunk_generate_rnd(world_seed,
                                           min_bx >> 4, min_bz >> 4)
    rot, rng = mc_random.next_int(rng, 4)
    ship = [0]
    env = _Env(rng, ship)
    x = min_bx + 8                          # chunkX * 16 + 8
    z = min_bz + 8
    base = _add_piece(env, None, rot, x, 0, z, BASE_FLOOR)
    base = _add_piece(env, base, rot, -1, 0, -1, SECOND_FLOOR_1)
    base = _add_piece(env, base, rot, -1, 4, -1, THIRD_FLOOR_1)
    base = _add_piece(env, base, rot, -1, 8, -1, THIRD_ROOF)
    _gen_recursively(_gen_tower, env, base, 1)
    _assign_chests(env.pieces, world_seed, version_key)
    return EndCityResult((min_bx, min_bz), rot, env.pieces,
                         bool(ship[0]), env.rng)


# ---------------------------------------------------------------------------
# 体素拼装（显示模型 / 对拍测试）
# ---------------------------------------------------------------------------

_RAW_CACHE: dict = {}


def _raw_template(name: str) -> dict:
    """模板 NBT -> 原始方块名体素 dict（缓存）。

    key = 模板名（如 "base_floor" -> templates/endcity__base_floor.nbt）；
    值 = (方块名, 形状码|None)（Properties 经
    block_shapes.shape_from_props 转形状码）。air 保留在原始 dict
    中（材质映射阶段剔除）。
    """
    cached = _RAW_CACHE.get(name)
    if cached is not None:
        return cached
    from Utils.SeedReverser import structure_models
    from Utils.SeedReverser import block_shapes as bs
    path = os.path.join(structure_models.TEMPLATE_DIR,
                        f"endcity__{name}.nbt")
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
        nm = structure_models._palette_entry_name(entry)
        props = structure_models._palette_entry_props(entry)
        shape = bs.shape_from_palette(nm, props)
        names.append((nm, shape))
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
    _RAW_CACHE[name] = out
    return out


def _rot_xz3(rot: int, x: int, y: int, z: int) -> tuple[int, int, int]:
    """无修正旋转 R（三维版，y 不变）。"""
    if rot == 0:
        return x, y, z
    if rot == 1:
        return -z, y, x
    if rot == 2:
        return -x, y, -z
    return z, y, -x


def end_city_raw_voxels(pieces, anchor: tuple[int, int]) -> dict:
    """piece 列表 + anchor -> 原始方块名拼装体素（对拍测试用）。

    坐标口径同 end_city_voxels：(x,z) = 世界 - anchor、y = 世界 - 64；
    值 = (方块名, 形状码|None) 或方块名。
    """
    ax, az = anchor
    vox: dict = {}
    for p in pieces:
        raw = _raw_template(p.name)
        ox, oy, oz = p.pos[0] - 1, p.pos[1], p.pos[2] - 1
        for (x, y, z), val in raw.items():
            nm, shp = val if isinstance(val, tuple) else (val, None)
            rx, ry, rz = _rot_xz3(p.rot, x, y, z)
            vox[(ox + rx - ax, oy + ry - 64, oz + rz - az)] = \
                (nm, shp) if shp is not None else nm
    return vox


def end_city_voxels(pieces, anchor: tuple[int, int]) -> dict:
    """piece 列表 + anchor -> 拼装显示体素（材质映射后）。

    逐 piece 加载模板（局部 (1,y,1) 锚点），无修正旋转 R 后平移到
    世界坐标；材质映射 structure_models._map_block（air/
    structure_block 映射为 None 自动剔除），形状码随 piece 旋转
    同步（shape_rotation 与 R 同族，stairs/chest/panel/bar 朝向
    一致）。模型口径：{(wx-ax, wy-64, wz-az): 材质}。覆盖顺序 =
    pieces 列表顺序（与 Java postProcess 同序，后写覆盖先写）。
    """
    from Utils.SeedReverser import structure_models
    from Utils.SeedReverser import block_shapes as bs
    ax, az = anchor
    vox: dict = {}
    for p in pieces:
        raw = _raw_template(p.name)
        if not raw:
            continue
        ox, oy, oz = p.pos[0] - 1, p.pos[1], p.pos[2] - 1
        for (x, y, z), val in raw.items():
            nm, shp = val if isinstance(val, tuple) else (val, None)
            mat = structure_models._map_block(nm, "half")
            if mat is None:
                continue
            rx, ry, rz = _rot_xz3(p.rot, x, y, z)
            wx, wy, wz = ox + rx, oy + ry, oz + rz
            if shp is not None:
                shp = bs.shape_rotation(shp, p.rot)
            base = mat[len("halfheight:"):] \
                if mat.startswith("halfheight:") else mat
            if shp is None and mat.startswith("halfheight:"):
                shp = bs.SHAPE_SLAB_BOT
            vox[(wx - ax, wy - 64, wz - az)] = \
                (base, shp) if shp is not None else base
    return vox
