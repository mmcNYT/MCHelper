# -*- coding: utf-8 -*-
"""目标选择器参数定义。

Minecraft 目标选择器语法：
  @p / @a / @e / @r / @s  +  可选参数
  参数格式：key=value 或 key=min..max

本模块定义所有可选参数及其合法值，供 TargetSelectorBuilder 使用。
"""

from __future__ import annotations

# 选择器类型
SELECTOR_TYPES = [
    ("@p 最近玩家", "@p"),
    ("@a 所有玩家", "@a"),
    ("@e 所有实体", "@e"),
    ("@r 随机玩家", "@r"),
    ("@s 自身", "@s"),
]

# 参数定义：(key, label, kind, default, extra)
# kind: text / int / float / enum / distance / range
SELECTOR_ARGS = [
    # 实体筛选
    ("type", "实体类型", "entity", None,
     {"hint": "仅选该类型实体；可加 ! 前缀排除"}),
    ("name", "名字", "text", None,
     {"hint": "精确匹配名字（支持通配符 *）"}),
    ("tag", "标签", "text", None,
     {"hint": "仅选带该标签的实体"}),
    ("team", "队伍", "text", None,
     {"hint": "仅选该队伍的玩家"}),
    # 位置筛选
    ("x", "X 坐标", "int", None,
     {"hint": "X 坐标（与 dx/dy/dz 配合使用）"}),
    ("y", "Y 坐标", "int", None,
     {"hint": "Y 坐标"}),
    ("z", "Z 坐标", "int", None,
     {"hint": "Z 坐标"}),
    ("dx", "X 范围", "int", None,
     {"hint": "X 方向范围（从 x 到 x+dx）"}),
    ("dy", "Y 范围", "int", None,
     {"hint": "Y 方向范围"}),
    ("dz", "Z 范围", "int", None,
     {"hint": "Z 方向范围"}),
    ("distance", "距离", "range", None,
     {"hint": "距离范围，如 5..10（5~10 格）"}),
    ("r", "最大距离", "float", None,
     {"hint": "最大距离（格）；与 @p 配合"}),
    ("rm", "最小距离", "float", None,
     {"hint": "最小距离（格）"}),
    # 玩家专属
    ("level", "经验等级", "range", None,
     {"hint": "经验等级范围，如 5..10"}),
    ("gamemode", "游戏模式", "enum", None,
     {"choices": ["survival", "creative", "adventure", "spectator"],
      "hint": "游戏模式"}),
    ("sort", "排序方式", "enum", "arbitrary",
     {"choices": ["arbitrary", "nearest", "furthest", "random"],
      "hint": "结果排序方式"}),
    ("limit", "数量限制", "int", None,
     {"hint": "最多选多少个"}),
    # 高级
    ("predicate", "谓词", "text", None,
     {"hint": "数据包谓词 id"}),
    ("scores", "记分板", "text", None,
     {"hint": "记分板条件，如 {obj:1..}"}),
]

# 参数对选择器类型的适用性（游戏实际规则）：
#   - type 仅 @e 有意义（其他选择器本身就是玩家/自己）
#   - level/gamemode 仅玩家类选择器（@a/@p/@r）有效；@s 是自己也可
#   - limit 对 @s 无意义（只选自己一个）
#   - sort 对 @s 无意义
# 未列出的参数默认全选择器可用。
_ARG_SELECTORS = {
    "type": {"@e"},                     # 仅实体选择器
    "level": {"@a", "@p", "@r", "@s"},
    "gamemode": {"@a", "@p", "@r", "@s"},
    "limit": {"@a", "@p", "@r", "@e"},  # @s 除外
    "sort": {"@a", "@p", "@r", "@e"},   # @s 除外
    "team": {"@a", "@p", "@r", "@s"},   # 队伍仅玩家
}


def args_for_selector(selector: str) -> list:
    """该选择器类型下**有效**的参数定义列表（SELECTOR_ARGS 子集）。

    过滤规则见 _ARG_SELECTORS；未受限的参数全部返回。
    """
    return [a for a in SELECTOR_ARGS
            if _ARG_SELECTORS.get(a[0], None) is None
            or selector in _ARG_SELECTORS[a[0]]]

# 预设（常用选择器，一键插入）
PRESETS = [
    ("@p 最近玩家", "@p"),
    ("@a 所有玩家", "@a"),
    ("@e 所有实体", "@e"),
    ("@r 随机玩家", "@r"),
    ("@s 自身", "@s"),
    ("@p 最近玩家（10 格内）", "@p[r=10]"),
    ("@a 所有玩家（10 格内）", "@a[r=10]"),
    ("@e 所有僵尸", "@e[type=zombie]"),
    ("@e 所有村民", "@e[type=villager]"),
    ("@e 所有物品", "@e[type=item]"),
    ("@e 所有箭", "@e[type=arrow]"),
    ("@a 创造模式玩家", "@a[gamemode=creative]"),
    ("@a 生存模式玩家", "@a[gamemode=survival]"),
    ("@a 5~10 级玩家", "@a[level=5..10]"),
    ("@a 距离 5~10 格", "@a[distance=5..10]"),
    ("@e 10 格内僵尸", "@e[type=zombie,distance=..10]"),
    ("@p 坐标 (0,64,0) 10 格内", "@p[x=0,y=64,z=0,r=10]"),
    ("@e 区域内所有实体", "@e[x=0,y=64,z=0,dx=10,dy=10,dz=10]"),
]


def parse_selector(text: str) -> tuple[str, dict]:
    """解析选择器文本 -> (selector, args_dict)。

    例："@e[type=zombie,distance=..10]" -> ("@e", {"type": "zombie", "distance": "..10"})
    """
    text = text.strip()
    if not text or text[0] != "@":
        return text, {}
    # 找第一个 [
    i = text.find("[")
    if i < 0:
        return text, {}
    selector = text[:i]
    inner = text[i + 1:].rstrip("]")
    args = {}
    for pair in inner.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        args[k.strip()] = v.strip()
    return selector, args


def build_selector(selector: str, args: dict) -> str:
    """(selector, args_dict) -> 选择器文本。

    参数按固定顺序排列，与官方文档一致。
    """
    if not args:
        return selector
    # 按官方文档顺序排列参数
    order = ["x", "y", "z", "dx", "dy", "dz", "r", "rm", "distance",
             "type", "name", "tag", "team", "level", "gamemode",
             "sort", "limit", "predicate", "scores"]
    parts = []
    for k in order:
        if k in args:
            v = args[k]
            if v is not None and v != "":
                parts.append(f"{k}={v}")
    for k, v in args.items():
        if k not in order and v is not None and v != "":
            parts.append(f"{k}={v}")
    return f"{selector}[{','.join(parts)}]"
