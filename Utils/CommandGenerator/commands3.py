# -*- coding: utf-8 -*-
"""剩余 26 条指令的序列化（纯函数，无 Qt）。

语法均逐行核对 1.21.11 反编译源码（骨架见 .temp/dump26.out 与
detail26b.out）。按复杂度分三个 mixin 区块：
  简单（单分支/少参数）、中等多分支、复合两段式。
"""
from __future__ import annotations

from . import snbt


def _rid(name, ns_prefix=True):
    return snbt.res_id(name, ns_prefix)


def _positional(values, defaults):
    last = -1
    for i, v in enumerate(values):
        if v is not None and v != "":
            last = i
    if last < 0:
        return []
    return [(values[i] if values[i] not in (None, "")
             else defaults[i]) for i in range(last + 1)]


def _fmt(v):
    if isinstance(v, bool):
        return str(v).lower()
    return str(v)


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
    """`/debugconfig config <player> <dialog>` / unconfig <player|uuid>"""
    br = p.get("branch") or "config"
    tgt = p.get("target") or "@s"
    if br == "config":
        dlg = p.get("dialog") or ""
        return f"/debugconfig config {tgt} {_rid(dlg)}" if dlg else \
            f"/debugconfig config {tgt}"
    return f"/debugconfig unconfig {tgt}"


def dialog(p, v="1.21.11"):
    """`/dialog show <targets> <dialog>` / clear"""
    br = p.get("branch") or "show"
    if br == "clear":
        return "/dialog clear @a"
    tgt = p.get("targets") or "@s"
    dlg = p.get("dialog") or ""
    return f"/dialog show {tgt} {_rid(dlg)}" if dlg else \
        f"/dialog show {tgt}"


def gamerule(p, v="1.21.11"):
    """`/gamerule <rule> [value]`（value 类型随规则变化）"""
    rule = p.get("rule") or "keep_inventory"
    val = p.get("value")
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
    """`/random [range]` / `reset [seed] [...]`"""
    if p.get("branch") == "reset":
        out = "/random reset"
        vals = _positional(
            [p.get("seed"), p.get("include_world_seed"),
             p.get("include_sequence_id"), p.get("sequence")],
            [0, True, True, ""])
        if vals:
            # reset 的可选参数须连续
            out += f" {int(vals[0])}"
            if len(vals) > 1:
                out += f" {str(bool(vals[1])).lower()}"
                if len(vals) > 2:
                    out += f" {str(bool(vals[2])).lower()}"
                    if len(vals) > 3 and vals[3]:
                        out += f" {_rid(vals[3])}"
        return out
    rng = (p.get("range") or "").strip()
    return f"/random {rng}" if rng else "/random 1..6"


def schedule(p, v="1.21.11"):
    """`/schedule function <f> <time> [append|replace]` / clear <f>"""
    br = p.get("branch") or "function"
    fn = p.get("function") or ""
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
    """`/tick` 各分支"""
    br = p.get("branch") or "query"
    if br in ("rate", "step", "sprint"):
        val = p.get("rate") if p.get("rate") is not None else p.get("time")
        out = f"/tick {br}"
        if val is not None:
            out += f" {val:g}" if isinstance(val, float) else f" {val}"
        return out
    return f"/tick {br}"


def forceload(p, v="1.21.11"):
    """`/forceload (add|remove|all|query)`（区块列坐标）"""
    br = p.get("branch") or "query"
    out = f"/forceload {br}"
    frm = (p.get("from") or "").strip()
    to = (p.get("to") or "").strip()
    if br in ("add", "remove") and frm:
        out += f" {frm}"
        if to:
            out += f" {to}"
    elif br == "query" and frm:
        out += f" {frm}"
    return out


def waypoint(p, v="1.21.11"):
    """`/waypoint` 各分支"""
    br = p.get("branch") or "list"
    out = f"/waypoint {br}"
    wp = (p.get("waypoint") or "").strip()
    if br == "modify" and wp:
        out += f" {wp}"
        sub = p.get("sub") or "color"
        out += f" {sub}"
        if sub == "color":
            c = p.get("color")
            out += f" {_fmt(c)}" if c is not None else " reset"
        elif sub == "style":
            out += f" {_rid(p.get('style') or 'default')}"
    elif br in ("list",) and wp:
        out += f" {wp}"
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
        out = f"/title {tgt} times"
        for x in vals:
            out += f" {int(x)}"
        return out
    txt = p.get("text") or ""
    body = snbt.text_component(txt) if isinstance(txt, str) and txt \
        else str(txt)
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
    """`/tp <targets> <location|destination>` [+ rotation/facing]"""
    ns_prefix = p.get("ns_prefix", True)
    tgt = (p.get("targets") or "").strip()
    out = "/tp"
    if tgt:
        out += f" {tgt}"
    mode = p.get("mode") or "location"
    if mode == "location":
        out += f" {p.get('location') or '~ ~ ~'}"
        rot = (p.get("rotation") or "").strip()
        if rot:
            out += f" {rot}"
    else:
        out += f" {_rid(p.get('destination') or '@s', ns_prefix)}"
    fmode = p.get("facing_mode")
    if fmode == "entity":
        out += (f" facing {_fmt(p.get('facing_anchor') or 'eyes')} "
                f"{p.get('facing_entity') or '@e[limit=1]'}")
    elif fmode == "location":
        out += f" facing {p.get('facing_location') or '~ ~ ~'}"
    return out


def rotate(p, v="1.21.11"):
    """`/rotate <target> <rotation>` / `... facing (...)`"""
    tgt = p.get("target") or "@s"
    if p.get("facing_mode") == "entity":
        return (f"/rotate {tgt} facing "
                f"{_fmt(p.get('facing_anchor') or 'eyes')} "
                f"{p.get('facing_entity') or '@e[limit=1]'}")
    if p.get("facing_mode") == "location":
        return (f"/rotate {tgt} facing "
                f"{p.get('facing_location') or '~ ~ ~'}")
    rot = p.get("rotation") or "0 0"
    return f"/rotate {tgt} {rot}"


def datapack(p, v="1.21.11"):
    """`/datapack (enable|disable|list|create)`"""
    br = p.get("branch") or "list"
    out = f"/datapack {br}"
    if br in ("enable", "disable"):
        name = (p.get("name") or "").strip()
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
        out += f" {p.get('id') or ''}"
        desc = p.get("description")
        if desc:
            out += f" {snbt.text_component(str(desc))}"
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
        out += f" {sub} {int(p.get('warning_value', 0))}"
    return out


# ---------------------------------------------------------------------------
# 复合（多分支 + 多类型参数）
# ---------------------------------------------------------------------------

def data(p, v="1.21.11"):
    """`/data (get|merge|modify|remove)`，路径与 NBT 均为字符串。

    get    (block <pos>|entity <e>) [path] [scale]
    merge  (block|entity) <目标> <nbt>
    remove (block|entity) <目标> <path>
    modify (block|entity) <目标> <path> (set|merge|insert N|prepend|
           append|from (block|entity) <源> [sourcePath]|string ...|
           value <nbt>)
    完整 modify 分支很深；这里覆盖最常用的 set/value、append 与
    from，其余由用户改输出。
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
        path = (p.get("path") or "").strip()
        return f"/data remove {_tgt()} {path}".rstrip()
    # modify
    path = (p.get("path") or "").strip()
    op = p.get("modify_op") or "value"
    out = f"/data modify {_tgt()} {path} {op}"
    if op in ("set", "merge", "prepend", "append"):
        nbt = (p.get("nbt") or "").strip()
        out += f" value {nbt}" if nbt else ""
        if op in ("set", "merge", "prepend", "append") and nbt:
            # set/merge/prepend/append 后直接跟 value <nbt>
            out = out.replace(f" {op} value", f" {op} value")
        return out.rstrip()
    if op == "from":
        skind = p.get("source_kind") or "entity"
        ssrc = (p.get("source_target") or "@s").strip()
        spath = (p.get("source_path") or "").strip()
        src = (f"block {p.get('source_pos') or '~ ~ ~'}"
               if skind == "block" else f"entity {ssrc}")
        out += f" from {src}"
        if spath:
            out += f" {spath}"
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
                f"{int(p.get('score', 0))}")
    if br == "players_add":
        return (f"/scoreboard players add {p.get('targets') or '@s'} "
                f"{p.get('objective') or 'obj1'} "
                f"{int(p.get('score', 1))}")
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
    if br in ("add", "remove", "get"):
        return f"/bossbar {br} {bid}"
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
        out += f" {int(p.get('value', 100) if sub == 'max' else p.get('value', 0))}"
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
        adv = p.get("advancement") or ""
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
        fid = p.get("feature") or ""
        pos = (p.get("pos") or "").strip()
        return (f"/place feature {_rid(fid, ns_prefix)} " +
                (pos or "~ ~ ~")).rstrip()
    if br == "template":
        tid = p.get("template") or ""
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
    # jigsaw
    pool = p.get("pool") or ""
    tgt = p.get("target") or ""
    out = (f"/place jigsaw {_rid(pool, ns_prefix)} {tgt} "
           f"{int(p.get('max_depth', 7))}")
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
