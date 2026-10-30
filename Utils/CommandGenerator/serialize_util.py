# -*- coding: utf-8 -*-
"""CommandGenerator：序列化公共工具（三处重复的统一落点）。

此前 _positional/_fmt 在 commands.py / commands2.py / commands3.py
各有一份且语义不一致（commands.py 版只把 None 当未填，另两版把
None+"" 都当未填）。统一为「None 和空串都算未填」：
  - optional 数值/布尔的空值在 params() 已归一为 None；
  - text 类空值归一为 ""（optional=False）；
  两种形态都应视为「未填」，否则 text 空串会顶掉默认值。

三文件统一 `from .serialize_util import fmt as _fmt, positional as _positional`。
"""


def positional(values, defaults):
    """按位补齐可选参数（Brigadier 参数必须从左到右连续）。

    values 为 UI 收集的可选值（None/"" = 未填），defaults 为各自
    默认值。取「最后一个非未填的下标」，把该下标之前的未填位用
    defaults 填充，其后全部丢弃。

    例：values=[None, 2, None], defaults=[1, 0, False]
        -> 最后非未填下标 1 -> 结果 [1, 2]
    """
    last = -1
    for i, v in enumerate(values):
        if v is not None and v != "":
            last = i
    if last < 0:
        return []
    return [(values[i] if values[i] not in (None, "")
             else defaults[i]) for i in range(last + 1)]


def fmt(v):
    """数值/布尔/字符串 -> 指令参数文本。"""
    if isinstance(v, bool):
        return str(v).lower()
    return str(v)
