# -*- coding: utf-8 -*-
"""SeedReverser 的后台逆推计算线程。

职责：
    把 48 位结构种的三层漏斗求解（Utils/SeedReverser/structure_math.
    solve_structure_seeds）放进工作线程执行——单次求解约 10 秒级，
    若在主线程直接计算会冻结整个界面。

    工作线程不做任何 UI 操作，只通过信号把进度/结果/错误回主线程：
        progress(qlonglong, qlonglong, str)  当前层进度 (done, total, 层名)
        calc_finished(list, str)  计算完成（候选列表 + 统计摘要）
            —— 刻意不叫 finished：QThread 自带 finished 信号（Qt 内部
               用它管理线程对象生命周期），自定义同名信号会遮蔽它，
               导致 wait()/退出清理等路径行为异常。
        error(str)                求解异常（观测不足 / 输入矛盾等）

    另有 SeedReverserVerifyThread：计算完成后自动批量正向验证全部候选
    （与手动「验证候选种子」同一验证语义），通过者回 UI 展示。

取消：
    求解器通过 cancel 回调轮询取消标志；主线程调用 request_cancel()
    置位后，求解器会在层间边界尽快退出并发出 calc_finished([], CANCELLED_SUMMARY)。

容差与重试：
    tol > 0 时把 tol 透传求解器；若全量观测求解无候选（常见于单条
    观测坐标抄错），自动逐条剔除后重试（最多 _MAX_RETRY_SHOTS 次）：
    剔除某条后有候选 → 候选列表附剔除提示文本一并发出。
    求解器抛 ValueError（观测不足/计算量超限）仍走 error 信号。

进度节流：
    层 3 是逐候选回调（候选可达数十万级），信号太密会淹没主线程事件
    循环；这里按时间间隔节流（每层最后一步强制发一次保证收尾）。
"""

import time

from PySide6.QtCore import QThread, Signal

from Utils.SeedReverser.structure_math import (
    solve_structure_seeds,
    verify_candidate_seed,
)

# 取消结束时的 calc_finished 摘要标记（区别于正常统计摘要）
CANCELLED_SUMMARY = "__cancelled__"

# 进度信号节流间隔（秒）
_PROGRESS_INTERVAL_S = 0.1

# 空结果后自动剔除单条观测重试的次数上限（每次重试另起一次三层漏斗，
# 上限过高会拖慢失败反馈；正常情况下前几次重试即能定位坏条目）
_MAX_RETRY_SHOTS = 8


class SeedReverserCalcThread(QThread):
    """后台逆推 48 位结构种的计算线程。

    用法：
        thread = SeedReverserCalcThread(observations, "1.21", parent=widget)
        thread.progress.connect(...)
        thread.calc_finished.connect(...)
        thread.error.connect(...)
        thread.start()
        # 需要取消时：thread.request_cancel()
    """

    # 进度总量在层 2 可达 幸存低位数 × 高位块数 ≈ 十亿级，
    # 超出 Qt int（32 位有符号，上限 2,147,483,647）会 OverflowError
    # 且数值回绕成负数 → 必须声明 64 位（qlonglong）。
    # 槽参数带 Python 类型注解即可透明接收 64 位整数，无需改动。
    progress = Signal("qlonglong", "qlonglong", str)   # done, total, stage（层名）
    calc_finished = Signal(list, str)  # candidates（48 位结构种列表）, summary
    error = Signal(str)                # 错误消息

    def __init__(self, observations, version_key, parent=None, tol: int = 0):
        super().__init__(parent)
        self._observations = list(observations)
        self._version_key = version_key
        # 缺省容差：仅对无 "tol" 键的观测生效（obs 自带 "tol" 优先，
        # UI 路径的 entries 逐条携带 tol，本参数保留作兑底/兼容）
        self._tol = int(tol)
        self._cancelled = False
        self._last_emit = 0.0  # 上次 progress 发出时刻（仅工作线程内访问）

    def request_cancel(self):
        """请求取消计算（主线程调用；仅置布尔标志，线程安全）。"""
        self._cancelled = True

    def run(self):
        """求解主流程：三层漏斗 → 候选列表（或取消 / 错误信号）。

        首轮全量观测；若无候选且非取消，自动逐条剔除重试（容错单条
        坐标抄错），命中后在 summary 前附剔除提示。
        """
        started = time.perf_counter()
        self._last_emit = 0.0
        try:
            result = solve_structure_seeds(
                self._observations,
                self._version_key,
                on_progress=self._on_progress,
                cancel=lambda: self._cancelled,
                tol=self._tol,
            )
        except ValueError as exc:
            # 观测不足 / 可 lifting 结构不足 / 容差计算量超限等预期错误
            self.error.emit(str(exc))
            return
        except Exception as exc:  # 兑底：任何异常都不能无声吞掉
            self.error.emit(f"计算线程异常：{exc!r}")
            return

        if self._cancelled:
            self.calc_finished.emit([], CANCELLED_SUMMARY)
            return

        # 空结果 → 逐条剔除重试（容错单条观测错误；容差与精确模式都适用）
        retry_note = ""
        if not result.get("candidates") and not self._cancelled:
            result, retry_note = self._retry_without_single_obs()
            if result is None:
                return  # 已发出取消或错误信号

        elapsed = time.perf_counter() - started
        summary = self._format_summary(result.get("stages", {}), elapsed)
        if retry_note:
            summary = retry_note + "\n" + summary
        self.calc_finished.emit(list(result.get("candidates", [])), summary)

    def _retry_without_single_obs(self):
        """逐条剔除观测重试（最多 _MAX_RETRY_SHOTS 次）。

        Returns:
            (result, note)：result 为最后一次求解结果 dict（candidates
            非空即命中）；note 为命中时的剔除提示（未命中为空串）。
            取消/出错时 result 为 None（信号已发出）；ValueError
            （如剔除后观测不足）静默跳过该次重试继续下一条。
        """
        n_obs = len(self._observations)
        for skip in range(min(n_obs, _MAX_RETRY_SHOTS)):
            if self._cancelled:
                self.calc_finished.emit([], CANCELLED_SUMMARY)
                return None, ""
            subset = [o for i, o in enumerate(self._observations) if i != skip]
            try:
                result = solve_structure_seeds(
                    subset,
                    self._version_key,
                    on_progress=self._on_progress,
                    cancel=lambda: self._cancelled,
                    tol=self._tol,
                )
            except ValueError:
                continue  # 剔除后观测不足等：换下一条
            except Exception as exc:
                self.error.emit(f"计算线程异常：{exc!r}")
                return None, ""
            if result.get("candidates"):
                # 命中：告知用户剔除了哪条（UI 端序号 = skip+1）
                note = (f"⚠ 提示：剔除第 {skip + 1} 条观测后才有候选，"
                        "该条坐标很可能抄错，请核对后重采。")
                return result, note
        return {"candidates": [], "stages": {}, "cancelled": False}, ""

    # ---------- 内部 ----------

    def _on_progress(self, done, total, stage):
        """求解器进度回调（工作线程）：节流后转发为 progress 信号。"""
        now = time.monotonic()
        if done >= total or (now - self._last_emit) >= _PROGRESS_INTERVAL_S:
            self._last_emit = now
            self.progress.emit(int(done), int(total), str(stage))

    @staticmethod
    def _format_summary(stages, elapsed) -> str:
        """把求解统计整理成多行摘要文本（结果区展示用）。"""
        if not stages:
            return "耗时: --"
        return (
            f"低位枚举位宽: {stages.get('low_bits', '?')} 位\n"
            f"层 1 幸存低位: {stages.get('layer1', 0):,}\n"
            f"层 2 幸存候选: {stages.get('layer2', 0):,}\n"
            f"层 3 精确验证: {stages.get('layer3', 0):,}\n"
            f"耗时: {elapsed:.1f}s"
        )


class SeedReverserVerifyThread(QThread):
    """批量正向验证候选结构种的后台线程。

    对 _last_candidates 全部候选逐个正向复算全部观测（与手动「验证候选
    种子」语义完全一致，含哨塔概率判定），通过者收集进结果列表：
        progress(qlonglong, qlonglong, str)  进度 (已验证个数, 总数, 阶段名)
        calc_finished(list, str)  验证完成（通过候选列表 + 文本摘要；
                                  取消时列表为空且摘要为 CANCELLED_SUMMARY）
        error(str)                异常

    语义说明：候选本就是求解器层 3 严格筛过的种子；此线程是对「同一
    验证逻辑」的批量复算，正常情况下全部通过（用于展示逐条比对明细与
    兜底确认），并不做额外更强的过滤。

    进度节流：候选可达数十万~百万级，逐个发信号会淹没主线程事件循环，
    与 SeedReverserCalcThread 相同按时间间隔节流（收尾强制发一次）。
    """

    progress = Signal("qlonglong", "qlonglong", str)
    calc_finished = Signal(list, str)
    error = Signal(str)

    def __init__(self, candidates, observations, version_key, parent=None):
        super().__init__(parent)
        self._candidates = list(candidates)
        self._observations = list(observations)
        self._version_key = version_key
        self._cancelled = False
        self._last_emit = 0.0  # 上次 progress 发出时刻（仅工作线程内访问）

    def request_cancel(self):
        """请求取消（主线程调用；仅置布尔标志，线程安全）。"""
        self._cancelled = True

    def run(self):
        """逐候选正向验证：通过者收集，全程无 UI 操作。"""
        total = len(self._candidates)
        passed = []
        self._last_emit = 0.0
        try:
            for idx, seed in enumerate(self._candidates):
                if self._cancelled:
                    self.calc_finished.emit([], CANCELLED_SUMMARY)
                    return
                ok, _ = verify_candidate_seed(
                    seed, self._observations, self._version_key)
                if ok:
                    passed.append(seed)
                now = time.monotonic()
                if (idx + 1 == total
                        or (now - self._last_emit) >= _PROGRESS_INTERVAL_S):
                    self._last_emit = now
                    self.progress.emit(idx + 1, total, "验证")
        except Exception as exc:  # 兜底：任何异常都不能无声吞掉
            self.error.emit(f"验证线程异常：{exc!r}")
            return
        elapsed_note = (f"共验证 {total} 个候选，"
                        f"通过 {len(passed)} 个")
        self.calc_finished.emit(passed, elapsed_note)
