# -*- coding: utf-8 -*-
"""MapPreviewer 群系配色表。

id 依据 cubiomes biomes.h BiomeID 枚举（与 Utils/SeedReverser/biome_names.py
同源）；配色参考 Amidst/cubiomes mapview 风格并按俯视观感微调。
覆盖 1.18+ 主世界表层常见群系，未收录 id 兜底灰色，不致渲染失败。
"""

# biome id -> (r, g, b)
BIOME_COLORS: dict[int, tuple[int, int, int]] = {
    # --- 海洋/河流 ---
    0: (63, 118, 228),     # ocean 海洋
    7: (82, 132, 240),     # river 河流（比海洋亮一档）
    10: (64, 96, 228),     # frozen_ocean 冻洋
    11: (96, 96, 228),     # frozen_river 冻河
    24: (49, 88, 190),     # deep_ocean 深海
    44: (76, 158, 255),    # warm_ocean 暖水海洋
    45: (66, 138, 245),    # lukewarm_ocean 温水海洋
    46: (63, 108, 228),    # cold_ocean 冷水海洋
    47: (64, 112, 210),    # deep_warm_ocean
    48: (56, 102, 200),    # deep_lukewarm_ocean
    49: (52, 92, 195),     # deep_cold_ocean
    50: (88, 110, 215),    # deep_frozen_ocean 深寒海洋

    # --- 平原/草原/沼泽 ---
    1: (141, 179, 96),     # plains 平原
    129: (145, 185, 100),  # sunflower_plains 向日葵平原
    35: (189, 178, 95),    # savanna 热带草原
    36: (170, 160, 90),    # savanna_plateau 热带高原
    163: (160, 150, 88),   # windswept_savanna 风袭热带草原
    164: (152, 143, 85),   # windswept_savanna_plateau
    6: (111, 158, 88),     # swamp 沼泽
    134: (109, 152, 85),   # swamp_hills
    184: (97, 143, 82),    # mangrove_swamp 红树林沼泽

    # --- 森林 ---
    4: (89, 135, 60),      # forest 森林
    18: (85, 128, 58),     # wooded_hills
    132: (100, 150, 70),   # flower_forest 繁花森林
    27: (106, 143, 70),    # birch_forest 桦木森林
    28: (100, 136, 67),    # birch_forest_hills
    155: (114, 148, 76),   # old_growth_birch_forest 原始桦木森林
    156: (108, 141, 73),   # tall_birch_hills
    29: (48, 82, 40),      # dark_forest 黑森林
    157: (45, 76, 38),     # dark_forest_hills
    21: (83, 123, 47),      # jungle 丛林
    22: (78, 115, 45),     # jungle_hills
    23: (90, 128, 55),     # sparse_jungle 稀疏丛林
    168: (64, 110, 42),    # bamboo_jungle 竹林
    169: (61, 105, 40),    # bamboo_jungle_hills

    # --- 针叶林/寒带 ---
    5: (85, 110, 78),      # taiga 针叶林
    19: (79, 102, 73),     # taiga_hills
    133: (82, 106, 76),    # taiga_mountains
    30: (120, 140, 130),   # snowy_taiga 雪林
    31: (112, 132, 122),   # snowy_taiga_hills
    158: (108, 128, 118),  # snowy_taiga_mountains
    32: (91, 115, 88),     # old_growth_pine_taiga 原始松针叶林
    33: (86, 110, 84),     # old_growth_spruce_taiga
    34: (90, 112, 85),     # windswept_forest 疏林山地
    12: (164, 175, 190),   # snowy_plains 雪原
    13: (158, 169, 184),   # snowy_mountains
    26: (140, 165, 190),   # snowy_beach 雪滩
    140: (176, 190, 210),  # ice_spikes 冰刺之地
    15: (150, 160, 180),   # mushroom_field_shore 蘑菇岛岸
    14: (178, 140, 180),   # mushroom_fields 蘑菇岛

    # --- 山地/裸岩/雪峰 ---
    3: (96, 106, 96),      # windswept_hills 风袭丘陵
    131: (104, 114, 104),  # windswept_gravelly_hills
    20: (90, 100, 92),     # mountain_edge
    17: (100, 105, 88),    # desert_hills
    25: (120, 120, 120),   # stony_shore 石岸
    177: (108, 152, 88),   # meadow 草甸
    178: (160, 172, 178),  # grove 雪坡林地
    179: (200, 210, 220),  # snowy_slopes 雪坡
    180: (225, 232, 240),  # jagged_peaks 尖峭山峰
    181: (215, 224, 235),  # frozen_peaks 冰封山峰
    182: (115, 120, 115),  # stony_peaks 裸岩山峰
    183: (38, 38, 48),     # deep_dark 深暗之域

    # --- 沙漠/恶地 ---
    2: (222, 204, 130),    # desert 沙漠
    130: (218, 198, 122),  # desert_lakes
    37: (197, 130, 77),    # badlands 恶地
    38: (186, 122, 72),    # wooded_badlands
    39: (190, 128, 76),    # badlands_plateau
    165: (185, 120, 72),   # eroded_badlands

    # --- 岸线/杂项 ---
    16: (222, 214, 163),   # beach 海滩
    185: (243, 183, 199),  # cherry_grove 樱花树林
    186: (140, 150, 145),  # pale_garden 苍白之园
    174: (140, 120, 90),   # dripstone_caves
    175: (90, 140, 95),    # lush_caves
}

# 未收录 id 的兜底色（灰）
FALLBACK_COLOR = (128, 128, 128)

# id -> 中文群系名（悬停信息条/图例用）
BIOME_CN_NAMES: dict[int, str] = {
    0: "海洋", 1: "平原", 2: "沙漠", 3: "风袭丘陵", 4: "森林", 5: "针叶林",
    6: "沼泽", 7: "河流", 10: "冻洋", 11: "冻河", 12: "雪原", 13: "雪山",
    14: "蘑菇岛", 15: "蘑菇岛岸", 16: "海滩", 17: "沙漠丘陵", 18: "山地森林",
    19: "针叶林丘陵", 20: "山地边缘", 21: "丛林", 22: "丛林丘陵", 23: "稀疏丛林",
    24: "深海", 25: "石岸", 26: "雪滩", 27: "桦木森林", 28: "桦木森林丘陵",
    29: "黑森林", 30: "雪林", 31: "雪林丘陵", 32: "原始松针叶林",
    33: "原始云杉针叶林", 34: "疏林山地", 35: "热带草原", 36: "热带高原",
    37: "恶地", 38: "繁茂恶地", 39: "恶地高原", 44: "暖水海洋",
    45: "温水海洋", 46: "冷水海洋", 47: "深暖水海洋", 48: "深温水海洋",
    49: "深冷水海洋", 50: "深寒海洋", 129: "向日葵平原", 130: "沙漠湖泊",
    131: "风袭砾质丘陵", 132: "繁花森林", 133: "针叶林山地", 134: "沼泽丘陵",
    140: "冰刺之地", 155: "原始桦木森林", 156: "高大桦木丘陵", 157: "黑森林丘陵",
    158: "雪林山地", 163: "风袭热带草原", 164: "风袭热带草原高原",
    165: "被风蚀的恶地", 168: "竹林", 169: "竹林丘陵", 174: "溶洞",
    175: "繁茂洞穴", 177: "草甸", 178: "雪坡林地", 179: "雪坡",
    180: "尖峭山峰", 181: "冰封山峰", 182: "裸岩山峰", 183: "深暗之域",
    184: "红树林沼泽", 185: "樱花树林", 186: "苍白之园",
}


def biome_color(bid: int) -> tuple[int, int, int]:
    """biome id → (r, g, b)，未收录兜底灰。"""
    return BIOME_COLORS.get(bid, FALLBACK_COLOR)


def biome_cn_name(bid: int) -> str:
    """biome id → 中文群系名，未知返回 id=N。"""
    return BIOME_CN_NAMES.get(bid, f"id={bid}")
