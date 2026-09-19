# -*- coding: utf-8 -*-
"""掠夺者前哨站（pillager_outpost）拼装模块 —— 复用 jigsaw_assembly 通用引擎。

反编译定案依据（1.21.11 NeoForge，.temp/mansion/decomp/...）：
- JigsawStructure（fgs）：start_height absolute(0) 零消耗；
  project_start_to_heightmap=WORLD_SURFACE_WG → L100
  $$30 = start_y(0) + getFirstFreeHeight(中心)；L101-102
  move(0, $$30-(minY+groundLevelDelta))（groundLevelDelta=1）
  → 起点底面 = 地表高度（引擎 start_y 注入）。
- use_expansion_hack=true → 引擎 expansion_hack=True（$$37 扩展语义，
  1.21.11 L315-342/L368-371；bastion/trial 为 False 不受影响）。
- towers 池唯一元素是 list_pool_element：getShuffledJigsawBlocks 委托
  elements[0]（watchtower 标记/连接语义），place 依序放置全部子元素
  （watchtower 无处理器 + watchtower_overgrown 带 minecraft:outpost_rot）
- outpost_rot（BlockRotProcessor.java L50）：逐方块
  LegacyRandomSource(Mth.getSeed(worldX,worldY,worldZ)).nextFloat() > 0.05
  → 删除该方块（95% 蚀）；位置派生独立流，不消耗布局/装饰 RNG。
- 箱子：watchtower NBT 无 chest 方块，由 DATA 标记（ChestNorth 等）
  handleDataMarker 放置，createChest 消耗装饰流 nextLong() 作
  LootTableSeed（mansion 同范式，composition 层复刻）。

对外接口：
    load_template(key) / load_pool(pool_id)
    assemble_outpost(level_seed, chunk_x, chunk_z, surface_y)
        -> JA.AssemblyResult
    apply_outpost_rot(state_name, x, y, z) -> Optional[str]
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from Utils.SeedReverser import jigsaw_assembly as JA
from Utils.SeedReverser.mc_rng import (MASK_48, MASK_64, MULT, ADD, _u,
                                       mth_get_seed)

PROJ_ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = PROJ_ROOT / "assets" / "SeedReverser" / "pillager_outpost"

START_POOL_ID = "pillager_outpost/base_plates"
OUTPOST_MAX_DEPTH = 7          # pillager_outpost.json "size": 7
OUTPOST_MAX_DIST = 80          # max_distance_from_center
OUTPOST_START_Y = 0            # start_height absolute(0)（地表注入前）
# features 池的 terrain_matching 子件 y 定位基准（getFirstFreeHeight
# 无真实高度图时用平坦近似；渲染可接受）
_OUTPOST_TERRAIN_Y = 63


# ===========================================================================
# 资产加载（独立缓存 + 剥 pillager_outpost/ 前缀）
# ===========================================================================
def _strip_ns(rid: str) -> str:
    return rid.split(":", 1)[-1] if ":" in rid else rid


def _split_key(key: str) -> List[str]:
    parts = key.split("/")
    if parts and parts[0] == "pillager_outpost":
        parts = parts[1:]
    return parts


_TEMPLATE_CACHE: Dict[str, JA.TemplateModel] = {}


def load_template(key: str) -> JA.TemplateModel:
    """'pillager_outpost/watchtower' -> templates/watchtower.nbt"""
    tm = _TEMPLATE_CACHE.get(key)
    if tm is not None:
        return tm
    path = ASSET_DIR.joinpath("templates",
                              Path(*_split_key(key))).with_suffix(".nbt")
    tm = JA._parse_template(key, path)
    _TEMPLATE_CACHE[key] = tm
    return tm


_POOL_CACHE: Dict[str, JA.StructureTemplatePool] = {}


def _list_element_hook(el: dict) -> JA.ListPoolElementSpec:
    """towers 池的 list_pool_element → ListPoolElementSpec。
    location = elements[0]（标记委托源），sub_locations = 全部子模板，
    sub_processors = 各子元素处理器 id（None=无）。"""
    subs = el.get("elements", [])
    return JA.ListPoolElementSpec(
        location=_strip_ns(subs[0].get("location", "")),
        projection=el.get("projection", "rigid"),
        weight=1,
        sub_locations=[_strip_ns(s.get("location", "")) for s in subs],
        sub_processors=[_strip_ns(s["processors"])
                        if isinstance(s.get("processors"), str) else None
                        for s in subs],
    )


def load_pool(pool_id: str) -> JA.StructureTemplatePool:
    """加载前哨站池（key 剥 pillager_outpost/ 前缀；towers 的 list
    元素经 _list_element_hook 转引擎候选表示）。"""
    resolved = _strip_ns(pool_id)
    p = _POOL_CACHE.get(resolved)
    if p is not None:
        return p
    if resolved == "empty":
        # minecraft:empty：注册过的空池（0 元素、无 fallback），无 JSON
        p = JA.parse_pool_dict("empty", {})
        _POOL_CACHE[resolved] = p
        return p
    path = ASSET_DIR.joinpath("template_pool",
                              Path(*_split_key(resolved))
                              ).with_suffix(".json")
    data = json.loads(path.read_text(encoding="utf-8"))
    p = JA.parse_pool_dict(resolved, data,
                           list_element_hook=_list_element_hook)
    _POOL_CACHE[resolved] = p
    return p


# ===========================================================================
# 拼装入口
# ===========================================================================
def assemble_outpost(level_seed: int, chunk_x: int, chunk_z: int,
                     surface_y: Optional[int] = None
                     ) -> JA.AssemblyResult:
    """pillager_outpost 拼装（fgs.a use_expansion_hack 语义）。

    surface_y：锚点区块中心的地表高度（WORLD_SURFACE_WG）。游戏走
    getFirstFreeHeight 真实高度图；预览无地形数据时缺省 63（海平面
    平坦基准），整座结构 y 平移不影响拼装拓扑与 RNG 消耗。

    起点投影（fgs.a L100-102）：$$30 = start_y(0) + surface(中心)；
    起点件 minY=0 → dy = surface - (0+1) + ... 由引擎
    start_y_is_offset=True 分支按 start_y=surface 复算（dy =
    surface-(minY+groundLevelDelta=1)，与 $$30-(minY+1) 恒等——
    surface 与 start_y(0) 之和即 start_y 参数）。
    """
    if surface_y is None:
        surface_y = _OUTPOST_TERRAIN_Y

    def terrain_height_fn(x: int, z: int) -> int:
        # feature_plates（terrain_matching）子的 getFirstFreeHeight
        # 近似：整座结构共用平坦基准（不消耗 RNG，逐标记缓存）
        return surface_y

    return JA.assemble_jigsaw(
        level_seed, chunk_x, chunk_z,
        start_pool_id=START_POOL_ID,
        max_depth=OUTPOST_MAX_DEPTH,
        start_y=surface_y,           # 起点底面 = 地表（$$30 语义）
        start_y_is_offset=True,      # dy = start_y-(minY+groundLevelDelta=1)
        max_dist=OUTPOST_MAX_DIST,
        pad_bottom=0,
        pad_top=0,
        load_pool_fn=load_pool,
        load_template_fn=load_template,
        expansion_hack=True,         # use_expansion_hack=true（前哨站专属）
        terrain_height_fn=terrain_height_fn,
    )


# ===========================================================================
# outpost_rot 降解（BlockRotProcessor L50 字节码语义）
# ===========================================================================
# settings.getRandom(worldPos)：StructurePlaceSettings.random 为 null →
#   RandomSource.create(Mth.getSeed(pos))（逐方块独立流，不消耗布局流）
# test：nextFloat() > 0.05 → 返回 null（删除方块）；<= 0.05 保留
#   （无 rottable 集合限制，所有方块参与判定）
_INV_2POW24 = 1.0 / float(1 << 24)
_LCG_MULT = MULT
_LCG_ADD = ADD


def apply_outpost_rot(state_name: str, x: int, y: int, z: int
                      ) -> Optional[str]:
    """单方块 5% 保留判定（内联 LCG，语义 = BlockRotProcessor.a）。

    返回 None = 方块被蚀（不放置/不渲染）；返回原 state = 保留。
    nextFloat() = next(24)*2^-24 = ((state*MULT+ADD)>>24)*2^-24，
    与 LegacyRandomSource 数学恒等（bastion/trial 降解同式）。
    """
    state = ((mth_get_seed(x, y, z) & MASK_64) ^ MULT) & MASK_48
    state = (state * MULT + ADD) & MASK_48
    if (state >> 24) * _INV_2POW24 > 0.05:
        return None
    return state_name
