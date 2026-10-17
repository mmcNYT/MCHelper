# -*- coding: utf-8 -*-
"""粒子预览动图（Java 版 Wiki 渲染 GIF）。

资源：assets/CommandGenerator/particles/*.gif|png（来自中文 Minecraft
Wiki「Java版粒子」页面的渲染动图，120+ 个）。粒子 id（game 命令
/particle 的参数名）与 Wiki 文件名不完全一致，本模块提供
id -> 文件名 映射与回退规则。

用法（预览框播放）：
    from Utils.CommandGenerator.particle_preview import particle_media
    path, is_gif = particle_media("minecraft:flame")
"""
from __future__ import annotations

import os

_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "assets", "CommandGenerator", "particles")

# 粒子 id（不含 minecraft: 前缀）-> Wiki 文件名（不含扩展名）
# 仅列不一致者；一致的（flame->flame.gif）由 _direct 推断。
_ALIAS = {
    # 官方 id 含下划线 / Wiki 驼峰或旧名
    "angry_villager": "angryVillager",
    "happy_villager": "happyVillager",
    "block_marker": "block_marker",
    "bubble_column_up": "bubble_column_up",
    "vibration": "Vibration",
    # 名字差异
    "mobportal": "portal",            # 旧版 id
    "reverse_portal": "reverse_portal",
    "small_flame": "small_flame",
    "soul_fire_flame": "soul_fire_flame",
    "dust_color_transition": "dust_color_transition",
    "dust_pillar": "dust_pillar",
    "dust_plume": "dust_plume",
    "white_ash": "white_ash",
    "crimson_spore": "crimson_spore",
    "warped_spore": "warped_spore",
    "sculk_charge": "sculk_charge",
    "sculk_charge_pop": "sculk_charge_pop",
    "sonic_boom": "sonic_boom",
    "trial_spawner_detection": "trial_spawner_detection",
    "trial_spawner_detection_ominous": "trial_spawner_detection_ominous",
    "ominous_spawning": "ominous_spawning",
    "raid_omen": "raid_omen",
    "trial_omen": "trial_omen",
    "vault_connection": "vault_connection",
    "totem_of_undying": "totem_of_undying",
    "enchanted_hit": "enchanted_hit",
    "damage_indicator": "damage_indicator",
    "electric_spark": "electric_spark",
    "elder_guardian": "elder_guardian",
    "entity_effect": "entity_effect",
    "instant_effect": "instant_effect",
    "dripping_dripstone_lava": "dripping_dripstone_lava",
    "dripping_dripstone_water": "dripping_dripstone_water",
    "falling_dripstone_lava": "falling_dripstone_lava",
    "falling_dripstone_water": "falling_dripstone_water",
    "falling_nectar": "falling_nectar",
    "spore_blossom_air": "spore_blossom_air",
    "campfire_cosy_smoke": "campfire_cosy_smoke",
    "campfire_signal_smoke": "campfire_signal_smoke",
    "cherry_leaves": "cherry_leaves",
    "pale_oak_leaves": "pale_oak_leaves",
    "tinted_leaves": "tinted_leaves",
    "glow_squid_ink": "glow_squid_ink",
    "squid_ink": "squid_ink",
    "snowflake": "snowflake",
    "dripping_obsidian_tear": "dripping_obsidian_tear",
    "falling_obsidian_tear": "falling_obsidian_tear",
    "landing_obsidian_tear": "landing_obsidian_tear",
    "dripping_honey": "dripping_honey",
    "falling_honey": "falling_honey",
    "landing_honey": "landing_honey",
    "dripping_lava": "dripping_lava",
    "falling_lava": "falling_lava",
    "landing_lava": "landing_lava",
    "dripping_water": "dripping_water",
    "falling_water": "falling_water",
    "gust_emitter_large": "gust_emitter_large",
    "gust_emitter_small": "gust_emitter_small",
    "small_gust": "small_gust",
    "item_cobweb": "item_cobweb",
    "item_slime": "item_slime",
    "item_snowball": "item_snowball",
    # 命令 id 与 Wiki 旧名的差异
    "poof": "poof",
    "explosion": "explosion",
    "explosion_emitter": "explosion_emitter",
    "large_smoke": "large_smoke",
    "block_break": "blockcrack",      # 方块破碎用 blockcrack 渲染图
    "block_dust": "blockdust",
    "spell": "spell",
    "effect": "spell",
    "instant_effect_old": "spell",
    "wax_on": "wax_on",
    "wax_off": "wax_off",
    "scrape": "scrape",
    "shriek": "shriek",
    "sculk_soul": "sculk_soul",
    "nautilus": "nautilus",
    "dolphin": "dolphin",
    "underwater": "underwater",
    "splash": "splash",
    "fishing": "fishing",
    "firework": "firework",
    "flash": "flash",
    "note": "note",
    "witch": "witch",
    "sneeze": "sneeze",
    "smoke": "smoke",
    "white_smoke": "white_smoke",
    "cloud": "cloud",
    "mycelium": "mycelium",
    "crimson_sign": "crimson_spore",  # 兼容旧 id
    "infested": "infested",
    "freezing": "freezing",
    "noxious_gas": "noxious_gas",
    "sulfur_bubbles": "sulfur_bubbles",
    "sulfur_cube_goo": "sulfur_cube_goo",
    "copper_fire_flame": "copper_fire_flame",
    "geyser": "geyser",
    "geyser_base": "geyser_base",
    "geyser_plume": "geyser_plume",
    "geyser_poof": "geyser_poof",
    "firefly": "firefly",
    "yellow_poplar_leaves": "yellow_poplar_leaves",
    "red_poplar_leaves": "red_poplar_leaves",
    "orange_poplar_leaves": "orange_poplar_leaves",
    "pause_mob_growth": "pause_mob_growth",
    "reset_mob_growth": "reset_mob_growth",
    "creaking_die": "creaking_die",
}


def _candidates(pid: str) -> list[str]:
    """粒子 id -> 可能的文件名（不含扩展名）候选列表。"""
    base = pid.removeprefix("minecraft:")
    out = []
    if base in _ALIAS:
        out.append(_ALIAS[base])
    out.append(base)                        # 一致：flame -> flame
    out.append(base.replace("_", ""))       # angry_villager -> angryvillager
    out.append("".join(p.capitalize() for p in base.split("_")))
    return out


def particle_media(pid: str) -> tuple[str | None, bool]:
    """粒子 id -> (文件绝对路径, 是否动图)。

    优先 gif（动图），回退 png；都没有返回 (None, False)。
    """
    if not pid:
        return None, False
    for name in _candidates(pid):
        for ext, is_gif in ((".gif", True), (".png", False)):
            p = os.path.join(_DIR, f"{name}{ext}")
            if os.path.isfile(p):
                return p, is_gif
    return None, False
