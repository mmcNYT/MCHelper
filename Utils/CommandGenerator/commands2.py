# -*- coding: utf-8 -*-
"""第 1 批剩余 7 条指令的序列化（纯函数）。

覆盖：item / loot / attribute / damage / playsound / particle /
spawn_armor_trims

语法均逐行核对 1.21.11 反编译源码（行号依据见各函数 docstring，
完整骨架见 .temp/dump7b.out 与 .temp/detail7b.out）。
"""
from __future__ import annotations

from . import snbt


def _rid(name: str, ns_prefix: bool = True) -> str:
    return snbt.res_id(name, ns_prefix)


from .serialize_util import fmt as _fmt, positional as _positional  # noqa: E402,E501,F401


# ---------------------------------------------------------------------------
# item（ItemCommands.java）
# ---------------------------------------------------------------------------

def _slot(s) -> str:
    """SlotArgument 兼容：纯数字补 container. 前缀（26.2 实测：裸 `0`
    报 Unknown slot '0'），字符串（如 weapon.mainhand）原样保留。"""
    if s is None or str(s).strip() == "":
        return "container.0"
    s = str(s).strip()
    if s.isdigit():
        return f"container.{int(s)}"
    return s


# 26.2 实测：item 的 modifier 参数必填，且 vanilla 无 item_modifier
# 数据文件（ResourceOrIdArgument.lootModifier 只认数据包 id 或内联
# SNBT 函数），缺省时给内联 SNBT 兑底（服务器实测解析通过）。
DEFAULT_ITEM_MODIFIER = '{"function":"minecraft:enchant_with_levels","levels":1}'


def item(params: dict, version_key: str = "1.21.11") -> str:
    """`/item` 四个分支（源码 L63-300+）：

      replace (block|entity) <目标> slot <slot>
              with <item> [count]            L67-99, L175-199
              from (block <pos> <slot> | entity <entity> <slot>)
                    <modifier>              L100-165, L200-260
      modify  (block|entity) <目标> <slot> <modifier>   L~270

    目标形态二选一：block 用 pos；entity 用 targets。
    """
    ns_prefix = params.get("ns_prefix", True)
    branch = params.get("branch") or "replace"
    kind = params.get("kind") or "block"          # block | entity
    # 必填目标空时兜底（UI 层由必填校验拦截）
    pos = (params.get("pos") or "").strip() or "~ ~ ~"
    targets = (params.get("targets") or "").strip() or "@s"
    slot = params.get("slot", 0)

    target = f"block {pos}" if kind == "block" else f"entity {targets}"
    out = f"/item {branch} {target} {_slot(slot)}"

    if branch == "replace":
        sub = params.get("sub") or "with"
        if sub == "with":
            iid = params.get("item") or "stone"
            out += f" with {_rid(iid, ns_prefix)}"
            cnt = params.get("count")
            if cnt is not None and int(cnt) != 1:
                out += f" {int(cnt)}"
        else:                                     # from
            skind = params.get("source_kind") or "block"
            spos = (params.get("source_pos") or "").strip() or "~ ~ ~"
            stargets = (params.get("source_targets") or "").strip() or "@s"
            sslot = params.get("source_slot", 0)
            src = (f"block {spos}" if skind == "block"
                   else f"entity {stargets}")
            out += f" from {src} {_slot(sslot)}"
            mod = (params.get("modifier") or "").strip()
            # 26.2 实测 modifier 必填：留空给内联 SNBT 兑底
            out += f" {mod or DEFAULT_ITEM_MODIFIER}"
        return out

    # modify（26.2 实测 modifier 必填，缺省报 Unknown）
    mod = (params.get("modifier") or "").strip()
    out += f" {mod or DEFAULT_ITEM_MODIFIER}"
    return out

    # modify（26.2 实测 modifier 必填，缺省报 Unknown）
    mod = (params.get("modifier") or "").strip()
    out += f" {mod or DEFAULT_ITEM_MODIFIER}"
    return out


# ---------------------------------------------------------------------------
# loot（LootCommand.java）
# ---------------------------------------------------------------------------

def loot(params: dict, version_key: str = "1.21.11") -> str:
    """`/loot <目标> <来源>`（源码 L39-260；addTargets 把目标树
    放在前面、来源作尾参 —— 26.2 实测反序会报 Incorrect argument）。

    目标（target，在前）：
      give <players> | spawn <pos> | insert <pos> |
      replace <entity|block> <目标> <slot> [count]
    来源（source，在后）：
      fish <loot_table> <pos> [tool]          钓鱼
      loot <loot_table>                       直接指定战利品表
      mine <pos> [tool|mainhand]              挖掘
      kill <entity>                           击杀掉落
    """
    ns_prefix = params.get("ns_prefix", True)
    source = params.get("source") or "loot"
    table = (params.get("loot_table") or "").strip()
    spos = (params.get("source_pos") or "").strip()
    tool = (params.get("tool") or "").strip()
    entity = (params.get("source_entity") or "").strip()

    # ---- 目标段（在前）----
    target = params.get("target") or "give"
    players = (params.get("players") or "").strip()
    tpos = (params.get("target_pos") or "").strip()
    tkind = params.get("target_kind") or "entity"
    ttargets = (params.get("target_targets") or "").strip()
    tslot = params.get("target_slot", 0)
    count = params.get("target_count")

    if target == "give":
        out = f"/loot give {players or '@p'}"
    elif target == "spawn":
        out = f"/loot spawn {tpos or '~ ~ ~'}"
    elif target == "insert":
        out = f"/loot insert {tpos or '~ ~ ~'}"
    else:                                          # replace
        t = (f"block {tpos}" if tkind == "block"
             else f"entity {ttargets or '@s'}")
        out = f"/loot replace {t} {_slot(tslot)}"
        if count is not None:
            out += f" {int(count)}"

    # ---- 来源段（尾参）----
    if source == "fish":
        seg = f"fish {_rid(table or 'gameplay/fishing', ns_prefix)} " \
              f"{spos or '~ ~ ~'}"
        if tool:
            seg += f" {_rid(tool, ns_prefix)}"
    elif source == "mine":
        seg = f"mine {spos or '~ ~ ~'}"
        if tool == "mainhand" or tool:
            seg += f" {tool if tool == 'mainhand' else _rid(tool, ns_prefix)}"
    elif source == "kill":
        seg = f"kill {entity or '@e[limit=1]'}"
    else:                                          # loot
        seg = f"loot {_rid(table or 'chests/simple_dungeon', ns_prefix)}"
    return f"{out} {seg}"


# ---------------------------------------------------------------------------
# attribute（AttributeCommand.java）
# ---------------------------------------------------------------------------

# 1.21 属性类别前缀映射（1.21 服务器 RCON 批量实测，35 项产品清单
# × {裸, generic., player.} 全测，见 .temp/probe_v121_attrs_out.txt；
# zombie.spawn_reinforcements 另测见 probe_v121_camel_out.txt）。
#   - 1.21（data version 3953）已 generic 化主体属性（1.20.5 起），
#     但 player 系交互/挖掘属性与 zombie.spawn_reinforcements
#     保持 1.21.2 前的旧命名；26.x 起注册表去前缀化。
#   - 不在表内的属性兜底 generic. 前缀（1.21 大多数属性属 generic 类）。
_ATTR_121_PREFIX = {
    # generic. 系（23 个，实测有值或 EXISTS）
    "armor": "generic.", "armor_toughness": "generic.",
    "attack_damage": "generic.", "attack_knockback": "generic.",
    "attack_speed": "generic.", "burning_time": "generic.",
    "explosion_knockback_resistance": "generic.",
    "fall_damage_multiplier": "generic.", "flying_speed": "generic.",
    "follow_range": "generic.", "gravity": "generic.",
    "jump_strength": "generic.", "knockback_resistance": "generic.",
    "luck": "generic.", "max_absorption": "generic.",
    "max_health": "generic.", "movement_efficiency": "generic.",
    "movement_speed": "generic.", "oxygen_bonus": "generic.",
    "safe_fall_distance": "generic.", "scale": "generic.",
    "step_height": "generic.",
    "water_movement_efficiency": "generic.",
    # player. 系（7 个，实测 EXISTS_NO_VALUE = 存在但盔甲架没有）
    "block_break_speed": "player.",
    "block_interaction_range": "player.",
    "entity_interaction_range": "player.",
    "mining_efficiency": "player.",
    "sneaking_speed": "player.",
    "submerged_mining_speed": "player.",
    "sweeping_damage_ratio": "player.",
    # zombie 系（1.21.2 前旧命名，实测 parse 通过）
    "spawn_reinforcements": "zombie.",
}

# 1.21 不存在的属性（26.x 新增，三种前缀形式实测均 Can't find）
_ATTR_121_MISSING = {"camera_distance", "tempt_range",
                     "waypoint_transmit_range", "waypoint_receive_range"}


def attr_id_121(name: str) -> "str | None":
    """属性名（裸或带 minecraft:）-> 1.21 全 id；1.21 不存在返回 None。

    供 attribute 指令与 give 的 attribute_modifiers 组件 type 字段
    共用（组件内同样需要类别前缀，实测 Bare type 报 Unknown
    registry key）。
    """
    base = str(name).strip().removeprefix("minecraft:")
    if base in _ATTR_121_MISSING:
        return None
    return "minecraft:" + _ATTR_121_PREFIX.get(base, "generic.") + base


def attribute(params: dict, version_key: str = "1.21.11") -> str:
    """`/attribute <target> <attribute> ...`（源码 L60-350）。

    分支：
      get [scale]                        scale 可选（默认 1.0）
      base get | base set <value>
      get [scale]                        （顶层）
      modifier add <id> <value> (add_value|add_multiplied_base|
                                 add_multiplied_total)
      modifier remove <id>
      modifier value get <id> [scale]
      reset

    1.21：属性 id 需类别前缀（generic./player./zombie.，RCON 实测
    裸 id 报 Can't find element）；26.x 独有属性生成提示文本。
    """
    ns_prefix = params.get("ns_prefix", True)
    targets = (params.get("targets") or "@s").strip()
    attr = params.get("attribute") or "armor"
    if version_key == "1.21":
        full = attr_id_121(attr)
        if full is None:
            base = str(attr).strip().removeprefix("minecraft:")
            return f"（1.21 无 {base} 属性）"
        out = f"/attribute {targets} {full if ns_prefix else full.removeprefix('minecraft:')}"
    else:
        # 26.2/1.21.11 注册表无 generic./player. 前缀（实测旧裸 id 合法）
        out = f"/attribute {targets} {_rid(attr, ns_prefix)}"

    branch = params.get("branch") or "get"
    if branch == "get":
        scale = params.get("scale")
        if scale is not None and float(scale) != 1.0:
            out += f" get {float(scale):g}"
        else:
            out += " get"
    elif branch == "base":
        sub = params.get("base_sub") or "get"
        if sub == "set":
            out += f" base set {params.get('value', 0.0):g}"
        else:
            out += " base get"
    elif branch == "reset":
        out += " reset"
    elif branch == "modifier":
        sub = params.get("modifier_sub") or "add"
        mid = (params.get("id") or "").strip()
        if sub == "add":
            val = params.get("value", 0.0)
            op = params.get("operation") or "add_value"
            out += f" modifier add {mid} {val:g} {op}"
        elif sub == "remove":
            out += f" modifier remove {mid}"
        else:                                     # value get
            scale = params.get("scale")
            if scale is not None and float(scale) != 1.0:
                out += f" modifier value get {mid} {float(scale):g}"
            else:
                out += f" modifier value get {mid}"
    return out


# ---------------------------------------------------------------------------
# damage（DamageCommand.java）
# ---------------------------------------------------------------------------

def damage(params: dict, version_key: str = "1.21.11") -> str:
    """`/damage <target> <amount> [<damageType>] [at <pos>|by <entity>
    [from <cause>]]`（源码 L40-110）。

    target 是**单数** entity（EntityArgument.entity()）。
    by/from 可组合：`by <entity> from <cause>`。
    """
    ns_prefix = params.get("ns_prefix", True)
    target = (params.get("target") or "@s").strip()
    amount = params.get("amount", 1.0)
    dtype = params.get("damage_type") or "generic"
    out = f"/damage {target} {amount:g} {_rid(dtype, ns_prefix)}"

    tag = params.get("tag")
    loc = (params.get("location") or "").strip()
    by = (params.get("by") or "").strip()
    cause = (params.get("cause") or "").strip()

    if tag == "at" and loc:
        out += f" at {loc}"
    elif tag == "by" and by:
        out += f" by {by}"
        if cause:
            out += f" from {cause}"
    return out


# ---------------------------------------------------------------------------
# playsound（PlaySoundCommand.java）
# ---------------------------------------------------------------------------

def playsound(params: dict, version_key: str = "1.21.11") -> str:
    """`/playsound <sound> <source> <targets> [pos] [volume] [pitch]
    [minVolume]`（源码 L38-90）。source 是必填 literal（26.2 实测
    缺它报 Incorrect argument），五个可选参数须连续。"""
    ns_prefix = params.get("ns_prefix", True)
    sound = params.get("sound") or "entity.player.levelup"
    src = params.get("source") or "master"
    targets = (params.get("targets") or "@p").strip()

    vals = _positional(
        [params.get("pos"), params.get("volume"), params.get("pitch"),
         params.get("min_volume")],
        ["~ ~ ~", 1.0, 1.0, 1.0])
    out = f"/playsound {_rid(sound, ns_prefix)} {src} {targets}"
    for v in vals:
        out += f" {_fmt(v)}"
    return out


# ---------------------------------------------------------------------------
# particle（ParticleCommand.java）
# ---------------------------------------------------------------------------

def particle(params: dict, version_key: str = "1.21.11") -> str:
    """`/particle <name> [pos] [delta] [speed] [count] [force|normal]
    [viewers]`（源码 L38-110）。

    delta 是三维向量（如 `0.1 0.1 0.1`）；count=0 时 delta 表示
    运动方向、speed 表示速度倍率。
    """
    ns_prefix = params.get("ns_prefix", True)
    name = params.get("name") or "heart"
    out = f"/particle {_rid(name, ns_prefix)}"

    vals = _positional(
        [params.get("pos"), params.get("delta"), params.get("speed"),
         params.get("count"), params.get("mode"),
         params.get("viewers")],
        ["~ ~ ~", "0 0 0", 0.1, 10, "normal", "@a"])
    for v in vals:
        if v in (None, ""):
            break
        out += f" {_fmt(v)}"
    return out


# ---------------------------------------------------------------------------
# spawn_armor_trims（SpawnArmorTrimsCommand.java）
# ---------------------------------------------------------------------------

def spawn_armor_trims(params: dict, version_key: str = "1.21.11") -> str:
    """`/spawn_armor_trims <pattern>`（源码 L30-60）。

    pattern 是 ResourceKeyArgument（TrimPattern 注册表）。
    """
    ns_prefix = params.get("ns_prefix", True)
    pat = params.get("pattern") or "sentry"
    return f"/spawn_armor_trims {_rid(pat, ns_prefix)}"


SERIALIZERS = {
    "item": item,
    "loot": loot,
    "attribute": attribute,
    "damage": damage,
    "playsound": playsound,
    "particle": particle,
    "spawn_armor_trims": spawn_armor_trims,
}
