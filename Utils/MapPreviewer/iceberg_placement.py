# -*- coding: utf-8 -*-
"""官方冰山 feature（IcebergFeature）复刻 + 放置链。

26.2 frozen_ocean / deep_frozen_ocean 的 features[2]（LOCAL_MODIFICATIONS,
decoration step=2）= [iceberg_packed(rarity 16), iceberg_blue(rarity 200),
amethyst_geode]，placement 链 = rarity_filter -> in_square -> biome。
feature 本体按 26.2 反编译 IcebergFeature.java 逐行复刻（.temp/mc262_decompile/）：
  - 椭圆(30%)/圆形两种形态；signedDistance 决定轮廓，圆版逐格随机扰动
  - 水上 overWaterHeight 3~27（圆版 10% 概率追加 7~25 巨型），水下最深 18
  - 30% 概率顶部 snow_block 帽（仅 air/snow/ice/water 格可替换）
  - signedDist>compareVal 的边缘格 10% 跳过（粗糙轮廓）
  - smooth：清悬浮冰（下方为空气）并把其上格清空 + 三面临空的孤立冰
  - cutOut：椭圆 90% / 圆 30% 概率在冰山上开洞（水下开到水、水上开到空气）
rng 语义：与树放置同链（structure_map.get_population_seed + decorrelated
step=2，Xoroshiro），iceberg_packed -> iceberg_blue 同流串行（官方 features[2]
列表顺序，place 内每次 next 调用都按 Java 短路求值顺序精确消耗）；
in_square 用 nextInt(16)（官方 InSquarePlacement）。浮点用 float32 模拟
Java float（Mth.ceil 边界格一致），signedDistance 用 float64（Math.cos）。

JM 显示语义（为何只返回出水部分，决定海面颜色）：
  - VanillaBlockHandler L67-68 把 ice/frosted_ice 标 BlockFlag.Ignore
    （冰在 JM 地图上从不显示）；BlockMD.isSnow 只含 snow_block/powder_snow/
    snow layer，ice 不算雪。
  - MC MOTION_BLOCKING = blocksMotion() || 有流体（Heightmap.java L151）；
    blocksMotion() = 碰撞 bounds 体积>=0.729 或 Ysize>=1（BlockBehaviour
    L502-545）。1 层 snow layer（高 0.125）不算 -> 冰面列（ice+snow layer）
    的 MOTION_BLOCKING 顶块=ice -> JM getBlockHeight 从该处向下扫遇 Ignore
    穿透（SurfaceRenderer L164-165）停在水面 -> 显示深蓝水色（官方
    frozen_ocean 瓦片实测 (42,41,148)，即 _render_rect 冰面改水色的依据）。
  - 冰山出水的 packed_ice/blue_ice/snow_block 均为 motion blocking（碰撞
    满块），正常成为顶块显示冰色/雪白帽，并经 heightmap 台阶获得 bevel
    立体感。水下部分 JM 不显示（水列在水面 break，mapBathymetry=false），
    故只返回 y>=海平面的方块。
"""
from __future__ import annotations

import math

import numpy as np

from Utils.MapPreviewer.tree_placement import _Rng as _BaseRng
from Utils.MapPreviewer.tree_placement import _decorrelated

_F32 = np.float32

_ICEBERG_BIOMES = ("frozen_ocean", "deep_frozen_ocean")

# IcebergFeature.place 所在 decoration step：LOCAL_MODIFICATIONS = 2
_ICEBERG_STEP = 2

# features[2] 列表顺序：packed(1/16) -> blue(1/200)；geode 不影响两者 rng
_ICEBERG_FEATURES = ((16, "minecraft:packed_ice"), (200, "minecraft:blue_ice"))


class _Rng(_BaseRng):
    """扩展 nextDouble / nextBoolean（Java 语义，Xoroshiro 版）。"""

    __slots__ = ()

    def next_double(self) -> float:
        # XoroshiroRandomSource.nextDouble(): (nextLong() >>> 11) * 2^-53
        return (self._xr.next_long() >> 11) / float(1 << 53)

    def next_boolean(self) -> bool:
        # nextBoolean(): (nextLong() & 1) != 0
        return (self._xr.next_long() & 1) != 0


def _ceil_f32(v) -> int:
    """Mth.ceil(float)：float32 值向上取整（float32 可被 float64 精确表示）。"""
    return int(math.ceil(float(v)))


def _r_ellipse(yoff: int, height: int, width: int) -> int:
    # heightDependentRadiusEllipse：无 rng
    scale = (_F32(1.0) - _F32(yoff) * _F32(yoff) / (_F32(height) * _F32(1.0))) \
        * _F32(width)
    return _ceil_f32(scale / _F32(2.0))


def _r_round(rng: "_Rng", yoff: int, height: int, width: int) -> int:
    # heightDependentRadiusRound：nextFloat + nextInt(5) 总是消耗；
    # height>15+n 分支内 nextInt(6) 在三元条件里求值（总是消耗）
    k = _F32(3.5) - rng.next_float()
    scale = (_F32(1.0) - _F32(yoff) * _F32(yoff) / (_F32(height) * k)) \
        * _F32(width)
    if height > 15 + rng.next_int(5):
        ty = yoff // 2 if yoff < 3 + rng.next_int(6) else yoff
        scale = (_F32(1.0) - _F32(ty) / (_F32(height) * k * _F32(0.4))) \
            * _F32(width)
    return _ceil_f32(scale / _F32(2.0))


def _r_steep(rng: "_Rng", yoff: int, height: int, width: int) -> int:
    # heightDependentRadiusSteep：nextFloat 一次
    k = _F32(1.0) + rng.next_float() / _F32(2.0)
    scale = (_F32(1.0) - _F32(yoff) / (_F32(height) * k)) * _F32(width)
    return _ceil_f32(scale / _F32(2.0))


def _sd_circle(rng: "_Rng", xo: int, zo: int, radius: int) -> float:
    # signedDistanceCircle：每次调用消耗一个 nextFloat
    off = _F32(10.0) * min(max(rng.next_float(), _F32(0.2)), _F32(0.8)) \
        / _F32(radius)
    return float(off) + float(xo * xo + zo * zo - radius * radius)


def _sd_ellipse(xo: int, zo: int, ox: int, oz: int, a: int, c: int,
                angle: float) -> float:
    # signedDistanceEllipse：Math.cos/sin 为 double
    # a/c 可为 0（getEllipseC 冠层收窄至 0、水下椭圆收缩为 0）：
    # Java double 除 0 = ±Inf/NaN（不抛异常），后续只判 sd < 0.0，
    # Inf/NaN 均为 false -> 返回 Inf 与官方逐位等价
    if a == 0 or c == 0:
        return math.inf
    dx = xo - ox
    dz = zo - oz
    ca = math.cos(angle)
    sa = math.sin(angle)
    return ((dx * ca - dz * sa) / a) ** 2 + ((dx * sa + dz * ca) / c) ** 2 - 1.0


def _ellipse_c(yoff: int, height: int, shape_c: int) -> int:
    # getEllipseC：冠部最后 3 层收窄
    c = shape_c
    if yoff > 0 and height - yoff <= 3:
        c -= 4 - (height - yoff)
    return c


def _place_iceberg(rng: "_Rng", wx: int, wz: int, main: str,
                   heights, x0: int, z0: int, w: int, h: int,
                   sea: int):
    """复刻 IcebergFeature.place。origin=(wx, sea, wz)。

    world(dx,dy,dz) 返回原方块近似：'a' 空气 / 'w' 水 / 'x' 实心
    （海床、pillar 冰柱体、地形；官方 packed_ice 不在可替换列表，同为 'x'）。
    vox 值：'m' 冰山主体（main 方块）、's' snow_block、'a' 空气、'w' 水。
    返回出水块 [(wx', wz', top_y, block_name)]。
    """
    snow_top = rng.next_double() > 0.7
    shape_angle = rng.next_double() * 2.0 * math.pi
    ea = 11 - rng.next_int(5)
    ec = 3 + rng.next_int(3)
    is_ell = rng.next_double() > 0.7
    over_h = rng.next_int(6) + 6 if is_ell else rng.next_int(15) + 3
    if (not is_ell) and rng.next_double() > 0.9:
        over_h += rng.next_int(19) + 7
    under_h = min(over_h + rng.next_int(11), 18)
    width = min(over_h + rng.next_int(7) - rng.next_int(5), 11)
    a = ea if is_ell else 11

    vox: dict = {}

    def world(dx, dy, dz):
        gy = wz + dz - z0
        gx = wx + dx - x0
        cy = min(max(gy, 0), h - 1)
        cx = min(max(gx, 0), w - 1)
        top = int(heights[cy, cx])
        y = sea + dy
        if y > top:
            if y <= sea and top < sea:
                return "w"
            return "a"
        return "x"

    def st_of(dx, dy, dz):
        k = (dx, dy, dz)
        if k in vox:
            return vox[k]
        return world(dx, dy, dz)

    def set_ice(dx, dy, dz, hdiff, height):
        st = st_of(dx, dy, dz)
        if st not in ("a", "w", "s"):
            return
        # randomness 在 state 检查之后无条件求值（isEllipse 短路）
        randomness = (not is_ell) or rng.next_double() > 0.05
        divisor = 3 if is_ell else 2
        if snow_top and st != "w":
            # && 链：前两条件真才消耗 nextInt
            thr = rng.next_int(max(1, height // divisor)) + height * 0.6
            if hdiff <= thr and randomness:
                vox[(dx, dy, dz)] = "s"
                return
        vox[(dx, dy, dz)] = "m"

    def gen_block(xo, yoff, zo, radius, height, aa=None):
        if aa is None:
            aa = a
        if is_ell:
            sd = _sd_ellipse(xo, zo, 0, 0, aa,
                             _ellipse_c(yoff, height, ec), shape_angle)
        else:
            sd = _sd_circle(rng, xo, zo, radius)
        if sd < 0.0:
            # compareVal：圆版总是消耗 nextInt(3)（三元无条件求值）
            cv = -0.5 if is_ell else -6 - rng.next_int(3)
            if sd > cv and rng.next_double() > 0.9:
                return
            set_ice(xo, yoff, zo, height - yoff, height)

    # ---- 水上部分 ----
    for xo in range(-a, a):
        for zo in range(-a, a):
            for yoff in range(0, over_h):
                if is_ell:
                    radius = _r_ellipse(yoff, over_h, width)
                else:
                    radius = _r_round(rng, yoff, over_h, width)
                if is_ell or xo < radius:
                    gen_block(xo, yoff, zo, radius, over_h)

    # ---- smooth（清悬浮冰 + 孤立冰；下方为空气时连同上格清空）----
    aa_s = ea if is_ell else width // 2
    for dx in range(-aa_s, aa_s + 1):
        for dz in range(-aa_s, aa_s + 1):
            for dy in range(0, over_h + 1):
                st = st_of(dx, dy, dz)
                if st in ("m", "s"):
                    if st_of(dx, dy - 1, dz) == "a":
                        vox[(dx, dy, dz)] = "a"
                        vox[(dx, dy + 1, dz)] = "a"
                    else:
                        cnt = 0
                        for nb in ((dx - 1, dy, dz), (dx + 1, dy, dz),
                                   (dx, dy, dz - 1), (dx, dy, dz + 1)):
                            if st_of(*nb) not in ("m", "s"):
                                cnt += 1
                        if cnt >= 3:
                            vox[(dx, dy, dz)] = "a"

    # ---- 水下部分（俯视不显示，仅维持 rng 流与官方一致）----
    for xo in range(-a, a):
        for zo in range(-a, a):
            for yoff in range(-1, -under_h, -1):
                if is_ell:
                    na = _ceil_f32(_F32(a) * (_F32(1.0)
                                   - _F32(yoff) * _F32(yoff)
                                   / _F32(under_h * 8.0)))
                else:
                    na = a
                radius = _r_steep(rng, -yoff, under_h, width)
                if xo < radius:
                    gen_block(xo, yoff, zo, radius, under_h, aa=na)

    # ---- cutOut（在冰山上开洞）----
    # doCutOut = isEllipse ? nextDouble() > 0.1 : nextDouble() > 0.7
    if rng.next_double() > (0.1 if is_ell else 0.7):
        sx = -1 if rng.next_boolean() else 1
        sz = -1 if rng.next_boolean() else 1
        xoff = rng.next_int(max(width // 2 - 2, 1))
        if rng.next_boolean():
            xoff = width // 2 + 1 - rng.next_int(max(width - width // 2 - 1, 1))
        zoff = rng.next_int(max(width // 2 - 2, 1))
        if rng.next_boolean():
            zoff = width // 2 + 1 - rng.next_int(max(width - width // 2 - 1, 1))
        if is_ell:
            xoff = zoff = rng.next_int(max(ea - 5, 1))
        ang = shape_angle + math.pi / 2 if is_ell \
            else rng.next_double() * 2.0 * math.pi
        for yoff in range(0, over_h - 3):
            radius = _r_round(rng, yoff, over_h, width)
            _carve(vox, st_of, radius, yoff, False, ang, sx * xoff, sz * zoff,
                   ea, ec)
        yoff = -1
        # Java for 条件 yOff > -height + nextInt(5) 逐次迭代求值：
        # 每轮循环消耗一个 nextInt(5)（不能提出循环外）
        while yoff > -over_h + rng.next_int(5):
            radius = _r_steep(rng, -yoff, over_h, width)
            _carve(vox, st_of, radius, yoff, True, ang, sx * xoff, sz * zoff,
                   ea, ec)
            yoff -= 1

    # ---- 收集出水部分（每列最高，y>=sea）----
    best = {}
    for (dx, dy, dz), st in vox.items():
        if dy < 0 or st not in ("m", "s"):
            continue
        k = (dx, dz)
        prev = best.get(k)
        if prev is None or dy > prev[0]:
            best[k] = (dy, st)
    res = []
    for (dx, dz), (dy, st) in best.items():
        gx = wx + dx - x0
        gz = wz + dz - z0
        if 0 <= gx < w and 0 <= gz < h:
            y = sea + dy
            if y > int(heights[gz, gx]):
                res.append((wx + dx, wz + dz, y,
                            "minecraft:snow_block" if st == "s" else main))
    return res


def _carve(vox, st_of, radius, yoff, under, ang, lox, loz, ea, ec):
    # generateCutOut.carve：椭圆洞，isIcebergState||snow -> 水/空气
    aa2 = radius + 1 + ea // 3
    cc2 = min(radius - 3, 3) + ec // 2 - 1
    for dx in range(-aa2, aa2):
        for dz in range(-aa2, aa2):
            sd = _sd_ellipse(dx, dz, lox, loz, aa2, cc2, ang)
            if sd < 0.0:
                st = st_of(dx, yoff, dz)
                if st in ("m", "s"):
                    vox[(dx, yoff, dz)] = "w" if under else "a"


def iceberg_placements(seed: int, x0: int, z0: int, w: int, h: int,
                       heights, biome_grid, id2key, sea_level: int = 63):
    """窗内所有冰山（官方 rarity/in_square/biome 过滤 + place 复刻）。

    返回 [(wx, wz, top_y, block_name)]，调用方做每列最高竞争。
    chunk 快筛用 4x4 量化群系网格（中心点），origin 处再判一次。
    """
    frz = set()
    for bid, key in id2key.items():
        if key.split(":")[-1] in _ICEBERG_BIOMES:
            frz.add(bid)
    if not frz:
        return []
    bg = np.asarray(biome_grid)
    ht = np.asarray(heights)
    out = []
    cx0, cx1 = x0 >> 4, (x0 + w - 1) >> 4
    cz0, cz1 = z0 >> 4, (z0 + h - 1) >> 4
    for cx in range(cx0, cx1 + 1):
        for cz in range(cz0, cz1 + 1):
            gx = cx * 16 + 8 - x0
            gz = cz * 16 + 8 - z0
            if gx < 0 or gx >= w or gz < 0 or gz >= h:
                continue
            if int(bg[gz, gx]) not in frz:
                continue
            rng = _Rng(_decorrelated(seed, cx, cz, _ICEBERG_STEP))
            for chance, main in _ICEBERG_FEATURES:
                # RarityFilter：通过 = nextFloat() < 1/chance
                if rng.next_float() >= 1.0 / chance:
                    continue
                # InSquarePlacement：nextInt(16) x2
                dx = rng.next_int(16)
                dz = rng.next_int(16)
                wx = cx * 16 + dx
                wz = cz * 16 + dz
                lx = wx - x0
                lz = wz - z0
                if lx < 0 or lx >= w or lz < 0 or lz >= h:
                    continue
                # BiomeFilter：origin 处群系
                if int(bg[lz, lx]) not in frz:
                    continue
                out.extend(_place_iceberg(rng, wx, wz, main, ht,
                                          x0, z0, w, h, sea_level))
    return out
