# -*- coding: utf-8 -*-
"""execute 的链式构建器（序列化侧，纯函数）。

execute 不是「面包屑+表单」能表达的指令 —— 它是**管道**：任意数量的
子命令按序连接，最后以 run <指令> 收尾。故 UI 用**行列表**（每行选
一个子命令 + 该行专属参数），序列化就是**把每行拼起来**。

行模型（UI 产出）：
    {"op": "as",        "args": {"targets": "@a"}}
    {"op": "if_block",  "args": {"pos": "~ ~ ~", "block": "stone"}}
    {"op": "run",       "args": {"cmd": "say hi"}}

serialize_chains(chains) 按官方语法顺序拼接。

子命令全集与参数（源码核对 ExecuteCommand.java，骨架见
.temp/exec_detail.out / exec_detail2.out）：
  位置/执行者: as at positioned positioned_as positioned_over
               rotated rotated_as facing facing_entity facing_pos
               align anchored in summon on
  条件:        if/unless + block blocks biome entity data items
               predicate function score loaded dimension stopwatch
               owner leasher target attacker vehicle controller
               origin passengers
  存储:        store (result|success) -> bossbar|score|entity|block
               + 数据类型(int..byte)+scale / 路径
  收尾:        run <指令>
"""
from __future__ import annotations

from . import snbt


def _rid(name, ns_prefix=True):
    return snbt.res_id(name, ns_prefix)


def _g(args, key, dflt=""):
    v = args.get(key)
    return str(v).strip() if v is not None else dflt


# 每个子命令的渲染函数：args -> 文本（不含子命令名本身）
def _as(a, ns):
    return _g(a, "targets", "@s")


def _at(a, ns):
    return _g(a, "targets", "@s")


def _positioned(a, ns):
    return _g(a, "pos", "~ ~ ~")


def _positioned_as(a, ns):
    return _g(a, "targets", "@s")


def _positioned_over(a, ns):
    return _g(a, "heightmap", "world_surface")


def _rotated(a, ns):
    return _g(a, "rot", "0 0")


def _rotated_as(a, ns):
    return _g(a, "targets", "@s")


def _facing_entity(a, ns):
    return (f"{_fmt_anchor(a.get('anchor'))} "
            f"{_g(a, 'targets', '@e[limit=1]')}")


def _facing_pos(a, ns):
    return _g(a, "pos", "~ ~ ~")


def _align(a, ns):
    return _g(a, "axes", "xyz")


def _anchored(a, ns):
    return _fmt_anchor(a.get("anchor"))


def _in(a, ns):
    return _rid(_g(a, "dimension", "overworld"), ns)


def _summon(a, ns):
    return _rid(_g(a, "entity", "pig"), ns)


def _on(a, ns):
    return _g(a, "relation", "vehicle")


def _if_block(a, ns):
    return f"{_g(a, 'pos', '~ ~ ~')} {_rid(_g(a, 'block', 'stone'), ns)}"


def _if_blocks(a, ns):
    out = (f"{_g(a, 'start', '~ ~ ~')} {_g(a, 'end', '~ ~ ~')} "
           f"{_g(a, 'destination', '~ ~ ~')} "
           f"{_rid(_g(a, 'source_dimension') or 'overworld', ns)} "
           f"{_rid(_g(a, 'target_dimension') or 'overworld', ns)} "
           f"{a.get('mode') or 'all'}")
    return out


def _if_biome(a, ns):
    out = f"{_g(a, 'pos', '~ ~ ~')} {_rid(_g(a, 'biome', 'plains'), ns)}"
    return out


def _if_entity(a, ns):
    return _g(a, "targets", "@e[limit=1]")


def _if_data(a, ns):
    kind = a.get("kind") or "entity"
    if kind == "block":
        src = f"block {_g(a, 'pos', '~ ~ ~')}"
    elif kind == "storage":
        src = f"storage {_rid(_g(a, 'source') or 'mch:st', ns)}"
    else:
        src = f"entity {_g(a, 'target', '@s')}"
    path = _g(a, "path", "")
    return f"{src} {path}".rstrip()


def _if_items(a, ns):
    kind = a.get("kind") or "entity"
    if kind == "block":
        src = f"block {_g(a, 'pos', '~ ~ ~')}"
    else:
        src = f"entity {_g(a, 'target', '@s')}"
    slots = _g(a, "slots", "weapon.mainhand")
    pred = _g(a, "item_predicate", "minecraft:diamond_sword")
    return f"{src} {slots} {pred}"


def _if_predicate(a, ns):
    return _rid(_g(a, "predicate", "mch:pred"), ns)


def _if_function(a, ns):
    return _rid(_g(a, "name", "mch:check"), ns)


def _if_score(a, ns):
    return (f"{_g(a, 'target', '@s')} "
            f"{_g(a, 'objective', 'obj1')} "
            f"{a.get('op') or 'matches'} "
            f"{_g(a, 'range', '1..')}")


def _if_loaded(a, ns):
    return _g(a, "pos", "~ ~ ~")


def _if_dimension(a, ns):
    return _rid(_g(a, "dimension", "overworld"), ns)


def _if_stopwatch(a, ns):
    return f"{_rid(_g(a, 'id', 'mch:sw'), ns)} {_g(a, 'range', '1..')}"


def _if_relation(a, ns):
    return _g(a, "targets", "@s")


def _store(a, ns):
    """store (result|success) <目标> ... <类型> <scale>"""
    res = a.get("result") or "result"
    tgt = a.get("store_target") or "score"

    if tgt == "score":
        body = (f"score {_g(a, 'target', '@s')} "
                f"{_g(a, 'objective', 'obj1')}")
    elif tgt == "bossbar":
        body = f"bossbar {_rid(_g(a, 'id', 'boss1'), ns)}"
    elif tgt == "entity":
        body = (f"entity {_g(a, 'target', '@s')} "
                f"{_g(a, 'path', 'Health')} {_fmt_dt(a.get('dtype'))} "
                f"{_g(a, 'scale', '1.0')}")
    elif tgt == "block":
        body = (f"block {_g(a, 'pos', '~ ~ ~')} "
                f"{_g(a, 'path', 'Items')} {_fmt_dt(a.get('dtype'))} "
                f"{_g(a, 'scale', '1.0')}")
    else:                                          # storage
        body = (f"storage {_rid(_g(a, 'source', 'mch:st'), ns)} "
                f"{_g(a, 'path', 'value')} {_fmt_dt(a.get('dtype'))} "
                f"{_g(a, 'scale', '1.0')}")
    # score/bossbar 无类型后缀；entity/block/storage 有
    if tgt in ("entity", "block", "storage"):
        return f"{res} {body}"
    return f"{res} {body}"


def _fmt_dt(dt):
    return (dt or "double").lower()


def _fmt_anchor(a):
    return (a or "eyes").lower()


def _run(a, ns):
    return _g(a, "cmd", "say hi")


_RENDER = {
    "as": _as, "at": _at,
    "positioned": _positioned,
    "positioned_as": _positioned_as,
    "positioned_over": _positioned_over,
    "rotated": _rotated, "rotated_as": _rotated_as,
    "facing_entity": _facing_entity, "facing_pos": _facing_pos,
    "align": _align, "anchored": _anchored, "in": _in,
    "summon": _summon, "on": _on,
    "if_block": _if_block, "unless_block": _if_block,
    "if_blocks": _if_blocks, "unless_blocks": _if_blocks,
    "if_biome": _if_biome, "unless_biome": _if_biome,
    "if_entity": _if_entity, "unless_entity": _if_entity,
    "if_data": _if_data, "unless_data": _if_data,
    "if_items": _if_items, "unless_items": _if_items,
    "if_predicate": _if_predicate, "unless_predicate": _if_predicate,
    "if_function": _if_function, "unless_function": _if_function,
    "if_score": _if_score, "unless_score": _if_score,
    "if_loaded": _if_loaded, "unless_loaded": _if_loaded,
    "if_dimension": _if_dimension, "unless_dimension": _if_dimension,
    "if_stopwatch": _if_stopwatch, "unless_stopwatch": _if_stopwatch,
    "if_owner": _if_relation, "unless_owner": _if_relation,
    "if_leasher": _if_relation, "unless_leasher": _if_relation,
    "if_target": _if_relation, "unless_target": _if_relation,
    "if_attacker": _if_relation, "unless_attacker": _if_relation,
    "if_vehicle": _if_relation, "unless_vehicle": _if_relation,
    "if_controller": _if_relation, "unless_controller": _if_relation,
    "if_origin": _if_relation, "unless_origin": _if_relation,
    "if_passengers": _if_relation, "unless_passengers": _if_relation,
    "store": _store,
    "run": _run,
}

# UI 里的分组（下拉顺序）
OP_GROUPS = [
    ("执行者/位置", [
        ("as", "as（以实体身份）"),
        ("at", "at（以实体位置）"),
        ("positioned", "positioned（定位坐标）"),
        ("positioned_as", "positioned as（以实体位置）"),
        ("positioned_over", "positioned over（高度图）"),
        ("rotated", "rotated（旋转）"),
        ("rotated_as", "rotated as（以实体旋转）"),
        ("facing_entity", "facing entity（面向实体）"),
        ("facing_pos", "facing（面向坐标）"),
        ("align", "align（对齐）"),
        ("anchored", "anchored（锚点）"),
        ("in", "in（维度）"),
        ("summon", "summon（临时实体）"),
        ("on", "on（关联实体）"),
    ]),
    ("条件 if/unless", [
        ("if_block", "if block（方块）"),
        ("if_blocks", "if blocks（区域）"),
        ("if_biome", "if biome（群系）"),
        ("if_entity", "if entity（实体）"),
        ("if_data", "if data（NBT）"),
        ("if_items", "if items（物品）"),
        ("if_predicate", "if predicate（谓词）"),
        ("if_function", "if function（函数）"),
        ("if_score", "if score（分数）"),
        ("if_loaded", "if loaded（已加载）"),
        ("if_dimension", "if dimension（维度）"),
        ("if_stopwatch", "if stopwatch（秒表）"),
        ("if_owner", "if owner（主人）"),
        ("if_leasher", "if leasher（拴绳）"),
        ("if_target", "if target（攻击目标）"),
        ("if_attacker", "if attacker（攻击者）"),
        ("if_vehicle", "if vehicle（载具）"),
        ("if_controller", "if controller（控制器）"),
        ("if_origin", "if origin（起源）"),
        ("if_passengers", "if passengers（乘客）"),
    ]),
    ("存储", [
        ("store", "store（存值）"),
    ]),
    ("收尾", [
        ("run", "run（执行指令）"),
    ]),
]


# 复合 op -> 官方多词前缀（如 positioned_over -> "positioned over"）。
# 早先直接输出 op 名（"positioned_over"），产出的指令游戏无法解析。
_OP_PREFIX = {
    "positioned_over": "positioned over",
    "positioned_as": "positioned as",
    "rotated_as": "rotated as",
    "facing_entity": "facing entity",
    "facing_pos": "facing",
}


def serialize_chain(chains: list, version_key: str = "1.21.11",
                    ns_prefix: bool = True) -> str:
    """链列表 -> `/execute ...` 文本。"""
    parts = []
    for ch in chains:
        op = ch.get("op") or ""
        args = ch.get("args") or {}
        fn = _RENDER.get(op)
        if fn is None:
            continue
        body = fn(args, ns_prefix)
        if op.startswith(("if_", "unless_")):
            cond, sub = op.split("_", 1)
            parts.append(f"{cond} {sub} {body}")
        elif op in _OP_PREFIX:
            parts.append(f"{_OP_PREFIX[op]} {body}")
        else:
            parts.append(f"{op} {body}")
    return "/execute " + " ".join(p.strip() for p in parts if p.strip())
