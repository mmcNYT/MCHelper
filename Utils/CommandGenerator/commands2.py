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


def _positional(values: list, defaults: list) -> list:
    """按位补齐可选参数（Brigadier 参数须从左到右连续）。"""
    last = -1
    for i, v in enumerate(values):
        if v is not None and v != "":
            last = i
    if last < 0:
        return []
    return [(values[i] if values[i] not in (None, "")
             else defaults[i]) for i in range(last + 1)]


def _fmt(v) -> str:
    """数值/布尔/字符串 -> 指令参数文本。"""
    if isinstance(v, bool):
        return str(v).lower()
    return str(v)


# ---------------------------------------------------------------------------
# item（ItemCommands.java）
# ---------------------------------------------------------------------------

def item(params: dict, version_key: str = "1.21.11") -> str:
    """`/item` 四个分支（源码 L63-300+）：

      replace (block|entity) <目标> slot <slot>
              with <item> [count]            L67-99, L175-199
              from (block <pos> <slot> | entity <entity> <slot>)
                    [modifier]              L100-165, L200-260
      modify  (block|entity) <目标> <slot> <modifier>   L~270

    目标形态二选一：block 用 pos；entity 用 targets。
    """
    ns_prefix = params.get("ns_prefix", True)
    branch = params.get("branch") or "replace"
    kind = params.get("kind") or "block"          # block | entity
    pos = (params.get("pos") or "").strip()
    targets = (params.get("targets") or "").strip()
    slot = params.get("slot", 0)

    target = f"block {pos}" if kind == "block" else f"entity {targets}"
    out = f"/item {branch} {target} {slot}"

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
            spos = (params.get("source_pos") or "").strip()
            stargets = (params.get("source_targets") or "").strip()
            sslot = params.get("source_slot", 0)
            src = (f"block {spos}" if skind == "block"
                   else f"entity {stargets}")
            out += f" from {src} {sslot}"
            mod = (params.get("modifier") or "").strip()
            if mod:
                out += f" {mod}"
        return out

    # modify
    mod = (params.get("modifier") or "").strip()
    if mod:
        out += f" {mod}"
    return out


# ---------------------------------------------------------------------------
# loot（LootCommand.java）
# ---------------------------------------------------------------------------

def loot(params: dict, version_key: str = "1.21.11") -> str:
    """`/loot <来源> <目标>`（源码 L39-260）。

    来源（source）：
      fish <loot_table> <pos> [tool]          钓鱼
      loot <loot_table>                       直接指定战利品表
      mine <pos> [tool|mainhand]              挖掘
      kill <entity>                           击杀掉落
    目标（target）：
      give <players> | spawn <pos> | insert <pos> |
      replace <entity|block> <目标> <slot> [count]
    """
    ns_prefix = params.get("ns_prefix", True)
    source = params.get("source") or "loot"
    table = (params.get("loot_table") or "").strip()
    spos = (params.get("source_pos") or "").strip()
    tool = (params.get("tool") or "").strip()
    entity = (params.get("source_entity") or "").strip()

    # ---- 来源段 ----
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

    out = f"/loot {seg}"

    # ---- 目标段 ----
    target = params.get("target") or "give"
    players = (params.get("players") or "").strip()
    tpos = (params.get("target_pos") or "").strip()
    tkind = params.get("target_kind") or "entity"
    ttargets = (params.get("target_targets") or "").strip()
    tslot = params.get("target_slot", 0)
    count = params.get("target_count")

    if target == "give":
        out += f" give {players or '@p'}"
    elif target == "spawn":
        out += f" spawn {tpos or '~ ~ ~'}"
    elif target == "insert":
        out += f" insert {tpos or '~ ~ ~'}"
    else:                                          # replace
        t = (f"block {tpos}" if tkind == "block"
             else f"entity {ttargets or '@s'}")
        out += f" replace {t} {tslot}"
        if count is not None:
            out += f" {int(count)}"
    return out


# ---------------------------------------------------------------------------
# attribute（AttributeCommand.java）
# ---------------------------------------------------------------------------

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
    """
    ns_prefix = params.get("ns_prefix", True)
    targets = (params.get("targets") or "@s").strip()
    attr = params.get("attribute") or "generic.max_health"
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
    """`/playsound <sound> <targets> [pos] [volume] [pitch] [minVolume]`
    （源码 L38-90）。五个可选参数须连续。"""
    ns_prefix = params.get("ns_prefix", True)
    sound = params.get("sound") or "entity.player.levelup"
    targets = (params.get("targets") or "@p").strip()

    vals = _positional(
        [params.get("pos"), params.get("volume"), params.get("pitch"),
         params.get("min_volume")],
        ["~ ~ ~", 1.0, 1.0, 1.0])
    out = f"/playsound {_rid(sound, ns_prefix)} {targets}"
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
