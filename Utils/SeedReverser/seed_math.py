# -*- coding: utf-8 -*-
"""SeedReverser 的辅助纯函数：信息量估算、区域/偏移计算。

本模块不含任何 UI 与线程逻辑，全部为确定性纯函数。

数学背景：
    Minecraft 结构生成的区域种子为
        s0 = (structureSeed + regX*341873128712 + regZ*132897987541 + salt) mod 2^64
    结构区块偏移（线性散布）：
        st = setSeed(s0) = (s0 ^ 0x5DEECE66D) mod 2^48
        st1 = (st * 0x5DEECE66D + 0xB) mod 2^48 → offX = nextInt(st1, chunkRange)
        st2 = (st1 * 0x5DEECE66D + 0xB) mod 2^48 → offZ = nextInt(st2, chunkRange)
    区域坐标与偏移由玩家观测的方块坐标决定：
        cx = x >> 4；reg = floor(cx / region_size)；off = cx - reg * region_size
"""

import math

# regionSeed 系数（cubiomes getRegionSeed）
_REG_X_COEF = 341873128712
_REG_Z_COEF = 132897987541


# ---------------------------------------------------------------------------
# 信息量
# ---------------------------------------------------------------------------

def calc_info_bits(observations) -> float:
    """返回所有观测的累计约束比特数（按各观测容差折减）。

    基础信息量：线性散布结构 offX/offZ 各贡献 log2(chunk_range)
    （合计约 9.17 比特）；三角散布（monument 等）四次 nextInt 取
    平均，约 log2(chunk_range)（单次 nextInt 的量）。

    容差折减：站位容差 tol 把每维位置约束从 1 个值放宽为
    min(2*tol+1, chunk_range) 个候选值（与求解器层 2 范围校验的
    通过率口径一致，_estimate_tolerance_work），该维信息量按
    log2(有效窗口/1) 折减；tol=0 时窗口为 1、无折减。

    Args:
        observations: 观测列表，每项为
            - 观测 dict（含 "params" 与可选 "tol"，即 UI 的 obs 结构，
              tol 缺省按 0 精确处理），或
            - params dict / 带 chunk_range 与 scatter 属性的对象
              （无容差概念，等效 tol=0，向后兼容）。

    Returns:
        累计比特数（float）。
    """
    total = 0.0
    for item in observations:
        # 双形态条目：观测 dict（含 "params" + 可选 "tol"）或 params
        # 本体（dict / 属性对象，无容差概念，等效 tol=0）
        if isinstance(item, dict) and "params" in item:
            params = item["params"]
            raw_tol = item.get("tol", 0)
        else:
            params = item
            raw_tol = 0
        chunk_range = getattr(params, "chunk_range", None)
        if chunk_range is None:
            chunk_range = params.get("chunk_range", 0)
        scatter = getattr(params, "scatter", None)
        if scatter is None:
            scatter = params.get("scatter", "linear")
        # 容差钳制 0~2（与 structure_math._obs_tol、UI 行内下拉同域）
        try:
            tol = max(0, min(2, int(raw_tol)))
        except (TypeError, ValueError):
            tol = 0
        # 每维有效窗口：tol 越大窗口越宽，上限 chunk_range
        window = min(2 * tol + 1, max(chunk_range, 1))
        dims = 1 if scatter == "triangle" else 2
        # 每维信息量 = log2(r) - log2(window)；window=r 时该维归零
        total += dims * math.log2(max(chunk_range, 1) / window)
    return total


def info_hint(bits: float) -> str:
    """按累计比特数返回提示文案（UI 信息量条右侧提示）。"""
    if bits < 9:
        return "至少需要 3 个结构才能计算"
    if bits < 18:
        return "再找 2~3 个结构"
    if bits < 27:
        return "可以尝试计算，再找 1~2 个更准"
    if bits < 40:
        return "信息量充足，可以计算"
    return "信息量非常充足，直接计算即可"


# ---------------------------------------------------------------------------
# 区域 / 偏移计算
# ---------------------------------------------------------------------------

def compute_region(block_x: int, block_z: int, region_size: int) -> tuple[int, int]:
    """由方块坐标计算所在区域坐标（区块单位，数学地板除）。

    方块坐标 → 区块坐标 cx = x >> 4；区域坐标 reg = floor(cx / region_size)。
    Python 的 // 即数学地板除，负数坐标正确。

    Args:
        block_x: 方块 X。
        block_z: 方块 Z。
        region_size: 区域边长（区块单位）。

    Returns:
        (reg_x, reg_z)。
    """
    return (block_x >> 4) // region_size, (block_z >> 4) // region_size


def compute_offset(block_x: int, block_z: int, reg_x: int, reg_z: int,
                   region_size: int) -> tuple[int, int]:
    """由方块坐标与区域坐标计算区域内区块偏移（offX, offZ）。

    offX = cx - regX * region_size；保证 0 <= off < region_size。

    Args:
        block_x: 方块 X。
        block_z: 方块 Z。
        reg_x: 区域 X。
        reg_z: 区域 Z。
        region_size: 区域边长（区块单位）。

    Returns:
        (off_x, off_z)。
    """
    cx = block_x >> 4
    cz = block_z >> 4
    return cx - reg_x * region_size, cz - reg_z * region_size


def is_near_boundary(off_x: int, off_z: int, region_size: int, threshold: int = 2) -> bool:
    """判断偏移是否离区域边界过近（区块单位）。

    结构区块偏移 ∈ [0, region_size)，但实际可用范围是
    [chunkRange 相关缓冲之外]；这里用通用阈值：off < threshold 或
    off > region_size - 1 - threshold 视为靠近边界。

    Args:
        off_x: 区域 X 偏移。
        off_z: 区域 Z 偏移。
        region_size: 区域边长。
        threshold: 边界距离阈值（区块）。

    Returns:
        True 表示至少一维离边界过近。
    """
    return (off_x < threshold or off_x > region_size - 1 - threshold
            or off_z < threshold or off_z > region_size - 1 - threshold)


def region_seed_value(structure_seed: int, reg_x: int, reg_z: int, salt: int) -> int:
    """regionSeed 原始 64 位值（setSeed 之前）。

    s0 = structureSeed + regX*341873128712 + regZ*132897987541 + salt
         （mod 2^64 回绕）

    Args:
        structure_seed: 48 位结构种。
        reg_x: 区域 X（区块单位）。
        reg_z: 区域 Z（区块单位）。
        salt: 结构 salt。

    Returns:
        0~2^64-1 的整数。
    """
    return (structure_seed
            + reg_x * _REG_X_COEF
            + reg_z * _REG_Z_COEF
            + salt) & ((1 << 64) - 1)