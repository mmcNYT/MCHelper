# -*- coding: utf-8 -*-
"""MapPreviewer 后台渲染线程（地图采样 + 结构枚举 + 瓦片增量渲染）。

职责：
    把 MapPreviewer 的计算放进工作线程：
        1. 地形采样：Utils/MapPreviewer/map_sampler.sample_region
           （native 优先，纯 Python 兜底；按行回调进度，行级取消）；
        2. 地图渲染：Utils/MapPreviewer/block_colors
           - MapPreviewerThread：整幅渲染，lod="block"（1 方块 =
             1 像素精细档）或 "cell"（4x4 方块合 1 像素快速档）；
           - TileRenderThread：视口驱动的瓦片批量增量渲染（拖动/
             缩放时只渲染新进入视口的区域，LOD 与主图一致）；
        3. 结构枚举：Utils/MapPreviewer/structure_map.enumerate_structures
           （13 种结构逐区域正向定位 + 群系校验，结构粒度回调进度）。

    工作线程不做任何 UI 操作，只通过信号把进度/结果/错误回主线程：
        progress(qlonglong, qlonglong, str)  统一进度 (done, total, 消息)
        render_finished(object, str)         完整结果 dict + 统计摘要
            —— 刻意不叫 finished：QThread 自带 finished 信号（Qt 内部
               用它管理线程对象生命周期），自定义同名信号会遮蔽它。
            —— 用 object 而非 dict：载荷含 numpy 数组与无符号位模式
               种子，QVariantMap 转换可能触发 shiboken 溢出钳制。
        error(str)                           错误消息

取消：
    主线程调用 request_cancel() 置位后：采样按行尽快返回（丢弃部分
    结果），结构枚举在结构间/区域间尽快退出，最终发出
    render_finished({}, CANCELLED_SUMMARY)。

进度节流：
    native 采样引擎自身按 30ms 批量回调；纯 Python 路径按行回调。
    这里统一再加 0.1s 时间节流，最后一步强制发出保证收尾。
"""

import time

import numpy as np
from PySide6.QtCore import QThread, Signal

from Utils.MapPreviewer.map_sampler import sample_region
from Utils.MapPreviewer.block_colors import (render_block_rgb,
                                             render_cell_rgb)
from Utils.MapPreviewer.structure_map import enumerate_structures

# 取消结束时的 render_finished 摘要标记（区别于正常统计摘要）
CANCELLED_SUMMARY = "__cancelled__"

# 进度信号节流间隔（秒）
_PROGRESS_INTERVAL_S = 0.1

# 瓦片边长（方块）：与结构枚举/进度条单位无耦合，仅控制增量粒度
_TILE_BLOCKS = 1024


class MapPreviewerThread(QThread):
    """后台渲染地图 + 枚举结构的计算线程。

    用法：
        thread = MapPreviewerThread(seed, "1.21", 1024, keys, parent=widget)
        thread.progress.connect(...)
        thread.render_finished.connect(...)
        thread.error.connect(...)
        thread.start()
        # 需要取消时：thread.request_cancel()
    """

    progress = Signal("qlonglong", "qlonglong", str)   # done, total, msg
    render_finished = Signal(object, str)              # 结果 dict, summary
    error = Signal(str)                                # 错误消息

    def __init__(self, seed: int, version_key: str, radius_blocks: int,
                 struct_keys=None, parent=None, lod: str = "block"):
        super().__init__(parent)
        self._seed = seed
        self._version_key = version_key
        self._radius = int(radius_blocks)
        self._struct_keys = list(struct_keys) if struct_keys else []
        self._lod = lod if lod in ("block", "cell") else "block"
        self._cancelled = False
        self._last_emit = 0.0   # 上次 progress 发出时刻（仅工作线程访问）

    def request_cancel(self):
        """请求取消计算（主线程调用；仅置布尔标志，线程安全）。"""
        self._cancelled = True

    def run(self):
        """两阶段主流程：地图采样 → 结构枚举 → 结果 dict。"""
        try:
            self._run_impl()
        except Exception as exc:  # 兜底：任何异常都不能无声吞掉
            self.error.emit(f"渲染线程异常：{exc!r}")

    def _run_impl(self):
        started = time.perf_counter()
        self._last_emit = 0.0

        # ---- 阶段 1：地形采样（native 优先，行级取消）----
        t0 = time.perf_counter()
        size = self._radius * 2
        map_res = sample_region(
            self._seed, self._version_key,
            0, 0, size, size,
            on_progress=self._on_sample_progress,
            cancel=lambda: self._cancelled,
            want_depth=True,        # 水深渐变/恶地色带用（零采样成本）
            want_temp_humid=True,   # 草色 tint 用（零采样成本）
        )
        t_sample = time.perf_counter() - t0
        if self._cancelled or map_res.get("cancelled"):
            self.render_finished.emit({}, CANCELLED_SUMMARY)
            return

        # ---- 阶段 1.5：地图渲染（lod="block" 1方块=1像素精细档 /
        # lod="cell" 4x4方块合1像素快速档，色彩基调一致）----
        t_render0 = time.perf_counter()
        nh = map_res["biomes"].shape[0]
        rows_total = int(map_res.get("rows_done") or nh)

        def on_render(done, total):
            # 渲染进度折算进采样进度段（上限不越界）
            self._emit_progress(min(rows_total,
                                    rows_total * int(done) // max(total, 1)),
                                rows_total, "渲染")

        render_kwargs = dict(
            seed=self._seed,
            origin_bx=int(map_res["origin_bx"]),
            origin_bz=int(map_res["origin_bz"]),
        )
        if self._lod == "cell":
            block_rgb = render_cell_rgb(
                map_res["biomes"], map_res.get("temp"), map_res.get("humid"),
                map_res.get("depth"))
        else:
            block_rgb = render_block_rgb(
                map_res["biomes"], map_res.get("temp"), map_res.get("humid"),
                map_res.get("depth"),
                on_progress=on_render, **render_kwargs)
        t_render = time.perf_counter() - t_render0
        map_res["rgb"] = block_rgb
        map_res["lod"] = self._lod

        # ---- 阶段 2：结构枚举（结构粒度进度，区域间/结构间取消）----
        t1 = time.perf_counter()
        n_structs = len(self._struct_keys)
        done_base = rows_total

        def on_struct(done, total, key):
            # 结构粒度回调 → 统一进度（总量 = 采样行数 + 结构数）
            self._emit_progress(done_base + int(done),
                                rows_total + max(total, 1),
                                f"结构 {key}")

        structs = enumerate_structures(
            self._seed, self._version_key,
            (-self._radius, -self._radius, self._radius, self._radius),
            self._struct_keys or None,
            on_progress=on_struct,
            cancel=lambda: self._cancelled,
        )
        t_struct = time.perf_counter() - t1
        if self._cancelled:
            self.render_finished.emit({}, CANCELLED_SUMMARY)
            return

        result = dict(map_res)
        result["structures"] = structs
        result["radius"] = self._radius
        result["seed"] = self._seed
        result["version"] = self._version_key
        result["t_sample"] = t_sample
        result["t_render"] = t_render
        result["t_struct"] = t_struct

        summary = (f"完成：引擎 {result.get('engine', '?')}"
                   f"｜采样 {t_sample:.2f}s｜渲染 {t_render:.2f}s"
                   f"｜结构 {t_struct:.2f}s"
                   f"｜标记 {len(structs)} 个")
        self.render_finished.emit(result, summary)

    # ---------- 内部 ----------

    def _on_sample_progress(self, done, total, msg):
        """采样进度回调（工作线程）：时间节流后转发为 progress 信号。"""
        self._emit_progress(int(done), int(total), str(msg))

    def _emit_progress(self, done, total, msg):
        now = time.monotonic()
        if done >= total or (now - self._last_emit) >= _PROGRESS_INTERVAL_S:
            self._last_emit = now
            self.progress.emit(done, total, msg)


class TileRenderThread(QThread):
    """视口驱动的瓦片批量增量渲染线程（拖动/缩放后补渲染新区域）。

    主线程把缺失瓦片的列表整批提交；本线程逐瓦片「采样 → 渲染 →
    发 tile_done(载荷)」，每完成一块立即发信号回主线程上屏（不等
    整批）。瓦片请求在渲染期间可能失效（用户又拖走了），主线程在
    tile_done 里自行丢弃不需要的瓦片即可，本线程不回溯。

    信号：
        tile_done(object)   单瓦片载荷 dict：{tx, tz, rgb, origin_bx,
                            origin_bz, engine}（tx/tz 为瓦片格坐标）
        batch_done(str)     整批完成（空串占位，便于统一 onFinished）
        error(str)
    """

    tile_done = Signal(object)
    batch_done = Signal()
    error = Signal(str)

    def __init__(self, seed: int, version_key: str, tiles: list,
                 parent=None, lod: str = "block"):
        super().__init__(parent)
        self._seed = seed
        self._version_key = version_key
        self._tiles = list(tiles)      # [(tx, tz), ...] 瓦片格坐标
        self._lod = lod if lod in ("block", "cell") else "block"
        self._cancelled = False

    def request_cancel(self):
        """请求放弃剩余瓦片（新一批提交前由主线程调用）。"""
        self._cancelled = True

    def run(self):
        try:
            self._run_impl()
        except Exception as exc:  # 兜底：任何异常都不能无声吞掉
            self.error.emit(f"瓦片渲染线程异常：{exc!r}")

    def _run_impl(self):
        for tx, tz in self._tiles:
            if self._cancelled:
                break
            obx = tx * _TILE_BLOCKS
            obz = tz * _TILE_BLOCKS
            res = sample_region(
                self._seed, self._version_key,
                obx + _TILE_BLOCKS // 2, obz + _TILE_BLOCKS // 2,
                _TILE_BLOCKS, _TILE_BLOCKS,
                want_depth=True, want_temp_humid=True,
                cancel=lambda: self._cancelled,
            )
            if self._cancelled or res.get("cancelled"):
                break
            if self._lod == "cell":
                rgb = render_cell_rgb(res["biomes"], res.get("temp"),
                                      res.get("humid"), res.get("depth"))
            else:
                rgb = render_block_rgb(
                    res["biomes"], res.get("temp"), res.get("humid"),
                    res.get("depth"), seed=self._seed,
                    origin_bx=int(res["origin_bx"]),
                    origin_bz=int(res["origin_bz"]))
            if self._cancelled:
                break
            self.tile_done.emit({
                "tx": tx, "tz": tz, "rgb": rgb,
                "origin_bx": int(res["origin_bx"]),
                "origin_bz": int(res["origin_bz"]),
                "engine": res.get("engine", "?"),
                "lod": self._lod,
            })
        if not self._cancelled:
            self.batch_done.emit()
