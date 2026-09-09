# -*- coding: utf-8 -*-
"""群系名映射表（SeedReverser 世界种子精化面板用）。

数据来源与准则：
- id 以 cubiomes biomes.h BiomeID 枚举为唯一权威（1.18~1.21+）；
- 中文译名以用户提供的 54 项权威对照表为准（与中文 Wiki 对齐，
  如 温水深海/积雪沙滩/积雪针叶林）；
- 自然生成清单以 cubiomes biomes.c isOverworld(mc>=1.18) 为准，与
  20 万点 BiomeSampler 采样实测（54 个 id）完全一致。

三个用途：
1. UI 下拉/补全：BIOME_CHOICES（显示标签, 内部键），仅收录 1.18+ 自然
   生成的 54 个主世界群系；
2. 名称解析：resolve_biome(label) -> biome_id | None，支持中文标签 /
   F3 显示名 / cubiomes 枚举名（下划线式或驼峰式）/ 1.18 改名前旧名，
   大小写与分隔符（空格/下划线/连字符）不敏感；
3. 观测列表显示：biome_label(id) -> 标签；
4. 图标：icon_path(key) -> 群系图标路径（biome_icons/<key>.png，
   取自中文 Wiki BiomeSprite，仅下拉 54 项配图）。
"""

import os

# (显示标签, 内部键)。标签 = 中文 Wiki 译名 + F3 英文原名（按 F3 优先）。
# 共 54 项 = 1.18+ 主世界自然生成全集。
BIOME_CHOICES = [
    ("海洋 ocean", "ocean"),                              # 0
    ("平原 plains", "plains"),                            # 1
    ("沙漠 desert", "desert"),                            # 2
    ("风袭丘陵 windswept_hills", "windswept_hills"),      # 3
    ("森林 forest", "forest"),                            # 4
    ("针叶林 taiga", "taiga"),                            # 5
    ("沼泽 swamp", "swamp"),                              # 6
    ("河流 river", "river"),                              # 7
    ("冻洋 frozen_ocean", "frozen_ocean"),                # 10
    ("冻河 frozen_river", "frozen_river"),                # 11
    ("雪原 snowy_plains", "snowy_plains"),                # 12
    ("蘑菇岛 mushroom_fields", "mushroom_fields"),        # 14
    ("沙滩 beach", "beach"),                              # 16
    ("丛林 jungle", "jungle"),                            # 21
    ("稀疏丛林 sparse_jungle", "sparse_jungle"),          # 23
    ("深海 deep_ocean", "deep_ocean"),                    # 24
    ("石岸 stony_shore", "stony_shore"),                  # 25
    ("积雪沙滩 snowy_beach", "snowy_beach"),              # 26
    ("桦木森林 birch_forest", "birch_forest"),            # 27
    ("黑森林 dark_forest", "dark_forest"),                # 29
    ("积雪针叶林 snowy_taiga", "snowy_taiga"),            # 30
    ("原始松木针叶林 old_growth_pine_taiga", "old_growth_pine_taiga"),  # 32
    ("原始云杉针叶林 old_growth_spruce_taiga", "old_growth_spruce_taiga"),  # 160
    ("风袭森林 windswept_forest", "windswept_forest"),    # 34
    ("热带草原 savanna", "savanna"),                      # 35
    ("热带高原 savanna_plateau", "savanna_plateau"),      # 36
    ("恶地 badlands", "badlands"),                        # 37
    ("疏林恶地 wooded_badlands", "wooded_badlands"),      # 38
    ("暖水海洋 warm_ocean", "warm_ocean"),                # 44
    ("温水海洋 lukewarm_ocean", "lukewarm_ocean"),        # 45
    ("冷水海洋 cold_ocean", "cold_ocean"),                # 46
    ("温水深海 deep_lukewarm_ocean", "deep_lukewarm_ocean"),  # 48
    ("冷水深海 deep_cold_ocean", "deep_cold_ocean"),      # 49
    ("冰冻深海 deep_frozen_ocean", "deep_frozen_ocean"),  # 50
    ("向日葵平原 sunflower_plains", "sunflower_plains"),  # 129
    ("风袭沙砾丘陵 windswept_gravelly_hills", "windswept_gravelly_hills"),  # 131
    ("繁花森林 flower_forest", "flower_forest"),          # 132
    ("冰刺之地 ice_spikes", "ice_spikes"),                # 140
    ("原始桦木森林 old_growth_birch_forest", "old_growth_birch_forest"),  # 155
    ("风袭热带草原 windswept_savanna", "windswept_savanna"),  # 163
    ("风蚀恶地 eroded_badlands", "eroded_badlands"),      # 165
    ("竹林 bamboo_jungle", "bamboo_jungle"),              # 168
    ("溶洞 dripstone_caves", "dripstone_caves"),          # 174
    ("繁茂洞穴 lush_caves", "lush_caves"),                # 175
    ("草甸 meadow", "meadow"),                            # 177
    ("雪林 grove", "grove"),                              # 178
    ("积雪山坡 snowy_slopes", "snowy_slopes"),            # 179
    ("尖峭山峰 jagged_peaks", "jagged_peaks"),            # 180
    ("冰封山峰 frozen_peaks", "frozen_peaks"),            # 181
    ("裸岩山峰 stony_peaks", "stony_peaks"),              # 182
    ("深暗之域 deep_dark", "deep_dark"),                  # 183
    ("红树林沼泽 mangrove_swamp", "mangrove_swamp"),      # 184
    ("樱花树林 cherry_grove", "cherry_grove"),            # 185
    ("苍白之园 pale_garden", "pale_garden"),              # 186
]

# ---- 解析别名（下拉未收录项 + 1.18 改名前旧名 + F3 变体）----
# 注：deep_warm_ocean(47) 已随 21w43a 移除不再生成；hills 系
# （desert_hills 17 等）、164（破碎的热带高原）、130/134 等在 1.18+
# 不再自然生成，仅保留旧名解析（旧版本观测/输入兜底）。
_BIOME_IDS: dict[str, int] = {
    # 主表（0~50）
    "ocean": 0, "plains": 1, "desert": 2, "mountains": 3,
    "windswept_hills": 3, "extremehills": 3,
    "forest": 4, "taiga": 5, "swamp": 6, "swampland": 6,
    "river": 7,
    "frozen_ocean": 10,
    "frozen_river": 11, "frozenriver": 11,
    "snowy_tundra": 12, "iceplains": 12, "snowy_plains": 12,
    "snowy_mountains": 13, "icemountains": 13,
    "mushroom_fields": 14, "mushroomisland": 14,
    "mushroom_field_shore": 15, "mushroomislandshore": 15,
    "beach": 16,
    "desert_hills": 17, "deserthills": 17,
    "wooded_hills": 18, "foresthills": 18,
    "taiga_hills": 19, "taigahills": 19,
    "mountain_edge": 20, "extremehillsedge": 20,
    "jungle": 21, "jungle_hills": 22, "junglehills": 22,
    "jungle_edge": 23, "jungleedge": 23, "sparse_jungle": 23,
    "deep_ocean": 24, "deepocean": 24,
    "stone_shore": 25, "stonebeach": 25, "stony_shore": 25,
    "snowy_beach": 26, "coldbeach": 26,
    "birch_forest": 27, "birchforest": 27,
    "birch_forest_hills": 28, "birchforesthills": 28,
    "dark_forest": 29, "roofedforest": 29,
    "snowy_taiga": 30, "coldtaiga": 30,
    "snowy_taiga_hills": 31, "coldtaigahills": 31,
    "giant_tree_taiga": 32, "megataiga": 32, "old_growth_pine_taiga": 32,
    "giant_tree_taiga_hills": 33, "megataigahills": 33,
    "wooded_mountains": 34, "extremehillsplus": 34, "windswept_forest": 34,
    "savanna": 35, "savanna_plateau": 36, "savannaplateau": 36,
    "badlands": 37, "mesa": 37,
    "wooded_badlands_plateau": 38, "wooded_badlands": 38,
    "badlands_plateau": 39,
    "warm_ocean": 44, "warmocean": 44,
    "lukewarm_ocean": 45, "lukewarmocean": 45,
    "cold_ocean": 46, "coldocean": 46,
    "deep_warm_ocean": 47, "warmdeepocean": 47,
    "deep_lukewarm_ocean": 48, "lukewarmdeepocean": 48,
    "deep_cold_ocean": 49, "colddeepocean": 49,
    "deep_frozen_ocean": 50, "frozendeepocean": 50,
    # 128+ 变种
    "sunflower_plains": 129,
    "desert_lakes": 130,
    "gravelly_mountains": 131, "windswept_gravelly_hills": 131,
    "flower_forest": 132,
    "taiga_mountains": 133,
    "swamp_hills": 134,
    "ice_spikes": 140,
    "tall_birch_forest": 155, "old_growth_birch_forest": 155,
    "tall_birch_hills": 156,
    "dark_forest_hills": 157,
    "snowy_taiga_mountains": 158,
    "giant_spruce_taiga": 160, "old_growth_spruce_taiga": 160,
    "giant_spruce_taiga_hills": 161,
    "modified_gravelly_mountains": 162,
    "shattered_savanna": 163, "windswept_savanna": 163,
    "shattered_savanna_plateau": 164, "windswept_savanna_plateau": 164,
    "eroded_badlands": 165,
    # 1.14+ 新增
    "bamboo_jungle": 168, "bamboo_jungle_hills": 169,
    "dripstone_caves": 174, "lush_caves": 175,
    "meadow": 177, "grove": 178, "snowy_slopes": 179,
    "jagged_peaks": 180, "frozen_peaks": 181, "stony_peaks": 182,
    "deep_dark": 183, "mangrove_swamp": 184, "cherry_grove": 185,
    "pale_garden": 186,
}

# 中文官方名 → 内部键（54 项权威对照，由用户提供；与下拉标签一一对应。
# 新增/修正群系时同步维护 BIOME_CHOICES 与本表即可）
CN_NAME_TO_KEY: dict[str, str] = {
    "海洋": "ocean", "平原": "plains", "沙漠": "desert",
    "森林": "forest", "针叶林": "taiga", "沼泽": "swamp",
    "河流": "river", "冻洋": "frozen_ocean", "冻河": "frozen_river",
    "雪原": "snowy_plains", "蘑菇岛": "mushroom_fields",
    "沙滩": "beach", "丛林": "jungle", "稀疏丛林": "sparse_jungle",
    "深海": "deep_ocean", "石岸": "stony_shore",
    "积雪沙滩": "snowy_beach", "桦木森林": "birch_forest",
    "黑森林": "dark_forest", "积雪针叶林": "snowy_taiga",
    "原始松木针叶林": "old_growth_pine_taiga",
    "原始云杉针叶林": "old_growth_spruce_taiga",
    "风袭森林": "windswept_forest", "热带草原": "savanna",
    "热带高原": "savanna_plateau", "恶地": "badlands",
    "疏林恶地": "wooded_badlands", "暖水海洋": "warm_ocean",
    "温水海洋": "lukewarm_ocean", "冷水海洋": "cold_ocean",
    "温水深海": "deep_lukewarm_ocean", "冷水深海": "deep_cold_ocean",
    "冰冻深海": "deep_frozen_ocean", "向日葵平原": "sunflower_plains",
    "风袭沙砾丘陵": "windswept_gravelly_hills",
    "繁花森林": "flower_forest", "冰刺之地": "ice_spikes",
    "原始桦木森林": "old_growth_birch_forest",
    "风袭热带草原": "windswept_savanna", "风蚀恶地": "eroded_badlands",
    "竹林": "bamboo_jungle", "溶洞": "dripstone_caves",
    "繁茂洞穴": "lush_caves", "草甸": "meadow", "雪林": "grove",
    "积雪山坡": "snowy_slopes", "尖峭山峰": "jagged_peaks",
    "冰封山峰": "frozen_peaks", "裸岩山峰": "stony_peaks",
    "深暗之域": "deep_dark", "红树林沼泽": "mangrove_swamp",
    "樱花树林": "cherry_grove", "苍白之园": "pale_garden",
}

# 旧版译名兜底（不进下拉，仅输入解析；不覆盖权威对照）
_LEGACY_CN_TO_KEY: dict[str, str] = {
    "积雪的沙滩": "snowy_beach",         # 1.20 前译名
    "积雪的针叶林": "snowy_taiga",       # 旧译名
    "疏林山地": "windswept_forest",      # 21w40a 前译名
    "蘑菇岛岸": "mushroom_field_shore",  # 1.18 起不生成
    "沙漠湖泊": "desert_lakes",          # 1.18 起不生成
    "海滩": "beach",                     # 旧版译名
    "雪滩": "snowy_beach",               # 旧版译名
}

# 汇总：权威对照 → 下拉标签前缀兜底 → 旧译名兜底（后者均不覆盖前者）
_F3_CN_TO_KEY: dict[str, str] = dict(CN_NAME_TO_KEY)
for _label, _key in BIOME_CHOICES:
    _F3_CN_TO_KEY.setdefault(_label.split(" ")[0], _key)
for _cn, _key in _LEGACY_CN_TO_KEY.items():
    _F3_CN_TO_KEY.setdefault(_cn, _key)


def _norm(s: str) -> str:
    """名称归一化：小写 + 去分隔符（空格/下划线/连字符）。"""
    return "".join(ch for ch in s.lower() if ch not in " _-")


_KEY_TO_ID: dict[str, int] = {_norm(k): v for k, v in _BIOME_IDS.items()}


def resolve_biome(label: str) -> int | None:
    """把用户输入的群系名解析为 biome id。

    支持：中文 F3 名 / cubiomes 枚举名（下划线或驼峰）/ 下拉标签全文。
    无法识别返回 None。
    """
    s = label.strip()
    if not s:
        return None
    # 下拉标签全文（"海洋 ocean"）
    for lab, key in BIOME_CHOICES:
        if s == lab:
            return _KEY_TO_ID.get(_norm(key))
    # 中文 F3 名
    if s in _F3_CN_TO_KEY:
        return _KEY_TO_ID.get(_norm(_F3_CN_TO_KEY[s]))
    # 英文枚举名（任意分隔符风格）
    return _KEY_TO_ID.get(_norm(s))


def biome_label(bid: int) -> str:
    """biome id → 显示标签（未收录返回英文枚举名或 "id=N"）。"""
    for lab, key in BIOME_CHOICES:
        if _KEY_TO_ID.get(_norm(key)) == bid:
            return lab
    for key, v in _BIOME_IDS.items():
        if v == bid:
            return key
    return f"id={bid}"


# ---- 图标 ----
# biome_icons/<内部键>.png（16x16，中文 Wiki BiomeSprite 下载后转存 PNG）。
# 放在本目录而非资源文件，便于用户按喜好替换图片。
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "biome_icons")


def icon_path(key: str) -> str | None:
    """内部键 → 图标文件绝对路径；文件缺失或键未知返回 None。"""
    if not key or os.path.basename(key) != key:
        return None
    p = os.path.join(ICON_DIR, key + ".png")
    return p if os.path.isfile(p) else None
