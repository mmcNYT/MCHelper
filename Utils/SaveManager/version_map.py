# -*- coding: utf-8 -*-
"""版本/数据版本映射。

- 1.18（21w39a）的数据版本 = 2860。1.18+ 起区块格式改为 sections +
  palette block_states + 打包 biome 数组，本项目地形渲染器只支持这一档。
- 数据版本用 Version.Id（level.dat 内），是比版本名字符串更可靠的判据
  （1.21.1 / 1.21.11 这类修订版数据版本不同但区块格式一致）。
- 显示名直接用 Version.Name（"26.2"/"1.21"/"1.20.1"），已是人读的，无需再映射。
"""
from __future__ import annotations

# 1.18 数据版本阈值（含）。低于此值的存档区块格式过旧，不支持地形预览。
DATA_VERSION_1_18 = 2860


def is_supported(data_version: int) -> bool:
    """数据版本是否 >= 1.18（含），即区块格式是否受支持。"""
    try:
        return int(data_version) >= DATA_VERSION_1_18
    except (TypeError, ValueError):
        return False


def version_display(version_name: str, data_version: int) -> str:
    """详情/列表显示用的版本字符串。

    优先用 level.dat 的 Version.Name（人读名）；缺失时回退数据版本号。
    """
    name = (version_name or "").strip()
    if name:
        return name
    if data_version:
        return f"data {data_version}"
    return "未知版本"
