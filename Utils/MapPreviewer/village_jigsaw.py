# -*- coding: utf-8 -*-
"""村庄 jigsaw 结构还原（26.2）。

MC 村庄由 jigsaw 系统生成：
  1. 结构定义给出 start_pool（town_centers）与 size（扩展层数）
  2. 从 start_pool 按权重选一个模板，放到锚点
  3. 该模板里的 minecraft:jigsaw 方块记录「连接方向 target_pool」，
     按 name/direction 从 target_pool 按权重选模板拼上去，递归 size 层
  4. 各模板是 gzip 压缩的 NBT（结构方块格式），含 size/palette/blocks

本模块提供：
  - load_template(): 读 jar 内 NBT -> {size, blocks[(x,y,z,block)], jigsaws}
  - VillagePlan: 给定种子+锚点，还原出整座村庄的方块集合（近似）
  - footprint(): 把方块集合压成「每列最高方块」的地图，供渲染
"""
from __future__ import annotations

import gzip
import io
import json
import os
import zipfile

import numpy as np

JAR = (r"C:\maomaochongD\.minecraft\.minecraft\versions"
       r"\26.2-NeoForge\26.2-NeoForge.jar")

# jigsaw 方块名
_JIGSAW = "minecraft:jigsaw"


# ---------------------------------------------------------------------------
# 极简 NBT 解析（只处理结构文件需要的子集）
# ---------------------------------------------------------------------------
class _R:
    def __init__(self, b: bytes):
        self.b = b
        self.i = 0

    def u1(self):
        v = self.b[self.i]; self.i += 1; return v

    def i2(self):
        v = int.from_bytes(self.b[self.i:self.i + 2], "big", signed=True)
        self.i += 2; return v

    def i4(self):
        v = int.from_bytes(self.b[self.i:self.i + 4], "big", signed=True)
        self.i += 4; return v

    def i8(self):
        v = int.from_bytes(self.b[self.i:self.i + 8], "big", signed=True)
        self.i += 8; return v

    def f4(self):
        import struct
        v = struct.unpack(">f", self.b[self.i:self.i + 4])[0]
        self.i += 4; return v

    def f8(self):
        import struct
        v = struct.unpack(">d", self.b[self.i:self.i + 8])[0]
        self.i += 8; return v

    def s(self):
        n = int.from_bytes(self.b[self.i:self.i + 2], "big", signed=False)
        self.i += 2
        v = self.b[self.i:self.i + n].decode("utf-8", "replace")
        self.i += n
        return v

    def raw(self, n):
        v = self.b[self.i:self.i + n]; self.i += n; return v


_TAG_END, _TAG_BYTE, _TAG_SHORT, _TAG_INT, _TAG_LONG = 0, 1, 2, 3, 4
_TAG_FLOAT, _TAG_DOUBLE, _TAG_BYTEARRAY, _TAG_STRING = 5, 6, 7, 8
_TAG_LIST, _TAG_COMPOUND, _TAG_INTARRAY, _TAG_LONGARRAY = 9, 10, 11, 12


def _payload(r: _R, tid: int):
    if tid == _TAG_BYTE:
        return r.u1()
    if tid == _TAG_SHORT:
        return r.i2()
    if tid == _TAG_INT:
        return r.i4()
    if tid == _TAG_LONG:
        return r.i8()
    if tid == _TAG_FLOAT:
        return r.f4()
    if tid == _TAG_DOUBLE:
        return r.f8()
    if tid == _TAG_BYTEARRAY:
        n = r.i4(); return r.raw(n)
    if tid == _TAG_STRING:
        return r.s()
    if tid == _TAG_LIST:
        it = r.u1(); n = r.i4()
        return [_payload(r, it) for _ in range(n)]
    if tid == _TAG_COMPOUND:
        out = {}
        while True:
            t = r.u1()
            if t == _TAG_END:
                break
            name = r.s()
            out[name] = _payload(r, t)
        return out
    if tid == _TAG_INTARRAY:
        n = r.i4(); return [r.i4() for _ in range(n)]
    if tid == _TAG_LONGARRAY:
        n = r.i4(); return [r.i8() for _ in range(n)]
    raise ValueError("bad tag %d" % tid)


def parse_nbt(data: bytes) -> dict:
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    r = _R(data)
    t = r.u1()
    if t != _TAG_COMPOUND:
        raise ValueError("root not compound: %d" % t)
    r.s()                      # root name（通常空）
    return _payload(r, _TAG_COMPOUND)


# ---------------------------------------------------------------------------
# 模板
# ---------------------------------------------------------------------------
_TPL_CACHE: dict[str, dict] = {}
_JAR = None


def _jar() -> zipfile.ZipFile:
    global _JAR
    if _JAR is None:
        _JAR = zipfile.ZipFile(JAR)
    return _JAR


def load_template(loc: str) -> dict | None:
    """loc 形如 'minecraft:village/plains/town_centers/plains_meeting_point_1'"""
    if loc in _TPL_CACHE:
        return _TPL_CACHE[loc]
    path = "data/%s/structure/%s.nbt" % tuple(
        loc.split(":", 1) if ":" in loc else ("minecraft", loc))
    try:
        raw = _jar().read(path)
    except KeyError:
        _TPL_CACHE[loc] = None
        return None
    try:
        nbt = parse_nbt(raw)
    except Exception:
        _TPL_CACHE[loc] = None
        return None
    size = [int(v) for v in nbt.get("size", [0, 0, 0])]
    # 部分结构（沉船等）用 **多调色板** 格式：根键是 palettes（复数），
    # 每个 block 用可选的 palette 索引选择子表；缺省索引 0。
    raw_pal = nbt.get("palette")
    multi = None
    if not raw_pal and nbt.get("palettes"):
        multi = nbt["palettes"]
        raw_pal = multi[0] if multi else []
    raw_pal = raw_pal or []

    def _build(palette_list):
        names, props = [], []
        for p in palette_list:
            names.append(p.get("Name", ""))
            props.append(p.get("Properties") or {})
        return names, props

    pal, pal_props = _build(raw_pal)
    _sub = {0: (pal, pal_props)}
    if multi:
        for _i, _pl in enumerate(multi):
            _sub[_i] = _build(_pl)
    blocks = []
    jigsaws = []
    for b in nbt.get("blocks", []):
        pos = b.get("pos", [0, 0, 0])
        st = int(b.get("state", 0))
        if multi:
            pn = int(b.get("palette", 0) or 0)
            names, props = _sub.get(pn, _sub[0])
        else:
            names, props = pal, pal_props
        nm = names[st] if 0 <= st < len(names) else ""
        x, y, z = int(pos[0]), int(pos[1]), int(pos[2])
        blocks.append((x, y, z, nm))
        if nm == _JIGSAW:
            # jigsaw 的朝向来自 palette 的 Properties.orientation
            # （如 'north_up'），不在 block 的 nbt 里。
            meta = dict(b.get("nbt", {}) or {})
            props = props[st] if 0 <= st < len(props) else {}
            if props.get("orientation"):
                meta["orientation"] = props["orientation"]
            jigsaws.append((x, y, z, meta))
    out = {"size": size, "blocks": blocks, "jigsaws": jigsaws}
    _TPL_CACHE[loc] = out
    return out


def _pool(pool_loc: str):
    """读 template_pool，返回 [(weight, element_dict)]"""
    path = "data/%s/worldgen/template_pool/%s.json" % tuple(
        pool_loc.split(":", 1) if ":" in pool_loc else ("minecraft", pool_loc))
    try:
        d = json.loads(_jar().read(path))
    except KeyError:
        return []
    out = []
    for e in d.get("elements", []):
        el = e.get("element", {})
        out.append((int(e.get("weight", 1)), el))
    return out


def _pick(pool_loc: str, rng) -> dict | None:
    els = _pool(pool_loc)
    if not els:
        return None
    tot = sum(w for w, _ in els)
    r = rng.random() * tot
    acc = 0.0
    for w, el in els:
        acc += w
        if r <= acc:
            return el
    return els[-1][1]


def village_footprint(seed: int, anchor_x: int, anchor_z: int,
                      variant: str = "plains", size: int = 6,
                      max_blocks: int = 40000) -> dict:
    """还原村庄（近似）：返回该村所有模板方块的聚集结果。

    由于完整 jigsaw 需要严格复刻连接点匹配与旋转，这里做等价近似：
      - 从 town_centers 按权重选一个中心模板放锚点（不旋转）
      - 后续按 size 层，从 plains/houses 池随机取房屋，围绕中心排布，
        保持与中心不重叠（按模板尺寸做环形布局）
    返回 {blocks: [(wx,wy,wz,name)], jigsaws: [(wx,wy,wz,dir)]}
    """
    rng = np.random.default_rng(
        (seed * 2654435761 ^ anchor_x * 40503 ^ anchor_z) & 0xFFFFFFFF)
    out_blocks = []
    out_jig = []

    def place(loc, ox, oy, oz):
        tpl = load_template(loc)
        if tpl is None:
            return None
        sx, sy, sz = tpl["size"]
        for (x, y, z, nm) in tpl["blocks"]:
            out_blocks.append((ox + x, oy + y, oz + z, nm))
            if len(out_blocks) > max_blocks:
                return tpl
        for (x, y, z, meta) in tpl["jigsaws"]:
            out_jig.append((ox + x, oy + y, oz + z,
                            meta.get("joint", "")))
        return tpl

    # 中心
    center_pool = "minecraft:village/%s/town_centers" % variant
    el = _pick(center_pool, rng)
    if el is None:
        return {"blocks": [], "jigsaws": []}
    loc = (el.get("location") or "").replace("minecraft:", "")
    ctr = place("minecraft:" + loc, anchor_x, 64, anchor_z)
    if ctr is None:
        return {"blocks": [], "jigsaws": []}
    csx, _, csz = ctr["size"]

    # 房屋池：围绕中心做同心环布局
    house_pools = [
        "minecraft:village/%s/houses" % variant,
        "minecraft:village/%s/streets" % variant,
        "minecraft:village/%s/decor" % variant,
    ]
    placed = [(anchor_x, anchor_z, csx, csz)]
    ring = 0
    while ring < size and len(out_blocks) < max_blocks:
        ring += 1
        radius = ring * 14
        n_slots = 4 + ring * 4
        for k in range(n_slots):
            if len(out_blocks) >= max_blocks:
                break
            ang = 2.0 * np.pi * k / n_slots + rng.random() * 0.3
            hx = anchor_x + int(round(np.cos(ang) * radius))
            hz = anchor_z + int(round(np.sin(ang) * radius))
            pool = house_pools[k % len(house_pools)]
            el = _pick(pool, rng)
            if el is None:
                continue
            loc = (el.get("location") or "").replace("minecraft:", "")
            tpl = load_template("minecraft:" + loc)
            if tpl is None:
                continue
            tw, _, td = tpl["size"]
            # 不重叠检查
            ok = True
            for (px, pz, pw, pd) in placed:
                if (abs(hx - px) < (tw + pw) // 2 + 1
                        and abs(hz - pz) < (td + pd) // 2 + 1):
                    ok = False
                    break
            if not ok:
                continue
            place("minecraft:" + loc, hx, 64, hz)
            placed.append((hx, hz, tw, td))
    return {"blocks": out_blocks, "jigsaws": out_jig}


# 屋顶类方块：这些不该被其它 piece 的地面方块盖住
_ROOF_BLOCKS = {
    "oak_stairs", "spruce_stairs", "birch_stairs", "jungle_stairs",
    "acacia_stairs", "dark_oak_stairs", "mangrove_stairs", "cherry_stairs",
    "oak_slab", "spruce_slab", "birch_slab", "jungle_slab", "acacia_slab",
    "dark_oak_slab", "mangrove_slab", "cherry_slab", "stone_slab",
    "cobblestone_slab", "smooth_stone_slab", "oak_planks", "spruce_planks",
    "birch_planks", "jungle_planks", "acacia_planks", "dark_oak_planks",
    "mangrove_planks", "cherry_planks", "cobblestone", "mossy_cobblestone",
    "white_terracotta", "yellow_terracotta", "orange_terracotta",
    "light_gray_terracotta", "bricks", "stone_bricks", "glass_pane",
    "glass", "terracotta", "deepslate_tiles", "mud_bricks",
}
# 地面类方块（会被屋顶优先覆盖）
_GROUND_BLOCKS = {"dirt_path", "grass_block", "dirt", "coarse_dirt",
                  "gravel", "sand", "podzol", "farmland", "water"}


def footprint_to_grid(fp: dict, x0: int, z0: int, w: int, h: int):
    """把方块集合压成 (h,w) 的方块名网格。

    重要：MC 的 jigsaw 各 piece 独立定位，后放的 piece 不会把地面铺到
    先放 piece 的**屋顶上方**。但简单"取最高方块"会出这个问题——
    后放模板的地面(y=64)恰好盖在先放模板的屋顶(y=65+)之上时，
    俯视就看到了房子内部。

    故采用双优先级：
      1) 屋顶类方块优先（只要有屋顶就显示屋顶）
      2) 其余按最高 y 取
    """
    grid = np.empty((h, w), dtype=object)
    grid[:] = None
    ytop = np.full((h, w), -9999, np.int32)
    roof_y = np.full((h, w), -9999, np.int32)
    roof_nm = np.empty((h, w), dtype=object)
    roof_nm[:] = None
    for (wx, wy, wz, nm) in fp["blocks"]:
        px, pz = wx - x0, wz - z0
        if not (0 <= px < w and 0 <= pz < h):
            continue
        sh = nm.split(":")[-1]
        if sh in ("air", "jigsaw", "structure_void", "cave_air", "void_air"):
            continue
        if sh in _ROOF_BLOCKS:
            if wy > roof_y[pz, px]:
                roof_y[pz, px] = wy
                roof_nm[pz, px] = nm
        if wy > ytop[pz, px]:
            ytop[pz, px] = wy
            grid[pz, px] = nm
    # 屋顶优先覆盖
    has_roof = roof_nm != None
    grid[has_roof] = roof_nm[has_roof]
    return grid
