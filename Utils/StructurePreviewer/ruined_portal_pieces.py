# -*- coding: utf-8 -*-
"""StructurePreviewer：废弃传送门 / 埋藏的宝藏（ruined_portal / buried_treasure）。

考证基准：1.21.11-Fabric jar 反编译（Vineflower 1.12.0 + 官方
client_mappings.txt 符号还原，反编译件 .temp/decomp/readable2/）：
- fid = RuinedPortalStructure：setups 权重选择 / air_pocket 概率 /
  giant 门 / 模板抽取 / rotation / mirror / findSuitableY；
- fic = RuinedPortalPiece：placeInWorld + 菱形土堆（b L139-173）+
  底层支撑柱（a L116-125）+ vines（a L95-108）+ overgrown 叶
  （b L110-114）；VerticalPlacement 枚举（fic.b L236-242）=
  a:on_land_surface / b:partly_buried / c:on_ocean_floor /
  d:in_mountain / e:underground / f:in_nether；
- fhh = BuriedTreasurePiece：OCEAN_FLOOR 地表向下扫描（下方为
  sandstone/stone/andesite/granite/diorite 即放箱，L18-48）+
  周围液体清填（全程无 RNG）+ createChest（ffs 6 参版，1 nextLong）；
- fhi = BuriedTreasureStructure：piece pos = (minBlockX+9, 90,
  minBlockZ+9)（fhi L19，与 structure_map._enum_treasure_well 锚点
  cx*16+9 同口径）；
- ffs = StructurePiece：getRandomDirection = Plane.HORIZONTAL
  faces[N,E,S,W][nextInt(4)]（L51-53）；createChest = 1 nextLong +
  state=null 自动朝向（L297-339 无 RNG）。

RNG 双流（与 igloo/pyramid 口径一致）：
- setup 流 = chunk_generate_rnd（Legacy LCG 重建）。铁证：ffo.java
  GenerationContext 构造 `WorldgenRandom(LegacyRandomSource(0L))
  .setLargeFeatureSeed(seed, cx, cz)`（evp.c 公式与
  chunk_generate_rnd 逐行一致）。消耗序（fid.a L41-94）：
    1. setups.size()>1 时权重判定 1 nextFloat（standard/mountain
       各两 setup 各 weight 0.5，逐项减 weight/sum，<0 选定；
       fid L45-63。单 setup 变体无此消耗）；
    2. air_pocket 概率判定：仅 0<p<1 时 1 nextFloat（p=0.0 直接
       false、p=1.0 直接 true，fid L104-110）；
    3. giant 门 nextFloat<0.05 -> 模板 nextInt(3)，
       否则 nextInt(10)（fid L76-80，两次判定共 1 nextFloat +
       1 nextInt）；
    4. rotation = Util.getRandom(values, rand) = nextInt(4)
       （fid L83；egm 枚举序 NONE/CW90/CW180/CCW90）；
    5. mirror：nextFloat<0.5 -> FRONT_BACK else NONE（fid L84；
       eev 枚举序 a=NONE b=LEFT_RIGHT c=FRONT_BACK，取 c）；
    6. findSuitableY（fid L116-158）按 placement：
       - in_nether(f)：airPocket ? nextBetween(32,100)
         : (nextFloat<0.5 ? nextBetween(27,29) : nextBetween(29,100))
         ——主世界 UI 不出现，防御分支直接 64；
       - in_mountain(d)：a(rand, 70, 64-h)（fid L160-162：lo<hi 才
         nextBetweenInclusive；平坦下 64-h<=47<70 恒无消耗）；
       - underground(e)：a(rand, -49, 64-h)（lo = getMinY()+15 =
         -64+15 = -49；平坦恒 1 nextInt）；
       - partly_buried(b)：nextBetween(2, 8)，y = 64-h+off；
       - on_land_surface(a)/on_ocean_floor(c)：无消耗，y = 64
         （$$4 = getBaseHeight(...)-1，OCEAN_FLOOR/WORLD_SURFACE
         平坦口径同 64；ocean 变体 heightmap 用 OCEAN_FLOOR 但
         findSuitableY 的 y 取 surface 分支，无额外 RNG）。
       四角向下扫描（L143-157）平坦地形恒首格命中返回初始值，
       无 RNG。y 依赖真实地形（getBaseHeight/噪声柱），平坦预览
       以 surface=64 代入，消耗序列与选择结构忠实照抄。
- postProcess 流（Xoroshiro128++）= population_seed(anchor 区块)
  + decorator + 10000*step（loot_rng salt 表：ruined_portal 各变体
  step=4、decorator standard=10/desert=11/jungle=12/mountain=13/
  ocean=15/swamp=16；buried_treasure step=3、decorator 0）：
  - 模板 placeInWorld 容器抽取：fjq L233 每 RandomizableContainer
    1 nextLong；ruined 每模板恰 1 箱 -> 流首个 nextLong =
    LootTableSeed（单 piece 无前置消耗，与 pyramid 的 createChest
    直接连抽同口径）；
  - buried_treasure：找地表/清液体全程无 RNG（fhh L18-48）-> 流
    首个 nextLong = 箱子 seed（与 loot_seed_for_chest skips=0 等价）。

变体群系映射（1.21.11 biome tag 展开，.temp/rp_tags_out.txt；
structures JSON 数组序 = standard, desert, jungle, swamp, mountain,
ocean, nether，第一个 tag 命中者胜出；全不命中时 fallback standard
——cubiomes 地图层对 ruined_portal 恒标 viable，与 Java 全 tag
判定存在已知偏差，见 structure_map.check_structure_at 注释）。

显示（模板 13 个已就位 assets/SeedReverser/templates/ruined_portal__*.nbt，
尺寸/箱子局部坐标/朝向码经 NBT 统计核对，.temp/rp_tpl_out.txt）：
- 块变换 t(l) = rot(mirror(l))：mirror FRONT_BACK 为 x' = 2*px - x
  （fjq transform；LEFT_RIGHT 翻 z 而 fic 只产 FRONT_BACK）；rot 绕
  pivot（sx//2, 0, sz//2）的 CW90=(-z,x)/CW180=(-x,-z)/CCW90=(z,-x)，
  pivot 恒不动，与 shipwreck _rotate_voxels 的 R_raw 同向；形状码
  先 shape_mirror(FRONT_BACK) 后 shape_rotation；
- postProcess 修饰（土堆/支撑柱/藤/叶）与箱子同一条 postProcess 流
  （箱子 seed 先取，后续修饰消耗不影响箱子），按平坦口径模拟：
  - 菱形土堆（fic L139-173）：off = nextInt(max(1, 8-(spanX+spanZ)//4))
    （$$8=(xSpan+zSpan)/2 一次整除、$$8/2 二次整除）；x 外层 z 内层
    遍历中心 ±14，dist=max(0, |dx|+|dz|+off)<14 时 nextDouble<W[14 项
    权重表] -> 目标 y = surface 类 placement 恒 64、其余
    min(bb.minY, 64)（|y-bb.minY|<=3 平坦恒过，fic L161）；
    现位非空气/非黑曜石/非熔岩（体素 dict 判定）-> 填
    netherrack（cold 变体不出 magma：nextFloat<0.07 判定仅非 cold
    消耗，fic L181）-> overgrown 时上方 nextFloat<0.5 且现为
    netherrack 且上方空 -> persistent jungle leaves -> 下方悬空
    延伸（起点填 + while nextFloat<0.5 move down 填，<=8 格）；
  - 底层支撑柱（fic L116-125）：bb 底层内部 (x1+1..x2-1,
    minZ+1..maxZ-1) 现 netherrack 者向下延伸（同 c()）；
  - vines/overgrown（fic L78-88）：bb 全格 betweenClosed 序
    （x 最快、y 中、z 最慢）遍历：vines 变体非空气非藤格
    nextInt(4)（faces[N,E,S,W]）选水平向，邻位空气（支撑面判定
    简化为恒可挂）-> 邻位放 vine:<opposite>；overgrown 变体每格
    恒 1 nextFloat<0.5 且现 netherrack 且上方空 -> 上方放
    persistent jungle leaves。
- 已知妥协：
  - 土堆/支撑柱的地表采样平坦口径恒 64，形状与真实地形下不同
    （RNG 消耗序列自洽，箱子 seed 不受影响——箱子在模板
    placeInWorld 内先行抽取）；
  - vines 支撑面判定简化为"邻位空气即可挂"（真实按
    getBlockSupport 完整判定）；
  - buried_treasure 真实 y 依赖地形（OCEAN_FLOOR 向下扫到"下方为
    岩类"的第一格，沙层厚度不可从种子预测），平坦口径画地表下
    一格 + 其下 3x3 sandstone 示意，箱子 LootTableSeed 与真实
    游戏严格一致（找地表无 RNG）；
  - buried_treasure 箱子朝向按"四周全埋"的 createChest fallback
    链（NORTH 被占->SOUTH->WEST->EAST，ffs L321-336）取 EAST，
    真实朝向随地形开口变化（无 RNG，预览不可判）。
"""
from __future__ import annotations

import os
from functools import lru_cache

from Utils.SeedReverser import block_shapes as bs
from Utils.SeedReverser import structure_models
from . import loot_rng

# --------------------------------------------------------------- 材质键
NETHERRACK = "netherrack"
MAGMA = "magma block"
LAVA = "lava"
OBSIDIAN = "obsidian"
GOLD_BLOCK = "block of gold"
IRON_BARS = "iron bars"
STONE = "stone"
STONE_BRICKS = "stone bricks"
JUNGLE_LEAVES = "jungle leaves"
SAND = "sand"
SANDSTONE = "sandstone"
CHEST = "chest"                       # chest:<f>:single 形状元组
VINE = "vine"                         # vine:<dir>

# 13 个模板统计（size=(sx,sy,sz)、chest 局部坐标 + 朝向码；
# .temp/rp_tpl_out.txt NBT 逐项核对，键 = 模板名后缀）
_RP_TPL = {
    "portal_1":        (6, 9, 6,  2, 2, 0, "w"),
    "portal_2":        (9, 12, 9, 8, 2, 6, "e"),
    "portal_3":        (8, 8, 9,  3, 3, 6, "w"),
    "portal_4":        (8, 7, 9,  3, 3, 2, "w"),
    "portal_5":        (10, 9, 7, 4, 3, 2, "s"),
    "portal_6":        (5, 7, 7,  1, 1, 4, "w"),
    "portal_7":        (9, 7, 9,  0, 1, 2, "w"),
    "portal_8":        (14, 9, 9, 4, 4, 2, "w"),
    "portal_9":        (10, 8, 9, 4, 1, 0, "w"),
    "portal_10":       (12, 6, 10, 2, 1, 7, "w"),
    "giant_portal_1":  (11, 17, 16, 4, 3, 3, "w"),
    "giant_portal_2":  (11, 16, 16, 9, 1, 9, "e"),
    "giant_portal_3":  (16, 16, 16, 9, 2, 3, "s"),
}

# 6 主世界变体 setup 表（1.21.11 jar structure/ruined_portal*.json 原文
# ——.temp/rp_extract_out.txt；字段 (placement, air_pocket_prob,
# mossiness, overgrown, vines, can_be_cold, replace_with_blackstone,
# weight)；nether 变体在下界维度，主世界 UI 不收录）
_SETUPS = {
    "ruined_portal": (
        ("underground", 1.0, 0.2, False, False, True, False, 0.5),
        ("on_land_surface", 0.5, 0.2, False, False, True, False, 0.5),
    ),
    "ruined_portal_desert": (
        ("partly_buried", 0.0, 0.0, False, False, False, False, 1.0),
    ),
    "ruined_portal_jungle": (
        ("on_land_surface", 0.5, 0.8, True, True, False, False, 1.0),
    ),
    "ruined_portal_swamp": (
        ("on_ocean_floor", 0.0, 0.5, False, True, True, False, 1.0),
    ),
    "ruined_portal_mountain": (
        ("in_mountain", 1.0, 0.2, False, False, True, False, 0.5),
        ("on_land_surface", 0.5, 0.2, False, False, True, False, 0.5),
    ),
    "ruined_portal_ocean": (
        ("on_ocean_floor", 0.0, 0.8, False, False, True, False, 1.0),
    ),
}

# 变体群系映射（1.21.11 biome tag 展开；cubiomes 群系 id；
# 数组序 = structures JSON 序，第一个命中者胜出）
_VARIANT_ORDER = ("ruined_portal", "ruined_portal_desert",
                  "ruined_portal_jungle", "ruined_portal_swamp",
                  "ruined_portal_mountain", "ruined_portal_ocean")
_VARIANT_BIOMES = {
    "ruined_portal": frozenset({
        1,    # plains
        12,   # snowy_plains
        129,  # sunflower_plains
        14,   # mushroom_fields
        140,  # ice_spikes
        174,  # dripstone_caves
        175,  # lush_caves
        35,   # savanna
        4, 132, 27, 155, 29, 186,        # forest 系 + pale_garden
        5, 30, 32, 160,                  # taiga 系
        7, 11,                           # river 系
        16, 26,                          # beach 系
        178,                             # grove
    }),
    "ruined_portal_desert": frozenset({2}),                       # desert
    "ruined_portal_jungle": frozenset({21, 23, 168}),             # jungle 系
    "ruined_portal_swamp": frozenset({6, 184}),                   # swamp 系
    "ruined_portal_mountain": frozenset({
        37, 165, 38,   # badlands 系
        3, 34, 131,    # windswept_hills 系
        36, 163,       # savanna_plateau / windswept_savanna
        25,            # stony_shore
        177, 181, 180, 182, 179, 185,  # meadow/peaks/slopes/cherry
    }),
    "ruined_portal_ocean": frozenset({
        0, 10, 24, 44, 45, 46, 47, 48, 49, 50,   # 全部海洋（OCEANIC 同集）
    }),
}


def variant_for_biome(biome_id: int) -> str:
    """锚点群系 id -> 变体结构键（tag 数组序首个命中；全不命中
    fallback standard——与 cubiomes 地图恒 viable 口径对齐）。"""
    for key in _VARIANT_ORDER:
        if biome_id in _VARIANT_BIOMES[key]:
            return key
    return "ruined_portal"


# 权重表（fic L144 原文 14 项）
_PILE_WEIGHTS = (1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0,
                 0.9, 0.9, 0.8, 0.7, 0.6, 0.4, 0.2)

# 水平方向（fid/ffs faces 序：Plane.HORIZONTAL = [N,E,S,W]；
# step 向量 = Direction.getStepX/getStepZ）
_HORIZONTAL = ("n", "e", "s", "w")
_DIR_VEC = {"n": (0, -1), "e": (1, 0), "s": (0, 1), "w": (-1, 0)}
_OPPOSITE = {"n": "s", "s": "n", "e": "w", "w": "e"}


@lru_cache(maxsize=16)
def _load_template(fname: str) -> dict:
    """模板 NBT -> 体素 dict（局部坐标；lru 缓存只读共享）。"""
    return structure_models._voxels_from_template_file(
        os.path.join(structure_models.TEMPLATE_DIR,
                     "ruined_portal__%s.nbt" % fname))


def _next_between(lo: int, hi: int):
    """Mth.randomBetweenInclusive + fid a(rand,lo,hi)（lo<hi 才消耗）。

    返回 (值, 或 None 表示无消耗——调用方用 fallback 值)。
    """
    # 由 _RPSim 内联实现（需要 state 推进），此函数仅作文档锚点。
    raise NotImplementedError


class _RPSim:
    """废弃传送门单 piece 模拟（setup 流 + postProcess 流 + 体素）。"""

    def __init__(self, world_seed: int, ax: int, az: int,
                 variant_key: str) -> None:
        self.voxels: dict = {}        # (世界x, 世界y, 世界z) -> 值
        self.chests: list = []        # (wx, wz, y_world, table, seed)
        self.ax = ax
        self.az = az
        self.variant = variant_key

        # ---------------- setup 流（Legacy LCG） ----------------
        from Utils.Public import structure_map
        state = structure_map.chunk_generate_rnd(world_seed, ax >> 4,
                                                 az >> 4)
        from Utils.SeedReverser import mc_random
        setups = _SETUPS[variant_key]
        if len(setups) > 1:                       # fid L45-63 权重判定
            f, state = mc_random.next_float(state)
            acc = f
            setup = setups[-1]
            for s in setups:
                acc -= s[7]                       # weight（sum=1）
                if acc < 0.0:
                    setup = s
                    break
        else:
            setup = setups[0]
        (self.placement, p_air, self.mossiness, self.overgrown,
         self.vines, self.cold, self.blackstone, _w) = setup
        if p_air == 0.0:                          # fid L104-110
            self.air_pocket = False
        elif p_air == 1.0:
            self.air_pocket = True
        else:
            f, state = mc_random.next_float(state)
            self.air_pocket = f < p_air
        f, state = mc_random.next_float(state)    # giant 门
        if f < 0.05:
            gi, state = mc_random.next_int(state, 3)
            self.giant = True
            tpl_name = "giant_portal_%d" % (gi + 1)
        else:
            ti, state = mc_random.next_int(state, 10)
            self.giant = False
            tpl_name = "portal_%d" % (ti + 1)
        self.template = "ruined_portal/" + tpl_name
        self.rot, state = mc_random.next_int(state, 4)      # rotation
        mf, state = mc_random.next_float(state)
        self.mirror_fb = mf < 0.5                           # FRONT_BACK

        self.sx, self.sy, self.sz, clx, cly, clz, cface = _RP_TPL[tpl_name]
        self.px = self.sx // 2
        self.pz = self.sz // 2

        # ---------------- findSuitableY（平坦口径） ----------------
        surface = 64                 # getBaseHeight(type)-1 平坦基准
        if self.placement == "in_nether":
            self.y0 = surface        # 主世界不出现，防御分支
        elif self.placement == "in_mountain":
            hi = surface - self.sy
            if 70 < hi:
                yv, state = mc_random.next_int(state, hi - 70 + 1)
                self.y0 = yv + 70
            else:
                self.y0 = hi
        elif self.placement == "underground":
            lo, hi = -49, surface - self.sy    # getMinY()+15 = -49
            yv, state = mc_random.next_int(state, hi - lo + 1)
            self.y0 = yv + lo
        elif self.placement == "partly_buried":
            off, state = mc_random.next_int(state, 7)
            self.y0 = surface - self.sy + off + 2
        else:   # on_land_surface / on_ocean_floor
            self.y0 = surface

        # ---------------- postProcess 流（Xoroshiro） ----------------
        step, decorator = loot_rng.salt_configs_for_version(
            "1.21")[variant_key]
        pop = loot_rng.get_population_seed(world_seed, ax, az)
        self.rng = loot_rng.XoroshiroJava(
            (pop + decorator + 10000 * step) & loot_rng._M64)

        # 模板 placeInWorld（fjq：容器各 1 nextLong；单箱 = 首个）
        chest_seed = self.rng.next_long()
        self._place_template(chest_seed, (clx, cly, clz))
        # 修饰：菱形土堆 -> 底层支撑柱 -> vines/overgrown 叶
        # （fic L76-88 语句序；注意 b(菱形) 在 a(支撑柱) 之前）
        self._mound()
        self._support()
        self._decor()

    # -- 变换（fjq transform：先 mirror 后 rotate，pivot 恒不动） --

    def _t(self, lx: int, ly: int, lz: int):
        if self.mirror_fb:
            lx = 2 * self.px - lx
        rx, rz = lx - self.px, lz - self.pz
        if self.rot == 1:                     # CLOCKWISE_90 (-z,x)
            rx, rz = -rz, rx
        elif self.rot == 2:                   # CLOCKWISE_180
            rx, rz = -rx, -rz
        elif self.rot == 3:                   # COUNTERCLOCKWISE_90
            rx, rz = rz, -rx
        return rx + self.px, ly, rz + self.pz

    def _put(self, wx: int, wy: int, wz: int, val) -> None:
        """世界坐标写体素（val=None 挖空）。"""
        if val is None:
            self.voxels.pop((wx, wy, wz), None)
        else:
            self.voxels[(wx, wy, wz)] = val

    def _get(self, wx: int, wy: int, wz: int):
        return self.voxels.get((wx, wy, wz))

    def _place_template(self, chest_seed: int,
                        chest_local: tuple) -> None:
        """模板 NBT -> mirror/rot 变换 -> 世界体素（以 y0 贴到 piece）。"""
        vox = _load_template(self.template.split("/", 1)[1])
        for (lx, ly, lz), mat in vox.items():
            tx, ty, tz = self._t(lx, ly, lz)
            if isinstance(mat, tuple):
                base, shape = mat
                if self.mirror_fb:
                    shape = bs.shape_mirror(shape, "FRONT_BACK")
                shape = bs.shape_rotation(shape, self.rot)
                mat = (base, shape) if shape else base
            self.voxels[(self.ax + tx, self.y0 + ty,
                         self.az + tz)] = mat
        # 箱子（模板内恰 1 个）：世界坐标与 LootTableSeed
        tx, ty, tz = self._t(*chest_local)
        wx, wy, wz = self.ax + tx, self.y0 + ty, self.az + tz
        self._put(wx, wy, wz, (CHEST, "chest:%s:single"
                               % self._face_of(chest_local[5] if False
                                               else _RP_TPL[
                                                   self.template.split(
                                                       "/", 1)[1]][6])))
        self.chests.append((wx, wz, wy, "chests/ruined_portal",
                            chest_seed))

    def _face_of(self, local: str) -> str:
        """局部水平朝向 -> 世界朝向（mirror+rotate 净变换）。"""
        if self.mirror_fb:
            local = {"e": "w", "w": "e"}.get(local, local)
        mp = ("nnnn", "nesw", "nsne", "nwns")[self.rot]
        # rot 表（与 bs.shape_rotation 同）：1:n->e 2:n->s 3:n->w
        table = {0: {"n": "n", "e": "e", "s": "s", "w": "w"},
                 1: {"n": "e", "e": "s", "s": "w", "w": "n"},
                 2: {"n": "s", "e": "w", "s": "n", "w": "e"},
                 3: {"n": "w", "e": "n", "s": "e", "w": "s"}}[self.rot]
        return table[local]

    # -- 修饰（fic postProcess L76-88，平坦口径） ----------------

    def _bb(self):
        """变换后 bb（世界口径，y 不随 rot/mirror）。"""
        corners = [self._t(0, 0, 0), self._t(self.sx - 1, 0, 0),
                   self._t(0, 0, self.sz - 1),
                   self._t(self.sx - 1, 0, self.sz - 1)]
        xs = [c[0] for c in corners]
        zs = [c[2] for c in corners]
        return (self.ax + min(xs), self.az + min(zs),
                self.ax + max(xs), self.az + max(zs))

    def _fill(self, wx: int, wy: int, wz: int) -> None:
        """fic d()：cold 变体恒 netherrack（0 消耗）；否则
        nextFloat<0.07 -> magma。"""
        if not self.cold:
            if self.rng.next_float() < 0.07:
                self._put(wx, wy, wz, MAGMA)
                return
        self._put(wx, wy, wz, NETHERRACK)

    def _extend_down(self, wx: int, wy: int, wz: int) -> None:
        """fic c()：起点填 + while nextFloat<0.5 向下延伸（<=8 格）。"""
        self._fill(wx, wy, wz)
        n = 8
        while n > 0 and self.rng.next_float() < 0.5:
            wy -= 1
            n -= 1
            self._fill(wx, wy, wz)

    def _leaves(self, wx: int, wy: int, wz: int) -> None:
        """fic b(bgr,dwp,is)（三参）：1 nextFloat<0.5 且现 netherrack
        且上方空 -> 上方放 persistent jungle leaves。"""
        if self.rng.next_float() < 0.5 \
                and self._get(wx, wy, wz) == NETHERRACK \
                and self._get(wx, wy + 1, wz) is None:
            self._put(wx, wy + 1, wz, JUNGLE_LEAVES)

    def _mound(self) -> None:
        """fic b(bgr,dwp)（L139-173）菱形 netherrack 土堆（平坦口径：
        地表采样恒 64；a() 判定用体素 dict——非空且非黑曜石/熔岩）。"""
        bb0x, bb0z, bb1x, bb1z = self._bb()
        cx = bb0x + (bb1x - bb0x + 1) // 2       # BoundingBox.getCenter
        cz = bb0z + (bb1z - bb0z + 1) // 2
        span2 = ((bb1x - bb0x + 1) + (bb1z - bb0z + 1)) // 2
        self.pile_off = self.rng.next_int(max(1, 8 - span2 // 2))
        surface_like = self.placement in ("on_land_surface",
                                          "on_ocean_floor")
        target = 64 if surface_like else min(self.y0, 64)
        for dx in range(-14, 15):                # x 外层 z 内层
            for dz in range(-14, 15):
                dist = max(0, abs(dx) + abs(dz) + self.pile_off)
                if dist >= 14:
                    continue
                if self.rng.next_double() >= _PILE_WEIGHTS[dist]:
                    continue
                wx, wz = cx + dx, cz + dz
                cur = self._get(wx, target, wz)
                if cur is not None and cur in (OBSIDIAN, LAVA):
                    continue                     # a() 判定不过
                self._fill(wx, target, wz)
                if self.overgrown:
                    self._leaves(wx, target, wz)
                self._extend_down(wx, target - 1, wz)

    def _support(self) -> None:
        """fic a(bgr,dwp)（L116-125）bb 底层内部 netherrack 向下延伸。"""
        bb0x, bb0z, bb1x, bb1z = self._bb()
        for wx in range(bb0x + 1, bb1x):
            for wz in range(bb0z + 1, bb1z):
                if self._get(wx, self.y0, wz) == NETHERRACK:
                    self._extend_down(wx, self.y0 - 1, wz)

    def _decor(self) -> None:
        """fic L78-88：bb 全格 betweenClosed 序（x 最快、y 中、z 最慢）
        vines 挂藤 / overgrown 放叶。"""
        if not (self.vines or self.overgrown):
            return
        bb0x, bb0z, bb1x, bb1z = self._bb()
        for wz in range(bb0z, bb1z + 1):
            for wy in range(self.y0, self.y0 + self.sy):
                for wx in range(bb0x, bb1x + 1):
                    cur = self._get(wx, wy, wz)
                    if self.vines:
                        # a(bgr,dwp,is)：非空气非藤 -> nextInt(4)
                        if cur is not None and cur != VINE \
                                and not (isinstance(cur, tuple)
                                         and cur[0] == VINE):
                            d = _HORIZONTAL[self.rng.next_int(4)]
                            nx, nz = _DIR_VEC[d]
                            if self._get(wx + nx, wy, wz + nz) is None:
                                self._put(wx + nx, wy, wz + nz,
                                          (VINE, "vine:"
                                           + _OPPOSITE[d]))
                    if self.overgrown:
                        self._leaves(wx, wy, wz)


class _BTSim:
    """埋藏的宝藏模拟（无 setup 流；postProcess 流首 nextLong）。"""

    def __init__(self, world_seed: int, ax: int, az: int) -> None:
        # ax/az = 区块角（minBlockX/Z）；锚点 (9, 9)（fhi L19）
        self.voxels: dict = {}
        self.chests: list = []
        step, decorator = loot_rng.salt_configs_for_version(
            "1.21")["buried_treasure"]
        pop = loot_rng.get_population_seed(world_seed, ax, az)
        rng = loot_rng.XoroshiroJava(
            (pop + decorator + 10000 * step) & loot_rng._M64)
        seed = rng.next_long()      # 找地表全程无 RNG（fhh L18-48）
        wx, wy, wz = ax + 9, 63, az + 9   # 地表下一格（平坦口径）
        # 示意覆盖：地表层 + 箱层沙 + 底层砂岩
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                self.voxels[(wx + dx, 64, wz + dz)] = SAND
                if (dx, dz) != (0, 0):
                    self.voxels[(wx + dx, 63, wz + dz)] = SAND
                self.voxels[(wx + dx, 62, wz + dz)] = SANDSTONE
        self.voxels[(wx, wy, wz)] = (CHEST, "chest:e:single")
        self.chests.append((wx, wz, wy, "chests/buried_treasure", seed))


# ---------------------------------------------------------------------------
# Composition 装配入口（composition.compose_display_model 调用）
# ---------------------------------------------------------------------------

def sim_ruined_portal(world_seed: int, ax: int, az: int,
                      biome_id: int) -> _RPSim:
    """变体选择 + 双流模拟（compose 与 display 共用，保证同源）。"""
    return _RPSim(world_seed, ax, az, variant_for_biome(biome_id))


def build_ruined_portal_voxels(comp) -> tuple[dict, set]:
    """Composition -> (体素 dict, 容器 (x,z) 相对偏移集合)。

    体素坐标 = 世界 - anchor（x/z）、世界 - 64（y）。重跑 _RPSim
    （与 compose 同一 RNG 序），容器 pos3 严格重合。
    """
    sim = _RPSim(comp.extra["world_seed"], comp.anchor[0],
                 comp.anchor[1], comp.variant_name)
    voxels = {(x - comp.anchor[0], y - 64, z - comp.anchor[1]): v
              for (x, y, z), v in sim.voxels.items()}
    chest_offs = {(wx - comp.anchor[0], wz - comp.anchor[1])
                  for (wx, wz, _y, _t, _sd) in sim.chests}
    return voxels, chest_offs


def build_buried_treasure_voxels(comp) -> tuple[dict, set]:
    """同上（埋藏的宝藏：沙 + 箱 + 砂岩示意覆盖）。"""
    sim = _BTSim(comp.extra["world_seed"], comp.anchor[0],
                 comp.anchor[1])
    voxels = {(x - comp.anchor[0], y - 64, z - comp.anchor[1]): v
              for (x, y, z), v in sim.voxels.items()}
    chest_offs = {(wx - comp.anchor[0], wz - comp.anchor[1])
                  for (wx, wz, _y, _t, _sd) in sim.chests}
    return voxels, chest_offs
