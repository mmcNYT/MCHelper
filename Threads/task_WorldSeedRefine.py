# -*- coding: utf-8 -*-
"""世界种子精化的后台计算线程（SeedReverser 二期·路线 A）。

职责：
    把高位 16 bit 枚举（Utils/SeedReverser/world_seed_refine.
    refine_world_seeds）放进工作线程执行。枚举总量为 候选数 × 2^16，
    native 引擎下完整 2^16 枚举约 0.2 秒、多候选时更长；若在主线程
    直接计算会冻结界面。

    工作线程不做任何 UI 操作，只通过信号把进度/结果/错误回主线程：
        progress(qlonglong, qlonglong, str)  进度 (done, total, 消息)
        refine_finished(object, str)         完整结果 dict + 统计摘要
            —— 刻意不叫 finished：QThread 自带 finished 信号（Qt 内部
               用它管理线程对象生命周期），自定义同名信号会遮蔽它，
               导致 wait()/退出清理等路径行为异常。
            —— 用 object 而非 dict：dict 会被 PySide6 转 QVariantMap，
               其中世界种子值可能超出 int64（未转换的无符号位模式）
               而触发 shiboken 溢出钳制；object 直接透传 Python 对象。
        error(str)                           错误（观测不足 / 输入矛盾等）

取消：
    主线程调用 request_cancel() 置位后，枚举器在候选间与高位步进间
    检查标志，尽快退出并发出 refine_finished({}, CANCELLED_SUMMARY)。

进度节流：
    native 引擎自身已按 4096 迭代批量回调，这里再加一层时间节流
    （每 0.1s 最多一条），最后一步强制发出保证收尾。
"""

import time

from PySide6.QtCore import QThread, Signal

from Utils.SeedReverser.world_seed_refine import refine_world_seeds

# 取消结束时的 refine_finished 摘要标记（区别于正常统计摘要）
CANCELLED_SUMMARY = "__cancelled__"

# 进度信号节流间隔（秒）
_PROGRESS_INTERVAL_S = 0.1


class WorldSeedRefineThread(QThread):
    """后台精化世界种子的计算线程。

    用法：
        thread = WorldSeedRefineThread(candidates, biome_obs, "1.21",
                                       parent=widget)
        thread.progress.connect(...)
        thread.refine_finished.connect(...)
        thread.error.connect(...)
        thread.start()
        # 需要取消时：thread.request_cancel()
    """

    # 枚举总量 = 候选数 × 2^16，多候选时超出 Qt int 上限，必须 64 位
    progress = Signal("qlonglong", "qlonglong", str)   # done, total, msg
    # object 而非 dict：避免 QVariantMap 转换把 ≥2^63 的种子钳制成 -1
    refine_finished = Signal(object, str)              # 结果 dict, summary
    error = Signal(str)                                # 错误消息

    def __init__(self, candidates, biome_obs, version_key, parent=None):
        super().__init__(parent)
        self._candidates = list(candidates)
        self._biome_obs = list(biome_obs)
        self._version_key = version_key
        self._cancelled = False
        self._last_emit = 0.0  # 上次 progress 发出时刻（仅工作线程内访问）

    def request_cancel(self):
        """请求取消计算（主线程调用；仅置布尔标志，线程安全）。"""
        self._cancelled = True

    def run(self):
        """精化主流程：高位枚举 → 结果 dict（或取消 / 错误信号）。"""
        started = time.perf_counter()
        self._last_emit = 0.0
        try:
            result = refine_world_seeds(
                self._candidates,
                self._biome_obs,
                self._version_key,
                on_progress=self._on_progress,
                cancel=lambda: self._cancelled,
            )
        except ValueError as exc:
            # 观测点不足 / 无候选等预期错误
            self.error.emit(str(exc))
            return
        except Exception as exc:  # 兜底：任何异常都不能无声吞掉
            self.error.emit(f"计算线程异常：{exc!r}")
            return

        if self._cancelled:
            self.refine_finished.emit({}, CANCELLED_SUMMARY)
            return

        elapsed = time.perf_counter() - started
        summary = self._format_summary(result.get("stages", {}),
                                       result.get("world_seeds", []),
                                       elapsed)
        self.refine_finished.emit(result, summary)

    # ---------- 内部 ----------

    def _on_progress(self, done, total, msg):
        """枚举器进度回调（工作线程）：时间节流后转发为 progress 信号。"""
        now = time.monotonic()
        if done >= total or (now - self._last_emit) >= _PROGRESS_INTERVAL_S:
            self._last_emit = now
            self.progress.emit(int(done), int(total), str(msg))

    @staticmethod
    def _format_summary(stages, world_seeds, elapsed) -> str:
        """把精化统计整理成多行摘要文本（结果区展示用）。"""
        parts = [
            f"候选数: {stages.get('candidates', 0):,}",
            f"高位区间: {stages.get('high_span', 0):,}",
            f"枚举总量: {stages.get('enum_total', 0):,}",
            f"实际枚举: {stages.get('enum_done', 0):,}",
            f"引擎: {stages.get('engine', '?')}",
            f"耗时: {elapsed:.2f}s",
        ]
        if world_seeds:
            parts.append(
                f"命中 {len(world_seeds)} 个世界种子:"
                + "".join(f"\n  {s}" for s in world_seeds)
            )
        else:
            parts.append("未命中任何世界种子（观测点有误或候选不含真值）")
        return "\n".join(parts)
