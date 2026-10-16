# -*- coding: utf-8 -*-
"""NBT 编辑对话框：树形键值编辑 + SNBT 文本双向同步。

设计目标（用户「只用动手指」）：
  - 左：树形编辑器。根是复合 {}，可添加/删除/改类型；值类型从下拉选
    （byte/short/int/long/float/double/string/byteArray/intArray/
     longArray/list/compound），字符串值直接填，复合/列表双击进入
    子层编辑
  - 右上：SNBT 原文（只读回显，随树同步）
  - 右下：SNBT 粘贴区 -> 「解析到树」

实现说明：SNBT 解析用**简化递归下降**（覆盖 {k:v,...} / [a,b,...] /
标量带后缀 / 引号字符串），足以处理 give 相关的实体与方块实体 NBT；
不追求完整 NBT 规范（嵌套深度与转义较罕见）。
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QSplitter,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget, QLineEdit, QPlainTextEdit,
                               QFileDialog)

# ---------------------------------------------------------------------------
# SNBT 解析（简化递归下降）
# ---------------------------------------------------------------------------

class _SNBTParser:
    """SNBT -> Python 结构（dict/list/带类型标记的标量）。

    标量带类型标记：返回 (kind, value)，kind ∈
      int/long/float/double/byte/short/string/bool
    """

    def __init__(self, text: str):
        self.s = text.strip()
        self.i = 0

    def parse(self):
        v = self._value()
        return v

    def _skip_ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t\r\n":
            self.i += 1

    def _value(self):
        self._skip_ws()
        if self.i >= len(self.s):
            return None
        c = self.s[self.i]
        if c == "{":
            return self._compound()
        if c == "[":
            return self._list()
        return self._scalar()

    def _compound(self):
        out = {}
        self.i += 1                      # {
        while True:
            self._skip_ws()
            if self.i >= len(self.s):
                # 未闭合：必须在「文本耗尽」时报错，否则 {a:1 会被
                # 静默当成 {a:1}（实测导致坏输入不报错）
                raise ValueError("复合标签未闭合（缺少 }）")
            if self.s[self.i] == "}":
                self.i += 1
                break
            # 键
            m = re.match(r'("?)([A-Za-z0-9_.\-+/]+)\1\s*:\s*',
                         self.s[self.i:])
            if not m:
                raise ValueError(
                    f"第 {self.i} 字符附近无法解析键：…{self.s[self.i:self.i + 24]}")
            key = m.group(2)
            self.i += m.end()
            out[key] = self._value()
            self._skip_ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
        return out

    def _list(self):
        out = []
        self.i += 1                      # [
        # 数组后缀 [B; ...] / [I; ...] / [L; ...]
        self._skip_ws()
        arr = None
        m = re.match(r'([BIL])\s*;\s*', self.s[self.i:])
        if m:
            arr = m.group(1)
            self.i += m.end()
        while True:
            self._skip_ws()
            if self.i >= len(self.s):
                break
            if self.s[self.i] == "]":
                self.i += 1
                break
            v = self._value()
            out.append(v)
            self._skip_ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
        if arr:
            # [I;..] -> intarray / [B;..] -> bytearray / [L;..] -> longarray
            return ({"B": "bytearray", "I": "intarray",
                     "L": "longarray"}[arr], out)
        return out

    def _scalar(self):
        rest = self.s[self.i:]
        # 引号字符串
        q = rest[0]
        if q in "\"'":
            j = 1
            buf = []
            while j < len(rest):
                if rest[j] == "\\" and j + 1 < len(rest):
                    buf.append(rest[j + 1])
                    j += 2
                    continue
                if rest[j] == q:
                    break
                buf.append(rest[j])
                j += 1
            self.i += j + 1
            return ("string", "".join(buf))
        # 数字（带类型后缀）
        #
        # 关键：**先匹配后缀再定类型**，且无后缀的裸数字按「含小数点
        # -> double，否则 int」。早先的正则让后缀判断落到
        # rest[m.end()-1]（可能是逗号/闭括号），导致无后缀整数被
        # 误判为 byte（实测 {a:1} -> ('byte',1)、Pos:[1.5,2,3] 全变
        # byte）。
        m = re.match(
            r'(-?(?:[0-9]+\.?[0-9]*|\.[0-9]+))([bBsSlLfFdD])?'
            r'(?=[,\]\}\s]|$)', rest)
        if m:
            num, sfx = m.group(1), m.group(2) or ""
            self.i += m.end()
            # 注意：**必须用 == 判断后缀，不能用 in** —— 空后缀 ""
            # 是任何字符串的子串，`"" in "bB"` 为 True，会让无后缀
            # 整数全部落进 byte 分支（实测 {a:1} -> ('byte',1)）。
            if sfx == "b" or sfx == "B":
                return ("byte", int(float(num)))
            if sfx == "s" or sfx == "S":
                return ("short", int(float(num)))
            if sfx == "l" or sfx == "L":
                return ("long", int(float(num)))
            if sfx == "f" or sfx == "F":
                return ("float", float(num))
            if sfx == "d" or sfx == "D" or "." in num:
                return ("double", float(num))
            return ("int", int(num))
        # 裸词（true/false/字符串）
        m = re.match(r'([A-Za-z_][A-Za-z0-9_.\-+]*)', rest)
        if m:
            self.i += m.end()
            t = m.group(1)
            if t == "true":
                return ("byte", 1)
            if t == "false":
                return ("byte", 0)
            return ("string", t)
        self.i += 1
        return ("string", rest[:1])


def parse_snbt(text: str):
    """SNBT 文本 -> Python 结构。失败抛 ValueError。"""
    p = _SNBTParser(text)
    v = p.parse()
    p._skip_ws()
    if p.i < len(p.s):
        raise ValueError(f"第 {p.i} 个字符附近无法解析：…{p.s[p.i:p.i + 24]}")
    return v


# ---------------------------------------------------------------------------
# Python 结构 -> 树
# ---------------------------------------------------------------------------

def scalar_kind_of(v) -> str:
    """从 Python 值猜 SNBT 类型名。"""
    if isinstance(v, bool):
        return "byte"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "double"
    return "string"


def to_tree_items(struct, parent_item, key=""):
    """递归填充 QTreeWidget。struct 为 dict/list/(kind,value)。"""
    if isinstance(struct, dict):
        node = QTreeWidgetItem(parent_item, [key or "{}", "compound", ""])
        for k, v in struct.items():
            to_tree_items(v, node, k)
        node.setExpanded(True)
        return
    if isinstance(struct, list):
        kind = "list"
        if struct and isinstance(struct[0], tuple) and \
                str(struct[0][0]).endswith("array"):
            kind = struct[0][0]
        node = QTreeWidgetItem(parent_item, [key or "[]", kind, ""])
        for idx, v in enumerate(struct):
            to_tree_items(v, node, str(idx))
        return
    if isinstance(struct, tuple) and len(struct) == 2 and \
            isinstance(struct[0], str):
        kind, val = struct
        if kind.endswith("array"):
            # [I;..]/[B;..]/[L;..] 是**数组节点**（有子项），不能当
            # 标量叶子 —— 早先落进第 216 行的标量分支，把整个列表
            # str() 塞进值列，回写变成字符串。
            node = QTreeWidgetItem(parent_item, [key or "[]", kind, ""])
            for idx, v in enumerate(val):
                to_tree_items(v, node, str(idx))
            node.setExpanded(True)
            return
        QTreeWidgetItem(parent_item, [key or "", kind, str(val)])
        return
    # 无类型标量
    QTreeWidgetItem(parent_item, [key or "", scalar_kind_of(struct),
                                  str(struct)])


# ---------------------------------------------------------------------------
# 树 -> SNBT
# ---------------------------------------------------------------------------

_NUM_SUFFIX = {"byte": "b", "short": "s", "long": "L", "float": "f",
               "double": "d"}


def _esc(s: str) -> str:
    return ('"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"')


def tree_to_snbt(item: QTreeWidgetItem) -> str:
    kind = (item.text(1) or "string").strip()
    children = [item.child(i) for i in range(item.childCount())]
    if kind == "compound":
        parts = []
        for ch in children:
            k = ch.text(0).strip()
            if not k:
                continue
            parts.append(f"{k}:{tree_to_snbt(ch)}")
        return "{" + ",".join(parts) + "}"
    # 数组类型（kind 由 to_tree_items 写为小写 intarray/bytearray/
    # longarray）。早先用 startswith("intArray")（驼峰）匹配，
    # 与实际 kind 不一致 -> 数组被当空标量输出 ""。
    if kind in ("intarray", "bytearray", "longarray"):
        parts = [tree_to_snbt(ch) for ch in children]
        pre = {"bytearray": "[B;", "intarray": "[I;",
               "longarray": "[L;"}[kind]
        return pre + ",".join(parts) + "]"
    if kind == "list" or kind.startswith("list"):
        parts = [tree_to_snbt(ch) for ch in children]
        return "[" + ",".join(parts) + "]"
    # 标量
    val = item.text(2).strip()
    if kind == "string":
        return _esc(val)
    if kind in _NUM_SUFFIX:
        try:
            float(val)
        except ValueError:
            return _esc(val)
        if kind in ("byte", "short", "long"):
            iv = int(float(val))
            return f"{iv}{_NUM_SUFFIX[kind]}"
        return f"{float(val)}{_NUM_SUFFIX[kind]}"
    if kind == "int":
        # int 无后缀（SNBT 规范：裸整数即 int）。早先漏了这一分支，
        # int 值落到兜底 _esc() 变成字符串 "1"。
        try:
            int(val)
        except ValueError:
            return _esc(val)
        return val
    # bool（树里以 byte 表示）与未知类型
    return _esc(val)


# ---------------------------------------------------------------------------
# 对话框
# ---------------------------------------------------------------------------

VALUE_KINDS = ["compound", "list", "byte", "short", "int", "long",
               "float", "double", "string"]


class NbtDialog(QDialog):
    """NBT 编辑对话框。"""

    def __init__(self, initial: str = "", title="编辑 NBT", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(860, 560)
        self._build()
        if initial.strip():
            self.load_text(initial)
        # 结果
        self.result_text = ""

    # ---- 构建 ----
    def _build(self):
        lay = QVBoxLayout(self)
        split = QSplitter(Qt.Orientation.Horizontal)
        lay.addWidget(split, 1)

        # 左：树
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("结构（右键或下方按钮增删）"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["键", "类型", "值"])
        self.tree.setColumnWidth(0, 190)
        self.tree.setColumnWidth(1, 90)
        ll.addWidget(self.tree, 1)

        btnrow = QHBoxLayout()
        for txt, fn in (("添加子项", self._add_child),
                        ("删除", self._delete),
                        ("添加到根", self._add_root)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            btnrow.addWidget(b)
        btnrow.addStretch(1)
        ll.addLayout(btnrow)

        # 选中时：类型/值可编辑（用项内控件）
        self.tree.itemDoubleClicked.connect(self._on_dclick)
        split.addWidget(left)

        # 右：SNBT 文本
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("SNBT 原文（可粘贴后点「解析到树」）"))
        self.text = QPlainTextEdit()
        self.text.setMaximumHeight(200)
        rl.addWidget(self.text)
        b = QPushButton("解析到树")
        b.clicked.connect(self._parse_text)
        rl.addWidget(b)
        rl.addStretch(1)
        split.addWidget(right)
        split.setSizes([520, 320])

        # 底部按钮
        brow = QHBoxLayout()
        brow.addStretch(1)
        ok = QPushButton("确定")
        ok.clicked.connect(self._accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        brow.addWidget(ok)
        brow.addWidget(cancel)
        lay.addLayout(brow)

    # ---- 数据 ----
    def load_text(self, text: str):
        try:
            struct = parse_snbt(text)
        except ValueError as exc:
            QMessageBox.warning(self, "解析失败", str(exc))
            return False
        self.tree.clear()
        # 树的顶层**就是**根复合：to_tree_items(dict, root) 会再造一层
        # "{}" 节点（实测变成 {}:{id:...}），故对 dict 直接把键值对
        # 挂到 root 下；列表/标量根才包一层。
        root = QTreeWidgetItem(self.tree, ["{}", "compound", ""])
        if isinstance(struct, dict):
            for k, v in struct.items():
                to_tree_items(v, root, k)
        elif isinstance(struct, list):
            for i, v in enumerate(struct):
                to_tree_items(v, root, str(i))
        else:
            to_tree_items(struct, root)
        self.tree.expandAll()
        self._sync_text()
        return True

    def _sync_text(self):
        roots = [self.tree.topLevelItem(i)
                 for i in range(self.tree.topLevelItemCount())]
        self.text.setPlainText(
            ",".join(tree_to_snbt(r) for r in roots))

    # ---- 事件 ----
    def _on_dclick(self, item, col):
        if col == 1:
            # 类型切换
            kinds = (VALUE_KINDS if item.parent() is not None
                     else ["compound"])
            cur = item.text(1)
            menu = QComboBox()
            menu.addItems(kinds)
            i = menu.findText(cur)
            if i >= 0:
                menu.setCurrentIndex(i)
            dlg = QDialog(self)
            dlg.setWindowTitle("选择类型")
            dl = QVBoxLayout(dlg)
            dl.addWidget(QLabel(f"「{item.text(0)}」的类型："))
            dl.addWidget(menu)
            bb = QHBoxLayout()
            okb = QPushButton("确定")
            cb = QPushButton("取消")
            okb.clicked.connect(dlg.accept)
            cb.clicked.connect(dlg.reject)
            bb.addWidget(okb)
            bb.addWidget(cb)
            dl.addLayout(bb)
            if dlg.exec() and menu.currentText() != cur:
                item.setText(1, menu.currentText())
                # 类型变化：清掉子项（compound/list 才有子项）
                if menu.currentText() not in ("compound", "list"):
                    item.takeChildren()
                self._sync_text()
        elif col == 2:
            cur = item.text(2)
            dlg = QDialog(self)
            dlg.setWindowTitle("编辑值")
            dl = QVBoxLayout(dlg)
            dl.addWidget(QLabel(f"「{item.text(0)}」的值："))
            ed = QLineEdit(cur)
            dl.addWidget(ed)
            bb = QHBoxLayout()
            okb = QPushButton("确定")
            cb = QPushButton("取消")
            okb.clicked.connect(dlg.accept)
            cb.clicked.connect(dlg.reject)
            bb.addWidget(okb)
            bb.addWidget(cb)
            dl.addLayout(bb)
            if dlg.exec():
                item.setText(2, ed.text())
                self._sync_text()

    def _selected(self):
        return self.tree.currentItem()

    def _add_child(self):
        p = self._selected()
        if p is None:
            return self._add_root()
        kind = p.text(1)
        if kind not in ("compound", "list"):
            QMessageBox.information(self, "添加子项",
                                    "只有 compound / list 可以有子项，"
                                    "请先双击「类型」列修改。")
            return
        ch = QTreeWidgetItem(p, ["键" if kind == "compound" else
                                 str(p.childCount()), "string", ""])
        p.setExpanded(True)
        self.tree.setCurrentItem(ch)
        self._sync_text()

    def _add_root(self):
        r = QTreeWidgetItem(self.tree, ["键", "string", ""])
        self.tree.setCurrentItem(r)
        self._sync_text()

    def _delete(self):
        it = self._selected()
        if it is None:
            return
        p = it.parent()
        if p is None:
            idx = self.tree.indexOfTopLevelItem(it)
            self.tree.takeTopLevelItem(idx)
        else:
            p.removeChild(it)
        self._sync_text()

    def _parse_text(self):
        t = self.text.toPlainText().strip()
        if not t:
            return
        # 根可能是 {..} 或 [..]
        self.load_text(t)

    def _accept(self):
        self._sync_text()
        self.result_text = self.text.toPlainText().strip()
        self.accept()
