# -*- coding: utf-8 -*-
"""CommandGenerator 工具：MC 指令生成器（当前实现 /give）。

三栏布局：
  左  ：指令分类树（41 条目标指令，全部已实现）
  中  ：参数区（QStackedWidget，逐指令一页；give 页含基础参数
         + 数据组件卡片区）
  右  ：预览（物品图标/中文名/附魔列表）+ 输出（指令文本/长度）
         + 校验（错误与警告）

设计要点：
- 参数区与序列化**解耦**：UI 只负责构造参数字典，交给
  `Utils/CommandGenerator/give.py`（纯函数、可单测）产出文本；
- 版本感知：附魔组件的 `{levels:{...}}` 包装在 data version <4307
  的版本（1.21）才输出，1.21.11/26.2 为裸映射。详见 give.py 注释；
- 实时刷新：任何控件变动 -> `_refresh()` -> 重新序列化 + 校验。
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication, QGroupBox, QHBoxLayout,
                               QMessageBox, QPushButton, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .tool_base import BaseToolWidget
from CodesUI.CommandGenerator import Ui_commandGenerator
from Utils.CommandGenerator import cmd_form as CF
from Utils.CommandGenerator import cmd_specs as CS
from Utils.CommandGenerator import commands as K
from Utils.CommandGenerator import components as C
from Utils.CommandGenerator import comp_editors as CE
from Utils.CommandGenerator import give as G
from Utils.CommandGenerator import item_list as IL

# 指令分组（对应 UI 设计：5 个语义分组）
CMD_GROUPS = [
    ("物品与实体", ["give", "item", "summon", "loot", "enchant", "effect",
                    "kill", "attribute", "damage", "playsound", "particle",
                    "spawn_armor_trims"]),
    ("方块与世界", ["setblock", "fill", "clone", "fillbiome", "place",
                    "locate", "forceload", "data", "worldborder",
                    "gamerule", "tick", "schedule"]),
    ("玩家与进度", ["experience", "advancement", "title", "scoreboard",
                    "team", "bossbar", "waypoint"]),
    ("执行与控制", ["execute", "dialog", "random", "spreadplayers",
                    "teleport", "rotate", "debugconfig", "chase",
                    "datapack", "raid"]),
]

# 已实现的指令 -> 中栏页索引
#   pageUnsupported = 0，pageGeneric = 1，pageGive = 2
# give 有专用的数据组件卡片区，故单独一页；
# 其余指令由 cmd_specs 声明式规格 + 通用表单渲染。
IMPLEMENTED = {
    "give": 2,
    "kill": 1,
    "enchant": 1,
    "effect": 1,
    "setblock": 1,
    "fill": 1,
    "summon": 1,
    "locate": 1,
    # 第 1 批剩余
    "item": 1,
    "loot": 1,
    "attribute": 1,
    "damage": 1,
    "playsound": 1,
    "particle": 1,
    "spawn_armor_trims": 1,
    # 第 2 批（剩余全部）
    "clone": 1,
    "fillbiome": 1,
    "place": 1,
    "forceload": 1,
    "data": 1,
    "worldborder": 1,
    "gamerule": 1,
    "tick": 1,
    "schedule": 1,
    "experience": 1,
    "advancement": 1,
    "title": 1,
    "scoreboard": 1,
    "team": 1,
    "bossbar": 1,
    "waypoint": 1,
    "dialog": 1,
    "random": 1,
    "spreadplayers": 1,
    "teleport": 1,
    "rotate": 1,
    "debugconfig": 1,
    "chase": 1,
    "datapack": 1,
    "raid": 1,
    # execute 专用页（索引在 _ensure_execute_page 里动态填入）
    "execute": 3,
}

VERSIONS = ["26.2", "1.21.11", "1.21"]

# 常用目标选择器
TARGET_PRESETS = ["@p", "@a", "@e", "@r", "@s",
                  "@a[distance=..10]", "@e[type=zombie]",
                  "@p[level=1..]", "@a[team=red]"]

_ICON_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "StructurePreviewer", "items")

MAX_CMD_LEN = 25600


class CommandGeneratorWidget(BaseToolWidget):
    """指令生成器。"""

    preferred_size = (1440, 920)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_commandGenerator()
        self.ui.setupUi(self)

        # 组件卡片：cid -> (QGroupBox, editor)
        self._cards = {}
        # 防止递归刷新
        self._busy = False

        self._build_tree()
        self._build_version_combo()
        self._build_target_combo()
        self._build_item_combo()
        self._build_comp_combo()
        self._connect()
        # _build_tree 里已 setCurrentItem，但那时信号尚未连接，
        # 故必须手动同步一次页索引，否则中栏停在「未实现」页
        self._on_cmd_changed()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _build_tree(self):
        tree = self.ui.cmdTree
        tree.clear()
        for group, cmds in CMD_GROUPS:
            top = QTreeWidgetItem([group])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for cmd in cmds:
                child = QTreeWidgetItem([cmd])
                child.setData(0, Qt.ItemDataRole.UserRole, cmd)
                if cmd in IMPLEMENTED:
                    # 全部指令都已实现，故不再加「[已实现]」后缀
                    # （标签已无区分作用，只是噪音）。保留加粗。
                    f = child.font(0)
                    f.setBold(True)
                    child.setFont(0, f)
                else:
                    child.setForeground(0, Qt.GlobalColor.gray)
                top.addChild(child)
            tree.addTopLevelItem(top)
        tree.expandAll()
        # 默认选中 give
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            for j in range(top.childCount()):
                ch = top.child(j)
                if ch.data(0, Qt.ItemDataRole.UserRole) == "give":
                    tree.setCurrentItem(ch)
                    return

    def _build_version_combo(self):
        self.ui.versionCombo.clear()
        self.ui.versionCombo.addItems(VERSIONS)
        idx = self.ui.versionCombo.findText("1.21.11")
        self.ui.versionCombo.setCurrentIndex(max(0, idx))

    def _build_target_combo(self):
        cb = self.ui.giveTargetCombo
        cb.clear()
        cb.addItems(TARGET_PRESETS)
        cb.setCurrentText("@p")

    def _build_item_combo(self):
        cb = self.ui.giveItemCombo
        cb.clear()
        # 有图标的排前面（更常用），其次按 id
        icons = IL.ITEM_ICONS
        head = sorted(icons)
        tail = [i for i in IL.ITEM_IDS if i not in icons]
        for iid in head + tail:
            cn = IL.ITEM_CN.get(iid, "")
            label = f"{cn}（{iid}）" if cn else iid
            cb.addItem(label, iid)
        # 默认钻石剑
        i = cb.findData("diamond_sword")
        if i >= 0:
            cb.setCurrentIndex(i)

    def _build_comp_combo(self):
        """「添加组件」下拉：按分组插入不可选的分隔标题。

        QComboBox 原生不支持 optgroup，故用「禁用 + 加粗」的项作为
        分组标题，其余为可选项。共覆盖全部 79 个组件。
        """
        cb = self.ui.giveCompCombo
        cb.clear()
        model = cb.model()
        for gname, ids in C.grouped_ids():
            cb.addItem(f"── {gname} ──", None)
            idx = cb.count() - 1
            it = model.item(idx)
            if it is not None:
                # 分组标题不可选
                it.setEnabled(False)
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            for cid in ids:
                cb.addItem(C.display(cid), cid)
        # 默认停在第一个**可选**组件上，避免初始落在分组标题
        # （标题 data 为 None，此时点「添加」会取不到组件）
        self._select_first_real_component()

    def _select_first_real_component(self):
        """把下拉定位到第一个真实组件（跳过分组标题）。"""
        cb = self.ui.giveCompCombo
        for i in range(cb.count()):
            if cb.itemData(i):
                cb.setCurrentIndex(i)
                return

    def _on_comp_combo_changed(self, _i):
        """选中分组标题时自动跳到下一个可选组件。

        另外：**QComboBox 允许用户直接用滚轮/键盘选中被 setEnabled(False)
        的项**（禁用只挡鼠标点击），故此处仍需兜底跳过。
        """
        cb = self.ui.giveCompCombo
        i = cb.currentIndex()
        if cb.itemData(i) is not None:
            return
        for j in range(i + 1, cb.count()):
            if cb.itemData(j):
                cb.setCurrentIndex(j)
                return
        for j in range(i - 1, -1, -1):
            if cb.itemData(j):
                cb.setCurrentIndex(j)
                return

    def _connect(self):
        u = self.ui
        u.cmdTree.itemSelectionChanged.connect(self._on_cmd_changed)
        u.versionCombo.currentIndexChanged.connect(self._refresh)
        u.nsPrefixCheck.stateChanged.connect(self._refresh)
        u.giveCountSpin.valueChanged.connect(self._refresh)
        u.giveTargetCombo.currentTextChanged.connect(self._refresh)
        u.giveItemCombo.currentIndexChanged.connect(self._refresh)
        u.giveItemCombo.editTextChanged.connect(self._refresh)
        u.giveCompAddBtn.clicked.connect(
            lambda _=False: self._add_component())
        u.giveCompCombo.currentIndexChanged.connect(
            self._on_comp_combo_changed)
        u.copyBtn.clicked.connect(self._copy)
        u.outputCopyBtn.clicked.connect(self._copy)
        u.clearBtn.clicked.connect(self._clear)
        u.giveTargetBuilderBtn.clicked.connect(self._selector_dialog)
        u.giveItemPickBtn.clicked.connect(self._pick_item)

    # ------------------------------------------------------------------
    # 指令切换
    # ------------------------------------------------------------------
    def _current_cmd(self) -> str | None:
        it = self.ui.cmdTree.currentItem()
        if it is None:
            return None
        return it.data(0, Qt.ItemDataRole.UserRole)

    def _on_cmd_changed(self):
        cmd = self._current_cmd()
        # execute 专用页：**必须先建页再取索引** —— 页是动态加入
        # centerStack 的，首次进入时 IMPLEMENTED 里的静态值（3）与实际
        # 索引不符，会导致切到错误页（实测切到了 give 页）。
        if cmd == "execute":
            self._ensure_execute_page()
        idx = IMPLEMENTED.get(cmd, 0)
        self.ui.centerStack.setCurrentIndex(idx)
        # 通用页：按指令重建表单（每种指令字段不同）
        if idx == 1 and cmd in CS.SPECS:
            self._build_generic_form(cmd)
        self._refresh()

    def _ensure_execute_page(self):
        """execute 专用链式构建器页（动态加入 centerStack）。

        不放进 .ui 是为了避免改 .ui 后还要重编译 CodesUI；页索引
        在 IMPLEMENTED 里登记为 3（pageUnsupported/Generic/Give 之后）。
        """
        if getattr(self, "_exec_page", None) is not None:
            return
        from Utils.CommandGenerator.execute_ui import ExecuteChainBuilder
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        self._exec_builder = ExecuteChainBuilder()
        self._exec_builder.changed.connect(self._refresh)
        lay.addWidget(self._exec_builder)
        self.ui.centerStack.addWidget(page)
        self._exec_page = page
        # 确认索引与 IMPLEMENTED 一致（.ui 现有 3 页 -> 新页索引 3）
        IMPLEMENTED["execute"] = self.ui.centerStack.indexOf(page)

    def _build_generic_form(self, cmd: str):
        """在 pageGeneric 内为 cmd 建表单（替换旧表单）。"""
        old = getattr(self, "_form", None)
        if old is not None:
            self.ui.genericFormHostLayout.removeWidget(old)
            old.setParent(None)
            old.deleteLater()
        self._form = CF.CommandForm(cmd)
        self._form.changed.connect(self._refresh)
        self.ui.genericFormHostLayout.addWidget(self._form)
        self.ui.genericTitle.setText(self._form.spec.get("title", cmd))

    # ------------------------------------------------------------------
    # 组件卡片
    # ------------------------------------------------------------------
    def _add_component(self, cid=None):
        """添加组件卡片。

        **注意 Qt 的 clicked 信号**：`QPushButton.clicked` 会带一个
        `checked: bool` 实参。若直接 `clicked.connect(self._add_component)`，
        点按钮时 cid 会收到 `False`（而不是 None），导致
        `if cid is None` 判断失效、函数提前返回 —— 表现为「点添加没反应」。
        故连接处必须用 lambda 丢弃该实参（见 _connect）。
        """
        if cid is None or cid is False or cid is True:
            cid = self.ui.giveCompCombo.currentData()
        if not cid or cid in self._cards:
            return
        self._make_card(cid)
        self._refresh()

    def _make_card(self, cid: str):
        """创建组件卡片并插入到 host 布局（spacer 之前）。"""
        box = QGroupBox(f"{C.label_of(cid)}  minecraft:{cid}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        editor = CE.build_editor(cid)
        # set_value 期间不触发刷新
        editor.changed.connect(self._refresh)
        lay.addWidget(editor)

        head = QHBoxLayout()
        head.addStretch(1)
        rm = QPushButton("移除组件")
        rm.clicked.connect(lambda _=False, c=cid: self._remove_component(c))
        head.addWidget(rm)
        lay.addLayout(head)

        host_lay = self.ui.giveCompHostLayout
        host_lay.insertWidget(host_lay.count() - 1, box)
        self._cards[cid] = (box, editor)
        return editor

    def _remove_component(self, cid: str):
        item = self._cards.pop(cid, None)
        if not item:
            return
        box, _ed = item
        self.ui.giveCompHostLayout.removeWidget(box)
        box.setParent(None)
        box.deleteLater()
        self._refresh()

    def _components(self) -> dict:
        out = {}
        for cid, (_box, ed) in self._cards.items():
            try:
                v = ed.value()
            except Exception:                     # noqa: BLE001
                v = None
            if v is None or v is False:
                continue
            out[cid] = v
        return out

    def _missing_component_fields(self) -> list:
        """收集各卡片未填的**必填**字段，供校验区提示。

        如 container_loot.loot_table、tool.rules 无法猜默认值，
        缺了游戏会拒绝解析该组件。
        """
        msgs = []
        for cid, (_box, ed) in self._cards.items():
            try:
                miss = ed.missing_required()
            except Exception:                     # noqa: BLE001
                miss = []
            for k in miss or []:
                msgs.append(f"⚠ {C.label_of(cid)}：必填字段 "
                            f"{k} 未填，该组件会被解析失败")
        return msgs

    # ------------------------------------------------------------------
    # 参数收集 / 刷新
    # ------------------------------------------------------------------
    def _params(self) -> dict:
        u = self.ui
        item = u.giveItemCombo.currentData()
        if not item:
            # 用户手输的文本
            txt = u.giveItemCombo.currentText().strip()
            item = txt.split("（")[-1].rstrip("）") if "（" in txt else txt
        return {
            "targets": u.giveTargetCombo.currentText().strip() or "@p",
            "item": item or "stone",
            "count": u.giveCountSpin.value(),
            "components": self._components(),
            "ns_prefix": u.nsPrefixCheck.isChecked(),
        }

    def _refresh(self):
        if self._busy:
            return
        self._busy = True
        try:
            cmd = self._current_cmd()
            u = self.ui
            ver = u.versionCombo.currentText()
            if cmd == "give":
                params = self._params()
                params["ns_prefix"] = u.nsPrefixCheck.isChecked()
                text = G.give(params, ver)
                u.outputEdit.setPlainText(text)
                u.outputLenLabel.setText(
                    f"长度 {len(text)} / {MAX_CMD_LEN}")
                self._update_preview(params)
                self._update_checks(text, params, ver)
            elif cmd == "execute":
                builder = getattr(self, "_exec_builder", None)
                if builder is None:
                    return
                from Utils.CommandGenerator import execute_cmd as EX
                chains = builder.chains()
                text = EX.serialize_chain(
                    chains, ver, u.nsPrefixCheck.isChecked())
                u.outputEdit.setPlainText(text)
                u.outputLenLabel.setText(
                    f"长度 {len(text)} / {MAX_CMD_LEN}")
                self._update_exec_preview(chains)
                self._update_exec_checks(text, chains, ver)
            elif cmd in IMPLEMENTED and cmd in CS.SPECS:
                form = getattr(self, "_form", None)
                if form is None or form.cmd != cmd:
                    return
                params = form.params()
                params["ns_prefix"] = u.nsPrefixCheck.isChecked()
                text = K.serialize(cmd, params, ver)
                u.outputEdit.setPlainText(text)
                u.outputLenLabel.setText(
                    f"长度 {len(text)} / {MAX_CMD_LEN}")
                self._update_generic_preview(cmd, params)
                self._update_generic_checks(cmd, text, params, ver)
        finally:
            self._busy = False

    # ------------------------------------------------------------------
    # execute 专用页的预览与校验
    # ------------------------------------------------------------------
    def _update_exec_preview(self, chains: list):
        from Utils.CommandGenerator import execute_cmd as EX
        u = self.ui
        names = []
        for ch in chains:
            op = ch.get("op", "")
            for _g, ops in EX.OP_GROUPS:
                for val, label in ops:
                    if val == op:
                        names.append(label)
                        break
        u.previewName.setText("execute 链")
        u.previewSub.setText(f"共 {len(chains)} 段")
        u.previewEnch.setText("\n".join(
            f"{i}. {n}" for i, n in enumerate(names, 1)))
        u.previewIcon.setPixmap(QPixmap())
        u.previewIcon.setText("—")

    def _update_exec_checks(self, text: str, chains: list, ver: str):
        u = self.ui
        errors = []
        warns = []
        if text.count("[") != text.count("]"):
            errors.append("✗ 方括号不配平")
        if text.count("{") != text.count("}"):
            errors.append("✗ 花括号不配平")
        if len(text) > MAX_CMD_LEN:
            errors.append(f"✗ 超过指令长度上限 {MAX_CMD_LEN}")

        ops = [c.get("op") for c in chains]
        if not ops:
            errors.append("✗ 链为空（至少需要 run 一段）")
        else:
            # run 必须在最后且只能一个
            if ops.count("run") == 0:
                errors.append("✗ 缺少收尾的 run 子命令")
            elif ops[-1] != "run":
                errors.append("✗ run 必须是最后一段")
            if ops.count("run") > 1:
                errors.append("✗ 只能有一个 run")
            # store 一般与 run 搭配
            if "store" in ops[:-1] and ops[-1] == "run":
                pass
            # 条件段的位置提示
            for i, op in enumerate(ops):
                if op in ("as", "at") and i > 0 and \
                        any(o.startswith(("if_", "unless_"))
                            for o in ops[:i]):
                    warns.append(
                        f"⚠ 第 {i + 1} 段 {op} 位于条件之后"
                        "（条件会先求值，可能非本意）")
                    break
            if ops.count("run") == 1 and len(ops) == 1:
                warns.append("⚠ 只有 run：等价于直接执行该指令")

        if not errors:
            errors.append(f"✓ 语法有效（目标版本 {ver}）")
        u.checkTitleLabel.setText(errors[0] if errors else "")
        u.checkList.clear()
        for m in errors[1:] + warns:
            u.checkList.addItem(m)

    def _update_preview(self, params: dict):
        u = self.ui
        iid = params["item"]
        cn = IL.ITEM_CN.get(iid, "")
        en = IL.ITEM_NAMES.get(iid, "")
        u.previewName.setText(cn or en or iid)
        u.previewSub.setText(f"{en} · minecraft:{iid}" if cn else
                             f"minecraft:{iid}")

        # 图标
        p = os.path.join(_ICON_DIR, f"{iid}.png")
        if os.path.exists(p):
            pm = QPixmap(p).scaled(
                64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            u.previewIcon.setPixmap(pm)
        else:
            u.previewIcon.setPixmap(QPixmap())
            u.previewIcon.setText("无图标")

        # 附魔/描述摘要
        lines = []
        ench = params["components"].get("enchantments") or \
            params["components"].get("stored_enchantments") or {}
        by = CE.enchant_by_id()
        if isinstance(ench, dict):
            for eid, lvl in ench.items():
                e = by.get(eid, {})
                lines.append(f'{e.get("name", eid)} {"I" * min(int(lvl), 10)}')
        lore = params["components"].get("lore") or []
        if isinstance(lore, (list, tuple)):
            lines.extend(str(x) for x in lore)
        u.previewEnch.setText("\n".join(lines))

    def _update_checks(self, text: str, params: dict, ver: str):
        u = self.ui
        errors = []
        warns = []

        # 括号配平
        if text.count("[") != text.count("]"):
            errors.append("✗ 组件方括号不配平")
        if text.count("{") != text.count("}"):
            errors.append("✗ 花括号不配平")
        # 长度
        if len(text) > MAX_CMD_LEN:
            errors.append(f"✗ 超过指令长度上限 {MAX_CMD_LEN}")
        # 目标 / 物品
        if not params["targets"].startswith("@"):
            warns.append("⚠ 目标不是以 @ 开头的选择器（玩家名也可）")
        if params["count"] < 1:
            errors.append("✗ 数量必须 >= 1")
        if params["count"] > 6400:
            warns.append("⚠ 数量超过 6400（64 组），游戏内会被限制")

        # 附魔校验
        ench = params["components"].get("enchantments")
        src = "enchantments" if ench else (
            "stored_enchantments"
            if params["components"].get("stored_enchantments") else None)
        if src:
            ench = params["components"][src]
            by = CE.enchant_by_id()
            ids = list(ench.keys())
            for eid in ids:
                e = by.get(eid)
                if not e:
                    warns.append(f"⚠ 未知附魔：{eid}")
                    continue
                lvl = int(ench[eid])
                mx = int(e.get("max_level", 255) or 255)
                if lvl > mx:
                    warns.append(
                        f'⚠ {e.get("name", eid)} 等级 {lvl} 超过上限 {mx}')
                for c in e.get("conflicts", []) or []:
                    if c in ids and c > eid:
                        warns.append(
                            f'⚠ {e.get("name", eid)} 与 '
                            f'{by.get(c, {}).get("name", c)} 互斥')
            if src == "stored_enchantments" and \
                    params["item"] != "enchanted_book":
                warns.append("⚠ stored_enchantments 通常仅用于附魔书")

        # 组件必填字段缺失（无法猜默认值的那几个）
        miss_msgs = self._missing_component_fields()
        if miss_msgs:
            errors.append("✗ 有组件缺少必填字段")
            warns = miss_msgs + warns

        if not errors:
            errors.append(f"✓ 语法有效（目标版本 {ver}）")

        u.checkTitleLabel.setText(errors[0] if errors else "")
        u.checkList.clear()
        for m in errors[1:] + warns:
            u.checkList.addItem(m)

    # ------------------------------------------------------------------
    # 通用页的预览与校验
    # ------------------------------------------------------------------
    def _update_generic_preview(self, cmd: str, params: dict):
        """通用页预览：按指令给出有意义的摘要。"""
        u = self.ui
        name, sub, icon = cmd, "", ""
        lines = []

        if cmd == "enchant":
            from Utils.CommandGenerator import comp_editors as _CE
            eid = params.get("enchantment") or ""
            e = _CE.enchant_by_id().get(eid, {})
            name = e.get("name", eid or "附魔")
            sub = f"{eid} · 等级 {params.get('level') or 1}"
            lines.append(e.get("description", ""))
        elif cmd == "effect":
            eid = params.get("effect") or ""
            from Utils.CommandGenerator import resource_lists as _RL
            name = _RL.EFFECT_CN.get(eid, eid or "状态效果")
            br = params.get("branch", "give")
            if br == "give":
                secs = params.get("seconds")
                sec_txt = f"{secs} 秒" if secs is not None else "默认时长"
                lvl = (params.get("amplifier") or 0) + 1
                sub = f"{eid} · {sec_txt} · 等级 {lvl}"
            elif br == "infinite":
                lvl = (params.get("amplifier") or 0) + 1
                sub = f"{eid} · 无限时长 · 等级 {lvl}"
            else:
                sub = f"清除 {eid or '全部效果'}"
        elif cmd == "summon":
            eid = params.get("entity") or ""
            from Utils.CommandGenerator import resource_lists as _RL
            name = _RL.ENTITY_CN.get(eid, eid or "实体")
            sub = eid
        elif cmd == "locate":
            br = params.get("branch", "structure")
            tgt = params.get("target") or ""
            from Utils.CommandGenerator import struct_list as _SL
            from Utils.CommandGenerator import resource_lists as _RL
            if br == "structure":
                name = _SL.STRUCT_CN.get(tgt, tgt)
            elif br == "biome":
                name = _RL.BIOME_CN.get(tgt, tgt)
            else:
                name = CS.POI_NOTE.get(tgt, tgt)
                sub = tgt
            sub = sub or tgt
        elif cmd in ("setblock", "fill"):
            bid = (params.get("block") or "").split("[")[0]
            name = IL.ITEM_CN.get(bid, bid)
            if cmd == "fill":
                sub = f"{params.get('from')} → {params.get('to')} · " \
                      f"{params.get('mode')}"
            else:
                sub = f"{params.get('pos')} · {params.get('mode')}"
            icon = bid
        elif cmd == "kill":
            name = "杀死实体"
            sub = params.get("targets") or "（命令执行者自身）"

        u.previewName.setText(name)
        u.previewSub.setText(sub)
        u.previewEnch.setText("\n".join(x for x in lines if x))

        # 图标：物品类指令尝试按物品 id 找图标
        cand = icon or (params.get("entity") if cmd == "summon" else "") \
            or (params.get("enchantment") if cmd == "enchant" else "")
        p = os.path.join(_ICON_DIR, f"{cand}.png") if cand else ""
        if p and os.path.exists(p):
            u.previewIcon.setPixmap(QPixmap(p).scaled(
                64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            u.previewIcon.setPixmap(QPixmap())
            u.previewIcon.setText("—")

    def _update_generic_checks(self, cmd: str, text: str, params: dict,
                               ver: str):
        """通用页校验：括号配平 / 长度 / 指令特定项。"""
        u = self.ui
        errors = []
        warns = []

        if text.count("[") != text.count("]"):
            errors.append("✗ 方括号不配平")
        if text.count("{") != text.count("}"):
            errors.append("✗ 花括号不配平")
        if len(text) > MAX_CMD_LEN:
            errors.append(f"✗ 超过指令长度上限 {MAX_CMD_LEN}")

        tgt = params.get("targets")
        if tgt and not str(tgt).startswith("@"):
            warns.append("⚠ 目标不是以 @ 开头的选择器（玩家名也可）")

        if cmd == "effect":
            br = params.get("branch")
            secs = params.get("seconds")
            if br == "give" and secs is not None and secs < 1:
                errors.append("✗ 时长须 >= 1 秒（源码 integer(1,1000000)）")
            if br == "infinite":
                warns.append("⚠ infinite 无时长参数（源码 L131）")

        if cmd == "enchant":
            eid = params.get("enchantment") or ""
            from Utils.CommandGenerator import comp_editors as _CE
            e = _CE.enchant_by_id().get(eid)
            if not e:
                warns.append(f"⚠ 未知附魔 id：{eid}")
            else:
                lvl = params.get("level")
                if lvl is not None and lvl > int(e.get("max_level", 255)):
                    warns.append(
                        f'⚠ {e.get("name", eid)} 等级 {lvl} 超过'
                        f'上限 {e.get("max_level")}')
                warns.append("⚠ enchant 只对**手持**物品生效"
                             "（命令执行者需手持目标物品）")

        if cmd == "fill":
            frm, to = params.get("from"), params.get("to")
            if frm and to:
                warns.append("⚠ 单次填充上限 32768 方块，超限会报错")
            if params.get("filter") and params.get("mode") != "replace":
                warns.append("⚠ 过滤仅对 replace 模式有效，当前模式会忽略")

        if cmd == "summon":
            nbt = params.get("nbt")
            if nbt and not (str(nbt).startswith("{")
                            and str(nbt).endswith("}")):
                errors.append("✗ NBT 必须是 {…} 复合标签")

        if cmd == "locate":
            tgt = str(params.get("target") or "")
            if tgt.startswith("#"):
                warns.append("⚠ 使用标签（#）时会定位到该类中最近的一个")

        if not errors:
            errors.append(f"✓ 语法有效（目标版本 {ver}）")

        u.checkTitleLabel.setText(errors[0] if errors else "")
        u.checkList.clear()
        for m in errors[1:] + warns:
            u.checkList.addItem(m)

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------
    def _copy(self):
        QApplication.clipboard().setText(self.ui.outputEdit.toPlainText())
        self.request_status_message.emit("指令已复制到剪贴板")

    def _clear(self):
        """清空当前指令的参数（give 清组件卡片，通用页重建表单）。"""
        cmd = self._current_cmd()
        if cmd == "give":
            for cid in list(self._cards):
                self._remove_component(cid)
            self.ui.giveCountSpin.setValue(1)
            self.ui.giveTargetCombo.setCurrentText("@p")
        else:
            form = getattr(self, "_form", None)
            if form is not None:
                form.reset()
        self._refresh()

    def _selector_dialog(self):
        """简易选择器构造（在文本框中直接编辑）。"""
        from PySide6.QtWidgets import QInputDialog
        cur = self.ui.giveTargetCombo.currentText()
        txt, ok = QInputDialog.getText(
            self, "选择器", "目标选择器（例：@e[type=zombie,limit=3]）：",
            text=cur)
        if ok and txt.strip():
            self.ui.giveTargetCombo.setCurrentText(txt.strip())

    def _pick_item(self):
        """按中文名/英文 id 搜索物品。"""
        from PySide6.QtWidgets import QInputDialog
        kw, ok = QInputDialog.getText(
            self, "选择物品", "输入中文名或英文 id 关键字：")
        if not ok or not kw.strip():
            return
        k = kw.strip().lower()
        hits = [i for i in IL.ITEM_IDS
                if k in i.lower() or k in IL.ITEM_CN.get(i, "").lower()]
        if not hits:
            QMessageBox.information(self, "选择物品", "没有匹配的物品。")
            return
        if len(hits) == 1:
            self._set_item(hits[0])
            return
        labels = [f'{IL.ITEM_CN.get(i, "")}（{i}）' if IL.ITEM_CN.get(i)
                  else i for i in hits[:80]]
        txt, ok = QInputDialog.getItem(
            self, "选择物品", f"匹配到 {len(hits)} 项（显示前 80）：",
            labels, 0, False)
        if ok and txt:
            self._set_item(hits[labels.index(txt)])

    def _set_item(self, iid: str):
        cb = self.ui.giveItemCombo
        i = cb.findData(iid)
        if i >= 0:
            cb.setCurrentIndex(i)
        else:
            cb.setCurrentText(iid)
        self._refresh()

    # ------------------------------------------------------------------
    @classmethod
    def tool_name(cls) -> str:
        return "指令生成器"
