# -*- coding: utf-8 -*-
"""存档管理器（SaveManager）工具：浏览/管理本地 MC 存档 + 地形俯视预览入口。

Phase 1（本文件当前范围）：存档管理外壳——扫描存档目录、列表展示（图标+名称+
版本）、详情（名称+版本）、全套操作（打开文件夹/重命名/删除→回收站/备份/导出）。

地形俯视图的渲染公共组件（Utils/Public/map_render）与可视化在后续阶段接入
右侧 mapView；本文件先把管理外壳做扎实、可独立交付使用。

设计要点：
- 存档目录来自设置 saves_dir（settings_config.json），缺省回退到项目默认 MC
  根目录；设置窗口可改（见 tool_Settings）。
- 扫描兼容多版本分散布局（<root>/saves 与 <root>/versions/*/saves）。
- 重命名走 level_dat.write_level_name（外科式字节补丁，不整体重序列化）。
- 删除走回收站（fs_utils.move_to_recycle_bin，调用前二次确认）。
- 备份=复制到用户所选目录（带时间戳）；导出=打包为 zip。
"""
import os
import shutil
import zipfile

from datetime import datetime

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QIcon, QKeyEvent, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QInputDialog,
                               QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox,
                               QPushButton, QSizePolicy)

from .tool_base import BaseToolWidget
from CodesUI.SaveManager import Ui_SaveManager
from Utils.Public.notification import NotificationWidget
from Utils.Public.map_render.terrain_view import TerrainView
from Utils.SaveManager.level_dat import write_level_name
from Utils.SaveManager.save_scanner import default_saves_root, scan_saves
from Utils.SaveManager.save_config import load_saves_dir
from Utils.SaveManager.save_info import SaveInfo
from Utils.SaveManager.version_map import version_display
from Utils.SaveManager.fs_utils import move_to_recycle_bin, open_in_explorer

# 通知样式（与项目其它工具一致）
_NOTIFY_DURATION_MS = 4000
_NOTIFY_TITLE_SIZE = 14
_NOTIFY_MESSAGE_SIZE = 12
_NOTIFY_PADDING = (16, 12, 16, 12)


# ---- locate 指令辅助表 ----
# 村庄变种 → 推演群系过滤表：推演引擎只有统一的 village 键（内部
# 自动覆盖 5 种变种），变种查询时用命中群系 id 过滤。
# biome id 与 Utils.Public.structure_map 常量一致（MEADOW=177 按
# cubiomes finders.c L1622 语义视为平原变种）。
_VARIANT_BIOMES = {
    "village_plains": (1, 177),    # PLAINS, MEADOW
    "village_desert": (2,),        # DESERT
    "village_savanna": (35,),      # SAVANNA
    "village_taiga": (5,),         # TAIGA
    "village_snowy": (12,),        # SNOWY_PLAINS
}
# 村庄变种显示名（解析法直接从 NBT 键读到 village_plains 等）
_VARIANT_NAMES = {
    "village_plains": "村庄（平原）",
    "village_desert": "村庄（沙漠）",
    "village_savanna": "村庄（热带草原）",
    "village_taiga": "村庄（针叶林）",
    "village_snowy": "村庄（雪原）",
}


def _version_key_of(version_name: str) -> str | None:
    """存档版本名 → 推演引擎版本键（"26.2"/"1.21.11"/"1.21"）。

    structure_map/BiomeSampler 只认这三个键；version_name 形如
    "1.21.11-NeoForge"（前缀匹配），匹配不到返回 None（调用方
    降级到 NBT 解析法）。
    """
    vn = (version_name or "").lower()
    if vn.startswith("26.2"):
        return "26.2"
    if vn.startswith("1.21.11"):
        return "1.21.11"
    if vn.startswith("1.21"):
        return "1.21"
    return None


def _struct_display_name(struct_key: str) -> str:
    """结构键 → 中文显示名（村庄变种表 + 参数表，未知回退原键）。"""
    from Utils.Public import structure_params
    return structure_params.STRUCT_NAMES.get(
        struct_key,
        _VARIANT_NAMES.get(struct_key, struct_key))


class SaveManagerWidget(BaseToolWidget, Ui_SaveManager):
    preferred_size = (1000, 700)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # 数据：全部存档 / 当前过滤后可见 / 选中项。
        # 须在 _adapt_layout 之前初始化——_build_dimension_bar 会读取
        # _current_dimension 设定维度按钮的初选状态。
        self._saves: list[SaveInfo] = []
        self._shown: list[SaveInfo] = []
        self._current: SaveInfo | None = None
        self._current_dimension = "overworld"

        self._adapt_layout()
        self._connect_signals()
        # 应用退出钩子：先停地形渲染线程再析构（避免运行中 QThread 被销毁崩溃）
        QApplication.instance().aboutToQuit.connect(self.terrain_view.shutdown)
        self._scan_and_populate()

    # ---------- 基类元信息 ----------
    @classmethod
    def tool_name(cls) -> str:
        return "SaveManager"

    # ---------- 布局/信号 ----------
    def _adapt_layout(self):
        """地图视图区伸展（Phase 1 为占位，Phase 3 接入地形视图）。"""
        from PySide6.QtWidgets import QSizePolicy
        # 用 TerrainView 替换 .ui 生成的 mapView 占位（QGraphicsView）
        old = self.mapView
        self.terrain_view = TerrainView(self)
        self.terrain_view.setObjectName("mapView")
        self.rightLayout.replaceWidget(old, self.terrain_view)
        old.hide()
        self.mapView = self.terrain_view
        self.mapView.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # rightLayout 第 3 项（mapView）竖直伸展
        self.rightLayout.setStretch(2, 1)
        # 主布局右侧（详情区）水平伸展，左侧列表取自身 sizeHint
        self.mainLayout.setStretch(1, 1)
        # 维度切换（主世界/下界/末地）插入地图上方
        self._build_dimension_bar()
        # 悬停信息实时显示到状态栏
        self.terrain_view.hover_info.connect(self._on_hover)
        # 指令框（按 / 键呼出）
        self._build_command_bar()
        # 渲染进度条与坐标信息同高度：把 statusLabel 包进水平行（文字在
        # 左吃掉伸展，进度条固定宽贴右）。TerrainView 只发 (total, done)
        # 信号，进度条控件与显隐由本侧管理（total=0 隐藏）。
        from PySide6.QtWidgets import QHBoxLayout, QProgressBar, QWidget
        row = QWidget(self)
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        idx = self.rightLayout.indexOf(self.statusLabel)
        self.rightLayout.removeWidget(self.statusLabel)
        row_lay.addWidget(self.statusLabel, 1)
        self.progBar = QProgressBar(row)
        self.progBar.setFormat("已渲染 %v / %m 区块")
        self.progBar.setFixedWidth(220)
        self.progBar.hide()
        row_lay.addWidget(self.progBar)
        self.rightLayout.insertWidget(idx, row)
        self.terrain_view.progress_changed.connect(self._on_progress)

    def _build_dimension_bar(self) -> None:
        """在 ops 与地图之间插入维度切换按钮行（QButtonGroup 互斥）。"""
        from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox,
                                       QHBoxLayout, QPushButton, QWidget)
        bar = QWidget(self)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        self._dim_group = QButtonGroup(self)
        self._dim_group.setExclusive(True)
        self._dim_buttons: dict[str, QPushButton] = {}
        for dim, label in (("overworld", "主世界"),
                           ("nether", "下界"),
                           ("end", "末地")):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(dim == self._current_dimension)
            self._dim_group.addButton(btn)
            self._dim_buttons[dim] = btn
            lay.addWidget(btn)
            btn.clicked.connect(lambda _=False, d=dim: self._on_dimension(d))
        lay.addStretch(1)
        self.hillshadeCheck = QCheckBox("地形阴影")
        self.hillshadeCheck.setChecked(True)   # 默认开（渲染线程初始值同步）
        self.hillshadeCheck.setToolTip(
            "用高度梯度+西北光源给地形加明暗起伏（更像 3D）")
        self.hillshadeCheck.toggled.connect(self._on_hillshade)
        lay.addWidget(self.hillshadeCheck)
        # 内容区域下拉：分散存档（服务器下载等）的独立地形块列表，
        # 选择即定位（由 terrain_view 的并查集分量提供）
        self.regionCombo = QComboBox()
        self.regionCombo.setToolTip(
            "存档里互相独立的区域（按已生成 chunk 的 8 邻接合并，\n"
            "region 文件内的破碎地形也能拆开；\n"
            "半生成空壳区块组成的分量已剔除）；\n"
            "打开存档时已自动定位到最大的区域")
        self.regionCombo.setMinimumWidth(160)
        self.regionCombo.currentIndexChanged.connect(self._on_region_group)
        lay.addWidget(self.regionCombo)
        # 插到 rightLayout 的 mapView（index 2）之前
        self.rightLayout.insertWidget(2, bar)

    def _on_dimension(self, dim: str) -> None:
        self._current_dimension = dim
        if self._current is not None and self._current.is_supported:
            self.terrain_view.set_save(self._current.path, dim)
            self._refresh_region_combo()

    def _refresh_region_combo(self) -> None:
        """从 terrain_view 的并查集分量列表填充「内容区域」下拉框。
        已自动定位到分量 0（最大块），其余块选择即跳转。"""
        combo = self.regionCombo
        combo.blockSignals(True)
        combo.clear()
        groups = getattr(self.terrain_view, "_region_groups", [])
        if groups:
            for i, g in enumerate(groups):
                combo.addItem(f"区域 {i + 1}｜{g['count']} 个区块")
        else:
            combo.addItem("无地形数据")
        combo.setEnabled(bool(groups))
        combo.setCurrentIndex(0)
        combo.blockSignals(False)
        if groups:
            ax, az = groups[0]["anchor"]
            self.statusLabel.setText(
                f"共 {len(groups)} 个独立区域，已定位到最大区域"
                f"（中心约 X={ax * 16 + 8}, Z={az * 16 + 8}）")

    def _on_region_group(self, idx: int) -> None:
        """下拉框选择：跳转到对应独立区域（跳转自身有缩放适配）。"""
        if idx >= 0:
            self.terrain_view.jump_to_region_group(idx)

    def _on_hillshade(self, on: bool) -> None:
        self.terrain_view.set_hillshade(on)

    def _build_command_bar(self) -> None:
        """指令框：按 / 键呼出，支持 locate <结构类型> 和 tp <x> <z> 指令。"""
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget
        bar = QWidget(self)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(4, 2, 4, 2)
        
        # 提示标签（/ 开头）
        prompt = QLabel("/", self)
        prompt.setStyleSheet("font-weight: bold; color: #666;")
        
        # 指令输入框
        self.cmdInput = QLineEdit(self)
        self.cmdInput.setPlaceholderText(
            "输入指令：locate <结构类型> 或 tp <x> <z>（如：/locate village 或 /tp 1000 -2000）"
        )
        self.cmdInput.returnPressed.connect(self._on_command)
        
        lay.addWidget(prompt)
        lay.addWidget(self.cmdInput, 1)
        
        # 默认隐藏，按 / 键呼出
        bar.hide()
        self.cmdBar = bar
        
        # 插入到维度按钮行下方（rightLayout index 1）
        self.rightLayout.insertWidget(1, bar)
    
    def keyPressEvent(self, ev: QKeyEvent) -> None:
        """快捷键：/ 键呼出指令框。"""
        if ev.key() == Qt.Key_Slash and not self.cmdInput.hasFocus():
            # 显示指令框并聚焦（/ 字符不入框，用户直接输入指令内容）
            self.cmdBar.show()
            self.cmdInput.setFocus()
            ev.accept()
            return
        super().keyPressEvent(ev)
    
    def _on_command(self) -> None:
        """执行指令框输入的指令。"""
        text = self.cmdInput.text().strip()
        if not text:
            return
        
        # 去除前导 /（如果输入了）
        if text.startswith("/"):
            text = text[1:].strip()
        
        parts = text.split(maxsplit=1)
        if not parts:
            return
        
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        if cmd == "locate":
            self._cmd_locate(args)
        elif cmd == "tp":
            self._cmd_tp(args)
        else:
            QMessageBox.warning(self, "指令错误",
                               f"未知指令：{cmd}\n支持：locate / tp")
    
    def _cmd_locate(self, args: str) -> None:
        """locate <结构类型>：推演最近结构并跳转。
        
        有种子：用 structure_map 推演（可推演未生成区域）；
        无种子：从已生成的 chunk NBT 解析（structures.starts.Children.BB）。
        """
        if not self._current or not self._current.is_supported:
            QMessageBox.warning(self, "无法定位", "请先选择支持地形预览的存档")
            return
        
        struct_type = args.strip()
        if not struct_type:
            QMessageBox.information(self, "指令用法",
                "locate <结构类型>\n\n示例：\n"
                "  /locate village\n"
                "  /locate village_plains\n"
                "  /locate mineshaft\n"
                "  /locate ancient_city\n\n"
                "主世界结构（18 种）：\n"
                "  village / pillager_outpost / desert_pyramid\n"
                "  jungle_temple / swamp_hut / igloo / shipwreck\n"
                "  ocean_ruin / monument / mansion / ancient_city\n"
                "  trail_ruins / trial_chambers / ruined_portal\n"
                "  stronghold / buried_treasure / mineshaft / desert_well\n\n"
                "村庄变种（5 种，可选）：\n"
                "  village_plains（平原）\n"
                "  village_desert（沙漠）\n"
                "  village_savanna（热带草原）\n"
                "  village_taiga（针叶林）\n"
                "  village_snowy（雪原）\n"
                "  不指定变种则查找所有村庄\n\n"
                "下界结构（2 种，需切换到下界维度）：\n"
                "  nether_fortress / bastion_remnant\n\n"
                "末地结构（1 种，需切换到末地维度）：\n"
                "  end_city")
            return
        
        try:
            from Utils.Public import structure_map, structure_params
            from Utils.SaveManager.level_dat import read_save_info, region_dir_for
            from Utils.Public.map_render.region_reader import RegionFile
            import os
            
            info = read_save_info(self._current.path)
            
            # 当前视口中心
            scene_center = self.terrain_view.mapToScene(
                self.terrain_view.viewport().rect().center())
            cx, cz = int(scene_center.x()), int(scene_center.y())
            
            # 维度检查：下界/末地结构必须切到对应维度（两种策略都受约束）
            need_dim = structure_params.STRUCT_DIMENSION.get(
                struct_type, "overworld")
            if need_dim != self._current_dimension:
                QMessageBox.information(
                    self, "维度不匹配",
                    f"{struct_type} 位于"
                    f"{structure_params.DIMENSION_NAMES.get(need_dim, need_dim)}，"
                    f"请先切换到对应维度再定位")
                return
            
            # 策略 1：有种子 → 推演（可覆盖未生成区域）
            if info.seed:
                vkey = _version_key_of(info.version_name)
                structures = None   # None = 未执行/降级；list = 推演结果
                if vkey is not None:
                    # 村庄变种 → 用统一的 village 键推演后按命中群系过滤
                    search_key = struct_type
                    biome_filter = None
                    if struct_type in _VARIANT_BIOMES:
                        search_key = "village"
                        biome_filter = _VARIANT_BIOMES[struct_type]
                    try:
                        # enumerate_structures 的 viewport 是方块坐标
                        # （含端点）；±512 区块 = ±8192 方块
                        chunk_radius = 512
                        radius_blocks = chunk_radius * 16
                        viewport = (
                            cx - radius_blocks,
                            cz - radius_blocks,
                            cx + radius_blocks,
                            cz + radius_blocks,
                        )
                        structures = structure_map.enumerate_structures(
                            info.seed, vkey, viewport,
                            struct_keys=(search_key,),
                            dimension=self._current_dimension)
                        if biome_filter is not None:
                            structures = [s for s in structures
                                          if s.get("biome") in biome_filter]
                    except ValueError as e:
                        if "不支持" in str(e):
                            structures = None   # 版本不支持推演 → 降级解析法
                        else:
                            raise
                if structures is not None:
                    if not structures:
                        QMessageBox.information(
                            self, "定位结果",
                            f"在视口周围 ±512 区块内未找到：\n{struct_type}")
                        return
                    nearest = min(structures, key=lambda s:
                                  (s["x"] - cx) ** 2 + (s["z"] - cz) ** 2)
                    self.terrain_view.centerOn(nearest["x"], nearest["z"])
                    dist = ((nearest["x"] - cx) ** 2
                            + (nearest["z"] - cz) ** 2) ** 0.5
                    st_name = _struct_display_name(
                        struct_type if struct_type in _VARIANT_NAMES
                        else nearest["struct"])
                    QMessageBox.information(
                        self, "定位成功（种子推演）",
                        f"结构：{st_name}\n"
                        f"坐标：X={nearest['x']}, Z={nearest['z']}\n"
                        f"距离：{dist:.0f} 方块 ({dist/16:.0f} 区块)\n\n"
                        f"（基于种子精确推演，包含未生成区域）")
                    return
            
            # 策略 2：无种子或推演不支持 → 解析已生成结构（chunk NBT）
            
            # 策略 2：无种子或推演失败 → 解析已生成结构（chunk NBB）
            rdir = region_dir_for(self._current.path, self._current_dimension)
            if not rdir or not os.path.isdir(rdir):
                QMessageBox.warning(self, "无法定位",
                                   "该存档无种子信息，且未找到 region 目录\n"
                                   "（仅支持解析已生成的结构）")
                return
            
            # 扫描已生成的结构（从 chunk NBT）
            found_structures = []
            region_files = sorted([f for f in os.listdir(rdir) if f.endswith(".mca")])
            
            # 限制扫描范围（避免遍历过多文件）：以视口为中心 ±64 region
            rx_center = cx // 512
            rz_center = cz // 512
            scan_radius = 64
            
            for rf_name in region_files:
                rx = int(rf_name.split(".")[1])
                rz = int(rf_name.split(".")[2])
                
                # 跳过范围外的 region
                if abs(rx - rx_center) > scan_radius or abs(rz - rz_center) > scan_radius:
                    continue
                
                rf_path = os.path.join(rdir, rf_name)
                rf = RegionFile(rf_path)
                if rf is None:
                    continue
                
                # 扫描 region 内的 32×32 chunks
                for local_cx in range(32):
                    for local_cz in range(32):
                        abs_cx = rx * 32 + local_cx
                        abs_cz = rz * 32 + local_cz
                        chunk = rf.read_chunk(abs_cx, abs_cz)
                        
                        if chunk and "structures" in chunk:
                            starts = chunk.get("structures", {}).get("starts", {})
                            
                            for st_type, data in starts.items():
                                # 宽松匹配：忽略 minecraft: 前缀
                                # 用户输入 "village" 匹配 "minecraft:village" 或 "village"
                                # 用户输入 "village_plains" 匹配 "minecraft:village_plains"
                                normalized_input = struct_type.lower()
                                normalized_nbt = st_type.lower().replace("minecraft:", "")
                                
                                # 精准匹配逻辑：
                                # - 用户输入 "village" → 匹配所有村庄变种（village_plains, village_desert 等）
                                # - 用户输入 "village_plains" → 仅匹配 village_plains
                                if normalized_input == "village":
                                    # 匹配所有村庄变种
                                    if not normalized_nbt.startswith("village_") and normalized_nbt != "village":
                                        continue
                                else:
                                    # 精准匹配（包括 village_plains 等变种）
                                    if normalized_input != normalized_nbt:
                                        continue
                                
                                if isinstance(data, dict):
                                    children = data.get("Children", [])
                                    for child in children:
                                        bb = child.get("BB", [])
                                        if bb and len(bb) >= 4:
                                            # BB 西北角 ≈ 锚点（95% 准确）
                                            bx, bz = bb[0], bb[2]
                                            # 显示完整类型（包括变种）
                                            display_type = st_type.replace("minecraft:", "")
                                            found_structures.append({
                                                "struct": display_type,
                                                "x": bx,
                                                "z": bz,
                                            })
            
            if not found_structures:
                QMessageBox.information(self, "定位结果",
                                       f"在已生成的区块中未找到：{struct_type}\n\n"
                                       f"扫描范围：视口中心 ±{scan_radius * 32} 区块\n"
                                       f"（仅解析已生成的结构，未生成区域无法定位）")
                return
            
            # 取最近的
            nearest = min(found_structures, key=lambda s:
                          (s["x"] - cx) ** 2 + (s["z"] - cz) ** 2)
            
            # 跳转
            self.terrain_view.centerOn(nearest["x"], nearest["z"])
            
            # 提示
            dist = ((nearest["x"] - cx) ** 2 + (nearest["z"] - cz) ** 2) ** 0.5
            QMessageBox.information(self, "定位成功（解析已生成结构）",
                                   f"结构：{_struct_display_name(nearest['struct'])}\n"
                                   f"坐标：X={nearest['x']}, Z={nearest['z']}\n"
                                   f"距离：{dist:.0f} 方块 ({dist/16:.0f} 区块)\n\n"
                                   f"（从已生成的 chunk NBT 解析，仅覆盖已生成区域）")
        
        except Exception as e:
            QMessageBox.critical(self, "定位失败",
                               f"解析结构时出错：\n{e}")
    
    def _cmd_tp(self, args: str) -> None:
        """tp <x> <z>：移动视图到指定坐标。"""
        parts = args.strip().split()
        if len(parts) < 2:
            QMessageBox.information(self, "指令用法",
                "tp <x> <z>\n\n示例：\n  /tp 1000 -2000\n  /tp 0 64")
            return
        
        try:
            x, z = int(parts[0]), int(parts[1])
            self.terrain_view.centerOn(x, z)
            QMessageBox.information(self, "传送成功",
                                   f"已移动到坐标：X={x}, Z={z}")
        except ValueError:
            QMessageBox.warning(self, "指令错误",
                               "坐标必须是整数\n\n示例：/tp 1000 -2000")

    def _connect_signals(self) -> None:
        self.refreshButton.clicked.connect(self._on_refresh)
        self.searchEdit.textChanged.connect(self._on_search)
        self.saveList.currentRowChanged.connect(self._on_select)
        self.openFolderButton.clicked.connect(self._on_open_folder)
        self.renameButton.clicked.connect(self._on_rename)
        self.deleteButton.clicked.connect(self._on_delete)
        self.backupButton.clicked.connect(self._on_backup)
        self.exportButton.clicked.connect(self._on_export)
        # 右键地图 -> 操作当前区块（区块 3D 预览弹窗）
        self.terrain_view.chunk_action.connect(self._on_chunk_action)

    # ---------- 扫描与列表 ----------
    def _resolve_root(self) -> str:
        return load_saves_dir(default_saves_root())

    def _scan_and_populate(self, keep_path: str | None = None) -> None:
        root = self._resolve_root()
        try:
            self._saves = scan_saves(root)
        except OSError as exc:
            self._saves = []
            self.statusLabel.setText(f"扫描失败：{exc}")
            self._populate("")
            return
        self._populate(self.searchEdit.text())
        supported = sum(1 for s in self._saves if s.is_supported)
        self.statusLabel.setText(
            f"共 {len(self._saves)} 个存档（支持地形预览 {supported} 个）"
            f"｜根目录：{root}")
        if keep_path:
            for i, s in enumerate(self._shown):
                if s.path == keep_path:
                    self.saveList.setCurrentRow(i)
                    break

    def _populate(self, filter_text: str) -> None:
        ft = (filter_text or "").strip().lower()
        # 重名检测：跨版本重名时在名称后附版本消歧
        from collections import Counter
        name_counts = Counter(s.name.lower() for s in self._saves)

        self.saveList.clear()
        self._shown = []
        for s in self._saves:
            if ft and ft not in s.name.lower():
                continue
            item = QListWidgetItem()
            if s.icon_path and os.path.isfile(s.icon_path):
                pix = QPixmap(s.icon_path)
                if not pix.isNull():
                    item.setIcon(QIcon(pix.scaled(
                        32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)))
            text = s.name
            if name_counts.get(s.name.lower(), 0) > 1:
                text = f"{s.name}  ({s.version_name or '?'})"
            item.setText(text)
            item.setToolTip(
                f"版本：{s.version_name or '?'}\n"
                f"来源：{s.source}\n"
                f"{'已有地形数据，可预览' if s.has_terrain else '无地形数据'}")
            self.saveList.addItem(item)
            self._shown.append(s)
        if not self._shown:
            self._current = None
            self._show_detail(None)

    # ---------- 选择 ----------
    def _on_select(self, row: int) -> None:
        if 0 <= row < len(self._shown):
            self._current = self._shown[row]
            self._show_detail(self._current)
        else:
            self._current = None
            self._show_detail(None)

    def _show_detail(self, save: SaveInfo | None) -> None:
        if save is None:
            self.nameLabel.setText("未选择存档")
            self.versionLabel.setText("")
            self.iconLabel.setPixmap(QPixmap())
            self._set_ops_enabled(False)
            self.terrain_view.clear()
            self._refresh_region_combo()
            return
        self.nameLabel.setText(save.name)
        ver = version_display(save.version_name, save.data_version)
        suffix = ("｜1.18+，支持地形预览" if save.is_supported
                  else "｜版本过旧（<1.18），不支持地形预览")
        self.versionLabel.setText(ver + suffix)
        if save.icon_path and os.path.isfile(save.icon_path):
            pix = QPixmap(save.icon_path)
            self.iconLabel.setPixmap(pix.scaled(
                72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            self.iconLabel.setPixmap(QPixmap())
        self._set_ops_enabled(True)
        self.statusLabel.setText(f"已选择：{save.name}｜{save.source}")
        # 地形预览：支持的存档以当前维度渲染；不支持的清空
        if save.is_supported:
            self.terrain_view.set_save(save.path, self._current_dimension)
            self._refresh_region_combo()
        else:
            self.terrain_view.clear()
            self._refresh_region_combo()

    def _on_hover(self, text: str) -> None:
        """地形视图悬停信息实时显示到状态栏。"""
        self.statusLabel.setText(text)

    def _on_progress(self, total: int, done: int) -> None:
        """地形渲染进度（按区块计数）：total=0 表示无活动批次，隐藏。"""
        bar = self.progBar
        if total <= 0:
            bar.hide()
            return
        bar.setRange(0, total)
        bar.setValue(min(done, total))
        bar.show()

    def _set_ops_enabled(self, enabled: bool) -> None:
        for w in (self.openFolderButton, self.renameButton,
                  self.deleteButton, self.backupButton,
                  self.exportButton):
            w.setEnabled(enabled)

    # ---------- 操作 ----------
    def _on_refresh(self) -> None:
        self._scan_and_populate()

    def _on_search(self, text: str) -> None:
        self._populate(text)

    def _on_open_folder(self) -> None:
        if self._current:
            open_in_explorer(self._current.path)

    def _on_rename(self) -> None:
        s = self._current
        if not s:
            return
        new_name, ok = QInputDialog.getText(
            self, "重命名存档", "请输入新的存档名称：", text=s.name)
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        if new_name == s.name:
            return
        success, err = write_level_name(s.path, new_name)
        if not success:
            QMessageBox.warning(self, "重命名失败", err or "未知错误")
            return
        self._notify("重命名成功", f"已重命名为：{new_name}")
        # 重新扫描以刷新显示（名称来自 level.dat）
        self._scan_and_populate()

    def _on_delete(self) -> None:
        s = self._current
        if not s:
            return
        confirm = QMessageBox.warning(
            self, "删除存档",
            f"确定将以下存档移入回收站？\n\n{s.name}\n（可在回收站还原）\n\n{s.path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        success, err = move_to_recycle_bin(s.path)
        if not success:
            QMessageBox.warning(self, "删除失败", err or "未知错误")
            return
        self._notify("已移入回收站", f"{s.name} 已删除（可在回收站还原）")
        self._current = None
        self._show_detail(None)
        self._scan_and_populate()

    def _on_backup(self) -> None:
        s = self._current
        if not s:
            return
        default_dir = os.path.dirname(s.path.rstrip("\\/"))
        dest_parent = QFileDialog.getExistingDirectory(
            self, "选择备份目标文件夹（将在此下新建备份）", default_dir)
        if not dest_parent:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c for c in s.name
                            if c not in '\\/:*?"<>|').strip() or "world"
        dest = os.path.join(dest_parent, f"{safe_name}_备份_{stamp}")
        try:
            shutil.copytree(s.path, dest)
        except (OSError, shutil.Error) as exc:
            QMessageBox.warning(self, "备份失败", str(exc))
            return
        self._notify("备份完成", f"已备份到：\n{dest}")

    def _on_export(self) -> None:
        s = self._current
        if not s:
            return
        default_name = "".join(c for c in s.name
                               if c not in '\\/:*?"<>|').strip() or "world"
        out_path, _ = QFileDialog.getSaveFileName(
            self, "导出存档为 zip",
            os.path.join(os.path.dirname(s.path.rstrip("\\/")),
                         default_name + ".zip"),
            "Zip 文件 (*.zip)")
        if not out_path:
            return
        if not out_path.lower().endswith(".zip"):
            out_path += ".zip"
        base_dir = os.path.dirname(s.path.rstrip("\\/"))
        try:
            with zipfile.ZipFile(out_path, "w",
                                 zipfile.ZIP_DEFLATED) as zf:
                for root, _dirs, files in os.walk(s.path):
                    for fname in files:
                        fp = os.path.join(root, fname)
                        arc = os.path.relpath(fp, base_dir)
                        zf.write(fp, arc)
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self._notify("导出完成", f"已导出到：\n{out_path}")

    # ---------- 通知 ----------
    def _notify(self, title: str, message: str) -> None:
        NotificationWidget.Show(
            title, message, _NOTIFY_DURATION_MS,
            title_size=_NOTIFY_TITLE_SIZE,
            message_size=_NOTIFY_MESSAGE_SIZE,
            padding=_NOTIFY_PADDING)

    # ---------- 区块 3D 预览（右键）----------
    def _on_chunk_action(self, wx: int, wz: int) -> None:
        """右键地图 -> 打开指向区块的 3D 预览弹窗。

        wx/wz 是右键点处的世界方块坐标（terrain_view 换算）；
        chunk 坐标 = 世界坐标 // 16。需已选存档（有 _current 与维度）。
        """
        if self._current is None:
            QMessageBox.information(self, "区块预览", "请先选择一个存档")
            return
        cx = wx // 16
        cz = wz // 16
        ChunkPreviewDialog.open(self._current.path, self._current_dimension,
                                cx, cz, parent=self)


# ---------------------------------------------------------------------------
# 区块 3D 预览（chunk voxel 提取 + 弹窗，复用 Structure3DView 渲染管线）
# ---------------------------------------------------------------------------
# 区块垂直范围（与 chunk_render.MIN_Y 一致）：1.18+ 世界 Y ∈ [-64, 319]，
# 共 24 个 section（sec_y ∈ [-4, 19]）。预览体素的 Y 用「相对 chunk 底部
# 的局部坐标」——3D 视口只需块相对结构，与 StructurePreviewer 模型同口径
# （其 voxels 已平移到 min_y=0）。
_CHUNK_MIN_Y = -64
_CHUNK_MAX_Y = 319
# 空气族（不进入 3D 体素；chunk_render 的 _AIR_LIKE 同集）
_CHUNK_AIR = frozenset({"minecraft:air", "minecraft:cave_air",
                        "minecraft:void_air"})


def chunk_to_voxels(built: dict) -> dict:
    """已 build_chunk 的区块数据 -> 3D 体素 {(lx, ly_local, lz): voxel_value}。

    精确复现：用 built["states"]（Name + Properties 完整方块状态）逐格还原
    几何。每个方块的体素值与 StructurePreviewer 模板体素同口径：
      - None（空气/装饰/作物）跳过
      - 基材质字符串 = 整格实体块
      - (基材质, 形状码) = 台阶/楼梯/门/栅栏等非完整方块，build_mesh 按
        形状码生成精确 AABB 几何。

    映射链与 _voxels_from_template_file 一致：台阶按 type=bottom/top/double
    选 half/full mode（bottom 半格、top 上格、double 整块），形状码由
    shape_from_props 依 Properties（facing/half/axis 等）还原。局部
    Y = 世界 Y - _CHUNK_MIN_Y，使体素原点落在 chunk 底（与结构模型
    voxels 同口径，便于视口自适应相机）。
    """
    from Utils.SeedReverser.structure_models import (
        _map_block, _palette_entry_half, _palette_entry_props)
    from Utils.SeedReverser import block_shapes as bs
    states = built.get("states") or built.get("blocks") or {}
    vox: dict = {}
    for sec_y, lookup in states.items():
        if lookup is None:
            continue
        for ly in range(16):
            wy = sec_y * 16 + ly
            if wy < _CHUNK_MIN_Y or wy > _CHUNK_MAX_Y:
                continue
            y_local = wy - _CHUNK_MIN_Y
            for lz in range(16):
                for lx in range(16):
                    got = lookup(ly, lz, lx)
                    # states lookup 返回 (name, props)；兼容旧 blocks
                    # lookup（仅 name str）
                    if isinstance(got, tuple):
                        name, props = got
                    else:
                        name, props = got, {}
                    if not name or name in _CHUNK_AIR:
                        continue
                    # 流体检测（water/lava + level 属性）
                    if "water" in name or "lava" in name:
                        props_dict = props if isinstance(props, dict) else {}
                        level_str = props_dict.get("level", "0")
                        try:
                            level = int(level_str)
                        except (ValueError, TypeError):
                            level = 0
                        fluid_type = "water" if "water" in name else "lava"
                        # 流体形状码：fluid:<level>:<type>
                        # level=0 源（满格）、1-7 流动（递降）、8 下落（满格）
                        mat = _map_block(name, "full")
                        if mat is None:
                            continue
                        shape = f"fluid:{level}:{fluid_type}"
                        vox[(lx, y_local, lz)] = (mat, shape)
                        continue
                    # 滴水石锥：官方模型是 cross 十字片（同花草几何），
                    # 十变体仅贴图不同 —— 按状态生成精确材质键
                    # "pointed dripstone <dir> <thickness>"（10 张变体
                    # 纹理已全量入库），几何走 SHAPE_PLANT
                    if name == "minecraft:pointed_dripstone":
                        props_dict = props if isinstance(props, dict) else {}
                        d = ("down" if props_dict.get("vertical_direction")
                             == "down" else "up")
                        th = props_dict.get("thickness", "tip")
                        if th not in ("tip", "frustum", "middle", "base",
                                      "tip_merge"):
                            th = "tip"
                        mat = f"pointed dripstone {d} {th}".replace(
                            "_", " ")
                        vox[(lx, y_local, lz)] = (mat, bs.SHAPE_PLANT)
                        continue
                    typ = _palette_entry_half_from_props(props)
                    mode = "full" if typ in ("top", "double") else "half"
                    mat = _map_block(name, mode)
                    if mat is None:
                        continue
                    shape = bs.shape_from_props(name, props)
                    half_prefix = (isinstance(mat, str)
                                   and mat.startswith("halfheight:"))
                    base = mat[len("halfheight:"):] if half_prefix else mat
                    if shape is None and half_prefix and typ != "double":
                        # 无 Properties 形状的旧前缀材质按底半格
                        shape = bs.SHAPE_SLAB_BOT
                    vox[(lx, y_local, lz)] = (base, shape) \
                        if shape is not None else base
    return vox


def _palette_entry_half_from_props(props: dict) -> str:
    """从已解析的 Properties dict 取 slab type（bottom/top/double/''）。"""
    v = props.get("type", "")
    return v if isinstance(v, str) else ""


class ChunkPreviewDialog:
    """区块 3D 预览弹窗（惰性构造单例）。

    右键地图 -> _on_chunk_action(wx, wz) -> open_chunk_preview 取本区块
    NBT、转 3D 体素、复用 Structure3DView（SeedReverser 3D 视口，原生
    OpenGL）渲染。视口嵌在普通 QDialog 里（与 StructurePreviewer 同款
    接入：Structure3DView 替换布局占位）。

    单例 + 显式关闭回调：关闭对话框时停视口动画定时器并置空引用，防
    关闭期 QOpenGLWidget 在 GL 上下文销毁后回调（0xC0000409）。
    """
    _instance = None

    def __init__(self):
        from PySide6.QtWidgets import QDialog
        self._dlg = QDialog()
        self._dlg.setWindowTitle("区块 3D 预览")
        self._dlg.resize(760, 620)
        self._dlg.setModal(False)
        from PySide6.QtWidgets import QVBoxLayout, QLabel
        lay = QVBoxLayout(self._dlg)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        # 信息标签：区块坐标 + 体素规模
        self._info = QLabel("")
        self._info.setWordWrap(True)
        lay.addWidget(self._info)
        # 3D 视口（复用 SeedReverser 结构视口）
        from Utils.SeedReverser import structure_3dview
        self._view = structure_3dview.Structure3DView()
        # 旁观者相机（WASD+鼠标 FP 飞行），与 StructurePreviewer 同体验
        self._view.set_spectator_mode(True)
        lay.addWidget(self._view, 1)
        self._dlg.finished.connect(self._on_closed)
        self._loaded = False

    def _on_closed(self) -> None:
        try:
            self._view.stop_variant_timer()
        except Exception:
            pass
        self._loaded = False

    def load_chunk(self, world_path: str, dimension: str,
                   cx: int, cz: int) -> bool:
        """读取并渲染指定区块。成功返回 True（弹窗可见）。"""
        from Utils.Public.map_render.region_reader import (
            RegionFile, region_path_for)
        from Utils.SeedReverser.structure_models import build_mesh
        from Utils.Public.map_render.chunk_render import build_chunk
        import os

        rpath = region_path_for(world_path, dimension, cx // 32, cz // 32)
        if not rpath or not os.path.isfile(rpath):
            self._info.setText(
                f"区块 ({cx}, {cz}) 所在 region 文件不存在：\n{rpath or '路径拼不出'}")
            self._dlg.show()
            self._dlg.raise_()
            return False
        rf = RegionFile(rpath)
        chunk = rf.read_chunk(cx & 31, cz & 31)
        if chunk is None:
            self._info.setText(f"区块 ({cx}, {cz}) 未生成或不可读（空 chunk）")
            self._dlg.show()
            self._dlg.raise_()
            return False
        built = build_chunk(chunk)
        vox = chunk_to_voxels(built)
        if not vox:
            self._info.setText(f"区块 ({cx}, {cz}) 无可见方块（全空气/装饰）")
            self._dlg.show()
            self._dlg.raise_()
            return False
        # 组装 3D model（与 StructurePreviewer.compose_display_model 同格式）
        xs = [p[0] for p in vox]
        zs = [p[2] for p in vox]
        ys = [p[1] for p in vox]
        size = (max(xs) + 1, max(ys) - min(ys) + 1, max(zs) + 1)
        tex_keys = sorted({(m[0] if isinstance(m, tuple) else m)
                           for m in vox.values()})
        mesh = build_mesh(vox)
        model = {"key": f"chunk:{cx},{cz}", "variant": None,
                 "voxels": vox, "size": size, "mesh": mesh,
                 "tex_keys": tex_keys}
        self._view.set_model(model)
        self._info.setText(
            f"区块 ({cx}, {cz})　｜　体素 {len(vox):,}"
            f"　｜　尺寸 {size[0]}×{size[1]}×{size[2]}\n"
            "操作：WASD 飞行、鼠标拖动转视角　｜　右上角「渲染模型」开启绘制")
        self._dlg.show()
        self._dlg.raise_()
        self._loaded = True
        return True

    @classmethod
    def open(cls, world_path: str, dimension: str, cx: int, cz: int,
             parent=None) -> None:
        if cls._instance is None:
            cls._instance = cls()
        cls._instance.load_chunk(world_path, dimension, cx, cz)
