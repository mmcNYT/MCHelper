# -*- coding: utf-8 -*-
"""MapPreviewer 结构选择窗口：「选择结构」按钮弹出的图标网格对话框。

UI 为用户在 Qt Designer 定义的 ChooseStructureWin.ui（结构列表
structureList + 确认按钮 confirmBtn），本模块只做控制逻辑：

- 网格视图（IconMode）展示当前版本可标注的主世界结构，图标用
  Wiki EnvSprite 资产（structure_icons），中文名显示在图标下方
  （QListWidget IconMode 自带文字换行布局）；
- MultiSelection 模式：点击条目即在"选中/取消"间切换（高亮 =
  在地图上标注该结构），与勾选框语义一致且无双重切换歧义；
- 图标文件缺失时仍可正常选择（只少图标不挡功能）。

调用方（Tools/tool_MapPreviewer）以 exec() 弹出，确认后经
get_selected() 取回选中集并写回自己的选择状态。
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QListWidget,
                               QListWidgetItem)

from CodesUI.ChooseStructureWin import Ui_chooseStructureWin
from Utils.Public import structure_icons as st_icons
from Utils.Public.structure_params import (DIMENSION_NAMES,
                                                 STRUCT_DIMENSION,
                                                 STRUCT_NAMES)

# 网格图标显示尺寸（屏幕 px）：16x16 精灵就近放大，像素风与地图标记一致
_ICON_SIZE = 36

# 选中态高亮：浅色底 + 深字（用户要求白色背景），hover 用浅灰、
# 分组标题配中灰，浅底下均可读
_SELECT_QSS = """
QListWidget {
    background: #ffffff;
}
QListWidget::item:selected {
    background: #cfe4f7;
    color: #1a1a1a;
    border: 1px solid #4a90d9;
}
QListWidget::item:hover:!selected {
    background: #eef2f6;
}
"""


class ChooseStructureWindow(QDialog, Ui_chooseStructureWin):
    """结构选择对话框。

    Args:
        parent: 父窗口（MapPreviewerWidget）。
        avail_keys: 当前版本可标注的结构键序列（调用方已按版本过滤）。
        selected: 初始选中的结构键集合（可为 None = 全不选）。
    """

    def __init__(self, parent=None, avail_keys=(), selected=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowTitle("选择结构")

        lst = self.structureList
        lst.setViewMode(QListWidget.ViewMode.IconMode)
        lst.setResizeMode(QListWidget.ResizeMode.Adjust)
        lst.setMovement(QListWidget.Movement.Static)
        # MultiSelection：点击即切换该条目的选中态（不影响其他条目），
        # 选中高亮 = 在地图上标注；不用 ItemIsUserCheckable 勾选框
        # （点击勾选框会原生切换 + itemClicked 再切换，双重抵消）
        lst.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        lst.setUniformItemSizes(True)
        lst.setSpacing(10)
        lst.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        lst.setStyleSheet(_SELECT_QSS)

        sel = selected or set()
        _add_dimension_groups(lst, avail_keys, sel)

        self.confirmBtn.clicked.connect(self.accept)

    def get_selected(self) -> set:
        """确认后取回选中的结构键集合。"""
        return {it.data(Qt.ItemDataRole.UserRole)
                for it in self.structureList.selectedItems()}


def _add_dimension_groups(lst: QListWidget, avail_keys, selected: set) -> None:
    """按维度（主世界/下界/末地）分组填充结构列表。

    分组标题用禁用 QListWidgetItem（不可选、不可点），仅作视觉分段；
    各组内保持 avail_keys 传入顺序（图上易找程度排序）。
    """
    groups: dict[str, list] = {"overworld": [], "nether": [], "end": []}
    for key in avail_keys:
        groups.setdefault(STRUCT_DIMENSION.get(key, "overworld"),
                          []).append(key)

    for dim in ("overworld", "nether", "end"):
        keys = groups.get(dim)
        if not keys:
            continue
        if dim != "overworld":
            _add_group_header(lst, DIMENSION_NAMES[dim], len(keys))
        for key in keys:
            item = QListWidgetItem(STRUCT_NAMES.get(key, key))
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled
                          | Qt.ItemFlag.ItemIsSelectable)
            icon_file = st_icons.icon_path(key)
            if icon_file:
                pm = QPixmap(icon_file)
                if not pm.isNull():
                    pm = pm.scaled(
                        _ICON_SIZE, _ICON_SIZE,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation)
                    item.setIcon(QIcon(pm))
            item.setToolTip("点击选中/取消：选中后该结构将标注在地图上")
            lst.addItem(item)
            if key in selected:
                item.setSelected(True)


def _add_group_header(lst: QListWidget, title: str, count: int) -> None:
    """插入一条禁用的分组标题行（如「下界 · 2 种」，不可选中）。"""
    header = QListWidgetItem(f"{title} · {count} 种")
    header.setFlags(Qt.ItemFlag.ItemIsEnabled)  # 无 Selectable = 禁用
    header.setForeground(QColor("#5f6673"))
    f = QFont()
    f.setBold(True)
    header.setFont(f)
    header.setSizeHint(QSize(0, 26))
    header.setTextAlignment(Qt.AlignmentFlag.AlignHCenter
                            | Qt.AlignmentFlag.AlignVCenter)
    lst.addItem(header)
