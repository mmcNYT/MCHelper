# -*- coding: utf-8 -*-
"""地图渲染公共组件包（放 Public 供多工具复用）。

只负责「读存档 region」这一段——解析区块、取每列顶层方块/高度/群系；方块
配色与坡度光照复用 MapPreviewer 的逐方块渲染管线（render_from_blocks：
JourneyMap 色表 + 影调 + slope），两者唯一差别是顶部方块来源（这里读存档，
MapPreviewer 走地形生成）。

- nbt.py          原始 NBT 解析（无 gzip；供 chunk 解压后解析）
- region_reader   .mca region 文件读取（头表 + chunk 解压 + NBT）
- chunk_render    chunk 内 heightmap 解码 / 顶层方块查找 / biome 查找
- world_render    region 网格 → 俯视 RGB 图（LightPack + render_from_blocks）

约定：仅支持 1.18+ 区块格式（sections + palette block_states + 打包
biome）。所有函数纯计算，不碰 Qt / 线程，便于在后台线程调用。
"""
