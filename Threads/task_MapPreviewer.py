# -*- coding: utf-8 -*-
"""MapPreviewer 后台渲染线程（地图采样 + 结构枚举）。

职责：
    把 MapPreviewer 的两阶段计算放进工作线程：
        1. 地形采样：Utils/MapPreviewer/map_sampler.sample_region
           （native 优先，纯 Python 兜底；按行回调进度，行级取消）；
        2. 结构枚举：Utils/MapPreviewer/structure_map.enumerate_structures
           （13 种结构逐区域正向定位 + 群系校验，结构粒度回调进度）。

    工作线程不做任何 UI 操作，只通过信号把进度/结果/错误回主线程：
        progress(qlonglong, qlonglong, str)  统一进度 (done, total, 消息)
            —— 总量 = 采样行数 + 结构种数，两阶段合并成一条进度条。
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

from PySide6.QtCore import QThread, Signal

from Utils.MapPreviewer.map_sampler import sample_region
from Utils.MapPreviewer.structure_map import enumerate_structures

# 取消结束时的 render_finished 摘要标记（区别于正常统计摘要）
CANCELLED_SUMMARY = "__cancelled__"

# 进度信号节流间隔（秒）
_PROGRESS_INTERVAL_S = 0.1


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
                 struct_keys=None, parent=None):
        super().__init__(parent)
        self._seed = seed
        self._version_key = version_key
        self._radius = int(radius_blocks)
        self._struct_keys = list(struct_keys) if struct_keys else []
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
            want_depth=True,   # 山体阴影用（不增加采样成本）
        )
        t_sample = time.perf_counter() - t0
        if self._cancelled or map_res.get("cancelled"):
            self.render_finished.emit({}, CANCELLED_SUMMARY)
            return

        # ---- 阶段 2：结构枚举（结构粒度进度，区域间/结构间取消）----
        t1 = time.perf_counter()
        rows_total = int(map_res.get("rows_done") or 0)
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
        result["t_struct"] = t_struct

        summary = (f"完成：引擎 {result.get('engine', '?')}"
                   f"｜采样 {t_sample:.2f}s｜结构 {t_struct:.2f}s"
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
