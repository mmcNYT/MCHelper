# -*- coding: utf-8 -*-
"""按 biome 解析植被密度画像（数据驱动，来自 placed_feature 真实 placement）。

placed_feature 的 placement 里，各类 count 连乘 × rarity 倒数 = 每 chunk
平均尝试次数，即密度。据此得到每群系的 树/花/草/作物 密度与树种，供精细
渲染做确定性散布（密度准确、位置确定性近似，非逐方块位精确）。
"""
from __future__ import annotations

import json
import os

_WG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "_native", "worldgen", "26.2")

# 植被 step 索引（VEGETAL_DECORATION）；不同 biome 基本固定在 9，兼容多步
_VEGETATION_STEPS = (4, 5, 9)

# placed/configured 名 -> 类别（名称兜底；主判据见 _configured_category）
def _classify(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ("tree", "mangrove", "palmtree", "palm", "cherry")):
        return "tree"
    if "flower" in n or "wildflower" in n or "poppy" in n or "tulip" in n:
        return "flower"
    if any(k in n for k in ("cactus", "sugar_cane", "pumpkin", "melon",
                            "bamboo", "berry", "cocoa")):
        return "crop"
    if any(k in n for k in ("grass", "fern", "bush", "dry_grass", "dead_bush",
                            "large_fern", "shrub")):
        return "grass"
    return "ignore"   # glow_lichen / leaf_litter / mushroom / firefly / freeze


_FLOWER_BLOCKS = ("poppy", "dandelion", "blue_orchid", "allium", "azure_bluet",
                  "oxeye_daisy", "cornflower", "lily_of_the_valley", "wither_rose",
                  "tulip", "torchflower", "flower", "cherry_sapling",
                  # 26.2：樱花林的地被是 pink_petals（不是树！）
                  "pink_petals", "wildflower", "sunflower", "lilac", "rose_bush",
                  "peony", "pitcher_plant", "cactus_flower", "leaf_litter")
_GRASS_BLOCKS = ("grass", "fern", "shrub", "dead_bush", "bush", "leaf_litter",
                 "dry_grass", "tall_grass", "large_fern", "seagrass")
_CROP_BLOCKS = ("cactus", "sugar_cane", "pumpkin", "melon", "carved_pumpkin",
                "bamboo", "cocoa", "sweet_berry_bush")


def _collect_blocks(obj, out: set, depth=0):
    """递归收集 JSON 里所有 state 的方块名。"""
    if depth > 8:
        return
    if isinstance(obj, dict):
        nm = obj.get("Name")
        if isinstance(nm, str):
            out.add(nm.split(":")[-1])
        for v in obj.values():
            _collect_blocks(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _collect_blocks(v, out, depth + 1)


def _sub_feature(ref):
    """placed/configured 引用可能是 str 或 {feature, placement}。"""
    if isinstance(ref, str):
        return _short(ref)
    if isinstance(ref, dict):
        f = ref.get("feature")
        if isinstance(f, str):
            return _short(f)
        if isinstance(f, dict):
            return _short(f.get("feature", ""))
    return ""


_CAT_CACHE: dict[str, str] = {}


def _configured_category(name: str, depth=0) -> str:
    """跟随 configured_feature 真实结构判类别。"""
    if not name:
        return "ignore"
    if name in _CAT_CACHE:
        return _CAT_CACHE[name]
    if depth > 6:
        return "ignore"
    cf = _load_json("configured_feature", name)
    if not cf:
        return _classify(name)
    t = cf.get("type", "").split(":")[-1]
    cfg = cf.get("config", cf)
    if t == "tree":
        _CAT_CACHE[name] = "tree"
        return "tree"
    if t in ("random_selector", "weightedList", "weighted_list"):
        kids = []
        d = cfg.get("default")
        if d is not None:
            kids.append(_sub_feature(d) or (d if isinstance(d, str) else ""))
        for e in cfg.get("features", []):
            kids.append(_sub_feature(e.get("feature") if isinstance(e, dict) else e))
        for k in kids:
            if k and _configured_category(k, depth + 1) == "tree":
                _CAT_CACHE[name] = "tree"
                return "tree"
        # 非树：取首个子类别
        for k in kids:
            c = _configured_category(k, depth + 1) if k else "ignore"
            if c != "ignore":
                _CAT_CACHE[name] = c
                return c
    # 用方块名判
    blocks: set[str] = set()
    _collect_blocks(cf, blocks)
    cat = "ignore"
    if any(any(fb in b for fb in _FLOWER_BLOCKS) for b in blocks):
        cat = "flower"
    elif any(any(cb in b for cb in _CROP_BLOCKS) for b in blocks):
        cat = "crop"
    elif any(any(gb in b for gb in _GRASS_BLOCKS) for b in blocks):
        cat = "grass"
    else:
        # simple_block 等：方块名判不出时才回退名称。
        # 注意不能盲信名称——"flower_cherry" 含 cherry 但不是树。
        cat = _classify(name) if t not in ("simple_block",) else "ignore"
    _CAT_CACHE[name] = cat
    return cat


# 树种 -> (冠层半径方块, 冠层RGB)。半径决定覆盖面积。
_SPECIES = {
    "oak":       (2, (40, 74, 28)),
    "fancy_oak": (3, (38, 72, 26)),
    "birch":     (2, (68, 102, 46)),
    "spruce":    (2, (30, 58, 42)),
    "pine":      (2, (28, 54, 40)),
    "jungle":    (3, (30, 82, 22)),
    "acacia":    (3, (104, 98, 46)),
    "dark_oak":  (3, (32, 60, 30)),
    "swamp":     (2, (58, 70, 38)),
    "mangrove":  (2, (62, 74, 28)),
    "cherry":    (3, (214, 156, 176)),
    "default":   (2, (40, 74, 28)),
}

# 显式画像 override（数据驱动判不准/需目视校准的群系）。
# 竹林：官方 bamboo_vegetation 每 chunk 30.1 次尝试其实是 random_selector
#（70% mega_jungle_tree / 15% jungle_bush / 5% fancy_oak / 10% grass_jungle
# 草丛），树是 checked 特征，在密竹林里因竹子占位与空间不足大量放置
# 失败，游戏内目视树很稀疏（参考图换算 ~0.6-1.2 棵/chunk）-> 有效树数
# 取 ~1.2 棵/chunk。
# 竹子本体与灰化土盘 = placed "minecraft:bamboo"（noise_based_count
# 160/80/0.3，count = ceil((Simplex2D(cx*0.2, cz*0.2)+0.3)*160)，Perlin
# 噪声驱动、空间强聚集），由 bamboo_placement.py 逐行复刻官方放置链，
# 不再用 crop/podzol_p 代理密度（旧字段已删，见该模块 docstring）。
_BIOME_VEG_OVERRIDE = {
    "bamboo_jungle": {
        "tree": 1.2 / 256.0,
        "species": "jungle",
        "crop_kind": "bamboo",
    },
}

# biome 短名 -> 主导树种（placed 名未能判定时的兜底）
_BIOME_SPECIES = {
    "forest": "oak", "birch_forest": "birch", "old_growth_birch_forest": "birch",
    "dark_forest": "dark_oak", "wooded_badlands": "oak",
    "plains": "oak", "sunflower_plains": "oak", "meadow": "oak",
    "taiga": "spruce", "old_growth_pine_taiga": "pine",
    "old_growth_spruce_taiga": "spruce", "snowy_taiga": "spruce",
    "grove": "spruce", "jagged_peaks": "spruce", "windswept_forest": "spruce",
    "jungle": "jungle", "sparse_jungle": "jungle", "bamboo_jungle": "jungle",
    "savanna": "acacia", "savanna_plateau": "acacia", "windswept_savanna": "acacia",
    "swamp": "swamp", "mangrove_swamp": "mangrove",
    "cherry_grove": "cherry",
    "flower_forest": "oak",
}

# 花名里的物种 -> 颜色（供 patch 内随机选色）
_FLOWER_COLORS = [
    (200, 46, 46),    # 红
    (232, 190, 40),   # 黄
    (96, 110, 220),   # 蓝
    (236, 236, 236),  # 白
    (214, 120, 180),  # 粉
    (224, 120, 40),   # 橙
    (150, 90, 180),   # 紫
]
_CROP_COLORS = {
    "cactus": (60, 120, 52), "sugar_cane": (96, 150, 70), "pumpkin": (196, 120, 30),
    "melon": (92, 140, 50), "bamboo": (110, 160, 60), "berry": (150, 60, 70),
}


def _load_json(sub, name):
    p = os.path.join(_WG, sub, name + ".json")
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def _short(name: str) -> str:
    return name.split(":")[-1]


def _attempts_from_placements(placements) -> float:
    """连乘各类 count × rarity 倒数 = 每 chunk 平均尝试次数。"""
    if not isinstance(placements, list):
        return 1.0
    v = 1.0
    for pl in placements:
        t = pl.get("type", "").split(":")[-1]
        if t == "count":
            c = pl.get("count")
            if isinstance(c, dict):
                # weighted_list
                dist = c.get("distribution")
                if isinstance(dist, list):
                    tw = sum(d.get("weight", 0) for d in dist) or 1
                    v *= sum(d.get("data", 0) * d.get("weight", 0) for d in dist) / tw
                else:
                    v *= 1.0
            else:
                v *= float(c)
        elif t == "noise_threshold_count":
            v *= (float(pl.get("below_noise", 0)) + float(pl.get("above_noise", 0))) / 2.0
        elif t == "rarity_filter":
            ch = float(pl.get("chance", 1) or 1)
            v /= max(ch, 1.0)
    return v


_SPECIES_KEYS = ("cherry", "mangrove", "jungle", "acacia", "dark_oak", "birch",
                 "spruce", "pine", "swamp", "fancy_oak", "oak", "palm")


def _species_of(biome_short: str, placed_short: str) -> str:
    """从 placed 名推断树种；多名混种（如 trees_birch_and_oak）时以群系
    主导树种为准，避免"先匹配到 birch 就把整片森林当白桦"的错判。"""
    n = placed_short
    hits = [k for k in _SPECIES_KEYS if k in n]
    biome_sp = _BIOME_SPECIES.get(biome_short)
    if biome_sp:
        # 混种：群系主导树种在命中列表里就用它
        if not hits or len(hits) > 1:
            if biome_sp in hits or len(hits) > 1 or not hits:
                return biome_sp
        return hits[0]
    if hits:
        return hits[0]
    return "default"


_PROFILE: dict[str, dict] = {}


def biome_vegetation(biome_key: str) -> dict:
    """返回 {tree, flower, grass, crop: 每chunk尝试数, species: 树种}。"""
    short = biome_key.split(":")[-1]
    prof = _PROFILE.get(short)
    if prof is not None:
        return prof
    b = _load_json("biome", short)
    acc = {"tree": 0.0, "flower": 0.0, "grass": 0.0, "crop": 0.0}
    species = _BIOME_SPECIES.get(short, "default")
    crop_kind = ""
    if b:
        feats = b.get("features", [])
        for si in _VEGETATION_STEPS:
            if si >= len(feats):
                continue
            for ref in feats[si]:
                name = ref if isinstance(ref, str) else ref.get("name", "")
                ps = _short(name)
                pf = _load_json("placed_feature", ps)
                if not pf:
                    continue
                # 类别：优先跟随 configured 真实结构，回退名称
                cat = _configured_category(_sub_feature(pf.get("feature", "")))
                if cat == "ignore":
                    cat = _classify(ps)
                if cat == "ignore":
                    continue
                att = _attempts_from_placements(pf.get("placement", []))
                acc[cat] += att
                if cat == "tree" and att > 0:
                    species = _species_of(short, ps)
                if cat == "crop":
                    for ck in _CROP_COLORS:
                        if ck in ps:
                            crop_kind = ck
    # 归一化到"每方块命中概率"：尝试数 / 256（chunk 面积），上限截断
    prof = {
        "tree": min(acc["tree"] / 256.0, 0.5),
        "flower": min(acc["flower"] / 256.0, 0.6),
        "grass": min(acc["grass"] / 256.0, 0.8),
        "crop": min(acc["crop"] / 256.0, 0.3),
        "species": species,
        "crop_kind": crop_kind,
    }
    # 显式 override：数据驱动判不准/需目视校准的群系（如竹林 checked
    # 树失败率、noise_based_count 竹密度），未覆盖字段保留数据驱动值
    ov = _BIOME_VEG_OVERRIDE.get(short)
    if ov:
        prof = {**prof, **ov}
    _PROFILE[short] = prof
    return prof


def species_canopy(species: str):
    return _SPECIES.get(species, _SPECIES["default"])


# ===========================================================================
# 冠内台阶剖面（树冠高度场逐格降差，0 = 冠顶层）
# ===========================================================================
# JM 的树冠立体感来自真实树叶的**分层摆放**：叶放置器逐层(yo)放叶，冠顶
# 窄、下层宽，JM heightmap（precipitationHeight 含树叶）在冠内就有台阶，
# populateSlopes 对台阶施加 bevel -> 北缘亮 / 南缘暗 / 冠内 2~3 级明暗。
# 此前树冠是同高平坦层（冠内 slope 恒 1，全平），与 JM 相比缺少台阶状
# 立体感。本函数按 26.2 反编译叶放置器几何返回「该列相对冠顶 H 的高度
# 降差」，剖面依据（.temp/mc262_decompile foliageplacers/）：
#   blob_foliage_placer（oak/birch r2 h3 off0）：yo=0/-1 r1、yo=-2/-3 r2
#       -> 核 3×3 在 H，外环在 H-2（swamp 真值 blob r3 核 cheb≤2，但
#          rad=2 冠按 blob r2 剖面近似）
#   fancy_foliage_placer（r2 off4 h4）：顶帽 r2 + 三层 r3 圆角 -> 0/1/2
#   jungle_foliage_placer（mega，r2 h2）：顶 r3 圆 + 下层 r4 环 -> 0/1
#   acacia_foliage_placer（r2）：顶 3×3 + 下层 5×5 缺角 -> 0/1（平台冠）
#   dark_oak_foliage_placer：y+1 r2 圆角(13格) + y0 r3 最宽 -> 0/1
#   spruce_foliage_placer：交替环带锥 r0,1,0,1,2（角格跳过）
#       -> 中心 0 / 十字环 1 / 斜角+外环 4（首个 r2 层在 yo=-4）
#   pine_foliage_placer（r1 off1）：顶单格 + r1 十字层 -> 0/1/2
#   cherry_foliage_placer（r4 h5）：r1 顶 / r2 中 / r3 底 圆顶 -> 0/1/2
#   random_spread_foliage_placer（mangrove r3 fh2）：散布团 -> 核 0 / 环 1
def crown_step(species: str, dx: int, dz: int) -> int:
    sp = species
    cheb = max(abs(dx), abs(dz))
    if sp in ("oak", "birch", "swamp", "palm", "default"):
        return 0 if cheb <= 1 else 2
    if sp == "fancy_oak":
        if cheb <= 1:
            return 0
        return 1 if dx * dx + dz * dz <= 9 else 2
    if sp == "jungle":
        return 0 if dx * dx + dz * dz <= 9 else 1
    if sp in ("acacia", "dark_oak"):
        return 0 if cheb <= 1 else 1
    if sp == "spruce":
        if dx == 0 and dz == 0:
            return 0
        if cheb == 1 and (dx == 0 or dz == 0):
            return 1
        return 4
    if sp == "pine":
        if dx == 0 and dz == 0:
            return 0
        if cheb == 1 and (dx == 0 or dz == 0):
            return 1
        return 2
    if sp == "cherry":
        return 0 if cheb <= 1 else (1 if cheb <= 2 else 2)
    if sp == "mangrove":
        return 0 if cheb <= 1 else 1
    return 0 if cheb <= 1 else 2


# 树种 -> 冠顶相对地表抬升（= 干高近似，取 26.2 trunk_placer 均值）。
# 真实树冠顶（叶放置 yo=0 层）在干顶；冠顶必须足够高，台阶降差后外环
# 仍高于地表，否则平地上外环会失去树冠资格（首测 H=+2 时 forest 缩水
# 43%：外环 H-2=+0 不高于地表，成片退回 grass_block）。
#   oak 干 4-6 / birch 5-7 / fancy_oak 3-14（含分枝）/ spruce 5-8+offset
#   pine 6-10+1 / jungle(mega) 10-31 / acacia 5-9（含横枝）/ dark_oak 6-9
#   swamp_oak 5-8 / mangrove 2-7（向上分枝）/ cherry 7-8
_CROWN_TOP = {
    "oak": 5, "birch": 5, "default": 5, "palm": 5,
    "fancy_oak": 8, "spruce": 6, "pine": 8, "jungle": 12,
    "acacia": 7, "dark_oak": 8, "swamp": 6, "mangrove": 6, "cherry": 8,
}


def crown_top(species: str) -> int:
    return _CROWN_TOP.get(species, 5)


def flower_color(idx: int):
    return _FLOWER_COLORS[idx % len(_FLOWER_COLORS)]


def crop_color(kind: str):
    return _CROP_COLORS.get(kind, (100, 150, 60))
