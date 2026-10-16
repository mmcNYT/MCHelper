# -*- coding: utf-8 -*-
"""StructurePreviewer：箱子朝向 reorient（官方 StructurePiece.reorient 转写）。

官方链路：`StructurePiece.createChest(level, bb, rng, x, y, z, table)`
（1.21.11 反编译 `ffs`）在未显式传入 BlockState 时调用
`reorient(level, pos, Blocks.CHEST.defaultBlockState())` 自动定向——
箱子锁扣必须背向实心墙，否则视觉上"面壁"。

`reorient` 算法（`StructurePiece.java` L354-396 逐行转写）：
    ① 扫水平四邻（Direction.Plane.HORIZONTAL 序 = N,E,S,W）：
       若有邻为 CHEST -> **原样返回**（避免两个箱子对脸）；
    ② 记录**唯一**的 isSolidRender 邻；出现第二个实心邻即放弃
       （`$$3 = null; break`）；
    ③ 有唯一实心邻 -> FACING = 该邻的**对向**（锁扣背向实心墙）；
    ④ 否则 fallback 链：从默认 FACING（chest 默认态 = NORTH）起，
       依次 反 -> 顺时针 -> 反，取第一个非实心邻。

本模块**不消耗任何 RNG**（纯几何），故不影响已对拍的 LootTableSeed。

`isSolidRender` 语义（`BlockBehaviour.java` L489/L630）：
    solidRender = Block.isShapeFullBlock(occlusionShape)
即"**遮挡形状为满块**"，与透明度无关。对应本项目模型：
    - 体素值为元组 (mat, shape) -> 非整格形状 -> 非满块 -> False；
    - 整格字符串 -> 满块，但水/岩浆的 occlusionShape 为空 -> False。
实测四结构（沙漠神殿/丛林神庙/下界要塞/要塞）箱子邻位出现的材质为
cut sandstone / cobblestone / stone bricks / mossy cobblestone /
bookshelf（整格实心）与 stone brick slab / tripwire / torch（形状码，
非满块），本判定与官方逐格一致。
"""
from __future__ import annotations

# Direction.Plane.HORIZONTAL 序（官方 faces 数组序 = N,E,S,W）
HORIZ = ("n", "e", "s", "w")

_STEP = {"n": (0, -1), "e": (1, 0), "s": (0, 1), "w": (-1, 0)}
_OPP = {"n": "s", "s": "n", "e": "w", "w": "e"}
_CW = {"n": "e", "e": "s", "s": "w", "w": "n"}     # Direction.getClockWise

# occlusionShape 为空（非满块）的整格材质：水/岩浆。
# BlockBehaviour.solidRender = isShapeFullBlock(occlusionShape)，
# 水/岩浆的 occlusionShape 是空形状 -> isSolidRender() == false。
_NON_SOLID_FULL = frozenset({"water", "lava"})


def _mat_of(val) -> str | None:
    """体素值 -> 材质键（元组取首元素；None = 空气）。"""
    if val is None:
        return None
    if isinstance(val, tuple):
        return val[0]
    return val


def is_chest(val) -> bool:
    """该体素是否为箱子（官方 `state.is(Blocks.CHEST)` 近似）。"""
    m = _mat_of(val)
    return m is not None and m.endswith("chest")


def is_solid_render(val) -> bool:
    """官方 `BlockState.isSolidRender()`：遮挡形状为满块。"""
    if val is None:
        return False
    if isinstance(val, tuple):
        return False               # 非整格形状 -> 遮挡形状非满块
    return val not in _NON_SOLID_FULL


def reorient(get, pos, default: str = "n") -> str:
    """官方 StructurePiece.reorient -> 世界水平 FACING 字母。

    get(pos) -> 体素值（None = 空气）。pos 为**放置时该坐标系**下的
    三元组；邻居偏移在各坐标系间平移不变，故世界系/模型系皆可。
    default = 箱子默认态朝向（Blocks.CHEST 默认 FACING = NORTH）。
    """
    x, y, z = pos
    unique = None
    for d in HORIZ:
        dx, dz = _STEP[d]
        nb = (x + dx, y, z + dz)
        val = get(nb)
        # ① 邻为箱子 -> 原样返回（防止两箱对脸）
        if is_chest(val):
            return default
        if is_solid_render(val):
            if unique is not None:
                unique = None      # 第二个实心邻 -> 放弃，走 fallback
                break
            unique = d
    # ③ 唯一实心邻 -> 取对向
    if unique is not None:
        return _OPP[unique]
    # ④ fallback 链：默认 -> 反 -> 顺时针 -> 反
    f = default
    dx, dz = _STEP[f]
    if is_solid_render(get((x + dx, y, z + dz))):
        f = _OPP[f]
        dx, dz = _STEP[f]
    if is_solid_render(get((x + dx, y, z + dz))):
        f = _CW[f]
        dx, dz = _STEP[f]
    if is_solid_render(get((x + dx, y, z + dz))):
        f = _OPP[f]
    return f


def chest_shape(get, pos, default: str = "n") -> str:
    """reorient 结果 -> 箱子形状码 `chest:<f>:single`。"""
    return "chest:" + reorient(get, pos, default) + ":single"
