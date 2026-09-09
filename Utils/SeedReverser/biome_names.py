# -*- coding: utf-8 -*-
"""群系名映射表（SeedReverser 世界种子精化面板用）。

数据来源：cubiomes biomes.h BiomeID 枚举（1.18~1.21+ 主世界表层群系）。

两个用途：
1. UI 下拉/补全：BIOME_CHOICES（显示标签, 内部键）；
2. 名称解析：resolve_biome(label) -> biome_id | None，支持
   中文标签 / F3 显示名 / cubiomes 枚举名（下划线式或驼峰式），大小写
   与分隔符（空格/下划线）不敏感。

F3 显示名与内部键的差异示例（Old Growth Birch Forest 等）：
F3 用 "Old Growth Birch Forest"，cubiomes 键 old_growth_birch_forest，
两者归一化后直接相同，无需单独别名表；仅下列少数名字需要显式别名。
"""

# (显示标签, 内部键)。标签 = 中文 + F3 英文原名（按 F3 屏幕优先）。
# id 以 cubiomes biomes.h 为准；id=-1 的键表示同名多 id 或非常量表层群系，
# 只用于解析 F3 名，不在下拉展示。
BIOME_CHOICES = [
    ("海洋 ocean", "ocean"),                        # 0
    ("平原 plains", "plains"),                      # 1
    ("沙漠 desert", "desert"),                      # 2
    ("风袭丘陵 windswept_hills", "windswept_hills"),  # 3
    ("森林 forest", "forest"),                      # 4
    ("针叶林 taiga", "taiga"),                      # 5
    ("沼泽 swamp", "swamp"),                        # 6
    ("河流 river", "river"),                        # 7
    ("冻洋 frozen_ocean", "frozen_ocean"),          # 10
    ("冻河 frozen_river", "frozen_river"),          # 11
    ("雪原 snowy_plains", "snowy_plains"),          # 12
    ("蘑菇岛 mushroom_fields", "mushroom_fields"),  # 14
    ("蘑菇岛岸 mushroom_field_shore", "mushroom_field_shore"),  # 15
    ("海滩 beach", "beach"),                        # 16
    ("丛林 jungle", "jungle"),                      # 21
    ("深海 deep_ocean", "deep_ocean"),              # 24
    ("石岸 stony_shore", "stony_shore"),            # 25
    ("雪滩 snowy_beach", "snowy_beach"),            # 26
    ("桦木森林 birch_forest", "birch_forest"),      # 27
    ("黑森林 dark_forest", "dark_forest"),          # 29
    ("雪林 snowy_taiga", "snowy_taiga"),            # 30
    ("原始松针叶林 old_growth_pine_taiga", "old_growth_pine_taiga"),      # 32
    ("原始云杉针叶林 old_growth_spruce_taiga", "old_growth_spruce_taiga"),  # 33
    ("疏林山地 windswept_forest", "windswept_forest"),  # 34
    ("热带草原 savanna", "savanna"),                # 35
    ("热带高原 savanna_plateau", "savanna_plateau"),  # 36
    ("恶地 badlands", "badlands"),                  # 37
    ("暖水海洋 warm_ocean", "warm_ocean"),          # 44
    ("温水海洋 lukewarm_ocean", "lukewarm_ocean"),  # 45
    ("冷水海洋 cold_ocean", "cold_ocean"),          # 46
    ("深暖水海洋 deep_warm_ocean", "deep_warm_ocean"),      # 47
    ("深温水海洋 deep_lukewarm_ocean", "deep_lukewarm_ocean"),  # 48
    ("深冷水海洋 deep_cold_ocean", "deep_cold_ocean"),      # 49
    ("深寒海洋 deep_frozen_ocean", "deep_frozen_ocean"),    # 50
    ("竹林 bamboo_jungle", "bamboo_jungle"),        # 168
    ("溶洞 dripstone_caves", "dripstone_caves"),    # 174
    ("繁茂洞穴 lush_caves", "lush_caves"),          # 175
    ("草甸 meadow", "meadow"),                      # 177
    ("雪坡林地 grove", "grove"),                    # 178
    ("雪坡 snowy_slopes", "snowy_slopes"),          # 179
    ("尖峭山峰 jagged_peaks", "jagged_peaks"),      # 180
    ("冰封山峰 frozen_peaks", "frozen_peaks"),      # 181
    ("裸岩山峰 stony_peaks", "stony_peaks"),        # 182
    ("深暗之域 deep_dark", "deep_dark"),            # 183
    ("红树林沼泽 mangrove_swamp", "mangrove_swamp"),  # 184
    ("樱花树林 cherry_grove", "cherry_grove"),      # 185
    ("苍白之园 pale_garden", "pale_garden"),        # 186
]

# ---- 解析别名（含 1.18 改名前的旧名 / F3 变体 / 下拉未收录项）----
_BIOME_IDS: dict[str, int] = {
    # 主表
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
    "old_growth_spruce_taiga": 33, "giant_spruce_taiga": 33,
    "giant_spruce_taiga_hills": 33,
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
    "modified_gravelly_mountains": 163,
    "shattered_savanna": 163, "windswept_savanna": 163,
    "shattered_savanna_plateau": 164, "windswept_savanna_plateau": 164,
    "eroded_badlands": 165,
    "bamboo_jungle": 168, "bamboo_jungle_hills": 169,
    "dripstone_caves": 174, "lush_caves": 175,
    "meadow": 177, "grove": 178, "snowy_slopes": 179,
    "jagged_peaks": 180, "frozen_peaks": 181, "stony_peaks": 182,
    "deep_dark": 183, "mangrove_swamp": 184, "cherry_grove": 185,
    "pale_garden": 186,
}

# F3 中文显示名 → 内部键（F3 中文语言下显示中文名）
_F3_CN_TO_KEY = {
    "海洋": "ocean", "平原": "plains", "沙漠": "desert",
    "森林": "forest", "针叶林": "taiga", "沼泽": "swamp",
    "河流": "river", "冻洋": "frozen_ocean", "冻河": "frozen_river",
    "雪原": "snowy_plains", "积雪的平原": "snowy_plains",
    "蘑菇岛": "mushroom_fields", "海滩": "beach",
    "丛林": "jungle", "深海": "deep_ocean", "石岸": "stony_shore",
    "积雪的海滩": "snowy_beach", "雪滩": "snowy_beach",
    "桦木森林": "birch_forest", "黑森林": "dark_forest",
    "积雪的针叶林": "snowy_taiga", "雪林": "snowy_taiga",
    "原始松木针叶林": "old_growth_pine_taiga",
    "原始云杉针叶林": "old_growth_spruce_taiga",
    "疏林山地": "windswept_forest",
    "热带草原": "savanna", "热带高原": "savanna_plateau",
    "恶地": "badlands", "暖水海洋": "warm_ocean",
    "温水海洋": "lukewarm_ocean", "冷水海洋": "cold_ocean",
    "深暖水海洋": "deep_warm_ocean", "深温水海洋": "deep_lukewarm_ocean",
    "深冷水海洋": "deep_cold_ocean", "深寒海洋": "deep_frozen_ocean",
    "竹林": "bamboo_jungle", "溶洞": "dripstone_caves",
    "繁茂洞穴": "lush_caves", "草甸": "meadow", "雪坡林地": "grove",
    "雪坡": "snowy_slopes", "尖峭山峰": "jagged_peaks",
    "冰封山峰": "frozen_peaks", "裸岩山峰": "stony_peaks",
    "深暗之域": "deep_dark", "红树林沼泽": "mangrove_swamp",
    "樱花树林": "cherry_grove", "苍白之园": "pale_garden",
    "向日葵平原": "sunflower_plains", "沙丘": "desert_lakes",
    "多沙的湖": "desert_lakes", "裸露的山地": "gravelly_mountains",
    "碎石山地": "windswept_gravelly_hills",
    "繁花森林": "flower_forest", "冰刺之地": "ice_spikes",
    "原始桦木森林": "old_growth_birch_forest",
    "黑森林高地": "dark_forest_hills",
    "破碎的热带草原": "windswept_savanna",
    "风袭热带草原": "windswept_savanna",
    "风袭砾质丘陵": "windswept_gravelly_hills",
    "被侵蚀的恶地": "eroded_badlands",
}

# 中文标签前缀 → 键（BIOME_CHOICES 标签形如 "海洋 ocean"）
for _label, _key in BIOME_CHOICES:
    _cn = _label.split(" ")[0]
    _F3_CN_TO_KEY.setdefault(_cn, _key)


def _norm(s: str) -> str:
    """名称归一化：小写 + 去分隔符（空格/下划线/连字符）。"""
    return "".join(ch for ch in s.lower() if ch not in " _-")


_KEY_TO_ID: dict[str, int] = {_norm(k): v for k, v in _BIOME_IDS.items()}
_KEY_TO_ID[_norm("mushroom_field_shore")] = 15


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
        key = _F3_CN_TO_KEY[s]
        return _KEY_TO_ID.get(_norm(key))
    # 英文枚举名（任意分隔符风格）
    nid = _KEY_TO_ID.get(_norm(s))
    if nid is not None:
        return nid
    return None


def biome_label(bid: int) -> str:
    """biome id → 显示标签（未收录返回英文枚举名或 "id=N"）。"""
    for lab, key in BIOME_CHOICES:
        if _KEY_TO_ID.get(_norm(key)) == bid:
            return lab
    for key, v in _BIOME_IDS.items():
        if v == bid:
            return key
    return f"id={bid}"
