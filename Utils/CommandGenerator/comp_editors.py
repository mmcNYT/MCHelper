# -*- coding: utf-8 -*-
"""CommandGenerator：数据组件编辑控件。

每个组件一个「卡片」（QGroupBox），由 `build_editor` 按
components.kind_of(cid) 工厂化创建，统一暴露：
    editor.value()   -> Python 值（喂给 give.serialize_component）
    editor.set_value(v)
    editor.changed   -> Signal（值变更，用于实时刷新输出）

控件类型（对应 components.py 的 kind）：
    text     单行文本 + 样式按钮（-> dict，输出文本组件）
    lore     多行文本（每行一条）
    enchant  附魔表（复用 data/enchants.json，含互斥校验）
    flag     无值开关（输出 {}）
    int      整数
    float    浮点
    color    颜色（颜色选择 -> 整数 RGB）
    model    自定义模型数据（整数）
    attr     属性修饰符表
    json     复杂结构：SNBT 文本框兜底
"""
from __future__ import annotations

import json
import os
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog,
                               QComboBox, QDoubleSpinBox, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QSizePolicy,
                               QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from Utils.CommandGenerator import components as C
from Utils.CommandGenerator import snbt

# ---------------------------------------------------------------------------
# 附魔数据（复用项目 data/enchants.json）
# ---------------------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_ENCH_PATH = os.path.join(_ROOT, "data", "enchants.json")

_ENCH_CACHE = None


def enchants_data() -> list:
    """读取附魔数据（缓存）。"""
    global _ENCH_CACHE
    if _ENCH_CACHE is None:
        try:
            with open(_ENCH_PATH, encoding="utf-8") as f:
                _ENCH_CACHE = json.load(f).get("enchants", [])
        except (OSError, ValueError):
            _ENCH_CACHE = []
    return _ENCH_CACHE


def enchant_by_id() -> dict:
    return {e["id"]: e for e in enchants_data()}


# ---------------------------------------------------------------------------
# 基类
# ---------------------------------------------------------------------------

class _Editor(QWidget):
    """组件编辑器基类。"""

    changed = Signal()

    def __init__(self, cid: str, parent=None):
        super().__init__(parent)
        self.cid = cid

    def value(self):
        raise NotImplementedError

    def set_value(self, v):
        raise NotImplementedError

    def missing_required(self) -> list:
        """未填的**必填**字段键名（供 UI 提示，默认无）。"""
        return []

    def _emit(self, *_a):
        self.changed.emit()


# ---------------------------------------------------------------------------
# 文本
# ---------------------------------------------------------------------------

_TEXT_COLORS = ["", "black", "dark_blue", "dark_green", "dark_aqua",
                "dark_red", "dark_purple", "gold", "gray", "dark_gray",
                "blue", "green", "aqua", "red", "light_purple", "yellow",
                "white"]


class TextEditor(_Editor):
    """单行文本 + 可选样式 -> 文本组件。

    无样式时 value() 返回 str（give.py 会转成裸 SNBT 字符串）；
    有样式时返回 dict（give.py 转成 {text:...,color:...}）。
    """

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("文本内容")
        self.edit.textChanged.connect(self._emit)
        row.addWidget(self.edit, 1)

        row.addWidget(QLabel("颜色"))
        self.color = QComboBox()
        self.color.setEditable(False)
        for c in _TEXT_COLORS:
            self.color.addItem(c or "（默认）", c)
        self.color.currentIndexChanged.connect(self._emit)
        row.addWidget(self.color)
        lay.addLayout(row)

        flags = QHBoxLayout()
        flags.setSpacing(10)
        self.bold = QCheckBox("粗体")
        self.italic = QCheckBox("斜体")
        self.underline = QCheckBox("下划线")
        self.strike = QCheckBox("删除线")
        for w in (self.bold, self.italic, self.underline, self.strike):
            w.stateChanged.connect(self._emit)
            flags.addWidget(w)
        flags.addStretch(1)
        lay.addLayout(flags)

    def value(self):
        text = self.edit.text()
        style = {}
        if self.color.currentData():
            style["color"] = self.color.currentData()
        if self.bold.isChecked():
            style["bold"] = True
        if self.italic.isChecked():
            style["italic"] = True
        if self.underline.isChecked():
            style["underlined"] = True
        if self.strike.isChecked():
            style["strikethrough"] = True
        if not style:
            return text                 # -> 裸 SNBT 字符串
        return {"text": text, **style}

    def set_value(self, v):
        if isinstance(v, dict):
            self.edit.setText(v.get("text", ""))
            c = v.get("color", "")
            i = self.color.findData(c)
            self.color.setCurrentIndex(max(0, i))
            self.bold.setChecked(bool(v.get("bold")))
            self.italic.setChecked(bool(v.get("italic")))
            self.underline.setChecked(bool(v.get("underlined")))
            self.strike.setChecked(bool(v.get("strikethrough")))
        else:
            self.edit.setText("" if v is None else str(v))


class LoreEditor(_Editor):
    """多行文本（每行一条 lore）。"""

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        hint = QLabel("每行一条描述")
        lay.addWidget(hint)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("第一行\n第二行")
        self.edit.setMinimumHeight(70)
        self.edit.textChanged.connect(self._emit)
        lay.addWidget(self.edit)

    def value(self):
        txt = self.edit.toPlainText()
        lines = [ln for ln in txt.split("\n") if ln.strip()]
        return lines or None

    def set_value(self, v):
        if isinstance(v, (list, tuple)):
            self.edit.setPlainText("\n".join(str(x) for x in v))
        elif v:
            self.edit.setPlainText(str(v))
        else:
            self.edit.setPlainText("")


# ---------------------------------------------------------------------------
# 附魔
# ---------------------------------------------------------------------------

class EnchantEditor(_Editor):
    """附魔表：附魔 + 等级，含 max_level / 互斥校验。

    value() 返回 {"sharpness": 5, ...}（give.py 按版本决定是否包 levels）。
    """

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent)
        self._table_data = enchant_by_id()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["附魔", "等级", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.table.setMinimumHeight(84)
        self.table.setMaximumHeight(200)
        hh = self.table.horizontalHeader()
        # 列宽策略（**不要用 ResizeToContents 给含控件的列**）：
        # ResizeToContents 只按「表头文字 + item 文本」量宽，**不计入
        # setCellWidget 放的控件**。故「等级」列按表头文字「等级」
        # 只拿到 32px，而 QSpinBox（含上下箭头）需要 73px —— 表现为
        # 等级列被压扁、数字和箭头挤在一起。
        # 解决：附魔列 Stretch（吸收余量），等级/操作列固定到控件的
        # 实际需要宽度。
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._spin_w = self._measure_spin_width()
        self._btn_w = self._measure_btn_width()
        self.table.setColumnWidth(1, self._spin_w)
        self.table.setColumnWidth(2, self._btn_w)
        lay.addWidget(self.table)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.add_combo = QComboBox()
        self.add_combo.setEditable(True)
        for e in enchants_data():
            self.add_combo.addItem(f'{e["name"]}（{e["id"]}）', e["id"])
        self.add_combo.setCurrentIndex(-1)
        self.add_combo.setMinimumWidth(220)
        row.addWidget(self.add_combo, 1)
        self.add_btn = QPushButton("添加附魔")
        self.add_btn.clicked.connect(self._add)
        row.addWidget(self.add_btn)
        lay.addLayout(row)

        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        lay.addWidget(self.warn)

    # ---- 列宽测量 ----
    @staticmethod
    def _measure_spin_width() -> int:
        """等级列所需宽度：一个 QSpinBox（含上下箭头）+ 边距。

        直接构造一个同规格 SpinBox 取 minimumSizeHint，避免硬编码 ——
        不同 DPI/字体下箭头与数字所占宽度不同。
        """
        probe = QSpinBox()
        probe.setMinimum(1)
        probe.setMaximum(255)
        probe.setValue(255)                 # 用最宽的数字量
        w = probe.minimumSizeHint().width() + 14    # 单元格左右内边距
        probe.deleteLater()
        return max(w, 72)

    @staticmethod
    def _measure_btn_width() -> int:
        """操作列所需宽度：一个「移除」按钮。"""
        probe = QPushButton("移除")
        w = probe.sizeHint().width() + 14
        probe.deleteLater()
        return max(w, 64)

    def _apply_col_widths(self):
        """表格尺寸变化后重新固定等级/操作列宽。"""
        try:
            self.table.setColumnWidth(1, self._spin_w)
            self.table.setColumnWidth(2, self._btn_w)
        except (AttributeError, RuntimeError):
            pass

    # ---- 内部 ----
    def _add(self):
        idx = self.add_combo.currentIndex()
        eid = self.add_combo.currentData()
        if eid is None:
            txt = self.add_combo.currentText().strip()
            eid = txt.split("（")[-1].rstrip("）") if "（" in txt else txt
        if not eid or eid not in self._table_data:
            return
        # 已存在则不重复添加
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) == eid:
                return
        self._append_row(eid, 1)
        if idx >= 0:
            self.add_combo.setCurrentIndex(-1)
        self._emit()

    def _append_row(self, eid: str, level: int):
        e = self._table_data.get(eid, {})
        r = self.table.rowCount()
        self.table.insertRow(r)

        it = QTableWidgetItem(f'{e.get("name", eid)}（{eid}）')
        it.setData(Qt.ItemDataRole.UserRole, eid)
        it.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(r, 0, it)

        spin = QSpinBox()
        # 让 SpinBox 填满单元格，否则即使列够宽也只有 31px 可用
        spin.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        spin.setMinimum(1)
        spin.setMaximum(int(e.get("max_level", 255) or 255))
        spin.setValue(level)
        spin.setMinimumWidth(self._spin_w - 14)
        spin.valueChanged.connect(self._emit)
        self.table.setCellWidget(r, 1, spin)

        btn = QPushButton("移除")
        btn.clicked.connect(lambda _=False, b=btn: self._remove(b))
        self.table.setCellWidget(r, 2, btn)

    def _remove(self, btn):
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 2) is btn:
                self.table.removeRow(r)
                break
        self._emit()

    def _rows(self):
        out = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            spin = self.table.cellWidget(r, 1)
            if it and spin:
                out.append((it.data(Qt.ItemDataRole.UserRole),
                            spin.value()))
        return out

    def value(self):
        rows = self._rows()
        if not rows:
            return None
        return {eid: lvl for eid, lvl in rows}

    def set_value(self, v):
        self.table.setRowCount(0)
        if isinstance(v, dict):
            for eid, lvl in v.items():
                self._append_row(eid, int(lvl))
        self._check()

    def _check(self):
        """互斥 / 适用性提示（不阻止输出，只提示）。"""
        rows = self._rows()
        ids = [e for e, _ in rows]
        msgs = []
        for eid in ids:
            e = self._table_data.get(eid, {})
            for c in e.get("conflicts", []) or []:
                if c in ids and c > eid:
                    other = self._table_data.get(c, {}).get("name", c)
                    msgs.append(f"⚠ {e.get('name', eid)} 与 {other} 互斥")
        self.warn.setText("\n".join(msgs))
        self.warn.setVisible(bool(msgs))


# ---------------------------------------------------------------------------
# 标量
# ---------------------------------------------------------------------------

class IntEditor(_Editor):
    def __init__(self, cid, parent=None, minimum=0, maximum=100000,
                 default=0, suffix=""):
        super().__init__(cid, parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setValue(default)
        self.spin.valueChanged.connect(self._emit)
        lay.addWidget(self.spin)
        if suffix:
            lay.addWidget(QLabel(suffix))
        lay.addStretch(1)

    def value(self):
        return self.spin.value()

    def set_value(self, v):
        try:
            self.spin.setValue(int(v))
        except (TypeError, ValueError):
            self.spin.setValue(0)


class FloatEditor(_Editor):
    def __init__(self, cid, parent=None, minimum=-100000.0,
                 maximum=100000.0, default=0.0, decimals=3):
        super().__init__(cid, parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setDecimals(decimals)
        self.spin.setValue(default)
        self.spin.valueChanged.connect(self._emit)
        lay.addWidget(self.spin)
        lay.addStretch(1)

    def value(self):
        return self.spin.value()

    def set_value(self, v):
        try:
            self.spin.setValue(float(v))
        except (TypeError, ValueError):
            self.spin.setValue(0.0)


class FlagEditor(_Editor):
    """无值组件（如 unbreakable / glider）-> 输出 {}。

    默认**勾选**：用户从「添加组件」里主动选了该组件，意图就是启用它；
    若默认不勾选会产出空值而被丢弃，等于添加无效。
    """

    def __init__(self, cid, parent=None, label="启用", checked=True):
        super().__init__(cid, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.check = QCheckBox(label)
        self.check.setChecked(checked)
        self.check.stateChanged.connect(self._emit)
        lay.addWidget(self.check)

    def value(self):
        return {} if self.check.isChecked() else None

    def set_value(self, v):
        self.check.setChecked(v is not None and v is not False)


class ColorEditor(_Editor):
    """颜色 -> 整数 RGB（give.py 输出 {rgb:N}）。"""

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent)
        self._rgb = 0xFFFFFF
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.swatch = QLabel()
        self.swatch.setFixedSize(28, 22)
        self.hex_edit = QLineEdit("#FFFFFF")
        self.hex_edit.setMaximumWidth(100)
        self.hex_edit.textChanged.connect(self._on_text)
        btn = QPushButton("选色…")
        btn.clicked.connect(self._pick)
        lay.addWidget(self.swatch)
        lay.addWidget(self.hex_edit)
        lay.addWidget(btn)
        lay.addStretch(1)
        self._refresh()

    def _refresh(self):
        self.swatch.setStyleSheet(
            f"background:#{self._rgb:06X};border:1px solid #888;")

    def _on_text(self, txt):
        t = txt.strip().lstrip("#")
        if len(t) == 6:
            try:
                self._rgb = int(t, 16)
                self._refresh()
                self._emit()
            except ValueError:
                pass

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._rgb), self, "选择颜色")
        if c.isValid():
            self._rgb = (c.red() << 16) | (c.green() << 8) | c.blue()
            self.hex_edit.setText(f"#{self._rgb:06X}")
            self._refresh()
            self._emit()

    def value(self):
        return self._rgb

    def set_value(self, v):
        try:
            self._rgb = int(v)
        except (TypeError, ValueError):
            self._rgb = 0xFFFFFF
        self.hex_edit.setText(f"#{self._rgb:06X}")
        self._refresh()


class EnumEditor(_Editor):
    """枚举字符串组件：下拉选择合法取值，避免产出空值。"""

    def __init__(self, cid, parent=None, choices=None):
        super().__init__(cid, parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.combo = QComboBox()
        self.combo.setEditable(True)
        for c in (choices if choices is not None
                  else C.enum_choices(cid)):
            self.combo.addItem(c, c)
        if self.combo.count() == 0:
            self.combo.setCurrentText("")
        self.combo.currentIndexChanged.connect(self._emit)
        self.combo.editTextChanged.connect(self._emit)
        lay.addWidget(self.combo, 1)

    def value(self):
        txt = self.combo.currentText().strip()
        return txt or None

    def set_value(self, v):
        if v is None:
            return
        i = self.combo.findData(v)
        if i >= 0:
            self.combo.setCurrentIndex(i)
        else:
            self.combo.setCurrentText(str(v))


class JsonEditor(_Editor):
    """复杂结构组件：SNBT 文本框兜底（直接作为组件值输出）。"""

    def __init__(self, cid, parent=None, hint=""):
        super().__init__(cid, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        cap = QLabel(hint or "SNBT 值（直接写入组件，例：{level:1}）")
        cap.setWordWrap(True)
        lay.addWidget(cap)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("{...} 或 [...] 或 数值/字符串")
        self.edit.textChanged.connect(self._emit)
        lay.addWidget(self.edit)

    def raw(self) -> str:
        return self.edit.text().strip()

    def value(self):
        return snbt.RawSnbt(self.raw())

    def set_value(self, v):
        self.edit.setText("" if v is None else str(v))


# ---------------------------------------------------------------------------
# 属性修饰符
# ---------------------------------------------------------------------------

# 槽位（官方 EquipmentSlotGroup 常用值）
ATTR_SLOTS = ["any", "mainhand", "offhand", "hand", "feet", "legs",
              "chest", "head", "armor", "body"]
ATTR_OPS = ["add_value", "add_multiplied_base", "add_multiplied_total"]


class AttrEditor(_Editor):
    """属性修饰符表。value() -> [ {id,type,amount,operation,slot}, ... ]"""

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["属性 id", "数值", "运算", "槽位", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(84)
        self.table.setMaximumHeight(180)
        hh = self.table.horizontalHeader()
        # 同 EnchantEditor：含控件的列**不能用 ResizeToContents**
        # （它只量表头文字，不计 cellWidget），故「操作」列显式定宽。
        for i in range(4):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._btn_w = EnchantEditor._measure_btn_width()
        self.table.setColumnWidth(4, self._btn_w)
        lay.addWidget(self.table)

        btn = QPushButton("添加属性")
        btn.clicked.connect(self._add)
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)

    def _add(self):
        r = self.table.rowCount()
        self.table.insertRow(r)

        name = QLineEdit("generic.attack_damage")
        name.textChanged.connect(self._emit)
        self.table.setCellWidget(r, 0, name)

        amt = QDoubleSpinBox()
        amt.setRange(-100000.0, 100000.0)
        amt.setDecimals(2)
        amt.setValue(1.0)
        amt.valueChanged.connect(self._emit)
        self.table.setCellWidget(r, 1, amt)

        op = QComboBox()
        op.addItems(ATTR_OPS)
        op.currentIndexChanged.connect(self._emit)
        self.table.setCellWidget(r, 2, op)

        slot = QComboBox()
        slot.addItems(ATTR_SLOTS)
        slot.currentIndexChanged.connect(self._emit)
        self.table.setCellWidget(r, 3, slot)

        rm = QPushButton("移除")
        rm.clicked.connect(lambda _=False, b=rm: self._remove(b))
        self.table.setCellWidget(r, 4, rm)
        self._emit()

    def _remove(self, btn):
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 4) is btn:
                self.table.removeRow(r)
                break
        self._emit()

    def value(self):
        out = []
        for r in range(self.table.rowCount()):
            name = self.table.cellWidget(r, 0)
            amt = self.table.cellWidget(r, 1)
            op = self.table.cellWidget(r, 2)
            slot = self.table.cellWidget(r, 3)
            if not (name and amt and op and slot):
                continue
            if not name.text().strip():
                continue
            out.append({
                "id": f"mch:attr{r}",
                "type": name.text().strip(),
                "amount": amt.value(),
                "operation": op.currentText(),
                "slot": slot.currentText(),
            })
        return out or None

    def set_value(self, v):
        self.table.setRowCount(0)
        for m in (v or []):
            self._add()
            r = self.table.rowCount() - 1
            self.table.cellWidget(r, 0).setText(m.get("type", ""))
            self.table.cellWidget(r, 1).setValue(float(m.get("amount", 0)))
            op = self.table.cellWidget(r, 2)
            i = op.findText(m.get("operation", "add_value"))
            op.setCurrentIndex(max(0, i))
            sl = self.table.cellWidget(r, 3)
            j = sl.findText(m.get("slot", "any"))
            sl.setCurrentIndex(max(0, j))


# ---------------------------------------------------------------------------
# 通用复合编辑器（由 comp_meta 的字段表驱动）
# ---------------------------------------------------------------------------

# codec 表达式 -> 控件类型（按优先级匹配）
_CODEC_RULES = [
    (r"Codec\.BOOL|BoolArgumentType", "bool"),
    (r"RGB_COLOR_CODEC|Color", "color"),
    (r"Codec\.LONG|Long\b", "long"),
    # 整数：需覆盖 ExtraCodecs.NON_NEGATIVE_INT / POSITIVE_INT 等
    # （早先只匹配 Codec\.INT，导致 food.nutrition 这类必填整数字段
    #  被判成文本框而值被丢弃）
    (r"_INT\b|Codec\.INT\b|Integer|intRange", "int"),
    (r"floatRange|Codec\.FLOAT|FLOAT|Float", "float"),
    (r"Codec\.DOUBLE|Double", "float"),
    (r"ComponentSerialization|Component\b", "text"),
    (r"HolderSet|Holder\.codec|EitherHolder|Holder<", "holder"),
    (r"CompoundTag", "nbt"),
    (r"\.listOf\(\)|sizeLimitedListOf|nonEmptyList|List<", "list"),
    (r"unboundedMap|Object2|Map<", "map"),
    (r"Codec\.STRING|String", "string"),
    (r"Identifier|ResourceLocation", "resid"),
]


def _codec_kind(codec: str) -> str:
    """按 codec 表达式猜控件类型。"""
    for pat, k in _CODEC_RULES:
        if re.search(pat, codec or ""):
            return k
    return "string"


def _is_java_const_ref(text: str) -> bool:
    """判断默认值文本是否为 **Java 常量引用**（不可直接写入 SNBT）。

    例如 `BlocksAttacks.ItemDamageFunction.DEFAULT`、
    `ItemUseAnimation.EAT`、`SoundEvents.GENERIC_EAT`、
    `DEFAULT.speedMultiplier`。

    这类值只是 Java 侧的默认实参，**不是 SNBT 字面量**；若原样写进
    组件会产出 `item_damage:"BlocksAttacks.ItemDamageFunction.DEFAULT"`
    这种游戏无法解析的内容。正确做法是**留空**，让游戏自己取默认。
    """
    t = (text or "").strip()
    if not t:
        return False
    # 字面量（数字/布尔/字符串/列表/映射/空值）不是常量引用
    if re.match(r'^-?[0-9]', t) or t in ("true", "false"):
        return False
    if t.startswith(('"', "List.of", "Map.of", "IntList.of", "Optional",
                     "{", "[", "new ")):
        return False
    if "emptySet" in t or "emptyList" in t or "emptyMap" in t:
        return False
    # 形如 Xxx.Yyy 或 Xxx.yyy(...)
    return bool(re.match(r'^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+', t))


def _default_to_python(text, kind):
    """把 Java 默认值文本转成 Python 值。

    常量引用一律返回 None（= 不填），由游戏取默认。
    """
    if text is None:
        return None
    t = str(text).strip()
    if not t:
        return None
    if _is_java_const_ref(t):
        return None
    if t in ("true", "false"):
        return t == "true"
    # 纯数值（可带 F/D/L 后缀）
    m = re.fullmatch(r"(-?(?:[0-9]+\.?[0-9]*|\.[0-9]+))([FfDdLl])?", t)
    if m and m.group(1) not in ("", ".", "-"):
        num = m.group(1)
        try:
            if kind == "float" or "." in num:
                return float(num)
            return int(num)
        except ValueError:
            pass
    if "empty" in t.lower():
        return None
    if t.startswith("List.of(") or t.startswith("IntList.of("):
        return []
    if t.startswith("Map.of(") or t.startswith("{"):
        return {}
    return None


class CompoundEditor(_Editor):
    """由 comp_meta 字段表驱动的复合组件编辑器。

    每个字段一行控件；`value()` 返回 {键名: 值}，喂给
    give.serialize_component 直接产出 SNBT。
    未填的**可选**字段留 None（serialize 时跳过）。
    """

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent)
        self._rows = []                 # [(field_spec, widget_kind, widget)]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)

        fields = C.fields_of(cid)
        if not fields:
            lay.addWidget(QLabel("该组件无可枚举字段，请用下方 SNBT 填写"))
            self._fallback = JsonEditor(cid, parent)
            self._fallback.changed.connect(self._emit)
            lay.addWidget(self._fallback)
            return
        self._fallback = None

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        for r, f in enumerate(fields):
            k = _codec_kind(f["codec"])
            lab = f["key"] + ("（可选）" if f["optional"] else "")
            grid.addWidget(QLabel(lab), r, 0)
            w, keff = self._make_field_widget(f, k)
            grid.addWidget(w, r, 1)
            d = f.get("default")
            if d:
                hint = QLabel(f"默认 {d}")
                hint.setStyleSheet("color:#888;font-size:11px;")
                grid.addWidget(hint, r, 2)
            self._rows.append((f, keff, w))
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

    def _make_field_widget(self, f: dict, k: str) -> tuple:
        """返回 (控件, 实际控件类型)。

        实际类型可能与推断的 k 不同（如默认值是枚举常量时把
        int/float 降级为 string），故必须把**实际**类型回传给
        `_read`，否则会对 QLineEdit 调 .value() 而报
        AttributeError。
        """
        dflt = _default_to_python(f.get("default"), k)
        opt = f["optional"]
        # 默认值可能是枚举常量引用（如 DEFAULT.speedMultiplier），
        # 与 codec 推断的数值类型不符 —— 此时按文本框处理，避免
        # float()/int() 抛错
        if k in ("int", "float") and isinstance(dflt, str):
            k = "string"

        # 字段级枚举（如 firework_explosion.shape）优先用下拉，
        # 否则必填字段会因文本框为空而**静默丢数据**
        choices = C.field_enum(self.cid, f["key"])
        if choices:
            cb = QComboBox()
            cb.setEditable(True)
            for c in choices:
                cb.addItem(c, c)
            if isinstance(dflt, str) and dflt in choices:
                cb.setCurrentIndex(cb.findData(dflt))
            elif choices:
                cb.setCurrentIndex(0)
            cb.currentIndexChanged.connect(self._emit)
            cb.editTextChanged.connect(self._emit)
            return cb, "enum"

        if k == "bool":
            cb = QComboBox()
            cb.addItem("（不填）", None)
            cb.addItem("true", True)
            cb.addItem("false", False)
            if isinstance(dflt, bool):
                i = cb.findData(dflt)
                cb.setCurrentIndex(i if i >= 0 else 0)
            cb.currentIndexChanged.connect(self._emit)
            return cb, k

        if k == "int":
            sp = QSpinBox()
            sp.setRange(-1000000000, 1000000000)
            if opt:
                sp.setMinimum(-1000000001)
                sp.setSpecialValueText("（不填）")
                sp.setValue(-1000000001 if dflt is None else int(dflt))
            else:
                sp.setValue(int(dflt) if dflt is not None else 0)
            sp.valueChanged.connect(self._emit)
            return sp, k

        if k == "float":
            sp = QDoubleSpinBox()
            sp.setRange(-1e9, 1e9)
            sp.setDecimals(3)
            if opt:
                sp.setMinimum(-1e9 - 1)
                sp.setSpecialValueText("（不填）")
                sp.setValue(-1e9 - 1 if dflt is None else float(dflt))
            else:
                sp.setValue(float(dflt) if dflt is not None else 0.0)
            sp.valueChanged.connect(self._emit)
            return sp, k

        if k == "long":
            # long 用文本框（QSpinBox 上限仅 int32；SNBT 需 L 后缀）
            ed = QLineEdit()
            ed.setText("" if dflt is None else str(dflt))
            ed.setPlaceholderText("整数（可带 L 后缀）")
            ed.textChanged.connect(self._emit)
            return ed, k

        if k == "color":
            return ColorEditor(self.cid), k

        # string / resid / holder / list / map / nbt / text -> 文本框
        ed = QLineEdit()
        if dflt is not None and not isinstance(dflt, (list, dict)):
            ed.setText(str(dflt))
        ed.setPlaceholderText({
            "nbt": "{...}",
            "list": "[...]",
            "map": "{k:v}",
            "text": '"文字" 或 {text:"..."}',
            "holder": "minecraft:xxx",
            "resid": "minecraft:xxx",
        }.get(k, ""))
        ed.textChanged.connect(self._emit)
        return ed, k

    def _read(self, w, k, f):
        if k == "bool":
            return w.currentData()
        if k == "int":
            if f["optional"] and w.value() < -1000000000:
                return None
            return w.value()
        if k == "float":
            if f["optional"] and w.value() < -1e9:
                return None
            return w.value()
        if k == "color":
            return w.value()
        if k == "enum":
            txt = w.currentText().strip()
            return txt or None
        # long / string / resid / holder / list / map / nbt 均为文本框
        txt = w.text().strip()
        return txt if txt else None

    def value(self):
        if self._fallback is not None:
            v = self._fallback.value()
            return v if str(v).strip() else None
        out = {}
        for f, k, w in self._rows:
            v = self._read(w, k, f)
            if v is None or v == "":
                continue
            out[f["key"]] = v
        return out or None

    def missing_required(self) -> list:
        """未填的必填字段（这些字段无法猜默认值，必须用户提供）。

        实测需要用户填的有：container_loot.loot_table（战利品表 id）、
        written_book_content.title/author（成书标题作者）、tool.rules
        （挖掘规则列表）等。
        """
        if self._fallback is not None:
            return []
        v = self.value() or {}
        return [f["key"] for f, _k, _w in self._rows
                if not f["optional"] and f["key"] not in v]

    def set_value(self, v):
        if self._fallback is not None:
            self._fallback.set_value(v)
            return
        if not isinstance(v, dict):
            return
        for f, k, w in self._rows:
            if f["key"] not in v:
                continue
            val = v[f["key"]]
            if k == "bool":
                i = w.findData(val)
                w.setCurrentIndex(i if i >= 0 else 0)
            elif k in ("int", "float"):
                w.setValue(val)
            elif k == "color":
                w.set_value(val)
            else:
                w.setText("" if val is None else
                          (snbt.snbt_any(val) if isinstance(val, (list, dict))
                           else str(val)))


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------

def build_editor(cid: str, parent=None) -> _Editor:
    """按组件形态创建编辑器。

    **手工专用**（语义特殊，需专用控件与版本分支）：
        enchantments / stored_enchantments -> 附魔表
        custom_name / item_name / lore     -> 文本组件
        unbreakable / glider / ... (unit)  -> 开关
        dyed_color                         -> 取色器
        attribute_modifiers                -> 属性表
        custom_model_data                  -> 整数（写出 floats）
        tooltip_display                    -> SNBT 兜底
    **其余**：由 comp_meta 的字段表驱动（CompoundEditor），
             无字段的退回 SNBT 文本框。
    """
    # 纯 NBT 组件：值就是**任意复合标签**，SNBT 文本框是**正确的**
    # 编辑方式（不存在更结构化的形态），但给足示例提示。
    NBT_HINTS = {
        "custom_data": '任意 NBT 复合，如 {SomeTag:1b}；游戏内可在'
                       '「数据修改」等场景读回',
        "entity_data": '实体 NBT（必须含 id），如 '
                       '{id:"minecraft:zombie",NoAI:1b}；'
                       '用于刷怪蛋/生物头颅等',
        "block_entity_data": '方块实体 NBT（须与容器类型匹配），如 '
                             '{Lock:"minecraft:diamond"}',
        "bucket_entity_data": '桶装实体 NBT（必须含 id），如 '
                              '{id:"minecraft:tropical_fish",Variant:0}',
    }
    if cid in NBT_HINTS:
        return JsonEditor(cid, parent, NBT_HINTS[cid])

    # ---- 手工专用 ----
    if cid in ("enchantments", "stored_enchantments"):
        return EnchantEditor(cid, parent)
    if cid in ("custom_name", "item_name"):
        return TextEditor(cid, parent)
    if cid == "lore":
        return LoreEditor(cid, parent)
    if cid == "attribute_modifiers":
        return AttrEditor(cid, parent)
    if cid == "dyed_color":
        return ColorEditor(cid, parent)
    if cid == "custom_model_data":
        return IntEditor(cid, parent, -100000, 100000, 0,
                         "（写出 {floats:[N.0f]}）")
    if cid == "max_stack_size":
        return IntEditor(cid, parent, 1, 99, 64)
    if cid == "max_damage":
        return IntEditor(cid, parent, 1, 100000, 100)
    if cid == "repair_cost":
        return IntEditor(cid, parent, 0, 100000, 0)

    # ---- 二批：holder / 列表 / map 类组件的结构化编辑器 ----
    from Utils.CommandGenerator import comp_editors2 as _E2

    # holder：单选资源
    HOLDER_SRC = {
        "break_sound": "sound",
        "damage_type": "damage_type",
        "instrument": "instrument",
        "jukebox_playable": "jukebox_song",
        "provides_trim_material": "trim_material",
    }
    if cid in HOLDER_SRC:
        return _E2.HolderEditor(cid, HOLDER_SRC[cid], parent)

    # 列表
    if cid in ("bundle_contents", "charged_projectiles"):
        return _E2.ItemListEditor(cid, parent)
    if cid == "pot_decorations":
        return _E2.ItemListEditor(cid, parent, max_items=4)
    if cid == "container":
        return _E2.ContainerEditor(cid, parent)
    if cid == "suspicious_stew_effects":
        return _E2.StewEditor(cid, parent)
    if cid == "banner_patterns":
        return _E2.BannerEditor(cid, parent)

    # map
    if cid == "block_state":
        return _E2.BlockStateEditor(cid, parent)
    if cid == "map_decorations":
        return _E2.MapDecoEditor(cid, parent)
    if cid == "potion_contents":
        return _E2.PotionEditor(cid, parent)
    # 第三批
    if cid == "profile":
        return _E2.ProfileEditor(cid, parent)
    if cid == "use_remainder":
        return _E2.ItemStackEditor(cid, parent)
    if cid in ("can_break", "can_place_on"):
        return _E2.BlockPredicateListEditor(cid, parent)
    if cid == "recipes":
        return _E2.RecipeListEditor(cid, parent)
    if cid == "bees":
        return _E2.BeesEditor(cid, parent)
    if cid == "lock":
        return _E2.LockEditor(cid, parent)

    # ---- 按形态 ----
    kind = C.kind_of(cid)
    if kind == "unit":
        return FlagEditor(cid, parent, "启用该组件")
    if kind == "text":
        return TextEditor(cid, parent)
    if kind == "textlines":
        return LoreEditor(cid, parent)
    if kind == "scalar":
        m = C.COMP_META.get(cid, {})
        codec = m.get("codec", "")
        if "BOOL" in codec:
            return FlagEditor(cid, parent, "启用该组件")
        if "FLOAT" in codec or "DOUBLE" in codec:
            return FloatEditor(cid, parent)
        return IntEditor(cid, parent, -100000, 100000, 0)
    if kind == "enum_string":
        return EnumEditor(cid, parent)
    if kind == "compound":
        return CompoundEditor(cid, parent)

    # list / map / holder / nbt -> 字段驱动的复合编辑器（无字段则兜底文本）
    return CompoundEditor(cid, parent)
