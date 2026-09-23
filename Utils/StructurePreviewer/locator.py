# -*- coding: utf-8 -*-
"""StructurePreviewer：结构定位层（locator）。

基于 Utils.Public.structure_map.enumerate_structures 复用既有
枚举与群系校验（与 MapPreviewer 的 GUI 验收口径一致），限定
igloo / shipwreck 两个结构键，并对每个锚点求完整构造组合。

UI 主流程（btnPreview）：
    1. locator.locate() 得到视野内锚点列表（含 biome id）
    2. composition.compose() 填充变种/部件/箱子/LootTableSeed
    3. composition.compose_display_model() 出 3D 视口模型
"""
from __future__ import annotations

from Utils.Public import structure_map
from . import composition, loot_rng

SUPPORTED = ("igloo", "shipwreck")


def locate(seed: int, version_key: str,
           viewport: tuple[int, int, int, int],
           struct_keys=SUPPORTED) -> list[dict]:
    """视野内结构实例列表（结构粒度，不含构造细节）。

    返回项：{struct, name, x, z, cx, cz, biome}。
    """
    return structure_map.enumerate_structures(
        seed, version_key, viewport, struct_keys=tuple(struct_keys))


def detail(seed: int, version_key: str, struct_key: str,
           anchor: tuple[int, int], biome_id: int) -> composition.Composition:
    """单锚点 -> 完整构造组合（变种/部件/箱子/LootTableSeed）。"""
    return composition.compose(struct_key, seed & ((1 << 64) - 1),
                               anchor[0], anchor[1], biome_id=biome_id,
                               version_key=version_key)


def locate_with_details(seed: int, version_key: str,
                        viewport: tuple[int, int, int, int],
                        struct_keys=SUPPORTED) -> list[dict]:
    """locate + 每项附加 comp（构造组合）与 model（3D 显示模型）。

    供 UI 直接消费；model 含 voxels/chests/anchor/anchor_off。
    """
    out = []
    for hit in locate(seed, version_key, viewport, struct_keys):
        comp = detail(seed, version_key, hit["struct"],
                      (hit["x"], hit["z"]), hit.get("biome", -1))
        item = dict(hit)
        item["comp"] = comp
        item["model"] = composition.compose_display_model(comp)
        out.append(item)
    return out


def format_seed_signed(seed: int) -> int:
    """无符号 -> Java 有符号显示（转发 loot_rng）。"""
    return loot_rng.signed_seed(seed)
