# -*- coding: utf-8 -*-
"""Public 公共模块包：存放被多个工具（Tools/tool_*.py）共用的模块。

当前收录（按共用工具数排序）：
- notification.py            桌面气泡通知（AutoBackUp/MapPreviewer/SeedReverser/StrongHoldFinder 共用）
- structure_icons.py         Wiki EnvSprite 结构图标加载（MapPreviewer/SeedReverser/StructurePreviewer 共用）
- biome_names.py             群系 id/中文名/图标路径（MapPreviewer/SeedReverser/StructurePreviewer 共用）
- structure_params.py        结构参数总表（MapPreviewer/SeedReverser/StructurePreviewer 共用）
- biome_signature_colors.py  群系签名色（MapPreviewer/SeedReverser 共用）
- stronghold_math.py         要塞定位数学（StrongHoldFinder/SeedReverser 共用）
- structure_map.py           结构→地图枚举/渲染引擎（MapPreviewer/StructurePreviewer 共用）

归属说明：mc_random / mc_rng / structure_models / jigsaw_assembly / biome_noise
虽也被 StructurePreviewer、MapPreviewer 复用，但与 Utils/SeedReverser/_native
编译扩展强耦合且被包内相对导入，属 SeedReverser 核心算法库，保留原位。
"""
