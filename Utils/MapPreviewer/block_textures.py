# -*- coding: utf-8 -*-
"""MC 方块材质贴图：从 jar 提取 16×16 顶面纹理，供精细渲染逐像素采样。

真实 MC 地图的方块不是纯色 —— 每块内部有 16×16 的材质花纹。本模块：
  1. 从 jar 读 assets/minecraft/textures/block/*.png
  2. 转成 (16,16,3) uint8 顶面 RGB
  3. 处理三类特殊：灰度图（grass/leaves 等需 tint）、透明（leaves 有镂空）、
     top 后缀（grass_block 用 grass_block_top）
  4. 打包成单张图集缓存到磁盘，避免每次解析 jar

对外:
    get_atlas(version) -> dict{block_name: (16,16,3) uint8}
    sample_block(atlas, name, px, pz) -> 单像素色
"""
from __future__ import annotations

import io
import json
import os
import zipfile

import numpy as np

_JAR = (r"C:\maomaochongD\.minecraft\.minecraft\versions"
        r"\26.2-NeoForge\26.2-NeoForge.jar")
_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "_native", "worldgen", "26.2", "block_atlas.npz")

# 方块名 -> 纹理文件名（顶面）。缺省用同名。
_TEX_ALIAS = {
    "minecraft:grass_block": "grass_block_top",
    "minecraft:podzol": "podzol_top",
    "minecraft:mycelium": "mycelium_top",
    "minecraft:path": "dirt_path_top",
    "minecraft:farmland": "farmland",
    "minecraft:snow_block": "snow",
    "minecraft:mud": "mud",
    "minecraft:moss_block": "moss_block",
    "minecraft:deepslate": "deepslate_top",
    "minecraft:basalt": "basalt_top",
    "minecraft:bone_block": "bone_block_top",
    "minecraft:quartz_block": "quartz_block_top",
    "minecraft:purpur_block": "purpur_block",
    "minecraft:sandstone": "sandstone_top",
    "minecraft:red_sandstone": "red_sandstone_top",
    "minecraft:oak_leaves": "oak_leaves",
    "minecraft:birch_leaves": "birch_leaves",
    "minecraft:spruce_leaves": "spruce_leaves",
    "minecraft:jungle_leaves": "jungle_leaves",
    "minecraft:acacia_leaves": "acacia_leaves",
    "minecraft:dark_oak_leaves": "dark_oak_leaves",
    "minecraft:mangrove_leaves": "mangrove_leaves",
    "minecraft:cherry_leaves": "cherry_leaves",
    "minecraft:azalea_leaves": "azalea_leaves",
    # 26.2 jar 无独立贴图/改名：映射到视觉等价贴图，避免回退品红
    "minecraft:bamboo": "bamboo_stalk",
    "minecraft:moss_carpet": "moss_block",
    "minecraft:bubble_column": "blue_ice",
    "minecraft:pointed_dripstone": "pointed_dripstone_up_base",
    "minecraft:smooth_sandstone": "sandstone_top",
    "minecraft:smooth_sandstone_slab": "sandstone_top",
    "minecraft:smooth_sandstone_stairs": "sandstone_top",
    "minecraft:smooth_quartz_slab": "quartz_block_bottom",
    "minecraft:smooth_quartz_stairs": "quartz_block_bottom",
    "minecraft:campfire": "campfire_log_lit",
    "minecraft:soul_campfire": "soul_campfire_log_lit",
    "minecraft:frosted_ice": "ice",
    "minecraft:grindstone": "grindstone_round",
    "minecraft:dropper": "dropper_front",
    "minecraft:command_block": "command_block_front",
    "minecraft:chain_command_block": "command_block_conditional",
    "minecraft:repeating_command_block": "command_block_back",
    "minecraft:ender_chest": "obsidian",
    "minecraft:trapped_chest": "oak_planks",
    "minecraft:beehive": "beehive_front",
    "minecraft:dried_kelp_block": "dried_kelp_top",
    "minecraft:decorated_pot": "decorated_pot_side",
    "minecraft:trial_spawner": "trial_spawner_side_inactive",
    "minecraft:sniffer_egg": "sniffer_egg_not_cracked_top",
    "minecraft:dried_ghast": "dried_ghast_hydration_0_top",
    "minecraft:sulfur_spike": "sulfur_spike_up_base",
    "minecraft:lava_cauldron": "cauldron_top",
    "minecraft:powder_snow_cauldron": "cauldron_top",
    "minecraft:smooth_quartz": "quartz_block_bottom",
    "minecraft:smooth_red_sandstone": "red_sandstone_top",
    "minecraft:smooth_red_sandstone_slab": "red_sandstone_top",
    "minecraft:smooth_red_sandstone_stairs": "red_sandstone_top",
    "minecraft:purpur_slab": "purpur_block",
    "minecraft:purpur_stairs": "purpur_block",
    "minecraft:petrified_oak_slab": "oak_planks",
    "minecraft:infested_chiseled_stone_bricks": "chiseled_stone_bricks",
    "minecraft:infested_cracked_stone_bricks": "cracked_stone_bricks",
    "minecraft:infested_mossy_stone_bricks": "mossy_stone_bricks",
    "minecraft:copper_chest": "copper_block",
    "minecraft:exposed_copper_chest": "exposed_copper",
    "minecraft:oxidized_copper_chest": "oxidized_copper",
    "minecraft:weathered_copper_chest": "weathered_copper",
    "minecraft:waxed_copper_chest": "copper_block",
    "minecraft:waxed_exposed_copper_chest": "exposed_copper",
    "minecraft:waxed_oxidized_copper_chest": "oxidized_copper",
    "minecraft:waxed_weathered_copper_chest": "weathered_copper",
    "minecraft:copper_golem_statue": "copper_block",
    "minecraft:exposed_copper_golem_statue": "exposed_copper",
    "minecraft:oxidized_copper_golem_statue": "oxidized_copper",
    "minecraft:weathered_copper_golem_statue": "weathered_copper",
    "minecraft:waxed_copper_golem_statue": "copper_block",
    "minecraft:waxed_exposed_copper_golem_statue": "exposed_copper",
    "minecraft:waxed_oxidized_copper_golem_statue": "oxidized_copper",
    "minecraft:waxed_weathered_copper_golem_statue": "weathered_copper",
    "minecraft:decorated_pot": "terracotta",
    "minecraft:test_block": "test_block_accept",
    "minecraft:candle_cake": "cake_top",
    "minecraft:white_candle_cake": "cake_top",
    "minecraft:orange_candle_cake": "cake_top",
    "minecraft:magenta_candle_cake": "cake_top",
    "minecraft:light_blue_candle_cake": "cake_top",
    "minecraft:yellow_candle_cake": "cake_top",
    "minecraft:lime_candle_cake": "cake_top",
    "minecraft:pink_candle_cake": "cake_top",
    "minecraft:gray_candle_cake": "cake_top",
    "minecraft:light_gray_candle_cake": "cake_top",
    "minecraft:cyan_candle_cake": "cake_top",
    "minecraft:purple_candle_cake": "cake_top",
    "minecraft:blue_candle_cake": "cake_top",
    "minecraft:brown_candle_cake": "cake_top",
    "minecraft:green_candle_cake": "cake_top",
    "minecraft:red_candle_cake": "cake_top",
    "minecraft:black_candle_cake": "cake_top",
    "minecraft:suspicious_gravel": "suspicious_gravel_0",
    "minecraft:suspicious_sand": "suspicious_sand_0",
    "minecraft:infested_stone": "stone",
    "minecraft:infested_deepslate": "deepslate",
    "minecraft:infested_cobblestone": "cobblestone",
    "minecraft:infested_stone_bricks": "stone_bricks",
    # 结构材质：MC 无同名贴图，映射到视觉等价基材
    "minecraft:brick_stairs": "bricks",
    "minecraft:stone_brick_stairs": "stone_bricks",
    "minecraft:stone_brick_slab": "stone_bricks",
    "minecraft:deepslate_brick_stairs": "deepslate_bricks",
    "minecraft:deepslate_brick_slab": "deepslate_bricks",
    "minecraft:deepslate_brick_wall": "deepslate_bricks",
    "minecraft:deepslate_tile_stairs": "deepslate_tiles",
    "minecraft:deepslate_tile_wall": "deepslate_tiles",
    "minecraft:mud_brick_stairs": "mud_bricks",
    "minecraft:mud_brick_slab": "mud_bricks",
    "minecraft:polished_blackstone_brick_stairs": "polished_blackstone_bricks",
    "minecraft:dark_oak_fence": "dark_oak_planks",
    "minecraft:spruce_fence": "spruce_planks",
    "minecraft:oak_fence": "oak_planks",
    "minecraft:white_carpet": "white_wool",
    "minecraft:gray_carpet": "gray_wool",
    "minecraft:red_carpet": "red_wool",
    "minecraft:light_blue_carpet": "light_blue_wool",
    "minecraft:light_gray_carpet": "light_gray_wool",
    "minecraft:red_bed": "red_wool",
    "minecraft:chest": "oak_planks",
    "minecraft:barrel": "barrel_side",
    "minecraft:dispenser": "dispenser_front",
    "minecraft:furnace": "furnace_front",
    "minecraft:magma_block": "magma",
    "minecraft:infested_stone_bricks": "stone_bricks",
    "minecraft:crafting_table": "crafting_table_top",
    "minecraft:carved_pumpkin": "carved_pumpkin_front",
    "minecraft:pumpkin": "pumpkin_side",
    "minecraft:hay_block": "hay_block_side",
    "minecraft:iron_bars": "iron_bars",
    "minecraft:ladder": "ladder",
    "minecraft:lectern": "lectern_front",
    "minecraft:hopper": "hopper_top",
    "minecraft:candle": "candle",
    "minecraft:waxed_copper_block": "copper_block",
    "minecraft:waxed_cut_copper": "cut_copper",
    "minecraft:waxed_oxidized_cut_copper": "oxidized_cut_copper",
    "minecraft:waxed_oxidized_cut_copper_stairs": "oxidized_cut_copper",
    "minecraft:gold_block": "gold_block",
    "minecraft:redstone_block": "redstone_block",
    "minecraft:redstone_lamp": "redstone_lamp",
    "minecraft:redstone_torch": "redstone_torch_on",
    "minecraft:soul_lantern": "soul_lantern",
    "minecraft:soul_sand": "soul_sand",
    "minecraft:soul_fire": "soul_fire_0",
    "minecraft:obsidian": "obsidian",
    "minecraft:cobweb": "cobweb",
    "minecraft:reinforced_deepslate": "reinforced_deepslate_side",
    "minecraft:sculk_sensor": "sculk_sensor_top",
    "minecraft:target": "target_top",
    "minecraft:comparator": "comparator",
    "minecraft:repeater": "repeater",
    "minecraft:brewing_stand": "brewing_stand",
    "minecraft:water_cauldron": "cauldron_side",
    "minecraft:cauldron": "cauldron_side",
    "minecraft:sticky_piston": "piston_top",
    "minecraft:piston_head": "piston_top",
    "minecraft:oak_wall_sign": "oak_planks",
    "minecraft:oak_button": "oak_planks",
    "minecraft:redstone_wire": "redstone_dust",
    "minecraft:redstone_wall_torch": "redstone_torch_on",
    "minecraft:lever": "lever",
    "minecraft:structure_block": "structure_block",
    "minecraft:potted_cactus": "dirt",
    "minecraft:potted_red_mushroom": "red_mushroom",
    # 楼梯/台阶/栅栏/作物：贴图名与方块名不同（带 _top / 复数等）
    "minecraft:oak_stairs": "oak_planks",
    "minecraft:spruce_stairs": "spruce_planks",
    "minecraft:birch_stairs": "birch_planks",
    "minecraft:jungle_stairs": "jungle_planks",
    "minecraft:acacia_stairs": "acacia_planks",
    "minecraft:dark_oak_stairs": "dark_oak_planks",
    "minecraft:oak_slab": "oak_planks",
    "minecraft:spruce_slab": "spruce_planks",
    "minecraft:stone_slab": "smooth_stone",
    "minecraft:cobblestone_slab": "cobblestone",
    "minecraft:oak_fence": "oak_planks",
    "minecraft:oak_log": "oak_log",
    "minecraft:wheat": "wheat_stage7",
    "minecraft:torch": "torch",
    "minecraft:wall_torch": "torch",
    "minecraft:glass_pane": "glass",
    "minecraft:oak_planks": "oak_planks",
    "minecraft:cobblestone": "cobblestone",
    "minecraft:dirt_path": "dirt_path_top",
    "minecraft:farmland": "farmland",
    "minecraft:air": "air",
    "minecraft:flowering_azalea_leaves": "flowering_azalea_leaves",
}

# 循环补齐的家族映射（写循环避免手抄 40+ 条错色）：
#   - 横幅：1.20+ 的 banner 无独立彩色贴图（entity/banner 只有通用底布 +
#     shader 染色），布色 = 染料色 → 映射同染料色羊毛（structure_render
#     末地城横幅同思路）。俯视图一格看，横幅顶面就是布色。
#   - 珊瑚墙扇：无独立 wall_fan 贴图（模型复用 *_coral_fan.png），映射
#     对应 fan 贴图；dead_* 变体同构。
#   - 作物：贴图带 stage 后缀（potatoes_stage0..3），顶面取成熟期
#     stage3（与 wheat → wheat_stage7 同法）。
for _c in ("white", "orange", "magenta", "light_blue", "yellow", "lime",
           "pink", "gray", "light_gray", "cyan", "purple", "blue", "brown",
           "green", "red", "black"):
    _TEX_ALIAS["minecraft:%s_banner" % _c] = "%s_wool" % _c
    _TEX_ALIAS["minecraft:%s_wall_banner" % _c] = "%s_wool" % _c
for _c in ("tube", "brain", "bubble", "fire", "horn",
           "dead_tube", "dead_brain", "dead_bubble", "dead_fire", "dead_horn"):
    _TEX_ALIAS["minecraft:%s_coral_wall_fan" % _c] = "%s_coral_fan" % _c
_TEX_ALIAS["minecraft:potatoes"] = "potatoes_stage3"
_TEX_ALIAS["minecraft:carrots"] = "carrots_stage3"
_TEX_ALIAS["minecraft:beetroots"] = "beetroots_stage3"

# 需要按群系 tint 上色的灰度贴图（MC 的 grass/leaves 是灰图 + tint）
_GRAYSCALE_TINT = {
    "grass_block_top", "podzol_top", "mycelium_top", "short_grass",
    "tall_grass_top", "fern", "large_fern_top", "oak_leaves",
    "birch_leaves", "spruce_leaves", "jungle_leaves", "acacia_leaves",
    "dark_oak_leaves", "mangrove_leaves", "cherry_leaves",
    "azalea_leaves", "flowering_azalea_leaves", "lily_pad",
    "vine", "sugar_cane", "attached_melon_stem", "melon_stem",
}


def _load_png(z: zipfile.ZipFile, path: str):
    from PIL import Image
    try:
        data = z.read(path)
    except KeyError:
        return None
    try:
        im = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None
    if im.size != (16, 16):
        im = im.resize((16, 16), Image.NEAREST)
    a = np.asarray(im).astype(np.uint8)
    # 透明像素（leaves 镂空）用不透明平均色填充，避免渲染出黑点
    alpha = a[..., 3]
    rgb = a[..., :3].copy()
    if (alpha < 128).any():
        solid = rgb[alpha >= 128]
        if len(solid):
            rgb[alpha < 128] = solid.mean(axis=0).astype(np.uint8)
    return rgb


def build_atlas(block_names: list[str], version: str = "26.2") -> dict:
    """为给定方块名构建 16×16 顶面纹理表。"""
    os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
    # 磁盘缓存：{name: (16,16,3)}
    cached = {}
    meta = _CACHE + ".json"
    if os.path.exists(_CACHE) and os.path.exists(meta):
        try:
            with open(meta, encoding="utf-8") as f:
                keys = set(json.load(f).get("names", []))
            if set(block_names) <= keys:
                arr = np.load(_CACHE)
                for nm in block_names:
                    cached[nm] = arr[nm]
                return cached
        except Exception:
            cached = {}

    z = zipfile.ZipFile(_JAR)
    out = {}
    for nm in block_names:
        short = nm.split(":")[-1]
        # waxed_ 前缀尽早剥离：铜门/铜台阶等回退链全程用无蜡名字，
        # 否则 base 里带着 waxed_ 导致所有候选都加载失败
        if short.startswith("waxed_"):
            short = short[len("waxed_"):]
        tex = _TEX_ALIAS.get(nm, short)
        # 26.2 铜系贴图不再带 waxed_ 前缀
        if tex.startswith("waxed_"):
            tex = tex[len("waxed_"):]
        rgb = _load_png(z, "assets/minecraft/textures/block/%s.png" % tex)
        if rgb is None:
            # top 变体 / 兼容其它命名
            for alt in (short + "_top", short + "_still", short):
                rgb = _load_png(z, "assets/minecraft/textures/block/%s.png" % alt)
                if rgb is not None:
                    break
        if rgb is None:
            # 楼梯/台阶/墙/栅栏等**没有独立贴图**，回退到基材：
            # dark_oak_stairs -> dark_oak_planks -> dark_oak
            # 后缀按长度降序匹配：否则 "_sign" 会抢在 "_wall_sign" 前面，
            # 把 base 抢成 "acacia_wall" 导致全部墙牌解析失败
            for suf in ("_wall_hanging_sign", "_pressure_plate",
                        "_glazed_terracotta", "_wall_sign", "_fence_gate",
                        "_stairs", "_trapdoor", "_button", "_carpet",
                        "_slab", "_wall", "_door", "_sign", "_chain",
                        "_lamp", "_torch", "_bulb", "_grate", "_bed",
                        "_wood", "_fence", "_hyphae"):
                if short.endswith(suf):
                    base = short[:-len(suf)]
                    for alt in (base + "_planks", base + "s", base + "_top",
                                base + "_side", base + "_log", base + "_stem",
                                base + "_wool", base,
                                base.replace("cracked_", "") + "_bricks",
                                base.replace("chiseled_", "") + "_bricks",
                                base.replace("polished_", "") + "_bricks"):
                        rgb = _load_png(
                            z,
                            "assets/minecraft/textures/block/%s.png" % alt)
                        if rgb is not None:
                            break
                    break
        if rgb is None:
            continue
        out[nm] = rgb
    # 落盘缓存（npz 需要同名 key）
    try:
        np.savez_compressed(_CACHE, **out)
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({"names": list(out.keys())}, f)
    except Exception:
        pass
    return out


def load_atlas(block_names: list[str]) -> dict:
    """缓存优先的贴图表加载。"""
    return build_atlas(block_names)


def needs_tint(block_name: str) -> bool:
    short = block_name.split(":")[-1]
    tex = _TEX_ALIAS.get(block_name, short)
    return tex in _GRAYSCALE_TINT
