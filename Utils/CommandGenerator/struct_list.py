# -*- coding: utf-8 -*-
"""CommandGenerator：结构 id 与中文名（供 `/locate structure` 与
`/place structure` 使用）。

id 来源：反编译 `BuiltinStructures.java` 的 `createKey("id")`
（34 个，实测提取）。

中文名来源与取舍：
  - 优先复用 `Utils/Public/structure_params.STRUCT_NAMES`（项目内既有
    译名，已对账中文 Minecraft Wiki）；
  - **但官方 id 与项目内部键并不一致**，需显式映射，例如：
        官方 `jungle_pyramid`  <->  项目 `jungle_temple`
        官方 `fortress`        <->  项目 `nether_fortress`
    故本表以**官方 id 为准**，逐一给出中文名，项目键仅作参考。
  - 官方把村庄/废弃传送门/矿井/海底废墟按变体拆成多个 id，
    这里各自标注（如 village_plains = 平原村庄）。
"""

# 官方结构 id -> 中文名（依据中文 Minecraft Wiki 标准译名）
STRUCT_CN = {
    # ---- 主世界 ----
    "ancient_city": "远古城市",
    "bastion_remnant": "堡垒遗迹",
    "buried_treasure": "埋藏的宝藏",
    "desert_pyramid": "沙漠神殿",
    "end_city": "末地城",
    "fortress": "下界要塞",
    "igloo": "雪屋",
    "jungle_pyramid": "丛林神庙",
    "mansion": "林地府邸",
    "mineshaft": "废弃矿井",
    "mineshaft_mesa": "废弃矿井（恶地）",
    "monument": "海底神殿",
    "nether_fossil": "下界化石",
    "ocean_ruin_cold": "海底废墟（寒冷）",
    "ocean_ruin_warm": "海底废墟（温暖）",
    "pillager_outpost": "掠夺者前哨站",
    "ruined_portal": "废弃传送门",
    "ruined_portal_desert": "废弃传送门（沙漠）",
    "ruined_portal_jungle": "废弃传送门（丛林）",
    "ruined_portal_mountain": "废弃传送门（山地）",
    "ruined_portal_nether": "废弃传送门（下界）",
    "ruined_portal_ocean": "废弃传送门（海洋）",
    "ruined_portal_swamp": "废弃传送门（沼泽）",
    "shipwreck": "沉船",
    "shipwreck_beached": "搁浅的沉船",
    "stronghold": "要塞",
    "swamp_hut": "女巫小屋",
    "trail_ruins": "古迹废墟",
    "trial_chambers": "试炼密室",
    "village_desert": "沙漠村庄",
    "village_plains": "平原村庄",
    "village_savanna": "热带草原村庄",
    "village_snowy": "雪原村庄",
    "village_taiga": "针叶林村庄",
}

STRUCT_IDS = sorted(STRUCT_CN)


def struct_label(sid: str) -> str:
    """UI 显示：`中文名（id）`。"""
    cn = STRUCT_CN.get(sid)
    return f"{cn}（{sid}）" if cn else sid


# ---------------------------------------------------------------------------
# 生物群系 / 状态效果 / 实体：统一从 resource_lists 取
# ---------------------------------------------------------------------------

def _label(cn_map: dict, names: dict, rid: str) -> str:
    cn = cn_map.get(rid)
    return f"{cn}（{rid}）" if cn and cn != names.get(rid) else rid


def biome_label(bid: str) -> str:
    from Utils.CommandGenerator import resource_lists as RL
    return _label(RL.BIOME_CN, RL.BIOME_NAMES, bid)


def effect_label(eid: str) -> str:
    from Utils.CommandGenerator import resource_lists as RL
    return _label(RL.EFFECT_CN, RL.EFFECT_NAMES, eid)


def entity_label(eid: str) -> str:
    from Utils.CommandGenerator import resource_lists as RL
    return _label(RL.ENTITY_CN, RL.ENTITY_NAMES, eid)
