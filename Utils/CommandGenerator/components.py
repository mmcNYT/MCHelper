# -*- coding: utf-8 -*-
"""CommandGenerator：数据组件元数据（名称 / 形态 / 中文名 / 分组）。

**权威来源**：
  - 形态与字段：`comp_meta.COMP_META`（自动生成，来自各组件的
    CODEC 定义 —— 见 .temp/gen_comp_meta.py）
  - 组件清单：反编译 DataComponents.java 的全部 79 个
    `register("id", ...)`

本模块只补「源码里没有」的信息：**中文名**与**UI 分组**。
编辑器形态一律以 `comp_meta` 为准，避免两处定义漂移。

`comp_meta.COMP_META[cid]["kind"]` 取值（10 种）：
    compound   有字段的复合（按 fields 生成子控件）
    list       列表
    map        键值映射（如 enchantments）
    scalar     标量（整数/浮点/布尔）
    holder     资源 holder（如音效、伤害类型）
    nbt        复合标签
    text       文本组件
    textlines  文本组件列表（lore）
    enum_string 枚举 -> 字符串
    unit       无值（{}）
"""
from __future__ import annotations

from Utils.CommandGenerator.comp_meta import COMP_META

# ---------------------------------------------------------------------------
# 中文名（仅 UI 显示；未列出的显示 id）
# ---------------------------------------------------------------------------
CN = {
    "custom_data": "自定义数据",
    "max_stack_size": "最大堆叠数",
    "max_damage": "最大耐久",
    "damage": "已损失耐久",
    "unbreakable": "无法破坏",
    "use_effects": "使用效果",
    "custom_name": "自定义名称",
    "minimum_attack_charge": "最小攻击蓄力",
    "damage_type": "伤害类型",
    "item_name": "物品名称",
    "item_model": "物品模型",
    "lore": "描述文字",
    "rarity": "稀有度",
    "enchantments": "附魔",
    "can_place_on": "可放置在",
    "can_break": "可破坏",
    "attribute_modifiers": "属性修饰符",
    "custom_model_data": "自定义模型数据",
    "tooltip_display": "提示框显示控制",
    "repair_cost": "修复惩罚",
    "creative_slot_lock": "创造模式槽位锁定",
    "enchantment_glint_override": "附魔光效覆盖",
    "intangible_projectile": "无形弹射物",
    "food": "食物",
    "consumable": "可消耗",
    "use_remainder": "使用后剩余物",
    "use_cooldown": "使用冷却",
    "damage_resistant": "伤害抗性",
    "tool": "工具",
    "weapon": "武器",
    "attack_range": "攻击范围",
    "enchantable": "可附魔",
    "equippable": "可装备",
    "repairable": "可修复",
    "glider": "滑翔",
    "tooltip_style": "提示框样式",
    "death_protection": "死亡保护",
    "blocks_attacks": "格挡攻击",
    "piercing_weapon": "穿刺武器",
    "kinetic_weapon": "动能武器",
    "swing_animation": "挥动动画",
    "stored_enchantments": "收纳附魔",
    "dyed_color": "染色",
    "map_color": "地图颜色",
    "map_id": "地图编号",
    "map_decorations": "地图标记",
    "map_post_processing": "地图后处理",
    "charged_projectiles": "装填的弹射物",
    "bundle_contents": "收纳袋内容",
    "potion_contents": "药水内容",
    "potion_duration_scale": "药水时长倍率",
    "suspicious_stew_effects": "迷之炖菜效果",
    "writable_book_content": "书与笔内容",
    "written_book_content": "成书内容",
    "trim": "盔甲纹饰",
    "debug_stick_state": "调试棒状态",
    "entity_data": "实体数据",
    "bucket_entity_data": "桶装实体数据",
    "block_entity_data": "方块实体数据",
    "instrument": "乐器",
    "provides_trim_material": "提供纹饰材料",
    "ominous_bottle_amplifier": "不祥之瓶等级",
    "jukebox_playable": "唱片机曲目",
    "provides_banner_patterns": "提供旗帜图案",
    "recipes": "配方",
    "lodestone_tracker": "磁石追踪",
    "firework_explosion": "烟花爆炸",
    "fireworks": "烟花",
    "profile": "头颅皮肤",
    "note_block_sound": "音符盒音效",
    "banner_patterns": "旗帜图案",
    "base_color": "基础颜色",
    "pot_decorations": "饰纹陶罐图案",
    "container": "容器内容",
    "block_state": "方块状态",
    "bees": "蜜蜂",
    "lock": "锁",
    "container_loot": "容器战利品表",
    "break_sound": "破坏音效",
}

# ---------------------------------------------------------------------------
# UI 分组（「添加组件」下拉的 optgroup 顺序）
# ---------------------------------------------------------------------------
GROUPS = [
    ("常用", [
        "enchantments", "custom_name", "lore", "unbreakable", "damage",
        "max_damage", "max_stack_size", "repair_cost",
        "attribute_modifiers", "custom_model_data", "dyed_color",
        "item_name", "rarity", "enchantment_glint_override",
        "tooltip_display", "stored_enchantments",
    ]),
    ("战斗与工具", [
        "tool", "weapon", "attack_range", "enchantable", "repairable",
        "blocks_attacks", "piercing_weapon", "kinetic_weapon",
        "damage_resistant", "death_protection", "minimum_attack_charge",
        "swing_animation",
    ]),
    ("消耗与食物", [
        "food", "consumable", "use_remainder", "use_cooldown",
        "use_effects", "potion_contents", "potion_duration_scale",
        "ominous_bottle_amplifier", "suspicious_stew_effects",
    ]),
    ("装备与外观", [
        "equippable", "glider", "trim", "provides_trim_material",
        "base_color", "item_model", "tooltip_style",
        "profile", "instrument",
    ]),
    ("容器与存储", [
        "container", "container_loot", "bundle_contents",
        "charged_projectiles", "block_entity_data", "entity_data",
        "bucket_entity_data", "lock", "bees", "pot_decorations",
    ]),
    ("地图与书籍", [
        "map_id", "map_color", "map_decorations", "map_post_processing",
        "writable_book_content", "written_book_content",
    ]),
    ("其他", [
        "custom_data", "creative_slot_lock", "intangible_projectile",
        "damage_type", "debug_stick_state", "recipes",
        "provides_banner_patterns", "banner_patterns",
        "note_block_sound", "break_sound", "jukebox_playable",
        "lodestone_tracker", "firework_explosion", "fireworks",
        "block_state",
    ]),
]

# 扁平清单（含去重；未在 GROUPS 里列出的组件补到「其他」末尾）
ALL_IDS = sorted(COMP_META)

_grouped = {c for _g, cs in GROUPS for c in cs}
_missing = [c for c in ALL_IDS if c not in _grouped]
if _missing:
    for i, (gname, cs) in enumerate(GROUPS):
        if gname == "其他":
            GROUPS[i] = (gname, cs + _missing)
            break


# ---------------------------------------------------------------------------
# enum_string 形态组件的合法取值
#
# 这些组件的值是「枚举名 -> 字符串」，必须给出真实取值，否则会产出
# `minecraft:rarity=`（空值，游戏无法解析）。
# 来源：对应枚举类的 StringRepresentable fromEnum / 常量名。
# ---------------------------------------------------------------------------
ENUM_CHOICES = {
    "rarity": ["common", "uncommon", "rare", "epic"],
    "base_color": [
        "white", "orange", "magenta", "light_blue", "yellow", "lime",
        "pink", "gray", "light_gray", "cyan", "purple", "blue", "brown",
        "green", "red", "black",
    ],
    "map_post_processing": ["lock", "scale"],
    "damage_type": [
        "in_fire", "lightning_bolt", "on_fire", "lava", "hot_floor",
        "in_wall", "cramming", "drown", "starve", "cactus", "fall",
        "fly_into_wall", "out_of_world", "generic", "magic", "wither",
        "dragon_breath", "dry_out", "sweet_berry_bush", "freeze",
        "stalagmite", "outside_border", "generic_kill", "campfire",
    ],
    "firework_explosion": ["small", "large", "star", "creeper", "burst"],
}

# ---------------------------------------------------------------------------
# 字段级枚举取值（codec 为某个内部枚举 CODEC，需给下拉）
#
# 键：组件 id -> {字段键: [取值]}
# 用于 `FireworkExplosion.Shape.CODEC` 这类「值类型是内部枚举」的字段；
# 若不给出，必填字段会因文本框为空而被丢弃（静默丢数据）。
# ---------------------------------------------------------------------------
FIELD_ENUMS = {
    "firework_explosion": {
        "shape": ["small", "large", "star", "creeper", "burst"],
    },
    "equippable": {
        "slot": ["any", "mainhand", "offhand", "hand", "feet", "legs",
                 "chest", "head", "armor", "body"],
    },
    "swing_animation": {
        "type": ["none", "whack", "stab"],
    },
}


def field_enum(cid: str, key: str) -> list:
    """某组件某字段的合法枚举取值（无则空列表）。"""
    return (FIELD_ENUMS.get(cid) or {}).get(key, [])


def enum_choices(cid: str) -> list:
    """enum_string 组件的合法取值（无则空列表）。"""
    return ENUM_CHOICES.get(cid, [])


def label_of(cid: str) -> str:
    """组件中文名（无则返回 id 本身）。"""
    return CN.get(cid, cid)


def kind_of(cid: str) -> str:
    """组件形态（来自 comp_meta）。"""
    m = COMP_META.get(cid)
    return m["kind"] if m else "compound"


def fields_of(cid: str) -> list:
    """compound 组件的字段表（其余返回空）。"""
    m = COMP_META.get(cid)
    return m["fields"] if m else []


def display(cid: str) -> str:
    """下拉里的一行：`中文名（id）`。"""
    cn = CN.get(cid)
    return f"{cn}（{cid}）" if cn else cid


def grouped_ids() -> list:
    """[(分组名, [cid, ...]), ...]，只含实际存在的组件。"""
    out = []
    for gname, cs in GROUPS:
        ids = [c for c in cs if c in COMP_META]
        if ids:
            out.append((gname, ids))
    return out


# 兼容旧接口（give.py 早期版本用过 COMMON；保留以免外部引用断裂）
COMMON = [(cid, CN.get(cid, cid), kind_of(cid))
          for cid in GROUPS[0][1] if cid in COMP_META]
OTHER = [c for c in ALL_IDS if c not in {x[0] for x in COMMON}]
