# -*- coding: utf-8 -*-
"""存档管理器逻辑包（非渲染）。

- save_info    存档信息数据类
- level_dat    读 level.dat（复用 SeedReverser 的 parse_nbt）
- version_map  版本/数据版本 → 是否支持 + 显示名
- save_scanner 扫描存档目录（兼容老/新两种世界布局）
"""
