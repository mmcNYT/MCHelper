# -*- coding: utf-8 -*-
"""StrongHoldFinder 的纯计算模块：F3+C 命令解析 + 两视线求交点。

背景（末影之眼三角定位法）：
    末影之眼被抛出后会朝最近的要塞方向飞行。玩家在两个不同位置，
    分别把准星对准末影之眼飞走的方向按 F3+C，会复制出形如

        /execute in minecraft:overworld run tp @s 123.45 64.00 -678.90 120.5 15.0

    的传送命令，末尾 5 个数字依次为 x y z yaw pitch。
    两条「位置 + 视线朝向」确定的视线在水平面上的交点，即要塞的水平位置。

Minecraft 的 yaw 角度系与数学课本不同（0° 朝南、顺时针增大）：
    0° = 南(+Z)，90° = 西(-X)，180° = 北(-Z)，270° = 东(+X)
    因此水平面 (XZ) 上的视线方向向量为 (dx, dz) = (-sin(yaw), cos(yaw))。
"""

import math
import re

# 匹配带可选正负号的十进制数（F3+C 不会产生科学计数法，正则顺带兼容）
_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)")

# 两条视线的单位方向向量叉积（= sin 夹角）小于该阈值视为平行，
# 对应夹角约 0.00006°，只拦截「几乎原样复制两遍」的情况
_PARALLEL_CROSS_EPS = 1e-6

# 两观测点水平间距小于该值（格）视为同一位置，无法三角定位
_SAME_POSITION_EPS = 0.5

# 八方位名，索引 = round(规范化 yaw / 45) 再映射到 0~7（见 yaw_to_compass）
_COMPASS = ("南", "西南", "西", "西北", "北", "东北", "东", "东南")


def parse_f3c_command(text: str) -> tuple[float, float, float]:
    """从 F3+C 复制的命令文本中解析出 (x, z, yaw)。

    不依赖命令前缀的完整格式（新旧版本的命令前缀不同），而是抓取文本中
    所有数字、取最后 5 个，按 F3+C 的固定顺序解释为 x y z yaw pitch，
    因此同时兼容标准命令、旧版 /tp 命令以及手打的纯数字。

    Args:
        text: 粘贴进输入框的原始文本。

    Returns:
        (x, z, yaw)：水平坐标与水平视角（度，未规范化）。

    Raises:
        ValueError: 文本为空，或其中数字不足 5 个。
    """
    if not text or not text.strip():
        raise ValueError("输入为空：请先在游戏中按 F3+C，再把复制的内容粘贴进来")
    numbers = [float(m.group()) for m in _NUMBER_RE.finditer(text)]
    if len(numbers) < 5:
        raise ValueError(
            f"内容无法识别：只找到 {len(numbers)} 个数字，"
            "而 F3+C 复制的命令应包含 5 个数字（x y z yaw pitch），"
            f"示例：/execute in minecraft:overworld run tp @s 123.45 64.0 -678.9 120.5 15.0"
        )
    x, _y, z, yaw, _pitch = numbers[-5:]
    return x, z, yaw


def looks_like_f3c(text: str) -> bool:
    """判断剪贴板文本是否像 F3+C 复制的内容（剪贴板自动填入的预判门槛）。

    判据（故意保守，避免把网页/文档里复制的普通数字误填进坐标框）：
    - 文本非空且长度不超过 200 字符（F3+C 命令约 90 字符）；
    - 数字个数 5~8 个（标准命令 5 个；自定义维度名等可能额外带数字）；
    - 文本中至少含一个小数点（F3+C 的坐标与视角恒带小数，纯整数列表不算）。

    Args:
        text: 剪贴板中的原始文本。

    Returns:
        True 表示很可能是 F3+C 内容，可以自动填入坐标框。
    """
    if not text:
        return False
    text = text.strip()
    if not text or len(text) > 200:
        return False
    if "." not in text:
        return False
    count = len(_NUMBER_RE.findall(text))
    return 5 <= count <= 8


def yaw_to_direction(yaw: float) -> tuple[float, float]:
    """把 Minecraft 的 yaw 角转成 XZ 平面上的单位方向向量 (dx, dz)。

    MC 角度系：0°=南(+Z)，90°=西(-X)，180°=北(-Z)，270°=东(+X)。
    """
    rad = math.radians(yaw)
    return (-math.sin(rad), math.cos(rad))


def normalize_yaw(yaw: float) -> float:
    """把 yaw 规范到 [-180, 180) 区间，仅用于展示。"""
    yaw = math.fmod(yaw, 360.0)
    if yaw >= 180.0:
        yaw -= 360.0
    elif yaw < -180.0:
        yaw += 360.0
    return yaw


def yaw_to_compass(yaw: float) -> str:
    """把 yaw 转成八方位名（南/西南/西/西北/北/东北/东/东南）。

    先规范化到 [-180, 180)，再按 45° 一档就近取方位。
    """
    idx = (int(round(normalize_yaw(yaw) / 45.0)) + 8) % 8
    return _COMPASS[idx]


def intersect_rays(
    x1: float, z1: float, yaw1: float,
    x2: float, z2: float, yaw2: float,
) -> dict:
    """求两条视线的交点（要塞的水平位置）。

    每条视线由「位置 + yaw」确定，参数方程为
        (x, z) + t * (-sin(yaw), cos(yaw))，t > 0 表示视线前方。
    解法：对 t1 * (d1 × d2) = (P2 - P1) × d2（二维叉积）先解出 t1，再回代得交点。

    Args:
        x1, z1, yaw1: 第一个观测点的水平坐标与视角。
        x2, z2, yaw2: 第二个观测点的水平坐标与视角。

    Returns:
        dict，含：
            x, z          交点坐标
            t1, t2        交点沿两条视线的有向参数（>0 在视线前方，<0 在背后，
                          数值 ≈ 交点到该观测点的距离）
            dist1, dist2  交点到两观测点的距离（即 |t1|、|t2|）

    Raises:
        ValueError: 两视线几乎平行，或两观测点几乎在同一位置。
    """
    dx1, dz1 = yaw_to_direction(yaw1)
    dx2, dz2 = yaw_to_direction(yaw2)
    cross = dx1 * dz2 - dz1 * dx2  # 单位向量叉积 = sin(两视线夹角)
    if abs(cross) < _PARALLEL_CROSS_EPS:
        raise ValueError(
            "两条视线几乎平行，无法求交点。"
            "请走到与第一个观测点相距较远的位置再按一次 F3+C"
        )
    if math.hypot(x2 - x1, z2 - z1) < _SAME_POSITION_EPS:
        raise ValueError("两个观测点几乎在同一位置，无法三角定位；请走到远处再观测一次")
    ex, ez = x2 - x1, z2 - z1
    t1 = (ex * dz2 - ez * dx2) / cross
    ix, iz = x1 + t1 * dx1, z1 + t1 * dz1
    # 交点在第二条视线上的有向参数（单位方向向量点乘即距离）
    t2 = (ix - x2) * dx2 + (iz - z2) * dz2
    return {
        "x": ix,
        "z": iz,
        "t1": t1,
        "t2": t2,
        "dist1": abs(t1),
        "dist2": abs(t2),
    }
