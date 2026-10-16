# -*- coding: utf-8 -*-
"""CommandGenerator：**通用参数表单渲染器**（spec -> 控件）。

这是「一套 UI 覆盖所有指令」的落点：读 `cmd_specs.SPECS[cmd]`，
为每个 field 按 kind 创建控件，并统一收集参数字典。

用法：
    form = CommandForm(cmd)
    form.changed.connect(on_change)
    form.params()   -> dict（直接喂给 commands.serialize）

分支指令（如 effect/locate）会先渲染「分支」下拉，切换时重建
下方的参数字段。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                               QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from Utils.CommandGenerator import cmd_specs as CS
from Utils.CommandGenerator import item_list as IL
from Utils.CommandGenerator import resource_lists as RL
from Utils.CommandGenerator import struct_list as SL


class CommandForm(QWidget):
    """按 spec 渲染的参数表单。"""

    changed = Signal()

    def __init__(self, cmd: str, parent=None):
        super().__init__(parent)
        self.cmd = cmd
        self.spec = CS.SPECS.get(cmd, {})
        self._widgets = {}          # key -> 取值回调 / 控件
        self._fields = []           # 当前字段 spec 列表
        self._branch_combo = None
        self._busy = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # 分支选择器
        if "branches" in self.spec:
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(QLabel(self.spec.get("branch_field", "分支")))
            self._branch_combo = QComboBox()
            for name, sub in self.spec["branches"].items():
                self._branch_combo.addItem(
                    sub.get("label", name), name)
            self._branch_combo.currentIndexChanged.connect(
                self._on_branch_changed)
            row.addWidget(self._branch_combo, 1)
            root.addLayout(row)

            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            root.addWidget(line)

        self._form_host = QWidget()
        self._form = QFormLayout(self._form_host)
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight |
                                     Qt.AlignmentFlag.AlignVCenter)
        self._form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self._form.setSpacing(6)
        root.addWidget(self._form_host)
        root.addStretch(1)

        self._rebuild()

    # ------------------------------------------------------------------
    def branch(self) -> str:
        return self._branch_combo.currentData() if self._branch_combo \
            else ""

    def _on_branch_changed(self):
        if self._busy:
            return
        self._rebuild()
        self.changed.emit()

    def _current_fields(self) -> list:
        if "branches" in self.spec:
            sub = self.spec["branches"].get(self.branch(), {})
            fields = list(sub.get("fields", []))
            # 附加公共尾参（如 loot 的目标段：所有来源共享）
            fields += self.spec.get("_target_fields", [])
            return fields
        return self.spec.get("fields", [])

    def _rebuild(self):
        """按当前分支重建字段控件。"""
        self._busy = True
        try:
            while self._form.count():
                it = self._form.takeAt(0)
                w = it.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
            self._widgets.clear()
            self._fields = self._current_fields()
            for fs in self._fields:
                w = self._make_widget(fs)
                label = fs["label"]
                if fs.get("optional"):
                    label += "（可空）"
                self._form.addRow(label, w)
                if fs.get("hint"):
                    h = QLabel(fs["hint"])
                    h.setWordWrap(True)
                    h.setStyleSheet("color: #888; font-size: 11px;")
                    self._form.addRow("", h)
        finally:
            self._busy = False

    # ------------------------------------------------------------------
    def _make_widget(self, fs: dict) -> QWidget:
        kind = fs["kind"]
        key = fs["key"]
        dflt = fs.get("default")

        if kind == "targets":
            cb = QComboBox()
            cb.setEditable(True)
            cb.addItem("")
            cb.addItems(CS.TARGET_PRESETS)
            cb.setCurrentText(dflt or "")
            cb.currentTextChanged.connect(self._emit)
            self._widgets[key] = ("text", cb)
            return cb

        if kind == "pos":
            cb = QComboBox()
            cb.setEditable(True)
            cb.addItem("")
            cb.addItems(fs.get("presets", CS.POS_PRESETS))
            cb.setCurrentText(dflt or "")
            cb.currentTextChanged.connect(self._emit)
            self._widgets[key] = ("text", cb)
            return cb

        if kind == "block":
            cb = QComboBox()
            cb.setEditable(True)
            cb.addItem("")
            cb.addItems(fs.get("presets", CS.COMMON_BLOCKS))
            # 方块下拉：默认附 1053 个官方方块（中文名），可搜索
            if fs.get("full_blocks", True):
                for rid, label in self._resource_items("block"):
                    cb.addItem(label if label == rid
                               else f"{label}（{rid}）", rid)
            if dflt:
                i = cb.findData(dflt)
                if i >= 0:
                    cb.setCurrentIndex(i)
                else:
                    cb.setCurrentText(dflt)
            cb.currentIndexChanged.connect(self._emit)
            cb.editTextChanged.connect(self._emit)
            self._widgets[key] = ("block_res", cb)
            return cb

        if kind == "loot_table_res":
            # 战利品表下拉（119 个官方表；id 含斜杠不加前缀）
            cb = QComboBox()
            cb.setEditable(True)
            cb.addItem("")
            for rid in getattr(RL, "LOOT_TABLE_IDS", []):
                cb.addItem(rid, rid)
            if dflt:
                i = cb.findData(dflt)
                if i >= 0:
                    cb.setCurrentIndex(i)
                else:
                    cb.setCurrentText(dflt)
            cb.currentIndexChanged.connect(self._emit)
            cb.editTextChanged.connect(self._emit)
            self._widgets[key] = ("resource", cb)
            return cb

        if kind == "resource":
            cb = QComboBox()
            cb.setEditable(True)
            cb.addItem("")
            for rid, label in self._resource_items(fs.get("source")):
                cb.addItem(label, rid)
            if dflt:
                i = cb.findData(dflt)
                if i >= 0:
                    cb.setCurrentIndex(i)
                else:
                    cb.setCurrentText(dflt)
            cb.currentIndexChanged.connect(self._emit)
            cb.editTextChanged.connect(self._emit)
            self._widgets[key] = ("resource", cb)
            return cb

        if kind == "enum":
            cb = QComboBox()
            labels = fs.get("labels", {})
            for c in fs.get("choices", []):
                cb.addItem(labels.get(c, c), c)
            if dflt is not None:
                i = cb.findData(dflt)
                if i >= 0:
                    cb.setCurrentIndex(i)
            cb.currentIndexChanged.connect(self._emit)
            self._widgets[key] = ("enum", cb)
            return cb

        if kind == "int":
            sp = QSpinBox()
            sp.setRange(int(fs.get("minimum", 0)),
                        int(fs.get("maximum", 100000)))
            opt = bool(fs.get("optional"))
            if opt:
                # 可选整数用 specialValueText 表示「未填」== 最小值-1
                sp.setMinimum(int(fs.get("minimum", 0)) - 1)
                sp.setSpecialValueText("（不填）")
                sp.setValue(sp.minimum() if dflt is None
                            else int(dflt))
            else:
                sp.setValue(0 if dflt is None else int(dflt))
            sp.valueChanged.connect(self._emit)
            self._widgets[key] = ("int", sp, opt,
                                  int(fs.get("minimum", 0)))
            return sp

        if kind == "float":
            sp = QDoubleSpinBox()
            sp.setRange(float(fs.get("minimum", -100000.0)),
                        float(fs.get("maximum", 100000.0)))
            sp.setDecimals(int(fs.get("decimals", 3)))
            opt = bool(fs.get("optional"))
            if opt:
                # 可选浮点与整数同法：specialValueText 表示「不填」
                # （早先漏了这个分支，可选浮点永远返回 0.0，
                #  导致 playsound/attribute/particle 的默认输出
                #  多出 "0.0" 参数）
                sp.setMinimum(float(fs.get("minimum", -100000.0)) - 1.0)
                sp.setSpecialValueText("（不填）")
                sp.setValue(sp.minimum() if dflt is None
                            else float(dflt))
            else:
                sp.setValue(0.0 if dflt is None else float(dflt))
            sp.valueChanged.connect(self._emit)
            self._widgets[key] = ("float", sp, opt,
                                  float(fs.get("minimum", -100000.0)))
            return sp

        if kind == "bool":
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            cb = QComboBox()
            if fs.get("optional"):
                cb.addItem("（不填）", None)
            cb.addItem("true", True)
            cb.addItem("false", False)
            cb.currentIndexChanged.connect(self._emit)
            lay.addWidget(cb)
            lay.addStretch(1)
            self._widgets[key] = ("enum", cb)
            return row

        if kind == "nbt":
            # NBT 不让用户手写：只读行 + 「编辑…」按钮弹树形编辑器
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            ed = QLineEdit()
            ed.setPlaceholderText("（空）— 点「编辑 NBT…」构造")
            ed.setReadOnly(True)
            ed.setText(dflt or "")
            ed.textChanged.connect(self._emit)
            btn = QPushButton("编辑 NBT…")
            btn.clicked.connect(lambda: self._open_nbt_dialog(key, ed))
            lay.addWidget(ed, 1)
            lay.addWidget(btn)
            self._widgets[key] = ("nbt", ed)
            return row

        # 兜底：text
        ed = QLineEdit()
        ed.setText("" if dflt is None else str(dflt))
        ed.textChanged.connect(self._emit)
        self._widgets[key] = ("text", ed)
        return ed

    def _resource_items(self, source: str | None):
        """按数据源返回 [(id, 显示名)]。

        覆盖所有下拉数据源（含 gen_res3/gen_res4 追加的清单）。
        """
        # (清单 IDS, 中文名 dict) 表驱动
        table = {
            "effect": ("EFFECT_IDS", "EFFECT_CN"),
            "entity": ("ENTITY_IDS", "ENTITY_CN"),
            "biome": ("BIOME_IDS", "BIOME_CN"),
            "sound": ("SOUND_IDS", "SOUND_CN"),
            "instrument": ("INSTRUMENT_IDS", "INSTRUMENT_CN"),
            "jukebox_song": ("JUKEBOX_SONG_IDS", "JUKEBOX_SONG_CN"),
            "trim_material": ("TRIM_MATERIAL_IDS", "TRIM_MATERIAL_CN"),
            "trim_pattern": ("TRIM_PATTERN_IDS", "TRIM_PATTERN_CN"),
            "banner_pattern": ("BANNER_PATTERN_IDS", "BANNER_PATTERN_CN"),
            "potion": ("POTION_IDS", "POTION_CN"),
            "attribute": ("ATTRIBUTE_IDS", "ATTRIBUTE_CN"),
            "damage_type": ("DAMAGE_TYPE_IDS", "DAMAGE_TYPE_CN"),
            "particle": ("PARTICLE_IDS", "PARTICLE_CN"),
            "block": ("BLOCK_IDS", "BLOCK_CN"),
            "loot_table": ("LOOT_TABLE_IDS", None),
        }
        if source == "structure":
            return [(x, SL.struct_label(x)) for x in SL.STRUCT_IDS]
        if source == "poi":
            return [(x, f'{CS.POI_NOTE.get(x, "")}（{x}）'.lstrip("（"))
                    for x in CS.POI_IDS]
        if source == "enchant":
            from Utils.CommandGenerator import comp_editors as CE
            return [(e["id"], f'{e["name"]}（{e["id"]}）')
                    for e in CE.enchants_data()]
        if source == "item":
            return [(x, IL.ITEM_CN.get(x, x)) for x in IL.ITEM_IDS]
        entry = table.get(source)
        if not entry:
            return []
        ids_attr, cn_attr = entry
        ids = getattr(RL, ids_attr, [])
        cn = getattr(RL, cn_attr, {}) if cn_attr else {}
        return [(x, cn.get(x, x)) for x in ids]

    def _emit(self, *_a):
        if not self._busy:
            self.changed.emit()

    def _open_nbt_dialog(self, key, ed):
        """NBT 编辑弹窗（核心：用户不手写 SNBT）。"""
        from Utils.CommandGenerator.nbt_dialog import NbtDialog
        dlg = NbtDialog(ed.text(), title="编辑 NBT", parent=self)
        if dlg.exec():
            ed.setText(dlg.result_text)
            self._emit()

    # ------------------------------------------------------------------
    def params(self) -> dict:
        """收集参数字典（含分支名）。"""
        out = {}
        if self._branch_combo is not None:
            out[self.spec.get("branch_key", "branch")] = self.branch()
        for key, entry in self._widgets.items():
            kind = entry[0]
            if kind == "text":
                out[key] = entry[1].currentText() if hasattr(
                    entry[1], "currentText") else entry[1].text()
            elif kind == "nbt":
                out[key] = entry[1].text()
            elif kind == "block_res":
                cb = entry[1]
                rid = cb.currentData()
                txt = cb.currentText().strip()
                if "（" in txt and txt.endswith("）"):
                    rid = txt.split("（")[-1][:-1]
                elif txt and cb.findText(txt) < 0:
                    rid = txt
                out[key] = rid
            elif kind == "resource":
                cb = entry[1]
                rid = cb.currentData()
                txt = cb.currentText().strip()
                # 用户手输时以文本为准（去掉「中文（id）」外壳）
                if "（" in txt and txt.endswith("）"):
                    rid = txt.split("（")[-1][:-1]
                elif txt and cb.findText(txt) < 0:
                    rid = txt
                out[key] = rid
            elif kind == "enum":
                out[key] = entry[1].currentData()
            elif kind == "int":
                _k, sp, opt, lo = entry
                out[key] = None if (opt and sp.value() < lo) \
                    else sp.value()
            elif kind == "float":
                _k, sp, opt, lo = entry
                out[key] = None if (opt and sp.value() < lo) \
                    else sp.value()
        # 文本类空值归一为 None 还是 ""：由 spec 的 optional 决定
        for fs in self._fields:
            k = fs["key"]
            if k in out and isinstance(out[k], str):
                if not out[k].strip():
                    out[k] = None if fs.get("optional") else ""
        return out

    def reset(self):
        self._rebuild()
        self.changed.emit()
