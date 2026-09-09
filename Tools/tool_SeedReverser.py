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

from PySide6.QtCore import QEvent, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QHeaderView,
                               QInputDialog, QMenu, QMessageBox,
                               QTreeWidgetItem)

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
from Utils.SeedReverser import seed_math, structure_params
from Utils.SeedReverser.biome_names import BIOME_CHOICES, biome_label, resolve_biome
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
    "village": "无严格中心；水井或钟（meeting point）附近最接近锚点",
    "desert_pyramid": "约21×21神殿的西北角（神殿向东南展开），常埋沙下",
    "igloo": "雪屋一角（屋子向东南展开）",
    "swamp_hut": "小屋一角（小屋向东南展开）",
    "jungle_temple": "庙宇一角（长廊向东南延伸）",
    "shipwreck": "船体一角（常见半埋沙滩/海底，看露出部分一角）",
    "ocean_ruin": "废墟一角（遗迹向东南展开）",
    "pillager_outpost": "瞭望塔底座一角",
    "monument": "神殿主体一角（向东南展开）",
    "mansion": "府邸一角（主体向东南展开）",
    "ancient_city": "城区内（范围极大，站位误差常超容差）",
    "trail_ruins": "废墟中心附近（多埋地下）",
    "trial_chambers": "入口走廊附近（多在深地下）",
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
    "  实测一致率仅 70%~88%，繁茂洞穴/溶洞会在深层大面积\n"
    "  覆盖地表群系，导致真种子被误拒。\n"
    "· 建议站在开阔地表采样，避开洞穴内、海底与山地陡坡。")

# 精化结果区初始内容 = 完整使用说明 + 待精化提示（常驻说明，精化结果覆盖显示）
_REFINE_DETAIL_INITIAL = _BIOME_MODE_HELP_TEXT + (
    "\n"
    "————————————————————————————\n"
    "尚未精化。精化结果（世界种子/多解/统计）将显示在这里。")


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
        # 版本下拉（1.21 默认）
        self.versionCombo.addItems(structure_params.VERSION_KEYS)
        self.versionCombo.setCurrentIndex(0)

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

        # 信息量条：0~48 比特，不显示数字文字（infoHintLabel 承担提示）
        self.infoProgressBar.setRange(0, 48)
        self.infoProgressBar.setValue(0)
        self.infoProgressBar.setTextVisible(False)

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

        self.biomeObsList.customContextMenuRequested.connect(
            self._on_biome_obs_context_menu)

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

    def _reload_struct_combo(self) -> None:
        """按当前版本刷新结构类型下拉（尽量保留原选中项）。"""
        version = self.versionCombo.currentText()
        keep_key = self.structTypeCombo.currentData()
        self.structTypeCombo.blockSignals(True)
        self.structTypeCombo.clear()
        for key in structure_params.available_structures(version):
            params = structure_params.get_params(key, version)
            bits = seed_math.calc_info_bits([params])
            name = structure_params.struct_key_to_name(key)
            self.structTypeCombo.addItem(f"{name}（约 {bits:.1f} 比特/个）", key)
        # 恢复原选中项（新版本仍可用时）
        if keep_key is not None:
            idx = self.structTypeCombo.findData(keep_key)
            if idx >= 0:
                self.structTypeCombo.setCurrentIndex(idx)
        self.structTypeCombo.blockSignals(False)
        self._on_struct_type_changed()

    # ---------- 信息量条与按钮状态 ----------
    def _update_info_bar(self) -> None:
        """重算信息量、刷新进度条颜色与提示文本、联动按钮状态。"""
        params_list = [obs["params"] for obs in self._observations]
        bits = seed_math.calc_info_bits(params_list)
        self.infoProgressBar.setValue(int(round(bits)))
        color = _INFO_BAR_COLOR_GOOD
        for upper, sec_color in _INFO_BAR_SECTIONS:
            if bits < upper:
                color = sec_color
                break
        self.infoProgressBar.setStyleSheet(
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
        """把观测追加为 structList 一行（第 6 列为行内容差下拉框）。"""
        item = QTreeWidgetItem([
            str(seq),
            obs["name"],
            str(obs["x"]),
            str(obs["z"]),
            f"({obs['reg_x']}, {obs['reg_z']})",
            "",          # 容差列：setItemWidget 注入 QComboBox，不存文本
            status,
        ])
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
        self.structList.addTopLevelItem(item)
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

    def _on_biome_mode_toggled(self, checked: bool) -> None:
        """群系模式开关：显隐精化面板，结果区高度随布局自然伸缩。

        informationBrowser 为垂直 Expanding：隐藏 refineGroupBox 时
        自动吃掉让出的空间（结果区加高）；显示时布局把空间还给
        groupbox（结果区缩短），无需手动干预高度。
        """
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
        bits = seed_math.calc_info_bits([obs["params"] for obs in self._observations])

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
            "最适合参与逆推；海底神殿、林地府邸、远古城市、前哨站只能"
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
            "4. 重复采集 3~6 个不同结构（不同区域）的坐标；\n"
            "5. 信息量达标后点「计算」，工具将逆推 48 位结构种候选；\n"
            "6. 计算完成自动验证全部候选并显示比对明细；双击种子可复制，\n"
            "   也可点「验证候选种子」对任意 48 位种子做正向比对。\n"
            "\n"
            "关于站位容差：\n"
            "· 生存模式 F3+C 得到的是玩家站位，不是结构生成锚点；\n"
            "· 精确模式（容差 0）需要站在锚点方块上，几乎不可用；\n"
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
        """双击信息框中的种子 hex → 复制到剪贴板。"""
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
        """复制提示超时后恢复信息量提示文本。"""
        bits = seed_math.calc_info_bits([obs["params"] for obs in self._observations])
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
        item = QTreeWidgetItem([
            str(seq), str(obs["x"]),
            str(obs["y"]) if obs.get("y") is not None else "—",
            str(obs["z"]), biome_label(obs["biome_id"]),
        ])
        item.setTextAlignment(0, int(Qt.AlignmentFlag.AlignCenter))
        item.setTextAlignment(1, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        item.setTextAlignment(2, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        item.setTextAlignment(3, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        self.biomeObsList.addTopLevelItem(item)

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
        if version in structure_params.VERSION_KEYS:
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
        if rv in structure_params.VERSION_KEYS:
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
        """
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
