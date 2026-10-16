# -*- coding: utf-8 -*-
"""holder / 列表 / 物品列表类组件的结构化编辑器（第二批）。

覆盖 26 个此前只有 SNBT 兜底的组件。所有编辑器继承
comp_editors._Editor（提供 changed 信号与 cid），保证与
「组件卡片」机制兼容（value()/set_value()/missing_required()）。

值形态依据（源码核对见 .temp/gap_detail.out）：
  HolderEditor      裸资源 id（4307+；give.py 处理 1.21 包装）
  ItemListEditor    List<ItemStack> / List<Item>
  ContainerEditor   ItemContainerContents = List<Slot{slot,item}>
  StewEditor        List<Entry{effect,duration}>
  BannerEditor      List<Layer{pattern,color}>
  BlockStateEditor  Map<String,String>
  MapDecoEditor     Map<id,Decoration{type,x,z,rotation}>
  PotionEditor      RecordCodec（potion/custom_color/custom_name）
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from Utils.CommandGenerator import comp_editors as _base
from Utils.CommandGenerator import resource_lists as RL
from Utils.CommandGenerator import item_list as IL
from Utils.CommandGenerator import snbt

_Editor = _base._Editor


# ---------------------------------------------------------------------------
# 资源下拉数据源
# ---------------------------------------------------------------------------

def resource_items(source: str):
    """(id, 显示名) 列表。"""
    mapping = {
        "sound": lambda: [(x, RL.SOUND_CN.get(x, x)) for x in RL.SOUND_IDS],
        "instrument": lambda: [(x, RL.INSTRUMENT_CN.get(x, x))
                               for x in RL.INSTRUMENT_IDS],
        "jukebox_song": lambda: [(x, RL.JUKEBOX_SONG_CN.get(x, x))
                                 for x in RL.JUKEBOX_SONG_IDS],
        "trim_material": lambda: [(x, RL.TRIM_MATERIAL_CN.get(x, x))
                                  for x in RL.TRIM_MATERIAL_IDS],
        "trim_pattern": lambda: [(x, RL.TRIM_PATTERN_CN.get(x, x))
                                 for x in RL.TRIM_PATTERN_IDS],
        "potion": lambda: [(x, RL.POTION_CN.get(x, x))
                           for x in RL.POTION_IDS],
        "effect": lambda: [(x, RL.EFFECT_CN.get(x, x))
                           for x in RL.EFFECT_IDS],
        "entity": lambda: [(x, RL.ENTITY_CN.get(x, x))
                           for x in RL.ENTITY_IDS],
        "biome": lambda: [(x, RL.BIOME_CN.get(x, x))
                          for x in RL.BIOME_IDS],
        "damage_type": lambda: [(x, RL.DAMAGE_TYPE_CN.get(x, x))
                                for x in getattr(RL, "DAMAGE_TYPE_IDS", [])],
        "item": lambda: [(x, IL.ITEM_CN.get(x, x)) for x in IL.ITEM_IDS],
    }
    fn = mapping.get(source)
    return fn() if fn else []


def _combo(source: str, allow_empty=True, editable=True):
    cb = QComboBox()
    cb.setEditable(editable)
    if allow_empty:
        cb.addItem("（不填）", "")
    for rid, label in resource_items(source):
        cb.addItem(label if label == rid else f"{label}（{rid}）", rid)
    cb.setCurrentIndex(0 if allow_empty else -1)
    return cb


def _strip_shell(text: str) -> str:
    """「中文名（id）」-> id。"""
    t = text.strip()
    if "（" in t and t.endswith("）"):
        t = t.split("（")[-1][:-1]
    return t


# ---------------------------------------------------------------------------
# holder：单选资源
# ---------------------------------------------------------------------------

class HolderEditor(_Editor):
    """单选资源 id。value() -> str 或 None。

    覆盖：break_sound / damage_type / instrument / jukebox_playable /
          provides_trim_material
    （4307+ 为裸值；1.21 的包装由 give._wrap_if_needed 处理）
    """

    def __init__(self, cid, source, parent=None):
        super().__init__(cid, parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.combo = _combo(source, allow_empty=True)
        self.combo.currentIndexChanged.connect(self._emit)
        self.combo.editTextChanged.connect(self._emit)
        lay.addWidget(self.combo, 1)

    def value(self):
        d = self.combo.currentData()
        if d:
            return d
        t = _strip_shell(self.combo.currentText())
        return t or None

    def set_value(self, v):
        if v is None:
            return
        i = self.combo.findData(str(v))
        if i >= 0:
            self.combo.setCurrentIndex(i)
        else:
            self.combo.setCurrentText(str(v))


# ---------------------------------------------------------------------------
# 通用「列表 + 子控件列」表
# ---------------------------------------------------------------------------

class _ListTableEditor(_Editor):
    """列表组件的通用表格骨架：子类定义列与取值。"""

    COLS = []            # [(标题, 宽度策略, 控件工厂名)]
    MAX_H = 170
    MIN_H = 72

    def __init__(self, cid, parent=None, add_label="添加"):
        super().__init__(cid, parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(4)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([c[0] for c in self.COLS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.table.setMinimumHeight(self.MIN_H)
        self.table.setMaximumHeight(self.MAX_H)
        hh = self.table.horizontalHeader()
        for i, (_t, mode, _f) in enumerate(self.COLS):
            hh.setSectionResizeMode(i, mode)
            if mode == QHeaderView.ResizeMode.Fixed:
                self.table.setColumnWidth(i, c[2]) if False else None
        self._lay.addWidget(self.table)
        row = QHBoxLayout()
        self.add_btn = QPushButton(add_label)
        self.add_btn.clicked.connect(lambda: self._add())
        row.addWidget(self.add_btn)
        row.addStretch(1)
        self._lay.addLayout(row)
        self._wire_widths()

    def _wire_widths(self):
        # Fixed 列的宽度来自 COLS 里第三项
        for i, (_t, mode, w) in enumerate(self.COLS):
            if mode == QHeaderView.ResizeMode.Fixed:
                self.table.setColumnWidth(i, w)

    # -- 子类实现 --
    def _add(self, *args, **kw):
        raise NotImplementedError

    def _row_values(self, r):
        raise NotImplementedError

    def _set_row(self, r, val):
        raise NotImplementedError

    # -- 通用 --
    def _remove(self, btn):
        for r in range(self.table.rowCount()):
            w = self.table.cellWidget(r, self.COLS.index(
                next(c for c in self.COLS if c[1] ==
                     QHeaderView.ResizeMode.Fixed)))
            pass
        self.changed.emit()

    def value(self):
        out = []
        for r in range(self.table.rowCount()):
            v = self._row_values(r)
            if v is not None:
                out.append(v)
        return out or None

    def set_value(self, v):
        self.table.setRowCount(0)
        for x in (v or []):
            self._add(val=x)
        self.changed.emit()


# ---------------------------------------------------------------------------
# 物品列表（可选槽位）
# ---------------------------------------------------------------------------

class ItemListEditor(_ListTableEditor):
    """List<ItemStack> 或 List<Item>。

    覆盖：bundle_contents / charged_projectiles / pot_decorations
    （BundleContents.CODEC = ItemStack.CODEC.listOf()；
      ChargedProjectiles 同；PotDecorations = byNameCodec().sizeLimitedListOf(4)）
    """

    COLS = [("物品", QHeaderView.ResizeMode.Stretch, 0)]

    def __init__(self, cid, parent=None, max_items=None):
        super().__init__(cid, parent, add_label="添加物品")
        self.max_items = max_items
        row = QHBoxLayout()
        self.item_combo = _combo("item", allow_empty=True)
        self.item_combo.setMinimumWidth(220)
        row.addWidget(self.item_combo, 1)
        # 复用表的「添加」按钮：把它移到组合框旁更直观
        self.add_btn.setText("添加物品")
        self._lay.insertLayout(self._lay.count() - 1, row)

    def _add(self, val=None):
        if val is None:
            val = _strip_shell(self.item_combo.currentText()) or None
            if not val:
                return
        if self.max_items and self.table.rowCount() >= self.max_items:
            return
        r = self.table.rowCount()
        self.table.insertRow(r)
        cb = _combo("item", allow_empty=False)
        i = cb.findData(val)
        cb.setCurrentIndex(i if i >= 0 else 0)
        cb.currentIndexChanged.connect(self._emit)
        cb.editTextChanged.connect(self._emit)
        self.table.setCellWidget(r, 0, cb)
        if val is not None and self.item_combo.currentIndex() >= 0:
            self.item_combo.setCurrentIndex(0)
        self._emit()

    def _row_values(self, r):
        w = self.table.cellWidget(r, 0)
        if not w:
            return None
        t = _strip_shell(w.currentText())
        return t or None

    def _set_row(self, r, val):
        w = self.table.cellWidget(r, 0)
        if w:
            i = w.findData(val)
            w.setCurrentIndex(i if i >= 0 else 0)


# ---------------------------------------------------------------------------
# 容器槽位
# ---------------------------------------------------------------------------

class ContainerEditor(_ListTableEditor):
    """ItemContainerContents = List<Slot{slot:int 0-255, item:ItemStack}>"""

    COLS = [("槽位", QHeaderView.ResizeMode.Fixed, 64),
            ("物品", QHeaderView.ResizeMode.Stretch, 0)]

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent, add_label="添加槽位")
        row = QHBoxLayout()
        self.slot_spin = QSpinBox()
        self.slot_spin.setRange(0, 255)
        self.slot_spin.setPrefix("槽 ")
        row.addWidget(self.slot_spin)
        self.item_combo = _combo("item", allow_empty=True)
        self.item_combo.setMinimumWidth(200)
        row.addWidget(self.item_combo, 1)
        self._lay.insertLayout(self._lay.count() - 1, row)

    def _add(self, val=None):
        if isinstance(val, dict):
            idx = int(val.get("slot", 0))
            iid = val.get("item", "")
        else:
            idx = self.slot_spin.value()
            iid = _strip_shell(self.item_combo.currentText()) or ""
            if not iid:
                return
        r = self.table.rowCount()
        self.table.insertRow(r)
        sp = QSpinBox()
        sp.setRange(0, 255)
        sp.setValue(idx)
        sp.valueChanged.connect(self._emit)
        self.table.setCellWidget(r, 0, sp)
        cb = _combo("item", allow_empty=False)
        i = cb.findData(iid)
        cb.setCurrentIndex(i if i >= 0 else 0)
        cb.currentIndexChanged.connect(self._emit)
        cb.editTextChanged.connect(self._emit)
        self.table.setCellWidget(r, 1, cb)
        self._emit()

    def _row_values(self, r):
        sp = self.table.cellWidget(r, 0)
        cb = self.table.cellWidget(r, 1)
        if not (sp and cb):
            return None
        t = _strip_shell(cb.currentText())
        if not t:
            return None
        return {"slot": sp.value(), "item": t}

    def _set_row(self, r, val):
        pass        # set_value 走 _add(val=dict)


# ---------------------------------------------------------------------------
# 迷之炖菜
# ---------------------------------------------------------------------------

class StewEditor(_ListTableEditor):
    """SuspiciousStewEffects = List<Entry{effect:Holder<MobEffect>, duration}>"""

    COLS = [("效果", QHeaderView.ResizeMode.Stretch, 0),
            ("时长(秒)", QHeaderView.ResizeMode.Fixed, 96),
            ("", QHeaderView.ResizeMode.Fixed, 64)]

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent, add_label="添加效果")
        row = QHBoxLayout()
        self.fx_combo = _combo("effect", allow_empty=True)
        self.fx_combo.setMinimumWidth(200)
        row.addWidget(self.fx_combo, 1)
        self.dur_spin = QSpinBox()
        self.dur_spin.setRange(1, 3600)
        self.dur_spin.setValue(160)      # 官方默认（源码 lenientOptionalFieldOf("duration", 160)）
        row.addWidget(self.dur_spin)
        self._lay.insertLayout(self._lay.count() - 1, row)

    def _add(self, val=None):
        # Entry 键名以源码为准：**id**（不是 effect）+ duration
        # （SuspiciousStewEffects.Entry CODEC：
        #   MobEffect.CODEC.fieldOf("id")
        #   Codec.INT.lenientOptionalFieldOf("duration", 160)）
        if isinstance(val, dict):
            fx = val.get("id") or val.get("effect", "")
            dur = int(val.get("duration", 160))
        else:
            fx = _strip_shell(self.fx_combo.currentText()) or ""
            dur = self.dur_spin.value()
            if not fx:
                return
        r = self.table.rowCount()
        self.table.insertRow(r)
        cb = _combo("effect", allow_empty=False)
        i = cb.findData(fx)
        cb.setCurrentIndex(i if i >= 0 else 0)
        cb.currentIndexChanged.connect(self._emit)
        self.table.setCellWidget(r, 0, cb)
        sp = QSpinBox()
        sp.setRange(1, 3600)
        sp.setValue(dur)
        sp.valueChanged.connect(self._emit)
        self.table.setCellWidget(r, 1, sp)
        rm = QPushButton("移除")
        rm.clicked.connect(lambda: self._remove_row(rm))
        self.table.setCellWidget(r, 2, rm)
        self._emit()

    def _remove_row(self, btn):
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 2) is btn:
                self.table.removeRow(r)
                break
        self._emit()

    def _row_values(self, r):
        cb = self.table.cellWidget(r, 0)
        sp = self.table.cellWidget(r, 1)
        if not (cb and sp):
            return None
        t = _strip_shell(cb.currentText())
        if not t:
            return None
        # 键名 id/duration（源码 fieldOf），duration 默认 160
        return {"id": t, "duration": sp.value()}

    def _set_row(self, r, val):
        pass


# ---------------------------------------------------------------------------
# 旗帜图案
# ---------------------------------------------------------------------------

class BannerEditor(_ListTableEditor):
    """BannerPatternLayers = List<Layer{pattern, color}>"""

    COLS = [("图案", QHeaderView.ResizeMode.Stretch, 0),
            ("颜色", QHeaderView.ResizeMode.Fixed, 120),
            ("", QHeaderView.ResizeMode.Fixed, 64)]

    DYE_COLORS = ["white", "orange", "magenta", "light_blue", "yellow",
                  "lime", "pink", "gray", "light_gray", "cyan", "purple",
                  "blue", "brown", "green", "red", "black"]

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent, add_label="添加图案")
        row = QHBoxLayout()
        self.pat_combo = _combo("trim_pattern", allow_empty=True)
        # 旗帜图案是独立注册表，用 BANNER_PATTERN 清单
        self.pat_combo.clear()
        self.pat_combo.addItem("（不填）", "")
        from Utils.CommandGenerator import resource_lists as _RL
        for rid in _RL.BANNER_PATTERN_IDS:
            cn = _RL.BANNER_PATTERN_CN.get(rid, rid)
            self.pat_combo.addItem(cn if cn == rid else f"{cn}（{rid}）",
                                   rid)
        self.pat_combo.setCurrentIndex(0)
        self.pat_combo.setMinimumWidth(200)
        row.addWidget(self.pat_combo, 1)
        self.color_combo = QComboBox()
        for c in self.DYE_COLORS:
            self.color_combo.addItem(c, c)
        row.addWidget(self.color_combo)
        self._lay.insertLayout(self._lay.count() - 1, row)

    def _add(self, val=None):
        if isinstance(val, dict):
            pat = val.get("pattern", "")
            col = val.get("color", "white")
        else:
            pat = _strip_shell(self.pat_combo.currentText()) or ""
            col = self.color_combo.currentData()
            if not pat:
                return
        r = self.table.rowCount()
        self.table.insertRow(r)
        pcb = QComboBox()
        pcb.setEditable(True)
        pcb.addItem("（不填）", "")
        for rid in RL.BANNER_PATTERN_IDS:
            cn = RL.BANNER_PATTERN_CN.get(rid, rid)
            pcb.addItem(cn if cn == rid else f"{cn}（{rid}）", rid)
        i = pcb.findData(pat)
        pcb.setCurrentIndex(i if i >= 0 else 0)
        pcb.currentIndexChanged.connect(self._emit)
        pcb.editTextChanged.connect(self._emit)
        self.table.setCellWidget(r, 0, pcb)
        ccb = QComboBox()
        for c in self.DYE_COLORS:
            ccb.addItem(c, c)
        j = ccb.findData(col)
        ccb.setCurrentIndex(j if j >= 0 else 0)
        ccb.currentIndexChanged.connect(self._emit)
        self.table.setCellWidget(r, 1, ccb)
        rm = QPushButton("移除")
        rm.clicked.connect(lambda: self._remove_row(rm))
        self.table.setCellWidget(r, 2, rm)
        self._emit()

    def _remove_row(self, btn):
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 2) is btn:
                self.table.removeRow(r)
                break
        self._emit()

    def _row_values(self, r):
        pcb = self.table.cellWidget(r, 0)
        ccb = self.table.cellWidget(r, 1)
        if not (pcb and ccb):
            return None
        p = _strip_shell(pcb.currentText())
        if not p:
            return None
        return {"pattern": p, "color": ccb.currentData()}

    def _set_row(self, r, val):
        pass


# ---------------------------------------------------------------------------
# 方块状态（键值）
# ---------------------------------------------------------------------------

class BlockStateEditor(_Editor):
    """BlockItemStateProperties = Map<String,String>（状态属性名 -> 值）"""

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["属性", "值"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.table.setMinimumHeight(64)
        self.table.setMaximumHeight(150)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        self.k_edit = QLineEdit()
        self.k_edit.setPlaceholderText("属性名，如 facing")
        self.v_edit = QLineEdit()
        self.v_edit.setPlaceholderText("值，如 north")
        row.addWidget(self.k_edit, 1)
        row.addWidget(self.v_edit, 1)
        ab = QPushButton("添加")
        ab.clicked.connect(self._add)
        row.addWidget(ab)
        lay.addLayout(row)

    def _add(self, val=None):
        if isinstance(val, (list, tuple)) and len(val) == 2:
            k, v = val
        else:
            k = self.k_edit.text().strip()
            v = self.v_edit.text().strip()
            if not k:
                return
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(k))
        self.table.setItem(r, 1, QTableWidgetItem(v))
        self.k_edit.clear()
        self.v_edit.clear()
        self._emit()

    def value(self):
        out = {}
        for r in range(self.table.rowCount()):
            a = self.table.item(r, 0)
            b = self.table.item(r, 1)
            if a and a.text().strip():
                out[a.text().strip()] = b.text().strip() if b else ""
        return out or None

    def set_value(self, v):
        self.table.setRowCount(0)
        if isinstance(v, dict):
            for k, val in v.items():
                self._add((k, val))
        self._emit()


# ---------------------------------------------------------------------------
# 地图标记
# ---------------------------------------------------------------------------

class MapDecoEditor(_Editor):
    """MapDecorations = Map<id, Decoration{type,x,z,rotation}>"""

    DECO_TYPES = ["player", "frame", "red_x", "target_x", "player_off_map",
                  "player_off_limits", "mansion", "monument", "banner_white",
                  "banner_orange", "banner_magenta", "banner_light_blue",
                  "banner_yellow", "banner_lime", "banner_pink",
                  "banner_gray", "banner_light_gray", "banner_cyan",
                  "banner_purple", "banner_blue", "banner_brown",
                  "banner_green", "banner_red", "banner_black"]

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["标记 id", "类型", "X", "Z", "旋转°"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.table.setMinimumHeight(64)
        self.table.setMaximumHeight(150)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in (1, 2, 3, 4):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 130)
        for i in (2, 3, 4):
            self.table.setColumnWidth(i, 64)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("标记 id（自定）")
        self.type_combo = QComboBox()
        for t in self.DECO_TYPES:
            self.type_combo.addItem(t, t)
        row.addWidget(self.id_edit, 1)
        row.addWidget(self.type_combo)
        ab = QPushButton("添加")
        ab.clicked.connect(self._add)
        row.addWidget(ab)
        lay.addLayout(row)

    def _add(self, val=None):
        if isinstance(val, dict) and "type" in val:
            # {deco_id: {type,x,z,rotation}} 在 value() 里展平传入
            pass
        if isinstance(val, (list, tuple)) and len(val) == 5:
            did, dtype, x, z, rot = val
        else:
            did = self.id_edit.text().strip()
            dtype = self.type_combo.currentData()
            if not did:
                return
            x, z, rot = 0.0, 0.0, 0.0
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(did))
        tc = QComboBox()
        for t in self.DECO_TYPES:
            tc.addItem(t, t)
        i = tc.findData(dtype)
        tc.setCurrentIndex(i if i >= 0 else 0)
        tc.currentIndexChanged.connect(self._emit)
        self.table.setCellWidget(r, 1, tc)
        for c, v in ((2, x), (3, z), (4, rot)):
            it = QTableWidgetItem(str(v))
            self.table.setItem(r, c, it)
        self.id_edit.clear()
        self._emit()

    def value(self):
        out = {}
        for r in range(self.table.rowCount()):
            a = self.table.item(r, 0)
            if not a or not a.text().strip():
                continue
            tc = self.table.cellWidget(r, 1)
            x = self.table.item(r, 2)
            z = self.table.item(r, 3)
            rot = self.table.item(r, 4)
            try:
                xf = float(x.text()) if x else 0.0
                zf = float(z.text()) if z else 0.0
                rf = float(rot.text()) if rot else 0.0
            except ValueError:
                xf = zf = rf = 0.0
            out[a.text().strip()] = {"type": tc.currentData() if tc
                                     else "player", "x": xf, "z": zf,
                                     "rotation": rf}
        return out or None

    def set_value(self, v):
        self.table.setRowCount(0)
        if isinstance(v, dict):
            for did, d in v.items():
                if isinstance(d, dict):
                    self._add((did, d.get("type", "player"),
                               d.get("x", 0.0), d.get("z", 0.0),
                               d.get("rotation", 0.0)))
        self._emit()


# ---------------------------------------------------------------------------
# 头颅皮肤（profile）
# ---------------------------------------------------------------------------

class ProfileEditor(_Editor):
    """ResolvableProfile：玩家名 / UUID（二选一）。

    FULL_CODEC 是 withAlternative(FULL_CODEC, ExtraCodecs.PLAYER_NAME,
    createUnresolved) -> 最简形式就是**裸玩家名字符串**。
    """

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        r0 = QHBoxLayout()
        r0.addWidget(QLabel("玩家名（最简形式）"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("如 Notch；填了名字可留空 UUID")
        self.name_edit.textChanged.connect(self._emit)
        r0.addWidget(self.name_edit, 1)
        lay.addLayout(r0)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("UUID（可选）"))
        self.uuid_edit = QLineEdit()
        self.uuid_edit.setPlaceholderText("如 069a79f4-44e9-4726-a5be-fca90e38aaf5")
        self.uuid_edit.textChanged.connect(self._emit)
        r1.addWidget(self.uuid_edit, 1)
        lay.addLayout(r1)

    def value(self):
        name = self.name_edit.text().strip()
        uid = self.uuid_edit.text().strip()
        if not name and not uid:
            return None
        if name and not uid:
            return name                    # 裸字符串形式
        out = {}
        if name:
            out["name"] = name
        if uid:
            out["id"] = uid
        return out

    def set_value(self, v):
        if v is None:
            return
        if isinstance(v, str):
            self.name_edit.setText(v)
        elif isinstance(v, dict):
            self.name_edit.setText(str(v.get("name", "")))
            self.uuid_edit.setText(str(v.get("id", "")))


# ---------------------------------------------------------------------------
# 单 ItemStack（use_remainder / lock 用）
# ---------------------------------------------------------------------------

class ItemStackEditor(_Editor):
    """单个 ItemStack：物品 id + 数量。value() -> {id, count}。"""

    def __init__(self, cid, parent=None, with_count=True):
        super().__init__(cid, parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.combo = _combo("item", allow_empty=True)
        self.combo.currentIndexChanged.connect(self._emit)
        self.combo.editTextChanged.connect(self._emit)
        lay.addWidget(self.combo, 1)
        self.count_spin = None
        if with_count:
            lay.addWidget(QLabel("数量"))
            self.count_spin = QSpinBox()
            self.count_spin.setRange(1, 99)
            self.count_spin.setValue(1)
            self.count_spin.valueChanged.connect(self._emit)
            lay.addWidget(self.count_spin)

    def value(self):
        iid = _strip_shell(self.combo.currentText())
        if not iid:
            return None
        out = {"id": iid}
        if self.count_spin is not None:
            out["count"] = self.count_spin.value()
        return out

    def set_value(self, v):
        if not v:
            return
        iid = v.get("id") if isinstance(v, dict) else v
        i = self.combo.findData(str(iid))
        self.combo.setCurrentIndex(i if i >= 0 else 0)
        if isinstance(v, dict) and self.count_spin is not None:
            self.count_spin.setValue(int(v.get("count", 1)))


# ---------------------------------------------------------------------------
# 方块谓词列表（can_break / can_place_on）
# ---------------------------------------------------------------------------

class BlockPredicateListEditor(_Editor):
    """AdventureModePredicate = List<BlockPredicate>。

    compactListCodec 允许单元素简写；这里统一输出列表形式。
    BlockPredicate 完整形态复杂（blocks/state/nbt/tag/predicate），
    本编辑器覆盖最常用的 **方块 id 或 #标签**，其余走 SNBT 兜底行。
    """

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        hint = QLabel("每行一个方块 id 或 #标签（如 stone、#minecraft:logs）")
        hint.setStyleSheet("color:#888;font-size:11px;")
        lay.addWidget(hint)
        self.table = QTableWidget(0, 1)
        self.table.setHorizontalHeaderLabels(["方块/标签"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.table.setMinimumHeight(56)
        self.table.setMaximumHeight(130)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("stone 或 #minecraft:logs")
        row.addWidget(self.edit, 1)
        ab = QPushButton("添加")
        ab.clicked.connect(self._add)
        row.addWidget(ab)
        lay.addLayout(row)

    def _add(self, val=None):
        if val is None:
            val = self.edit.text().strip()
            if not val:
                return
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(str(val)))
        self.edit.clear()
        self._emit()

    def value(self):
        out = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and it.text().strip():
                out.append(it.text().strip())
        return out or None

    def set_value(self, v):
        self.table.setRowCount(0)
        for x in (v or []):
            self._add(x)
        self._emit()


# ---------------------------------------------------------------------------
# 配方列表（recipes）
# ---------------------------------------------------------------------------

class RecipeListEditor(_Editor):
    """List<ResourceKey<Recipe<?>>>：配方 id 列表（手输，官方无静态表）。

    value() 输出 ["minecraft:x", ...]（游戏按 List<ResourceKey> 解析）。
    """

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        hint = QLabel("每行一个配方 id（如 minecraft:cooked_beef）")
        hint.setStyleSheet("color:#888;font-size:11px;")
        lay.addWidget(hint)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("minecraft:xxx（回车添加）")
        self.edit.returnPressed.connect(self._add)
        lay.addWidget(self.edit)
        self.table = QTableWidget(0, 1)
        self.table.setHorizontalHeaderLabels(["配方 id"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.table.setMinimumHeight(56)
        self.table.setMaximumHeight(130)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table)

    def _add(self, val=None):
        if val is None:
            val = self.edit.text().strip()
            if not val:
                return
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(str(val)))
        self.edit.clear()
        self._emit()

    def value(self):
        out = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and it.text().strip():
                out.append(it.text().strip())
        return out or None

    def set_value(self, v):
        self.table.setRowCount(0)
        for x in (v or []):
            self._add(x)
        self._emit()


# ---------------------------------------------------------------------------
# 蜜蜂（bees）
# ---------------------------------------------------------------------------

class BeesEditor(_Editor):
    """Bees = List<BeehiveBlockEntity.Occupant>。

    Occupant CODEC（源码）：
        EntityData.CODEC.fieldOf("entity_data")
        Codec.INT.fieldOf("ticks_in_hive")
    EntityData 含 id/Health 等 NBT —— 完整编辑不现实，覆盖最常用：
        entity_data.id（实体 id）+ ticks_in_hive。
    """

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ["蜜蜂实体", "在巢刻数", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.table.setMinimumHeight(56)
        self.table.setMaximumHeight(120)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 100)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 64)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        self.bee_combo = _combo("entity", allow_empty=True)
        self.bee_combo.setMinimumWidth(200)
        row.addWidget(self.bee_combo, 1)
        self.ticks_spin = QSpinBox()
        self.ticks_spin.setRange(0, 100000000)
        self.ticks_spin.setValue(0)
        row.addWidget(self.ticks_spin)
        ab = QPushButton("添加蜜蜂")
        ab.clicked.connect(self._add)
        row.addWidget(ab)
        lay.addLayout(row)

    def _add(self, val=None):
        if isinstance(val, dict):
            eid = (val.get("entity_data") or {}).get("id", "bee") \
                if isinstance(val.get("entity_data"), dict) \
                else "bee"
            ticks = int(val.get("ticks_in_hive", 0))
        else:
            eid = _strip_shell(self.bee_combo.currentText()) or ""
            if not eid:
                return
            ticks = self.ticks_spin.value()
        r = self.table.rowCount()
        self.table.insertRow(r)
        cb = _combo("entity", allow_empty=False)
        i = cb.findData(eid)
        cb.setCurrentIndex(i if i >= 0 else 0)
        cb.currentIndexChanged.connect(self._emit)
        self.table.setCellWidget(r, 0, cb)
        sp = QSpinBox()
        sp.setRange(0, 100000000)
        sp.setValue(ticks)
        sp.valueChanged.connect(self._emit)
        self.table.setCellWidget(r, 1, sp)
        rm = QPushButton("移除")
        rm.clicked.connect(lambda: self._remove_row(rm))
        self.table.setCellWidget(r, 2, rm)
        self._emit()

    def _remove_row(self, btn):
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 2) is btn:
                self.table.removeRow(r)
                break
        self._emit()

    def value(self):
        out = []
        for r in range(self.table.rowCount()):
            cb = self.table.cellWidget(r, 0)
            sp = self.table.cellWidget(r, 1)
            if not (cb and sp):
                continue
            eid = _strip_shell(cb.currentText())
            if not eid:
                continue
            out.append({
                "entity_data": {"id": eid},
                "ticks_in_hive": sp.value(),
            })
        return out or None

    def set_value(self, v):
        self.table.setRowCount(0)
        for x in (v or []):
            self._add(x)
        self._emit()


class LockEditor(_Editor):
    """LockCode = ItemPredicate（箱子上锁的物品谓词）。

    ItemPredicate 完整形态复杂（含 count/potion/wearable 等）；
    覆盖最常用的**裸物品 id**简写（游戏接受 "minecraft:diamond"，
    等价于「持有该物品才能打开此容器」）。复杂谓词请退回 SNBT。
    """

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("开锁所需物品"))
        self.combo = _combo("item", allow_empty=True)
        self.combo.currentIndexChanged.connect(self._emit)
        self.combo.editTextChanged.connect(self._emit)
        lay.addWidget(self.combo, 1)

    def value(self):
        t = _strip_shell(self.combo.currentText())
        return t or None

    def set_value(self, v):
        if v is None:
            return
        i = self.combo.findData(str(v))
        self.combo.setCurrentIndex(i if i >= 0 else 0)


class PotionEditor(_Editor):
    """PotionContents = {potion?, custom_color?, custom_name?, custom_effects?}

    顶层 CODEC 是 withAlternative(FULL_CODEC, Potion.CODEC, ...)，
    即可只给一个裸 potion id。这里提供 potion + custom_color +
    custom_name 三项（custom_effects 走 SNBT 兜底）。
    """

    def __init__(self, cid, parent=None):
        super().__init__(cid, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        row0 = QHBoxLayout()
        row0.addWidget(QLabel("药水"))
        self.potion = _combo("potion", allow_empty=True)
        self.potion.currentIndexChanged.connect(self._emit)
        self.potion.editTextChanged.connect(self._emit)
        row0.addWidget(self.potion, 1)
        lay.addLayout(row0)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("自定义颜色"))
        self.color_edit = QLineEdit()
        self.color_edit.setPlaceholderText("RGB 整数，留空不填")
        self.color_edit.textChanged.connect(self._emit)
        row1.addWidget(self.color_edit, 1)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("自定义名称"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("留空不填")
        self.name_edit.textChanged.connect(self._emit)
        row2.addWidget(self.name_edit, 1)
        lay.addLayout(row2)

    def value(self):
        out = {}
        p = self.potion.currentData() or _strip_shell(
            self.potion.currentText())
        if p:
            out["potion"] = p
        ct = self.color_edit.text().strip()
        if ct:
            try:
                out["custom_color"] = int(ct, 0)
            except ValueError:
                pass
        nt = self.name_edit.text().strip()
        if nt:
            out["custom_name"] = nt
        return out or None

    def set_value(self, v):
        if not isinstance(v, dict):
            return
        i = self.potion.findData(v.get("potion", ""))
        self.potion.setCurrentIndex(i if i >= 0 else 0)
        cc = v.get("custom_color")
        self.color_edit.setText(str(cc) if cc is not None else "")
        self.name_edit.setText(str(v.get("custom_name", "")) if
                               v.get("custom_name") else "")
