# -*- coding: utf-8 -*-
"""目标选择器构建器控件。

UI 设计（用户「只用动手指」）：
  - 顶部：选择器类型下拉（@p / @a / @e / @r / @s）+ 预设按钮
  - 中部：参数行列表（每行 = 参数下拉 + 值控件 + 删除按钮）
  - 底部：添加参数下拉 + 实时预览 + 复制按钮

参数值控件按类型分配：
  - entity → 实体下拉（215 个官方实体）
  - text → 自由输入
  - int → QSpinBox
  - float → QLineEdit + QDoubleValidator
  - enum → QComboBox
  - range → QLineEdit + 范围校验（如 "5..10"）
"""
from __future__ import annotations

import re

from PySide6.QtCore import QLocale, QRegularExpression, Qt, Signal  # noqa: E402
from PySide6.QtGui import (QDoubleValidator, QKeySequence, QRegularExpressionValidator,
                           QShortcut)
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog,
                               QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSizePolicy,
                               QSpinBox, QToolButton, QVBoxLayout,
                               QWidget)

from Utils.CommandGenerator import item_list as IL
from Utils.CommandGenerator import resource_lists as RL
from Utils.CommandGenerator.target_selector import (  # noqa: E402
    PRESETS, SELECTOR_ARGS, SELECTOR_TYPES, build_selector, parse_selector)


class _ParamRow(QWidget):
    """一行参数：参数下拉 + 值控件 + 删除按钮。"""

    changed = Signal()
    remove_requested = Signal(object)

    def __init__(self, key=None, value=None, parent=None):
        super().__init__(parent)
        self._key = key
        # 键左值右（两列网格：参数键列固定宽与顶部对齐，值列 stretch）
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)

        # 参数下拉（键）
        self.combo = QComboBox()
        self.combo.addItem("选择参数…", "")
        for k, label, kind, default, extra in SELECTOR_ARGS:
            self.combo.addItem(f"{k}（{label}）", k)
        if key:
            i = self.combo.findData(key)
            if i >= 0:
                self.combo.setCurrentIndex(i)
        self.combo.currentIndexChanged.connect(self._on_key_changed)

        # 值单元容器：_build_value 只替换其中的值控件
        # （网格没有 insertWidget，切换参数类型时清空重建容器内容）
        self._value_host = QWidget()
        self._value_lay = QHBoxLayout(self._value_host)
        self._value_lay.setContentsMargins(0, 0, 0, 0)
        self._value_lay.setSpacing(4)
        self.value = None
        self._build_value(value)

        # 删除按钮与值控件并排在值单元内
        rm = QToolButton()
        rm.setText("✕")
        rm.clicked.connect(lambda: self.remove_requested.emit(self))
        self._value_lay.addWidget(rm)

        grid.addWidget(self.combo, 0, 0)
        grid.addWidget(self._value_host, 0, 1)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        # 键下拉宽度与顶部「选择器/预设/添加参数」列对齐
        self.combo.setMinimumWidth(110)

    def _on_key_changed(self):
        self._key = self.combo.currentData()
        self._build_value(None)
        self.changed.emit()

    def _build_value(self, value):
        if self.value is not None:
            self.value.setParent(None)
            self.value = None
        if not self._key:
            return
        spec = next((s for s in SELECTOR_ARGS if s[0] == self._key), None)
        if not spec:
            return
        _, _, kind, default, extra = spec
        if kind == "entity":
            w = QComboBox()
            w.setEditable(True)
            w.setPlaceholderText("可选")
            for eid in RL.ENTITY_IDS:
                cn = RL.ENTITY_CN.get(eid, eid)
                w.addItem(f"{cn}（{eid}）" if cn != eid else eid, eid)
            if value:
                i = w.findData(value)
                w.setCurrentIndex(i if i >= 0 else 0)
            w.currentIndexChanged.connect(lambda *_: self.changed.emit())
            w.editTextChanged.connect(lambda *_: self.changed.emit())
            # 可搜索：215 个实体靠输入子串过滤
            from Utils.CommandGenerator.combo_complete import attach_search
            attach_search(w)
            self.value = w
        elif kind == "text":
            w = QLineEdit()
            w.setPlaceholderText("可选" + (f"（{extra.get('hint','')}）" if extra.get("hint") else ""))
            if value:
                w.setText(str(value))
            w.textChanged.connect(lambda *_: self.changed.emit())
            self.value = w
        elif kind == "int":
            w = QSpinBox()
            w.setRange(-2147483648, 2147483647)
            w.setSpecialValueText("可选")
            try:
                w.setValue(int(value)) if value is not None else w.setValue(0)
            except (TypeError, ValueError):
                w.setValue(0)
            w.valueChanged.connect(lambda *_: self.changed.emit())
            self.value = w
        elif kind == "float":
            w = QLineEdit()
            w.setPlaceholderText("可选" + (f"（{extra.get('hint','')}）" if extra.get("hint") else ""))
            v = QDoubleValidator(-1e308, 1e308, 12)
            v.setLocale(QLocale.c())
            w.setValidator(v)
            if value:
                w.setText(str(value))
            w.textChanged.connect(lambda *_: self.changed.emit())
            self.value = w
        elif kind == "enum":
            w = QComboBox()
            w.addItem("可选", "")
            for c in extra.get("choices", []):
                w.addItem(c, c)
            if value:
                i = w.findData(value)
                w.setCurrentIndex(i if i >= 0 else 0)
            w.currentIndexChanged.connect(lambda *_: self.changed.emit())
            self.value = w
        elif kind == "range":
            w = QLineEdit()
            w.setPlaceholderText("可选（如 5..10 / 5 / ..10 / 5..）")
            w.setValidator(QRegularExpressionValidator(
                QRegularExpression(r"(-?[0-9]+)?\.\.(-?[0-9]+)?|-?[0-9]+")))
            if value:
                w.setText(str(value))
            w.textChanged.connect(lambda *_: self.changed.emit())
            self.value = w
        if self.value is not None:
            # 插到删除按钮之前（删除按钮是该 HBox 的最后一项）
            self._value_lay.insertWidget(
                self._value_lay.count() - 1, self.value, 1)

    def key(self):
        return self._key

    def value_text(self):
        if not self._key or self.value is None:
            return ""
        if isinstance(self.value, QComboBox):
            data = self.value.currentData()
            # "可选" 项的 data 为 ""，应返回空字符串
            return data if data not in (None, "") else ""
        if isinstance(self.value, QLineEdit):
            return self.value.text().strip()
        if isinstance(self.value, QSpinBox):
            # specialValueText("可选") 对应 value = minimum()
            if self.value.value() == self.value.minimum():
                return ""
            return str(self.value.value())
        return ""


class TargetSelectorBuilder(QWidget):
    """目标选择器构建器。"""

    changed = Signal()

    def __init__(self, initial="", parent=None):
        super().__init__(parent)
        self._rows = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # 顶部（键左值右两列网格：选择器 / 预设 / 添加参数 三行对齐）
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        self.selector = QComboBox()
        self.selector.setMinimumWidth(120)
        for label, val in SELECTOR_TYPES:
            self.selector.addItem(label, val)
        self.selector.currentIndexChanged.connect(self._on_changed)
        grid.addWidget(QLabel("选择器"), 0, 0)
        grid.addWidget(self.selector, 0, 1)

        # 预设下拉（早先是 18 个按钮横排挤成数行 —— 太臃肿；
        # 收进一个下拉，一步选中）
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("选择常用选择器…", "")
        for label, val in PRESETS:
            self.preset_combo.addItem(label, val)
        self.preset_combo.currentIndexChanged.connect(self._on_preset)
        grid.addWidget(QLabel("预设"), 1, 0)
        grid.addWidget(self.preset_combo, 1, 1)

        # 添加参数
        self.add_combo = QComboBox()
        self.add_combo.addItem("选择参数…", "")
        for k, label, kind, default, extra in SELECTOR_ARGS:
            self.add_combo.addItem(f"{k}（{label}）", k)
        self.add_combo.currentIndexChanged.connect(self._on_add)
        grid.addWidget(QLabel("添加参数"), 2, 0)
        grid.addWidget(self.add_combo, 2, 1)

        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        # 参数行（已添加的条件；每行 = 键下拉 + 值控件 + 删除）
        self.param_host = QWidget()
        self.param_lay = QVBoxLayout(self.param_host)
        self.param_lay.setContentsMargins(0, 0, 0, 0)
        self.param_lay.setSpacing(2)
        lay.addWidget(self.param_host)

        # 预览
        self.preview = QLabel()
        self.preview.setStyleSheet(
            "background:#1a1a2e;color:#00ff88;padding:6px;border-radius:4px;"
            "font-family:monospace;font-size:12px;")
        self.preview.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.preview)

        # 初始值
        if initial:
            self.set_text(initial)
        else:
            self._update_preview()

    def _on_changed(self):
        self._update_preview()
        self.changed.emit()

    def _on_add(self):
        key = self.add_combo.currentData()
        if not key:
            return
        # 检查是否已存在
        if any(r.key() == key for r in self._rows):
            return
        row = _ParamRow(key=key)
        row.changed.connect(self._on_changed)
        row.remove_requested.connect(self._remove_row)
        self.param_lay.addWidget(row)
        self._rows.append(row)
        self.add_combo.setCurrentIndex(0)
        self._update_preview()
        self.changed.emit()

    def _remove_row(self, row):
        self._rows.remove(row)
        self.param_lay.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._update_preview()
        self.changed.emit()

    def _on_preset(self, _idx=None):
        """预设下拉：应用后复位，便于连续选不同预设。"""
        val = self.preset_combo.currentData()
        if not val:
            return
        self._apply_preset(val)
        self.preset_combo.setCurrentIndex(0)

    def _apply_preset(self, text):
        selector, args = parse_selector(text)
        self.selector.setCurrentIndex(
            self.selector.findData(selector) or 0)
        # 清空现有行
        for r in list(self._rows):
            self._remove_row(r)
        # 添加参数
        for k, v in args.items():
            row = _ParamRow(key=k, value=v)
            row.changed.connect(self._on_changed)
            row.remove_requested.connect(self._remove_row)
            self.param_lay.addWidget(row)
            self._rows.append(row)
        self._update_preview()
        self.changed.emit()

    def _update_preview(self):
        selector = self.selector.currentData() or "@s"
        args = {}
        for r in self._rows:
            k = r.key()
            v = r.value_text()
            if k and v:
                args[k] = v
        self.preview.setText(build_selector(selector, args))

    def text(self) -> str:
        return self.preview.text()

    def set_text(self, text: str):
        selector, args = parse_selector(text)
        i = self.selector.findData(selector)
        if i >= 0:
            self.selector.setCurrentIndex(i)
        for r in list(self._rows):
            self._remove_row(r)
        for k, v in args.items():
            row = _ParamRow(key=k, value=v)
            row.changed.connect(self._on_changed)
            row.remove_requested.connect(self._remove_row)
            self.param_lay.addWidget(row)
            self._rows.append(row)
        self._update_preview()


# ---------------------------------------------------------------------------
# 统一弹窗编辑（与 NBT 字段同模式：只读行 + 「编辑…」按钮）
# ---------------------------------------------------------------------------
class TargetSelectorDialog(QDialog):
    """目标选择器弹窗：内嵌 TargetSelectorBuilder + 确定/取消。

    所有需要目标选择器的入口**统一**经此弹窗编辑，不再各自为政
    （give 页弹纯文本输入框、execute 链行用简易下拉、通用表单内嵌
    整块构建器 —— 三种形态并存，已全部改为本弹窗）。
    """

    def __init__(self, initial: str = "", title="选择目标",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 520)
        self.result_text = initial.strip()

        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        self.builder = TargetSelectorBuilder(initial)
        lay.addWidget(self.builder, 1)

        brow = QHBoxLayout()
        brow.addStretch(1)
        ok = QPushButton("确定")
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        brow.addWidget(ok)
        brow.addWidget(cancel)
        lay.addLayout(brow)

    def _accept(self):
        self.result_text = self.builder.text().strip()
        self.accept()


class TargetSelectorField(QWidget):
    """目标选择器字段：**可编辑下拉框** + 「编辑…」按钮。

    - 下拉：常用选择器一步选中（@s/@p/@a/@e/@r + 常用组合），
      也可直接手输玩家名或粘贴选择器原文；
    - 「编辑…」：复杂条件在统一弹窗里**一步一步添加**。
    """

    changed = Signal()

    # 常用选择器（字段行下拉，精选而非全部 18 预设）
    QUICK = ["@s", "@p", "@a", "@e", "@r",
             "@a[distance=..10]", "@a[gamemode=creative]",
             "@e[type=zombie]", "@e[type=villager]",
             "@e[type=item]", "@p[level=1..]"]

    def __init__(self, initial: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setMinimumWidth(200)
        self.combo.addItem("")                     # 可清空的空项
        for v in self.QUICK:
            self.combo.addItem(v, v)
        if initial:
            self.combo.setCurrentText(initial)
        # 手输 / 下拉选都触发 changed
        self.combo.currentIndexChanged.connect(
            lambda *_: self.changed.emit())
        self.combo.editTextChanged.connect(
            lambda *_: self.changed.emit())
        # 可搜索：输入子串过滤常用选择器
        from Utils.CommandGenerator.combo_complete import attach_search
        attach_search(self.combo)
        lay.addWidget(self.combo, 1)

        btn = QPushButton("编辑…")
        btn.clicked.connect(self._open_dialog)
        lay.addWidget(btn)

    def _open_dialog(self):
        dlg = TargetSelectorDialog(self.text(),
                                   parent=self.window())
        if dlg.exec():
            self.combo.setCurrentText(dlg.result_text)
            self.changed.emit()

    def text(self) -> str:
        return self.combo.currentText().strip()

    def set_text(self, text: str):
        self.combo.setCurrentText(text or "")

    def edit(self):
        """行编辑器（兼容旧 probe 的 .edit 访问）。"""
        return self.combo.lineEdit()