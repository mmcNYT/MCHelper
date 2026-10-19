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
    "minecraft:sticky_piston": "piston_top",
    "minecraft:piston_head": "piston_top",
    "minecraft:oak_wall_sign": "oak_planks",
    "minecraft:oak_button": "oak_planks",
    "minecraft:redstone_wire": "redstone_dust",
    "minecraft:redstone_wall_torch": "redstone_torch_on",
    "minecraft:lever": "lever",
    "minecraft:structure_block": "structure_block",
    "minecraft:potted_cactus": "dirt",
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
            for suf in ("_stairs", "_slab", "_wall", "_fence_gate",
                        "_trapdoor", "_button", "_pressure_plate",
                        "_door", "_sign", "_wall_sign", "_carpet",
                        "_glazed_terracotta", "_bulb", "_grate",
                        "_chain", "_lamp", "_torch", "_bed"):
                if short.endswith(suf):
                    base = short[:-len(suf)]
                    for alt in (base + "_planks", base + "s", base + "_top",
                                base + "_side", base,
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
