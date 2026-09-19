# -*- coding: utf-8 -*-
"""世界种子精化（SeedReverser 二期·路线 A）。

给定 48 位结构种候选（= 64 位世界种子的低 48 位），用群系观测点枚举
高位 16 bit，恢复完整 64 位世界种子：

    worldSeed = (high16 << 48) | s48        （high16 ∈ [0, 2^16)）

判定方法：每个高位候选与 s48 拼出 64 位种子，用 biome_noise.BiomeSampler
（已与 cubiomes 45/45 对拍通过）在全部群系观测点采样，全部一致才算通过。

观测点坐标：x/z 为方块坐标（>>2 换算）；y 可选（方块 Y，>>2 换算），
缺省按深层噪声层 y=0 判定。带 y 时与游戏 F3 群系判定一致，
可区分地表与洞穴群系（繁茂/溶洞等在深层大面积判定，不带 y 会误判）。
"""
from __future__ import annotations

import sys
import time

import numpy as np

from .biome_noise import (BiomeSampler, block_to_noise, VERSION_TO_BTREE,
                          get_btree, _load_btree)

# ---- C++ 精化扩展（可选，缺失或异常时降级纯 Python 路径）----
try:
    from ._native import _biome_refine as _native_ext
except Exception:  # ImportError 以及扩展自身导入期异常，一律降级
    _native_ext = None

# native 端已推入的 btree 版本名集合（避免每次调用重复推数据）
_NATIVE_BTREES: set[str] = set()

# 观测点数量下限：主世界 1:4 噪声格上不同群系组合数有限（约 2^14），观测点
# 少于 7 个时判别力上限（2^-7 相对 2^16 枚举空间）不足以保证唯一解；经验上
# 多样群系观测 ≥7 点通常唯一。此处仅做下限校验，不强推观测点多样性。
MIN_OBS = 7

# 进度回调节流：每 64 个高位步触发一次（枚举内层很快，逐次回调开销不可忽略）
_PROGRESS_MASK = 0x3F

# 无符号 64 位 → 有符号 int64（与游戏 /seed、F3 显示一致的表示）。
# C++ 端与 Python 降级路径都以无符号位模式拼种子（(high<<48)|s48 可能 ≥2^63），
# 对外统一转回有符号：x ≥ 2^63 → x - 2^64。
_U64_MASK = (1 << 64) - 1
_S63_SIGN = 1 << 63


def _to_signed64(x: int) -> int:
    """无符号 64 位种子值 → 有符号 int64（超过 2^63-1 时映射为负数）。"""
    x &= _U64_MASK
    return x - (1 << 64) if x & _S63_SIGN else x


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


def _refine_native(cands, obs_list, btree_name, on_progress, cancel, high_span):
    """native 路径（C++ 多线程）；失败抛 RuntimeError 由调用方降级。"""
    if _native_ext is None:
        raise RuntimeError("native 精化扩展不可用")
    _ensure_native_btree(btree_name)
    obs_dicts = [{"nx": nx, "nz": nz, "y": ny, "biome_id": bid}
                 for nx, ny, nz, bid in obs_list]
    arr = _native_ext.refine_full(
        cands, obs_dicts, btree_name, high_span,
        on_progress=on_progress, check_cancel=cancel,
    )
    # C++ 端以无符号位模式返回（uint64 数组），统一转有符号 int64，
    # 避免下游 Qt 信号（int64）与 UI 显示把 ≥2^63 的种子钳成 -1
    return [_to_signed64(int(x)) for x in arr.tolist()]


def _check_cancel(cancel) -> bool:
    """cancel 为可调用对象时执行并转 bool；否则返回 False。"""
    if cancel is None:
        return False
    try:
        return bool(cancel())
    except TypeError:
        return False


def refine_world_seeds(
    candidates,
    biome_obs,
    version_key: str = "1.21",
    on_progress=None,
    cancel=None,
    high_limit=None,
) -> dict:
    """从 48 位结构种候选出发，枚举高 16 位恢复完整 64 位世界种子。

    参数
    ----
    candidates : list[int]
        一期 solve_structure_seeds 输出的候选种子（结构种，即世界种子低 48
        位；超出 48 位会自动掩码截断）。
    biome_obs : list[dict]
        群系观测点列表，每项形如 {"x": 方块x, "z": 方块z, "biome_id": int}，
        可选 {"y": 方块Y}（F3 所示脚下高度）。坐标为方块坐标，内部 >>2
        换算为噪声坐标（与游戏 F3 群系显示一致）；缺 y 按深层噪声层 y=0。
    version_key : str
        版本键（"26.2"/"1.21.11"/"1.21"），决定 btree 表与气候参数。
    on_progress : callable(done, total, msg) | None
        进度回调，done/total 为已枚举高位候选数；节流为每 64 步一次，另有
        候选切换、开始与结束时的即时回调。
    cancel : callable() -> bool | None
        取消检查函数，返回 True 表示请求取消；在候选间与高位步进间检查。
    high_limit : int | None
        调试/快速验证用：只枚举 high16 ∈ [0, high_limit)，None 表示全 2^16。

    返回
    ----
    dict:
        {
            "world_seeds": list[int],   # 全部通过全部观测验证的 64 位种子
            "stages": {
                "candidates": int,      # 输入候选数
                "high_span": int,       # 实际枚举的高位区间大小
                "enum_total": int,      # 理论总步数（候选数 × high_span）
                "enum_done": int,       # 实际枚举步数（取消时 < enum_total）
                "hits": int,            # 命中种子数
                "elapsed": float,       # 耗时（秒）
                "engine": str,          # "native" 或 "python"
            },
            "cancelled": bool,
        }
    """
    if not candidates:
        raise ValueError("没有候选种子：请先运行结构逆推生成候选")
    if not biome_obs or len(biome_obs) < MIN_OBS:
        raise ValueError(
            f"群系观测点不足：需要 ≥{MIN_OBS} 个（当前 {len(biome_obs) if biome_obs else 0} 个）"
        )

    # 候选归一化：只保留低 48 位（结构种语义）
    mask48 = (1 << 48) - 1
    cands = []
    for c in candidates:
        c = int(c) & mask48
        if c not in cands:
            cands.append(c)
    if not cands:
        raise ValueError("候选种子经 48 位掩码后为空")

    # 观测点预处理：方块坐标 → 噪声坐标（x/z >>2；y 可选，方块 Y >>2，
    # 缺省 0 即深层噪声层。带 y 与游戏 F3 群系判定一致，可区分洞穴/地表）
    obs_list = []
    for o in biome_obs:
        nx = block_to_noise(int(o["x"]))
        nz = block_to_noise(int(o["z"]))
        ny = int(o["y"]) >> 2 if o.get("y") is not None else 0
        bid = int(o["biome_id"])
        obs_list.append((nx, ny, nz, bid))

    high_span = 1 << 16 if high_limit is None else min(1 << 16, int(high_limit))
    enum_total = len(cands) * high_span

    # get_btree 先做版本校验（不支持的版本抛友好 ValueError）
    get_btree(version_key)
    btree_name = VERSION_TO_BTREE[version_key]

    # ---- native 路径（C++ 多线程），失败自动降级纯 Python ----
    if _native_ext is not None:
        try:
            last_prog = {"done": 0}

            def _prog(done, total, msg):
                last_prog["done"] = done
                if on_progress is not None:
                    on_progress(done, total, msg)

            t0 = time.perf_counter()
            found = _refine_native(cands, obs_list, btree_name,
                                   _prog, cancel, high_span)
            elapsed = time.perf_counter() - t0
            # C++ 端取消标志不回传：复查 cancel 状态（取消后标志保持 True）
            was_cancelled = bool(_check_cancel(cancel))
            return {
                "world_seeds": found,
                "stages": {
                    "candidates": len(cands),
                    "high_span": high_span,
                    "enum_total": enum_total,
                    "enum_done": last_prog["done"] if was_cancelled else enum_total,
                    "hits": len(found),
                    "elapsed": elapsed,
                    "engine": "native",
                },
                "cancelled": was_cancelled,
            }
        except Exception as e:
            # native 失败（未知 btree/数据异常等）→ 降级纯 Python；
            # 原先静默吞掉会让"极慢"无从排查，此处留一行诊断
            print(f"[refine] native 路径失败，降级纯 Python：{e!r}",
                  file=sys.stderr)

    # 开始回调
    if on_progress is not None:
        try:
            on_progress(0, enum_total, "开始枚举高位 16 bit")
        except Exception:
            pass

    t0 = time.perf_counter()
    found: list[int] = []
    enum_done = 0
    cancelled = False

    for s48 in cands:
        # 候选间取消检查（观测点验证整段可放弃）
        if _check_cancel(cancel):
            cancelled = True
            break

        for high in range(high_span):
            seed = (high << 48) | s48
            if seed & _S63_SIGN:
                seed -= 1 << 64   # 无符号位模式 → 有符号 int64（同 native）
            sampler = BiomeSampler(seed, version_key)
            if all(sampler.biome_at(nx, ny, nz) == bid
                   for nx, ny, nz, bid in obs_list):
                found.append(seed)
            enum_done += 1
            if (high & _PROGRESS_MASK) == _PROGRESS_MASK:
                if on_progress is not None:
                    try:
                        on_progress(enum_done, enum_total, None)
                    except Exception:
                        pass
                if _check_cancel(cancel):
                    cancelled = True
                    break

        if cancelled:
            break
        if on_progress is not None:
            try:
                on_progress(enum_done, enum_total, f"候选 {s48} 完成")
            except Exception:
                pass

    elapsed = time.perf_counter() - t0
    return {
        "world_seeds": found,
        "stages": {
            "candidates": len(cands),
            "high_span": high_span,
            "enum_total": enum_total,
            "enum_done": enum_done,
            "hits": len(found),
            "elapsed": elapsed,
            "engine": "python",
        },
        "cancelled": cancelled,
    }
