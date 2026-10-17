# -*- coding: utf-8 -*-
"""物品 id 过滤：从 `item_list.ITEM_IDS` 中剔除**非物品条目**。

`item_list.ITEM_IDS` 取自客户端 jar 的 lang 键全集，其中混有：
  1. **翻译键**（含 `.` 的，如 `banner.base.black`、`potion.effect.awkward`、
     `tipped_arrow.effect.fire_resistance`）—— 共 928 个，不是物品 id；
  2. 理论上还可能有 `xxx.disabled` 这类状态键。

真实物品 id 不含 `.`，共 1708 个。指令表单的物品下拉、NBT 物品选择器等
一律用本模块的 `REAL_ITEM_IDS`，避免出现「选不中/无译名」的假条目。

（`ITEM_ICONS` 是图标文件名集合，键空间又不同 —— 里面另有 132 个药水/箭
的图标变体如 `potion_awkward`，同样不可当物品 id 用，见
`tool_CommandGenerator._build_item_combo` 的说明。）
"""
from __future__ import annotations

from Utils.CommandGenerator import item_list as IL


def _real(iid: str) -> bool:
    """真实物品 id：不含点号，且不是 `xxx.disabled` 之类的状态键。"""
    return "." not in iid


#: 真实物品 id（1708 个），按原顺序。
REAL_ITEM_IDS = [i for i in IL.ITEM_IDS if _real(i)]

#: 有图标的真实物品（排序权重用）。
REAL_ITEM_ICONS = [i for i in REAL_ITEM_IDS if i in IL.ITEM_ICONS]


def item_label(iid: str) -> str:
    """物品 id -> 显示名（中文优先，无译名回退英文名，再回退 id）。"""
    cn = IL.ITEM_CN.get(iid)
    if cn:
        return cn
    return IL.ITEM_NAMES.get(iid, iid)


def item_items() -> list:
    """[(id, 显示名)]，供下拉使用。"""
    return [(i, item_label(i)) for i in REAL_ITEM_IDS]
