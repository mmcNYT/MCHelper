# -*- coding: utf-8 -*-
"""MapPreviewer 结构图标：结构键 + 群系 id → Wiki EnvSprite PNG 图标。

图标来源：英文 Minecraft Wiki 的 EnvSprite 环境精灵（16x16 PNG），2026-09
经浏览器通道批量下载转存。图标统一放项目 assets/MapPreviewer/（而非打进
资源文件）便于用户按喜好替换图片（同 SeedReverser 模式）。

Wiki 原始 URL 模式：https://minecraft.wiki/images/EnvSprite_<name>.png
- Wiki 无独立"平原村庄"文件名：plains-village 是 new-village 的重定向；
- 村庄变体按生成群系区分外观（对应 structure_map._check_village 的
  五变体判定）；村庄在草甸(MEADOW)上生成时判定层已归入平原，
  这里同样映射到平原村庄图标。
"""

import os

# ---------------------------------------------------------------------------
# 图标目录：assets/MapPreviewer/（图标统一放项目 assets/ 按工具分子目录）
# ---------------------------------------------------------------------------
ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(  # Utils/MapPreviewer/ → 项目根
    os.path.dirname(os.path.abspath(__file__)))), "assets", "MapPreviewer")

# ---------------------------------------------------------------------------
# 群系 id 常量（cubiomes biomes.h，与 structure_map.py 同源；
# 此处仅映射所需几项，避免为取常量而引入整套结构判定模块）
# ---------------------------------------------------------------------------
PLAINS = 1
DESERT = 2
TAIGA = 5
SNOWY_PLAINS = 12
SNOWY_TAIGA = 30
SAVANNA = 35
MEADOW = 177

# ---------------------------------------------------------------------------
# 映射表
# ---------------------------------------------------------------------------

# 结构键 → EnvSprite 名（Wiki 上丛林神殿/沙漠神殿的精灵名带 pyramid）
_STRUCT_SPRITE = {
    "village":          "new-village",
    "pillager_outpost": "pillager-outpost",
    "desert_pyramid":   "desert-pyramid",
    "jungle_temple":    "jungle-pyramid",
    "swamp_hut":        "swamp-hut",
    "igloo":            "igloo",
    "shipwreck":        "shipwreck",
    "ocean_ruin":       "ocean-ruin",
    "monument":         "monument",
    "mansion":          "mansion",
    "ancient_city":     "ancient-city",
    "trail_ruins":      "trail-ruins",
    "trial_chambers":   "trial-chambers",
    "ruined_portal":    "ruined-portal",
    "stronghold":       "stronghold",
    "buried_treasure":  "buried-treasure",
    "mineshaft":        "mineshaft",
    "desert_well":      "desert-well",
    # 下界/末地扩展（缺图标时自动回退自绘红圈，不挡功能）
    "nether_fortress":  "fortress",
    "bastion_remnant":  "bastion-remnant",
    "end_city":         "end-city",
}

# 村庄变体：群系 id → EnvSprite 名（与 _check_village 五变体一致；
# MEADOW 归平原、SNOWY_TAIGA 外观同为雪原，均作兜底补充）
_VILLAGE_BIOME_SPRITE = {
    PLAINS:        "new-village",
    MEADOW:        "new-village",
    DESERT:        "desert-village",
    SAVANNA:       "savanna-village",
    TAIGA:         "taiga-village",
    SNOWY_PLAINS:  "snowy-village",
    SNOWY_TAIGA:   "snowy-village",
}

# 村庄悬停文案用群系中文短名（"群系名 + 村庄"，如"平原村庄"）
_VILLAGE_BIOME_CN = {
    PLAINS:        "平原",
    MEADOW:        "平原",
    DESERT:        "沙漠",
    SAVANNA:       "热带草原",
    TAIGA:         "针叶林",
    SNOWY_PLAINS:  "雪原",
    SNOWY_TAIGA:   "雪原",
}


def sprite_key(struct_key: str, biome: int | None = None) -> str | None:
    """结构键 + 群系 id → EnvSprite 名（不含前缀/后缀）。

    村庄按群系取变体精灵；群系未知或不在五变体表内时退回默认村庄图。
    其他结构或未知键返回 None。
    """
    if struct_key == "village":
        if biome is not None:
            sp = _VILLAGE_BIOME_SPRITE.get(int(biome))
            if sp:
                return sp
        return "new-village"
    return _STRUCT_SPRITE.get(struct_key)


def icon_path(struct_key: str, biome: int | None = None) -> str | None:
    """结构键 + 群系 id → 图标 PNG 绝对路径。

    键未知、路径非法或文件缺失（用户删除/替换中）时返回 None，
    调用方应回退到自绘标记，不要假设返回值恒存在。
    """
    sp = sprite_key(struct_key, biome)
    if not sp or os.path.basename(sp) != sp:
        return None
    p = os.path.join(ICON_DIR, "EnvSprite_" + sp + ".png")
    return p if os.path.isfile(p) else None


def display_name(name_cn: str, struct_key: str,
                 biome: int | None = None) -> str:
    """结构悬停/标签显示名：村庄 → "群系名+村庄"，其余结构原样返回。

    name_cn 传 STRUCT_NAMES 里的中文名（如"村庄"）。
    """
    if struct_key == "village" and biome is not None:
        cn = _VILLAGE_BIOME_CN.get(int(biome))
        if cn:
            return cn + "村庄"
    return name_cn
