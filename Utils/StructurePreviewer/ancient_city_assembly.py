# -*- coding: utf-8 -*-
"""远古城市（ancient_city, 1.19+）拼装模块 —— 复用 jigsaw_assembly 通用引擎。

字节码定案依据（1.21.11 Fabric，.temp/ancient_city/*.txt + ekv_probe/）：

fhp.a（JigsawStructure.findGenerationPoint，jigsaw_struct_1211.txt L160-208）：
  1. y = fdv.a(rng, evn)         ← start_height absolute(-27) 零消耗
  2. pos = (chunkX*16, y, chunkZ*16)
  3. fhc.create(aliases, pos, seed)  ← ancient_city 无 pool_aliases（
     structure JSON 无该字段）→ 空别名，不耗主流
  4. fgs.a(...)                  ← 主流：rotation → start pool →
                                    findStartJigsawBlock（重定位）

ancient_city.json（1.21.11 jar 提取）：
  start_pool = minecraft:ancient_city/city_center（3 元素等权）
  start_jigsaw_name = minecraft:city_anchor   ← 起点重定位（新语义）
  size = 7（max_depth）、max_distance_from_center = 116
  start_height = absolute(-27)、terrain_adaptation = beard_box
  step = underground_decoration、use_expansion_hack = false

fgs.a（主流消耗 + 重定位，fgs_1211.txt L84-247）：
  rotation = Rotation.getRandom（nextInt(4)）
  start    = pool.getRandom（weight 展开 nextInt(3)）
  findStartJigsawBlock：起点模板 getShuffledJigsawBlocks 洗牌
    （city_center_1/2/3 各 5 个 jigsaw 标记 → 4 次主流 nextInt，
     probe_anchors_out.txt 实证）→ 找 name == city_anchor 的标记
  templatePosition = pos - (anchorWorld - pos) = pos - R(local)
    （anchor 局部 (13,24,20)；字节码两次 is.b(Vec3i) 减法定案）
  dy = k - (box.minY + groundLevelDelta)，k = templatePosition.y，
    groundLevelDelta = fgw.h() 基类恒 1（javap iconst_1 实证，
    四个子类 fgp/fgq/fgu/fgv 均不覆写）
  y 基准：无 project_start_to_heightmap（JSON 无该字段）→
    Optional.empty → k = templatePosition.y；beard_box 仅影响
    Beardifier 地形贴合，不参与布局（预览不实现）。

处理器（processor_list/ancient_city_*.json，1.21.11 jar 提取）：
  起点池 city_center       → ancient_city_start_degradation（3 规则）
  walls / walls/no_corners → ancient_city_walls_degradation
                             （block_rot 0.95 + 4 规则）
  其余（city_center/walls、structures、city/entrance）
                           → ancient_city_generic_degradation
                             （block_rot 0.95 + 3 规则）
  sculk 池                 → feature_pool_element（sculk_patch 地物）
                             + empty，引擎按 fgs$b 语义跳过（trial 先例）
  block_rot：BlockRotProcessor，in #ancient_city_replaceable 才判定，
    nextFloat(pos流) <= 0.95 保留 / 超过蚀空（outpost_rot 同式，
    integrity 0.95）；rule 链：random_block_match 短路（不匹配不
    消耗），与 bastion/trial 降解同型。两处理器各自独立
    RandomSource.create(Mth.getSeed(pos)) 逐方块流（outpost 实证
    StructurePlaceSettings 不缓存）。

容器口径（probe_containers_out.txt / probe_tables_out.txt，58 模板）：
  15 个 minecraft:chest（无 barrel；ice_box 也是 chest）：
    - 14 个 NBT 带 LootTable（13 张 chests/ancient_city +
      1 张 chests/ancient_city_ice_box）→ 进预测列表；
    - city_center_2 的 1 个无字段（游戏内空箱，RandomizableContainer
      只认 NBT 字段，不写 LootTableSeed 不消耗流，trial 同语义）。
  LootTableSeed：每区块 population 流 = get_population_seed + 0
    + 10000*7（salt=(7,0)，cl_salts_1_21_5.txt L33：7 0
    minecraft:ancient_city），同区块按放置序（piece 序 × 块内
    (Y,X,Z)）连抽 nextLong。

结构集（structure_set/ancient_cities.json）：salt=20083232、
  spacing=24、separation=8 —— 与 structure_params.STRUCT_PARAMS
  ["ancient_city"] 一致（既有落点层无需改动）。

对外接口：
    load_template(key) / load_pool(pool_id)
    assemble_ancient_city(level_seed, chunk_x, chunk_z)
        -> JA.AssemblyResult
    apply_ancient_city_degradation(state_name, x, y, z, variant)
        -> Optional[str]        # variant: start/generic/walls
    degradation_variant(key) -> str
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from Utils.SeedReverser import jigsaw_assembly as JA
from Utils.SeedReverser.mc_rng import (MASK_48, MASK_64, MULT, ADD,
                                       mth_get_seed)

PROJ_ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = PROJ_ROOT / "assets" / "SeedReverser" / "ancient_city"

START_POOL_ID = "ancient_city/city_center"
ANCIENT_CITY_MAX_DEPTH = 7     # ancient_city.json "size": 7
ANCIENT_CITY_MAX_DIST = 116    # max_distance_from_center
ANCIENT_CITY_START_Y = -27     # start_height absolute(-27)
ANCIENT_CITY_ANCHOR_NAME = "minecraft:city_anchor"

# 起点池三元素（city_center 池 JSON 序，weight 全 1）
_START_TEMPLATES = (
    "ancient_city/city_center/city_center_1",
    "ancient_city/city_center/city_center_2",
    "ancient_city/city_center/city_center_3",
)


# ===========================================================================
# 资产加载（独立缓存；资产目录保留 ancient_city/ 前缀层级，
# key 剥 minecraft: 命名空间后即相对路径，无需剥层）
# ===========================================================================
def _strip_ns(rid: str) -> str:
    return rid.split(":", 1)[-1] if ":" in rid else rid


_TEMPLATE_CACHE: Dict[str, JA.TemplateModel] = {}


def load_template(key: str) -> JA.TemplateModel:
    """'ancient_city/city_center/city_center_1'
    -> templates/ancient_city/city_center/city_center_1.nbt

    缺失模板 = 空模板（fjr.a(amo)=getOrCreate 字节码实证：b(amo)
    返回 empty 时 new fjq() 空模板入缓存，不抛异常）。1.21.11 jar
    的 walls/no_corners 池引用了不存在的 intact_horizontal_wall_
    stairs_5（vanilla 数据缺陷）：该候选照常消耗 rotation_shuffled
    （3 次），但无 jigsaw 标记永远放不下——与游戏行为一致。
    """
    tm = _TEMPLATE_CACHE.get(key)
    if tm is not None:
        return tm
    path = ASSET_DIR.joinpath("templates",
                              Path(*key.split("/"))).with_suffix(".nbt")
    if not path.exists():
        tm = JA.TemplateModel(key=key, size_x=0, size_y=0, size_z=0,
                              markers=[])
    else:
        tm = JA._parse_template(key, path)
    _TEMPLATE_CACHE[key] = tm
    return tm


_POOL_CACHE: Dict[str, JA.StructureTemplatePool] = {}


def _list_element_hook(el: dict) -> JA.ListPoolElementSpec:
    """structures 池的 list_pool_element → ListPoolElementSpec
    （outpost 同范式）。ice_box_1（单子件，processors 为空 dict =
    无处理器，冰箱不风化）与 camp_1/2/3（三子件连放）两个 list。"""
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
    """'ancient_city/city_center' -> template_pool/ancient_city/
    city_center.json；'empty' 为注册过的空池（无 JSON）。"""
    resolved = _strip_ns(pool_id)
    p = _POOL_CACHE.get(resolved)
    if p is not None:
        return p
    if resolved == "empty":
        # minecraft:empty：注册过的空池（0 元素、无 fallback），
        # 终止候选放置（fgs$b 语义），空池 shuffle 零消耗。
        p = JA.parse_pool_dict("empty", {})
        _POOL_CACHE[resolved] = p
        return p
    path = ASSET_DIR.joinpath(
        "template_pool", Path(*resolved.split("/"))).with_suffix(".json")
    data = json.loads(path.read_text(encoding="utf-8"))
    p = JA.parse_pool_dict(resolved, data,
                           list_element_hook=_list_element_hook)
    _POOL_CACHE[resolved] = p
    return p


# ===========================================================================
# 拼装入口
# ===========================================================================
def assemble_ancient_city(level_seed: int, chunk_x: int,
                          chunk_z: int) -> JA.AssemblyResult:
    """ancient_city 拼装（fhp.a + fgs.a 1.21 语义）。

    主流：rotation nextInt(4) → start pick nextInt(3) → 起点标记
    洗牌（4 次消耗）→ anchor 重定位 → dy = k-(minY+1)。y 无采样
    （absolute -27 零消耗，skip_y_bound=None）。start_y_is_offset
    =True（groundLevelDelta=1，与 bastion 同式）。
    """
    return JA.assemble_jigsaw(
        level_seed, chunk_x, chunk_z,
        start_pool_id=START_POOL_ID,
        max_depth=ANCIENT_CITY_MAX_DEPTH,
        start_y=ANCIENT_CITY_START_Y,
        start_y_is_offset=True,
        max_dist=ANCIENT_CITY_MAX_DIST,
        pad_bottom=0,               # dimension_padding：JSON 无该字段
        pad_top=0,
        load_pool_fn=load_pool,
        load_template_fn=load_template,
        start_jigsaw_name=ANCIENT_CITY_ANCHOR_NAME,
    )


# ===========================================================================
# 降解处理器（enm RuleProcessor + BlockRotProcessor，字节码语义）
# ===========================================================================
# #minecraft:ancient_city_replaceable 标签（jar 提取，12 个方块）：
_REPLACEABLE = frozenset((
    "minecraft:deepslate",
    "minecraft:deepslate_bricks",
    "minecraft:deepslate_tiles",
    "minecraft:deepslate_brick_slab",
    "minecraft:deepslate_tile_slab",
    "minecraft:deepslate_brick_stairs",
    "minecraft:deepslate_tile_wall",
    "minecraft:deepslate_brick_wall",
    "minecraft:cobbled_deepslate",
    "minecraft:cracked_deepslate_bricks",
    "minecraft:cracked_deepslate_tiles",
    "minecraft:gray_wool",
))

# rule 链（random_block_match，按 JSON 序；同 block 单条，跨 block
# 短路不消耗——bastion _DEGRADABLE_ITEMS 同型语义）：
_RULES_START = (
    (0.3, "minecraft:deepslate_bricks",
     "minecraft:cracked_deepslate_bricks"),
    (0.3, "minecraft:deepslate_tiles",
     "minecraft:cracked_deepslate_tiles"),
    (0.05, "minecraft:soul_lantern", "minecraft:air"),
)
# walls：bricks/tiles/slab(0.3→air)/lantern（JSON 序）
_RULES_WALLS = (
    (0.3, "minecraft:deepslate_bricks",
     "minecraft:cracked_deepslate_bricks"),
    (0.3, "minecraft:deepslate_tiles",
     "minecraft:cracked_deepslate_tiles"),
    (0.3, "minecraft:deepslate_tile_slab", "minecraft:air"),
    (0.05, "minecraft:soul_lantern", "minecraft:air"),
)
_RULES_BY_VARIANT = {
    "start": _RULES_START,
    "generic": _RULES_START,
    "walls": _RULES_WALLS,
}

_INV_2POW24 = 1.0 / float(1 << 24)


def degradation_variant(key: str) -> str:
    """模板 key -> 处理器 variant（start/generic/walls）。

    按 8 个池 JSON 的 processors 字段定案：起点池 city_center 三件
    = start；walls 与 walls/no_corners 池（模板 key 均以
    ancient_city/walls/ 开头）= walls；city_center/walls 池、
    structures 池、city/entrance 池 = generic（注意 city_center/
    walls 子目录虽名含 walls 但绑 generic，不能按目录名粗分）。
    """
    if key in _START_TEMPLATES:
        return "start"
    if key.startswith("ancient_city/walls/"):
        return "walls"
    return "generic"


def _rot_rot(x: int, y: int, z: int) -> bool:
    """block_rot integrity=0.95 单判定：True = 保留，False = 蚀空。

    nextFloat() <= 0.95 → 保留（95%），超过 → 蚀空（outpost_rot
    同式，integrity 0.05 保留方向一致）。
    """
    state = ((mth_get_seed(x, y, z) & MASK_64) ^ MULT) & MASK_48
    state = (state * MULT + ADD) & MASK_48
    return (state >> 24) * _INV_2POW24 <= 0.95


def _apply_rules(state_name: str, x: int, y: int, z: int,
                 rules) -> str:
    """rule 链单方块（eni/enm 语义：逐方块独立
    LegacyRandomSource(Mth.getSeed(x,y,z))，random_block_match
    短路——不匹配的规则不消耗随机数，首条命中即返回）。"""
    # 快速路径：三规则输入集合外零消耗直接返回
    if state_name not in ("minecraft:deepslate_bricks",
                          "minecraft:deepslate_tiles",
                          "minecraft:soul_lantern",
                          "minecraft:deepslate_tile_slab"):
        return state_name
    state = ((mth_get_seed(x, y, z) & MASK_64) ^ MULT) & MASK_48
    for prob, blk, out in rules:
        if state_name != blk:
            continue
        state = (state * MULT + ADD) & MASK_48
        if (state >> 24) * _INV_2POW24 < prob:
            return out
    return state_name


def apply_ancient_city_degradation(state_name: str, x: int, y: int, z: int,
                                   variant: str = "generic"
                                   ) -> Optional[str]:
    """ancient_city 处理器链单方块（generic/walls 含 block_rot 前置）。

    处理器数组序 = JSON 序：block_rot（generic/walls）→ rule 链 →
    protected_blocks（无 RNG，渲染忽略）。两处理器各自独立建流，
    互不影响。返回 None = 方块被蚀空（不放置/不渲染）。
    """
    if variant != "start":
        # block_rot：仅 #ancient_city_replaceable 参与判定
        if state_name in _REPLACEABLE and not _rot_rot(x, y, z):
            return None
    return _apply_rules(state_name, x, y, z, _RULES_BY_VARIANT[variant])
