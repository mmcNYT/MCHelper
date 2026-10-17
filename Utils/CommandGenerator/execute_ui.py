# -*- coding: utf-8 -*-
"""execute 链式构建器控件。

execute 是**管道**语法：任意数量的子命令按序连接，以 run 收尾。
故 UI 用「行列表」而非「面包屑 + 表单」：
  - 每行 = 一个子命令（分组下拉）+ 该行专属参数控件
  - 行可上移/下移/删除
  - 底部「+ 添加子命令」

切换某行的子命令时，该行的参数控件**动态重建**（不同子命令参数不同）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from Utils.CommandGenerator import execute_cmd as X
from Utils.CommandGenerator import item_list as IL
from Utils.CommandGenerator import resource_lists as RL
from Utils.CommandGenerator import struct_list as SL

# 每个 op 的参数定义：[(key, label, kind, extra)]
# kind: text / targets / pos / int / float / enum / resource / item
OP_ARGS = {
    "as": [("targets", "目标", "targets", {})],
    "at": [("targets", "目标", "targets", {})],
    "positioned": [("pos", "坐标", "pos", {})],
    "positioned_as": [("targets", "目标", "targets", {})],
    "positioned_over": [("heightmap", "高度图", "enum",
                         {"choices": ["world_surface", "ocean_floor",
                                      "motion_blocking",
                                      "motion_blocking_no_leaves"]})],
    "rotated": [("rot", "旋转(yaw pitch)", "text",
                 {"placeholder": "如 0 90"})],
    "rotated_as": [("targets", "目标", "targets", {})],
    "facing_entity": [("anchor", "锚点", "enum",
                       {"choices": ["eyes", "feet"]}),
                      ("targets", "目标实体", "targets", {})],
    "facing_pos": [("pos", "坐标", "pos", {})],
    "align": [("axes", "轴向组合", "enum",
               {"choices": ["x", "y", "z", "xy", "xz", "yz", "xyz"]})],
    "anchored": [("anchor", "锚点", "enum",
                  {"choices": ["eyes", "feet"]})],
    "in": [("dimension", "维度", "enum",
            {"choices": ["overworld", "the_nether", "the_end"]})],
    "summon": [("entity", "实体", "resource", {"source": "entity"})],
    "on": [("relation", "关联", "enum",
            {"choices": ["vehicle", "controller", "leasher", "owner",
                         "passengers", "target", "attacker", "origin"]})],
    # 条件
    "if_block": [("pos", "坐标", "pos", {}),
                 ("block", "方块", "block", {})],
    "if_blocks": [("start", "起点", "pos", {}),
                  ("end", "终点", "pos", {}),
                  ("destination", "目标点", "pos", {}),
                  ("source_dimension", "源维度", "enum",
                   {"choices": ["overworld", "the_nether", "the_end"],
                    "optional": True}),
                  ("target_dimension", "目标维度", "enum",
                   {"choices": ["overworld", "the_nether", "the_end"],
                    "optional": True}),
                  ("mode", "模式", "enum",
                   {"choices": ["all", "masked"], "optional": True})],
    "if_biome": [("pos", "坐标", "pos", {}),
                 ("biome", "群系", "resource", {"source": "biome"})],
    "if_entity": [("targets", "实体", "targets", {})],
    "if_data": [("kind", "类型", "enum",
                 {"choices": ["entity", "block", "storage"]}),
                ("target", "实体", "targets", {"optional": True,
                 "show_when": ("kind", ["entity"])}),
                ("pos", "坐标", "pos", {"optional": True,
                 "show_when": ("kind", ["block"])}),
                ("source", "storage id", "text", {"optional": True,
                 "show_when": ("kind", ["storage"]),
                 "placeholder": "如 mystorage"}),
                ("path", "NBT 路径", "text",
                 {"placeholder": "如 Health 或 Items[0].id"})],
    "if_items": [("kind", "类型", "enum",
                  {"choices": ["entity", "block"]}),
                 ("target", "实体", "targets", {"optional": True,
                  "show_when": ("kind", ["entity"])}),
                 ("pos", "坐标", "pos", {"optional": True,
                  "show_when": ("kind", ["block"])}),
                 ("slots", "槽位", "text",
                  {"default": "weapon.mainhand",
                   "placeholder": "如 weapon.mainhand 或 container.0"}),
                 ("item_predicate", "物品谓词", "text",
                 {"placeholder": "如 minecraft:diamond"})],
    "if_predicate": [("predicate", "谓词 id", "text",
                      {"placeholder": "如 minecraft:custom/pred"})],
    "if_function": [("name", "函数", "text",
                     {"placeholder": "如 minecraft:custom/func"})],
    "if_score": [("target", "目标", "text", {"default": "@s"}),
                 ("objective", "目标名", "text", {"default": "obj1"}),
                 ("op", "比较", "enum",
                  {"choices": ["matches", "<", "<=", "=", ">=", ">"]}),
                 ("range", "范围/值", "text", {"default": "1..",
                  "placeholder": "如 5、1..10、..3"})],
    "if_loaded": [("pos", "坐标", "pos", {})],
    "if_dimension": [("dimension", "维度", "enum",
                      {"choices": ["overworld", "the_nether",
                                   "the_end"]})],
    "if_stopwatch": [("id", "秒表 id", "text",
                      {"placeholder": "如 stopwatch:main"}),
                     ("range", "范围", "text", {"default": "1..",
                      "placeholder": "如 5、1..10、..3"})],
    "store": [("result", "存什么", "enum",
               {"choices": ["result", "success"]}),
              ("store_target", "存到", "enum",
               {"choices": ["score", "bossbar", "entity", "block",
                            "storage"]}),
              # 以下按 store_target 条件显示 —— 否则 10 个参数挤一行
              ("target", "实体/记分持有者", "text",
               {"default": "@s", "show_when": ("store_target",
                                               ["score", "entity"])}),
              ("objective", "记分目标名", "text",
               {"default": "obj1", "show_when": ("store_target",
                                                 ["score"])}),
              ("id", "bossbar id", "text",
               {"default": "boss1", "show_when": ("store_target",
                                                  ["bossbar"])}),
              ("pos", "坐标（block）", "pos",
               {"show_when": ("store_target", ["block"])}),
              ("source", "storage id", "text",
               {"show_when": ("store_target", ["storage"])}),
              ("path", "NBT 路径", "text",
               {"show_when": ("store_target",
                              ["entity", "block", "storage"]),
                "placeholder": "留空自动：Health / Items / value"}),
              ("dtype", "数据类型", "enum",
               {"choices": ["int", "float", "short", "long", "double",
                            "byte"],
                "show_when": ("store_target",
                              ["entity", "block", "storage"])}),
              ("scale", "倍率", "text",
               {"default": "1.0",
                "show_when": ("store_target",
                              ["entity", "block", "storage"])})],
    "run": [("cmd", "要执行的指令", "text", {"default": "say hi"})],
}

# 条件类 op 展开：if_/unless_ 共用同一套参数定义
for _op in list(OP_ARGS):
    if _op.startswith("if_"):
        OP_ARGS["unless_" + _op[3:]] = OP_ARGS[_op]


def _resource_items(source):
    from Utils.CommandGenerator import item_filter as IF
    m = {
        "entity": lambda: [(x, RL.ENTITY_CN.get(x, x))
                           for x in RL.ENTITY_IDS],
        "biome": lambda: [(x, RL.BIOME_CN.get(x, x))
                          for x in RL.BIOME_IDS],
        "dimension": lambda: [("overworld", "主世界"),
                              ("the_nether", "下界"),
                              ("the_end", "末地")],
        # 物品：过滤后的真实 id（ITEM_IDS 含 928 个翻译键条目）
        "item": IF.item_items,
    }
    fn = m.get(source)
    return fn() if fn else []


class ChainRow(QWidget):
    """链中的一行。"""

    changed = Signal()
    remove_requested = Signal(object)
    move_requested = Signal(object, int)

    def __init__(self, op="as", args=None, index=1, parent=None):
        super().__init__(parent)
        self.op = op
        self._widgets = {}
        self._field_widgets = {}
        self._controllers = set()
        self._hidden = set()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(6)

        self.no_label = QLabel(f"{index}")
        self.no_label.setFixedWidth(22)
        self.no_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.no_label)

        self.combo = QComboBox()
        self.combo.setMinimumWidth(190)
        for gname, ops in X.OP_GROUPS:
            for val, label in ops:
                self.combo.addItem(f"{gname}｜{label}", val)
        i = self.combo.findData(op)
        if i >= 0:
            self.combo.setCurrentIndex(i)
        self.combo.currentIndexChanged.connect(self._on_op_changed)
        lay.addWidget(self.combo)

        self.param_host = QWidget()
        self.param_lay = QHBoxLayout(self.param_host)
        self.param_lay.setContentsMargins(0, 0, 0, 0)
        self.param_lay.setSpacing(6)
        lay.addWidget(self.param_host, 1)

        for sym, delta in (("↑", -1), ("↓", 1)):
            b = QPushButton(sym)
            b.setFixedWidth(30)
            b.clicked.connect(
                lambda _=False, d=delta: self.move_requested.emit(self, d))
            lay.addWidget(b)
        rm = QPushButton("✕")
        rm.setFixedWidth(30)
        rm.clicked.connect(lambda: self.remove_requested.emit(self))
        lay.addWidget(rm)

        self._build_params(args or {})

    def set_index(self, i):
        self.no_label.setText(str(i))

    def _on_op_changed(self):
        self.op = self.combo.currentData()
        self._build_params({})
        self.changed.emit()

    def _on_control_changed(self):
        """控制字段（被 show_when 引用）变更 -> 只切可见性。

        **不重建控件** —— 重建会销毁用户正在编辑的控件（焦点丢失、
        外部持有的引用变悬空），实测切换 store_target 后从 score 到
        block 完全失效。改为创建全部字段、只 show/hide。
        """
        self._apply_visibility()
        self.changed.emit()

    def _clear_params(self):
        while self.param_lay.count():
            it = self.param_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._widgets.clear()
        self._field_widgets = {}

    def _build_params(self, args):
        self._clear_params()
        specs = OP_ARGS.get(self.op, [])
        # 「控制字段」= 被 show_when 引用的字段
        self._controllers = {sp[3]["show_when"][0] for sp in specs
                             if "show_when" in sp[3]}
        for key, label, kind, extra in specs:
            lab = QLabel(label)
            w = self._make_widget(key, kind, extra, args.get(key))
            self.param_lay.addWidget(lab)
            self.param_lay.addWidget(w)
            # 记录 label+widget 以便整对隐藏
            self._field_widgets[key] = (lab, w, extra)
        self.param_lay.addStretch(1)
        self._apply_visibility()

    def _apply_visibility(self):
        """按 show_when 显示/隐藏字段（label 与控件一起）。

        同时把结果记进 `self._hidden` —— **不能用 isVisible() 判断**
        「是否被条件隐藏」：控件所在页或祖先未显示时 isVisible() 也为
        False，会把所有字段误判为隐藏（实测导致 args 全被丢弃、
        只剩默认值）。
        """
        cur = self._current_args()
        self._hidden = set()
        for key, (lab, w, extra) in self._field_widgets.items():
            sw = extra.get("show_when")
            vis = True
            if sw:
                ctrl_key, allowed = sw
                vis = cur.get(ctrl_key) in allowed
            lab.setVisible(vis)
            w.setVisible(vis)
            if not vis:
                self._hidden.add(key)

    def _visible(self, extra, args) -> bool:
        """按 show_when 判断该参数是否应显示。"""
        sw = extra.get("show_when")
        if not sw:
            return True
        ctrl_key, allowed = sw
        cur = args.get(ctrl_key)
        if cur is None:
            # 未显式给值时，取控制控件当前值
            entry = self._widgets.get(ctrl_key)
            cur = entry[1].currentData() if entry else None
        return cur in allowed

    def _current_args(self) -> dict:
        """已建控件当前值的快照（供重建时保留用户输入）。"""
        out = {}
        for key, (kind, w) in self._widgets.items():
            if kind == "enum":
                out[key] = w.currentData()
            elif kind == "resource":
                out[key] = w.currentData()
            elif kind == "target_sel":
                out[key] = w.text()
            elif kind == "text":
                out[key] = (w.currentText() if hasattr(w, "currentText")
                            else w.text())
        return out

    def _make_widget(self, key, kind, extra, value):
        default = extra.get("default")
        if kind == "text":
            w = QLineEdit()
            w.setMinimumWidth(120)
            w.setText(str(value) if value is not None
                      else (default or ""))
            if extra.get("placeholder"):
                w.setPlaceholderText(extra["placeholder"])
            w.textChanged.connect(lambda *_: self.changed.emit())
            self._widgets[key] = ("text", w)
            return w
        if kind == "pos":
            w = QComboBox()
            w.setEditable(True)
            w.addItems(["~ ~ ~", "~ ~ ~1", "~ ~-1 ~", "0 64 0"])
            w.setCurrentText(str(value) if value is not None
                             else (default or "~ ~ ~"))
            w.currentTextChanged.connect(lambda *_: self.changed.emit())
            self._widgets[key] = ("text", w)
            return w
        if kind == "targets":
            # 统一弹窗编辑（与通用表单同一 TargetSelectorField）
            from Utils.CommandGenerator.target_selector_ui import (
                TargetSelectorField)
            w = TargetSelectorField(
                str(value) if value is not None
                else (default or "@s"))
            w.changed.connect(lambda *_: self.changed.emit())
            self._widgets[key] = ("target_sel", w)
            return w
        if kind == "enum":
            w = QComboBox()
            choices = extra.get("choices", [])
            if extra.get("optional"):
                w.addItem("（不填）", "")
            for c in choices:
                w.addItem(c, c)
            if value is None and default:
                value = default
            i = w.findData(value)
            w.setCurrentIndex(i if i >= 0 else 0)
            # 控制字段（被 show_when 引用）变更时重建参数行
            if key in getattr(self, "_controllers", ()):
                w.currentIndexChanged.connect(
                    lambda *_: self._on_control_changed())
            else:
                w.currentIndexChanged.connect(
                    lambda *_: self.changed.emit())
            self._widgets[key] = ("enum", w)
            return w
        if kind == "block":
            w = QComboBox()
            w.setEditable(True)
            for bid in RL.BLOCK_IDS:
                cn = RL.BLOCK_CN.get(bid, bid)
                w.addItem(f"{cn}（{bid}）" if cn != bid else bid, bid)
            i = w.findData(value if value is not None
                           else (default or "stone"))
            w.setCurrentIndex(i if i >= 0 else 0)
            w.currentIndexChanged.connect(lambda *_: self.changed.emit())
            w.editTextChanged.connect(lambda *_: self.changed.emit())
            self._widgets[key] = ("resource", w)
            # 可搜索：1053 个方块靠输入子串过滤
            from Utils.CommandGenerator.combo_complete import attach_search
            attach_search(w)
            return w
        if kind == "resource":
            w = QComboBox()
            w.setEditable(True)
            src = extra.get("source")
            from PySide6.QtGui import QIcon
            from Utils.CommandGenerator.entity_icons import (
                entity_icon_path)
            for rid, label in _resource_items(src):
                text = f"{label}（{rid}）" if label != rid else rid
                # 实体源加图标
                ip = entity_icon_path(rid) if src == "entity" else None
                if ip:
                    w.addItem(QIcon(ip), text, rid)
                else:
                    w.addItem(text, rid)
            i = w.findData(value)
            w.setCurrentIndex(i if i >= 0 else 0)
            w.currentIndexChanged.connect(lambda *_: self.changed.emit())
            w.editTextChanged.connect(lambda *_: self.changed.emit())
            self._widgets[key] = ("resource", w)
            # 可搜索：实体/群系/物品等大清单靠输入子串过滤
            from Utils.CommandGenerator.combo_complete import attach_search
            attach_search(w)
            return w
        # 兜底
        w = QLineEdit()
        w.setText("" if value is None else str(value))
        w.textChanged.connect(lambda *_: self.changed.emit())
        self._widgets[key] = ("text", w)
        return w

    def params(self) -> dict:
        """本行 -> {"op": ..., "args": {...}}。

        **隐藏的字段不进入参数**（否则 store 会同时写出 objective 与
        path 等互斥参数）。判据用控件实际可见性，与 UI 所见一致。
        """
        out = {}
        for key, entry in self._widgets.items():
            kind = entry[0]
            w = entry[1]
            # 被 show_when 隐藏 -> 跳过（用显式集合，不用 isVisible()）
            if key in self._hidden:
                continue
            if kind == "text":
                v = w.currentText() if hasattr(w, "currentText") \
                    else w.text()
                v = v.strip()
            elif kind == "target_sel":
                v = w.text()
            elif kind == "enum":
                v = w.currentData()
            elif kind == "resource":
                v = w.currentData()
                txt = w.currentText().strip()
                if "（" in txt and txt.endswith("）"):
                    v = txt.split("（")[-1][:-1]
                elif txt and w.findText(txt) < 0:
                    v = txt
            else:
                v = None
            if v not in (None, ""):
                out[key] = v
        # 兜底：可见性未被跟踪时（理论上不会）仍按条件过滤一遍
        specs = OP_ARGS.get(self.op, [])
        for key, _label, _kind, extra in specs:
            if key in out and not self._visible(extra, out):
                out.pop(key, None)
        return {"op": self.op, "args": out}


class ExecuteChainBuilder(QWidget):
    """execute 的链式构建器（整体）。"""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        hint = QLabel(
            "execute 是管道式指令：按顺序添加子命令，最后以 run 收尾。"
            "例如：as @a → at @s → run say hi")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;")
        lay.addWidget(hint)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.host = QWidget()
        self.host_lay = QVBoxLayout(self.host)
        self.host_lay.setContentsMargins(0, 0, 0, 0)
        self.host_lay.setSpacing(2)
        self.scroll.setWidget(self.host)
        lay.addWidget(self.scroll, 1)

        brow = QHBoxLayout()
        add = QPushButton("+ 添加子命令")
        add.clicked.connect(lambda: self.add_row())
        brow.addWidget(add)
        clear = QPushButton("清空")
        clear.clicked.connect(self.clear_rows)
        brow.addWidget(clear)
        brow.addStretch(1)
        lay.addLayout(brow)

        # 默认给一条**可直接用**的最小链：as @s -> run say hi
        # （早先只加 as，缺 run 会立刻报「缺少收尾的 run」）
        self.add_row("as")
        self.add_row("run")

    # ---- 行管理 ----
    def add_row(self, op="as", args=None, after=None):
        row = ChainRow(op, args, len(self._rows) + 1)
        row.changed.connect(self._on_row_changed)
        row.remove_requested.connect(self._remove_row)
        row.move_requested.connect(self._move_row)
        if after is not None and after in self._rows:
            idx = self._rows.index(after) + 1
            self._rows.insert(idx, row)
            self.host_lay.insertWidget(idx, row)
        else:
            self._rows.append(row)
            self.host_lay.addWidget(row)
        self._renumber()
        self.changed.emit()
        return row

    def _remove_row(self, row):
        if row in self._rows:
            self._rows.remove(row)
            self.host_lay.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._renumber()
        self.changed.emit()

    def _move_row(self, row, delta):
        if row not in self._rows:
            return
        i = self._rows.index(row)
        j = i + delta
        if not (0 <= j < len(self._rows)):
            return
        self._rows[i], self._rows[j] = self._rows[j], self._rows[i]
        # 重排控件
        for k, r in enumerate(self._rows):
            self.host_lay.removeWidget(r)
            self.host_lay.insertWidget(k, r)
        self._renumber()
        self.changed.emit()

    def _renumber(self):
        for i, r in enumerate(self._rows, 1):
            r.set_index(i)

    def clear_rows(self):
        for r in list(self._rows):
            self.host_lay.removeWidget(r)
            r.setParent(None)
            r.deleteLater()
        self._rows.clear()
        self.changed.emit()

    def _on_row_changed(self):
        self.changed.emit()

    # ---- 值 ----
    def chains(self) -> list:
        return [r.params() for r in self._rows]

    def set_chains(self, chains):
        self.clear_rows()
        for ch in chains or []:
            self.add_row(ch.get("op", "as"), ch.get("args"))
        self.changed.emit()
