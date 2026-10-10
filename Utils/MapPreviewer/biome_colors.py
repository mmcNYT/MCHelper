# -*- coding: utf-8 -*-
"""MapPreviewer 群系配色表。

id 依据 cubiomes biomes.h BiomeID 枚举（与 Utils/Public/biome_names.py
同源）；配色参考 Amidst/cubiomes mapview 风格并按俯视观感微调。
覆盖 1.18+ 主世界表层、下界五群系与末地五群系常见群系，未收录 id 兜底灰色，不致渲染失败。

中文群系名（悬停/图例）以 Utils/Public/biome_names.py 的 54 项
权威对照表为唯一数据源动态生成，与 SeedReverser 显示严格一致；
其余非自然生成变种与下界/末地为本地兑底表。
"""

# biome id -> (r, g, b)
BIOME_COLORS: dict[int, tuple[int, int, int]] = {
    # --- 海洋/河流 ---
    0: (64, 150, 214),     # ocean 海洋
    7: (160, 198, 244),    # river 河流
    10: (150, 206, 238),   # frozen_ocean 冻洋
    11: (112, 178, 222),   # frozen_river 冻河
    24: (24, 50, 160),     # deep_ocean 深海
    44: (70, 160, 240),    # warm_ocean 暖水海洋
    45: (116, 162, 244),   # lukewarm_ocean 温水海洋
    46: (52, 104, 200),    # cold_ocean 冷水海洋
    47: (70, 120, 176),    # deep_warm_ocean
    48: (36, 86, 192),     # deep_lukewarm_ocean
    49: (26, 72, 186),     # deep_cold_ocean
    50: (96, 132, 196),    # deep_frozen_ocean 深冻洋

    # --- 平原/草原/沼泽 ---
    1: (156, 190, 108),   # plains 平原
    129: (192, 200, 96),  # sunflower_plains 向日葵平原
    35: (188, 180, 90),   # savanna 热带草原
    36: (172, 162, 80),   # savanna_plateau 热带高原
    163: (158, 146, 74),  # windswept_savanna 风袭热带草原
    164: (142, 136, 68),  # windswept_savanna_plateau
    6: (58, 152, 116),    # swamp 沼泽
    134: (78, 166, 96),   # swamp_hills
    184: (108, 146, 60),  # mangrove_swamp 红树林沼泽

# --- 森林 ---
    4: (80, 128, 58),      # forest 森林
    18: (110, 118, 56),    # wooded_hills
    132: (178, 148, 138),  # flower_forest 繁花森林
    27: (168, 200, 112),   # birch_forest 桦木森林
    28: (122, 150, 80),    # birch_forest_hills
    155: (174, 202, 128),  # old_growth_birch_forest 原始桦木森林
    156: (108, 142, 78),   # tall_birch_hills
    29: (38, 66, 46),      # dark_forest 黑森林
    157: (62, 92, 64),     # dark_forest_hills
    21: (178, 142, 82),    # jungle 丛林
    22: (140, 100, 64),    # jungle_hills
    23: (134, 166, 108),   # sparse_jungle 稀疏丛林
    168: (122, 174, 98),   # bamboo_jungle 竹林
    169: (92, 148, 66),    # bamboo_jungle_hills

    # --- 针叶林/寒带 ---
    5: (58, 104, 82),     # taiga 针叶林
    19: (48, 72, 68),     # taiga_hills
    133: (88, 134, 100),  # taiga_mountains
    30: (142, 168, 154),  # snowy_taiga 积雪针叶林
    31: (118, 136, 132),  # snowy_taiga_hills
    158: (176, 184, 182), # snowy_taiga_mountains
    32: (112, 146, 102),  # old_growth_pine_taiga 原始松木针叶林
    33: (66, 124, 96),    # old_growth_spruce_taiga
    34: (150, 134, 96),   # windswept_forest 风袭森林
    12: (186, 194, 210),  # snowy_plains 雪原
    13: (140, 164, 190),  # snowy_mountains
    26: (160, 182, 196),  # snowy_beach 雪滩
    140: (176, 214, 214), # ice_spikes 冰刺之地
    15: (150, 146, 150),  # mushroom_field_shore 蘑菇岛岸
    14: (118, 96, 146),   # mushroom_fields 蘑菇岛

    # --- 山地/裸岩/雪峰 ---
    3: (112, 124, 102),   # windswept_hills 风袭丘陵
    131: (148, 150, 140), # windswept_gravelly_hills
    20: (96, 102, 96),    # mountain_edge
    17: (172, 142, 96),   # desert_hills
    25: (150, 150, 164),  # stony_shore 石岸
    177: (186, 194, 128), # meadow 草甸
    178: (120, 160, 172), # grove 雪林
    179: (214, 220, 234), # snowy_slopes 雪坡
    180: (252, 252, 252), # jagged_peaks 尖峭山峰
    181: (238, 242, 250), # frozen_peaks 冰封山峰
    182: (156, 160, 152), # stony_peaks 裸岩山峰
    183: (28, 32, 40),    # deep_dark 深暗之域

    # --- 沙漠/恶地 ---
    2: (224, 182, 122),    # desert 沙漠
    130: (238, 204, 140),  # desert_lakes
    37: (204, 132, 76),    # badlands 恶地
    38: (180, 152, 102),   # wooded_badlands
    39: (196, 102, 60),    # badlands_plateau
    165: (168, 92, 50),    # eroded_badlands

    # --- 岸线/杂项 ---
    16: (200, 208, 150),   # beach 海滩
    185: (255, 176, 200),  # cherry_grove 樱花树林（明亮粉）
    186: (122, 146, 136),  # pale_garden 苍白之园
    174: (150, 120, 82),   # dripstone_caves
    175: (90, 146, 112),   # lush_caves
    187: (168, 138, 54),   # sulfur_caves 硫磺洞穴（26.2，红黄暖色调）

    # --- 下界（1.16+，getNetherBiome 五群系）---
    8: (96, 46, 46),       # nether_wastes 下界荒地
    170: (120, 96, 58),    # soul_sand_valley 灵魂沙峡谷
    171: (204, 60, 46),    # crimson_forest 绯红森林
    172: (118, 124, 132),  # warped_forest 诡异森林
    173: (96, 88, 112),    # basalt_deltas 玄武岩三角洲

    # --- 末地（the_end 中心岛 + 外围小岛/内陆/高地/荒芜边缘）---
    # 游戏语义：chunk 级 25x25 邻域无小岛场 → small_end_islands，
    # 实际渲染为虚空（F3 在虚空处显示该群系）；4 方块/像素下小岛
    # 本身近乎不可见，画深色才能使外岛群系形成主岛+虚空+外岛结构
    9: (214, 214, 158),    # the_end 末地
    40: (12, 12, 24),      # small_end_islands → 虚空底色（近似黑）
    41: (226, 230, 150),   # end_midlands 末地内陆
    42: (250, 244, 186),   # end_highlands 末地高地
    43: (196, 196, 148),   # end_barrens 末地荒芜之地
}

# 未收录 id 的兜底色（灰）
FALLBACK_COLOR = (128, 128, 128)

# id -> 中文群系名兑底表（悬停信息条/图例用）。
# 主世界 1.18+ 自然生成 54 项由 SeedReverser 权威表动态生成（见下方
# _build_biome_cn_names）；本表只收录其余 id：1.18+ 不再自然生成的
# 主世界变种、下界/末地群系。译名风格与 MapPreviewer 群系下拉
# （task_MapPreviewer.DIM_BIOME_TABLES）一致；33/160 修正：
# 33 是原始松木针叶林的丘陵变种，160 才是原始云杉针叶林本体。
_BASE_CN_NAMES: dict[int, str] = {
    8: "下界荒地", 9: "末地",
    13: "雪山", 15: "蘑菇岛岸", 17: "沙漠丘陵", 18: "繁茂丘陵",
    19: "针叶林丘陵", 20: "山地边缘", 22: "丛林丘陵",
    28: "桦木森林丘陵", 31: "积雪针叶林丘陵", 33: "原始松木针叶林丘陵",
    39: "恶地高原", 47: "深暖水海洋",
    130: "沙漠湖泊", 133: "针叶林山地", 134: "沼泽丘陵",
    156: "高大桦木丘陵", 157: "繁茂黑森林", 158: "积雪针叶林山地",
    161: "原始云杉针叶林丘陵", 164: "风袭热带草原高原",
    169: "竹林丘陵",
    40: "末地小型岛屿", 41: "末地中部高地", 42: "末地高地",
    43: "末地荒地",
    170: "灵魂沙峡谷", 171: "绯红森林", 172: "诡异森林",
    173: "玄武岩三角洲",
}


def _build_biome_cn_names() -> dict[int, str]:
    """兑底表 + SeedReverser 权威 54 项（id→中文前缀）合并。
    权威表导入失败时仅用兑底表，悬停不致报错。"""
    names: dict[int, str] = dict(_BASE_CN_NAMES)
    try:
        from Utils.Public.biome_names import BIOME_CHOICES, resolve_biome
        for label, _key in BIOME_CHOICES:
            bid = resolve_biome(label)
            if bid is not None:
                names[int(bid)] = label.split(" ")[0]
    except Exception:
        pass
    return names


BIOME_CN_NAMES: dict[int, str] = _build_biome_cn_names()


def biome_color(bid: int) -> tuple[int, int, int]:
    """biome id → (r, g, b)，未收录兜底灰。"""
    return BIOME_COLORS.get(bid, FALLBACK_COLOR)


def biome_cn_name(bid: int) -> str:
    """biome id → 中文群系名（SeedReverser 权威名优先），未知返回 id=N。"""
    return BIOME_CN_NAMES.get(bid, f"id={bid}")
