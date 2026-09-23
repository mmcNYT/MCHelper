# -*- coding: utf-8 -*-
"""群系标志色表（下拉选中群系后，行编辑器内群系名文字染该色）。

数据来源与准则：
- 颜色抓取自中文 Minecraft Wiki 各群系页面信息框
  （zh.minecraft.wiki，2026-09-19 抓取，Java 版数值）；
- 陆地群系取「草地颜色」；海洋/河流类群系草地色无区分度，
  改取「水体颜色」（JE 值）；
- 沼泽 / 红树林沼泽草色按噪声分两档，取信息框主档（噪声值
  不小于 -0.1）；
- 下界 / 末地群系草色在 wiki 上为统一值（下界 #BFB755、
  末地 #8EB971），照录（供 MapPreviewer 下界/末地维度下拉）。

键 = biome_names.BIOME_CHOICES / _EXTRA_DIM_BIOMES 的内部键；
值 = "#RRGGBB"。未收录键由 color_for_label 返回 None（调用方
恢复默认文字色）。
"""

# 海洋/河流类（11 项）：草地色无区分度，取水体颜色（JE）
_WATER_KEY_COLORS: dict[str, str] = {
    "ocean": "#3F76E4",                # 海洋
    "deep_ocean": "#3F76E4",           # 深海
    "warm_ocean": "#43D5EE",           # 暖水海洋
    "lukewarm_ocean": "#45ADF2",       # 温水海洋
    "cold_ocean": "#3D57D6",           # 冷水海洋
    "deep_lukewarm_ocean": "#45ADF2",  # 温水深海
    "deep_cold_ocean": "#3D57D6",      # 冷水深海
    "deep_frozen_ocean": "#3938C9",    # 冰冻深海
    "frozen_ocean": "#3938C9",         # 冻洋
    "river": "#3F76E4",                # 河流
    "frozen_river": "#3938C9",         # 冻河
}

# 其余群系取草地颜色（主世界 44 项 + 下界/末地 10 项）
BIOME_SIGNATURE_COLORS: dict[str, str] = {
    # 海洋/河流类：水体颜色（JE）
    **_WATER_KEY_COLORS,
    # 平原类
    "plains": "#91BD59",                    # 平原
    "sunflower_plains": "#91BD59",          # 向日葵平原
    "snowy_plains": "#80B497",              # 雪原
    "ice_spikes": "#80B497",                # 冰刺之地
    # 干旱类
    "desert": "#BFB755",                    # 沙漠
    "savanna": "#BFB755",                   # 热带草原
    "savanna_plateau": "#BFB755",           # 热带高原
    "windswept_savanna": "#BFB755",         # 风袭热带草原
    "badlands": "#90814D",                  # 恶地
    "eroded_badlands": "#90814D",           # 风蚀恶地
    "wooded_badlands": "#90814D",           # 疏林恶地
    # 森林类
    "forest": "#79C05A",                    # 森林
    "flower_forest": "#79C05A",             # 繁花森林
    "birch_forest": "#88BB67",              # 桦木森林
    "old_growth_birch_forest": "#88BB67",   # 原始桦木森林
    "dark_forest": "#507A32",               # 黑森林
    "pale_garden": "#778272",               # 苍白之园
    "jungle": "#59C93C",                    # 丛林
    "sparse_jungle": "#64C73F",             # 稀疏丛林
    "bamboo_jungle": "#59C93C",             # 竹林
    "taiga": "#86B783",                     # 针叶林
    "snowy_taiga": "#80B497",               # 积雪针叶林
    "old_growth_pine_taiga": "#86B87F",     # 原始松木针叶林
    "old_growth_spruce_taiga": "#86B783",   # 原始云杉针叶林
    # 湿地/岸滩类
    "swamp": "#6A7039",                     # 沼泽（主档：噪声值不小于 -0.1）
    "mangrove_swamp": "#6A7039",            # 红树林沼泽（同上主档）
    "beach": "#91BD59",                     # 沙滩
    "snowy_beach": "#83B593",               # 积雪沙滩
    "stony_shore": "#8AB689",               # 石岸
    "mushroom_fields": "#55C93F",           # 蘑菇岛（草地颜色）
    # 山地类
    "windswept_hills": "#8AB689",           # 风袭丘陵
    "windswept_gravelly_hills": "#8AB689",  # 风袭沙砾丘陵
    "windswept_forest": "#8AB689",          # 风袭森林
    "meadow": "#83BB6D",                    # 草甸
    "cherry_grove": "#B6DB61",              # 樱花树林
    "grove": "#80B497",                     # 雪林
    "snowy_slopes": "#80B497",              # 积雪山坡
    "jagged_peaks": "#80B497",              # 尖峭山峰
    "frozen_peaks": "#80B497",              # 冰封山峰
    "stony_peaks": "#9ABE4B",               # 裸岩山峰
    # 洞穴类
    "dripstone_caves": "#91BD59",           # 溶洞（JE）
    "lush_caves": "#8EB971",                # 繁茂洞穴（JE）
    "deep_dark": "#91BD59",                 # 深暗之域
    "sulfur_caves": "#ABA64F",              # 硫黄洞穴
    # 下界（草地颜色，wiki 各下界群系统一值）
    "nether_wastes": "#BFB755",             # 下界荒地
    "soul_sand_valley": "#BFB755",          # 灵魂沙峡谷
    "crimson_forest": "#BFB755",            # 绯红森林
    "warped_forest": "#BFB755",             # 诡异森林
    "basalt_deltas": "#BFB755",             # 玄武岩三角洲
    # 末地（草地颜色，wiki 各末地群系统一值）
    "the_end": "#8EB971",                   # 末地
    "small_end_islands": "#8EB971",         # 末地小型岛屿
    "end_midlands": "#8EB971",              # 末地中部高地（末地内陆）
    "end_highlands": "#8EB971",             # 末地高地
    "end_barrens": "#8EB971",               # 末地荒地
}


def color_for_label(label: str) -> str | None:
    """下拉标签（"中文 内部键"）→ 标志色；未匹配返回 None。

    末段作为查表键（标签 = "中文 英文键"，两者均不含空格），
    兼容直接传内部键；空串/未知项（如「选择群系」占位、手输
    未匹配文本）返回 None，由调用方恢复默认文字色。
    """
    if not label:
        return None
    key = label.strip().rsplit(" ", 1)[-1]
    return BIOME_SIGNATURE_COLORS.get(key)
