# -*- coding: utf-8 -*-
"""把 density_sampler 的 JSON 密度树编译成 native blob（供 _density_sampler.pyd）。

blob 格式见 _native/_density_module.cpp 顶部注释。
纯 Python 端做「JSON 语义 → 扁平数值表」，C++ 端只做求值。
"""
from __future__ import annotations

import json
import os
import struct

from Utils.MapPreviewer import density_sampler as ds

# 与 C++ enum 对应
OP_CONST, OP_Y_GRAD = 0, 1
OP_ADD, OP_MUL, OP_MIN, OP_MAX = 2, 3, 4, 5
OP_HALF_NEG, OP_QUARTER_NEG, OP_HALF_POS, OP_QUARTER_POS = 6, 7, 8, 9
OP_ABS, OP_SQUARE, OP_CUBE, OP_INVERT, OP_SQUEEZE = 10, 11, 12, 13, 14
OP_CLAMP = 15
OP_NOISE = 16
OP_SHIFTED_NOISE = 17
OP_SHIFT_A, OP_SHIFT_B, OP_SHIFT = 18, 19, 20
OP_OLD_BLENDED = 21
OP_SPLINE = 22
OP_RANGE_CHOICE = 23
OP_INTERPOLATED = 24
OP_FIND_TOP = 25
OP_CACHE2D, OP_CACHE_ONCE, OP_PASSTHRU = 26, 27, 28
OP_INTERVAL_SELECT = 29

_MAP_SIMPLE = {
    "half_negative": OP_HALF_NEG, "quarter_negative": OP_QUARTER_NEG,
    "half_positive": OP_HALF_POS, "quarter_positive": OP_QUARTER_POS,
    "abs": OP_ABS, "square": OP_SQUARE, "cube": OP_CUBE,
    "invert": OP_INVERT, "squeeze": OP_SQUEEZE,
}
_PASSTHRU = {"flat_cache", "cache_all_in_cell", "blend_density"}


class Compiler:
    """把 JSON 密度函数编译成扁平节点表。"""

    def __init__(self, sampler, version="26.2"):
        self.s = sampler
        self.nodes = []       # each: dict
        self.splines = []     # each: (coord_node, [points])
        self.noises = []      # each: (first_octave, amps, name_lo, name_hi)
        self._noise_idx = {}
        self._spline_seen = {}
        self._spline_keep = []   # 持住样条对象，防 id 重用
        self.children = []

    # ---- 资源 ----
    def _noise_id(self, name):
        if name in self._noise_idx:
            return self._noise_idx[name]
        fo, amps = self.s._load_noise_params(name)
        lo, hi = ds._seed_from_hash(name)
        # 转成无符号 64 位
        self.noises.append((int(fo), [float(a) for a in amps], lo & ds._MASK64,
                            hi & ds._MASK64))
        idx = len(self.noises) - 1
        self._noise_idx[name] = idx
        return idx

    def _add(self, **kw):
        node = {"op": OP_CONST, "p": [0.0, 0.0, 0.0, 0.0],
                "a": [-1, -1, -1], "noise": -1, "spline": -1, "cell": [4, 8],
                "child_off": 0, "child_cnt": 0}
        node.update(kw)
        self.nodes.append(node)
        return len(self.nodes) - 1

    def _const(self, v):
        return self._add(op=OP_CONST, p=[float(v), 0, 0, 0])

    # ---- 主体 ----
    def compile(self, node):
        if isinstance(node, bool):
            return self._const(1.0 if node else 0.0)
        if isinstance(node, (int, float)):
            return self._const(node)
        if isinstance(node, str):
            return self.compile(self.s._load_df(node))

        typ = node.get("type", "")
        kind = typ.split(":")[-1]

        if kind in ("add", "mul", "min", "max"):
            a = self.compile(node["argument1"])
            b = self.compile(node["argument2"])
            op = {"add": OP_ADD, "mul": OP_MUL, "min": OP_MIN, "max": OP_MAX}[kind]
            return self._add(op=op, a=[a, b, -1])

        if kind in _MAP_SIMPLE:
            a = self.compile(node["argument"])
            return self._add(op=_MAP_SIMPLE[kind], a=[a, -1, -1])

        if kind == "clamp":
            a = self.compile(node["input"])
            return self._add(op=OP_CLAMP, a=[a, -1, -1],
                             p=[float(node["min"]), float(node["max"]), 0, 0])

        if kind == "y_clamped_gradient":
            return self._add(op=OP_Y_GRAD,
                             p=[float(node["from_y"]), float(node["to_y"]),
                                float(node["from_value"]), float(node["to_value"])])

        if kind == "noise":
            nid = self._noise_id(node["noise"])
            return self._add(op=OP_NOISE, noise=nid,
                             p=[float(node.get("xz_scale", 1.0)),
                                float(node.get("y_scale", 1.0)), 0, 0])

        if kind == "shifted_noise":
            nid = self._noise_id(node["noise"])
            sx = self.compile(node.get("shift_x", 0.0))
            sy = self.compile(node.get("shift_y", 0.0))
            sz = self.compile(node.get("shift_z", 0.0))
            return self._add(op=OP_SHIFTED_NOISE, noise=nid, a=[sx, sy, sz],
                             p=[float(node.get("xz_scale", 1.0)),
                                float(node.get("y_scale", 1.0)), 0, 0])

        if kind in ("shift_a", "shift_b", "shift"):
            ref = node["argument"]
            if isinstance(ref, dict):
                ref = ref.get("noise", ref)
            nid = self._noise_id(ref)
            op = {"shift_a": OP_SHIFT_A, "shift_b": OP_SHIFT_B,
                  "shift": OP_SHIFT}[kind]
            return self._add(op=op, noise=nid)

        if kind == "old_blended_noise":
            return self._add(op=OP_OLD_BLENDED,
                             p=[float(node["xz_scale"]), float(node["y_scale"]),
                                float(node["xz_factor"]), float(node["y_factor"])],
                             cell=[int(round(float(node["smear_scale_multiplier"])
                                              * 1000)), 0])

        if kind == "spline":
            sid = self._compile_spline(node["spline"])
            return self._add(op=OP_SPLINE, spline=sid)

        if kind == "range_choice":
            inp = self.compile(node["input"])
            tin = self.compile(node["when_in_range"])
            tout = self.compile(node["when_out_of_range"])
            return self._add(op=OP_RANGE_CHOICE, a=[inp, tin, tout],
                             p=[float(node["min_inclusive"]),
                                float(node["max_exclusive"]), 0, 0])

        if kind == "interpolated":
            a = self.compile(node["argument"])
            return self._add(op=OP_INTERPOLATED, a=[a, -1, -1], cell=[4, 8])

        if kind == "interval_select":
            inp = self.compile(node["input"])
            ths = [float(t) for t in node["thresholds"]]
            if len(ths) > 4:
                raise NotImplementedError("interval_select 阈值超过 4 个")
            fns = [self.compile(f) for f in node["functions"]]
            off = len(self.children)
            self.children.extend(fns)
            return self._add(op=OP_INTERVAL_SELECT, a=[inp, -1, -1],
                             p=[ths[0], ths[1] if len(ths) > 1 else 0.0,
                                ths[2] if len(ths) > 2 else 0.0,
                                ths[3] if len(ths) > 3 else 0.0],
                             cell=[len(ths), 8], child_off=off,
                             child_cnt=len(fns))

        if kind in ("cache_2d", "cache_once"):
            a = self.compile(node["argument"])
            return self._add(op=OP_CACHE2D if kind == "cache_2d" else OP_CACHE_ONCE,
                             a=[a, -1, -1])

        if kind in _PASSTHRU:
            return self.compile(node["argument"])

        if kind == "find_top_surface":
            dens = self.compile(node["density"])
            upper = self.compile(node["upper_bound"])
            return self._add(op=OP_FIND_TOP, a=[dens, upper, -1],
                             p=[0.0, 0.0, float(node["lower_bound"]), 0.0],
                             cell=[int(node["cell_height"]), int(node["cell_height"])])

        if kind == "blend_alpha":
            return self._const(1.0)
        if kind in ("blend_offset", "beardifier"):
            return self._const(0.0)

        raise NotImplementedError(f"native 未支持的密度类型: {typ}")

    def _compile_spline(self, sp):
        # 去重键用 id(sp)，但必须同时持住对象引用（_spline_keep）：
        # 否则对象被 GC 回收后地址会被新对象重用，id() 冲突 → 不同样条
        # 被判为同一个 → spline 索引错挂（曾致 factor 求值 2.19 vs 4.99）。
        # 注意不能用 json.dumps 做键：嵌套样条是内联展开的，序列化会指数爆炸。
        key = id(sp)
        if key in self._spline_seen:
            return self._spline_seen[key]
        self._spline_keep.append(sp)
        coord = self.compile(sp["coordinate"])
        sid = len(self.splines)
        self._spline_seen[key] = sid
        self.splines.append([coord, []])   # 先占位（防递归）
        pts = []
        for p in sp["points"]:
            val = p["value"]
            if isinstance(val, dict) and "coordinate" in val:
                child = self._compile_spline(val)
                pts.append((ds._f32(p["location"]), 0.0,
                            ds._f32(p.get("derivative", 0.0)), child))
            else:
                pts.append((ds._f32(p["location"]), ds._f32(val),
                            ds._f32(p.get("derivative", 0.0)), -1))
        self.splines[sid] = [coord, pts]
        return sid

    # ---- 序列化 ----
    def to_blob(self, root, router_ids, sea_level, blended_params=None,
                terrain_hash=None, surface_noises=None):
        b = bytearray()
        b += b"MDF1"
        b += struct.pack("<I", len(self.nodes))
        for n in self.nodes:
            b += struct.pack("<i", n["op"])
            b += struct.pack("<4d", *n["p"])
            b += struct.pack("<3i", *n["a"])
            b += struct.pack("<2i", n["noise"], n["spline"])
            b += struct.pack("<2i", *n["cell"])
            b += struct.pack("<2i", n["child_off"], n["child_cnt"])
        b += struct.pack("<I", len(self.children))
        for c in self.children:
            b += struct.pack("<i", c)
        b += struct.pack("<I", len(self.splines))
        for coord, pts in self.splines:
            b += struct.pack("<iI", coord, len(pts))
            for loc, val, der, child in pts:
                b += struct.pack("<3fi", loc, val, der, child)
        b += struct.pack("<i", root)
        b += struct.pack("<I", len(self.noises))
        for fo, amps, lo, hi in self.noises:
            b += struct.pack("<i", fo)
            b += struct.pack("<I", len(amps))
            for a in amps:
                b += struct.pack("<d", a)
            b += struct.pack("<QQ", lo, hi)
        for r in router_ids:
            b += struct.pack("<i", r)
        b += struct.pack("<i", sea_level)
        if blended_params is not None and terrain_hash is not None:
            b += struct.pack("<B", 1)
            xz, ys, xf, yf, sm = blended_params
            b += struct.pack("<5d", xz, ys, xf, yf, sm)
            b += struct.pack("<QQ", terrain_hash[0], terrain_hash[1])
        else:
            b += struct.pack("<B", 0)
        if surface_noises is not None:
            b += surface_noises
        else:
            b += struct.pack("<I", 0)
        return bytes(b)


def build_blob(seed, version="26.2"):
    """返回 (blob, compiler) —— 编译主世界 final_density + 含水层 router。"""
    s = ds.build_sampler(seed, version)
    comp = Compiler(s, version)

    ow = os.path.join(os.path.dirname(s._df_dir), "noise_settings", "overworld.json")
    with open(ow, encoding="utf-8") as f:
        settings = json.load(f)
    router = settings["noise_router"]

    root = comp.compile(router["final_density"])
    rids = [comp.compile(router[k]) for k in
            ("barrier", "fluid_level_floodedness", "fluid_level_spread", "lava",
             "erosion", "depth", "preliminary_surface_level")]

    # old_blended_noise 参数：沿引用递归找（base_3d_noise.json 等文件里）
    blended = None
    _seen_refs = set()

    def find_blended(node):
        nonlocal blended
        if blended is not None:
            return
        if isinstance(node, dict):
            if node.get("type", "").endswith("old_blended_noise"):
                blended = (float(node["xz_scale"]), float(node["y_scale"]),
                           float(node["xz_factor"]), float(node["y_factor"]),
                           float(node["smear_scale_multiplier"]))
                return
            for v in node.values():
                find_blended(v)
        elif isinstance(node, list):
            for v in node:
                find_blended(v)
        elif isinstance(node, str) and node not in _seen_refs:
            _seen_refs.add(node)
            try:
                find_blended(s._load_df(node))
            except Exception:
                pass

    find_blended(router["final_density"])
    if blended is None:
        # 兜底：直接读 base_3d_noise.json
        try:
            bn = s._load_df("minecraft:overworld/base_3d_noise")
            find_blended(bn)
        except Exception:
            pass

    th = ds._seed_from_hash("minecraft:terrain")
    blob = comp.to_blob(root, rids, int(settings.get("sea_level", 63)),
                        blended, (th[0] & ds._MASK64, th[1] & ds._MASK64))
    return blob, comp
