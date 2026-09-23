# -*- coding: utf-8 -*-
"""要塞（Stronghold）拼装引擎 + 战利品流模拟。

拼装 RNG = LegacyRandom（java.util.Random 48 位 LCG）：
    Structure.GenerationContext（Java 1.21）= new WorldgenRandom(
        new LegacyRandomSource(0L)) + c(seed, chunkX, chunkZ)
        = setLargeFeatureSeed = xp fork chunkGenerateRnd（finders.h L597-604）。
    复用 structure_map.chunk_generate_rnd + mc_random 函数式 API。

重试循环（StrongholdStructure.java L24-45）：
    do {
        builder.clear();
        rng.setLargeFeatureSeed(seed + attempt++, chunkX, chunkZ);
        start = StartPiece(rng, cx*16+2, 64, cz*16+2);  // facing = nextInt(4)
    } while (portalRoomPiece == null)
主循环（Java L37-41 = xp L431-443）：
    while queue: queue.remove(nextInt(len)) → 扩展该件
    （接受件同时进 pieces 与 pendingChildren——Java b() L189-190 /
      xp 链表尾插；FillerCorridor 也入队，pop 时零消耗；
      起始件直接扩展一次、不入队；xp generationStopped = 7 个受限
      piece 全部满额除名后停机（updateGenerationStatus 循环走完
      置位）——照抄 xp：主循环 while queue and not stopped、
      _extend 开头提前 return）

loot 流 = Xoroshiro（照抄 xp features/stronghold.c getStrongholdLoot）：
    每区块（合并盒覆盖到的区块角遍历）：
        rnd = XoroshiroJ(getPopulationSeed(seed, 区块角x, 区块角z)
                         + step*10000 + decorator)
        按 piece 列表顺序对相交件（仅 xz 判定）走 postProcess 消耗；
        箱子 loot seed = nextLong（仅当箱子落在本区块才消耗）；
        眼睛 = nextFloat > 0.9F（12 次无条件消耗，bit 按坐标落区置位）

Y 沉降（moveBelowSeaLevel，xp 默认不做；Java 1.21 无条件执行）：
    k = (合并盒高度) + minWorldY(-64) + 1
    if k < 53: k += nextInt(53-k)   ← 消耗拼装终态流（不影响 loot：
      loot 为逐区块独立流，且沉降只做全体平移，isTall 等高度差不变）
    dy = k - maxY → 全体 piece y 平移

口径定案：
    - 拼装/接受判定以 xp fork features/stronghold.c 为基准（社区大规模
      验证）。已知分叉：xp 低高度 piece 接受条件 b0.y>1 / 公共路径
      「b0.y>10 且碰撞才拒绝」与 Java「minY>10 且无碰撞才接受」在
      深地下（minY<=10）语义不同——按定案照抄 xp，对拍只比
      xz / 箱子 / 眼睛 / piece 序列；
    - Library 高度选择（11 高失败降 6 高）不消耗 RNG（Java L489
      isTall = bb.e() > 6 零消耗，xp 同）；
    - 探针参考输出：xp_build/probe_sh_out.txt（probe_sh.c）。
"""

from __future__ import annotations

from typing import Optional

# --- 项目内依赖（与 composition.py 同口径：项目根须在 sys.path，
#     即从 MCHelper 根目录运行；结构上对齐 fortress_pieces.py）------
from Utils.Public import structure_map      # noqa: F401
from Utils.SeedReverser import mc_random          # noqa: F401
from .loot_rng import XoroshiroJava, get_population_seed, _M64  # noqa: F401

# ---------------------------------------------------------------------------
# piece 类型（xp stronghold.h 枚举顺序）
# ---------------------------------------------------------------------------

SH_STRAIGHT = 0
SH_PRISON_HALL = 1
SH_LEFT_TURN = 2
SH_RIGHT_TURN = 3
SH_ROOM_CROSSING = 4
SH_STRAIGHT_STAIRS_DOWN = 5
SH_STAIRS_DOWN = 6
SH_FIVE_CROSSING = 7
SH_CHEST_CORRIDOR = 8
SH_LIBRARY = 9
SH_PORTAL_ROOM = 10
SH_FILLER_CORRIDOR = 11
SH_PIECE_COUNT = 12

# 名称表（xp stronghold_info name 列）
SH_NAMES = ("SHS", "SHPH", "SHLT", "SHRT", "SHRC", "SHSSD", "SHSD", "SH5C",
            "SHCC", "SHLi", "SHPR", "SHFC")

# (offset, size, weight, maxPlaceCount, minDepth)（xp stronghold_info L25-42）
SH_INFO = (
    ((-1, -1, 0), (5, 5, 7), 40, 0, 0),     # STRAIGHT
    ((-1, -1, 0), (9, 5, 11), 5, 5, 0),     # PRISON_HALL
    ((-1, -1, 0), (5, 5, 5), 20, 0, 0),     # LEFT_TURN
    ((-1, -1, 0), (5, 5, 5), 20, 0, 0),     # RIGHT_TURN
    ((-4, -1, 0), (11, 7, 11), 10, 6, 0),   # ROOM_CROSSING
    ((-1, -7, 0), (5, 11, 8), 5, 5, 0),     # STRAIGHT_STAIRS_DOWN
    ((-1, -7, 0), (5, 11, 5), 5, 5, 0),     # STAIRS_DOWN
    ((-4, -3, 0), (10, 9, 11), 5, 4, 0),    # FIVE_CROSSING
    ((-1, -1, 0), (5, 5, 7), 5, 4, 0),      # CHEST_CORRIDOR
    ((-4, -1, 0), (14, 11, 15), 10, 2, 5),  # LIBRARY
    ((-4, -1, 0), (11, 8, 16), 20, 1, 6),   # PORTAL_ROOM
    ((-1, -1, 0), (5, 5, 4), -1, -1, -1),   # FILLER_CORRIDOR（不参选）
)

SH_TOTAL_WEIGHT = 145  # Σ weight（StrongholdPieces.a() 重置后的初值）

# 传送门房间 12 个眼睛框的局部坐标 (x, z)（y 恒 3；xp eye_positions L527-540）
EYE_POSITIONS = ((4, 8), (5, 8), (6, 8), (4, 12), (5, 12), (6, 12),
                 (3, 9), (3, 10), (3, 11), (7, 9), (7, 10), (7, 11))

# loot 表键（xp 写法；composition 层转快照名）
LOOT_CORRIDOR = "chests/stronghold_corridor"
LOOT_CROSSING = "chests/stronghold_crossing"
LOOT_LIBRARY = "chests/stronghold_library"


def loot_table_for_version(table: str, version_key: str) -> str:
    """表名 -> 带档后缀表名（C loot_tables.c L296-311 分档）。

    引擎（simulate_loot_stream）输出保持 xp 规范表名；本映射供
    composition 层把档后缀写入 Chest.loot_table，使快照加载层
    （load_loot_snapshot 无分档记录时直接命中 <表>.<档>.json）选对
    档。解析 era 仍由运行时版本推导（本结构快照均无 tag/options
    引用，era 差异仅在附魔函数，与快照档同源自洽）。
    定案：crossing C 端恒 1_13 档（单文件）；library -> 1_20；
    corridor：版本线收敛（26.2/1.21.11/1.21 三键）后恒 1_21_9 档
    （"26." 前缀覆盖 26.2/26.3；1_21_6 档项目无对应版本键，
    不引入）。
    """
    if table == LOOT_CROSSING:
        return table
    v = str(version_key)
    if table == LOOT_LIBRARY:
        return LOOT_LIBRARY + ".1_20"
    if table == LOOT_CORRIDOR:
        if v.startswith(("1.21.9", "1.21.11", "26.")):
            return LOOT_CORRIDOR + ".1_21_9"
        return LOOT_CORRIDOR + ".1_20"
    return table

_SALT_STRONGHOLD_1194 = (4, 19)   # finders.c L357-361（1.19.4+ 档）


def stronghold_salt(version_key: str = "1.21") -> tuple[int, int]:
    """stronghold 的 (generation_step, decorator_index)。"""
    return _SALT_STRONGHOLD_1194


# ---------------------------------------------------------------------------
# 几何辅助（xp finders.h / stronghold.c）
# ---------------------------------------------------------------------------

def orient_box(pos, offset, size, facing):
    """xp orientBox（finders.h L72-97）→ (bb0, bb1)。

    bb1 = 含端点最大方块角（Java maxX/maxY/maxZ 语义）。
    pos/offset/size 均为 (x, y, z)。
    """
    ox, oy, oz = offset
    sx, sy, sz = size
    px, py, pz = pos
    y0 = py + oy
    y1 = py + oy + sy - 1
    if facing == 0:      # north
        b0 = (px + ox, y0, pz + oz - sz + 1)
        b1 = (px + ox + sx - 1, y1, pz + oz)
    elif facing == 1:    # east
        b0 = (px + oz, y0, pz + ox)
        b1 = (px + oz + sz - 1, y1, pz + ox + sx - 1)
    elif facing == 2:    # south
        b0 = (px + ox, y0, pz + oz)
        b1 = (px + ox + sx - 1, y1, pz + oz + sz - 1)
    elif facing == 3:    # west
        b0 = (px + oz - sz + 1, y0, pz + ox)
        b1 = (px + oz, y1, pz + ox + sx - 1)
    else:
        raise ValueError(f"bad facing {facing}")
    return b0, b1


def boxes_intersect(a0, a1, b0, b1):
    """xp hasIntersection（finders.h L100-104）。"""
    return (a1[0] >= b0[0] and a0[0] <= b1[0]
            and a1[2] >= b0[2] and a0[2] <= b1[2]
            and a1[1] >= b0[1] and a0[1] <= b1[1])


def rot_pos(bb0, bb1, lx, lz, rot):
    """xp rotPos（stronghold.c L482-492）：局部 (x, z) → 世界 (x, z)。"""
    if rot == 0:
        return bb0[0] + lx, bb1[2] - lz
    if rot == 1:
        return bb0[0] + lz, bb0[2] + lx
    if rot == 2:
        return bb0[0] + lx, bb0[2] + lz
    if rot == 3:
        return bb1[0] - lz, bb0[2] + lx
    raise ValueError(f"bad rot {rot}")


# ---------------------------------------------------------------------------
# 拼装（getStrongholdPieces 移植）
# ---------------------------------------------------------------------------

class _SHEnv:
    """拼装环境（xp StrongholdPieceEnv）。

    list  = 已接受 pieces（接受序，xp 数组）
    queue = 待扩展子件（xp 链表 list->next..；Java pendingChildren）
    """

    __slots__ = ("state", "list", "queue", "portal", "imposed_piece",
                 "typlast", "ntyp", "deltyp", "total_weight",
                 "gen_stopped", "nmax")

    def __init__(self, state: int, nmax: int = 512) -> None:
        self.state = state
        self.list: list[dict] = []
        self.queue: list[dict] = []
        self.portal = False
        self.imposed_piece: Optional[int] = None
        self.typlast = -1
        self.ntyp = [0] * 11
        self.deltyp = 0
        self.total_weight = SH_TOTAL_WEIGHT
        self.gen_stopped = False
        self.nmax = nmax          # xp SH_PIECE_BUF，探针同 512


def _has_collision(env: _SHEnv, b0, b1):
    """xp hasCollision：返回第一个相交 piece（Java findCollisionPiece）。"""
    for q in env.list:
        if boxes_intersect(q["bb0"], q["bb1"], b0, b1):
            return q
    return None


def _add_piece(env: _SHEnv, typ: int, x: int, y: int, z: int,
               depth: int, facing: int) -> bool:
    """xp addStrongholdPiece（stronghold.c L77-198）。

    返回是否接受。构造期 RNG 仅在接受成功路径消耗（Java 各 piece
    构造；Library 高度选择与 FillerCorridor 零消耗）。
    """
    offset = SH_INFO[typ][0]
    size = list(SH_INFO[typ][1])

    if typ == SH_LIBRARY:
        # xp L98-105：先试 11 高（minY>10 且无碰撞 → 直接接受），
        # 否则降 6 高走公共路径。高度选择不消耗 RNG。
        b0, b1 = orient_box((x, y, z), offset, size, facing)
        if b0[1] > 10 and _has_collision(env, b0, b1) is None:
            pass  # L_box_end（11 高接受）
        else:
            size[1] = 6
            b0, b1 = orient_box((x, y, z), offset, size, facing)
            # 公共路径（xp L133-136）：minY>10 且有碰撞才拒绝
            if b0[1] > 10 and _has_collision(env, b0, b1) is not None:
                return False
    elif typ == SH_FILLER_CORRIDOR:
        # xp L106-129：必须有碰撞 piece 且同 minY；z 从 2 收缩到 1
        # 找不重叠的最短段，接受条件 b0.y > 1（1.21 分支 minI=1）。
        b0, b1 = orient_box((x, y, z), offset, size, facing)
        p = _has_collision(env, b0, b1)
        if p is None:
            return False
        if p["bb0"][1] != b0[1]:
            return False
        for i in (2, 1):
            size[2] = i
            b0, b1 = orient_box((x, y, z), offset, size, facing)
            if boxes_intersect(p["bb0"], p["bb1"], b0, b1):
                continue
            size[2] = i + 1
            b0, b1 = orient_box((x, y, z), offset, size, facing)
            if b0[1] > 1:
                break
        else:
            return False
    else:
        # 公共路径（xp L133-136）
        b0, b1 = orient_box((x, y, z), offset, size, facing)
        if b0[1] > 10 and _has_collision(env, b0, b1) is not None:
            return False

    piece = {
        "type": typ, "name": SH_NAMES[typ], "pos": (x, y, z),
        "bb0": b0, "bb1": b1, "rot": facing, "depth": depth,
        "add": 0, "chests": [], "eyes": 0,
    }

    # 构造期 RNG（Java 各 piece 构造；与 xp L150-181 一致）。
    # entry_door：Java nextInt(5) 原始值（0/1=OPENING、2=WOOD_DOOR、
    # 3=GRATES、4=IRON_DOOR，几何层映射）；rc_type：RoomCrossing
    # type 完整值（0..4，add bit0 = type==2 仅是兼容投影）。
    # 两者只加存储，不改变消耗顺序（对拍不敏感）。
    st = env.state
    if typ == SH_STRAIGHT:
        v, st = mc_random.next_int(st, 5)            # entryDoor
        piece["entry_door"] = v
        st = mc_random.next_state(st)
        piece["add"] |= (1 if (st >> 47) == 0 else 0) << 0   # leftChild
        st = mc_random.next_state(st)
        piece["add"] |= (1 if (st >> 47) == 0 else 0) << 1   # rightChild
    elif typ in (SH_PRISON_HALL, SH_LEFT_TURN, SH_RIGHT_TURN,
                 SH_STRAIGHT_STAIRS_DOWN, SH_STAIRS_DOWN,
                 SH_CHEST_CORRIDOR, SH_LIBRARY):
        v, st = mc_random.next_int(st, 5)            # entryDoor
        piece["entry_door"] = v
    elif typ == SH_ROOM_CROSSING:
        v, st = mc_random.next_int(st, 5)            # entryDoor
        piece["entry_door"] = v
        v2, st = mc_random.next_int(st, 5)           # type（L888）
        piece["rc_type"] = v2
        piece["add"] |= (1 if v2 == 2 else 0) << 0   # 有箱变体
    elif typ == SH_FIVE_CROSSING:
        v, st = mc_random.next_int(st, 5)            # entryDoor
        piece["entry_door"] = v
        st = mc_random.next_state(st)                # leftLow = nextBoolean
        piece["add"] |= (st >> 47) << 0
        st = mc_random.next_state(st)                # leftHigh
        piece["add"] |= (st >> 47) << 1
        st = mc_random.next_state(st)                # rightLow
        piece["add"] |= (st >> 47) << 2
        v, st = mc_random.next_int(st, 3)            # rightHigh
        piece["add"] |= (1 if v > 0 else 0) << 3
    elif typ == SH_PORTAL_ROOM:
        env.portal = True                            # 构造零消耗（Java L129）
    # SH_FILLER_CORRIDOR / SH_ROOM_*：无额外消耗
    env.state = st

    env.list.append(piece)
    env.queue.append(piece)      # xp 链表尾插 / Java pendingChildren.add
    if len(env.list) >= env.nmax:            # xp L194-196
        env.gen_stopped = True
    return True


def _update_generation_status(env: _SHEnv) -> None:
    """xp updateGenerationStatus（stronghold.c L53-64）。

    只要还存在未除名的受限 piece（placeCount < weight，即还能继续
    放置）就不停机；全部受限 piece 满额除名后循环走完 → 置位。
    """
    for typ in range(11):
        if (env.deltyp >> typ) & 1:
            continue
        max_count = SH_INFO[typ][3]
        weight = SH_INFO[typ][2]
        if max_count > 0 and env.ntyp[typ] < weight:
            return
    env.gen_stopped = True


def _extend(env: _SHEnv, piece: dict, x: int, y: int, z: int,
            facing: int) -> None:
    """xp extendStronghold（stronghold.c L200-247）。"""
    if piece["depth"] > 50:
        return

    # 112 格半径限制（Java b() L186 同；以起始件 bb0 为参考点）
    s0 = env.list[0]["bb0"]
    if abs(x - s0[0]) > 112 or abs(z - s0[2]) > 112:
        return

    if env.gen_stopped:                      # xp L209-211
        return

    depth = piece["depth"] + 1

    if env.imposed_piece is not None:
        imposed = env.imposed_piece
        env.imposed_piece = None
        if _add_piece(env, imposed, x, y, z, depth, facing):
            return

    for _attempt in range(5):
        sel, env.state = mc_random.next_int(env.state, env.total_weight)
        placed = False
        for typ in range(11):
            if (env.deltyp >> typ) & 1:
                continue
            weight = SH_INFO[typ][2]
            sel -= weight
            if sel >= 0:
                continue
            count = env.ntyp[typ]
            max_count = SH_INFO[typ][3]
            min_depth = SH_INFO[typ][4]
            # xp canPlace + typlast（Java L158：!a(depth) || ==previousPiece）
            if (max_count != 0 and count >= max_count) \
                    or depth < min_depth or typ == env.typlast:
                break
            if not _add_piece(env, typ, x, y, z, depth, facing):
                continue
            count += 1
            env.ntyp[typ] = count
            env.typlast = typ
            if max_count != 0 and count >= max_count:
                # xp：满额除名 → updateGenerationStatus（可达，见上）
                env.total_weight -= weight
                env.deltyp |= 1 << typ
                _update_generation_status(env)
            placed = True
            break
        if placed:
            return

    _add_piece(env, SH_FILLER_CORRIDOR, x, y, z, depth, facing)


def _child_forward(env: _SHEnv, piece: dict, offx: int, offy: int) -> None:
    """xp generateSmallDoorChildForward（stronghold.c L249-266）。"""
    rot = piece["rot"]
    bb0, bb1 = piece["bb0"], piece["bb1"]
    if rot == 0:
        _extend(env, piece, bb0[0] + offx, bb0[1] + offy, bb0[2] - 1, 0)
    elif rot == 2:
        _extend(env, piece, bb0[0] + offx, bb0[1] + offy, bb1[2] + 1, 2)
    elif rot == 3:
        _extend(env, piece, bb0[0] - 1, bb0[1] + offy, bb0[2] + offx, 3)
    else:  # rot == 1
        _extend(env, piece, bb1[0] + 1, bb0[1] + offy, bb0[2] + offx, 1)


def _child_left(env: _SHEnv, piece: dict, offy: int, offz: int) -> None:
    """xp generateSmallDoorChildLeft（stronghold.c L268-280）。"""
    rot = piece["rot"]
    bb0, bb1 = piece["bb0"], piece["bb1"]
    if rot in (0, 2):
        _extend(env, piece, bb0[0] - 1, bb0[1] + offy, bb0[2] + offz, 3)
    else:
        _extend(env, piece, bb0[0] + offz, bb0[1] + offy, bb0[2] - 1, 0)


def _child_right(env: _SHEnv, piece: dict, offy: int, offz: int) -> None:
    """xp generateSmallDoorChildRight（stronghold.c L282-294）。"""
    rot = piece["rot"]
    bb0, bb1 = piece["bb0"], piece["bb1"]
    if rot in (0, 2):
        _extend(env, piece, bb1[0] + 1, bb0[1] + offy, bb0[2] + offz, 1)
    else:
        _extend(env, piece, bb0[0] + offz, bb0[1] + offy, bb1[2] + 1, 2)


def _extend_piece(env: _SHEnv, piece: dict) -> None:
    """xp extendStrongholdPiece（stronghold.c L296-371）。"""
    typ = piece["type"]
    if typ == SH_STRAIGHT:
        _child_forward(env, piece, 1, 1)
        if piece["add"] & (1 << 0):
            _child_left(env, piece, 1, 2)
        if piece["add"] & (1 << 1):
            _child_right(env, piece, 1, 2)
    elif typ in (SH_PRISON_HALL, SH_CHEST_CORRIDOR, SH_STRAIGHT_STAIRS_DOWN):
        _child_forward(env, piece, 1, 1)
    elif typ == SH_LEFT_TURN:
        if piece["rot"] in (0, 1):
            _child_left(env, piece, 1, 1)
        else:
            _child_right(env, piece, 1, 1)
    elif typ == SH_RIGHT_TURN:
        if piece["rot"] in (0, 1):
            _child_right(env, piece, 1, 1)
        else:
            _child_left(env, piece, 1, 1)
    elif typ == SH_ROOM_CROSSING:
        _child_forward(env, piece, 4, 1)
        _child_left(env, piece, 1, 4)
        _child_right(env, piece, 1, 4)
    elif typ == SH_STAIRS_DOWN:
        if piece["add"] != 0:                    # 起始件（isSource）
            env.imposed_piece = SH_FIVE_CROSSING
        _child_forward(env, piece, 1, 1)
    elif typ == SH_FIVE_CROSSING:
        n, n2 = 3, 5
        if piece["rot"] in (3, 0):
            n, n2 = 8 - n, 8 - n2
        _child_forward(env, piece, 5, 1)
        if piece["add"] & (1 << 0):
            _child_left(env, piece, n, 1)
        if piece["add"] & (1 << 1):
            _child_left(env, piece, n2, 7)
        if piece["add"] & (1 << 2):
            _child_right(env, piece, n, 1)
        if piece["add"] & (1 << 3):
            _child_right(env, piece, n2, 7)
    # LIBRARY / PORTAL_ROOM / FILLER_CORRIDOR：无子件


def _apply_sink(pieces: list[dict], state: int) -> int:
    """Java 1.21 moveBelowSeaLevel（StructurePiecesBuilder L33-44）。

    在拼装终态流上消耗 nextInt(53-k)（Java 同一流；不影响 loot——
    loot 为逐区块独立流，且沉降为全体平移，isTall 等高度差不变）。
    返回消耗后的流状态。
    """
    min_y = min(p["bb0"][1] for p in pieces)
    max_y = max(p["bb1"][1] for p in pieces)
    height = max_y - min_y + 1
    k = height + (-64) + 1
    if k < 53:
        v, state = mc_random.next_int(state, 53 - k)
        k += v
    dy = k - max_y
    if dy:
        for p in pieces:
            p["bb0"] = (p["bb0"][0], p["bb0"][1] + dy, p["bb0"][2])
            p["bb1"] = (p["bb1"][0], p["bb1"][1] + dy, p["bb1"][2])
            p["pos"] = (p["pos"][0], p["pos"][1] + dy, p["pos"][2])
    return state


def assemble_stronghold(world_seed: int, chunk_x: int, chunk_z: int,
                        sink_y: bool = True) -> list[dict]:
    """getStrongholdPieces 全流程（含重试循环与可选 Java Y 沉降）。

    返回 piece dict 列表（bb0/bb1 为含端点闭区间，Java 语义）。
    sink_y=True 时按 Java 1.21 moveBelowSeaLevel 沉降（xp 默认不做；
    沉降只影响 y，xz/箱子/眼睛与 xp 完全一致）。
    """
    x = (chunk_x << 4) + 2
    z = (chunk_z << 4) + 2

    attempt = 0
    pieces: list[dict] = []
    env: Optional[_SHEnv] = None
    while True:
        attempt += 1
        # Java：setLargeFeatureSeed(seed + attempt++, cx, cz)，每次独立播种
        state = structure_map.chunk_generate_rnd(world_seed + attempt - 1,
                                                 chunk_x, chunk_z)
        # StartPiece：facing = nextInt(4)，entryDoor 恒 OPENING（零消耗），
        # bb = pos 按朝向扩展（xp L408-424；5×5 足印朝向对称）
        rot, state = mc_random.next_int(state, 4)
        size = SH_INFO[SH_STAIRS_DOWN][1]
        start = {
            "type": SH_STAIRS_DOWN, "name": SH_NAMES[SH_STAIRS_DOWN],
            "pos": (x, 64, z), "rot": rot, "depth": 0, "add": 1,
            "chests": [], "eyes": 0,
            "entry_door": 0,     # StartPiece 恒 OPENING（L1033 零消耗）
            "bb0": (x, 64, z),
            "bb1": ((x + size[0] - 1, 64 + size[1] - 1, z + size[2] - 1)
                    if rot in (0, 2) else
                    (x + size[2] - 1, 64 + size[1] - 1, z + size[0] - 1)),
        }

        env = _SHEnv(state)
        env.list.append(start)
        # ntyp[STAIRS_DOWN]=0 / typlast=-1：起始件不经权重路径（Java
        # previousPiece=null、placeCount 未计），后续仍可选 5 个 StairsDown
        _extend_piece(env, start)

        while env.queue and not env.gen_stopped:   # xp L431 同条件
            idx, env.state = mc_random.next_int(env.state, len(env.queue))
            cur = env.queue.pop(idx)
            _extend_piece(env, cur)

        pieces = env.list
        if env.portal:
            break

    if sink_y:
        _apply_sink(pieces, env.state)
    return pieces


# ---------------------------------------------------------------------------
# loot 流（getStrongholdLoot 移植：逐区块 Xoroshiro）
# ---------------------------------------------------------------------------

def _generate_box_skip(piece_bb0, piece_bb1, piece_rot, cx, cz,
                       x0, y0, z0, x1, y1, z1, rng: XoroshiroJava) -> None:
    """xp generateBox（stronghold.c L494-520）。

    对应 Java「带 SmoothStoneSelector 的填充」：nextFloat 只在世界坐标
    落在 [cx, cx+16)×[cz, cz+16) 的壳层体素消耗（StructurePiece.java
    L260-269：区块外体素 getBlockState 短路为 AIR → 选择器不调用）。
    """
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            for z in range(z0, z1 + 1):
                tx, tz = rot_pos(piece_bb0, piece_bb1, x, z, piece_rot)
                if cx <= tx < cx + 16 and cz <= tz < cz + 16:
                    if y == y0 or y == y1 or x == x0 or x == x1 \
                            or z == z0 or z == z1:
                        rng.next_float()


def simulate_loot_stream(world_seed: int, pieces: list[dict],
                         version_key: str = "1.21") -> None:
    """getStrongholdLoot 的 loot/眼睛段（就地填 piece["chests"]/["eyes"]）。

    piece 列表来自 assemble_stronghold（沉降与否均可：沉降为全体平移，
    isTall 高度差不变，逐区块相交与消耗只依赖 xz）。
    """
    step, decorator = stronghold_salt(version_key)
    count = len(pieces)

    min_x = min(p["bb0"][0] for p in pieces)
    min_z = min(p["bb0"][2] for p in pieces)
    max_x = max(p["bb1"][0] for p in pieces)
    max_z = max(p["bb1"][2] for p in pieces)

    for p in pieces:
        p["chests"] = []
        p["eyes"] = 0

    for cx in range(min_x & ~15, (max_x & ~15) + 1, 16):
        for cz in range(min_z & ~15, (max_z & ~15) + 1, 16):
            pop = get_population_seed(world_seed, cx, cz)
            rng = XoroshiroJava((pop + decorator + 10000 * step) & _M64)
            for i in range(count):
                p = pieces[i]
                pb0, pb1, prot = p["bb0"], p["bb1"], p["rot"]
                if not (pb1[0] >= cx and pb0[0] <= cx + 15
                        and pb1[2] >= cz and pb0[2] <= cz + 15):
                    continue
                typ = p["type"]
                if typ == SH_STRAIGHT:
                    _generate_box_skip(pb0, pb1, prot, cx, cz,
                                       0, 0, 0, 4, 4, 6, rng)
                    for _ in range(4):
                        rng.next_float()
                elif typ == SH_PRISON_HALL:
                    _generate_box_skip(pb0, pb1, prot, cx, cz,
                                       0, 0, 0, 8, 4, 10, rng)
                    rng.skip_n(12)
                elif typ == SH_LEFT_TURN or typ == SH_RIGHT_TURN:
                    _generate_box_skip(pb0, pb1, prot, cx, cz,
                                       0, 0, 0, 4, 4, 4, rng)
                elif typ == SH_ROOM_CROSSING:
                    _generate_box_skip(pb0, pb1, prot, cx, cz,
                                       0, 0, 0, 10, 6, 10, rng)
                    if p["add"] & 1:
                        wx, wz = rot_pos(pb0, pb1, 3, 8, prot)
                        if cx <= wx < cx + 16 and cz <= wz < cz + 16:
                            p["chests"].append(
                                {"x": wx, "y": pb0[1] + 4, "z": wz,
                                 "table": LOOT_CROSSING,
                                 "seed": rng.next_long()})
                elif typ == SH_STRAIGHT_STAIRS_DOWN:
                    _generate_box_skip(pb0, pb1, prot, cx, cz,
                                       0, 0, 0, 4, 10, 7, rng)
                elif typ == SH_STAIRS_DOWN:
                    _generate_box_skip(pb0, pb1, prot, cx, cz,
                                       0, 0, 0, 4, 10, 4, rng)
                elif typ == SH_FIVE_CROSSING:
                    _generate_box_skip(pb0, pb1, prot, cx, cz,
                                       0, 0, 0, 9, 8, 10, rng)
                    rng.skip_n(109)
                elif typ == SH_CHEST_CORRIDOR:
                    _generate_box_skip(pb0, pb1, prot, cx, cz,
                                       0, 0, 0, 4, 4, 6, rng)
                    wx, wz = rot_pos(pb0, pb1, 3, 3, prot)
                    if cx <= wx < cx + 16 and cz <= wz < cz + 16:
                        p["chests"].append(
                            {"x": wx, "y": pb0[1] + 2, "z": wz,
                             "table": LOOT_CORRIDOR,
                             "seed": rng.next_long()})
                elif typ == SH_LIBRARY:
                    is_tall = pb1[1] - pb0[1] + 1 > 6
                    cur_h = 11 if is_tall else 6
                    _generate_box_skip(pb0, pb1, prot, cx, cz,
                                       0, 0, 0, 13, cur_h - 1, 14, rng)
                    # generateMaybeBox(2,1,1,11,4,13)：
                    # skip = 4*10*13 = 520（xp L522-525）
                    rng.skip_n(520)
                    wx, wz = rot_pos(pb0, pb1, 3, 5, prot)
                    if cx <= wx < cx + 16 and cz <= wz < cz + 16:
                        p["chests"].append(
                            {"x": wx, "y": pb0[1] + 3, "z": wz,
                             "table": LOOT_LIBRARY,
                             "seed": rng.next_long()})
                    if is_tall:
                        wx, wz = rot_pos(pb0, pb1, 12, 1, prot)
                        if cx <= wx < cx + 16 and cz <= wz < cz + 16:
                            p["chests"].append(
                                {"x": wx, "y": pb0[1] + 8, "z": wz,
                                 "table": LOOT_LIBRARY,
                                 "seed": rng.next_long()})
                elif typ == SH_PORTAL_ROOM:
                    rng.skip_n(760)              # the famous 760 skips
                    for j, (ex, ez) in enumerate(EYE_POSITIONS):
                        if rng.next_float() > 0.9:
                            wx, wz = rot_pos(pb0, pb1, ex, ez, prot)
                            if cx <= wx < cx + 16 and cz <= wz < cz + 16:
                                p["eyes"] |= 1 << j
                # SH_FILLER_CORRIDOR：无消耗


def compose_stronghold_pieces(world_seed: int, chunk_x: int, chunk_z: int,
                              version_key: str = "1.21") -> list[dict]:
    """组装入口：拼装（含 Java Y 沉降）+ loot 流。

    返回 piece dict 列表，含：
        type/name/pos/rot/depth/bb0/bb1/add
        entry_door: 构造期 nextInt(5) 原始值（门型映射见 _door_type）
        rc_type:    RoomCrossing type 完整值 0..4（仅该类型）
        chests: [{x, z, table, seed}]（世界 xz 方块坐标）
        eyes:   int（PORTAL_ROOM 12 位 bit 数组；非 portal_room 恒 0）
    """
    pieces = assemble_stronghold(world_seed, chunk_x, chunk_z, sink_y=True)
    simulate_loot_stream(world_seed, pieces, version_key)
    return pieces


# ---------------------------------------------------------------------------
# 几何转写（postProcess 移植：StrongholdPieces.java L232-1226 逐段；
# 材质/形状码约定同 fortress_pieces.py）
#
# generateBox 语义（StructurePiece 字节码定案）：
# - (..., true, rnd, SMOOTH_STONE_SELECTOR)：skipAir=true → 仅边界格
#   写（selector 恒石砖，定案不做风化变体），内部**不动**（保留先写，
#   piece 互不重叠 + FillerCorridor 专门填缝 → 等价空气）；
# - (..., false, rnd, SELECTOR)：全格写：边界石砖、内部 CAVE_AIR
#   （体素 pop）；
# - (stateA, stateB, false)：全格写（A=边界 B=内部；本结构全部 A==B
#   或单层/单柱薄盒——任一轴单格时全盒恒"边界"）；
# - 后写胜出；AIR = 体素 pop；createChest/spawner 恒放（chunk 剪裁
#   预览无意义）；概率填充（cobweb 0.07F / Straight 火把 0.1F）不
#   做：cobweb 恒不放、火把恒放（RNG 消耗已由 loot 流 skip 处理，
#   几何层零 RNG）。
#
# 方向性方块：门/墙上火把/梯子/按钮的水平 FACING 与楼梯 FACING 同类
# （HorizontalDirectional 语义），净效果同 _WX_STAIRS 表（fortress
# 字节码定案）；torch/panel/button 形状码取映射后世界朝向的反侧
# （wall_panel_edge：FACING=朝外、贴边=反侧）。
#
# 材质键（assets/SeedReverser/textures/block/<键>.png）：
#   缺失纹理替代定案：END_PORTAL_FRAME→"end_stone_bricks"（有眼整格
#   /无眼半砖区分）、END_PORTAL→"obsidian"、STONE_BUTTON→"stone"、
#   INFESTED_STONE_BRICKS→"stone bricks"（恒石砖）。
# ---------------------------------------------------------------------------

from Utils.SeedReverser import block_shapes as bs          # noqa: E402
from .fortress_pieces import _Ctx as _FCtx                 # noqa: E402
from .fortress_pieces import _PieceBB, _WX_STAIRS          # noqa: E402

SB = "stone bricks"              # SmoothStoneSelector 恒石砖（定案）
SB_STAIRS = "stone brick stairs"
SB_SLAB = "stone brick slab"     # SMOOTH_STONE_SLAB（bottom）；DOUBLE=整格
COBBLE = "cobblestone"
COBBLE_STAIRS = "cobblestone stairs"
PLANKS = "oak planks"
BOOKSHELF_M = "bookshelf"
BARS_M = "iron bars"
FENCE_M = "oak fence"
LADDER_M = "ladder"
LAVA_M = "lava"
WATER_M = "water"
SPAWNER_M = "spawner"
TORCH_M = "torch"
FRAME_M = "end portal frame side"    # END_PORTAL_FRAME（jar 模型 side 面）
FRAME_EYE_M = "end portal frame eye"  # 有眼：顶面=眼纹理（_FULL_FACES 分面）
PORTAL_M = "end portal"              # END_PORTAL（entity 星空纹理）
BUTTON_M = "stone"               # STONE_BUTTON 无专用纹理（定案）
CHEST_M = "chest"                # 须含 "chest"（_face_mat 分面判定）
OAK_DOOR_M = "oak door bottom"   # 门双纹理由 _mat_shape 按半区自动换
IRON_DOOR_M = "iron door bottom"

_OPP = {"n": "s", "s": "n", "e": "w", "w": "e"}

_SLAB = (SB_SLAB, bs.SHAPE_SLAB_BOT)
_BARS = (BARS_M, bs.SHAPE_PANE)
_FENCE = (FENCE_M, bs.SHAPE_FENCE_POST)


class _CtxS(_FCtx):
    """stronghold postProcess 上下文（复用 fortress _Ctx 的 place/box/
    air_box；补楼梯材质与 torch/panel/button/door 方向性方法）。"""

    def wx_dir(self, local: str) -> str:
        """局部水平朝向 -> 世界朝向（placeBlock mirror/rotate 净效果）。"""
        return _WX_STAIRS[self.facing].get(local, local)

    def stairs(self, x: int, y: int, z: int, local: str) -> None:
        self.place(x, y, z, (SB_STAIRS, bs.SHAPE_STAIRS[self.wx_dir(local)]))

    def torch_wall(self, x: int, y: int, z: int, local: str) -> None:
        # 方向链字节码定案（1.21.11）：placeBlock 先 state.mirror 后
        # state.rotate；setOrientation 派生 N→(NONE,NONE) S→(LEFT_RIGHT,
        # NONE) W→(LEFT_RIGHT,CW90) E→(NONE,CW90)；Mirror 对水平
        # FACING 译为 E↔W（CW180），rotate CW90 = N→E→S→W。净效果
        # 即 _WX_STAIRS，贴附墙 = 世界 FACING 反侧（canSurvive 链）。
        # mirror 组合走廊火把指向 sel_box 内部空气格 → 悬空系游戏原样。
        self.place(x, y, z, (TORCH_M, "torch:" + _OPP[self.wx_dir(local)]))

    def torch_post(self, x: int, y: int, z: int) -> None:
        self.place(x, y, z, (TORCH_M, bs.SHAPE_TORCH_V))

    def panel(self, x: int, y: int, z: int, local: str, mat: str) -> None:
        self.place(x, y, z, (mat, "panel:" + _OPP[self.wx_dir(local)]))

    def button(self, x: int, y: int, z: int, local: str) -> None:
        self.place(x, y, z, (BUTTON_M, "button:" + _OPP[self.wx_dir(local)]))

    def door(self, x: int, y: int, z: int, mat: str,
             local: str = "n") -> None:
        """门（恒关闭、铰链左——关闭几何与铰链无关；块默认 FACING=
        NORTH，PrisonHall 铁门显式 WEST 由 local 指定）。"""
        self.place(x, y, z,
                   (mat, "door:l:c:" + self.wx_dir(local) + ":left"))

    def chest(self, x: int, y: int, z: int) -> None:
        self.place(x, y, z, (CHEST_M, bs.SHAPE_CHEST_N))

    def sel_box(self, x0: int, y0: int, z0: int, x1: int, y1: int,
                z1: int, hollow: bool) -> None:
        """SMOOTH_STONE_SELECTOR generateBox（几何层恒 stone bricks）。

        hollow=True（skipAir=true）：边界写石砖、内部不动；
        hollow=False：边界石砖、内部显式挖空（体素 pop）。
        """
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                for z in range(z0, z1 + 1):
                    if (x == x0 or x == x1 or y == y0 or y == y1
                            or z == z0 or z == z1):
                        self.place(x, y, z, SB)
                    elif not hollow:
                        self.place(x, y, z, None)


def _door_type(c: _CtxS, typ: int, x: int, y: int, z: int) -> None:
    """StrongholdPiece.a(...)（L1245-1301）：entryDoor 门型。

    typ = 构造期 nextInt(5) 原始值（0/1=OPENING、2=WOOD_DOOR、
    3=GRATES、4=IRON_DOOR，L1303-1317）。OAK/IRON_DOOR 未显式设
    FACING → 块默认 NORTH（局部）；GRATES 铁栏杆臂由 pane 自动连臂。
    """
    if typ in (0, 1):                # OPENING：3x3 挖空
        c.air_box(x, y, z, x + 2, y + 2, z)
    elif typ == 2:                   # WOOD_DOOR：石砖框 + 橡木门
        c.place(x, y, z, SB)
        c.place(x, y + 1, z, SB)
        c.place(x, y + 2, z, SB)
        c.place(x + 1, y + 2, z, SB)
        c.place(x + 2, y + 2, z, SB)
        c.place(x + 2, y + 1, z, SB)
        c.place(x + 2, y, z, SB)
        c.door(x + 1, y, z, OAK_DOOR_M)
        c.door(x + 1, y + 1, z, OAK_DOOR_M)
    elif typ == 3:                   # GRATES：中空 + 铁栏杆包边
        c.place(x + 1, y, z, None)
        c.place(x + 1, y + 1, z, None)
        c.place(x, y, z, _BARS)
        c.place(x, y + 1, z, _BARS)
        for gx in (x, x + 1, x + 2):
            c.place(gx, y + 2, z, _BARS)
        c.place(x + 2, y + 1, z, _BARS)
        c.place(x + 2, y, z, _BARS)
    elif typ == 4:                   # IRON_DOOR：石砖框 + 铁门 + 按钮
        c.place(x, y, z, SB)
        c.place(x, y + 1, z, SB)
        c.place(x, y + 2, z, SB)
        c.place(x + 1, y + 2, z, SB)
        c.place(x + 2, y + 2, z, SB)
        c.place(x + 2, y + 1, z, SB)
        c.place(x + 2, y, z, SB)
        c.door(x + 1, y, z, IRON_DOOR_M)
        c.door(x + 1, y + 1, z, IRON_DOOR_M)
        c.button(x + 2, y + 1, z + 1, "n")   # FACING=NORTH（L1298）
        c.button(x + 2, y + 1, z - 1, "s")   # FACING=SOUTH（L1299）


# ============================================================ piece 布局

def _piece_chest_corridor(c: _CtxS, ed: int) -> None:
    # ChestCorridor.postProcess（L233-251）
    c.sel_box(0, 0, 0, 4, 4, 6, True)
    _door_type(c, ed, 1, 1, 0)
    _door_type(c, 0, 1, 1, 6)                    # 出口恒 OPENING
    c.box(3, 1, 2, 3, 1, 4, SB)
    c.place(3, 1, 1, _SLAB)
    c.place(3, 1, 5, _SLAB)
    c.place(3, 2, 2, _SLAB)
    c.place(3, 2, 4, _SLAB)
    for z in (2, 3, 4):
        c.place(2, 1, z, _SLAB)
    c.chest(3, 2, 3)                             # 局部 (3,2,3)（L249）


def _piece_filler_corridor(c: _CtxS, steps: int) -> None:
    # FillerCorridor.postProcess（L294-317）；steps 从 bb 现算（L260：
    # N/S → zSpan、E/W → xSpan，由调用方传入）
    for z in range(steps):
        c.box(0, 0, z, 4, 0, z, SB)
        for y in (1, 2, 3):
            c.place(0, y, z, SB)
            c.air_box(1, y, z, 3, y, z)
            c.place(4, y, z, SB)
        c.box(0, 4, z, 4, 4, z, SB)


def _piece_five_crossing(c: _CtxS, ed: int, add: int) -> None:
    # FiveCrossing.postProcess（L389-436）
    c.sel_box(0, 0, 0, 9, 8, 10, True)
    _door_type(c, ed, 4, 3, 0)
    if add & (1 << 0):                           # leftLow
        c.air_box(0, 3, 1, 0, 5, 3)
    if add & (1 << 2):                           # rightLow
        c.air_box(9, 3, 1, 9, 5, 3)
    if add & (1 << 1):                           # leftHigh
        c.air_box(0, 5, 7, 0, 7, 9)
    if add & (1 << 3):                           # rightHigh
        c.air_box(9, 5, 7, 9, 7, 9)
    c.air_box(5, 1, 10, 7, 3, 10)
    c.sel_box(1, 2, 1, 8, 2, 6, False)           # 单层薄盒全石砖
    c.sel_box(4, 1, 5, 4, 4, 9, False)           # 单柱
    c.sel_box(8, 1, 5, 8, 4, 9, False)
    c.sel_box(1, 4, 7, 3, 4, 9, False)
    c.sel_box(1, 3, 5, 3, 3, 6, False)
    c.box(1, 3, 4, 3, 3, 4, _SLAB)
    c.box(1, 4, 6, 3, 4, 6, _SLAB)
    c.sel_box(5, 1, 7, 7, 1, 8, False)
    c.box(5, 1, 9, 7, 1, 9, _SLAB)
    c.box(5, 2, 7, 7, 2, 7, _SLAB)
    c.box(4, 5, 7, 4, 5, 9, _SLAB)
    c.box(8, 5, 7, 8, 5, 9, _SLAB)
    c.box(5, 5, 7, 7, 5, 9, SB_SLAB)             # DOUBLE slab = 整格
    c.torch_wall(6, 5, 6, "s")                   # FACING=SOUTH（L435）


def _piece_left_turn(c: _CtxS, ed: int) -> None:
    # LeftTurn.postProcess（L465-475）
    c.sel_box(0, 0, 0, 4, 4, 4, True)
    _door_type(c, ed, 1, 1, 0)
    if c.facing not in (0, 1):                   # != NORTH && != EAST
        c.air_box(4, 1, 1, 4, 3, 3)
    else:
        c.air_box(0, 1, 1, 0, 3, 3)


def _piece_right_turn(c: _CtxS, ed: int) -> None:
    # RightTurn.postProcess（L866-875）
    c.sel_box(0, 0, 0, 4, 4, 4, True)
    _door_type(c, ed, 1, 1, 0)
    if c.facing not in (0, 1):
        c.air_box(0, 1, 1, 0, 3, 3)
    else:
        c.air_box(4, 1, 1, 4, 3, 3)


def _piece_library(c: _CtxS, ed: int, is_tall: bool) -> None:
    # Library.postProcess（L515-627）；is_tall = bb y 跨度 > 6（L489）
    h = 11 if is_tall else 6
    c.sel_box(0, 0, 0, 13, h - 1, 14, True)
    _door_type(c, ed, 4, 1, 0)
    # cobweb maybeBox(0.07F, L524)：几何层跳过（RNG 由 loot 流
    # skip_n(520) 处理）
    for z in range(1, 14):                       # 侧壁书架/木柱（L528-546）
        wall_m = PLANKS if (z - 1) % 4 == 0 else BOOKSHELF_M
        c.box(1, 1, z, 1, 4, z, wall_m)
        c.box(12, 1, z, 12, 4, z, wall_m)
        if is_tall:
            c.box(1, 6, z, 1, 9, z, wall_m)
            c.box(12, 6, z, 12, 9, z, wall_m)
        if (z - 1) % 4 == 0:                     # z=1,5,9,13 火把
            c.torch_wall(2, 3, z, "e")           # FACING=EAST
            c.torch_wall(11, 3, z, "w")          # FACING=WEST
    for z in (3, 5, 7, 9, 11):                   # 中层书架（L548-552）
        c.box(3, 1, z, 4, 3, z, BOOKSHELF_M)
        c.box(6, 1, z, 7, 3, z, BOOKSHELF_M)
        c.box(9, 1, z, 10, 3, z, BOOKSHELF_M)
    if is_tall:
        c.box(1, 5, 1, 3, 5, 13, PLANKS)         # 夹层（L555-561）
        c.box(10, 5, 1, 12, 5, 13, PLANKS)
        c.box(4, 5, 1, 9, 5, 2, PLANKS)
        c.box(4, 5, 12, 9, 5, 13, PLANKS)
        c.place(9, 5, 11, PLANKS)
        c.place(8, 5, 11, PLANKS)
        c.place(9, 5, 10, PLANKS)
        # 栏杆臂（L562-586；统一 post 形状码，connect_arms 连臂）
        c.box(3, 6, 3, 3, 6, 11, _FENCE)
        c.box(10, 6, 3, 10, 6, 9, _FENCE)
        c.box(4, 6, 2, 9, 6, 2, _FENCE)
        c.box(4, 6, 12, 7, 6, 12, _FENCE)
        c.place(3, 6, 2, _FENCE)
        c.place(3, 6, 12, _FENCE)
        c.place(10, 6, 2, _FENCE)
        for k in range(3):                       # L572-586
            c.place(8 + k, 6, 12 - k, _FENCE)
            if k != 2:
                c.place(8 + k, 6, 11 - k, _FENCE)
        for y in range(1, 8):                    # 梯子 1..7（L588-595）
            c.panel(10, y, 13, "s", LADDER_M)    # FACING=SOUTH
        # 中央柱栏杆细节（L596-612）
        c.place(6, 9, 7, _FENCE)
        c.place(7, 9, 7, _FENCE)
        c.place(6, 8, 7, _FENCE)
        c.place(7, 8, 7, _FENCE)
        c.place(6, 7, 7, _FENCE)
        c.place(7, 7, 7, _FENCE)
        c.place(5, 7, 7, _FENCE)
        c.place(8, 7, 7, _FENCE)
        c.place(6, 7, 6, _FENCE)
        c.place(6, 7, 8, _FENCE)
        c.place(7, 7, 6, _FENCE)
        c.place(7, 7, 8, _FENCE)
        for tx, ty, tz in ((5, 8, 7), (8, 8, 7), (6, 8, 6),
                           (6, 8, 8), (7, 8, 6), (7, 8, 8)):
            c.torch_post(tx, ty, tz)             # 立式火把（L613-619）
    c.chest(3, 3, 5)                             # 箱1（L622）
    if is_tall:
        c.place(12, 9, 1, None)                  # 挖空（L624）
        c.chest(12, 8, 1)                        # 箱2（L625）


def _piece_portal_room(c: _CtxS, ed: int, eyes: int) -> None:
    # PortalRoom.postProcess（L686-769）
    c.sel_box(0, 0, 0, 10, 7, 15, False)         # 实心：壳层+内部挖空
    _door_type(c, 3, 4, 1, 0)                    # 恒 GRATES（L688）
    c.sel_box(1, 6, 1, 1, 6, 14, False)          # y6 回廊（L690-693）
    c.sel_box(9, 6, 1, 9, 6, 14, False)
    c.sel_box(2, 6, 1, 8, 6, 2, False)
    c.sel_box(2, 6, 14, 8, 6, 14, False)
    c.sel_box(1, 1, 1, 2, 1, 4, False)           # y1 平台（L694-695）
    c.sel_box(8, 1, 1, 9, 1, 4, False)
    c.box(1, 1, 1, 1, 1, 3, LAVA_M)              # 角落岩浆（L696-697）
    c.box(9, 1, 1, 9, 1, 3, LAVA_M)
    c.sel_box(3, 1, 8, 7, 1, 12, False)          # 中央平台（L698）
    c.box(4, 1, 9, 6, 1, 11, LAVA_M)             # 中心岩浆（L699）
    for z in (3, 5, 7, 9, 11, 13):               # 铁栏杆（L703-710）
        c.box(0, 3, z, 0, 4, z, _BARS)
        c.box(10, 3, z, 10, 4, z, _BARS)
    for x in (2, 4, 6, 8):
        c.box(x, 3, 15, x, 4, 15, _BARS)
    c.sel_box(4, 1, 5, 6, 1, 7, False)           # 楼梯垫层（L713-715）
    c.sel_box(4, 2, 6, 6, 2, 7, False)
    c.sel_box(4, 3, 7, 6, 3, 7, False)
    for x in (4, 5, 6):
        c.stairs(x, 1, 4, "n")                   # FACING=NORTH（L712）
        c.stairs(x, 2, 5, "n")
        c.stairs(x, 3, 6, "n")
    # 12 框架：坐标序 = EYE_POSITIONS = Java $$19[0..11]（L735-746）
    for j, (fx, fz) in enumerate(EYE_POSITIONS):
        if (eyes >> j) & 1:
            c.place(fx, 3, fz, FRAME_EYE_M)      # 框+眼 → 整格（顶面=眼）
        else:
            c.place(fx, 3, fz, FRAME_M)          # 空框 → 整格（13/16 近似）
    if eyes == 0xFFF:                            # 全眼 → 传送门（L747-758）
        for px in (4, 5, 6):
            for pz in (9, 10, 11):
                c.place(px, 3, pz, PORTAL_M)
    c.place(5, 3, 6, SPAWNER_M)                  # 蠹虫刷怪笼（L760-764）


def _piece_prison_hall(c: _CtxS, ed: int) -> None:
    # PrisonHall.postProcess（L799-836）
    c.sel_box(0, 0, 0, 8, 4, 10, True)
    _door_type(c, ed, 1, 1, 0)
    c.air_box(1, 1, 10, 3, 3, 10)
    c.sel_box(4, 1, 1, 4, 3, 1, False)           # 中央柱（L803-806）
    c.sel_box(4, 1, 3, 4, 3, 3, False)
    c.sel_box(4, 1, 7, 4, 3, 7, False)
    c.sel_box(4, 1, 9, 4, 3, 9, False)
    for y in (1, 2, 3):                          # 牢房铁栏杆（L808-826）
        c.place(4, y, 4, _BARS)
        c.place(4, y, 5, _BARS)
        c.place(4, y, 6, _BARS)
        c.place(5, y, 5, _BARS)
        c.place(6, y, 5, _BARS)
        c.place(7, y, 5, _BARS)
    c.place(4, 3, 2, _BARS)                      # 封顶（L828-829）
    c.place(4, 3, 8, _BARS)
    c.door(4, 1, 2, IRON_DOOR_M, "w")            # 铁门 FACING=WEST
    c.door(4, 2, 2, IRON_DOOR_M, "w")
    c.door(4, 1, 8, IRON_DOOR_M, "w")
    c.door(4, 2, 8, IRON_DOOR_M, "w")


def _piece_room_crossing(c: _CtxS, ed: int, rc_type: int) -> None:
    # RoomCrossing.postProcess（L915-1000）
    c.sel_box(0, 0, 0, 10, 6, 10, True)
    _door_type(c, ed, 4, 1, 0)
    c.air_box(4, 1, 10, 6, 3, 10)                # 三向通道（L918-920）
    c.air_box(0, 1, 4, 0, 3, 6)
    c.air_box(10, 1, 4, 10, 3, 6)
    if rc_type == 0:                             # 火把柱（L922-938）
        c.place(5, 1, 5, SB)
        c.place(5, 2, 5, SB)
        c.place(5, 3, 5, SB)
        c.torch_wall(4, 3, 5, "w")               # FACING=WEST
        c.torch_wall(6, 3, 5, "e")               # FACING=EAST
        c.torch_wall(5, 3, 4, "s")               # FACING=SOUTH
        c.torch_wall(5, 3, 6, "n")               # FACING=NORTH
        for x in (4, 6):
            for z in (4, 5, 6):
                c.place(x, 1, z, _SLAB)
        c.place(5, 1, 4, _SLAB)
        c.place(5, 1, 6, _SLAB)
    elif rc_type == 1:                           # 水池（L939-951）
        for k in range(5):
            c.place(3, 1, 3 + k, SB)
            c.place(7, 1, 3 + k, SB)
            c.place(3 + k, 1, 3, SB)
            c.place(3 + k, 1, 7, SB)
        c.place(5, 1, 5, SB)
        c.place(5, 2, 5, SB)
        c.place(5, 3, 5, SB)
        c.place(5, 4, 5, WATER_M)
    elif rc_type == 2:                           # 阁楼（L952-998）
        for i in range(1, 10):
            c.place(i, 3, 1, COBBLE)
            c.place(i, 3, 9, COBBLE)
            c.place(1, 3, i, COBBLE)
            c.place(9, 3, i, COBBLE)
        c.place(5, 1, 4, COBBLE)
        c.place(5, 1, 6, COBBLE)
        c.place(5, 3, 4, COBBLE)
        c.place(5, 3, 6, COBBLE)
        c.place(4, 1, 5, COBBLE)
        c.place(6, 1, 5, COBBLE)
        c.place(4, 3, 5, COBBLE)
        c.place(6, 3, 5, COBBLE)
        for y in (1, 2, 3):                      # 四角柱（L972-977）
            for px, pz in ((4, 4), (6, 4), (4, 6), (6, 6)):
                c.place(px, y, pz, COBBLE)
        c.torch_wall(5, 3, 5, "n")               # 默认 FACING=NORTH
        for z in range(2, 9):                    # 木板层（L981-992）
            c.place(2, 3, z, PLANKS)
            c.place(3, 3, z, PLANKS)
            if z <= 3 or z >= 7:
                c.place(4, 3, z, PLANKS)
                c.place(5, 3, z, PLANKS)
                c.place(6, 3, z, PLANKS)
            c.place(7, 3, z, PLANKS)
            c.place(8, 3, z, PLANKS)
        for y in (1, 2, 3):                      # 梯子 FACING=WEST
            c.panel(9, y, 3, "w", LADDER_M)
        c.chest(3, 4, 8)                         # 箱在木板层上方（L998）


def _piece_stairs_down(c: _CtxS, ed: int) -> None:
    # StairsDown.postProcess（L1073-1094；StartPiece 同布局）
    c.sel_box(0, 0, 0, 4, 10, 4, True)
    _door_type(c, ed, 1, 7, 0)
    _door_type(c, 0, 1, 1, 4)                    # 出口恒 OPENING
    c.place(2, 6, 1, SB)
    c.place(1, 5, 1, SB)
    c.place(1, 6, 1, _SLAB)
    c.place(1, 5, 2, SB)
    c.place(1, 4, 3, SB)
    c.place(1, 5, 3, _SLAB)
    c.place(2, 4, 3, SB)
    c.place(3, 3, 3, SB)
    c.place(3, 4, 3, _SLAB)
    c.place(3, 3, 2, SB)
    c.place(3, 2, 1, SB)
    c.place(3, 3, 1, _SLAB)
    c.place(2, 2, 1, SB)
    c.place(1, 1, 1, SB)
    c.place(1, 2, 1, _SLAB)
    c.place(1, 1, 2, SB)
    c.place(1, 1, 3, _SLAB)


def _piece_straight(c: _CtxS, ed: int, add: int) -> None:
    # Straight.postProcess（L1163-1180）
    c.sel_box(0, 0, 0, 4, 4, 6, True)
    _door_type(c, ed, 1, 1, 0)
    _door_type(c, 0, 1, 1, 6)                    # 出口恒 OPENING
    # 墙上火把 0.1F（L1169-1172）：几何层恒放
    c.torch_wall(1, 2, 1, "e")
    c.torch_wall(3, 2, 1, "w")
    c.torch_wall(1, 2, 5, "e")
    c.torch_wall(3, 2, 5, "w")
    if add & (1 << 0):                           # leftChild
        c.air_box(0, 1, 2, 0, 3, 4)
    if add & (1 << 1):                           # rightChild
        c.air_box(4, 1, 2, 4, 3, 4)


def _piece_straight_stairs_down(c: _CtxS, ed: int) -> None:
    # StraightStairsDown.postProcess（L1209-1224）
    c.sel_box(0, 0, 0, 4, 10, 7, True)
    _door_type(c, ed, 1, 7, 0)
    _door_type(c, 0, 1, 1, 7)                    # 出口恒 OPENING
    for i in range(6):                           # 圆石楼梯 6 级
        for x in (1, 2, 3):
            c.stairs(x, 6 - i, 1 + i, "s")       # FACING=SOUTH
            if i < 5:
                c.place(x, 5 - i, 1 + i, SB)     # 垫层石砖


# ============================================================ 入口

def _reattach_wall_decor(vox: dict) -> list:
    """贴边装饰（torch/panel/button）贴附校正（后处理）。

    方向链逐环模拟（mirror/rotate 字节码）与游戏实测不符：用户
    在游戏内实测要塞走廊火把全部贴墙，无 mirror 组合悬空现象。
    改用物理约束：贴边格为空时从 4 个水平邻格中选实心格改贴附
    方向（单实心直接取；多实心取环向最近；全空保留，视为结构
    接口处的真悬空）。返回 [(pos, 旧shape, 新shape)]。
    """
    edge = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}
    ring = ("n", "e", "s", "w")
    fixes = []
    for pos, v in list(vox.items()):
        if not (isinstance(v, tuple) and isinstance(v[1], str)):
            continue
        kind, _, rest = v[1].partition(":")
        if kind not in ("torch", "panel", "button") or rest not in edge:
            continue
        dx, dz = edge[rest]
        if vox.get((pos[0] + dx, pos[1], pos[2] + dz)) is not None:
            continue
        cands = []
        for name, (ox, oz) in edge.items():
            nv = vox.get((pos[0] + ox, pos[1], pos[2] + oz))
            if nv is None or (isinstance(nv, tuple) and isinstance(nv[1], str)
                              and nv[1].startswith(
                                  ("torch:", "panel:", "button:"))):
                continue
            cands.append(name)
        if not cands:
            continue
        if len(cands) == 1:
            new = cands[0]
        else:
            ci = ring.index(rest)
            new = min(cands, key=lambda n: min(
                (ci - ring.index(n)) % 4, (ring.index(n) - ci) % 4))
        vox[pos] = (v[0], f"{kind}:{new}")
        fixes.append((pos, v[1], vox[pos][1]))
    return fixes


def build_stronghold_voxels(pieces: list[dict], anchor) -> dict:
    """piece dict 列表 -> 模型体素 dict {(x,y,z): 值}。

    pieces = assemble_stronghold / compose_stronghold_pieces 输出（需
    含 entry_door / add / eyes / rc_type）。按 accepted 顺序执行
    postProcess（后写胜出；AIR=体素 pop）。anchor=(ax, az)：模型
    x/z = 世界 - anchor、y = 世界 - 64（沉降后 y 可为负，同 fortress
    口径）。返回值不含箱子标注逻辑（compose_display_model 负责）。
    """
    vox: dict = {}
    ax, az = anchor
    for p in pieces:
        typ = p["type"]
        ed = p.get("entry_door", 0)
        pbb = _PieceBB((p["bb0"], p["bb1"]))
        facing = p.get("rot") or 0

        def write(wx: int, wy: int, wz: int, val):
            k = (wx - ax, wy - 64, wz - az)
            if val is None:
                vox.pop(k, None)
            else:
                vox[k] = val

        c = _CtxS(pbb, facing, write)
        if typ == SH_STAIRS_DOWN:
            _piece_stairs_down(c, ed)            # StartPiece 同布局
        elif typ == SH_STRAIGHT:
            _piece_straight(c, ed, p["add"])
        elif typ == SH_PRISON_HALL:
            _piece_prison_hall(c, ed)
        elif typ == SH_LEFT_TURN:
            _piece_left_turn(c, ed)
        elif typ == SH_RIGHT_TURN:
            _piece_right_turn(c, ed)
        elif typ == SH_ROOM_CROSSING:
            _piece_room_crossing(c, ed, p.get("rc_type", 0))
        elif typ == SH_STRAIGHT_STAIRS_DOWN:
            _piece_straight_stairs_down(c, ed)
        elif typ == SH_FIVE_CROSSING:
            _piece_five_crossing(c, ed, p["add"])
        elif typ == SH_CHEST_CORRIDOR:
            _piece_chest_corridor(c, ed)
        elif typ == SH_LIBRARY:
            is_tall = p["bb1"][1] - p["bb0"][1] + 1 > 6
            _piece_library(c, ed, is_tall)
        elif typ == SH_PORTAL_ROOM:
            _piece_portal_room(c, ed, p.get("eyes", 0))
        elif typ == SH_FILLER_CORRIDOR:
            if facing in (0, 2):                 # N/S → zSpan（L260）
                steps = p["bb1"][2] - p["bb0"][2] + 1
            else:                                # E/W → xSpan
                steps = p["bb1"][0] - p["bb0"][0] + 1
            _piece_filler_corridor(c, steps)
        # 其余（理论无）：跳过
    fixes = _reattach_wall_decor(vox)
    return vox
