# -*- coding: utf-8 -*-
"""StructurePreviewer：下界要塞逐方块布局（fortress pieces）。

把 composition.compose_nether_fortress 生成的 piece 序列按官方
NetherFortressPieces.java（26.1 官方未混淆源码，postProcess 逐段
转写）展开为模型体素 dict {(x,y,z): 值}。

坐标与朝向语义（StructurePiece.java 字节码级定案，全部核过）：
- getWorldX/Y/Z：局部 (x,y,z) -> 世界。facing 0..3 = C 口径
  (Plane.HORIZONTAL 随机序 {N,E,S,W})：
      0=NORTH x=minX+x  z=maxZ-z
      1=EAST  x=minX+z  z=minZ+x
      2=SOUTH x=minX+x  z=minZ+z
      3=WEST  x=maxX-z  z=minZ+x
  y = bb.minY + y（所有 fortress piece orientation 恒非空）。
- 方向性方块状态变换（placeBlock 内 mirror/rotate，字节码
  L217-221 + setOrientation L1263-1317）：piece facing 决定
  mirror/rotate 组合，对楼梯 FACING（状态值 = 踏步贴靠侧）的
  净效果为局部朝向 -> 世界朝向映射：
      0 NORTH: n->n e->e s->s w->w（恒等）
      1 EAST : n->e e->s s->w w->n（CW90）
      2 SOUTH: n->n e->w s->s w->e（LEFT_RIGHT 镜像）
      3 WEST : e->n w->s n->e s->w（镜像+CW90）
- 栅栏统一输出 post 形状码（connect_arms 按邻居自动连臂），
  不区分 nsew 状态（视觉等价）。

体素值约定（structure_models.build_mesh）：
- 整格 = 材质键 str；方向性方块 = (材质键, 形状码) 元组。
- 形状码：bs.SHAPE_STAIRS["n|s|e|w"]、bs.SHAPE_FENCE_POST、
  bs.SHAPE_CHEST_N 的 chest:<facing>、bs.SHAPE_CROSS（地狱疣）。

材质键（纹理文件 assets/SeedReverser/textures/block/<键>.png）：
- "nether bricks" / "lava" / "soul sand" / "nether wart" /
  "spawner"（后四者本轮补齐纹理）。
- 箱子材质键 "chest"（_face_mat 分面纹理按 "chest" in mat 判定）。

已知妥协（用户已认可）：
- 无地形：fillColumnDown 全部跳过（预览只画 piece 布局本身）；
- 箱子朝向从简：固定局部 north（真实游戏按周边固体邻居
  reorient，预览无全局世界上下文）；LootTableSeed 口径不变（xp）。
- spawner/lava 恒放置（真实游戏受 chunkBB.isInside 限制，预览中
  chunk 覆盖全结构恒真）；y 基准恒 64（不模拟 moveInsideHeights
  平移，该平移发生在 piece 树生成之后、不影响布局内部）。
- AIR = generateBox 显式挖空（体素 pop），非空气保留；postProcess
  按 accepted 顺序执行、无条件覆盖（后写胜出）。
"""
from __future__ import annotations

from Utils.SeedReverser import block_shapes as bs
from . import loot_rng

# --------------------------------------------------------------- 材质键
NB = "nether bricks"                    # 下界砖
LAVA = "lava"
SOUL_SAND = "soul sand"
SPAWNER = "spawner"
CHEST_MAT = "chest"                     # 需含 "chest"（_face_mat 判定）

_FENCE = (NB, bs.SHAPE_FENCE_POST)
_WART = ("nether wart", bs.SHAPE_CROSS)

# 楼梯局部朝向 -> 世界朝向映射表（索引 = piece facing 0..3）。
_WX_STAIRS = (
    {"n": "n", "s": "s", "e": "e", "w": "w"},          # 0 NORTH
    {"n": "e", "s": "w", "e": "s", "w": "n"},          # 1 EAST（CW90）
    {"n": "n", "s": "s", "e": "w", "w": "e"},          # 2 SOUTH（镜像）
    {"n": "e", "s": "w", "e": "n", "w": "s"},          # 3 WEST（镜像+CW90）
)


class _PieceBB:
    """piece 世界包围盒（Java BoundingBox 语义，min/max 含端点格）。

    composition 的 Piece.bb 为 (bb0, bb1)（bb1 = 含端点最大角，
    Java maxX 语义），直接换算 min/max。
    """

    __slots__ = ("min_x", "min_y", "min_z", "max_x", "max_y", "max_z")

    def __init__(self, bb) -> None:
        (self.min_x, self.min_y, self.min_z), (mx, my, mz) = bb
        self.max_x = mx
        self.max_y = my
        self.max_z = mz

    def world_xy(self, x: int, z: int, facing: int) -> tuple[int, int]:
        """getWorldX/getWorldZ 联合映射（字节码定案表）。

        facing 0 NORTH: x=minX+x  z=maxZ-z
        facing 1 EAST : x=minX+z  z=minZ+x
        facing 2 SOUTH: x=minX+x  z=minZ+z
        facing 3 WEST : x=maxX-z  z=minZ+x
        """
        if facing == 0:
            return self.min_x + x, self.max_z - z
        if facing == 1:
            return self.min_x + z, self.min_z + x
        if facing == 2:
            return self.min_x + x, self.min_z + z
        return self.max_x - z, self.min_z + x


class _Ctx:
    """单 piece 的 postProcess 上下文（setWorldX/Y/Z + placeBlock）。

    write(x, y, z, val)：val None = AIR（体素 pop，显式挖空）。
    """

    __slots__ = ("pbb", "facing", "write")

    def __init__(self, pbb: _PieceBB, facing: int, write) -> None:
        self.pbb = pbb
        self.facing = facing
        self.write = write

    # -- placeBlock 语义：局部 (x,y,z) -> 世界，方向性状态做变换 --
    def place(self, x: int, y: int, z: int, val) -> None:
        wx, wz = self.pbb.world_xy(x, z, self.facing)
        self.write(wx, self.pbb.min_y + y, wz, val)

    def stairs(self, x: int, y: int, z: int, local: str) -> None:
        """楼梯：局部 FACING 状态 -> 世界 FACING 状态。"""
        world = _WX_STAIRS[self.facing].get(local, local)
        self.place(x, y, z, (NB, bs.SHAPE_STAIRS[world]))

    def fence(self, x0: int, y0: int, z0: int,
              x1: int, y1: int, z1: int) -> None:
        """generateBox 栅栏（post 形状码，状态无关）。"""
        self.box(x0, y0, z0, x1, y1, z1, _FENCE)

    # -- generateBox（edge/fill + 无 skipAir）--
    def box(self, x0: int, y0: int, z0: int,
            x1: int, y1: int, z1: int, val) -> None:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                for z in range(z0, z1 + 1):
                    self.place(x, y, z, val)

    def air_box(self, x0: int, y0: int, z0: int,
                x1: int, y1: int, z1: int) -> None:
        """generateBox(..., AIR, AIR)：显式挖空（体素 pop）。"""
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                for z in range(z0, z1 + 1):
                    self.place(x, y, z, None)


# =========================================================== piece 布局
# 每函数 = 一个 piece 类型的 postProcess（NetherFortressPieces.java
# 逐段转写；generateBox AIR 显式挖空、fillColumnDown 跳过）。


def _piece_start_bridge_crossing(c: _Ctx) -> None:
    # BridgeCrossing.postProcess（StartPiece 同布局，Java L227-262）
    c.box(7, 3, 0, 11, 4, 18, NB)
    c.box(0, 3, 7, 18, 4, 11, NB)
    c.air_box(8, 5, 0, 10, 7, 18)
    c.air_box(0, 5, 8, 18, 7, 10)
    c.box(7, 5, 0, 7, 5, 7, NB)
    c.box(7, 5, 11, 7, 5, 18, NB)
    c.box(11, 5, 0, 11, 5, 7, NB)
    c.box(11, 5, 11, 11, 5, 18, NB)
    c.box(0, 5, 7, 7, 5, 7, NB)
    c.box(11, 5, 7, 18, 5, 7, NB)
    c.box(0, 5, 11, 7, 5, 11, NB)
    c.box(11, 5, 11, 18, 5, 11, NB)
    c.box(7, 2, 0, 11, 2, 5, NB)
    c.box(7, 2, 13, 11, 2, 18, NB)
    c.box(7, 0, 0, 11, 1, 3, NB)
    c.box(7, 0, 15, 11, 1, 18, NB)
    # fillColumnDown x7..11 z0..2/z16..18 + x0..2/16..18 z7..11：跳过
    c.box(0, 2, 7, 5, 2, 11, NB)
    c.box(13, 2, 7, 18, 2, 11, NB)
    c.box(0, 0, 7, 3, 1, 11, NB)
    c.box(15, 0, 7, 18, 1, 11, NB)


def _piece_bridge_straight(c: _Ctx) -> None:
    # BridgeStraight.postProcess（Java L160-186）
    c.box(0, 3, 0, 4, 4, 18, NB)
    c.air_box(1, 5, 0, 3, 7, 18)
    c.box(0, 5, 0, 0, 5, 18, NB)
    c.box(4, 5, 0, 4, 5, 18, NB)
    c.box(0, 2, 0, 4, 2, 5, NB)
    c.box(0, 2, 13, 4, 2, 18, NB)
    c.box(0, 0, 0, 4, 1, 3, NB)
    c.box(0, 0, 15, 4, 1, 18, NB)
    # fillColumnDown x0..4 z0..2/z16..18：跳过
    c.fence(0, 1, 1, 0, 4, 1)        # nseFence
    c.fence(0, 3, 4, 0, 4, 4)
    c.fence(0, 3, 14, 0, 4, 14)
    c.fence(0, 1, 17, 0, 4, 17)
    c.fence(4, 1, 1, 4, 4, 1)        # nswFence
    c.fence(4, 3, 4, 4, 4, 4)
    c.fence(4, 3, 14, 4, 4, 14)
    c.fence(4, 1, 17, 4, 4, 17)


def _piece_room_crossing(c: _Ctx) -> None:
    # RoomCrossing.postProcess（Java L294-320）
    c.box(0, 0, 0, 6, 1, 6, NB)
    c.air_box(0, 2, 0, 6, 7, 6)
    c.box(0, 2, 0, 1, 6, 0, NB)
    c.box(0, 2, 6, 1, 6, 6, NB)
    c.box(5, 2, 0, 6, 6, 0, NB)
    c.box(5, 2, 6, 6, 6, 6, NB)
    c.box(0, 2, 0, 0, 6, 1, NB)
    c.box(0, 2, 5, 0, 6, 6, NB)
    c.box(6, 2, 0, 6, 6, 1, NB)
    c.box(6, 2, 5, 6, 6, 6, NB)
    c.box(2, 6, 0, 4, 6, 0, NB)
    c.fence(2, 5, 0, 4, 5, 0)        # weFence
    c.box(2, 6, 6, 4, 6, 6, NB)
    c.fence(2, 5, 6, 4, 5, 6)
    c.box(0, 6, 2, 0, 6, 4, NB)
    c.fence(0, 5, 2, 0, 5, 4)        # nsFence
    c.box(6, 6, 2, 6, 6, 4, NB)
    c.fence(6, 5, 2, 6, 5, 4)
    # fillColumnDown x0..6 z0..6：跳过


def _piece_stairs_room(c: _Ctx) -> None:
    # StairsRoom.postProcess（Java L350-377）
    c.box(0, 0, 0, 6, 1, 6, NB)
    c.air_box(0, 2, 0, 6, 10, 6)
    c.box(0, 2, 0, 1, 8, 0, NB)
    c.box(5, 2, 0, 6, 8, 0, NB)
    c.box(0, 2, 1, 0, 8, 6, NB)
    c.box(6, 2, 1, 6, 8, 6, NB)
    c.box(1, 2, 6, 5, 8, 6, NB)
    c.fence(0, 3, 2, 0, 5, 4)        # nsFence
    c.fence(6, 3, 2, 6, 5, 2)
    c.fence(6, 3, 4, 6, 5, 4)
    c.place(5, 2, 5, NB)
    c.box(4, 2, 5, 4, 3, 5, NB)
    c.box(3, 2, 5, 3, 4, 5, NB)
    c.box(2, 2, 5, 2, 5, 5, NB)
    c.box(1, 2, 5, 1, 6, 5, NB)
    c.box(1, 7, 1, 5, 7, 4, NB)
    c.air_box(6, 8, 2, 6, 8, 4)
    c.box(2, 6, 0, 4, 8, 0, NB)
    c.fence(2, 5, 0, 4, 5, 0)        # weFence
    # fillColumnDown：跳过


def _piece_monster_throne(c: _Ctx) -> None:
    # MonsterThrone.postProcess（Java L411-456）
    c.air_box(0, 2, 0, 6, 7, 7)
    c.box(1, 0, 0, 5, 1, 7, NB)
    c.box(1, 2, 1, 5, 2, 7, NB)
    c.box(1, 3, 2, 5, 3, 7, NB)
    c.box(1, 4, 3, 5, 4, 7, NB)
    c.box(1, 2, 0, 1, 4, 2, NB)
    c.box(5, 2, 0, 5, 4, 2, NB)
    c.box(1, 5, 2, 1, 5, 3, NB)
    c.box(5, 5, 2, 5, 5, 3, NB)
    c.box(0, 5, 3, 0, 5, 8, NB)
    c.box(6, 5, 3, 6, 5, 8, NB)
    c.box(1, 5, 8, 5, 5, 8, NB)
    # 栅栏（含端头单臂，均 post 形状码）
    c.place(1, 6, 3, _FENCE)         # w 臂
    c.place(5, 6, 3, _FENCE)         # e 臂
    c.place(0, 6, 3, _FENCE)         # e+n 臂
    c.place(6, 6, 3, _FENCE)         # w+n 臂
    c.fence(0, 6, 4, 0, 6, 7)        # nsFence
    c.fence(6, 6, 4, 6, 6, 7)
    c.place(0, 6, 8, _FENCE)         # e+s 臂
    c.place(6, 6, 8, _FENCE)         # w+s 臂
    c.fence(1, 6, 8, 5, 6, 8)        # weFence
    c.place(1, 7, 8, _FENCE)         # e 臂
    c.fence(2, 7, 8, 4, 7, 8)
    c.place(5, 7, 8, _FENCE)         # w 臂
    c.place(2, 8, 8, _FENCE)         # e 臂
    c.place(3, 8, 8, _FENCE)         # we 臂
    c.place(4, 8, 8, _FENCE)         # w 臂
    # spawner：局部 (3,5,5)（chunkBB 恒真、blaze 由 UI 语义标注）
    c.place(3, 5, 5, SPAWNER)
    # fillColumnDown x0..6 z0..6：跳过


def _piece_castle_entrance(c: _Ctx) -> None:
    # CastleEntrance.postProcess（Java L486-552）
    c.box(0, 3, 0, 12, 4, 12, NB)
    c.air_box(0, 5, 0, 12, 13, 12)
    c.box(0, 5, 0, 1, 12, 12, NB)
    c.box(11, 5, 0, 12, 12, 12, NB)
    c.box(2, 5, 11, 4, 12, 12, NB)
    c.box(8, 5, 11, 10, 12, 12, NB)
    c.box(5, 9, 11, 7, 12, 12, NB)
    c.box(2, 5, 0, 4, 12, 1, NB)
    c.box(8, 5, 0, 10, 12, 1, NB)
    c.box(5, 9, 0, 7, 12, 1, NB)
    c.box(2, 11, 2, 10, 12, 10, NB)
    c.fence(5, 8, 0, 7, 8, 0)        # 裸 NETHER_BRICK_FENCE（post）
    for i in range(1, 12, 2):        # i = 1,3,5,7,9,11
        c.fence(i, 10, 0, i, 11, 0)  # weFence
        c.fence(i, 10, 12, i, 11, 12)
        c.fence(0, 10, i, 0, 11, i)  # nsFence
        c.fence(12, 10, i, 12, 11, i)
        c.place(i, 13, 0, NB)
        c.place(i, 13, 12, NB)
        c.place(0, 13, i, NB)
        c.place(12, 13, i, NB)
        if i == 11:
            continue
        c.place(i + 1, 13, 0, _FENCE)
        c.place(i + 1, 13, 12, _FENCE)
        c.place(0, 13, i + 1, _FENCE)
        c.place(12, 13, i + 1, _FENCE)
    c.place(0, 13, 0, _FENCE)        # n+e 臂
    c.place(0, 13, 12, _FENCE)       # s+e 臂
    c.place(12, 13, 12, _FENCE)      # s+w 臂
    c.place(12, 13, 0, _FENCE)       # n+w 臂
    for z2 in range(3, 10, 2):       # z2 = 3,5,7,9
        c.fence(1, 7, z2, 1, 8, z2)  # ns+w 臂
        c.fence(11, 7, z2, 11, 8, z2)  # ns+e 臂
    c.box(4, 2, 0, 8, 2, 12, NB)
    c.box(0, 2, 4, 12, 2, 8, NB)
    c.box(4, 0, 0, 8, 1, 3, NB)
    c.box(4, 0, 9, 8, 1, 12, NB)
    c.box(0, 0, 4, 3, 1, 8, NB)
    c.box(9, 0, 4, 12, 1, 8, NB)
    # fillColumnDown x4..8 / x0..2+10..12：跳过
    c.box(5, 5, 5, 7, 5, 7, NB)
    c.air_box(6, 1, 6, 6, 4, 6)
    c.place(6, 0, 6, NB)
    c.place(6, 5, 6, LAVA)


def _piece_castle_small_corridor(c: _Ctx) -> None:
    # CastleSmallCorridorPiece.postProcess（Java L582-598）
    c.box(0, 0, 0, 4, 1, 4, NB)
    c.air_box(0, 2, 0, 4, 5, 4)
    c.box(0, 2, 0, 0, 5, 4, NB)
    c.box(4, 2, 0, 4, 5, 4, NB)
    c.fence(0, 3, 1, 0, 4, 1)        # nsFence
    c.fence(0, 3, 3, 0, 4, 3)
    c.fence(4, 3, 1, 4, 4, 1)
    c.fence(4, 3, 3, 4, 4, 3)
    c.box(0, 6, 0, 4, 6, 4, NB)
    # fillColumnDown：跳过


def _piece_corridor_turn(c: _Ctx, chest: bool) -> None:
    """CastleSmallCorridorRight/LeftTurnPiece.postProcess
    （Java L637-659 / L698-720，isNeedingChest 来自 chest_count）。"""
    c.box(0, 0, 0, 4, 1, 4, NB)
    c.air_box(0, 2, 0, 4, 5, 4)
    # --- RightTurn（Java L642-648）---
    c.box(0, 2, 0, 0, 5, 4, NB)
    c.fence(0, 3, 1, 0, 4, 1)        # nsFence
    c.fence(0, 3, 3, 0, 4, 3)
    c.box(4, 2, 0, 4, 5, 0, NB)
    c.box(1, 2, 4, 4, 5, 4, NB)
    c.fence(1, 3, 4, 1, 4, 4)        # weFence
    c.fence(3, 3, 4, 3, 4, 4)
    if chest:                        # 局部 (1,2,3)，createChest
        c.place(1, 2, 3, (CHEST_MAT, bs.SHAPE_CHEST_N))
    c.box(0, 6, 0, 4, 6, 4, NB)
    # fillColumnDown：跳过


def _piece_corridor_turn_left(c: _Ctx, chest: bool) -> None:
    # CastleSmallCorridorLeftTurnPiece.postProcess（Java L698-720）
    c.box(0, 0, 0, 4, 1, 4, NB)
    c.air_box(0, 2, 0, 4, 5, 4)
    c.box(4, 2, 0, 4, 5, 4, NB)
    c.fence(4, 3, 1, 4, 4, 1)        # nsFence
    c.fence(4, 3, 3, 4, 4, 3)
    c.box(0, 2, 0, 0, 5, 0, NB)
    c.box(0, 2, 4, 3, 5, 4, NB)
    c.fence(1, 3, 4, 1, 4, 4)        # weFence
    c.fence(3, 3, 4, 3, 4, 4)
    if chest:                        # 局部 (3,2,3)
        c.place(3, 2, 3, (CHEST_MAT, bs.SHAPE_CHEST_N))
    c.box(0, 6, 0, 4, 6, 4, NB)
    # fillColumnDown：跳过


def _piece_corridor_stairs(c: _Ctx) -> None:
    # CastleCorridorStairsPiece.postProcess（Java L750-775）
    # 楼梯局部 FACING=SOUTH（Java L751），经 _Ctx.stairs 变换。
    for step in range(10):           # step = 0..9
        floor = max(1, 7 - step)
        roof = min(max(floor + 5, 14 - step), 13)
        z = step
        c.box(0, 0, z, 4, floor, z, NB)
        c.air_box(1, floor + 1, z, 3, roof - 1, z)
        if step <= 6:
            c.stairs(1, floor + 1, z, "s")
            c.stairs(2, floor + 1, z, "s")
            c.stairs(3, floor + 1, z, "s")
        c.box(0, roof, z, 4, roof, z, NB)
        c.box(0, floor + 1, z, 0, roof - 1, z, NB)
        c.box(4, floor + 1, z, 4, roof - 1, z, NB)
        if (step & 1) == 0:
            c.fence(0, floor + 2, z, 0, floor + 3, z)   # nsFence
            c.fence(4, floor + 2, z, 4, floor + 3, z)
        # fillColumnDown：跳过


def _piece_t_balcony(c: _Ctx) -> None:
    # CastleCorridorTBalconyPiece.postProcess（Java L811-840）
    c.box(0, 0, 0, 8, 1, 8, NB)
    c.air_box(0, 2, 0, 8, 5, 8)
    c.box(0, 6, 0, 8, 6, 5, NB)
    c.box(0, 2, 0, 2, 5, 0, NB)
    c.box(6, 2, 0, 8, 5, 0, NB)
    c.fence(1, 3, 0, 1, 4, 0)        # weFence
    c.fence(7, 3, 0, 7, 4, 0)
    c.box(0, 2, 4, 8, 2, 8, NB)
    c.air_box(1, 1, 4, 2, 2, 4)
    c.air_box(6, 1, 4, 7, 2, 4)
    c.fence(1, 3, 8, 7, 3, 8)        # weFence
    c.place(0, 3, 8, _FENCE)         # e+s 臂
    c.place(8, 3, 8, _FENCE)         # w+s 臂
    c.fence(0, 3, 6, 0, 3, 7)        # nsFence
    c.fence(8, 3, 6, 8, 3, 7)
    c.box(0, 3, 4, 0, 5, 5, NB)
    c.box(8, 3, 4, 8, 5, 5, NB)
    c.box(1, 3, 5, 2, 5, 5, NB)
    c.box(6, 3, 5, 7, 5, 5, NB)
    c.fence(1, 4, 5, 1, 5, 5)        # weFence
    c.fence(7, 4, 5, 7, 5, 5)
    # fillColumnDown z0..5：跳过


def _piece_corridor_crossing(c: _Ctx) -> None:
    # CastleSmallCorridorCrossingPiece.postProcess（Java L872-885）
    c.box(0, 0, 0, 4, 1, 4, NB)
    c.air_box(0, 2, 0, 4, 5, 4)
    c.box(0, 2, 0, 0, 5, 0, NB)
    c.box(4, 2, 0, 4, 5, 0, NB)
    c.box(0, 2, 4, 0, 5, 4, NB)
    c.box(4, 2, 4, 4, 5, 4, NB)
    c.box(0, 6, 0, 4, 6, 4, NB)
    # fillColumnDown：跳过


def _piece_stalk_room(c: _Ctx) -> None:
    # CastleStalkRoom.postProcess（Java L916-1015）
    c.box(0, 3, 0, 12, 4, 12, NB)
    c.air_box(0, 5, 0, 12, 13, 12)
    c.box(0, 5, 0, 1, 12, 12, NB)
    c.box(11, 5, 0, 12, 12, 12, NB)
    c.box(2, 5, 11, 4, 12, 12, NB)
    c.box(8, 5, 11, 10, 12, 12, NB)
    c.box(5, 9, 11, 7, 12, 12, NB)
    c.box(2, 5, 0, 4, 12, 1, NB)
    c.box(8, 5, 0, 10, 12, 1, NB)
    c.box(5, 9, 0, 7, 12, 1, NB)
    c.box(2, 11, 2, 10, 12, 10, NB)
    for i in range(1, 12, 2):
        c.fence(i, 10, 0, i, 11, 0)  # weFence
        c.fence(i, 10, 12, i, 11, 12)
        c.fence(0, 10, i, 0, 11, i)  # nsFence
        c.fence(12, 10, i, 12, 11, i)
        c.place(i, 13, 0, NB)
        c.place(i, 13, 12, NB)
        c.place(0, 13, i, NB)
        c.place(12, 13, i, NB)
        if i == 11:
            continue
        c.place(i + 1, 13, 0, _FENCE)
        c.place(i + 1, 13, 12, _FENCE)
        c.place(0, 13, i + 1, _FENCE)
        c.place(12, 13, i + 1, _FENCE)
    c.place(0, 13, 0, _FENCE)        # n+e 臂
    c.place(0, 13, 12, _FENCE)       # s+e 臂
    c.place(12, 13, 12, _FENCE)      # s+w 臂
    c.place(12, 13, 0, _FENCE)       # n+w 臂
    for z2 in range(3, 10, 2):
        c.fence(1, 7, z2, 1, 8, z2)  # nswFence
        c.fence(11, 7, z2, 11, 8, z2)  # nseFence
    # 中央螺旋楼梯：局部 FACING=NORTH（Java L957）
    for i in range(7):               # i = 0..6
        z3 = i + 4
        for x in range(5, 8):
            c.stairs(x, 5 + i, z3, "n")
        if 5 <= z3 <= 8:
            c.box(5, 5, z3, 7, i + 4, z3, NB)
        elif 9 <= z3 <= 10:
            c.box(5, 8, z3, 7, i + 4, z3, NB)
        if i >= 1:
            c.air_box(5, 6 + i, z3, 7, 9 + i, z3)
    for x2 in range(5, 8):
        c.stairs(x2, 12, 11, "n")
    c.fence(5, 6, 7, 5, 7, 7)        # nseFence
    c.fence(7, 6, 7, 7, 7, 7)        # nswFence
    c.air_box(5, 13, 12, 7, 13, 12)
    c.box(2, 5, 2, 3, 5, 3, NB)
    c.box(2, 5, 9, 3, 5, 10, NB)
    c.box(2, 5, 4, 2, 5, 8, NB)
    c.box(9, 5, 2, 10, 5, 3, NB)
    c.box(9, 5, 9, 10, 5, 10, NB)
    c.box(10, 5, 4, 10, 5, 8, NB)
    # 平台边缘楼梯（局部 FACING=WEST/EAST，Java L985-992）
    for zz in (2, 3, 9, 10):
        c.stairs(4, 5, zz, "w")
        c.stairs(8, 5, zz, "e")
    c.box(3, 4, 4, 4, 4, 8, SOUL_SAND)
    c.box(8, 4, 4, 9, 4, 8, SOUL_SAND)
    c.box(3, 5, 4, 4, 5, 8, _WART)
    c.box(8, 5, 4, 9, 5, 8, _WART)
    c.box(4, 2, 0, 8, 2, 12, NB)
    c.box(0, 2, 4, 12, 2, 8, NB)
    c.box(4, 0, 0, 8, 1, 3, NB)
    c.box(4, 0, 9, 8, 1, 12, NB)
    c.box(0, 0, 4, 3, 1, 8, NB)
    c.box(9, 0, 4, 12, 1, 8, NB)
    # fillColumnDown：跳过


def _piece_bridge_end_filler(c: _Ctx, self_seed: int) -> None:
    # BridgeEndFiller.postProcess（Java L1050-1074）
    # selfRandom = RandomSource.createThreadLocalInstance((long)selfSeed)
    #   = LegacyRandomSource = java.util.Random 精确语义（JavaRandom）。
    # selfSeed 为无符号 32 位捕获（mc_random.next_bits），Java 存储为
    # 有符号 int32（(long)selfSeed 符号扩展），先转回有符号再传。
    rng = loot_rng.JavaRandom(self_seed if self_seed < 1 << 31
                              else self_seed - (1 << 32))
    for x in range(5):
        for y in (3, 4):
            z = rng.next_int(8)
            c.box(x, y, 0, x, y, z, NB)
    z2 = rng.next_int(8)
    c.box(0, 5, 0, 0, 5, z2, NB)
    z2 = rng.next_int(8)
    c.box(4, 5, 0, 4, 5, z2, NB)
    for x in range(5):
        z3 = rng.next_int(5)
        c.box(x, 2, 0, x, 2, z3, NB)
    for x in range(5):
        for y in (0, 1):
            z = rng.next_int(3)
            c.box(x, y, 0, x, y, z, NB)


# ============================================================ 入口

# 类型号 -> 布局函数（xp features/fortress.c 类型序 = Java 类序）。
# 9/10（拐角）需 chest 标志，14 需 selfSeed，单独分发。
_DISPATCH = {
    0: _piece_start_bridge_crossing,   # NeStart（=BridgeCrossing 布局）
    1: _piece_bridge_straight,         # NeBS
    2: _piece_start_bridge_crossing,   # NeBCr（BridgeCrossing 同布局）
    3: _piece_room_crossing,           # NeRC
    4: _piece_stairs_room,             # NeSR
    5: _piece_monster_throne,          # NeMT
    6: _piece_castle_entrance,         # NeCE
    7: _piece_castle_small_corridor,   # NeSC
    8: _piece_corridor_crossing,       # NeSCSC
    12: _piece_t_balcony,              # NeCTB
    13: _piece_stalk_room,             # NeCSR
}


def build_fortress_voxels(comp) -> dict:
    """Composition -> 模型体素 dict {(x,y,z): 值}（模型坐标）。

    遍历 comp.pieces（accepted 顺序 = Java postProcess 顺序，后写
    覆盖先写），把 piece 的 AABB 平移到模型系（- anchor，y-64），
    逐类型执行布局转写。返回值不含箱子标注逻辑（compose_display_model
    负责）。
    """
    vox: dict = {}
    ax, az = comp.anchor
    for p in comp.pieces:
        if p.bb is None or p.type == 14 and p.self_seed is None:
            continue
        pbb = _PieceBB(p.bb)
        facing = p.rot if p.rot is not None else 0

        def write(wx: int, wy: int, wz: int, val):
            if val is None:              # AIR：显式挖空
                vox.pop((wx - ax, wy - 64, wz - az), None)
                return
            vox[(wx - ax, wy - 64, wz - az)] = val

        c = _Ctx(pbb, facing, write)
        fn = _DISPATCH.get(p.type)
        if fn is not None:
            fn(c)
        elif p.type == 9:                # CORRIDOR_TURN_RIGHT
            _piece_corridor_turn(c, bool(p.chest_count))
        elif p.type == 10:               # CORRIDOR_TURN_LEFT
            _piece_corridor_turn_left(c, bool(p.chest_count))
        elif p.type == 14:               # FORTRESS_END（BridgeEndFiller）
            if p.self_seed is not None:
                _piece_bridge_end_filler(c, p.self_seed)
        # 其余（理论无）：跳过
    return vox
