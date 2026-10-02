# -*- coding: utf-8 -*-
"""「查找物品」定位窗口控制器（ChooseTargetItemWin.ui 弹窗）。

- 物品下拉：可编辑 + QCompleter 输入匹配（中文名/短 ID 子串过滤）；
- 结构下拉：选择物品后只显示该物品可能产出的结构，「无」= 全候选最近；
- 「开始查找」：后台线程遍历候选结构实例，RNG 校验箱子是否产出目标物品，
  返回最近命中，展示详细信息（结构名/坐标/距离/命中箱子与表）；
- 「导入预览」：把命中结果交给 StructurePreviewer：置种子/结构/坐标、
  加载该实例预览，并把命中箱子高亮（琥珀描边）。
"""

import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QComboBox, QCompleter, QDialog,
                               QPushButton)

from CodesUI.ChooseTargetItemWin import Ui_previewBtn
from Utils.Public import structure_icons as struct_icons
from . import catalog, search

# 搜索半径（方块；与预览器 _LOCATE_RADIUS 一致）
_RADIUS = 4096

# 物品图标目录（16x16 原版纹理，与 StructurePreviewer 展示同源）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_ITEM_ICON_DIR = os.path.join(_ROOT, "assets", "StructurePreviewer", "items")


def _item_icon(item_full: str) -> QIcon:
    """物品全名 -> 16x16 原版图标（无图标回退空 QIcon）。"""
    short = item_full.split(":", 1)[-1]
    p = os.path.join(_ITEM_ICON_DIR, short + ".png")
    if os.path.exists(p):
        icon = QIcon(p)
        if not icon.isNull():
            return icon
    return QIcon()


def _struct_icon(ui_key: str) -> QIcon:
    """UI 结构键 -> 结构图标（cubiomes 键查图标表）。"""
    p = struct_icons.icon_path(catalog.enum_key(ui_key))
    if p:
        icon = QIcon(p)
        if not icon.isNull():
            return icon
    return QIcon()


class _FindThread(QThread):
    """后台搜索线程：跑 search.find_nearest，避免阻塞 UI。"""

    progress = Signal(int, int, str)      # done, total, stage
    done = Signal(object)                 # 命中结果 dict | None
    failed = Signal(str)

    def __init__(self, seed: int, version: str, struct_key: str | None,
                 item_full: str, cx: int, cz: int, parent=None):
        super().__init__(parent)
        self._seed = seed
        self._version = version
        self._struct = struct_key
        self._item = item_full
        self._cx = cx
        self._cz = cz
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            res = search.find_nearest(
                self._seed, self._version, self._struct, self._item,
                self._cx, self._cz, radius=_RADIUS,
                on_progress=lambda d, t, s: self.progress.emit(d, t, s),
                cancel=lambda: self._cancel,
                first_hit=True)
            if not self._cancel:
                self.done.emit(res)
        except search.FindCancelled:
            pass
        except Exception as exc:
            if not self._cancel:
                self.failed.emit(str(exc))


class ChooseItemDialog(QDialog, Ui_previewBtn):
    """物品定位弹窗。previewer 为 StructurePreviewerWidget（取种子/版本/导入）。"""

    def __init__(self, previewer, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowTitle("定位物品")
        self._previewer = previewer
        self._thread: _FindThread | None = None
        self._result: dict | None = None
        # 物品目录 [(显示名, 物品全名), ...]
        self._items = catalog.all_items()

        self._build_item_combo()
        self._refresh_structure_combo()
        self.importPreviewBtn.setEnabled(False)

        # 查找结构变化时刷新结构下拉提示文案
        self.targetItemCombo.lineEdit().textEdited.connect(
            self._on_item_text_edited)
        self.targetItemCombo.lineEdit().editingFinished.connect(
            self._on_item_editing_finished)
        self.doFindBtn.clicked.connect(self._on_find_click)
        self.importPreviewBtn.clicked.connect(self._on_import)
        self.cancelBtn.clicked.connect(self.reject)

    # ---------- 物品下拉（可编辑 + 输入匹配） ----------
    def _build_item_combo(self) -> None:
        combo = self.targetItemCombo
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setMaxVisibleItems(12)
        for label, full in self._items:
            combo.addItem(_item_icon(full), label)
        # 初始不预选任何物品（空输入）：结构下拉保持全部，等用户选物品再过滤
        combo.setCurrentIndex(-1)
        if combo.lineEdit() is not None:
            combo.lineEdit().setText("")
        completer = QCompleter([label for label, _ in self._items], combo)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        combo.setCompleter(completer)

    def _on_item_text_edited(self, text: str) -> None:
        """输入变化：重算物品解析并刷新结构下拉。"""
        self._refresh_structure_combo()

    def _on_item_editing_finished(self) -> None:
        self._refresh_structure_combo()

    def _resolve_item(self) -> str | None:
        """把下拉当前文本解析为物品全名（None=未匹配到唯一物品）。"""
        text = (self.targetItemCombo.currentText() or "").strip()
        if not text:
            return None
        for label, full in self._items:
            if label == text:
                return full
        low = text.lower()
        for label, full in self._items:
            if full.split(":", 1)[-1] == low:
                return full
        matches = [full for label, full in self._items
                   if low in label.lower() or low in full]
        return matches[0] if len(matches) == 1 else None

    def _refresh_structure_combo(self) -> None:
        """结构下拉：物品解析后只显示该物品可能的生成结构；否则全部。

        首项「无（自动：最近）」data=None，即留空搜索 = 全候选最近。
        """
        combo = self.targetStructureCombo
        item_full = self._resolve_item()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("无（自动：最近）", None)
        if item_full is not None:
            keys = catalog.structures_for_item(item_full)
        else:
            keys = catalog.ALL_STRUCT_KEYS
        for k in keys:
            combo.addItem(_struct_icon(k), catalog.struct_name(k), k)
        combo.blockSignals(False)

    # ---------- 查找 ----------
    def _on_find_click(self) -> None:
        """按钮统一入口：查找中则停止，否则开始查找。"""
        th = self._thread
        if th is not None and th.isRunning():
            th.request_cancel()
            self.doFindBtn.setEnabled(False)
            self.informationBrowser.setPlainText("正在停止查找…")
            return
        self._on_find()

    def _on_find(self) -> None:
        pv = self._previewer
        if pv is None:
            return
        try:
            seed = pv._parse_seed(pv.seedEdit.text())
        except ValueError as e:
            self.informationBrowser.setPlainText(str(e))
            return
        item = self._resolve_item()
        if item is None:
            self.informationBrowser.setPlainText(
                "请先在「目标物品」输入或选择一个物品（可输入中文名/ID 匹配）")
            return
        try:
            cx = pv._parse_int(self.XEdit.text(), "X", 0)
            cz = pv._parse_int(self.ZEdit.text(), "Z", 0)
        except ValueError as e:
            self.informationBrowser.setPlainText(str(e))
            return
        struct = self.targetStructureCombo.currentData()
        version = pv.versionCombo.currentText()

        self._result = None
        self.importPreviewBtn.setEnabled(False)
        self.informationBrowser.setPlainText("正在查找最近命中实例…")
        self.doFindBtn.setText("停止查找")
        self._thread = _FindThread(seed, version, struct, item, cx, cz,
                                   parent=self)
        self._thread.progress.connect(self._on_progress)
        self._thread.done.connect(self._on_done)
        self._thread.failed.connect(self._on_fail)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_thread_finished(self) -> None:
        """查找线程结束（含取消）：按钮恢复为「开始查找」。"""
        self.doFindBtn.setText("开始查找")
        self.doFindBtn.setEnabled(True)

    def _on_progress(self, done: int, total: int, stage: str) -> None:
        self.informationBrowser.setPlainText(
            f"搜索中 {done}/{total}：{stage}…")

    def _on_fail(self, msg: str) -> None:
        self.informationBrowser.setPlainText(f"查找失败：{msg}")

    def _on_done(self, res: dict | None) -> None:
        self._thread = None
        if res is None:
            self.informationBrowser.setPlainText(
                f"半径 {_RADIUS} 方块内未找到实际产出该物品的结构实例")
            return
        self._result = res
        self.importPreviewBtn.setEnabled(True)
        lines = [
            "找到最近命中实例：",
            f"  结构：{res['struct_name']}（变体 {res['variant']}）",
            f"  锚点：({res['x']}, {res['z']})",
            f"  距起点约：{res['distance'] ** 0.5:.0f} 方块",
        ]
        lines.append(f"  命中箱子 {len(res['hits'])} 个：")
        for h in res["hits"]:
            lines.append(
                f"    箱{h['chest_num']}（{h['table']}）@ {h['pos']}｜"
                f"LootTableSeed {h['seed_signed']}")
        self.informationBrowser.setPlainText("\n".join(lines))

    # ---------- 导入预览 ----------
    def _on_import(self) -> None:
        if self._result is None:
            return
        pv = self._previewer
        if pv is None:
            return
        pv.apply_item_preview(self._result)
        self.accept()

    # ---------- 关闭钩子 ----------
    def done(self, r) -> None:  # noqa: N802
        th = self._thread
        if th is not None and th.isRunning():
            th.request_cancel()
            th.wait(3000)
        super().done(r)