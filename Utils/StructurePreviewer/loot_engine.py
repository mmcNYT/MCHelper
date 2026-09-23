# -*- coding: utf-8 -*-
"""StructurePreviewer 战利品求值引擎（Cubiomes-Loot 的 Python 移植）。

语义逐行对照 xpple/cubiomes fork（5815e4f）：
    - loot/loot_table_parser.c   JSON -> pool/entry/function 对象
    - loot/loot_table_context.c  求值主循环 generate_loot
    - loot/loot_functions.c      各 LootFunction 的 RNG 消耗与附魔算法

与 C 版的等价性要点：
    - RNG 消耗顺序必须一致：pool 条件 -> rolls -> 每 roll 的加权抽取
      （entry<=1 时不消耗 nextInt）-> 子表内联展开 -> entry 函数依序执行。
    - absSkipN 跳过的是 n 个 raw 输出（skip_n），不是 n 个 nextLongJ。
    - 附魔相关所有浮点均为 float32 域（用 np.float32 显式模拟）。
    - rolls 为 JSON 对象时恒为 uniform（即使 min==max 也消耗 nextInt(1)）；
      set_count 的 min==max 则为 constant（不消耗）。两者不可混淆。
    - 物品直接用 "minecraft:xxx" 字符串做键，不需要 C 的全局 ID 表；
      附魔用规范短名（protection/...），效果保留 "minecraft:xxx" 全名。
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

import numpy as np

from Utils.StructurePreviewer import loot_rng

_M64 = (1 << 64) - 1

# ---------------------------------------------------------------------------
# 版本时代（对应 C 的 MCVersion 相对比较，只需序不需具体值）
# ---------------------------------------------------------------------------

# 版本时代（对应 C 的 MCVersion 相对比较，只需序不需具体值）。
# 版本线收敛为 26.2 / 1.21.11 / 1.21；其余 era 常量/区间保留供
# 快照档位自包含解析（分档快照用档位自己的 era 烘焙）。
E_1_13 = 0
E_1_14 = 1      # 1.14 ~ 1.20（get_applicable 的 ORDER_V1_14 区间）
E_1_21 = 2      # 1.21 ~ 1.21.8（ORDER_V1_21）
E_1_21_9 = 3    # enchant_randomly 默认改走 tag 的分界
E_1_21_11 = 4   # ORDER_V1_21_11（+lunge）
E_26_2 = 5

_ERA_BY_VERSION: dict[str, int] = {
    "1.21": E_1_21,
    "1.21.11": E_1_21_11,
    "26.2": E_26_2,
}


def era_for_version(version_key: str) -> int:
    """版本键 -> era（未知键回退 E_1_21，版本线收敛后最小合法档）。"""
    return _ERA_BY_VERSION.get(version_key, E_1_21)


# ---------------------------------------------------------------------------
# 附魔枚举（顺序必须与 C 的 enum Enchantment 一致；MAX_LEVEL 表按序索引）
# ---------------------------------------------------------------------------

ENCHANTMENT_ORDER: tuple[str, ...] = (
    # 0 NO_ENCHANTMENT
    "no_enchantment",
    # 1-12 armor
    "protection", "fire_protection", "blast_protection",
    "projectile_protection", "respiration", "aqua_affinity", "thorns",
    "swift_sneak", "feather_falling", "depth_strider", "frost_walker",
    "soul_speed",
    # 13-19 swords
    "sharpness", "smite", "bane_of_arthropods", "knockback", "fire_aspect",
    "looting", "sweeping_edge",
    # 20-22 tools
    "efficiency", "silk_touch", "fortune",
    # 23-24 fishing rods
    "luck_of_the_sea", "lure",
    # 25-28 bows
    "power", "punch", "flame", "infinity",
    # 29-31 crossbows（注意 C 枚举序：QUICK_CHARGE 在 MULTISHOT 之前）
    "quick_charge", "multishot", "piercing",
    # 32-35 tridents
    "impaling", "riptide", "loyalty", "channeling",
    # 36-38 maces
    "density", "breach", "wind_burst",
    # 39-42 general
    "mending", "unbreaking", "vanishing_curse", "binding_curse",
    # 43 1.21.11+
    "lunge",
)

_ENCH_ID: dict[str, int] = {n: i for i, n in enumerate(ENCHANTMENT_ORDER)}
_NENCH = len(ENCHANTMENT_ORDER)

# 常用附魔 id 常量（互斥表/判定用，避免散落魔法数字）
E_PROTECTION = _ENCH_ID["protection"]
E_FIRE_PROTECTION = _ENCH_ID["fire_protection"]
E_BLAST_PROTECTION = _ENCH_ID["blast_protection"]
E_PROJECTILE_PROTECTION = _ENCH_ID["projectile_protection"]
E_RESPIRATION = _ENCH_ID["respiration"]
E_AQUA_AFFINITY = _ENCH_ID["aqua_affinity"]
E_THORNS = _ENCH_ID["thorns"]
E_SWIFT_SNEAK = _ENCH_ID["swift_sneak"]
E_FEATHER_FALLING = _ENCH_ID["feather_falling"]
E_DEPTH_STRIDER = _ENCH_ID["depth_strider"]
E_FROST_WALKER = _ENCH_ID["frost_walker"]
E_SOUL_SPEED = _ENCH_ID["soul_speed"]
E_SHARPNESS = _ENCH_ID["sharpness"]
E_SMITE = _ENCH_ID["smite"]
E_BANE = _ENCH_ID["bane_of_arthropods"]
E_KNOCKBACK = _ENCH_ID["knockback"]
E_FIRE_ASPECT = _ENCH_ID["fire_aspect"]
E_LOOTING = _ENCH_ID["looting"]
E_SWEEPING_EDGE = _ENCH_ID["sweeping_edge"]
E_EFFICIENCY = _ENCH_ID["efficiency"]
E_SILK_TOUCH = _ENCH_ID["silk_touch"]
E_FORTUNE = _ENCH_ID["fortune"]
E_LUCK_OF_THE_SEA = _ENCH_ID["luck_of_the_sea"]
E_LURE = _ENCH_ID["lure"]
E_POWER = _ENCH_ID["power"]
E_PUNCH = _ENCH_ID["punch"]
E_FLAME = _ENCH_ID["flame"]
E_INFINITY = _ENCH_ID["infinity"]
E_QUICK_CHARGE = _ENCH_ID["quick_charge"]
E_MULTISHOT = _ENCH_ID["multishot"]
E_PIERCING = _ENCH_ID["piercing"]
E_IMPALING = _ENCH_ID["impaling"]
E_RIPTIDE = _ENCH_ID["riptide"]
E_LOYALTY = _ENCH_ID["loyalty"]
E_CHANNELING = _ENCH_ID["channeling"]
E_DENSITY = _ENCH_ID["density"]
E_BREACH = _ENCH_ID["breach"]
E_WIND_BURST = _ENCH_ID["wind_burst"]
E_MENDING = _ENCH_ID["mending"]
E_UNBREAKING = _ENCH_ID["unbreaking"]
E_VANISHING = _ENCH_ID["vanishing_curse"]
E_BINDING = _ENCH_ID["binding_curse"]
E_LUNGE = _ENCH_ID["lunge"]

# ---------------------------------------------------------------------------
# MAX_LEVEL（C: get_max_level 静态表，按枚举序）
# ---------------------------------------------------------------------------

_MAX_LEVEL: tuple[int, ...] = (
    0,
    # armor
    4, 4, 4, 4, 3, 1, 3, 3, 4, 3, 2, 3,
    # swords
    5, 5, 5, 2, 2, 3, 3,
    # tools
    5, 1, 3,
    # fishing
    3, 3,
    # bows
    5, 2, 1, 1,
    # crossbows
    3, 1, 4,
    # tridents
    5, 3, 3, 1,
    # maces
    5, 4, 3,
    # general
    1, 3, 1, 1,
    # 1.21.11+
    3,
)

assert len(_MAX_LEVEL) == _NENCH


def get_max_level(ench: int | str) -> int:
    if isinstance(ench, str):
        ench = _ENCH_ID[ench]
    return _MAX_LEVEL[ench]


# ---------------------------------------------------------------------------
# 权重（C: get_weight；default = 2 rare）
# ---------------------------------------------------------------------------

_WEIGHT_OVERRIDE: dict[int, int] = {}
for _n in ("protection", "sharpness", "efficiency", "power", "piercing"):
    _WEIGHT_OVERRIDE[_ENCH_ID[_n]] = 10
for _n in ("fire_protection", "feather_falling", "projectile_protection",
           "smite", "bane_of_arthropods", "knockback", "unbreaking",
           "loyalty", "quick_charge", "density", "lunge"):
    _WEIGHT_OVERRIDE[_ENCH_ID[_n]] = 5
for _n in ("thorns", "binding_curse", "soul_speed", "silk_touch", "infinity",
           "channeling", "vanishing_curse"):
    _WEIGHT_OVERRIDE[_ENCH_ID[_n]] = 1


def _get_weight(ench: int) -> int:
    return _WEIGHT_OVERRIDE.get(ench, 2)


# ---------------------------------------------------------------------------
# 互斥表（C: fill_incompatible_enchantments；对角线恒互斥）
# ---------------------------------------------------------------------------

_INCOMPATIBLE: set[tuple[int, int]] = set()


def _init_incompatible() -> None:
    if _INCOMPATIBLE:
        return
    for i in range(_NENCH):
        _INCOMPATIBLE.add((i, i))
    prot = (E_PROTECTION, E_FIRE_PROTECTION, E_BLAST_PROTECTION,
            E_PROJECTILE_PROTECTION)
    for a in prot:
        for b in prot:
            _INCOMPATIBLE.add((a, b))
    sharp = (E_SHARPNESS, E_SMITE, E_BANE)
    for a in sharp:
        for b in sharp:
            _INCOMPATIBLE.add((a, b))
    for f in (E_FORTUNE, E_LUCK_OF_THE_SEA, E_LOOTING):
        _INCOMPATIBLE.add((f, E_SILK_TOUCH))
        _INCOMPATIBLE.add((E_SILK_TOUCH, f))
    _INCOMPATIBLE.add((E_DEPTH_STRIDER, E_FROST_WALKER))
    _INCOMPATIBLE.add((E_FROST_WALKER, E_DEPTH_STRIDER))
    _INCOMPATIBLE.add((E_MENDING, E_INFINITY))
    _INCOMPATIBLE.add((E_INFINITY, E_MENDING))
    _INCOMPATIBLE.add((E_RIPTIDE, E_CHANNELING))
    _INCOMPATIBLE.add((E_CHANNELING, E_RIPTIDE))
    _INCOMPATIBLE.add((E_RIPTIDE, E_LOYALTY))
    _INCOMPATIBLE.add((E_LOYALTY, E_RIPTIDE))
    _INCOMPATIBLE.add((E_PIERCING, E_MULTISHOT))
    _INCOMPATIBLE.add((E_MULTISHOT, E_PIERCING))
    _INCOMPATIBLE.add((E_DENSITY, E_BREACH))
    _INCOMPATIBLE.add((E_BREACH, E_DENSITY))


# ---------------------------------------------------------------------------
# 物品类型（C: enum ItemType，同序）
# ---------------------------------------------------------------------------

IT_NO_ITEM = 0
IT_HELMET = 1
IT_CHESTPLATE = 2
IT_LEGGINGS = 3
IT_BOOTS = 4
IT_SWORD = 5
IT_PICKAXE = 6
IT_SHOVEL = 7
IT_AXE = 8
IT_HOE = 9
IT_FISHING_ROD = 10
IT_BOW = 11
IT_CROSSBOW = 12
IT_TRIDENT = 13
IT_MACE = 14
IT_BOOK = 15
IT_SPEAR = 16


def get_item_type(item_name: str) -> int:
    """C: loot_table_parser.c get_item_type —— 注意后缀子串匹配顺序不能乱
    （_pickaxe 必须先于 _axe，否则 iron_pickaxe 会被误判为 AXE）。"""
    if "_spear" in item_name:
        return IT_SPEAR
    if "_pickaxe" in item_name:
        return IT_PICKAXE
    if "_axe" in item_name:
        return IT_AXE
    if "_shovel" in item_name:
        return IT_SHOVEL
    if "_hoe" in item_name:
        return IT_HOE
    if "_sword" in item_name:
        return IT_SWORD
    if "_helmet" in item_name:
        return IT_HELMET
    if "_chestplate" in item_name:
        return IT_CHESTPLATE
    if "_leggings" in item_name:
        return IT_LEGGINGS
    if "_boots" in item_name:
        return IT_BOOTS
    if item_name == "minecraft:fishing_rod":
        return IT_FISHING_ROD
    if item_name == "minecraft:crossbow":
        return IT_CROSSBOW
    if item_name == "minecraft:trident":
        return IT_TRIDENT
    if item_name == "minecraft:bow":
        return IT_BOW
    if item_name == "minecraft:book":
        return IT_BOOK
    if item_name == "minecraft:mace":
        return IT_MACE
    return IT_NO_ITEM


# ---------------------------------------------------------------------------
# MobEffect / Potion（C: loot_functions.c MOB_EFFECTS / POTIONS）
# 只保留求值用得上的字段：瞬时性集合 + 药水 -> 单效果映射
# ---------------------------------------------------------------------------

# is_instantaneous = 1 的效果（set_effect 的 duration 不乘 20）
_INSTANT_EFFECTS = frozenset((
    "minecraft:instant_health", "minecraft:instant_damage", "minecraft:saturation",
))

# 药水名 -> (效果数, [(效果名, 基础时长), ...])；求值只使用单效果药水
POTIONS: dict[str, tuple[int, tuple[tuple[str, int], ...]]] = {
    "minecraft:water": (0, ()),
    "minecraft:mundane": (0, ()),
    "minecraft:thick": (0, ()),
    "minecraft:awkward": (0, ()),
    "minecraft:night_vision": (1, (("minecraft:night_vision", 3600),)),
    "minecraft:long_night_vision": (1, (("minecraft:night_vision", 9600),)),
    "minecraft:invisibility": (1, (("minecraft:invisibility", 3600),)),
    "minecraft:long_invisibility": (1, (("minecraft:invisibility", 9600),)),
    "minecraft:leaping": (1, (("minecraft:jump_boost", 3600),)),
    "minecraft:long_leaping": (1, (("minecraft:jump_boost", 9600),)),
    "minecraft:strong_leaping": (1, (("minecraft:jump_boost", 1800),)),
    "minecraft:fire_resistance": (1, (("minecraft:fire_resistance", 3600),)),
    "minecraft:long_fire_resistance": (1, (("minecraft:fire_resistance", 9600),)),
    "minecraft:swiftness": (1, (("minecraft:speed", 3600),)),
    "minecraft:long_swiftness": (1, (("minecraft:speed", 9600),)),
    "minecraft:strong_swiftness": (1, (("minecraft:speed", 1800),)),
    "minecraft:slowness": (1, (("minecraft:slowness", 1800),)),
    "minecraft:long_slowness": (1, (("minecraft:slowness", 4800),)),
    "minecraft:strong_slowness": (1, (("minecraft:slowness", 400),)),
    "minecraft:turtle_master": (2, (("minecraft:slowness", 400),
                                    ("minecraft:resistance", 400))),
    "minecraft:long_turtle_master": (2, (("minecraft:slowness", 800),
                                         ("minecraft:resistance", 800))),
    "minecraft:strong_turtle_master": (2, (("minecraft:slowness", 400),
                                           ("minecraft:resistance", 400))),
    "minecraft:water_breathing": (1, (("minecraft:water_breathing", 3600),)),
    "minecraft:long_water_breathing": (1, (("minecraft:water_breathing", 9600),)),
    "minecraft:healing": (1, (("minecraft:instant_health", 1),)),
    "minecraft:strong_healing": (1, (("minecraft:instant_health", 1),)),
    "minecraft:harming": (1, (("minecraft:instant_damage", 1),)),
    "minecraft:strong_harming": (1, (("minecraft:instant_damage", 1),)),
    "minecraft:poison": (1, (("minecraft:poison", 900),)),
    "minecraft:long_poison": (1, (("minecraft:poison", 1800),)),
    "minecraft:strong_poison": (1, (("minecraft:poison", 432),)),
    "minecraft:regeneration": (1, (("minecraft:regeneration", 900),)),
    "minecraft:long_regeneration": (1, (("minecraft:regeneration", 1800),)),
    "minecraft:strong_regeneration": (1, (("minecraft:regeneration", 450),)),
    "minecraft:strength": (1, (("minecraft:strength", 3600),)),
    "minecraft:long_strength": (1, (("minecraft:strength", 9600),)),
    "minecraft:strong_strength": (1, (("minecraft:strength", 1800),)),
    "minecraft:weakness": (1, (("minecraft:weakness", 1800),)),
    "minecraft:long_weakness": (1, (("minecraft:weakness", 4800),)),
    "minecraft:luck": (1, (("minecraft:luck", 6000),)),
    "minecraft:slow_falling": (1, (("minecraft:slow_falling", 1800),)),
    "minecraft:long_slow_falling": (1, (("minecraft:slow_falling", 4800),)),
    "minecraft:wind_charged": (1, (("minecraft:wind_charged", 3600),)),
    "minecraft:weaving": (1, (("minecraft:weaving", 3600),)),
    "minecraft:oozing": (1, (("minecraft:oozing", 3600),)),
    "minecraft:infested": (1, (("minecraft:infested", 3600),)),
}


# ---------------------------------------------------------------------------
# 附魔名 -> 枚举 id（C: get_enchantment_from_name，顺序/子串匹配照抄）
# ---------------------------------------------------------------------------

def get_enchantment_from_name(ench: str) -> int:
    e = _ENCH_ID
    if ench == "minecraft:protection": return e["protection"]
    if ench == "minecraft:fire_protection": return e["fire_protection"]
    if ench == "minecraft:feather_falling": return e["feather_falling"]
    if ench == "minecraft:blast_protection": return e["blast_protection"]
    if ench == "minecraft:projectile_protection": return e["projectile_protection"]
    if ench == "minecraft:respiration": return e["respiration"]
    if ench == "minecraft:aqua_affinity": return e["aqua_affinity"]
    if ench == "minecraft:thorns": return e["thorns"]
    if ench == "minecraft:soul_speed": return e["soul_speed"]
    if ench == "minecraft:depth_strider": return e["depth_strider"]
    if ench == "minecraft:frost_walker": return e["frost_walker"]
    if ench == "minecraft:swift_sneak": return e["swift_sneak"]
    if ench == "minecraft:sharpness": return e["sharpness"]
    if ench == "minecraft:smite": return e["smite"]
    if ench == "minecraft:bane_of_arthropods": return e["bane_of_arthropods"]
    if ench == "minecraft:knockback": return e["knockback"]
    if ench == "minecraft:fire_aspect": return e["fire_aspect"]
    if ench == "minecraft:looting": return e["looting"]
    if "sweeping" in ench: return e["sweeping_edge"]
    if ench == "minecraft:efficiency": return e["efficiency"]
    if ench == "minecraft:silk_touch": return e["silk_touch"]
    if ench == "minecraft:fortune": return e["fortune"]
    if ench == "minecraft:power": return e["power"]
    if ench == "minecraft:flame": return e["flame"]
    if ench == "minecraft:infinity": return e["infinity"]
    if ench == "minecraft:punch": return e["punch"]
    if ench == "minecraft:multishot": return e["multishot"]
    if ench == "minecraft:quick_charge": return e["quick_charge"]
    if ench == "minecraft:piercing": return e["piercing"]
    if ench == "minecraft:impaling": return e["impaling"]
    if ench == "minecraft:loyalty": return e["loyalty"]
    if ench == "minecraft:riptide": return e["riptide"]
    if ench == "minecraft:channeling": return e["channeling"]
    if ench == "minecraft:luck_of_the_sea": return e["luck_of_the_sea"]
    if ench == "minecraft:lure": return e["lure"]
    if ench == "minecraft:density": return e["density"]
    if ench == "minecraft:breach": return e["breach"]
    if ench == "minecraft:wind_burst": return e["wind_burst"]
    if ench == "minecraft:lunge": return e["lunge"]
    if ench == "minecraft:mending": return e["mending"]
    if ench == "minecraft:unbreaking": return e["unbreaking"]
    if "binding" in ench: return e["binding_curse"]
    if "vanishing" in ench: return e["vanishing_curse"]
    return 0  # NO_ENCHANTMENT


# ---------------------------------------------------------------------------
# 适用性 / 宝藏 / 有效等级（C: is_applicable / is_treasure / test_effective_level）
# ---------------------------------------------------------------------------

def is_treasure_enchantment(ench: int) -> bool:
    return ench in (E_MENDING, E_BINDING, E_VANISHING, E_FROST_WALKER,
                    E_SOUL_SPEED, E_SWIFT_SNEAK, E_WIND_BURST)


def is_applicable(ench: int, item: int, use_overrides: bool) -> bool:
    if ench == 0:  # NO_ENCHANTMENT
        return False
    if item == IT_BOOK:
        return True  # the wildcard
    if ench in (E_VANISHING, E_UNBREAKING, E_MENDING):
        return True
    if ench == E_THORNS:
        return item == IT_CHESTPLATE or (use_overrides and item in
                                         (IT_LEGGINGS, IT_BOOTS, IT_HELMET))
    if ench in (E_BINDING, E_PROTECTION, E_FIRE_PROTECTION, E_BLAST_PROTECTION,
                E_PROJECTILE_PROTECTION):
        return item in (IT_CHESTPLATE, IT_LEGGINGS, IT_BOOTS, IT_HELMET)
    if ench in (E_RESPIRATION, E_AQUA_AFFINITY):
        return item == IT_HELMET
    if ench in (E_FEATHER_FALLING, E_DEPTH_STRIDER, E_FROST_WALKER, E_SOUL_SPEED):
        return item == IT_BOOTS
    if ench == E_SWIFT_SNEAK:
        return item == IT_LEGGINGS
    if ench in (E_SHARPNESS, E_SMITE, E_BANE):
        return item == IT_SWORD or item == IT_SPEAR or (use_overrides and item == IT_AXE)
    if ench in (E_KNOCKBACK, E_FIRE_ASPECT, E_LOOTING):
        return item == IT_SWORD or item == IT_SPEAR
    if ench == E_SWEEPING_EDGE:
        return item == IT_SWORD
    if ench in (E_EFFICIENCY, E_SILK_TOUCH, E_FORTUNE):
        return item in (IT_PICKAXE, IT_SHOVEL, IT_AXE, IT_HOE)
    if ench in (E_POWER, E_PUNCH, E_FLAME, E_INFINITY):
        return item == IT_BOW
    if ench in (E_MULTISHOT, E_QUICK_CHARGE, E_PIERCING):
        return item == IT_CROSSBOW
    if ench in (E_LUCK_OF_THE_SEA, E_LURE):
        return item == IT_FISHING_ROD
    if ench in (E_IMPALING, E_RIPTIDE, E_LOYALTY, E_CHANNELING):
        return item == IT_TRIDENT
    if ench in (E_DENSITY, E_BREACH, E_WIND_BURST):
        return item == IT_MACE
    if ench == E_LUNGE:
        return item == IT_SPEAR
    return False


def test_effective_level(ench: int, i: int, n: int) -> bool:
    """C: test_effective_level(enchantment, ench_level=i, level=n)。
    检查附魔等级 i 在有效等级 n 下是否可用，逐行照抄区间。"""
    if ench == E_PROTECTION:
        ok = 1 + (i - 1) * 11 <= n <= 1 + (i - 1) * 11 + 11
    elif ench == E_FIRE_PROTECTION:
        ok = 10 + (i - 1) * 8 <= n <= 10 + (i - 1) * 8 + 8
    elif ench == E_FEATHER_FALLING:
        ok = 5 + (i - 1) * 6 <= n <= 5 + (i - 1) * 6 + 6
    elif ench == E_BLAST_PROTECTION:
        ok = 5 + (i - 1) * 8 <= n <= 5 + (i - 1) * 8 + 8
    elif ench == E_PROJECTILE_PROTECTION:
        ok = 3 + (i - 1) * 6 <= n <= 3 + (i - 1) * 6 + 6
    elif ench == E_RESPIRATION:
        ok = 10 * i <= n <= 10 * i + 30
    elif ench == E_AQUA_AFFINITY:
        ok = 1 <= n <= 41
    elif ench == E_THORNS:
        ok = 10 + 20 * (i - 1) <= n <= 10 + 20 * (i - 1) + 50
    elif ench == E_DEPTH_STRIDER:
        ok = i * 10 <= n <= i * 10 + 15
    elif ench == E_FROST_WALKER:
        ok = i * 10 <= n <= i * 10 + 15
    elif ench == E_BINDING:
        ok = 25 <= n <= 50
    elif ench == E_SOUL_SPEED:
        ok = i * 10 <= n <= i * 10 + 15
    elif ench == E_SHARPNESS:
        ok = 1 + (i - 1) * 11 <= n <= 1 + (i - 1) * 11 + 20
    elif ench == E_SMITE:
        ok = 5 + (i - 1) * 8 <= n <= 5 + (i - 1) * 8 + 20
    elif ench == E_BANE:
        ok = 5 + (i - 1) * 8 <= n <= 5 + (i - 1) * 8 + 20
    elif ench == E_KNOCKBACK:
        ok = 5 + 20 * (i - 1) <= n <= 1 + (i * 10) + 50
    elif ench == E_FIRE_ASPECT:
        ok = 10 + 20 * (i - 1) <= n <= 1 + (i * 10) + 50
    elif ench == E_LOOTING:
        ok = 15 + (i - 1) * 9 <= n <= 1 + (i * 10) + 50
    elif ench == E_SWEEPING_EDGE:
        ok = 5 + (i - 1) * 9 <= n <= 5 + (i - 1) * 9 + 15
    elif ench == E_EFFICIENCY:
        ok = 1 + 10 * (i - 1) <= n <= 1 + (i * 10) + 50
    elif ench == E_SILK_TOUCH:
        ok = 15 <= n <= 1 + (i * 10) + 50
    elif ench == E_UNBREAKING:
        ok = 5 + (i - 1) * 8 <= n <= 1 + (i * 10) + 50
    elif ench == E_FORTUNE:
        ok = 15 + (i - 1) * 9 <= n <= 1 + (i * 10) + 50
    elif ench == E_POWER:
        ok = 1 + (i - 1) * 10 <= n <= 1 + (i - 1) * 10 + 15
    elif ench == E_PUNCH:
        ok = 12 + (i - 1) * 20 <= n <= 12 + (i - 1) * 20 + 25
    elif ench == E_FLAME:
        ok = 20 <= n <= 50
    elif ench == E_INFINITY:
        ok = 20 <= n <= 50
    elif ench in (E_LUCK_OF_THE_SEA, E_LURE):
        ok = 15 + (i - 1) * 9 <= n <= 1 + (i * 10) + 50
    elif ench == E_LOYALTY:
        ok = 5 + (i * 7) <= n <= 50
    elif ench == E_IMPALING:
        ok = 1 + (i - 1) * 8 <= n <= 1 + (i - 1) * 8 + 20
    elif ench == E_RIPTIDE:
        ok = 10 + (i * 7) <= n <= 50
    elif ench == E_CHANNELING:
        ok = 25 <= n <= 50
    elif ench == E_MULTISHOT:
        ok = 20 <= n <= 50
    elif ench == E_QUICK_CHARGE:
        ok = 12 + (i - 1) * 20 <= n <= 50
    elif ench == E_PIERCING:
        ok = 1 + (i - 1) * 10 <= n <= 50
    elif ench == E_MENDING:
        ok = i * 25 <= n <= i * 25 + 50
    elif ench == E_VANISHING:
        ok = 25 <= n <= 50
    elif ench in (E_DENSITY, E_LUNGE):
        ok = 5 + (i - 1) * 8 <= n <= 25 + (i - 1) * 8
    elif ench in (E_BREACH, E_WIND_BURST):
        ok = 15 + (i - 1) * 9 <= n <= 65 + (i - 1) * 9
    else:
        raise ValueError(f"test_effective_level: unknown enchantment id {ench}")
    return ok


# ---------------------------------------------------------------------------
# 附魔容忍度（C: get_enchantability —— 原注释 "I'm truly sorry."）
# ---------------------------------------------------------------------------

_ENCHANTABILITY: dict[str, int] = {}
for _m, _v in (("leather", 15), ("iron", 9), ("golden", 25), ("diamond", 10)):
    for _p in ("helmet", "chestplate", "leggings", "boots"):
        _ENCHANTABILITY[f"minecraft:{_m}_{_p}"] = _v
for _m, _v in (("iron", 14), ("golden", 22), ("diamond", 10)):
    for _p in ("pickaxe", "axe", "hoe", "shovel", "sword"):
        _ENCHANTABILITY[f"minecraft:{_m}_{_p}"] = _v
_ENCHANTABILITY["minecraft:fishing_rod"] = 1
_ENCHANTABILITY["minecraft:book"] = 1
_ENCHANTABILITY["minecraft:bow"] = 1


def get_enchantability(item_name: str) -> int:
    return _ENCHANTABILITY.get(item_name, 1)


# ---------------------------------------------------------------------------
# 可抽取附魔的遍历顺序（C: ORDER_V1_13/14/21/21_11）
# C 条件翻译：version > MC_1_13 -> V1_14；version > MC_1_20(=1.20.6) -> V1_21；
# version >= MC_1_21_11 -> V1_21_11。era 域等价条件见 _order_for_era。
# ---------------------------------------------------------------------------

_ORDER_V1_13 = (
    "protection", "fire_protection", "feather_falling", "blast_protection",
    "projectile_protection", "respiration", "aqua_affinity", "thorns",
    "depth_strider", "frost_walker", "binding_curse",
    "sharpness", "smite", "bane_of_arthropods", "knockback", "fire_aspect",
    "looting", "sweeping_edge",
    "efficiency", "silk_touch", "unbreaking", "fortune",
    "power", "punch", "flame", "infinity",
    "luck_of_the_sea", "lure", "loyalty", "impaling", "riptide", "channeling",
    "mending", "vanishing_curse",
)
_ORDER_V1_14 = _ORDER_V1_13 + ("multishot", "quick_charge", "piercing")
_ORDER_V1_21 = (
    "protection", "fire_protection", "feather_falling", "blast_protection",
    "projectile_protection", "respiration", "aqua_affinity", "thorns",
    "depth_strider",
    "sharpness", "smite", "bane_of_arthropods", "knockback", "fire_aspect",
    "looting", "sweeping_edge",
    "efficiency", "silk_touch", "unbreaking", "fortune",
    "power", "punch", "flame", "infinity",
    "luck_of_the_sea", "lure", "loyalty", "impaling", "riptide", "channeling",
    "multishot", "quick_charge", "piercing", "density", "breach",
    "binding_curse", "vanishing_curse", "frost_walker", "mending",
)
_ORDER_V1_21_11 = _ORDER_V1_21[:35] + ("lunge",) + _ORDER_V1_21[35:]

_ORDER_V1_13_IDS = tuple(_ENCH_ID[n] for n in _ORDER_V1_13)
_ORDER_V1_14_IDS = tuple(_ENCH_ID[n] for n in _ORDER_V1_14)
_ORDER_V1_21_IDS = tuple(_ENCH_ID[n] for n in _ORDER_V1_21)
_ORDER_V1_21_11_IDS = tuple(_ENCH_ID[n] for n in _ORDER_V1_21_11)


def _order_for_era(era: int) -> tuple[int, ...]:
    if era >= E_1_21_11:
        return _ORDER_V1_21_11_IDS
    if era > E_1_14:
        return _ORDER_V1_21_IDS
    if era > E_1_13:
        return _ORDER_V1_14_IDS
    return _ORDER_V1_13_IDS


def get_applicable_enchantments(item: int, era: int, use_overrides: bool) -> list[int]:
    """按版本 ORDER 表过滤适用附魔（C: get_applicable_enchantments）。"""
    return [e for e in _order_for_era(era) if is_applicable(e, item, use_overrides)]


# ---------------------------------------------------------------------------
# 1.21+ tag 展开（C: get_non_treasure_1_21 / get_on_random_loot_1_21）
# 成员顺序 = 原版 tag 文件顺序
# ---------------------------------------------------------------------------

_NON_TREASURE_PRE_1_21_11 = (
    "protection", "fire_protection", "feather_falling", "blast_protection",
    "projectile_protection", "respiration", "aqua_affinity", "thorns",
    "depth_strider",
    "sharpness", "smite", "bane_of_arthropods", "knockback", "fire_aspect",
    "looting", "sweeping_edge",
    "efficiency", "silk_touch", "unbreaking", "fortune",
    "power", "punch", "flame", "infinity",
    "luck_of_the_sea", "lure", "loyalty", "impaling", "riptide", "channeling",
    "multishot", "quick_charge", "piercing", "density", "breach",
)
_NON_TREASURE_1_21_11 = _NON_TREASURE_PRE_1_21_11 + ("lunge",)

_NT_PRE_IDS = tuple(_ENCH_ID[n] for n in _NON_TREASURE_PRE_1_21_11)
_NT_112_IDS = tuple(_ENCH_ID[n] for n in _NON_TREASURE_1_21_11)

_ON_RANDOM_LOOT_TAIL = (E_BINDING, E_VANISHING, E_FROST_WALKER, E_MENDING)


def get_non_treasure(era: int, item: int, use_overrides: bool) -> list[int]:
    tag = _NT_112_IDS if era >= E_1_21_11 else _NT_PRE_IDS
    return [e for e in tag if is_applicable(e, item, use_overrides)]


def get_on_random_loot(era: int, item: int, use_overrides: bool) -> list[int]:
    out = get_non_treasure(era, item, use_overrides)
    out += [e for e in _ON_RANDOM_LOOT_TAIL if is_applicable(e, item, use_overrides)]
    return out


def _is_tag_match(tag: str, name: str) -> bool:
    if not tag or not name:
        return False
    return (tag[1:] if tag.startswith("#") else tag) == name


# ---------------------------------------------------------------------------
# 等级向量（C: get_enchant_level_vector —— 每个附魔只取其最高有效等级一条）
# ---------------------------------------------------------------------------

def _build_level_vector(level: int, applicable: list[int]) -> tuple[int, int, list[tuple[int, int, int]]]:
    """返回 (vecSize, totalWeight, [(ench, ench_level, weight), ...])，
    对应 C 的 vec[0]=size, vec[1]=totalWeight, 之后三元组。"""
    triples: list[tuple[int, int, int]] = []
    total_weight = 0
    for ench in applicable:
        for ench_level in range(get_max_level(ench), 0, -1):
            if test_effective_level(ench, ench_level, level):
                w = _get_weight(ench)
                triples.append((ench, ench_level, w))
                total_weight += w
                break
    return len(triples), total_weight, triples


def _choose_enchantment(rng: loot_rng.JavaRandom, triples: list[tuple[int, int, int]],
                        total_weight: int) -> int:
    """C: choose_enchantment —— 累计权重扫描，返回三元组下标。
    w < 0 判定与 C 一致（w 减到负即选中）。"""
    w = rng.next_int(total_weight)
    for i, (_, _, weight) in enumerate(triples):
        w -= weight
        if w < 0:
            return i
    return len(triples) - 1  # vecCapacity - 3


def _remove_incompatible(triples: list[tuple[int, int, int]], index: int) -> list[tuple[int, int, int]]:
    """C: remove_incompatible_enchantments —— 移除与选中项互斥的三元组。"""
    _init_incompatible()
    chosen = triples[index][0]
    return [t for t in triples if not (chosen, t[0]) in _INCOMPATIBLE]


# ---------------------------------------------------------------------------
# ItemStack 与 LootFunction（C 结构/函数的类化；fun 用 kind 字符串分发）
# ---------------------------------------------------------------------------

@dataclass
class ItemStack:
    item: str
    count: int = 1
    # [(附魔规范短名, 等级), ...] 按获得顺序
    enchantments: list[tuple[str, int]] = field(default_factory=list)
    # set_effect / set_potion 写入的 (效果全名, 时长)；无则 None
    effect: tuple[str, int] | None = None
    # set_potion 写入的药水类型全名（如 minecraft:strong_regeneration）；
    # 供 UI 按类型显示药水名/染色图标（水瓶等无效果药水也保留）
    potion: str | None = None


class LootFunction:
    """对应 C 的 LootFunction：kind 决定 apply 行为，params 为其参数。
    apply 内的 RNG 消耗顺序与 C 完全一致；版本相关列表在解析期烘焙。"""

    __slots__ = ("kind", "params")

    def __init__(self, kind: str, params: dict):
        self.kind = kind
        self.params = params

    def apply(self, rng: loot_rng.JavaRandom, is_: ItemStack) -> None:
        k = self.kind
        if k == "set_count_constant":
            is_.count = self.params["min"]
        elif k == "set_count_uniform":
            lo, hi = self.params["min"], self.params["max"]
            is_.count = rng.next_int(hi - lo + 1) + lo
        elif k == "set_effect":
            entries = self.params["entries"]  # [(效果全名, min, max), ...]
            effect_name, dmin, dmax = entries[rng.next_int(len(entries))]
            duration = rng.next_int_between(dmin, dmax)
            if effect_name not in _INSTANT_EFFECTS:  # 非瞬时效果时长 x20
                duration *= 20
            is_.effect = (effect_name, duration)
        elif k == "set_potion":
            # 目前只有单效果药水生效（C 注释：buried treasure / abandoned camps）
            pid = self.params["id"]
            is_.potion = pid
            potion = POTIONS[pid]
            if potion[0] == 1:
                is_.effect = potion[1][0]
        elif k == "skip_n":
            rng.skip_n(self.params["n"])
        elif k == "skip_one":
            rng.skip_n(1)
        elif k == "no_op":
            pass
        elif k == "enchant_randomly_one":
            # C: set_enchantment_random_level_function —— 与列表变体不同：
            # 恒消耗 nextInt(1) 再 nextInt(max_level)+1（max_level==1 时也消耗）。
            rng.next_int(1)
            level = rng.next_int(self.params["max_level"]) + 1
            is_.enchantments = [(self.params["ench"], level)]
        elif k == "enchant_randomly":
            # C: enchant_randomly_function —— 列表变体：nextInt(n) 选附魔，
            # 仅 max_level > 1 时再消耗 nextInt(max_level)+1。
            pairs = self.params["pairs"]  # [(ench, max_level), ...] = 构建顺序
            ench, max_level = pairs[rng.next_int(len(pairs))]
            level = rng.next_int(max_level) + 1 if max_level > 1 else 1
            is_.enchantments = [(ench, level)]
        elif k == "enchant_with_levels":
            self._apply_enchant_with_levels(rng, is_)
        else:  # pragma: no cover
            raise ValueError(f"unknown loot function kind: {k}")

    def _apply_enchant_with_levels(self, rng, is_: ItemStack) -> None:
        p = self.params
        enchantability = p["enchantability"]
        min_l, max_l = p["min_level"], p["max_level"]
        vectors = p["vectors"]  # vectors[level+1] = (size, totalWeight, triples)

        # 有效等级：min + nextInt(span) + 1 + nextInt(delta) + nextInt(delta)
        level = min_l
        if min_l != max_l:
            level += rng.next_int(max_l - min_l + 1)

        delta = enchantability // 4 + 1
        level += 1 + rng.next_int(delta) + rng.next_int(delta)

        # C: amplifier = (absNextFloat + absNextFloat - 1.0F) * 0.15F，全程 float32
        amp = (np.float32(rng.next_float()) + np.float32(rng.next_float())
               - np.float32(1.0)) * np.float32(0.15)
        # C: java_round_positive((float)level + (float)level * amplifier)
        #    —— f + 0.5F 同样在 float32 域相加后再 floor
        val = np.float32(level) + np.float32(level) * amp
        level = int(math.floor(float(np.float32(val + np.float32(0.5)))))

        # C 直接读 varparams_int_arr[level + 1]（越界为 UB）；Python 侧钳制到
        # 末尾向量防御（真实参数下 level 不会超过 2*max_level-1，不可达）。
        vec = vectors[min(level + 1, len(vectors) - 1)]
        vec_size, total_weight, triples = vec
        if vec_size == 0:
            return

        triples = list(triples)
        index = _choose_enchantment(rng, triples, total_weight)
        result = [(ENCHANTMENT_ORDER[triples[index][0]], triples[index][1])]

        while rng.next_int(50) <= level:
            triples = _remove_incompatible(triples, index)
            total_weight = sum(t[2] for t in triples)
            if not triples:
                break
            index = _choose_enchantment(rng, triples, total_weight)
            result.append((ENCHANTMENT_ORDER[triples[index][0]], triples[index][1]))
            level //= 2

        is_.enchantments = result


# ---------------------------------------------------------------------------
# LootTable 与求值（C: loot_table_context.c 的池结构 + generate_loot）
# ---------------------------------------------------------------------------

class _Entry:
    """C LootPool 的 entry_to_item/entry_functions_* 的合并表示。
    item=None 且 subtable=None -> 空条目（C: entry id -1）。"""

    __slots__ = ("item", "subtable", "functions")

    def __init__(self):
        self.item: str | None = None      # minecraft:xxx 全名
        self.subtable: int | None = None  # 子表在 LootTable.subtables 中的下标
        self.functions: list = []


class _Pool:
    __slots__ = ("min_rolls", "max_rolls", "uniform_rolls", "conditions",
                 "entries", "total_weight", "precomputed")

    def __init__(self):
        self.min_rolls = 0
        self.max_rolls = 0
        self.uniform_rolls = False  # False: 数字 rolls（不消耗）；True: 对象（恒消耗）
        self.conditions: list = []  # random_chance 概率（float32 化后）
        self.entries: list = []
        self.total_weight = 0
        self.precomputed: list = []  # 按权重展开的条目下标（C: precomputed_loot）


@dataclass
class LootTable:
    pools: list = field(default_factory=list)
    subtables: list = field(default_factory=list)

    def generate(self, rng: loot_rng.JavaRandom, out: list) -> None:
        for pool in self.pools:
            self._generate_pool(pool, rng, out)

    def _generate_pool(self, pool: _Pool, rng, out: list) -> None:
        # 1) 池条件：random_chance -> nextFloat < p；任一失败整池跳过
        for chance in pool.conditions:
            if not (rng.next_float() < chance):
                return
        # 2) rolls：数字 = 常量（不消耗）；对象 = uniform（min==max 也消耗 nextInt）
        if pool.uniform_rolls:
            rolls = rng.next_int(pool.max_rolls - pool.min_rolls + 1) + pool.min_rolls
        else:
            rolls = pool.min_rolls
        # 3) 逐 roll 加权抽取：entry_count <= 1 时不消耗 nextInt
        for _ in range(rolls):
            if len(pool.entries) > 1:
                w = rng.next_int(pool.total_weight)
            else:
                w = 0
            entry = pool.entries[pool.precomputed[w]]
            if entry.subtable is not None:
                self.subtables[entry.subtable].generate(rng, out)  # 子表内联展开
                continue
            if entry.item is None:
                continue  # 空条目
            stack = ItemStack(item=entry.item)
            for fn in entry.functions:
                fn.apply(rng, stack)
            out.append(stack)


# ---------------------------------------------------------------------------
# JSON 解析（C: loot_table_parser.c）
# ---------------------------------------------------------------------------

def _ench_pairs(ids: list) -> list:
    return [(ENCHANTMENT_ORDER[i], get_max_level(i)) for i in ids]


def _enchant_randomly_full(item_type: int, era: int, is_treasure: bool) -> LootFunction:
    # C: create_enchant_randomly —— ORDER 表（use_overrides=1），可过滤 treasure
    ids = get_applicable_enchantments(item_type, era, True)
    if not is_treasure:
        ids = [i for i in ids if not is_treasure_enchantment(i)]
    return LootFunction("enchant_randomly", {"pairs": _ench_pairs(ids)})


def _enchant_randomly_tag(tag: str, item_type: int, era: int):
    # C: create_enchant_randomly_tag；不匹配或空 -> None（调用方回退全表）
    if _is_tag_match(tag, "minecraft:on_random_loot"):
        ids = get_on_random_loot(era, item_type, True)
    elif (_is_tag_match(tag, "minecraft:non_treasure")
            or _is_tag_match(tag, "minecraft:in_enchanting_table")):
        ids = get_non_treasure(era, item_type, True)
    else:
        return None
    if not ids:
        return None
    return LootFunction("enchant_randomly", {"pairs": _ench_pairs(ids)})


def _parse_enchant_randomly(fd: dict, item_name: str, era: int) -> LootFunction:
    item_type = get_item_type(item_name)
    is_treasure = bool(fd.get("treasure"))  # 默认 false

    options = fd.get("options")
    if options is None:
        options = fd.get("enchantments")  # 旧字段名
    if options is None:
        if era >= E_1_21_9:  # 无字段且 1.21.9+ -> 默认 tag（in_enchanting_table）
            fn = _enchant_randomly_tag("#minecraft:in_enchanting_table", item_type, era)
            return fn if fn is not None else _enchant_randomly_full(item_type, era,
                                                                    is_treasure)
        return _enchant_randomly_full(item_type, era, is_treasure)

    if isinstance(options, str):
        if options.startswith("#"):
            fn = _enchant_randomly_tag(options, item_type, era)
            return fn if fn is not None else _enchant_randomly_full(item_type, era,
                                                                    is_treasure)
        ench = get_enchantment_from_name(options)
        if ench == 0:  # 未识别的名字 -> 全表（C 同款分支）
            return _enchant_randomly_full(item_type, era, is_treasure)
        return LootFunction("enchant_randomly_one",
                            {"ench": ENCHANTMENT_ORDER[ench],
                             "max_level": get_max_level(ench)})

    if len(options) == 1:  # 单元素列表 -> one-enchant 变体
        ench = get_enchantment_from_name(options[0])
        return LootFunction("enchant_randomly_one",
                            {"ench": ENCHANTMENT_ORDER[ench],
                             "max_level": get_max_level(ench)})
    return LootFunction("enchant_randomly",
                        {"pairs": _ench_pairs([get_enchantment_from_name(s)
                                               for s in options])})


def _make_enchant_with_levels(item_name: str, min_l: int, max_l: int,
                              applicable: list) -> LootFunction:
    # vectors[level+1] = (size, totalWeight, triples)；level 覆盖 0..2*max_l-1
    vectors = [None]
    for level in range(2 * max_l):
        size, weight, triples = _build_level_vector(level, applicable)
        vectors.append((size, weight, triples))
    return LootFunction("enchant_with_levels", {
        "enchantability": get_enchantability(item_name),
        "min_level": min_l,
        "max_level": max_l,
        "vectors": vectors,
    })


def _parse_enchant_with_levels(fd: dict, item_name: str, era: int) -> LootFunction:
    item_type = get_item_type(item_name)

    levels = fd.get("levels")
    min_l = max_l = 0
    if isinstance(levels, dict):
        min_l, max_l = int(levels["min"]), int(levels["max"])
    elif levels is not None:
        min_l = max_l = int(levels)

    is_treasure = True  # 注意：enchant_with_levels 的 treasure 默认 true
    treasure = fd.get("treasure")
    if treasure is not None:
        is_treasure = bool(treasure)

    options = fd.get("options")
    if isinstance(options, str) and options.startswith("#"):
        if _is_tag_match(options, "minecraft:on_random_loot"):
            applicable = get_on_random_loot(era, item_type, False)  # use_overrides=0
        elif (_is_tag_match(options, "minecraft:non_treasure")
                or _is_tag_match(options, "minecraft:in_enchanting_table")):
            applicable = get_non_treasure(era, item_type, False)
        else:
            applicable = None
        if applicable is not None:
            if not is_treasure:
                applicable = [i for i in applicable
                              if not is_treasure_enchantment(i)]
            return _make_enchant_with_levels(item_name, min_l, max_l, applicable)

    # 全表路径（C: create_enchant_with_levels，use_overrides=0）
    applicable = get_applicable_enchantments(item_type, era, False)
    if not is_treasure:
        applicable = [i for i in applicable if not is_treasure_enchantment(i)]
    return _make_enchant_with_levels(item_name, min_l, max_l, applicable)


def _parse_set_count(fd: dict) -> LootFunction:
    count = fd.get("count")
    if isinstance(count, dict):
        lo, hi = int(count["min"]), int(count["max"])
    else:
        lo = hi = int(count)
    if lo == hi:  # min==max -> 常量（C 在 create_set_count 时已分流，不消耗 RNG）
        return LootFunction("set_count_constant", {"min": lo})
    return LootFunction("set_count_uniform", {"min": lo, "max": hi})


def _parse_set_effect(fd: dict) -> LootFunction:
    entries = []
    for eff in fd["effects"]:
        duration = eff["duration"]  # C 仅接受 minecraft:uniform
        entries.append((eff["type"], int(duration["min"]), int(duration["max"])))
    return LootFunction("set_effect", {"entries": entries})


def _parse_functions(entry_data: dict, item_name: str, era: int) -> list:
    flist = entry_data.get("functions")
    if flist is None:
        flist = entry_data.get("modifier")  # 旧字段名
    if flist is None:
        return []
    if isinstance(flist, dict):  # 单对象也合法（C 包一层 wrapper）
        flist = [flist]

    out = []
    for fd in flist:
        fname = fd.get("function")
        if fname is None:
            fname = fd.get("type")
        if fname == "minecraft:set_count":
            out.append(_parse_set_count(fd))
        elif fname == "minecraft:enchant_with_levels":
            out.append(_parse_enchant_with_levels(fd, item_name, era))
        elif fname == "minecraft:enchant_randomly":
            out.append(_parse_enchant_randomly(fd, item_name, era))
        elif fname == "minecraft:set_damage":
            out.append(LootFunction("skip_one", {}))
        elif fname == "minecraft:set_stew_effect":
            out.append(_parse_set_effect(fd))
        elif fname == "minecraft:set_potion":
            out.append(LootFunction("set_potion", {"id": fd["id"]}))
        elif fname == "minecraft:set_ominous_bottle_amplifier":
            out.append(LootFunction("skip_one", {}))
        else:  # exploration_map / set_name / set_components ... 一律 no_op
            out.append(LootFunction("no_op", {}))
    return out


def load_loot_table(data, era: int, resolve=None) -> LootTable:
    """解析战利品表。data: dict / JSON 字符串 / bytes；era 为版本时代。
    resolve(name) -> dict 用于解析一层子表（C 同样拒绝嵌套子表）。"""
    if isinstance(data, (str, bytes)):
        data = json.loads(data)

    table = LootTable()
    subtable_index: dict = {}

    def ensure_subtable(name: str) -> int:
        idx = subtable_index.get(name)
        if idx is None:
            if resolve is None:
                raise ValueError(f"unresolved loot subtable: {name}")
            sub = load_loot_table(resolve(name), era, resolve=None)
            idx = len(table.subtables)
            table.subtables.append(sub)
            subtable_index[name] = idx
        return idx

    for pool_data in data["pools"]:
        pool = _Pool()

        rolls = pool_data["rolls"]
        if isinstance(rolls, dict):  # C: 对象一律 uniform（恒消耗）
            pool.min_rolls = int(rolls["min"])
            pool.max_rolls = int(rolls["max"])
            pool.uniform_rolls = True
        else:
            pool.min_rolls = pool.max_rolls = int(rolls)

        for cond in pool_data.get("conditions") or ():
            if cond.get("condition") != "minecraft:random_chance":
                raise ValueError(f"unsupported loot condition: {cond.get('condition')}")
            # C: chance 先转 float32 再比较（避免双精度比较的边界差）
            pool.conditions.append(float(np.float32(cond["chance"])))

        total_weight = 0
        precomputed: list = []
        for entry_data in pool_data["entries"]:
            weight = int(entry_data.get("weight", 1))
            entry = _Entry()
            if entry_data.get("type") == "minecraft:loot_table":
                entry.subtable = ensure_subtable(entry_data["value"])
            else:
                name = entry_data.get("name")
                if name is not None:
                    entry.item = name
                    entry.functions = _parse_functions(entry_data, name, era)
            precomputed.extend([len(pool.entries)] * weight)
            pool.entries.append(entry)
            total_weight += weight

        pool.total_weight = total_weight
        pool.precomputed = precomputed
        table.pools.append(pool)

    return table


def load_loot_table_file(path: str, era: int, resolve=None) -> LootTable:
    with open(path, "r", encoding="utf-8") as f:
        return load_loot_table(f.read(), era, resolve=resolve)


# ---------------------------------------------------------------------------
# 快照选表：同一张表在不同版本间内容会变（C loot_tables.c 的分档边界）。
# 命名规范 <table>.<1_20|1_21|1_21_11>.json；未分档的表用无后缀快照。
# 分档边界（C loot_tables.c 双级分发，1.21 线三档）：
#     shipwreck_supply/map/treasure: >=1.21.11 -> 1_21_11；>=1.21 -> 1_21；否则 1_20
#     pillager_outpost:              >=1.21.9  -> 1_21_11；>=1.21 -> 1_21；否则 1_20
#
# 快照版本自包含（C 烘焙表语义）：init_xxx_1_21_11() 烧死 MC_1_21_11，
# 运行时 mc=1.21.9 也按 1.21.11 语义展开 tag/全表（探针实证：outpost
# book 在 1.21.9 下候选 n=40 含 lunge）。故分档快照的解析 era 取快照
# 档位，运行时 era 只决定选哪一档。
# ---------------------------------------------------------------------------
_SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "data", "loot")

_LOOT_TABLE_ERAS: dict[str, tuple[int, str, str]] = {
    # 表名 -> (边界1: era>=边界1 用 1_21_11 档；否则 era>=边界2 用 1_21 档；
    #           再否则旧档后缀)。对应 C loot_tables.c 双级分发：
    #   < MC_1_21 -> 1_20 档；< MC_1_21_11 -> 1_21 档；否则 1_21_11 档。
    # 1_21 档 = 官方 1.21.1 jar 原生表（supply/outpost 皮革装备与书本
    # 带(options: #minecraft:on_random_loot)，走 tag HolderSet 路径，
    # 已由真实种子数据实锤：冰霜行者I / 荆棘III+弹射物保护I 全命中）。
    "shipwreck_supply": (E_1_21_11, E_1_21, "1_20"),
    "shipwreck_map": (E_1_21_11, E_1_21, "1_20"),
    "shipwreck_treasure": (E_1_21_11, E_1_21, "1_20"),
    "pillager_outpost": (E_1_21_9, E_1_21, "1_20"),
    # 林地府邸：resin_clump（1.21.4+ 树脂）仅存在于 1.21.11 档；
    # 1_21/1_20 档从本地官方 jar 提取（1.21.1-NeoForge / 1.20.1）。
    # 表结构 1.14~1.21.11 无其他变动（三档逐条 diff 实证）。
    "woodland_mansion": (E_1_21_11, E_1_21, "1_20"),
    # 海底废墟：1.21.11 相对 1.21.1 纯新增（big：stone_spear 权重 2 +
    # 鹦鹉螺铠四色新 pool；small：stone_spear + 鹦鹉螺铠 pool；small
    # 无 golden_apple），1.21.9 表与 1.21.1 相同 -> 边界 E_1_21_11。
    # 1_20 档 = 官方 1.20.1 jar 原生表（small 有 stone_axe/rotten_flesh
    # 无 golden_apple；enchant_randomly 无 options 字段）。
    "underwater_ruin_big": (E_1_21_11, E_1_21, "1_20"),
    "underwater_ruin_small": (E_1_21_11, E_1_21, "1_20"),
    # 远古城市：1.21.11 主表 saddle→leather（同槽位换物品，
    # 1.21.1/1.20.1 条目一致仅 enchant_randomly 格式差），三档
    # 均取官方 jar 原生表。ice_box 三版本逐字节相同 → 未分档单文件。
    "ancient_city": (E_1_21_11, E_1_21, "1_20"),
    # 沙漠神殿/丛林神庙：三档官方 jar 原生表（1.20.1/1.21/1.21.11
    # 逐档 diff 有差异）；jungle_temple_dispenser 三版本逐字节相同
    # → 未分档单文件。
    "desert_pyramid": (E_1_21_11, E_1_21, "1_20"),
    "jungle_temple": (E_1_21_11, E_1_21, "1_20"),
    # 废弃传送门/埋藏的宝藏：三档官方 jar 原生表；ruined_portal
    # 三档逐档 diff 有差异（1.21.11 增 lodestone、1.21 调整权重）；
    # buried_treasure 1_21 档与 1_20 档逐字节相同（复制 1_20 内容
    # 占位），1_21_11 增鹦鹉螺铠四色 + iron_spear。
    "ruined_portal": (E_1_21_11, E_1_21, "1_20"),
    "buried_treasure": (E_1_21_11, E_1_21, "1_20"),
}

# 快照档后缀 -> 解析 era（对齐 C 烘焙表 version 烧死语义）
_SNAPSHOT_ERAS = {
    "1_20": E_1_14,       # C: MC_1_20 落在 ORDER_V1_14 语义区间（1.14~1.20）
    "1_21": E_1_21,       # 1.21~1.21.8：1.21.1 jar 原生语义
    "1_21_11": E_1_21_11,
}


def load_loot_snapshot(table_name: str, era: int,
                       snapshot_dir: str | None = None) -> LootTable:
    """按 (表名, era) 选取正确版本档的快照并求值加载。

    table_name: "chests/xxx" 或 "xxx"；无分档的表直接取 xxx.json。
    分档快照用快照档位自己的 era 解析（版本自包含）；未分档快照
    保持运行时 era。
    同目录快照存在时自动作一层子表 resolve（trial_chambers/reward
    引用 reward_common/rare/unique；C 同样只支持一层）。
    """
    name = table_name.split("/")[-1]
    seg = _LOOT_TABLE_ERAS.get(name)

    def _resolve(snapshot_dir: str) -> object:
        # 子表按同目录快照文件名（剥命名空间 + minecraft:）查找；
        # 返回原始 JSON dict（ensure_subtable 内部再 load_loot_table）。
        # 未分档子表即同目录 <短名>.json；缺失则报未解析（C 同语义）。
        def resolve(sub_name: str):
            sub_short = sub_name.split("/")[-1]
            p = os.path.join(snapshot_dir, sub_short + ".json")
            if not os.path.exists(p):
                raise ValueError(f"unresolved loot subtable: {sub_name}")
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        return resolve

    if seg is None:
        path = os.path.join(snapshot_dir or _SNAPSHOT_DIR, name + ".json")
        return load_loot_table_file(path, era,
                                    resolve=_resolve(snapshot_dir
                                                     or _SNAPSHOT_DIR))
    boundary, mid_boundary, old_suffix = seg
    if era >= boundary:
        suffix = "1_21_11"
    elif era >= mid_boundary:
        suffix = "1_21"
    else:
        suffix = old_suffix
    _dir = snapshot_dir or _SNAPSHOT_DIR
    path = os.path.join(_dir, "%s.%s.json" % (name, suffix))
    return load_loot_table_file(path, _SNAPSHOT_ERAS[suffix],
                                resolve=_resolve(_dir))


def generate_loot(table: LootTable, seed: int) -> list:
    """对整张表求值；seed 为该箱的 LootTableSeed（有符号 int64 亦可）。

    求值用标准 Java LCG（C: RandomSource.create(lootSeed) =
    LegacyRandomSource，默认 JAVA_RANDOM）；LootTableSeed 的推导才用
    Xoroshiro（见 loot_rng.loot_seed_for_chest），两条线不可混用。
    """
    rng = loot_rng.JavaRandom(seed)
    out: list = []
    table.generate(rng, out)
    return out


__all__ = [
    "ItemStack", "LootFunction", "LootTable",
    "load_loot_table", "load_loot_table_file", "load_loot_snapshot",
    "generate_loot",
    "era_for_version", "get_item_type", "get_enchantment_from_name",
    "get_max_level", "get_enchantability", "get_applicable_enchantments",
    "get_non_treasure", "get_on_random_loot",
    "is_applicable", "is_treasure_enchantment", "test_effective_level",
    "POTIONS", "ENCHANTMENT_ORDER",
    "E_1_13", "E_1_14", "E_1_21", "E_1_21_9", "E_1_21_11", "E_26_2",
]
