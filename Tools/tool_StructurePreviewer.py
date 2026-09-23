# -*- coding: utf-8 -*-
"""StructurePreviewer 工具：按世界种子预览结构构造 + 预测箱子战利品。

使用流程：
1. 输入世界种子（十进制/负数/0x 十六进制），选择版本与结构类型
   （当前支持雪屋/沉船/下界要塞/堡垒遗迹，后两者生成于下界）；
2. 「预览」按钮两态，由实例加载状态驱动：
   - 默认「附近的实例」：以输入坐标为中心（留空以原点为中心），
     后台线程按区域制枚举当前种子附近的真实结构实例（群系校验，
     与游戏 /locate 结果一致），双击列表行加载该实例；
   - 加载实例后按钮变「预览」：compose 出该实例的模板变种/旋转/
     箱子坐标与各箱 LootTableSeed，3D 视口注入显示模型（右键
     旋转/滚轮缩放）；坐标改动后按钮复位回「附近的实例」；
3. 「粘贴F3+C」：解析游戏 F3+C 复制的 tp 命令（含
   /execute in <维度> run tp @s X Y Z Yaw Pitch 及省略形式），
   自动填入锚点 X/Z（Y 与视角忽略；维度与当前结构不符会提示）；
4. 箱子列表逐箱显示战利品表名、LootTableSeed（Java 有符号显示）
    与开箱内容预测（图标 + 名称 x 合并数量、附魔/炖菜效果按 RNG
    顺序生成；同箱内完全相同的物品合并数量；有附魔的物品图标
    叠加游戏原版附魔光效纹理动态流光）。

机制说明（对拍基准 xpple/cubiomes fork 5815e4f finders.c）：
- 变种/部件/箱子坐标：getVariant + getStructurePieces 的 RNG 消耗
  序列逐行移植（Utils/StructurePreviewer/composition.py）；
- LootTableSeed：getPopulationSeed + salt 档（loot_rng.py），箱序
  即同区块流内 nextLong 消耗顺序；
- 战利品求值：Cubiomes-Loot 移植（loot_engine.py），浮点 float32
  域，与游戏 1.18~1.21 行为一致（era 由版本键决定）。

已知妥协（composition 第一版，模型示意用途；RNG/坐标不受影响）：
- igloo 3D 模型不随 rotation/mirror 旋转（公式含隐藏 piece 内
  偏移，反解不唯一）；shipwreck 全 20 个官方变种模板已就位
  （degraded 为官方降级模板），仅 igloo 模型角度保留妥协。
"""

import json
import math
import os
import re

from PySide6.QtCore import (QEvent, QRect, QSize, QStandardPaths, Qt,
                            QThread, QTimer, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QPainter,
                           QPalette, QPen, QPixmap, QRegion)
from PySide6.QtWidgets import (QApplication, QDialog, QGridLayout,
                               QHeaderView, QLabel, QMenu, QStyle,
                               QStyledItemDelegate, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

from .tool_base import BaseToolWidget
from CodesUI.StructurePreviewer import Ui_structurePreviewer
from Utils.Public import structure_icons as struct_icons
from Utils.Public.structure_map import (
    BiomeSampler, check_structure_at, enumerate_structures)
from Utils.Public import structure_params
from Utils.SeedReverser import structure_3dview
from Utils.Public.biome_names import biome_label
from Utils.StructurePreviewer import composition, loot_engine, loot_rng

# 会话持久化（本页输入状态重启不丢）：配置目录 JSON 文件
_SESSION_FILE = "structure_previewer_session.json"
# 灵敏度滑条：整数档位 [1,30] ↔ 实际 0.01~0.30 度/像素（内部/100）
_SENS_MIN = 1
_SENS_MAX = 30
_SENS_DEFAULT = 5

# 本工具支持的结构键（下界结构维度路由见 structure_params.STRUCT_DIMENSION）
# woodland_mansion：UI/展示/compose 用键；枚举与群系校验链路（
# enumerate_structures/check_structure_at/图标/显示名）用 cubiomes
# 键 "mansion"，预览流程由 _UI_TO_ENUM 别名映射（见下方）。
_STRUCT_KEYS = ("igloo", "shipwreck", "ocean_ruin", "stronghold",
                "nether_fortress", "bastion_remnant", "end_city",
                "trial_chambers", "ancient_city", "village",
                "pillager_outpost", "woodland_mansion",
                "desert_pyramid", "jungle_temple",
                "ruined_portal", "buried_treasure")

# UI 键 -> 枚举/校验/图标/显示名链路键（cubiomes 键名差异桥接）
_UI_TO_ENUM = {"woodland_mansion": "mansion"}

# loot 快照目录（分档快照选择逻辑见 loot_engine.load_loot_snapshot）
_LOOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), "Utils", "StructurePreviewer", "data", "loot")

# 物品 id（minecraft: 后缀）-> 中文名（六张表全集；中文 Wiki 名）
_ITEM_CN = {
    "ancient_debris": "远古残骸", "apple": "苹果", "arrow": "箭",
    "bamboo": "竹子", "beetroot_seeds": "甜菜种子", "bone_block": "骨块", "book": "书",
    "buried_treasure_map": "埋藏的宝藏地图", "carrot": "胡萝卜",
    "chain": "锁链", "clock": "时钟", "coal": "煤炭",
    "coast_armor_trim_smithing_template": "海岸盔甲纹样锻造模板",
    "compass": "指南针", "cooked_porkchop": "熟猪排",
    "copper_horse_armor": "铜马铠",
    "copper_nautilus_armor": "铜鹦鹉螺铠",
    "crying_obsidian": "哭泣的黑曜石",
    "crossbow": "弩", "dark_oak_log": "深色橡木原木", "diamond": "钻石",
    "diamond_boots": "钻石靴子", "diamond_chestplate": "钻石胸甲",
    "diamond_helmet": "钻石头盔",
    "diamond_horse_armor": "钻石马铠", "diamond_leggings": "钻石护腿",
    "diamond_nautilus_armor": "钻石鹦鹉螺铠",
    "diamond_pickaxe": "钻石镐", "diamond_spear": "钻石矛",
    "diamond_shovel": "钻石锹", "diamond_sword": "钻石剑", "emerald": "绿宝石",
    "experience_bottle": "附魔之瓶", "feather": "羽毛",
    "flint_and_steel": "打火石", "gilded_blackstone": "镀金黑石",
    "gold_block": "金块", "gold_ingot": "金锭", "gold_nugget": "金粒",
    "golden_apple": "金苹果", "golden_axe": "金斧",
    "golden_boots": "金靴子", "golden_carrot": "金胡萝卜",
    "golden_chestplate": "金胸甲", "golden_helmet": "金头盔",
    "golden_horse_armor": "金马铠", "golden_leggings": "金护腿",
    "golden_nautilus_armor": "金鹦鹉螺铠", "golden_sword": "金剑",
    "goat_horn": "山羊角", "gunpowder": "火药",
    "iron_block": "铁块", "iron_boots": "铁靴子",
    "iron_chestplate": "铁胸甲", "iron_helmet": "铁头盔",
    "iron_horse_armor": "铁马铠", "iron_leggings": "铁护腿",
    "iron_nautilus_armor": "铁鹦鹉螺铠", "iron_ingot": "铁锭", "iron_nugget": "铁粒",
    "iron_pickaxe": "铁镐", "iron_shovel": "铁锹", "iron_sword": "铁剑",
    "lapis_lazuli": "青金石", "leather": "皮革",
    "leather_boots": "皮革靴子", "leather_chestplate": "皮革胸甲",
    "leather_helmet": "皮革帽子", "leather_leggings": "皮革裤子",
    "lodestone": "磁石", "magma_cream": "岩浆膏", "map": "地图",
    "moss_block": "苔藓块", "music_disc_pigstep": "音乐唱片（Pigstep）",
    "nether_wart": "下界疣", "netherite_scrap": "下界合金碎片",
    "netherite_upgrade_smithing_template": "下界合金升级锻造模板",
    "obsidian": "黑曜石", "paper": "纸",
    "piglin_banner_pattern": "猪灵旗帜图案",
    "poisonous_potato": "毒马铃薯", "potato": "马铃薯",
    "pumpkin": "南瓜", "rib_armor_trim_smithing_template": "肋骨盔甲纹样锻造模板",
    "rotten_flesh": "腐肉", "saddle": "鞍",
    "spire_armor_trim_smithing_template": "尖塔盔甲纹样锻造模板",
    "spectral_arrow": "光灵箭", "stone_axe": "石斧", "string": "线",
    "suspicious_stew": "迷之炖菜", "tnt": "TNT", "wheat": "小麦",
    # -- 试炼密室 9 表物品补全（中文 Wiki 名）--
    "acacia_planks": "金合欢木板", "amethyst_shard": "紫水晶碎片",
    "baked_potato": "烤马铃薯", "bamboo_hanging_sign": "竹制悬挂式告示牌",
    "bamboo_planks": "竹木板", "bolt_armor_trim_smithing_template":
        "旋风盔甲纹样锻造模板",
    "bone_meal": "骨粉", "bow": "弓", "bucket": "铁桶", "cake": "蛋糕",
    "diamond_axe": "钻石斧", "diamond_block": "钻石块",
    "emerald_block": "绿宝石块", "ender_pearl": "末影珍珠",
    "glow_berries": "发光浆果", "golden_pickaxe": "金镐",
    "guster_banner_pattern": "旋风旗帜图案", "honey_bottle": "蜂蜜瓶",
    "honeycomb": "蜜脾", "iron_axe": "铁斧", "milk_bucket": "牛奶桶",
    "music_disc_precipice": "音乐唱片（Precipice）",
    "ominous_bottle": "不祥之瓶", "potion": "药水", "scaffolding": "脚手架",
    "shield": "盾牌", "stick": "木棍", "stone_pickaxe": "石镐",
    "tipped_arrow": "药水箭", "torch": "火把", "trial_key": "试炼钥匙",
    "trident": "三叉戟", "tuff": "凝灰岩", "wind_charge": "风弹",
    "wooden_axe": "木斧",
    # -- 要塞 3 表物品补全（中文 Wiki 名）--
    "bread": "面包", "redstone": "红石粉",
    "music_disc_otherside": "音乐唱片（Otherside）",
    "eye_armor_trim_smithing_template": "眼畦盔甲纹样锻造模板",
    # -- 林地府邸表物品补全（中文 Wiki 名）--
    "lead": "拴绳", "enchanted_golden_apple": "附魔金苹果",
    "music_disc_13": "音乐唱片（13）", "music_disc_cat": "音乐唱片（cat）",
    "name_tag": "命名牌", "chainmail_chestplate": "锁链胸甲",
    "diamond_hoe": "钻石钻", "melon_seeds": "西瓜种子",
    "pumpkin_seeds": "南瓜种子", "resin_clump": "树脂团",
    "bone": "骨头",
    "vex_armor_trim_smithing_template": "恼鬼盔甲纹样锻造模板",
    # -- 远古城市两表物品补全（中文 Wiki 名）--
    "echo_shard": "回响碎片", "disc_fragment_5": "唱片残片（5）",
    "sculk": "幽匿块", "sculk_sensor": "幽匿感测体",
    "sculk_catalyst": "幽匿催发体", "soul_torch": "灵魂火把",
    "candle": "蜡烛", "packed_ice": "浮冰", "snowball": "雪球",
    "ward_armor_trim_smithing_template": "守卫盔甲纹样锻造模板",
    "silence_armor_trim_smithing_template": "沉静盔甲纹样锻造模板",
    # -- 海底废墟/掠夺者前哨站/堡垒遗迹漏网物品补全（中文 Wiki 名）--
    "fishing_rod": "钓鱼竿", "stone_spear": "石矛",
    "sentry_armor_trim_smithing_template": "哨兵盔甲纹样锻造模板",
    "snout_armor_trim_smithing_template": "猪鼻盔甲纹样锻造模板",
    "tripwire_hook": "绊线钩",
    # -- 村庄表物品补全（中文 Wiki 名）--
    "bundle": "收纳袋", "dandelion": "蒲公英", "oak_sapling": "橡树苗",
    # -- 沙漠神殿/丛林神庙表物品补全（中文 Wiki 名）--
    "sand": "沙子", "spider_eye": "蜘蛛眼",
    "dune_armor_trim_smithing_template": "沙丘盔甲纹样锻造模板",
    "wild_armor_trim_smithing_template": "荒野盔甲纹样锻造模板",
    # -- 废弃传送门/埋藏的宝藏表物品补全（中文 Wiki 名）--
    "bell": "钟", "fire_charge": "火焰弹", "flint": "燧石",
    "glistering_melon_slice": "闪烁的西瓜片",
    "golden_hoe": "金锄", "golden_shovel": "金锹",
    "light_weighted_pressure_plate": "轻质测重压力板",
    "heart_of_the_sea": "海洋之心", "prismarine_crystals": "海晶结晶",
    "cooked_cod": "熟鳕鱼", "cooked_salmon": "熟鲑鱼",
    "iron_spear": "铁矛",
}

# 附魔短名 -> 中文名（loot_engine.ENCHANTMENT_ORDER 全集；中文 Wiki 名）
_ENCH_CN = {
    "protection": "保护", "fire_protection": "火焰保护",
    "blast_protection": "爆炸保护", "projectile_protection": "弹射物保护",
    "respiration": "水下呼吸", "aqua_affinity": "水下速掘", "thorns": "荆棘",
    "swift_sneak": "迅捷潜行", "feather_falling": "摔落缓冲",
    "depth_strider": "深海探索者", "frost_walker": "冰霜行者",
    "soul_speed": "灵魂疾行", "sharpness": "锋利", "smite": "亡灵杀手",
    "bane_of_arthropods": "节肢杀手", "knockback": "击退",
    "fire_aspect": "火焰附加", "looting": "抢夺",
    "sweeping_edge": "横扫之刃", "efficiency": "效率",
    "silk_touch": "精准采集", "fortune": "时运",
    "luck_of_the_sea": "海之眷顾", "lure": "饵钓", "power": "力量",
    "punch": "冲击", "flame": "火矢", "infinity": "无限",
    "quick_charge": "快速装填", "multishot": "多重射击",
    "piercing": "穿透", "impaling": "穿刺", "riptide": "激流",
    "loyalty": "忠诚", "channeling": "引雷", "density": "致密",
    "breach": "破空", "wind_burst": "风爆", "mending": "经验修补",
    "unbreaking": "耐久", "vanishing_curse": "消失诅咒",
    "binding_curse": "绑定诅咒", "lunge": "突刺",
}

# 状态效果全名（minecraft:xxx）-> 中文名
# （1.21.11 原版 39 效果全集，中文 Wiki 名；loot 求值产出的效果 id
# 均可命中，不再回退英文 id）
_EFFECT_CN = {
    "minecraft:speed": "迅捷", "minecraft:slowness": "缓慢",
    "minecraft:haste": "急迫", "minecraft:mining_fatigue": "挖掘疲劳",
    "minecraft:strength": "力量", "minecraft:instant_health": "瞬间治疗",
    "minecraft:instant_damage": "瞬间伤害", "minecraft:jump_boost": "跳跃提升",
    "minecraft:nausea": "反胃", "minecraft:regeneration": "再生",
    "minecraft:resistance": "抗性提升", "minecraft:fire_resistance": "抗火",
    "minecraft:water_breathing": "水下呼吸", "minecraft:invisibility": "隐形",
    "minecraft:blindness": "失明", "minecraft:night_vision": "夜视",
    "minecraft:hunger": "饥饿", "minecraft:weakness": "虚弱",
    "minecraft:poison": "中毒", "minecraft:wither": "凋零",
    "minecraft:health_boost": "生命提升", "minecraft:absorption": "伤害吸收",
    "minecraft:saturation": "饱和", "minecraft:glowing": "发光",
    "minecraft:levitation": "漂浮", "minecraft:luck": "幸运",
    "minecraft:unluck": "霉运", "minecraft:slow_falling": "缓降",
    "minecraft:conduit_power": "潮涌能量",
    "minecraft:dolphins_grace": "海豚的恩惠",
    "minecraft:bad_omen": "不祥之兆",
    "minecraft:hero_of_the_village": "村庄英雄",
    "minecraft:darkness": "黑暗", "minecraft:trial_omen": "试炼之兆",
    "minecraft:raid_omen": "袭击之兆", "minecraft:wind_charged": "蓄风",
    "minecraft:weaving": "缠绕", "minecraft:oozing": "渗浆",
    "minecraft:infested": "虫蚀",
}

# 罗马数字等级（附魔显示用，1~10 足够）
_ROMAN = ("", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")

# 选中箱子行的前景琥珀（与视口描边同色）
_HIGHLIGHT_AMBER = QColor(0xF1, 0xC4, 0x0F)

# 物品图标目录（16x16 原版纹理，从 1.21.11 客户端 jar 提取；
# 方块物品/新版物品定义/重命名物品已在提取阶段折算为 <物品短名>.png）
_ICON_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(
        __file__))), "assets", "StructurePreviewer", "items")

# 附魔光效纹理（游戏原版 enchanted_glint_item，128x128 透明底紫白流纹；
# 与 EnchantCaculator 共用同一份，已归入公共资源 assets/Public）
_GLINT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(
        __file__))), "assets", "Public",
    "enchanted_glint.png")
_GLINT_OK = os.path.exists(_GLINT_PATH)
_glint_cache: dict[int, "QPixmap"] = {}

# 游戏容器 GUI 贴图（从 1.21.11 客户端 jar 提取的原版贴图）：
# - slot.png：18x18 单槽凹槽（顶/左 #373737 内阴影 + 底/右 #FFFFFF 亮线
#   + #8B8B8B 内部），1x 直接 drawPixmap 不缩放；
# - generic_54.png：256x256 大箱子 GUI 图集，实际面板区 x 0..175
#   （宽 176，游戏 GUI 标准宽）；裁 (0,0,176,90) 为单箱界面槽区
#   面板 = 17px 标题区 + 3 行箱槽（y18..69，槽位 x8 起步距 18）
#   + 底部收边，与游戏内箱子界面同源。
# 像素观感不变：slot.png 内部三色与 v1 手绘完全一致，仅底色来源
# 从 CSS 近似改为原版贴图（亚像素、描边完全同游戏）。
_GUI_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(
        __file__))), "assets", "StructurePreviewer", "gui")
_SLOT_TEX = os.path.join(_GUI_DIR, "slot.png")
_PANEL_TEX = os.path.join(_GUI_DIR, "generic_54.png")
_slot_tex_cache: dict[int, "QPixmap"] = {}
_panel_cache: "QPixmap | None" = None
_panel_cache_scale = 0

# 单箱面板两段拼接参数（1x 像素，见 _GUI_DIR 注释）
_PANEL_W, _PANEL_H = 176, 78
_PANEL_TOP_H = 71                  # 上段：标题区 + 3 行槽 + 槽底白线
_PANEL_STRIP_Y, _PANEL_STRIP_H = 215, 7   # 下段：图集底部边框条

# 槽位图标绘制比例（用户需求：图标缩小 20% -> 0.8 倍槽内区）
_ICON_SLOT_RATIO = 0.8

# 子行自定义角色：UserRole = 物品短名（图标键），UserRole+1 = 有附魔
_ENCHANTED_ROLE = Qt.ItemDataRole.UserRole + 1

# 物品纹理缓存 {短名: (QPixmap 16x16, 不透明区 QRegion 或 None)}
_item_pix_cache: dict[str, tuple] = {}
# 缩放物品纹理缓存 {(短名, scale): (QPixmap 16*scale, QRegion 或 None)}
_item_scaled_cache: dict[tuple, tuple] = {}

# bastion start 变种索引 -> 中文短名（composition._BASTION_STARTS 顺序；
# 非官方命名，按 wiki 对应部位的习惯称呼）
_BASTION_START_CN = ("堡垒主体", "疣猪兽棚", "宝藏房", "桥")

# ancient_city 起点变种索引 -> 中文短名（city_center 池三件同尺寸，
# 内部布局不同；非官方命名，按内部特征习惯称呼）
_ANCIENT_CITY_START_CN = ("中心喷泉型", "大型中心型", "回字环型")

# 附近实例枚举半径（方块；32*16=512 方块 ≈ 8 区块半径）
_LOCATE_RADIUS = 4096

# loot 表缓存：{era: {表名: LootTable}}
_loot_cache: dict[int, dict[str, "loot_engine.LootTable"]] = {}


def _loot_table(table_name: str, era: int):
    """按 era 取缓存的 LootTable（走 loot_engine 快照选表，文件缺失时异常上抛）。

    试炼密室表在 1.20.5 引入且各档内容一致（1.21+ 才有该结构），
    单文件快照不参与 _LOOT_TABLE_ERAS 分档。
    """
    by_name = _loot_cache.setdefault(era, {})
    if table_name not in by_name:
        by_name[table_name] = loot_engine.load_loot_snapshot(
            table_name, era, snapshot_dir=_LOOT_DIR)
    return by_name[table_name]


def _tp_command(x: int, z: int, struct_key: str) -> str:
    """实例锚点 -> 可粘回游戏聊天栏的传送指令（F3+C 同款格式）。

    与 SeedReverser「复制 F3+C 格式」同款约定：Y=100 落到结构上空
    （实例枚举只有 X/Z 锚点，精确高度玩家自行调整）、视角归零；
    维度按结构所属世界展开——tp 不会跨维度生效，在下界结构上
    必须 execute in 切到 the_nether 才能到达坐标。
    """
    dim = structure_params.STRUCT_DIMENSION.get(struct_key, "overworld")
    dim_id = {"overworld": "overworld", "nether": "the_nether",
              "end": "the_end"}[dim]
    return (f"/execute in minecraft:{dim_id} "
            f"run tp @s {x} 100 {z} 0 0")


# 药水基名表（potion id 短名 -> 中文名；键为药水名而非效果 id——
# swiftness/healing 等与效果 id 不同名；中文 Wiki 药水页译名）
_POTION_BASE_CN = {
    "water": "水瓶", "mundane": "平凡的药水", "thick": "浓稠的药水",
    "awkward": "粗制的药水",
    "night_vision": "夜视药水", "invisibility": "隐形药水",
    "leaping": "跳跃药水", "fire_resistance": "抗火药水",
    "swiftness": "迅捷药水", "slowness": "迟缓药水",
    "turtle_master": "海龟神药", "water_breathing": "水肺药水",
    "healing": "治疗药水", "harming": "伤害药水",
    "poison": "剧毒药水", "regeneration": "再生药水",
    "strength": "力量药水", "weakness": "虚弱药水",
    "luck": "幸运药水", "slow_falling": "缓降药水",
}

# 药水/药水箭容器物品（图标走类型染色贴图 <容器>_<药水 id 短名>.png）
_POTION_ITEMS = frozenset(("potion", "splash_potion",
                           "lingering_potion", "tipped_arrow"))

# 图标键染色贴图存在性缓存 {候选键: bool}
_icon_key_cache: dict[str, bool] = {}


def _potion_display_name(item_short: str, potion_id: str) -> str:
    """药水类型 -> 游戏同款中文名（强效再生药水/喷溅型夜视药水/药水箭）。

    long_ 前缀版与普通版同名（游戏译名行为）；未知基名用效果名
    桑底（<效果>药水）。"""
    pid = potion_id.split(":", 1)[-1]
    base = pid
    prefix = ""
    if base.startswith("strong_"):
        base = base[7:]
        prefix = "强效"
    elif base.startswith("long_"):
        base = base[5:]
    name = _POTION_BASE_CN.get(base)
    if name is None:
        name = _EFFECT_CN.get("minecraft:" + base, base) + "药水"
    full = prefix + name
    if item_short == "splash_potion":
        full = "喷溅型" + full
    elif item_short == "lingering_potion":
        full = "滞留型" + full
    elif item_short == "tipped_arrow":
        full = "药水箭" if base == "water" else full + "箭"
    return full


def _icon_key(stack: "loot_engine.ItemStack") -> str:
    """ItemStack -> 图标键：药水类带类型后缀（potion_<id 短名>），
    对应 items 目录的预染色贴图；染色贴图缺失时回退基础短名。"""
    key = stack.item.split(":", 1)[-1]
    pot = stack.potion
    if pot and key in _POTION_ITEMS:
        cand = f"{key}_{pot.split(':', 1)[-1]}"
        ok = _icon_key_cache.get(cand)
        if ok is None:
            ok = _icon_key_cache[cand] = os.path.exists(
                os.path.join(_ICON_DIR, cand + ".png"))
        if ok:
            return cand
    return key


def _item_label(stack: "loot_engine.ItemStack") -> str:
    """ItemStack -> 「皮革帽子（保护III） x3」式显示文本（数量已合并）。

    药水类优先用类型名（游戏译名：强效再生药水/喷溅型夜视药水/药
    水箭），名称已含效果信息，效果时长不再附括号（tooltip 保留）。"""
    key = stack.item.split(":", 1)[-1]
    if stack.potion and key in _POTION_ITEMS:
        return (f"{_potion_display_name(key, stack.potion)} "
                f"x{stack.count}")
    name = _ITEM_CN.get(key, key)
    if stack.enchantments:
        parts = []
        for ench, lvl in stack.enchantments:
            cn = _ENCH_CN.get(ench, ench)
            lvl_s = _ROMAN[lvl] if 0 < lvl < len(_ROMAN) else str(lvl)
            parts.append(f"{cn}{lvl_s}")
        name += f"（{'、'.join(parts)}）"
    if stack.effect is not None:
        eff = stack.effect
        eff_cn = _EFFECT_CN.get(eff[0], eff[0].split(":", 1)[-1])
        # 游戏内时长单位为秒（Cubliomes-Loot 输出已乘 20 tick）
        name += f"（{eff_cn} {eff[1] // 20}秒）"
    return f"{name} x{stack.count}"


# 诅咒附魔短名（游戏内诅咒行显示红色）
_CURSE_KEYS = frozenset({"vanishing_curse", "binding_curse"})


def _rom(n: int) -> str:
    """附魔等级 -> 罗马数字（1~10，越界回退阿拉伯数字）。"""
    return _ROMAN[n] if 0 < n < len(_ROMAN) else str(n)


def _item_tooltip_html(stack: "loot_engine.ItemStack") -> str:
    """ItemStack -> 游戏 tooltip 风格富文本（深色卡片详情）。

    视觉对齐 EnchantCaculator/enchanted_item_card._TooltipBox（即
    游戏内物品悬停提示框）：近黑紫背景 + 紫色描边；首行物品名
    白字，附魔/效果属性行灰字，诅咒附魔红字（同游戏）。数量并入
    名称行（xN），附魔每行一条（名称 + 罗马数字等级）。
    """
    key = stack.item.split(":", 1)[-1]
    if stack.potion and key in _POTION_ITEMS:
        name = _potion_display_name(key, stack.potion)
    else:
        name = _ITEM_CN.get(key, key)
    if stack.count > 1:
        name += f" x{stack.count}"
    rows = [f'<tr><td style="color:#FFFFFF;">{name}</td></tr>']
    for ench, lvl in stack.enchantments:
        cn = _ENCH_CN.get(ench, ench)
        color = "#FF5555" if ench in _CURSE_KEYS else "#AAAAAA"
        rows.append(f'<tr><td style="color:{color};">{cn} {_rom(lvl)}</td></tr>')
    if stack.effect is not None:
        eff_cn = _EFFECT_CN.get(stack.effect[0],
                                stack.effect[0].split(":", 1)[-1])
        # 游戏内时长单位为秒（Cubliomes-Loot 输出已乘 20 tick）
        rows.append(f'<tr><td style="color:#AAAAAA;">{eff_cn} '
                    f'{stack.effect[1] // 20}秒</td></tr>')
    # 边框实现：Qt 富文本引擎不绘制 table 的 CSS border，改用嵌套
    # 表格——外层紫色 (#5000FF) 单元格 cellpadding=1 露出 1px 作
    # 边框，内层深紫近黑 (#100010) 底（同游戏提示框观感，取自
    # EnchantCaculator._TooltipBox 配色）。
    return ('<table cellspacing="0" cellpadding="1" bgcolor="#5000FF">'
            '<tr><td>'
            '<table cellspacing="0" cellpadding="4" bgcolor="#100010">'
            + "".join(rows) + '</table></td></tr></table>')


def _merge_stacks(items: list["loot_engine.ItemStack"]) -> list:
    """同箱内完全相同的物品合并数量（物品/附魔列表/效果全等）。

    首次出现顺序保留（与 RNG 产出顺序一致）；key 用
    repr（dataclass 元组字段可哈希），可合并不相邻的重复堆。
    条目复制后再累加，不修改调用方的原对象——同一 ItemStack
    若被上游共享引用（同一对象出现两次），原对象 count 不被污染，
    且各按其自身数量参与合并，不会重复计数。药水类型并入键
    （water/mundane 均无 effect，仅靠 potion id 区分）。"""
    merged: dict[str, "loot_engine.ItemStack"] = {}
    out: list["loot_engine.ItemStack"] = []
    for it in items:
        k = repr((it.item, tuple(it.enchantments), it.effect, it.potion))
        if k in merged:
            merged[k].count += it.count
        else:
            clone = loot_engine.ItemStack(item=it.item, count=it.count,
                                          enchantments=list(it.enchantments),
                                          effect=it.effect,
                                          potion=it.potion)
            merged[k] = clone
            out.append(clone)
    return out


def _load_item_pixmap(key: str) -> tuple | None:
    """加载物品纹理（16x16 原版尺寸）与不透明区 QRegion（含缓存）。

    返回 (QPixmap, QRegion|None)；文件缺失返回 None（行无图标）。
    QRegion 用于流光绘制剪裁到物品不透明像素（不外溢背景）。
    """
    if key in _item_pix_cache:
        return _item_pix_cache[key]
    result = None
    path = os.path.join(_ICON_DIR, f"{key}.png")
    if os.path.exists(path):
        pix = QPixmap(path)
        if not pix.isNull():
            region = None
            if _GLINT_OK:
                mask = pix.createMaskFromColor(Qt.transparent,
                                               Qt.MaskInColor)
                region = QRegion(mask)
            result = (pix, region)
    _item_pix_cache[key] = result
    return result


def _load_item_scaled(key: str, scale: int) -> tuple | None:
    """按 scale 返回预缩放 (图标 QPixmap, 不透明区 QRegion)（缓存）。

    - 图标：16x16 原版纹理最近邻放大到 round(16*scale*0.8)（用户
      需求缩小 20%，_ICON_SLOT_RATIO 对所有 scale 一致；
      FastTransformation 像素风不插值，硬边保留，非整数倍时像素
      块宽度略有不均，属最近邻采样的固有表现）；
    - 剪裁区：缩放图 createMaskFromColor(透明, MaskInColor) 同 1x
      配方（探针实证：MaskInColor+透明色 → QRegion 覆盖不透明区，
      out_probe_glint.txt scale=1 changed_at_opqA=True）；QBitmap
      返回后必须先包 QRegion 再 translated（QBitmap 无 translated，
      在 QPainter.updateClipRegion 内部调它会崩）；剪裁区从缩小后
      的图生成，随图标尺寸自动同步。
    """
    ck = (key, scale)
    if ck in _item_scaled_cache:
        return _item_scaled_cache[ck]
    base = _load_item_pixmap(key)
    result = None
    if base is not None:
        size = max(1, round(16 * scale * _ICON_SLOT_RATIO))
        big = base[0].scaled(
            size, size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation)
        region = None
        if _GLINT_OK:
            mask = big.createMaskFromColor(Qt.transparent,
                                           Qt.MaskInColor)
            region = QRegion(mask)
        result = (big, region)
    _item_scaled_cache[ck] = result
    return result


def _load_glint_pixmap(size: int) -> "QPixmap | None":
    """加载并预缩放附魔光效纹理（按尺寸缓存，多规格共存）。"""
    if not _GLINT_OK:
        return None
    if size not in _glint_cache:
        _glint_cache[size] = QPixmap(_GLINT_PATH).scaled(
            size * 2, size * 2,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.FastTransformation)
    return _glint_cache[size]


def _load_panel_pixmap(scale: int = 1) -> "QPixmap | None":
    """加载大箱子 GUI 贴图并拼出单箱槽区面板（缓存按 scale）。

    - 拼接（1x 几何，游戏 3 行容器标准上半部）：
      上段 (0,0,176,71)＝标题区+3 行槽+槽底白线；
      下段 (0,215,176,7)＝图集底部边框条（探针 out_probe_gui_tex.txt
      实测：槽行 y=18/36/54 起，y214 白线、y219 #555555、y221 黑边）；
    - scale：整数倍放大（FastTransformation 最近邻，像素风不插值）；
    - 缺文件返回 None（调用方回退纯色背景）。
    """
    global _panel_cache, _panel_cache_scale
    if not os.path.exists(_PANEL_TEX):
        return None
    if _panel_cache is None or _panel_cache_scale != scale:
        src = QPixmap(_PANEL_TEX)
        if src.isNull():
            return None
        top = src.copy(0, 0, _PANEL_W, _PANEL_TOP_H)
        strip = src.copy(0, _PANEL_STRIP_Y, _PANEL_W, _PANEL_STRIP_H)
        canvas = QPixmap(_PANEL_W, _PANEL_H)
        canvas.fill(Qt.transparent)
        pt = QPainter(canvas)
        pt.drawPixmap(0, 0, top)
        pt.drawPixmap(0, _PANEL_TOP_H, strip)
        pt.end()
        _panel_cache = canvas.scaled(
            _PANEL_W * scale, _PANEL_H * scale,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation)
        _panel_cache_scale = scale
    return _panel_cache


# ---------- 像素文字（游戏 ascii.png 字形，预处理 JSON 零运行时解析） ----------
# 字形数据由 .temp/prep_pixel_font.py 一次性生成：从 1.21.11 jar 的
# default.json(include) 取字符→格位映射，解析 ascii.png (128x128,
# bd1 索引) 得每个可打印 ASCII 字符的 {x 内容起始列, w 内容宽,
# rows 8 行位图}。字体规则：8px 高、ascent 7、advance = 内容宽+1
# （1.13+ bitmap 字体）、空格 advance=4（include/space.json）。
# 开箱 GUI 文字默认用普通系统字体（_PIXEL_FONT_UI=False，恢复旧
# 版观感）；置 True 切回游戏像素字形（标题条 + 数量角标）。
_PIXEL_FONT_UI = False
_FONT_JSON = os.path.join(_GUI_DIR, "font_ascii.json")
_glyph_cache: "dict | None" = None


def _load_glyphs() -> dict:
    """加载字形位图数据（缺文件/损坏返回 {}，调用方回退系统字体）。"""
    global _glyph_cache
    if _glyph_cache is None:
        try:
            with open(_FONT_JSON, "r", encoding="utf-8") as f:
                _glyph_cache = json.load(f)
        except (OSError, ValueError):
            _glyph_cache = {}
    return _glyph_cache


def _pixel_text_size(text: str) -> tuple[int, int]:
    """像素文字 1x 尺寸（像素宽, 8 像素高），规则同 _draw_pixel_text。"""
    glyphs = _load_glyphs()
    width = 0
    for ch in text:
        g = glyphs.get(ch)
        if g and g["w"]:
            width += g["w"] + 1
        else:
            width += 4 if ch == " " else 6
    return width, 8


def _draw_pixel_text(p: "QPainter", x: int, y: int, text: str,
                     color: "QColor", scale: int = 1,
                     shadow: "QColor | None" = None) -> None:
    """用游戏字形画像素文字（左上角基准，fillRect 逐位画点）。

    - 字形仅画内容列（JSON 已按 1.13+ 规则测得 x 起始与 w 宽），
      advance = 内容宽 + 1 像素空隙，同游戏排字；
    - shadow：游戏文字自带的 1px 右下阴影（整体先画阴影层再画
      文字层，两层分离避免阴影覆盖相邻字形亮像素）；
    - 缺字形/空格按 advance 4 兑底；JSON 缺失时调用方应走回退。"""
    glyphs = _load_glyphs()
    rects: list[tuple[int, int]] = []
    cx = x
    for ch in text:
        g = glyphs.get(ch)
        if not g or not g["w"]:
            cx += (4 if ch == " " else 6) * scale
            continue
        gx = g["x"]
        for dy, bits in enumerate(g["rows"]):
            if not bits:
                continue
            for col in range(g["w"]):
                if bits & (0x80 >> (gx + col)):
                    rects.append((cx + col * scale, y + dy * scale))
        cx += (g["w"] + 1) * scale
    if shadow is not None:
        for px, py in rects:
            p.fillRect(px + scale, py + scale, scale, scale, shadow)
    for px, py in rects:
        p.fillRect(px, py, scale, scale, color)


class _GlintItemDelegate(QStyledItemDelegate):
    """战利品子行委托：行首绘制物品图标；附魔物品图标叠加流光。

    - 图标：assets/StructurePreviewer/items/<物品短名>.png（16x16 原版
    纹理），绘制在文本左侧（图标在名称前）；
    - 流光：附魔物品每帧在图标不透明区内加法混合两层反向滚动的
    光效纹理（CompositionMode_Plus 只提亮不遮盖，观感同游戏内
    附魔物品微微发光）；同一实例共享一个 QTimer 统一重绘。
    """

    ICON = 16                 # 图标绘制边长（原版 16x16，不缩放）
    PAD = 4                   # 图标与文本/行缘间距
    FRAME_MS = 50             # 流光帧间隔（~20fps）
    SCROLL = 1                # 两层每帧位移（px，反向）

    def __init__(self, tree: "QTreeWidget", parent=None):
        super().__init__(parent)
        self._tree = tree
        self._t_fast = 0
        self._t_slow = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        if _GLINT_OK:
            self._timer.start(self.FRAME_MS)

    def stop(self) -> None:
        """停流光定时器（工具页关闭时调用，防退出期崩溃）。"""
        self._timer.stop()

    def _advance(self) -> None:
        """每帧推进两层位移并重绘视口（仅附魔子行区域，开销极低）。"""
        self._t_fast = (self._t_fast + self.SCROLL) % self.ICON
        self._t_slow = (self._t_slow - self.SCROLL) % self.ICON
        vp = self._tree.viewport()
        if vp is not None:
            vp.update()

    def paint(self, painter, option, index) -> None:
        key = index.data(Qt.ItemDataRole.UserRole)
        if not key:
            super().paint(painter, option, index)
            return
        loaded = _load_item_pixmap(key)
        if loaded is None:
            super().paint(painter, option, index)
            return
        pix, region = loaded

        # 1) 背景与选中态用原实现绘制（含 hover/选中高亮/琥珀前景）
        opt = option
        self.initStyleOption(opt, index)
        opt.text = ""
        opt.icon = QIcon()
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem,
                          opt, painter, opt.widget)

        # 2) 图标（图标在前，与文本留 PAD 间距）
        rect = opt.rect
        x = rect.x() + self.PAD
        y = rect.y() + (rect.height() - self.ICON) // 2
        painter.drawPixmap(x, y, pix)

        # 3) 附魔流光（仅附魔物品；两层反向滚动 + 加法混合）
        if _GLINT_OK and index.data(_ENCHANTED_ROLE):
            tex = _load_glint_pixmap(self.ICON)
            if tex is not None:
                painter.save()
                if region is not None:
                    painter.setClipRegion(region.translated(x, y))
                painter.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_Plus)
                painter.setOpacity(0.35)
                for off in (self._t_fast, self._t_slow):
                    ox, oy = x - off, y - off
                    for dx in (0, self.ICON * 2):
                        for dy in (0, self.ICON * 2):
                            painter.drawPixmap(ox + dx, oy + dy, tex)
                painter.restore()

        # 4) 文本（图标区右侧起绘，沿用行前景色/省略号）
        painter.save()
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        if isinstance(fg, QBrush):
            painter.setPen(QPen(fg.color()))
        else:
            painter.setPen(QPen(opt.palette.color(QPalette.ColorRole.Text)))
        text_rect = rect.adjusted(self.ICON + self.PAD * 2, 0, 0, 0)
        fm = opt.fontMetrics
        elided = fm.elidedText(index.data(Qt.ItemDataRole.DisplayRole) or "",
                               Qt.TextElideMode.ElideRight,
                               text_rect.width())
        painter.drawText(text_rect,
                         Qt.AlignmentFlag.AlignVCenter
                         | Qt.AlignmentFlag.AlignLeft, elided)
        painter.restore()


class _SlotWidget(QLabel):
    """游戏同款容器槽位：原版 slot.png 槽底 + 图标 + 数量角标 + 流光。

    - 槽底：游戏容器槽位同款原版贴图 slot.png（18x18，顶/左
      #373737 内阴影 + 底/右 #FFFFFF 亮线 + #8B8B8B 内部，与
      generic_54.png 图集内嵌槽位同源）；scale 整数倍时贴图与
      图标同步最近邻放大（FastTransformation，像素风不插值）；
    - 图标：原版纹理像素风，槽内绘制边长 = round(16*scale*0.8)
      （用户需求缩小 20%，居中），剪裁区/流光随图标起点同步；
    - 数量角标：右下角，像素字体白字 + 1px 右下阴影（游戏数量
      显示同款），仅在数量 >1 时显示；
    - 附魔流光：Plus 混合两层反向滚动光效纹理（与
      _GlintItemDelegate 同款实现，剪裁到图标不透明区）。
    用 paintEvent 自绘而非 pixmap 拼合：流光需要每帧重绘。
    """

    SLOT = 18                       # 1x 槽位边长（游戏 GUI 18px 槽距）
    GLINT_MS = 50                   # 流光帧间隔（同 _GlintItemDelegate）

    def __init__(self, stack=None, glint_timer: "QTimer | None" = None,
                 scale: int = 1, parent=None):
        super().__init__(parent)
        self._scale = max(1, int(scale))
        self.setFixedSize(self.SLOT * self._scale, self.SLOT * self._scale)
        self._pix = None
        self._region = None
        self._ench = False
        self._count = 0
        self._t_fast = 0
        self._t_slow = 0
        if stack is not None:
            key = _icon_key(stack)
            loaded = _load_item_scaled(key, self._scale)
            if loaded is not None:
                self._pix, self._region = loaded
            self._ench = bool(stack.enchantments)
            self._count = stack.count
            # 详情 = 游戏 tooltip 风格富文本（同箱子列表子行）
            self.setToolTip(_item_tooltip_html(stack))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if glint_timer is not None and self._ench and _GLINT_OK:
            glint_timer.timeout.connect(self._advance_glint)

    def _advance_glint(self) -> None:
        """推进两层流光位移并重绘（仅附魔槽位连接，开销极低）。"""
        span = 16 * self._scale       # 周期 = 图标跨度（倍缩放无缝循环）
        self._t_fast = (self._t_fast + 1) % span
        self._t_slow = (self._t_slow - 1) % span
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        s = self._scale
        # 1) 槽底：原版 slot.png（18x18），按 scale 整数倍最近邻
        #    放大后整贴（描边/阴影/底色比例与游戏一致，按尺寸缓存）
        if os.path.exists(_SLOT_TEX):
            key = 18 * s
            if key not in _slot_tex_cache:
                _slot_tex_cache[key] = QPixmap(_SLOT_TEX).scaled(
                    key, key, Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation)
            p.drawPixmap(self.rect(), _slot_tex_cache[key])
        else:                        # 贴图缺失回退：手绘三色凹槽
            p.fillRect(0, 0, 18 * s, 18 * s,
                       QColor(0x8B, 0x8B, 0x8B))
            p.fillRect(0, 0, 17 * s, s, QColor(0x37, 0x37, 0x37))
            p.fillRect(0, 0, s, 17 * s, QColor(0x37, 0x37, 0x37))
            p.fillRect(s, 17 * s, 17 * s, s, QColor(0xFF, 0xFF, 0xFF))
            p.fillRect(17 * s, s, s, 17 * s, QColor(0xFF, 0xFF, 0xFF))
        if self._pix is None:
            return
        # 2) 物品图标（缩小 20% 居中：_pix 边长 = round(12.8*s)，
        #    槽内区 (s,s) 起算居中偏移，非整数时左偏取整）
        iw = self._pix.width()
        ix = s + (16 * s - iw) // 2
        p.drawPixmap(ix, ix, self._pix)
        # 3) 附魔流光（两层反向滚动 + Plus 加法，剪裁不透明区；
        #    剪裁与滚动基准点 = 图标起点 ix，相位随缩小同步平移）
        if self._ench and _GLINT_OK:
            tex = _load_glint_pixmap(16 * s)
            if tex is not None:
                p.save()
                if self._region is not None:
                    p.setClipRegion(self._region.translated(ix, ix))
                p.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_Plus)
                p.setOpacity(0.35)
                span = 16 * s
                step = 2 * span
                for off in (self._t_fast, self._t_slow):
                    for dx in (0, step):
                        for dy in (0, step):
                            p.drawPixmap(ix - off + dx, ix - off + dy, tex)
                p.restore()
        # 4) 数量角标（>1 时右下角）：默认普通系统字体粗体白字 +
        # 多向描边阴影（_PIXEL_FONT_UI=True 切回游戏像素字形）
        if self._count > 1:
            text = str(self._count)
            if _PIXEL_FONT_UI and _load_glyphs():
                tw, _th = _pixel_text_size(text)
                tx = 17 * s - tw * s           # 右对齐（含 s px 内边距）
                ty = 10 * s                    # 字形底行对齐 17px 线
                _draw_pixel_text(p, tx, ty, text,
                                 QColor(0xFF, 0xFF, 0xFF), s,
                                 QColor(0x3F, 0x3F, 0x3F))
            else:
                p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                f = QFont()
                f.setPixelSize(12 * s)
                f.setBold(True)
                p.setFont(f)
                fm = p.fontMetrics()
                tw, th = fm.horizontalAdvance(text), fm.ascent()
                tx = 17 * s - tw                # 右对齐（含 s px 槽内边距）
                ty = 17 * s                     # 底对齐基线
                p.setPen(QPen(QColor(0x3F, 0x3F, 0x3F), 1))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if dx or dy:
                            p.drawText(tx + dx, ty + dy, text)
                p.setPen(QPen(QColor(0xFF, 0xFF, 0xFF), 1))
                p.drawText(tx, ty, text)
        return


class ChestLootDialog(QDialog):
    """箱子战利品 GUI（游戏大箱子同款 3x9 槽位布局 + 原版面板贴图）。

    - 背景：generic_54.png 裁 (0,0,176,90) 的单箱槽区面板（游戏
      箱子界面同源贴图），整体按 GUI_SCALE 倍最近邻放大；
    - 槽位序 = generate_loot 原始产出顺序逐堆摆放（游戏物品实际
      入箱顺序，与工具箱列表的合并显示口径不同）；槽位坐标与
      generic_54 图集一致（x8 起、y17 标题区下、步距 18）；
    - 每槽 = _SlotWidget：原版 slot.png 凹槽 + 原版纹理图标 +
      数量角标 + 附魔流光，tooltip 同游戏槽位语义；
    - 非模态（show）：主窗口保持可交互，避免模态 exec 阻塞主窗
      造成程序卡死的假象；同工具同时最多一个开箱窗（重开先关旧）；
    - E 键关闭（同游戏关闭容器界面；Esc 默认 reject 同样隐藏）；
      失焦自动关（悬浮面板行为）：焦点被视口/主窗/其它程序夺走
      即关，避免锁定态视口吞掉 Esc/E 后 GUI 永远关不掉。
    """

    GUI_SCALE = 2                   # 整体缩放倍数（1x=游戏原生 176x90）

    def __init__(self, items: list, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        # 非模态：exec() 会阻塞父窗口事件处理，观感像程序卡死；
        # 改 show() 由调用方持有引用防 GC（见 _on_chest_open_requested）
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint,
                           False)
        # 悬停提示去系统白框：Windows 默认 QTipLabel 是白底外框，
        # 会包在富文本卡片外面（截图实测）；把系统框架底色改成
        # 卡片同色 #100010、边框归零，紫色描边直接贴边（游戏观感）。
        # 样式表（QToolTip/QTipLabel 选择器）与调色板 ToolTipBase
        # 双保险，只作用于本对话框内的悬停提示。
        self.setStyleSheet("QToolTip, QTipLabel { "
                           "background-color: #100010; "
                           "border: 0px; color: #ffffff; }")
        _tip_pal = self.palette()
        _tip_pal.setColor(QPalette.ColorRole.ToolTipBase,
                          QColor(0x10, 0x00, 0x10))
        _tip_pal.setColor(QPalette.ColorRole.ToolTipText,
                          QColor(0xFF, 0xFF, 0xFF))
        self.setPalette(_tip_pal)
        self._glint_timer: QTimer | None = None
        self._build_ui(items)

    # ---------- UI ----------
    def _build_ui(self, items: list) -> None:
        s = self.GUI_SCALE
        self._panel = _load_panel_pixmap(s)
        # 窗体 = 面板贴图原始尺寸（1x 176x78），无系统边框（游戏
        # 界面观感），标题条文字画在面板 17px 标题区
        self.setFixedSize(_PANEL_W * s, _PANEL_H * s)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        # 真半透明窗体：generic_54 四角是斜切圆角（对角线黑边外为
        # 透明像素，游戏内露世界画面）。不开此属性时透明区露出
        # 系统窗底灰白色，四角凸出「白色直角尖角」；开启后透桌面，
        # 与游戏悬浮观感一致。须在 show 之前设置。
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground,
                          True)
        # 共享流光定时器：只在本箱有附魔物品时启动（关窗随对象销毁）
        if _GLINT_OK and any(s_.enchantments
                             for s_ in items[:27]):
            self._glint_timer = QTimer(self)
            self._glint_timer.start(_SlotWidget.GLINT_MS)
        # 27 槽：3 行 x 9 列，行优先（物品按产出顺序依次入槽）；
        # 槽间距 0（槽位相邻，游戏容器槽位即如此）
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        for i in range(min(27, len(items))):
            cell = _SlotWidget(items[i], self._glint_timer, scale=s)
            grid.addWidget(cell, i // 9, i % 9)
        # 空槽补位到 27（游戏箱子永远渲染全部槽位）
        for i in range(len(items), 27):
            grid.addWidget(_SlotWidget(None, scale=s), i // 9, i % 9)
        # 边距对齐 generic_54 图集：槽位网格 x8 起、标题区高 17
        # （与游戏箱子 GUI 同坐标），底部 7px 是边框条
        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(8 * s, 17 * s, 6 * s, 7 * s)
        wrap.setSpacing(0)
        wrap.addLayout(grid)
        if not items:
            tip = QLabel("（空）")
            tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tip.setStyleSheet("color: #404040;")
            wrap.addWidget(tip)
        elif len(items) > 27:
            # 防御：正常箱子 loot 表不会超 27 堆
            over = QLabel(f"另有 {len(items) - 27} 堆未显示（超容器容量）")
            over.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wrap.addWidget(over)

    def paintEvent(self, ev) -> None:  # noqa: N802
        """面板背景：generic_54 两段拼接贴图整窗拉伸（游戏同款）；
        标题条 = 面板 17px 标题区居中深灰像素文字（游戏字形）。

        超宽自适应：标题像素宽 > 可用区（面板宽-2 格内边距）时
        先降 1x 渲染（等宽对半），再超则省略号截断——保证不越出
        面板（loot 表路径长，如 chests/end_city_treasure @ 坐标，
        2x 面板 352px 放不下 1x 也 205px 全串，曾被窗体边缘切字
        成「字形残缺」观感）。
        """
        p = QPainter(self)
        if self._panel is not None:
            p.drawPixmap(self.rect(), self._panel)
        else:                        # 贴图缺失回退：纯面板灰
            p.fillRect(self.rect(), QColor(0xC6, 0xC6, 0xC6))
        # 标题条：默认普通系统字体居中 #404040（_PIXEL_FONT_UI=True
        # 切回游戏像素字形 + 1px 阴影 #101010，超宽降级/省略号）
        text = self.windowTitle()
        if _PIXEL_FONT_UI and _load_glyphs():
            s = self.GUI_SCALE
            avail = (_PANEL_W - 16) * s      # 槽区内边距同款余量
            scale = s
            tw, _th = _pixel_text_size(text)
            if tw * s > avail:
                scale = 1
                tw = _pixel_text_size(text)[0]
            if tw * scale > avail:
                # 省略号截断（… 用两点 ..，ASCII 字形内）
                while text and _pixel_text_size(text + "..")[0] * scale \
                        > avail:
                    text = text[:-1]
                text += ".."
                tw = _pixel_text_size(text)[0]
            x0 = (_PANEL_W * s - tw * scale) // 2
            y0 = (17 - 8) // 2 * scale       # 17px 标题区垂直居中
            _draw_pixel_text(p, x0, y0, text,
                             QColor(0x40, 0x40, 0x40), scale,
                             QColor(0x10, 0x10, 0x10))
        else:
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
            f = QFont()
            f.setPixelSize(8 * self.GUI_SCALE)
            p.setFont(f)
            p.setPen(QColor(0x40, 0x40, 0x40))
            p.drawText(QRect(0, 0, _PANEL_W * self.GUI_SCALE,
                             17 * self.GUI_SCALE),
                       Qt.AlignmentFlag.AlignCenter, text)

    # ---------- 按键 ----------
    def changeEvent(self, ev) -> None:  # noqa: N802
        """失焦自动关：非模态无边框窗没有关闭钮，焦点一旦离开
        （点视口/点列表/Alt+Tab），Esc/E 会被锁定态视口吞掉，GUI
        就关不掉了（实测死锁）。悬浮面板行为：失活即关，close 走
        finished 信号 -> 工具层解锁链路。

        QWidget 激活变化走 ActivationChange（WindowDeactivate 是
        QWindow 层事件，不进 changeEvent，实测手动派发不回调）；
        获得激活时 isActiveWindow 为 True 不关，仅失活关闭。
        """
        if ev.type() == QEvent.Type.ActivationChange \
                and self.isVisible() and not self.isActiveWindow():
            self.close()
        super().changeEvent(ev)

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        if ev.key() == Qt.Key.Key_E and not ev.isAutoRepeat():
            # 非模态窗口用 close()（隐藏+可被回收），accept() 仅对
            # exec() 事件循环有意义
            self.close()
            ev.accept()
            return
        super().keyPressEvent(ev)


class _LocateThread(QThread):
    """附近实例枚举线程（复用 enumerate_structures，结构粒度进度）。"""

    progress = Signal(int, int)          # done, total
    finished_ok = Signal(list)           # 实例列表
    error = Signal(str)

    def __init__(self, seed: int, version_key: str, struct_key: str,
                 center_x: int, center_z: int, parent=None):
        super().__init__(parent)
        self._seed = seed
        self._version_key = version_key
        self._struct_key = struct_key
        self._cx = center_x
        self._cz = center_z
        self._cancelled = False

    def request_cancel(self):
        self._cancelled = True

    def run(self):
        try:
            r = _LOCATE_RADIUS
            viewport = (self._cx - r, self._cz - r,
                        self._cx + r, self._cz + r)
            # 结果按距中心排序（近的排前面）
            items = enumerate_structures(
                self._seed, self._version_key, viewport,
                [self._struct_key],
                on_progress=lambda d, t, k: (
                    self.progress.emit(int(d), int(t))),
                cancel=lambda: self._cancelled,
                # 下界结构必须按维度枚举（非主世界维度自动走
                # NetherSampler；缺省 overworld 会被维度防御过滤成空）
                dimension=structure_params.STRUCT_DIMENSION.get(
                    self._struct_key, "overworld"),
            )
            if self._cancelled:
                return
            cx, cz = self._cx, self._cz
            items.sort(key=lambda it: (it["x"] - cx) ** 2
                       + (it["z"] - cz) ** 2)
            self.finished_ok.emit(items)
        except Exception as exc:
            if not self._cancelled:
                self.error.emit(f"实例枚举失败：{exc}")


class StructurePreviewerWidget(BaseToolWidget, Ui_structurePreviewer):
    preferred_size = (1170, 826)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # 3D 视口替换占位（与 SeedReverser 同款接入）；本工具
        # 默认旁观者相机（WASD+鼠标 FP 飞行），切结构不退出模式
        self._view = structure_3dview.Structure3DView()
        self._view.setObjectName("structure3DView")
        self._view.render_error.connect(self._on_render_error)
        self._view.chest_open_requested.connect(self._on_chest_open_requested)
        # 锁定态 Esc/E 转发：关开箱 GUI（双保险，见 handler docstring）
        self._view.spectator_close_request.connect(
            self._on_spectator_close_request)
        self._view.set_spectator_mode(True)
        self.gridLayout.replaceWidget(self.viewportPlaceholder, self._view)
        self.viewportPlaceholder.hide()
        # 当前注入的显示模型（compose_display_model 输出；箱子行高亮用）
        self._model: dict | None = None
        # 当前选中箱子序号（0 起；-1 = 未选）
        self._selected_chest = -1
        # 已加载预览的实例坐标（x_str, z_str)；None = 未加载。
        # 按钮两态判据：当前坐标框内容与之相等 → 「预览」，否则
        # 「附近的实例」（坐标变了即视为新搜索目标）
        self._loaded_pos: tuple[str, str] | None = None
        # 本次枚举请求的上下文签名（种子/版本/结构/中心坐标），
        # 完成回调时与当前 UI 比对，不一致则丢弃过期结果
        self._locate_sig: tuple | None = None
        # 会话持久化：恢复完成前抑制写盘（防半恢复状态回写）
        self._session_ready = False

        # 附近实例线程与缓存
        self._locate_thread = None
        self._locate_result: list[dict] = []
        # 开箱窗引用（非模态 show；持有防 GC，重开先关旧）
        self._chest_dlg: "ChestLootDialog | None" = None
        # loot 表缓存随实例预览构建（era 变化时重建）
        self._current_era = -1

        self._init_ui()

    # ---------- 基类接口 ----------
    @classmethod
    def tool_name(cls) -> str:
        return "StructurePreviewer"

    # ---------- 初始化 ----------
    def _init_ui(self) -> None:
        # .ui 中三个 GroupBox 内部是绝对定位（不缩放、不贴合），
        # 运行时改装布局管理器并做防溢出处理
        self._fit_groupbox_layouts()

        # 版本下拉（VERSION_KEYS = 26.2/1.21.11/1.21，loot/biome 链路
        # 三键全支持）
        self.versionCombo.addItems(structure_params.VERSION_KEYS)
        self.versionCombo.setCurrentIndex(0)

        # 结构下拉：仅本工具支持的两个结构（图标复用 MapPreviewer 资产）
        # 名称/图标查 cubiomes 键（STRUCT_NAMES/图标表无 woodland_mansion
        # 别名），结构键仍存 UI 键
        for key in _STRUCT_KEYS:
            enum_key = _UI_TO_ENUM.get(key, key)
            name = structure_params.STRUCT_NAMES.get(enum_key, key)
            spath = struct_icons.icon_path(enum_key)
            if spath:
                icon = QIcon(spath)
                if not icon.isNull():
                    self.structCombo.addItem(icon, name, key)
                else:
                    self.structCombo.addItem(name, key)
            else:
                self.structCombo.addItem(name, key)
        self.structCombo.setCurrentIndex(0)

        # 信息/箱子/实例三个区域文本初始化
        self.infoLabel.setText(
            "输入种子后点「附近的实例」查找，或「粘贴F3+C」填入坐标")
        # 提示文案较长：必须换行，否则 QLabel 不换行的
        # minimumSizeHint=整行文本宽，会把网格列 0-1 撑到 576px，
        # 挤塌列 3-4（Z 输入框塌成 24px 缝）并整体右移
        self.hintLabel.setWordWrap(True)
        self.hintLabel.setText(
            "提示：右键结果行复制传送指令")

        # 附近实例表头
        self.treeWidget.setColumnCount(4)
        self.treeWidget.setHeaderLabels(["结构", "X", "Z", "群系"])
        self.treeWidget.setRootIsDecorated(False)
        self.treeWidget.setAlternatingRowColors(True)

        # 箱子表头（战利品展示为子行）
        self.chestList.setColumnCount(1)
        self.chestList.setHeaderLabels(["箱子与战利品"])
        self.chestList.setRootIsDecorated(True)
        self.chestList.itemClicked.connect(self._on_chest_clicked)
        # 子行物品图标+附魔流光：自定义委托负责绘制（图标在名称前）
        self.chestList.setIconSize(QSize(16, 16))
        self._glint_delegate = _GlintItemDelegate(self.chestList,
                                                  parent=self.chestList)
        self.chestList.setItemDelegate(self._glint_delegate)

        # 进度条：默认隐藏（定位时短暂显示）
        self.progressBar.setRange(0, 100)
        self.progressBar.hide()

        # 按钮：单按钮两态（匹配已加载实例=「预览」/否则「附近的实例」）
        self.btnPreview.clicked.connect(self._on_preview_clicked)
        self.pasteBtn.clicked.connect(self._on_paste_f3c)
        self.coordXEdit.textChanged.connect(self._update_preview_button)
        self.coordZEdit.textChanged.connect(self._update_preview_button)
        self._update_preview_button()
        # 镜头灵敏度滑条：整数档 [1,30] ↔ 0.01~0.30 度/像素，
        # 联动视口转视角灵敏度；标签显示实际值（滑条默认值在
        # _restore_session 里恢复，这里只接信号与初始显示）
        self.lensSensitivitySlider.setRange(_SENS_MIN, _SENS_MAX)
        self.lensSensitivitySlider.setValue(_SENS_DEFAULT)
        self.lensSensitivitySlider.valueChanged.connect(
            self._on_sensitivity_changed)
        self._on_sensitivity_changed(self.lensSensitivitySlider.value())
        self.treeWidget.itemDoubleClicked.connect(
            self._on_instance_activated)
        # 右键实例行：复制传送指令（F3+C 同款，维度随结构所属世界）
        self.treeWidget.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.treeWidget.customContextMenuRequested.connect(
            self._on_instance_context_menu)
        # 搜索上下文变化（结构/版本/种子）：作废已加载实例与过期列表
        self.structCombo.currentIndexChanged.connect(
            self._invalidate_context)
        self.versionCombo.currentIndexChanged.connect(
            self._invalidate_context)
        self.seedEdit.textChanged.connect(self._invalidate_context)

        # 退出钩子：停后台线程（防退出期 QThread 析构 0xC0000409）
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._stop_locate_thread)
            app.aboutToQuit.connect(self._stop_glint_delegate)
            app.aboutToQuit.connect(self._save_session)
        # 启动时恢复上次会话（种子/坐标/灵敏度；异常静默跳过）
        self._restore_session()
        self._session_ready = True

    # ---------- 会话持久化（本页输入状态重启不丢） ----------
    def _session_path(self) -> str:
        """会话文件路径（用户配置目录下 structure_previewer_session.json）。"""
        config_dir = QStandardPaths.writableLocation(
            QStandardPaths.AppConfigLocation)
        if not config_dir:
            config_dir = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, _SESSION_FILE)

    def _save_session(self) -> None:
        """保存本页输入状态：种子、坐标、镜头灵敏度。

        数据变化点与退出时调用；恢复完成前不落盘。写盘失败仅
        打印不干扰交互（同 SeedReverser 会话口径）。
        """
        if not self._session_ready:
            return
        try:
            data = {
                "seed": self.seedEdit.text(),
                "coord_x": self.coordXEdit.text(),
                "coord_z": self.coordZEdit.text(),
                "sensitivity": self.lensSensitivitySlider.value(),
            }
            with open(self._session_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"保存结构预览会话失败: {e}")

    def _restore_session(self) -> None:
        """启动时从会话文件恢复（文件缺失/损坏时静默跳过）。"""
        path = self._session_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
        except (OSError, ValueError) as e:
            print(f"恢复结构预览会话失败: {e}")
            return
        seed = data.get("seed")
        if isinstance(seed, str):
            self.seedEdit.setText(seed)
        cx = data.get("coord_x")
        if isinstance(cx, str):
            self.coordXEdit.setText(cx)
        cz = data.get("coord_z")
        if isinstance(cz, str):
            self.coordZEdit.setText(cz)
        sens = data.get("sensitivity")
        if isinstance(sens, int) and _SENS_MIN <= sens <= _SENS_MAX:
            self.lensSensitivitySlider.setValue(sens)

    # ---------- 镜头灵敏度（滑条 ↔ 视口转视角灵敏度） ----------
    def _on_sensitivity_changed(self, value: int) -> None:
        """滑条变化：换算并应用到视口 + 标签显示实际值 + 落盘。"""
        deg = value / 100.0
        self._view.set_spectator_sensitivity(deg)
        self.lensSensitivityLabel.setText(
            f"镜头灵敏度 {deg:.2f}°/px")
        self._save_session()             # 灵敏度变化落盘（恢复期被抑制）

    @staticmethod
    def _fit_tree_widget(tree: "QTreeWidget",
                         content_cols: int = 0) -> None:
        """树视图防溢出：禁横向滚动，超宽文本省略号 + 悬浮提示。

        - ElideRight：超出列宽的文字显示为 …；
        - 横向滚动条常隐，末列随面板拉伸（stretchLastSection）；
        - content_cols > 0 时前 N 列按内容自适应（如 结构/X/Z 列），
          其余留给末列；uniformRowHeights 加速大列表。
        """
        tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tree.setVerticalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        tree.setHorizontalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        header = tree.header()
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(32)
        for c in range(max(0, min(content_cols, tree.columnCount() - 1))):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        tree.setUniformRowHeights(True)

    def _fit_groupbox_layouts(self) -> None:
        """把 .ui 绝对定位的内部控件改挂到 GroupBox 布局上。

        .ui 编译产物中 infoLabel/treeWidget/chestList 是
        setGeometry 固定矩形：GroupBox 缩放时既不跟随（小了被裁切）
        也不贴合边缘。此处为每个 GroupBox 装上 QVBoxLayout，让内容
        自动填满标题栏以下区域；树视图再按 _fit_tree_widget 防溢出。
        """
        # 结构信息：QLabel 占满，长文本自动换行
        info_v = QVBoxLayout(self.infoGroupBox)
        info_v.setContentsMargins(8, 4, 8, 8)
        info_v.setSpacing(0)
        self.infoLabel.setWordWrap(True)
        self.infoLabel.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction)
        self.infoLabel.setAlignment(Qt.AlignmentFlag.AlignLeft
                                    | Qt.AlignmentFlag.AlignTop)
        info_v.addWidget(self.infoLabel, 1)

        # 附近的实例：树占满 GroupBox
        locate_v = QVBoxLayout(self.locateGroupBox)
        locate_v.setContentsMargins(4, 4, 4, 4)
        locate_v.setSpacing(0)
        locate_v.addWidget(self.treeWidget, 1)
        self._fit_tree_widget(self.treeWidget)

        # 箱子与战利品：树占满 GroupBox
        chests_v = QVBoxLayout(self.chestsGroupBox)
        chests_v.setContentsMargins(4, 4, 4, 4)
        chests_v.setSpacing(0)
        chests_v.addWidget(self.chestList, 1)
        self._fit_tree_widget(self.chestList)

    # ---------- 输入解析 ----------
    @staticmethod
    def _parse_seed(text: str) -> int:
        t = text.strip()
        if not t:
            raise ValueError("请输入世界种子")
        try:
            if t.lower().startswith("0x") or t.lower().startswith("-0x"):
                v = int(t, 16)
            else:
                v = int(t, 10)
        except ValueError:
            raise ValueError(f"无法解析种子：{t!r}（支持十进制与 0x 十六进制）")
        if not (-(1 << 63) <= v < (1 << 63)):
            raise ValueError("种子超出 64 位有符号整数范围")
        return v

    @staticmethod
    def _parse_int(text: str, what: str, default: int | None = None) -> int:
        t = text.strip()
        if not t:
            if default is not None:
                return default
            raise ValueError(f"请输入 {what} 坐标")
        try:
            return int(t, 10)
        except ValueError:
            raise ValueError(f"无法解析 {what} 坐标：{t!r}")

    # F3+C 内容中的数字（含负号与小数）
    _F3C_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")

    @classmethod
    def _parse_f3c(cls, text: str) -> tuple[int, int, str | None]:
        """解析 F3+C 剪贴板内容 → (方块X, 方块Z, 维度名|None)。

        兼容格式（Y 坐标与视角一律忽略，取整用 floor 对齐游戏）：
          /execute in minecraft:overworld run tp @s 72.7 64 -119.4 -120.6 12.3
          /tp @s 72.7 64 -119.4
          72.7 64 -119.4（纯坐标）
        """
        dim = None
        m = re.search(r"in\s+(?:minecraft:)?([A-Za-z_]+)\s+run\s+tp\b", text)
        if m:
            dim = m.group(1).lower()
            # F3+C 用命名空间 id the_nether/the_end，归一到结构维度键
            if dim == "the_nether":
                dim = "nether"
            elif dim == "the_end":
                dim = "end"
        nums = cls._F3C_NUM_RE.findall(text)
        if len(nums) < 3:
            raise ValueError(
                "无法解析 F3+C 内容：请按 F3+C 复制完整坐标"
                "（/execute in ... run tp @s X Y Z）后重试")
        x = math.floor(float(nums[0]))
        z = math.floor(float(nums[2]))
        return x, z, dim

    def _current_struct_key(self) -> str:
        return self.structCombo.currentData() or "igloo"

    # ---------- 粘贴 F3+C ----------
    def _on_paste_f3c(self) -> None:
        """「粘贴F3+C」：读剪贴板 → 填 X/Z（坐标变了按钮复位为「附近的实例」）。"""
        text = QApplication.clipboard().text().strip()
        if not text:
            self.infoLabel.setText(
                "剪贴板为空：在游戏中按 F3+C 复制坐标后再点本按钮")
            return
        try:
            x, z, dim = self._parse_f3c(text)
        except ValueError as e:
            self.infoLabel.setText(str(e))
            return
        self.coordXEdit.setText(str(x))
        self.coordZEdit.setText(str(z))
        struct_dim = structure_params.STRUCT_DIMENSION.get(
            self._current_struct_key(), "overworld")
        if dim is not None and dim != struct_dim:
            self.infoLabel.setText(
                f"已填入 ({x}, {z})｜注意：F3+C 维度为 {dim}，"
                f"当前结构生成于"
                f"{structure_params.DIMENSION_NAMES.get(struct_dim, struct_dim)}，"
                "坐标可能不匹配")
        else:
            self.infoLabel.setText(
                f"已填入 ({x}, {z})，点「附近的实例」以该点为中心查找")

    # ---------- 按钮两态 ----------
    def _is_loaded_current(self) -> bool:
        """当前坐标框内容 == 已加载预览的实例坐标（按钮呈「预览」态）。"""
        if self._loaded_pos is None:
            return False
        return (self.coordXEdit.text().strip(),
                self.coordZEdit.text().strip()) == self._loaded_pos

    def _update_preview_button(self) -> None:
        """坐标匹配已加载实例 → 「预览」；否则 → 「附近的实例」。"""
        if self._is_loaded_current():
            self.btnPreview.setText("预览")
            self.btnPreview.setToolTip("显示该坐标处的结构与战利品预测")
        else:
            self.btnPreview.setText("附近的实例")
            self.btnPreview.setToolTip(
                "以输入坐标为中心枚举附近实例（留空以原点为中心）")
        self._save_session()             # 坐标变化落盘（恢复期被抑制）

    # ---------- 搜索上下文 ----------
    def _context_signature(self) -> tuple:
        """当前搜索上下文签名（种子/版本/结构/中心坐标）。"""
        return (self.seedEdit.text().strip(),
                self.versionCombo.currentText(),
                self._current_struct_key(),
                self.coordXEdit.text().strip(),
                self.coordZEdit.text().strip())

    def _invalidate_context(self) -> None:
        """结构/版本/种子变化：作废已加载实例与过期列表，按钮复位。

        实例列表的枚举结果只对请求时的上下文有效：切换结构/版本/
        种子后旧行不再可信，双击会预览出错误组合，必须清空。
        """
        self._loaded_pos = None
        self.treeWidget.clear()
        self._locate_result = []
        self._update_preview_button()
        self._save_session()             # 种子/版本/结构变化落盘

    # ---------- 附近实例 ----------
    def _on_locate_clicked(self) -> None:
        if self._locate_thread is not None:
            return                     # 枚举进行中
        try:
            seed = self._parse_seed(self.seedEdit.text())
        except ValueError as e:
            self.infoLabel.setText(str(e))
            return
        # 枚举以输入坐标为中心；留空以 (0,0) 为中心
        try:
            cx = self._parse_int(self.coordXEdit.text(), "X", 0)
            cz = self._parse_int(self.coordZEdit.text(), "Z", 0)
        except ValueError as e:
            self.infoLabel.setText(str(e))
            return
        version = self.versionCombo.currentText()
        key = self._current_struct_key()
        self._locate_sig = self._context_signature()   # 竞态防护基线
        self.btnPreview.setEnabled(False)
        self.progressBar.setRange(0, 0)     # 忙碌态
        self.progressBar.show()
        self.treeWidget.clear()
        # 枚举链路用 cubiomes 键（woodland_mansion -> mansion）
        self._locate_thread = _LocateThread(
            seed, version, _UI_TO_ENUM.get(key, key), cx, cz, parent=self)
        self._locate_thread.finished.connect(self._locate_thread.deleteLater)
        self._locate_thread.finished.connect(self._on_locate_finished)
        self._locate_thread.finished_ok.connect(self._on_locate_ok)
        self._locate_thread.error.connect(self._on_locate_error)
        self._locate_thread.start()

    def _stop_locate_thread(self) -> None:
        """退出钩子：请求取消并同步等待线程收尾后丢引用。"""
        th = self._locate_thread
        if th is None:
            return
        self._locate_thread = None
        th.request_cancel()
        # finished→deleteLater 已在创建处连接；此处只丢引用，
        # C++ 对象随事件循环回收（此时线程已退出，析构安全）
        th.wait(3000)

    def _stop_glint_delegate(self) -> None:
        """退出钩子：停战利品流光动画定时器（防退出期重绘崩溃）。"""
        self._glint_delegate.stop()

    def _on_locate_finished(self) -> None:
        """线程结束（正常/取消/异常）统一收尾：恢复按钮。"""
        self._locate_thread = None
        self.btnPreview.setEnabled(True)
        self.progressBar.hide()

    def _on_locate_ok(self, items: list) -> None:
        # 竞态防护：枚举期间上下文（种子/版本/结构/中心）已变 →
        # 结果过期，丢弃（列表已由 _invalidate_context 清空）
        if self._locate_sig != self._context_signature():
            self.infoLabel.setText("上下文已变化，本次搜索结果已丢弃，请重新查找")
            return
        self._locate_result = items
        self.treeWidget.clear()
        if not items:
            self.infoLabel.setText(
                f"附近 {_LOCATE_RADIUS} 方块内未找到该结构实例")
            return
        for it in items:
            cells = [it["name"], str(it["x"]), str(it["z"]),
                     biome_label(it["biome"])]
            row = QTreeWidgetItem(cells)
            # 列宽不足省略号时，悬浮可见全文
            row.setToolTip(0, " | ".join(cells))
            # UserRole 存 (x, z, 结构键)：双击填坐标用前两位；右键复制
            # 传送指令时按行自带的结构键展开维度，不依赖当下下拉状态
            row.setData(0, Qt.ItemDataRole.UserRole,
                        (it["x"], it["z"], it["struct"]))
            self.treeWidget.addTopLevelItem(row)
        self.infoLabel.setText(
            f"找到 {len(items)} 个实例（双击行加载预览，右键复制传送指令）")

    def _on_locate_error(self, msg: str) -> None:
        self.infoLabel.setText(msg)

    def _on_instance_activated(self, item, _col) -> None:
        """双击实例行：填坐标并标记为已加载实例（按钮变「预览」）→ 预览。"""
        pos = item.data(0, Qt.ItemDataRole.UserRole)
        if pos:
            self._loaded_pos = (str(pos[0]), str(pos[1]))
            self.coordXEdit.setText(self._loaded_pos[0])
            self.coordZEdit.setText(self._loaded_pos[1])
            self._on_preview_clicked()

    # ---------- 右键复制传送指令 ----------
    def _on_instance_context_menu(self, pos) -> None:
        """右键实例行：复制 F3+C 同款传送指令（execute in <维度> run tp）。

        维度从行自带的结构键推导（见 _on_locate_ok 的 UserRole 注释），
        菜单项文案直接标出目标世界，避免拿到指令才发现 tp 错维度。
        """
        item = self.treeWidget.itemAt(pos)
        if item is None or not item.data(0, Qt.ItemDataRole.UserRole):
            return
        p = item.data(0, Qt.ItemDataRole.UserRole)
        dim_key = structure_params.STRUCT_DIMENSION.get(p[2], "overworld")
        dim_cn = structure_params.DIMENSION_NAMES.get(dim_key, dim_key)
        menu = QMenu(self)
        act_tp = menu.addAction(f"复制TP指令（{dim_cn}，F3+C 格式）")
        if menu.exec(self.treeWidget.viewport().mapToGlobal(pos)) is act_tp:
            self._copy_instance_tp(item)

    def _copy_instance_tp(self, item) -> None:
        """实例行传送指令写入剪贴板（菜单动作与离屏测试共用实现）。"""
        p = item.data(0, Qt.ItemDataRole.UserRole)
        if not p:
            return
        QApplication.clipboard().setText(_tp_command(p[0], p[1], p[2]))
        self.infoLabel.setText(
            f"已复制 ({p[0]}, {p[1]}) 的传送指令，"
            "粘贴到游戏聊天栏回车执行（Y=100 上空，自行调整高度）")

    # ---------- 预览主流程（单按钮两态统一入口）----------
    def _on_preview_clicked(self) -> None:
        if not self._is_loaded_current():
            self._on_locate_clicked()
            return
        try:
            seed = self._parse_seed(self.seedEdit.text())
            bx = self._parse_int(self.coordXEdit.text(), "X")
            bz = self._parse_int(self.coordZEdit.text(), "Z")
        except ValueError as e:
            self.infoLabel.setText(str(e))
            return
        version = self.versionCombo.currentText()
        key = self._current_struct_key()
        try:
            # 0) 别名映射：枚举/校验链路用 cubiomes 键（如
            # woodland_mansion -> mansion），compose 仍用 UI 键。
            enum_key = _UI_TO_ENUM.get(key, key)
            # 1) 群系校验：锚点处无结构 → 提示（不影响 compose 演示）。
            # 下界结构走 check_structure_at 内部惰性创建的 NetherSampler，
            # 主世界 BiomeSampler 不必创建（省噪声初始化开销）
            sampler = (BiomeSampler(seed, version)
                       if structure_params.STRUCT_DIMENSION.get(enum_key, "overworld")
                       == "overworld" else None)
            viable, biome = check_structure_at(
                enum_key, seed, bx, bz, version, sampler)
            # 2) compose：变种/旋转/箱子坐标/LootTableSeed
            biome_arg = biome if biome >= 0 else -1
            comp = composition.compose(
                key, seed, bx, bz, biome_id=biome_arg, version_key=version)
            # 3) 显示模型 + 注入视口（mesh/tex_keys 已由
            # compose_display_model 组装，无需再建）
            model = composition.compose_display_model(comp)
            self._view.set_model(model)
            self._model = model
            self._selected_chest = -1
            self._view.set_chest_highlights(None)
            # 开箱准星：可交互箱子 = 渲染体素里的全部容器方块
            #（含 RNG 未预测的——bastion jigsaw 渲染箱多于预测箱，
            # 见 compose_display_model.chest_blocks）；open_map 按
            # 模型坐标映射到预测 Chest（有预测才弹战利品 GUI）。
            self._view.set_interact_chests(model.get("chest_blocks"))
            # 4) 战利品
            era = loot_engine.era_for_version(version)
            # 缓存 comp/era 供 3D 开箱（准星右键/E）按序取 loot_seed
            self._comp = comp
            self._era = era
            self._fill_chests(comp, era, viable, biome)
            self._fill_info(comp, viable, biome, seed, version)
        except Exception as exc:
            self.infoLabel.setText(f"预览失败：{exc}")

    def _fill_info(self, comp, viable: bool, biome: int,
                   seed: int, version: str) -> None:
        key = comp.struct_key
        # 显示名查 cubiomes 键（STRUCT_NAMES 无 woodland_mansion 别名）
        name = structure_params.STRUCT_NAMES.get(
            _UI_TO_ENUM.get(key, key), key)
        # variant_name 与键同名时（如要塞）不重复展示
        variant = (f"（{comp.variant_name}）"
                   if comp.variant_name != key else "")
        lines = [
            f"结构：{name}{variant}",
            f"锚点：({comp.anchor[0]}, {comp.anchor[1]})"
            f"｜旋转 {comp.rotation}"
            + ("｜镜像" if comp.mirror else ""),
            f"群系：{biome_label(biome)}"
            + ("" if viable else "（⚠ 该锚点未通过生成校验——"
                              "结构可能不存在，仅供 RNG 演示）"),
        ]
        if key == "igloo":
            if comp.extra.get("basement"):
                lines.append(f"地下室：有（竖井 {comp.extra['size']} 段）")
            else:
                lines.append("地下室：无")
        elif key == "shipwreck":
            lines.append(f"搁浅（beached）："
                         f"{'是' if comp.extra.get('beached') else '否'}")
        elif key == "nether_fortress":
            lines.append(f"部件数：{comp.extra.get('n_pieces', '?')}（含起始件）")
        elif key == "end_city":
            lines.append(f"部件数：{comp.extra.get('n_pieces', '?')}（含起始件）"
                         + ("｜含末地船" if comp.extra.get("ship") else ""))
        elif key == "bastion_remnant":
            start = comp.extra.get("start")
            cn = (_BASTION_START_CN[start]
                  if isinstance(start, int) and 0 <= start < len(_BASTION_START_CN)
                  else comp.variant_name)
            lines.append(f"起点类型：{cn}")
        elif key == "trial_chambers":
            lines.append(f"部件数：{comp.extra.get('n_pieces', '?')}（含起始件）"
                         f"｜密室层 y：{comp.extra.get('start_y', '?')}")
        elif key == "ancient_city":
            start = comp.extra.get("start")
            cn = (_ANCIENT_CITY_START_CN[start]
                  if isinstance(start, int)
                  and 0 <= start < len(_ANCIENT_CITY_START_CN)
                  else comp.variant_name)
            lines.append(f"中心类型：{cn}"
                         f"｜部件数：{comp.extra.get('n_pieces', '?')}（含起始件）")
            lines.append(f"城市底面 y：{comp.extra.get('start_y', '?')}")
        elif key == "village":
            variant = comp.extra.get("variant", "?")
            zombie = comp.extra.get("zombie", False)
            lines.append(f"变体：{variant}"
                         + ("（僵尸村庄：起点抽中僵尸中心）" if zombie else ""))
            lines.append(f"中心类型：{comp.extra.get('start', '?') + 1} 号"
                         f"（起点池权重展开序）"
                         f"｜部件数：{comp.extra.get('n_pieces', '?')}（含起始件）")
            lines.append(f"地基面 y：{comp.extra.get('start_y', '?')}")
        elif key == "pillager_outpost":
            lines.append(f"部件数：{comp.extra.get('n_pieces', '?')}（含起始件）")
        elif key == "stronghold":
            eyes = comp.extra.get("portal_eyes", 0)
            lines.append(f"部件数：{comp.extra.get('n_pieces', '?')}（含起始件）")
            lines.append(f"传送门已填眼：{bin(eyes).count('1')}/12"
                         f"（{hex(eyes)}）")
        elif key in ("desert_pyramid", "jungle_temple"):
            dir_cn = ("北", "东", "南", "西")[comp.extra.get("facing", 0) % 4]
            lines.append(f"朝向：{dir_cn}"
                         f"｜容器数：{comp.extra.get('n_containers', '?')}"
                         "（含发射器）")
        elif key == "ruined_portal":
            mirror = comp.extra.get("mirror_fb", False)
            lines.append(f"变体：{comp.extra.get('variant_cn', '?')}"
                         f"｜放置：{comp.extra.get('placement_cn', '?')}")
            lines.append(f"模板：{comp.extra.get('template', '?')}")
            rot = comp.rotation % 4
            lines.append(f"朝向：{('北', '东', '南', '西')[rot]}"
                         f"｜镜像（前后）：{'是' if mirror else '否'}")
            lines.append(f"埋放 y：{comp.extra.get('y0', '?')}"
                         f"（平坦基准，地下/山体变体为负）"
                         f"｜气室：{'有' if comp.extra.get('air_pocket') else '无'}"
                         f"｜藤蔓：{'有' if comp.extra.get('vines') else '无'}"
                         f"｜葱郁：{'有' if comp.extra.get('overgrown') else '无'}")
        elif key == "buried_treasure":
            lines.append("锚点：区块内 (9, 9)"
                         "｜单箱埋于地表下一格（平坦示意）")
        elif key == "woodland_mansion":
            lines.append(f"拼装旋转：{comp.extra.get('rot_name', '?')}"
                         f"｜房间件数：{comp.extra.get('n_pieces', '?')}")
            lines.append(f"覆盖区块：{comp.extra.get('chunk', '?')}")
        elif key == "ocean_ruin":
            lines.append(f"水温：{'暖水' if comp.extra.get('temp') == 'warm' else '冷水'}"
                         f"｜大型：{'是' if comp.extra.get('large') else '否'}")
            if comp.extra.get("cluster"):
                lines.append(f"簇件：{comp.extra.get('n_cluster', '?')} 件")
            lines.append(f"部件数：{comp.extra.get('n_pieces', '?')}（含簇件）")
        lines.append(f"箱子数：{len(comp.chests)}")
        self.infoLabel.setText("\n".join(lines))

    def _fill_chests(self, comp, era: int, viable: bool,
                     biome: int) -> None:
        self.chestList.clear()
        if not comp.chests:
            self.chestList.setHeaderLabels(
                ["箱子与战利品（无箱子）"])
            return
        for i, chest in enumerate(comp.chests, start=1):
            table_name = chest.loot_table
            seed_signed = loot_rng.signed_seed(chest.loot_seed)
            label = (f"箱{i}（{table_name}）@ ({chest.pos[0]}, {chest.pos[1]})"
                     f"｜LootTableSeed: {seed_signed}")
            top = QTreeWidgetItem([label])
            top.setToolTip(0, label)
            try:
                table = _loot_table(table_name, era)
                items = loot_engine.generate_loot(table, chest.loot_seed)
            except Exception as exc:
                err = f"战利品求值失败：{exc}"
                top.addChild(QTreeWidgetItem([err]))
                top.setToolTip(0, err)
                self.chestList.addTopLevelItem(top)
                continue
            if items:
                for stack in _merge_stacks(items):
                    txt = _item_label(stack)
                    child = QTreeWidgetItem([txt])
                    # 详情 = 游戏 tooltip 风格富文本（深色卡片：
                    # 物品名白字 + 附魔/效果灰字行）
                    child.setToolTip(0, _item_tooltip_html(stack))
                    key = _icon_key(stack)
                    child.setData(0, Qt.ItemDataRole.UserRole, key)
                    if stack.enchantments:
                        child.setData(0, _ENCHANTED_ROLE, True)
                    top.addChild(child)
            else:
                top.addChild(QTreeWidgetItem(["（空）"]))
            self.chestList.addTopLevelItem(top)
        self.chestList.expandAll()

    # ---------- 3D 开箱（准星右键/E）：弹出箱子 GUI ----------
    def _on_chest_open_requested(self, idx: int) -> None:
        """视口准星态右键/E 开箱：弹出该箱战利品 GUI。

        idx 是交互箱子全集（model["chest_blocks"]）里的下标；按
        模型坐标映射到 RNG 预测的 Chest（pos_model），有预测才
        求值战利品（未匹配到预测箱时弹提示而非编造战利品）。
        槽位摆放 = generate_loot 原始产出
        顺序（不合并，游戏实际入箱序）；开箱期间视口 FP 输入锁定，
        关窗解锁并按需恢复鼠标捕获。关窗途径：E / Esc / 失焦自动
        关（ChestLootDialog.changeEvent）/ 锁定态视口 Esc-E 转发
        （spectator_close_request，双保险）。
        """
        chest = None
        pos = None
        if self._model is not None \
                and 0 <= idx < len(self._model.get("chest_blocks", [])):
            pos = self._model["chest_blocks"][idx]
            if getattr(self, "_comp", None) is not None:
                for c in self._comp.chests:
                    if c.pos_model == pos:
                        chest = c
                        break
        if chest is None or pos is None:
            # 早退（无预测数据）：无 GUI 弹出，直接按需恢复鼠标锁定
            self._view.note_chest_gui_closed()
            if pos is not None:
                self.infoLabel.setText(
                    "该箱子未匹配到预测数据，暂无战利品")
            return
        items = []
        era = getattr(self, "_era", None)
        if era is not None:
            try:
                table = _loot_table(chest.loot_table, era)
                items = loot_engine.generate_loot(table, chest.loot_seed)
            except Exception as exc:  # noqa: BLE001
                self.infoLabel.setText(f"战利品求值失败：{exc}")
        # 标题短名：去掉 chests/ 内部路径前缀（像素字体 2x 面板
        # 宽 352px，全路径约 410px 会溢出被切；短名 + 坐标足够辨识，
        # 与箱子列表括号内同名前缀口径一致）
        short = chest.loot_table.split("/", 1)[-1]
        title = f"{short} @ ({pos[0]}, {pos[1]}, {pos[2]})"
        # 非模态单实例：关旧（deleteLater 释放）再建新，show 后由
        # self._chest_dlg 持引用防 GC；主窗口事件循环不阻塞
        old = self._chest_dlg
        dlg = ChestLootDialog(items, title, self)
        self._chest_dlg = dlg                # 先换引用：旧窗 finished 到达
        dlg.finished.connect(                # 时 sender 校验不误撤新锁
            self._on_chest_dlg_finished)
        if old is not None:
            old.close()
            old.deleteLater()
        dlg.show()
        # 开箱期间锁死视口 FP 输入（移动/转视角/滚轮调速），关窗
        # 解锁并按需恢复鼠标捕获继续飞行；开箱前的锁定态
        # （_sp_resume_grab）保留到关窗时消耗
        self._view.set_spectator_input_locked(True)

    def _on_spectator_close_request(self) -> None:
        """锁定态视口 Esc/E 转发：关开箱 GUI（若在）。双保险——
        正常路径弹窗失焦自关（ChestLootDialog.changeEvent）；焦点
        停在视口且弹窗未收到失活的平台边缘态由此兜底。"""
        dlg = self._chest_dlg
        if dlg is not None and dlg.isVisible():
            dlg.close()

    def _on_chest_dlg_finished(self) -> None:
        """开箱窗 finished（E/Esc 关闭）：解锁视口 FP 输入。

        sender 校验：替换重开时旧窗 close 的 finished 同步到达，
        此时 self._chest_dlg 已指向新窗，不误撤新窗的输入锁。
        """
        if self.sender() is self._chest_dlg:
            self._view.set_spectator_input_locked(False)

    # ---------- 箱子行点击：视口琥珀描边高亮 ----------
    def _on_chest_clicked(self, item, _col) -> None:
        """点顶层行（箱子）→ 视口高亮该箱；子行（战利品）归到其父。"""
        while item.parent() is not None:
            item = item.parent()
        idx = self.chestList.indexOfTopLevelItem(item)
        if idx < 0:
            return
        self._selected_chest = idx
        # 行前景琥珀强调（其余行复位）
        amber = QBrush(_HIGHLIGHT_AMBER)
        for i in range(self.chestList.topLevelItemCount()):
            it = self.chestList.topLevelItem(i)
            it.setForeground(0, amber if i == idx else QBrush())
        marks = self._model["chests"] if self._model else None
        if marks and idx < len(marks):
            self._view.set_chest_highlights([marks[idx]])

    # ---------- 渲染错误 ----------
    def _on_render_error(self, msg: str) -> None:
        self.infoLabel.setText(msg)

    # ---------- ` 键全局兜底：焦点不在 3D 视口时也能开始控制视角 ----------
    def keyPressEvent(self, ev) -> None:  # noqa: N802
        if ev.key() == Qt.Key.Key_QuoteLeft and self._view.isVisible() \
                and self._view.is_spectator_mode() \
                and not self._view.mouse_grabbed():
            # 仅在「未控制」态转发（锁定态 ` 由视口自身处理呼出）；
            # 焦点给视口让后续 WASD 直接生效
            self._view.setFocus(Qt.FocusReason.OtherFocusReason)
            self._view.spectator_toggle_grab()
            ev.accept()
            return
        super().keyPressEvent(ev)

