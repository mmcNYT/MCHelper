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
     _RPSim 复用）。海底废墟亦属模板型，现走官方全链复刻
     （见 ocean_ruin_blocks：流复刻 + 逐 piece OCEAN_FLOOR_WG y
     + 下沉判定 + BlockRotProcessor 逐方块蚀除 + 数据标记）。
    C) 纯程序化型：无 NBT 模板，由 Java 逐方块生成 ——
       林地府邸、丛林神庙、沙漠神殿、女巫小屋、海底神殿。前四者
       现走真实块渲染（见 mansion_blocks / jungle_temple_blocks /
       desert_pyramid_blocks / swamp_hut_blocks：复用
       StructurePreviewer 逐行转写 + 官方 y 语义，俯视显示真实结构）；
       海底神殿亦属此类（见 ocean_monument_blocks：房间图流复刻 +
       逐 piece 画块 26.2 全序转写 + 水盒地形清除 caps）。
"""
from __future__ import annotations

import json
import os
import threading
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


# ------------------------------------------------------------------
# 丛林神庙：ScatteredFeaturePiece 全链复刻（替代 footprint 矩形）。
# 复用 StructurePreviewer pyramid_pieces._sim_jungle（1.21.11 字节码
# + 26.2 源码双重核对的 postProcess 逐行转写：MossStoneSelector
# cobblestone 40%/mossy 60% 逐格 nextFloat、9 处 generateAirBox 挖空、
# 楼梯/绊线/红石/活塞机关、2 箱 2 发射器，RNG 流同步推进）。
# 本模块补两件：
#   1) 朝向：变体流 structure_map.chunk_generate_rnd(seed, cx, cz) →
#      mc_random.next_int(state, 4)（Plane.HORIZONTAL faces 序
#      {N,E,S,W}，composition._compose_pyramid 同口径）；
#   2) 官方 y：ScatteredFeaturePiece.updateAverageGroundHeight
#      （26.2 ScatteredFeaturePiece.java L50-76）—— 全足迹
#      MOTION_BLOCKING_NO_LEAVES 高度整除平均。jungle piece 12x15
#      （E/W 朝向转置 15x12）经 makeBoundingBox axis==Z 分支恒从
#      anchor 正向延伸且 <=15 格，完全落在锚点 chunk 内 -> 官方的
#      chunkBB 裁剪不生效，avg = Σ(fill_top+1) // 列数。fill_top 是
#      surface 管线输出（无树/无水/无 feature），恰为放置时
#      （surface_structures 先于 vegetal_decoration）MBNL 语义。
#      全部 piece y 平移：世界 y = 体素 y(局部+64) - 64 + heightPos。
# 俯视只需基名：楼梯/机关形状码与朝向属性不影响顶面色（同府邸/
# 废弃传送门口径）；暗室(局部 y -3..-1)在地表下，由逐列最高竞争
# 自然淘汰。beard=False：坡地地形高于结构顶的列保持地形（官方
# 俯视语义，同府邸口径）。
# ------------------------------------------------------------------
_JP_MAT = {
    "cobblestone": "minecraft:cobblestone",
    "mossy cobblestone": "minecraft:mossy_cobblestone",
    "chiseled stone bricks": "minecraft:chiseled_stone_bricks",
    "cobblestone stairs": "minecraft:cobblestone_stairs",
    "chest": "minecraft:chest",
    "dispenser": "minecraft:dispenser",
    "tripwire hook": "minecraft:tripwire_hook",
    "tripwire": "minecraft:tripwire",
    "redstone wire": "minecraft:redstone_wire",
    "vine": "minecraft:vine",
    "lever": "minecraft:lever",
    "sticky piston": "minecraft:sticky_piston",
    "repeater": "minecraft:repeater",
}


def jungle_temple_blocks(seed: int, ax: int, az: int, pack: dict,
                         threads: int = 1) -> list:
    """丛林神庙真实块 -> [(x, y, z, "minecraft:xxx"), ...]。

    ax/az = 结构锚点（区块角，enumerate_structures 的 x/z，16 对齐）。
    """
    from Utils.StructurePreviewer import pyramid_pieces as _pp
    from Utils.Public import structure_map as _smap
    from Utils.SeedReverser import mc_random as _mcr

    if _native is None:
        return []
    ctx = (pack or {}).get("ctx")
    if ctx is None:
        return []
    cx, cz = ax >> 4, az >> 4
    state = _smap.chunk_generate_rnd(seed, cx, cz)
    facing, _st = _mcr.next_int(state, 4)
    sim = _pp._sim_jungle(seed, ax, az, facing)
    # 官方 y：全足迹 MBNL（fill_top+1）整除平均；正值整除 floor==trunc
    gw, gh = sim.max_x + 1, sim.max_z + 1
    grid = _native.fill_top_grid(ctx, ax, az, gw, gh, -64, 320, threads)
    n = gw * gh
    height_pos = (int(grid.sum()) + n) // n
    out = []
    for (wx, wy, wz), val in sim.voxels.items():
        name = _JP_MAT.get(val[0] if isinstance(val, tuple) else val)
        if name is None:
            continue
        out.append((ax + wx, wy - 64 + height_pos, az + wz, name))
    return out


# ------------------------------------------------------------------
# 沙漠神殿：ScatteredFeaturePiece 全链复刻（替代 footprint 矩形）。
# 复用 StructurePreviewer pyramid_pieces._sim_desert（1.21.11 fhj 逐行
# 转写，与 26.2 DesertPyramidPiece 全文逐行核对：postProcess 主体完全
# 一致）。本模块补四件：
#   1) 朝向：变体流 structure_map.chunk_generate_rnd(seed, cx, cz) →
#      mc_random.next_int(state, 4)（同丛林神庙口径）；
#   2) 官方 y：updateHeightPositionToLowestGroundHeight(level, -nextInt(3))
#      （26.2 ScatteredFeaturePiece.java L78-102；1.21.11 ffm 同名 2 参
#      重载，fhj L35 调用的正是它——_sim_desert 注释里的
#      updateAverageGroundHeight 系误标）——全足迹 MBNL(fill_top+1)
#      最低值 − r，r = postProcess 流 nextInt(3)。_sim_desert L305
#      消耗但丢弃该返回值，此处用同参数独立 XoroshiroJava 实例复算
#      同一次 nextInt(3)（_Sim.__init__ 每次新建流，互不干扰，不碰
#      _sim_desert 内部流与箱子 LootTableSeed 链）。footprint 21×21
#      恰为锚点角起 ax..ax+20 / az..az+20（两朝向同形）。
#   3) 转写勘误（.temp/decomp/readable/fhj.java 复核）：
#      a) 挖掘室顶 fhj L276 = placeCollapsedRoof(14..18, 0, 11..15)
#         （26.2 L358 同），每格 level.getRandom().nextFloat()<0.33 ->
#         砂岩否则沙（世界装饰流不可预测）→ 固定取多数分支沙。
#         _desert_secret_room 把这行误转写为 fill_air——此处补回
#         5×5 沙层（俯视被金字塔阶梯环掩埋，为完整性仍补）；
#      b) 补遗漏的 2 块橙色陶瓦 (16,-4,16)、(16,-4,10)（fhj L298/301
#         = 26.2 L380/383，埋于基座内俯视不可见）。
#   4) 逐列官方竞争（含 AIR 挖掘语义，替代共享 _stamp_real_blocks 的
#      beard 两档近似）：官方 postProcess 在地形之后执行——实心块
#      无条件替换（**等高也替换**，如 r=1 时基座/顶尖蓝陶瓦恰在地表），
#      AIR 盒真实写空气（沙丘穿进结构时官方挖掉 AIR 覆盖范围内的
#      地形）。逐列规则：S_top=列内最高实心世界 y、air_top=列内最高
#      AIR 世界 y；结构胜出 iff S_top>=fill_top 或 air_top>=fill_top，
#      胜出列只输出其顶块（分派侧 beard=True 直接落 heights/blocks），
#      未胜出列不输出（地形/植被保持——沙丘半埋神殿的官方俯视）。
#      俯视可见物：阶梯环 y1..9、四角塔 3×3 顶+4 楼梯 y10、顶尖 1×1
#      洞露蓝陶瓦（官方著名特征，全 r 可见）、陶瓦菱形/走廊/挖掘室/
#      TNT/四箱被环层掩埋或埋深淘汰。
# _desert_air_positions：_sim_desert 的 fill_air/fill_hollow(AIR) 用
#   dict.pop 实现，弹出的空气位不留在体素表；用一次带线程锁的录制跑
#   临时包 _Sim.place 拿到（按 width/depth/facing 过滤，防止并发录制
#   到丛林/其它朝向的模拟），按 facing 缓存——结构几何与种子/锚点
#   无关，空气布局恒定。录制集需剔除转写勘误补回的塌顶实心位。
# ------------------------------------------------------------------
_DP_MAT = {
    "sandstone": "minecraft:sandstone",
    "cut sandstone": "minecraft:cut_sandstone",
    "chiseled sandstone": "minecraft:chiseled_sandstone",
    "sandstone stairs": "minecraft:sandstone_stairs",
    "sandstone slab": "minecraft:sandstone_slab",
    "sand": "minecraft:sand",
    "orange terracotta": "minecraft:orange_terracotta",
    "blue terracotta": "minecraft:blue_terracotta",
    "tnt": "minecraft:tnt",
    "stone": "minecraft:stone",            # 石质压力板 (STONE_PLATE[0])
    "chest": "minecraft:chest",
}

_DP_AIR_CACHE: dict[int, frozenset] = {}
_DP_AIR_LOCK = threading.Lock()


def _desert_air_positions(facing: int) -> frozenset:
    """沙漠神殿官方 AIR 摆放位（锚点相对 (wx,wy,wz)，wy=局部 y+64）。"""
    cached = _DP_AIR_CACHE.get(facing)
    if cached is not None:
        return cached
    with _DP_AIR_LOCK:
        cached = _DP_AIR_CACHE.get(facing)
        if cached is not None:
            return cached
        from Utils.StructurePreviewer import pyramid_pieces as _pp
        orig = _pp._Sim.place
        rec: set = set()

        def _rec(self, x, y, z, val):
            if (val is None and self.width == 21 and self.depth == 21
                    and self.facing == facing):
                rec.add(self._w(x, y, z))
            orig(self, x, y, z, val)

        _pp._Sim.place = _rec
        try:
            _pp._sim_desert(1, 0, 0, facing)   # 种子/锚点不影响空气布局
        finally:
            _pp._Sim.place = orig
        # 转写勘误：挖掘室顶官方为塌顶实心层（非空气），从空气集剔除
        for dx in range(14, 19):
            for dz in range(11, 16):
                wx, wz = _pp._world_xy(dx, dz, facing, 20, 20)
                rec.discard((wx, 64, wz))
        cached = frozenset(rec)
        _DP_AIR_CACHE[facing] = cached
        return cached


def desert_pyramid_blocks(seed: int, ax: int, az: int, pack: dict,
                          threads: int = 1) -> list:
    """沙漠神殿真实块 -> [(x, y, z, "minecraft:xxx"), ...]（逐列顶块）。

    ax/az = 结构锚点（区块角，enumerate_structures 的 x/z，16 对齐）。
    只输出官方竞争胜出列的顶块（含 AIR 挖掘语义，见上），分派侧以
    beard=True 落盘。
    """
    from Utils.StructurePreviewer import pyramid_pieces as _pp
    from Utils.StructurePreviewer import loot_rng as _lrng
    from Utils.Public import structure_map as _smap
    from Utils.SeedReverser import mc_random as _mcr

    if _native is None:
        return []
    ctx = (pack or {}).get("ctx")
    if ctx is None:
        return []
    cx, cz = ax >> 4, az >> 4
    state = _smap.chunk_generate_rnd(seed, cx, cz)
    facing, _st = _mcr.next_int(state, 4)
    sim = _pp._sim_desert(seed, ax, az, facing)
    # 26.2/1.21.11 勘误层（见上）：补塌顶 5×5 沙 + 2 块橙陶瓦。
    # 坐标经 _world_xy 净变换（与 _Sim.place 同口径，wy=局部 y+64）。
    for dx in range(14, 19):
        for dz in range(11, 16):
            wx, wz = _pp._world_xy(dx, dz, facing, sim.max_x, sim.max_z)
            sim.voxels[(wx, 64, wz)] = _pp.SAND
    for dx, dz in ((16, 16), (16, 10)):
        wx, wz = _pp._world_xy(dx, dz, facing, sim.max_x, sim.max_z)
        sim.voxels[(wx, 60, wz)] = _pp.ORANGE_TERRACOTTA
    # r 复算：重建同参数 postProcess 流消耗同一次 nextInt(3)
    step, decorator = _lrng.salt_configs_for_version("1.21")["desert_pyramid"]
    pop = _lrng.get_population_seed(seed, ax, az)
    r = _lrng.XoroshiroJava(
        (pop + decorator + 10000 * step) & _lrng._M64).next_int(3)
    # 官方 y：全足迹 MBNL（fill_top+1）最低值 − r（无 chunkBB 过滤）
    gw, gh = sim.max_x + 1, sim.max_z + 1
    grid = _native.fill_top_grid(ctx, ax, az, gw, gh, -64, 320, threads)
    height_pos = int(grid.min()) + 1 - r
    # ---- 逐列官方竞争（含 AIR 挖掘语义，见模块注释 4）----
    col_top: dict = {}      # (wx, wz) -> (最高实心 wy, 材质名)
    for (wx, wy, wz), val in sim.voxels.items():
        name = _DP_MAT.get(val[0] if isinstance(val, tuple) else val)
        if name is None:
            continue
        cur = col_top.get((wx, wz))
        if cur is None or wy > cur[0]:
            col_top[(wx, wz)] = (wy, name)
    col_air: dict = {}      # (wx, wz) -> 最高 AIR wy
    for wx, wy, wz in _desert_air_positions(facing):
        if wy > col_air.get((wx, wz), -(1 << 62)):
            col_air[(wx, wz)] = wy
    out = []
    for (wx, wz), (wy, name) in col_top.items():
        fill = int(grid[wz, wx])     # 足迹 21×21 恰为 ax..ax+20 两轴同形
        s_top = wy - 64 + height_pos
        air_wy = col_air.get((wx, wz))
        if (s_top >= fill or (air_wy is not None
                              and air_wy - 64 + height_pos >= fill)):
            out.append((ax + wx, s_top, az + wz, name))
    return out


# ------------------------------------------------------------------
# 女巫小屋：ScatteredFeaturePiece 全链复刻（替代 footprint 矩形）。
# 复用 StructurePreviewer pyramid_pieces._sim_hut（26.2
# SwampHutPiece L56-95 逐行转写：云杉板墙+屋顶平台+屋檐楼梯圈+
# 四橡木柱+窗洞/盆栽/工作台/干锅；无 RNG 流、无箱子）。
# 本模块补三件：
#   1) 朝向：同丛林/沙漠口径 chunk_generate_rnd + next_int(4)
#      （SwampHutStructure L23 context.random() 构造时
#      getRandomHorizontalDirection = nextInt(4)）；
#   2) 官方 y：updateAverageGroundHeight(level, chunkBB, 0)
#      （26.2 ScatteredFeaturePiece L50-76，同丛林神庙同款公式）——
#      height_pos = floor((Σ(fill_top+1))/n) = (Σgrid+n)//n；
#   3) 逐列官方竞争（同 desert_pyramid_blocks）：S_top>=fill 或
#      air_top>=fill 胜出只输出顶块，分派侧 beard=True 落盘。窗洞
#      AIR 为官方 placeBlock AIR 的 3 格（L70-72），硬编码局部坐标
#      经 _world_xy 净变换（_Sim.place 对 AIR 已 pop，此处只收集
#      位置）。L91-95 柱下探 y=-1 恒被竞争淘汰。
# ------------------------------------------------------------------
_HP_MAT = {
    "spruce planks": "minecraft:spruce_planks",
    "oak log": "minecraft:oak_log",
    "oak fence": "minecraft:oak_fence",
    "potted red mushroom": "minecraft:potted_red_mushroom",
    "crafting table": "minecraft:crafting_table",
    "cauldron": "minecraft:cauldron",
    "spruce stairs": "minecraft:spruce_stairs",
}


def swamp_hut_blocks(seed: int, ax: int, az: int, pack: dict,
                     threads: int = 1) -> list:
    """女巫小屋真实块 -> [(x, y, z, "minecraft:xxx"), ...]（逐列顶块）。

    ax/az = 结构锚点（区块角，enumerate_structures 的 x/z，16 对齐）。
    只输出官方竞争胜出列的顶块，分派侧以 beard=True 落盘。
    """
    from Utils.StructurePreviewer import pyramid_pieces as _pp
    from Utils.Public import structure_map as _smap
    from Utils.SeedReverser import mc_random as _mcr

    if _native is None:
        return []
    ctx = (pack or {}).get("ctx")
    if ctx is None:
        return []
    cx, cz = ax >> 4, az >> 4
    state = _smap.chunk_generate_rnd(seed, cx, cz)
    facing, _st = _mcr.next_int(state, 4)
    sim = _pp._sim_hut(seed, ax, az, facing)
    # 官方 y：updateAverageGroundHeight(level, chunkBB, 0)（同丛林）
    gw, gh = sim.max_x + 1, sim.max_z + 1
    grid = _native.fill_top_grid(ctx, ax, az, gw, gh, -64, 320, threads)
    n = gw * gh
    height_pos = (int(grid.sum()) + n) // n
    # ---- 逐列官方竞争（同 desert_pyramid_blocks）----
    col_top: dict = {}
    for (wx, wy, wz), val in sim.voxels.items():
        name = _HP_MAT.get(val[0] if isinstance(val, tuple) else val)
        if name is None:
            continue
        cur = col_top.get((wx, wz))
        if cur is None or wy > cur[0]:
            col_top[(wx, wz)] = (wy, name)
    col_air: dict = {}      # 官方窗洞 AIR（L70-72）
    for dx, dy, dz in ((1, 3, 4), (5, 3, 4), (5, 3, 5)):
        wx, wz = _pp._world_xy(dx, dz, facing, sim.max_x, sim.max_z)
        wy = dy + 64
        if wy > col_air.get((wx, wz), -(1 << 62)):
            col_air[(wx, wz)] = wy
    out = []
    for (wx, wz), (wy, name) in col_top.items():
        fill = int(grid[wz, wx])
        s_top = wy - 64 + height_pos
        air_wy = col_air.get((wx, wz))
        if (s_top >= fill or (air_wy is not None
                              and air_wy - 64 + height_pos >= fill)):
            out.append((ax + wx, s_top, az + wz, name))
    return out


# ------------------------------------------------------------------
# 海底废墟：官方 NBT 模板 + 流复刻（26.2 OceanRuinStructure L40-48 /
# OceanRuinPieces L143-244 / TemplateStructurePiece L82-101 逐行转写）。
# 流（context.random() = setLargeFeatureSeed 流，同丛林/沙漠/女巫口径）：
#   rotation = Rotation.getRandom → nextInt(4)（OceanRuinStructure L46，
#   先于 addPieces）；isLarge = nextFloat() <= large_probability(0.3)
#   （L159）；baseIntegrity = isLarge ? 0.9 : 0.8（L160）。
#   模板选择（addPiece L221-243）：WARM = Util.getRandom → nextInt(len)
#   （BIG_WARM_RUINS 4 / WARM_RUINS 8）；COLD = nextInt(len) 选 idx，
#   brick/cracked/mossy 三模板同位同旋转叠加（integrity 0.9|0.8/0.7/0.5，
#   模板选择流只消耗一次 nextInt）。
#   cluster（L162 短路：isLarge 时才消耗 nextFloat；L167-195）：
#   parentBB = transform((15,0,15))+pos（fromCorners 双闭区间）；
#   allPositions 8 候选（每个 2 次 Mth.nextInt，L198-208 行序原样）；
#   ruins = Mth.nextInt(4,8)（L182）；循环：nextInt(size) 选位 + 
#   Rotation.getRandom + transform((5,0,6)) 盒与 parentBB 相交判定
#   （BoundingBox.intersects L114-121），不相交才 addPiece(false, 0.8)
#   ——模板选择流仅在不相交时消耗。
# 官方 y（OceanRuinPiece.postProcess L352-361，逐 piece）：
#   y1 = getHeight(OCEAN_FLOOR_WG, pos.x, pos.z) = 密度实心顶 + 1
#   （fill_top_grid 在海床列即 OCEAN_FLOOR 语义：水/空气非实心不计，
#   与 onTopOfChunkCenter → getBaseHeight 的密度直算口径一致）；
#   下沉判定 getHeight(pos, level, corner)（L365-398）：corner =
#   transform(size-1,0,size-1)+pos；逐列从 y1-1 向下首个非空气/水/冰 →
#   floorY = min(fill_top, y1-1)（fill 层顶）；minY=min(floorY)、
#   area=count(floorY < y1-1-2)、width=|pos.x-corner.x|；
#   topY-minY>2 且 area>width-2 → y=minY+1（沉到谷底海床+1），否则 y=y1。
# 逐方块蚀除（BlockRotProcessor L49-52）：每块独立
#   LegacyRandomSource(Mth.getSeed(模板相对 x,y,z))
#   （StructurePlaceSettings.getRandom L114：settings.random 为空 →
#   Mth.getSeed(pos)，pos=模板相对坐标），nextFloat() > integrity 不放。
# 处理器链（makeSettings L292-297）：BlockIgnoreProcessor.
#   STRUCTURE_AND_AIR → air/structure_block 不放；chest/drowned 数据
#   标记（structure_block 的 nbt.metadata）由 handleDataMarker
#   （OceanRuinPiece L318-340，TemplateStructurePiece L94-101 永远
#   遍历全部 DATA 标记）无条件放置：chest → minecraft:chest
#   （waterlogged 俯视同色）；drowned → 水（y<=海平面）/空气（俯视
#   不渲染）。可疑沙/砾（CappedProcessor）俯视同色不渲染。
# warm/cold 判定：ChunkGenerator.createStructures L508-550 失败重抽
#   （tryGenerate 失败 → 移出候选再抽，直到成功或耗尽）+ 双群系标签
#   互斥 → 每个海洋锚点必生成一个变体（枚举侧 _OCEANIC 全海洋白名单
#   与官方一致）。锚点群系（_check_feature 采样点 cx*4+2, 79, cz*4+2）
#   ∈ ocean_ruin_cold 标签 → COLD，否则 WARM（warm 标签 44/45/48；
#   47 deep_warm 两标签均不含，1.18+ 采样恒不产生该群系）。
# ------------------------------------------------------------------
_RUIN_ROT = ("NONE", "CLOCKWISE_90", "CLOCKWISE_180", "COUNTERCLOCKWISE_90")
_WARM_RUINS = tuple(f"minecraft:underwater_ruin/warm_{i}"
                    for i in range(1, 9))
_BIG_WARM_RUINS = tuple(f"minecraft:underwater_ruin/big_warm_{i}"
                        for i in (4, 5, 6, 7))
_RUINS_BRICK = tuple(f"minecraft:underwater_ruin/brick_{i}"
                     for i in range(1, 9))
_RUINS_CRACKED = tuple(f"minecraft:underwater_ruin/cracked_{i}"
                       for i in range(1, 9))
_RUINS_MOSSY = tuple(f"minecraft:underwater_ruin/mossy_{i}"
                     for i in range(1, 9))
_BIG_RUINS_BRICK = tuple(f"minecraft:underwater_ruin/big_brick_{i}"
                         for i in (1, 2, 3, 8))
_BIG_RUINS_CRACKED = tuple(f"minecraft:underwater_ruin/big_cracked_{i}"
                           for i in (1, 2, 3, 8))
_BIG_RUINS_MOSSY = tuple(f"minecraft:underwater_ruin/big_mossy_{i}"
                         for i in (1, 2, 3, 8))
# 26.2 群系标签 #minecraft:has_structure/ocean_ruin_cold（jar 内实测）
_OCEAN_RUIN_COLD_BIOMES = {0, 10, 24, 46, 49, 50}

_RUIN_TPL: dict = {}


def _ruin_template(loc: str):
    """load_template + 数据标记提取（structure_block 的 nbt.metadata）。

    返回 (tpl, markers) 或 None；markers = [(x, y, z, "chest"|"drowned")]。
    chest/drowned 标记块在模板调色板里是 minecraft:structure_block，
    官方 placeInWorld 不放置（BlockIgnoreProcessor），placeInWorld 后
    filterBlocks(STRUCTURE_BLOCK) 重新找出并逐个 handleDataMarker ——
    即标记不受 BlockRotProcessor 蚀除，永远生效。
    """
    if loc in _RUIN_TPL:
        return _RUIN_TPL[loc]
    tpl = _vj.load_template(loc)
    out = None
    if tpl is not None:
        ns, stem = loc.split(":", 1)
        markers: list = []
        try:
            nbt = _vj.parse_nbt(
                _vj._jar().read(f"data/{ns}/structure/{stem}.nbt"))
            for b in nbt.get("blocks", []):
                md = (b.get("nbt") or {}).get("metadata")
                if md in ("chest", "drowned"):
                    p = b.get("pos", [0, 0, 0])
                    markers.append((int(p[0]), int(p[1]), int(p[2]), md))
        except Exception:
            markers = []
        out = (tpl, markers)
    _RUIN_TPL[loc] = out
    return out


def _ruin_piece_blocks(tpl, markers, wx: int, wz: int, y: int,
                       rot: str, integrity: float, degrad,
                       sea_level: int = 63) -> list:
    """单个 piece：蚀除后的实体方块 + 数据标记 → [(x, y, z, name)]。

    wx/wz = 模板最小角世界坐标（postProcess 调整后的 templatePosition）。
    """
    from Utils.StructurePreviewer.mansion_pieces import transform_pos
    out = []
    for (tx, ty, tz, nm) in tpl["blocks"]:
        sh = nm.split(":")[-1]
        if sh in _SKIP or sh == "structure_block":
            continue     # BlockIgnoreProcessor.STRUCTURE_AND_AIR
        degrad.reseed_for(tx, ty, tz)
        if degrad.next_float() > integrity:
            continue     # BlockRotProcessor：nextFloat > integrity 不放
        dx, dy, dz = transform_pos((tx, ty, tz), "NONE", rot)
        out.append((wx + dx, y + dy, wz + dz, nm))
    for (tx, ty, tz, md) in markers:
        dx, dy, dz = transform_pos((tx, ty, tz), "NONE", rot)
        if md == "chest":
            out.append((wx + dx, y + dy, wz + dz, "minecraft:chest"))
        elif y + dy <= sea_level:      # drowned：y<=海平面 水，否则空气
            out.append((wx + dx, y + dy, wz + dz, "minecraft:water"))
    return out


def ocean_ruin_blocks(seed: int, ax: int, az: int, pack: dict,
                      threads: int = 1) -> list:
    """海底废墟真实块 -> [(x, y, z, "minecraft:xxx"), ...]。

    ax/az = 结构锚点（区块角，enumerate_structures 的 x/z，16 对齐）。
    官方流 + 逐 piece OCEAN_FLOOR_WG y + 下沉判定 + 蚀除（见段注释）。
    """
    from Utils.Public import structure_map as _smap
    from Utils.SeedReverser import mc_random as _mcr
    from Utils.SeedReverser.mc_rng import DegradationRandom
    from Utils.StructurePreviewer.mansion_pieces import transform_pos

    if _native is None:
        return []
    ctx = (pack or {}).get("ctx")
    if ctx is None:
        return []
    cx, cz = ax >> 4, az >> 4
    # 变体：锚点群系 ∈ cold 标签（_check_feature 采样点）
    bs = (pack or {}).get("bs")
    cold = False
    if bs is not None:
        bid = int(bs.biome_at(cx * 4 + 2, 319 >> 2, cz * 4 + 2))
        cold = bid in _OCEAN_RUIN_COLD_BIOMES
    state = _smap.chunk_generate_rnd(seed, cx, cz)
    r, state = _mcr.next_int(state, 4)          # generatePieces L46
    rot = _RUIN_ROT[r]
    f1, state = _mcr.next_float(state)   # L159：nextFloat 推进流
    is_large = f1 <= 0.3
    base_int = 0.9 if is_large else 0.8           # L160
    ox, oz = cx * 16, cz * 16                     # chunkMinBlockX/Z
    pieces = []      # (loc, x, z, rot, integrity)
    # ---- 主 piece（addPiece L221-243）----
    n = 4 if is_large else 8
    idx, state = _mcr.next_int(state, n)
    if cold:
        brick = _BIG_RUINS_BRICK if is_large else _RUINS_BRICK
        cracked = _BIG_RUINS_CRACKED if is_large else _RUINS_CRACKED
        mossy = _BIG_RUINS_MOSSY if is_large else _RUINS_MOSSY
        for arr, itg in ((brick, base_int), (cracked, 0.7), (mossy, 0.5)):
            pieces.append((arr[idx], ox, oz, rot, itg))
    else:
        arr = _BIG_WARM_RUINS if is_large else _WARM_RUINS
        pieces.append((arr[idx], ox, oz, rot, base_int))
    # ---- cluster（L162 短路 + L167-195）----
    in_cluster = False
    if is_large:      # L162：Java && 短路——非 large 不消耗 nextFloat
        f2, state = _mcr.next_float(state)
        in_cluster = f2 <= 0.9
    if in_cluster:
        dx15, _, dz15 = transform_pos((15, 0, 15), "NONE", rot)
        corner = (ox + dx15, oz + dz15)
        blx, blz = min(ox, corner[0]), min(oz, corner[1])
        cands = []          # allPositions L198-208，行序原样

        def _ni(lo, hi):
            nonlocal state
            v, state = _mcr.next_int(state, hi - lo + 1)
            return lo + v   # Mth.nextInt(random, min, max)

        cands.append((blx - 16 + _ni(1, 8), blz + 16 + _ni(1, 7)))
        cands.append((blx - 16 + _ni(1, 8), blz + _ni(1, 7)))
        cands.append((blx - 16 + _ni(1, 8), blz - 16 + _ni(4, 8)))
        cands.append((blx + _ni(1, 7), blz + 16 + _ni(1, 7)))
        cands.append((blx + _ni(1, 7), blz - 16 + _ni(4, 6)))
        cands.append((blx + 16 + _ni(1, 7), blz + 16 + _ni(3, 8)))
        cands.append((blx + 16 + _ni(1, 7), blz + _ni(1, 7)))
        cands.append((blx + 16 + _ni(1, 7), blz - 16 + _ni(4, 8)))
        rv, state = _mcr.next_int(state, 5)
        ruins = 4 + rv    # Mth.nextInt(4, 8)
        p_x1, p_x2 = sorted((ox, corner[0]))
        p_z1, p_z2 = sorted((oz, corner[1]))
        for _ in range(ruins):
            if not cands:
                break
            i, state = _mcr.next_int(state, len(cands))
            px2, pz2 = cands.pop(i)
            r2, state = _mcr.next_int(state, 4)   # Rotation.getRandom
            rot2 = _RUIN_ROT[r2]
            ddx, _, ddz = transform_pos((5, 0, 6), "NONE", rot2)
            x1, x2 = sorted((px2, px2 + ddx))
            z1, z2 = sorted((pz2, pz2 + ddz))
            if x2 >= p_x1 and x1 <= p_x2 and z2 >= p_z1 and z1 <= p_z2:
                continue      # intersects(parentBB) → 不加 piece
            idx3, state = _mcr.next_int(state, 8)  # addPiece 模板选择
            if cold:
                for arr, itg in ((_RUINS_BRICK, 0.8),
                                 (_RUINS_CRACKED, 0.7),
                                 (_RUINS_MOSSY, 0.5)):
                    pieces.append((arr[idx3], px2, pz2, rot2, itg))
            else:
                pieces.append((_WARM_RUINS[idx3], px2, pz2, rot2, 0.8))
    # ---- 逐 piece y 语义 + 蚀除盖章 ----
    degrad = DegradationRandom()
    out = []
    for (loc, wx, wz, rname, itg) in pieces:
        rt = _ruin_template(loc)
        if rt is None:
            continue
        tpl, markers = rt
        sx, _sy, sz = tpl["size"]
        # y1 = getHeight(OCEAN_FLOOR_WG, pos) = 密度实心顶 + 1
        y1 = int(_native.fill_top_grid(ctx, wx, wz, 1, 1, -64, 320, 1)[0, 0])
        y1 += 1
        # 下沉判定（L365-398）：corner = transform(size-1,0,size-1)+pos
        ddx, _, ddz = transform_pos((sx - 1, 0, sz - 1), "NONE", rname)
        cx2, cz2 = wx + ddx, wz + ddz
        x1, x2 = sorted((wx, cx2))
        z1, z2 = sorted((wz, cz2))
        tops = _native.fill_top_grid(ctx, x1, z1, x2 - x1 + 1, z2 - z1 + 1,
                                     -64, 320, threads)
        topY = y1 - 1
        floors = np.minimum(tops.astype(np.int64), topY)
        minY = int(floors.min())
        area = int((floors < topY - 2).sum())
        width = abs(wx - cx2)
        if topY - minY > 2 and area > width - 2:
            y = minY + 1
        else:
            y = y1
        out.extend(_ruin_piece_blocks(tpl, markers, wx, wz, y,
                                      rname, itg, degrad))
    return out


# ------------------------------------------------------------------
# 海底神殿（monument）：26.2 OceanMonumentStructure L30-53 +
# OceanMonumentPieces L172-1988 逐行转写（纯程序化，无 NBT 模板）。
# 流（context.random() = setLargeFeatureSeed 流，同丛林/沙漠/女巫/废墟）:
#   orientation = Plane.HORIZONTAL.getRandomDirection → nextInt(4)
#   （faces 序 NORTH/EAST/SOUTH/WEST，Direction.java L577/588）→
#   generateRoomGraph：coreRoom = grid[ri(nextInt(4),0,2)]（L292）→
#   Util.shuffle(46 房，Fisher-Yates i=size..2 swap(i-1, nextInt(i))，
#   Util.java L1107-1114) → 关闭循环（每房至多 5 次 nextInt(6)，
#   findSource 连通性保护，L327 scanIndex 后缀自增短路语义）→
#   fitter 循环（顺序 DoubleXY/DoubleYZ/DoubleZ/DoubleX/DoubleY/
#   SimpleTop/Simple，L190-196；仅 SimpleRoom create 消耗 nextInt(3)）
#   → wingRandom = nextInt()（无界 32 位，next_bits(state,32)；
#   left 用原值、right 用值+1，L218-220）。
# 坐标变换（StructurePiece L135-165）：getWorldX：N/S→minX+x、
#   W→maxX-z、E→minX+z；getWorldZ：N→maxZ-z、S/W/E→minZ+x；
#   getWorldY=minY+y。makeBoundingBox（L71-77）：Z 轴朝向 x 尺寸
#   =width，X 轴朝向 x 尺寸=depth（w/d 互换）。子 piece bbox 在局部
#   原点系构造后统一 move(getWorldPos(9,0,22))（L209-213）；wings/
#   penthouse bbox 直接 fromCorners(getWorldPos(...))（L215-217）。
# 官方 postProcess 全序（L343-402）：主水盒(0,0,0,58,25,58)（世界
#   y>=63 段→air，其余非 FILL_KEEP→water）→ 双翼 → 入口拱/墙 →
#   顶件 → 下/中/上墙 → 7x7 柱网（4x4 底灯+fillColumnDown 至清除后
#   列顶，跳过 (3,0) 入口位）→ 外圈 5 层阶梯水盒（x/z=-1-i..58+i，
#   y0=i*2）→ 子 piece 全部 postProcess。FILL_KEEP=冰三兄弟+water
#   （L1427-1432）；y 基准固定 39（L183），seaLevel=63。
# 地形交互（JM 同款真实竞争）：水盒覆盖列的海床被清 → caps[(x,z)]=
#   盒底-1（heights 压低到 min(heights,cap)，空腔列渲染深水）；柱列
#   fillColumnDown 从 y=-1 填 prismarine_bricks 至清除后列顶。
# chunk-random 依赖效果（SimpleTopRoom 湿海绵、SimpleRoom
#   centerPillar）俯视全被顶板/盖板遮挡（海绵 y<=3<顶板 y=4；
#   centerPillar 要求无 UP 开口⇔有顶板），转写省略。
# 输出：(每列最高实体块列表(water/air 除外), caps dict)。
# ------------------------------------------------------------------
_MONU_GRAY = "minecraft:prismarine"
_MONU_LIGHT = "minecraft:prismarine_bricks"
_MONU_BLACK = "minecraft:dark_prismarine"
_MONU_LAMP = "minecraft:sea_lantern"
_MONU_GOLD = "minecraft:gold_block"
_MONU_WATER = "minecraft:water"
_MONU_AIR = "minecraft:air"
_MONU_KEEP = frozenset(("minecraft:ice", "minecraft:packed_ice",
                        "minecraft:blue_ice", _MONU_WATER))
# Direction 3D data value：DOWN=0 UP=1 NORTH=2 SOUTH=3 WEST=4 EAST=5
_MONU_HOR = ("NORTH", "EAST", "SOUTH", "WEST")   # Plane.HORIZONTAL faces
_MONU_OPP = (1, 0, 3, 2, 5, 4)
_MONU_STEP = ((0, -1, 0), (0, 1, 0), (0, 0, -1),
              (0, 0, 1), (-1, 0, 0), (1, 0, 0))
# GRIDROOM 索引（L1441-1444）
_MONU_RI = lambda rx, ry, rz: ry * 25 + rz * 5 + rx
_MONU_GRID_SOURCE = _MONU_RI(2, 0, 0)
_MONU_GRID_TOP = _MONU_RI(2, 2, 0)
_MONU_GRID_LWING = _MONU_RI(0, 1, 0)
_MONU_GRID_RWING = _MONU_RI(4, 1, 0)


def _monu_wx(bb, orient, x, z):
    """StructurePiece.getWorldX（L135-147）。"""
    if orient == "WEST":
        return bb[3] - z
    if orient == "EAST":
        return bb[0] + z
    return bb[0] + x          # NORTH/SOUTH


def _monu_wz(bb, orient, x, z):
    """StructurePiece.getWorldZ（L153-165）。"""
    if orient == "NORTH":
        return bb[5] - z
    if orient == "SOUTH":
        return bb[2] + z         # L161 case SOUTH -> minZ() + z
    return bb[2] + x          # WEST/EAST


def _monu_room_bbox(orient, room_index, rw, rh, rd):
    """OceanMonumentPiece.makeBoundingBox（L1473-1497）：局部原点系。

    返回 (minX, minY, minZ, maxX, maxY, maxZ)。
    """
    rx = room_index % 5
    rz = (room_index // 5) % 5
    ry = room_index // 25
    if orient in ("NORTH", "SOUTH"):
        bb = (0, 0, 0, rw * 8 - 1, rh * 4 - 1, rd * 8 - 1)
    else:                     # X 轴朝向：x 尺寸=depth、z 尺寸=width
        bb = (0, 0, 0, rd * 8 - 1, rh * 4 - 1, rw * 8 - 1)
    if orient == "NORTH":
        dx, dy, dz = rx * 8, ry * 4, -(rz + rd) * 8 + 1
    elif orient == "SOUTH":
        dx, dy, dz = rx * 8, ry * 4, rz * 8
    elif orient == "WEST":
        dx, dy, dz = -(rz + rd) * 8 + 1, ry * 4, rx * 8
    else:
        dx, dy, dz = rz * 8, ry * 4, rx * 8
    return (bb[0] + dx, bb[1] + dy, bb[2] + dz,
            bb[3] + dx, bb[4] + dy, bb[5] + dz)


def _monu_from_corners(bb, orient, p0, p1):
    """BoundingBox.fromCorners(getWorldPos(p0), getWorldPos(p1))（L215-217）。"""
    xs = (_monu_wx(bb, orient, p0[0], p0[2]), _monu_wx(bb, orient, p1[0], p1[2]))
    zs = (_monu_wz(bb, orient, p0[0], p0[2]), _monu_wz(bb, orient, p1[0], p1[2]))
    ys = (bb[1] + p0[1], bb[1] + p1[1])
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


class _MonuRoom:
    """OceanMonumentPieces.RoomDefinition（L1933-1987）。"""
    __slots__ = ("index", "connections", "hasOpening", "claimed",
                 "isSource", "scanIndex")

    def __init__(self, idx):
        self.index = idx
        self.connections = [None] * 6
        self.hasOpening = [False] * 6
        self.claimed = False
        self.isSource = False
        self.scanIndex = 0

    def set_connection(self, d, other):
        self.connections[d] = other
        other.connections[_MONU_OPP[d]] = self

    def update_openings(self):
        for i in range(6):
            self.hasOpening[i] = self.connections[i] is not None

    def find_source(self, scan_idx):
        if self.isSource:
            return True
        self.scanIndex = scan_idx
        for i in range(6):
            c = self.connections[i]
            if (c is not None and self.hasOpening[i]
                    and c.scanIndex != scan_idx and c.find_source(scan_idx)):
                return True
        return False


def _monu_room_graph(state):
    """MonumentBuilding.generateRoomGraph（L228-341）。

    返回 ((room_defs, source_room, core_room), state)；room_defs 已
    shuffle 并含 roof/leftWing/rightWing（L337-340）。
    """
    from Utils.SeedReverser import mc_random as _mcr
    grid = [None] * 75
    for x in range(5):
        for z in range(4):
            grid[_MONU_RI(x, 0, z)] = _MonuRoom(_MONU_RI(x, 0, z))
    for x in range(5):
        for z in range(4):
            grid[_MONU_RI(x, 1, z)] = _MonuRoom(_MONU_RI(x, 1, z))
    for x in range(1, 4):
        for z in range(2):
            grid[_MONU_RI(x, 2, z)] = _MonuRoom(_MONU_RI(x, 2, z))
    source_room = grid[_MONU_GRID_SOURCE]
    # 邻居连接（L257-280；z 方向邻居连接方向取反 L272）
    for x in range(5):
        for z in range(5):
            for y in range(3):
                pos = _MONU_RI(x, y, z)
                if grid[pos] is None:
                    continue
                for d in range(6):
                    sx, sy, sz = _MONU_STEP[d]
                    nx, ny, nz = x + sx, y + sy, z + sz
                    if 0 <= nx < 5 and 0 <= nz < 5 and 0 <= ny < 3:
                        npos = _MONU_RI(nx, ny, nz)
                        if grid[npos] is not None:
                            if nz == z:
                                grid[pos].set_connection(d, grid[npos])
                            else:
                                grid[pos].set_connection(
                                    _MONU_OPP[d], grid[npos])
    roof = _MonuRoom(1003)
    lw = _MonuRoom(1001)
    rw = _MonuRoom(1002)
    grid[_MONU_GRID_TOP].set_connection(1, roof)     # UP
    grid[_MONU_GRID_LWING].set_connection(3, lw)     # SOUTH
    grid[_MONU_GRID_RWING].set_connection(3, rw)
    roof.claimed = lw.claimed = rw.claimed = True
    source_room.isSource = True
    v, state = _mcr.next_int(state, 4)
    core_room = grid[_MONU_RI(v, 0, 2)]
    core_room.claimed = True
    core_room.connections[5].claimed = True                    # EAST
    core_room.connections[2].claimed = True                    # NORTH
    core_room.connections[5].connections[2].claimed = True
    core_room.connections[1].claimed = True                    # UP
    core_room.connections[5].connections[1].claimed = True
    core_room.connections[2].connections[1].claimed = True
    core_room.connections[5].connections[2].connections[1].claimed = True
    room_defs = []
    for definition in grid:
        if definition is not None:
            definition.update_openings()
            room_defs.append(definition)
    roof.update_openings()
    lw.update_openings()
    rw.update_openings()
    # Util.shuffle（Fisher-Yates，Util.java L1107-1114）
    for i in range(len(room_defs), 1, -1):
        j, state = _mcr.next_int(state, i)
        room_defs[i - 1], room_defs[j] = room_defs[j], room_defs[i - 1]
    # 关闭循环（L312-335）：每房至多 5 次尝试关 2 门，findSource 保连通
    scan_index = 1
    for definition in room_defs:
        close_count = 0
        attempt = 0
        while close_count < 2 and attempt < 5:
            attempt += 1
            f, state = _mcr.next_int(state, 6)
            if definition.hasOpening[f]:
                of = _MONU_OPP[f]
                definition.hasOpening[f] = False
                definition.connections[f].hasOpening[of] = False
                # L327：findSource(scanIndex++) && ...（短路，后缀自增）
                s1 = scan_index
                scan_index += 1
                ok1 = definition.find_source(s1)
                ok2 = False
                if ok1:
                    s2 = scan_index
                    scan_index += 1
                    ok2 = definition.connections[f].find_source(s2)
                if ok1 and ok2:
                    close_count += 1
                else:
                    definition.hasOpening[f] = True
                    definition.connections[f].hasOpening[of] = True
    room_defs = room_defs + [roof, lw, rw]
    return (room_defs, source_room, core_room), state


def _monu_fits_dxy(d):
    return (d.hasOpening[5] and not d.connections[5].claimed
            and d.hasOpening[1] and not d.connections[1].claimed
            and d.connections[5].hasOpening[1]
            and not d.connections[5].connections[1].claimed)


def _monu_fits_dyz(d):
    return (d.hasOpening[2] and not d.connections[2].claimed
            and d.hasOpening[1] and not d.connections[1].claimed
            and d.connections[2].hasOpening[1]
            and not d.connections[2].connections[1].claimed)


def _monu_fit_children(orient, room_defs, source_room, core_room, state):
    """MonumentBuilding 构造器 L186-207：fitter 顺序分配房间。"""
    from Utils.SeedReverser import mc_random as _mcr
    children = []
    source_room.claimed = True
    children.append(("entry",
                     _monu_room_bbox(orient, source_room.index, 1, 1, 1),
                     source_room))
    children.append(("core",
                     _monu_room_bbox(orient, core_room.index, 2, 2, 2),
                     core_room))
    for d in room_defs:
        if d.claimed or d.index >= 75:
            continue
        if _monu_fits_dxy(d):
            d.claimed = True
            d.connections[5].claimed = True
            d.connections[1].claimed = True
            d.connections[5].connections[1].claimed = True
            children.append(("dxy", _monu_room_bbox(orient, d.index, 2, 2, 1), d))
        elif _monu_fits_dyz(d):
            d.claimed = True
            d.connections[2].claimed = True
            d.connections[1].claimed = True
            d.connections[2].connections[1].claimed = True
            children.append(("dyz", _monu_room_bbox(orient, d.index, 1, 2, 2), d))
        elif d.hasOpening[2] and not d.connections[2].claimed:
            src = d
            if (not d.hasOpening[2]) or d.connections[2].claimed:
                src = d.connections[3]            # L127-130（fits 后恒假，防呆）
            src.claimed = True
            src.connections[2].claimed = True
            children.append(("dz", _monu_room_bbox(orient, src.index, 1, 1, 2), src))
        elif d.hasOpening[5] and not d.connections[5].claimed:
            d.claimed = True
            d.connections[5].claimed = True
            children.append(("dx", _monu_room_bbox(orient, d.index, 2, 1, 1), d))
        elif d.hasOpening[1] and not d.connections[1].claimed:
            d.claimed = True
            d.connections[1].claimed = True
            children.append(("dy", _monu_room_bbox(orient, d.index, 1, 2, 1), d))
        elif (not d.hasOpening[4] and not d.hasOpening[5]
              and not d.hasOpening[2] and not d.hasOpening[3]
              and not d.hasOpening[1]):
            d.claimed = True
            children.append(("top", _monu_room_bbox(orient, d.index, 1, 1, 1), d))
        else:
            d.claimed = True
            v, state = _mcr.next_int(state, 3)     # SimpleRoom mainDesign
            children.append(("simple",
                             _monu_room_bbox(orient, d.index, 1, 1, 1),
                             (d, v)))
    return children, state


class _MonuSim:
    """海底神殿画块模拟器：3D dict（含 water/air）+ 海床清除 caps。

    place_block = StructurePiece.placeBlock（canBeReplaced 恒 true，
    chunkBB 全覆盖）；water_box = generateWaterBox（FILL_KEEP 保留、
    世界 y>=63 → air、否则 water）+ caps 海床压低记录；on_fill_box =
    generateBoxOnFillOnly（仅替换 water）；fill_down = fillColumnDown
    （air/液体/海草 → 实心停）。
    """

    def __init__(self, ctx, threads: int = 1):
        self.ctx = ctx
        self.threads = threads
        self.blocks: dict = {}
        self.caps: dict = {}
        self._top = None
        self._top_origin = (0, 0)

    def prefetch(self, wx0: int, wz0: int, size: int):
        g = _native.fill_top_grid(self.ctx, wx0, wz0, size, size,
                                  -64, 320, self.threads)
        self._top = g
        self._top_origin = (wx0, wz0)

    def top(self, wx: int, wz: int) -> int:
        ox, oz = self._top_origin
        ix, iz = wx - ox, wz - oz
        if 0 <= ix < self._top.shape[1] and 0 <= iz < self._top.shape[0]:
            return int(self._top[iz, ix])
        return int(_native.fill_top_grid(self.ctx, wx, wz, 1, 1,
                                         -64, 320, 1)[0, 0])

    def box(self, bb, orient, x0, y0, z0, x1, y1, z1, nm):
        for y in range(y0, y1 + 1):
            wy = bb[1] + y
            for x in range(x0, x1 + 1):
                for z in range(z0, z1 + 1):
                    self.blocks[(_monu_wx(bb, orient, x, z), wy,
                                 _monu_wz(bb, orient, x, z))] = nm

    def one(self, bb, orient, x, y, z, nm):
        self.blocks[(_monu_wx(bb, orient, x, z), bb[1] + y,
                     _monu_wz(bb, orient, x, z))] = nm

    def water_box(self, bb, orient, x0, y0, z0, x1, y1, z1):
        wy0 = bb[1] + y0
        for y in range(y0, y1 + 1):
            wy = bb[1] + y
            for x in range(x0, x1 + 1):
                for z in range(z0, z1 + 1):
                    wx = _monu_wx(bb, orient, x, z)
                    wz = _monu_wz(bb, orient, x, z)
                    cur = self.blocks.get((wx, wy, wz))
                    if cur is not None and cur in _MONU_KEEP:
                        continue
                    if wy >= 63 and cur != _MONU_WATER:
                        self.blocks[(wx, wy, wz)] = _MONU_AIR
                    else:
                        self.blocks[(wx, wy, wz)] = _MONU_WATER
        for x in range(x0, x1 + 1):
            for z in range(z0, z1 + 1):
                wx = _monu_wx(bb, orient, x, z)
                wz = _monu_wz(bb, orient, x, z)
                cap = wy0 - 1
                cur = self.caps.get((wx, wz))
                if cur is None or cap < cur:
                    self.caps[(wx, wz)] = cap

    def on_fill_box(self, bb, orient, x0, y0, z0, x1, y1, z1, nm):
        for y in range(y0, y1 + 1):
            wy = bb[1] + y
            for x in range(x0, x1 + 1):
                for z in range(z0, z1 + 1):
                    p = (_monu_wx(bb, orient, x, z), wy,
                         _monu_wz(bb, orient, x, z))
                    if self.blocks.get(p) == _MONU_WATER:
                        self.blocks[p] = nm

    def fill_down(self, bb, orient, x, y, z, nm):
        wx = _monu_wx(bb, orient, x, z)
        wz = _monu_wz(bb, orient, x, z)
        wy = bb[1] + y
        t = self.top(wx, wz)
        cap = self.caps.get((wx, wz))
        if cap is not None and t > cap:
            t = cap
        while wy > t:
            self.blocks[(wx, wy, wz)] = nm
            wy -= 1

    def top_blocks(self) -> list:
        best = {}
        for (wx, wy, wz), nm in self.blocks.items():
            if nm == _MONU_WATER or nm == _MONU_AIR:
                continue
            cur = best.get((wx, wz))
            if cur is None or wy > cur[0]:
                best[(wx, wz)] = (wy, nm)
        return [(wx, y, wz, nm) for (wx, wz), (y, nm) in best.items()]


def _monu_wing(sim, orient, bb, flipped, xoff):
    """MonumentBuilding.generateWing（L404-446）。DOT_DECO_DATA=LIGHT。"""
    sim.box(bb, orient, xoff + 0, 0, 0, xoff + 24, 0, 20, _MONU_GRAY)
    sim.water_box(bb, orient, xoff + 0, 1, 0, xoff + 24, 10, 20)
    for i in range(4):
        sim.box(bb, orient, xoff + i, i + 1, i, xoff + i, i + 1, 20,
                _MONU_LIGHT)
        sim.box(bb, orient, xoff + i + 7, i + 5, i + 7, xoff + i + 7,
                i + 5, 20, _MONU_LIGHT)
        sim.box(bb, orient, xoff + 17 - i, i + 5, i + 7, xoff + 17 - i,
                i + 5, 20, _MONU_LIGHT)
        sim.box(bb, orient, xoff + 24 - i, i + 1, i, xoff + 24 - i,
                i + 1, 20, _MONU_LIGHT)
        sim.box(bb, orient, xoff + i + 1, i + 1, i, xoff + 23 - i,
                i + 1, i, _MONU_LIGHT)
        sim.box(bb, orient, xoff + i + 8, i + 5, i + 7, xoff + 16 - i,
                i + 5, i + 7, _MONU_LIGHT)
    sim.box(bb, orient, xoff + 4, 4, 4, xoff + 6, 4, 20, _MONU_GRAY)
    sim.box(bb, orient, xoff + 7, 4, 4, xoff + 17, 4, 6, _MONU_GRAY)
    sim.box(bb, orient, xoff + 18, 4, 4, xoff + 20, 4, 20, _MONU_GRAY)
    sim.box(bb, orient, xoff + 11, 8, 11, xoff + 13, 8, 20, _MONU_GRAY)
    sim.one(bb, orient, xoff + 12, 9, 12, _MONU_LIGHT)
    sim.one(bb, orient, xoff + 12, 9, 15, _MONU_LIGHT)
    sim.one(bb, orient, xoff + 12, 9, 18, _MONU_LIGHT)
    left_pos = xoff + (19 if flipped else 5)
    right_pos = xoff + (5 if flipped else 19)
    for z in range(20, 4, -3):
        sim.one(bb, orient, left_pos, 5, z, _MONU_LIGHT)
    for z in range(19, 6, -3):
        sim.one(bb, orient, right_pos, 5, z, _MONU_LIGHT)
    for i in range(4):
        pos = (xoff + 24 - (17 - i * 3)) if flipped else (xoff + 17 - i * 3)
        sim.one(bb, orient, pos, 5, 5, _MONU_LIGHT)
    sim.one(bb, orient, right_pos, 5, 5, _MONU_LIGHT)
    sim.box(bb, orient, xoff + 11, 1, 12, xoff + 13, 7, 12, _MONU_GRAY)
    sim.box(bb, orient, xoff + 12, 1, 11, xoff + 12, 7, 13, _MONU_GRAY)


def _monu_archs(sim, orient, bb):
    """generateEntranceArchs（L448-466）。"""
    sim.water_box(bb, orient, 25, 0, 0, 32, 8, 20)
    for i in range(4):
        z4 = 5 + i * 4
        sim.box(bb, orient, 24, 2, z4, 24, 4, z4, _MONU_LIGHT)
        sim.box(bb, orient, 22, 4, z4, 23, 4, z4, _MONU_LIGHT)
        sim.one(bb, orient, 25, 5, z4, _MONU_LIGHT)
        sim.one(bb, orient, 26, 6, z4, _MONU_LIGHT)
        sim.one(bb, orient, 26, 5, z4, _MONU_LAMP)
        sim.box(bb, orient, 33, 2, z4, 33, 4, z4, _MONU_LIGHT)
        sim.box(bb, orient, 34, 4, z4, 35, 4, z4, _MONU_LIGHT)
        sim.one(bb, orient, 32, 5, z4, _MONU_LIGHT)
        sim.one(bb, orient, 31, 6, z4, _MONU_LIGHT)
        sim.one(bb, orient, 31, 5, z4, _MONU_LAMP)
        sim.box(bb, orient, 27, 6, z4, 30, 6, z4, _MONU_GRAY)


def _monu_entrance_wall(sim, orient, bb):
    """generateEntranceWall（L468-525）。"""
    sim.box(bb, orient, 15, 0, 21, 42, 0, 21, _MONU_GRAY)
    sim.water_box(bb, orient, 26, 1, 21, 31, 3, 21)
    sim.box(bb, orient, 21, 12, 21, 36, 12, 21, _MONU_GRAY)
    sim.box(bb, orient, 17, 11, 21, 40, 11, 21, _MONU_GRAY)
    sim.box(bb, orient, 16, 10, 21, 41, 10, 21, _MONU_GRAY)
    sim.box(bb, orient, 15, 7, 21, 42, 9, 21, _MONU_GRAY)
    sim.box(bb, orient, 16, 6, 21, 41, 6, 21, _MONU_GRAY)
    sim.box(bb, orient, 17, 5, 21, 40, 5, 21, _MONU_GRAY)
    sim.box(bb, orient, 21, 4, 21, 36, 4, 21, _MONU_GRAY)
    sim.box(bb, orient, 22, 3, 21, 26, 3, 21, _MONU_GRAY)
    sim.box(bb, orient, 31, 3, 21, 35, 3, 21, _MONU_GRAY)
    sim.box(bb, orient, 23, 2, 21, 25, 2, 21, _MONU_GRAY)
    sim.box(bb, orient, 32, 2, 21, 34, 2, 21, _MONU_GRAY)
    sim.box(bb, orient, 28, 4, 20, 29, 4, 21, _MONU_LIGHT)
    sim.one(bb, orient, 27, 3, 21, _MONU_LIGHT)
    sim.one(bb, orient, 30, 3, 21, _MONU_LIGHT)
    sim.one(bb, orient, 26, 2, 21, _MONU_LIGHT)
    sim.one(bb, orient, 31, 2, 21, _MONU_LIGHT)
    sim.one(bb, orient, 25, 1, 21, _MONU_LIGHT)
    sim.one(bb, orient, 32, 1, 21, _MONU_LIGHT)
    for i in range(7):
        sim.one(bb, orient, 28 - i, 6 + i, 21, _MONU_BLACK)
        sim.one(bb, orient, 29 + i, 6 + i, 21, _MONU_BLACK)
    for i in range(4):
        sim.one(bb, orient, 28 - i, 9 + i, 21, _MONU_BLACK)
        sim.one(bb, orient, 29 + i, 9 + i, 21, _MONU_BLACK)
    sim.one(bb, orient, 28, 12, 21, _MONU_BLACK)
    sim.one(bb, orient, 29, 12, 21, _MONU_BLACK)
    for i in range(3):
        sim.one(bb, orient, 22 - i * 2, 8, 21, _MONU_BLACK)
        sim.one(bb, orient, 22 - i * 2, 9, 21, _MONU_BLACK)
        sim.one(bb, orient, 35 + i * 2, 8, 21, _MONU_BLACK)
        sim.one(bb, orient, 35 + i * 2, 9, 21, _MONU_BLACK)
    sim.water_box(bb, orient, 15, 13, 21, 42, 15, 21)
    sim.water_box(bb, orient, 15, 1, 21, 15, 6, 21)
    sim.water_box(bb, orient, 16, 1, 21, 16, 5, 21)
    sim.water_box(bb, orient, 17, 1, 21, 20, 4, 21)
    sim.water_box(bb, orient, 21, 1, 21, 21, 3, 21)
    sim.water_box(bb, orient, 22, 1, 21, 22, 2, 21)
    sim.water_box(bb, orient, 23, 1, 21, 24, 1, 21)
    sim.water_box(bb, orient, 42, 1, 21, 42, 6, 21)
    sim.water_box(bb, orient, 41, 1, 21, 41, 5, 21)
    sim.water_box(bb, orient, 37, 1, 21, 40, 4, 21)
    sim.water_box(bb, orient, 36, 1, 21, 36, 3, 21)
    sim.water_box(bb, orient, 33, 1, 21, 34, 1, 21)
    sim.water_box(bb, orient, 35, 1, 21, 35, 2, 21)


def _monu_roof(sim, orient, bb):
    """generateRoofPiece（L527-561）。"""
    sim.box(bb, orient, 21, 0, 22, 36, 0, 36, _MONU_GRAY)
    sim.water_box(bb, orient, 21, 1, 22, 36, 23, 36)
    for i in range(4):
        y = 13 + i
        sim.box(bb, orient, 21 + i, y, 21 + i, 36 - i, y, 21 + i,
                _MONU_LIGHT)
        sim.box(bb, orient, 21 + i, y, 36 - i, 36 - i, y, 36 - i,
                _MONU_LIGHT)
        sim.box(bb, orient, 21 + i, y, 22 + i, 21 + i, y, 35 - i,
                _MONU_LIGHT)
        sim.box(bb, orient, 36 - i, y, 22 + i, 36 - i, y, 35 - i,
                _MONU_LIGHT)
    sim.box(bb, orient, 25, 16, 25, 32, 16, 32, _MONU_GRAY)
    for cx0, cz0 in ((25, 25), (32, 25), (25, 32), (32, 32)):
        sim.box(bb, orient, cx0, 17, cz0, cx0, 19, cz0, _MONU_LIGHT)
    sim.one(bb, orient, 26, 20, 26, _MONU_LIGHT)
    sim.one(bb, orient, 27, 21, 27, _MONU_LIGHT)
    sim.one(bb, orient, 27, 20, 27, _MONU_LAMP)
    sim.one(bb, orient, 26, 20, 31, _MONU_LIGHT)
    sim.one(bb, orient, 27, 21, 30, _MONU_LIGHT)
    sim.one(bb, orient, 27, 20, 30, _MONU_LAMP)
    sim.one(bb, orient, 31, 20, 31, _MONU_LIGHT)
    sim.one(bb, orient, 30, 21, 30, _MONU_LIGHT)
    sim.one(bb, orient, 30, 20, 30, _MONU_LAMP)
    sim.one(bb, orient, 31, 20, 26, _MONU_LIGHT)
    sim.one(bb, orient, 30, 21, 27, _MONU_LIGHT)
    sim.one(bb, orient, 30, 20, 27, _MONU_LAMP)
    sim.box(bb, orient, 28, 21, 27, 29, 21, 27, _MONU_GRAY)
    sim.box(bb, orient, 27, 21, 28, 27, 21, 29, _MONU_GRAY)
    sim.box(bb, orient, 28, 21, 30, 29, 21, 30, _MONU_GRAY)
    sim.box(bb, orient, 30, 21, 28, 30, 21, 29, _MONU_GRAY)


def _monu_lower_wall(sim, orient, bb):
    """generateLowerWall（L563-613）。"""
    sim.box(bb, orient, 0, 0, 21, 6, 0, 57, _MONU_GRAY)
    sim.water_box(bb, orient, 0, 1, 21, 6, 7, 57)
    sim.box(bb, orient, 4, 4, 21, 6, 4, 53, _MONU_GRAY)
    for i in range(4):
        sim.box(bb, orient, i, i + 1, 21, i, i + 1, 57 - i, _MONU_LIGHT)
    for z in range(23, 53, 3):
        sim.one(bb, orient, 5, 5, z, _MONU_LIGHT)
    sim.one(bb, orient, 5, 5, 52, _MONU_LIGHT)
    sim.box(bb, orient, 4, 1, 52, 6, 3, 52, _MONU_GRAY)
    sim.box(bb, orient, 5, 1, 51, 5, 3, 53, _MONU_GRAY)
    sim.box(bb, orient, 51, 0, 21, 57, 0, 57, _MONU_GRAY)
    sim.water_box(bb, orient, 51, 1, 21, 57, 7, 57)
    sim.box(bb, orient, 51, 4, 21, 53, 4, 53, _MONU_GRAY)
    for i in range(4):
        sim.box(bb, orient, 57 - i, i + 1, 21, 57 - i, i + 1, 57 - i,
                _MONU_LIGHT)
    for z in range(23, 53, 3):
        sim.one(bb, orient, 52, 5, z, _MONU_LIGHT)
    sim.one(bb, orient, 52, 5, 52, _MONU_LIGHT)
    sim.box(bb, orient, 51, 1, 52, 53, 3, 52, _MONU_GRAY)
    sim.box(bb, orient, 52, 1, 51, 52, 3, 53, _MONU_GRAY)
    sim.box(bb, orient, 7, 0, 51, 50, 0, 57, _MONU_GRAY)
    sim.water_box(bb, orient, 7, 1, 51, 50, 10, 57)
    for i in range(4):
        sim.box(bb, orient, i + 1, i + 1, 57 - i, 56 - i, i + 1, 57 - i,
                _MONU_LIGHT)


def _monu_middle_wall(sim, orient, bb):
    """generateMiddleWall（L615-672）。"""
    sim.box(bb, orient, 7, 0, 21, 13, 0, 50, _MONU_GRAY)
    sim.water_box(bb, orient, 7, 1, 21, 13, 10, 50)
    sim.box(bb, orient, 11, 8, 21, 13, 8, 53, _MONU_GRAY)
    for i in range(4):
        sim.box(bb, orient, i + 7, i + 5, 21, i + 7, i + 5, 54,
                _MONU_LIGHT)
    for z in range(21, 46, 3):
        sim.one(bb, orient, 12, 9, z, _MONU_LIGHT)
    sim.box(bb, orient, 44, 0, 21, 50, 0, 50, _MONU_GRAY)
    sim.water_box(bb, orient, 44, 1, 21, 50, 10, 50)
    sim.box(bb, orient, 44, 8, 21, 46, 8, 53, _MONU_GRAY)
    for i in range(4):
        sim.box(bb, orient, 50 - i, i + 5, 21, 50 - i, i + 5, 54,
                _MONU_LIGHT)
    for z in range(21, 46, 3):
        sim.one(bb, orient, 45, 9, z, _MONU_LIGHT)
    sim.box(bb, orient, 14, 0, 44, 43, 0, 50, _MONU_GRAY)
    sim.water_box(bb, orient, 14, 1, 44, 43, 10, 50)
    for x in range(12, 46, 3):
        sim.one(bb, orient, x, 9, 45, _MONU_LIGHT)
        sim.one(bb, orient, x, 9, 52, _MONU_LIGHT)
        if x in (12, 18, 24, 33, 39, 45):
            sim.one(bb, orient, x, 9, 47, _MONU_LIGHT)
            sim.one(bb, orient, x, 9, 50, _MONU_LIGHT)
            sim.one(bb, orient, x, 10, 45, _MONU_LIGHT)
            sim.one(bb, orient, x, 10, 46, _MONU_LIGHT)
            sim.one(bb, orient, x, 10, 51, _MONU_LIGHT)
            sim.one(bb, orient, x, 10, 52, _MONU_LIGHT)
            sim.one(bb, orient, x, 11, 47, _MONU_LIGHT)
            sim.one(bb, orient, x, 11, 50, _MONU_LIGHT)
            sim.one(bb, orient, x, 12, 48, _MONU_LIGHT)
            sim.one(bb, orient, x, 12, 49, _MONU_LIGHT)
    for i in range(3):
        sim.box(bb, orient, 8 + i, 5 + i, 54, 49 - i, 5 + i, 54,
                _MONU_GRAY)
    sim.box(bb, orient, 11, 8, 54, 46, 8, 54, _MONU_LIGHT)
    sim.box(bb, orient, 14, 8, 44, 43, 8, 53, _MONU_GRAY)


def _monu_upper_wall(sim, orient, bb):
    """generateUpperWall（L674-718）。"""
    sim.box(bb, orient, 14, 0, 21, 20, 0, 43, _MONU_GRAY)
    sim.water_box(bb, orient, 14, 1, 22, 20, 14, 43)
    sim.box(bb, orient, 18, 12, 22, 20, 12, 39, _MONU_GRAY)
    sim.box(bb, orient, 18, 12, 21, 20, 12, 21, _MONU_LIGHT)
    for i in range(4):
        sim.box(bb, orient, i + 14, i + 9, 21, i + 14, i + 9, 43 - i,
                _MONU_LIGHT)
    for z in range(23, 40, 3):
        sim.one(bb, orient, 19, 13, z, _MONU_LIGHT)
    sim.box(bb, orient, 37, 0, 21, 43, 0, 43, _MONU_GRAY)
    sim.water_box(bb, orient, 37, 1, 22, 43, 14, 43)
    sim.box(bb, orient, 37, 12, 22, 39, 12, 39, _MONU_GRAY)
    sim.box(bb, orient, 37, 12, 21, 39, 12, 21, _MONU_LIGHT)
    for i in range(4):
        sim.box(bb, orient, 43 - i, i + 9, 21, 43 - i, i + 9, 43 - i,
                _MONU_LIGHT)
    for z in range(23, 40, 3):
        sim.one(bb, orient, 38, 13, z, _MONU_LIGHT)
    sim.box(bb, orient, 21, 0, 37, 36, 0, 43, _MONU_GRAY)
    sim.water_box(bb, orient, 21, 1, 37, 36, 14, 43)
    sim.box(bb, orient, 21, 12, 37, 36, 12, 39, _MONU_GRAY)
    for i in range(4):
        sim.box(bb, orient, 15 + i, i + 9, 43 - i, 42 - i, i + 9, 43 - i,
                _MONU_LIGHT)
    for x in range(21, 37, 3):
        sim.one(bb, orient, x, 13, 38, _MONU_LIGHT)


def _monu_post_building(sim, orient, bb, children):
    """MonumentBuilding.postProcess（L343-402）全序。"""
    sim.water_box(bb, orient, 0, 0, 0, 58, 25, 58)     # L354 主水盒
    _monu_wing(sim, orient, bb, False, 0)               # L355
    _monu_wing(sim, orient, bb, True, 33)               # L356
    _monu_archs(sim, orient, bb)                        # L357
    _monu_entrance_wall(sim, orient, bb)                # L358
    _monu_roof(sim, orient, bb)                         # L359
    _monu_lower_wall(sim, orient, bb)                   # L360
    _monu_middle_wall(sim, orient, bb)                  # L361
    _monu_upper_wall(sim, orient, bb)                   # L362
    for px in range(7):                                 # L364-388 柱网
        pz = 0
        while pz < 7:
            if pz == 0 and px == 3:
                pz = 6
            bx, bz = px * 9, pz * 9
            for w4 in range(4):
                for d4 in range(4):
                    sim.one(bb, orient, bx + w4, 0, bz + d4, _MONU_LIGHT)
                    sim.fill_down(bb, orient, bx + w4, -1, bz + d4,
                                  _MONU_LIGHT)
            pz += 6 if px not in (0, 6) else 1
    for i in range(5):                                  # L390-395 外圈阶梯
        y0 = i * 2
        sim.water_box(bb, orient, -1 - i, y0, -1 - i, -1 - i, 23, 58 + i)
        sim.water_box(bb, orient, 58 + i, y0, -1 - i, 58 + i, 23, 58 + i)
        sim.water_box(bb, orient, -i, y0, -1 - i, 57 + i, 23, -1 - i)
        sim.water_box(bb, orient, -i, y0, 58 + i, 57 + i, 23, 58 + i)
    for kind, cb, meta in children:                     # L397-401 子 pieces
        _MONU_POST[kind](sim, orient, cb, meta)


def _monu_floor(sim, orient, bb, xoff, zoff, down_opening):
    """generateDefaultFloor（L1526-1539）。"""
    if down_opening:
        sim.box(bb, orient, xoff + 0, 0, zoff + 0, xoff + 2, 0, zoff + 7,
                _MONU_GRAY)
        sim.box(bb, orient, xoff + 5, 0, zoff + 0, xoff + 7, 0, zoff + 7,
                _MONU_GRAY)
        sim.box(bb, orient, xoff + 3, 0, zoff + 0, xoff + 4, 0, zoff + 2,
                _MONU_GRAY)
        sim.box(bb, orient, xoff + 3, 0, zoff + 5, xoff + 4, 0, zoff + 7,
                _MONU_GRAY)
        sim.box(bb, orient, xoff + 3, 0, zoff + 2, xoff + 4, 0, zoff + 2,
                _MONU_LIGHT)
        sim.box(bb, orient, xoff + 3, 0, zoff + 5, xoff + 4, 0, zoff + 5,
                _MONU_LIGHT)
        sim.box(bb, orient, xoff + 2, 0, zoff + 3, xoff + 2, 0, zoff + 4,
                _MONU_LIGHT)
        sim.box(bb, orient, xoff + 5, 0, zoff + 3, xoff + 5, 0, zoff + 4,
                _MONU_LIGHT)
    else:
        sim.box(bb, orient, xoff + 0, 0, zoff + 0, xoff + 7, 0, zoff + 7,
                _MONU_GRAY)


def _monu_post_entry(sim, orient, bb, d):
    """OceanMonumentEntryRoom（L1324-1353）。"""
    sim.box(bb, orient, 0, 3, 0, 2, 3, 7, _MONU_LIGHT)
    sim.box(bb, orient, 5, 3, 0, 7, 3, 7, _MONU_LIGHT)
    sim.box(bb, orient, 0, 2, 0, 1, 2, 7, _MONU_LIGHT)
    sim.box(bb, orient, 6, 2, 0, 7, 2, 7, _MONU_LIGHT)
    sim.box(bb, orient, 0, 1, 0, 0, 1, 7, _MONU_LIGHT)
    sim.box(bb, orient, 7, 1, 0, 7, 1, 7, _MONU_LIGHT)
    sim.box(bb, orient, 0, 1, 7, 7, 3, 7, _MONU_LIGHT)
    sim.box(bb, orient, 1, 1, 0, 2, 3, 0, _MONU_LIGHT)
    sim.box(bb, orient, 5, 1, 0, 6, 3, 0, _MONU_LIGHT)
    if d.hasOpening[2]:
        sim.water_box(bb, orient, 3, 1, 7, 4, 2, 7)
    if d.hasOpening[4]:
        sim.water_box(bb, orient, 0, 1, 3, 1, 2, 4)
    if d.hasOpening[5]:
        sim.water_box(bb, orient, 6, 1, 3, 7, 2, 4)


def _monu_post_core(sim, orient, bb, d):
    """OceanMonumentCoreRoom（L737-810）。"""
    sim.on_fill_box(bb, orient, 1, 8, 0, 14, 8, 14, _MONU_GRAY)
    for x0, z0, x1, z1 in ((0, 0, 0, 15), (15, 0, 15, 15),
                           (1, 0, 15, 0), (1, 15, 14, 15)):
        sim.box(bb, orient, x0, 7, z0, x1, 7, z1, _MONU_LIGHT)
    for yx in range(1, 7):
        blk = _MONU_GRAY if yx in (2, 6) else _MONU_LIGHT
        for x in (0, 15):
            sim.box(bb, orient, x, yx, 0, x, yx, 1, blk)
            sim.box(bb, orient, x, yx, 6, x, yx, 9, blk)
            sim.box(bb, orient, x, yx, 14, x, yx, 15, blk)
        sim.box(bb, orient, 1, yx, 0, 1, yx, 0, blk)
        sim.box(bb, orient, 6, yx, 0, 9, yx, 0, blk)
        sim.box(bb, orient, 14, yx, 0, 14, yx, 0, blk)
        sim.box(bb, orient, 1, yx, 15, 14, yx, 15, blk)
    sim.box(bb, orient, 6, 3, 6, 9, 6, 9, _MONU_BLACK)
    sim.box(bb, orient, 7, 4, 7, 8, 5, 8, _MONU_GOLD)
    for yx in (3, 6):
        for x in (6, 9):
            sim.one(bb, orient, x, yx, 6, _MONU_LAMP)
            sim.one(bb, orient, x, yx, 9, _MONU_LAMP)
    for x0, z0 in ((5, 6), (5, 9), (10, 6), (10, 9),
                   (6, 5), (9, 5), (6, 10), (9, 10)):
        sim.box(bb, orient, x0, 1, z0, x0, 2, z0, _MONU_LIGHT)
    for x0, z0 in ((5, 5), (5, 10), (10, 5), (10, 10)):
        sim.box(bb, orient, x0, 2, z0, x0, 6, z0, _MONU_LIGHT)
    for x0, z0, x1 in ((5, 1, 5), (10, 1, 10)):
        sim.box(bb, orient, x0, 7, z0, x1, 7, 6, _MONU_LIGHT)
        sim.box(bb, orient, x0, 7, 9, x1, 7, 14, _MONU_LIGHT)
    for z0 in (5, 10):
        sim.box(bb, orient, 1, 7, z0, 6, 7, z0, _MONU_LIGHT)
        sim.box(bb, orient, 9, 7, z0, 14, 7, z0, _MONU_LIGHT)
    sim.box(bb, orient, 2, 1, 2, 2, 1, 3, _MONU_LIGHT)
    sim.box(bb, orient, 3, 1, 2, 3, 1, 2, _MONU_LIGHT)
    sim.box(bb, orient, 13, 1, 2, 13, 1, 3, _MONU_LIGHT)
    sim.box(bb, orient, 12, 1, 2, 12, 1, 2, _MONU_LIGHT)
    sim.box(bb, orient, 2, 1, 12, 2, 1, 13, _MONU_LIGHT)
    sim.box(bb, orient, 3, 1, 13, 3, 1, 13, _MONU_LIGHT)
    sim.box(bb, orient, 13, 1, 12, 13, 1, 13, _MONU_LIGHT)
    sim.box(bb, orient, 12, 1, 13, 12, 1, 13, _MONU_LIGHT)


def _monu_post_dx(sim, orient, bb, d):
    """OceanMonumentDoubleXRoom（L823-887）。east=conn[5]、west=自身。"""
    east = d.connections[5]
    if d.index // 25 > 0:
        _monu_floor(sim, orient, bb, 8, 0, east.hasOpening[0])
        _monu_floor(sim, orient, bb, 0, 0, d.hasOpening[0])
    if d.connections[1] is None:
        sim.on_fill_box(bb, orient, 1, 4, 1, 7, 4, 6, _MONU_GRAY)
    if east.connections[1] is None:
        sim.on_fill_box(bb, orient, 8, 4, 1, 14, 4, 6, _MONU_GRAY)
    sim.box(bb, orient, 0, 3, 0, 0, 3, 7, _MONU_LIGHT)
    sim.box(bb, orient, 15, 3, 0, 15, 3, 7, _MONU_LIGHT)
    sim.box(bb, orient, 1, 3, 0, 15, 3, 0, _MONU_LIGHT)
    sim.box(bb, orient, 1, 3, 7, 14, 3, 7, _MONU_LIGHT)
    sim.box(bb, orient, 0, 2, 0, 0, 2, 7, _MONU_GRAY)
    sim.box(bb, orient, 15, 2, 0, 15, 2, 7, _MONU_GRAY)
    sim.box(bb, orient, 1, 2, 0, 15, 2, 0, _MONU_GRAY)
    sim.box(bb, orient, 1, 2, 7, 14, 2, 7, _MONU_GRAY)
    sim.box(bb, orient, 0, 1, 0, 0, 1, 7, _MONU_LIGHT)
    sim.box(bb, orient, 15, 1, 0, 15, 1, 7, _MONU_LIGHT)
    sim.box(bb, orient, 1, 1, 0, 15, 1, 0, _MONU_LIGHT)
    sim.box(bb, orient, 1, 1, 7, 14, 1, 7, _MONU_LIGHT)
    sim.box(bb, orient, 5, 1, 0, 10, 1, 4, _MONU_LIGHT)
    sim.box(bb, orient, 6, 2, 0, 9, 2, 3, _MONU_GRAY)
    sim.box(bb, orient, 5, 3, 0, 10, 3, 4, _MONU_LIGHT)
    sim.one(bb, orient, 6, 2, 3, _MONU_LAMP)
    sim.one(bb, orient, 9, 2, 3, _MONU_LAMP)
    if d.hasOpening[3]:
        sim.water_box(bb, orient, 3, 1, 0, 4, 2, 0)
    if d.hasOpening[2]:
        sim.water_box(bb, orient, 3, 1, 7, 4, 2, 7)
    if d.hasOpening[4]:
        sim.water_box(bb, orient, 0, 1, 3, 0, 2, 4)
    if east.hasOpening[3]:
        sim.water_box(bb, orient, 11, 1, 0, 12, 2, 0)
    if east.hasOpening[2]:
        sim.water_box(bb, orient, 11, 1, 7, 12, 2, 7)
    if east.hasOpening[5]:
        sim.water_box(bb, orient, 15, 1, 3, 15, 2, 4)


def _monu_post_dxy(sim, orient, bb, d):
    """OceanMonumentDoubleXYRoom（L900-1008）。"""
    east = d.connections[5]
    west_up = d.connections[1]
    east_up = east.connections[1]
    if d.index // 25 > 0:
        _monu_floor(sim, orient, bb, 8, 0, east.hasOpening[0])
        _monu_floor(sim, orient, bb, 0, 0, d.hasOpening[0])
    if west_up.connections[1] is None:
        sim.on_fill_box(bb, orient, 1, 8, 1, 7, 8, 6, _MONU_GRAY)
    if east_up.connections[1] is None:
        sim.on_fill_box(bb, orient, 8, 8, 1, 14, 8, 6, _MONU_GRAY)
    for y in range(1, 8):
        blk = _MONU_GRAY if y in (2, 6) else _MONU_LIGHT
        sim.box(bb, orient, 0, y, 0, 0, y, 7, blk)
        sim.box(bb, orient, 15, y, 0, 15, y, 7, blk)
        sim.box(bb, orient, 1, y, 0, 15, y, 0, blk)
        sim.box(bb, orient, 1, y, 7, 14, y, 7, blk)
    sim.box(bb, orient, 2, 1, 3, 2, 7, 4, _MONU_LIGHT)
    sim.box(bb, orient, 3, 1, 2, 4, 7, 2, _MONU_LIGHT)
    sim.box(bb, orient, 3, 1, 5, 4, 7, 5, _MONU_LIGHT)
    sim.box(bb, orient, 13, 1, 3, 13, 7, 4, _MONU_LIGHT)
    sim.box(bb, orient, 11, 1, 2, 12, 7, 2, _MONU_LIGHT)
    sim.box(bb, orient, 11, 1, 5, 12, 7, 5, _MONU_LIGHT)
    sim.box(bb, orient, 5, 1, 3, 5, 3, 4, _MONU_LIGHT)
    sim.box(bb, orient, 10, 1, 3, 10, 3, 4, _MONU_LIGHT)
    sim.box(bb, orient, 5, 7, 2, 10, 7, 5, _MONU_LIGHT)
    for x0 in (5, 10):
        for z0 in (2, 5):
            sim.box(bb, orient, x0, 5, z0, x0, 7, z0, _MONU_LIGHT)
    for x0, z0 in ((6, 2), (9, 2), (6, 5), (9, 5)):
        sim.one(bb, orient, x0, 6, z0, _MONU_LIGHT)
    sim.box(bb, orient, 5, 4, 3, 6, 4, 4, _MONU_LIGHT)
    sim.box(bb, orient, 9, 4, 3, 10, 4, 4, _MONU_LIGHT)
    for x0, z0 in ((5, 2), (5, 5), (10, 2), (10, 5)):
        sim.one(bb, orient, x0, 4, z0, _MONU_LAMP)
    if d.hasOpening[3]:
        sim.water_box(bb, orient, 3, 1, 0, 4, 2, 0)
    if d.hasOpening[2]:
        sim.water_box(bb, orient, 3, 1, 7, 4, 2, 7)
    if d.hasOpening[4]:
        sim.water_box(bb, orient, 0, 1, 3, 0, 2, 4)
    if east.hasOpening[3]:
        sim.water_box(bb, orient, 11, 1, 0, 12, 2, 0)
    if east.hasOpening[2]:
        sim.water_box(bb, orient, 11, 1, 7, 12, 2, 7)
    if east.hasOpening[5]:
        sim.water_box(bb, orient, 15, 1, 3, 15, 2, 4)
    if west_up.hasOpening[3]:
        sim.water_box(bb, orient, 3, 5, 0, 4, 6, 0)
    if west_up.hasOpening[2]:
        sim.water_box(bb, orient, 3, 5, 7, 4, 6, 7)
    if west_up.hasOpening[4]:
        sim.water_box(bb, orient, 0, 5, 3, 0, 6, 4)
    if east_up.hasOpening[3]:
        sim.water_box(bb, orient, 11, 5, 0, 12, 6, 0)
    if east_up.hasOpening[2]:
        sim.water_box(bb, orient, 11, 5, 7, 12, 6, 7)
    if east_up.hasOpening[5]:
        sim.water_box(bb, orient, 15, 5, 3, 15, 6, 4)


def _monu_post_dy(sim, orient, bb, d):
    """OceanMonumentDoubleYRoom（L1021-1096）。"""
    if d.index // 25 > 0:
        _monu_floor(sim, orient, bb, 0, 0, d.hasOpening[0])
    above = d.connections[1]
    if above.connections[1] is None:
        sim.on_fill_box(bb, orient, 1, 8, 1, 6, 8, 6, _MONU_GRAY)
    sim.box(bb, orient, 0, 4, 0, 0, 4, 7, _MONU_LIGHT)
    sim.box(bb, orient, 7, 4, 0, 7, 4, 7, _MONU_LIGHT)
    sim.box(bb, orient, 1, 4, 0, 6, 4, 0, _MONU_LIGHT)
    sim.box(bb, orient, 1, 4, 7, 6, 4, 7, _MONU_LIGHT)
    for x0, z0, z1 in ((2, 1, 1), (1, 2, 2), (5, 1, 2), (6, 2, 2),
                       (2, 5, 6), (1, 5, 5), (5, 5, 6), (6, 5, 5)):
        sim.box(bb, orient, x0, 4, z0, x0, 4, z1, _MONU_LIGHT)
    definition = d
    for y in (1, 5):
        for cond, axis, fixed, lo, hi in (
                (3, "z", 0, 0, 0), (2, "z", 7, 7, 7),
                (4, "x", 0, 0, 0), (5, "x", 7, 7, 7)):
            if definition.hasOpening[cond]:
                if axis == "z":
                    sim.box(bb, orient, 2, y, fixed, 2, y + 2, fixed,
                            _MONU_LIGHT)
                    sim.box(bb, orient, 5, y, fixed, 5, y + 2, fixed,
                            _MONU_LIGHT)
                    sim.box(bb, orient, 3, y + 2, fixed, 4, y + 2, fixed,
                            _MONU_LIGHT)
                else:
                    sim.box(bb, orient, fixed, y, 2, fixed, y + 2, 2,
                            _MONU_LIGHT)
                    sim.box(bb, orient, fixed, y, 5, fixed, y + 2, 5,
                            _MONU_LIGHT)
                    sim.box(bb, orient, fixed, y + 2, 3, fixed, y + 2, 4,
                            _MONU_LIGHT)
            else:
                if axis == "z":
                    sim.box(bb, orient, 0, y, fixed, 7, y + 2, fixed,
                            _MONU_LIGHT)
                    sim.box(bb, orient, 0, y + 1, fixed, 7, y + 1, fixed,
                            _MONU_GRAY)
                else:
                    sim.box(bb, orient, fixed, y, 0, fixed, y + 2, 7,
                            _MONU_LIGHT)
                    sim.box(bb, orient, fixed, y + 1, 0, fixed, y + 1, 7,
                            _MONU_GRAY)
        definition = above


def _monu_post_dyz(sim, orient, bb, d):
    """OceanMonumentDoubleYZRoom（L1109-1215）。north=conn[2]、south=自身。"""
    north = d.connections[2]
    south = d
    north_up = north.connections[1]
    south_up = south.connections[1]
    if d.index // 25 > 0:
        _monu_floor(sim, orient, bb, 0, 8, north.hasOpening[0])
        _monu_floor(sim, orient, bb, 0, 0, south.hasOpening[0])
    if south_up.connections[1] is None:
        sim.on_fill_box(bb, orient, 1, 8, 1, 6, 8, 7, _MONU_GRAY)
    if north_up.connections[1] is None:
        sim.on_fill_box(bb, orient, 1, 8, 8, 6, 8, 14, _MONU_GRAY)
    for y in range(1, 8):
        blk = _MONU_GRAY if y in (2, 6) else _MONU_LIGHT
        sim.box(bb, orient, 0, y, 0, 0, y, 15, blk)
        sim.box(bb, orient, 7, y, 0, 7, y, 15, blk)
        sim.box(bb, orient, 1, y, 0, 6, y, 0, blk)
        sim.box(bb, orient, 1, y, 15, 6, y, 15, blk)
    for y in range(1, 8):
        blk = _MONU_LAMP if y in (2, 6) else _MONU_BLACK
        sim.box(bb, orient, 3, y, 7, 4, y, 8, blk)
    if south.hasOpening[3]:
        sim.water_box(bb, orient, 3, 1, 0, 4, 2, 0)
    if south.hasOpening[5]:
        sim.water_box(bb, orient, 7, 1, 3, 7, 2, 4)
    if south.hasOpening[4]:
        sim.water_box(bb, orient, 0, 1, 3, 0, 2, 4)
    if north.hasOpening[2]:
        sim.water_box(bb, orient, 3, 1, 15, 4, 2, 15)
    if north.hasOpening[4]:
        sim.water_box(bb, orient, 0, 1, 11, 0, 2, 12)
    if north.hasOpening[5]:
        sim.water_box(bb, orient, 7, 1, 11, 7, 2, 12)
    if south_up.hasOpening[3]:
        sim.water_box(bb, orient, 3, 5, 0, 4, 6, 0)
    if south_up.hasOpening[5]:
        sim.water_box(bb, orient, 7, 5, 3, 7, 6, 4)
        sim.box(bb, orient, 5, 4, 2, 6, 4, 5, _MONU_LIGHT)
        sim.box(bb, orient, 6, 1, 2, 6, 3, 2, _MONU_LIGHT)
        sim.box(bb, orient, 6, 1, 5, 6, 3, 5, _MONU_LIGHT)
    if south_up.hasOpening[4]:
        sim.water_box(bb, orient, 0, 5, 3, 0, 6, 4)
        sim.box(bb, orient, 1, 4, 2, 2, 4, 5, _MONU_LIGHT)
        sim.box(bb, orient, 1, 1, 2, 1, 3, 2, _MONU_LIGHT)
        sim.box(bb, orient, 1, 1, 5, 1, 3, 5, _MONU_LIGHT)
    if north_up.hasOpening[2]:
        sim.water_box(bb, orient, 3, 5, 15, 4, 6, 15)
    if north_up.hasOpening[4]:
        sim.water_box(bb, orient, 0, 5, 11, 0, 6, 12)
        sim.box(bb, orient, 1, 4, 10, 2, 4, 13, _MONU_LIGHT)
        sim.box(bb, orient, 1, 1, 10, 1, 3, 10, _MONU_LIGHT)
        sim.box(bb, orient, 1, 1, 13, 1, 3, 13, _MONU_LIGHT)
    if north_up.hasOpening[5]:
        sim.water_box(bb, orient, 7, 5, 11, 7, 6, 12)
        sim.box(bb, orient, 5, 4, 10, 6, 4, 13, _MONU_LIGHT)
        sim.box(bb, orient, 6, 1, 10, 6, 3, 10, _MONU_LIGHT)
        sim.box(bb, orient, 6, 1, 13, 6, 3, 13, _MONU_LIGHT)


def _monu_post_dz(sim, orient, bb, d):
    """OceanMonumentDoubleZRoom（L1228-1311）。north=conn[2]、south=自身。"""
    north = d.connections[2]
    south = d
    if d.index // 25 > 0:
        _monu_floor(sim, orient, bb, 0, 8, north.hasOpening[0])
        _monu_floor(sim, orient, bb, 0, 0, south.hasOpening[0])
    if south.connections[1] is None:
        sim.on_fill_box(bb, orient, 1, 4, 1, 6, 4, 7, _MONU_GRAY)
    if north.connections[1] is None:
        sim.on_fill_box(bb, orient, 1, 4, 8, 6, 4, 14, _MONU_GRAY)
    sim.box(bb, orient, 0, 3, 0, 0, 3, 15, _MONU_LIGHT)
    sim.box(bb, orient, 7, 3, 0, 7, 3, 15, _MONU_LIGHT)
    sim.box(bb, orient, 1, 3, 0, 7, 3, 0, _MONU_LIGHT)
    sim.box(bb, orient, 1, 3, 15, 6, 3, 15, _MONU_LIGHT)
    sim.box(bb, orient, 0, 2, 0, 0, 2, 15, _MONU_GRAY)
    sim.box(bb, orient, 7, 2, 0, 7, 2, 15, _MONU_GRAY)
    sim.box(bb, orient, 1, 2, 0, 7, 2, 0, _MONU_GRAY)
    sim.box(bb, orient, 1, 2, 15, 6, 2, 15, _MONU_GRAY)
    sim.box(bb, orient, 0, 1, 0, 0, 1, 15, _MONU_LIGHT)
    sim.box(bb, orient, 7, 1, 0, 7, 1, 15, _MONU_LIGHT)
    sim.box(bb, orient, 1, 1, 0, 7, 1, 0, _MONU_LIGHT)
    sim.box(bb, orient, 1, 1, 15, 6, 1, 15, _MONU_LIGHT)
    for x0, z0 in ((1, 1), (6, 1), (1, 13), (6, 13)):
        sim.box(bb, orient, x0, 1, z0, x0, 1, z0 + 1, _MONU_LIGHT)
        sim.box(bb, orient, x0, 3, z0, x0, 3, z0 + 1, _MONU_LIGHT)
    for x0, z0 in ((2, 6), (5, 6), (2, 9), (5, 9)):
        sim.box(bb, orient, x0, 1, z0, x0, 3, z0, _MONU_LIGHT)
    sim.box(bb, orient, 3, 2, 6, 4, 2, 6, _MONU_LIGHT)
    sim.box(bb, orient, 3, 2, 9, 4, 2, 9, _MONU_LIGHT)
    sim.box(bb, orient, 2, 2, 7, 2, 2, 8, _MONU_LIGHT)
    sim.box(bb, orient, 5, 2, 7, 5, 2, 8, _MONU_LIGHT)
    for x0, z0 in ((2, 5), (5, 5), (2, 10), (5, 10)):
        sim.one(bb, orient, x0, 2, z0, _MONU_LAMP)
    for x0, z0 in ((2, 5), (5, 5), (2, 10), (5, 10)):
        sim.one(bb, orient, x0, 3, z0, _MONU_LIGHT)
    if south.hasOpening[3]:
        sim.water_box(bb, orient, 3, 1, 0, 4, 2, 0)
    if south.hasOpening[5]:
        sim.water_box(bb, orient, 7, 1, 3, 7, 2, 4)
    if south.hasOpening[4]:
        sim.water_box(bb, orient, 0, 1, 3, 0, 2, 4)
    if north.hasOpening[2]:
        sim.water_box(bb, orient, 3, 1, 15, 4, 2, 15)
    if north.hasOpening[4]:
        sim.water_box(bb, orient, 0, 1, 11, 0, 2, 12)
    if north.hasOpening[5]:
        sim.water_box(bb, orient, 7, 1, 11, 7, 2, 12)


def _monu_post_top(sim, orient, bb, d):
    """OceanMonumentSimpleTopRoom（L1772-1818；湿海绵段俯视不可见，省略）。"""
    if d.index // 25 > 0:
        _monu_floor(sim, orient, bb, 0, 0, d.hasOpening[0])
    if d.connections[1] is None:
        sim.on_fill_box(bb, orient, 1, 4, 1, 6, 4, 6, _MONU_GRAY)
    sim.box(bb, orient, 0, 1, 0, 0, 1, 7, _MONU_LIGHT)
    sim.box(bb, orient, 7, 1, 0, 7, 1, 7, _MONU_LIGHT)
    sim.box(bb, orient, 1, 1, 0, 6, 1, 0, _MONU_LIGHT)
    sim.box(bb, orient, 1, 1, 7, 6, 1, 7, _MONU_LIGHT)
    sim.box(bb, orient, 0, 2, 0, 0, 2, 7, _MONU_BLACK)
    sim.box(bb, orient, 7, 2, 0, 7, 2, 7, _MONU_BLACK)
    sim.box(bb, orient, 1, 2, 0, 6, 2, 0, _MONU_BLACK)
    sim.box(bb, orient, 1, 2, 7, 6, 2, 7, _MONU_BLACK)
    sim.box(bb, orient, 0, 3, 0, 0, 3, 7, _MONU_LIGHT)
    sim.box(bb, orient, 7, 3, 0, 7, 3, 7, _MONU_LIGHT)
    sim.box(bb, orient, 1, 3, 0, 6, 3, 0, _MONU_LIGHT)
    sim.box(bb, orient, 1, 3, 7, 6, 3, 7, _MONU_LIGHT)
    sim.box(bb, orient, 0, 1, 3, 0, 2, 4, _MONU_BLACK)
    sim.box(bb, orient, 7, 1, 3, 7, 2, 4, _MONU_BLACK)
    sim.box(bb, orient, 3, 1, 0, 4, 2, 0, _MONU_BLACK)
    sim.box(bb, orient, 3, 1, 7, 4, 2, 7, _MONU_BLACK)
    if d.hasOpening[3]:
        sim.water_box(bb, orient, 3, 1, 0, 4, 2, 0)


def _monu_post_simple(sim, orient, bb, meta):
    """OceanMonumentSimpleRoom（L1598-1759；centerPillar 俯视被盖，省略）。"""
    d, main_design = meta
    if d.index // 25 > 0:
        _monu_floor(sim, orient, bb, 0, 0, d.hasOpening[0])
    if d.connections[1] is None:
        sim.on_fill_box(bb, orient, 1, 4, 1, 6, 4, 6, _MONU_GRAY)
    if main_design == 0:
        for x0, z0 in ((0, 0), (5, 0), (0, 5), (5, 5)):
            sim.box(bb, orient, x0, 1, z0, x0 + 2, 1, z0 + 2, _MONU_LIGHT)
            sim.box(bb, orient, x0, 3, z0, x0 + 2, 3, z0 + 2, _MONU_LIGHT)
        sim.box(bb, orient, 0, 2, 0, 0, 2, 2, _MONU_GRAY)
        sim.box(bb, orient, 1, 2, 0, 2, 2, 0, _MONU_GRAY)
        sim.one(bb, orient, 1, 2, 1, _MONU_LAMP)
        sim.box(bb, orient, 7, 2, 0, 7, 2, 2, _MONU_GRAY)
        sim.box(bb, orient, 5, 2, 0, 6, 2, 0, _MONU_GRAY)
        sim.one(bb, orient, 6, 2, 1, _MONU_LAMP)
        sim.box(bb, orient, 0, 2, 5, 0, 2, 7, _MONU_GRAY)
        sim.box(bb, orient, 1, 2, 7, 2, 2, 7, _MONU_GRAY)
        sim.one(bb, orient, 1, 2, 6, _MONU_LAMP)
        sim.box(bb, orient, 7, 2, 5, 7, 2, 7, _MONU_GRAY)
        sim.box(bb, orient, 5, 2, 7, 6, 2, 7, _MONU_GRAY)
        sim.one(bb, orient, 6, 2, 6, _MONU_LAMP)
        if d.hasOpening[3]:
            sim.box(bb, orient, 3, 3, 0, 4, 3, 0, _MONU_LIGHT)
        else:
            sim.box(bb, orient, 3, 3, 0, 4, 3, 1, _MONU_LIGHT)
            sim.box(bb, orient, 3, 2, 0, 4, 2, 0, _MONU_GRAY)
            sim.box(bb, orient, 3, 1, 0, 4, 1, 1, _MONU_LIGHT)
        if d.hasOpening[2]:
            sim.box(bb, orient, 3, 3, 7, 4, 3, 7, _MONU_LIGHT)
        else:
            sim.box(bb, orient, 3, 3, 6, 4, 3, 7, _MONU_LIGHT)
            sim.box(bb, orient, 3, 2, 7, 4, 2, 7, _MONU_GRAY)
            sim.box(bb, orient, 3, 1, 6, 4, 1, 7, _MONU_LIGHT)
        if d.hasOpening[4]:
            sim.box(bb, orient, 0, 3, 3, 0, 3, 4, _MONU_LIGHT)
        else:
            sim.box(bb, orient, 0, 3, 3, 1, 3, 4, _MONU_LIGHT)
            sim.box(bb, orient, 0, 2, 3, 0, 2, 4, _MONU_GRAY)
            sim.box(bb, orient, 0, 1, 3, 1, 1, 4, _MONU_LIGHT)
        if d.hasOpening[5]:
            sim.box(bb, orient, 7, 3, 3, 7, 3, 4, _MONU_LIGHT)
        else:
            sim.box(bb, orient, 6, 3, 3, 7, 3, 4, _MONU_LIGHT)
            sim.box(bb, orient, 7, 2, 3, 7, 2, 4, _MONU_GRAY)
            sim.box(bb, orient, 6, 1, 3, 7, 1, 4, _MONU_LIGHT)
    elif main_design == 1:
        for x0, z0 in ((2, 2), (2, 5), (5, 5), (5, 2)):
            sim.box(bb, orient, x0, 1, z0, x0, 3, z0, _MONU_LIGHT)
            sim.one(bb, orient, x0, 2, z0, _MONU_LAMP)
        for x0, z0, x1, z1 in ((0, 0, 1, 0), (0, 1, 0, 1),
                               (0, 7, 1, 7), (0, 6, 0, 6),
                               (6, 7, 7, 7), (7, 6, 7, 6),
                               (6, 0, 7, 0), (7, 1, 7, 1)):
            sim.box(bb, orient, x0, 1, z0, x1, 3, z1, _MONU_LIGHT)
        for x0, z0 in ((1, 0), (0, 1), (1, 7), (0, 6),
                       (6, 7), (7, 6), (6, 0), (7, 1)):
            sim.one(bb, orient, x0, 2, z0, _MONU_GRAY)
        if not d.hasOpening[3]:
            sim.box(bb, orient, 1, 3, 0, 6, 3, 0, _MONU_LIGHT)
            sim.box(bb, orient, 1, 2, 0, 6, 2, 0, _MONU_GRAY)
            sim.box(bb, orient, 1, 1, 0, 6, 1, 0, _MONU_LIGHT)
        if not d.hasOpening[2]:
            sim.box(bb, orient, 1, 3, 7, 6, 3, 7, _MONU_LIGHT)
            sim.box(bb, orient, 1, 2, 7, 6, 2, 7, _MONU_GRAY)
            sim.box(bb, orient, 1, 1, 7, 6, 1, 7, _MONU_LIGHT)
        if not d.hasOpening[4]:
            sim.box(bb, orient, 0, 3, 1, 0, 3, 6, _MONU_LIGHT)
            sim.box(bb, orient, 0, 2, 1, 0, 2, 6, _MONU_GRAY)
            sim.box(bb, orient, 0, 1, 1, 0, 1, 6, _MONU_LIGHT)
        if not d.hasOpening[5]:
            sim.box(bb, orient, 7, 3, 1, 7, 3, 6, _MONU_LIGHT)
            sim.box(bb, orient, 7, 2, 1, 7, 2, 6, _MONU_GRAY)
            sim.box(bb, orient, 7, 1, 1, 7, 1, 6, _MONU_LIGHT)
    else:
        sim.box(bb, orient, 0, 1, 0, 0, 1, 7, _MONU_LIGHT)
        sim.box(bb, orient, 7, 1, 0, 7, 1, 7, _MONU_LIGHT)
        sim.box(bb, orient, 1, 1, 0, 6, 1, 0, _MONU_LIGHT)
        sim.box(bb, orient, 1, 1, 7, 6, 1, 7, _MONU_LIGHT)
        sim.box(bb, orient, 0, 2, 0, 0, 2, 7, _MONU_BLACK)
        sim.box(bb, orient, 7, 2, 0, 7, 2, 7, _MONU_BLACK)
        sim.box(bb, orient, 1, 2, 0, 6, 2, 0, _MONU_BLACK)
        sim.box(bb, orient, 1, 2, 7, 6, 2, 7, _MONU_BLACK)
        sim.box(bb, orient, 0, 3, 0, 0, 3, 7, _MONU_LIGHT)
        sim.box(bb, orient, 7, 3, 0, 7, 3, 7, _MONU_LIGHT)
        sim.box(bb, orient, 1, 3, 0, 6, 3, 0, _MONU_LIGHT)
        sim.box(bb, orient, 1, 3, 7, 6, 3, 7, _MONU_LIGHT)
        sim.box(bb, orient, 0, 1, 3, 0, 2, 4, _MONU_BLACK)
        sim.box(bb, orient, 7, 1, 3, 7, 2, 4, _MONU_BLACK)
        sim.box(bb, orient, 3, 1, 0, 4, 2, 0, _MONU_BLACK)
        sim.box(bb, orient, 3, 1, 7, 4, 2, 7, _MONU_BLACK)
        if d.hasOpening[3]:
            sim.water_box(bb, orient, 3, 1, 0, 4, 2, 0)
        if d.hasOpening[2]:
            sim.water_box(bb, orient, 3, 1, 7, 4, 2, 7)
        if d.hasOpening[4]:
            sim.water_box(bb, orient, 0, 1, 3, 0, 2, 4)
        if d.hasOpening[5]:
            sim.water_box(bb, orient, 7, 1, 3, 7, 2, 4)


def _monu_post_wing(sim, orient, bb, main_design):
    """OceanMonumentWingRoom（L1834-1930）。"""
    if main_design == 0:
        for i in range(4):
            sim.box(bb, orient, 10 - i, 3 - i, 20 - i, 12 + i, 3 - i, 20,
                    _MONU_LIGHT)
        sim.box(bb, orient, 7, 0, 6, 15, 0, 16, _MONU_LIGHT)
        sim.box(bb, orient, 6, 0, 6, 6, 3, 20, _MONU_LIGHT)
        sim.box(bb, orient, 16, 0, 6, 16, 3, 20, _MONU_LIGHT)
        sim.box(bb, orient, 7, 1, 7, 7, 1, 20, _MONU_LIGHT)
        sim.box(bb, orient, 15, 1, 7, 15, 1, 20, _MONU_LIGHT)
        sim.box(bb, orient, 7, 1, 6, 9, 3, 6, _MONU_LIGHT)
        sim.box(bb, orient, 13, 1, 6, 15, 3, 6, _MONU_LIGHT)
        sim.box(bb, orient, 8, 1, 7, 9, 1, 7, _MONU_LIGHT)
        sim.box(bb, orient, 13, 1, 7, 14, 1, 7, _MONU_LIGHT)
        sim.box(bb, orient, 9, 0, 5, 13, 0, 5, _MONU_LIGHT)
        sim.box(bb, orient, 10, 0, 7, 12, 0, 7, _MONU_BLACK)
        sim.box(bb, orient, 8, 0, 10, 8, 0, 12, _MONU_BLACK)
        sim.box(bb, orient, 14, 0, 10, 14, 0, 12, _MONU_BLACK)
        for z in range(18, 6, -3):
            sim.one(bb, orient, 6, 3, z, _MONU_LAMP)
            sim.one(bb, orient, 16, 3, z, _MONU_LAMP)
        for x0, z0 in ((10, 10), (12, 10), (10, 12), (12, 12),
                       (8, 6), (14, 6)):
            sim.one(bb, orient, x0, 0, z0, _MONU_LAMP)
        for x0, z0 in ((4, 4), (18, 4), (4, 18), (18, 18)):
            sim.one(bb, orient, x0, 2, z0, _MONU_LIGHT)
            sim.one(bb, orient, x0, 1, z0, _MONU_LAMP)
            sim.one(bb, orient, x0, 0, z0, _MONU_LIGHT)
        sim.one(bb, orient, 9, 7, 20, _MONU_LIGHT)
        sim.one(bb, orient, 13, 7, 20, _MONU_LIGHT)
        sim.box(bb, orient, 6, 0, 21, 7, 4, 21, _MONU_LIGHT)
        sim.box(bb, orient, 15, 0, 21, 16, 4, 21, _MONU_LIGHT)
    else:
        sim.box(bb, orient, 9, 3, 18, 13, 3, 20, _MONU_LIGHT)
        sim.box(bb, orient, 9, 0, 18, 9, 2, 18, _MONU_LIGHT)
        sim.box(bb, orient, 13, 0, 18, 13, 2, 18, _MONU_LIGHT)
        x = 9
        for _ in range(2):
            sim.one(bb, orient, x, 6, 20, _MONU_LIGHT)
            sim.one(bb, orient, x, 5, 20, _MONU_LAMP)
            sim.one(bb, orient, x, 4, 20, _MONU_LIGHT)
            x = 13
        sim.box(bb, orient, 7, 3, 7, 15, 3, 14, _MONU_LIGHT)
        for x0 in (10, 12):
            sim.box(bb, orient, x0, 0, 10, x0, 6, 10, _MONU_LIGHT)
            sim.box(bb, orient, x0, 0, 12, x0, 6, 12, _MONU_LIGHT)
            sim.one(bb, orient, x0, 0, 10, _MONU_LAMP)
            sim.one(bb, orient, x0, 0, 12, _MONU_LAMP)
            sim.one(bb, orient, x0, 4, 10, _MONU_LAMP)
            sim.one(bb, orient, x0, 4, 12, _MONU_LAMP)
        for x0 in (8, 14):
            sim.box(bb, orient, x0, 0, 7, x0, 2, 7, _MONU_LIGHT)
            sim.box(bb, orient, x0, 0, 14, x0, 2, 14, _MONU_LIGHT)
        sim.box(bb, orient, 8, 3, 8, 8, 3, 13, _MONU_BLACK)
        sim.box(bb, orient, 14, 3, 8, 14, 3, 13, _MONU_BLACK)


def _monu_post_pent(sim, orient, bb, meta):
    """OceanMonumentPenthouse（L1366-1416）。"""
    sim.box(bb, orient, 2, -1, 2, 11, -1, 11, _MONU_LIGHT)
    sim.box(bb, orient, 0, -1, 0, 1, -1, 11, _MONU_GRAY)
    sim.box(bb, orient, 12, -1, 0, 13, -1, 11, _MONU_GRAY)
    sim.box(bb, orient, 2, -1, 0, 11, -1, 1, _MONU_GRAY)
    sim.box(bb, orient, 2, -1, 12, 11, -1, 13, _MONU_GRAY)
    sim.box(bb, orient, 0, 0, 0, 0, 0, 13, _MONU_LIGHT)
    sim.box(bb, orient, 13, 0, 0, 13, 0, 13, _MONU_LIGHT)
    sim.box(bb, orient, 1, 0, 0, 12, 0, 0, _MONU_LIGHT)
    sim.box(bb, orient, 1, 0, 13, 12, 0, 13, _MONU_LIGHT)
    for i in range(2, 12, 3):
        sim.one(bb, orient, 0, 0, i, _MONU_LAMP)
        sim.one(bb, orient, 13, 0, i, _MONU_LAMP)
        sim.one(bb, orient, i, 0, 0, _MONU_LAMP)
    sim.box(bb, orient, 2, 0, 3, 4, 0, 9, _MONU_LIGHT)
    sim.box(bb, orient, 9, 0, 3, 11, 0, 9, _MONU_LIGHT)
    sim.box(bb, orient, 4, 0, 9, 9, 0, 11, _MONU_LIGHT)
    sim.one(bb, orient, 5, 0, 8, _MONU_LIGHT)
    sim.one(bb, orient, 8, 0, 8, _MONU_LIGHT)
    sim.one(bb, orient, 10, 0, 10, _MONU_LIGHT)
    sim.one(bb, orient, 3, 0, 10, _MONU_LIGHT)
    sim.box(bb, orient, 3, 0, 3, 3, 0, 7, _MONU_BLACK)
    sim.box(bb, orient, 10, 0, 3, 10, 0, 7, _MONU_BLACK)
    sim.box(bb, orient, 6, 0, 10, 7, 0, 10, _MONU_BLACK)
    for x in (3, 10):
        for z in range(2, 9, 3):
            sim.box(bb, orient, x, 0, z, x, 2, z, _MONU_LIGHT)
    sim.box(bb, orient, 5, 0, 10, 5, 2, 10, _MONU_LIGHT)
    sim.box(bb, orient, 8, 0, 10, 8, 2, 10, _MONU_LIGHT)
    sim.box(bb, orient, 6, -1, 7, 7, -1, 8, _MONU_BLACK)
    sim.water_box(bb, orient, 6, -1, 3, 7, -1, 4)


_MONU_POST = {
    "entry": _monu_post_entry,
    "core": _monu_post_core,
    "dx": _monu_post_dx,
    "dxy": _monu_post_dxy,
    "dy": _monu_post_dy,
    "dyz": _monu_post_dyz,
    "dz": _monu_post_dz,
    "top": _monu_post_top,
    "simple": _monu_post_simple,
    "wing": lambda sim, orient, bb, md: _monu_post_wing(sim, orient, bb, md),
    "pent": _monu_post_pent,
}


def ocean_monument_blocks(seed: int, ax: int, az: int, pack: dict,
                          threads: int = 1):
    """海底神殿真实块 -> ([(x, y, z, "minecraft:xxx")...], caps)。

    ax/az = 结构锚点（区块角 16 对齐，enumerate_structures 的 x/z）。
    MonumentBuilding west/north = chunkMin - 29（OceanMonumentStructure
    L45-46）；y 基准固定 39（L183）。caps = {(wx, wz): cap}：水盒清除
    带的海床压低（heights[col] = min(heights[col], cap)，空腔列渲染
    深水、结构列由真实块竞争）。
    """
    from Utils.Public import structure_map as _smap
    from Utils.SeedReverser import mc_random as _mcr
    if _native is None:
        return None
    ctx = (pack or {}).get("ctx")
    if ctx is None:
        return None
    cx, cz = ax >> 4, az >> 4
    state = _smap.chunk_generate_rnd(seed, cx, cz)
    r, state = _mcr.next_int(state, 4)          # getRandomDirection L47
    orient = _MONU_HOR[r]
    west, north = ax - 29, az - 29
    bb = (west, 39, north, west + 57, 61, north + 57)
    (room_defs, source_room, core_room), state = _monu_room_graph(state)
    children, state = _monu_fit_children(orient, room_defs, source_room,
                                         core_room, state)
    # L209-213：子 piece bbox 统一 move(getWorldPos(9, 0, 22))
    offx = _monu_wx(bb, orient, 9, 22)
    offz = _monu_wz(bb, orient, 9, 22)
    moved = []
    for kind, b, meta in children:
        moved.append((kind, (b[0] + offx, b[1] + 39, b[2] + offz,
                             b[3] + offx, b[4] + 39, b[5] + offz), meta))
    # L218-221：wings + penthouse（bbox 已是世界坐标，不再 move）
    state = _mcr.next_state(state)              # wingRandom = nextInt()
    wing_random = state >> 16                   # next(32) 无界
    moved.append(("wing",
                  _monu_from_corners(bb, orient, (1, 1, 1), (23, 8, 21)),
                  wing_random & 1))
    moved.append(("wing",
                  _monu_from_corners(bb, orient, (34, 1, 1), (56, 8, 21)),
                  (wing_random + 1) & 1))
    moved.append(("pent",
                  _monu_from_corners(bb, orient, (22, 13, 22),
                                     (35, 17, 35)), None))
    sim = _MonuSim(ctx, threads)
    sim.prefetch(west - 6, north - 6, 70)
    _monu_post_building(sim, orient, bb, moved)
    return sim.top_blocks(), sim.caps
