# -*- coding: utf-8 -*-
"""MapPreviewer 群系配色表。

id 依据 cubiomes biomes.h BiomeID 枚举（与 Utils/SeedReverser/biome_names.py
同源）；配色参考 Amidst/cubiomes mapview 风格并按俯视观感微调。
覆盖 1.18+ 主世界表层、下界五群系与末地五群系常见群系，未收录 id 兜底灰色，不致渲染失败。

中文群系名（悬停/图例）以 Utils/SeedReverser/biome_names.py 的 54 项
权威对照表为唯一数据源动态生成，与 SeedReverser 显示严格一致；
其余非自然生成变种与下界/末地为本地兑底表。
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
    50: (88, 110, 215),    # deep_frozen_ocean 深冻洋

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
    30: (120, 140, 130),   # snowy_taiga 积雪针叶林
    31: (112, 132, 122),   # snowy_taiga_hills
    158: (108, 128, 118),  # snowy_taiga_mountains
    32: (91, 115, 88),     # old_growth_pine_taiga 原始松木针叶林
    33: (86, 110, 84),     # old_growth_spruce_taiga
    34: (90, 112, 85),     # windswept_forest 风袭森林
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
    178: (160, 172, 178),  # grove 雪林
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
    187: (168, 138, 60),   # sulfur_caves 硫磺洞穴（26.2，红黄暖色调）

    # --- 下界（1.16+，getNetherBiome 五群系）---
    8: (90, 45, 45),       # nether_wastes 下界荒地
    170: (91, 67, 52),     # soul_sand_valley 灵魂沙峡谷
    171: (112, 30, 30),    # crimson_forest 绯红森林
    172: (45, 110, 95),    # warped_forest 诡异森林
    173: (72, 66, 78),     # basalt_deltas 玄武岩三角洲

    # --- 末地（the_end 中心岛 + 外围小岛/内陆/高地/荒芜边缘）---
    # 游戏语义：chunk 级 25x25 邻域无小岛场 → small_end_islands，
    # 实际渲染为虚空（F3 在虚空处显示该群系）；4 方块/像素下小岛
    # 本身近乎不可见，画深色才能与外岛群系形成主岛+虚空+外岛结构
    9: (222, 222, 165),    # the_end 末地
    40: (12, 12, 20),      # small_end_islands → 虚空底色（近似黑）
    41: (214, 214, 155),   # end_midlands 末地内陆
    42: (226, 226, 172),   # end_highlands 末地高地
    43: (204, 204, 150),   # end_barrens 末地荒芜之地
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
        from Utils.SeedReverser.biome_names import BIOME_CHOICES, resolve_biome
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
