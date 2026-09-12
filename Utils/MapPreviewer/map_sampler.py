# -*- coding: utf-8 -*-
"""MapPreviewer 世界俯视图采样器。

把 Utils/SeedReverser/biome_noise.py 的 BiomeSampler（1.18+ 主世界群系
逐点采样，与 cubiomes biomenoise.c 位级对拍）扩展成矩形区域批量采样，
产出 numpy uint8 RGB 矩阵，供 UI 层转 QImage 显示。

引擎说明：
    native 优先：Utils/MapPreviewer/_native/_map_sampler.pyd（C++ 多线程，
    管线与 _biome_refine.cpp 同源，已与纯 Python 路径逐点对拍）；
    缺失或加载/调用失败时自动降级纯 Python 逐点路径（结果位级一致，
    仅速度差异）。

坐标约定：
    方块坐标 (bx, bz) → 噪声格坐标 = 方块 >> 2（1:4）
    每个像素 = 1 个噪声格 = 4x4 方块
    采样层固定 ny=16（方块层 y≈64~79，海平面地表层，与 F3 群系判定
    一致层，经用户真实数据校准）

表面层模式（surface_mode，最高方块渲染）：
    固定层切入高山山体（depth 参数 > 0，即采样层在真实地表之下）时
    btree 最近邻会判到地下群系（174 滴水石/175 繁茂洞/183 深暗之域），
    俯视图上表现为"地表随处可见溶洞"。surface_mode=True 时把这些格
    的 depth 参数置 0（地表线 d=0）重判群系；d<=0（水面/低地）不动
    → 水色零回归。depth 矩阵仍用原始 d（hillshade/水深渐变不变）。
"""

from __future__ import annotations

import time

import numpy as np

from Utils.SeedReverser.biome_noise import BiomeSampler
from Utils.SeedReverser.biome_noise import climate_to_biome
from Utils.SeedReverser.biome_noise import VERSION_TO_BTREE, _load_btree
from Utils.MapPreviewer.biome_colors import biome_color

# ---- native 扩展（可选，缺失或异常时降级纯 Python 路径）----
try:
    from Utils.MapPreviewer._native import _map_sampler as _native_ext
except Exception:  # ImportError 以及扩展自身导入期异常，一律降级
    _native_ext = None

# native 端已推入的 btree 版本名集合（避免每次调用重复推数据）
_NATIVE_BTREES: set[str] = set()

# 默认采样层（噪声格 y）：ny=16 ≈ 方块层 64~79，地表层
DEFAULT_NY = 16


def _ensure_native_btree(btree_name: str) -> None:
    """把指定版本 btree 数据推入 native 扩展（每版本仅首次）。"""
    if _native_ext is None or btree_name in _NATIVE_BTREES:
        return
    bt = _load_btree(btree_name)
    _native_ext.set_btree(
        btree_name,
        np.ascontiguousarray(bt.steps, dtype=np.uint32),
        np.ascontiguousarray(bt.param, dtype=np.int64),
        np.ascontiguousarray(bt.nodes, dtype=np.uint64),
        bt.order,
    )
    _NATIVE_BTREES.add(btree_name)


def sample_region(
    seed: int,
    version_key: str,
    cx_blocks: int,
    cz_blocks: int,
    width_blocks: int,
    height_blocks: int,
    ny: int = DEFAULT_NY,
    on_progress=None,
    cancel=None,
    want_depth: bool = False,
    want_temp_humid: bool = False,
    surface_mode: bool = True,
) -> dict:
    """采样矩形区域，返回 dict 载荷（线程与 UI 解耦）。

    Args:
        seed: 世界种子（有符号 int64，内部按无符号 64 位处理）。
        version_key: 版本键 "1.18"~"1.21"。
        cx_blocks/cz_blocks: 区域中心（方块坐标）。
        width_blocks/height_blocks: 区域宽高（方块，内部对齐 4 的倍数）。
        ny: 采样层（噪声格 y）。
        on_progress: on_progress(done, total, msg) 回调（节流由线程负责）。
        cancel: cancel() -> bool，返回 True 时尽快返回部分结果。
        want_depth: 是否同时返回 depth 参数矩阵（1.18+ 地形起伏骨架，
            不额外增加采样成本）。
        want_temp_humid: 是否同时返回温度/湿度参数矩阵（方块级草色
            tint、水面渐变等渲染增强用；不额外增加采样成本）。
        surface_mode: 表面层重判（最高方块渲染）。采样层切入山体
            （d>0）时置 depth=0 重判为地表群系，消除"地表溶洞"；
            默认 True（俯视图语义），结构校验路径不经过此函数。

    Returns:
        dict: {
            "rgb": np.ndarray (H, W, 3) uint8,
            "biomes": np.ndarray (H, W) int32,
            "depth": np.ndarray (H, W) int32   # 仅 want_depth=True；
                # 即 climate_point 第 5 参数的 np 量化值（depth*10000），
                # 值域约 [-12850, 6160]（海平面≈-1585）
            "origin_bx": 区域左上角方块 x（对齐 4）,
            "origin_bz": 区域左上角方块 z,
            "ny": ny,
            "surface_mode": surface_mode,
            "engine": "native" | "python",
            "elapsed": 秒,
            "cancelled": bool,
            "rows_done": 已完成行数（取消时为部分行）,
            "depth": 仅 want_depth=True；climate 第 5 参数的 np 量化值
                （depth*10000，海平面≈-1585）
            "temp"/"humid": 仅 want_temp_humid=True；气候第 1/2 参数的
                np 量化值（温度/湿度*10000）
        }
    """
    t0 = time.perf_counter()

    # 宽高对齐 4 的倍数（噪声格整数像素）
    w = max(16, (int(width_blocks) // 4) * 4)
    h = max(16, (int(height_blocks) // 4) * 4)
    nw = w >> 2
    nh = h >> 2

    # 左上角噪声格（中心对齐）
    origin_nx = (int(cx_blocks) - w // 2) >> 2
    origin_nz = (int(cz_blocks) - h // 2) >> 2

    # ---- native 路径 ----
    if _native_ext is not None:
        try:
            btree_name = VERSION_TO_BTREE[version_key]
            _ensure_native_btree(btree_name)
            res = _native_ext.sample_map(
                seed, btree_name, origin_nx, origin_nz, nw, nh, ny,
                on_progress=on_progress, check_cancel=cancel,
                want_depth=want_depth,
                want_temp_humid=want_temp_humid,
                surface_mode=surface_mode,
            )
            biomes = np.asarray(res["biomes"], dtype=np.int32)
            cancelled = bool(res["cancelled"])
            rows_done = int(res["rows_done"])
            rgb = _colors_for(biomes)
            out = {
                "rgb": rgb,
                "biomes": biomes,
                "origin_bx": origin_nx << 2,
                "origin_bz": origin_nz << 2,
                "ny": ny,
                "surface_mode": surface_mode,
                "engine": "native",
                "elapsed": time.perf_counter() - t0,
                "cancelled": cancelled,
                "rows_done": rows_done,
            }
            if want_depth:
                out["depth"] = np.asarray(res["depth"], dtype=np.int32)
            if want_temp_humid:
                out["temp"] = np.asarray(res["temp"], dtype=np.int32)
                out["humid"] = np.asarray(res["humid"], dtype=np.int32)
            return out
        except Exception:
            # native 失败（btree 未初始化、内存不足等）→ 降级纯 Python
            pass

    # ---- 纯 Python 路径（位级一致的兜底）----
    sampler = BiomeSampler(seed, version_key)
    btree = sampler._btree

    rgb = np.empty((nh, nw, 3), dtype=np.uint8)
    biomes = np.empty((nh, nw), dtype=np.int32)
    depth = np.empty((nh, nw), dtype=np.int32) if want_depth else None
    temp = np.empty((nh, nw), dtype=np.int32) if want_temp_humid else None
    humid = np.empty((nh, nw), dtype=np.int32) if want_temp_humid else None
    cancelled = False

    total = nh
    done_rows = 0
    for row in range(nh):
        if cancel is not None and cancel():
            cancelled = True
            break
        nz = origin_nz + row
        for col in range(nw):
            np6 = sampler.climate_point_xz(origin_nx + col, nz, ny)
            if surface_mode and np6[4] > 0:
                # 表面层重判：采样层在真实地表之下（高山内部）→
                # depth 参数置 0（地表线 d=0）重判群系；
                # depth 矩阵仍记原始 d（与 native 路径一致）
                d_raw = np6[4]
                np6 = np6[:4] + (0,) + np6[5:]
                biomes[row, col] = climate_to_biome(np6, btree)
                if depth is not None:
                    depth[row, col] = d_raw
            else:
                biomes[row, col] = climate_to_biome(np6, btree)
                if depth is not None:
                    depth[row, col] = np6[4]
            if temp is not None:
                temp[row, col] = np6[0]
                humid[row, col] = np6[1]
        done_rows = row + 1
        if on_progress is not None:
            on_progress(done_rows, total, "python")

    rgb = _colors_for(biomes)

    out = {
        "rgb": rgb,
        "biomes": biomes,
        "origin_bx": origin_nx << 2,
        "origin_bz": origin_nz << 2,
        "ny": ny,
        "surface_mode": surface_mode,
        "engine": "python",
        "elapsed": time.perf_counter() - t0,
        "cancelled": cancelled,
        "rows_done": done_rows,
    }
    if depth is not None:
        out["depth"] = depth
    if temp is not None:
        out["temp"] = temp
        out["humid"] = humid
    return out


def _colors_for(biomes: np.ndarray) -> np.ndarray:
    """int32 群系矩阵 → uint8 RGB 矩阵（numpy 向量化查表）。"""
    table = np.zeros(256, dtype=np.uint8)
    rgb = np.empty((biomes.shape[0], biomes.shape[1], 3), dtype=np.uint8)
    for ch in range(3):
        # 群系 id 0~255；超出范围的 id 按兜底色处理
        lut = table
        for bid in range(256):
            lut[bid] = biome_color(bid)[ch]
        rgb[:, :, ch] = lut[np.clip(biomes, 0, 255)]
    return rgb
