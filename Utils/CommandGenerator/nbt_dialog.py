# -*- coding: utf-8 -*-
"""NBT 编辑对话框：全内联编辑 + 快速添加模板 + SNBT 文本双向同步。

设计目标（用户「只用动手指」）：
  - **全内联**：键（QLineEdit）、类型（QComboBox）、值（随类型变化的
    控件）三列**全部直接操作**，不再「双击 → 弹窗 → 确定」三步
  - byte/short/int 用 QSpinBox（上下箭头点选）；long/float/double 用
    带校验的输入框；string 自由输入
  - **快速添加**：内置常用标签库（通用实体 / 盔甲架 / 容器），选中即
    以正确的键名、类型、默认值插入，用户只改数字
  - 右键菜单：添加子项 / 添加兄弟 / 复制节点 / 上移 / 下移 / 删除
  - 重复键与空键**红色高亮**；查找框回车定位
  - 右：SNBT 原文（随树实时同步；可粘贴后「解析到树」反向进入树形）

SNBT 解析用**简化递归下降**（覆盖 {k:v,...} / [a,b,...] / 数组 /
带后缀标量 / 引号字符串），足以处理 give 相关的实体与方块实体 NBT。
"""
from __future__ import annotations

import re

from PySide6.QtCore import QLocale, QRegularExpression, Qt
from PySide6.QtGui import (QDoubleValidator, QKeySequence, QRegularExpressionValidator,
                           QShortcut)
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QMessageBox, QPushButton,
                               QSplitter, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget, QSpinBox)

# ---------------------------------------------------------------------------
# SNBT 解析（简化递归下降）
# ---------------------------------------------------------------------------

class _SNBTParser:
    """SNBT -> Python 结构（dict/list/带类型标记的标量）。

    标量带类型标记：返回 (kind, value)，kind ∈
      int/long/float/double/byte/short/string
    """

    def __init__(self, text: str):
        self.s = text.strip()
        self.i = 0

    def parse(self):
        return self._value()

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
                    f"第 {self.i} 字符附近无法解析键：…"
                    f"{self.s[self.i:self.i + 24]}")
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
        self._skip_ws()
        arr = None
        m = re.match(r'([BIL])\s*;\s*', self.s[self.i:])
        if m:
            arr = m.group(1)
            self.i += m.end()
        while True:
            self._skip_ws()
            if self.i >= len(self.s):
                raise ValueError("列表未闭合（缺少 ]）")
            if self.s[self.i] == "]":
                self.i += 1
                break
            out.append(self._value())
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
        # -> double，否则 int」。
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
                return ("byte", _int_of(num))
            if sfx == "s" or sfx == "S":
                return ("short", _int_of(num))
            if sfx == "l" or sfx == "L":
                # long 必须按整数字符串直取 —— int(float(...)) 在
                # 2^63-1 处丢精度（实测 9223372036854775807 变 ...808）
                return ("long", _int_of(num))
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
        raise ValueError(
            f"第 {p.i} 个字符附近无法解析：…{p.s[p.i:p.i + 24]}")
    return v


# ---------------------------------------------------------------------------
# 树 <-> SNBT（由对话框的行控件读取，见 NbtDialog）
# ---------------------------------------------------------------------------

CONTAINER_KINDS = ("compound", "list", "bytearray", "intarray", "longarray")
KINDS = ["compound", "list", "bytearray", "intarray", "longarray",
         "byte", "short", "int", "long", "float", "double", "string"]
INT_RANGES = {"byte": (-128, 127), "short": (-32768, 32767),
              "int": (-2147483648, 2147483647)}
_NUM_SUFFIX = {"byte": "b", "short": "s", "long": "L",
               "float": "f", "double": "d"}
_ELEM_KIND = {"bytearray": "byte", "intarray": "int", "longarray": "long"}

# 类型下拉的中文标签（data 仍是英文 kind，序列化不变）。
# 「傻瓜式」：新手面对 13 个英文术语无从下手；中文 + 用途提示后
# 一眼可辨（整数（32 位）vs 长整数（64 位）…）。
# **保持短**：类型列宽有限（~150px），过长的标签会被 QComboBox
# 截断；完整说明放 tooltip（见 _add_row 的注释列）。
KIND_LABELS = {
    "compound": "复合 {键:值}",
    "list": "列表 [a,b]",
    "bytearray": "字节数组 [B;]",
    "intarray": "整数数组 [I;]",
    "longarray": "长整数数组 [L;]",
    "byte": "小整数 ±127",
    "short": "整数 ±3.2万",
    "int": "整数 ±21亿",
    "long": "长整数 64位",
    "float": "小数 32位",
    "double": "小数 64位",
    "string": "文本",
}

# 类型下拉的完整说明（QComboBox setToolTip / 行 tooltip 用）
KIND_TOOLTIPS = {
    "compound": "复合标签 {键:值}：可以嵌套更多键值对",
    "list": "列表 [a,b,c]：有序集合，元素按顺序排列",
    "bytearray": "字节数组 [B;1,2]：每项 -128~127 的字节数",
    "intarray": "整数数组 [I;1,2]：每项 ±21 亿的整数",
    "longarray": "长整数数组 [L;1,2]：每项 64 位大数",
    "byte": "字节整数：-128 ~ 127（SNBT 后缀 b）",
    "short": "短整数：-32768 ~ 32767（后缀 s）",
    "int": "整数：±21 亿（SNBT 裸数字）",
    "long": "64 位长整数：±922 京（后缀 L）",
    "float": "32 位小数（后缀 f）",
    "double": "64 位小数，最常用（后缀 d）",
    "string": "文本字符串",
}

_KEY_OK = re.compile(r'^[A-Za-z0-9_.\-+/]+$')


def _int_of(num: str) -> int:
    """整数字符串直取；带小数点（非法 SNBT）才经 float 容错。"""
    if re.fullmatch(r'-?[0-9]+', num):
        return int(num)
    return int(float(num))


def _esc(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _key_snbt(k: str) -> str:
    """键名转 SNBT：安全字符裸写，其余加引号（与解析器的键正则一致）。"""
    return k if _KEY_OK.match(k) else _esc(k)


def _struct_kind(struct) -> str:
    if isinstance(struct, dict):
        return "compound"
    if isinstance(struct, list):
        return "list"
    if isinstance(struct, tuple) and len(struct) == 2 and \
            isinstance(struct[0], str):
        return struct[0]
    return "string"


# ---------------------------------------------------------------------------
# 快速添加：常用标签库（键名、类型、默认值均按 1.20.5+ NBT 约定）
#   (标签, 键, SNBT 值) —— 值用 SNBT 文本书写，经 parse_snbt 得到结构，
#   与「粘贴解析」走同一条路，避免手写元组出错。
#   键为 None 的行是**分组标题**（下拉里不可选）。
# ---------------------------------------------------------------------------

QUICK_PRESETS = [
    ("—— 通用实体 ——", None, None),
    ("NoAI（禁用 AI）", "NoAI", "1b"),
    ("Invulnerable（无敌）", "Invulnerable", "1b"),
    ("Silent（静音）", "Silent", "1b"),
    ("Glowing（发光轮廓）", "Glowing", "1b"),
    ("NoGravity（无重力）", "NoGravity", "1b"),
    ("Invisible（隐身）", "Invisible", "1b"),
    ("CustomNameVisible（名字常显）", "CustomNameVisible", "1b"),
    ("CustomName（自定义名字）", "CustomName", '"名字"'),
    ("Health（生命值）", "Health", "20.0f"),
    ("AbsorptionAmount（吸收护盾）", "AbsorptionAmount", "0.0f"),
    ("Fire（剩余着火刻）", "Fire", "-1s"),
    ("Tags（标签）", "Tags", '["mch"]'),
    ("Rotation（yaw、pitch）", "Rotation", "[0.0f,0.0f]"),
    ("Motion（运动向量）", "Motion", "[0.0d,0.0d,0.0d]"),
    ("HandItems（主手 / 副手）", "HandItems",
     '[{id:"minecraft:air",count:1},{id:"minecraft:air",count:1}]'),
    ("ArmorItems（盔甲四件）", "ArmorItems",
     '[{id:"minecraft:air",count:1},{id:"minecraft:air",count:1},'
     '{id:"minecraft:air",count:1},{id:"minecraft:air",count:1}]'),
    ("—— 盔甲架 ——", None, None),
    ("ShowArms（显示手臂）", "ShowArms", "1b"),
    ("Small（小型）", "Small", "1b"),
    ("NoBasePlate（无底座）", "NoBasePlate", "1b"),
    ("Marker（纯标记）", "Marker", "1b"),
    ("—— 容器（方块实体）——", None, None),
    ("Lock（上锁）", "Lock", '"minecraft:diamond"'),
    ("Items（物品栏）", "Items", "[]"),
    ("Slot（槽位）", "Slot", "0b"),
]


from Utils.CommandGenerator.nbt_key_cn import KEY_CN   # noqa: E402


class NbtDialog(QDialog):
    """NBT 编辑对话框（全内联编辑）。"""

    def __init__(self, initial: str = "", title="编辑 NBT", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(920, 640)
        self.result_text = ""
        self._busy = False          # 构建期屏蔽控件信号，避免半成品触发同步
        self._hidden = set()        # 占位（与旧版字段兼容）
        self._build()
        self._init_root()
        if initial.strip():
            self.load_text(initial)

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(6)

        # 快速添加 + 查找
        top = QHBoxLayout()
        top.addWidget(QLabel("快速添加"))
        self.quick = QComboBox()
        self.quick.addItem("选择常用标签…", None)
        for label, key, _snbt in QUICK_PRESETS:
            self.quick.addItem(label, None if key is None else (key, _snbt))
        self.quick.currentIndexChanged.connect(self._on_quick)
        top.addWidget(self.quick, 1)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("查找键（回车定位）")
        self.find_edit.setMaximumWidth(180)
        self.find_edit.returnPressed.connect(self._find_next)
        top.addWidget(self.find_edit)
        lay.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)
        lay.addWidget(split, 1)

        # 左：树（全内联控件）
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["键", "类型", "值"])
        # 列宽：键 190（长键名+中文注释如 CustomNameVisible（名字常显）
        # 需 240px，但 QLineEdit 可横向滚动，190 是不滚动也能看全大部分
        # 的平衡值）；类型 150 容纳「长整数数组 [L;]」（108 会截断）
        self.tree.setColumnWidth(0, 190)
        self.tree.setColumnWidth(1, 150)
        self.tree.setSelectionMode(
            QTreeWidget.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(
            QTreeWidget.EditTrigger.NoEditTriggers)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        ll.addWidget(self.tree, 1)
        brow = QHBoxLayout()
        for txt, fn, tip in (
            ("＋ 添加条目", self._add_child,
             "加到「当前选中」里面；选中的若是普通值则加到它旁边"),
            ("＋ 同级再添一条", self._add_sibling,
             "在选中条目旁再加一条同类型的"),
            ("复制", self._duplicate, "复制选中的条目（含全部内容）"),
            ("删除", self._delete, "删除选中的条目"),
        ):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            brow.addWidget(b)
        brow.addStretch(1)
        ll.addLayout(brow)
        QShortcut(QKeySequence.Delete, self.tree, self._delete)
        split.addWidget(left)

        # 右：SNBT 文本
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        rl.addWidget(QLabel("SNBT 原文（粘贴现成的可反向编辑）"))
        self.text = QLineEdit()
        self.text.setPlaceholderText("粘贴 {键:值,…} 后回车或点下方按钮")
        self.text.returnPressed.connect(self._parse_text)
        rl.addWidget(self.text)
        pb = QPushButton("⤴ 解析到树")
        pb.clicked.connect(self._parse_text)
        rl.addWidget(pb)
        rl.addStretch(1)
        split.addWidget(right)
        split.setSizes([560, 340])

        hint = QLabel("三步上手：① 从「快速添加」选一个常用标签（或点根行的 ＋）"
                      "→ ② 改键名和值 → ③ 确定。键名重复/留空会标红；"
                      "右侧 SNBT 可粘贴现成的命令反向解析。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;font-size:11px;")
        lay.addWidget(hint)

        brow2 = QHBoxLayout()
        brow2.addStretch(1)
        ok = QPushButton("确定")
        ok.clicked.connect(self._accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        brow2.addWidget(ok)
        brow2.addWidget(cancel)
        lay.addLayout(brow2)

    def _init_root(self, kind="compound"):
        """根行：类型锁定（compound 或 list），键列显示 {} / []。

        值格做成可点击的「＋ 添加第一项」—— 新手面对空树 + 一排
        英文按钮的第一反应是「我从哪开始？」；根行直接给出入口。
        """
        self._root_kind = kind
        self.root = QTreeWidgetItem(self.tree)
        k = QLabel("{}" if kind == "compound" else "[]")
        k.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tree.setItemWidget(self.root, 0, k)
        t = QLabel(KIND_LABELS.get(kind, kind))
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setToolTip(KIND_TOOLTIPS.get(kind, ""))
        self.tree.setItemWidget(self.root, 1, t)
        s = QLabel("＋ 点击添加第一项")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s.setStyleSheet("color:#4a9eff;")
        s.setCursor(Qt.CursorShape.PointingHandCursor)
        s.setToolTip("或从上方「快速添加」选一个常用标签")
        s.mousePressEvent = lambda ev: (self._add_child())
        self._root_add_label = s
        self.tree.setItemWidget(self.root, 2, s)

    # ------------------------------------------------------------------
    # 行构建
    # ------------------------------------------------------------------
    def _kind_of(self, item) -> str:
        if item is self.root:
            return self._root_kind
        w = self.tree.itemWidget(item, 1)
        if isinstance(w, QComboBox):
            return w.currentData() or "string"
        if isinstance(w, QLabel):
            # 锁定类型的 QLabel 显示中文标签（KIND_LABELS）——
            # 必须反查回英文 kind，否则中文泄进序列化分支
            # （实测 intarray 子元素回写为 ""）。
            text = w.text()
            for k, lab in KIND_LABELS.items():
                if lab == text:
                    return k
            return text if text in KINDS else "string"
        return "string"

    def _add_row(self, parent_item, key, struct=None, kind=None,
                 value=None, select=True, at=None):
        """在 parent_item 下加一行。struct 优先（来自解析），否则 kind+value。

        at=None 追加到末尾；否则 insertChild(at) —— **必须先插到最终
        位置再挂控件**：removeChild 会销毁该 item 已挂的
        setItemWidget 控件（Qt 接管所有权，实测重排后 itemWidget
        全变 None），所以「先加再移」的写法是错的。
        """
        if struct is not None:
            kind = _struct_kind(struct)
            if kind not in CONTAINER_KINDS:
                value = struct[1] if isinstance(struct, tuple) else struct
        pk = self._kind_of(parent_item)
        named = pk not in ("list",) + tuple(_ELEM_KIND)
        item = QTreeWidgetItem()
        if at is None:
            parent_item.addChild(item)
        else:
            parent_item.insertChild(max(0, at), item)

        # --- 键列 ---
        if named:
            cn = KEY_CN.get(str(key))
            display_key = f"{key}（{cn}）" if cn else str(key)
            ed = QLineEdit(display_key)
            ed.setPlaceholderText("键名")
            ed.textChanged.connect(self._on_change)
            if cn:
                ed.setToolTip(f"{key}\n{cn}")
            self.tree.setItemWidget(item, 0, ed)
        else:
            lab = QLabel(str(key))
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cn = KEY_CN.get(str(key))
            if cn:
                lab.setToolTip(f"{key}\n{cn}")
            self.tree.setItemWidget(item, 0, lab)

        # --- 类型列 ---
        # 数组元素类型锁定（bytearray 的子必须是 byte…），其余可换
        locked = pk in _ELEM_KIND
        if locked:
            t = QLabel(KIND_LABELS.get(_ELEM_KIND[pk], _ELEM_KIND[pk]))
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setToolTip(KIND_TOOLTIPS.get(_ELEM_KIND[pk], ""))
            self.tree.setItemWidget(item, 1, t)
        else:
            cb = QComboBox()
            for k in KINDS:
                cb.addItem(KIND_LABELS.get(k, k), k)
            cb.setCurrentIndex(max(0, cb.findData(kind)))
            # 悬停选项看完整说明（列表展开时逐项提示）
            cb.setToolTip(KIND_TOOLTIPS.get(kind, ""))
            cb.currentIndexChanged.connect(
                lambda *_: self._on_type_changed(item))
            self.tree.setItemWidget(item, 1, cb)

        # --- 值列 ---
        self._set_value_cell(item, kind, value)

        # --- 子级 ---
        if kind == "compound" and isinstance(struct, dict):
            for k, v in struct.items():
                self._add_row(item, k, v)
        elif kind == "list" and isinstance(struct, list):
            for i, v in enumerate(struct):
                self._add_row(item, str(i), v)
        elif kind in _ELEM_KIND and isinstance(struct, tuple) and \
                isinstance(struct[1], list):
            for i, v in enumerate(struct[1]):
                vv = v[1] if isinstance(v, tuple) else v
                self._add_row(item, str(i), kind=_ELEM_KIND[kind], value=vv)

        if select:
            self.tree.setCurrentItem(item)
        return item

    def _set_value_cell(self, item, kind, value):
        """按类型装值列控件。"""
        w = None
        if kind == "compound":
            w = QLabel("{}")
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
        elif kind in ("list", "bytearray", "intarray", "longarray"):
            w = QLabel("[0 项]")
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
        elif kind == "string":
            w = QLineEdit("" if value is None else str(value))
            w.setPlaceholderText("文本")
            w.textChanged.connect(self._on_change)
        elif kind in INT_RANGES:
            lo, hi = INT_RANGES[kind]
            w = QSpinBox()
            w.setRange(lo, hi)
            try:
                w.setValue(int(value))
            except (TypeError, ValueError):
                w.setValue(0)
            w.valueChanged.connect(self._on_change)
        elif kind == "long":
            w = QLineEdit("0" if value is None else str(value))
            w.setPlaceholderText("64 位整数")
            w.setValidator(QRegularExpressionValidator(
                QRegularExpression(r"-?[0-9]{0,19}")))
            w.textChanged.connect(self._on_change)
        elif kind in ("float", "double"):
            w = QLineEdit("0.0" if value is None else str(value))
            w.setPlaceholderText("小数")
            v = QDoubleValidator(-1e308, 1e308, 12)
            v.setLocale(QLocale.c())
            w.setValidator(v)
            w.textChanged.connect(self._on_change)
        if w is not None:
            self.tree.setItemWidget(item, 2, w)

    # ------------------------------------------------------------------
    # 读取 / 序列化
    # ------------------------------------------------------------------
    def _scalar_value(self, item, kind):
        w = self.tree.itemWidget(item, 2)
        if kind == "string":
            return w.text()
        if kind == "long":
            try:
                return int(w.text())
            except (TypeError, ValueError):
                return 0
        if kind in ("float", "double"):
            try:
                return float(w.text())
            except (TypeError, ValueError):
                return 0.0
        if kind in INT_RANGES:
            return w.value()
        return ""

    def _scalar_snbt(self, item, kind):
        w = self.tree.itemWidget(item, 2)
        if kind == "string":
            return _esc(w.text() if w else "")
        if kind == "long":
            try:
                return f"{int(w.text())}L"
            except (TypeError, ValueError):
                return "0L"
        if kind in ("float", "double"):
            try:
                v = float(w.text())
            except (TypeError, ValueError):
                v = 0.0
            return f"{v}{_NUM_SUFFIX[kind]}"
        if kind == "int":
            # int 无后缀（SNBT 裸整数即 int），**必须先于 INT_RANGES
            # 判断** —— int 也在 INT_RANGES 里，先查 _NUM_SUFFIX 会
            # KeyError（实测载入 {a:1} 即崩）。
            return str(w.value())
        if kind in INT_RANGES:
            return f"{w.value()}{_NUM_SUFFIX[kind]}"
        return _esc("")

    def _extract_key(self, text: str) -> str:
        """从「key（中文）」格式中提取 key 部分。

        早先直接用 kw.text() 作为 key，但用户编辑时可能输入「key（中文）」，
        也可能只输入「key」。必须剥离中文括号部分，只保留 key。
        """
        text = text.strip()
        # 去掉末尾的「）」及其前面的中文
        if "（" in text and text.endswith("）"):
            text = text.split("（")[0].strip()
        return text

    def _serialize(self, item) -> str:
        kind = self._kind_of(item)
        n = item.childCount()
        if kind == "compound":
            parts = []
            for i in range(n):
                ch = item.child(i)
                kw = self.tree.itemWidget(ch, 0)
                raw_key = kw.text().strip() if isinstance(kw, QLineEdit) \
                    else ""
                key = self._extract_key(raw_key)
                if not key:
                    continue
                parts.append(f"{_key_snbt(key)}:{self._serialize(ch)}")
            return "{" + ",".join(parts) + "}"
        if kind == "list":
            return "[" + ",".join(self._serialize(item.child(i))
                                  for i in range(n)) + "]"
        if kind in _ELEM_KIND:
            pre = {"bytearray": "[B;", "intarray": "[I;",
                   "longarray": "[L;"}[kind]
            return pre + ",".join(self._serialize(item.child(i))
                                  for i in range(n)) + "]"
        return self._scalar_snbt(item, kind)

    def to_snbt(self) -> str:
        """树 -> SNBT 文本（供测试与外部读取）。"""
        return self._serialize(self.root)

    # ------------------------------------------------------------------
    # 同步：重编号 / 摘要 / 重复键标红 / 写 SNBT
    # ------------------------------------------------------------------
    def _on_change(self, *_a):
        if self._busy:
            return
        # 编辑键名时同步更新 tooltip（中文说明随键名变化）
        w = self.tree.currentItem()
        if w is not None:
            kw = self.tree.itemWidget(w, 0)
            if isinstance(kw, QLineEdit):
                raw_key = kw.text().strip()
                key = self._extract_key(raw_key)
                cn = KEY_CN.get(key)
                kw.setToolTip(f"{key}\n{cn}" if cn else key)
        self._sync()

    def _sync(self):
        self._busy = True
        try:
            self._renumber(self.root)
            self._summaries(self.root)
            self._mark_bad_keys(self.root)
            self.text.setText(self.to_snbt())
        finally:
            self._busy = False

    def _renumber(self, item):
        k = self._kind_of(item)
        n = item.childCount()
        if k == "list" or k in _ELEM_KIND:
            for i in range(n):
                ch = item.child(i)
                w = self.tree.itemWidget(ch, 0)
                if isinstance(w, QLabel):
                    w.setText(str(i))
        for i in range(n):
            self._renumber(item.child(i))

    def _summaries(self, item):
        # 根行的值格是「＋ 添加」入口，不参与摘要覆写
        if item is self.root:
            for i in range(item.childCount()):
                self._summaries(item.child(i))
            return
        k = self._kind_of(item)
        w = self.tree.itemWidget(item, 2)
        if isinstance(w, QLabel):
            if k == "compound":
                w.setText(f"{{{item.childCount()} 项}}")
            elif k in ("list", "bytearray", "intarray", "longarray"):
                w.setText(f"[{item.childCount()} 项]")
        for i in range(item.childCount()):
            self._summaries(item.child(i))

    def _mark_bad_keys(self, item):
        """复合标签的子键：空键或重复键标红。"""
        k = self._kind_of(item)
        if k == "compound":
            seen = {}
            for i in range(item.childCount()):
                ch = item.child(i)
                w = self.tree.itemWidget(ch, 0)
                if not isinstance(w, QLineEdit):
                    continue
                raw_key = w.text().strip()
                key = self._extract_key(raw_key)
                seen.setdefault(key, []).append(w)
            for key, ws in seen.items():
                bad = (not key) or len(ws) > 1
                for w in ws:
                    w.setStyleSheet(
                        "background:#ffd9d9;" if bad else "")
        for i in range(item.childCount()):
            self._mark_bad_keys(item.child(i))

    # ------------------------------------------------------------------
    # 数据进出
    # ------------------------------------------------------------------
    def load_text(self, text: str) -> bool:
        try:
            struct = parse_snbt(text)
        except ValueError as exc:
            QMessageBox.warning(self, "解析失败", str(exc))
            return False
        self._busy = True
        self.tree.clear()
        kind = ("compound" if isinstance(struct, dict)
                else "list" if isinstance(struct, list) else "compound")
        self._init_root(kind)
        if isinstance(struct, dict):
            for k, v in struct.items():
                self._add_row(self.root, k, v, select=False)
        elif isinstance(struct, list):
            for i, v in enumerate(struct):
                self._add_row(self.root, str(i), v, select=False)
        else:
            self._add_row(self.root, "value", struct, select=False)
        self.tree.expandAll()
        self._busy = False
        self._sync()
        return True

    def _parse_text(self):
        t = self.text.text().strip()
        if not t:
            return
        self.load_text(t)

    def _accept(self):
        self._sync()
        # 空键条目会被序列化**静默丢弃**（早先直接确定，用户发现
        # 条目消失却不知原因）。确定前明确告知，给取消回去补名的机会。
        empty_rows = []
        for i in range(self.root.childCount()):
            ch = self.root.child(i)
            w = self.tree.itemWidget(ch, 0)
            if isinstance(w, QLineEdit) and not w.text().strip():
                empty_rows.append(ch)
        if empty_rows:
            ret = QMessageBox.warning(
                self, "有空键名的条目",
                f"有 {len(empty_rows)} 个条目的键名是空的（红底标出），"
                "确定后会被丢弃。\n\n"
                "「丢弃」继续；「取消」回去补键名。",
                QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if ret != QMessageBox.StandardButton.Discard:
                # 取消：选中并聚焦第一个空键名，直接补
                self.tree.setCurrentItem(empty_rows[0])
                w = self.tree.itemWidget(empty_rows[0], 0)
                if isinstance(w, QLineEdit):
                    w.setFocus()
                    w.selectAll()
                return
        self.result_text = self.text.text().strip()
        self.accept()

    # ------------------------------------------------------------------
    # 编辑动作
    # ------------------------------------------------------------------
    def _on_type_changed(self, item):
        """类型切换：容器 -> 标量时丢弃子级，值控件按新类型重建。"""
        if self._busy:
            return
        kind = self._kind_of(item)
        if kind not in CONTAINER_KINDS:
            item.takeChildren()
        self._set_value_cell(item, kind, None)
        # tooltip 随类型更新（悬停可见完整说明）
        tw = self.tree.itemWidget(item, 1)
        if isinstance(tw, QComboBox):
            tw.setToolTip(KIND_TOOLTIPS.get(kind, ""))
        self._sync()

    def _sel(self):
        return self.tree.currentItem()

    def _unique_key(self, parent_item, base="新键"):
        keys = set()
        for i in range(parent_item.childCount()):
            w = self.tree.itemWidget(parent_item.child(i), 0)
            if isinstance(w, QLineEdit):
                keys.add(w.text().strip())
        if base not in keys:
            return base
        n = 2
        while f"{base}{n}" in keys:
            n += 1
        return f"{base}{n}"

    def _focus_key(self, item):
        w = self.tree.itemWidget(item, 0)
        if isinstance(w, QLineEdit):
            w.setFocus()
            w.selectAll()

    def _add_child(self):
        it = self._sel() or self.root
        k = self._kind_of(it)
        if k in ("list",) + tuple(_ELEM_KIND):
            n = it.childCount()
            ek = self._kind_of(it.child(0)) if n else (
                "string" if k == "list" else _ELEM_KIND[k])
            row = self._add_row(it, str(n), kind=ek)
            self.tree.expandItem(it)
            self.tree.setCurrentItem(row)
            self._focus_key(row)
            self._sync()
            return
        if k != "compound":
            it = it.parent() or self.root
        key = self._unique_key(it)
        row = self._add_row(it, key, kind="string")
        self.tree.expandItem(it)
        self.tree.setCurrentItem(row)
        self._focus_key(row)
        self._sync()

    def _add_sibling(self):
        it = self._sel()
        if it is None or it is self.root:
            return self._add_child()
        p = it.parent() or self.root
        if self._kind_of(p) in ("list",) + tuple(_ELEM_KIND):
            # 列表：追加元素（兄弟即下一个元素）
            n = p.childCount()
            ek = self._kind_of(it)
            row = self._add_row(p, str(n), kind=ek)
            self.tree.setCurrentItem(row)
            self._focus_key(row)
            self._sync()
            return
        key = self._unique_key(p, "新键")
        idx = p.indexOfChild(it) + 1
        row = self._add_row(p, key, kind=self._kind_of(it), at=idx)
        self.tree.setCurrentItem(row)
        self._focus_key(row)
        self._sync()

    def _delete(self):
        it = self._sel()
        if it is None or it is self.root:
            return
        p = it.parent()
        if p is None:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(it))
        else:
            p.removeChild(it)
        self._sync()

    def _duplicate(self):
        it = self._sel()
        if it is None or it is self.root:
            return
        p = it.parent() or self.root
        try:
            struct = parse_snbt(self._serialize(it))
        except ValueError:
            return
        key = self.tree.itemWidget(it, 0)
        base = key.text().strip() if isinstance(key, QLineEdit) \
            else str(p.childCount())
        if self._kind_of(p) == "compound":
            base = self._unique_key(p, base)
        idx = p.indexOfChild(it) + 1
        row = self._add_row(p, base, struct, select=False, at=idx)
        self.tree.setCurrentItem(row)
        self._focus_key(row)
        self._sync()

    def _move_item(self, item, delta):
        """列表/数组子项上移(-1)/下移(+1)。

        用「序列化 -> 删除 -> 在目标位置插入克隆」实现。**必须用
        at= 直接插入最终位置** —— 若先 append 再 removeChild/
        insertChild 重排，Qt 会在 removeChild 时销毁已挂的
        setItemWidget 控件（实测 itemWidget 全变 None）。
        """
        p = item.parent()
        if p is None or self._kind_of(p) not in \
                ("list",) + tuple(_ELEM_KIND):
            return
        i = p.indexOfChild(item)
        j = i + delta
        if not (0 <= j < p.childCount()):
            return
        try:
            struct = parse_snbt(self._serialize(item))
        except ValueError:
            return
        key = self.tree.itemWidget(item, 0)
        base = key.text().strip() if isinstance(key, QLineEdit) else str(i)
        p.removeChild(item)
        row = self._add_row(p, base, struct, select=False, at=j)
        self.tree.setCurrentItem(row)
        self._sync()

    # ------------------------------------------------------------------
    # 快速添加 / 查找 / 右键菜单
    # ------------------------------------------------------------------
    def _on_quick(self, idx):
        if self._busy:
            return
        data = self.quick.itemData(idx)
        if not data:
            return
        key, snbt = data
        try:
            struct = parse_snbt(snbt)
        except ValueError:
            return
        # 落点：选中项若是复合标签 -> 其内；否则 -> 其父复合（或根）
        it = self._sel() or self.root
        k = self._kind_of(it)
        if k != "compound":
            it = it.parent() or self.root
        row = self._add_row(it, key, struct)
        self.tree.expandItem(it)
        self.tree.setCurrentItem(row)
        self._sync()
        # 复位下拉，便于重复添加同一标签
        self._busy = True
        self.quick.setCurrentIndex(0)
        self._busy = False

    def _find_next(self):
        q = self.find_edit.text().strip().lower()
        if not q:
            return
        items = []

        def walk(it):
            for i in range(it.childCount()):
                ch = it.child(i)
                items.append(ch)
                walk(ch)

        walk(self.root)
        if not items:
            return
        cur = self._sel()
        start = items.index(cur) + 1 if cur in items else 0
        for off in range(len(items)):
            it = items[(start + off) % len(items)]
            w = self.tree.itemWidget(it, 0)
            txt = w.text() if w is not None else ""
            if q in txt.lower():
                p = it.parent()
                while p is not None:
                    self.tree.expandItem(p)
                    p = p.parent()
                self.tree.setCurrentItem(it)
                self.tree.scrollToItem(it)
                return

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        m = QMenu(self)
        m.addAction("＋ 添加条目", self._add_child)
        if it is not None and it is not self.root:
            m.addAction("＋ 同级再添一条", self._add_sibling)
            m.addAction("复制", self._duplicate)
            p = it.parent()
            if p is not None and self._kind_of(p) in \
                    ("list",) + tuple(_ELEM_KIND):
                m.addSeparator()
                m.addAction("上移", lambda: self._move_item(it, -1))
                m.addAction("下移", lambda: self._move_item(it, 1))
            m.addSeparator()
            m.addAction("删除", self._delete)
        m.exec(self.tree.viewport().mapToGlobal(pos))
