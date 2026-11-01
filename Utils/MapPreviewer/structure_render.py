# -*- coding: utf-8 -*-
"""陆地结构渲染：把 jigsaw / 单模板结构还原成真实方块（替代矩形近似）。

MC 26.2 的陆地结构分三类：
  A) jigsaw 型：由 template_pool 递归拼接 —— 村庄、掠夺者前哨、
     远古城市、废墟遗迹、试炼密室、堡垒遗迹。
     复用 village_jigsaw_exact 的拼接器（连接点匹配 + 旋转 + 不重叠）。
  B) 固定模板型：Java 代码把少量模板按固定方式堆叠 ——
     雪屋(igloo: bottom+middle+top)、沉船。废弃传送门曾属此类，
     现走官方 postProcess 全链复刻（见 ruined_portal_blocks：
     变体选择 + 处理器链 + 菱形土堆/滴柱/藤叶，StructurePreviewer
     _RPSim 复用）。
   C) 纯程序化型：无 NBT 模板，由 Java 逐方块生成 ——
      沙漠神殿、丛林神庙、沼泽小屋。这类仍用**按真实尺寸**的
      footprint 近似。林地府邸曾属此类，现走真实块渲染（见
      mansion_blocks：复用 StructurePreviewer mansion_pieces 的
      MansionGrid 拼装 + 官方 5×5 盒最低地表 y，俯视显示真实屋顶）。
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

import numpy as np

from Utils.MapPreviewer import village_jigsaw as _vj

try:
    from Utils.MapPreviewer._native import _density_sampler as _native
except Exception:
    _native = None

# 结构 key -> (类型, 参数)
#   jigsaw: 起始 pool；stack: 模板列表(自下而上)；pick: 模板目录
_JIGSAW_START = {
    "pillager_outpost": "minecraft:pillager_outpost/base_plates",
    "ancient_city": "minecraft:ancient_city/city_center",
    "trail_ruins": "minecraft:trail_ruins/tower",
    "trial_chambers": "minecraft:trial_chambers/chamber/end",
    "bastion_remnant": "minecraft:bastion/starts",
}
# 固定堆叠：自下而上的模板路径
_STACK = {
    "igloo": ["minecraft:igloo/bottom", "minecraft:igloo/middle",
              "minecraft:igloo/top"],
}
# 从目录中按种子挑一个模板
_PICK = {
    "shipwreck": "minecraft:shipwreck/",
}
# 纯程序化结构：(宽, 长) 取自 MC 实际占地
_PROCEDURAL = {
    "desert_pyramid": (21, 21),
    "jungle_temple": (12, 12),
    "swamp_hut": (10, 12),
    "mansion": (20, 30),
}

_SKIP = {"air", "jigsaw", "structure_void", "cave_air", "void_air", ""}


def _pick_one(loc_prefix: str, seed: int, ax: int, az: int) -> str | None:
    """从模板目录里按 (seed, 坐标) 稳定地挑一个模板。"""
    jar = _vj._jar()
    stem = loc_prefix.split(":", 1)[-1].strip("/")
    pre = "data/minecraft/structure/%s/" % stem
    cands = sorted(n[len(pre):-4] for n in jar.namelist()
                   if n.startswith(pre) and n.endswith(".nbt"))
    cands = [c for c in cands if "/" not in c]
    if not cands:
        return None
    # 稳定散列：同一结构每次渲染选同一模板
    h = (seed * 2654435761 ^ ax * 40503 ^ az * 97) & 0x7FFFFFFF
    return "minecraft:%s/%s" % (stem, cands[h % len(cands)])


def _stamp_template(loc: str, ox: int, oy: int, oz: int,
                    out: list, seen: set) -> int:
    """把一个模板放到世界坐标 (ox,oy,oz)（原点=模板最小角）。"""
    tpl = _vj.load_template(loc)
    if tpl is None:
        return 0
    n = 0
    for (x, y, z, nm) in tpl["blocks"]:
        if nm.split(":")[-1] in _SKIP:
            continue
        out.append((ox + x, oy + y, oz + z, nm))
        n += 1
    return n


def structure_blocks(key: str, seed: int, ax: int, az: int,
                     base_y: int, max_blocks: int = 60000) -> list:
    """返回该结构在世界坐标下的实体方块列表 [(x,y,z,name)]。

    空列表表示该结构无模板（调用方应回退到 footprint 近似）。
    """
    out: list = []
    if key in _JIGSAW_START:
        try:
            from Utils.MapPreviewer import village_jigsaw_exact as _vx
            r = _vx.build_jigsaw(seed, ax, az, _JIGSAW_START[key],
                                 base_y=base_y, max_blocks=max_blocks)
            for (x, y, z, nm) in r["blocks"]:
                if nm.split(":")[-1] not in _SKIP:
                    out.append((x, y, z, nm))
        except Exception:
            return []
        return out
    if key in _STACK:
        seen = set()
        y = base_y
        for loc in _STACK[key]:
            tpl = _vj.load_template(loc)
            if tpl is None:
                return []
            _stamp_template(loc, ax - tpl["size"][0] // 2, y,
                            az - tpl["size"][2] // 2, out, seen)
            y += tpl["size"][1]          # 自下而上堆叠
        return out
    if key in _PICK:
        loc = _pick_one(_PICK[key], seed, ax, az)
        if not loc:
            return []
        tpl = _vj.load_template(loc)
        if tpl is None:
            return []
        _stamp_template(loc, ax - tpl["size"][0] // 2, base_y,
                        az - tpl["size"][2] // 2, out, set())
        return out
    return []


def procedural_size(key: str):
    """纯程序化结构的真实占地尺寸（无模板可用）。"""
    return _PROCEDURAL.get(key)


# ------------------------------------------------------------------
# 废弃传送门：官方 postProcess 全链复刻（26.2 反编译逐行）。
# 复用 StructurePreviewer 的 _RPSim（setup 流 + 处理器链 + 菱形土堆/
# 底层支撑柱/藤叶），本模块补三件适配：
#   1) 变体选择：enumerate_structures 对 ruined_portal 恒 viable 不采样
#      群系（cubiomes 口径），此处按锚点地表群系 id（BIOME_ID cubiomes
#      系）-> structures JSON 数组序首个 tag 命中（全不中 fallback
#      standard）；官方按各结构 JSON 的 stub 位置逐变体校验，地图口径
#      以地表群系近似（洞穴/地下群系不参与变体选择）；
#   2) 真实地表：surface_fn = fill_top_grid 网格（官方 getBaseHeight/
#      getSurfaceY 口径，无 RNG）——mound 逐列贴地、findSuitableY 取
#      bb 中心真实地表 + 4 角投影扫描（3/4 角实心，fid L206-233）；
#   3) cold：can_be_cold 变体按锚点群系温度 < 0.15（26.2 biome JSON
#      temperature 字段；官方 coldEnoughToSnow 的高山高度衰减项未模拟，
#      仅影响山地高海拔个案的 magma/岩浆规则配色）。
# 俯视渲染只需基名：楼梯/台阶形状码与朝向属性不影响顶面色（颜色
# 由 4d 统一配色按 bid -> jm_palette 给出，jungle_leaves 自动走
# 群系叶 tint）。
# ------------------------------------------------------------------
_RP_MAT = {
    "netherrack": "minecraft:netherrack",
    "magma block": "minecraft:magma_block",
    "lava": "minecraft:lava",
    "obsidian": "minecraft:obsidian",
    "crying obsidian": "minecraft:crying_obsidian",
    "block of gold": "minecraft:gold_block",
    "iron bars": "minecraft:iron_bars",
    "stone": "minecraft:stone",
    "stone bricks": "minecraft:stone_bricks",
    "cracked stone bricks": "minecraft:cracked_stone_bricks",
    "mossy stone bricks": "minecraft:mossy_stone_bricks",
    "chiseled stone bricks": "minecraft:chiseled_stone_bricks",
    "stone brick stairs": "minecraft:stone_brick_stairs",
    "mossy stone brick stairs": "minecraft:mossy_stone_brick_stairs",
    "stone brick slab": "minecraft:stone_brick_slab",
    "mossy stone brick slab": "minecraft:mossy_stone_brick_slab",
    "stone slab": "minecraft:stone_slab",
    "mossy stone brick wall": "minecraft:mossy_stone_brick_wall",
    "jungle leaves": "minecraft:jungle_leaves",
    "chest": "minecraft:chest",
    "vine": "minecraft:vine",
    "vines": "minecraft:vine",
}

# 地表网格半径：mound 半径 14 + bb 中心偏移≤8 + 模板边≤16
_RP_GRID_HALF = 36

_BIOME_NAME_BY_ID: dict[int, str] = {}


def _rp_biome_name(bid: int) -> str | None:
    """cubiomes 系群系 id -> 名称（BIOME_ID 逆表，首次惰性建）。"""
    if not _BIOME_NAME_BY_ID:
        from Utils.SeedReverser import biome_noise as _bn
        for _nm, _bid in _bn.BIOME_ID.items():
            _BIOME_NAME_BY_ID.setdefault(_bid, _nm)
    return _BIOME_NAME_BY_ID.get(int(bid))


@lru_cache(maxsize=256)
def _rp_biome_temperature(biome_name: str) -> float | None:
    """26.2 官方 biome JSON temperature（缺文件 -> None，视为不冷）。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "_native", "worldgen", "26.2", "biome",
                        "%s.json" % biome_name)
    try:
        with open(path, encoding="utf-8") as f:
            return float(json.load(f).get("temperature", 1.0))
    except Exception:
        return None


def ruined_portal_blocks(seed: int, ax: int, az: int, pack: dict,
                         threads: int = 1) -> list:
    """官方废弃传送门全链模拟 -> [(x, y, z, "minecraft:xxx"), ...]。

    ax/az = 结构锚点（区块角，enumerate_structures 的 x/z）。
    地面以下（y < 该列实心顶）的方块被滤除——underground/in_mountain
    变体与滴柱俯视不可见；on_ocean_floor 的实体仍在水线以下，由
    水面链路自然呈现（与沉船同口径）。
    """
    from Utils.StructurePreviewer import ruined_portal_pieces as _rp

    if _native is None:
        return []
    ctx = (pack or {}).get("ctx")
    if ctx is None:
        return []
    gx0, gz0 = ax - _RP_GRID_HALF, az - _RP_GRID_HALF
    gs = 2 * _RP_GRID_HALF + 1
    grid = _native.fill_top_grid(ctx, gx0, gz0, gs, gs, -64, 320, threads)

    def surface_fn(wx: int, wz: int) -> int:
        ix, iz = wx - gx0, wz - gz0
        if 0 <= ix < gs and 0 <= iz < gs:
            return int(grid[iz, ix])
        return -65     # 网格外（正常不应发生）

    surf0 = surface_fn(ax, az)
    bid = int(pack["bs"].biome_at(ax >> 2, max(surf0, -64) >> 2,
                                  az >> 2))
    variant = _rp.variant_for_biome(bid)
    cold = False
    nm = _rp_biome_name(bid)
    if nm and _rp._SETUPS[variant][0][5]:      # can_be_cold（同变体共享）
        _t = _rp_biome_temperature(nm)
        cold = _t is not None and _t < 0.15
    sim = _rp._RPSim(seed, ax, az, variant,
                     surface_fn=surface_fn, cold=cold)
    out = []
    for (wx, wy, wz), mat in sim.voxels.items():
        name = _RP_MAT.get(mat[0] if isinstance(mat, tuple) else mat)
        if name is None:
            continue
        ix, iz = wx - gx0, wz - gz0
        if 0 <= ix < gs and 0 <= iz < gs and wy < int(grid[iz, ix]):
            continue     # 地面以下俯视不可见
        out.append((wx, wy, wz, name))
    return out


def has_template(key: str) -> bool:
    return (key in _JIGSAW_START or key in _STACK or key in _PICK)


# ------------------------------------------------------------------
# 林地府邸：真实块渲染（替代 footprint 色块）。
# 复用 StructurePreviewer mansion_pieces.assemble_mansion（MansionGrid
# + createMansion 逐行转写，对拍 6 案例 ALL PASS）：
#   结构线 LegacyRandom.setLargeFeatureSeed → rotation nextInt(4) →
#   MansionGrid/createMansion；锚点 = chunkBlock(7,7)，Y=64 平坦基准。
# 本模块补两件：
#   1) 官方 y：WoodlandMansionStructure.findGenerationPoint →
#      getLowestYIn5by5BoxOffset7Blocks（Structure.java L184-199）：
#      4 角 getFirstOccupiedHeight(WORLD_SURFACE_WG) 取 min；盒起点
#      chunkBlock(7,7)、尺寸随 rotation（NONE(5,5)/CW90(-5,5)/
#      CW180(-5,-5)/CCW90(5,-5)——size 为负时角点 = min+size，
#      getCornerHeights 直接相加）；y<60 官方拒绝生成（返回 []，
#      调用方不回退 footprint）。全部 piece y 平移 delta = y0 - 64。
#   2) 材质直出：模板 palette 原名（minecraft:xxx）进 blocks/heights
#      通道，4d 统一配色按 jm_palette 上色（与村庄/废弃传送门口径
#      一致，俯视只需基名，楼梯/台阶形状码不影响顶面色）。
# 俯视可见 = 每列最高结构方块（屋顶深色橡木板/楼梯）；贴地用
# beard=False：地形高于结构顶的列保持地形（官方模板高于屋顶处不
# 放块，地形穿出，俯视语义一致），避免 beard=True 在山坡把 heights
# 压出凹坑。
# ------------------------------------------------------------------
_MANSION_ROT_OFFSET = {
    "NONE": (5, 5),
    "CLOCKWISE_90": (-5, 5),
    "CLOCKWISE_180": (-5, -5),
    "COUNTERCLOCKWISE_90": (5, -5),
}


def mansion_blocks(seed: int, ax: int, az: int, pack: dict,
                   threads: int = 1) -> list:
    """林地府邸真实块 -> [(x, y, z, "minecraft:xxx"), ...]。

    ax/az = 结构锚点（区块角，enumerate_structures 的 x/z，16 对齐）。
    官方 y<60 拒绝生成时返回 []（调用方不回退 footprint）。
    """
    from Utils.StructurePreviewer import mansion_pieces as _mp

    if _native is None:
        return []
    ctx = (pack or {}).get("ctx")
    if ctx is None:
        return []
    cx, cz = ax >> 4, az >> 4
    pieces, _chests, rot_name = _mp.assemble_mansion(seed, cx, cz)
    # 官方 y：5×5 盒 4 角 WORLD_SURFACE_WG 最低值（盒尺寸随 rotation，
    # 允许为负 => 角点 = (bx, bz) 与 (bx+sx, bz+sz)）
    sx, sz = _MANSION_ROT_OFFSET.get(rot_name, (5, 5))
    bx, bz = cx * 16 + 7, cz * 16 + 7
    ys = [int(_native.fill_top_grid(ctx, x, z, 1, 1, -64, 320, threads)[0, 0])
          for x, z in ((bx, bz), (bx, bz + sz),
                       (bx + sx, bz), (bx + sx, bz + sz))]
    y0 = min(ys)
    if y0 < 60:
        return []          # 官方 findGenerationPoint 拒绝生成
    dy = y0 - 64
    out = []
    for pc in pieces:
        tpl = _mp._load_template(pc["name"])
        px, py, pz = pc["pos"]
        py += dy
        for (lx, ly, lz), (nm, _shp) in tpl["blocks"].items():
            wx, wy, wz = _mp.transform_pos((lx, ly, lz), pc["mirror"],
                                           pc["rot"])
            out.append((wx + px, wy + py, wz + pz, nm))
    return out
