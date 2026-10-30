# -*- coding: utf-8 -*-
"""CommandGenerator：7 条指令的序列化（纯函数，无 Qt 依赖）。

覆盖：kill / enchant / effect / setblock / fill / summon / locate

所有语法均逐行核对 1.21.11 反编译源码，关键分支已在各函数
docstring 内注明行号依据。

通用约定：参数以 `dict` 传入，返回完整指令文本（含前导 `/`）。
"""
from __future__ import annotations

from Utils.CommandGenerator import struct_list as SL
from Utils.CommandGenerator import snbt
from .serialize_util import positional as _positional


def _rid(name: str, ns_prefix: bool = True) -> str:
    return snbt.res_id(name, ns_prefix)


# ---------------------------------------------------------------------------
# kill（KillCommand.java L15-21）
# ---------------------------------------------------------------------------

def kill(params: dict, version_key: str = "1.21.11") -> str:
    """`/kill [targets]`

    targets 可省略（L18：无参时作用于执行者自身）。
    """
    targets = (params.get("targets") or "").strip()
    return "/kill" + (f" {targets}" if targets else "")


# ---------------------------------------------------------------------------
# enchant（EnchantCommand.java L42-69）
# ---------------------------------------------------------------------------

def enchant(params: dict, version_key: str = "1.21.11") -> str:
    """`/enchant <targets> <enchantment> [level]`

    - `enchantment` 必填；`level` 可省略，省略时官方取 1（L53）。
    - level 的范围是 `integer(0)`，即**允许 0**（L57），无上限。
    """
    ns_prefix = params.get("ns_prefix", True)
    targets = params.get("targets") or "@s"
    ench = params.get("enchantment") or "sharpness"
    out = f"/enchant {targets} {_rid(ench, ns_prefix)}"
    lvl = params.get("level")
    if lvl is not None and lvl != 1:
        out += f" {int(lvl)}"
    return out


# ---------------------------------------------------------------------------
# effect（EffectCommands.java L36-160）
# ---------------------------------------------------------------------------

def effect(params: dict, version_key: str = "1.21.11") -> str:
    """`/effect` 三个分支（EffectCommands.java L36-160）：

    - `clear [targets] [effect]`（L40-59）
        targets 可省略（清空自身全部效果）；给了 targets 才能给
        effect（只清某个效果）。
    - `give <targets> <effect> [seconds] [amplifier] [hideParticles]`
      （L62-117）—— effect 之后三个参数**逐级可选**（L69 的
        executes 证明 seconds 可省）；seconds 范围 (1,1000000)。
    - `give <targets> <effect> infinite [amplifier] [hideParticles]`
      （L115-155）—— 26.2 实测：`effect infinite ...` 不是合法
        形状，infinite 是 give 下 effect 之后的 literal（服务器报
        Incorrect argument）。

    Brigadier 要求参数从左到右连续，故用 `_positional` 补齐空洞：
    只填 amplifier 时必须补出 seconds（give）或直接放 amplifier
    （infinite）。
    """
    ns_prefix = params.get("ns_prefix", True)
    branch = params.get("branch") or "give"
    targets = (params.get("targets") or "").strip()
    eff = params.get("effect")

    # ---- clear ----
    if branch == "clear":
        out = "/effect clear"
        if targets:
            out += f" {targets}"
            if eff:
                out += f" {_rid(eff, ns_prefix)}"
        return out

    out = f"/effect {branch} {targets or '@s'} " \
          f"{_rid(eff or 'speed', ns_prefix)}"

    hide = params.get("hide_particles")
    hide_v = None if hide is None else str(bool(hide)).lower()

    if branch == "infinite":
        # infinite 是 give 下的 literal，而非顶层子命令（26.2 实测）
        out = f"/effect give {targets or '@s'} " \
              f"{_rid(eff or 'speed', ns_prefix)} infinite"
        # [amplifier, hideParticles]
        vals = _positional([params.get("amplifier"), hide_v], [0, "false"])
    else:
        # [seconds, amplifier, hideParticles]
        vals = _positional([params.get("seconds"), params.get("amplifier"),
                            hide_v], [1, 0, "false"])

    for v in vals:
        out += f" {int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v}"
    return out


# ---------------------------------------------------------------------------
# setblock（SetBlockCommand.java L27-95）
# ---------------------------------------------------------------------------

SETBLOCK_MODES = ["replace", "destroy", "keep", "strict"]


def setblock(params: dict, version_key: str = "1.21.11") -> str:
    """`/setblock <pos> <block> [destroy|keep|replace|strict]`

    四种模式互斥，等价于同一个 mode 枚举（L46/59/72/85）。
    replace 是默认，显式写出也合法。
    """
    ns_prefix = params.get("ns_prefix", True)
    pos = params.get("pos") or "~ ~ ~"
    block = params.get("block") or "stone"
    mode = params.get("mode") or "replace"
    out = f"/setblock {pos} {_block(block, ns_prefix)}"
    if mode != "replace":
        out += f" {mode}"
    return out


def _block(spec: str, ns_prefix: bool = True) -> str:
    """方块参数：`id[state=value,...]`。

    spec 形如 `oak_stairs[facing=north,half=top]`；只对 id 部分做
    命名空间处理，方括号内容原样保留（状态名不带命名空间）。
    """
    spec = (spec or "").strip()
    if "[" in spec:
        bid, _, rest = spec.partition("[")
        return _rid(bid.strip(), ns_prefix) + "[" + rest
    return _rid(spec, ns_prefix)


# ---------------------------------------------------------------------------
# fill（FillCommand.java L39-190）
# ---------------------------------------------------------------------------

FILL_MODES = ["replace", "keep", "outline", "hollow", "destroy", "strict"]


def fill(params: dict, version_key: str = "1.21.11") -> str:
    """`/fill <from> <to> <block> [replace|keep|outline|hollow|destroy|strict]`

    结构细节（源码依据）：
      - 基础形式 `<from> <to> <block>`（wrapWithMode 的 executes，L108）
      - `replace [filter]`：filter 可选，L71
      - `keep` / `outline` / `hollow` / `destroy` / `strict` 为
        wrapWithMode 内的同级 literal（L80/L119/L132/L145/L158）
    """
    ns_prefix = params.get("ns_prefix", True)
    frm = params.get("from") or "~ ~ ~"
    to = params.get("to") or "~ ~ ~"
    block = params.get("block") or "stone"
    mode = params.get("mode") or "replace"
    filt = (params.get("filter") or "").strip()

    out = f"/fill {frm} {to} {_block(block, ns_prefix)}"
    if mode == "replace":
        if filt:
            out += f" replace {filt}"
    else:
        out += f" {mode}"
    return out


# ---------------------------------------------------------------------------
# summon（SummonCommand.java L38-70）
# ---------------------------------------------------------------------------

def summon(params: dict, version_key: str = "1.21.11") -> str:
    """`/summon <entity> [pos] [nbt]`

    - entity 必填；pos 省略时默认在命令执行位置（L43）
    - nbt 是 CompoundTag，省略时无额外数据（L54）
    """
    ns_prefix = params.get("ns_prefix", True)
    ent = params.get("entity") or "pig"
    pos = (params.get("pos") or "").strip()
    nbt = (params.get("nbt") or "").strip()

    out = f"/summon {_rid(ent, ns_prefix)}"
    if pos:
        out += f" {pos}"
    if nbt:
        if not pos:
            out += " ~ ~ ~"          # nbt 需 pos 占位
        out += f" {nbt}"
    return out


# ---------------------------------------------------------------------------
# locate（LocateCommand.java L57-90）
# ---------------------------------------------------------------------------

LOCATE_BRANCHES = ["structure", "biome", "poi"]


def locate(params: dict, version_key: str = "1.21.11") -> str:
    """`/locate <structure|biome|poi> <目标>`

    - structure: `ResourceOrTagKeyArgument`（L63）—— 可给 `#标签`
    - biome:     `ResourceOrTagArgument`（L75）—— 可给 `#标签`
    - poi:       兴趣点类型（L84）
    """
    ns_prefix = params.get("ns_prefix", True)
    branch = params.get("branch") or "structure"
    target = (params.get("target") or "").strip()
    if not target:
        # 兜底按分支取对应类型的合法 id（26.2 实测：poi 用 plains 会
        # 报 Can't find element —— POI 与群系是两个注册表）
        target = ("village_plains" if branch == "structure"
                  else "armorer" if branch == "poi" else "plains")
    # 标签（# 开头）不加命名空间前缀，其余按资源 id 处理
    if target.startswith("#"):
        tgt = target
    else:
        tgt = _rid(target, ns_prefix)
    return f"/locate {branch} {tgt}"


# ---------------------------------------------------------------------------
# 分派
# ---------------------------------------------------------------------------

SERIALIZERS = {
    "kill": kill,
    "enchant": enchant,
    "effect": effect,
    "setblock": setblock,
    "fill": fill,
    "summon": summon,
    "locate": locate,
}


def serialize(cmd: str, params: dict,
              version_key: str = "1.21.11") -> str:
    """按指令名分派。未实现的指令返回提示文本。

    give 走专用的 give.give()（数据组件 + 版本分支，形态与其它指令
    不同）；其余按三张 SERIALIZERS 表分派。
    """
    if cmd == "give":
        from Utils.CommandGenerator import give as G
        return G.give(params, version_key)
    from Utils.CommandGenerator import commands2 as K2
    from Utils.CommandGenerator import commands3 as K3
    fn = (SERIALIZERS.get(cmd) or K2.SERIALIZERS.get(cmd)
          or K3.SERIALIZERS.get(cmd))
    if fn is None:
        return f"（{cmd} 尚未实现）"
    return fn(params, version_key)
