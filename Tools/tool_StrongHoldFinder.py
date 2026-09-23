# -*- coding: utf-8 -*-
"""StrongHoldFinder 工具：两次 F3+C 观测，三角定位要塞。

使用流程（末影之眼三角定位法）：
1. 抛出末影之眼，把准星对准它飞走的方向，按 F3+C；
2. 后台监听线程检测到剪贴板变化后，自动把内容填进第一个空坐标输入框
   （也可以手动粘贴或直接编辑输入框）；
3. 走到远处（建议与第一次观测相距 200 格以上）重复上述操作，填入另一框；
4. 两观测点相距 30 格以上时自动计算，并在屏幕右下角弹出要塞坐标通知；
   相距不足 30 格时信息框会提示，也可手动点击「计算」。

自动监测的激活条件：
- 仅当 StrongHoldFinder 是 tab 栏最上层页时才自动监测剪贴板；
  切到其它工具页时自动填入暂停（手动粘贴不受影响），切回后恢复；
- 主窗口最小化到系统托盘后自动监测继续生效（tab 仍停留在本页即可），
  支持挂后台等定位结果的用法。

自动填入防抖（仅作用于坐标一，手动粘贴不受影响）：
- 距上次自动填入不足 8 秒，或与上次自动填入位置相距不足 10 格（1 格 = 1 米）
  的新观测会被忽略——避免站在原地对末影之眼反复按 F3+C 时来回覆盖；
- 点「清除」会重置防抖状态；需要覆盖时可手动粘贴或清除后重新观测。

计算完成后：
- 结果同时给出主世界要塞坐标与下界交通坐标（主世界坐标 / 8）；
- 生成一条可粘贴到聊天栏的 /tp 传送命令并自动复制到剪贴板。
"""

import math
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QTabWidget

from .tool_base import BaseToolWidget
from CodesUI.StrongHoldFinder import Ui_strongHoldFinder
from Threads.task_StrongHoldFinder import ClipboardListenerThread
from Utils.Public.notification import NotificationWidget
from Utils.Public.stronghold_math import (
    intersect_rays,
    looks_like_f3c,
    normalize_yaw,
    parse_f3c_command,
    parse_f3c_command_full,
    yaw_to_compass,
)

# ----- 自动填入 / 自动计算策略参数（Minecraft 中 1 格 = 1 米） -----
_AUTO_FILL_COOLDOWN_S = 8.0     # 坐标一两次自动填入的最小间隔（秒）
_AUTO_FILL_MIN_DISTANCE = 10.0  # 坐标一自动填入与上次位置的最小距离（格）
_AUTO_CALC_MIN_DISTANCE = 30.0  # 两观测点相距达到该值（格）时自动计算
_RESULT_NOTIFY_DURATION_MS = 6000  # 自动计算通知的显示时长

# 通知外观：定位结果需要醒目，字体与内边距均大于默认值（窗口自适应变大）
_NOTIFY_TITLE_SIZE = 16
_NOTIFY_MESSAGE_SIZE = 14
_NOTIFY_PADDING = (20, 16, 20, 16)


class StrongHoldFinderWidget(BaseToolWidget, Ui_strongHoldFinder):
    preferred_size = (663, 373)  # UI 设计尺寸，主窗口切到本 tab 时自适应

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        # 防抖状态：上次自动填入坐标一的时刻与位置（None 表示尚无记录）
        self._last_auto_fill_time: float | None = None
        self._last_auto_fill_pos: tuple[float, float] | None = None
        # 最近一次计算的传送命令（用于结果展示）
        self._tp_command = ""
        # 打开工具时先给出使用说明
        self.informationBrowser.setPlainText(
            "使用方法：\n"
            "1. 抛出末影之眼，把准星对准它飞走的方向，按 F3+C；\n"
            "2. MCHelper 检测到剪贴板变化后会自动把内容填进坐标输入框（无需手动粘贴，\n"
            "   也可以手动粘贴或直接编辑输入框；8 秒内或与上次位置相距不足 10 格的\n"
            "   重复观测会被自动忽略）；\n"
            "   注意：自动监测仅在本页位于 tab 栏最上层时生效，切到其它\n"
            "   工具页会暂停、切回后恢复；窗口最小化到系统托盘后自动监测\n"
            "   继续生效（tab 仍停留在本页即可）；\n"
            "3. 走到远处再对准一次；两观测点相距 30 格以上时会自动计算，\n"
            "   并在屏幕右下角弹出要塞坐标通知（含下界交通坐标）；\n"
            "4. 计算完成后传送命令会自动复制到剪贴板，可直接粘贴到游戏聊天栏。"
        )
        # 按钮 → 槽
        self.doCaculate.clicked.connect(self._on_do_caculate_clicked)
        self.clearCoordinates.clicked.connect(self._on_clear_coordinates_clicked)

        # 剪贴板监听：后台线程只监测变化，读剪贴板与填入在主线程执行。
        # 监听线程常驻（轮询序号开销可忽略，停/启反而引入竞态）；
        # 「仅激活页才自动填入」的门控在 _on_clipboard_changed 入口做。
        self._clipboard_thread = ClipboardListenerThread(self)
        self._clipboard_thread.clipboard_changed.connect(self._on_clipboard_changed)
        self._clipboard_thread.start()

        # 退出兜底：Qt 只给顶层窗口发 closeEvent，不会传给作为子控件的工具页，
        # 托盘菜单「关闭程序」等路径也不会触发窗口 closeEvent；
        # 若监听线程在仍运行时被析构，程序会以 0xC0000409 崩溃退出。
        # 因此这里挂接应用级 aboutToQuit 信号，保证任何退出路径都会先停线程。
        QApplication.instance().aboutToQuit.connect(self._stop_clipboard_thread)

    def _stop_clipboard_thread(self) -> None:
        """停止剪贴板监听线程（应用退出前调用；重复调用无副作用）。"""
        if self._clipboard_thread is None:
            return
        self._clipboard_thread.requestInterruption()
        self._clipboard_thread.quit()
        self._clipboard_thread.wait(1000)

    def closeEvent(self, event) -> None:
        """窗口关闭时停止剪贴板监听线程（aboutToQuit 的双保险）。"""
        self._stop_clipboard_thread()
        super().closeEvent(event)

    # ---------- 实现基类接口 ----------
    @classmethod
    def tool_name(cls) -> str:
        return "StrongHoldFinder"

    # ---------- 槽函数 ----------
    def _is_active_tab_page(self) -> bool:
        """本页是否处于 tab 栏最上层（当前激活页）。

        仅用于门控自动监测：只有激活时才自动读剪贴板，切到其它工具页
        时自动填入暂停，切回后恢复。规则：
        - 本页不在任何 QTabWidget 内（独立使用/测试）：视为始终激活，
          门控不生效；
        - 在 tab 内：祖先 QTabWidget 的当前页是本页才算激活。
          故意不看窗口可见性——最小化到托盘（hide）不改变 tab 当前页，
          隐藏后自动监测继续生效，支持挂后台等定位结果的用法。
        """
        container = None
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QTabWidget):
                container = parent
                break
            parent = parent.parentWidget()
        if container is None:
            return True
        return container.currentWidget() is self

    def _on_clear_coordinates_clicked(self) -> None:
        """清除：清空输入框、信息框，并重置自动填入的防抖状态。"""
        self.coordinate1Edit.clear()
        self.coordinate2Edit.clear()
        self.informationBrowser.clear()
        self._last_auto_fill_time = None
        self._last_auto_fill_pos = None

    def _on_clipboard_changed(self) -> None:
        """剪贴板变化（主线程槽）：内容是 F3+C 时按规则自动填入。

        门控：仅当本页是 tab 栏最上层时才自动填入（托盘隐藏不改变
        tab 当前页，隐藏后仍继续生效）；非激活页收到信号直接忽略。
        """
        if not self._is_active_tab_page():
            return
        text = QApplication.clipboard().text()
        if not looks_like_f3c(text):
            return
        if text == self.coordinate1Edit.text() or text == self.coordinate2Edit.text():
            return
        if self.coordinate1Edit.text().strip() == "":
            self._auto_fill_first(text)
        elif self.coordinate2Edit.text().strip() == "":
            self._auto_fill_second(text)
        # 两框皆有内容时不自动覆盖，避免破坏用户已确认的观测数据

    def _auto_fill_first(self, text: str) -> None:
        """自动填入坐标一：带 8 秒冷却与 10 格距离防抖。

        首次填入（无历史记录）直接通过；否则与上次自动填入比较——
        间隔不足 8 秒或位置相距不足 10 格时忽略本次观测并提示。
        """
        try:
            x, z, _yaw = parse_f3c_command(text)
        except ValueError:
            return
        now = time.monotonic()
        if self._last_auto_fill_time is not None:
            too_soon = (now - self._last_auto_fill_time) < _AUTO_FILL_COOLDOWN_S
            too_close = (
                self._last_auto_fill_pos is not None
                and math.hypot(x - self._last_auto_fill_pos[0],
                               z - self._last_auto_fill_pos[1]) < _AUTO_FILL_MIN_DISTANCE
            )
            if too_soon or too_close:
                self.informationBrowser.setPlainText(
                    "已忽略一次自动填入：与上次观测的间隔不足 8 秒或位置相距不足 10 格。\n"
                    "如确认要使用该数据，可手动粘贴，或点「清除」后重新观测。"
                )
                return
        self.coordinate1Edit.setText(text)
        self._last_auto_fill_time = now
        self._last_auto_fill_pos = (x, z)
        if self.coordinate2Edit.text().strip() == "":
            self.informationBrowser.setPlainText(
                "已自动填入坐标一（检测到剪贴板中的 F3+C 内容）。"
                "下次剪贴板出现新的 F3+C 内容时会自动填入坐标二。"
            )

    def _auto_fill_second(self, text: str) -> None:
        """自动填入坐标二：两观测点相距 30 格以上时自动计算并弹通知。"""
        self.coordinate2Edit.setText(text)
        try:
            x1, z1, _yaw1 = parse_f3c_command(self.coordinate1Edit.text())
            x2, z2, _yaw2 = parse_f3c_command(text)
        except ValueError:
            self.informationBrowser.setPlainText(
                "已自动填入坐标二（检测到剪贴板中的 F3+C 内容），可以点击「计算」。"
            )
            return
        dist = math.hypot(x2 - x1, z2 - z1)
        if dist < _AUTO_CALC_MIN_DISTANCE:
            self.informationBrowser.setPlainText(
                f"已自动填入坐标二。两观测点相距约 {dist:.0f} 格（不足 30 格，"
                "建议走远些再观测一次以提高精度），也可直接点击「计算」。"
            )
            return
        result = self._compute_and_show()
        if result is None:
            return
        NotificationWidget.Show(
            "要塞定位完成",
            f"要塞位置：X = {result['x']:.1f}，Z = {result['z']:.1f}\n"
            f"下界交通：X = {result['x'] / 8:.1f}，Z = {result['z'] / 8:.1f}\n"
            "传送命令已复制到剪贴板",
            _RESULT_NOTIFY_DURATION_MS,
            title_size=_NOTIFY_TITLE_SIZE,
            message_size=_NOTIFY_MESSAGE_SIZE,
            padding=_NOTIFY_PADDING,
        )

    def _on_do_caculate_clicked(self) -> None:
        """计算按钮：解析两条 F3+C 命令 → 求两视线交点 → 结果输出到信息框。"""
        self._compute_and_show()

    def _compute_and_show(self) -> dict | None:
        """执行计算、把结果写入信息框，并把传送命令复制到剪贴板。

        复制内容为可粘贴到聊天栏的传送命令：
            ``/tp @s <要塞x> <y> <要塞z>``
        y 取两观测点 y 的较大值（游戏内实际 y 以到达时为准）。

        Returns:
            成功时返回交点结果 dict（x/z/t1/t2/dist1/dist2），失败返回 None。
        """
        text1 = self.coordinate1Edit.text().strip()
        text2 = self.coordinate2Edit.text().strip()
        if not text1 or not text2:
            self.informationBrowser.setPlainText(
                "两个输入框都需要先填入按 F3+C 复制的内容，才能进行计算。\n"
                "操作：对准末影之眼飞走的方向按 F3+C → 粘贴 → 走远一点再观测一次。"
            )
            return None
        try:
            x1, y1, z1, yaw1 = parse_f3c_command_full(text1)
            x2, y2, z2, yaw2 = parse_f3c_command_full(text2)
            result = intersect_rays(x1, z1, yaw1, x2, z2, yaw2)
        except ValueError as exc:
            self.informationBrowser.setPlainText(f"计算失败：{exc}")
            return None
        # 生成传送命令并复制到剪贴板（y 取两观测点较大值）
        self._tp_command = f"/tp @s {result['x']:.1f} {max(y1, y2):.1f} {result['z']:.1f}"
        QApplication.clipboard().setText(self._tp_command)
        self.informationBrowser.setPlainText(
            self._format_result(result, x1, y1, z1, yaw1, x2, y2, z2, yaw2,
                                self._tp_command)
        )
        return result

    # ---------- 内部辅助 ----------
    @staticmethod
    def _format_result(
        result: dict,
        x1: float, y1: float, z1: float, yaw1: float,
        x2: float, y2: float, z2: float, yaw2: float,
        tp_command: str = "",
    ) -> str:
        """把交点结果整理成展示文本，附带下界交通坐标与传送命令。"""
        lines = [
            "———— 要塞定位结果 ————",
            "",
            f"观测一：X = {x1:.1f}，Y = {y1:.1f}，Z = {z1:.1f}，"
            f"视线朝向 {yaw_to_compass(yaw1)}（yaw = {normalize_yaw(yaw1):.1f}°）",
            f"观测二：X = {x2:.1f}，Y = {y2:.1f}，Z = {z2:.1f}，"
            f"视线朝向 {yaw_to_compass(yaw2)}（yaw = {normalize_yaw(yaw2):.1f}°）",
            "",
            f"交点（要塞水平位置）：X = {result['x']:.1f}，Z = {result['z']:.1f}",
            f"下界交通（主世界坐标/8）：X = {result['x'] / 8:.1f}，Z = {result['z'] / 8:.1f}",
            "",
            f"传送命令（已复制到剪贴板）：{tp_command}",
            "",
        ]
        warnings = []
        if result["t1"] < 0:
            warnings.append("交点位于观测一的视线反方向，当时准星可能没有对准末影之眼，建议重新观测")
        if result["t2"] < 0:
            warnings.append("交点位于观测二的视线反方向，当时准星可能没有对准末影之眼，建议重新观测")
        if warnings:
            lines.extend(f"注意：{w}" for w in warnings)
            lines.append("")
        lines += [
            "提示：末影之眼在距要塞约 20 格内会悬停下坠，近距离观测误差大；",
            "两次观测点相距越远、瞄准越准，交点越可靠。",
        ]
        return "\n".join(lines)
