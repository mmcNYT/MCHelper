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

网格化 build_mesh：贪心剔除被遮挡面 + 同材质面聚合为绘制槽，
输出共享顶点缓冲 / 索引缓冲 / 槽区间表，供 structure_3dview
上传 GPU 一次构建、多次绘制；未知材质单独成槽（视口回退灰色）。
半砖/楼梯类材质以 "halfheight:<纹理键>" 前缀标记半高渲染。
"""
import gzip
import os
import random
import struct
import threading

from Utils.SeedReverser import structure_blueprints as sb

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
    "minecraft:bedrock": "stone",
    "minecraft:blackstone": "stone",
    "minecraft:polished_blackstone": "stone",
    "minecraft:tuff": "tuff",
    "minecraft:polished_tuff": "polished tuff",
    "minecraft:deepslate": "stone",
    "minecraft:coal_ore": "stone",
    "minecraft:iron_ore": "stone",
    "minecraft:spawner": "stone",
    "minecraft:trial_spawner": "stone",
    "minecraft:vault": "stone",
    "minecraft:ominous_vault": "stone",
    "minecraft:sculk": "stone",
    "minecraft:sculk_catalyst": "stone",
    "minecraft:cobblestone": "cobblestone",
    "minecraft:mossy_cobblestone": "mossy cobblestone",
    "minecraft:cobbled_deepslate": "cobblestone",
    "minecraft:stone_bricks": "stone bricks",
    "minecraft:infested_stone_bricks": "stone bricks",
    "minecraft:bricks": "stone bricks",
    "minecraft:polished_blackstone_bricks": "stone bricks",
    "minecraft:polished_deepslate": "stone bricks",
    "minecraft:deepslate_bricks": "stone bricks",
    "minecraft:deepslate_tiles": "stone bricks",
    "minecraft:reinforced_deepslate": "stone bricks",
    "minecraft:mossy_stone_bricks": "mossy stone bricks",
    "minecraft:infested_mossy_stone_bricks": "mossy stone bricks",
    "minecraft:cracked_stone_bricks": "cracked stone bricks",
    "minecraft:infested_cracked_stone_bricks": "cracked stone bricks",
    "minecraft:cracked_polished_blackstone_bricks": "cracked stone bricks",
    "minecraft:cracked_deepslate_bricks": "cracked stone bricks",
    "minecraft:cracked_deepslate_tiles": "cracked stone bricks",
    "minecraft:chiseled_stone_bricks": "chiseled stone bricks",
    "minecraft:chiseled_polished_blackstone": "chiseled stone bricks",
    "minecraft:chiseled_deepslate": "chiseled stone bricks",
    "minecraft:andesite": "polished andesite",
    "minecraft:polished_andesite": "polished andesite",
    "minecraft:diorite": "polished andesite",
    "minecraft:polished_diorite": "polished andesite",
    "minecraft:granite": "granite",
    "minecraft:polished_granite": "granite",
    # -- 石材楼梯/台阶（半高）/墙 --
    "minecraft:stone_brick_stairs": "halfheight:stone brick stairs",
    "minecraft:polished_blackstone_brick_stairs":
        "halfheight:stone brick stairs",
    "minecraft:deepslate_brick_stairs": "halfheight:stone brick stairs",
    "minecraft:deepslate_tile_stairs": "halfheight:stone brick stairs",
    "minecraft:stone_brick_slab": "halfheight:stone brick slab",
    "minecraft:polished_blackstone_brick_slab":
        "halfheight:stone brick slab",
    "minecraft:deepslate_brick_slab": "halfheight:stone brick slab",
    "minecraft:deepslate_tile_slab": "halfheight:stone brick slab",
    "minecraft:stone_brick_wall": "stone bricks",
    "minecraft:mossy_stone_brick_wall": "mossy stone bricks",
    "minecraft:polished_blackstone_brick_wall": "stone bricks",
    "minecraft:deepslate_brick_wall": "stone bricks",
    "minecraft:deepslate_tile_wall": "stone bricks",
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
    "minecraft:podzol": "dirt",
    "minecraft:grass_block": "grass block top",
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
    "minecraft:stripped_oak_log": "oak log",
    "minecraft:stripped_oak_wood": "oak log",
    "minecraft:spruce_log": "spruce log",
    "minecraft:stripped_spruce_log": "spruce log",
    "minecraft:stripped_spruce_wood": "spruce log",
    "minecraft:dark_oak_log": "dark oak log",
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
    "minecraft:oak_door": "oak planks",
    "minecraft:spruce_door": "spruce door",
    "minecraft:ladder": "ladder",
    "minecraft:bookshelf": "oak planks",
    "minecraft:chiseled_bookshelf": "oak planks",
    "minecraft:lectern": "oak planks",
    "minecraft:composter": "composter",
    "minecraft:loom": "oak planks",
    # -- 功能方块 --
    "minecraft:chest": "chest",
    "minecraft:trapped_chest": "trapped chest",
    "minecraft:barrel": "chest",
    "minecraft:furnace": "furnace",
    "minecraft:blast_furnace": "furnace",
    "minecraft:smoker": "furnace",
    "minecraft:dispenser": "dispenser",
    "minecraft:dropper": "dispenser",
    "minecraft:crafting_table": "crafting table",
    "minecraft:brewing_stand": "brewing stand",
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
    "minecraft:soul_torch": "torch",
    "minecraft:soul_wall_torch": "torch",
    "minecraft:lantern": "torch",
    "minecraft:soul_lantern": "torch",
    "minecraft:sea_lantern": "sea lantern",
    "minecraft:redstone_torch": "redstone torch",
    "minecraft:redstone_wall_torch": "redstone torch",
    "minecraft:repeater": "redstone repeater",
    "minecraft:comparator": "redstone repeater",
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
    "minecraft:gilded_blackstone": "block of gold",
    "minecraft:iron_bars": "iron bars",
    "minecraft:chain": "iron bars",
    "minecraft:cobweb": "cobweb",
    # -- 染色/装饰 --
    "minecraft:orange_terracotta": "orange terracotta",
    "minecraft:light_gray_terracotta": "orange terracotta",
    "minecraft:blue_terracotta": "blue terracotta",
    "minecraft:white_glazed_terracotta": "white carpet",
    "minecraft:decorated_pot": "orange terracotta",
    "minecraft:white_wool": "white carpet",
    "minecraft:white_carpet": "halfheight:white carpet",
    "minecraft:red_carpet": "halfheight:red carpet",
    "minecraft:light_gray_carpet": "halfheight:light gray carpet",
    "minecraft:red_bed": "red bed",
    "minecraft:white_bed": "white bed",
    "minecraft:gray_banner": "ominous wall banner",
    "minecraft:gray_wall_banner": "ominous wall banner",
    "minecraft:white_wall_banner": "ominous wall banner",
    "minecraft:ominous_banner": "ominous wall banner",
    "minecraft:potted_red_mushroom": "potted red mushroom",
    "minecraft:potted_cactus": "potted cactus",
    "minecraft:potted_fern": "potted cactus",
    "minecraft:potted_dead_bush": "potted cactus",
    "minecraft:flower_pot": "potted cactus",
    "minecraft:quartz_block": "snow block",
    "minecraft:smooth_quartz": "snow block",
    "minecraft:quartz_pillar": "snow block",
    "minecraft:iron_block": "snow block",
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
    "minecraft:copper_door": "copper grate",
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
    "minecraft:waxed_oxidized_copper_door": "copper grate",
    "minecraft:red_candle": "torch",
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
    # -- 二轮补映射（模板实际出现、首轮遗漏）--
    "minecraft:glass_pane": "glass",
    "minecraft:glass": "glass",
    "minecraft:iron_door": "iron bars",
    "minecraft:polished_deepslate_wall": "stone bricks",
    "minecraft:mud_brick_stairs": "halfheight:orange terracotta",
    "minecraft:mud_brick_slab": "halfheight:orange terracotta",
    "minecraft:mud_bricks": "orange terracotta",
    "minecraft:cobblestone_slab": "halfheight:cobblestone slab",
    "minecraft:stone_slab": "halfheight:stone slab",
    "minecraft:redstone_lamp": "torch",
    "minecraft:infested_chiseled_stone_bricks": "chiseled stone bricks",
    "minecraft:netherrack": "netherrack",
    "minecraft:soul_sand": "gravel",
    "minecraft:soul_fire": None,
    "minecraft:brown_carpet": "halfheight:light gray carpet",
    "minecraft:gray_carpet": "halfheight:light gray carpet",
    "minecraft:gray_wool": "light gray carpet",
    "minecraft:redstone_block": "redstone torch",
    "minecraft:target": "redstone torch",
    "minecraft:sculk_sensor": "stone",
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
    "minecraft:waxed_oxidized_copper": "oxidized copper",
    "minecraft:waxed_copper_bulb": "copper bulb",
    "minecraft:oxidized_cut_copper": "oxidized cut copper",
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
    "minecraft:lava": None,
    "minecraft:bubble_column": None,
    "minecraft:seagrass": None,
    "minecraft:tall_seagrass": None,
    "minecraft:kelp": None,
    "minecraft:kelp_plant": None,
    "minecraft:sea_pickle": None,
    "minecraft:oak_leaves": None,
    "minecraft:spruce_leaves": None,
    "minecraft:mangrove_leaves": None,
    "minecraft:grass": None,
    "minecraft:short_grass": None,
    "minecraft:tall_grass": None,
    "minecraft:fern": None,
    "minecraft:large_fern": None,
    "minecraft:dead_bush": None,
    "minecraft:sweet_berry_bush": None,
    "minecraft:snow": None,
    "minecraft:red_mushroom": None,
    "minecraft:brown_mushroom": None,
    "minecraft:wheat": None,
    "minecraft:carrots": None,
    "minecraft:potatoes": None,
    "minecraft:beetroot": None,
    "minecraft:moss_carpet": None,
    "minecraft:moss_block": None,
    "minecraft:sculk_vein": None,
    "minecraft:sculk_shrieker": None,
    "minecraft:redstone_wire": None,
    "minecraft:rail": None,
    "minecraft:powered_rail": None,
    "minecraft:detector_rail": None,
    "minecraft:activator_rail": None,
    "minecraft:oak_button": None,
    "minecraft:spruce_button": None,
    "minecraft:dark_oak_button": None,
    "minecraft:stone_button": None,
    "minecraft:skeleton_skull": None,
    "minecraft:skeleton_wall_skull": None,
    "minecraft:candle": None,
    "minecraft:white_candle": None,
    "minecraft:bell": None,
    "minecraft:campfire": None,
    "minecraft:soul_campfire": None,
    "minecraft:end_rod": None,
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
    mats = []
    for entry in palette:
        name = _palette_entry_name(entry)
        typ = _palette_entry_half(entry)
        mode = "full" if typ in ("top", "double") else "half"
        mats.append(_map_block(name, mode))
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
def _schem_base_and_type(name: str):
    """palette 名 "minecraft:xxx[k=v,...]" -> (基名, slab type 值)。"""
    base, _, props = name.partition("[")
    typ = ""
    if props:
        for kv in props.rstrip("]").split(","):
            k, _, v = kv.partition("=")
            if k == "type":
                typ = v
    return base, typ


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
    mats = {}                                       # palette 索引 -> 材质键
    names = {}                                      # palette 索引 -> 基名
    for name, pid in palette.items():
        if not isinstance(pid, int) or pid < 0:
            continue
        base, typ = _schem_base_and_type(name)
        names[pid] = base
        mode = "full" if typ in ("top", "double") else "half"
        mats[pid] = _map_block(base, mode)
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
            # 台阶/楼梯/地毯按半高：蓝图调色板名含 slab/stairs/carpet
            low = tex
            if any(w in low for w in ("slab", "stairs", "carpet")):
                mat = "halfheight:" + tex
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
    mesh 见 build_mesh；tex_keys = 材质键列表（槽序）。
    """
    ck = (key, variant)
    with _CACHE_LOCK:
        if _CACHE["key"] == ck and _CACHE["model"] is not None:
            return _CACHE["model"]
        vox = build_voxels(key, variant)
        mesh = build_mesh(vox)
        tex_keys = sorted({m for m in vox.values() if isinstance(m, str)})
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
_TRANSPARENT_MATS = frozenset({"water", "glass", "ice"})


def _face_visible(mat: str, nb) -> bool:
    """owner 材质 mat 朝向邻居 nb（None = 空气/出界）的面是否可见。

    - 邻居为空 -> 可见；
    - 邻居为透明材（水/玻璃/冰）：同材合并剔除，异材保留
      （实心邻水面需绘制——透过半透明水可见；实心邻玻璃同理）；
    - 邻居为实心：剔除（被挡；透明面贴实心墙同样不可见）。
    """
    if nb is None:
        return True
    if nb in _TRANSPARENT_MATS:
        return mat != nb
    return False


# 六向面：法线 + 该面 4 顶点（单位块角点，逆时针 = 朝外）
_FACES = {
    "+y": ((0, 1, 0),
           ((0, 1, 1), (1, 1, 1), (1, 1, 0), (0, 1, 0))),
    "+x": ((1, 0, 0),
           ((1, 0, 1), (1, 0, 0), (1, 1, 0), (1, 1, 1))),
    "-x": ((-1, 0, 0),
           ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0))),
    "+z": ((0, 0, 1),
           ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))),
    "-z": ((0, 0, -1),
           ((1, 0, 0), (0, 0, 0), (0, 1, 0), (1, 1, 0))),
}


def build_mesh(vox: dict) -> dict:
    """体素 -> 绘制网格（共享顶点 + 材质槽区间）。

    返回 {"verts": [x,y,z,u,v,nx,ny,nz,...], "idx": [...],
          "slots": [(idx_start, idx_count), ...],
          "slot_mat": [mat, ...]}。
    - 底面(-y)一律不画（贴地观察场景不可见，省一半三角形）；
    - 半高块（"halfheight:" 前缀）高 0.5；
    - 面剔除透明感知：实心邻水/玻璃/冰保留面（透过透明材可见），
      水体内部同材合并、贴墙水面剔除（详见 _face_visible）；
    - UV 为世界坐标平铺值（0..N），图集换算在视口着色器侧完成。
    """
    slot_verts: dict = {}
    slot_index: dict = {}
    for (x, y, z), mat in vox.items():
        half = isinstance(mat, str) and mat.startswith("halfheight:")
        base = mat[len("halfheight:"):] if half else mat
        arr = slot_verts.setdefault(base, [])
        idx = slot_index.setdefault(base, [])
        for face, (normal, corners) in _FACES.items():
            nx, ny, nz = normal
            nb = vox.get((x + nx, y + ny, z + nz))
            if nb is not None:
                nb_half = isinstance(nb, str) and nb.startswith("halfheight:")
                # 半高邻居不完全遮挡（保留整面，重叠区由深度测试
                # 兜底）；整块邻居按透明感知规则剔除。
                if not nb_half and not _face_visible(mat, nb):
                    continue
            h1 = 0.5 if half else 1.0            # cy=1 顶点高度
            base_i = len(arr) // 8               # 当前槽顶点数（非浮点数！）
            for (cx, cy, cz) in corners:
                wy = y + (h1 if cy else 0.0)
                if ny != 0:                      # 顶面：u=x, v=z
                    u, v = float(x + cx), float(z + cz)
                elif nx != 0:                    # 侧面 x：u=z, v=y
                    u, v = float(z + cz), float(wy)
                else:                            # 侧面 z：u=x, v=y
                    u, v = float(x + cx), float(wy)
                arr.extend((x + cx, wy, z + cz, u, v, nx, ny, nz))
            idx.extend((base_i, base_i + 1, base_i + 2,
                        base_i, base_i + 2, base_i + 3))
    verts_all, idx_all, slots, slot_mat = [], [], [], []
    water_idx: list = []
    for mat in sorted(slot_verts):
        vert_start = len(verts_all) // 8
        verts_all.extend(slot_verts[mat])
        if mat == "water":
            # 水面索引不进常规槽：收集后统一挪到索引尾部，
            # 视口按 (water_off, water_count) 半透明第二遍绘制
            for i in slot_index[mat]:
                water_idx.append(i + vert_start)
            continue
        idx_start = len(idx_all)
        for i in slot_index[mat]:
            idx_all.append(i + vert_start)
        slots.append((idx_start, len(slot_index[mat])))
        slot_mat.append(mat)
    water_off = len(idx_all)
    idx_all.extend(water_idx)
    return {"verts": verts_all, "idx": idx_all,
            "slots": slots, "slot_mat": slot_mat,
            "water_off": water_off, "water_count": len(water_idx)}
