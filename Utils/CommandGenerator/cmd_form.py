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
                    # 可空标注在控件 placeholder（_mark_optional），
                    # 不再占用标签文字
                    self._mark_optional(w)
                self._form.addRow(label, w)
                if fs.get("hint"):
                    h = QLabel(fs["hint"])
                    h.setWordWrap(True)
                    h.setStyleSheet("color: #888; font-size: 11px;")
                    self._form.addRow("", h)
            self._apply_visibility()
        finally:
            self._busy = False

    # ------------------------------------------------------------------
    def _mark_optional(self, w):
        """可空字段的值控件打 placeholder「（可空）…」。

        - QLineEdit / 可编辑 QComboBox：已有 placeholder 则**前缀**
          「（可空）」，没有则直接设；不覆盖提示语义。
          QComboBox 的 setPlaceholderText 只影响**未编辑时**的显示，
          可编辑下拉实际输入框是 lineEdit() —— 两处都设。
        - QSpinBox/QDoubleSpinBox：specialValueText「（不填）」机制
          已表达可空，不动。
        - TargetSelectorField 等容器：findChildren 下钻其内部
          QLineEdit/QComboBox 再标。
        """
        self._mark_optional_r(w, "（可空）")

    @staticmethod
    def _mark_optional_r(w, mark):
        from PySide6.QtWidgets import QComboBox
        targets = [w]
        # 容器（如 TargetSelectorField）下钻一层可输入控件
        targets += w.findChildren(QLineEdit)
        targets += [c for c in w.findChildren(QComboBox)
                    if c.isEditable()]
        for t in targets:
            if isinstance(t, QLineEdit):
                cur = t.placeholderText()
                if mark not in cur:
                    t.setPlaceholderText(f"{mark}{cur}" if cur else mark)
            elif isinstance(t, QComboBox) and t.isEditable():
                if hasattr(t, "setPlaceholderText"):   # Qt6 combo API
                    cur = t.placeholderText()
                    if mark not in cur:
                        t.setPlaceholderText(f"{mark}{cur}" if cur else mark)
                le = t.lineEdit()
                if le is not None:
                    cur = le.placeholderText()
                    if mark not in cur:
                        le.setPlaceholderText(
                            f"{mark}{cur}" if cur else mark)

    def _controller_values(self) -> dict:
        """被 show_when 引用的控制字段当前值快照。"""
        out = {}
        for fs in self._fields:
            sw = fs.get("show_when")
            if sw:
                ctrl = sw[0]
                entry = self._widgets.get(ctrl)
                if entry and entry[0] == "enum":
                    out[ctrl] = entry[1].currentData()
        return out

    def _apply_visibility(self):
        """按 show_when 显隐字段（label 行与 hint 行一起）。

        同 execute_ui 的机制：**不能用 isVisible()** 判断「是否被条件
        隐藏」—— 页未显示时全 False；必须显式记隐藏集合。
        QFormLayout 的行没有独立 widget，需 labelForField 定位行号。
        """
        cur = self._controller_values()
        self._hidden = set()
        # 行号 -> 字段映射（label/hint 各占一行）
        row_of = {}
        row = 0
        for fs in self._fields:
            row_of[row] = fs          # 字段行
            n = 1
            if fs.get("hint"):
                n = 2                 # hint 占额外一行
            row += n
        for fs in self._fields:
            sw = fs.get("show_when")
            if not sw:
                continue
            ctrl, allowed = sw
            if cur.get(ctrl) not in allowed:
                self._hidden.add(fs["key"])
        # 批量显隐（用 QFormLayout 的 setRowVisible）
        form = self._form
        for r, fs in row_of.items():
            key = fs["key"]
            vis = key not in self._hidden
            if hasattr(form, "setRowVisible"):
                form.setRowVisible(r, vis)

    def _on_control_changed(self):
        """控制字段变更 -> 只重算显隐，不重建控件。"""
        self._apply_visibility()
        self._emit()

    # ------------------------------------------------------------------
    def _make_widget(self, fs: dict) -> QWidget:
        kind = fs["kind"]
        key = fs["key"]
        dflt = fs.get("default")

        if kind == "targets":
            # 统一弹窗编辑：表单里只占一行（只读行 + 编辑按钮），
            # 复杂选择器在弹窗里构造（与 NBT 字段同一模式）。
            from Utils.CommandGenerator.target_selector_ui import (
                TargetSelectorField)
            w = TargetSelectorField(dflt or "")
            w.changed.connect(self._emit)
            self._widgets[key] = ("target_selector", w)
            return w

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
            # 可搜索：1053 个方块靠输入子串过滤
            from Utils.CommandGenerator.combo_complete import attach_search
            attach_search(cb)
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
            # 可搜索：119 个战利品表靠输入子串过滤
            from Utils.CommandGenerator.combo_complete import attach_search
            attach_search(cb)
            return cb

        if kind == "resource":
            cb = QComboBox()
            cb.setEditable(True)
            cb.addItem("")
            src = fs.get("source")
            for rid, label in self._resource_items(src):
                # 实体源加图标（assets/CommandGenerator/entities）
                if src == "entity":
                    from Utils.CommandGenerator.entity_icons import (
                        entity_icon_path)
                    from PySide6.QtGui import QIcon
                    ip = entity_icon_path(rid)
                    if ip:
                        cb.addItem(QIcon(ip), label, rid)
                        continue
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
            # 可搜索：实体/群系/声音/结构等大清单靠输入子串过滤
            from Utils.CommandGenerator.combo_complete import attach_search
            attach_search(cb)
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
            # 被其他字段的 show_when 引用 -> 变更时重算显隐
            controllers = {f.get("show_when", (None,))[0]
                            for f in self._fields
                            if f.get("show_when")}
            if key in controllers:
                cb.currentIndexChanged.connect(
                    lambda *_: self._on_control_changed())
            else:
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
            from Utils.CommandGenerator import item_filter as IF
            return IF.item_items()
        if source == "sound":
            # 音效译名：官方来自 zh_cn.json 的 subtitles.*（音效无直接
            # lang 条目），sound_cn.py 由 gen_sound_assets.py 生成
            from Utils.CommandGenerator.sound_cn import SOUND_CN
            return [(x, SOUND_CN.get(x, x)) for x in RL.SOUND_IDS]
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
        """收集参数字典（含分支名）。

        **被 show_when 隐藏的字段不进参数**（否则序列化会带上
        与当前子分支矛盾的默认值）。
        """
        out = {}
        if self._branch_combo is not None:
            out[self.spec.get("branch_key", "branch")] = self.branch()
        for key, entry in self._widgets.items():
            if key in getattr(self, "_hidden", ()):
                continue          # 子分支隐藏的字段跳过
            kind = entry[0]
            if kind == "text":
                out[key] = entry[1].currentText() if hasattr(
                    entry[1], "currentText") else entry[1].text()
            elif kind == "nbt":
                out[key] = entry[1].text()
            elif kind == "target_selector":
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
