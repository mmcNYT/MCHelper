# -*- coding: utf-8 -*-
"""试炼密室（trial_chambers, 1.21+）拼装模块 —— 复用 jigsaw_assembly 通用引擎。

字节码定案依据（工作空间 %TEMP%\\ekv_probe\\*.txt，1.21.11 Fabric，
类名映射：fhp=JigsawStructure / fhc=PoolAliasLookup / fha 家族=
PoolAliasBinding / fgs=JigsawPlacement / eur=LegacyRandomSource /
eur$a=LegacyPositionalRandomFactory / bgj.b(III)=Mth.getSeed(III)）：

fhp.a(fo.a) L160-208（拼装总入口）：
  1. y = fdv.a(rng, evn)                ← start_height uniform(-40,-20)，
                                           即 nextInt(21)-40，位于
                                           fhc.create 与 fgs.a **之前**
  2. pos = (chunkX*16, y, chunkZ*16)
  3. fhc.create(aliases, pos, worldSeed) ← alias 专用流，不耗主流
  4. fgs.a(..., pos, ...)               ← 主流：rotation → start pool

fhc.create（alias 流构造，字节码 L13-28）：
  LegacyRandomSource(worldSeed)         ← bgr.a(J) → eur
    .e()                                ← forkPositional：eur$a(g() 当前
                                           state 作 factorySeed)
                                           factorySeed = (worldSeed
                                           ^ 0x5DEECE66D) & (2^48-1)
    .at(pos)                            ← eur$a.a(III) 字节码 lxor 定案：
                                           LegacyRandomSource(
                                           Mth.getSeed(x,y,z) ^ factorySeed)
  然后 List<fha>.forEach 逐 binding resolve（顺序 = JSON 顺序）

fha 家族消耗语义：
  - fgz Direct      零 RNG，直接 alias→target
  - fhe Random      一次 nextInt(totalWeight)（cbn.a 前缀和）选 target
  - fhd RandomGroup 一次 nextInt(totalWeight) 选组（组是
                    WeightedList<List<fha>>），组内 binding 按序 resolve
  trial 的 3 个 alias 依次消耗：
    random_group nextInt(3) → random(melee) nextInt(3)
    → random(small_melee) nextInt(4)

fgs.a（主流消耗，与 bastion 同引擎）：
  rotation = nextInt(4) → startPool.getRandom = nextInt(totalWeight)
  → dy = k - box.minY（无投影、groundLevelDelta=0；trial 起点件本地
  minY=0 → dy=0）；dimension_padding=10 仅检查起始件
  （y∈[-40,-20] 恒过 -64+10，不触发 empty）；外层大盒：
  xz = 起点中心±116（含端+1），y = [max(k-116, -64), min(k+117, 320))

资产口径（项目内 = 1.21 官方 jar，与 1.21.11 loot/拼装语义一致）：
  assets/SeedReverser/trial_chambers/
    trial_chambers.json                 结构定义（内嵌解析）
    template_pool/<剥前缀 key>.json     45 池
    templates/<剥前缀 key>.nbt          170 模板
  池/模板 key 均剥 trial_chambers/ 前缀：
    trial_chambers/chamber/end → template_pool/chamber/end.json

对外接口：
    resolve_aliases(level_seed, pos) -> Dict[str, str]
    assemble_trial_chambers(level_seed, chunk_x, chunk_z, y)
    apply_trial_degradation(state_name, x, y, z) -> str
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from Utils.SeedReverser import jigsaw_assembly as JA
from Utils.SeedReverser.mc_rng import (MASK_48, MASK_64, MULT, ADD,
                                       LegacyRandomSource, _u,
                                       mth_get_seed)

PROJ_ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = PROJ_ROOT / "assets" / "SeedReverser" / "trial_chambers"

START_POOL_ID = "trial_chambers/chamber/end"
TRIAL_MAX_DEPTH = 20          # trial_chambers.json "size": 20
TRIAL_MAX_DIST = 116          # max_distance_from_center
TRIAL_START_MIN_Y = -40       # start_height uniform(-40,-20)
TRIAL_START_SPAN = 21         # nextInt(21) - 40


# ===========================================================================
# 资产加载（独立缓存 + 剥 trial_chambers/ 前缀）
# ===========================================================================
def _strip_ns(rid: str) -> str:
    return rid.split(":", 1)[-1] if ":" in rid else rid


def _split_key(key: str) -> List[str]:
    parts = key.split("/")
    if parts and parts[0] == "trial_chambers":
        parts = parts[1:]
    return parts


_TEMPLATE_CACHE: Dict[str, JA.TemplateModel] = {}


def load_template(key: str) -> JA.TemplateModel:
    """'trial_chambers/hallway/straight' -> templates/hallway/straight.nbt"""
    tm = _TEMPLATE_CACHE.get(key)
    if tm is not None:
        return tm
    path = ASSET_DIR.joinpath("templates",
                              Path(*_split_key(key))).with_suffix(".nbt")
    tm = JA._parse_template(key, path)
    _TEMPLATE_CACHE[key] = tm
    return tm


_POOL_CACHE: Dict[str, JA.StructureTemplatePool] = {}


def _load_pool_resolved(resolved_id: str) -> JA.StructureTemplatePool:
    """加载 alias 解析后的池（无 alias 语境用 load_pool）。"""
    p = _POOL_CACHE.get(resolved_id)
    if p is not None:
        return p
    if resolved_id == "empty":
        # minecraft:empty 是注册过的空池（无 JSON 文件）；
        # entrance_cap 的 fallback 即它。空池 shuffle 零消耗，与游戏一致。
        p = JA.parse_pool_dict("empty", {})
        _POOL_CACHE[resolved_id] = p
        return p
    path = ASSET_DIR.joinpath("template_pool",
                              Path(*_split_key(resolved_id))
                              ).with_suffix(".json")
    data = json.loads(path.read_text(encoding="utf-8"))
    p = JA.parse_pool_dict(resolved_id, data)
    _POOL_CACHE[resolved_id] = p
    return p


def load_pool(pool_id: str) -> JA.StructureTemplatePool:
    """不做 alias 的直载（start_pool 等恒等映射场景）。"""
    return _load_pool_resolved(_strip_ns(pool_id))


# ===========================================================================
# pool_aliases（fhc.create + fha 家族）
# ===========================================================================
_STRUCT_DEF_PATH = ASSET_DIR / "trial_chambers.json"
_STRUCT_DEF_CACHE: Optional[dict] = None


def _struct_def() -> dict:
    global _STRUCT_DEF_CACHE
    if _STRUCT_DEF_CACHE is None:
        _STRUCT_DEF_CACHE = json.loads(
            _STRUCT_DEF_PATH.read_text(encoding="utf-8"))
    return _STRUCT_DEF_CACHE


def _weighted_pick(rng: LegacyRandomSource, weighted: List[Tuple[int, object]]
                   ) -> object:
    """cbn.a（WeightedList.getRandom）：nextInt(总权重) → 前缀和取元素。"""
    total = sum(w for w, _item in weighted)
    i = rng.next_int(total)
    for w, item in weighted:
        i -= w
        if i < 0:
            return item
    return weighted[-1][1]          # 浮点边界兜底（理论不可达）


def _resolve_binding(binding: dict, alias_map: Dict[str, str],
                     rng: LegacyRandomSource) -> None:
    btype = _strip_ns(binding.get("type", ""))
    if btype == "direct":
        # fgz：零消耗
        alias_map[_strip_ns(binding["alias"])] = _strip_ns(binding["target"])
    elif btype == "random":
        # fhe：一次 nextInt(totalWeight)
        targets = [(_strip_ns(t["data"]), int(t.get("weight", 1)))
                   for t in binding["targets"]]
        # WeightedList 内部按 (weight, 序) 存 —— pick 按序前缀和
        picked = _weighted_pick(rng, [(w, tid) for tid, w in targets])
        alias_map[_strip_ns(binding["alias"])] = picked
    elif btype == "random_group":
        # fhd：一次 nextInt(totalWeight) 选组，组内 binding 按序 resolve
        groups = [([(b, ) for b in g["data"]], int(g.get("weight", 1)))
                  for g in binding["groups"]]
        picked = _weighted_pick(rng, [(w, bindings)
                                      for bindings, w in groups])
        for (b, ) in picked:
            _resolve_binding(b, alias_map, rng)
    else:
        raise ValueError(f"未知 pool_alias 类型: {btype}")


def resolve_aliases(level_seed: int, pos: Tuple[int, int, int]
                    ) -> Dict[str, str]:
    """fhc.create(aliases, pos, worldSeed) 的 Python 复刻。

    factorySeed = (worldSeed ^ 0x5DEECE66D) & (2^48-1)  ← eur.e() 取 g()
    rng = LegacyRandomSource(mth_get_seed(x,y,z) ^ factorySeed)
    3 个 binding 按 JSON 顺序 resolve（Direct 零消耗）。
    返回 {alias_key(剥ns): target_key(剥ns)}。
    """
    factory_seed = (_u(level_seed) ^ MULT) & MASK_48
    rng = LegacyRandomSource(mth_get_seed(pos[0], pos[1], pos[2])
                             ^ factory_seed)
    alias_map: Dict[str, str] = {}
    for binding in _struct_def()["pool_aliases"]:
        _resolve_binding(binding, alias_map, rng)
    return alias_map


_ALIAS_CACHE: Dict[Tuple[int, int, int, int], Dict[str, str]] = {}


def resolve_aliases_cached(level_seed: int, pos: Tuple[int, int, int]
                           ) -> Dict[str, str]:
    key = (level_seed, pos[0], pos[1], pos[2])
    m = _ALIAS_CACHE.get(key)
    if m is None:
        m = resolve_aliases(level_seed, pos)
        _ALIAS_CACHE[key] = m
    return m


# ===========================================================================
# 拼装入口
# ===========================================================================
def assemble_trial_chambers(level_seed: int, chunk_x: int, chunk_z: int,
                            y: int) -> JA.AssemblyResult:
    """trial_chambers 拼装（fhp.a + fgs.a 1.21 语义）。

    y = start_height 采样结果（nextInt(21)-40），须由调用方从
    chunkGenerateRnd 同条流采出（structure_map._jigsaw_variant 已实现
    y→rotation→start 顺序，可交叉验证）；本函数重建主流后以
    skip_y_bound=21 补位（拒绝采样确定性相同 → 消耗次数逐位一致），
    再接 rotation / start pool。jigsaw 标记的 pool 字段经 alias 映射
    后加载（闭包注入，Direct/Random/RandomGroup 已在 resolve 阶段定案）。
    """
    pos = (chunk_x * 16, y, chunk_z * 16)
    alias = resolve_aliases_cached(level_seed, pos)

    def load_pool_fn(pool_id: str) -> JA.StructureTemplatePool:
        # Placer 传入的 pool_id 已剥命名空间；先过 alias 再加载
        return _load_pool_resolved(alias.get(pool_id, pool_id))

    return JA.assemble_jigsaw(
        level_seed, chunk_x, chunk_z,
        start_pool_id=START_POOL_ID,
        max_depth=TRIAL_MAX_DEPTH,
        start_y=y,
        start_y_is_offset=False,     # trial：dy = k - minY（起点件 minY=0）
        max_dist=TRIAL_MAX_DIST,
        pad_bottom=0,                # dimension_padding=10 仅查起始件
        pad_top=0,                   # （y∈[-40,-20] 恒过），不进大盒
        skip_y_bound=TRIAL_START_SPAN,
        load_pool_fn=load_pool_fn,
        load_template_fn=load_template,
    )


# ===========================================================================
# 铜灯降解（trial_chambers_copper_bulb_degradation，enm+eni 字节码语义）
# ===========================================================================
# 规则（两版 JSON 一致，1.21 / 1.21.11 逐字节比对 SAME）：
#   waxed_copper_bulb → p0.1        waxed_oxidized_copper_bulb (lit)
#                     → p0.33333334 waxed_weathered_copper_bulb (lit)
#                     → p0.5         waxed_exposed_copper_bulb  (lit)
# 三条按序共用同一条方块随机流（Mth.getSeed(x,y,z) 播种的
# LegacyRandomSource），random_block_match = nextFloat() < prob；
# 首条命中即返回；protected_blocks 处理器无 RNG，渲染可忽略。
# 输出态 Properties 恒 lit=true / powered=false，材质仅按方块名映射。
_TRIAL_BULB_RULES = (
    (0.1, "minecraft:waxed_oxidized_copper_bulb"),
    (0.33333334, "minecraft:waxed_weathered_copper_bulb"),
    (0.5, "minecraft:waxed_exposed_copper_bulb"),
)
_INV_2POW24 = 1.0 / float(1 << 24)


def apply_trial_degradation(state_name: str, x: int, y: int, z: int) -> str:
    """单方块降解（内联 LCG，语义 = enm.a + eni.a，见 bastion 同式）。

    不可降解方块直接原样返回；waxed_copper_bulb 走 3 条规则共用流，
    至多消耗 3 次 nextFloat。
    """
    if state_name != "minecraft:waxed_copper_bulb":
        return state_name
    state = ((mth_get_seed(x, y, z) & MASK_64) ^ MULT) & MASK_48
    for prob, out in _TRIAL_BULB_RULES:
        state = (state * MULT + ADD) & MASK_48
        if (state >> 24) * _INV_2POW24 < prob:
            return out
    return state_name
