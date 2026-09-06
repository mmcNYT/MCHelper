# -*- coding: utf-8 -*-
"""StrongHoldFinder 工具：两次 F3+C 观测，三角定位要塞。

使用流程（末影之眼三角定位法）：
1. 抛出末影之眼，把准星对准它飞走的方向，按 F3+C 复制命令，粘贴进「坐标一」；
2. 走到远处（建议与第一次观测相距 200 格以上）重复上述操作，粘贴进「坐标二」；
3. 点击「计算」：两条视线在水平面上的交点即要塞位置，结果显示在下方信息框。
"""

from .tool_base import BaseToolWidget
from CodesUI.StrongHoldFinder import Ui_strongHoldFinder
from Utils.StrongHoldFinder.stronghold_math import (
    intersect_rays,
    normalize_yaw,
    parse_f3c_command,
    yaw_to_compass,
)


class StrongHoldFinderWidget(BaseToolWidget, Ui_strongHoldFinder):
    preferred_size = (634, 518)  # UI 设计尺寸，主窗口切到本 tab 时自适应

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        # 打开工具时先给出使用说明
        self.informationBrowser.setPlainText(
            "使用方法：\n"
            "1. 抛出末影之眼，把准星对准它飞走的方向，按 F3+C，"
            "把复制的内容粘贴进「坐标一」；\n"
            "2. 走到远处（建议与第一次观测相距 200 格以上）再对准一次，"
            "粘贴进「坐标二」；\n"
            "3. 点击「计算」，两条视线的交点就是要塞的水平位置。"
        )
        # 按钮 → 槽
        self.doCaculate.clicked.connect(self._on_do_caculate_clicked)
        self.clearCoordinates.clicked.connect(self._on_clear_coordinates_clicked)

    # ---------- 实现基类接口 ----------
    @classmethod
    def tool_name(cls) -> str:
        return "StrongHoldFinder"

    # ---------- 槽函数 ----------
    def _on_clear_coordinates_clicked(self) -> None:
        """清除：清空两个输入框与结果信息框。"""
        self.coordinate1Edit.clear()
        self.coordinate2Edit.clear()
        self.informationBrowser.clear()

    def _on_do_caculate_clicked(self) -> None:
        """计算：解析两条 F3+C 命令 → 求两视线交点 → 结果输出到信息框。"""
        text1 = self.coordinate1Edit.text().strip()
        text2 = self.coordinate2Edit.text().strip()
        if not text1 or not text2:
            self.informationBrowser.setPlainText(
                "两个输入框都需要先粘贴按 F3+C 复制的内容，才能进行计算。\n"
                "操作：对准末影之眼飞走的方向按 F3+C → 粘贴 → 走远一点再观测一次。"
            )
            return
        try:
            x1, z1, yaw1 = parse_f3c_command(text1)
            x2, z2, yaw2 = parse_f3c_command(text2)
            result = intersect_rays(x1, z1, yaw1, x2, z2, yaw2)
        except ValueError as exc:
            self.informationBrowser.setPlainText(f"计算失败：{exc}")
            return
        self.informationBrowser.setPlainText(
            self._format_result(result, x1, z1, yaw1, x2, z2, yaw2)
        )

    # ---------- 内部辅助 ----------
    @staticmethod
    def _format_result(
        result: dict,
        x1: float, z1: float, yaw1: float,
        x2: float, z2: float, yaw2: float,
    ) -> str:
        """把交点结果整理成展示文本，附带可信度警示与使用提示。"""
        lines = [
            "———— 要塞定位结果 ————",
            "",
            f"观测一：X = {x1:.1f}，Z = {z1:.1f}，"
            f"视线朝向 {yaw_to_compass(yaw1)}（yaw = {normalize_yaw(yaw1):.1f}°）",
            f"观测二：X = {x2:.1f}，Z = {z2:.1f}，"
            f"视线朝向 {yaw_to_compass(yaw2)}（yaw = {normalize_yaw(yaw2):.1f}°）",
            "",
            f"交点（要塞水平位置）：X = {result['x']:.1f}，Z = {result['z']:.1f}",
            f"距观测一：约 {result['dist1']:.1f} 格",
            f"距观测二：约 {result['dist2']:.1f} 格",
        ]
        warnings = []
        if result["t1"] < 0:
            warnings.append("交点位于观测一的视线反方向，当时准星可能没有对准末影之眼，建议重新观测")
        if result["t2"] < 0:
            warnings.append("交点位于观测二的视线反方向，当时准星可能没有对准末影之眼，建议重新观测")
        if warnings:
            lines.append("")
            lines.extend(f"注意：{w}" for w in warnings)
        lines += [
            "",
            "提示：末影之眼在距要塞约 20 格内会悬停下坠，近距离观测误差大；",
            "两次观测点相距越远、瞄准越准，交点越可靠。",
        ]
        return "\n".join(lines)
