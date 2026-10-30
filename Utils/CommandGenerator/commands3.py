# -*- coding: utf-8 -*-
"""剩余 26 条指令的序列化（纯函数，无 Qt）。

语法逐行核对 MC 反编译源码：26.2 全量（.temp/mc262_decompile/，
骨架见 .temp/dump26.out）+ 1.21.11 零散类（.temp/mc1211_classes/）。
按复杂度分三个 mixin 区块：
  简单（单分支/少参数）、中等多分支、复合两段式。

必填参数的空值在 UI 层由 required 校验拦截；本层兜底策略仅保
直接调用 API 时不产出非法指令。
"""
from __future__ import annotations

from . import snbt


def _rid(name, ns_prefix=True):
    return snbt.res_id(name, ns_prefix)


from .serialize_util import fmt as _fmt, positional as _positional  # noqa: E402


# ---------------------------------------------------------------------------
# 简单组（单分支 / 参数少）
# ---------------------------------------------------------------------------

def chase(p, v="1.21.11"):
    """`/chase (lead|follow) <host> <port> [bind]` / stop"""
    br = p.get("branch") or "stop"
    if br == "stop":
        return "/chase stop"
    host = p.get("host") or "localhost"
    port = p.get("port", 25565)
    out = f"/chase {br} {host} {int(port)}"
    if br == "lead" and p.get("bind_address"):
        out += f" {p['bind_address']}"
    return out


def debugconfig(p, v="1.21.11"):
    """`/debugconfig config <player>` / unconfig <uuid> /
    dialog <uuid> <dialog>`（26.2 官方三分支，见
    DebugConfigCommand.java L29-60）"""
    br = p.get("branch") or "config"
    # unconfig/dialog 的 target 是 UuidArgument（空时兜底全零 UUID）
    if br in ("unconfig", "dialog"):
        uid = (p.get("target") or "").strip() or \
            "00000000-0000-0000-0000-000000000000"
        if br == "unconfig":
            return f"/debugconfig unconfig {uid}"
        dlg = (p.get("dialog") or "").strip() or "minecraft:quick_actions"
        return f"/debugconfig dialog {uid} {_rid(dlg)}"
    # config：官方无 dialog 参数（单玩家由 spec/必填校验保证）
    tgt = (p.get("target") or "").strip() or "@s"
    return f"/debugconfig config {tgt}"


def dialog(p, v="1.21.11"):
    """`/dialog show <targets> <dialog>` / clear <targets>`
    （DialogCommand.java L20-43，show/clear 的 targets 均必填）

    1.21：指令不存在（26.x 新增），生成提示文本。
    """
    if v == "1.21":
        return "（1.21 无 dialog 指令）"
    br = p.get("branch") or "show"
    tgt = (p.get("targets") or "").strip() or "@s"
    if br == "clear":
        return f"/dialog clear {tgt}"
    dlg = (p.get("dialog") or "").strip() or "minecraft:quick_actions"
    return f"/dialog show {tgt} {_rid(dlg)}"


# 1.21 gamerule 规则名映射。权威依据：26.2 反编译
# net/minecraft/util/datafix/fixes/GameRuleRegistryFix.java
#（挂载 schema v4658，介于 3953/4671 之间）+ 1.21（3953）服务器
# RCON 实测（probe_v121_rules2_out.txt / probe_v121_camel_out.txt）：
#   - 官方改名 19 条（1.21 侧目标名已实测存在）；
#   - elytra_movement_check / raids 为官方 convertBooleanInverted
#     反转对，生成时布尔值取反（否则语义相反）；
#   - fire_spread_radius_around_player 官方为 int 合成规则
#     （doFireTick × allowFireTicksAwayFromPlayer：-1 全域/0 关/
#     128 玩家半径内），1.21 无 allowFireTicksAwayFromPlayer，
#     降级为 doFireTick 布尔（0→false，非 0→true）；
#   - 驼峰同形（keep_inventory→keepInventory 等）由 _camel_rule
#     兜底；
#   - 1.21（3953）无对应的 10 条 → 提示文本（其中 pvp/
#     spawn_monsters/tnt_explodes 为 1.21.2+~1.21.10 间新增、
#     locator_bar 1.21.5+、command_blocks_work/spawner_blocks_work
#     1.21.2+，均以 3953 实测为准）。
_RULE_121_RENAME = {
    "advance_time": "doDaylightCycle",
    "advance_weather": "doWeatherCycle",
    "show_advancement_messages": "announceAdvancements",
    "spawn_mobs": "doMobSpawning",
    "spawn_patrols": "doPatrolSpawning",
    "spawn_phantoms": "doInsomnia",
    "spawn_wandering_traders": "doTraderSpawning",
    "spawn_wardens": "doWardenSpawning",
    "spread_vines": "doVinesSpread",
    "entity_drops": "doEntityDrops",
    "block_drops": "doTileDrops",
    "mob_drops": "doMobLoot",
    "limited_crafting": "doLimitedCrafting",
    "immediate_respawn": "doImmediateRespawn",
    "natural_health_regeneration": "naturalRegeneration",
    "max_snow_accumulation_height": "snowAccumulationHeight",
    "max_command_sequence_length": "maxCommandChainLength",
    "respawn_radius": "spawnRadius",
    "max_block_modifications": "commandModificationBlockLimit",
    "elytra_movement_check": "disableElytraMovementCheck",  # 值反转
    "raids": "disableRaids",  # 值反转
}

# 官方 convertBooleanInverted 反转对（生成时布尔值取反）
_RULE_121_INVERT = {"elytra_movement_check", "raids"}

# 1.21 无对应规则（3953 实测不存在，见 _RULE_121_RENAME 注释）
_RULE_121_MISSING = {
    "allow_entering_nether_using_portals", "command_blocks_work",
    "locator_bar", "max_command_forks", "max_minecart_speed",
    "player_movement_check", "pvp", "spawner_blocks_work",
    "spawn_monsters", "tnt_explodes",
}


def _camel_rule(name: str) -> str:
    """snake_case -> camelCase（首词保持小写）。"""
    parts = name.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def _to_bool(v):
    """宽松布尔解析（bool 直通；true/1/yes → True，其余 False）。"""
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")


def gamerule(p, v="1.21.11"):
    """`/gamerule <rule> [value]`（value 类型随规则变化）

    1.21：规则名为驼峰/旧命名（26.x 为蛇形）。改名与无对应见
    _RULE_121_RENAME / _RULE_121_MISSING（官方 GameRuleRegistryFix
    对照 + RCON 实测）；elytra_movement_check/raids 为官方反转对
    （布尔取反）；fire_spread_radius_around_player 为 int 合成
    规则，降级为 doFireTick 布尔（0→false，非 0→true）。
    """
    rule = p.get("rule") or "keep_inventory"
    val = p.get("value")
    if v == "1.21":
        base = str(rule).strip().removeprefix("minecraft:")
        if base in _RULE_121_MISSING:
            return f"（1.21 无 {base} 规则）"
        if base == "fire_spread_radius_around_player":
            rule = "doFireTick"
            if val is not None and val != "":
                try:
                    val = int(val) != 0
                except (TypeError, ValueError):
                    val = _to_bool(val)
        else:
            rule = _RULE_121_RENAME.get(base) or _camel_rule(base)
            if base in _RULE_121_INVERT and val is not None and val != "":
                val = not _to_bool(val)
    out = f"/gamerule {rule}"
    if val is not None and val != "":
        out += f" {_fmt(val)}"
    return out


def raid(p, v="1.21.11"):
    """`/raid` 各分支"""
    br = p.get("branch") or "check"
    out = f"/raid {br}"
    if br == "start":
        omen = p.get("omenlvl")
        if omen is not None:
            out += f" {int(omen)}"
    elif br == "sound":
        out += f" {p.get('type') or '@s'}"
        lv = p.get("level")
        if lv is not None:
            out += f" {int(lv)}"
    return out


def random(p, v="1.21.11"):
    """`/random (roll|value) <range>` / `reset <sequence|*> [seed] [...]`
    （26.2 实测：range 前必须有 roll/value literal；reset 后必须有
    序列或 *，顺序为 sequence → seed → 含世界种子 → 含序列 id）"""
    if p.get("branch") == "reset":
        # sequence 必填，兜底 *（全部序列）
        seq = (str(p.get("sequence") or "").strip() or "*")
        out = f"/random reset {seq}"
        if seq != "*":
            out = f"/random reset {_rid(seq)}"
        vals = _positional(
            [p.get("seed"), p.get("include_world_seed"),
             p.get("include_sequence_id")],
            [None, None, None])
        if vals:
            # seed 之后的布尔须连续可选
            out += f" {int(vals[0])}"
            if len(vals) > 1:
                out += f" {str(bool(vals[1])).lower()}"
                if len(vals) > 2:
                    out += f" {str(bool(vals[2])).lower()}"
        return out
    rng = (p.get("range") or "").strip() or "1..6"
    return f"/random roll {rng}"


def schedule(p, v="1.21.11"):
    """`/schedule function <f> <time> [append|replace]` / clear <f>"""
    br = p.get("branch") or "function"
    fn = (p.get("function") or "").strip() or "custom:tick"
    ns_prefix = p.get("ns_prefix", True)
    if br == "clear":
        return f"/schedule clear {_rid(fn, ns_prefix)}".rstrip()
    t = p.get("time") or "1d"
    out = f"/schedule function {_rid(fn, ns_prefix)} {t}"
    mode = p.get("mode")
    if mode:
        out += f" {mode}"
    return out


def tick(p, v="1.21.11"):
    """`/tick (query|rate <值>|step [时长]|step stop|sprint <时长>|
    sprint stop|freeze|unfreeze)`（TickCommand.java L23-56）。
    26.2 实测：无顶层 stop literal；stop 挂在 step/sprint 之下。
    rate 值必填（兜底 20），sprint 时长必填（兜底 100）。"""
    br = p.get("branch") or "query"
    if br in ("rate", "step", "sprint"):
        val = p.get("rate") if p.get("rate") is not None else p.get("time")
        if val is None:
            if br == "rate":
                return "/tick rate 20"
            if br == "sprint":
                return "/tick sprint 100"
            return "/tick step"          # 裸 step 合法 = 步进 1 刻
        out = f"/tick {br} {val:g}" if isinstance(val, float) \
            else f"/tick {br} {val}"
        return out
    if br == "stop":
        return "/tick step stop"
    if br == "sprint_stop":
        return "/tick sprint stop"
    return f"/tick {br}"


def forceload(p, v="1.21.11"):
    """`/forceload (add|remove) <from> [<to>] | remove all |
    query [<pos>]`（ForceLoadCommand.java L38-95）。26.2 实测：
    无顶层 all literal（all 挂在 remove 之下）；add/remove 的
    from 必填（兜底 0 0，区块坐标）。"""
    br = p.get("branch") or "query"
    frm = (p.get("from") or "").strip()
    to = (p.get("to") or "").strip()
    if br == "all":
        return "/forceload remove all"
    if br in ("add", "remove"):
        out = f"/forceload {br} {frm or '0 0'}"
        if to:
            out += f" {to}"
        return out
    out = f"/forceload query"
    if frm:
        out += f" {frm}"
    return out


def waypoint(p, v="1.21.11"):
    """`/waypoint list` / `modify <wp> color <named>|color hex <hex>|
    color reset|style set <id>|style reset`
    （WaypointCommand.java L35-90：hex/reset 是 color 下的 literal，
    style 的 set/reset 同理）

    1.21：指令不存在（1.21.5+ 新增），生成提示文本。
    """
    if v == "1.21":
        return "（1.21 无 waypoint 指令）"
    br = p.get("branch") or "list"
    if br != "modify":
        return f"/waypoint {br}"
    wp = (p.get("waypoint") or "").strip() or "@e[limit=1]"
    sub = p.get("sub") or "color"
    out = f"/waypoint modify {wp}"
    if sub == "color":
        c = p.get("color")
        # 命名色需带 color literal（26.2 实测：裸色值/裸 reset 不合法）
        out += " color reset" if c in (None, "") else f" color {_fmt(c)}"
    elif sub == "hex":
        hx = (str(p.get("hex_color") or "")).strip().lstrip("#") or "FF0000"
        # HexColorArgument 只吃 3/6 位十六进制裸串（# 非法未引号字符）
        out += f" color hex {hx}"
    elif sub == "color_reset":
        out += " color reset"
    elif sub == "style_set":
        sty = (p.get("style") or "").strip() or "minecraft:default"
        out += f" style set {_rid(sty)}"
    else:  # style_reset
        out += " style reset"
    return out


# ---------------------------------------------------------------------------
# 中等多分支
# ---------------------------------------------------------------------------

def experience(p, v="1.21.11"):
    """`/experience (add|set) <target> <amount> [points|levels]` /
    query <target> (points|levels)"""
    br = p.get("branch") or "add"
    tgt = p.get("target") or "@s"
    if br == "query":
        unit = p.get("unit") or "points"
        return f"/experience query {tgt} {unit}"
    amt = p.get("amount", 0)
    unit = p.get("unit") or "points"
    return f"/experience {br} {tgt} {int(amt)} {unit}"


def title(p, v="1.21.11"):
    """`/title <targets> (clear|reset|subtitle <json>|actionbar <json>|
    title <json>|times <fadeIn> <stay> <fadeOut>)`"""
    ns_prefix = p.get("ns_prefix", True)
    tgt = p.get("targets") or "@s"
    br = p.get("branch") or "title"
    if br in ("clear", "reset"):
        return f"/title {tgt} {br}"
    if br == "times":
        vals = _positional(
            [p.get("fade_in"), p.get("stay"), p.get("fade_out")],
            [10, 70, 20])
        # times 后三个时长必填，全空时兜底官方默认 (10, 70, 20)
        if not vals:
            vals = [10, 70, 20]
        out = f"/title {tgt} times"
        for x in vals:
            out += f" {int(x)}"
        return out
    txt = p.get("text")
    # text_component("") 输出合法空组件 `""`，不再产生尾随空格
    body = snbt.text_component(str(txt if txt is not None else ""))
    return f"/title {tgt} {br} {body}"


def spreadplayers(p, v="1.21.11"):
    """`/spreadplayers <center> <dist> <maxRange> <respectTeams>
    <targets>` / `... under <maxHeight>`"""
    ns = p.get("ns_prefix", True)
    cx = p.get("center_x", 0.0)
    cz = p.get("center_z", 0.0)
    out = (f"/spreadplayers {cx:g} {cz:g} "
           f"{p.get('spread_distance', 16.0):g} "
           f"{p.get('max_range', 128.0):g} "
           f"{str(bool(p.get('respect_teams', False))).lower()} "
           f"{p.get('targets') or '@e'}")
    mh = p.get("max_height")
    if mh is not None:
        out += f" under {int(mh)}"
    return out


def teleport(p, v="1.21.11"):
    """`/tp <targets> <location|destination>` [+ rotation/facing]

    26.2 服务器实测：rotation/facing 子节点只挂在
    `<targets> <location>` 树下；裸位置形式（不带 targets）没有这
    两个子节点，因此带 rotation/facing 时必须补 targets。"""
    ns_prefix = p.get("ns_prefix", True)
    tgt = (p.get("targets") or "").strip()
    mode = p.get("mode") or "location"
    fmode = p.get("facing_mode")
    rot = (p.get("rotation") or "").strip()
    # facing 仅存在于 location 树；destination 模式不接 facing
    needs_targets = mode == "location" and (bool(fmode) or bool(rot))
    out = "/tp"
    if tgt:
        out += f" {tgt}"
    elif needs_targets:
        out += " @s"
    if mode == "location":
        out += f" {p.get('location') or '~ ~ ~'}"
        if not fmode and rot:
            out += f" {rot}"
        if fmode == "entity":
            # 官方顺序：facing entity <实体> [eyes|feet]
            # （TeleportCommand.java L94-110，实体在前锚点在后）
            out += (f" facing entity {p.get('facing_entity') or '@e[limit=1]'}"
                    f" {_fmt(p.get('facing_anchor') or 'eyes')}")
        elif fmode == "location":
            out += f" facing {p.get('facing_location') or '~ ~ ~'}"
    else:
        out += f" {_rid(p.get('destination') or '@s', ns_prefix)}"
    return out


def rotate(p, v="1.21.11"):
    """`/rotate <target> <rotation>` / `... facing <pos>` /
    `... facing entity <entity> [eyes|feet]`

    1.21：指令不存在（1.21.2 新增），生成提示文本。
    """
    if v == "1.21":
        return "（1.21 无 rotate 指令）"
    tgt = p.get("target") or "@s"
    fmode = p.get("facing_mode")
    if fmode == "entity":
        # 官方顺序：实体在前，锚点在后
        return (f"/rotate {tgt} facing entity "
                f"{p.get('facing_entity') or '@e[limit=1]'} "
                f"{_fmt(p.get('facing_anchor') or 'eyes')}")
    if fmode == "location":
        return (f"/rotate {tgt} facing "
                f"{p.get('facing_location') or '~ ~ ~'}")
    rot = p.get("rotation") or "0 0"
    return f"/rotate {tgt} {rot}"


def datapack(p, v="1.21.11"):
    """`/datapack (enable|disable|list|create)`"""
    br = p.get("branch") or "list"
    out = f"/datapack {br}"
    if br in ("enable", "disable"):
        name = (p.get("name") or "").strip() or "vanilla"
        out += f" {name}"
        if br == "enable":
            order = p.get("order")
            if order in ("first", "last"):
                out += f" {order}"
            else:
                existing = (p.get("existing") or "").strip()
                before_after = p.get("before_after")
                if before_after and existing:
                    out += f" {before_after} {existing}"
    elif br == "create":
        if v == "1.21":
            # 1.21 无 create 子命令（26.x 新增），生成提示文本
            return "（1.21 无 datapack create 子命令）"
        # 26.2 实测：create <id> <描述>，描述必填（空描述给 ""）
        out += f" {p.get('id') or 'custom'}"
        desc = p.get("description")
        out += f" {snbt.text_component(str(desc)) if desc else '\"\"'}"
    elif br == "list":
        f = p.get("filter")
        if f:
            out += f" {f}"
    return out


def fillbiome(p, v="1.21.11"):
    """`/fillbiome <from> <to> <biome> [replace <filter>]`"""
    ns_prefix = p.get("ns_prefix", True)
    frm = p.get("from") or "~ ~ ~"
    to = p.get("to") or "~ ~ ~"
    biome = p.get("biome") or "plains"
    out = f"/fillbiome {frm} {to} {_rid(biome, ns_prefix)}"
    filt = (p.get("filter") or "").strip()
    if filt:
        out += f" replace {filt if filt.startswith('#') else _rid(filt, ns_prefix)}"
    return out


def clone(p, v="1.21.11"):
    """`/clone [from <dim>] <begin> <end> [to <dim>] <destination>
    [strict] [replace|masked|filtered <filter>] [force|move|normal]`"""
    ns_prefix = p.get("ns_prefix", True)
    out = "/clone"
    if p.get("source_dimension"):
        out += f" from {p['source_dimension']}"
    out += (f" {p.get('begin') or '~ ~ ~'} "
            f"{p.get('end') or '~ ~ ~'}")
    if p.get("target_dimension"):
        out += f" to {p['target_dimension']}"
    out += f" {p.get('destination') or '~ ~ ~'}"
    if p.get("strict"):
        out += " strict"
    mode = p.get("mode") or "replace"
    if mode == "filtered":
        filt = (p.get("filter") or "").strip()
        out += f" filtered {filt if filt.startswith('#') else _rid(filt, ns_prefix)}"
    else:
        out += f" {mode}"
    om = p.get("overlap") or "normal"
    if om != "normal":
        out += f" {om}"
    return out


def worldborder(p, v="1.21.11"):
    """`/worldborder` 各分支"""
    br = p.get("branch") or "get"
    out = f"/worldborder {br}"
    if br in ("add", "set"):
        d = p.get("distance")
        out += f" {d if d is not None else 0:g}"
        t = p.get("time")
        if t is not None:
            out += f" {int(t)}"
    elif br == "center":
        out += f" {p.get('center_x', 0):g} {p.get('center_z', 0):g}"
    elif br == "damage":
        sub = p.get("damage_sub") or "amount"
        out += f" {sub} {p.get('damage_value', 0):g}"
    elif br == "warning":
        sub = p.get("warning_sub") or "distance"
        out += f" {sub} {int(p.get('warning_value') or 0)}"
    return out


# ---------------------------------------------------------------------------
# 复合（多分支 + 多类型参数）
# ---------------------------------------------------------------------------

def data(p, v="1.21.11"):
    """`/data (get|merge|modify|remove)`，路径与 NBT 均为字符串。

    get    (block <pos>|entity <e>) [path] [scale]
    merge  (block|entity) <目标> <nbt>
    remove (block|entity) <目标> <path>
    modify (block|entity) <目标> <path> <op> <来源>
           <op> = set|merge|insert N|prepend|append
           <来源> = value <nbt> | from (block <pos>|entity <e>) <srcPath>
    完整 modify 分支很深；这里覆盖最常用的 set/value、append 与
    set from，其余由用户改输出。
    """
    ns_prefix = p.get("ns_prefix", True)
    br = p.get("branch") or "get"
    kind = p.get("kind") or "entity"
    tgt = (p.get("target") or "@s").strip()

    def _tgt():
        return (f"block {p.get('pos') or '~ ~ ~'}"
                if kind == "block" else f"entity {tgt}")

    if br == "get":
        path = (p.get("path") or "").strip()
        scale = p.get("scale")
        out = f"/data get {_tgt()}"
        if path:
            out += f" {path}"
            if scale is not None and float(scale) != 1.0:
                out += f" {float(scale):g}"
        return out
    if br == "merge":
        nbt = (p.get("nbt") or "").strip() or "{}"
        return f"/data merge {_tgt()} {nbt}"
    if br == "remove":
        # remove 的 path 官方必填，空时兜底合法路径
        path = (p.get("path") or "").strip() or "CustomName"
        return f"/data remove {_tgt()} {path}"
    # modify
    path = (p.get("path") or "").strip() or "CustomName"
    # 26.2 无裸 value op（原默认 "value" 会产出非法形状），默认 set
    op = p.get("modify_op") or "set"
    # 26.2 服务器实测：from 是来源说明符，挂在操作之下；操作位必须是
    # set/insert/prepend/append/merge（DataCommands.java
    # decorateModification）。旧实现把 from 当操作产出缺操作的非法
    # 形状，现固定补 set。
    out = f"/data modify {_tgt()} {path} {'set' if op == 'from' else op}"
    if op in ("set", "merge", "prepend", "append"):
        # set/merge/prepend/append 后必须跟 value <nbt>；
        # 空 NBT 在 UI 层由必填校验拦截，这里兜底 "{}"
        nbt = (p.get("nbt") or "").strip() or "{}"
        out += f" value {nbt}"
        return out
    if op == "from":
        skind = p.get("source_kind") or "entity"
        ssrc = (p.get("source_target") or "@s").strip()
        spath = (p.get("source_path") or "").strip()
        src = (f"block {p.get('source_pos') or '~ ~ ~'}"
               if skind == "block" else f"entity {ssrc}")
        # 前面已补操作 set，此处显式写出来源说明符 from
        out += f" from {src}"
        if spath:
            out += f" {spath}"
        else:
            out += " CustomName"  # 兜底合法路径
        return out
    return out.rstrip()


def scoreboard(p, v="1.21.11"):
    """`/scoreboard` 常用分支（objectives/players 两树）"""
    ns_prefix = p.get("ns_prefix", True)
    br = p.get("branch") or "objectives_list"

    if br == "objectives_list":
        return "/scoreboard objectives list"
    if br == "objectives_add":
        name = p.get("objective_name") or "obj1"
        crit = p.get("criteria") or "dummy"
        out = f"/scoreboard objectives add {name} {crit}"
        dn = p.get("display_name")
        if dn:
            out += f" {snbt.text_component(str(dn))}"
        return out
    if br == "objectives_remove":
        return f"/scoreboard objectives remove {p.get('objective') or 'obj1'}"
    if br == "objectives_setdisplay":
        slot = p.get("slot") or "sidebar"
        obj = (p.get("objective") or "").strip()
        out = f"/scoreboard objectives setdisplay {slot}"
        if obj:
            out += f" {obj}"
        return out
    # players
    if br == "players_set":
        return (f"/scoreboard players set {p.get('targets') or '@s'} "
                f"{p.get('objective') or 'obj1'} "
                f"{int(p.get('score') or 0)}")
    if br == "players_add":
        return (f"/scoreboard players add {p.get('targets') or '@s'} "
                f"{p.get('objective') or 'obj1'} "
                f"{int(p.get('score') or 1)}")
    if br == "players_get":
        return (f"/scoreboard players get {p.get('targets') or '@s'} "
                f"{p.get('objective') or 'obj1'}")
    if br == "players_reset":
        tgt = p.get("targets") or "@s"
        obj = (p.get("objective") or "").strip()
        out = f"/scoreboard players reset {tgt}"
        if obj:
            out += f" {obj}"
        return out
    if br == "players_list":
        tgt = (p.get("targets") or "").strip()
        return f"/scoreboard players list" + (f" {tgt}" if tgt else "")
    return "/scoreboard objectives list"


def team(p, v="1.21.11"):
    """`/team` 常用分支"""
    ns_prefix = p.get("ns_prefix", True)
    br = p.get("branch") or "list"
    if br == "list":
        t = (p.get("team") or "").strip()
        return "/team list" + (f" {t}" if t else "")
    if br == "add":
        return f"/team add {p.get('team') or 'newteam'}"
    if br == "remove":
        return f"/team remove {p.get('team') or 'newteam'}"
    if br == "empty":
        return f"/team empty {p.get('team') or 'newteam'}"
    if br == "join":
        t = p.get("team") or "newteam"
        m = (p.get("members") or "").strip()
        return "/team join " + t + (f" {m}" if m else "")
    if br == "leave":
        return f"/team leave {p.get('members') or '@s'}"
    if br == "modify":
        t = p.get("team") or "newteam"
        opt = p.get("option") or "color"
        out = f"/team modify {t} {opt}"
        if opt == "color":
            out += f" {p.get('color') or 'red'}"
        elif opt in ("prefix", "suffix"):
            v = p.get("text") or ""
            out += f" {snbt.text_component(str(v))}"
        elif opt in ("friendlyFire", "seeFriendlyInvisibles"):
            out += f" {str(bool(p.get('value', True))).lower()}"
        return out
    return "/team list"


def bossbar(p, v="1.21.11"):
    """`/bossbar (add|remove|list|get|set)`"""
    ns_prefix = p.get("ns_prefix", True)
    br = p.get("branch") or "list"
    if br == "list":
        return "/bossbar list"
    bid = _rid(p.get("id") or "boss1", ns_prefix)
    if br == "add":
        # 26.2 实测：add <id> <显示名>，显示名必填
        nm = snbt.text_component(str(p.get("name") or "Bossbar"))
        return f"/bossbar add {bid} {nm}"
    if br == "get":
        # 26.2 实测：get <id> <查询项>，查询项必填且仅
        # value/max/visible/players（color/name/style 只在 set）
        return f"/bossbar get {bid} {p.get('option') or 'value'}"
    if br == "remove":
        return f"/bossbar remove {bid}"
    # set
    sub = p.get("sub") or "name"
    out = f"/bossbar set {bid} {sub}"
    if sub == "name":
        out += f" {snbt.text_component(str(p.get('name') or 'Boss'))}"
    elif sub == "color":
        out += f" {p.get('color') or 'red'}"
    elif sub == "style":
        out += f" {p.get('style') or 'notched_10'}"
    elif sub in ("value", "max"):
        # value 是可空 int（spec optional=True）：「不填」时 params
        # 返回 None —— p.get('value', 0) 对**值为 None** 的键不取
        # 默认值（get 只在 key 缺失时用默认），int(None) 即崩。
        # 各属性的游戏内默认：value=0、max=100。
        val = p.get("value")
        out += f" {val if val is not None else (100 if sub == 'max' else 0)}"
    elif sub == "visible":
        out += f" {str(bool(p.get('visible', True))).lower()}"
    elif sub == "players":
        out += f" {p.get('targets') or '@a'}"
    return out


def advancement(p, v="1.21.11"):
    """`/advancement (grant|revoke) <targets> (everything|only|from|
    through|until) <advancement> [criterion]`"""
    ns_prefix = p.get("ns_prefix", True)
    br = p.get("branch") or "grant"
    tgt = p.get("targets") or "@s"
    mode = p.get("mode") or "everything"
    out = f"/advancement {br} {tgt} {mode}"
    if mode != "everything":
        adv = (p.get("advancement") or "").strip()
        if not adv:
            # 空 id：UI 层必填拦截；直接调用时退回 everything（合法）
            return f"/advancement {br} {tgt} everything"
        out += f" {_rid(adv, ns_prefix)}"
        crit = (p.get("criterion") or "").strip()
        if crit and mode == "only":
            out += f" {crit}"
    return out


def place(p, v="1.21.11"):
    """`/place (feature|jigsaw|structure|template)`"""
    ns_prefix = p.get("ns_prefix", True)
    br = p.get("branch") or "structure"
    if br == "structure":
        sid = p.get("structure") or "village_plains"
        pos = (p.get("pos") or "").strip()
        out = f"/place structure {_rid(sid, ns_prefix)}"
        if pos:
            out += f" {pos}"
        return out
    if br == "feature":
        # feature id 官方必填（空 id UI 层拦截，这里兜底常用地物）
        fid = (p.get("feature") or "").strip() or "minecraft:forest_rock"
        pos = (p.get("pos") or "").strip()
        return (f"/place feature {_rid(fid, ns_prefix)} " +
                (pos or "~ ~ ~")).rstrip()
    if br == "template":
        # template id 官方必填（兜底合法 id，游戏内不存在时报缺失而非语法错）
        tid = (p.get("template") or "").strip() or "minecraft:empty"
        pos = (p.get("pos") or "").strip()
        rot = p.get("rotation")
        mir = p.get("mirror")
        integ = p.get("integrity")
        seed = p.get("seed")
        out = f"/place template {_rid(tid, ns_prefix)} {pos or '~ ~ ~'}"
        vals = _positional(
            [rot, mir, integ, seed],
            ["none", "none", 1.0, 0])
        for x in vals:
            out += f" {_fmt(x)}"
        return out
    # jigsaw：pool/target 官方必填（空 id 在 UI 层拦截，这里兜底）
    pool = (p.get("pool") or "").strip() or "minecraft:village/plains/houses"
    tgt = (p.get("target") or "").strip() or "minecraft:empty"
    out = (f"/place jigsaw {_rid(pool, ns_prefix)} {tgt} "
           f"{int(p.get('max_depth') or 7)}")
    pos = (p.get("position") or "").strip()
    if pos:
        out += f" {pos}"
    return out


SERIALIZERS = {
    "chase": chase, "debugconfig": debugconfig, "dialog": dialog,
    "gamerule": gamerule, "raid": raid, "random": random,
    "schedule": schedule, "tick": tick, "forceload": forceload,
    "waypoint": waypoint, "experience": experience, "title": title,
    "spreadplayers": spreadplayers, "teleport": teleport,
    "rotate": rotate, "datapack": datapack, "fillbiome": fillbiome,
    "clone": clone, "worldborder": worldborder, "data": data,
    "scoreboard": scoreboard, "team": team, "bossbar": bossbar,
    "advancement": advancement, "place": place,
}
