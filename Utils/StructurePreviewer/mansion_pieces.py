# -*- coding: utf-8 -*-
"""StructurePreviewer：林地府邸（woodland_mansion）逐方块生成。

移植自官方映射反编译源（1.21.11 jar + SpecialSource + Vineflower）：
    net/minecraft/world/level/levelgen/structure/structures/
        WoodlandMansionPieces.java（1229 行：MansionGrid +
        MansionPiecePlacer + FloorRoomCollection + SimpleGrid）
        WoodlandMansionStructure.java（findGenerationPoint / afterPlace）
    支撑类：Structure.java（GenerationContext.makeRandom）、
        WorldgenRandom.java（setLargeFeatureSeed / setDecorationSeed /
        setFeatureSeed）、ChunkGenerator.java（applyBiomeDecoration /
        getWritableArea）、StructureStart.java（placeInChunk）、
        TemplateStructurePiece.java（postProcess）、StructurePiece.java
        （createChest）、StructureTemplate.java（transform /
        getZeroPositionWithTransform / getBoundingBox / filterBlocks /
        placeInWorld）、WoodlandMansionPiece.handleDataMarker。
    行号引用一律指 WoodlandMansionPieces.java，另注明者除外。

数据流（与游戏一致的两条独立 RNG 线）：
    结构线（模板拼装，LegacyRandomSource = 48 位 LCG）：
        GenerationContext.makeRandom（Structure.java L225-228）=
            WorldgenRandom(LegacyRandomSource).setLargeFeatureSeed(
                world_seed, chunk_x, chunk_z)
        -> Rotation.getRandom（nextInt(4)，消耗 1 次）
        -> new MansionGrid(random)（走廊/房间识别序列）
        -> MansionPiecePlacer.createMansion（房间模板名继续消耗）
        findGenerationPoint 的锚点 = getLowestYIn5by5BoxOffset7Blocks
        = BlockPos(chunk.getBlockX(7), 最低Y, chunk.getBlockZ(7))；
        Y<60 拒绝生成（地形查询不复刻，本模块 Y 固定 64）。
    装饰线（箱子 LootTableSeed，Xoroshiro128++ per-chunk）：
        ChunkGenerator.applyBiomeDecoration L290：
            pop = setDecorationSeed(world_seed, chunkX*16, chunkZ*16)
        mansion 在 SURFACE_STRUCTURES（step=4）内注册序 5
        （cl_salts_1_21_5.txt L12：4 5 minecraft:mansion）：
            setFeatureSeed(pop, 5, 4) => setSeed(pop + 40005)
        StructureStart.placeInChunk（L81-96）按 pieces 列表序，bb 与
        区块 writable box（x/z = 区块 16×16，y = [minY+1, maxY]）相交
        的 piece 依次 postProcess（同一装饰流贯穿）；
        placeInWorld 的 setBlock 不消耗装饰流；模板自带容器（实证 7 个
        模板 75 个箱子，NBT 全为固定 Items、无 LootTable 字段）是装饰
        性固定箱，setBlock 落方块时 loadContents 亦不耗流、开箱不 roll
        表；随机箱仅来自 DATA 标记 handleDataMarker("Chest*") ->
        createChest（StructurePiece.java L398-414：chunkBox 内且该处
        非 CHEST 才放置）消耗一次 nextLong() = LootTableSeed，
        每箱恰一次（73 模板共 10 个 Chest* 标记）。

坐标约定：grid (x, y) 的 y 是网格纵轴（Java 同名）；世界 (x,z) 以
findGenerationPoint 锚点（chunkBlock(7,7)）为 pos 基准，模板局部坐标
经 mirror->rot 变换（StructureTemplate.transform L483-511，pivot=0）
后加 piece pos。模型层（composition）(x,z) = 世界 - anchor、
y = 世界 - 64。
"""
from __future__ import annotations

from pathlib import Path

from Utils.MapPreviewer import structure_map
from Utils.SeedReverser import block_shapes as _bs
from Utils.SeedReverser import mc_random, structure_models
from . import loot_rng

_M64 = loot_rng._M64

# 模板资产目录：assets/SeedReverser/woodland_mansion/<模板名>.nbt
# （73 个文件，源自 1.21.11 原版 jar data/minecraft/structure/
#   woodland_mansion/，名称 = WoodlandMansionPiece.makeLocation 短名）
_ASSET_DIR = (Path(__file__).resolve().parents[2] / "assets"
              / "SeedReverser" / "woodland_mansion")

# ---------------------------------------------------------------------------
# 方向与旋转（Java 语义最小子集）
# ---------------------------------------------------------------------------
# from2DDataValue 序（Direction BY_2D_DATA）：0=S 1=W 2=N 3=E
# Plane.HORIZONTAL 迭代序（Direction.java L575）：N, E, S, W
# getClockWise: N->E, E->S, S->W, W->N（Direction.java L189-197）
# Rotation.rotate(dir)：CW90=clockwise、180=opposite、CCW90=ccw
# Rotation.getRotated：模 4 加法（Rotation.java L38-84）

_DIR_2D = ("S", "W", "N", "E")            # from2DDataValue 下标
_HORIZONTAL = ("N", "E", "S", "W")         # Plane.HORIZONTAL 迭代序
_STEP2 = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}
_STEP3 = {"N": (0, 0, -1), "S": (0, 0, 1), "W": (-1, 0, 0), "E": (1, 0, 0),
          "UP": (0, 1, 0)}
_CLOCKWISE = {"N": "E", "E": "S", "S": "W", "W": "N"}
_COUNTER_CW = {"N": "W", "W": "S", "S": "E", "E": "N"}
_OPPOSITE = {"N": "S", "S": "N", "W": "E", "E": "W"}

_ROT_NAMES = ("NONE", "CLOCKWISE_90", "CLOCKWISE_180",
              "COUNTERCLOCKWISE_90")       # Rotation.values() 序
_ROT_IDX = {n: i for i, n in enumerate(_ROT_NAMES)}
_MIRRORS = ("NONE", "LEFT_RIGHT", "FRONT_BACK")


def _rot_add(rot: str, delta: str) -> str:
    """Rotation.getRotated：旋转叠加（模 4 加法）。"""
    return _ROT_NAMES[(_ROT_IDX[rot] + _ROT_IDX[delta]) & 3]


def _rotate_dir(rot: str, d: str) -> str:
    """Rotation.rotate(Direction)：水平方向按放置旋转。"""
    if rot == "CLOCKWISE_90":
        return _CLOCKWISE[d]
    if rot == "CLOCKWISE_180":
        return _OPPOSITE[d]
    if rot == "COUNTERCLOCKWISE_90":
        return _COUNTER_CW[d]
    return d


def _rel2(pos: tuple, d: str, n: int = 1) -> tuple:
    """BlockPos.relative(水平方向, n)。"""
    return (pos[0] + _STEP2[d][0] * n, pos[1], pos[2] + _STEP2[d][1] * n)


def _rel3(pos: tuple, d: str, n: int = 1) -> tuple:
    """BlockPos.relative(方向, n)（含 UP）。"""
    s = _STEP3[d]
    return (pos[0] + s[0] * n, pos[1] + s[1] * n, pos[2] + s[2] * n)


def transform_pos(p: tuple, mirror: str, rot: str) -> tuple:
    """StructureTemplate.transform（L483-511，pivot=0）：mirror 先、rot 后。

    LEFT_RIGHT: z = -z；FRONT_BACK: x = -x；
    CW90: (-z, y, x)；180: (-x, y, -z)；CCW90: (z, y, -x)。
    """
    x, y, z = p
    if mirror == "LEFT_RIGHT":
        z = -z
    elif mirror == "FRONT_BACK":
        x = -x
    if rot == "CLOCKWISE_90":
        return (-z, y, x)
    if rot == "CLOCKWISE_180":
        return (-x, y, -z)
    if rot == "COUNTERCLOCKWISE_90":
        return (z, y, -x)
    return (x, y, z)


def blockpos_rotate(p: tuple, rot: str) -> tuple:
    """BlockPos.rotate（BlockPos.java L215-222）。"""
    x, y, z = p
    if rot == "CLOCKWISE_90":
        return (-z, y, x)
    if rot == "CLOCKWISE_180":
        return (-x, y, -z)
    if rot == "COUNTERCLOCKWISE_90":
        return (z, y, -x)
    return (x, y, z)


def zero_pos_with_transform(pos: tuple, mirror: str, rot: str,
                            sx: int, sz: int) -> tuple:
    """StructureTemplate.getZeroPositionWithTransform（L547-568）。"""
    sx -= 1
    sz -= 1
    a = sx if mirror == "FRONT_BACK" else 0
    b = sz if mirror == "LEFT_RIGHT" else 0
    if rot == "COUNTERCLOCKWISE_90":
        return (pos[0] + b, pos[1], pos[2] + sx - a)
    if rot == "CLOCKWISE_90":
        return (pos[0] + sz - b, pos[1], pos[2] + a)
    if rot == "CLOCKWISE_180":
        return (pos[0] + sx - a, pos[1], pos[2] + sz - b)
    return (pos[0] + a, pos[1], pos[2] + b)


# ---------------------------------------------------------------------------
# 结构线 RNG（LegacyRandomSource = java.util.Random 48 位 LCG）
# ---------------------------------------------------------------------------

class LegacyRandom:
    """WorldgenRandom(LegacyRandomSource) 拼装流的函数式封装。

    播种：setLargeFeatureSeed（WorldgenRandom.java L56-62）=
        setSeed(seed); l1=nextLong(); l2=nextLong();
        rnd = chunkX*l1 ^ chunkZ*l2 ^ seed; setSeed(rnd)
    与 structure_map.chunk_generate_rnd（cubiomes chunkGenerateRnd）
    完全同源，直接复用。
    """

    __slots__ = ("_s",)

    def __init__(self, state: int) -> None:
        self._s = state & mc_random._MASK48

    @classmethod
    def from_large_feature(cls, world_seed: int,
                           chunk_x: int, chunk_z: int) -> "LegacyRandom":
        return cls(structure_map.chunk_generate_rnd(world_seed,
                                                    chunk_x, chunk_z))

    def next_int(self, bound: int) -> int:
        """Java nextInt(bound)（含拒绝采样，mc_random 完整版语义）。"""
        v, self._s = mc_random.next_int(self._s, bound)
        return v

    def next_boolean(self) -> bool:
        """Java nextBoolean() = next(1) != 0。"""
        self._s = mc_random.next_state(self._s)
        return (self._s >> 47) != 0

    @property
    def state(self) -> int:
        return self._s


def util_shuffle(lst: list, rng: LegacyRandom) -> None:
    """Util.shuffle（Util.java L1000-1007）：
    for i = size; i > 1; i--: j = nextInt(i); swap(i-1, j)。"""
    for i in range(len(lst), 1, -1):
        j = rng.next_int(i)
        lst[i - 1], lst[j] = lst[j], lst[i - 1]


# ---------------------------------------------------------------------------
# SimpleGrid（WoodlandMansionPieces.java L1098-1138 逐行转写）
# ---------------------------------------------------------------------------

_CLEAR = 0
_CORRIDOR = 1
_ROOM = 2
_START_ROOM = 3
_TEST_ROOM = 4
_BLOCKED = 5
_ROOM_1X1 = 65536
_ROOM_1X2 = 131072
_ROOM_2X2 = 262144
_ROOM_ORIGIN_FLAG = 1048576
_ROOM_DOOR_FLAG = 2097152
_ROOM_STAIRS_FLAG = 4194304
_ROOM_CORRIDOR_FLAG = 8388608
_ROOM_TYPE_MASK = 983040
_ROOM_ID_MASK = 65535


class SimpleGrid:
    """width×height 网格（int[width][height]，越界读 valueIfOutside）。"""

    __slots__ = ("width", "height", "outside", "g")

    def __init__(self, width: int, height: int, value_if_outside: int) -> None:
        self.width = width
        self.height = height
        self.outside = value_if_outside
        self.g = [[0] * height for _ in range(width)]

    def set(self, x: int, y: int, v: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self.g[x][y] = v

    def set_rect(self, x0: int, y0: int, x1: int, y1: int, v: int) -> None:
        """四参 set（L1117-1123）：外层 y、内层 x，含端点，越界自动跳过。"""
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.set(x, y, v)

    def get(self, x: int, y: int) -> int:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.g[x][y]
        return self.outside

    def setif(self, x: int, y: int, cond: int, v: int) -> None:
        if self.get(x, y) == cond:
            self.set(x, y, v)

    def edges_to(self, x: int, y: int, v: int) -> bool:
        """edgesTo（L1135-1137）：四正邻任一 == v。"""
        return (self.get(x - 1, y) == v or self.get(x + 1, y) == v
                or self.get(x, y + 1) == v or self.get(x, y - 1) == v)


def _is_house(grid: SimpleGrid, x: int, y: int) -> bool:
    """MansionGrid.isHouse（L157-160）：值 ∈ {1,2,3,4}。"""
    v = grid.get(x, y)
    return v == _CORRIDOR or v == _ROOM or v == _START_ROOM or v == _TEST_ROOM


# ---------------------------------------------------------------------------
# MansionGrid（L97-396 逐行转写）
# ---------------------------------------------------------------------------

class MansionGrid:
    """11×11 三层网格生成（RNG 消耗序与 Java 逐行一致）。"""

    __slots__ = ("baseGrid", "thirdFloorGrid", "floorRooms",
                 "entranceX", "entranceY", "_rng")

    def __init__(self, rng: LegacyRandom) -> None:
        self._rng = rng
        self.entranceX = 7
        self.entranceY = 4
        # 构造 L126-135
        self.baseGrid = SimpleGrid(11, 11, _BLOCKED)
        g = self.baseGrid
        g.set_rect(7, 4, 8, 5, _START_ROOM)      # 入口房 2×2
        g.set_rect(6, 4, 6, 5, _ROOM)            # 西邻 2 格
        g.set_rect(9, 2, 10, 7, _BLOCKED)        # 东侧封死
        g.set_rect(8, 2, 8, 3, _CORRIDOR)        # 北走廊
        g.set_rect(8, 6, 8, 7, _CORRIDOR)        # 南走廊
        g.set(6, 3, _CORRIDOR)
        g.set(6, 6, _CORRIDOR)
        g.set_rect(0, 0, 11, 1, _BLOCKED)        # 北缘
        g.set_rect(0, 9, 11, 11, _BLOCKED)       # 南缘
        # 4 段递归走廊（L136-139），全部朝西延伸
        self._recursive_corridor(g, 7, 2, "W", 6)
        self._recursive_corridor(g, 7, 7, "W", 6)
        self._recursive_corridor(g, 5, 3, "W", 3)
        self._recursive_corridor(g, 5, 6, "W", 3)
        # cleanEdges 收敛（L141-142）
        while self._clean_edges(g):
            pass
        # 房间识别（L144-151）
        self.floorRooms = [SimpleGrid(11, 11, _BLOCKED) for _ in range(3)]
        self._identify_rooms(g, self.floorRooms[0])
        self._identify_rooms(g, self.floorRooms[1])
        self.floorRooms[0].set_rect(8, 4, 8, 5, _ROOM_CORRIDOR_FLAG)
        self.floorRooms[1].set_rect(8, 4, 8, 5, _ROOM_CORRIDOR_FLAG)
        # 三层（L152-154）
        self.thirdFloorGrid = SimpleGrid(11, 11, _BLOCKED)
        self._setup_third_floor()
        self._identify_rooms(self.thirdFloorGrid, self.floorRooms[2])

    # -- isRoomId / get1x2RoomDirection -----------------------------------

    def is_room_id(self, x: int, y: int, floor: int, rid: int) -> bool:
        """isRoomId（L162-164）：$$0 参数未用（反编译伪影），只查
        floorRooms[floor]。"""
        return (self.floorRooms[floor].get(x, y) & _ROOM_ID_MASK) == rid

    def get1x2RoomDirection(self, grid: SimpleGrid, x: int, y: int,
                            floor: int, rid: int) -> str | None:
        """get1x2RoomDirection（L167-175）：Plane.HORIZONTAL 序找同 id
        邻格；找不到返回 None（Java @Nullable）。"""
        for hd in _HORIZONTAL:
            if self.is_room_id(x + _STEP2[hd][0], y + _STEP2[hd][1],
                               floor, rid):
                return hd
        return None

    # -- recursiveCorridor（L177-204）--------------------------------------

    def _recursive_corridor(self, grid: SimpleGrid, x: int, y: int,
                            d: str, depth: int) -> None:
        if depth > 0:
            grid.set(x, y, _CORRIDOR)
            grid.setif(x + _STEP2[d][0], y + _STEP2[d][1],
                       _CLEAR, _CORRIDOR)
            for _ in range(8):
                # from2DDataValue(nextInt(4))：0=S 1=W 2=N 3=E
                nd = _DIR_2D[self._rng.next_int(4)]
                # 短路求值：nd != EAST 时不消耗 nextBoolean
                if nd != _OPPOSITE[d] and (nd != "E"
                                           or not self._rng.next_boolean()):
                    fx = x + _STEP2[d][0]
                    fy = y + _STEP2[d][1]
                    if (grid.get(fx + _STEP2[nd][0], fy + _STEP2[nd][1])
                            == _CLEAR
                            and grid.get(fx + 2 * _STEP2[nd][0],
                                         fy + 2 * _STEP2[nd][1]) == _CLEAR):
                        self._recursive_corridor(
                            grid, x + _STEP2[d][0] + _STEP2[nd][0],
                            y + _STEP2[d][1] + _STEP2[nd][1], nd, depth - 1)
                        break
            cw = _CLOCKWISE[d]
            ccw = _COUNTER_CW[d]
            grid.setif(x + _STEP2[cw][0], y + _STEP2[cw][1], _CLEAR, _ROOM)
            grid.setif(x + _STEP2[ccw][0], y + _STEP2[ccw][1],
                       _CLEAR, _ROOM)
            grid.setif(x + _STEP2[d][0] + _STEP2[cw][0],
                       y + _STEP2[d][1] + _STEP2[cw][1], _CLEAR, _ROOM)
            grid.setif(x + _STEP2[d][0] + _STEP2[ccw][0],
                       y + _STEP2[d][1] + _STEP2[ccw][1], _CLEAR, _ROOM)
            grid.setif(x + 2 * _STEP2[d][0], y + 2 * _STEP2[d][1],
                       _CLEAR, _ROOM)
            grid.setif(x + 2 * _STEP2[cw][0], y + 2 * _STEP2[cw][1],
                       _CLEAR, _ROOM)
            grid.setif(x + 2 * _STEP2[ccw][0], y + 2 * _STEP2[ccw][1],
                       _CLEAR, _ROOM)

    # -- cleanEdges（L206-236）----------------------------------------------

    def _clean_edges(self, grid: SimpleGrid) -> bool:
        changed = False
        for y in range(grid.height):
            for x in range(grid.width):
                if grid.get(x, y) == _CLEAR:
                    n = 0
                    n += 1 if _is_house(grid, x + 1, y) else 0
                    n += 1 if _is_house(grid, x - 1, y) else 0
                    n += 1 if _is_house(grid, x, y + 1) else 0
                    n += 1 if _is_house(grid, x, y - 1) else 0
                    if n >= 3:
                        grid.set(x, y, _ROOM)
                        changed = True
                    elif n == 2:
                        k = 0
                        k += 1 if _is_house(grid, x + 1, y + 1) else 0
                        k += 1 if _is_house(grid, x - 1, y + 1) else 0
                        k += 1 if _is_house(grid, x + 1, y - 1) else 0
                        k += 1 if _is_house(grid, x - 1, y - 1) else 0
                        if k <= 1:
                            grid.set(x, y, _ROOM)
                            changed = True
        return changed

    # -- identifyRooms（L296-395）--------------------------------------------

    def _identify_rooms(self, grid: SimpleGrid, rooms: SimpleGrid) -> None:
        cells: list[tuple[int, int]] = []
        for y in range(grid.height):
            for x in range(grid.width):
                if grid.get(x, y) == _ROOM:
                    cells.append((x, y))
        util_shuffle(cells, self._rng)
        next_id = 10                              # L308：id 从 10 起
        for x, y in cells:
            if rooms.get(x, y) != 0:
                continue
            x0 = x1 = x
            y0 = y1 = y
            kind = _ROOM_1X1
            if (rooms.get(x + 1, y) == 0 and rooms.get(x, y + 1) == 0
                    and rooms.get(x + 1, y + 1) == 0
                    and grid.get(x + 1, y) == _ROOM
                    and grid.get(x, y + 1) == _ROOM
                    and grid.get(x + 1, y + 1) == _ROOM):
                x1, y1 = x + 1, y + 1             # 东南 2×2
                kind = _ROOM_2X2
            elif (rooms.get(x - 1, y) == 0 and rooms.get(x, y + 1) == 0
                    and rooms.get(x - 1, y + 1) == 0
                    and grid.get(x - 1, y) == _ROOM
                    and grid.get(x, y + 1) == _ROOM
                    and grid.get(x - 1, y + 1) == _ROOM):
                x0, y1 = x - 1, y + 1             # 西南 2×2
                kind = _ROOM_2X2
            elif (rooms.get(x - 1, y) == 0 and rooms.get(x, y - 1) == 0
                    and rooms.get(x - 1, y - 1) == 0
                    and grid.get(x - 1, y) == _ROOM
                    and grid.get(x, y - 1) == _ROOM
                    and grid.get(x - 1, y - 1) == _ROOM):
                x0, y0 = x - 1, y - 1             # 西北 2×2
                kind = _ROOM_2X2
            elif (rooms.get(x + 1, y) == 0
                    and grid.get(x + 1, y) == _ROOM):
                x1 = x + 1                        # 东向 1×2
                kind = _ROOM_1X2
            elif (rooms.get(x, y + 1) == 0
                    and grid.get(x, y + 1) == _ROOM):
                y1 = y + 1                        # 南向 1×2
                kind = _ROOM_1X2
            elif (rooms.get(x - 1, y) == 0
                    and grid.get(x - 1, y) == _ROOM):
                x0 = x - 1                        # 西向 1×2
                kind = _ROOM_1X2
            elif (rooms.get(x, y - 1) == 0
                    and grid.get(x, y - 1) == _ROOM):
                y0 = y - 1                        # 北向 1×2
                kind = _ROOM_1X2
            # 门位（L362-380）：两次 nextBoolean 恒消耗；True 取 min 角
            door_x = x0 if self._rng.next_boolean() else x1
            door_y = y0 if self._rng.next_boolean() else y1
            door_flag = _ROOM_DOOR_FLAG
            if not grid.edges_to(door_x, door_y, _CORRIDOR):
                door_x = x0 if door_x == x1 else x1      # 换 x
                door_y = y0 if door_y == y1 else y1      # 换 y
                if not grid.edges_to(door_x, door_y, _CORRIDOR):
                    door_y = y0 if door_y == y1 else y1  # 换 y
                    if not grid.edges_to(door_x, door_y, _CORRIDOR):
                        door_x = x0 if door_x == x1 else x1  # 换 x
                        door_y = y0 if door_y == y1 else y1  # 换 y
                        if not grid.edges_to(door_x, door_y, _CORRIDOR):
                            door_flag = 0
                            door_x, door_y = x0, y0
            for yy in range(y0, y1 + 1):
                for xx in range(x0, x1 + 1):
                    if xx == door_x and yy == door_y:
                        rooms.set(xx, yy, _ROOM_ORIGIN_FLAG | door_flag
                                  | kind | next_id)
                    else:
                        rooms.set(xx, yy, kind | next_id)
            next_id += 1

    # -- setupThirdFloor（L238-294）------------------------------------------

    def _setup_third_floor(self) -> None:
        f1 = self.floorRooms[1]
        candidates: list[tuple[int, int]] = []
        for y in range(11):
            for x in range(11):
                v = f1.get(x, y)
                if ((v & _ROOM_TYPE_MASK) == _ROOM_1X2
                        and (v & _ROOM_DOOR_FLAG) == _ROOM_DOOR_FLAG):
                    candidates.append((x, y))
        t = self.thirdFloorGrid
        if not candidates:
            t.set_rect(0, 0, 10, 10, _BLOCKED)
            return
        cx, cy = candidates[self._rng.next_int(len(candidates))]
        v = f1.get(cx, cy)
        f1.set(cx, cy, v | _ROOM_STAIRS_FLAG)
        d = self.get1x2RoomDirection(self.baseGrid, cx, cy, 1,
                                     v & _ROOM_ID_MASK)
        # 1x2 门格必有同 id 邻格，d 恒非 None（防御性兜底）
        if d is None:                             # pragma: no cover
            t.set_rect(0, 0, 10, 10, _BLOCKED)
            f1.set(cx, cy, v)
            return
        nx = cx + _STEP2[d][0]
        ny = cy + _STEP2[d][1]
        for yy in range(11):
            for xx in range(11):
                if not _is_house(self.baseGrid, xx, yy):
                    t.set(xx, yy, _BLOCKED)
                elif xx == cx and yy == cy:
                    t.set(xx, yy, _START_ROOM)
                elif xx == nx and yy == ny:
                    t.set(xx, yy, _START_ROOM)
                    self.floorRooms[2].set(xx, yy, _ROOM_CORRIDOR_FLAG)
        open_dirs: list[str] = []
        for hd in _HORIZONTAL:
            if t.get(nx + _STEP2[hd][0], ny + _STEP2[hd][1]) == _CLEAR:
                open_dirs.append(hd)
        if not open_dirs:
            t.set_rect(0, 0, 10, 10, _BLOCKED)
            f1.set(cx, cy, v)                     # L285：回滚 stairs 旗标
            return
        d2 = open_dirs[self._rng.next_int(len(open_dirs))]
        self._recursive_corridor(t, nx + _STEP2[d2][0], ny + _STEP2[d2][1],
                                 d2, 4)
        while self._clean_edges(t):
            pass


# ---------------------------------------------------------------------------
# 楼层模板名（FloorRoomCollection：L44-79 / L1061-1096 / L1140-1141）
# ---------------------------------------------------------------------------

class _FirstFloor:
    """FirstFloorRoomCollection。"""

    @staticmethod
    def get1x1(rng: LegacyRandom) -> str:
        return "1x1_a" + str(rng.next_int(5) + 1)

    @staticmethod
    def get1x1Secret(rng: LegacyRandom) -> str:
        return "1x1_as" + str(rng.next_int(4) + 1)

    @staticmethod
    def get1x2Side(rng: LegacyRandom, stairs: bool) -> str:
        return "1x2_a" + str(rng.next_int(9) + 1)

    @staticmethod
    def get1x2Front(rng: LegacyRandom, stairs: bool) -> str:
        return "1x2_b" + str(rng.next_int(5) + 1)

    @staticmethod
    def get1x2Secret(rng: LegacyRandom) -> str:
        return "1x2_s" + str(rng.next_int(2) + 1)

    @staticmethod
    def get2x2(rng: LegacyRandom) -> str:
        return "2x2_a" + str(rng.next_int(4) + 1)

    @staticmethod
    def get2x2Secret(rng: LegacyRandom) -> str:
        return "2x2_s1"                           # 零消耗


class _SecondFloor:
    """SecondFloorRoomCollection（ThirdFloorRoomCollection 空继承，
    L1140-1141）。"""

    @staticmethod
    def get1x1(rng: LegacyRandom) -> str:
        return "1x1_b" + str(rng.next_int(5) + 1)

    @staticmethod
    def get1x1Secret(rng: LegacyRandom) -> str:
        return "1x1_as" + str(rng.next_int(4) + 1)

    @staticmethod
    def get1x2Side(rng: LegacyRandom, stairs: bool) -> str:
        # stairs 判定本身不耗流
        return "1x2_c_stairs" if stairs else "1x2_c" + str(rng.next_int(4) + 1)

    @staticmethod
    def get1x2Front(rng: LegacyRandom, stairs: bool) -> str:
        return "1x2_d_stairs" if stairs else "1x2_d" + str(rng.next_int(5) + 1)

    @staticmethod
    def get1x2Secret(rng: LegacyRandom) -> str:
        # nextInt(1) 也消耗一次流（2 幂特判仍推进状态）
        return "1x2_se" + str(rng.next_int(1) + 1)

    @staticmethod
    def get2x2(rng: LegacyRandom) -> str:
        return "2x2_b" + str(rng.next_int(5) + 1)

    @staticmethod
    def get2x2Secret(rng: LegacyRandom) -> str:
        return "2x2_s1"                           # 零消耗


_FLOOR_COLLECTIONS = (_FirstFloor, _SecondFloor, _SecondFloor)

# ---------------------------------------------------------------------------
# 模板 NBT 加载（尺寸 / 显示体素 / Chest* DATA 标记）
# ---------------------------------------------------------------------------

_TPL_CACHE: dict = {}


def template_path(name: str) -> Path:
    return _ASSET_DIR / (name + ".nbt")


def _load_template(name: str) -> dict:
    """模板 NBT -> {"size", "blocks", "chest_markers"}（缓存）。

    blocks: {(x,y,z): (方块名, shape 码或 None)}，air/structure_void/
    structure_block 不入显示体素；chest_markers: [(x,y,z,metadata)]
    按 filterBlocks 遍历序 = buildInfoList 重排后顺序（StructureTemplate
    L152-166：实心/其它/有NBT 三组，各组 (y,x,z) 升序；structure_block
    带 nbt 恒落有NBT 组）=> 排序键 (y,x,z)。同 piece 多 DATA 标记的
    处理序由此确定，直接影响装饰线 nextLong 分配。
    注：模板自带容器（chest 带 Items NBT、无 LootTable，如 1x2_a9 的
    42 个装饰箱）为固定内容，placeInWorld 放置不耗装饰流（见文件头
    数据流注释），不在 chest_markers 内。
    """
    cached = _TPL_CACHE.get(name)
    if cached is not None:
        return cached
    with open(template_path(name), "rb") as f:
        root = structure_models.parse_nbt(f.read())
    size_raw = root.get("size")
    size = tuple(size_raw[1]) if isinstance(size_raw, tuple) else (1, 1, 1)
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
        props = structure_models._palette_entry_props(entry)
        shape = _bs.shape_from_palette(nm, props)
        entries.append((nm, shape))
    blocks: dict = {}
    chest_markers: list = []
    blocks_raw = root.get("blocks")
    if blocks_raw:
        for item in blocks_raw[1]:
            pos_raw = item.get("pos")
            pos = pos_raw[1] if isinstance(pos_raw, tuple) else pos_raw
            if not isinstance(pos, list) or len(pos) != 3:
                continue
            st = item.get("state", 0)
            if not (0 <= st < len(entries)):
                continue
            nm, shape = entries[st]
            if nm == "minecraft:structure_block":
                nbt = item.get("nbt")
                meta = ""
                if isinstance(nbt, dict):
                    v = nbt.get("metadata", nbt.get("Metadata", ""))
                    meta = v if isinstance(v, str) else ""
                if meta.startswith("Chest"):
                    chest_markers.append((pos[0], pos[1], pos[2], meta))
                continue
            if nm in ("minecraft:air", "minecraft:cave_air",
                      "minecraft:structure_void"):
                continue
            blocks[(pos[0], pos[1], pos[2])] = (nm, shape)
    # buildInfoList 重排：有NBT 组按 (y, x, z) 升序（L154-156 比较器）
    chest_markers.sort(key=lambda m: (m[1], m[0], m[2]))
    out = {"size": size, "blocks": blocks, "chest_markers": chest_markers}
    _TPL_CACHE[name] = out
    return out


def _piece_bb(size: tuple, mirror: str, rot: str,
              pos: tuple) -> tuple:
    """TemplateStructurePiece 构造 bb（StructureTemplate.getBoundingBox
    L574-584）：transform(ZERO) 与 transform(size-1) 的 fromCorners +
    move(pos)，闭区间 [min, max]。"""
    sx, sy, sz = size
    a = transform_pos((0, 0, 0), mirror, rot)
    b = transform_pos((sx - 1, sy - 1, sz - 1), mirror, rot)
    return (pos[0] + min(a[0], b[0]), pos[1] + min(a[1], b[1]),
            pos[2] + min(a[2], b[2]),
            pos[0] + max(a[0], b[0]), pos[1] + max(a[1], b[1]),
            pos[2] + max(a[2], b[2]))


# ---------------------------------------------------------------------------
# MansionPiecePlacer（L398-1052 逐行转写）：模板拼装
# ---------------------------------------------------------------------------

_MANSION_LOOT_TABLE = "chests/woodland_mansion"
_MANSION_STEP = 4                     # SURFACE_STRUCTURES
_MANSION_DECORATOR = 5                # cl_salts_1_21_5.txt L12：4 5 mansion
_MANSION_SALT_OFFSET = _MANSION_DECORATOR + 10000 * _MANSION_STEP  # 40005


class _PlacementData:
    """PlacementData（L1055-1059）。"""

    __slots__ = ("pos", "rot", "wall")

    def __init__(self, pos: tuple, rot: str, wall: str) -> None:
        self.pos = pos
        self.rot = rot
        self.wall = wall


def _add_piece(pieces: list, name: str, pos: tuple, rot: str,
               mirror: str = "NONE") -> None:
    pieces.append({"name": name, "pos": pos, "rot": rot, "mirror": mirror})


def _traverse_wall_piece(pieces: list, d: _PlacementData) -> None:
    """traverseWallPiece（L844-851）：add(wall, pos+E*7)；pos += S*8。"""
    _add_piece(pieces, d.wall,
               _rel2(d.pos, _rotate_dir(d.rot, "E"), 7), d.rot)
    d.pos = _rel2(d.pos, _rotate_dir(d.rot, "S"), 8)


def _traverse_turn(pieces: list, d: _PlacementData) -> None:
    """traverseTurn（L853-859）：pos+=S*(-1) -> wall_corner ->
    pos+=S*(-7)+W*(-6) -> rot=CW90。"""
    d.pos = _rel2(d.pos, _rotate_dir(d.rot, "S"), -1)
    _add_piece(pieces, "wall_corner", d.pos, d.rot)
    d.pos = _rel2(d.pos, _rotate_dir(d.rot, "S"), -7)
    d.pos = _rel2(d.pos, _rotate_dir(d.rot, "W"), -6)
    d.rot = _rot_add(d.rot, "CLOCKWISE_90")


def _traverse_inner_turn(pieces: list, d: _PlacementData) -> None:
    """traverseInnerTurn（L861-865）：pos+=S*6+E*8 -> rot=CCW90。"""
    d.pos = _rel2(d.pos, _rotate_dir(d.rot, "S"), 6)
    d.pos = _rel2(d.pos, _rotate_dir(d.rot, "E"), 8)
    d.rot = _rot_add(d.rot, "COUNTERCLOCKWISE_90")


def _traverse_outer_walls(pieces: list, pd: _PlacementData, g: SimpleGrid,
                          d0: str, x: int, y: int, tx: int, ty: int) -> None:
    """traverseOuterWalls（L591-628）逐行转写。

    两套方向状态（Java 源实证，勿合并）：
      - 局部 gdir（参数 $$3，do-while 内演化）：网格步进用未旋转的
        绝对方向（getStepX/Z 不经 rotate）；外角转 CW、内角转 CCW；
        $$10 = gdir 的初始快照，终止条件 = cx==tx and cy==ty and
        gdir==$$10。
      - pd.rotation（PlacementData.rotation）：仅由 traverse 系列
        （_traverse_turn / _traverse_inner_turn）内演化，所有位移
        经 _rotate_dir(pd.rot, ..)。
    """
    cx, cy = x, y
    gdir = d0                                  # $$10 = $$3 初始快照
    while True:
        fx = cx + _STEP2[gdir][0]
        fy = cy + _STEP2[gdir][1]
        if not _is_house(g, fx, fy):
            # 外角（L606-611）：traverseTurn 后 gdir 转 CW，
            # 与终态（快照）比较决定是否放墙件
            _traverse_turn(pieces, pd)
            gdir = _CLOCKWISE[gdir]
            if cx != tx or cy != ty or gdir != d0:
                _traverse_wall_piece(pieces, pd)
        elif _is_house(g, fx + _STEP2[_COUNTER_CW[gdir]][0],
                       fy + _STEP2[_COUNTER_CW[gdir]][1]):
            # 内角（L612-619）：不放件，traverseInnerTurn 后 gdir 转 CCW
            _traverse_inner_turn(pieces, pd)
            cx, cy = fx, fy
            gdir = _COUNTER_CW[gdir]
        else:
            # 直行（L620-625）
            cx, cy = fx, fy
            if cx != tx or cy != ty or gdir != d0:
                _traverse_wall_piece(pieces, pd)
        if cx == tx and cy == ty and gdir == d0:
            return


def _create_roof(pieces: list, base: tuple, rot: str, g: SimpleGrid,
                 lower: SimpleGrid | None, start_x: int, start_y: int) -> None:
    """createRoof（L630-836）：roof/roof_front + small_wall（仅
    lower!=null 且本格两层都有）+ roof_corner/roof_inner_corner。"""

    def cell_pos(gy: int, gx: int) -> tuple:
        p = _rel2(base, _rotate_dir(rot, "S"), 8 + (gy - start_y) * 8)
        return _rel2(p, _rotate_dir(rot, "E"), (gx - start_x) * 8)

    for gy in range(g.height):
        for gx in range(g.width):
            if not _is_house(g, gx, gy):
                continue
            if lower is not None and _is_house(lower, gx, gy):
                continue                        # L641-642
            p27 = cell_pos(gy, gx)
            _add_piece(pieces, "roof", _rel3(p27, "UP", 3), rot)  # L643
            if not _is_house(g, gx + 1, gy):    # 东缺（L644-647）
                _add_piece(pieces, "roof_front",
                           _rel2(p27, _rotate_dir(rot, "E"), 6), rot)
            if not _is_house(g, gx - 1, gy):    # 西缺（L649-657）
                p10 = _rel2(p27, _rotate_dir(rot, "S"), 7)
                _add_piece(pieces, "roof_front", p10,
                           _rot_add(rot, "CLOCKWISE_180"))
            if not _is_house(g, gx, gy - 1):    # 北缺（L659-666）
                _add_piece(pieces, "roof_front",
                           _rel2(p27, _rotate_dir(rot, "W"), 1),
                           _rot_add(rot, "COUNTERCLOCKWISE_90"))
            if not _is_house(g, gx, gy + 1):    # 南缺（L668-674）
                p12 = _rel2(p27, _rotate_dir(rot, "E"), 6)
                p12 = _rel2(p12, _rotate_dir(rot, "S"), 6)
                _add_piece(pieces, "roof_front", p12,
                           _rot_add(rot, "CLOCKWISE_90"))
    if lower is not None:
        # small_wall / small_wall_corner（L679-763）：本格上下都有房
        for gy in range(g.height):
            for gx in range(g.width):
                if not _is_house(g, gx, gy) or not _is_house(lower, gx, gy):
                    continue
                v17 = cell_pos(gy, gx)
                if not _is_house(g, gx + 1, gy):        # 东（L686-689）
                    _add_piece(pieces, "small_wall",
                               _rel2(v17, _rotate_dir(rot, "E"), 7), rot)
                if not _is_house(g, gx - 1, gy):        # 西（L691-699）
                    p18 = _rel2(v17, _rotate_dir(rot, "W"), 1)
                    p18 = _rel2(p18, _rotate_dir(rot, "S"), 6)
                    _add_piece(pieces, "small_wall", p18,
                               _rot_add(rot, "CLOCKWISE_180"))
                if not _is_house(g, gx, gy - 1):        # 北（L701-709）
                    p19 = _rel2(v17, _rotate_dir(rot, "N"), 1)
                    _add_piece(pieces, "small_wall", p19,
                               _rot_add(rot, "COUNTERCLOCKWISE_90"))
                if not _is_house(g, gx, gy + 1):        # 南（L711-719）
                    p20 = _rel2(v17, _rotate_dir(rot, "E"), 6)
                    p20 = _rel2(p20, _rotate_dir(rot, "S"), 7)
                    _add_piece(pieces, "small_wall", p20,
                               _rot_add(rot, "CLOCKWISE_90"))
                if not _is_house(g, gx + 1, gy):        # 东缺时墙角
                    if not _is_house(g, gx, gy - 1):    # L722-725
                        p21 = _rel2(v17, _rotate_dir(rot, "E"), 7)
                        p21 = _rel2(p21, _rotate_dir(rot, "N"), 2)
                        _add_piece(pieces, "small_wall_corner", p21, rot)
                    if not _is_house(g, gx, gy + 1):    # L728-736
                        p22 = _rel2(v17, _rotate_dir(rot, "E"), 8)
                        p22 = _rel2(p22, _rotate_dir(rot, "S"), 7)
                        _add_piece(pieces, "small_wall_corner", p22,
                                   _rot_add(rot, "CLOCKWISE_90"))
                if not _is_house(g, gx - 1, gy):        # 西缺时墙角
                    if not _is_house(g, gx, gy - 1):    # L740-748
                        p23 = _rel2(v17, _rotate_dir(rot, "W"), 2)
                        p23 = _rel2(p23, _rotate_dir(rot, "N"), 1)
                        _add_piece(pieces, "small_wall_corner", p23,
                                   _rot_add(rot, "COUNTERCLOCKWISE_90"))
                    if not _is_house(g, gx, gy + 1):    # L750-758
                        p24 = _rel2(v17, _rotate_dir(rot, "W"), 1)
                        p24 = _rel2(p24, _rotate_dir(rot, "S"), 8)
                        _add_piece(pieces, "small_wall_corner", p24,
                                   _rot_add(rot, "CLOCKWISE_180"))
    for gy in range(g.height):
        for gx in range(g.width):
            if not _is_house(g, gx, gy):
                continue
            if lower is not None and _is_house(lower, gx, gy):
                continue                        # L769-770
            v19 = cell_pos(gy, gx)
            if not _is_house(g, gx + 1, gy):            # 东缺（L771-796）
                p29 = _rel2(v19, _rotate_dir(rot, "E"), 6)
                if not _is_house(g, gx, gy + 1):
                    p30 = _rel2(p29, _rotate_dir(rot, "S"), 6)
                    _add_piece(pieces, "roof_corner", p30, rot)
                elif _is_house(g, gx + 1, gy + 1):
                    p31 = _rel2(p29, _rotate_dir(rot, "S"), 5)
                    _add_piece(pieces, "roof_inner_corner", p31, rot)
                if not _is_house(g, gx, gy - 1):
                    _add_piece(pieces, "roof_corner", p29,
                               _rot_add(rot, "COUNTERCLOCKWISE_90"))
                elif _is_house(g, gx + 1, gy - 1):
                    p32 = _rel2(v19, _rotate_dir(rot, "E"), 9)
                    p32 = _rel2(p32, _rotate_dir(rot, "N"), 2)
                    _add_piece(pieces, "roof_inner_corner", p32,
                               _rot_add(rot, "CLOCKWISE_90"))
            if not _is_house(g, gx - 1, gy):            # 西缺（L798-831）
                p33 = v19
                if not _is_house(g, gx, gy + 1):
                    p34 = _rel2(p33, _rotate_dir(rot, "S"), 6)
                    _add_piece(pieces, "roof_corner", p34,
                               _rot_add(rot, "CLOCKWISE_90"))
                elif _is_house(g, gx - 1, gy + 1):
                    p35 = _rel2(p33, _rotate_dir(rot, "S"), 8)
                    p35 = _rel2(p35, _rotate_dir(rot, "W"), 3)
                    _add_piece(pieces, "roof_inner_corner", p35,
                               _rot_add(rot, "COUNTERCLOCKWISE_90"))
                if not _is_house(g, gx, gy - 1):
                    _add_piece(pieces, "roof_corner", p33,
                               _rot_add(rot, "CLOCKWISE_180"))
                elif _is_house(g, gx - 1, gy - 1):
                    p36 = _rel2(p33, _rotate_dir(rot, "S"), 1)
                    _add_piece(pieces, "roof_inner_corner", p36,
                               _rot_add(rot, "CLOCKWISE_180"))


def _add_room_1x1(pieces: list, p1: tuple, rot: str, door_dir: str | None,
                  coll, rng: LegacyRandom) -> None:
    """addRoom1x1（L867-889）：恒耗 get1x1；门向非 E 且非 N/W/S（UP/null）
    再耗 get1x1Secret。"""
    r = "NONE"
    name = coll.get1x1(rng)
    if door_dir != "E":
        if door_dir == "N":
            r = _rot_add(r, "COUNTERCLOCKWISE_90")
        elif door_dir == "W":
            r = _rot_add(r, "CLOCKWISE_180")
        elif door_dir == "S":
            r = _rot_add(r, "CLOCKWISE_90")
        else:
            name = coll.get1x1Secret(rng)
    off = zero_pos_with_transform((1, 0, 0), "NONE", r, 7, 7)
    r = _rot_add(r, rot)                          # $$5 = $$5.getRotated($$2)
    off = blockpos_rotate(off, rot)               # $$7 = $$7.rotate($$2)
    _add_piece(pieces, name, (p1[0] + off[0], p1[1], p1[2] + off[2]), r)


def _add_room_1x2(pieces: list, p1: tuple, rot: str, side: str | None,
                  door: str | None, coll, stairs: bool,
                  rng: LegacyRandom) -> None:
    """addRoom1x2（L891-995）十四分支。side=$$3（同 id 邻向），
    door=$$4（门向）。"""
    if door == "E" and side == "S":               # L900-902
        _add_piece(pieces, coll.get1x2Side(rng, stairs),
                   _rel2(p1, _rotate_dir(rot, "E"), 1), rot)
    elif door == "E" and side == "N":             # L903-910
        p8 = _rel2(p1, _rotate_dir(rot, "E"), 1)
        p8 = _rel2(p8, _rotate_dir(rot, "S"), 6)
        _add_piece(pieces, coll.get1x2Side(rng, stairs), p8, rot,
                   "LEFT_RIGHT")
    elif door == "W" and side == "N":             # L911-918
        p9 = _rel2(p1, _rotate_dir(rot, "E"), 7)
        p9 = _rel2(p9, _rotate_dir(rot, "S"), 6)
        _add_piece(pieces, coll.get1x2Side(rng, stairs), p9,
                   _rot_add(rot, "CLOCKWISE_180"))
    elif door == "W" and side == "S":             # L919-925
        p10 = _rel2(p1, _rotate_dir(rot, "E"), 7)
        _add_piece(pieces, coll.get1x2Side(rng, stairs), p10, rot,
                   "FRONT_BACK")
    elif door == "S" and side == "E":             # L926-932
        p11 = _rel2(p1, _rotate_dir(rot, "E"), 1)
        _add_piece(pieces, coll.get1x2Side(rng, stairs), p11,
                   _rot_add(rot, "CLOCKWISE_90"), "LEFT_RIGHT")
    elif door == "S" and side == "W":             # L933-939
        p12 = _rel2(p1, _rotate_dir(rot, "E"), 7)
        _add_piece(pieces, coll.get1x2Side(rng, stairs), p12,
                   _rot_add(rot, "CLOCKWISE_90"))
    elif door == "N" and side == "W":             # L940-947
        p13 = _rel2(p1, _rotate_dir(rot, "E"), 7)
        p13 = _rel2(p13, _rotate_dir(rot, "S"), 6)
        _add_piece(pieces, coll.get1x2Side(rng, stairs), p13,
                   _rot_add(rot, "CLOCKWISE_90"), "FRONT_BACK")
    elif door == "N" and side == "E":             # L948-955
        p14 = _rel2(p1, _rotate_dir(rot, "E"), 1)
        p14 = _rel2(p14, _rotate_dir(rot, "S"), 6)
        _add_piece(pieces, coll.get1x2Side(rng, stairs), p14,
                   _rot_add(rot, "COUNTERCLOCKWISE_90"))
    elif door == "S" and side == "N":             # L956-959
        p15 = _rel2(p1, _rotate_dir(rot, "E"), 1)
        p15 = _rel2(p15, _rotate_dir(rot, "N"), 8)   # relative(N, 0) 无操作
        _add_piece(pieces, coll.get1x2Front(rng, stairs), p15, rot)
    elif door == "N" and side == "S":             # L960-967
        p16 = _rel2(p1, _rotate_dir(rot, "E"), 7)
        p16 = _rel2(p16, _rotate_dir(rot, "S"), 14)
        _add_piece(pieces, coll.get1x2Front(rng, stairs), p16,
                   _rot_add(rot, "CLOCKWISE_180"))
    elif door == "W" and side == "E":             # L968-974
        p17 = _rel2(p1, _rotate_dir(rot, "E"), 15)
        _add_piece(pieces, coll.get1x2Front(rng, stairs), p17,
                   _rot_add(rot, "CLOCKWISE_90"))
    elif door == "E" and side == "W":             # L975-982
        p18 = _rel2(p1, _rotate_dir(rot, "W"), 7)
        p18 = _rel2(p18, _rotate_dir(rot, "S"), 6)
        _add_piece(pieces, coll.get1x2Front(rng, stairs), p18,
                   _rot_add(rot, "COUNTERCLOCKWISE_90"))
    elif door == "UP" and side == "E":            # L983-989
        p19 = _rel2(p1, _rotate_dir(rot, "E"), 15)
        _add_piece(pieces, coll.get1x2Secret(rng), p19,
                   _rot_add(rot, "CLOCKWISE_90"))
    elif door == "UP" and side == "S":            # L990-994
        p20 = _rel2(p1, _rotate_dir(rot, "E"), 1)
        _add_piece(pieces, coll.get1x2Secret(rng), p20, rot)


def _add_room_2x2(pieces: list, p1: tuple, rot: str, side: str,
                  door: str, coll, rng: LegacyRandom) -> None:
    """addRoom2x2（L997-1045）八分支。side=$$3（经 getClockWise 校验），
    door=$$4。"""
    dx = dz = 0
    r2 = rot
    mirror = "NONE"
    if door == "E" and side == "S":               # L1009-1010
        dx = -7
    elif door == "E" and side == "N":             # L1011-1014
        dx = -7
        dz = 6
        mirror = "LEFT_RIGHT"
    elif door == "N" and side == "E":             # L1015-1018
        dx = 1
        dz = 14
        r2 = _rot_add(rot, "COUNTERCLOCKWISE_90")
    elif door == "N" and side == "W":             # L1019-1023
        dx = 7
        dz = 14
        r2 = _rot_add(rot, "COUNTERCLOCKWISE_90")
        mirror = "LEFT_RIGHT"
    elif door == "S" and side == "W":             # L1024-1027
        dx = 7
        dz = -8
        r2 = _rot_add(rot, "CLOCKWISE_90")
    elif door == "S" and side == "E":             # L1028-1032
        dx = 1
        dz = -8
        r2 = _rot_add(rot, "CLOCKWISE_90")
        mirror = "LEFT_RIGHT"
    elif door == "W" and side == "N":             # L1033-1036
        dx = 15
        dz = 6
        r2 = _rot_add(rot, "CLOCKWISE_180")
    elif door == "W" and side == "S":             # L1037-1040
        dx = 15
        mirror = "FRONT_BACK"
    p10 = _rel2(p1, _rotate_dir(rot, "E"), dx)
    p10 = _rel2(p10, _rotate_dir(rot, "S"), dz)
    _add_piece(pieces, coll.get2x2(rng), p10, r2, mirror)


def _add_room_2x2_secret(pieces: list, p1: tuple, rot: str, coll,
                         rng: LegacyRandom) -> None:
    """addRoom2x2Secret（L1047-1052）：get2x2Secret 零消耗。"""
    p4 = _rel2(p1, _rotate_dir(rot, "E"), 1)
    _add_piece(pieces, coll.get2x2Secret(rng), p4, rot)


def _create_mansion(pos: tuple, rot: str, grid: MansionGrid,
                    rng: LegacyRandom) -> list:
    """MansionPiecePlacer.createMansion（L409-589）。

    pos = findGenerationPoint 锚点（chunkBlock(7,7)；Y 本模块固定 64）。
    返回 [{name, pos, rot, mirror}]（pieces 列表序 = 装饰线处理序）。
    """
    pieces: list = []
    d4 = _PlacementData(pos, rot, "wall_flat")
    # entrance（L838-842）：先 add 再前移 pos
    _add_piece(pieces, "entrance",
               _rel2(d4.pos, _rotate_dir(rot, "W"), 9), rot)
    d4.pos = _rel2(d4.pos, _rotate_dir(rot, "S"), 16)
    d5 = _PlacementData(_rel3(d4.pos, "UP", 8), rot, "wall_window")
    start_x = grid.entranceX + 1                  # L424 = 8
    start_y = grid.entranceY + 1                  # L425 = 5
    tgt_x = grid.entranceX + 1                    # L426 = 8
    tgt_y = grid.entranceY                        # L427 = 4
    _traverse_outer_walls(pieces, d4, grid.baseGrid, "S",
                          start_x, start_y, tgt_x, tgt_y)   # L428
    _traverse_outer_walls(pieces, d5, grid.baseGrid, "S",
                          start_x, start_y, tgt_x, tgt_y)   # L429
    d10 = _PlacementData(_rel3(d4.pos, "UP", 19), rot, "wall_window")  # L430
    tgrid = grid.thirdFloorGrid
    for ty in range(tgrid.height):                # L436-446：y 升 x 降
        done = False
        for tx in range(tgrid.width - 1, -1, -1):
            if _is_house(tgrid, tx, ty):
                d10.pos = _rel2(d10.pos, _rotate_dir(rot, "S"),
                                8 + (ty - start_y) * 8)
                d10.pos = _rel2(d10.pos, _rotate_dir(rot, "E"),
                                (tx - start_x) * 8)
                _traverse_wall_piece(pieces, d10)
                _traverse_outer_walls(pieces, d10, tgrid, "S",
                                      tx, ty, tx, ty)
                done = True
                break
        if done:
            break
    # 注意：roof/房间用原始 pos（$0），非前移后的 d4.pos
    _create_roof(pieces, _rel3(pos, "UP", 16), rot, grid.baseGrid,
                 grid.thirdFloorGrid, start_x, start_y)     # L448
    _create_roof(pieces, _rel3(pos, "UP", 27), rot, grid.thirdFloorGrid,
                 None, start_x, start_y)                    # L449
    for floor in range(3):                        # L459-588
        base_p = _rel3(pos, "UP", 8 * floor + (3 if floor == 2 else 0))
        rooms = grid.floorRooms[floor]
        main = grid.thirdFloorGrid if floor == 2 else grid.baseGrid
        coll = _FLOOR_COLLECTIONS[floor]
        carpet_s = "carpet_south_1" if floor == 0 else "carpet_south_2"
        carpet_w = "carpet_west_1" if floor == 0 else "carpet_west_2"
        # 走廊 + 地毯（L466-508）
        for gy in range(main.height):
            for gx in range(main.width):
                if main.get(gx, gy) != 1:
                    continue
                p23 = _rel2(base_p, _rotate_dir(rot, "S"),
                            8 + (gy - start_y) * 8)
                p23 = _rel2(p23, _rotate_dir(rot, "E"),
                            (gx - start_x) * 8)
                _add_piece(pieces, "corridor_floor", p23, rot)
                if (main.get(gx, gy - 1) == 1
                        or (rooms.get(gx, gy - 1) & _ROOM_CORRIDOR_FLAG)
                        == _ROOM_CORRIDOR_FLAG):
                    _add_piece(pieces, "carpet_north",
                               _rel3(_rel2(p23, _rotate_dir(rot, "E"), 1),
                                     "UP", 1), rot)
                if (main.get(gx + 1, gy) == 1
                        or (rooms.get(gx + 1, gy) & _ROOM_CORRIDOR_FLAG)
                        == _ROOM_CORRIDOR_FLAG):
                    p_e = _rel2(p23, _rotate_dir(rot, "S"), 1)
                    p_e = _rel2(p_e, _rotate_dir(rot, "E"), 5)
                    _add_piece(pieces, "carpet_east",
                               _rel3(p_e, "UP", 1), rot)
                if (main.get(gx, gy + 1) == 1
                        or (rooms.get(gx, gy + 1) & _ROOM_CORRIDOR_FLAG)
                        == _ROOM_CORRIDOR_FLAG):
                    p_s = _rel2(p23, _rotate_dir(rot, "S"), 5)
                    p_s = _rel2(p_s, _rotate_dir(rot, "W"), 1)
                    _add_piece(pieces, carpet_s, p_s, rot)
                if (main.get(gx - 1, gy) == 1
                        or (rooms.get(gx - 1, gy) & _ROOM_CORRIDOR_FLAG)
                        == _ROOM_CORRIDOR_FLAG):
                    p_w = _rel2(p23, _rotate_dir(rot, "W"), 1)
                    p_w = _rel2(p_w, _rotate_dir(rot, "N"), 1)
                    _add_piece(pieces, carpet_w, p_w, rot)
        # 内墙 + 房间（L510-588）
        wall = "indoors_wall_1" if floor == 0 else "indoors_wall_2"
        door = "indoors_door_1" if floor == 0 else "indoors_door_2"
        dirs: list = []
        for gy in range(main.height):
            for gx in range(main.width):
                is_start = floor == 2 and main.get(gx, gy) == 3
                if main.get(gx, gy) != 2 and not is_start:
                    continue
                v = rooms.get(gx, gy)
                vtype = v & _ROOM_TYPE_MASK
                vid = v & _ROOM_ID_MASK
                is_start = (is_start and (v & _ROOM_CORRIDOR_FLAG)
                            == _ROOM_CORRIDOR_FLAG)
                dirs.clear()
                if (v & _ROOM_DOOR_FLAG) == _ROOM_DOOR_FLAG:
                    for hd in _HORIZONTAL:        # Plane.HORIZONTAL 序
                        if main.get(gx + _STEP2[hd][0],
                                    gy + _STEP2[hd][1]) == 1:
                            dirs.append(hd)
                door_dir = None
                if dirs:
                    door_dir = dirs[rng.next_int(len(dirs))]   # L533 耗流
                elif (v & _ROOM_ORIGIN_FLAG) == _ROOM_ORIGIN_FLAG:
                    door_dir = "UP"
                p35 = _rel2(base_p, _rotate_dir(rot, "S"),
                            8 + (gy - start_y) * 8)
                p35 = _rel2(p35, _rotate_dir(rot, "E"),
                            -1 + (gx - start_x) * 8)
                if (_is_house(main, gx - 1, gy)          # 西墙 L540-542
                        and not grid.is_room_id(gx - 1, gy,
                                                floor, vid)):
                    _add_piece(pieces, door if door_dir == "W" else wall,
                               p35, rot)
                if main.get(gx + 1, gy) == 1 and not is_start:  # 东 L544
                    _add_piece(pieces, door if door_dir == "E" else wall,
                               _rel2(p35, _rotate_dir(rot, "E"), 8), rot)
                if (_is_house(main, gx, gy + 1)          # 南墙 L549-557
                        and not grid.is_room_id(gx, gy + 1,
                                                floor, vid)):
                    p37 = _rel2(p35, _rotate_dir(rot, "S"), 7)
                    p37 = _rel2(p37, _rotate_dir(rot, "E"), 7)
                    _add_piece(pieces, door if door_dir == "S" else wall,
                               p37, _rot_add(rot, "CLOCKWISE_90"))
                if main.get(gx, gy - 1) == 1 and not is_start:  # 北 L559
                    p38 = _rel2(p35, _rotate_dir(rot, "N"), 1)
                    p38 = _rel2(p38, _rotate_dir(rot, "E"), 7)
                    _add_piece(pieces, door if door_dir == "N" else wall,
                               p38, _rot_add(rot, "CLOCKWISE_90"))
                if vtype == _ROOM_1X1:                   # L569
                    _add_room_1x1(pieces, p35, rot, door_dir, coll, rng)
                elif vtype == _ROOM_1X2 and door_dir is not None:  # L571
                    side = grid.get1x2RoomDirection(main, gx, gy,
                                                    floor, vid)
                    stairs = (v & _ROOM_STAIRS_FLAG) == _ROOM_STAIRS_FLAG
                    _add_room_1x2(pieces, p35, rot, side, door_dir,
                                  coll, stairs, rng)
                elif (vtype == _ROOM_2X2 and door_dir is not None
                        and door_dir != "UP"):           # L575-581
                    side2 = _CLOCKWISE[door_dir]
                    if not grid.is_room_id(gx + _STEP2[side2][0],
                                           gy + _STEP2[side2][1],
                                           floor, vid):
                        side2 = _OPPOSITE[side2]
                    _add_room_2x2(pieces, p35, rot, side2, door_dir,
                                  coll, rng)
                elif vtype == _ROOM_2X2 and door_dir == "UP":  # L582
                    _add_room_2x2_secret(pieces, p35, rot, coll, rng)
    return pieces


# ---------------------------------------------------------------------------
# 装饰线（Xoroshiro per-chunk）：箱子 LootTableSeed
# ---------------------------------------------------------------------------

def _bb_intersects(a: tuple, b: tuple) -> bool:
    """BoundingBox.intersects：闭区间重叠（x/z/y 三维）。"""
    return (a[0] <= b[3] and a[3] >= b[0]
            and a[2] <= b[5] and a[5] >= b[2]
            and a[1] <= b[4] and a[4] >= b[1])


def _bb_contains(bb: tuple, p: tuple) -> bool:
    """BoundingBox.isInside：闭区间含点。"""
    return (bb[0] <= p[0] <= bb[3] and bb[1] <= p[1] <= bb[4]
            and bb[2] <= p[2] <= bb[5])


def _decor_loot(world_seed: int, pieces: list) -> list:
    """装饰线箱子种子（StructureStart.placeInChunk L81-96 语义）。

    mansion 覆盖的每个区块 c 独立建流：
        pop = getPopulationSeed(seed, c 区块角)（getWritableArea 同区块）
        rng = XoroshiroJava(pop + 5 + 10000*4)
    pieces 列表序遍历，bb 与区块 writable box（xz = 区块 16×16，y 恒内）
    相交者 postProcess：DATA 标记（filterBlocks 按模板 blocks 序，
    chunkBox 裁剪）Chest* -> createChest（bb 内且非 CHEST）->
    rng.nextLong() = LootTableSeed。
    Y 维不裁剪：mansion y ∈ [64, ~95] ⊂ writable [-63, 319]。
    """
    if not pieces:
        return []
    boxes = []
    for pc in pieces:
        tpl = _load_template(pc["name"])
        boxes.append(_piece_bb(tpl["size"], pc["mirror"], pc["rot"],
                               pc["pos"]))
    ex0 = min(b[0] for b in boxes)
    ex1 = max(b[3] for b in boxes)
    ez0 = min(b[2] for b in boxes)
    ez1 = max(b[5] for b in boxes)
    chests: list = []
    for cz in range(ez0 >> 4, (ez1 >> 4) + 1):
        for cx in range(ex0 >> 4, (ex1 >> 4) + 1):
            bx0 = cx * 16
            bz0 = cz * 16
            chunk_box = (bx0, 0, bz0, bx0 + 15, 319, bz0 + 15)
            pop = loot_rng.get_population_seed(world_seed, bx0, bz0)
            rng = loot_rng.XoroshiroJava((pop + _MANSION_SALT_OFFSET) & _M64)
            for pc, bb in zip(pieces, boxes):
                if not _bb_intersects(bb, chunk_box):
                    continue
                tpl = _load_template(pc["name"])
                for (lx, ly, lz, _meta) in tpl["chest_markers"]:
                    w = transform_pos((lx, ly, lz), pc["mirror"], pc["rot"])
                    w = (w[0] + pc["pos"][0], w[1] + pc["pos"][1],
                         w[2] + pc["pos"][2])
                    if not (bx0 <= w[0] <= bx0 + 15
                            and bz0 <= w[2] <= bz0 + 15):
                        continue                  # filterBlocks 裁剪
                    if not _bb_contains(bb, w):
                        continue                  # createChest isInside
                    seed = rng.next_long()
                    chests.append({"pos": w, "loot_table": _MANSION_LOOT_TABLE,
                                   "loot_seed": seed, "piece": pc["name"],
                                   "marker": _meta})
    return chests


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

def assemble_mansion(world_seed: int, chunk_x: int,
                     chunk_z: int) -> tuple[list, list, str]:
    """按世界种子复现林地府邸（WoodlandMansionStructure.findGenerationPoint
    + generateMansion + 装饰线）。

    结构线（LegacyRandomSource，与 chunk_generate_rnd 同源）：
        Rotation.getRandom -> nextInt(4)（WoodlandMansionStructure L31）
        -> MansionGrid(random) -> createMansion（同一流）
    锚点 = (chunkBlock(7), chunkBlock(7))；Y 因地形查询不复刻固定 64
    （游戏为 5×5 区块最低表面，>=60 才生成）。
    装饰线：per-chunk Xoroshiro，见 _decor_loot。

    返回 (pieces, chests, rot_name)：
        pieces  [{name, pos(x,y,z), rot, mirror}]，pos 世界坐标
        chests  [{pos(x,y,z), loot_table, loot_seed, piece, marker}]
        rot_name _ROT_NAMES 之一
    """
    rng = LegacyRandom.from_large_feature(world_seed, chunk_x, chunk_z)
    rot = _ROT_NAMES[rng.next_int(4)]
    pos = (chunk_x * 16 + 7, 64, chunk_z * 16 + 7)
    grid = MansionGrid(rng)
    pieces = _create_mansion(pos, rot, grid, rng)
    chests = _decor_loot(world_seed, pieces)
    return pieces, chests, rot
