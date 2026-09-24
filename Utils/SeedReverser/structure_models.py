# -*- coding: utf-8 -*-
"""SeedReverser 结构 3D 模型构建（NBT 模板 / 蓝图挤出 / 程序化合成）。

M3 混合方案：结构键按来源分三类构建体素模型：
- NBT 模板（8 键）：1.21.jar 提取的官方结构模板
  （assets/SeedReverser/templates/*.nbt，gzip 压缩 NBT，自解析），
  palette 方块名经 _MAT_MAP 映射到 84 张真实方块纹理；
- 蓝图挤出（1 键）：structure_blueprints 的 top+tcol 逐格向上挤到
  高度值，palette 人话名归一化后直接作为纹理键（jungle_temple）；
- 程序化合成（5 键）：monument/swamp_hut/village/trial_chambers/
  desert_pyramid 按原版形体规则合成（monument 中央塔+四翼；
  swamp_hut 架空小屋；village 井+四屋拼装；trial 回字形大室；
  desert 按 wiki 逐层蓝图重建，含地下暗室/南面双塔/顶榵）；
- WorldEdit .schem（Sponge Schematic v2/v3，SCHEM_FILES 3 键）：
  游戏内真实提取的结构，文件存在时优先于程序化结果，
  缺失时回退程序化建模（village/monument/trial_chambers）。

统一输出：体素字典 {(x,y,z): mat}（x 西→东、z 北→南、y 向上，
(0,0,0) = 结构包围盒西北角 = cubiomes 生成锚点）。
体素值两种形态：
- 纯字符串 mat：整格方块（程序化示意体/蓝图挤出/兼容旧入口）；
- (mat, shape) 二元组：带形状码的非完整方块（半砖/楼梯/门/
  活板门/栅栏/墙/玻璃板/铁栏杆/链/火把/箱子/床等），
  shape 码语义与几何见 block_shapes（palette Properties 驱动）。

网格化 build_mesh：形状感知面剔除（形状占用查询）+ 同材质面聚
合为绘制槽，输出共享顶点缓冲 / 索引缓冲 / 槽区间表，供
structure_3dview 上传 GPU 一次构建、多次绘制；未知材质单独成槽
（视口回退灰色）。兼容半高 "halfheight:" 前缀（蓝图挤出侧）。
"""
import gzip
import math
import os
import random
import struct
import threading
from collections import deque

import numpy as np

from Utils.SeedReverser import block_shapes as bs
from Utils.SeedReverser import structure_blueprints as sb

# 1/16 像素步长（_decor_face_mat 盒身份判别用）
_E16 = 1.0 / 16.0

__all__ = [
    "UNKNOWN_MAT", "TEMPLATE_FILES", "VARIANT_FILES", "VARIANT_KEYS",
    "ANCHOR_CENTER_KEYS", "ANCHOR_OFFSETS", "EXTRUDE_KEYS",
    "SCHEM_FILES",
    "voxels_from_template", "build_voxels", "build_model", "model_size",
    "tex_keys_used",
]

# ---------------------------------------------------------------------------
# 资产路径：Utils/SeedReverser/ → 项目根 → assets/SeedReverser/
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
TEMPLATE_DIR = os.path.join(_ROOT, "assets", "SeedReverser", "templates")
TEX_DIR = os.path.join(_ROOT, "assets", "SeedReverser", "textures", "block")

# ---------------------------------------------------------------------------
# 结构键 -> 模型来源
# ---------------------------------------------------------------------------
# NBT 模板（assets/SeedReverser/templates/ 下文件名，"__" = 原路径分隔符）
TEMPLATE_FILES = {
    "igloo": ["igloo__top.nbt", "igloo__middle.nbt", "igloo__bottom.nbt"],
    "pillager_outpost": ["pillager_outpost__watchtower.nbt"],
    "ruined_portal": ["ruined_portal__portal_1.nbt"],
    "shipwreck": ["shipwreck__with_mast.nbt"],
    "ocean_ruin": ["underwater_ruin__big_warm_4.nbt"],
    "ocean_ruin_cold": ["underwater_ruin__big_brick_1.nbt"],
    "ancient_city": ["ancient_city__city_center__city_center_1.nbt"],
    "trail_ruins": ["trail_ruins__buildings__group_full_1.nbt"],
}
# 变种模板（同一结构键的多个官方模板，各自独立建模，3D 视口轮播）。
# 注意与 TEMPLATE_FILES 的“多文件拼接”语义不同：列表每项 = 单独模型。
VARIANT_FILES = {
    "ocean_ruin": [f"underwater_ruin__big_warm_{n}.nbt"
                   for n in (4, 5, 6, 7)]
                  + [f"underwater_ruin__{t}_{n}.nbt"
                     for t in ("warm", "brick", "cracked", "mossy")
                     for n in range(1, 9)]
                  + [f"underwater_ruin__big_{t}_{n}.nbt"
                     for t in ("brick", "cracked", "mossy")
                     for n in (1, 2, 3, 8)],
    "ocean_ruin_cold": [f"underwater_ruin__big_brick_{n}.nbt"
                        for n in (1, 2, 3, 8)],
    "ruined_portal": ["ruined_portal__portal_1.nbt"]
                     + [f"ruined_portal__portal_{n}.nbt"
                        for n in range(2, 11)]
                     + [f"ruined_portal__giant_portal_{n}.nbt"
                        for n in (1, 2, 3)],
    # 沉船 20 官方变种（含 degraded 降级模板）：顺序与
    # composition._SW_INFO 的 sw_typ 索引一一对应（beached 抽取
    # 索引 0/4..10/17..19 即得搁浅合法变种）；首项 with_mast =
    # TEMPLATE_FILES["shipwreck"] 默认模板（轮播从默认开始）。
    "shipwreck": [f"shipwreck__{v}.nbt" for v in (
        "with_mast",
        "upsidedown_full", "upsidedown_fronthalf", "upsidedown_backhalf",
        "sideways_full", "sideways_fronthalf", "sideways_backhalf",
        "rightsideup_full", "rightsideup_fronthalf", "rightsideup_backhalf",
        "with_mast_degraded", "upsidedown_full_degraded",
        "upsidedown_fronthalf_degraded", "upsidedown_backhalf_degraded",
        "sideways_full_degraded", "sideways_fronthalf_degraded",
        "sideways_backhalf_degraded", "rightsideup_full_degraded",
        "rightsideup_fronthalf_degraded", "rightsideup_backhalf_degraded",
    )],
}
VARIANT_KEYS = frozenset(VARIANT_FILES)
# 锚点标记画在结构中心的结构键（3D 视口红线柱位置）。
# wiki（Ocean Monument）：1.13+ 神殿“生成在区块角上”即结构中心，
# 正中央 4 个方块分属 4 个区块；其余结构锚点为包围盒西北角 (0,0)。
ANCHOR_CENTER_KEYS = frozenset({"monument"})
# 非中心锚点结构的锚点偏移（模型局部坐标，x 东/z 南，单位=方块）。
# 视口红线/区块网格按此平移；缺省 = (0,0) = 包围盒西北角。
# - village：模型局部坐标井柱簇（17 块水柱）形心 x=29.0/z=53.0，
#   红线/区块线直接用局部形心（与 trial_chambers 同口径）；
#   用户 GUI 对照：红线应落在井口。
ANCHOR_OFFSETS = {
    "village": (29.0, 53.0),
    "trial_chambers": (9.0, 35.4),
}
# 蓝图挤出（structure_blueprints.BLUEPRINTS 的 top+tcol）
EXTRUDE_KEYS = {"jungle_temple"}
# 程序化合成（_PROC_BUILDERS 分发表）
PROCEDURAL_KEYS = {"monument", "swamp_hut",
                   "trial_chambers", "village", "desert_pyramid"}
# WorldEdit 真实提取结构（assets/SeedReverser/schematics/*.schem，
# Sponge Schematic v2/v3）：文件存在时优先，缺失回退程序化建模。
SCHEM_DIR = os.path.join(_ROOT, "assets", "SeedReverser", "schematics")
SCHEM_FILES = {
    "village": "village.schem",
    "monument": "monument.schem",
    "trial_chambers": "trial_chambers.schem",
}
# 环境方块过滤清单：待用户确认后填入（拟过滤框选混入的石头/深板岩/
# 泥土/树叶/原木等）；空集 = 仅丢弃 _MAT_MAP=None 的方块（air/water）。
_SCHEM_ENV_FILTER: frozenset = frozenset()

UNKNOWN_MAT = "__unknown__"   # 未映射方块的回退材质（视口渲染灰色）

_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"

# ---------------------------------------------------------------------------
# NBT palette 方块名 -> 材质键。
# 材质键 = 纹理文件键（assets/SeedReverser/textures/block/<键>.png），
# "halfheight:" 前缀 = 半高块（台阶/楼梯）；
# None = 非实体/透明方块，构建时直接跳过；
# 未收录的方块名回退 UNKNOWN_MAT（视口渲染中性灰）。
# ---------------------------------------------------------------------------
_MAT_MAP = {
    # -- 石材 --
    "minecraft:stone": "stone",
    "minecraft:smooth_stone": "stone",
    "minecraft:bedrock": "bedrock",
    "minecraft:deepslate": "deepslate",
    # -- 下界黑石/玄武岩系（bastion 主体；basalt 端面经 _COL_ENDS、
    #    轴向经 shape_from_props col:<axis>，几何/分面联动）--
    "minecraft:blackstone": "blackstone",
    "minecraft:blackstone_slab": "halfheight:blackstone",
    "minecraft:blackstone_stairs": "halfheight:polished blackstone bricks",
    "minecraft:blackstone_wall": "blackstone",
    "minecraft:basalt": "basalt",
    "minecraft:polished_basalt": "polished basalt",
    "minecraft:coal_ore": "coal ore",
    "minecraft:iron_ore": "iron ore",
    "minecraft:spawner": "spawner",
    "minecraft:trial_spawner": "trial spawner side inactive",
    "minecraft:vault": "vault side off",
    "minecraft:ominous_vault": "ominous vault side off",
    "minecraft:sculk": "stone",
    "minecraft:sculk_catalyst": "stone",
    "minecraft:cobblestone": "cobblestone",
    "minecraft:mossy_cobblestone": "mossy cobblestone",
    "minecraft:mossy_cobblestone_slab": "halfheight:mossy cobblestone",
    "minecraft:cobbled_deepslate": "cobbled deepslate",
    "minecraft:stone_bricks": "stone bricks",
    "minecraft:infested_stone_bricks": "stone bricks",
    "minecraft:bricks": "stone bricks",
    "minecraft:polished_blackstone_bricks": "polished blackstone bricks",
    "minecraft:polished_deepslate": "polished deepslate",
    "minecraft:deepslate_bricks": "deepslate bricks",
    "minecraft:deepslate_tiles": "deepslate tiles",
    "minecraft:reinforced_deepslate": "reinforced deepslate",
    "minecraft:mossy_stone_bricks": "mossy stone bricks",
    "minecraft:infested_mossy_stone_bricks": "mossy stone bricks",
    "minecraft:cracked_stone_bricks": "cracked stone bricks",
    "minecraft:infested_cracked_stone_bricks": "cracked stone bricks",
    "minecraft:cracked_polished_blackstone_bricks":
        "cracked polished blackstone bricks",
    "minecraft:cracked_deepslate_bricks": "cracked deepslate bricks",
    "minecraft:cracked_deepslate_tiles": "cracked deepslate tiles",
    "minecraft:chiseled_stone_bricks": "chiseled stone bricks",
    "minecraft:chiseled_polished_blackstone":
        "chiseled polished blackstone",
    "minecraft:polished_blackstone": "polished blackstone",
    "minecraft:chiseled_deepslate": "chiseled deepslate",
    "minecraft:andesite": "polished andesite",
    "minecraft:polished_andesite": "polished andesite",
    "minecraft:diorite": "polished diorite",
    "minecraft:polished_diorite": "polished diorite",
    "minecraft:granite": "granite",
    "minecraft:polished_granite": "granite",
    # -- 石材楼梯/台阶（半高）/墙 --
    "minecraft:stone_brick_stairs": "halfheight:stone brick stairs",
    "minecraft:polished_blackstone_brick_stairs":
        "halfheight:polished blackstone bricks",
    "minecraft:deepslate_brick_stairs": "halfheight:deepslate bricks",
    "minecraft:deepslate_tile_stairs": "halfheight:deepslate tiles",
    "minecraft:stone_brick_slab": "halfheight:stone brick slab",
    "minecraft:polished_blackstone_brick_slab":
        "halfheight:polished blackstone bricks",
    "minecraft:deepslate_brick_slab": "halfheight:deepslate bricks",
    "minecraft:deepslate_tile_slab": "halfheight:deepslate tiles",
    "minecraft:stone_brick_wall": "stone bricks",
    "minecraft:mossy_stone_brick_wall": "mossy stone bricks",
    "minecraft:polished_blackstone_brick_wall":
        "polished blackstone bricks",
    "minecraft:deepslate_brick_wall": "deepslate bricks",
    "minecraft:deepslate_tile_wall": "deepslate tiles",
    "minecraft:cobblestone_stairs": "halfheight:cobblestone stairs",
    "minecraft:mossy_cobblestone_stairs":
        "halfheight:cobblestone stairs",
    "minecraft:cobblestone_wall": "cobblestone wall",
    "minecraft:mossy_cobblestone_wall": "cobblestone wall",
    # -- 土/砂 --
    "minecraft:obsidian": "obsidian",
    "minecraft:crying_obsidian": "obsidian",
    "minecraft:dirt": "dirt",
    "minecraft:coarse_dirt": "dirt",
    "minecraft:podzol": "podzol side",
    "minecraft:grass_block": "grass block side",
    "minecraft:dirt_path": "dirt path",
    "minecraft:farmland": "farmland",
    "minecraft:gravel": "gravel",
    "minecraft:suspicious_gravel": "gravel",
    "minecraft:sand": "sand",
    "minecraft:red_sand": "sand",
    "minecraft:suspicious_sand": "sand",
    "minecraft:sandstone": "sandstone",
    "minecraft:smooth_sandstone": "sandstone",
    "minecraft:red_sandstone": "sandstone",
    "minecraft:smooth_red_sandstone": "sandstone",
    "minecraft:chiseled_sandstone": "chiseled sandstone",
    "minecraft:cut_sandstone": "cut sandstone",
    "minecraft:sandstone_stairs": "halfheight:sandstone stairs",
    "minecraft:smooth_sandstone_stairs": "halfheight:sandstone stairs",
    "minecraft:sandstone_slab": "halfheight:sandstone slab",
    "minecraft:smooth_sandstone_slab": "halfheight:sandstone slab",
    "minecraft:cut_sandstone_slab": "halfheight:sandstone slab",
    "minecraft:sandstone_wall": "sandstone",
    # -- 木质 --
    "minecraft:oak_planks": "oak planks",
    "minecraft:spruce_planks": "spruce planks",
    "minecraft:dark_oak_planks": "dark oak planks",
    "minecraft:birch_planks": "birch planks",
    "minecraft:oak_log": "oak log",
    "minecraft:stripped_oak_log": "stripped oak log",
    "minecraft:stripped_oak_wood": "oak log",
    "minecraft:spruce_log": "spruce log",
    "minecraft:stripped_spruce_log": "stripped spruce log",
    "minecraft:stripped_spruce_wood": "spruce log",
    "minecraft:dark_oak_log": "dark oak log",
    "minecraft:stripped_dark_oak_log": "stripped dark oak log",
    "minecraft:oak_stairs": "halfheight:oak stairs",
    "minecraft:spruce_stairs": "halfheight:spruce stairs",
    "minecraft:dark_oak_stairs": "halfheight:dark oak stairs",
    "minecraft:birch_stairs": "halfheight:birch planks",
    "minecraft:oak_slab": "halfheight:oak slab",
    "minecraft:spruce_slab": "halfheight:spruce slab",
    "minecraft:dark_oak_slab": "halfheight:dark oak slab",
    "minecraft:oak_fence": "oak fence",
    "minecraft:spruce_fence": "spruce fence",
    "minecraft:dark_oak_fence": "dark oak fence",
    "minecraft:oak_trapdoor": "oak trapdoor",
    "minecraft:spruce_trapdoor": "spruce trapdoor",
    # 门：基键 = 下半块纹理；上半块在 _DOOR_PART_TEX 按形状码换
    "minecraft:oak_door": "oak door bottom",
    "minecraft:spruce_door": "spruce door bottom",
    "minecraft:ladder": "ladder",
    "minecraft:hay_block": "hay block side",
    "minecraft:pumpkin": "pumpkin side",
    "minecraft:carved_pumpkin": "carved pumpkin",
    "minecraft:bookshelf": "bookshelf",
    "minecraft:chiseled_bookshelf": "oak planks",
    "minecraft:lectern": "oak planks",
    "minecraft:composter": "composter side",
    "minecraft:loom": "oak planks",
    # -- 功能方块 --
    "minecraft:chest": "chest",
    "minecraft:trapped_chest": "trapped chest",
    # 末影箱（end_city third_floor_2 等模板内出现）：玩家存储方块，
    # 形状码由 block_shapes（name.endswith("chest") 分支）按 facing
    # 定向，纹理 ender chest*.png 三件套已就位
    "minecraft:ender_chest": "ender chest",
    "minecraft:barrel": "barrel",
    "minecraft:furnace": "furnace",
    "minecraft:blast_furnace": "blast furnace",
    "minecraft:smoker": "smoker",
    "minecraft:dispenser": "dispenser",
    "minecraft:dropper": "dispenser",
    "minecraft:crafting_table": "crafting table",
    "minecraft:brewing_stand": "brewing stand",
    "minecraft:dragon_wall_head": "dragon_head",
    "minecraft:dragon_head": "dragon_head",
    "minecraft:cauldron": "cauldron",
    "minecraft:water_cauldron": "cauldron",
    "minecraft:lava_cauldron": "cauldron",
    "minecraft:powder_snow_cauldron": "cauldron",
    "minecraft:tnt": "tnt",
    # 结构方块/jigsaw 为占位标记方块（jigsaw 拼装点/结构数据标记），
    # 世界生成时消耗不落地，非建筑实体，建模时直接剔除
    # （用户需求：删除所有模型中的结构方块）
    "minecraft:jigsaw": None,
    "minecraft:jigsaw_block": None,
    "minecraft:structure_block": None,
    "minecraft:torch": "torch",
    "minecraft:wall_torch": "torch",
    "minecraft:soul_torch": "soul torch",
    "minecraft:soul_wall_torch": "soul torch",
    "minecraft:lantern": "lantern",
    "minecraft:soul_lantern": "soul_lantern",
    "minecraft:sea_lantern": "sea lantern",
    "minecraft:redstone_torch": "redstone torch",
    "minecraft:redstone_wall_torch": "redstone torch",
    "minecraft:repeater": "repeater top",
    "minecraft:comparator": "comparator top",
    "minecraft:lever": "lever",
    "minecraft:tripwire": "tripwire",
    "minecraft:piston": "piston",
    "minecraft:sticky_piston": "sticky piston",
    "minecraft:piston_head": "piston",
    # -- 海底神殿 --
    "minecraft:prismarine": "prismarine",
    "minecraft:prismarine_bricks": "prismarine",
    "minecraft:dark_prismarine": "prismarine",
    "minecraft:prismarine_brick_stairs": "halfheight:prismarine",
    "minecraft:dark_prismarine_stairs": "halfheight:prismarine",
    "minecraft:prismarine_brick_slab": "halfheight:prismarine",
    "minecraft:dark_prismarine_slab": "halfheight:prismarine",
    "minecraft:prismarine_wall": "prismarine",
    "minecraft:wet_sponge": "sea lantern",   # 无海绵纹理，最近似发光块
    "minecraft:acacia_button": None,
    "minecraft:magma_block": "magma block",
    # -- 冰雪/金属/杂 --
    "minecraft:ice": "ice",
    "minecraft:packed_ice": "packed ice",
    "minecraft:blue_ice": "ice",
    "minecraft:snow_block": "snow block",
    "minecraft:gold_block": "block of gold",
    "minecraft:gilded_blackstone": "gilded blackstone",
    "minecraft:iron_bars": "iron bars",
    "minecraft:chain": "chain",
    "minecraft:cobweb": "cobweb",
    # -- 染色/装饰 --
    "minecraft:orange_terracotta": "orange terracotta",
    "minecraft:light_gray_terracotta": "orange terracotta",
    "minecraft:blue_terracotta": "blue terracotta",
    "minecraft:white_glazed_terracotta": "white carpet",
    "minecraft:decorated_pot": "orange terracotta",
    "minecraft:white_wool": "white carpet",
    "minecraft:white_carpet": "white carpet",
    "minecraft:red_carpet": "red carpet",
    "minecraft:light_gray_carpet": "light gray carpet",
    "minecraft:red_bed": "red bed",
    "minecraft:white_bed": "white bed",
    "minecraft:gray_banner": "ominous wall banner",
    "minecraft:gray_wall_banner": "ominous wall banner",
    "minecraft:white_wall_banner": "ominous wall banner",
    # 末地城横幅无图案（纯染色布），用同色羊毛纹理贴 panel
    "minecraft:magenta_wall_banner": "magenta_wool",
    "minecraft:ominous_banner": "ominous wall banner",
    "minecraft:potted_red_mushroom": "potted red mushroom",
    "minecraft:potted_cactus": "potted cactus",
    "minecraft:potted_fern": "potted cactus",
    "minecraft:potted_dead_bush": "potted cactus",
    "minecraft:flower_pot": "potted cactus",
    "minecraft:quartz_pillar": "quartz pillar",
    "minecraft:iron_block": "iron block",
    # -- 铜系（试炼密室，真实纹理）--
    "minecraft:copper_block": "copper block",
    "minecraft:exposed_copper": "copper block",
    "minecraft:weathered_copper": "cut copper",
    "minecraft:oxidized_copper": "oxidized copper",
    "minecraft:chiseled_copper": "cut copper",
    "minecraft:copper_grate": "copper grate",
    "minecraft:exposed_chiseled_copper": "cut copper",
    "minecraft:waxed_copper_block": "copper block",
    "minecraft:copper_bulb": "copper bulb",
    "minecraft:exposed_copper_bulb": "copper bulb",
    "minecraft:waxed_chiseled_copper": "cut copper",
    "minecraft:copper_door": "copper door bottom",
    "minecraft:waxed_copper_door": "copper door bottom",
    "minecraft:oxidized_copper_trapdoor": "oxidized copper trapdoor",
    "minecraft:copper_trapdoor": "copper grate",
    "minecraft:waxed_exposed_copper_bulb": "copper bulb",
    "minecraft:waxed_oxidized_copper_bulb": "copper bulb",
    "minecraft:waxed_weathered_copper_bulb": "copper bulb",
    "minecraft:waxed_cut_copper": "cut copper",
    "minecraft:waxed_cut_copper_slab": "halfheight:cut copper",
    "minecraft:waxed_oxidized_cut_copper_slab":
        "halfheight:oxidized cut copper",
    "minecraft:waxed_oxidized_cut_copper_stairs": "oxidized cut copper",
    "minecraft:waxed_copper_grate": "copper grate",
    "minecraft:waxed_oxidized_copper_grate": "copper grate",
    "minecraft:waxed_oxidized_copper_door": "copper door bottom",
    "minecraft:red_candle": "candle",
    # -- 藤蔓/招牌/压力板 --
    "minecraft:vine": "vines",
    "minecraft:glow_lichen": "vines",
    "minecraft:oak_sign": "oak wall sign",
    "minecraft:oak_wall_sign": "oak wall sign",
    "minecraft:spruce_sign": "oak wall sign",
    "minecraft:spruce_wall_sign": "oak wall sign",
    "minecraft:oak_hanging_sign": "oak wall sign",
    "minecraft:spruce_hanging_sign": "oak wall sign",
    "minecraft:stone_pressure_plate": "stone pressure plate",
    "minecraft:polished_blackstone_pressure_plate":
        "stone pressure plate",
    "minecraft:dark_oak_pressure_plate": "stone pressure plate",
    "minecraft:oak_pressure_plate": "stone pressure plate",
    # -- 远古城市（1.19+，真实纹理；2026-09 材质适配轮）--
    # 深板岩系补充（半高台阶/楼梯复用整块纹理，与 polished
    # blackstone 系同式）
    "minecraft:cobbled_deepslate_slab": "halfheight:cobbled deepslate",
    "minecraft:cobbled_deepslate_stairs": "halfheight:cobbled deepslate",
    "minecraft:cobbled_deepslate_wall": "cobbled deepslate",
    "minecraft:polished_deepslate_slab": "halfheight:polished deepslate",
    "minecraft:polished_deepslate_stairs": "halfheight:polished deepslate",
    "minecraft:smooth_basalt": "smooth basalt",
    # 幽匿系（原 stone 风格化 -> 真实幽匿纹理，只古城出现）
    "minecraft:sculk": "sculk",
    "minecraft:sculk_catalyst": "sculk catalyst side",
    "minecraft:sculk_sensor": "sculk sensor side",
    # 冰箱（ice_box_1）
    "minecraft:iron_trapdoor": "iron trapdoor",
    "minecraft:note_block": "note block",
    "minecraft:snow": "halfheight:snow",   # 雪层 1-6 层统一半高近似
    # 营地（camp_1/2/3）：lit 两种状态不区分（静态帧无火焰动画），
    # 统一熄灭原木纹理半高
    "minecraft:campfire": "halfheight:campfire log",
    # 营地装饰头颅（无独立 block 纹理，游戏用 entity 贴图；骨块
    # 半高近似）
    "minecraft:skeleton_skull": "halfheight:bone block",
    # 城市中心红石导线（官方 multipart redstone_dust_* 几何经
    # shape_from_props -> rswire 辐射臂；纹理 redstone wire.png =
    # 官方 1.21.11 line0/line1 灰度纹理按 egb COLORS[power=0] 染色
    # 合成，世界平铺 UV 命中线带；孤点态（全空）无 dot 斑，当前
    # 消费方全为连接态）
    "minecraft:redstone_wire": "redstone wire",
    # 三色羊毛/地毯（营地帐篷 + 路面装饰；wool/carpet 同色同键）
    "minecraft:blue_wool": "blue wool",
    "minecraft:blue_carpet": "blue wool",
    "minecraft:cyan_wool": "cyan wool",
    "minecraft:cyan_carpet": "cyan wool",
    "minecraft:light_blue_wool": "light blue wool",
    "minecraft:light_blue_carpet": "light blue wool",
    # -- 二轮补映射（模板实际出现、首轮遗漏）--
    "minecraft:glass_pane": "glass",
    "minecraft:glass": "glass",
    "minecraft:nether_portal": "nether portal",
    "minecraft:magenta_stained_glass": "magenta_stained_glass",
    "minecraft:iron_door": "iron door bottom",
    "minecraft:polished_deepslate_wall": "polished deepslate",
    "minecraft:mud_brick_stairs": "halfheight:orange terracotta",
    "minecraft:mud_brick_slab": "halfheight:orange terracotta",
    "minecraft:mud_bricks": "orange terracotta",
    "minecraft:cobblestone_slab": "halfheight:cobblestone slab",
    "minecraft:stone_slab": "halfheight:stone slab",
    "minecraft:redstone_lamp": "redstone lamp",
    "minecraft:infested_chiseled_stone_bricks": "chiseled stone bricks",
    "minecraft:netherrack": "netherrack",
    "minecraft:soul_sand": "soul sand",
    "minecraft:soul_fire": "soul fire",   # 城市中心灵魂火盆（透明十字火焰纹理，FS discard 镂空）
    "minecraft:brown_carpet": "light gray carpet",
    "minecraft:gray_carpet": "light gray carpet",
    "minecraft:gray_wool": "gray wool",   # 古城中心铺装 x31（真实灰羊毛）
    "minecraft:redstone_block": "redstone block",
    "minecraft:target": "target side",
    "minecraft:sculk_sensor": "sculk sensor side",
    "minecraft:tuff": "tuff",
    "minecraft:polished_tuff": "polished tuff",
    "minecraft:tuff_bricks": "tuff bricks",
    "minecraft:chiseled_tuff_bricks": "chiseled tuff bricks",
    "minecraft:chiseled_tuff": "tuff",
    "minecraft:polished_tuff_slab": "halfheight:polished tuff",
    "minecraft:polished_tuff_stairs": "halfheight:polished tuff",
    "minecraft:grindstone": "stone",
    "minecraft:oak_fence_gate": "oak fence",
    "minecraft:smooth_stone_slab": "halfheight:stone slab",
    "minecraft:green_carpet": "light gray carpet",
    "minecraft:dandelion": None,
    "minecraft:poppy": None,
    "minecraft:oxeye_daisy": None,
    "minecraft:azure_bluet": None,
    "minecraft:beetroots": None,
    "minecraft:waxed_oxidized_cut_copper": "oxidized cut copper",
    # -- 村庄（1.14+ jigsaw；2026-09 材质适配轮）--
    # 金合欢系（社区链路全量接入）
    "minecraft:acacia_planks": "acacia planks",
    "minecraft:acacia_log": "acacia log",
    "minecraft:acacia_wood": "acacia log",
    "minecraft:stripped_acacia_log": "stripped acacia log",
    "minecraft:acacia_slab": "halfheight:acacia planks",
    "minecraft:acacia_stairs": "halfheight:acacia planks",
    # 栅栏块模型 = planks 纹理（1.20+ 无独立 item 栅栏图；oak 先例除外）
    "minecraft:acacia_fence": "acacia planks",
    "minecraft:acacia_fence_gate": "acacia planks",
    "minecraft:acacia_pressure_plate": "acacia planks",
    "minecraft:acacia_door": "acacia door bottom",
    "minecraft:spruce_fence_gate": "spruce planks",
    "minecraft:spruce_pressure_plate": "spruce planks",
    "minecraft:acacia_sapling": "acacia sapling",
    "minecraft:jungle_door": "jungle door bottom",
    "minecraft:jungle_fence": "jungle planks",
    "minecraft:jungle_fence_gate": "jungle planks",
    "minecraft:jungle_trapdoor": "jungle trapdoor",
    "minecraft:jungle_button": None,
    # 砂土/粘土/仙人掌/瓜菜
    "minecraft:clay": "clay",
    "minecraft:cactus": "cactus side",
    "minecraft:melon": "melon side",
    "minecraft:melon_stem": "melon stem",
    "minecraft:pumpkin_stem": "pumpkin stem",
    # 作物（动态 age stage 优先，见 crop_stage_mat；此处为无 props
    # 管线的静态兑底 + 处理器输出路径）
    "minecraft:wheat": "wheat stage0",
    "minecraft:carrots": "carrots stage0",
    "minecraft:potatoes": "potatoes stage0",
    "minecraft:beetroots": "beetroots stage0",
    # 工作方块（side 基键 + _FULL_FACES 顶面）
    "minecraft:cartography_table": "cartography table side",
    "minecraft:fletching_table": "fletching table side",
    "minecraft:smithing_table": "smithing table side",
    "minecraft:stonecutter": "stonecutter side",
    # 陶瓦/羊毛/地毯/玻璃板
    "minecraft:terracotta": "terracotta",
    "minecraft:white_terracotta": "white terracotta",
    "minecraft:lime_terracotta": "lime terracotta",
    "minecraft:light_blue_glazed_terracotta": "light blue wool",
    "minecraft:lime_glazed_terracotta": "lime wool",
    "minecraft:orange_glazed_terracotta": "orange wool",
    "minecraft:yellow_glazed_terracotta": "yellow wool",
    "minecraft:light_gray_wool": "light gray wool",
    "minecraft:lime_wool": "lime wool",
    "minecraft:orange_wool": "orange wool",
    "minecraft:yellow_wool": "yellow wool",
    "minecraft:lime_carpet": "lime wool",
    "minecraft:orange_carpet": "orange wool",
    "minecraft:purple_carpet": "purple wool",
    "minecraft:yellow_carpet": "yellow wool",
    "minecraft:white_stained_glass_pane": "white stained glass",
    "minecraft:orange_stained_glass_pane": "orange stained glass",
    "minecraft:yellow_stained_glass_pane": "yellow stained glass",
    # 床（新色：毯区色相替换合成图；分面见 _decor_face_mat bed 分支）
    "minecraft:blue_bed": "blue bed",
    "minecraft:cyan_bed": "cyan bed",
    "minecraft:green_bed": "green bed",
    "minecraft:lime_bed": "lime bed",
    "minecraft:orange_bed": "orange bed",
    "minecraft:purple_bed": "purple bed",
    "minecraft:yellow_bed": "yellow bed",
    "minecraft:brown_wall_banner": "ominous wall banner",
    "minecraft:purple_glazed_terracotta": "purple wool",
    "minecraft:brown_bed": "brown bed",
    "minecraft:magenta_bed": "magenta bed",
    "minecraft:light_blue_terracotta": "light blue terracotta",
    "minecraft:potted_azure_bluet": "potted cactus",
    # -- mansion 遗留补齐（彩色羊毛/地毯装饰、白桦栏杆、深色橡木
    # 树苗/门/栅栏门、青金石块）--
    "minecraft:birch_fence": "birch planks",
    "minecraft:dark_oak_fence_gate": "dark oak planks",
    "minecraft:dark_oak_door": "dark oak door bottom",
    "minecraft:dark_oak_sapling": "dark oak sapling",
    "minecraft:black_wool": "black wool",
    "minecraft:green_wool": "green wool",
    "minecraft:brown_wool": "brown wool",
    "minecraft:red_wool": "red wool",
    "minecraft:black_carpet": "black wool",
    "minecraft:magenta_carpet": "magenta wool",
    "minecraft:pink_carpet": "pink wool",
    "minecraft:black_wall_banner": "ominous wall banner",
    "minecraft:potted_red_tulip": "potted cactus",
    "minecraft:potted_white_tulip": "potted cactus",
    "minecraft:potted_birch_sapling": "potted cactus",
    "minecraft:lapis_block": "block of lapis",
    # 盆栽（无独立纹理，花盆合成图近似，flower_pot 先例）
    "minecraft:potted_dandelion": "potted cactus",
    "minecraft:potted_poppy": "potted cactus",
    "minecraft:potted_spruce_sapling": "potted cactus",
    # 闪长岩/花岗岩（村庄桩饰；diorite 改用官方纹理更准）
    "minecraft:diorite_stairs": "halfheight:diorite",
    "minecraft:diorite_slab": "halfheight:diorite",
    "minecraft:diorite_wall": "diorite",
    "minecraft:granite_stairs": "halfheight:granite",
    "minecraft:granite_wall": "granite",
    "minecraft:spruce_wood": "spruce log",
    # -- 村庄渲染升级（原 None -> 十字/近似；作物/小花/钟）--
    "minecraft:wheat": "wheat stage4",
    "minecraft:poppy": "poppy",
    "minecraft:dandelion": "dandelion",
    "minecraft:oxeye_daisy": "oxeye daisy",
    "minecraft:short_grass": "short grass",
    "minecraft:tall_grass": "tall grass top",
    "minecraft:fern": "fern",
    "minecraft:large_fern": "large fern top",
    "minecraft:dead_bush": "dead bush",
    "minecraft:bell": "bell side",
    # -- 植物补遗（跨结构扫描：trial/red_mushroom 等漏网；藤菇/海泡
    # 菜均官方单图，十字渲染）--
    "minecraft:red_mushroom": "red mushroom",
    "minecraft:brown_mushroom": "brown mushroom",
    "minecraft:sea_pickle": "sea pickle",
    "minecraft:mangrove_roots": "mangrove roots",
    "minecraft:muddy_mangrove_roots": "muddy mangrove roots",
    "minecraft:mangrove_log": "mangrove log",
    "minecraft:mangrove_wood": "mangrove log",
    "minecraft:mud": "mud",
    "minecraft:white_concrete": "white concrete",
    "minecraft:tripwire_hook": "tripwire hook",
    "minecraft:potted_allium": "potted cactus",
    "minecraft:potted_blue_orchid": "potted cactus",
    "minecraft:potted_oxeye_daisy": "potted cactus",
    "minecraft:waxed_oxidized_copper": "oxidized copper",
    "minecraft:waxed_copper_bulb": "copper bulb",
    "minecraft:oxidized_cut_copper": "oxidized cut copper",
    # -- 三轮补映射（trial_chambers 模板遗漏，_map_block hook 实证
    #    481 格回退 UNKNOWN_MAT；waxed_* 官方共用未涂蜡纹理）--
    "minecraft:powder_snow": "powder snow",
    "minecraft:light_gray_stained_glass": "light gray stained glass",
    "minecraft:white_stained_glass": "white stained glass",
    "minecraft:black_stained_glass": "black stained glass",
    "minecraft:red_concrete": "red concrete",
    "minecraft:waxed_oxidized_copper_trapdoor": "oxidized copper trapdoor",
    "minecraft:waxed_cut_copper_stairs": "cut copper",
    "minecraft:waxed_oxidized_chiseled_copper": "oxidized chiseled copper",
    "minecraft:red_terracotta": "orange terracotta",
    "minecraft:yellow_terracotta": "orange terracotta",
    "minecraft:red_glazed_terracotta": "red carpet",
    # -- 非实体/透明/细杆：跳过 --
    "minecraft:air": None,
    "minecraft:cave_air": None,
    "minecraft:void_air": None,
    "minecraft:light": None,
    "minecraft:barrier": None,
    "minecraft:structure_void": None,
    "minecraft:moving_piston": None,
    # 水方圡保留材质键（视口半透明渲染）；air 仍跳过。
    "minecraft:water": "water",
    # 岩浆：不透明绘制（与水同格时在体素归一化处让位于水，见
    # build_mesh 上游 normalize；此处静态帧纹理）
    "minecraft:lava": "lava",
    "minecraft:bubble_column": None,
    "minecraft:seagrass": None,
    "minecraft:tall_seagrass": None,
    "minecraft:kelp": None,
    "minecraft:kelp_plant": None,
    # minecraft:sea_pickle：村庄沙漠水沟出现，键移至村庄段（十字）
    # -- 树叶（非完整方块感观：带透明孔纹理 + discard 镂空） --
    "minecraft:oak_leaves": "oak leaves",
    "minecraft:spruce_leaves": "spruce leaves",
    "minecraft:birch_leaves": "birch leaves",
    "minecraft:jungle_leaves": "jungle leaves",
    "minecraft:acacia_leaves": "acacia leaves",
    "minecraft:dark_oak_leaves": "dark oak leaves",
    "minecraft:mangrove_leaves": "mangrove leaves",
    "minecraft:cherry_leaves": "cherry leaves",
    "minecraft:pale_oak_leaves": "pale oak leaves",
    "minecraft:azalea_leaves": "azalea leaves",
    "minecraft:flowering_azalea_leaves": "flowering azalea leaves",
    "minecraft:grass": None,
    # minecraft:short_grass/tall_grass/fern/large_fern/dead_bush：
    # 村庄草皮/枯灌需渲染，键移至村庄段（SHAPE_CROSS 十字）
    "minecraft:sweet_berry_bush": None,
    # minecraft:red_mushroom/brown_mushroom/bell/wheat：同上移至村庄段
    # carrots/potatoes None 行删除（crop_stage_mat 动态 stage 接管）
    "minecraft:beetroot": None,
    "minecraft:moss_carpet": None,
    "minecraft:moss_block": None,
    "minecraft:sculk_vein": None,
    "minecraft:sculk_shrieker": None,
    # minecraft:redstone_wire：古城城市中心电路需渲染，键移至
    # 古城段（halfheight:redstone block 风格化近似）
    "minecraft:rail": None,
    "minecraft:powered_rail": None,
    "minecraft:detector_rail": None,
    "minecraft:activator_rail": None,
    "minecraft:oak_button": None,
    "minecraft:spruce_button": None,
    "minecraft:dark_oak_button": None,
    "minecraft:stone_button": None,
    # minecraft:skeleton_skull：古城营地头颅需渲染，键移至古城段
    #（halfheight:bone block 近似）
    "minecraft:skeleton_wall_skull": None,
    "minecraft:candle": "candle",
    "minecraft:white_candle": "candle",
    # minecraft:bell：村庄会心堂需渲染，键移至村庄段
    #（bell:floor/ceiling 真模型，分面见 _face_mat bell 分支）
    # minecraft:campfire：古城营地篝火需渲染，键移至古城段
    #（halfheight:campfire log，lit 两态不区分）
    "minecraft:soul_campfire": None,
    # -- 末地城紫颂石系（end city 模板主体；纹理已就位）--
    "minecraft:end_stone_bricks": "end_stone_bricks",
    "minecraft:purpur_block": "purpur_block",
    "minecraft:purpur_pillar": "purpur_pillar",
    "minecraft:purpur_pillar_top": "purpur_pillar_top",
    "minecraft:purpur_stairs": "halfheight:purpur_block",
    "minecraft:purpur_slab": "halfheight:purpur_block",
    # 堡垒桥台/试炼密室杂项（模板实际出现）
    "minecraft:glowstone": "glowstone",
    "minecraft:quartz_block": "quartz block",
    "minecraft:smooth_quartz": "smooth quartz",
    "minecraft:smooth_quartz_slab": "halfheight:smooth quartz",
    "minecraft:bone_block": "quartz block",
    "minecraft:fire": None,
    "minecraft:nether_wart": "nether wart",
    # 末地烛（官方 end_rod 模型 = 底座 2/16 + 立杆，bar:y 近似）
    "minecraft:end_rod": "end_rod",
}

# ==== PART2 ====

# ---------------------------------------------------------------------------
# NBT 解析（纯 Python，13 种标签，gzip 解压）
# ---------------------------------------------------------------------------
_TAG_END, _TAG_BYTE, _TAG_SHORT, _TAG_INT, _TAG_LONG = 0, 1, 2, 3, 4
_TAG_FLOAT, _TAG_DOUBLE, _TAG_BYTEARR, _TAG_STRING = 5, 6, 7, 8
_TAG_LIST, _TAG_COMPOUND, _TAG_INTARR, _TAG_LONGARR = 9, 10, 11, 12


def parse_nbt(data: bytes) -> dict:
    """解析 gzip 压缩的结构模板 NBT，返回 root compound（dict）。

    标签值用 (tag_type, python_value) 表示；compound 用 dict、
    list 用 (elem_type, [values])。未知标签抛 ValueError。
    """
    data = gzip.decompress(data)
    pos = 0
    if data[pos] != _TAG_COMPOUND:
        raise ValueError("NBT root 不是 TAG_Compound")
    pos += 1
    nl = struct.unpack_from(">H", data, pos)[0]
    pos += 2 + nl
    value, pos = _read_payload(data, pos, _TAG_COMPOUND)
    return value


def _read_payload(data: bytes, pos: int, tag: int):
    if tag == _TAG_BYTE:
        return struct.unpack_from(">b", data, pos)[0], pos + 1
    if tag == _TAG_SHORT:
        return struct.unpack_from(">h", data, pos)[0], pos + 2
    if tag == _TAG_INT:
        return struct.unpack_from(">i", data, pos)[0], pos + 4
    if tag == _TAG_LONG:
        return struct.unpack_from(">q", data, pos)[0], pos + 8
    if tag == _TAG_FLOAT:
        return struct.unpack_from(">f", data, pos)[0], pos + 4
    if tag == _TAG_DOUBLE:
        return struct.unpack_from(">d", data, pos)[0], pos + 8
    if tag == _TAG_BYTEARR:
        n = struct.unpack_from(">i", data, pos)[0]
        return data[pos + 4:pos + 4 + n], pos + 4 + n
    if tag == _TAG_STRING:
        n = struct.unpack_from(">H", data, pos)[0]
        s = data[pos + 2:pos + 2 + n].decode("utf-8", "replace")
        return s, pos + 2 + n
    if tag == _TAG_LIST:
        et = data[pos]
        n = struct.unpack_from(">i", data, pos + 1)[0]
        pos += 5
        items = []
        if et == _TAG_END:                       # 空列表（TAG_END 元素）
            return (et, items), pos
        for _ in range(max(0, n)):
            v, pos = _read_payload(data, pos, et)
            items.append(v)
        return (et, items), pos
    if tag == _TAG_COMPOUND:
        out = {}
        while True:
            t = data[pos]
            if t == _TAG_END:
                return out, pos + 1
            nl = struct.unpack_from(">H", data, pos + 1)[0]
            name = data[pos + 3:pos + 3 + nl].decode("utf-8", "replace")
            v, pos = _read_payload(data, pos + 3 + nl, t)
            out[name] = v
    if tag == _TAG_INTARR:
        n = struct.unpack_from(">i", data, pos)[0]
        vals = struct.unpack_from(f">{max(0, n)}i", data, pos + 4)
        return list(vals), pos + 4 + 4 * max(0, n)
    if tag == _TAG_LONGARR:
        n = struct.unpack_from(">i", data, pos)[0]
        vals = struct.unpack_from(f">{max(0, n)}q", data, pos + 4)
        return list(vals), pos + 4 + 8 * max(0, n)
    raise ValueError(f"未知 NBT 标签类型 {tag}")


def _palette_entry_name(entry) -> str:
    """palette 条目（dict，值为裸类型）-> 方块名。"""
    if isinstance(entry, dict):
        v = entry.get("Name", "")
        return v if isinstance(v, str) else ""
    return ""


def _palette_entry_half(entry) -> str:
    """palette 条目的 slab type 属性：'bottom'/'top'/'double'/''"""
    if isinstance(entry, dict):
        props = entry.get("Properties")
        if isinstance(props, dict):
            v = props.get("type", "")
            return v if isinstance(v, str) else ""
    return ""


def _voxels_from_template_file(path: str) -> dict:
    """单个模板 NBT -> 体素 dict（palette 方块名 -> _MAT_MAP 映射）。

    兼容两种格式：
    - 单 palette：root["palette"]（TAG_List of compound）；
    - 多 palette（随机变体，如沉船）：root["palettes"]（TAG_List of
      TAG_List），取第一个变体。
    """
    with open(path, "rb") as f:
        root = parse_nbt(f.read())
    palette_raw = root.get("palette")
    if palette_raw is None:
        palettes_raw = root.get("palettes")
        if palettes_raw and isinstance(palettes_raw, tuple):
            variants = palettes_raw[1]
            palette = variants[0][1] if variants else []
        else:
            palette = []
    else:
        palette = palette_raw[1]
    # palette 条目：{"Name": "minecraft:xxx", "Properties": {...}}（裸值）
    # 输出体素值：None 跳过 / (基材质, 形状码) 带形状 / 基材质 整格。
    # 旧 halfheight: 前缀在此归一化为形状码（top 半砖按官方几何
    # 画上半砖——旧逻辑误画整块）。
    mats = []
    for entry in palette:
        name = _palette_entry_name(entry)
        typ = _palette_entry_half(entry)
        mode = "full" if typ in ("top", "double") else "half"
        mat = _map_block(name, mode)
        if mat is None:
            mats.append(None)
            continue
        shape = bs.shape_from_props(name, _palette_entry_props(entry))
        half_prefix = isinstance(mat, str) \
            and mat.startswith("halfheight:")
        base = mat[len("halfheight:"):] if half_prefix else mat
        if shape is None and half_prefix and typ != "double":
            # 无 properties 形状的旧前缀材质（蓝图/历史映射）按底半格
            shape = bs.SHAPE_SLAB_BOT
        mats.append((base, shape) if shape is not None else base)
    blocks = root.get("blocks")
    if not blocks:
        return {}
    block_list = blocks[1] if isinstance(blocks, tuple) else blocks
    vox = {}
    for item in block_list:
        # pos 是 TAG_List -> (elem_type, [x, y, z])；state 是 TAG_Int 裸值
        pos_raw = item.get("pos")
        pos = pos_raw[1] if isinstance(pos_raw, tuple) else pos_raw
        st = item.get("state", 0)
        if not isinstance(pos, list) or len(pos) != 3:
            continue
        x, y, z = pos
        mat = mats[st] if 0 <= st < len(mats) else UNKNOWN_MAT
        if mat is None:
            continue
        vox[(x, y, z)] = mat
    return vox


def _palette_entry_props(entry) -> dict:
    """palette 条目的 Properties 属性 dict（无则空 dict）。"""
    if isinstance(entry, dict):
        props = entry.get("Properties")
        if isinstance(props, dict):
            return props
    return {}


# 作物生长阶段（官方 blockstates age->stage 模型映射，1.21.11 jar
# 提取；SHAPE_CROSS 十字渲染，纹理键 = 前缀 + stage 序号）。
# carrots/potatoes 四阶段纹理对 age 0..7 折叠（0,1->0 / 2,3->1 /
# 4,5,6->2 / 7->3）；beetroots 1.21.11 有四张纹理一对一。
_CROP_STAGES = {
    "minecraft:wheat": ("wheat stage", (0, 1, 2, 3, 4, 5, 6, 7)),
    "minecraft:carrots": ("carrots stage", (0, 0, 1, 1, 2, 2, 2, 3)),
    "minecraft:potatoes": ("potatoes stage", (0, 0, 1, 1, 2, 2, 2, 3)),
    "minecraft:beetroots": ("beetroots stage", (0, 1, 2, 3)),
}


def crop_stage_mat(name: str, props: dict | None) -> str | None:
    """作物方块 -> 按 age 属性的动态纹理键（非作物返回 None）。

    age 缺省按 0（zombie 处理器输出 age=0 的成熟前状态）；越界按
    最后一档钳制。调用方优先于 _map_block 静态映射。
    """
    cfg = _CROP_STAGES.get(name)
    if cfg is None:
        return None
    try:
        age = int((props or {}).get("age", "0"))
    except (TypeError, ValueError):
        age = 0
    stages = cfg[1]
    return cfg[0] + str(stages[min(max(age, 0), len(stages) - 1)])


def _map_block(name: str, mode: str) -> str | None:
    """NBT 方块名 -> 材质键。

    mode="full"：台阶为上半/双层，按整块（去 halfheight: 前缀）；
    mode="half"：保持映射原样（bottom 台阶保留半高标记）。
    """
    mat = _MAT_MAP.get(name, UNKNOWN_MAT)
    if mode == "full" and isinstance(mat, str) and mat.startswith(
            "halfheight:"):
        return mat[len("halfheight:"):]
    return mat


# ---------------------------------------------------------------------------
# WorldEdit .schem（Sponge Schematic v2/v3）解析
# ---------------------------------------------------------------------------
def _schem_base_and_type(name: str) -> tuple:
    """palette 名 "minecraft:xxx[k=v,...]" -> (基名, props dict)。"""
    base, _, props = name.partition("[")
    d = {}
    if props:
        for kv in props.rstrip("]").split(","):
            k, _, v = kv.partition("=")
            if k:
                d[k] = v
    return base, d


def _read_schem_varint(data: bytes, pos: int) -> tuple:
    """Sponge BlockData varint：1..3 字节小端 7 位组，最大 21 位。

    负值(-1)按 21 位补码全 1 解出（0x1FFFFF），不可能是合法
    palette 索引，经 names 查表自然跳过，无需特判。
    """
    value = 0
    for i in range(3):
        if pos >= len(data):
            raise ValueError("BlockData 截断")
        b = data[pos]
        pos += 1
        value |= (b & 0x7F) << (7 * i)
        if not (b & 0x80):
            break
    return value, pos


def _voxels_from_schem_file(path: str) -> dict:
    """Sponge Schematic (.schem) -> 体素 dict，重定基到结构包围盒西北角。

    - v2：根（或 root["Schematic"]）平铺 BlockData/Palette 字段；
    - v3：root["Schematic"]["Blocks"] 内收纳 Data/Palette
      （WorldEdit 7.4 实测导出布局，两代均兼容）；
    - 方块数据为 YZX 顺序 varint palette 索引（外层 y、内层 x）；
    - _MAT_MAP=None（air/water 等）与 _SCHEM_ENV_FILTER 命名方块
      不保留，也不参与包围盒计算；
    - 框选"宁大勿小"混入的纯空边（air/water/环境块）经重定基剔除：
      保留体素的最小角平移为 (0,0,0) = 结构本体包围盒西北角
      = cubiomes 锚点，与 WorldEdit pos1 相对位置无关。
    """
    with open(path, "rb") as f:
        root = parse_nbt(f.read())
    if "BlockData" not in root and isinstance(root.get("Schematic"), dict):
        root = root["Schematic"]                    # Sponge v3 嵌套
    width = root.get("Width") or 0
    height = root.get("Height") or 0
    length = root.get("Length") or 0
    blocks = root.get("Blocks")
    if isinstance(blocks, dict) and isinstance(
            blocks.get("Data"), (bytes, bytearray)):
        block_data = blocks["Data"]                 # v3：Blocks.Data
        palette_raw = blocks.get("Palette")
    else:
        block_data = root.get("BlockData")          # v2：平铺字段
        palette_raw = root.get("Palette")
    if not (width and height and length) or not isinstance(
            block_data, (bytes, bytearray)):
        return {}
    palette = palette_raw if isinstance(palette_raw, dict) else {}
    mats = {}                                       # palette 索引 -> 体素值
    names = {}                                      # palette 索引 -> 基名
    for name, pid in palette.items():
        if not isinstance(pid, int) or pid < 0:
            continue
        base, props = _schem_base_and_type(name)
        names[pid] = base
        typ = props.get("type", "")
        mode = "full" if typ in ("top", "double") else "half"
        mat = _map_block(base, mode)
        if mat is None:
            mats[pid] = None
            continue
        shape = bs.shape_from_props(base, props)
        half_prefix = isinstance(mat, str) \
            and mat.startswith("halfheight:")
        base_tex = mat[len("halfheight:"):] if half_prefix else mat
        if shape is None and half_prefix and typ != "double":
            # 无 properties 形状的旧前缀材质按底半格
            shape = bs.SHAPE_SLAB_BOT
        mats[pid] = (base_tex, shape) if shape is not None else base_tex
    vox: dict = {}
    x = y = z = 0
    pos = 0
    for _ in range(width * height * length):
        pid, pos = _read_schem_varint(block_data, pos)
        base = names.get(pid)
        if base is not None and base not in _SCHEM_ENV_FILTER:
            mat = mats.get(pid, UNKNOWN_MAT)
            if mat is not None:
                vox[(x, y, z)] = mat
        x += 1
        if x == width:
            x = 0
            z += 1
            if z == length:
                z = 0
                y += 1
    if vox:
        mx = min(p[0] for p in vox)
        my = min(p[1] for p in vox)
        mz = min(p[2] for p in vox)
        if (mx, my, mz) != (0, 0, 0):
            vox = {(px - mx, py - my, pz - mz): m
                   for (px, py, pz), m in vox.items()}
    return vox


# ---------------------------------------------------------------------------
# 蓝图挤出（top 高度图 + tcol 最高层调色板 -> 体素柱）
# ---------------------------------------------------------------------------
def _norm_block_name(name: str) -> str:
    """Wiki 人话名 -> 纹理键（与 structure_preview._norm_block 一致）。"""
    s = name.strip().lower()
    if s.startswith("entitysprite:"):
        s = s[len("entitysprite:"):]
    if "-rot" in s:                              # 去 -rotNNN 旋转后缀
        head, _, tail = s.rpartition("-rot")
        if tail.isdigit():
            s = head
    return s


def _voxels_from_blueprint(key: str) -> dict:
    """蓝图 top+tcol -> 体素：每格从 y=1..h 挤出柱（h=top 高度值）。"""
    bp = sb.blueprint(key)
    if bp is None:
        raise ValueError(f"{key}: 无蓝图")
    top, tcol, pal = bp["top"], bp["tcol"], bp["palette"]
    vox = {}
    for z, row in enumerate(top):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            h = int(ch, 36) if ch.isalnum() else 1   # base36，兼容大写 A-Z
            mat_ch = tcol[z][x] if z < len(tcol) and x < len(tcol[z]) else "."
            tex = _norm_block_name(pal.get(mat_ch, ""))
            mat = tex if os.path.isfile(os.path.join(TEX_DIR, tex + ".png")) \
                else UNKNOWN_MAT
            # 台阶/楼梯按半高：蓝图调色板名含 slab/stairs；地毯不
            # 打 halfheight 前缀——官方厚 1/16，走 carpet 形状码
            low = tex
            if any(w in low for w in ("slab", "stairs")):
                mat = "halfheight:" + tex
            elif low.endswith("carpet"):
                mat = (mat, bs.SHAPE_CARPET)
            for y in range(1, h + 1):
                vox[(x, y - 1, z)] = mat
    return vox


# ---------------------------------------------------------------------------
# 统一入口：体素模型构建 + 缓存（模块级单条 + 线程锁）
# ---------------------------------------------------------------------------
_CACHE_LOCK = threading.Lock()
_CACHE: dict = {"key": None, "model": None}


def build_voxels(key: str, variant: int | None = None) -> dict:
    """结构键 -> 体素 dict {(x,y,z): mat}。

    variant=None 用默认模板（TEMPLATE_FILES[key]，多文件拼接）；
    variant=i（0 起）用 VARIANT_FILES[key][i] 单独建模（变种轮播）。
    未知键抛 ValueError。

    体素坐标：x 西→东、z 北→南、y 向上，(0,0,0) = 包围盒西北角
    底部 = cubiomes 生成锚点位置（结构最低角）。
    igloo 特例：三段 NBT 各自从 y=0 开始，按 top/middle/bottom
    顺序垂直向下堆叠（top 在地表，地下室在下方负高度）。
    """
    if key in VARIANT_KEYS:
        if variant is None:
            files = TEMPLATE_FILES[key]
        else:
            names = VARIANT_FILES[key]
            files = [names[variant % len(names)]]
        vox = {}
        for fname in files:
            part = _voxels_from_template_file(
                os.path.join(TEMPLATE_DIR, fname))
            vox.update(part)
        return vox
    if key in TEMPLATE_FILES:
        files = TEMPLATE_FILES[key]
        if key == "igloo":
            # 三段堆叠：top 原位（y≥0），middle/bottom依次向下
            vox: dict = {}
            dy = 0
            for fname in files:
                part = _voxels_from_template_file(
                    os.path.join(TEMPLATE_DIR, fname))
                if not part:
                    continue
                h = max(p[1] for p in part) + 1   # 该段自身高度
                for (x, y, z), m in part.items():
                    vox[(x, y + dy, z)] = m
                dy -= h                            # 下一段顶接在本段底
            return vox
        vox = {}
        for fname in files:
            part = _voxels_from_template_file(
                os.path.join(TEMPLATE_DIR, fname))
            vox.update(part)
        return vox
    # 蓝图挤出：按键接确定性后处理（苔石混杂 / 入口雕刻）
    if key in EXTRUDE_KEYS:
        vox = _voxels_from_blueprint(key)
        if key == "jungle_temple":
            _mossify_jungle(vox)
            _carve_jungle_temple(vox)
        return vox
    # WorldEdit 真实提取结构：文件存在优先，缺失回退程序化建模
    if key in SCHEM_FILES:
        path = os.path.join(SCHEM_DIR, SCHEM_FILES[key])
        if os.path.isfile(path):
            return _voxels_from_schem_file(path)
    if key in PROCEDURAL_KEYS:
        return _PROC_BUILDERS[key]()
    raise ValueError(f"未知结构键：{key}")


def _rng(key: str) -> random.Random:
    """结构键派生的确定性随机源（同键结果可复现，跨会话稳定）。"""
    return random.Random(f"mchelper:{key}")


def _mossify_jungle(vox: dict) -> None:
    """丛林神庙：圆石按 50% 概率换苔石（原版为均匀混合）。"""
    rnd = _rng("jungle_temple")
    for pos, mat in vox.items():
        if mat == "cobblestone" and rnd.random() < 0.5:
            vox[pos] = "mossy cobblestone"


def _carve_jungle_temple(vox: dict) -> None:
    """丛林神庙：南面正中 2 宽 2 高门洞（y1..2），穿透三层外墙。

    蓝图挤出为逐格实心柱，与沙漠神殿同模式反向雕出入口。南面为
    z 最大侧（D=13，外墙 z9..12 含顶部出檐行），门洞居中 x7..8，
    y0 保留作门槛地面；苔石随机替换在雕刻前完成，门洞边缘与
    其余墙面材质分布一致。
    """
    for y in (1, 2):
        for x in (7, 8):
            for z in range(9, 13):
                vox.pop((x, y, z), None)       # 南门洞穿透三层外墙


# 沙漠神殿 wiki 逐层蓝图（Desert Pyramid/Structure，21x21 字符画，
# x 自西向东 / z 自北向南）。行首缩进即空列：主金字塔居中
# (x1..19)，南面双塔位于 x0..4 / x16..20（z14..19），南门走
# 廊（z8..10 通道）通向南墙外入口（z15+，x9..11）。
# 字符 -> 方块（wiki 计数全对账：TNT9/箱4/刻纹砂岩62/切制砂岩238/
# 橙陶瓦66/蓝陶瓦2/砂岩楼梯17/台阶2/压力板1）：
#   S=Sandstone  C=Cut Sandstone  H=Chiseled Sandstone
#   O=Orange Terracotta  B=Blue Terracotta  d=Sand
#   T=TNT  E=Chest  P=Pressure Plate  t=Sandstone Stairs
#   l=Sandstone Slab  R/G/B/W=羊毛（暗室埋沙/塌顶占位，建模按
#   wiki 生成规则替换为 sand/sandstone）
# 自动生成：desert_layers_out.txt -> _DESERT_LAYERS（21 行/层）
# 自动生成：desert_layers_out.txt -> _DESERT_LAYERS（21 行/层）
# 自动生成：desert_layers_out.txt -> _DESERT_LAYERS（21 行/层）
_DESERT_LAYERS = {
    -14: (
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '        CCCCC',
        '        CCCCC',
        '        CCCCC',
        '        CCCCC',
        '        CCCCC',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
    ),
    -13: (
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '        CCCCC',
        '        CTTTC',
        '        CTTTC',
        '        CTTTC',
        '        CCCCC',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
    ),
    -12: (
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '        CCCCC',
        '        CCCCC',
        '        CCCCC',
        '        CCCCC',
        '        CCCCC',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
    ),
    -11: (
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '          C',
        '        CCECC',
        '        C   C',
        '       CE P EC',
        '        C   C',
        '        CCECC',
        '          C',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
    ),
    -10: (
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '          H',
        '        HH HH',
        '        H   H',
        '       H     H',
        '        H   H',
        '        HH HH',
        '          H',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
    ),
    -9: (
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '        CCCCC',
        '        C   C',
        '        C   C',
        '        C   C',
        '        CCCCC',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
    ),
    -8: (
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '        SSSSS',
        '        S   S',
        '        S   S',
        '        S   S',
        '        SSSSS',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
    ),
    -7: (
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '        SSSSS',
        '        S   S',
        '        S   S',
        '        S   S',
        '        SSSSS',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
    ),
    -6: (
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '        SSSSS',
        '        S   S',
        '        S   S',
        '        S   S',
        '        SSSSS',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
    ),
    -5: (
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '        SSSSS',
        '        S   S',
        '        S   S',
        '        S   S',
        '        SSSSS',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
    ),
    -4: (
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSOSSSSSSSSSSSSSSSS',
        'SSSSOSSSSSSSSSSSSSSSS',
        'SSSOSOSSSSSSSSSSSSSSS',
        'SOOSBSOOSSSSSSSSSSSSS',
        'SSSOSOSSSSSSSSSSSSSSS',
        'SSSSOSSSS   SSSSSSSSS',
        'SSSSOSSSS   SSSSSSSSS',
        'SSSSSSSSS   SSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
    ),
    -3: (
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSdtSSSSSSSSSSSSSSS',
        'SCCCRCCCSSSSSSSSSSSSS',
        'SCRRRRRCSSSSSSSSSSSSS',
        'SCRRRRRCSSSSSSSSSSSSS',
        'CRRRRRRRCSSSSSSSSSSSS',
        'SCRRRRRCSSSSSSSSSSSSS',
        'SCRRRRRCS   SSSSSSSSS',
        'SCCCRCCCS   SSSSSSSSS',
        'SSSSCSSSS   SSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
    ),
    -2: (
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSdtSSSSSSSSSSSSSS',
        'SHHHRHHHSSSSSSSSSSSSS',
        'SHRRRRRHSSSSSSSSSSSSS',
        'SHRRRRRHSSSSSSSSSSSSS',
        'HRRRRRRRHSSSSSSSSSSSS',
        'SHRRRRRHSSSSSSSSSSSSS',
        'SHRRRRRHS   SSSSSSSSS',
        'SHHHRHHHS   SSSSSSSSS',
        'SSSSHSSSS   SSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
    ),
    -1: (
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSGGdtSSSSSSSSSSSSS',
        'SCCCCCCCSSSSSSSSSSSSS',
        'SCRRRRRCSSSSSSSSSSSSS',
        'SCRRRRRCSSSSSSSSSSSSS',
        'SCRRRRRCSSSSSSSSSSSSS',
        'SCRRRRRCSSSSSSSSSSSSS',
        'SCRRRRRCS   SSSSSSSSS',
        'SCCCCCCCS   SSSSSSSSS',
        'SSSSSSSSS   SSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
    ),
    0: (
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSdddddSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSWWWWWSSSSSSSSSSSSSS',
        'SSWWWWWSSSSSSSSSSSSSS',
        'SSWWWWWSSSOSSSSSSSSSS',
        'SSWWWWWSSSOSSSSSSSSSS',
        'SSWWWWWSSOSOSSSSSSSSS',
        'SSSSSSSOOSBSOOSSSSSSS',
        'SSSSSSSSSOSOSSSSSSSSS',
        'SSSSSSSSSSOSSSSSSSSSS',
        'SSSSSSSSSSOSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
        'SSSSSSSSSSSSSSSSSSSSS',
    ),
    1: (
        '',
        ' SSSSSSSSSSSSSSSSSSS',
        ' S                 S',
        ' S  C           C  S',
        ' S                 S',
        ' S  C           C  S',
        ' S                 S',
        ' S  C           C  S',
        ' S      C   C      S',
        ' SSSC           C SS',
        ' SSS              SS',
        ' SSSC           C SS',
        ' SSS    C   C     SS',
        ' SSSC           C SS',
        ' SSS              SS',
        ' SSSC           C SS',
        'SSSSS   S   S   SSSSS',
        'SSS SSSSS   SSSSS SSS',
        'SSt               tSS',
        'S   SSSSSC CSSSSS   S',
        'SSSSS   S   S   SSSSS',
    ),
    2: (
        '',
        '',
        '  SSSSSSSSSSSSSSSSS',
        '  S H           H S',
        '  S               S',
        '  S H           H S',
        '  S               S',
        '  S H           H S',
        '  S     C   C     S',
        ' SSSH           H SS',
        ' SSS              SS',
        ' SSSH           H SS',
        ' SSS    C   C     SS',
        ' SSSH           H SS',
        ' SSS              SS',
        ' SSSH           H SS',
        'SSSSS   S   S   SSSSS',
        'CSS SSSSS   SSSSS SSC',
        'Ol                 lO',
        'C   SSSSSC CSSSSS   C',
        'SCOCS   S   S   SCOCS',
    ),
    3: (
        '',
        '',
        '',
        '   SSSSSSSSSSSSSSS',
        '   SS           SS',
        '   SS           SS',
        '   SS           SS',
        '   SS           SS',
        '   SS   C   C   SS',
        ' SSSS           SSSS',
        ' SSSS           SSSS',
        ' SSSS           SSSS',
        ' SSSS   C   C   SSSS',
        ' SSSS           SSSS',
        ' SSSS           SSSS',
        ' SSSS           SSSS',
        'SStSS   S   S   SStSS',
        'C   SSSSS   SSSSS   C',
        'O   SSSSS   SSSSS   O',
        'C   SSSSSCCCSSSSS   C',
        'SCOCS   S   S   SCOCS',
    ),
    4: (
        '',
        '',
        '',
        '',
        '    SSSSSSSSSSSSS',
        '    SSSSSSSSSSSSS',
        '    SSSSSSSSSSSSS',
        '    SSSSSSSSSSSSS',
        '    SSSSSSSSSSSSS',
        ' SSSSSSSS   SSSSSSSS',
        ' SSSSSSSS   SSSSSSSS',
        ' SSSSSSSS   SSSSSSSS',
        ' SSSSSSSSSSSSSSSSSSS',
        ' SSSSSSSSSSSSSSSSSSS',
        ' SSSSSSSSSSSSSSSSSSS',
        ' StSSSSSSSSSSSSSSStS',
        'SS SSSSSSSSSSSSSSS SS',
        'O   S   SSSSS   S   O',
        'H   S   SSSSS   S   H',
        'O   S   SSSSS   S   O',
        'SOHOS   CCCCC   SOHOS',
    ),
    5: (
        '',
        '',
        '',
        '',
        '',
        '     SSSSSSSSSSS',
        '     S         S',
        '     S         S',
        '     S         S',
        '     C         C',
        '',
        '     C         C',
        '     S         S',
        '     S         S',
        '     S         S',
        '     SSSSSSSSSSS',
        'SS SS           SS SS',
        'C   S           S   C',
        'O   S           S   O',
        'C   S           S   C',
        'SCOCS   COHOC   SCOCS',
    ),
    6: (
        '',
        '',
        '',
        '',
        '',
        '',
        '      SSSSSSSSS',
        '      S       S',
        '      S       S',
        '     CS       SC',
        '',
        '     CS       SC',
        '      S       S',
        '      S       S',
        '      SSSSSSSSS',
        '',
        'SS SS           SS SS',
        'O   S           S   O',
        'H   S           S   H',
        'O   S           S   O',
        'SOHOS    CCC    SOHOS',
    ),
    7: (
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '       SSSSSSS',
        '       S     S',
        '     CSS     SSC',
        '     CSS     SSC',
        '     CSS     SSC',
        '       S     S',
        '       SSSSSSS',
        '',
        '',
        'SSSSS           SSSSS',
        'O   S           S   O',
        'O   S           S   O',
        'O   S           S   O',
        'SOOOS           SOOOS',
    ),
    8: (
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '        SSSSS',
        '        S   S',
        '        S   S',
        '        S   S',
        '        SSSSS',
        '',
        '',
        '',
        'SSSSS           SSSSS',
        'C   S           S   C',
        'C   S           S   C',
        'C   S           S   C',
        'SCCCS           SCCCS',
    ),
    9: (
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '         SSS',
        '         S S',
        '         SSS',
        '',
        '',
        '',
        '',
        'SSSSS           SSSSS',
        'SSSSS           SSSSS',
        'SSSSS           SSSSS',
        'SSSSS           SSSSS',
        'SSSSS           SSSSS',
    ),
    10: (
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '  t               t',
        ' SSS             SSS',
        'tSSSt           tSSSt',
        ' SSS             SSS',
        '  t               t',
    ),
}

# 字符 -> 纹理键。羊毛不在此表：W=塌顶/G=互斥对/R=埋沙按 wiki 生成
# 规则在构建函数内处理；B=蓝陶瓦本体是真实方块（全结构 2 块）。
# 其余：E=chest、d=sand、l=slab、t=stairs、P=pressure plate 均有纹理
_DESERT_CHAR_MAT = {
    "S": "sandstone", "C": "cut sandstone", "H": "chiseled sandstone",
    "O": "orange terracotta", "B": "blue terracotta",
    "d": "sand", "T": "tnt", "E": "chest", "P": "stone pressure plate",
    "t": "halfheight:sandstone stairs", "l": "halfheight:sandstone slab",
}
# 羊毛字符（W/G/R）不在此表：按 wiki 生成规则在构建函数内展开


def _voxels_desert_pyramid() -> dict:
    """沙漠神殿：wiki 逐层蓝图数据驱动重建（含地下暗室）。

    数据源 = _DESERT_LAYERS（Layer -14..10 全 21x21 字符画，来自
    Minecraft Wiki Desert Pyramid/Structure 逐层蓝图页 HTML 解析，
    方块计数与 wiki Materials 表全对账）。建模规则：

    - 每字符 = 1 体素（行列即 x/z，y = 层号）；羊毛字符按 wiki
      生成规则替换：W=暗室塌顶 25 块（Materials 备注"33% 砂岩 +
      其余沙子"，确定性伪随机保证可复现）；G=2 块"沙/砂岩互斥对"
      （wiki 羊毛备注：两格位置一沙一砂岩，按 x 奇偶确定性分配）；
      R=暗室埋沙 83 块 -> sand（suspicious sand 考古交互块不建模，
      保持 sand）；B=蓝陶瓦本体（Materials"Blue Terracotta 2"，
      两处图案中心，逐层蓝图恰 2 块）——注意 B 不是羊毛标记；
    - 蓝图 22 个层中 Layer -8..-5 为同一模板（wiki"Layer -8 to -5"
      合并标签），此处按相同内容补齐 4 层；
    - 包围盒：x0..20/z0..20/y-14..10 -> 重定基后 21x21x25，
      (0,0,0)=西北角底部；
    - 塔顶天窗：Layer 9/10 印证 wiki"金字塔顶端 1 格宽窗户"
      （主体收分至 y9 中心 3x3 壳，y10 檐口留缝）；
    - 南门走廊贯通（Layer 1..3 走廊行 + Layer 0 地面走道）；
    - 地下暗室完整建模（TNT 9 / 箱 4 / 压力板 1 / 考古沙以 sand
      示意），拾取站位提示仍以地表图案区（橙陶瓦标记）为准。
    """
    vox: dict = {}
    for ly, rows in _DESERT_LAYERS.items():
        for z, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch in ("G", " "):
                    continue                   # G=沙/砂岩互斥对，不建
                if ch == "W":
                    # 塌顶 25 块：33% 砂岩 + 67% 沙子（wiki 备注），
                    # 确定性伪随机保证可复现
                    mat = "sandstone" if (x * 7 + z * 13) % 3 == 0 \
                        else "sand"
                elif ch == "R":
                    mat = "sand"               # 暗室埋沙（可疑沙不区分）
                else:
                    mat = _DESERT_CHAR_MAT.get(ch)
                if mat is None:
                    continue
                vox[(x, ly, z)] = mat
    return vox


# ---------------------------------------------------------------------------
# 程序化合成（原版形体规则）：分发见 _PROC_BUILDERS
# ---------------------------------------------------------------------------
def _voxels_swamp_hut() -> dict:
    """女巫小屋：橡木桩架空 + 云杉板墙 + 屋内陈设（原点贴合包围盒）。

    原版形体：5x6 屋体架在 4 根木桩上（桩底插入沼泽水面下），南面
    门前平台，屋内炼药锅 + 工作台。模型 y0 = 木桩底（水面下），
    地板 y3、室内 y4..5、平顶 y6；屋顶四向出檐 1 格，出檐即包围盒
    边界，锚点 = 包围盒西北角（出檐西北角）。
    """
    W = "spruce planks"
    LOG = "oak log"
    vox: dict = {}

    def box(x0, y0, z0, x1, y1, z1, mat):
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for z in range(z0, z1 + 1):
                    vox[(x, y, z)] = mat

    # 屋体占用 x1..5, z1..6；出檐使包围盒为 x0..6, z0..7
    # 架空支撑柱（4 根，y0..2）+ 地板层 y3
    for px, pz in ((1, 1), (5, 1), (1, 6), (5, 6)):
        box(px, 0, pz, px, 2, pz, LOG)
    box(1, 3, 1, 5, 3, 6, W)
    # 南侧门前平台（z=7）+ 平台支撑柱
    box(2, 3, 7, 4, 3, 7, W)
    box(2, 0, 7, 2, 2, 7, LOG)
    box(4, 0, 7, 4, 2, 7, LOG)
    # 墙体 y4..y5：围一圈
    for y in (4, 5):
        for x in range(1, 6):
            vox[(x, y, 1)] = W
            vox[(x, y, 6)] = W
        for z in range(1, 7):
            vox[(1, y, z)] = W
            vox[(5, y, z)] = W
    vox.pop((3, 4, 1), None)                   # 北窗
    # 屋顶 y=6：满铺 x0..6, z0..7（含四向出檐）
    box(0, 6, 0, 6, 6, 7, W)
    # 屋内陈设：炼药锅 + 工作台
    vox[(2, 4, 2)] = "cauldron"
    vox[(4, 4, 2)] = "crafting table"
    # 南门洞（平台通屋内，y4..y5, x=3, z=6）
    vox.pop((3, 4, 6), None)
    vox.pop((3, 5, 6), None)
    return vox


def _voxels_village() -> dict:
    """村庄：中央水井 + 四角 4 栋拼装房屋（复用真实房屋 NBT）。

    水井 3x3 居中（圆石框 + 中心水柱 + 四角原木柱 + 石砖檐口顶盖）。
    房屋用 plains_medium_house_1 模板（13x11, 8 高）平移拼入四角，
    整体布局 54x40，锚点 = 包围盒西北角。
    """
    vox: dict = {}

    def box(x0, y0, z0, x1, y1, z1, mat):
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for z in range(z0, z1 + 1):
                    vox[(x, y, z)] = mat

    # 井：中心 (26..28, 19..21)，圆石框 y0 + 中心水柱 + 四角柱 y1..3
    box(26, 0, 19, 28, 0, 21, "cobblestone")
    box(27, 0, 20, 27, 0, 20, "gravel")        # 水无纹理，砾石示意
    for px, pz in ((26, 19), (28, 19), (26, 21), (28, 21)):
        box(px, 1, pz, px, 3, pz, "oak log")
    # 顶盖：石砖檐口 3x3（y4）+ 顶 1x1（y5）
    box(26, 4, 19, 28, 4, 21, "stone bricks")
    box(27, 5, 20, 27, 5, 20, "stone bricks")
    # 四栋房屋：复用真实房屋模板（13 宽 x 11 深），四角散布
    tpl = _voxels_from_template_file(os.path.join(
        TEMPLATE_DIR, "village__plains__houses__plains_medium_house_1.nbt"))
    offs = ((0, 0), (41, 0), (0, 29), (41, 29))   # 西北/东北/西南/东南
    for ox, oz in offs:
        for (x, y, z), m in tpl.items():
            vox[(x + ox, y, z + oz)] = m
    return vox


def _voxels_trial_chambers() -> dict:
    """试炼密室 Wiki 形态：全封闭凝灰岩砖箱体 + 中央决斗室 + 三层柱廊。

    Wiki（Trial Chambers/Structure）：地下结构，主体凝灰岩砖
    （tuff bricks）+ 磨制凝灰岩，涂蜡氧化铜走道地面、铜灯照明、
    铜格栅装饰；由柱廊与决斗室 jigsaw 拼接，整体封闭无外墙开口。
    程序化近似：40x40x20 全封闭箱体（外壳 tuff bricks）+ 中央
    决斗室（x12..27，墙 tuff bricks、地面 polished tuff、四棵
    铜柱、顶嵌 3x3 铜灯）+ 环状三层走廊（y2..6/8..12/14..18，
    层间 tuff bricks 楼板 y7/y13，下层走道地面 oxidized cut
    copper）；外墙 y9..10 铜格栅饰带；四角 2x2 氧化铜方柱通高；
    走廊四边中点地嵌铜灯。锚点 = 包围盒西北角。
    """
    TB = "tuff bricks"
    PT = "polished tuff"
    OG = "oxidized cut copper"
    CU = "copper block"
    OX = "oxidized copper"
    GR = "copper grate"
    BULB = "copper bulb"
    vox: dict = {}

    def box(x0, y0, z0, x1, y1, z1, mat):
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for z in range(z0, z1 + 1):
                    vox[(x, y, z)] = mat

    # 1 外壳：40x40x20 全实心凝灰岩砖箱体
    box(0, 0, 0, 39, 19, 39, TB)
    # 2 环状走廊空腔：非外壳壁且非中央区（中央区仅保留 y1..16）
    for x in range(1, 39):
        for y in range(1, 19):
            for z in range(1, 39):
                if 12 <= x <= 27 and 12 <= z <= 27 and y <= 16:
                    continue
                vox.pop((x, y, z), None)
    # 3 中央决斗室内腔（x14..25, y2..14, z14..25）
    for x in range(14, 26):
        for y in range(2, 15):
            for z in range(14, 26):
                vox.pop((x, y, z), None)
    # 4 三层楼板：环区 y7/y13 铺凝灰岩砖，下层走道地面 y1 铺氧化铜
    for x in range(1, 39):
        for z in range(1, 39):
            if 12 <= x <= 27 and 12 <= z <= 27:
                continue
            vox[(x, 1, z)] = OG
            vox[(x, 7, z)] = TB
            vox[(x, 13, z)] = TB
    # 5 决斗室地面：磨制凝灰岩（含墙内缘一圈）
    box(13, 1, 13, 26, 1, 26, PT)
    # 6 室内四棵铜柱（对应刷怪场/保险库区）
    for cx, cz in ((15, 15), (24, 15), (15, 24), (24, 24)):
        box(cx, 2, cz, cx, 14, cz, CU)
    # 7 顶嵌 3x3 铜灯（决斗室顶板 y15 内圈）
    box(19, 15, 19, 21, 15, 21, BULB)
    # 8 外墙铜格栅饰带 y9..10
    for y in (9, 10):
        for x in range(40):
            vox[(x, y, 0)] = GR
            vox[(x, y, 39)] = GR
        for z in range(40):
            vox[(0, y, z)] = GR
            vox[(39, y, z)] = GR
    # 9 四角 2x2 氧化铜方柱（y1..18 通高）
    for cx, cz in ((1, 1), (37, 1), (1, 37), (37, 37)):
        box(cx, 1, cz, cx + 1, 18, cz + 1, OX)
    # 10 走廊四边中点地嵌铜灯
    for lx, lz in ((19, 5), (19, 34), (5, 19), (34, 19)):
        vox[(lx, 1, lz)] = BULB
    return vox


def _voxels_monument() -> dict:
    """海底神殿 Wiki 形态：底部 23 柱 + 中央主体（前部高塔）+ 前伸两翼。

    Wiki（Ocean Monument/Structure）：58x58 基座，高 22 层；中央主体
    居中偏后（x17..39, z18..39，23x22），内部为空腔殿堂；前部竖高塔
    （x24..34, z24..39, y1..21）含主入口（南面 3x3, y3..5）与顶层
    penthouse（海晶灯顶 y21）；主体殿堂内藏宝室以金块堆示意
    （Wiki：暗海晶石包 8 金块）；两翼自主体前侧伸出（x1..16 /
    x41..56, z28..39，高 8）环抱入口，与 Wiki 俯视图一致；23 根
    2x2 巨柱错列网格分布（含四角），自基座下 y-8 延至 y-1（示意
    向海床延伸段）；本体 y0..21 恰 22 层（基座 y0，主体至 y13，
    高塔至 y21，主入口 y3..5）；包围盒 y-8..21，锚点 = 包围盒
    西北角 (0,-8,0)。
    """
    P = "prismarine"
    vox: dict = {}

    def box(x0, y0, z0, x1, y1, z1, mat):
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for z in range(z0, z1 + 1):
                    vox[(x, y, z)] = mat

    def del_box(x0, y0, z0, x1, y1, z1):
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for z in range(z0, z1 + 1):
                    vox.pop((x, y, z), None)

    # 23 根巨柱：错列网格（行距 14、列距 14 交错 +7，含四角），
    # 全部位于基座下方 y-8..-1（真实中柱向下延伸至海床，此处 8 格示意）
    pillars = [(0, 0), (14, 0), (28, 0), (42, 0), (56, 0),
               (7, 14), (21, 14), (35, 14), (49, 14),
               (0, 28), (14, 28), (28, 28), (42, 28), (56, 28),
               (7, 42), (21, 42), (35, 42), (49, 42),
               (0, 56), (14, 56), (28, 56), (42, 56), (56, 56)]
    for (px, pz) in pillars:
        box(px, -8, pz, px + 1, -1, pz + 1, P)
    # 基座平台：y0 全铺 58x58（覆盖柱顶段）
    box(0, 0, 0, 57, 0, 57, P)
    # 中央主体：底部 23x22（x17..39, z18..39），y1..13，四周壁厚 3
    box(17, 1, 18, 39, 13, 39, P)
    # 主体内部殿堂空腔（x20..36, y1..12, z21..36）
    del_box(20, 1, 21, 36, 12, 36)
    # 前部高塔（x24..34, z24..39, y1..21）：殿堂内重新填实
    box(24, 1, 24, 34, 21, 39, P)
    # 高塔内部：入口大厅（x26..32, y1..9, z26..37）
    del_box(26, 1, 26, 32, 9, 37)
    # 主入口（南面前壁 z38..39）：3 宽 3 高（x27..29, y3..5）穿透
    del_box(27, 3, 38, 29, 5, 39)
    # 藏宝室：大厅深处金块堆 4x2x4（Wiki：暗海晶石包 8 金块示意；
    # 置于塔大厅内避免被塔体回填覆盖）
    box(28, 8, 32, 31, 9, 35, "block of gold")
    # 高塔上层空腔（y10..20, x26..32, z27..37）：penthouse 内腔
    del_box(26, 10, 27, 32, 20, 37)
    # 海晶灯顶（penthouse 顶板 y21，x27..31, z30..34）
    box(27, 21, 30, 31, 21, 34, "sea lantern")
    # 两翼：主体前侧（z28..39）左右伸出，高 8（y1..8）
    box(1, 1, 28, 16, 8, 39, P)                # 西翼（x1..16）
    box(41, 1, 28, 56, 8, 39, P)               # 东翼（x41..56）
    # 翼内大房间空洞（x4..14 / x43..53, y1..6, z31..36）
    del_box(4, 1, 31, 14, 6, 36)
    del_box(43, 1, 31, 53, 6, 36)
    # 翼顶四角小塔（5x5, y9..12）
    box(4, 9, 31, 8, 12, 35, P)                # 西翼塔
    box(49, 9, 31, 53, 12, 35, P)              # 东翼塔
    return vox


# 程序化合成分发表：结构键 -> 构建函数
_PROC_BUILDERS = {
    "monument": _voxels_monument,
    "swamp_hut": _voxels_swamp_hut,
    "trial_chambers": _voxels_trial_chambers,
    "village": _voxels_village,
    "desert_pyramid": _voxels_desert_pyramid,
}


def model_size(vox: dict) -> tuple:
    """体素 dict -> 包围盒尺寸 (W, D, H)（x/z/y 方向跨度）。"""
    if not vox:
        return (0, 0, 0)
    xs = [p[0] for p in vox]
    ys = [p[1] for p in vox]
    zs = [p[2] for p in vox]
    return (max(xs) - min(xs) + 1,
            max(zs) - min(zs) + 1,
            max(ys) - min(ys) + 1)


def build_model(key: str, variant: int | None = None) -> dict:
    """构建并返回模型 dict（带缓存：(key, variant) 单条，切换零成本复用）。

    返回 {"key", "variant", "voxels", "size", "mesh", "tex_keys"}；
    mesh 见 build_mesh；tex_keys = 材质键列表（含形状元组者取其
    纹理位）。
    """
    ck = (key, variant)
    with _CACHE_LOCK:
        if _CACHE["key"] == ck and _CACHE["model"] is not None:
            return _CACHE["model"]
        vox = build_voxels(key, variant)
        mesh = build_mesh(vox)
        tex_keys = sorted({_mat_shape(v)[0] for v in vox.values()})
        model = {"key": key, "variant": variant, "voxels": vox,
                 "size": model_size(vox), "mesh": mesh, "tex_keys": tex_keys}
        _CACHE.update(key=ck, model=model)
        return model


def tex_keys_used(model: dict) -> list:
    """模型用到的纹理键（含 halfheight: 前缀者去前缀）。"""
    out = set()
    for m in model["tex_keys"]:
        out.add(m.split(":", 1)[1] if m.startswith("halfheight:") else m)
    return sorted(out)


# ---------------------------------------------------------------------------
# 网格化：可见面剔除 + 同材质聚合槽
# ---------------------------------------------------------------------------
# 透明材质：面剔除按“异材保留、同材合并”处理；水在视口半透明绘制
# ladder：梯子/横幅贴墙板纹理大部分镂空（FS discard），作为邻居
# 时不得剔墙面——否则所贴方块整面消失、梯子看似悬空（官方
# occlusion 亦不把 ladder 计入不透明遮挡）
_TRANSPARENT_MATS = frozenset({
    "water", "glass", "ice", "ladder",
    # 染色玻璃族（官方 HalfTransparentBlock 家族：同类剔面、
    # 异材豁免、不参与遮挡；26.2 染色玻璃贴图为半透明像素）
    "white stained glass", "orange stained glass",
    "yellow stained glass", "light gray stained glass",
    "black stained glass", "magenta_stained_glass",
})

# 半透明渲染层（26.2 ChunkSectionLayer.TRANSLUCENT 语义：贴图含
# 0<alpha<255 像素 -> 真混合管线，视口第二遍绘制）。集合由
# .temp/scan_alpha_layers.py 按 26.2 NativeImage.computeTransparency
# 规则离线扫描 TEX_DIR 全部贴图得出；redstone wire 按 26.2
# 官方 force_translucent 语义并入。
_TRANSLUCENT_MATS = frozenset({
    "water", "ice", "nether portal",
    "white stained glass", "orange stained glass",
    "yellow stained glass", "light gray stained glass",
    "black stained glass", "magenta_stained_glass",
    "redstone wire",
})

# 体素值 -> (纹理键, 形状码|None) 归一化（兼容旧 halfheight: 前缀）
_HP = "halfheight:"
_HALF = 0.5                         # 半层边界（AABB 贴边占用判定）


def _mat_shape(v) -> tuple:
    """体素值 -> (基纹理键, 形状码或 None)。未知材质 -> UNKNOWN_MAT。

    门按形状码选分块纹理：基键 "xxx door bottom"，上半门
    （door:u:*）换 "xxx door top"（MC 官方分块贴图，每半块各
    一整张 16x16）。
    """
    if isinstance(v, tuple):
        mat, shape = v[0], v[1]
        if (shape and shape.startswith("door:u:")
                and isinstance(mat, str) and mat.endswith(" door bottom")):
            return mat[:-len(" bottom")] + " top", shape
        return mat, shape
    if isinstance(v, str) and v.startswith(_HP):
        return v[len(_HP):], bs.SHAPE_SLAB_BOT
    return (v if isinstance(v, str) else UNKNOWN_MAT), None


# 整格分面表：基键 -> (顶, 底, 侧)；None = 该面沿用基键纹理。
# 仅收有独立顶/底纹理的方块（新结构未来按需补表 + 纹理即生效）。
_FULL_FACES = {
    "grass block side": ("grass block top", "dirt", None),
    "podzol side": ("podzol top", "dirt", None),
    "bookshelf": ("oak planks", "oak planks", None),
    "farmland": (None, "dirt", "dirt"),
    "target side": ("target top", "target top", None),
    # 传送门框架（jar end_portal_frame[_filled].json：top=frame_top、
    # side=frame_side；有眼 filled 上部凸台=eye——整格近似把眼画在顶面）
    "end portal frame side": ("end portal frame top", None, None),
    "end portal frame eye": ("end portal frame eye", None,
                             "end portal frame side"),
    # -- 村庄（顶/底/侧，None = 沿用基键）--
    "cactus side": ("cactus top", "cactus top", None),
    "melon side": ("melon top", "melon side", None),
    "cartography table side": ("cartography table top", None, None),
    "fletching table side": ("fletching table top", None, None),
    "smithing table side": ("smithing table top", None, None),
    "stonecutter side": ("stonecutter top", None, None),
    # 试炼刷怪笼（1.21.11 jar trial_spawner.json：无素面，状态变
    # 体；模板全部 waiting_for_players -> inactive；ominous 变体
    # 模板 0 出现不入）
    "trial spawner side inactive": ("trial spawner top inactive",
                                    "trial spawner bottom", None),
}

# 轴心方块端面表：基键 -> 端面纹理键（查不到 = 六面同图）。
# 形状码 col:<axis>（block_shapes）按轴向选 ±轴两面用端面。
_COL_ENDS = {
    "oak log": "oak log top",
    "spruce log": "spruce log top",
    "dark oak log": "dark oak log top",
    "acacia log": "acacia log top",
    "mangrove log": "mangrove log top",
    "stripped oak log": "stripped oak log top",
    "stripped spruce log": "stripped spruce log top",
    "stripped dark oak log": "stripped dark oak log top",
    "stripped acacia log": "stripped acacia log top",
    "basalt": "basalt top",
    "polished basalt": "polished basalt top",
    "quartz pillar": "quartz pillar top",
    "deepslate": "deepslate top",
}

# 炉族前脸表：基键 -> (顶, 前脸, 亮前脸, 竖直前脸)。
# side 沿用基键（furnace.png 等已覆盖为侧面图）；顶面也用于底面
# （官方 orientable 模型 down=top）。竖直前脸仅 dispenser
# （facing=up/down 时官方 dispenser_up/down.json：朝向面 =
# dispenser_front_vertical，对侧 = top）。
_FC_FACES = {
    "furnace": ("furnace top", "furnace front",
                "furnace front on", None),
    "blast furnace": ("blast furnace top", "blast furnace front",
                      "blast furnace front on", None),
    "smoker": ("smoker top", "smoker front", "smoker front on", None),
    "dispenser": ("furnace top", "dispenser front",
                  "dispenser front", "dispenser front vertical"),
    # 宝库（vault：正面锁眼贴 vault_front_off，侧面 vault_side_off，
    # 顶 vault_top 且顶图兼底（同炉族 orientable 约定）；模板
    # vault_state 全 inactive -> off；ominous_vault 独立方块键同构
    # ominous 贴图）
    "vault side off": ("vault top", "vault front off",
                       "vault front off", None),
    "ominous vault side off": ("ominous vault top",
                               "ominous vault front off",
                               "ominous vault front off", None),
}

# 箱子/炉族朝向 -> 法线（形状码首段）
_FACE_N = {"n": (0, 0, -1), "s": (0, 0, 1),
           "e": (1, 0, 0), "w": (-1, 0, 0)}


def _face_mat(mat: str, shape: str | None, normal: tuple,
              box: tuple | None = None) -> tuple:
    """按面分流纹理：返回 (纹理键, rect)。

    rect = (u0, v0, u1, v1[, swap]) 为图归一化窗（官方 JSON uv
    [a,b,c,d] 按 FaceInfo 顶点配对换算：up 面 v=(1-b,1-d)、
    down/侧面 v=(1-d,1-b)，u=(a,c)；窗可反向；swap=True 轴交换
    见 _emit_quad），None = 基键全图。
    键 None 表示无分流（rect 必为 None）。

    - 箱子（chest:<f>[:<type>]，官方 ChestModel 三面材质观感）：
      单箱朝向面用基键（chest.png 带锁扣正面）；大箱左右半朝向
      面用半窗合成图（chest big left/right：锁扣列贴接缝缘，
      两半拼合复原整锁扣；图名指锁扣在图中的位置——大端窗
      u∈[1/16,1] 采样到图右缘故用 big right），顶面盖顶木纹，
      其余面侧面拼合（视口无背剔除，底面开口可见顶面背面）；
    - 桶（barrel）：顶盖/底专用图，侧面用基键；
    - 轴心方块（col:<axis>）：±轴两端用端面图（原木年轮/玄武
      岩顶等），其余面基键；
    - 炉族（fc:<f>[:lit]）：前脸/亮前脸/竖直前脸 + 顶底图；
    - 整格分面（_FULL_FACES）：草方块/灰化土/书架/耕地/标靶等
      独立顶底纹理；
    - 工作台特例：官方模型无朝向，north/west 两面固定为前脸。
    """
    if shape:
        kind, _, rest = shape.partition(":")
        if kind == "chest":
            if "chest" not in mat:
                return (None, None)
            parts = rest.split(":")
            face_n = _FACE_N.get(parts[0])
            if normal == (0, 1, 0):
                return (mat + " top", None)
            if face_n is not None and normal != face_n:
                return (mat + " plain", None)
            # 朝向面：单箱基键；大箱按 half 与窗口配对取合成图
            # （图名指锁扣在图中的位置：大端窗 u∈[1/16,1] 采样
            # 图右缘 -> "big right"；小端窗 u∈[0,15/16] -> 图左缘）。
            # left 半占 facing 左手侧格，其接缝缘在 u 大端的情形：
            # n=西格（x 窗）/ e=北格（z 窗）-> 大端窗；s/w 为小端
            # 窗。right 半互补。几何见 _CHEST_LEFT_OF 占格表。
            typ = parts[1] if len(parts) > 1 else "single"
            if typ in ("left", "right"):
                f = parts[0]
                big_end = ((typ == "left") == (f in ("n", "e")))
                return (mat + (" big right" if big_end else " big left"),
                        None)
            return (None, None)
        if kind == "barrel":
            if mat != "barrel":
                return (None, None)
            if normal == (0, 1, 0):
                return ("barrel top", None)
            if normal == (0, -1, 0):
                return ("barrel bottom", None)
            return (None, None)
        if kind == "col":
            end = _COL_ENDS.get(mat)
            if end is None:
                return (None, None)
            axis = rest if rest in ("x", "y", "z") else "y"
            if axis == "y" and normal[1] != 0:
                return (end, None)
            if axis == "x" and normal[0] != 0:
                return (end, None)
            if axis == "z" and normal[2] != 0:
                return (end, None)
            return (None, None)
        if kind == "fc":
            cfg = _FC_FACES.get(mat)
            if cfg is None:
                return (None, None)
            top, front, front_on, front_v = cfg
            f, _, lit = rest.partition(":")
            if f in ("u", "d") and front_v is not None:
                if normal == ((0, -1, 0) if f == "d" else (0, 1, 0)):
                    return (front, None)
                if normal[1] != 0:
                    return (top, None)
                return (None, None)
            if f in _FACE_N and normal == _FACE_N[f]:
                return ((front_on if lit else front), None)
            if normal == (0, 1, 0) or normal == (0, -1, 0):
                return (top, None)
            return (None, None)
        if kind == "bell":
            # 官方全对齐（block_shapes._bell）：底座 = 官方 JSON
            # 贴图精确 uv（柱 stone / 梁·吊杆 dark oak planks）；
            # 钟体 = BellRenderer 实体两段盒，bell_body.png 32x32
            # （ModelPart box UV，见 _BELL_BASE_R/_BELL_BODY_R；
            # 静态直立无摆动）。按 box 特征：满高窄柱 / y>=13/16
            # 梁·吊杆（y1 区分）/ 钟口座 y[4,6] / 钟身 y[6,13]
            if box is not None:
                y0, y1 = box[1], box[4]
                if y0 <= 1e-9 and y1 >= 1.0 - 1e-9:
                    # 满高柱：侧窗 2px/4px 按面宽选，顶底按柱
                    # 截面尺寸（floor:x _RU(0,0,2,4) / floor:z
                    # 官方 y=90 旋转后 _RU(0,0,4,2)）
                    xs = round((box[3] - box[0]) * 16)
                    zs = round((box[5] - box[2]) * 16)
                    if normal[1] > 0:
                        return ("stone", _RU(0, 0, xs, zs))
                    if normal[1] < 0:
                        return ("stone", _RS(0, 0, xs, zs))
                    span = xs if normal[2] != 0 else zs
                    return ("stone", _RS(0, 1, 2 if span <= 2 else 4, 16))
                if y0 >= 13 / 16 - 1e-9:
                    if y1 >= 1.0 - 1e-9:
                        # 吊杆：官方四侧独立窗 + up；down 被钟
                        # 身遮（官方省略），取南窗兑底
                        if normal[1] > 0:
                            return ("dark oak planks", _RU(1, 3, 3, 5))
                        r = {(0, 0, -1): _RS(7, 2, 9, 5),
                             (1, 0, 0): _RS(1, 2, 3, 5),
                             (0, 0, 1): _RS(6, 2, 8, 5),
                             (-1, 0, 0): _RS(4, 2, 6, 5)}
                        return ("dark oak planks",
                                r.get(normal, _RS(6, 2, 8, 5)))
                    # 横梁（floor/wall 全变体）：长面 n 窗
                    # [2,2,14,4]（s 窗差 1 行木纹无感）、端面 2px
                    # 官方 between_walls cullface 窗 [5,4,7,6]
                    if normal[1] > 0:
                        return ("dark oak planks", _RU(2, 3, 14, 5))
                    if normal[1] < 0:
                        return ("dark oak planks", _RS(2, 3, 14, 5))
                    span = (round((box[3] - box[0]) * 16)
                            if normal[2] != 0
                            else round((box[5] - box[2]) * 16))
                    if span < 8:
                        return ("dark oak planks", _RS(5, 4, 7, 6))
                    return ("dark oak planks", _RS(2, 2, 14, 4))
                key = _BELL_BASE_R if y1 <= 6 / 16 + 1e-9 else _BELL_BODY_R
                r = key.get(normal)
                if r is not None:
                    return ("bell body", r)
            return (None, None)
        if kind == "composter":
            # 官方 composter.json：底板全格 y[0,2]（down/内底 =
            # composter_bottom）+ 四壁满高（沿口顶 = composter_top，
            # 内外侧 = 基键 composter_side）。按 box 特征：满高 = 壁
            if box is not None:
                if box[4] >= 1.0 - 1e-9 and normal == (0, 1, 0):
                    return ("composter top", None)    # 沿口顶面
                if box[4] <= 2 / 16 + 1e-9:
                    return ("composter bottom", None)  # 底板上下
            return (None, None)
        return _decor_face_mat(mat, kind, rest, normal, box)
    if mat == "crafting table":
        # 官方 crafting_table.json：up=top, down=oak_planks,
        # north/west=front, south/east=side（无朝向属性，固定两面）
        if normal == (0, 1, 0):
            return ("crafting table top", None)
        if normal == (0, -1, 0):
            return ("oak planks", None)
        if normal == (0, 0, -1) or normal == (-1, 0, 0):
            return ("crafting table front", None)
        return ("crafting table side", None)
    cfg = _FULL_FACES.get(mat)
    if cfg is not None:
        if normal == (0, 1, 0):
            return (cfg[0], None)
        if normal == (0, -1, 0):
            return (cfg[1], None)
        return (cfg[2], None)
    return (None, None)


# 装饰方块 rect 分流（_face_mat 尾部统一入口）。rect 语义：
# 图归一化窗 (u0, v0, u1, v1[, swap])，由官方 JSON uv [a,b,c,d]
# （单位 = 纹理像素，图 v 轴向下）换算——shader 图行 = (1-v)*16
# （v=0 采图底行），按 FaceInfo 顶点配对（v0<->(minU,minV)）+ 六
# 面轴映射推导：
#   up 面     rect.v = (1-b, 1-d)（图 b..d 行沿 +v 正向铺）
#   down/侧面 rect.v = (1-d, 1-b)（down 图沿 -z；侧面沿 -y）
#   rect.u = (a, c) 统一（N/E 官方 U 反向的镜像差在噪点窗无感）
# 16px 图/16px 世界 = 像素值 / 16；窗可反向（u0>u1/v0>v1），
# _emit_quad 线性插值天然支持。swap=True（仅 f=e/w 床顶）：
# u/v 轴交换——枕带在图 v 轴、需映射到世界 x 轴。
def _RU(a, b, c, d):                     # up 面像素窗 -> 归一化窗
    return (a / 16.0, 1 - b / 16.0, c / 16.0, 1 - d / 16.0)


def _RS(a, b, c, d):                     # side/down 面像素窗 -> 窗
    return (a / 16.0, 1 - d / 16.0, c / 16.0, 1 - b / 16.0)


# 灯笼 rect 表（template_lantern.json，lantern.png 16x48；
# 纹理键图为顶部 16 行重排版，见 make_decor_tex）：
# 主体侧面 uv[0,2,6,9] -> 图 16x48 像素 (0,2)-(6,9)；重排版把
# 原 v 2..9 行原样放回 v 2..9（0..16 行原样拷贝），rect 不变。
_LANTERN_R = {
    "side": _RS(0, 2, 6, 9),        # 主体四侧
    "body_u": _RU(0, 9, 6, 15),     # 主体 up（官方 uv 9..15 在 16x48
                                    # 顶部 16 行内，重排版原样）
    "body_d": _RS(0, 9, 6, 15),     # 主体 down（图沿 -z，v 式与 up 反）
    "cap_u": _RU(1, 10, 5, 14),     # 顶盖 up uv[1,10,5,14]
    "cap_s": _RS(1, 0, 5, 2),       # 顶盖侧 uv[1,0,5,2]
}

# 末地烛 rect 表（end_rod.json，end_rod.png 16x16）：杆侧面
# uv[0,0,2,15]，顶盖面 uv[2,0,4,2]，底座 uv[2,6,6,7] / up[2,2,6,6]。
_EROD_R = {
    "pole_s": _RS(0, 0, 2, 15),     # 杆四侧
    "pole_u": _RU(2, 0, 4, 2),      # 杆 up
    "base_s": _RS(2, 6, 6, 7),      # 底座四侧
    "base_u": _RU(2, 2, 6, 6),      # 底座 up
    "base_d": _RS(6, 6, 2, 2),      # 底座 down（官方 uv 反写 = 手动镜像）
}

# 酿造台 rect 表（brewing_stand.json）：杆 #stand 16x16（键
# "brewing stand"）侧面 uv[7,2,9,16]、端面 uv[7,7,9,9]；底板
# #base（键 brewing_stand_base）三板各自 6x6 up 窗 + 侧 2px 带
# （官方按面轴分窗：z 面 9..15、x 面东 5..11/西北 1..7/西南 9..15）。
_BREW_R = {
    "rod_s": _RS(7, 2, 9, 16),      # 杆侧面
    "rod_e_up": _RU(7, 7, 9, 9),    # 杆 up
    "rod_e_dn": _RS(7, 7, 9, 9),    # 杆 down
    "plat_u_e": _RU(9, 5, 15, 11),  # 东板 up
    "plat_u_nw": _RU(1, 1, 7, 7),   # 西北板 up
    "plat_u_sw": _RU(1, 9, 7, 15),  # 西南板 up
    "plat_s_z": _RS(9, 14, 15, 16),  # 底板 z 向侧带
    "plat_s_x_e": _RS(5, 14, 11, 16),   # x 向侧带：东板
    "plat_s_x_nw": _RS(1, 14, 7, 16),   # x 向侧带：西北板
    "plat_s_x_sw": _RS(9, 14, 15, 16),  # x 向侧带：西南板
    "plat_d_e": _RS(9, 5, 15, 11),  # down（官方同 up 窗，cullface 挡）
    "plat_d_nw": _RS(1, 1, 7, 7),
    "plat_d_sw": _RS(1, 9, 7, 15),
}

# 花盆壁侧横带（flower_pot.json 侧 uv v 10..16 行，u 全列）。
_FPOT_S = _RS(0, 10, 16, 16)


# 钟体 rect（BellRenderer 实体两段盒，键图 bell body.png =
# 官方 entity/bell/bell_body.png 32x32 原图，图集入槽最近邻缩
# 至 16，归一化窗不受影响）。实体盒 UV（ModelPart$Cube 反编译
# 实证）与方块 JSON 语义差异：up/down 图 v 沿 -z 铺（_RS 式
# v=(1-d,1-b)）、侧面图 v 沿 +y 铺（v=(1-b,1-d)）、N/W/E 面 u
# 反向（S 面正向）。窗 = ModelPart box UV 布局 [d|w|w|d] 行。
def _B32U(a, b, c, d):
    """实体盒 up/down 面像素窗(32 图) -> 归一化窗。"""
    return (a / 32, 1 - d / 32, c / 32, 1 - b / 32)


def _B32S(a, b, c, d, rev_u=False):
    """实体盒侧面像素窗(32 图) -> 归一化窗；N/W/E 面 u 反向。"""
    return ((c / 32 if rev_u else a / 32), 1 - b / 32,
            (a / 32 if rev_u else c / 32), 1 - d / 32)


_BELL_BODY_R = {   # 钟身 6x7x6 uv(0,0)：up(6,0,12,6) down(12,0,18,6)
    (0, 1, 0): _B32U(6, 0, 12, 6),
    (0, -1, 0): _B32U(12, 0, 18, 6),
    (-1, 0, 0): _B32S(0, 6, 6, 13, True),    # west
    (0, 0, -1): _B32S(6, 6, 12, 13, True),   # north
    (1, 0, 0): _B32S(12, 6, 18, 13, True),   # east
    (0, 0, 1): _B32S(18, 6, 24, 13),         # south
}

_BELL_BASE_R = {   # 口座 8x2x8 uv(0,13)：up(8,13,16,21) down(16,13,24,21)
    (0, 1, 0): _B32U(8, 13, 16, 21),
    (0, -1, 0): _B32U(16, 13, 24, 21),
    (-1, 0, 0): _B32S(0, 21, 8, 23, True),
    (0, 0, -1): _B32S(8, 21, 16, 23, True),
    (1, 0, 0): _B32S(16, 21, 24, 23, True),
    (0, 0, 1): _B32S(24, 21, 32, 23),
}

# 床顶面 rect（键图 = 垫顶整块：上半枕带行 0..7、下半毯区）。
# facing = 床头朝向（wiki：head 块在 facing 端、枕贴床头端）。
# 枕带 = 图 v (0.5,1)；顶面 pu=x/pv=z：f=s 枕南（v 正向窗）、
# f=n 枕北（v 反向）；f=e/w 枕沿 x —— swap 窗（u 承载图 v 轴）。
_BED_HEAD_R = {
    "s": (0.0, 0.5, 1.0, 1.0),
    "n": (0.0, 1.0, 1.0, 0.5),
    "e": (0.0, 0.5, 1.0, 1.0, True),
    "w": (0.0, 1.0, 1.0, 0.5, True),
}
_BED_FOOT_R = (0.0, 0.0, 1.0, 0.5)   # foot 无枕：毯区窗（各向同性）

# 龙首 5 面 rect（16px 纹理直提，rect = 全图 None）：
# face/top/side/west/bot 五键已在 make_decor_tex 按框 UV 区合成。
_DHEAD_FACES = {
    "face": "dragon face", "top": "dragon head top",
    "side": "dragon head side", "west": "dragon head west",
    "bot": "dragon head bot",
}


# 面跳过哨兵：_decor_face_mat 返回它 = 官方模型该面无 faces，应
# 完全不 emit（区别于 (None, None) = 无分流回退基键整面）。
_SKIP_FACE = "__skip__"


# 全 16 色床（bed:head/foot 分面顶窗白名单；分色垫顶图 bed <color>
# top.png，白/红官方先例 + 其余按红模板毯区色相替换合成）
_BED_MATS = frozenset(
    f"{c} bed" for c in (
        "white", "orange", "magenta", "light_blue", "yellow", "lime",
        "pink", "gray", "light_gray", "cyan", "purple", "blue",
        "brown", "green", "red", "black"))


def _decor_face_mat(mat: str, kind: str, rest: str, normal: tuple,
                    box: tuple | None) -> tuple:
    """装饰方块（新形状码族）按面分流 (键, rect)。

    box = 当前 AABB（世界相对本地方块坐标），用于多盒方块按盒
    身份分流（酿造台底板/杆）；rect 语义见 _face_mat docstring。
    """
    nx, ny, nz = normal
    if kind == "rswire":
        # 十字图世界平铺 UV 自动命中线带（臂/中心板/竖片皆然）
        return (None, None)
    if kind == "thook":
        # 官方 tripwire_hook[_attached].json 多纹理分区：绊线伸出
        # 段 #tripwire / 钩件 #hook（=基键 tripwire hook）/ 背板+
        # 横臂 #wood（oak planks）。按盒最小维度分流（0.5px 线 /
        # 0.8px 钩件薄盒 / 1.4px 横臂；剩余大盒=背板或未 attached
        # ±45° 斜件包围盒——后者以最长维 <6px 区分回基键）。
        if box is not None:
            dims = (box[3] - box[0], box[4] - box[1], box[5] - box[2])
            md, xd = min(dims), max(dims)
            if md <= 0.6 * _E16:
                return ("tripwire", None)         # 绊线伸出段
            if md <= 1.0 * _E16:
                return (None, None)               # 钩件（attached 版）
            if md <= 1.5 * _E16:
                return ("oak planks", None)       # 横臂
            if xd >= 6 * _E16:
                return ("oak planks", None)       # 背板
            return (None, None)                   # 未 attached 钩件
        return (None, None)
    if kind in ("repeater", "comparator"):
        # 官方 repeater_1tick/comparator.json：底板 #slab=smooth_stone、
        # 顶面 #top=repeater/comparator（基键）；火把柱 #unlit=
        # redstone_torch_off（灭态；powered 仅火把纹理差异）
        if box is not None and box[1] <= 1e-9:
            if ny > 0:
                return (None, None)               # 底板顶 = 基键
            return ("smooth stone", None)         # 底板侧/底
        return ("redstone torch off", None)       # 火把柱
    if kind == "sculk":
        # sculk_sensor.json：底座 #side/#top/#bottom + 触须 #tendrils
        if box is not None and box[1] <= 1e-9 \
                and box[4] <= 8 * _E16 + 1e-9:
            if ny > 0:
                return ("sculk sensor top", None)
            if ny < 0:
                return ("sculk sensor bottom", None)
            return (None, None)                   # 底座侧 = 基键
        return ("sculk sensor tendril", None)     # 触须直立板
    if kind == "lamp":
        # 红石灯 lit 两态整格纹理
        return ("redstone lamp on", None) if rest == "1" else (None, None)
    if kind == "pist":
        # 官方 template_piston（cube 组）：facing 端=platform
        # （sticky=piston_top_sticky / 普通=piston_top）、-facing 端=
        # piston_bottom、其余=piston_side；extended（缩进盒）的
        # facing 端缩进面=杆室内壁（piston_inside）
        parts = rest.split(":")
        f = parts[0] if parts[0] in ("n", "s", "e", "w", "u", "d") \
            else "n"
        sticky = "s" in parts[1:]
        extended = "x" in parts[1:]
        axis_face = {"n": (0, 0, -1), "s": (0, 0, 1), "e": (1, 0, 0),
                     "w": (-1, 0, 0), "u": (0, 1, 0),
                     "d": (0, -1, 0)}.get(f, (0, 0, -1))
        if normal == axis_face:
            if extended:
                return ("piston_inner", None)
            return ("piston_top_sticky" if sticky else "piston_top",
                    None)
        if normal == (-axis_face[0], -axis_face[1], -axis_face[2]):
            return ("piston_bottom", None)
        return ("piston_side", None)
    if kind == "brewing":
        if mat != "brewing stand":
            return (None, None)
        if box is not None and box[1] <= 1e-9 and box[4] <= 2 * _E16 + 1e-9:
            # 底板盒（y 0..2）：up 用所属板窗、侧带按面轴、down 同窗
            east = box[0] > 8.5 * _E16
            nw = box[2] < 8.5 * _E16
            if ny > 0:
                return ("brewing_stand_base",
                        _BREW_R["plat_u_e" if east else
                                ("plat_u_nw" if nw else "plat_u_sw")])
            if ny < 0:
                return ("brewing_stand_base",
                        _BREW_R["plat_d_e" if east else
                                ("plat_d_nw" if nw else "plat_d_sw")])
            if nz != 0:
                return ("brewing_stand_base", _BREW_R["plat_s_z"])
            # x 面：官方按板分窗（东 5..11、西北 1..7、西南 9..15）
            return ("brewing_stand_base",
                    _BREW_R["plat_s_x_e" if east else
                            ("plat_s_x_nw" if nw else "plat_s_x_sw")])
        # 杆：侧面窄条窗、up/down 端面
        if ny > 0:
            return (mat, _BREW_R["rod_e_up"])
        if ny < 0:
            return (mat, _BREW_R["rod_e_dn"])
        return (mat, _BREW_R["rod_s"])
    if kind == "flowerpot":
        # 官方 flower_pot.json：壁侧 uv v 10..16 行（陶壁横带）；
        # 内底 up = #dirt。壁顶窄条/内壁窄面沿用全图（1px 面，
        # 拉伸观感可忽略）；壁面统一用 flower_pot 直提图（基键
        # potted cactus 为盆+植株合成图，布局与壁窗不对应）。
        if box is not None and box[1] <= 1e-9 and box[4] <= 4 * _E16 + 1e-9:
            if ny > 0:
                return ("dirt", None)
            return ("flower_pot", _FPOT_S)
        if ny != 0:
            return ("flower_pot", None)
        return ("flower_pot", _FPOT_S)
    if kind == "candle":
        # 蜡烛柱（template_candle.json）：侧 uv[0,8,2,14] 顶
        # uv[0,6,2,8] 底 uv[0,14,2,16]（2x6x2 柱）
        if ny > 0:
            return (mat, _RU(0, 6, 2, 8))
        if ny < 0:
            return (mat, _RS(0, 14, 2, 16))
        return (mat, _RS(0, 8, 2, 14))
    if kind == "torch":
        # 火把（template_torch / template_torch_wall，torch.png）：
        # 立式杆单盒官方窗（侧 uv[7,6,9,16]、up 焦头 [7,6,9,8]、
        # down [7,13,9,15]）。墙上斜杆三级台阶段（block_shapes
        # _torch：y 3.5..6.5/6.5..10.5/10.5..13.5）按段等分杆身
        # 纹理带（官方 v 行 6..16 = 杆顶..杆底）：下段 13..16、
        # 中段 9..13、顶段 6..9；段间环面取衔接行 ±1 窄带。
        if box is None or box[1] <= 1e-9:            # 立式杆（y0=0）
            if ny > 0:
                return (mat, _RU(7, 6, 9, 8))
            if ny < 0:
                return (mat, _RS(7, 13, 9, 15))
            return (mat, _RS(7, 6, 9, 16))
        if box[1] <= 4 * _E16:                       # 下段（y0=3.5/16）
            if ny > 0:
                return (mat, _RS(7, 12, 9, 14))      # 衔接环面（行13）
            if ny < 0:
                return (mat, _RS(7, 14, 9, 16))      # 杆底贴墙端
            return (mat, _RS(7, 13, 9, 16))          # 杆身带
        if box[1] <= 7 * _E16:                       # 中段（y0=6.5/16）
            if ny > 0:
                return (mat, _RS(7, 8, 9, 10))       # 衔接环面（行9）
            if ny < 0:
                return (mat, _RS(7, 12, 9, 14))      # 衔接环面（行13）
            return (mat, _RS(7, 9, 9, 13))           # 杆身带
        if ny > 0:
            return (mat, _RU(7, 6, 9, 8))            # 顶段端面=焦头
        if ny < 0:
            return (mat, _RS(7, 8, 9, 10))           # 衔接环面（行9）
        return (mat, _RS(7, 6, 9, 9))                # 顶段杆身带
    if kind == "lantern":
        r = _LANTERN_R
        if box is not None and box[1] >= 7 * _E16 - 1e-9 and \
                box[3] - box[0] < 5 * _E16:
            # 顶盖盒（4x2x4）：up 用 cap_u，侧/下用 cap_s
            if ny > 0:
                return (mat, r["cap_u"])
            return (mat, r["cap_s"])
        # 主体盒（6x7x6）：up/down 用 body 窗，侧用 side
        if ny > 0:
            return (mat, r["body_u"])
        if ny < 0:
            return (mat, r["body_d"])
        return (mat, r["side"])
    if kind == "erod":
        r = _EROD_R
        if box is not None and box[3] - box[0] <= 4 * _E16 + 1e-9 \
                and box[4] - box[1] <= 4 * _E16 + 1e-9 \
                and box[5] - box[2] <= 4 * _E16 + 1e-9:
            # 底座盒（4x4x4 或其旋转变体——四向最长边 4/16）
            if ny > 0:
                return (mat, r["base_u"])
            if ny < 0:
                return (mat, r["base_d"])
            return (mat, r["base_s"])
        # 杆盒（2x15x2 / 水平 15x2x2）
        if ny > 0:
            return (mat, r["pole_u"])
        if ny < 0:
            return (mat, r["pole_u"])
        return (mat, r["pole_s"])
    if kind == "dhead":
        # 12³ 单盒：facing = 脸朝向；脸面/背侧面/顶/底
        key = _DHEAD_FACES
        f = rest.partition(":")[0] or "n"
        if ny > 0:
            return (key["top"], None)
        if ny < 0:
            return (key["bot"], None)
        face_n = _FACE_N[f]
        if normal == face_n:
            return (key["face"], None)
        # 非 facing 侧面统一侧鳞图；f=n 时世界 west 面即模型 west
        # 区（west 图与 side 同为鳞片，朝向旋转后不特判）
        if normal == (-1, 0, 0) and f == "n":
            return (key["west"], None)
        return (key["side"], None)
    if kind == "bed":
        # 顶面分区（键图 = 垫顶整块：上半枕带行 0..7、下半毯区）。
        # facing = 床头朝向（wiki：head 块在 facing 端、枕贴床头端）。
        # 顶面 pu=x/pv=z：f=s 枕南（v 正向窗）、f=n 枕北（v 反向）；
        # f=e/w 枕沿 x —— swap 窗（u 承载图 v 轴、v 承载图 u 轴）。
        # foot 无枕：v 窗取毯区 (0,0.5)，各向同性无需交换。
        # 白名单 = 全 9 色（村庄 7 色床 + 白/红；分色合成图见
        # bed <color> top.png）。
        part, _, f = rest.partition(":")
        if ny <= 0 or mat not in _BED_MATS:
            return (None, None)
        key = "bed " + mat.split()[0] + " top"
        if part == "head":
            return (key, _BED_HEAD_R.get(f, _BED_HEAD_R["s"]))
        return (key, _BED_FOOT_R)
    if kind == "wsign":
        # 板盒：正面（贴边反侧 = 朝外法线）用 oak sign board 窗
        # (0, 0.25, 1, 0.75)——合成图板内容行 4..12，按侧式换算
        # v=(1-12/16, 1-4/16)=(0.25,0.75)，pv=0（板底）-> 行 12
        # = 板内容底，方向正确。背面/边沿用基键（oak wall sign）。
        att = rest or "n"
        outward = {"n": (0, 0, 1), "s": (0, 0, -1),
                   "e": (-1, 0, 0), "w": (1, 0, 0)}[att]
        if normal == outward:
            return ("oak sign board", (0.0, 0.25, 1.0, 0.75))
        return (None, None)
    if kind == "pisth":
        # 活塞头（jar 实证 template_piston_head.json +
        # piston_head[_sticky].json：#platform = sticky ?
        # piston_top_sticky（外端推板绿粘液面）: piston_top、
        # #unsticky = piston_top（内端木板顶）、#side = piston_side）：
        # 平台 facing 端=platform 全图、内端（-facing）=unsticky
        # 全图、薄向两端=side 4px 带；轴盒（16 长越界咬合后沿伸出
        # 向满格）：柱面=side 顶带（官方 west uv[16,4,0,0] 石框灰），
        # 端面官方无 faces -> 跳面哨兵（消面机制管不到：轴端面与
        # 平台内端面/本体缩进面法线相反而共面）。
        parts = rest.split(":")
        f = parts[0] if parts[0] in ("n", "s", "e", "w", "u", "d") \
            else "n"
        sticky = "s" in parts[1:]
        if box is None:
            return (None, None)
        axis_face = {"n": (0, 0, -1), "s": (0, 0, 1), "e": (1, 0, 0),
                     "w": (-1, 0, 0), "u": (0, 1, 0),
                     "d": (0, -1, 0)}[f]
        dims = (box[3] - box[0], box[4] - box[1], box[5] - box[2])
        fulls = sum(1 for d in dims if d >= 1.0 - 1e-9)
        if fulls >= 2:
            # 平台盒（两轴满格 + 薄向 4px）：除 ±facing 大面外，
            # 其余四面官方均 uv[0,0,16,4] 4px 带拉伸
            if normal == axis_face:
                # platform 外端：sticky 头=绿粘液面
                return ("piston_top_sticky" if sticky
                        else "piston_top", None)
            if normal == (-axis_face[0], -axis_face[1],
                          -axis_face[2]):
                # unsticky 内端整面（木板顶面）
                return ("piston_top", None)
            return ("piston_side", _RS(0, 0, 16, 4))
        # 轴盒（单满格轴 = 伸出向）：端面官方无 faces -> 跳面哨兵
        if normal == axis_face or normal == (-axis_face[0],
                                             -axis_face[1],
                                             -axis_face[2]):
            return (_SKIP_FACE, None)
        return ("piston_side", _RS(16, 4, 0, 0))
    if kind == "lectern":
        # 讲台用橡木板近似：全面基键（mat = oak planks）
        return (None, None)
    return (None, None)


def _rect(b: tuple, axis: int) -> tuple:
    """AABB(b) 在 axis 法向平面上的投影矩形 (u0, v0, u1, v1)。"""
    if axis == 0:                         # x 面：投影 (z, y)
        return (b[2], b[1], b[5], b[4])
    if axis == 1:                         # y 面：投影 (x, z)
        return (b[0], b[2], b[3], b[5])
    return (b[0], b[1], b[3], b[4])       # z 面：投影 (x, y)


def _covered(inner: tuple, outer: tuple) -> bool:
    """投影矩形 inner 是否被 outer 完全覆盖（容差 1e-9）。"""
    return outer[0] <= inner[0] + 1e-9 and outer[2] >= inner[2] - 1e-9 \
        and outer[1] <= inner[1] + 1e-9 and outer[3] >= inner[3] - 1e-9


# 六向面：法线 + 该面 4 顶点（单位块角点，逆时针 = 朝外）
# -y 绕序由 _box_face 兜底分支叉积验证（(e1-e0)x(e2-e0) 朝 -y）
_FACES = {
    "+y": ((0, 1, 0),
           ((0, 1, 1), (1, 1, 1), (1, 1, 0), (0, 1, 0))),
    "-y": ((0, -1, 0),
           ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1))),
    "+x": ((1, 0, 0),
           ((1, 0, 1), (1, 0, 0), (1, 1, 0), (1, 1, 1))),
    "-x": ((-1, 0, 0),
           ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0))),
    "+z": ((0, 0, 1),
           ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))),
    "-z": ((0, 0, -1),
           ((1, 0, 0), (0, 0, 0), (0, 1, 0), (1, 1, 0))),
}

# 六邻方向元组（内部体素快速跳过用，顺序固定便于对拍）
_NEIGHBOR_DIRS = ((0, 1, 0), (0, -1, 0), (1, 0, 0),
                   (-1, 0, 0), (0, 0, 1), (0, 0, -1))

# 植物（SHAPE_PLANT）对角 quad 表：MC template_cross 两条竖直对
# 角平面，各正/反两个 quad（视口开 GL_CULL_FACE，绕序 = 正面
# CCW；同视角被剔侧不进光栅化，共面无深度冲突）。法线 (0,0,±1)
# 光照均匀；UV 走 _emit_quad rect=None 的 u=x/v=y 世界平铺 = 整
# 格纹理（shader fract 取样）。首角贴 y 顶/底、z 前/后格界混
# 合：quad_pos 分桶（nzv≠0 轴 ceil-1/floor，其余轴 4 角 min
# floor）回本格，且 chunk AABB 的 maxy/miny/maxz/minz 各有首
# 角喂到。
_PLANT_QUADS = (
    # 面 A（x=z 对角平面）
    (((1, 1, 1), (0, 1, 0), (0, 0, 0), (1, 0, 1)), (0, 0, 1)),
    (((0, 0, 0), (0, 1, 0), (1, 1, 1), (1, 0, 1)), (0, 0, -1)),
    # 面 B（x+z=1 对角平面）
    (((0, 1, 1), (0, 0, 1), (1, 0, 0), (1, 1, 0)), (0, 0, 1)),
    (((1, 0, 0), (0, 0, 1), (0, 1, 1), (1, 1, 0)), (0, 0, -1)),
)


def _boxes_with_arms(vox: dict, pos: tuple, shape) -> list:
    """某位置形状的完整 AABB 列表（post/pane/wall 含连通臂）。

    自身面生成与邻居贴界面矩形共用，保证接缝判定对称。
    """
    boxes = list(bs.shape_boxes(shape))
    if shape:
        kind = shape.partition(":")[0]
        if kind in ("post", "pane", "wall"):
            x, y, z = pos
            nbs = tuple(bs.connect_kind(vox.get(p))
                        for p in ((x, y, z - 1), (x, y, z + 1),
                                  (x + 1, y, z), (x - 1, y, z)))
            boxes.extend(bs.connect_arms(kind, nbs))
    return boxes


def build_occlusion(vox: dict) -> dict:
    """逐 16³ section 可见性矩阵（MC 洞穴剔除构建期同款，加载期一次）。

    移植自 1.21.11 反编译源码（官方映射）：
    - VisGraph.resolve()：opaque 格标阻挡 -> 从 6 个外表面边缘的
      空格 flood fill -> 每个空域记录接触到的外表面方向 ->
      6×6 bool 矩阵（同空域接触的两面互相可见）。特例：
      opaque < 256 -> 全 true；全实心 -> 全 false。
      isSolidRender 对应：实心整格且非透明（与 _mat_shape 一致）；
    - SectionCompiler.compile：全 section 独立计算，无跨 section 信息。

    输出 {"sections": {(sx,sy,sz)->matrix}, "bounds": (...)}，
    matrix 为 36 位 int（face_from*6+face_to 位；1=可见）。
    方向用原版 Direction.values() 序：(0=-Y, 1=+Y, 2=-Z, 3=+Z,
    4=-X, 5=+X)。
    """
    blocked = set()
    xs = ys = zs = None
    for (x, y, z), v in vox.items():
        mat, shape = _mat_shape(v)
        if not shape and mat not in _TRANSPARENT_MATS:
            blocked.add((x, y, z))
        if xs is None:
            xs = (x, x)
            ys = (y, y)
            zs = (z, z)
        else:
            if x < xs[0]:
                xs = (x, xs[1])
            elif x > xs[1]:
                xs = (xs[0], x)
            if y < ys[0]:
                ys = (y, ys[1])
            elif y > ys[1]:
                ys = (ys[0], y)
            if z < zs[0]:
                zs = (z, zs[1])
            elif z > zs[1]:
                zs = (zs[0], z)
    if xs is None:
        return {"sections": {}, "bounds": (0, 0, 0, -1, -1, -1)}
    x0, x1 = xs
    y0, y1 = ys
    z0, z1 = zs
    # 体素 -> 16³ section 网格（负坐标 //16 即 floor，与
    # SectionPos.blockToSectionCoord 一致）；格内相对坐标用 &15
    sec_grid: dict = {}
    for (x, y, z) in blocked:
        sec_grid.setdefault((x // 16, y // 16, z // 16), set()).add(
            (x & 15, y & 15, z & 15))
    sections: dict = {}
    # VisGraph.resolve 移植：从 6 个外表面边缘空格 flood fill，
    # addEdges 记录每个空域接触的外表面方向，VisibilitySet.add
    # 对同空域的方向对双向置位。位序 = 原版 Direction ordinal：
    # 0=-Y 1=+Y 2=-Z 3=+Z 4=-X 5=+X；idx = x<<0|y<<8|z<<4
    for skey, cells in sec_grid.items():
        opaque = set()
        for (rx, ry, rz) in cells:
            opaque.add(rx | (ry << 8) | (rz << 4))
        if len(opaque) < 256:
            sections[skey] = (1 << 36) - 1   # 稀疏/空 section 全可见
            continue
        if len(opaque) >= 4096:
            sections[skey] = 0               # 全实心 -> 全不可见
            continue
        matrix = 0
        seen: set = set()
        # 6 外表面：(axis, side, face_dir_ordinal)
        # axis 0=x 1=y 2=z；side 0=负向面 15=正向面；face_dir：
        # x- → -X(4), x+ → +X(5), y- → -Y(0), y+ → +Y(1),
        # z- → -Z(2), z+ → +Z(3)
        for ax, side, fd in ((0, 0, 4), (0, 15, 5), (1, 0, 0),
                             (1, 15, 1), (2, 0, 2), (2, 15, 3)):
            for a in range(16):
                for b in range(16):
                    rel = [0, 0, 0]
                    rel[ax] = side
                    rel[(ax + 1) % 3] = a
                    rel[(ax + 2) % 3] = b
                    idx = rel[0] | (rel[1] << 8) | (rel[2] << 4)
                    if idx in opaque or idx in seen:
                        continue
                    # BFS 本空域（含边缘接触面收集）
                    comp_faces = 1 << fd    # 种子格在本边缘面上
                    q = [idx]
                    seen.add(idx)
                    while q:
                        cur = q.pop()
                        cx = cur & 15
                        cy = (cur >> 8) & 15
                        cz = (cur >> 4) & 15
                        if cx == 0:
                            comp_faces |= 1 << 4   # WEST
                        elif cx == 15:
                            comp_faces |= 1 << 5   # EAST
                        if cy == 0:
                            comp_faces |= 1 << 0   # DOWN
                        elif cy == 15:
                            comp_faces |= 1 << 1   # UP
                        if cz == 0:
                            comp_faces |= 1 << 2   # NORTH
                        elif cz == 15:
                            comp_faces |= 1 << 3   # SOUTH
                        for nx, ny, nz in (
                                (cx + 1, cy, cz), (cx - 1, cy, cz),
                                (cx, cy + 1, cz), (cx, cy - 1, cz),
                                (cx, cy, cz + 1), (cx, cy, cz - 1)):
                            if not (0 <= nx < 16 and 0 <= ny < 16
                                    and 0 <= nz < 16):
                                continue
                            ni = nx | (ny << 8) | (nz << 4)
                            if ni not in opaque and ni not in seen:
                                seen.add(ni)
                                q.append(ni)
                    # 同空域接触的方向对 -> 双向置位
                    f = comp_faces
                    while f:
                        low = f & -f
                        i1 = low.bit_length() - 1
                        g = f
                        while g:
                            low2 = g & -g
                            i2 = low2.bit_length() - 1
                            matrix |= 1 << (i1 + 6 * i2)
                            matrix |= 1 << (i2 + 6 * i1)
                            g ^= low2
                        f ^= low
        sections[skey] = matrix
    return {"sections": sections,
            "bounds": (x0, y0, z0, x1, y1, z1)}


def build_mesh(vox: dict) -> dict:
    """体素 -> 绘制网格（共享顶点 + 材质槽区间）。

    返回 {"verts": [x,y,z,u,v,nx,ny,nz,...], "idx": [...],
          "slots": [(idx_start, idx_count), ...],
          "slot_mat": [mat, ...]}。
    - 体素值两种形态：纯字符串 = 整格；(纹理键, 形状码) = 非完整
      方块（半砖/楼梯/门/活板门/栅栏/箱子/火把等，几何见
      block_shapes.shape_boxes）；
    - 形状按 AABB 逐面生成（面法线朝外），面剔除采用“共面 +
      投影覆盖”精确判据：只有本 AABB 贴格界、且邻居在同格界处
      有贴界面完全遮盖本面投影时才剔（修复半砖/楼梯下方看穿：
      半砖顶面 y=0.5 不贴格界永不被上方整格误剔）；
    - 同方块内其他 AABB 同侧同平面完全覆盖时剔小面（如锅壁
      贴底），避免重复绘制；
    - 栅栏/墙/玻璃板按邻居连通类别自动补横臂（connect_arms），
      臂 AABB 合入本方块面生成（臂端贴邻居格界时被剔）；
    - 底面(-y) 正常生成（旁观者模式可飞到下方看悬空/外沿
      底面）；实心堆叠内部共面覆盖仍被剔（贴地土也方下半面
      会被下方方块剔除，只有真悬空/暴露的底面入网格）；
    - 面剔除透明感知：实心邻水/玻璃/冰保留面（透过透明材可见）；
    - UV 为世界坐标平铺值（0..N），图集换算在视口着色器侧完成。

    性能：按体素值缓存 _mat_shape / 基础 AABB / 邻居贴界面矩形
    （值均为不可变元组；bastion 级模型 ~30 万次重复归一化/投影
    降为「每不同体素值一次」）；整格实心体素若六邻全为整格实心
    非透明则整体跳过（面剔除的必然结果，bastion 实测 ~60% 体素
    命中）；post/pane/wall 的连通臂随邻居变化，仍逐位现算不走
    缓存；语义与逐位计算完全一致。
    """
    slot_verts: dict = {}
    slot_index: dict = {}
    # 体素值级缓存（键 = 体素值，str 或 (mat, shape) 元组，均可哈希）
    v_ms: dict = {}        # v -> (mat, shape)                （_mat_shape）
    v_boxes: dict = {}     # v -> 基础 AABB 元组（不含连通臂）（shape_boxes）
    v_nb: dict = {}        # (v, axis, sign) -> 贴界面矩形元组
    for (x, y, z), v in vox.items():
        info = v_ms.get(v)
        if info is None:
            info = v_ms[v] = _mat_shape(v)
        mat, shape = info
        # 槽位先建（与旧路径逐字节一致：完全埋没的异材体素也会
        # 留下 0 索引空槽，如 ancient_city 的 dirt；无渲染效果但
        # 保持 mesh 结构严格等价）
        arr = slot_verts.setdefault(mat, [])
        idx = slot_index.setdefault(mat, [])
        if not shape and mat not in _TRANSPARENT_MATS:
            # 内部体素快速跳过：自身整格实心非透明且六邻全为整格
            # 实心非透明时，六个面在原逐面路径下必然全部被剔（贴
            # 格界 + 满格贴界面矩形完全覆盖投影，数学等价）；任何
            # 透明/异形邻居都不满足条件走原路径，保守方向安全。
            # bastion 实测 ~60% 体素命中，面迭代 -60%。
            inside = True
            for d in _NEIGHBOR_DIRS:
                nb_v = vox.get((x + d[0], y + d[1], z + d[2]))
                if nb_v is None:
                    inside = False
                    break
                nb_info = v_ms.get(nb_v)
                if nb_info is None:
                    nb_info = v_ms[nb_v] = _mat_shape(nb_v)
                if nb_info[1] or nb_info[0] in _TRANSPARENT_MATS:
                    inside = False
                    break
            if inside:
                continue
        base_boxes = v_boxes.get(v)
        if base_boxes is None:
            base_boxes = v_boxes[v] = bs.shape_boxes(shape)
        boxes = base_boxes
        if shape:
            kind = shape.partition(":")[0]
            if kind == "plant":
                # 农作物/花草（SHAPE_PLANT）：对角 X 专用路径
                # （_PLANT_QUADS 注释详述绕序/法线/UV/分桶语义），
                # 不走 AABB 面循环
                for pq, pn in _PLANT_QUADS:
                    _emit_quad(arr, idx, x, y, z, pq, pn)
                continue
            if kind in ("post", "pane", "wall"):
                # 连通臂随四向邻居变化：逐位现算（基础 AABB 复用缓存）
                boxes = list(base_boxes)
                nbs = tuple(bs.connect_kind(vox.get(p))
                            for p in ((x, y, z - 1), (x, y, z + 1),
                                      (x + 1, y, z), (x - 1, y, z)))
                boxes.extend(bs.connect_arms(kind, nbs))
        for face, (normal, corners) in _FACES.items():
            nx, ny, nz = normal
            axis = 0 if nx else (1 if ny else 2)
            pos_sign = ny or nx or nz
            # 邻居贴界面矩形（剔除候选）：透明异材不剔（透过可见）
            nb_rects = None
            nb_pos = (x + nx, y + ny, z + nz)
            nb_v = vox.get(nb_pos)
            if nb_v is not None:
                nb_info = v_ms.get(nb_v)
                if nb_info is None:
                    nb_info = v_ms[nb_v] = _mat_shape(nb_v)
                nb_mat, nb_shape = nb_info
                if not (nb_mat in _TRANSPARENT_MATS and mat != nb_mat):
                    nb_key = (nb_v, axis, pos_sign)
                    nb_rects = v_nb.get(nb_key)
                    if nb_rects is None:
                        rects = []
                        if nb_shape and nb_shape.partition(":")[0] in (
                                "post", "pane", "wall"):
                            # 连通类：臂随其四向邻居变化，逐位现算
                            for c in _boxes_with_arms(vox, nb_pos, nb_shape):
                                if pos_sign > 0 and c[axis] <= 1e-9:
                                    rects.append(_rect(c, axis))
                                elif pos_sign < 0 \
                                        and c[axis + 3] >= 1.0 - 1e-9:
                                    rects.append(_rect(c, axis))
                        else:
                            nb_base = v_boxes.get(nb_v)
                            if nb_base is None:
                                nb_base = v_boxes[nb_v] = \
                                    bs.shape_boxes(nb_shape)
                            for c in nb_base:
                                if pos_sign > 0 and c[axis] <= 1e-9:
                                    rects.append(_rect(c, axis))
                                elif pos_sign < 0 \
                                        and c[axis + 3] >= 1.0 - 1e-9:
                                    rects.append(_rect(c, axis))
                        nb_rects = v_nb[nb_key] = tuple(rects)
            for b in boxes:
                # 本 AABB 在该侧是否贴格界（不贴界的面不可能与
                # 邻居共面；同方块内共面覆盖仍可能）
                plane = b[axis + 3] if pos_sign > 0 else b[axis]
                flush = plane >= 1.0 - 1e-9 if pos_sign > 0 \
                    else plane <= 1e-9
                covered = False
                if flush and nb_rects:
                    r = _rect(b, axis)
                    for nr in nb_rects:
                        if _covered(r, nr):
                            covered = True
                            break
                if not covered:
                    # 同方块内其他 AABB 同侧同平面完全覆盖 → 剔
                    # （内容相等者除外：完全重合面深度一致，重复
                    # 绘制无害，互剔会全光）
                    r = _rect(b, axis)
                    for b2 in boxes:
                        if b2 == b or b2[axis + 3] != plane:
                            continue
                        if _covered(r, _rect(b2, axis)):
                            covered = True
                            break
                if covered:
                    continue
                # 同格水+岩浆（废弃传送门水下岩浆）：岩浆在水中
                # 不可见（岩浆重于水沉底），让位于水——跳过岩浆面
                if mat == "lava" and vox.get((x, y + 1, z)) is not None \
                        and _mat_shape(vox.get((x, y + 1, z)))[0] == "water":
                    continue
                fmat, rect = _face_mat(mat, shape, normal, b)
                if fmat == _SKIP_FACE:
                    continue          # 官方无 faces：面不生成
                if fmat is None:
                    fmat, rect = mat, None
                if fmat == mat:
                    _emit_quad(arr, idx, x, y, z,
                               _box_face(b, normal), normal, rect)
                else:
                    _emit_quad(slot_verts.setdefault(fmat, []),
                               slot_index.setdefault(fmat, []),
                               x, y, z, _box_face(b, normal), normal,
                               rect)
    verts_all, idx_all, slots, slot_mat = [], [], [], []
    trans_idx: list = []     # 半透明槽索引（垫尾，视口第二遍）
    quad_slot: list = []      # 每 quad 槽序（quad -> slots 下标，烘焙用）
    quad_pos: list = []       # 每 quad 所在方块（世界格坐标，chunk 排序用）
    # 拼接顺序：非半透明槽按字母序，半透明槽强制垫底——主体顶点
    # 物理连续、半透明顶点恒在尾部（视口按 (trans_off, trans_count)
    # 索引区间整体第二遍绘制；字母序下若插在主体中部会让 quad_slot
    # 物理对位与半透明索引引用双双错位，如 trial 的 water<white bed）。
    # 半透明槽照常注册 slots/slot_mat/quad_slot（tile 烘焙统一走
    # quad_slot），只把索引挪到尾部。
    ordered_mats = [m for m in sorted(slot_verts)
                    if m not in _TRANSLUCENT_MATS]
    ordered_mats.extend(m for m in sorted(slot_verts)
                        if m in _TRANSLUCENT_MATS)
    for mat in ordered_mats:
        vert_start = len(verts_all) // 8
        verts_all.extend(slot_verts[mat])
        idx_start = len(idx_all)
        qi = len(slots)
        slots.append((idx_start, len(slot_index[mat])))
        slot_mat.append(mat)
        # 本槽 quad 的槽序（_emit_quad 每 quad 追加 32 浮点
        # = 4 顶点，quad 数 = 顶点数 // 4，按顶点顺序对应）
        for _v in range(len(slot_verts[mat]) // 32):
            quad_slot.append(qi)
        if mat in _TRANSLUCENT_MATS:
            # 半透明索引不进主体：收集后统一挪到索引尾部，
            # 视口按 (trans_off, trans_count) 半透明第二遍绘制
            for i in slot_index[mat]:
                trans_idx.append(i + vert_start)
        else:
            for i in slot_index[mat]:
                idx_all.append(i + vert_start)
    # 每 quad 的方块坐标：逐槽回放（顶点 8 列 x,y,z 在 0..2 列）。
    # 取「面所属格」而非角点：法线轴取朝面一侧（+向 ceil-1 / -向
    # floor，面在该轴 4 角共面，首角值即平面值）；其余轴取 4 角
    # 最小值 floor——首角不保证最小（如顶面首角 xz 组合任意），
    # 取首角 floor 会让 y 跨 16 界的竖直面错分到邻层 section 的
    # chunk（退化组装 bastion 实测 (0,0,0) 键与 chunk 10 AABB
    # 不相交）。分桶必须与遮挡域的体素格划分一致。
    for qi, mat in enumerate(slot_mat):
        vv = slot_verts[mat]
        for k in range(0, len(vv), 32):      # 32 浮点 = 1 quad
            nxv, nyv, nzv = vv[k + 5], vv[k + 6], vv[k + 7]
            gx = math.floor(min(vv[k], vv[k + 8], vv[k + 16],
                                vv[k + 24]))
            gy = math.floor(min(vv[k + 1], vv[k + 9], vv[k + 17],
                                vv[k + 25]))
            gz = math.floor(min(vv[k + 2], vv[k + 10], vv[k + 18],
                                vv[k + 26]))
            if nxv > 0:
                gx = math.ceil(vv[k]) - 1
            elif nxv < 0:
                gx = math.floor(vv[k])
            if nyv > 0:
                gy = math.ceil(vv[k + 1]) - 1
            elif nyv < 0:
                gy = math.floor(vv[k + 1])
            if nzv > 0:
                gz = math.ceil(vv[k + 2]) - 1
            elif nzv < 0:
                gz = math.floor(vv[k + 2])
            quad_pos.append((int(gx), int(gy), int(gz)))
    trans_off = len(idx_all)
    idx_all.extend(trans_idx)
    # ---- chunk 空间重排（MC 式视锥剔除基础）----
    # 主体 idx 每 6 索引一个 quad，按 quad 所在方块坐标 16³ 分桶
    # 排序；桶 = 视口逐 chunk 剔除的绘制单元。半透明区间保持在
    # 尾部不动（半透明第二遍整体绘制，不参与 chunk 剔除）。
    n_q = len(idx_all) // 6 - len(trans_idx) // 6
    idx_np_pre = np.asarray(idx_all, dtype=np.int64)
    # quad_slot 全量输出（含尾段半透明槽）：视口 tile 烘焙统一按
    # quad→槽号表赋值，半透明顶点不再需要特判；主体段（[:n_q]）
    # 与 chunk 重排域对位，仅重排逻辑使用
    qs_all = np.asarray(quad_slot, dtype=np.int64)
    qs = qs_all[:n_q]
    qp = np.asarray(quad_pos[:n_q], dtype=np.int64)
    # 排序键：chunk 坐标 (cy,cx,cz) 主序（argsort 于首 chunk 出现
    # 序，即 lexsort 后的去重序）。保持 slots/chunks 物理序 =
    # 槽拼接序 / chunk 首现序：遮挡域的 chunk 序号与之共用一套
    # 物理序（域 chunk 集合成员 = chunks 列表下标），烘焙与域
    # 查表都无需二次映射。块内 (y,x,z) 次序不重排（同 chunk 内
    # quad 顺序无绘制语义）。
    if n_q:
        ck_flat = (qp[:, 0] // 16) * 1000003 \
            + (qp[:, 1] // 16) * 1009 + qp[:, 2] // 16
        uniq, first = np.unique(ck_flat, return_index=True)
        order = np.argsort(first)             # 按 chunk 首现序
        cat = np.empty(len(uniq), dtype=np.int64)
        cat[order] = np.arange(len(uniq))
        key = cat[np.searchsorted(uniq, ck_flat)]
        perm = np.argsort(key, kind="stable")
    else:
        perm = np.zeros(0, np.int64)
    body = idx_np_pre[:n_q * 6].reshape(n_q, 6)[perm] \
        if n_q else idx_np_pre[:0].reshape(0, 6)
    idx_np = np.concatenate(
        (body.reshape(-1), idx_np_pre[n_q * 6:])).astype(
        np.uint16 if (not len(idx_all) or max(idx_all) < 65536)
        else np.uint32)
    # chunk 边界（重排后扫描）：同 (cx,cy,cz) 的 quad 连续区间
    nq_sorted = qp[perm] if n_q else np.zeros((0, 3), np.int64)
    chunk_key = (nq_sorted[:, 0] // 16) * 1000003 \
        + (nq_sorted[:, 1] // 16) * 1009 + nq_sorted[:, 2] // 16 \
        if n_q else np.zeros(0, np.int64)
    # chunks 输出：(idx_off, idx_count, minx,miny,minz, maxx,maxy,maxz)
    # chunk 序号 = chunks 列表下标 = 域 chunk 集合成员（物理序）
    chunks: list = []
    if n_q:
        bounds = np.nonzero(np.diff(chunk_key))[0] + 1
        starts = np.concatenate(([0], bounds))
        ends = np.concatenate((bounds, [n_q]))
        # 每 quad AABB 由其 4 角顶点推出（面共面，4 角即覆盖范围；
        # x,y,z 在 8 列顶点的 0/1/2 列，flat 偏移 = vid*8）。
        # 注意必须取齐 4 个角：_box_face 四角布局中第 0/3 角是矩形
        # 相邻角（如 +y 面 x 恒等于 b[0]），只用两角 min/max 会把
        # AABB 退化成一条线——视锥剔除在特定视角误删整 chunk，
        # 钟架等小结构整块消失露出其后水面（实测 dist=10/p55）。
        v_np = np.asarray(verts_all, dtype=np.float32).reshape(-1, 8)
        q0 = body[:, 0]
        q1 = body[:, 1]
        q2 = body[:, 2]
        q3 = body[:, 3]
        qx = np.minimum(np.minimum(v_np[q0, 0], v_np[q1, 0]),
                        np.minimum(v_np[q2, 0], v_np[q3, 0]))
        qx2 = np.maximum(np.maximum(v_np[q0, 0], v_np[q1, 0]),
                         np.maximum(v_np[q2, 0], v_np[q3, 0]))
        qy = np.minimum(np.minimum(v_np[q0, 1], v_np[q1, 1]),
                        np.minimum(v_np[q2, 1], v_np[q3, 1]))
        qy2 = np.maximum(np.maximum(v_np[q0, 1], v_np[q1, 1]),
                         np.maximum(v_np[q2, 1], v_np[q3, 1]))
        qz = np.minimum(np.minimum(v_np[q0, 2], v_np[q1, 2]),
                        np.minimum(v_np[q2, 2], v_np[q3, 2]))
        qz2 = np.maximum(np.maximum(v_np[q0, 2], v_np[q1, 2]),
                         np.maximum(v_np[q2, 2], v_np[q3, 2]))
        for s, e in zip(starts, ends):
            i0 = int(s * 6)
            i1 = int(e * 6)
            chunks.append((
                i0, i1 - i0,
                float(qx[s:e].min()), float(qy[s:e].min()),
                float(qz[s:e].min()), float(qx2[s:e].max()),
                float(qy2[s:e].max()), float(qz2[s:e].max())))
    # ---- 逐 section 可见性矩阵（MC 洞穴剔除构建期同款）----
    # sections 字典键 = 体素 16³ section 键，与 build_mesh 的 chunk
    # 重排同一划分。chunk_at：section 键 -> chunks 列表下标（键用
    # 重排扫描的「面所属格」16³ 键——不能用 AABB min 反推：跨层
    # 平面的 quad（如 y=15 格顶面在 y=16.0 平面）会让纯边界 chunk
    # 的 AABB min 跳到上层（16.0//16=1），抢注上层 chunk 的键，
    # 真 chunk 从映射表消失 → 室内成片缺渲染（实测 y 层 1 缺
    # 22/25）。运行期（视口）按眼 section BFS 传播求可见 section
    # 集，再经 chunk_at 换算成交集（旧全局连通域方案已废弃，
    # 反编译证实游戏无此语义）。
    occl = build_occlusion(vox)
    chunk_at: dict = {}
    if n_q:
        cq16 = nq_sorted // 16
        for si, (s, _e) in enumerate(zip(starts, ends)):
            chunk_at[(int(cq16[s, 0]), int(cq16[s, 1]),
                      int(cq16[s, 2]))] = si
    occl["chunk_at"] = chunk_at
    verts_np = np.array(verts_all, dtype=np.float32)
    return {"verts": verts_np, "idx": idx_np,
            "slots": slots, "slot_mat": slot_mat,
            "quad_slot": qs_all.tolist(),
            "trans_off": trans_off, "trans_count": len(trans_idx),
            "chunks": chunks, "occl": occl}


def _box_face(b: tuple, normal: tuple) -> tuple:
    """AABB(b) 上法线为 normal 侧的面四角（世界相对本地坐标，
    绕序与 _FACES 角点布局同构 = 面法线朝外）。"""
    nx, ny, nz = normal
    if ny > 0:
        # +y：与 _FACES["+y"] 同布局 ((0,1,1),(1,1,1),(1,1,0),(0,1,0))
        return ((b[0], b[4], b[5]), (b[3], b[4], b[5]),
                (b[3], b[4], b[2]), (b[0], b[4], b[2]))
    if ny < 0:
        # -y：与 _FACES["-y"] 同布局 ((0,0,0),(1,0,0),(1,0,1),(0,0,1))
        return ((b[0], b[1], b[2]), (b[3], b[1], b[2]),
                (b[3], b[1], b[5]), (b[0], b[1], b[5]))
    if nx > 0:
        # +x：((1,0,1),(1,0,0),(1,1,0),(1,1,1))
        return ((b[3], b[1], b[5]), (b[3], b[1], b[2]),
                (b[3], b[4], b[2]), (b[3], b[4], b[5]))
    if nx < 0:
        # -x：((0,0,0),(0,0,1),(0,1,1),(0,1,0))
        return ((b[0], b[1], b[2]), (b[0], b[1], b[5]),
                (b[0], b[4], b[5]), (b[0], b[4], b[2]))
    if nz > 0:
        # +z：((0,0,1),(1,0,1),(1,1,1),(0,1,1))
        return ((b[0], b[1], b[5]), (b[3], b[1], b[5]),
                (b[3], b[4], b[5]), (b[0], b[4], b[5]))
    # -z：((1,0,0),(0,0,0),(0,1,0),(1,1,0))
    return ((b[3], b[1], b[2]), (b[0], b[1], b[2]),
            (b[0], b[4], b[2]), (b[3], b[4], b[2]))


def _emit_quad(arr: list, idx: list, x: int, y: int, z: int,
               quad, normal: tuple, rect=None) -> None:
    """四角 quad（世界相对本地坐标）+ 法线入槽：顶点 + 双三角索引。

    rect = None：u/v 走世界平铺整格坐标（旧路径，零变化）；
    非 None：(u0, v0, u1, v1[, swap]) 窗内按面内归一化坐标线性
    插值——顶/底面 pu 沿 x、pv 沿 z；x 面 pu 沿 z、pv 沿 y；z 面
    pu 沿 x、pv 沿 y（与旧 u/v 轴选择一致，保证 uv 窗方向与
    FaceInfo 顶点配对推导对齐）。swap=True（床顶 e/w）：u/v 承
    轴互换（枕带在图 v 轴、映射到世界 x 轴）。
    """
    nx, ny, nz = normal
    base_i = len(arr) // 8
    if rect is None:
        for (cx, cy, cz) in quad:
            if ny != 0:                  # 顶面：u=x, v=z
                u, v = float(x + cx), float(z + cz)
            elif nx != 0:                # 侧面 x：u=z, v=y
                u, v = float(z + cz), float(y + cy)
            else:                        # 侧面 z：u=x, v=y
                u, v = float(x + cx), float(y + cy)
            arr.extend((x + cx, y + cy, z + cz, u, v, nx, ny, nz))
    else:
        swap = len(rect) > 4 and rect[4]
        u0, v0, u1, v1 = rect[0], rect[1], rect[2], rect[3]
        # 面两变轴的角点范围（4 角共面，窗 = AABB 投影）
        if ny != 0:
            ia, ib = 0, 2
        elif nx != 0:
            ia, ib = 2, 1
        else:
            ia, ib = 0, 1
        cs = [(c[ia], c[ib]) for c in quad]
        a0 = min(c[0] for c in cs)
        a1 = max(c[0] for c in cs)
        b0 = min(c[1] for c in cs)
        b1 = max(c[1] for c in cs)
        for (cx, cy, cz) in quad:
            c = (cx, cy, cz)
            pu = (c[ia] - a0) / (a1 - a0) if a1 > a0 else 0.0
            pv = (c[ib] - b0) / (b1 - b0) if b1 > b0 else 0.0
            if swap:
                pu, pv = pv, pu
            u = u0 + (u1 - u0) * pu
            v = v0 + (v1 - v0) * pv
            arr.extend((x + cx, y + cy, z + cz, u, v, nx, ny, nz))
    idx.extend((base_i, base_i + 1, base_i + 2,
                base_i, base_i + 2, base_i + 3))


