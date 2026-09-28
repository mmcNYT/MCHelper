# -*- coding: utf-8 -*-
"""物品定位（依附 StructurePreviewer）：物品 -> 可能产出结构目录 + 最近命中实例搜索。

包结构：
- catalog.py             物品 -> 结构目录（从战利品快照反推每物品可能产出的结构）
- search.py              最近命中实例搜索（枚举 + compose + RNG 战利品校验）
- target_item_dialog.py  定位窗口控制器（ChooseTargetItemWin.ui 弹窗）
"""