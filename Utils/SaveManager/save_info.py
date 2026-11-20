# -*- coding: utf-8 -*-
"""SaveInfo：一个存档（世界）的元信息数据类。

只承载元数据，不含任何渲染逻辑。字段按「存档管理外壳实际需要」裁剪：
名称 + 版本是详情展示的核心；种子提取但当前不展示（26.2 起 level.dat
不再落地种子，1.16~1.21 仍存，留待日后与种子破解器联动）；模式/最后
游玩提取留存但不作为详情主字段。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# GameType 整数 → 中文显示名（与游戏一致）
GAME_TYPE_NAMES = {
    0: "生存",
    1: "创造",
    2: "冒险",
    3: "旁观者",
}


@dataclass
class SaveInfo:
    """一个存档的元信息。

    Attributes:
        path: 世界文件夹绝对路径（含 level.dat 的目录）。
        name: 存档显示名（level.dat 的 LevelName；缺失时回退文件夹名）。
        version_name: 游戏版本名（Version.Name，如 "26.2"/"1.21"）。
        data_version: 数据版本号（Version.Id，决定区块格式与是否支持）。
        game_type: 游戏模式整数（GameType）。
        last_played: 最后游玩毫秒时间戳（LastPlayed）。
        seed: 世界种子（WorldGenSettings.seed；26.2 起为 None）。
        icon_path: 存档图标 icon.png 路径（不存在则 None）。
        overworld_region_dir: 主世界 region 目录路径（不存在则 None；
            老格式 <world>/region，新格式 <world>/dimensions/minecraft/overworld/region）。
        has_terrain: 是否已有地形数据（region 目录下存在 .mca）。
        source: 该存档来自哪个扫描根（如 "saves" / "versions/26.2-NeoForge/saves"），
            用于在重名时区分。
    """

    path: str
    name: str
    version_name: str = ""
    data_version: int = 0
    game_type: int = 0
    last_played: int = 0
    seed: int | None = None
    icon_path: str | None = None
    overworld_region_dir: str | None = None
    has_terrain: bool = False
    source: str = ""

    @property
    def game_type_name(self) -> str:
        return GAME_TYPE_NAMES.get(self.game_type, str(self.game_type))

    @property
    def is_supported(self) -> bool:
        """是否为本工具支持的地形预览版本（1.18+）。"""
        from Utils.SaveManager.version_map import is_supported
        return is_supported(self.data_version)

    def __str__(self) -> str:  # pragma: no cover - 调试用
        return f"SaveInfo(name={self.name!r}, ver={self.version_name}, path={self.path!r})"
