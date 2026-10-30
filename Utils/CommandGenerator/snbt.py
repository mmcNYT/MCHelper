# -*- coding: utf-8 -*-
"""CommandGenerator：SNBT 文本组件与 SNBT 值序列化原语。

Minecraft 1.20.5+ 的 `/give` 使用**数据组件**语法：

    /give @p minecraft:diamond_sword[
        minecraft:enchantments={levels:{"minecraft:sharpness":5}},
        minecraft:custom_name='"屠龙宝刀"'
    ] 1

其中括号内是 **SNBT**（字符串化 NBT）。本模块只做「Python 值 -> SNBT
文本」的纯函数转换，不依赖 Qt、不依赖项目其他模块，便于单测。

关键语法要点（1.21.11 GiveCommand + ItemStack.CODEC 实证）：
  - 组件列表用 `[...]`，逗号分隔，**不能有空格**（官方解析器容忍，
    但习惯紧凑）；
  - 组件 id 可省略 `minecraft:` 前缀；
  - **文本组件**（custom_name/lore/item_name）的值是「JSON 文本组件
    的 SNBT 表示」：纯文本要写成 `'"文字"'`（即含引号的字符串），
    带样式则写成 `{text:"...",color:"gold",bold:true}`；
  - **附魔**是 `{levels:{"minecraft:sharpness":5}}`（levels 是映射）；
  - 字符串在 SNBT 里用**双引号**，内部双引号用 `\\"` 转义。

SNBT 数字后缀（NBT 规范）：
    b=byte  s=short  L=long  f=float  d=double；int 无后缀。
"""
from __future__ import annotations


class RawSnbt(str):
    """标记「已是合法 SNBT 文本，直接写入、不得再转义」。

    用于 json 类组件的兜底编辑器：用户在文本框里写的
    `{level:1}` / `[1,2]` / `7` 已是 SNBT，若再当普通字符串
    加引号就会变成 `"{level:1}"`（类型错误）。

    str 子类，故可安全放进 dict / 做字符串比较。
    """

    __slots__ = ()

# ---------------------------------------------------------------------------
# SNBT 标量
# ---------------------------------------------------------------------------

# SNBT 中无需引号的「安全」字符：字母数字与少量符号。
# 其余（含空格、中文、冒号以外的符号）一律加双引号。
_SAFE = set("abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789_-.+")


def snbt_string(s: str) -> str:
    """Python 字符串 -> SNBT 字符串字面量（总是加双引号）。

    总是加引号是刻意的：`"5"` 与 `5` 在 SNBT 里类型不同，而组件值
    常需精确控制（如 custom_model_data 的 string 分支）。
    """
    out = s.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + out + '"'


def snbt_key(s: str) -> str:
    """映射键 -> SNBT 键文本。

    **含冒号的键必须加引号**：SNBT 的未引号字符串规则
    （SnbtGrammar.PLAIN_STRING_CHUNK）贪婪且允许 `:`，故
    `{minecraft:sharpness:5}` 里的键会一路吃到行尾而无法定位
    分隔冒号。附魔/属性等资源 id 键因此统一加引号：
        {levels:{"minecraft:sharpness":5}}
    仅字母数字与 `_-.+` 的键才裸写（如 {text:"..."}）。
    """
    if s and all(c in _SAFE for c in s):
        return s
    return snbt_string(s)


def snbt_int(v: int) -> str:
    return str(int(v))


def snbt_byte(v: int) -> str:
    return f"{int(v)}b"


def snbt_short(v: int) -> str:
    return f"{int(v)}s"


def snbt_long(v: int) -> str:
    return f"{int(v)}L"


def snbt_float(v: float) -> str:
    return f"{float(v)}f"


def snbt_double(v: float) -> str:
    return f"{float(v)}d"


def snbt_bool(v: bool) -> str:
    """SNBT 布尔 -> byte（1b/0b）。1.20.5+ 组件里布尔即 byte。"""
    return "1b" if v else "0b"


# ---------------------------------------------------------------------------
# SNBT 复合结构
# ---------------------------------------------------------------------------

def snbt_list(items: list) -> str:
    """Python list -> SNBT 列表 `[a,b,c]`（元素已序列化为 SNBT 文本）。"""
    return "[" + ",".join(items) + "]"


def snbt_compound(pairs: list) -> str:
    """[(key, snbt_value_text), ...] -> SNBT 复合 `{k:v,...}`。

    值为 None 的项被跳过（便于可选字段）。
    """
    body = ",".join(f"{snbt_key(k)}:{v}" for k, v in pairs
                    if v is not None)
    return "{" + body + "}"


def snbt_map(mapping: dict, value_fn=None) -> str:
    """Python dict -> SNBT 复合（键按插入序；value_fn 定制值序列化）。"""
    pairs = []
    for k, v in mapping.items():
        pairs.append((str(k), value_fn(v) if value_fn else snbt_any(v)))
    return snbt_compound(pairs)


def snbt_any(v) -> str:
    """通用 Python 值 -> SNBT 文本（自动按类型分派）。

    注意：**bool 必须早于 int 判断**（Python 里 bool 是 int 子类）。
    """
    if v is None:
        return "null"            # 极少用；占位保证不抛错
    if isinstance(v, bool):
        return snbt_bool(v)
    if isinstance(v, int):
        return snbt_int(v)
    if isinstance(v, float):
        return snbt_double(v)
    if isinstance(v, str):
        return snbt_string(v)
    if isinstance(v, (list, tuple)):
        return snbt_list([snbt_any(x) for x in v])
    if isinstance(v, dict):
        return snbt_map(v)
    return snbt_string(str(v))


# ---------------------------------------------------------------------------
# 文本组件（JSON 文本组件的 SNBT 表示）
# ---------------------------------------------------------------------------

import json


def _json_dump(obj) -> str:
    """严格 JSON 序列化（键带引号、无空格、非 ASCII 不转义）。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def text_component(text: str = "", color: str | None = None,
                   bold: bool = False, italic: bool = False,
                   underlined: bool = False, strikethrough: bool = False,
                   obfuscated: bool = False,
                   click: tuple | None = None,
                   hover: tuple | None = None,
                   version_key: str = "1.21.11") -> str:
    """文本 -> 组件 SNBT（供 custom_name / item_name / lore 用）。

    无任何样式时输出**裸 SNBT 字符串** `"文字"`：这正是官方
    `ComponentArgument.EXAMPLES` 的首项形式（`"hello world"`），
    因为组件编解码用 `ComponentSerialization.CODEC`
    = `either(STRING, list, compound)` 配 NbtOps，纯文本走 STRING 分支。

    有样式时输出复合 `{text:"文字",color:"gold",bold:1b}`。

    **注意不要写成 `'"文字"'`**：那是「内容是带引号的字符串」，游戏内
    会把引号一起显示出来。

    click/hover = (action, value)，如 ("run_command", "say hi")。

    **1.21（data version < 4307）**：custom_name / item_name / lore 等
    组件值的文本组件走 **stringified** 编码（1.21 服务器 RCON 实测：
    对象形报 Malformed 'Not a string'，probe_v121/b_out.txt）——
    组件值必须是 JSON 字符串字面量，其内容才是组件的严格 JSON：
        纯文本：  "\"测试甲\""
        带样式：  "{\"text\":\"中文甲\"}"
    内容必须严格 JSON（键带引号、布尔 true/false、无 SNBT 后缀），
    否则 Gson 报 MalformedJsonException（如 lore=["L2 raw"]）。
    """
    if version_key == "1.21":
        obj = {"text": text}
        if color:
            obj["color"] = color
        for name, on in (("bold", bold), ("italic", italic),
                         ("underlined", underlined),
                         ("strikethrough", strikethrough),
                         ("obfuscated", obfuscated)):
            if on:
                obj[name] = True
        if click:
            obj["clickEvent"] = {"action": click[0], "value": click[1]}
        if hover:
            obj["hoverEvent"] = {"action": hover[0],
                                 "contents": hover[1]}
        if list(obj) == ["text"]:
            # 纯文本：内容就是 JSON 字符串
            inner = _json_dump(text)
        else:
            inner = _json_dump(obj)
        # 外层再套一层 JSON 字符串字面量（stringified）
        return json.dumps(inner, ensure_ascii=False)
    styles = []
    if color:
        styles.append(("color", snbt_string(color)))
    for name, on in (("bold", bold), ("italic", italic),
                     ("underlined", underlined),
                     ("strikethrough", strikethrough),
                     ("obfuscated", obfuscated)):
        if on:
            styles.append((name, snbt_bool(True)))
    if click:
        styles.append(("clickEvent", snbt_compound([
            ("action", snbt_string(click[0])),
            ("value", snbt_string(click[1])),
        ])))
    if hover:
        styles.append(("hoverEvent", snbt_compound([
            ("action", snbt_string(hover[0])),
            ("contents", snbt_string(hover[1])),
        ])))
    if not styles:
        return snbt_string(text)
    pairs = [("text", snbt_string(text))] + styles
    return snbt_compound(pairs)


def component_value(v, version_key: str = "1.21.11") -> str:
    """组件值分派：str = 纯文本 / dict = 结构化样式 / 其他原样。

    UI 层两种传法：
        "屠龙宝刀"                                   -> 纯文本
        {"text": "宝刀", "color": "gold"}            -> 带样式
    """
    if isinstance(v, str):
        return text_component(v, version_key=version_key)
    if isinstance(v, dict):
        return text_component(**v, version_key=version_key)
    return str(v)


def text_component_lines(lines: list, version_key: str = "1.21.11") -> str:
    """多行文本（lore）-> SNBT 列表 `["行1","行2"]`。

    每行可为 str（纯文本）、dict（结构化样式）或已序列化的组件 SNBT。
    1.21 走 stringified（见 text_component 说明）。
    """
    return snbt_list([component_value(ln, version_key)
                      for ln in lines])


# ---------------------------------------------------------------------------
# 物品与资源 id
# ---------------------------------------------------------------------------

def res_id(name: str, ns_prefix: bool = True,
           default_ns: str = "minecraft") -> str:
    """资源 id 规范化。

    ns_prefix=False 时省略 `minecraft:` 前缀（官方解析器默认补
    minecraft，输出更短）；显式带其他命名空间时不省略。
    """
    if ":" in name:
        ns, _, path = name.partition(":")
        if ns == default_ns and not ns_prefix:
            return path
        return name
    return f"{default_ns}:{name}" if ns_prefix else name
