# -*- coding: utf-8 -*-
"""可搜索下拉补全（所有可输入下拉统一接入）。

效果同 MapPreviewer 的群系定位下拉：
  - 获得焦点/输入任意字符 → **始终弹出完整候选列表**，
    并按输入子串**实时过滤**（中英文、任意位置匹配，大小写不敏感）；
  - 不同于 QComboBox 自带补全（仅**前缀**匹配、输入首字符后不再弹），
    UnfilteredPopup + QSortFilterProxyModel 对「中文（id）」这类
    带空格/括号的中英混合标签更可用；
  - 选中或按 Esc/回车后收起；清空输入回到全量列表。

用法（一行接入，30+ 处下拉共用）：
    from Utils.CommandGenerator.combo_complete import attach_search
    attach_search(combo)

约定：候选项从 combo 自身逐项读取（第 0 列文本），无需另维护模型；
combo 重建（clear + addItem）后自动跟随 —— 模型是 combo 的行编辑器
子对象，随 combo 存续，列表内容按需刷新（见 refresh）。
"""
from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox, QCompleter


def attach_search(combo: QComboBox,
                   role: int = Qt.ItemDataRole.DisplayRole) -> QCompleter:
    """给可编辑下拉挂「输入即过滤」的补全。

    - combo 必须已 setEditable(True)（未设则顺手设上）；
    - 候选 = combo 现有项的显示文本（**跳过空项与禁用项** —— 分组
      标题 setEnabled(False) 不可选，也不该进搜索候选）；
    - 返回 QCompleter（调用方可进一步定制，如 setFilterRole）。
    """
    if not combo.isEditable():
        combo.setEditable(True)

    model = QStandardItemModel(combo)
    proxy = QSortFilterProxyModel(combo)
    proxy.setSourceModel(model)
    proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    proxy.setFilterKeyColumn(0)

    completer = QCompleter(proxy, combo)
    completer.setCompletionMode(
        QCompleter.CompletionMode.UnfilteredPopupCompletion)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    # 暴露 proxy 供测试/定制（completionModel() 是 Qt 内部包装取不到
    # setFilterFixedString）
    completer.filter_proxy = proxy
    combo.setCompleter(completer)

    # 输入子串 → 实时过滤候选列表
    combo.lineEdit().textEdited.connect(proxy.setFilterFixedString)

    # 初始填充；后续 combo 内容变化时由 refresh() / 事件同步
    refresh(combo, model)
    # combo 增删项时自动重建候选（clear/addItem 都发 model rows* 信号）
    combo.model().rowsInserted.connect(
        lambda *_: refresh(combo, model, role))
    combo.model().rowsRemoved.connect(
        lambda *_: refresh(combo, model, role))
    return completer


def refresh(combo: QComboBox, model: QStandardItemModel,
            role: int = Qt.ItemDataRole.DisplayRole):
    """按 combo 当前项重建候选模型（跳过空项与禁用项）。

    同时携带图标（若有），让补全弹窗也显示图标。
    """
    model.clear()
    m = combo.model()
    for i in range(combo.count()):
        mi = m.item(i)
        if mi is not None and not mi.isEnabled():
            continue                     # 分组标题等禁用项不进候选
        txt = combo.itemText(i)
        if not txt:
            continue
        item = QStandardItem(txt)
        # 携带图标（combo 的 itemIcon）
        icon = combo.itemIcon(i)
        if icon and not icon.isNull():
            item.setIcon(icon)
        model.appendRow(item)