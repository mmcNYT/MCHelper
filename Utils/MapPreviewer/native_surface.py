# -*- coding: utf-8 -*-
"""surface 规则树 -> native blob（MDS1 格式）。

与 density blob 分离：surface 独立编译，可在不同 seed 间复用结构，
只有彩带表随 seed 变化。

对外:
    build_surface_blob(sampler, biome_ids) -> (blob, block_names)
"""
from __future__ import annotations

import json
import os
import struct

from Utils.MapPreviewer import density_sampler as ds

RULE_BLOCK, RULE_SEQUENCE, RULE_CONDITION, RULE_BANDLANDS = 0, 1, 2, 3

COND_NOT, COND_BIOME, COND_NOISE_THRESHOLD, COND_VERTICAL_GRADIENT = 0, 1, 2, 3
COND_ABOVE_PRELIM, COND_STONE_DEPTH, COND_Y_ABOVE, COND_WATER = 4, 5, 6, 7
COND_HOLE, COND_STEEP, COND_TEMPERATURE = 8, 9, 10

_BIOME_TEMP_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_native", "worldgen", "26.2",
    "biome_temps.json")

# temperature_modifier = frozen 的群系
_FROZEN_BIOMES = {"frozen_ocean", "deep_frozen_ocean", "frozen_river",
                  "snowy_plains", "snowy_taiga", "snowy_beach", "snowy_slopes",
                  "ice_spikes", "frozen_peaks", "grove"}


class SurfaceCompiler:
    def __init__(self, sampler, key2id: dict[str, int]):
        """key2id: {"minecraft:ocean": 24, ...}（键是带命名空间的群系名）。"""
        self.s = sampler
        self.biome_ids = key2id
        self.block_names: list[str] = []
        self._block_idx: dict[str, int] = {}
        self.rules: list[dict] = []
        self.conds: list[dict] = []
        self.children: list[int] = []
        self._noise_idx: dict[str, int] = {}
        self.noises: list[tuple] = []

    # ---- 基础 ----
    def _block(self, name):
        v = self._block_idx.get(name)
        if v is None:
            v = len(self.block_names)
            self.block_names.append(name)
            self._block_idx[name] = v
        return v

    def _noise_id(self, name):
        if name in self._noise_idx:
            return self._noise_idx[name]
        fo, amps = self.s._load_noise_params(name)
        lo, hi = ds._seed_from_hash(name)
        self.noises.append((name, int(fo), [float(a) for a in amps],
                            lo & ds._MASK64, hi & ds._MASK64))
        v = len(self.noises) - 1
        self._noise_idx[name] = v
        return v

    def _add_rule(self, **kw):
        n = {"type": RULE_BLOCK, "p0": -1, "a0": -1, "a1": -1,
             "child_off": 0, "child_cnt": 0}
        n.update(kw)
        self.rules.append(n)
        return len(self.rules) - 1

    def _add_cond(self, **kw):
        c = {"type": COND_NOT, "a0": -1, "p": [0.0, 0.0, 0.0, 0.0],
             "noise": -1, "flag": False, "i0": 0, "i1": 0, "biomes": []}
        c.update(kw)
        self.conds.append(c)
        return len(self.conds) - 1

    def _anchor(self, a):
        return ds._vertical_anchor(a)

    # ---- 条件 ----
    def compile_cond(self, node):
        typ = node.get("type", "").split(":")[-1]

        if typ == "not":
            sub = self.compile_cond(node["invert"])
            return self._add_cond(type=COND_NOT, a0=sub)

        if typ == "biome":
            raw = node["biome_is"]
            names = raw if isinstance(raw, list) else [raw]
            ids = []
            for n in names:
                nm = n if n.startswith("minecraft:") else "minecraft:" + n
                bid = self.biome_ids.get(nm)
                if bid is not None:
                    ids.append(bid)
            return self._add_cond(type=COND_BIOME, biomes=ids)

        if typ == "noise_threshold":
            nid = self._noise_id(node["noise"])
            return self._add_cond(
                type=COND_NOISE_THRESHOLD, noise=nid,
                p=[float(node["min_threshold"]), float(node["max_threshold"]),
                   0.0, 0.0],
                flag=bool(node.get("is_3d", False)))

        if typ == "vertical_gradient":
            # random_name 不是 worldgen/noise 资源，而是用于
            # surface_random_float(x,y,z) 的语义标记（见 SurfaceRules
            # VerticalGradientCondition：按 block pos 取随机，不走噪声表）。
            return self._add_cond(
                type=COND_VERTICAL_GRADIENT,
                i0=self._anchor(node["true_at_and_below"]),
                i1=self._anchor(node["false_at_and_above"]))

        if typ == "above_preliminary_surface":
            return self._add_cond(type=COND_ABOVE_PRELIM)

        if typ == "stone_depth":
            return self._add_cond(
                type=COND_STONE_DEPTH,
                p=[0.0, 0.0, float(node["offset"]), 0.0],
                flag=(node["surface_type"] == "ceiling"),
                i0=1 if node["add_surface_depth"] else 0,
                i1=int(node["secondary_depth_range"]),
                p1=float(node["secondary_depth_range"]))

        if typ == "y_above":
            return self._add_cond(
                type=COND_Y_ABOVE,
                p=[float(self._anchor(node["anchor"])), 0.0, 0.0, 0.0],
                flag=bool(node["add_stone_depth"]),
                i1=int(node["surface_depth_multiplier"]))

        if typ == "water":
            return self._add_cond(
                type=COND_WATER,
                p=[float(node["offset"]), 0.0, 0.0, 0.0],
                flag=bool(node["add_stone_depth"]),
                i1=int(node["surface_depth_multiplier"]))

        if typ == "hole":
            return self._add_cond(type=COND_HOLE)

        if typ == "steep":
            return self._add_cond(type=COND_STEEP)

        if typ == "temperature":
            return self._add_cond(type=COND_TEMPERATURE)

        raise NotImplementedError(f"surface 条件未支持: {typ}")

    # ---- 规则 ----
    def compile_rule(self, node):
        typ = node.get("type", "").split(":")[-1]

        if typ == "block":
            return self._add_rule(type=RULE_BLOCK,
                                  p0=self._block(node["result_state"]["Name"]))

        if typ == "sequence":
            subs = []
            for s in node["sequence"]:
                subs.append(self.compile_rule(s))
            # child_off 必须在递归编译完子节点之后再取：
            # 嵌套 sequence 会先向 self.children 追加，提前取会指向错位
            off = len(self.children)
            self.children.extend(subs)
            return self._add_rule(type=RULE_SEQUENCE,
                                  child_off=off, child_cnt=len(subs))

        if typ == "condition":
            c = self.compile_cond(node["if_true"])
            then = self.compile_rule(node["then_run"])
            return self._add_rule(type=RULE_CONDITION, a0=c, a1=then)

        if typ == "bandlands":
            return self._add_rule(type=RULE_BANDLANDS)

        raise NotImplementedError(f"surface 规则未支持: {typ}")


def build_surface_blob(sampler, biome_ids: dict[str, int],
                       version: str = "26.2"):
    """编译主世界 surface_rule + 彩带表 + biome 温度。

    Returns:
        (blob: bytes, block_names: list[str], noise_names: list[str])
    """
    # 调用方持有 id->key（BIOME_ID 反查表）；compiler 需要 key->id
    key2id = {str(nm): int(bid) for bid, nm in biome_ids.items()}
    comp = SurfaceCompiler(sampler, key2id)

    ow = os.path.join(os.path.dirname(sampler._df_dir),
                      "noise_settings", "overworld.json")
    with open(ow, encoding="utf-8") as f:
        settings = json.load(f)
    root = comp.compile_rule(settings["surface_rule"])

    # 彩带表（与 Python 引擎同 RNG 路径）
    cb = ds.Xoroshiro128.from_hash_xor("minecraft:clay_bands",
                                       sampler._pos_lo, sampler._pos_hi)
    rng = ds._SurfaceRandomSource(cb.lo, cb.hi)
    bands = ds.SurfaceRulesEngine._generate_bands(rng)
    band_ids = [comp._block(nm) for nm in bands]

    # clay_bands_offset 噪声
    clay_off = comp._noise_id("minecraft:clay_bands_offset")

    # biome 温度表
    temps = {}
    try:
        with open(_BIOME_TEMP_FILE, encoding="utf-8") as f:
            temps = json.load(f)
    except Exception:
        pass

    b = bytearray()
    b += b"MDS1"

    # 方块名表
    b += struct.pack("<I", len(comp.block_names))
    for nm in comp.block_names:
        raw = nm.encode("utf-8")
        b += struct.pack("<I", len(raw)) + raw

    # 规则
    b += struct.pack("<I", len(comp.rules))
    for r in comp.rules:
        b += struct.pack("<6i", r["type"], r["p0"], r["a0"], r["a1"],
                         r["child_off"], r["child_cnt"])

    # 条件
    b += struct.pack("<I", len(comp.conds))
    for c in comp.conds:
        b += struct.pack("<2i", c["type"], c["a0"])
        b += struct.pack("<4d", *c["p"])
        b += struct.pack("<i", c["noise"])
        b += struct.pack("<B", 1 if c["flag"] else 0)
        b += struct.pack("<2i", c["i0"], c["i1"])
        b += struct.pack("<I", len(c["biomes"]))
        for bid in c["biomes"]:
            b += struct.pack("<i", bid)

    # children
    b += struct.pack("<I", len(comp.children))
    for ch in comp.children:
        b += struct.pack("<i", ch)
    b += struct.pack("<i", root)

    # 彩带
    b += struct.pack("<I", len(band_ids))
    for v in band_ids:
        b += struct.pack("<i", v)
    b += struct.pack("<i", clay_off)

    # biome 温度表（id -> (temp, frozen)）
    ent = []
    for bid, nm in biome_ids.items():          # biome_ids: id -> "minecraft:key"
        short = str(nm).split(":")[-1]
        if short in temps:
            ent.append((int(bid), float(temps[short]),
                        1 if short in _FROZEN_BIOMES else 0))
    b += struct.pack("<I", len(ent))
    for bid, tv, fz in ent:
        b += struct.pack("<IdB", bid, tv, fz)

    # biome 名表（id -> "minecraft:key"；native 侧 eroded/frozen 判定用）
    b += struct.pack("<I", len(biome_ids))
    for bid, nm in biome_ids.items():
        raw = str(nm).encode("utf-8")
        b += struct.pack("<iI", int(bid), len(raw)) + raw

    # surface 噪声表（surface 编译器独立索引；native 用 st->noises[n.noise]）
    b += struct.pack("<I", len(comp.noises))
    for (nm, fo, amps, lo, hi) in comp.noises:
        b += struct.pack("<i", int(fo))
        b += struct.pack("<I", len(amps))
        for a in amps:
            b += struct.pack("<d", a)
        b += struct.pack("<QQ", lo, hi)

    # SurfaceSystem 构造函数固定创建的 8 个噪声（L54-63）：
    # 即使 surface_rule 未引用，native 侧 extension 也需要实例。
    FIXED = ["minecraft:surface", "minecraft:surface_secondary",
             "minecraft:badlands_pillar", "minecraft:badlands_pillar_roof",
             "minecraft:badlands_surface", "minecraft:iceberg_pillar",
             "minecraft:iceberg_pillar_roof", "minecraft:iceberg_surface",
             "minecraft:clay_bands_offset"]
    for nm in FIXED:
        if nm not in comp._noise_idx:
            comp._noise_id(nm)

    noise_names = [n[0] for n in comp.noises]
    return bytes(b), comp.block_names, noise_names, comp.noises


def build_surface_noise_blob(comp_noises):
    """surface 专用噪声表（8 个槽位），写入 density blob 末尾。"""
    SLOTS = {
        "minecraft:surface": 0,
        "minecraft:surface_secondary": 1,
        "minecraft:badlands_surface": 2,
        "minecraft:badlands_pillar": 3,
        "minecraft:badlands_pillar_roof": 4,
        "minecraft:iceberg_surface": 5,
        "minecraft:iceberg_pillar": 6,
        "minecraft:iceberg_pillar_roof": 7,
    }
    seen = {}
    for (nm, fo, amps, lo, hi) in comp_noises:
        if nm in SLOTS:
            seen[SLOTS[nm]] = (fo, amps, lo, hi)
    b = bytearray()
    b += struct.pack("<I", len(seen))
    for slot in sorted(seen):
        fo, amps, lo, hi = seen[slot]
        b += struct.pack("<i", int(fo))
        b += struct.pack("<I", len(amps))
        for a in amps:
            b += struct.pack("<d", a)
        b += struct.pack("<QQ", lo, hi)
        b += struct.pack("<i", slot)
    return bytes(b)
