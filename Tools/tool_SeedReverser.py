# -*- coding: utf-8 -*-
"""SeedReverser 工具：结构坐标逆推 48 位结构种 + 世界种子精化。

使用流程：
1. 在游戏中找到 3~6 个不同结构的坐标（推荐沉船——海滩常见、易辨认）；
2. 站在结构旁按 F3 读出 X/Z 坐标（或按 F3+C 复制后点「粘贴F3+C」）；
3. 勾选「群系模式」= 世界种子精化（群系验证）：结构逆推完成后，在下方
   面板录入 ≥7 个群系观测点（F3 显示的群系名 + 站位方块坐标），从候选
   结构种出发枚举高 16 位，恢复完整 64 位世界种子（native 引擎秒级）；
4. 信息量达标后点「计算」，后台线程逆推候选结构种（约 10 秒级）；
5. 计算完成自动批量验证全部候选（正向全量比对，按钮可取消），并显示
   汇总与首个候选的逐条比对明细；
6. 结果区查看候选种子（hex + 十进制双格式），双击种子即可复制；
   也可点「验证候选种子」对任意 48 位种子做正向全量比对。

说明：
- 只支持 1.18~1.21+ 参数线（salt / regionSize / chunkRange 不随小版本变化）；
- 结构类型下拉按「可逆推 / 仅验证」分组（横线分隔）：可逆推（沉船/神殿/
  雪屋等 mod≥2 线性结构）参与预筛，进度条也只统计这类观测；废弃传送门/
  前哨站/海底神殿/远古城市只能作验证观测（层 3 过滤假阳性）；
  林地府邸已下架（锚点定位误差过大，无计算价值）；
- 会话持久化：已采集的结构/群系观测、候选种子与版本/群系模式
  选择实时落盘（用户配置目录 seed_reverser_session.json），重启自动恢复；
- 「群系模式」勾选后显示下方「世界种子精化」面板（默认隐藏，结果区自动加高）；
- 群系模式完整使用说明常驻精化面板的说明区（精化结果会覆盖显示）；
- 站位容差逐观测独立：列表每行的「容差」下拉框选择该观测允许的
  锚点偏差（0~2 区块），默认值按结构类型自动预设（小型单模板 0，
  村庄/试炼/古迹等大型或深埋结构 2，见 structure_params.
  DEFAULT_TOLERANCES）；容差会大幅降低信息量——村庄/试炼密室
  （mod 2）在容差 ≥1 时预筛失效，需以小型结构（mod 8）为主；
  信息量不足会直接报错并给建议；
- 快捷键：Enter 添加 / Ctrl+Enter 计算 / Esc 取消计算验证或清空输入 /
  Delete（列表获得焦点时）删除选中观测。
"""

import json
import os
import re
from collections import Counter

from PySide6.QtCore import (QEvent, QPersistentModelIndex,
                            QSortFilterProxyModel, QRect, QSize,
                            QStandardPaths, Qt, QTimer)
from PySide6.QtGui import (QBrush, QColor, QIcon, QKeySequence, QShortcut,
                           QStandardItem, QStandardItemModel)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox,
                               QCompleter, QLineEdit, QHeaderView,
                               QInputDialog, QMenu, QMessageBox,
                               QStyledItemDelegate, QStyle,
                               QStyleOptionViewItem, QTreeWidgetItem)

from .tool_base import BaseToolWidget
from CodesUI.SeedReverser import Ui_seedReverser
from Threads.task_SeedReverser import (
    CANCELLED_SUMMARY,
    SeedReverserCalcThread,
    SeedReverserVerifyThread,
)
from Threads.task_WorldSeedRefine import (
    CANCELLED_SUMMARY as _REFINE_CANCELLED_SUMMARY,
    WorldSeedRefineThread,
)
from Utils.AutoBackUp.notification import NotificationWidget
from Utils.MapPreviewer import structure_icons as struct_icons
from Utils.SeedReverser import (seed_math, structure_params,
                                structure_3dview, structure_preview)
from Utils.SeedReverser.biome_names import (
    BIOME_CHOICES,
    biome_label,
    icon_path,
    resolve_biome,
)
from Utils.SeedReverser.structure_math import verify_candidate_seed
from Utils.StrongHoldFinder.stronghold_math import (
    looks_like_f3c,
    parse_f3c_command,
    parse_f3c_command_full,
)

# ----- 常量（与设计方案对齐） -----
_MIN_OBSERVATIONS = 3      # 计算所需最少观测数（solve 内部同样校验）
_BORDER_THRESHOLD = 2      # 离区域边界的警告阈值（区块）
_SESSION_FILE = "seed_reverser_session.json"   # 会话文件名（配置目录下）
_NOTIFY_DURATION_MS = 6000
_NOTIFY_TITLE_SIZE = 16
_NOTIFY_MESSAGE_SIZE = 14
_NOTIFY_PADDING = (20, 16, 20, 16)

# 信息量条颜色分段（比特上限 → 颜色，与设计方案 10.1 一致）
_INFO_BAR_SECTIONS = (
    (18, "#E74C3C"),   # <18 红：不足，候选集过大
    (27, "#E67E22"),   # <27 橙：可以尝试但候选较多
    (40, "#F1C40F"),   # <40 黄：较好，候选数可控
)

_INFO_BAR_COLOR_GOOD = "#27AE60"   # >=40 绿：充足

# 状态列颜色（前景色, 背景色）；None 背景表示不设置
_STATUS_COLORS = {
    "OK":    ("#27AE60", None),
    "边界!":  ("#E67E22", "#FEF9E7"),
}

# structList 容差列（0 起）与下拉框容差上限（structure_math 上限 2）
_TOL_COL = 5
_TOL_COMBO_MAX = 2

# 种子 hex 匹配（双击信息框里的种子时复制）
_SEED_HEX_RE = re.compile(r"0x[0-9A-Fa-f]{1,16}")

# 各结构锚点大致位置提示（选择结构时显示在信息量提示行 + 下拉框
# tooltip）。依据 Minecraft Wiki：Java 版村庄无全局定义的中心，
# 水井/钟（1.14+ 的 meeting point）是全村唯一系统性放置的部分；
# 单模板结构（神殿/雪屋/小屋等）的生成锚点为模板包围盒一角，
# 结构整体向东南（+X/+Z）展开。
_ANCHOR_HINTS = {
    "village": "无严格中心；水井或钟（meeting point）附近最接近锚点（容差建议2）",
    "desert_pyramid": "约21×21神殿的西北角，但神庙中心蓝色陶瓦所在区块就是（容差建议0）",
    "igloo": "雪屋一角（容差建议0）",
    "swamp_hut": "小屋一角（容差建议0）",
    "jungle_temple": "庙宇一角（容差建议0）",
    "shipwreck": "船体一角（常见半埋沙滩/海底，看露出部分一角）（容差建议1）",
    "ocean_ruin": "大型废墟主体一角（遗迹向东南展开）（容差据遗迹大小决定）",
    "monument": "建筑最上层正中心4个方块各属四个区块，找区块西北角的方块（容差建议0）",
    "trial_chambers": "两个水池附近（容差建议1）",
    "ruined_portal": "区块西北角（容差建议1）",
}

# 精化功能最少群系观测点数（refine_world_seeds 内部同样校验）
_MIN_BIOME_OBS = 7

# 勾选群系模式时写入说明区的完整使用说明（同时构成 _REFINE_DETAIL_INITIAL 前缀）
_BIOME_MODE_HELP_TEXT = (
    "———— 世界种子精化（群系验证）使用说明 ————\n"
    "前置：先用结构逆推得到候选结构种（或手动填入候选）。\n"
    "\n"
    "1. 游戏内按 F3，走到不同群系处，记录：\n"
    "   · X/Z：方块坐标（F3 第一行 XYZ）；\n"
    "   · Y：脚下方块高度（建议填写，见下方说明）；\n"
    "   · 群系：F3 左侧 Biome 一行的名字（中英文均可识别）。\n"
    "2. 在精化面板逐条录入后点「添加」；或游戏内 F3+C 复制后\n"
    "   点「粘贴F3+C」自动填入 X/Y/Z（群系需手动选择/输入）。\n"
    "3. 需要 ≥7 个观测点，尽量覆盖不同群系（同群系多点信息重复）。\n"
    "4. 点「开始精化」：枚举高 16 位（每候选验证 65536 个种子，\n"
    "   native 引擎下约 0.2 秒/候选），输出满足全部观测的 64 位世界种子。\n"
    "5. 唯一解即成功（自动复制到剪贴板）；多解需到游戏内核对；\n"
    "   未命中说明观测有误或候选不含真值。\n"
    "\n"
    "关于 Y 坐标（重要）：\n"
    "· 填 Y：按该高度的群系判定，与游戏 F3 显示完全一致——推荐。\n"
    "  X 框粘贴 F3+C 复制的完整文本可自动填入 X/Y/Z。\n"
    "· 不填：按深层（y≈0）群系判定，与地表 F3 可能有出入：\n"
    "· 建议站在开阔地表采样，避开洞穴内、海底与山地陡坡。")

# 精化结果区初始内容 = 完整使用说明 + 待精化提示（常驻说明，精化结果覆盖显示）
_REFINE_DETAIL_INITIAL = _BIOME_MODE_HELP_TEXT + (
    "\n"
    "————————————————————————————\n"
    "尚未精化。精化结果（世界种子/多解/统计）将显示在这里。")


class _NoEditDelegate(QStyledItemDelegate):
    """屏蔽指定列的行内编辑器（双击编辑只开放给可安全校验的列）。

    同时负责「编辑中不绘制 item 文字」：编辑器打开期间视图仍会
    重绘该单元格，item 文字会透过（不完全遮盖底色的）下拉编辑器
    形成重影（用户截图实证）。这里用 createEditor/destroyEditor
    跟踪正在编辑的 index，paint 时该单元格只画背景不画文字，
    当前值改由编辑器自己显示。
    """

    def __init__(self, readonly_columns=(), parent=None):
        super().__init__(parent)
        self._readonly = set(readonly_columns)
        # 正被行内编辑的 index（编辑器打开→销毁期间非 None）
        self._edit_index = None

    def createEditor(self, parent, option, index):
        if index.column() in self._readonly:
            return None
        editor = super().createEditor(parent, option, index)
        if editor is not None:
            self._track_editor(editor, option, index)
        return editor

    def _track_editor(self, editor, option, index) -> None:
        """记录正在编辑的 index，并立即重绘该单元格清掉旧文字。"""
        self._edit_index = QPersistentModelIndex(index)
        # deleteLater 关闭路径兑底：编辑器销毁后解除跟踪
        editor.destroyed.connect(self._clear_edit_index)
        view = option.widget
        if view is not None:
            view.viewport().update(view.visualRect(index))

    def destroyEditor(self, editor, index):
        self._edit_index = None
        return super().destroyEditor(editor, index)

    def _clear_edit_index(self, *_args) -> None:
        self._edit_index = None

    def _is_editing(self, index) -> bool:
        return self._edit_index is not None and index == self._edit_index

    def _paint_item(self, painter, option, index,
                    with_text: bool = True) -> None:
        """统一单元格绘制入口（with_text=False 用于编辑中防重影）。"""
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        if not with_text:
            opt.text = ""
            opt.icon = QIcon()
        widget = option.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem,
                          opt, painter, widget)

    def paint(self, painter, option, index) -> None:
        self._paint_item(painter, option, index,
                         with_text=not self._is_editing(index))


class BiomeComboDelegate(_NoEditDelegate):
    """群系下拉项委托：文字居左，16px 群系图标固定画在项的右侧。

    图标按显示标签查表（icons: label -> QIcon），不依赖 model 的
    DecorationRole——组合框下拉列表与补全浮层（两者 model 不同）
    可共用同一 delegate。背景用完整矩形绘制（选中/悬停高亮满宽），
    文字矩形向右缩窄，避免长标签与图标重叠。
    """

    ICON_SIZE = 16   # 图标边长（源图 16x16）
    ICON_PAD = 6     # 图标与右边缘间距

    def __init__(self, icons: dict, parent=None,
                 icon_column: int | None = None, readonly_columns=()):
        super().__init__(readonly_columns, parent)
        self._icons = icons
        # None = 任意列都尝试画图标（combo 单列模型）；
        # 指定列号 = 仅该列画图标（多列树/表共用 delegate 时用）
        self._icon_column = icon_column

    def sizeHint(self, option, index):
        """为右侧图标预留空间，防重叠（仅限画图标的列）。"""
        size = super().sizeHint(option, index)
        if (self._icon_column is not None
                and index.column() != self._icon_column):
            return size
        if self._icon_column is None:
            # combo 弹层：宽度不够会让长文字压到图标，加宽
            return QSize(size.width() + self.ICON_SIZE + self.ICON_PAD * 2,
                         max(size.height(), self.ICON_SIZE + 4))
        # 树/表：图标列多为 Stretch 拉伸列，无需加宽，只保行高
        return QSize(size.width(), max(size.height(), self.ICON_SIZE + 4))

    def paint(self, painter, option, index) -> None:
        if self._is_editing(index):
            # 编辑中：不画 item 文字/图标，防透过编辑器形成重影
            super().paint(painter, option, index)
            return
        if (self._icon_column is not None
                and index.column() != self._icon_column):
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        icon = self._icons.get(opt.text)
        widget = option.widget
        style = widget.style() if widget else QApplication.style()
        if icon is None or icon.isNull():
            super().paint(painter, option, index)
            return
        # 1) 完整矩形画背景（高亮/选中态满宽不缺角）
        panel = QStyleOptionViewItem(option)
        self.initStyleOption(panel, index)
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem,
                            panel, painter, widget)
        # 2) 缩窄矩形画文字（不画默认图标，图标位预留给右侧）
        text_opt = QStyleOptionViewItem(option)
        self.initStyleOption(text_opt, index)
        text_opt.icon = QIcon()
        text_opt.rect.adjust(0, 0, -(self.ICON_SIZE + self.ICON_PAD * 2), 0)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem,
                          text_opt, painter, widget)
        # 3) 图标画在项的右侧（「选项后面」）
        r = QRect(option.rect.right() - self.ICON_SIZE - self.ICON_PAD,
                  option.rect.top(), self.ICON_SIZE + self.ICON_PAD,
                  option.rect.height())
        icon.paint(painter, r, Qt.AlignmentFlag.AlignRight
                   | Qt.AlignmentFlag.AlignVCenter)


class StructRowDelegate(_NoEditDelegate):
    """structList 双击行内编辑：「类型」列下拉、「X/Z」列文本框。

    #/区域/容差/状态列只读（区域与状态是坐标的派生值，容差由行内
    下拉框承担）；编辑提交由 itemChanged 统一处理（见
    _on_struct_item_changed：重算区域/偏移/边界并做冲突检查）。
    """

    def __init__(self, widget, parent=None):
        super().__init__(readonly_columns=(0, 4, 5, 6), parent=parent)
        self._w = widget

    def createEditor(self, parent, option, index):
        if index.column() == 1:
            combo = QComboBox(parent)
            version = self._w.versionCombo.currentText()
            for key in structure_params.available_structures(version):
                name = structure_params.struct_key_to_name(key)
                if not structure_params.is_reversible(key):
                    name += "（仅验证）"
                self._w._add_struct_combo_item(combo, name, key)
            self._track_editor(combo, option, index)
            return combo
        editor = super().createEditor(parent, option, index)
        if index.column() == 2 and isinstance(editor, QLineEdit):
            editor.setPlaceholderText("X（可粘 F3+C）")
        elif index.column() == 3 and isinstance(editor, QLineEdit):
            editor.setPlaceholderText("Z")
        return editor

    def setEditorData(self, editor, index):
        if index.column() == 1 and isinstance(editor, QComboBox):
            i = editor.findData(index.data(Qt.ItemDataRole.UserRole))
            editor.setCurrentIndex(i if i >= 0 else 0)
            return
        super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if index.column() == 1 and isinstance(editor, QComboBox):
            model.setData(index, editor.currentData(),
                          Qt.ItemDataRole.UserRole)
            return
        super().setModelData(editor, model, index)


class BiomeRowDelegate(BiomeComboDelegate):
    """biomeObsList 双击行内编辑 + 群系列行末图标（继承图标绘制）。

    「群系」列为带图标下拉（复用主下拉的图标 delegate 与双语补全）；
    X/Y/Z 为整数文本框（Y 可留空）；# 列只读。提交校验见
    _on_biome_item_changed（同噪声格去重等）。
    """

    def __init__(self, widget, parent=None):
        super().__init__(widget._biome_icons, parent,
                         icon_column=4, readonly_columns=(0,))
        self._w = widget

    def createEditor(self, parent, option, index):
        if index.column() == 4:
            combo = QComboBox(parent)
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            model = QStandardItemModel(combo)
            for label, _key in BIOME_CHOICES:
                model.appendRow(QStandardItem(label))
            proxy = QSortFilterProxyModel(combo)
            proxy.setSourceModel(model)
            proxy.setFilterCaseSensitivity(
                Qt.CaseSensitivity.CaseInsensitive)
            proxy.setFilterKeyColumn(0)
            completer = QCompleter(proxy, combo)
            completer.setCompletionMode(
                QCompleter.CompletionMode.UnfilteredPopupCompletion)
            completer.setCaseSensitivity(
                Qt.CaseSensitivity.CaseInsensitive)
            combo.setCompleter(completer)
            # 弹层复用主下拉的图标 delegate（图标画在选项右侧）
            combo.view().setItemDelegate(self._w._biome_delegate)
            completer.popup().setItemDelegate(self._w._biome_delegate)
            combo.lineEdit().textEdited.connect(proxy.setFilterFixedString)
            self._track_editor(combo, option, index)
            return combo
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        if index.column() == 4 and isinstance(editor, QComboBox):
            editor.lineEdit().setText(
                index.data(Qt.ItemDataRole.DisplayRole) or "")
            return
        super().setEditorData(editor, index)


class SeedReverserWidget(BaseToolWidget, Ui_seedReverser):
    preferred_size = (1170, 826)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # 观测数据：与 structList 行一一对应，字段见 _on_add_clicked
        self._observations: list[dict] = []
        # 后台计算线程（None 表示空闲）
        self._calc_thread = None
        self._calc_running = False
        # 最近一次计算的候选结构种（验证功能用）
        self._last_candidates: list[int] = []
        # 候选结果对应的版本键
        self._result_version: str | None = None
        # 自动/批量验证：后台线程与状态（None 表示空闲）
        self._verify_thread = None
        self._verify_running = False
        # 世界种子精化：观测数据与后台线程（与 _observations/_calc_thread 同构）
        self._biome_obs: list[dict] = []
        self._refine_thread = None
        self._refine_running = False
        # 会话持久化：恢复完成前抑制实时保存（防半恢复状态写盘）
        self._session_ready = False

        self._init_ui()
        self._init_signals()
        self._update_info_bar()
        # 应用级退出钩子：工具页是子控件收不到 closeEvent，aboutToQuit
        # 是退出兜底；先停线程再保存会话（连接顺序 = 调用顺序）。
        # PySide6 易踩坑：运行中的 QThread 在退出阶段被析构会 0xC0000409 崩溃。
        QApplication.instance().aboutToQuit.connect(self._stop_calc_thread)
        QApplication.instance().aboutToQuit.connect(self._save_session)
        # 启动时恢复上次会话（观测/候选/选项；异常时静默丢弃，不影响启动）
        self._restore_session()
        self._session_ready = True

    # ---------- 实现基类接口 ----------
    @classmethod
    def tool_name(cls) -> str:
        return "SeedReverser"

    # ---------- 初始化 ----------
    def _init_ui(self) -> None:
        """填充下拉框、设置列表表头、初始文本与按钮状态。"""
        # 锚点 3D 预览：用 Structure3DView 替换 UI 编译产物里的占位
        # anchorPreviewLabel（保留同名属性引用，外部引用不破）。
        self._anchor_view = structure_3dview.Structure3DView()
        self._anchor_view.setObjectName("anchor3DView")
        # 渲染报错 -> 信息框（模型构建失败/上传失败/绘制异常统一走此链路）
        self._anchor_view.render_error.connect(self._on_render_error)
        self.gridLayout.replaceWidget(self.anchorPreviewLabel,
                                      self._anchor_view)
        self.anchorPreviewLabel.hide()
        self._anchor_preview_key = None
        self._anchor_preview_size = None

        # 版本下拉（VERSION_KEYS = 26.2/1.21.11/1.21 新到旧；会话恢复可覆盖）
        self.versionCombo.addItems(structure_params.VERSION_KEYS)
        self.versionCombo.setCurrentIndex(0)

        # 结构图标：内部键 → QIcon（复用 MapPreviewer 的 Wiki EnvSprite
        # 资产，assets/MapPreviewer/EnvSprite_*.png，16x16）。缺图时
        # 走无图标回退路径（icon_path 文件缺失返回 None 自动跳过）。
        # 必须在 _reload_struct_combo 首次调用前构建（下拉加项时查表）。
        self._struct_icons: dict[str, QIcon] = {}
        for key in structure_params.STRUCT_NAMES:
            spath = struct_icons.icon_path(key)
            if spath:
                icon = QIcon(spath)
                if not icon.isNull():
                    self._struct_icons[key] = icon

        # 结构类型下拉（随版本过滤）
        self._reload_struct_combo()

        # 观测列表：编译产物只有 1 列占位表头，这里代码设置 7 列
        # （第 6 列「容差」为行内下拉框：QComboBox 由 setItemWidget 注入）
        self.structList.setColumnCount(7)
        self.structList.setHeaderLabels(
            ["#", "类型", "X", "Z", "区域", "容差", "状态"])
        self.structList.setRootIsDecorated(False)
        self.structList.setAlternatingRowColors(True)
        self.structList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._resize_struct_columns()

        # 信息量条：0~48 比特，条内显示累计值（如 27bit / 48bit），
        # infoHintLabel 承担文字提示
        self.infoProgressBar.setRange(0, 48)
        self.infoProgressBar.setValue(0)
        self.infoProgressBar.setTextVisible(True)
        self.infoProgressBar.setFormat("%vbit / 48bit")

        # 群系模式：世界种子精化面板开关（勾选启用，不再阻塞结构逆推）
        self.biomeModeCheckBox.setToolTip(
            "勾选后启用下方「世界种子精化」面板：结构逆推得到候选结构种后，\n"
            "用 ≥7 个群系观测点枚举高 16 位，恢复完整 64 位世界种子。"
        )

        # 精化面板：obsList 列设置与初始状态（Y 列在 X/Z 之间）
        self.biomeObsList.setColumnCount(5)
        self.biomeObsList.setHeaderLabels(["#", "X", "Y", "Z", "群系"])
        self.biomeObsList.setRootIsDecorated(False)
        self.biomeObsList.setAlternatingRowColors(True)
        self.biomeObsList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._resize_biome_columns()

        # 群系名下拉：可编辑 + 双语补全（含 F3 别名）
        for label, _key in BIOME_CHOICES:
            self.biomeNameCombo.addItem(label)
        self.biomeNameCombo.setInsertPolicy(
            QComboBox.InsertPolicy.NoInsert)
        self.biomeNameCombo.setCurrentIndex(-1)

        # 包含式补全：输入任意片段（中文或英文）即过滤候选，
        # UnfilteredPopup + 代理模型 contains 过滤（自带补全是前缀式，
        # 对带空格的英文标签基本不可用）
        self._biome_model = QStandardItemModel(self.biomeNameCombo)
        for label, _key in BIOME_CHOICES:
            self._biome_model.appendRow(QStandardItem(label))
        self._biome_proxy = QSortFilterProxyModel(self.biomeNameCombo)
        self._biome_proxy.setSourceModel(self._biome_model)
        self._biome_proxy.setFilterCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive)
        self._biome_proxy.setFilterKeyColumn(0)
        self._biome_completer = QCompleter(
            self._biome_proxy, self.biomeNameCombo)
        self._biome_completer.setCompletionMode(
            QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._biome_completer.setCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive)
        self.biomeNameCombo.setCompleter(self._biome_completer)
        self.biomeNameCombo.lineEdit().textEdited.connect(
            self._biome_proxy.setFilterFixedString)

        # 群系图标：显示标签 → QIcon（assets/SeedReverser/<内部键>.png，16x16）。
        # 1) 下拉列表/补全浮层用 delegate 把图标画在文字右侧；
        # 2) 当前选中项用行编辑器尾部 action 显示图标（带浮层互斥联动）。
        self._biome_icons: dict[str, QIcon] = {}
        for label, key in BIOME_CHOICES:
            path = icon_path(key)
            if path:
                icon = QIcon(path)
                if not icon.isNull():
                    self._biome_icons[label] = icon
        self._biome_delegate = BiomeComboDelegate(
            self._biome_icons, self.biomeNameCombo)
        self.biomeNameCombo.view().setItemDelegate(self._biome_delegate)
        self._biome_completer.popup().setItemDelegate(self._biome_delegate)
        # 下拉视图高度按 54 项全显微调（默认视口可能过矮）
        self.biomeNameCombo.view().setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # 群系观测列表：末列「群系」同样在行末尾画图标（共用 delegate，
        # 仅作用于第 4 列；其余列走原生绘制）。图标固定在单元格右端，
        # 列随窗口拉伸时图标仍贴行末，与下拉项视觉一致。
        # BiomeRowDelegate 继承图标绘制并承担双击行内编辑
        self._obs_delegate = BiomeRowDelegate(self, self.biomeObsList)
        self.biomeObsList.setItemDelegate(self._obs_delegate)

        # 双击行内编辑：类型列下拉 / X Z 群系列可编辑，
        # 校验与回滚由 itemChanged 处理器统一负责（_init_signals 连接）
        self.structList.setItemDelegate(
            StructRowDelegate(self, self.structList))
        self.structList.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked)
        self.biomeObsList.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked)

        # 当前项图标 action 先占位（无图标），选择/输入变化时联动更新；
        # TrailingPosition = 行编辑器文字右侧，与下拉项右侧图标视觉一致
        self._biome_trailing_action = \
            self.biomeNameCombo.lineEdit().addAction(
                QIcon(), QLineEdit.ActionPosition.TrailingPosition)
        self._biome_trailing_action.setToolTip("当前群系图标")
        self.biomeNameCombo.currentIndexChanged.connect(
            self._update_biome_trailing_icon)
        # textChanged 兜底：补全浮层确认文本不走 textEdited，
        # 手动改字时则立即清除不再匹配的图标
        self.biomeNameCombo.lineEdit().textChanged.connect(
            self._update_biome_trailing_icon)

        # Y 输入框：可选（ Designer 无占位提示，这里设置）
        self.biomeYEdit.setPlaceholderText("Y(可不填)")
        self.biomeYEdit.setToolTip(
            "脚下方块高度（F3 第一行 XYZ 的 Y），可不填。\n"
            "填写后按该高度的地表群系判定，与游戏 F3 显示一致；\n"
            "不填按深层判定（可能与地表不同，洞穴群系会干扰）。\n"
            "X 框粘贴 F3+C 复制文本时 Y 自动填入。")

        # 精化面板：默认整体隐藏，勾选「群系模式」后显示（不占布局空间）
        self.refineGroupBox.setVisible(False)
        self.refineGroupBox.setEnabled(False)
        # 候选框长度上限保持 Qt 默认 32767 字符（已是 QLineEdit 上限）：
        # 111 候选 ≈ 2.1k 字符，数千候选也远未达上限，无需额外处理
        # 「批量粘贴」按钮改为「粘贴F3+C」：游戏内复制后一键填入 X/Y/Z
        # （群系名无法从 F3+C 提取，仍需手动选择/输入）
        self.pushButton.setText("粘贴F3+C")
        self.pushButton.setToolTip(
            "把剪贴板中的 F3+C 文本解析后填入 X/Y/Z 输入框。\n"
            "先在游戏内按 F3+C 复制，选好群系后点「添加」。")

        # Designer 残留值归零；说明区给初始内容（使用说明常驻）；提示标签初始状态
        self.refineProgressBar.setValue(0)
        self.worldSeedDetailBrowser.setPlainText(_REFINE_DETAIL_INITIAL)
        self._update_refine_buttons()

        # 结果区初始使用说明
        self.informationBrowser.setPlainText(self._initial_help_text())

        self._update_buttons()

    def _init_signals(self) -> None:
        """连接所有信号槽与快捷键。"""
        self.versionCombo.currentIndexChanged.connect(self._on_version_changed)
        self.structTypeCombo.currentIndexChanged.connect(self._on_struct_type_changed)
        self.biomeModeCheckBox.toggled.connect(self._on_biome_mode_toggled)

        self.addButton.clicked.connect(self._on_add_clicked)
        self.pasteF3CButton.clicked.connect(self._on_paste_f3c)
        self.clearInputButton.clicked.connect(self._on_clear_input)
        self.coordXEdit.returnPressed.connect(self._on_add_clicked)
        self.coordZEdit.returnPressed.connect(self._on_add_clicked)

        self.structList.customContextMenuRequested.connect(self._on_list_context_menu)
        # 双击行内编辑：提交校验统一走 itemChanged
        self.structList.itemChanged.connect(self._on_struct_item_changed)

        self.biomeObsList.customContextMenuRequested.connect(
            self._on_biome_obs_context_menu)
        self.biomeObsList.itemChanged.connect(self._on_biome_item_changed)

        self.calcButton.clicked.connect(self._on_calc_clicked)
        self.verifyButton.clicked.connect(self._on_verify_clicked)
        self.clearAllButton.clicked.connect(self._on_clear_all)

        # 精化面板信号
        self.candidateFromCalcBtn.clicked.connect(self._on_import_candidates)
        self.addBiomeObsBtn.clicked.connect(self._on_add_biome_obs)
        self.pushButton.clicked.connect(self._on_paste_biome_f3c)
        self.clearBiomeBtn.clicked.connect(self._on_clear_biome_obs)
        self.refineButton.clicked.connect(self._on_refine_clicked)
        self.refineClearBtn.clicked.connect(self._on_refine_clear)
        self.biomeXEdit.returnPressed.connect(self._on_add_biome_obs)
        self.biomeZEdit.returnPressed.connect(self._on_add_biome_obs)
        self.biomeYEdit.returnPressed.connect(self._on_add_biome_obs)
        # 候选种子手敲完成后落盘（自动回填/导入/清除路径各自保存）
        self.candidateSeedEdit.editingFinished.connect(self._save_session)

        # 双击信息框中的种子 hex → 复制到剪贴板
        self.informationBrowser.installEventFilter(self)

        # 快捷键：Ctrl+Enter 计算/取消；Esc 取消或清空输入；
        # Delete 仅在列表获得焦点时删除选中行（WidgetShortcut 防误触）
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._on_calc_clicked)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._on_escape)
        delete_sc = QShortcut(QKeySequence(Qt.Key_Delete), self.structList)
        delete_sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete_sc.activated.connect(self._delete_selected)

    def _add_struct_combo_item(self, combo, text: str, key: str) -> None:
        """给结构选择下拉加项（带 Wiki EnvSprite 图标，缺图回退无图标）。

        结构类型主下拉与行内编辑下拉共用；参数顺序与
        combo.addItem(text, userData) 一致。图标存 DecorationRole
        由原生绘制，弹层宽度自适应含图标。
        """
        icon = self._struct_icons.get(key)
        if icon is not None:
            combo.addItem(icon, text, key)
        else:
            combo.addItem(text, key)

    def _reload_struct_combo(self) -> None:
        """按当前版本刷新结构类型下拉，按「可逆推 / 仅验证」分组：

        可逆推（linear 且 lift_mod>=2）在前并标注信息量；之后插入
        不可选中的横线分隔项，仅验证观测（lift_mod=0，层 3 过滤假
        阳性）在后并标注「仅验证」。进度条统计口径与分组一致。
        """
        version = self.versionCombo.currentText()
        keep_key = self.structTypeCombo.currentData()
        self.structTypeCombo.blockSignals(True)
        self.structTypeCombo.clear()
        reversible, verify_only = [], []
        for key in structure_params.available_structures(version):
            (reversible if structure_params.is_reversible(key)
             else verify_only).append(key)
        for key in reversible:
            params = structure_params.get_params(key, version)
            bits = seed_math.calc_info_bits([params])
            name = structure_params.struct_key_to_name(key)
            self._add_struct_combo_item(
                self.structTypeCombo,
                f"{name}（约 {bits:.1f} 比特/个）", key)
        if verify_only:
            sep_idx = self.structTypeCombo.count()
            self.structTypeCombo.addItem("─" * 24, None)
            sep_item = self.structTypeCombo.model().item(sep_idx)
            if sep_item is not None:
                # 去掉可选标记：分隔项仅供视觉分组，不可选中
                sep_item.setFlags(
                    sep_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for key in verify_only:
                name = structure_params.struct_key_to_name(key)
                self._add_struct_combo_item(
                    self.structTypeCombo, f"{name}（仅验证）", key)
        # 恢复原选中项（新版本仍可用时）
        if keep_key is not None:
            idx = self.structTypeCombo.findData(keep_key)
            if idx >= 0:
                self.structTypeCombo.setCurrentIndex(idx)
        self.structTypeCombo.blockSignals(False)
        self._on_struct_type_changed()

    # ---------- 信息量条与按钮状态 ----------
    def _update_info_bar(self) -> None:
        """重算信息量、刷新进度条颜色与提示文本、联动按钮状态。

        进度条只统计可逆推观测（linear 且 lift_mod>=2）：仅验证观测
        不约束低位预筛，计入会虚高信息量误导用户。
        """
        # 传完整观测 dict（含 tol）：容差把每维位置约束从 1 值放宽为
        # min(2tol+1, chunk_range) 候选值，信息量按窗口折减（与求解
        # 器容差通过率同口径，见 seed_math.calc_info_bits）
        obs_list = [obs for obs in self._observations
                    if structure_params.is_reversible(obs["struct_key"])]
        bits = seed_math.calc_info_bits(obs_list)
        # 钳到 [0, maximum] 再 setValue：QProgressBar 对超上限 setValue
        # 静默忽略且 value 停在初始 -1（Qt 6.11 实测，.temp/test_pb_probe3
        # G6，真实 GUI 显示为 "0bit / 48bit" 空条）——观测足够多时 bits
        # 可超 48，重启恢复路径首帧即触发，条显示 0 与"信息量非常充足"
        # 提示矛盾；钳制后信息量拉满显示满格 48bit / 48bit
        self.infoProgressBar.setValue(
            max(0, min(self.infoProgressBar.maximum(), int(round(bits)))))
        color = _INFO_BAR_COLOR_GOOD
        for upper, sec_color in _INFO_BAR_SECTIONS:
            if bits < upper:
                color = sec_color
                break
        # 轨道彻底隐形必须加控件级规则：只写 ::groove/::chunk 子控件规则时
        # QStyleSheetStyle 对本体绘制仍回退原生样式（底部灰色凹槽边框线即
        # 原生 trough），控件级 background+border 声明触发样式表完全接管，
        # 凹槽按规则画"空"才真正消失（value=0 时仅剩 xxbit / 48bit 文本）
        self.infoProgressBar.setStyleSheet(
            "QProgressBar { background: transparent; border: none; }"
            "QProgressBar::groove { background: transparent; border: none; }"
            f"QProgressBar::chunk {{ background-color: {color}; }}"
        )
        self.infoHintLabel.setText(seed_math.info_hint(bits))
        self._update_buttons()

    def _update_buttons(self) -> None:
        """按钮状态矩阵（设计方案 4.2 的等价实现；计算/验证中提供取消出口）。"""
        if self._calc_running or self._verify_running:
            if self._verify_running:
                self.calcButton.setText("取消验证")
                self.calcButton.setToolTip("正在批量验证候选种子（点击取消）")
            else:
                self.calcButton.setText("取消计算")
                self.calcButton.setToolTip("")
            self.calcButton.setEnabled(True)   # 点击 = 取消
            self.verifyButton.setEnabled(False)
            self.clearAllButton.setEnabled(False)
            self.addButton.setEnabled(False)
            self.pasteF3CButton.setEnabled(False)
            self.clearInputButton.setEnabled(False)
            self.versionCombo.setEnabled(False)
            self.structTypeCombo.setEnabled(False)
            self.biomeModeCheckBox.setEnabled(False)
            self.coordXEdit.setEnabled(False)
            self.coordZEdit.setEnabled(False)
            return

        for w in (self.addButton, self.pasteF3CButton, self.clearInputButton,
                  self.versionCombo, self.structTypeCombo, self.biomeModeCheckBox,
                  self.coordXEdit, self.coordZEdit):
            w.setEnabled(True)

        n = len(self._observations)
        has_result = bool(self._last_candidates)
        if n < _MIN_OBSERVATIONS:
            self.calcButton.setText(f"计算（至少 {_MIN_OBSERVATIONS} 个）")
            self.calcButton.setEnabled(False)
        else:
            self.calcButton.setText("重新计算" if has_result else "计算")
            self.calcButton.setEnabled(True)
        self.verifyButton.setEnabled(has_result)
        self.clearAllButton.setEnabled(n > 0 or has_result)

    # ---------- 采集操作 ----------
    def _on_paste_f3c(self) -> None:
        """粘贴 F3+C：解析剪贴板，填入 X/Z 输入框。"""
        text = QApplication.clipboard().text().strip()
        if not looks_like_f3c(text):
            self.informationBrowser.setPlainText(
                "剪贴板内容不是有效的 F3+C 格式。\n"
                "请在游戏中按 F3+C 复制后再点「粘贴F3+C」，或直接手动输入坐标。"
            )
            self._flash_red(self.coordXEdit, self.coordZEdit)
            return
        try:
            x, z, _yaw = parse_f3c_command(text)
        except ValueError as exc:
            self.informationBrowser.setPlainText(f"解析 F3+C 失败：{exc}")
            self._flash_red(self.coordXEdit, self.coordZEdit)
            return
        self.coordXEdit.setText(str(int(x)))
        self.coordZEdit.setText(str(int(z)))
        self.coordXEdit.setFocus()

    def _on_clear_input(self) -> None:
        """清除输入：只清坐标输入框，不影响已采集列表。"""
        self.coordXEdit.clear()
        self.coordZEdit.clear()
        self.coordXEdit.setFocus()

    def _on_add_clicked(self) -> None:
        """添加按钮：8 步校验流程 → 追加观测行 → 更新信息量条。"""
        # 1/2. 非空 + 整数（或 F3+C 整段文本自动提取）
        raw_x = self.coordXEdit.text()
        raw_z = self.coordZEdit.text()
        if not raw_x.strip() and not raw_z.strip():
            self.informationBrowser.setPlainText(
                "请先输入或粘贴坐标（按 F3+C 复制后点「粘贴F3+C」，或手动输入 X/Z）。"
            )
            self._flash_red(self.coordXEdit, self.coordZEdit)
            return
        x, raw_z = self._coerce_coord(raw_x, raw_z, is_x=True)
        z, _ = self._coerce_coord(raw_z, "", is_x=False)
        if x is None or z is None:
            self.informationBrowser.setPlainText(
                "坐标必须是整数方块坐标（如 -1234、567），或整段 F3+C 文本。"
            )
            self._flash_red(self.coordXEdit, self.coordZEdit)
            return

        # 3~5. 区域 / 偏移计算
        struct_key = self.structTypeCombo.currentData()
        if not struct_key:
            # 分组分隔线（横线）被键盘选中时 currentData 为 None
            self.informationBrowser.setPlainText(
                "请选择一个结构类型（不要选分隔线）。"
            )
            return
        version = self.versionCombo.currentText()
        params = structure_params.get_params(struct_key, version)
        region_size = params["region_size"]
        reg_x, reg_z = seed_math.compute_region(x, z, region_size)
        off_x, off_z = seed_math.compute_offset(x, z, reg_x, reg_z, region_size)

        # 6. 同区域同类型重复检查
        for obs in self._observations:
            if obs["struct_key"] == struct_key and \
                    obs["reg_x"] == reg_x and obs["reg_z"] == reg_z:
                self.informationBrowser.setPlainText(
                    f"该区域 (reg {reg_x}, {reg_z}) 已有同类型结构"
                    f"「{params['name']}」，不能重复采集。\n"
                    "提示：找下一个该类型结构时，至少要跨过一个区域。"
                )
                self._flash_red(self.coordXEdit, self.coordZEdit)
                return

        # 7. 边界检查（允许添加但警告）
        near_boundary = seed_math.is_near_boundary(
            off_x, off_z, region_size, _BORDER_THRESHOLD)
        status = "边界!" if near_boundary else "OK"

        # 8. 追加观测与列表行（容差默认值按结构类型预设，可在行内下拉修改）
        obs = {
            "struct_key": struct_key,
            "name": params["name"],
            "x": x, "z": z,
            "reg_x": reg_x, "reg_z": reg_z,
            "off_x": off_x, "off_z": off_z,
            "near_boundary": near_boundary,
            "tol": structure_params.get_default_tolerance(struct_key),
            "params": params,
        }
        self._observations.append(obs)
        self._append_list_row(len(self._observations), obs, status)

        self.coordXEdit.clear()
        self.coordZEdit.clear()
        self.coordXEdit.setFocus()
        self._update_info_bar()
        self._save_session()

        if near_boundary:
            self.informationBrowser.setPlainText(
                f"警告：观测「{params['name']} ({x}, {z})」的区块偏移为 "
                f"({off_x}, {off_z})，离区域边界不足 {_BORDER_THRESHOLD} 区块。\n"
                "玩家站位跨区块时可能导致区域判定偏差，建议换一个离边界远的结构。"
            )

    # ---------- 结构观测：双击行内编辑提交 ----------
    def _on_struct_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """structList 行内编辑提交：校验 → 回滚或重算派生字段。

        程序化回写同样会触发 itemChanged，回写用 blockSignals 包裹
        防递归。合法提交后旧结果失效（与删除观测同一处理）。
        """
        idx = self.structList.indexOfTopLevelItem(item)
        if not (0 <= idx < len(self._observations)):
            return
        obs = self._observations[idx]

        # 类型列：数据写在 UserRole（DisplayRole 仍是中文名，由这里回写）
        if column == 1:
            new_key = item.data(1, Qt.ItemDataRole.UserRole)
            if not new_key or new_key == obs["struct_key"]:
                return
            version = self.versionCombo.currentText()
            try:
                params = structure_params.get_params(new_key, version)
            except KeyError:
                # 新版本已移除的结构：回滚并提示
                self.structList.blockSignals(True)
                try:
                    item.setData(1, Qt.ItemDataRole.UserRole,
                                 obs["struct_key"])
                finally:
                    self.structList.blockSignals(False)
                self.informationBrowser.setPlainText(
                    f"当前版本不支持该结构类型，已回滚为「{obs['name']}」。")
                return
            # 新类型区域大小可能不同 → 先用旧坐标重算区域，再做查重
            region_size = params["region_size"]
            reg_x, reg_z = seed_math.compute_region(
                obs["x"], obs["z"], region_size)
            for i, o in enumerate(self._observations):
                if i != idx and o["struct_key"] == new_key \
                        and o["reg_x"] == reg_x and o["reg_z"] == reg_z:
                    # 同区域同类型冲突：回滚 UserRole（DisplayRole 本就未变）
                    self.structList.blockSignals(True)
                    try:
                        item.setData(1, Qt.ItemDataRole.UserRole,
                                     obs["struct_key"])
                    finally:
                        self.structList.blockSignals(False)
                    self.informationBrowser.setPlainText(
                        f"修改未生效：该区域 (reg {reg_x}, {reg_z}) 已有"
                        f"同类型结构「{params['name']}」，不能重复采集。\n"
                        "提示：找下一个该类型结构时，至少要跨过一个区域。")
                    return
            obs["struct_key"] = new_key
            obs["name"] = params["name"]
            obs["params"] = params   # 同步新参数表（salt/region_size 等）
            obs["reg_x"], obs["reg_z"] = reg_x, reg_z
            obs["off_x"], obs["off_z"] = seed_math.compute_offset(
                obs["x"], obs["z"], reg_x, reg_z, region_size)
            # 容差回落新类型默认值并重建行内下拉框（闭包持同一 obs 引用）
            obs["tol"] = structure_params.get_default_tolerance(new_key)
            self._attach_tol_combo(item, obs)
            # 类型变了 → 区域大小可能变 → 用旧坐标重算全部派生字段
            status = self._recalc_struct_obs(obs)
            self.structList.blockSignals(True)
            try:
                item.setText(1, obs["name"])
                icon = self._struct_icons.get(new_key)
                if icon is not None:
                    item.setIcon(1, icon)
                item.setText(4, f"({obs['reg_x']}, {obs['reg_z']})")
                item.setText(6, status)
                fg, bg = _STATUS_COLORS.get(status, (None, None))
                item.setForeground(6, QColor(fg) if fg else QBrush())
                item.setBackground(6, QColor(bg) if bg else QBrush())
            finally:
                self.structList.blockSignals(False)
            self._after_struct_edit()
            return

        # X / Z 列：整数或整段 F3+C 文本
        if column in (2, 3):
            raw = item.text(column).strip()
            if not raw:
                self._rollback_struct_cell(item, obs, column, "坐标不能为空")
                return
            # _coerce_coord 返回 (本坐标值, 另一框文本)：X 列粘 F3+C 时
            # 第二个返回值是解析出的 Z（与添加路径行为一致），纯整数时
            # 是原 Z 的字符串形式；Z 列只取第一个返回值
            if column == 2:
                val, other = self._coerce_coord(raw, str(obs["z"]), is_x=True)
                if val is None:
                    self._rollback_struct_cell(
                        item, obs, column,
                        "坐标必须是整数方块坐标（如 -1234、567），或整段 F3+C 文本")
                    return
                x = int(val)
                try:
                    z = int(other)
                except ValueError:
                    self._rollback_struct_cell(
                        item, obs, column, "无法从输入解析出有效坐标")
                    return
            else:
                val, _ = self._coerce_coord(raw, "", is_x=False)
                if val is None:
                    self._rollback_struct_cell(
                        item, obs, column,
                        "坐标必须是整数方块坐标（如 -1234、567），或整段 F3+C 文本")
                    return
                z = int(val)
                x = obs["x"]
            # 区域/偏移重算 + 同区域同类型重复检查（排除自身）
            region_size = obs["params"]["region_size"]
            reg_x, reg_z = seed_math.compute_region(x, z, region_size)
            for i, o in enumerate(self._observations):
                if i != idx and o["struct_key"] == obs["struct_key"] \
                        and o["reg_x"] == reg_x and o["reg_z"] == reg_z:
                    self._rollback_struct_cell(
                        item, obs, column,
                        f"该区域 (reg {reg_x}, {reg_z}) 已有同类型结构"
                        f"「{obs['name']}」，不能重复采集。\n"
                        "提示：找下一个该类型结构时，至少要跨过一个区域。")
                    return
            obs["x"], obs["z"] = x, z
            obs["reg_x"], obs["reg_z"] = reg_x, reg_z
            obs["off_x"], obs["off_z"] = seed_math.compute_offset(
                x, z, reg_x, reg_z, region_size)
            status = self._recalc_struct_obs(obs)
            self.structList.blockSignals(True)
            try:
                item.setText(2, str(x))
                item.setText(3, str(z))
                item.setText(4, f"({reg_x}, {reg_z})")
                item.setText(6, status)
                fg, bg = _STATUS_COLORS.get(status, (None, None))
                item.setForeground(6, QColor(fg) if fg else QBrush())
                item.setBackground(6, QColor(bg) if bg else QBrush())
            finally:
                self.structList.blockSignals(False)
            self._after_struct_edit()
            if status == "边界!":
                self.informationBrowser.setPlainText(
                    f"警告：观测「{obs['name']} ({x}, {z})」的区块偏移为 "
                    f"({obs['off_x']}, {obs['off_z']})，离区域边界不足 "
                    f"{_BORDER_THRESHOLD} 区块。\n"
                    "玩家站位跨区块时可能导致区域判定偏差，建议换一个离边界远的结构。")

    def _recalc_struct_obs(self, obs: dict) -> str:
        """重算边界标志并返回状态文本（区域/偏移已由调用方更新）。"""
        obs["near_boundary"] = seed_math.is_near_boundary(
            obs["off_x"], obs["off_z"], obs["params"]["region_size"],
            _BORDER_THRESHOLD)
        return "边界!" if obs["near_boundary"] else "OK"

    def _rollback_struct_cell(self, item: QTreeWidgetItem, obs: dict,
                              column: int, reason: str) -> None:
        """非法输入回滚：恢复旧显示文本，信息区提示原因。"""
        old = {2: str(obs["x"]), 3: str(obs["z"])}.get(column, "")
        self.structList.blockSignals(True)
        try:
            item.setText(column, old)
        finally:
            self.structList.blockSignals(False)
        self.informationBrowser.setPlainText(
            f"修改未生效：{reason}\n已恢复原值。")

    def _after_struct_edit(self) -> None:
        """合法提交后的公共收尾：结果失效 + 信息条 + 落盘。"""
        self._last_candidates = []
        self._result_version = None
        if self._verify_running and self._verify_thread is not None:
            self._verify_thread.request_cancel()
        self._update_info_bar()
        self._save_session()

    def _resize_struct_columns(self) -> None:
        """structList 列宽自适应（固定像素列宽在各 DPI/字体下的挤压问题）。

        #/X/Z/区域/状态用 ResizeToContents：列宽随内容与表头自动适配
        （用户截图反馈的「X/Z 只剩表头、数值显示不全、状态列大片
        留白」即固定像素 + stretchLastSection 默认拉伸所致）；
        「类型」列 Stretch 吸收剩余宽度；「容差」列 ResizeToContents
        感知不到 setItemWidget 注入的下拉框，按其 sizeHint 手动
        定宽（Interactive 允许拖动微调）。
        """
        header = self.structList.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(28)
        for col in (0, 2, 3, 4, 6):
            header.setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        # 容差列：用与 _attach_tol_combo 相同的三档文本量宽 + 8px 边距
        header.setSectionResizeMode(_TOL_COL, QHeaderView.ResizeMode.Interactive)
        probe = QComboBox(self.structList)
        for t in range(_TOL_COMBO_MAX + 1):
            probe.addItem(f"{t} 区块" if t else "0（精确）", t)
        probe.ensurePolished()
        header.resizeSection(_TOL_COL, probe.sizeHint().width() + 8)
        probe.deleteLater()

    def _resize_biome_columns(self) -> None:
        """biomeObsList 列宽：前 4 列内容自适应，末列「群系」Stretch。"""
        header = self.biomeObsList.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(28)
        for col in range(self.biomeObsList.columnCount() - 1):
            header.setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            self.biomeObsList.columnCount() - 1, QHeaderView.ResizeMode.Stretch)

    def _append_list_row(self, seq: int, obs: dict, status: str) -> None:
        """把观测追加为 structList 一行（第 6 列为行内容差下拉框）。

        程序化 setText 会触发 itemChanged，这里 blockSignals 包裹
        （连接早于会话恢复，恢复路径同样经此函数）；类型列另存
        UserRole（struct_key），供 delegate 编辑器回显与提交比对。
        """
        item = QTreeWidgetItem([
            str(seq),
            obs["name"],
            str(obs["x"]),
            str(obs["z"]),
            f"({obs['reg_x']}, {obs['reg_z']})",
            "",          # 容差列：setItemWidget 注入 QComboBox，不存文本
            status,
        ])
        item.setData(1, Qt.ItemDataRole.UserRole, obs["struct_key"])
        # 类型列首部画结构图标（原生 DecorationRole 绘制；图标随类型
        # 变更同步，见 _on_struct_item_changed）
        icon = self._struct_icons.get(obs["struct_key"])
        if icon is not None:
            item.setIcon(1, icon)
        # 列 1/2/3 允许双击行内编辑（只读列由 delegate createEditor 拦截）
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(0, int(Qt.AlignmentFlag.AlignCenter))
        item.setTextAlignment(2, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        item.setTextAlignment(3, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        item.setTextAlignment(4, int(Qt.AlignmentFlag.AlignCenter))
        item.setTextAlignment(6, int(Qt.AlignmentFlag.AlignCenter))
        fg_color, bg_color = _STATUS_COLORS.get(status, (None, None))
        if fg_color:
            item.setForeground(6, QColor(fg_color))
        if bg_color:
            item.setBackground(6, QColor(bg_color))
        self.structList.blockSignals(True)
        try:
            self.structList.addTopLevelItem(item)
        finally:
            self.structList.blockSignals(False)
        self._attach_tol_combo(item, obs)

    def _attach_tol_combo(self, item: QTreeWidgetItem, obs: dict) -> None:
        """给观测行第 6 列注入容差下拉框（0/1/2 区块，改动即落盘）。"""
        combo = QComboBox(self.structList)
        for t in range(_TOL_COMBO_MAX + 1):
            combo.addItem(f"{t} 区块" if t else "0（精确）", t)
        combo.setCurrentIndex(max(0, combo.findData(obs["tol"])))
        combo.setToolTip(
            "该观测的站位容差（区块）：玩家站位与结构锚点的允许偏差。\n\n"
            "0 = 精确锚点：信息量最大，适合小型单模板结构；\n"
            "1~2 = 容差模式：站位误差大时用（村庄/试炼/古迹等默认 2）。\n\n"
            "注意：容差越大信息量越低；村庄/试炼密室（mod 2）在容差 ≥1\n"
            "时预筛失效，请以小型结构（沙漠神殿/雪屋/女巫小屋/丛林神庙\n"
            "/沉船/海底废墟）为主。"
        )

        def _on_tol_changed(idx: int, _ob=obs, _c=combo):
            _ob["tol"] = int(_c.itemData(idx))
            # 容差改变直接影响该观测的信息量贡献，信息条即时联动
            self._update_info_bar()
            self._save_session()

        combo.currentIndexChanged.connect(_on_tol_changed)
        self.structList.setItemWidget(item, _TOL_COL, combo)

    def _renumber_rows(self) -> None:
        """删除观测后重排行序号列。"""
        for i in range(self.structList.topLevelItemCount()):
            self.structList.topLevelItem(i).setText(0, str(i + 1))

    def _delete_selected(self) -> None:
        """删除当前选中的观测行（右键菜单 / Delete 键共用）。"""
        item = self.structList.currentItem()
        if item is None:
            return
        idx = self.structList.indexOfTopLevelItem(item)
        if idx < 0 or idx >= len(self._observations):
            return
        del self._observations[idx]
        self.structList.takeTopLevelItem(idx)
        self._renumber_rows()
        # 观测已变化，旧结果不再可信：中止验证并回采集态
        self._last_candidates = []
        self._result_version = None
        if self._verify_running and self._verify_thread is not None:
            self._verify_thread.request_cancel()
        self._update_info_bar()
        self._save_session()

    def _on_list_context_menu(self, pos) -> None:
        """列表右键菜单：删除此条 / 复制坐标 / 复制 F3+C 格式。"""
        item = self.structList.itemAt(pos)
        if item is None:
            return
        idx = self.structList.indexOfTopLevelItem(item)
        if not (0 <= idx < len(self._observations)):
            return
        obs = self._observations[idx]

        menu = QMenu(self)
        act_delete = menu.addAction("删除此条")
        act_copy_coord = menu.addAction("复制坐标")
        act_copy_f3c = menu.addAction("复制 F3+C 格式")
        chosen = menu.exec(self.structList.viewport().mapToGlobal(pos))

        if chosen is act_delete:
            self._delete_selected()
        elif chosen is act_copy_coord:
            QApplication.clipboard().setText(f"{obs['x']}, {obs['z']}")
        elif chosen is act_copy_f3c:
            # 可粘回游戏聊天栏的传送命令（y=100，仅用于飞到该结构上空）
            QApplication.clipboard().setText(
                f"/execute in minecraft:overworld run tp @s {obs['x']} 100 {obs['z']} 0 0"
            )

    # ---------- 版本 / 模式切换 ----------
    def _on_version_changed(self) -> None:
        """版本切换：刷新结构下拉，检查已采集观测的版本可用性。"""
        self._reload_struct_combo()
        version = self.versionCombo.currentText()
        available = set(structure_params.available_structures(version))
        outdated = [obs["name"] for obs in self._observations
                    if obs["struct_key"] not in available]
        if outdated:
            names = "、".join(sorted(set(outdated)))
            self.informationBrowser.setPlainText(
                f"注意：版本已切换为 {version}.x，其中「{names}」并不存在。\n"
                "相关观测仍保留在列表中，但请确认它们确实来自所选版本的世界。"
            )
        self._save_session()

    def _on_struct_type_changed(self) -> None:
        """结构类型切换：更新 tooltip 信息量说明 + 显示锚点位置提示。"""
        version = self.versionCombo.currentText()
        key = self.structTypeCombo.currentData()
        if not key:
            self.structTypeCombo.setToolTip("")
            return
        params = structure_params.get_params(key, version)
        if params["scatter"] == "triangle":
            tip = (f"{params['name']}：三角散布结构，每个约 "
                   f"{seed_math.calc_info_bits([params]):.1f} 比特，"
                   "不能单独参与逆推预筛。")
        elif params["lift_mod"] == 0:
            tip = (f"{params['name']}：该结构无法参与低位预筛，"
                   "只能作为附加验证观测。")
        else:
            tip = (f"{params['name']}：线性散布结构，每个约 "
                   f"{seed_math.calc_info_bits([params]):.1f} 比特。")
        # 锚点位置提示：站位越靠近锚点，容差模式命中率越高；
        # 写入 infoHintLabel（添加观测后会被信息量提示覆盖，符合
        # 「选结构时看一眼」的时序），完整说明留在 tooltip
        anchor = _ANCHOR_HINTS.get(key)
        if anchor:
            tip += f"\n锚点位置：{anchor}"
            self.infoHintLabel.setText(f"锚点: {anchor}")
        self.structTypeCombo.setToolTip(tip)
        # 右侧示意图：侧视 + 俯视 + 锚点标注（左上角）随结构切换刷新
        self._update_anchor_preview()

    def _update_anchor_preview(self) -> None:
        """结构切换 -> 3D 视口更新（模型走 build_model 缓存）。

        原平面示意图（structure_preview）已由 3D 视口取代；
        保留方法名与调用点，减少外部引用破坏。
        """
        key = self.structTypeCombo.currentData()
        if not key:
            self._anchor_view.set_structure(None)
            self._anchor_preview_key = None
            return
        if key == self._anchor_preview_key:
            return
        self._anchor_preview_key = key
        name = structure_params.struct_key_to_name(key)
        self._anchor_view.set_structure(key, name)

    def _on_render_error(self, msg: str) -> None:
        """3D 视口渲染报错：写入信息框（换行追加，保留已有内容）。"""
        self.informationBrowser.append(f"[3D 视口] {msg}")

    def _on_biome_mode_toggled(self, checked: bool) -> None:
        """群系模式开关：显隐精化面板与结构 3D 视口。

        群系模式只采群系观测，结构模型预览无用武之地——隐藏右侧
        3D 视口把空间让给精化面板；关闭时恢复显示（模型仍跟随
        结构下拉，重显即原样）。informationBrowser 为垂直 Expanding：
        隐藏 refineGroupBox 时自动吃掉让出的空间（结果区加高）；
        显示时布局把空间还给 groupbox（结果区缩短），无需手动干预。
        """
        # 3D 视口与精化面板互斥显隐（群系模式=纯群系观测，无结构预览）
        self._anchor_view.setHidden(checked)
        if checked:
            if not self.refineGroupBox.isVisible():
                self.refineGroupBox.setVisible(True)
            self.refineGroupBox.setEnabled(True)
            self.refineInfoLabel.setText(self._refine_idle_hint())
        else:
            self.refineGroupBox.setVisible(False)
            self.refineGroupBox.setEnabled(False)
        self._update_refine_buttons()
        self._save_session()

    # ---------- 精化面板：辅助 ----------
    @staticmethod
    def _y_tag_of(obs_list) -> str:
        """统计观测点中带 Y 的条数，生成提示后缀（无带 Y 点时为空）。"""
        n_y = sum(1 for o in obs_list if o.get("y") is not None)
        return f"（{n_y} 点带Y）" if n_y else ""

    def _refine_idle_hint(self) -> str:
        n = len(self._biome_obs)
        y_tag = self._y_tag_of(self._biome_obs)
        if n < _MIN_BIOME_OBS:
            return f"群系观测 {n}/{_MIN_BIOME_OBS} 点{y_tag}"
        n_cands = self._count_refine_candidates()
        return (f"已就绪：{n} 个观测点{y_tag} × "
                f"{n_cands if n_cands > 0 else '?'} 候选 × 2^16")

    @staticmethod
    def _parse_candidate_text(text: str) -> list[int]:
        """解析候选种子文本（hex/十进制混合，逗号/空格/换行分隔）。"""
        cands = []
        for tok in re.split(r"[\s,;，；]+", text.strip()):
            if not tok:
                continue
            try:
                v = int(tok, 16) if tok.lower().startswith("0x") else int(tok, 10)
            except ValueError:
                continue
            if 0 <= v < (1 << 48) and v not in cands:
                cands.append(v)
        return cands

    def _count_refine_candidates(self) -> int:
        """当前候选框内的有效候选数（解析失败静默忽略）。"""
        return len(self._parse_candidate_text(self.candidateSeedEdit.text()))

    def _update_refine_buttons(self) -> None:
        """精化面板按钮状态矩阵（独立于结构逆推的 _update_buttons）。"""
        if self._refine_running:
            self.refineButton.setText("停止精化")
            self.refineButton.setEnabled(True)
            self.refineClearBtn.setEnabled(False)
            self.refineInfoLabel.setText("精化中…（点击按钮停止）")
            return
        self.refineButton.setText("开始精化")
        self.refineClearBtn.setEnabled(True)
        n = len(self._biome_obs)
        n_cands = self._count_refine_candidates()
        y_tag = self._y_tag_of(self._biome_obs)
        ok = n >= _MIN_BIOME_OBS and n_cands > 0
        self.refineButton.setEnabled(ok)
        if n < _MIN_BIOME_OBS:
            self.refineInfoLabel.setText(
                f"群系观测 {n}/{_MIN_BIOME_OBS} 点{y_tag}")
        elif n_cands == 0:
            self.refineInfoLabel.setText(
                "请先完成结构逆推，或手动输入候选结构种")
        else:
            self.refineInfoLabel.setText(
                f"已就绪：{n} 个观测点{y_tag}，{n_cands} 个候选，"
                f"枚举总量 {n_cands * (1 << 16):,}")

    # ---------- 计算操作 ----------
    def _on_calc_clicked(self) -> None:
        """计算按钮：空闲时启动后台线程；计算/验证中点击 = 取消。"""
        if self._calc_running:
            if self._calc_thread is not None:
                self._calc_thread.request_cancel()
                self.calcButton.setText("取消中…")
                self.calcButton.setEnabled(False)
            return
        if self._verify_running:
            if self._verify_thread is not None:
                self._verify_thread.request_cancel()
                self.calcButton.setText("取消中…")
                self.calcButton.setEnabled(False)
            return
        if len(self._observations) < _MIN_OBSERVATIONS:
            return  # 按钮禁用态的兑底防御

        entries = [
            {
                "struct_key": obs["struct_key"],
                "reg_x": obs["reg_x"],
                "reg_z": obs["reg_z"],
                "off_x": obs["off_x"],
                "off_z": obs["off_z"],
                "tol": obs["tol"],
            }
            for obs in self._observations
        ]
        self._last_candidates = []
        self._result_version = None
        self.informationBrowser.setPlainText(
            "正在逆推结构种，请稍候…\n（按钮上显示进度，约 10 秒级）")

        thread = SeedReverserCalcThread(
            entries, self.versionCombo.currentText(), parent=self)
        thread.progress.connect(self._on_calc_progress)
        thread.calc_finished.connect(self._on_calc_finished)
        thread.error.connect(self._on_calc_error)
        # 内置 finished（线程真正结束）→ 清引用，防悬挂
        thread.finished.connect(self._on_thread_finished)
        self._calc_thread = thread
        self._calc_running = True
        self._update_buttons()
        thread.start()

    def _on_calc_progress(self, done: int, total: int, stage: str) -> None:
        """计算进度：按钮文本同时承担「可点击取消」与百分比，阶段放 tooltip。"""
        pct = int(round(done * 100 / total)) if total else 0
        self.calcButton.setText(f"取消计算 {pct}%")
        self.calcButton.setToolTip(f"阶段 {stage}: {done}/{total}（点击按钮取消）")

    def _on_calc_finished(self, candidates: list, summary: str) -> None:
        """计算完成：格式化输出结果 + 通知 + 恢复状态。"""
        self._calc_running = False
        self.calcButton.setToolTip("")

        if summary == CANCELLED_SUMMARY:
            self.informationBrowser.setPlainText("计算已取消。")
            self._update_buttons()
            return

        self._last_candidates = list(candidates)
        self._result_version = self.versionCombo.currentText()
        version = self.versionCombo.currentText()
        bits = seed_math.calc_info_bits(list(self._observations))

        # 决策点 5A：群系模式开启时自动把候选回填到精化面板
        if self.biomeModeCheckBox.isChecked() and candidates:
            self._auto_fill_candidates(candidates)

        counts = Counter(obs["name"] for obs in self._observations)
        obs_desc = ", ".join(f"{name} ×{cnt}" for name, cnt in counts.items())
        tol_line = self._tol_summary_line()

        if candidates:
            lines = [
                "———— 逆推结果 ————",
                f"版本: {version}.x",
                f"有效观测: {len(self._observations)} 个（{obs_desc}）",
                tol_line,
                f"信息量: {bits:.1f} / 48 比特",
                "",
                f"候选结构种（48 位，共 {len(candidates)} 个）:",
            ]
            for i, seed in enumerate(candidates, 1):
                lines.append(f"  {i}. 0x{seed:012X}  (十进制: {seed})")
            lines += [
                "",
                "正在自动验证全部候选种子（正向全量比对，按钮可取消）…",
                "",
                "———— 统计 ————",
                summary,
            ]
            self.informationBrowser.setPlainText("\n".join(lines))
            self._start_auto_verification()
            NotificationWidget.Show(
                "种子逆推完成",
                f"找到 {len(candidates)} 个候选结构种\n"
                f"首个: 0x{candidates[0]:012X}\n"
                "详情见工具结果区",
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )
        else:
            # 无候选：没有任何 48 位种子能满足全部观测
            #（后台线程已自动尝试逐条剔除重试，仍未命中）
            self.informationBrowser.setPlainText(
                "———— 错误 ————\n"
                "没有任何 48 位种子能同时满足这些观测\n"
                "（已自动尝试剔除单条观测重试，仍未命中）。\n"
                "最可能原因：\n"
                f"  1. 版本选择不匹配（当前: {version}.x）—— 请确认游戏版本后切换；\n"
                "  2. 两条以上坐标抄错，或站位离结构锚点超过容差；\n"
                "  3. 玩家站位跨区域导致区域判定偏差（状态列出现「边界!」时尤甚）。\n"
                "\n"
                "建议：逐个删除最近添加的观测重新计算；或增大站位容差（最大 2）；\n"
                "容差模式下优先补采小型结构（沙漠神殿/雪屋/女巫小屋/沉船等）。\n"
                "\n"
                "———— 统计 ————\n" + summary
            )
            NotificationWidget.Show(
                "逆推失败",
                "没有找到满足全部观测的结构种\n详见工具结果区",
                5000,
                title_size=13,
                message_size=12,
            )
        self._update_buttons()
        # 候选/版本/容差/候选框文本（含自动回填）已全部就绪，统一落盘
        self._save_session()

    def _tol_summary_line(self) -> str:
        """按当前观测容差生成结果区的一行摘要。

        全部 0 → 精确模式；否则列出每个非 0 容差及其观测数，
        便于用户核对逐条容差设置是否与意图一致。
        """
        tols = [obs["tol"] for obs in self._observations]
        if not any(tols):
            return "站位容差: 全部 0（精确模式）"
        parts = [f"容差 {t} 区块 ×{n}" for t, n in sorted(Counter(tols).items()) if t > 0]
        n_zero = tols.count(0)
        if n_zero:
            parts.append(f"精确 ×{n_zero}")
        return "站位容差: " + "，".join(parts)

    def _on_calc_error(self, message: str) -> None:
        """求解异常（观测不足等）：输出原因与建议 + 通知 + 恢复状态。"""
        self._calc_running = False
        self.calcButton.setToolTip("")
        self._save_session()
        self.informationBrowser.setPlainText(
            "———— 无法计算 ————\n"
            f"{message}\n"
            "\n"
            "提示：沉船 / 沙漠神殿 / 雪屋 / 女巫小屋 / 丛林神庙等线性结构"
            "最适合参与逆推；海底神殿、远古城市、前哨站只能"
            "作为附加验证观测。"
        )
        NotificationWidget.Show(
            "逆推出错",
            message[:60] + ("…" if len(message) > 60 else ""),
            5000,
            title_size=13,
            message_size=12,
        )
        self._update_buttons()

    def _on_thread_finished(self) -> None:
        """QThread 内置 finished（线程对象真正结束）：清理引用。"""
        if self._calc_thread is not None and not self._calc_thread.isRunning():
            self._calc_thread = None
        if self._verify_thread is not None and not self._verify_thread.isRunning():
            self._verify_thread = None
        if self._verify_thread is not None and not self._verify_thread.isRunning():
            self._verify_thread = None

    # ---------- 精化面板：候选导入 ----------
    def _auto_fill_candidates(self, candidates: list) -> None:
        """结构逆推成功后自动回填候选到 candidateSeedEdit（全量不截断）。

        曾按 ≤16 个截断导入：候选超 16 时真种子若不在前 16 个，
        精化必然未命中（用户村庄容差 2 → 111 候选案例的真种子排
        第 17+ 位）。现全量导入——候选多时由用户自行补充群系观测
        压缩，native 精化引擎下每候选仅约 0.2 秒，规模可承受。
        """
        text = ", ".join(str(s) for s in candidates)
        self.candidateSeedEdit.setText(text)
        self._update_refine_buttons()
        self._save_session()

    def _on_import_candidates(self) -> None:
        """从计算结果导入候选（手动兑底，全量不截断）。"""
        if not self._last_candidates:
            self.refineInfoLabel.setText("暂无计算结果：请先运行结构逆推")
            return
        self.candidateSeedEdit.setText(
            ", ".join(str(s) for s in self._last_candidates))
        self._update_refine_buttons()
        self._save_session()

    # ---------- 验证操作 ----------
    def _on_verify_clicked(self) -> None:
        """验证候选种子：正向复算全部观测并逐条比对。"""
        if not self._last_candidates:
            return
        options = [f"0x{seed:012X}" for seed in self._last_candidates]
        choice, ok = QInputDialog.getItem(
            self, "验证候选种子",
            "选择或输入候选种子（支持 0x 开头的 hex 或十进制）:",
            options, 0, True)
        if not ok:
            return
        seed = self._parse_seed_text(choice)
        if seed is None:
            self.informationBrowser.append(
                "\n验证失败：种子格式无效（应为 0x 开头的 12 位 hex，"
                "或 0 ~ 2^48-1 的十进制数）。")
            return
        self._run_verification(seed)

    def _parse_seed_text(self, text: str) -> int | None:
        """解析种子文本（hex / 十进制），范围校验 0 ~ 2^48-1。"""
        s = text.strip()
        if not s:
            return None
        try:
            value = int(s, 16) if s.lower().startswith("0x") else int(s, 10)
        except ValueError:
            return None
        if not (0 <= value < (1 << 48)):
            return None
        return value

    def _run_verification(self, seed: int) -> None:
        """对给定种子做正向全量比对（同步），结果追加到信息框。

        语义与层 3 一致：逐观测用自己的行内容差（obs["tol"]）。
        """
        version = self._result_version or self.versionCombo.currentText()
        ok, body = verify_candidate_seed(seed, self._observations, version)
        lines = [
            "",
            "———— 验证结果 ————",
            f"种子: 0x{seed:012X} (十进制: {seed})",
            "",
            *body,
        ]
        self.informationBrowser.append("\n".join(lines))

    # ---------- 自动批量验证（计算完成后触发） ----------
    def _start_auto_verification(self) -> None:
        """启动后台线程批量验证全部候选（含逐条比对明细展示）。"""
        version = self._result_version or self.versionCombo.currentText()
        candidates = self._last_candidates
        thread = SeedReverserVerifyThread(
            candidates, [dict(o) for o in self._observations], version,
            parent=self)
        thread.progress.connect(self._on_verify_progress)
        thread.calc_finished.connect(self._on_verify_finished)
        thread.error.connect(self._on_verify_error)
        # 内置 finished（线程真正结束）→ 清引用，防悬挂
        thread.finished.connect(self._on_thread_finished)
        self._verify_thread = thread
        self._verify_running = True
        self._update_buttons()
        thread.start()

    def _on_verify_progress(self, done: int, total: int, stage: str) -> None:
        """验证进度：按钮文本承担「可点击取消」与百分比。"""
        pct = int(round(done * 100 / total)) if total else 0
        self.calcButton.setText(f"取消验证 {pct}%")
        self.calcButton.setToolTip(
            f"验证 {stage}: {done}/{total}（点击按钮取消）")

    def _on_verify_finished(self, passed: list, summary: str) -> None:
        """批量验证完成：追加汇总与逐条比对明细，恢复状态。"""
        self._verify_running = False
        self.calcButton.setToolTip("")
        if summary == CANCELLED_SUMMARY:
            self.informationBrowser.append("\n自动验证已取消。")
            self._update_buttons()
            return
        version = self._result_version or self.versionCombo.currentText()
        tol_note = self._tol_summary_line()
        lines = [
            "",
            "———— 自动验证 ————",
            f"{summary}（{tol_note}）",
        ]
        if passed:
            lines.append(
                f"全部 {len(passed)} 个候选均与观测一致 ✓ "
                "（首个如下，完整列表见上方逆推结果）")
            ok, body = verify_candidate_seed(
                passed[0], self._observations, version)
            lines.extend(body)
            lines.append("")
        else:
            lines.append("无候选通过验证，请检查观测坐标或版本。")
        self.informationBrowser.append("\n".join(lines))
        self._update_buttons()

    def _on_verify_error(self, message: str) -> None:
        """批量验证异常：输出原因并恢复状态（计算结果仍保留）。"""
        self._verify_running = False
        self.calcButton.setToolTip("")
        self.informationBrowser.append(
            f"\n自动验证失败：{message}\n（逆推结果仍有效，可手动验证排查。）")
        self._update_buttons()

    # ---------- 清空操作 ----------
    def _on_clear_all(self) -> None:
        """清空全部（带确认对话框）。"""
        confirm = QMessageBox.question(
            self, "清空全部",
            "确定清空所有已采集结构和计算结果？此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._observations.clear()
        self._last_candidates = []
        self._result_version = None
        if self._verify_running and self._verify_thread is not None:
            self._verify_thread.request_cancel()
        self.structList.clear()
        self.coordXEdit.clear()
        self.coordZEdit.clear()
        self.informationBrowser.setPlainText(
            "已清空全部观测与结果。\n\n" + self._initial_help_text())
        self._update_info_bar()
        self._update_refine_buttons()
        self._save_session()

    def _initial_help_text(self) -> str:
        """初始使用说明文本（__init__ 与清空共用）。"""
        return (
            "使用方法：\n"
            "1. 在游戏中找到结构（推荐沉船——海滩常见、易辨认）；\n"
            "2. 站在结构旁，按 F3 读出 X/Z 坐标（或按 F3+C 复制）；\n"
            "3. 在上方选择结构类型，粘贴或输入坐标，点「添加」；\n"
            "4. 重复采集 5 个以上结构（不同区域）的坐标；\n"
            "5. 信息量达标后点「计算」，工具将逆推 48 位结构种候选；\n"
            "6. 计算完成自动验证全部候选并显示比对明细；双击种子可复制，\n"
            "   也可点「验证候选种子」对任意 48 位种子做正向比对。\n"
            "\n"
            "关于站位容差：\n"
            "· 锚点一定在区块的西北角"
            "· 生存模式 F3+C 得到的是玩家站位，不是结构生成锚点；\n"
            "· 建议容差 2：站位与锚点差 ±2 区块内均可命中；\n"
            "· 容差会降低信息量：村庄/试炼几乎失效，请以小型结构为主。\n"
            "\n"
            "群系模式（世界种子精化）：\n"
            "· 勾选「群系模式」展开下方精化面板（勾选前隐藏，结果区自动加高）；\n"
            "· 候选结构种全量导入精化面板，不做数量截断；候选较多时\n"
            "  补充群系观测点即可压缩，精化引擎每候选约 0.2 秒；\n"
            "· 完整使用说明常驻面板内的说明区。"
        )

    # ---------- 结果区交互 ----------
    def eventFilter(self, obj, event) -> bool:
        """双击信息框种子 hex 复制。（锚点 3D 视口自带交互，
        原 label Resize 重绘分支已随平面版移除。）"""
        if (obj is self.informationBrowser
                and event.type() == QEvent.Type.MouseButtonDblClick):
            cursor = self.informationBrowser.textCursor()
            cursor.select(cursor.SelectionType.WordUnderCursor)
            word = cursor.selectedText().strip()
            if _SEED_HEX_RE.fullmatch(word):
                QApplication.clipboard().setText(word)
                self.infoHintLabel.setText(f"已复制 {word}")
                QTimer.singleShot(4000, self._restore_info_hint)
                return True
        return super().eventFilter(obj, event)

    def _restore_info_hint(self) -> None:
        """复制提示超时后恢复信息量提示文本（与信息条同口径）。"""
        obs_list = [obs for obs in self._observations
                    if structure_params.is_reversible(obs["struct_key"])]
        bits = seed_math.calc_info_bits(obs_list)
        self.infoHintLabel.setText(seed_math.info_hint(bits))

    # ---------- 输入校验反馈 ----------
    def _flash_red(self, *edits) -> None:
        """输入校验失败：红框短暂闪烁后恢复。"""
        style = "QLineEdit { border: 2px solid #E74C3C; }"
        for edit in edits:
            edit.setStyleSheet(style)

        def restore():
            for edit in edits:
                edit.setStyleSheet("")

        QTimer.singleShot(600, restore)

    def _coerce_coord(self, raw_text: str, other_text: str, is_x: bool):
        """把输入框内容规整为整数坐标。

        支持两种形式：纯整数（含负号）；整段 F3+C 文本（自动提取 X/Z，
        X 框粘 F3+C 时顺带把 Z 回填给另一框）。

        Returns:
            (value, other_text)：value 为 None 表示解析失败。
        """
        s = raw_text.strip()
        if s:
            try:
                return int(s), other_text
            except ValueError:
                pass
            if looks_like_f3c(s):
                try:
                    x, z, _yaw = parse_f3c_command(s)
                except ValueError:
                    return None, other_text
                if is_x:
                    return int(x), str(int(z))
                return int(z), other_text
        return None, other_text

    # ---------- 精化面板：群系观测录入 ----------
    def _on_add_biome_obs(self) -> None:
        """添加群系观测：坐标校验 + 群系名解析 + 重复检查 → 追加行。

        X 框可粘贴 F3+C 完整文本（自动提取 X/Y/Z，Y 回填到 Y 框）。
        """
        raw_x = self.biomeXEdit.text().strip()
        raw_z = self.biomeZEdit.text().strip()
        raw_y = self.biomeYEdit.text().strip()
        # F3+C 快捷录入：X 框粘贴完整文本时自动填入 X/Y/Z
        if raw_x and not raw_z and looks_like_f3c(raw_x):
            try:
                fx, fy, fz, _yaw = parse_f3c_command_full(raw_x)
                self.biomeXEdit.setText(str(int(fx)))
                self.biomeYEdit.setText(str(int(fy)))
                self.biomeZEdit.setText(str(int(fz)))
                raw_x = self.biomeXEdit.text()
                raw_z = self.biomeZEdit.text()
                raw_y = self.biomeYEdit.text()
            except ValueError:
                pass
        if not raw_x or not raw_z:
            self.refineInfoLabel.setText("请输入 X/Z 方块坐标（Y 可不填）")
            self._flash_red(self.biomeXEdit, self.biomeZEdit)
            return
        try:
            x, z = int(raw_x), int(raw_z)
        except ValueError:
            self.refineInfoLabel.setText("坐标必须是整数方块坐标（如 -1234）")
            self._flash_red(self.biomeXEdit, self.biomeZEdit)
            return
        y = None
        if raw_y:
            try:
                y = int(raw_y)
            except ValueError:
                self.refineInfoLabel.setText("Y 必须是整数方块高度，或留空")
                self._flash_red(self.biomeYEdit)
                return
        bid = resolve_biome(self.biomeNameCombo.currentText())
        if bid is None:
            self.refineInfoLabel.setText(
                f"无法识别群系名：{self.biomeNameCombo.currentText().strip()!r}\n"
                "可从下拉选择，或输入 F3 显示名（中/英文）")
            return
        # 同噪声格去重（信息冗余，直接拒绝；带不同 Y 的同 (x,z) 点有效）
        nx, nz = x >> 2, z >> 2
        ny = (y >> 2) if y is not None else 0
        for o in self._biome_obs:
            if ((o["x"] >> 2) == nx and (o["z"] >> 2) == nz
                    and ((o["y"] >> 2) if o.get("y") is not None else 0) == ny):
                self.refineInfoLabel.setText(
                    f"({x}, {z}, y={y if y is not None else '缺省'}) "
                    "与已有观测位于同一噪声格，信息冗余")
                return
        obs = {"x": x, "z": z, "biome_id": bid}
        if y is not None:
            obs["y"] = y
        self._biome_obs.append(obs)
        self._append_biome_row(len(self._biome_obs), obs)
        self.biomeXEdit.clear()
        self.biomeZEdit.clear()
        self.biomeYEdit.clear()
        self.biomeXEdit.setFocus()
        self._update_refine_buttons()
        self._save_session()

    def _append_biome_row(self, seq: int, obs: dict) -> None:
        """把群系观测追加为 biomeObsList 一行（Y 缺省显示「—”）。

        列 1/2/3/4 允许双击行内编辑（# 列由 delegate 拦截）；
        blockSignals 包裹 addTopLevelItem 防程序化触发 itemChanged。
        """
        item = QTreeWidgetItem([
            str(seq), str(obs["x"]),
            str(obs["y"]) if obs.get("y") is not None else "—",
            str(obs["z"]), biome_label(obs["biome_id"]),
        ])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(0, int(Qt.AlignmentFlag.AlignCenter))
        item.setTextAlignment(1, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        item.setTextAlignment(2, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        item.setTextAlignment(3, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        self.biomeObsList.blockSignals(True)
        try:
            self.biomeObsList.addTopLevelItem(item)
        finally:
            self.biomeObsList.blockSignals(False)

    # ---------- 群系观测：双击行内编辑提交 ----------
    def _on_biome_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """biomeObsList 行内编辑提交：校验 → 回滚或规范化回写。

        程序化回写用 blockSignals 包裹防递归。合法提交后
        刷新精化按钮状态并落盘。
        """
        idx = self.biomeObsList.indexOfTopLevelItem(item)
        if not (0 <= idx < len(self._biome_obs)):
            return
        obs = self._biome_obs[idx]

        # X / Z 列：整数或整段 F3+C 文本
        if column in (1, 3):
            raw = item.text(column).strip()
            if not raw:
                self._rollback_biome_cell(item, obs, column, "坐标不能为空")
                return
            if column == 1 and looks_like_f3c(raw):
                try:
                    fx, fy, fz, _yaw = parse_f3c_command_full(raw)
                except ValueError as exc:
                    self._rollback_biome_cell(item, obs, column,
                                              f"解析 F3+C 失败：{exc}")
                    return
                # 解析返回 float，噪声格运算与存储都用 int
                x, y, z = int(fx), int(fy), int(fz)
            else:
                try:
                    if column == 1:
                        x = int(raw)
                        z = int(item.text(3).strip())
                    else:
                        z = int(raw)
                        x = int(item.text(1).strip())
                    y = obs.get("y")
                except ValueError:
                    self._rollback_biome_cell(
                        item, obs, column,
                        "坐标必须是整数方块坐标（如 -1234），或整段 F3+C 文本")
                    return
            # 同噪声格去重（排除自身；带不同 Y 的同 (x,z) 点有效）
            nx, nz = x >> 2, z >> 2
            ny = (y >> 2) if y is not None else 0
            for i, o in enumerate(self._biome_obs):
                if i == idx:
                    continue
                if ((o["x"] >> 2) == nx and (o["z"] >> 2) == nz
                        and ((o["y"] >> 2) if o.get("y") is not None
                             else 0) == ny):
                    self._rollback_biome_cell(
                        item, obs, column,
                        f"({x}, {z}, y={y if y is not None else '缺省'}) "
                        "与已有观测位于同一噪声格，信息冗余")
                    return
            obs["x"], obs["z"] = x, z
            if y is not None:
                obs["y"] = y
            else:
                obs.pop("y", None)
            self._rewrite_biome_row(item, obs)
            self._after_biome_edit()
            return

        # Y 列：整数或留空（「—」视作留空）
        if column == 2:
            raw = item.text(2).strip()
            if raw in ("", "—"):
                y = None
            else:
                try:
                    y = int(raw)
                except ValueError:
                    self._rollback_biome_cell(
                        item, obs, column, "Y 必须是整数方块高度，或留空")
                    return
            # 换 Y 可能撞上同 (x,z) 噪声格的另一条观测
            ny = (y >> 2) if y is not None else 0
            for i, o in enumerate(self._biome_obs):
                if i == idx:
                    continue
                if ((o["x"] >> 2) == (obs["x"] >> 2)
                        and (o["z"] >> 2) == (obs["z"] >> 2)
                        and ((o["y"] >> 2) if o.get("y") is not None
                             else 0) == ny):
                    self._rollback_biome_cell(
                        item, obs, column,
                        f"y={y if y is not None else '缺省'} "
                        "与已有观测位于同一噪声格，信息冗余")
                    return
            if y is not None:
                obs["y"] = y
            else:
                obs.pop("y", None)
            self._rewrite_biome_row(item, obs)
            self._after_biome_edit()
            return

        # 群系列：双语标签 / F3 别名解析（resolve_biome）
        if column == 4:
            text = item.text(4).strip()
            bid = resolve_biome(text)
            if bid is None:
                self.biomeObsList.blockSignals(True)
                try:
                    item.setText(4, biome_label(obs["biome_id"]))
                finally:
                    self.biomeObsList.blockSignals(False)
                self.refineInfoLabel.setText(
                    f"无法识别群系名：{text!r}，已恢复原群系。\n"
                    "可从下拉选择，或输入 F3 显示名（中/英文）")
                return
            obs["biome_id"] = bid
            self._rewrite_biome_row(item, obs)
            self._after_biome_edit()

    def _rewrite_biome_row(self, item: QTreeWidgetItem, obs: dict) -> None:
        """从 obs 规范化回写整行显示（Y 缺省显示「—」，群系用全标签）。"""
        self.biomeObsList.blockSignals(True)
        try:
            item.setText(1, str(obs["x"]))
            item.setText(2, str(obs["y"]) if obs.get("y") is not None else "—")
            item.setText(3, str(obs["z"]))
            item.setText(4, biome_label(obs["biome_id"]))
        finally:
            self.biomeObsList.blockSignals(False)

    def _rollback_biome_cell(self, item: QTreeWidgetItem, obs: dict,
                             column: int, reason: str) -> None:
        """非法输入回滚：恢复旧显示文本，精化提示区说明原因。"""
        old = {1: str(obs["x"]),
               2: str(obs["y"]) if obs.get("y") is not None else "—",
               3: str(obs["z"]),
               4: biome_label(obs["biome_id"])}.get(column, "")
        self.biomeObsList.blockSignals(True)
        try:
            item.setText(column, old)
        finally:
            self.biomeObsList.blockSignals(False)
        self.refineInfoLabel.setText(f"修改未生效：{reason}\n已恢复原值。")

    def _after_biome_edit(self) -> None:
        """合法提交后的公共收尾：按钮状态 + 落盘。"""
        self._update_refine_buttons()
        self._save_session()

    def _on_paste_biome_f3c(self) -> None:
        """粘贴F3+C：解析剪贴板 F3+C 文本，填入群系面板的 X/Y/Z 输入框。

        与「添加」路径的 F3+C 自动识别共用解析函数（parse_f3c_command_full）。
        群系名无法从 F3+C 文本中提取，填入坐标后光标定位到群系下拉框，
        提示用户手动选择。
        """
        text = QApplication.clipboard().text().strip()
        if not looks_like_f3c(text):
            self.refineInfoLabel.setText(
                "剪贴板内容不是有效的 F3+C 格式。\n"
                "请在游戏中按 F3+C 复制后再点「粘贴F3+C」。")
            self._flash_red(self.biomeXEdit, self.biomeZEdit)
            return
        try:
            x, y, z, _yaw = parse_f3c_command_full(text)
        except ValueError as exc:
            self.refineInfoLabel.setText(f"解析 F3+C 失败：{exc}")
            self._flash_red(self.biomeXEdit, self.biomeZEdit)
            return
        self.biomeXEdit.setText(str(int(x)))
        self.biomeYEdit.setText(str(int(y)))
        self.biomeZEdit.setText(str(int(z)))
        self.biomeNameCombo.setFocus()
        self.biomeNameCombo.setCurrentIndex(-1)
        self.refineInfoLabel.setText(
            "已填入 X/Y/Z：请在下拉框选择或输入当前群系名，然后点「添加」")

    def _update_biome_trailing_icon(self, *_args) -> None:
        """选择/输入变化 → 联动行编辑器尾部的群系图标。

        以 currentText() 精确匹配标准标签为准：匹配到 54 项之一则显示
        对应图标；手动输入任意其他文本或清空选择时移除图标。
        （可编辑组合框的 currentText 即行编辑器文本，两种事件源统一处理）
        """
        icon = self._biome_icons.get(self.biomeNameCombo.currentText())
        self._biome_trailing_action.setIcon(icon if icon is not None
                                            else QIcon())

    def _on_clear_biome_obs(self) -> None:
        self._biome_obs.clear()
        self.biomeObsList.clear()
        self._update_refine_buttons()
        self._save_session()

    def _on_biome_obs_context_menu(self, pos) -> None:
        """群系观测列表右键菜单：删除此条 / 复制坐标。"""
        item = self.biomeObsList.itemAt(pos)
        if item is None:
            return
        idx = self.biomeObsList.indexOfTopLevelItem(item)
        if not (0 <= idx < len(self._biome_obs)):
            return
        obs = self._biome_obs[idx]
        menu = QMenu(self)
        act_delete = menu.addAction("删除此条")
        act_copy = menu.addAction("复制坐标")
        chosen = menu.exec(self.biomeObsList.viewport().mapToGlobal(pos))
        if chosen is act_delete:
            del self._biome_obs[idx]
            self.biomeObsList.takeTopLevelItem(idx)
            for i in range(self.biomeObsList.topLevelItemCount()):
                self.biomeObsList.topLevelItem(i).setText(0, str(i + 1))
            self._update_refine_buttons()
            self._save_session()
        elif chosen is act_copy:
            if obs.get("y") is not None:
                QApplication.clipboard().setText(
                    f"{obs['x']}, {obs['y']}, {obs['z']}")
            else:
                QApplication.clipboard().setText(f"{obs['x']}, {obs['z']}")

    # ---------- 精化面板：计算 ----------
    def _on_refine_clicked(self) -> None:
        """精化按钮：空闲时启动线程；运行中点击 = 停止。"""
        if self._refine_running:
            if self._refine_thread is not None:
                self._refine_thread.request_cancel()
                self.refineButton.setText("停止中…")
                self.refineButton.setEnabled(False)
            return
        cands = self._parse_candidate_text(self.candidateSeedEdit.text())
        if not cands:
            self.refineInfoLabel.setText("候选种子无效：请导入或手动输入")
            return
        if len(self._biome_obs) < _MIN_BIOME_OBS:
            self.refineInfoLabel.setText(
                f"群系观测不足：需要 ≥{_MIN_BIOME_OBS} 个"
                f"（当前 {len(self._biome_obs)} 个）")
            return
        obs = [{"x": o["x"], "z": o["z"], "biome_id": o["biome_id"],
                "y": o.get("y")}
               for o in self._biome_obs]
        self.worldSeedDetailBrowser.setPlainText("正在精化世界种子…")

        thread = WorldSeedRefineThread(
            cands, obs, self.versionCombo.currentText(), parent=self)
        thread.progress.connect(self._on_refine_progress)
        thread.refine_finished.connect(self._on_refine_finished)
        thread.error.connect(self._on_refine_error)
        thread.finished.connect(self._on_refine_thread_finished)
        self._refine_thread = thread
        self._refine_running = True
        self._update_refine_buttons()
        thread.start()

    def _on_refine_progress(self, done: int, total: int, msg: str) -> None:
        """精化进度只驱动进度条；按钮与信息标签文案由状态切换统一管理
        （运行中按钮固定「停止精化」，infoLabel 固定「精化中…」）。"""
        pct = int(round(done * 100 / total)) if total else 0
        self.refineProgressBar.setValue(pct)

    def _on_refine_finished(self, result: dict, summary: str) -> None:
        self._refine_running = False
        self.refineProgressBar.setValue(100 if result.get("world_seeds") else 0)
        if summary == _REFINE_CANCELLED_SUMMARY:
            self.refineInfoLabel.setText("精化已取消")
            self.worldSeedDetailBrowser.setPlainText("精化已取消。")
            self._update_refine_buttons()
            return
        seeds = result.get("world_seeds", [])
        if not seeds:
            self.worldSeedDetailBrowser.setPlainText(
                "———— 未命中 ————\n"
                "没有任何 64 位种子能同时满足这些观测。\n"
                "可能原因：\n"
                "  1. 观测点群系抄错 / 坐标跨过噪声格边界；\n"
                "  2. 候选结构种不含真值（重跑结构逆推或补充结构观测）；\n"
                "  3. 版本选择与实际世界不符。\n"
                "\n———— 统计 ————\n" + summary)
        elif len(seeds) == 1:
            s = seeds[0]
            self.worldSeedDetailBrowser.setPlainText(
                f"———— 世界种子 ————\n"
                f"{s}\n"
                f"hex: 0x{s & ((1 << 64) - 1):016X}\n"
                "\n———— 统计 ————\n" + summary)
        else:
            lines = [f"———— 多解（{len(seeds)} 个候选，需人工核对）————"]
            lines += [f"  {s}" for s in seeds]
            lines += ["", "———— 统计 ————", summary]
            self.worldSeedDetailBrowser.setPlainText("\n".join(lines))
        if seeds:
            QApplication.clipboard().setText(
                "\n".join(str(s) for s in seeds))
            self.refineInfoLabel.setText(
                f"命中 {len(seeds)} 个世界种子，已复制到剪贴板")
            NotificationWidget.Show(
                "世界种子精化完成",
                f"命中 {len(seeds)} 个候选\n"
                f"首个: {seeds[0]}\n"
                "已复制到剪贴板，详情见精化面板",
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )
        else:
            NotificationWidget.Show(
                "世界种子精化未命中",
                "没有种子满足全部观测\n详见精化面板",
                5000, title_size=13, message_size=12)
        self._update_refine_buttons()

    def _on_refine_error(self, message: str) -> None:
        self._refine_running = False
        self.refineProgressBar.setValue(0)
        self.worldSeedDetailBrowser.setPlainText(
            "———— 无法精化 ————\n" + message)
        NotificationWidget.Show(
            "精化出错", message[:60] + ("…" if len(message) > 60 else ""),
            5000, title_size=13, message_size=12)
        self._update_refine_buttons()

    def _on_refine_thread_finished(self) -> None:
        if self._refine_thread is not None and not self._refine_thread.isRunning():
            self._refine_thread = None

    def _on_refine_clear(self) -> None:
        """清除精化：候选 + 观测 + 结果全部复位。"""
        self.candidateSeedEdit.clear()
        self._on_clear_biome_obs()
        self.refineProgressBar.setValue(0)
        self.worldSeedDetailBrowser.setPlainText(_REFINE_DETAIL_INITIAL)
        self._update_refine_buttons()
        # _on_clear_biome_obs 已落盘；候选框文本变化需再次保存
        self._save_session()

    # ---------- 快捷键 ----------
    def _on_escape(self) -> None:
        """Esc：计算/验证中取消；空闲时清空输入框。"""
        if self._calc_running:
            if self._calc_thread is not None:
                self._calc_thread.request_cancel()
                self.calcButton.setText("取消中…")
                self.calcButton.setEnabled(False)
            return
        if self._verify_running:
            if self._verify_thread is not None:
                self._verify_thread.request_cancel()
                self.calcButton.setText("取消中…")
                self.calcButton.setEnabled(False)
            return
        self.coordXEdit.clear()
        self.coordZEdit.clear()
        self.coordXEdit.setFocus()

    # ---------- 会话持久化（观测数据重启不丢） ----------
    def _session_path(self) -> str:
        """会话文件路径（用户配置目录下 seed_reverser_session.json）。"""
        config_dir = QStandardPaths.writableLocation(
            QStandardPaths.AppConfigLocation)
        if not config_dir:
            config_dir = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, _SESSION_FILE)

    def _save_session(self) -> None:
        """把当前采集状态写入会话文件（数据变化点与退出时调用）。

        只保存输入侧状态（观测/候选/选项），输出文本（结果区/精化
        详情）由启动后的初始文本承担；恢复完成前不落盘（_session_ready
        抑制半恢复状态写盘）。观测列表仅主线程修改，读写无并发风险。
        """
        if not self._session_ready:
            return
        try:
            data = {
                "version": self.versionCombo.currentText(),
                "biome_mode": self.biomeModeCheckBox.isChecked(),
                "observations": [
                    {k: obs[k] for k in ("struct_key", "name", "x", "z",
                                         "reg_x", "reg_z", "off_x", "off_z",
                                         "near_boundary", "tol")}
                    for obs in self._observations
                ],
                "candidates": list(self._last_candidates),
                "result_version": self._result_version,
                "biome_obs": [dict(o) for o in self._biome_obs],
                "candidate_text": self.candidateSeedEdit.text(),
            }
            with open(self._session_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"保存种子逆推会话失败: {e}")

    def _restore_session(self) -> None:
        """启动时从会话文件恢复（文件缺失/损坏时静默跳过）。"""
        path = self._session_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
        except (OSError, ValueError) as e:
            print(f"恢复种子逆推会话失败: {e}")
            return

        # 全局选项（版本切换会刷新结构下拉，须在恢复观测前执行）
        version = data.get("version")
        if isinstance(version, str) and \
                self.versionCombo.findText(version) >= 0:
            self.versionCombo.setCurrentText(version)

        # 结构观测：逐条独立校验，坏条目跳过不阻止其余恢复。
        # 兼容旧格式：旧文件无逐条 tol，用旧全局 "tol"（缺省 0）统一继承；
        # 新格式逐条 "tol" 优先；非法值回退默认容差表。
        legacy_tol = data.get("tol")
        if not isinstance(legacy_tol, int) or not (0 <= legacy_tol <= 2):
            legacy_tol = 0
        for raw in data.get("observations", []):
            obs = self._rebuild_observation(raw, version or
                                            self.versionCombo.currentText(),
                                            legacy_tol)
            if obs is not None:
                self._observations.append(obs)
                status = "边界!" if obs["near_boundary"] else "OK"
                self._append_list_row(len(self._observations), obs, status)

        candidates = data.get("candidates")
        if isinstance(candidates, list):
            self._last_candidates = [
                s for s in candidates
                if isinstance(s, int) and 0 <= s < (1 << 48)
            ]
        rv = data.get("result_version")
        if isinstance(rv, str) and \
                self.versionCombo.findText(rv) >= 0:
            self._result_version = rv

        # 群系观测（biome_id 只存数字，显示时由 biome_label 反查）
        for raw in data.get("biome_obs", []):
            try:
                obs = {"x": int(raw["x"]), "z": int(raw["z"]),
                       "biome_id": int(raw["biome_id"])}
                if not (0 <= obs["biome_id"] <= 255):
                    continue
                y = raw.get("y")
                if y is not None:
                    obs["y"] = int(y)
            except (KeyError, TypeError, ValueError):
                continue
            self._biome_obs.append(obs)
            self._append_biome_row(len(self._biome_obs), obs)

        text = data.get("candidate_text")
        if isinstance(text, str) and text:
            self.candidateSeedEdit.setText(text)
        if data.get("biome_mode"):
            self.biomeModeCheckBox.setChecked(True)

        self._update_info_bar()
        self._update_refine_buttons()
        self._update_buttons()

    def _rebuild_observation(self, raw, version: str, legacy_tol: int = 0) -> dict | None:
        """从会话 dict 重建结构观测（params 按保存时版本重算）。

        结构键无效（参数表已移除该结构等）返回 None；坐标字段在采集
        时已固化，region/offset 不随重建变化。容差：新格式逐条 "tol"
        优先；缺省回退 legacy_tol（旧文件的全局值）；仍非法再回退
        默认容差表（保证恢复后的观测总带合法 tol）。
        """
        if not isinstance(raw, dict):
            return None
        try:
            struct_key = raw["struct_key"]
            params = structure_params.get_params(struct_key, version)
            tol = raw.get("tol", legacy_tol)
            if isinstance(tol, bool) or not isinstance(tol, int) or not (0 <= tol <= 2):
                tol = structure_params.get_default_tolerance(struct_key)
            return {
                "struct_key": struct_key,
                "name": params["name"],
                "x": int(raw["x"]), "z": int(raw["z"]),
                "reg_x": int(raw["reg_x"]), "reg_z": int(raw["reg_z"]),
                "off_x": int(raw["off_x"]), "off_z": int(raw["off_z"]),
                "near_boundary": bool(raw["near_boundary"]),
                "tol": tol,
                "params": params,
            }
        except (KeyError, TypeError, ValueError):
            return None

    def save_config(self) -> None:
        """主窗口退出协议（save_all_tools_config）：保存采集会话。"""
        self._save_session()

    # ---------- 线程管理 ----------
    def _stop_calc_thread(self) -> None:
        """停止全部计算线程（应用退出前调用；重复调用无副作用）。

        结构逆推在层间检查取消标志（块粒度约 0.1~0.5 秒）；批量验证
        在候选间检查（单候选微秒级，随时可停）；精化枚举在候选间与
        高位步进间检查（native 引擎下整轮不到 1 秒）。
        wait(5000) 足够；不使用 terminate（强杀线程会破坏 Qt 状态）。
        另：停掉 3D 视口的变种轮播 QTimer——退出阶段运行中的
        QTimer 被析构会 0xC0000409 崩溃（PySide6 已知坑）。
        """
        self._anchor_view.stop_variant_timer()
        for thread in (self._calc_thread, self._verify_thread, self._refine_thread):
            if thread is None:
                continue
            try:
                if thread.isRunning():
                    thread.request_cancel()
                    thread.wait(5000)
            except RuntimeError:
                # 退出阶段 C++ 对象可能已被析构，防御性忽略
                pass
        self._calc_thread = None
        self._verify_thread = None
        self._refine_thread = None

    def closeEvent(self, event) -> None:
        """窗口关闭时停止计算线程（aboutToQuit 的双保险）。"""
        self._stop_calc_thread()
        super().closeEvent(event)
