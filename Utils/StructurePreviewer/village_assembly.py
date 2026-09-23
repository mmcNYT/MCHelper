# -*- coding: utf-8 -*-
"""村庄（village）拼装模块 —— 复用 jigsaw_assembly 通用引擎。

结构定义定案（1.21.11 jar 提取，data/minecraft/worldgen/structure/
village_<biome>.json ×5，与 data/minecraft/worldgen/structure_set/
villages.json）：
  - 五变体结构键：village_desert / village_plains / village_savanna /
    village_snowy / village_taiga，共用 placement
    （salt=10387312, spacing=34, separation=8 —— 与
    structure_params.STRUCT_PARAMS["village"] 一致，锚点相同，
    哪个变体生成由锚点群系决定）
  - type=jigsaw：start_pool=village/<biome>/town_centers、size=6、
    max_distance_from_center=80、start_height=absolute(0)、
    project_start_to_heightmap=WORLD_SURFACE_WG（→ 起点底面 = 地表，
    start_y_is_offset=True 与 outpost 同式）、
    terrain_adaptation=beard_thin（仅地形贴合，预览不建模）、
    use_expansion_hack=true（与 outpost 同，引擎已支持）
  - 起点池（plains 例）8 元素：4 普通中心 ×weight50 +
    4 僵尸中心 ×weight1（总 204）。僵尸中心 street 标记指向
    village/<biome>/zombie/streets 池 → 完整僵尸村庄链（1.21.x 僵尸
    村庄回归为起点池元素，无独立结构定义）。起点 pick 尺寸表与
    structure_map._VILLAGE_TABLES/_VILLAGE_TABLE_MOD 逐项吻合
    （cubiomes getVariant 的 village 表即由此池推导）。

处理器（RuleProcessor，16 种入库 assets/.../village/processors/）：
  通用引擎 apply_processor：每方块独立
  LegacyRandomSource(Mth.getSeed(x,y,z))，规则链共用一条流；
  input 谓词短路（block/tag/blockstate 匹配不消耗，
  random_block[_state]_match 匹配才消耗 next(24)*2^-24）；
  location_predicate 除 always_true 外（村庄仅 block_match water）
  平坦预览无世界上下文恒 False → 规则不命中（水面街道变化属
  预览已知妥协）。命中返回 output_state(Name+Properties)。
  zombie_* 的 tag_match(#minecraft:doors) → air、
  blockstate_match（glass_pane 连接态 → 棕色玻璃板）已支持。
  处理器逐方块独立流不消耗布局/装饰 RNG，LootTableSeed 不受影响。

池元素类型：legacy_single(592)/empty(22)/feature(35)。legacy 的
getBoundingBox = 全模板盒（jigsaw_assembly.TemplateModel 同口径）；
feature（村民/猫/铁傀儡/动物等地物）引擎按 fgs$b 语义跳过；
empty 终止候选。全部池无 list_pool_element。

对外接口：
  load_template(key) / load_pool(pool_id)
  assemble_village(level_seed, chunk_x, chunk_z, variant="plains",
                   surface_y=None) -> JA.AssemblyResult
  apply_processor(pid, name, props, x, y, z) -> (name, props) | None
  VARIANTS / variant_from_biome(biome_id) -> str
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Tuple

from Utils.SeedReverser import jigsaw_assembly as JA
from Utils.SeedReverser.mc_rng import MASK_48, MASK_64, MULT, ADD, \
    mth_get_seed

PROJ_ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = PROJ_ROOT / "assets" / "SeedReverser" / "village"

VILLAGE_MAX_DEPTH = 6          # village_*.json "size": 6
VILLAGE_MAX_DIST = 80          # max_distance_from_center
_VILLAGE_TERRAIN_Y = 63        # WORLD_SURFACE_WG 平坦基准（outpost 同式）
VARIANTS = ("desert", "plains", "savanna", "snowy", "taiga")


def variant_from_biome(biome_id: int) -> str:
    """锚点群系 id -> 村庄变体（structure_map._check_village 同口径：
    meadow 按 plains）。未知群系回退 plains（演示模式）。"""
    from Utils.Public import structure_map as sm
    if biome_id == sm.MEADOW:
        return "plains"
    for var, const in (("desert", "DESERT"), ("plains", "PLAINS"),
                       ("savanna", "SAVANNA"), ("taiga", "TAIGA"),
                       ("snowy", "SNOWY_PLAINS")):
        if getattr(sm, const) == biome_id:
            return var
    return "plains"


# ===========================================================================
# 资产加载（独立缓存；key 保留 village/ 前缀 = 相对路径层级）
# ===========================================================================
def _strip_ns(rid: str) -> str:
    return rid.split(":", 1)[-1] if ":" in rid else rid


_TEMPLATE_CACHE: Dict[str, JA.TemplateModel] = {}


def load_template(key: str) -> JA.TemplateModel:
    """'village/plains/houses/plains_small_house_1'
    -> templates/village/plains/houses/plains_small_house_1.nbt
    （缺失模板 = 空模板，ancient_city 同款防御语义）。"""
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


def load_pool(pool_id: str) -> JA.StructureTemplatePool:
    """'village/plains/streets' -> template_pool/plains/streets.json
    （池资产目录以 jar 剥除 template_pool/village/ 后为根，无
    village/ 层；'empty' 为注册过的空池，无 JSON）。"""
    resolved = _strip_ns(pool_id)
    p = _POOL_CACHE.get(resolved)
    if p is not None:
        return p
    if resolved == "empty":
        p = JA.parse_pool_dict("empty", {})
        _POOL_CACHE[resolved] = p
        return p
    parts = resolved.split("/")
    if parts and parts[0] == "village":
        parts = parts[1:]
    path = ASSET_DIR.joinpath("template_pool",
                              Path(*parts)).with_suffix(".json")
    data = json.loads(path.read_text(encoding="utf-8"))
    p = JA.parse_pool_dict(resolved, data)
    _POOL_CACHE[resolved] = p
    return p


# ===========================================================================
# 拼装入口
# ===========================================================================
def assemble_village(level_seed: int, chunk_x: int, chunk_z: int,
                     variant: str = "plains",
                     surface_y: Optional[int] = None) -> JA.AssemblyResult:
    """village_<variant> 拼装（fhp.a + fgs.a 1.21 语义）。

    surface_y：锚点区块中心的地表高度（WORLD_SURFACE_WG）。预览无
    地形数据缺省 63（海平面平坦基准），y 平移不影响拼装拓扑与 RNG
    消耗。主流：rotation nextInt(4) → start pool pick nextInt(204)
    → 起点标记洗牌 → 展开池；expansion_hack=True（street 池高度
    扩展语义，outpost 同式）。
    """
    if surface_y is None:
        surface_y = _VILLAGE_TERRAIN_Y

    def terrain_height_fn(x: int, z: int) -> int:
        return surface_y

    return JA.assemble_jigsaw(
        level_seed, chunk_x, chunk_z,
        start_pool_id=f"village/{variant}/town_centers",
        max_depth=VILLAGE_MAX_DEPTH,
        start_y=surface_y,           # absolute(0) + WORLD_SURFACE_WG 投影
        start_y_is_offset=True,      # dy = start_y-(minY+groundLevelDelta=1)
        max_dist=VILLAGE_MAX_DIST,
        pad_bottom=0,
        pad_top=0,
        load_pool_fn=load_pool,
        load_template_fn=load_template,
        expansion_hack=True,         # use_expansion_hack=true
        terrain_height_fn=terrain_height_fn,
    )


# ===========================================================================
# 处理器（RuleProcessor 数据驱动引擎；enm/eni 字节码语义）
# ===========================================================================
# enm.a：rng = RandomSource.create(Mth.getSeed(pos))（每方块独立）；
# worldState = level.getBlockState(pos)（location 谓词用，平坦预览
# 无世界数据 → block_match water 恒 False）；规则链按 JSON 序共用
# 该流，enp nbt 无短路关系（村庄无 output_nbt）。
_PROC_DIR = ASSET_DIR / "processors"
_INV_2POW24 = 1.0 / float(1 << 24)

# #minecraft:doors（1.21.11 jar tags/block/doors.json + wooden_doors 展开）
_DOORS = frozenset(
    "minecraft:" + s for s in (
        "oak_door", "spruce_door", "birch_door", "jungle_door",
        "acacia_door", "dark_oak_door", "pale_oak_door", "crimson_door",
        "warped_door", "mangrove_door", "bamboo_door", "cherry_door",
        "copper_door", "exposed_copper_door", "weathered_copper_door",
        "oxidized_copper_door", "waxed_copper_door",
        "waxed_exposed_copper_door", "waxed_weathered_copper_door",
        "waxed_oxidized_copper_door", "iron_door"))

_PROC_CACHE: Dict[str, Optional[Tuple[tuple, frozenset]]] = {}


def _load_proc(pid: str):
    """处理器 id -> (rules, input_blocks)；'empty'/解析失败 = None。

    rule 元组形如：
      ("rb", block, prob, out_name, out_props)      random_block_match
      ("b", block, out_name, out_props)             block_match
      ("bs", name, props, out_name, out_props)      blockstate_match
      ("rbs", name, props, prob, out_name, out_props) random_blockstate
      ("tag", members, out_name, out_props)         tag_match
    location：("always",) / ("b", block)（平坦预览 water 恒 False）。
    """
    cached = _PROC_CACHE.get(pid)
    if cached is not None or pid in _PROC_CACHE:
        return cached
    rules: list = []
    inputs: set = set()
    if pid != "empty":
        path = _PROC_DIR / f"{pid}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for proc in data.get("processors", []):
            for r in proc.get("rules", []):
                ip = r["input_predicate"]
                t = ip["predicate_type"]
                out_s = r["output_state"]
                out_name = out_s.get("Name", "minecraft:air")
                out_props = dict(out_s.get("Properties") or {})
                lp = r.get("location_predicate", {})
                lt = str(lp.get("predicate_type", "always_true")).split(":")[-1]
                if lt == "block_match":
                    loc = ("b", lp.get("block", ""))
                else:
                    loc = ("always",)
                t = str(t).split(":")[-1]
                if t == "random_block_match":
                    blk = ip.get("block", "")
                    rules.append(("rb", blk, float(ip.get("probability", 0)),
                                  loc, out_name, out_props))
                    inputs.add(blk)
                elif t == "block_match":
                    blk = ip.get("block", "")
                    rules.append(("b", blk, loc, out_name, out_props))
                    inputs.add(blk)
                elif t == "blockstate_match":
                    bs = ip.get("block_state") or {}
                    nm = bs.get("Name", "")
                    pr = dict(bs.get("Properties") or {})
                    rules.append(("bs", nm, pr, loc, out_name, out_props))
                    inputs.add(nm)
                elif t == "random_blockstate_match":
                    bs = ip.get("block_state") or {}
                    nm = bs.get("Name", "")
                    pr = dict(bs.get("Properties") or {})
                    rules.append(("rbs", nm, pr,
                                  float(ip.get("probability", 0)),
                                  loc, out_name, out_props))
                    inputs.add(nm)
                elif t == "tag_match":
                    tag = ip.get("tag", "")
                    members = _DOORS if tag.endswith("doors") else frozenset()
                    rules.append(("tag", members, loc, out_name, out_props))
                    inputs.update(members)
    out = (tuple(rules), frozenset(inputs))
    _PROC_CACHE[pid] = out
    return out


def apply_processor(pid: Optional[str], name: str, props: Optional[dict],
                    x: int, y: int, z: int
                    ) -> Optional[Tuple[str, dict]]:
    """单方块处理器（village RuleProcessor 语义）。

    返回 (name, props) = 落地方块状态；None = air（不放置）。
    每方块独立 LegacyRandomSource(Mth.getSeed(x,y,z))，规则链共用；
    不在规则输入集的方块零消耗快速路径（与 Java 短路逐条 test
    不命中等价）。
    """
    if pid is None or pid == "empty":
        return name, (props or {})
    loaded = _load_proc(pid)
    if loaded is None:
        return name, (props or {})
    rules, inputs = loaded
    if name not in inputs:
        return name, (props or {})
    # Mth.getSeed(x, y, z) -> LegacyRandomSource（内联 LCG，
    # 与 bastion apply_degradation 同式）
    state = ((mth_get_seed(x, y, z) & MASK_64) ^ MULT) & MASK_48
    for r in rules:
        kind = r[0]
        hit = False
        if kind == "rb":
            if name != r[1]:
                continue
            state = (state * MULT + ADD) & MASK_48
            hit = (state >> 24) * _INV_2POW24 < r[2]
        elif kind == "b":
            hit = name == r[1]
        elif kind == "bs":
            hit = name == r[1] and (props or {}) == r[2]
        elif kind == "rbs":
            if name != r[1] or (props or {}) != r[2]:
                continue
            state = (state * MULT + ADD) & MASK_48
            hit = (state >> 24) * _INV_2POW24 < r[3]
        else:  # tag
            hit = name in r[1]
        if not hit:
            continue
        loc = r[-3]
        if loc[0] != "always":
            # 平坦预览无世界方块：location block_match 恒 False
            continue
        out_name = r[-2]
        if out_name == "minecraft:air":
            return None
        return out_name, dict(r[-1])
    return name, (props or {})
