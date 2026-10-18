# -*- coding: utf-8 -*-
"""村庄 jigsaw 严格拼接（26.2）。

MC 的 jigsaw 生成（JigsawPlacement.addPieces）：
  1. 从 start_pool 按权重取模板，放到锚点（初始朝向 north, 不旋转）
  2. 遍历已放模板的 jigsaw 方块：
       - 取该方块的 orientation -> 出方向 dir 与「连接面法线」
       - 按 nbt.pool 取目标池，剔除 name 与 target 不匹配的候选
       - 候选模板随机旋转（joint=rollable 时允许绕轴向翻转）
       - 把候选模板的「对接 jigsaw」平移到本 jigsaw 前方 1 格，朝向相反
       - 检查不与已放模板 AABB 相交（allowOverlap 除外）
  3. 递归到 size 层或达到 max_distance_from_center

本模块实现上述流程（近似处已在注释标明）。
"""
from __future__ import annotations

import json

import numpy as np

from Utils.MapPreviewer import village_jigsaw as _vj

# 方块朝向 -> (dx, dz)
_DIR_VEC = {
    "north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0),
    "up": (0, 0), "down": (0, 0),
}
_OPPOSITE = {"north": "south", "south": "north", "west": "east",
             "east": "west", "up": "down", "down": "up"}


def _parse_orientation(orient: str):
    """orientation -> (出方向, 顶面朝向)。

    MC 的 JigsawBlock orientation 形如 'north_up' / 'up_north'：
    第一个分量是**连接面朝向（front）**，第二个是顶面朝向。
    水平连接点为 'north_up'/'south_up'/'east_up'/'west_up'（front 水平），
    垂直连接点为 'up_north'/'down_south' 等（front 竖直）。
    故 front 一律取第一个分量。
    """
    parts = (orient or "north_up").split("_")
    front = parts[0] if parts else "north"
    top = parts[1] if len(parts) > 1 else "up"
    return front, top


def _rotate(dx: int, dz: int, turns: int):
    """把偏移绕 Y 轴顺时针旋转 turns 个 90°（MC 的 ROT_90）。"""
    for _ in range(turns % 4):
        dx, dz = -dz, dx
    return dx, dz


def _rot_dir(d: str, turns: int) -> str:
    order = ["north", "east", "south", "west"]
    if d not in order:
        return d
    return order[(order.index(d) - turns) % 4]


def load_pool(pool_loc: str):
    """返回 [(weight, location, element_dict)]（只保留 single_pool_element）。"""
    path = "data/%s/worldgen/template_pool/%s.json" % tuple(
        pool_loc.split(":", 1) if ":" in pool_loc
        else ("minecraft", pool_loc))
    try:
        d = json.loads(_vj._jar().read(path))
    except KeyError:
        return []
    out = []
    for e in d.get("elements", []):
        el = e.get("element", {})
        et = el.get("element_type", "").split(":")[-1]
        loc = (el.get("location") or "").replace("minecraft:", "")
        if not loc:
            continue
        # 只处理单模板（legacy_single_pool_element / single_pool_element）
        if et not in ("legacy_single_pool_element", "single_pool_element"):
            continue
        out.append((int(e.get("weight", 1)), loc, el))
    return out


class Placed:
    __slots__ = ("loc", "ox", "oy", "oz", "turns", "size")

    def __init__(self, loc, ox, oy, oz, turns, size):
        self.loc = loc
        self.ox, self.oy, self.oz = ox, oy, oz
        self.turns = turns
        self.size = size

    def aabb(self, pad: int = 0):
        sx, sy, sz = self.size
        if self.turns % 2:
            sx, sz = sz, sx
        return (self.ox - pad, self.oy - pad, self.oz - pad,
                self.ox + sx + pad, self.oy + sy + pad, self.oz + sz + pad)


def _overlaps(a, b) -> bool:
    return not (a[3] <= b[0] or b[3] <= a[0] or
                a[4] <= b[1] or b[4] <= a[1] or
                a[5] <= b[2] or b[5] <= a[2])


def build_village(seed: int, anchor_x: int, anchor_z: int,
                  variant: str = "plains", size: int = 6,
                  max_distance: int = 80, max_pieces: int = 120,
                  max_blocks: int = 250000) -> dict:
    """严格 jigsaw 拼接（对齐 JigsawPlacement.addPieces 的语义）。"""
    rng = np.random.default_rng(
        (seed * 2654435761 ^ anchor_x * 40503 ^ anchor_z) & 0xFFFFFFFF)

    placed: list[Placed] = []
    out_blocks: list[tuple] = []
    out_conns: list[dict] = []      # 待处理的连接点
    block_count = 0

    def emit(tpl, p: Placed):
        nonlocal block_count
        for (x, y, z, nm) in tpl["blocks"]:
            dx, dz = _rotate(x, z, p.turns)
            if p.turns % 2:
                # 旋转 90/270 后宽高互换，需以旋转后尺寸修正 x
                sx, _, sz = tpl["size"]
                dx, dz = _rotate(x, z, p.turns)
                dx += (sz - 1) if p.turns % 4 == 1 else 0
                dz += (sx - 1) if p.turns % 4 == 3 else 0
            out_blocks.append((p.ox + dx, p.oy + y, p.oz + dz, nm))
            block_count += 1
        for (x, y, z, meta) in tpl["jigsaws"]:
            dx, dz = _rotate(x, z, p.turns)
            out_conns.append({
                "wx": p.ox + dx, "wy": p.oy + y, "wz": p.oz + dz,
                "meta": meta, "turns": p.turns,
                "size": tpl["size"],
            })

    # ---- 1) 中心 ----
    pool = load_pool("minecraft:village/%s/town_centers" % variant)
    if not pool:
        return {"blocks": [], "conns": []}
    tot = sum(w for w, _, _ in pool)
    r = rng.random() * tot
    acc = 0.0
    center = pool[-1]
    for w, loc, el in pool:
        acc += w
        if r <= acc:
            center = (w, loc, el)
            break
    ctr_tpl = _vj.load_template("minecraft:" + center[1])
    if ctr_tpl is None:
        return {"blocks": [], "conns": []}
    ctr = Placed(center[1], anchor_x, 64, anchor_z, 0, ctr_tpl["size"])
    placed.append(ctr)
    emit(ctr_tpl, ctr)

    # ---- 2) 逐层扩展 ----
    depth_budget = size
    attempted = set()
    queue = list(out_conns)
    out_conns = []
    while queue and len(placed) < max_pieces and block_count < max_blocks:
        conn = queue.pop(0)
        meta = conn["meta"] or {}
        target_name = meta.get("target", "")
        pool_loc = meta.get("pool", "")
        if not pool_loc:
            continue
        # 该 jigsaw 的出方向：orientation 的 front，旋转后
        orient = meta.get("orientation", "north_up")
        front, _top = _parse_orientation(str(orient))
        front = _rot_dir(front, conn["turns"])
        dx, dz = _DIR_VEC.get(front, (0, -1))
        # 对接位置 = 本 jigsaw 前面 1 格
        nx, nz = conn["wx"] + dx, conn["wz"] + dz
        ny = conn["wy"]

        if (nx, ny, nz, pool_loc) in attempted:
            continue
        attempted.add((nx, ny, nz, pool_loc))

        cands = load_pool(pool_loc)
        if not cands:
            continue
        # 距离限制
        if abs(nx - anchor_x) > max_distance or abs(nz - anchor_z) > max_distance:
            continue

        tot = sum(w for w, _, _ in cands)
        rr = rng.random() * tot
        acc = 0.0
        chosen = cands[-1]
        for w, loc, el in cands:
            acc += w
            if rr <= acc:
                chosen = (w, loc, el)
                break

        tpl = _vj.load_template("minecraft:" + chosen[1])
        if tpl is None:
            continue
        sx, sy, sz = tpl["size"]
        # 需要旋转，使该模板里「target 匹配的对接 jigsaw」朝向 -front
        # 简化：试 4 个旋转，选一个使 AABB 最不重叠且存在匹配对接点
        want_dir = _OPPOSITE[front]
        best = None
        for turns in range(4):
            # 找模板里 name == target_name 的 jigsaw（旋转后朝向 == want_dir）
            hit = None
            for (jx, jy, jz, jmeta) in tpl["jigsaws"]:
                jm = jmeta or {}
                if jm.get("name") != target_name:
                    continue
                jorient = jm.get("orientation", "north_up")
                jf, _jt = _parse_orientation(str(jorient))
                jf = _rot_dir(jf, turns)
                if jf == want_dir:
                    hit = (jx, jy, jz)
                    break
            if hit is None:
                continue
            # 把 hit 平移到 (nx,ny,nz)
            rdx, rdz = _rotate(hit[0], hit[2], turns)
            ox = nx - rdx
            oz = nz - rdz
            oy = ny - hit[1]
            cand = Placed(chosen[1], ox, oy, oz, turns, (sx, sy, sz))
            # 容差 -1：边界恰好相接不算重叠（MC 也允许轻微交叉，
            # 屋檐/楼梯常跨出 1 格）
            if any(_overlaps(cand.aabb(-1), p.aabb(-1)) for p in placed):
                continue
            best = cand
            break
        if best is None:
            continue
        placed.append(best)
        emit(tpl, best)
        # 新连接点入队
        for c in out_conns:
            queue.append(c)
        out_conns = []

    return {"blocks": out_blocks, "conns": out_conns, "pieces": len(placed)}
