# -*- coding: utf-8 -*-
"""CommandGenerator：指令序列化（纯函数，无 Qt 依赖）。

设计：**Python 参数字典 -> 指令文本**。UI 层只负责填 dict，
本模块负责产出正确文本，便于单测。

当前实现 `/give`。

版本差异（源码 + jar 实证，见 Docs/CODEBASE.md）：
  - **data version >= 4307（1.21.11 / 26.2）**：
        minecraft:enchantments={"minecraft:sharpness":5}      裸映射
  - **data version < 4307（1.21 = 3953）**：
        minecraft:enchantments={levels:{"minecraft:sharpness":5}}
    依据：ItemEnchantments.CODEC = Codec.unboundedMap(...) 为当前格式；
    TooltipDisplayComponentFix(schema 4307) 执行
    fixComponentAndUnwrap(..., "enchantments", "levels", ...) 把
    levels 键剥掉 -> 4307 之前才是包装格式。

文本组件：ComponentArgument 直接用 ComponentSerialization.CODEC
（either(STRING, list, compound)），故纯文本可写 SNBT 字符串
`"文字"`，带样式写 `{text:"文字",color:"gold"}`。

**1.21（data version < 4307）例外（RCON 实测，probe_v121*.txt）：**
  - custom_name / item_name / lore 的组件值走 **stringified**
    （组件值 = JSON 字符串字面量，内容 = 严格 JSON 组件），
    对象形报 Malformed 'Not a string'（snbt.text_component 分支）；
  - attribute_modifiers 的 type 字段需类别前缀
    （generic./player./zombie.，commands2.attr_id_121）；
  - enchantments 等包装组件由 ench_wrapped() 处理（实测裸映射
    亦可通过，但包装形更符合 1.21 规范，保留分支）。
"""
from __future__ import annotations

import re

from . import snbt

# 各支持版本的 data version（SharedConstants.WORLD_VERSION / jar
# version.json 实测）
DATA_VERSIONS = {"1.21": 3953, "1.21.11": 4671, "26.2": 4903}

# 组件包装键被剥离的 schema 分界（TooltipDisplayComponentFix 引入）
#
# 实证链（勿凭记忆改动）：
#   1) ItemEnchantments.CODEC = Codec.unboundedMap(Enchantment.CODEC,
#      LEVEL_CODEC)  -> **裸映射**，无 levels 包装（1.21.11 反编译 L33）
#   2) TooltipDisplayComponentFix（DataFixers schema 4307）执行
#        fixComponentAndUnwrap($$1x, "minecraft:enchantments", "levels", ...)
#      ——unwrap 即「把 levels 键剥掉」-> 4307 **之前**才是
#      {levels:{...}}，4307 起为裸映射。
#   3) 版本 data version：1.21=3953（<4307，包装）、
#      1.21.11=4671、26.2=4903（均 >=4307，裸映射）。
#   4) 26.2 未混淆 jar 直接验证：ItemEnchantments.class 内
#      **不含** b"levels"，而两个 datafixer 内均含（对照成立）。
_SCHEMA_FLATTENED = 4307


def data_version(version_key: str) -> int:
    """版本键 -> data version（未知版本回退到最新语义）。"""
    return DATA_VERSIONS.get(version_key, max(DATA_VERSIONS.values()))


def ench_wrapped(version_key: str) -> bool:
    """该版本是否使用**包装复合**形态（4307 之前为 True）。

    适用于 `_UNWRAPPED` 里的全部 5 个组件，不只是 enchantments。
    """
    return data_version(version_key) < _SCHEMA_FLATTENED


# ---------------------------------------------------------------------------
# schema 4307 的 5 个「解包」组件
#
# TooltipDisplayComponentFix（DataFixers schema 4307）对它们各调用一次
# fixComponentAndUnwrap（源码 L63-67）：
#     dyed_color           unwrap "rgb"
#     attribute_modifiers  unwrap "modifiers"
#     enchantments         unwrap "levels"
#     stored_enchantments  unwrap "levels"
#     jukebox_playable     unwrap "song"
# unwrap 即「把包装键剥掉」，故：
#     data version <  4307（1.21 = 3953）    -> 包装复合 {key:值}
#     data version >= 4307（1.21.11/26.2）   -> **裸值**
# 各组件自身 CODEC 印证裸值形态：
#     DyedItemColor.CODEC        = RGB_COLOR_CODEC.xmap(...)      裸整数
#     ItemAttributeModifiers.CODEC = Entry.CODEC.listOf().xmap(...) 裸列表
#     ItemEnchantments.CODEC     = unboundedMap(...)              裸映射
#     JukeboxPlayable.CODEC      = EitherHolder.codec(...)        裸 holder
# ---------------------------------------------------------------------------
_UNWRAPPED = {
    "dyed_color": "rgb",
    "attribute_modifiers": "modifiers",
    "enchantments": "levels",
    "stored_enchantments": "levels",
    "jukebox_playable": "song",
}


def comp_id(name: str, ns_prefix: bool = True) -> str:
    """组件 id。"""
    return snbt.res_id(name, ns_prefix)


def _enchantments_component(enchants: dict, version_key: str,
                            ns_prefix: bool) -> str:
    """附魔映射 -> 组件值文本（按版本决定是否 levels 包装）。

    enchants: {"sharpness": 5, "fire_aspect": 2}
    """
    pairs = [(snbt.res_id(k, ns_prefix), snbt.snbt_int(v))
             for k, v in enchants.items() if v]
    inner = snbt.snbt_compound(pairs)
    if ench_wrapped(version_key):
        return snbt.snbt_compound([("levels", inner)])
    return inner


def _wrap_if_needed(name: str, bare: str, version_key: str) -> str:
    """按版本给「解包组件」的裸值加回包装键（仅 4307 之前的版本）。"""
    key = _UNWRAPPED.get(name)
    if key and ench_wrapped(version_key):
        return snbt.snbt_compound([(key, bare)])
    return bare


def _plain_scalar(comp: str, value) -> str:
    """按组件类型序列化标量值。"""
    if isinstance(value, snbt.RawSnbt):
        return str(value)                 # 已是 SNBT，直写
    if isinstance(value, bool):
        return snbt.snbt_bool(value)
    if isinstance(value, int):
        return snbt.snbt_int(value)
    if isinstance(value, float):
        return snbt.snbt_double(value)
    if isinstance(value, str):
        return snbt.snbt_string(value)
    if isinstance(value, (list, dict)):
        return snbt.snbt_any(value)
    return snbt.snbt_string(str(value))


def serialize_component(name: str, value, version_key: str = "1.21.11",
                        ns_prefix: bool = True) -> str:
    """单个组件 -> `id=值` 文本。

    特例处理（其余按通用规则）：
      - enchantments / stored_enchantments：按版本包装 levels；
      - custom_name / item_name：文本组件（可传 str 或组件 SNBT）；
      - lore：文本组件列表（可传 [str, ...]）；
      - unbreakable：`{}`（空复合，非 bool）；
      - **解包组件**（`dyed_color` / `attribute_modifiers` /
        `enchantments` / `stored_enchantments` / `jukebox_playable`）：
        4307+ 输出裸值，1.21 加回包装键（见 `_UNWRAPPED` 说明）。
    """
    cid = comp_id(name, ns_prefix)

    # 兜底编辑器给的原始 SNBT：直写（含 json 类组件）
    if isinstance(value, snbt.RawSnbt):
        return f"{cid}={value}"

    if name in ("enchantments", "stored_enchantments"):
        return f"{cid}={_enchantments_component(value, version_key, ns_prefix)}"

    if name in ("custom_name", "item_name"):
        # str -> 纯文本组件；dict -> 带样式组件
        # 1.21 为 stringified JSON（见 snbt.text_component）
        return f"{cid}={snbt.component_value(value, version_key)}"

    if name == "lore":
        return f"{cid}={snbt.text_component_lines(list(value), version_key)}"

    if name == "unbreakable":
        # 官方组件值是**空复合** {}（不是 bool）
        return cid + "={}"

    # 其余 unit 类组件（glider / creative_slot_lock / intangible_projectile…）
    # 值同样是空复合 {}
    if isinstance(value, dict) and not value:
        from Utils.CommandGenerator import components as _C2
        if _C2.kind_of(name) == "unit":
            return cid + "={}"

    if name == "tooltip_display":
        # {"hide_tooltip":1b,"hidden_components":[...]}
        return f"{cid}={snbt.snbt_any(value)}"

    if name == "custom_model_data":
        # 1.21.4+ 为 {floats:[...],strings:[...],flags:[...]} 复合
        if isinstance(value, int):
            return f"{cid}=" + snbt.snbt_compound(
                [("floats", snbt.snbt_list([snbt.snbt_float(value)]))])
        return f"{cid}={snbt.snbt_any(value)}"

    if name == "dyed_color":
        # 4307+ 为**裸整数**（RGB_COLOR_CODEC.xmap）；1.21 用 {rgb:N}
        bare = snbt.snbt_int(value) if isinstance(value, int) \
            else snbt.snbt_any(value)
        return f"{cid}={_wrap_if_needed(name, bare, version_key)}"

    if name == "attribute_modifiers":
        # 4307+ 为**裸列表**（Entry.CODEC.listOf()）；1.21 用 {modifiers:[...]}
        # Entry 的字段（ItemAttributeModifiers.java L38 附近）：
        #   type  : 属性 id
        #   id    : 修饰符 id
        #   amount: 数值
        #   operation: add_value / add_multiplied_base / add_multiplied_total
        #   slot  : any/mainhand/...（可选，默认 any）
        if version_key == "1.21":
            from Utils.CommandGenerator import commands2 as _K2
        mods = []
        for m in value:
            pairs = []
            if m.get("id"):
                pairs.append(("id", snbt.snbt_string(m["id"])))
            if m.get("type"):
                tname = snbt.res_id(m["type"], ns_prefix)
                if version_key == "1.21":
                    # 1.21 组件内 type 同样需类别前缀（实测裸 id 报
                    # Unknown registry key）；不存在的属性丢弃该条目
                    t121 = _K2.attr_id_121(tname)
                    if t121 is None:
                        continue
                    tname = t121 if ns_prefix \
                        else t121.removeprefix("minecraft:")
                pairs.append(("type", snbt.snbt_string(tname)))
            if m.get("amount") is not None:
                pairs.append(("amount", snbt.snbt_double(m["amount"])))
            if m.get("operation"):
                pairs.append(("operation", snbt.snbt_string(m["operation"])))
            if m.get("slot"):
                pairs.append(("slot", snbt.snbt_string(m["slot"])))
            mods.append(snbt.snbt_compound(pairs))
        bare = snbt.snbt_list(mods)
        return f"{cid}={_wrap_if_needed(name, bare, version_key)}"

    if name == "jukebox_playable":
        # EitherHolder<JukeboxSong>：4307+ 裸值，1.21 用 {song:...}
        bare = value if isinstance(value, snbt.RawSnbt) \
            else snbt.snbt_string(snbt.res_id(str(value), ns_prefix))
        return f"{cid}={_wrap_if_needed(name, bare, version_key)}"

    # ---- ItemStack 列表（bundle_contents / charged_projectiles）----
    # ItemStack.CODEC = {id:Item.CODEC, count:intRange(1,99) 默认 1,
    #                    components?}
    # 元素必须输出 {id:"minecraft:x",count:1}，不能是裸字符串
    # （bundle_contents 的编辑器给 ["diamond",...]，故在此转换）。
    if name in ("bundle_contents", "charged_projectiles") and \
            isinstance(value, list):
        items = []
        for x in value:
            if isinstance(x, dict):
                iid = x.get("id", "")
                cnt = x.get("count", 1)
            else:
                iid, cnt = str(x), 1
            if not iid:
                continue
            items.append(snbt.snbt_compound([
                ("id", snbt.snbt_string(snbt.res_id(iid, ns_prefix))),
                ("count", snbt.snbt_int(cnt)),
            ]))
        return f"{cid}={snbt.snbt_list(items)}"

    # ---- 容器槽位（container）----
    # ItemContainerContents.Slot = {slot:intRange(0,255), item:ItemStack}
    # ItemStack 元素同样要 {id,count} 复合。
    if name == "container" and isinstance(value, list):
        slots = []
        for s in value:
            if not isinstance(s, dict):
                continue
            iid = s.get("item", "")
            if not iid:
                continue
            slots.append(snbt.snbt_compound([
                ("slot", snbt.snbt_int(s.get("slot", 0))),
                ("item", snbt.snbt_compound([
                    ("id", snbt.snbt_string(snbt.res_id(iid, ns_prefix))),
                    ("count", snbt.snbt_int(s.get("count", 1))),
                ])),
            ]))
        return f"{cid}={snbt.snbt_list(slots)}"

    # ---- 迷之炖菜（suspicious_stew_effects）----
    # Entry = {id:MobEffect.CODEC, duration:int 默认 160}
    if name == "suspicious_stew_effects" and isinstance(value, list):
        entries = []
        for e in value:
            if not isinstance(e, dict):
                continue
            fx = e.get("id") or e.get("effect", "")
            if not fx:
                continue
            entries.append(snbt.snbt_compound([
                ("id", snbt.snbt_string(snbt.res_id(fx, ns_prefix))),
                ("duration", snbt.snbt_int(e.get("duration", 160))),
            ]))
        return f"{cid}={snbt.snbt_list(entries)}"

    # ---- 旗帜图案（banner_patterns）----
    # Layer = {pattern:BannerPattern.CODEC, color:DyeColor.CODEC}
    if name == "banner_patterns" and isinstance(value, list):
        layers = []
        for l in value:
            if not isinstance(l, dict):
                continue
            pat = l.get("pattern", "")
            if not pat:
                continue
            layers.append(snbt.snbt_compound([
                ("pattern", snbt.snbt_string(snbt.res_id(pat, ns_prefix))),
                ("color", snbt.snbt_string(l.get("color", "white"))),
            ]))
        return f"{cid}={snbt.snbt_list(layers)}"

    # ---- 药水内容（potion_contents）----
    # FULL_CODEC = {potion:Holder, custom_color:int, custom_name:string,
    #               custom_effects:list}（均可选）
    if name == "potion_contents" and isinstance(value, dict):
        pairs = []
        if value.get("potion"):
            pairs.append(("potion", snbt.snbt_string(
                snbt.res_id(value["potion"], ns_prefix))))
        if value.get("custom_color") is not None:
            pairs.append(("custom_color",
                          snbt.snbt_int(value["custom_color"])))
        if value.get("custom_name"):
            pairs.append(("custom_name", snbt.snbt_string(
                value["custom_name"])))
        return f"{cid}={snbt.snbt_compound(pairs)}"

    # ---- 饰纹陶罐（pot_decorations）----
    # PotDecorations.CODEC = BuiltInRegistries.ITEM.byNameCodec()
    #                        .sizeLimitedListOf(4)
    # 元素是 **Item id 字符串**（非 ItemStack 复合），需命名空间。
    if name == "pot_decorations" and isinstance(value, list):
        return f"{cid}={snbt.snbt_list([snbt.snbt_string(snbt.res_id(str(x), ns_prefix)) for x in value])}"

    # ---- 地图标记（map_decorations）----
    # Map<id, Decoration{type,x,z,rotation}>（x/z 为 double，rotation float）
    # 值是普通复合，故用 `{key={...}}` 而非 `{key:{...}}` 形式上的区别
    # 仅在引号与否 —— 键若含非法字符需引号（snbt_key 已处理）。
    if name == "map_decorations" and isinstance(value, dict):
        outer = []
        for did, d in value.items():
            if not isinstance(d, dict):
                continue
            outer.append((did, snbt.snbt_compound([
                ("type", snbt.snbt_string(d.get("type", "player"))),
                ("x", snbt.snbt_double(d.get("x", 0.0))),
                ("z", snbt.snbt_double(d.get("z", 0.0))),
                ("rotation", snbt.snbt_double(d.get("rotation", 0.0))),
            ])))
        return f"{cid}={snbt.snbt_compound(outer)}"

    # ---- 方块状态（block_state）----
    # BlockItemStateProperties = Map<String,String>（值是**字符串**）
    if name == "block_state" and isinstance(value, dict):
        pairs = [(str(k), snbt.snbt_string(str(v)))
                 for k, v in value.items()]
        return f"{cid}={snbt.snbt_compound(pairs)}"

    # ---- 锁（lock）----
    # LockCode.CODEC = ItemPredicate.CODEC.xmap(...)；
    # ItemPredicate 接受**裸物品 id 字符串**简写
    if name == "lock" and isinstance(value, str):
        return f"{cid}={snbt.snbt_string(snbt.res_id(value, ns_prefix))}"

    # ---- 头颅皮肤（profile）----
    # withAlternative(FULL_CODEC, PLAYER_NAME, createUnresolved)
    # -> 最简形式是**裸玩家名字符串**；含 UUID 时输出 {name,id}
    if name == "profile":
        if isinstance(value, str):
            return f"{cid}={snbt.snbt_string(value)}"
        if isinstance(value, dict):
            pairs = []
            if value.get("name"):
                pairs.append(("name", snbt.snbt_string(value["name"])))
            if value.get("id"):
                pairs.append(("id", snbt.snbt_string(value["id"])))
            return f"{cid}={snbt.snbt_compound(pairs)}"

    # ---- 使用后剩余物（use_remainder）----
    # UseRemainder.CODEC = ItemStack.CODEC.xmap(...) -> 裸 ItemStack
    if name == "use_remainder" and isinstance(value, dict):
        iid = value.get("id", "")
        if not iid:
            return f"{cid}=" + snbt.snbt_compound([])
        return f"{cid}={snbt.snbt_compound([
            ('id', snbt.snbt_string(snbt.res_id(iid, ns_prefix))),
            ('count', snbt.snbt_int(value.get('count', 1))),
        ])}"

    # ---- 可破坏 / 可放置（can_break / can_place_on）----
    # AdventureModePredicate.CODEC = compactListCodec(BlockPredicate,
    #   nonEmptyList(BlockPredicate.listOf())) -> 元素是 BlockPredicate；
    # 最简 BlockPredicate 是**裸方块 id 字符串**或 #tag
    if name in ("can_break", "can_place_on") and isinstance(value, list):
        preds = []
        for x in value:
            t = str(x).strip()
            if not t:
                continue
            # #标签原样；方块 id 加命名空间；含 [状态] 的拆开处理
            if t.startswith("#"):
                preds.append(snbt.snbt_string(t))
            elif "[" in t:
                bid, _, rest = t.partition("[")
                preds.append(snbt.snbt_string(
                    snbt.res_id(bid.strip(), ns_prefix)) + "[" + rest)
            else:
                preds.append(snbt.snbt_string(snbt.res_id(t, ns_prefix)))
        # compactListCodec：单元素时允许裸值，但列表形式总是合法
        return f"{cid}={snbt.snbt_list(preds)}"

    # ---- 配方列表（recipes）----
    # List<ResourceKey<Recipe<?>>> -> 字符串列表（键已是完整 id）
    if name == "recipes" and isinstance(value, list):
        return f"{cid}={snbt.snbt_list([snbt.snbt_string(str(x)) for x in value])}"

    # ---- 蜜蜂（bees）----
    # Occupant = {entity_data:{id:...,...}, ticks_in_hive:int}
    if name == "bees" and isinstance(value, list):
        occ = []
        for b in value:
            if not isinstance(b, dict):
                continue
            edata = b.get("entity_data")
            if not isinstance(edata, dict) or not edata.get("id"):
                continue
            # entity_data 是 CustomData：{id:...} 是最小 NBT
            inner = snbt.snbt_compound(
                [(k, snbt.snbt_string(str(v)) if isinstance(v, str)
                  else snbt.snbt_any(v))
                 for k, v in edata.items()])
            occ.append(snbt.snbt_compound([
                ("entity_data", inner),
                ("ticks_in_hive", snbt.snbt_int(
                    b.get("ticks_in_hive", 0))),
            ]))
        return f"{cid}={snbt.snbt_list(occ)}"

    # 通用复合（CompoundEditor 产出 {snake_case键: 值}）：
    # dict -> {k:v,...}，按字段顺序（comp_meta 的声明序）输出更贴近官方
    if isinstance(value, dict):
        return f"{cid}={snbt.snbt_compound(_ordered_pairs(name, value))}"

    return f"{cid}={_plain_scalar(name, value)}"


def _ordered_pairs(name: str, value: dict) -> list:
    """把 {键: 值} 转成 [(键, SNBT 值文本)]，按 comp_meta 字段序排列。

    键名来自 comp_meta（源码 fieldOf 的 snake_case 原文），已是权威
    形态，故**直接作为 SNBT 键**使用（含冒号的资源键会由 snbt_key
    自动加引号）。

    值按该字段的 codec 决定 SNBT 类型：long 需 `L` 后缀
    （如 container_loot 的 seed:0L），否则会被当 int 解析。
    """
    from Utils.CommandGenerator import comp_editors as _CE
    from Utils.CommandGenerator import components as _C
    fmap = {f["key"]: f for f in _C.fields_of(name)}
    order = [f["key"] for f in _C.fields_of(name)]
    keys = [k for k in order if k in value]
    keys += [k for k in value if k not in keys]

    out = []
    for k in keys:
        v = value[k]
        codec = (fmap.get(k) or {}).get("codec", "")
        kk = _CE._codec_kind(codec)
        if kk == "long" and isinstance(v, str):
            # 文本输入：已带后缀则原样，否则补 L
            s = v.strip()
            if s and not s.upper().endswith("L") and re.fullmatch(
                    r"-?[0-9]+", s):
                s += "L"
            out.append((k, snbt.RawSnbt(s) if s else None))
        elif kk == "long" and isinstance(v, int):
            out.append((k, snbt.snbt_long(v)))
        elif kk == "float" and isinstance(v, (int, float)) \
                and not isinstance(v, bool):
            # SNBT 浮点后缀取决于 codec：Codec.FLOAT -> f，DOUBLE/floatRange
            # -> d。写错类型游戏解析会失败（FLOAT 组件不接受 double 标签）
            if re.search(r"Codec\.FLOAT|\bFLOAT\b", codec):
                out.append((k, snbt.snbt_float(v)))
            else:
                out.append((k, snbt.snbt_double(v)))
        else:
            out.append((k, snbt.snbt_any(v)))
    return [(k, t) for k, t in out if t is not None]


def give(params: dict, version_key: str = "1.21.11") -> str:
    """参数 dict -> `/give` 指令文本。

    params:
        targets   : "支持对象"，如 "@p" / "@a[team=red]"（必填）
        item      : 物品 id，如 "diamond_sword"（必填）
        count     : 数量（缺省 1；为 1 时省略）
        components: {"enchantments": {...}, "custom_name": "...", ...}
        ns_prefix : 是否输出 minecraft: 前缀（缺省 True）
    """
    targets = params.get("targets") or "@p"
    item = params.get("item") or "stone"
    count = params.get("count", 1)
    comps = params.get("components") or {}
    ns_prefix = params.get("ns_prefix", True)

    # 组件顺序：按传入序（UI 决定），跳过 None/空/空字符串
    #
    # 注意：**空 dict 不能一律跳过** —— `unbreakable` / `glider` /
    # `creative_slot_lock` 等 unit 类组件的正确值就是 `{}`，跳过会
    # 导致这些开关失效。故只跳过「非 unit 的空 dict」。
    from Utils.CommandGenerator import components as _C
    parts = []
    for name, value in comps.items():
        if value is None or value is False:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, dict) and not value \
                and _C.kind_of(name) != "unit":
            continue
        if isinstance(value, list) and not value:
            continue
        text = serialize_component(name, value, version_key, ns_prefix)
        # 防御：值为空会产生 `minecraft:xxx=`（非法 SNBT），丢弃该组件
        if text.endswith("="):
            continue
        parts.append(text)

    out = f"/give {targets} {snbt.res_id(item, ns_prefix)}"
    if parts:
        out += "[" + ",".join(parts) + "]"
    # 数量：1 可省略；>=2 才写
    try:
        c = int(count)
    except (TypeError, ValueError):
        c = 1
    if c != 1:
        out += f" {c}"
    return out
