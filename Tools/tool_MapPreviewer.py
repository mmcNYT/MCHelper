# -*- coding: utf-8 -*-
"""MapPreviewer 工具：世界俯视群系图渲染 + 21 种结构图标化标注。

结构标记用 Wiki EnvSprite 图标（村庄按生成群系区分变体图标），
无论缩放级别屏幕大小恒定（JourneyMap 式）；图标缺失时回退红圈。

使用流程：
1. 选择游戏版本、输入种子（支持负数与 0x 十六进制）、选视野半径、
   切换维度（主世界/下界/末地，worldCombo）；
2. 「选择结构」弹窗勾选要标注的结构，点「生成地图」；
3. 后台线程两阶段计算：地形采样（native 引擎秒级）→ 结构枚举
   （正向定位 + cubiomes 位级群系校验，杜绝「应生成却没生成」误报）；
4. 地图上：滚轮缩放（锚点缩放）、按住拖动平移、悬停查看坐标与群系、
   点击结构标记复制对应 /tp 传送命令；
5. 定位：坐标输入框（默认 0,0）回车把视图中心移到该坐标；结构定位
   下拉选一个结构自动查找，群系定位下拉选一个群系（可输入匹配）
   自动查找，找到离输入坐标最近的实例/出现位置后，红色虚线连接
   定位点并直接显示两端坐标，视角自动缩放到两点可见（换回首项
   或右键虚线删除路径；结构定位与群系定位互斥，后定位者自动
   移除前一定位；拖动地图后坐标隐藏）；右键地图可把该点坐标
   直接填入定位输入框（X/Z 栏）。

说明：
- 无限地图：初始视野以 (0,0) 为中心的方形区域（半径 512~4096 方块）
  仅决定首屏渲染范围；拖动/缩小后新区域由瓦片线程自动采样渲染
  （渐进铺满，不受初始半径限制）；
- LOD 双档：视口可见宽 ≤512 方块时 1 方块=1 像素精细渲染（block），
  更宽视野 4 方块合 1 像素快速渲染（cell），初始渲染与增量渲染
  均须 <5s；
- 结构判定与 cubiomes finders.c isViableStructurePos 位级一致
  （对拍 1560 点全过，含真实存档验证的 6 条结构观测）；
- 进度数字只在进度条展示；按钮单状态机「生成地图 ↔ 停止渲染」；
- 会话持久化：版本/种子/半径/结构选择实时落盘（用户配置目录
  map_previewer_session.json），重启自动恢复；
- 工具内不调用 setApplicationName（会话目录由主进程应用名决定）。
"""

import json
import os

from collections import OrderedDict

from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtCore import (QEvent, QPointF, QRectF, QStandardPaths, Qt,
                            QTimer)
from PySide6.QtWidgets import (QApplication, QComboBox, QCompleter,
                               QGraphicsItem, QGraphicsLineItem,
                               QGraphicsPixmapItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView,
                               QMenu, QToolTip)

from .tool_base import BaseToolWidget
from CodesUI.MapPreviewer import Ui_mapPreviewer
from Threads.task_MapPreviewer import (
    CANCELLED_SUMMARY,
    BiomeLocateThread,
    DIM_BIOME_TABLES,
    MapPreviewerThread,
    StructureLocateThread,
    StructureScanThread,
    TileRenderThread,
    _TILE_BLOCKS,
)
from Utils.AutoBackUp.notification import NotificationWidget
from Utils.MapPreviewer import structure_icons as st_icons
from Utils.MapPreviewer.biome_colors import biome_cn_name
from Utils.MapPreviewer.choose_structure import ChooseStructureWindow
from Utils.MapPreviewer.structure_map import available_structures
from Utils.SeedReverser import biome_names
from Utils.SeedReverser.structure_params import DIMENSION_NAMES, STRUCT_NAMES

# 会话文件名（用户配置目录下）
_SESSION_FILE = "map_previewer_session.json"
# 结构标记半径（场景像素，即方块单位；图标缺失时的红圈回退用）
_MARKER_R = 10.0
# 结构图标显示尺寸（屏幕像素，ItemIgnoresTransformations 下恒定，
# 不随地图缩放变化——JourneyMap 式标记；16x16 精灵就近放大，
# 像素风与游戏一致，放大的不透明像素即悬停热区）
_MARK_ICON_SIZE = 28
# 标记命中半径（场景单位=方块；点击复制与悬停 tooltip 共用判定）
_MARKER_HIT_R = 14.0
# 增量结构扫描：视口扩边（结构锚点容错）与单次扫描边长上限（方块）。
# 上限 8192 = 最大半径 4096 地图边长：极端缩小时扫描量钳在与
# 全图初始枚举同量级（<1s），再大的视野由「更新结构」按钮全量处理
_SCAN_MARGIN = 128
_SCAN_MAX_SIDE = 8192
# 通知样式（与 SeedReverser 一致）
_NOTIFY_DURATION_MS = 6000
_NOTIFY_TITLE_SIZE = 16
_NOTIFY_MESSAGE_SIZE = 14
_NOTIFY_PADDING = (20, 16, 20, 16)


# 视野半径下拉文本 → 方块半径（与 CodesUI 下拉项一致；512/1024 已移除）
_RADIUS_MAP = {"2048": 2048, "4096": 4096}

# 缩放钳制范围（视口缩放比 = 屏幕像素/方块）：最小取全图适配值
# 略下（4096 半径适配约 0.13，不裁边）；再小会让视口需要的瓦片
# 总量超出缓存预算导致重复渲染（见 _CACHE_WEIGHT_BUDGET 注释）
_ZOOM_MIN_SCALE = 0.13
_ZOOM_MAX_SCALE = 4.0
# 瓦片缓存加权预算（加权 LRU）：cell 瓦片（256x256x3）权重 1，
# block 瓦片（1024x1024x3）内存 ≈16 倍、权重 6（折中取值）。
# 预算须 ≥ 极限缩小视口所需瓦片总量（m11=0.13 时 1080p 视口约
# 9x7=63 格，2.5K 屏约 20x14=280 格），否则铺满过程会互相淘汰、
# 永远补不齐；400 ≈ 78MB（cell 全占）~200MB（block 满 66 块）
_CACHE_WEIGHT_BUDGET = 400
_CACHE_W_BLOCK = 6
# 单批瓦片数上限：每批 <1s 上屏（距视口中心近的优先），完成后
# batch_done 零延迟续批直至视口补齐（渐进铺满）
_TILE_BATCH_MAX = 8
# 续批轮次上限（兜底：防极端视口/缓存互柜导致无限补渲染）。
# 实时淘汰已限制为只逐视口外瓦片（见 _evict_tiles），续批不会
# 自吞刚渲染的瓦片，轮次只受视口容量/单批大小约束，300 足够
_MAX_FILL_ROUNDS = 300
# 可导航世界边界（方块）：±2^21，与采样器安全范围一致。必须显式
# 设为场景矩形，否则 QGraphicsScene 的自动 sceneRect 跟随已铺
# 瓦片包围盒，视图拖拽/centerOn 会被钳在已渲染区域内，永远
# 滚不出去，也永远触发不了范围外补渲染（无限地图失效）
_WORLD_LIMIT = 1 << 21

# 「常用」预设结构（与 SeedReverser 观测用版本表的易找顺序一致）
_COMMON_STRUCTS = ("village", "desert_pyramid", "swamp_hut")

# 维度下拉索引 → 维度键（CodesUI worldCombo：0=主世界 1=下界 2=末地）
_DIM_COMBO_INDEX = {0: "overworld", 1: "nether", 2: "end"}

# 结构定位：定位点标记半径与虚线样式（红色虚线 + 上方距离文本，
# IgnoresTransformations 恒定屏幕大小，同结构标记风格）
_LOC_PIN_R = 6.0
_LOC_PIN_COLOR = QColor(255, 64, 64)
_LOC_LINE_COLOR = QColor(255, 64, 64, 220)
_LOC_LINE_WIDTH = 2.0
_LOC_TEXT_COLOR = QColor(255, 96, 96)
_LOC_TEXT_PT = 10
# 定位视角适配：两点包围盒外扩边距（方块）与最小视宽（太近时
# 仍拉到可辨识的视野，避免过度放大）
_LOC_VIEW_PAD = 0.25   # 相对包围盒边长的比例
_LOC_VIEW_MIN_SPAN = 384.0
# 端点坐标标签防遮挡：基础避让量按屏幕像素设计（覆盖浮板图
# 标视觉半宽 18px = 36px 画布/2），_make_coord_label 按当前
# 缩放换算成场景单位——纯场景单位抬升在缩小时收缩，恒定屏幕
# 大小的图标会压住标签
_COORD_LIFT_PX = 24.0
# 图标浮起展示（仿 MC 物品展示图：灰色方形底板承托图标 + 右下
# 偏移的柔和暗影，顶光浮起观感；画在屏幕像素级，与恒定屏幕大小
# 的图标一致）
_MARK_PAD = 4    # 合成画布四周留影空间（px）
_MARK_PIX_SIZE = _MARK_ICON_SIZE + _MARK_PAD * 2
_MARK_PLATE = QColor(148, 148, 148)   # 底板灰（截图取色 #949494）
_MARK_SHADOW = QColor(58, 58, 58)     # 影基色（#3A3A3A），分层淡出
# 暗影分层（左上扩, 右下扩, alpha）：由外向内四级叠加渐浓（最外
# 层极淡作过渡），右下比左上延伸更远（顶光投影）；数值经渲染采样校准
_SHADOW_LAYERS = ((3, 4, 18), (2, 4, 36), (1, 3, 60), (1, 2, 110))


def _compose_plate_icon(src: QPixmap) -> QPixmap:
    """源图标 → 灰色方形底板 + 右下偏移柔和暗影（36px 画布）：
    28px 灰板居中，图标就近缩放到 24px 内缩其上（2px 边距），
    暗影用三层错位矩形由外向内叠加渐浓、右下延伸更远——
    模拟物品浮起展示的顶光投影观感；透明底合成。"""
    s = _MARK_PIX_SIZE
    out = QPixmap(s, s)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    plate = QRectF(_MARK_PAD, _MARK_PAD, _MARK_ICON_SIZE, _MARK_ICON_SIZE)
    for grow_lt, grow_rb, alpha in _SHADOW_LAYERS:
        c = QColor(_MARK_SHADOW)
        c.setAlpha(alpha)
        p.fillRect(QRectF(plate.left() - grow_lt, plate.top() - grow_lt,
                          plate.width() + grow_lt + grow_rb,
                          plate.height() + grow_lt + grow_rb), c)
    p.fillRect(plate, _MARK_PLATE)
    pm = src.scaled(_MARK_ICON_SIZE - 4, _MARK_ICON_SIZE - 4,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation)
    if not pm.isNull():
        p.drawPixmap(_MARK_PAD + 2, _MARK_PAD + 2, pm)
    p.end()
    return out

# 区块网格（半透明，16 方块一格）
_CHUNK_GRID_SIZE = 16
_CHUNK_GRID_COLOR = QColor(255, 255, 255, 28)


class MapPreviewerWidget(BaseToolWidget, Ui_mapPreviewer):
    preferred_size = (1081, 801)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # 后台渲染线程（None 表示空闲）
        self._thread = None
        self._running = False
        # 视野结构扫描线程（None 表示空闲；地图生成后拖动/缩放补结构）
        self._scan_thread = None
        self._scan_retired: list = []   # 已放弃但在跑的扫描线程（防析构崩溃）
        self._scan_epoch = 0   # 结构扫描批序号（递增；迟到结果丢弃）
        self._scan_covered = None   # 已覆盖结构扫描的世界矩形 (bx0,bz0,bx1,bz1)
        # 已知结构去重表：(struct, x, z) → 结果 dict（初始+增量扫描合并）
        self._structs_seen: dict = {}
        self._has_map = False   # 是否已有生成过的地图（决定按钮文案）
        # 瓦片增量渲染线程（None 表示空闲；拖动/缩放时补渲染新区域）
        self._tile_thread = None
        # 已放弃但可能仍在跑的瓦片线程（保引用防析构崩溃，
        # finished 回调统一回收）
        self._tile_retired: list = []
        # 最近一次渲染载荷（悬停查询/重绘开关/瓦片坐标系用）
        self._last: dict | None = None
        # 已渲染瓦片表：{(tx, tz): QPixmap}（tx/tz 为瓦片格坐标；
        # OrderedDict 实现 LRU，超上限淘汰最久未用）
        self._tiles: "OrderedDict" = OrderedDict()
        # 场景中的瓦片像素项：{(tx, tz): QGraphicsPixmapItem}
        self._tile_items: dict = {}
        # 每块瓦片的 LOD 档（"block"/"cell"；与 _tiles 同键同步增删）
        self._tile_lod: dict = {}
        # 当前瓦片批序号（递增；旧线程的迟到结果按序号丢弃）
        self._tile_epoch = 0
        # 渐进铺满续批轮次（用户交互触发时清零；超上限停止补渲染）
        self._fill_rounds = 0
        # 网格图形项（重绘开关时快速移除/重建）
        self._grid_item = None
        # 结构标记（点击复制用）
        self._markers: list = []
        self._hover_tip_item = None   # 当前主动 tooltip 指向的标记
        # 结构选择集（勾选状态；None = 尚未初始化）。
        # 选择按维度分桶：_selected 恒为当前维度的选择，其余维度的
        # 选择保存在 _selected_other（维度切换时互换，互不丢失）
        self._selected: set[str] | None = None
        self._selected_other: dict[str, set] = {}
        self._active_dimension = "overworld"
        # 维度采样器缓存（悬停范围外探测用；(seed, dim) → sampler 实例，
        # 避免每次 MouseMove 重建 256 次洗牌的 Perlin 初始化）
        self._probe_samplers: dict = {}
        # 维度切换取消在途渲染后，迟到的「已停止」不覆盖切换提示
        self._suppress_finished_label = False
        # 会话持久化：恢复完成前抑制实时保存
        self._session_ready = False
        # 显示开关（右键菜单切换）；地形阴影（hillshade）默认开启，
        # 切换后提示重新生成地图生效（不自动重渲染）
        self._grid_on = True
        self._hillshade_on = True
        # 结构定位线程（None 表示空闲；同扫描线程的保引用策略）
        self._locate_thread = None
        self._locate_retired: list = []
        self._locate_epoch = 0   # 定位批序号（递增；迟到结果丢弃）
        # 定位场景项（定位点/虚线/距离与坐标标签；换图/重渲染/
        # 新定位时清除）
        self._locate_items: list = []
        # 定位链端点坐标标签（任务④：定位后直接显示，拖动地图后
        # 隐藏；图标项也入列，setVisible 对其是无害空操作）
        self._coord_labels: list = []
        # 定位激活状态：定位成功的结构键/定位点(红点方块坐标)/定位
        # 实例（图标强制显示与「移除定位」用；换种子/版本复位）
        self._locate_struct_key: str | None = None
        self._locate_point: tuple[int, int] | None = None
        self._locate_inst: dict | None = None
        self._locate_dist: float = 0.0
        # 群系定位线程（None 空闲；同结构定位的保引用策略）
        self._biome_thread = None
        self._biome_retired: list = []
        self._biome_epoch = 0   # 群系定位批序号（递增；迟到结果丢弃）
        # 群系定位激活状态：群系 id/实例点方块坐标/距离/图标场景项
        # （结构定位与群系定位互斥，后定位者自动移除前一定位）
        self._locate_biome_id: int | None = None
        self._locate_biome_xy: tuple[int, int] | None = None
        self._locate_biome_dist: float = 0.0
        self._locate_biome_icon_key: str | None = None
        self._biome_key_map: dict = {}   # 群系 id → 图标内部键（下拉重建时更新）
        # 功能①强制图标（定位结构未被勾选时补显；移除定位时撤下）
        self._locate_forced_marker = None

        self._init_ui()
        self._init_signals()
        # 应用级退出钩子：先停线程再保存会话（连接顺序 = 调用顺序）。
        # PySide6 易踩坑：运行中的 QThread 在退出阶段被析构会 0xC0000409。
        QApplication.instance().aboutToQuit.connect(self._stop_thread)
        QApplication.instance().aboutToQuit.connect(self._persist)
        self._restore_session()
        self._session_ready = True

    # ---------- 实现基类接口 ----------
    @classmethod
    def tool_name(cls) -> str:
        return "MapPreviewer"

    # ---------- 初始化 ----------
    def _init_ui(self) -> None:
        """场景/视图设置与控件初始状态。"""
        self._scene = QGraphicsScene(self)
        # 显式全域场景矩形（无限地图）：视图可滚动/居中到任意位置，
        # 范围外区域由 _ensure_viewport_tiles 按需补渲染
        self._scene.setSceneRect(QRectF(float(-_WORLD_LIMIT),
                                        float(-_WORLD_LIMIT),
                                        float(2 * _WORLD_LIMIT),
                                        float(2 * _WORLD_LIMIT)))
        self.viewMap.setScene(self._scene)
        self.viewMap.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.viewMap.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.viewMap.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.viewMap.setResizeAnchor(
            QGraphicsView.ViewportAnchor.AnchorViewCenter)
        # 悬停实时查询需要鼠标移动事件（不依赖按键修饰）
        self.viewMap.setMouseTracking(True)
        self.viewMap.viewport().installEventFilter(self)

        # 拖拽平移状态（Chrome 式：按住左键拖动跟随，松开结束）
        self._pan_start: int | None = None
        # 拖动/缩放后延迟调度增量渲染（QTimer 单发；避免拖动过程中
        # 每像素都触发重排）
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setSingleShot(True)
        self._schedule_timer.setInterval(180)
        self._schedule_timer.timeout.connect(self._ensure_viewport_tiles)
        # 结构增量扫描调度（拖动/缩放停顿后触发，与瓦片补渲染同节奏）
        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.setInterval(180)
        self._scan_timer.timeout.connect(self._ensure_structure_scan)

        # 版本下拉默认 1.21（UI 已置项，代码再兜底一次）
        if self.comboVersion.currentIndex() < 0:
            self.comboVersion.setCurrentIndex(0)
        # 视野半径默认 2048（下拉仅剩 2048/4096 两档）
        self.comboRadius.setCurrentIndex(0)
        # 维度下拉默认主世界（UI 已置三项：主世界/下界/末地）
        if self.worldCombo.currentIndex() < 0:
            self.worldCombo.setCurrentIndex(0)

        # 结构/群系定位下拉默认项（填充在版本/维度就绪后统一处理）
        self.structureLocateList.setToolTip(
            "选择一个结构，自动查找离坐标输入最近（默认 0,0）的实例；\n"
            "换回首项撤销定位")
        # 群系定位下拉（CodesUI 已有控件）：可输入匹配，选中即自动查找
        self.biomeLocateList.setEditable(True)
        self.biomeLocateList.setInsertPolicy(
            QComboBox.InsertPolicy.NoInsert)
        comp = self.biomeLocateList.completer()
        if comp is not None:
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            comp.setFilterMode(Qt.MatchFlag.MatchContains)
        self.biomeLocateList.setToolTip(
            "输入或选择一个群系，自动查找离坐标输入最近（默认 0,0）的"
            "出现位置；换回首项撤销定位")

        self.progressRender.setRange(0, 100)
        self.progressRender.setValue(0)
        self.progressRender.setTextVisible(False)

        self._update_struct_menu()

    def _init_signals(self) -> None:
        self.btnRender.clicked.connect(self._on_render_clicked)
        self.editSeed.returnPressed.connect(self._on_render_clicked)
        self.btnStructures.clicked.connect(self._on_struct_menu)
        self.comboRadius.currentIndexChanged.connect(self._persist)
        self.comboVersion.currentIndexChanged.connect(self._on_version_changed)
        self.worldCombo.currentIndexChanged.connect(self._on_dimension_changed)
        self.xEdit.returnPressed.connect(self._on_locate_coord_clicked)
        self.zEdit.returnPressed.connect(self._on_locate_coord_clicked)
        self.structureLocateList.currentIndexChanged.connect(
            self._on_struct_choice_changed)
        self.biomeLocateList.currentIndexChanged.connect(
            self._on_biome_choice_changed)

    # ---------- 结构选择窗口 ----------
    def _on_version_changed(self, _) -> None:
        """版本切换：可用结构集变化，清理失效选择并实时落盘。"""
        self._update_struct_menu()
        self._persist()

    def _current_dimension(self) -> str:
        """worldCombo 当前维度键（overworld/nether/end）。"""
        return _DIM_COMBO_INDEX.get(self.worldCombo.currentIndex(),
                                    "overworld")

    def _on_dimension_changed(self, _) -> None:
        """维度切换：结构选择按维度分桶互换，旧地图整体失效清空。

        下界/末地的结构集、群系采样与配色都独立于主世界，旧地图的
        瓦片/标记/悬停探测/增量线程语义全部跨维度错配，直接清空并
        提示重新生成（避免误用旧维度数据）。
        """
        old, new = self._active_dimension, self._current_dimension()
        if new == old:
            return    # 会话恢复回设同维度：无需切换
        if self._running:
            self._cancel_render()   # 防御：在途渲染属于旧维度，取消
            self._suppress_finished_label = True
        # 旧维度选择入桶，换上新维度已保存的选择
        self._selected_other[old] = set(self._selected or set())
        self._active_dimension = new
        self._selected = set(self._selected_other.get(new, set()))
        self._update_struct_menu()
        self._clear_map()
        self._persist()

    def _clear_map(self) -> None:
        """清空地图显示：瓦片/标记/悬停/增量扫描状态全部复位。"""
        self._cancel_tile_thread()
        self._cancel_scan_thread()
        self._tile_epoch += 1
        self._scene.clear()
        self._grid_item = None
        self._markers = []
        self._hover_tip_item = None
        self._tiles = OrderedDict()
        self._tile_items = {}
        self._tile_lod = {}
        self._last = None
        self._has_map = False
        self._scan_covered = None
        self._structs_seen = {}
        self._clear_locate_items()
        self._cancel_locate_thread()
        self._locate_epoch += 1
        self._cancel_biome_thread()
        self._reset_locate_state()
        self.progressRender.setValue(0)
        self.labelHover.setText("悬停地图查看坐标与群系")
        self.labelInfo.setText(
            "已切换到"
            + DIMENSION_NAMES.get(self._active_dimension, "主世界")
            + "，请重新生成地图")
        self._set_running_ui(False)

    def _avail_keys(self) -> tuple[str, ...]:
        """当前版本+维度可标注的结构键。"""
        return available_structures(self.comboVersion.currentText(),
                                    dimension=self._current_dimension())

    def _update_struct_menu(self) -> None:
        """同步按钮 tooltip 与选择集（版本/维度切换后可用集变化）。"""
        keys = self._avail_keys()
        if self._selected is None:
            self._selected = set(_COMMON_STRUCTS) & set(keys)
        # 清掉当前维度不可用的选择，并把选择存回当前维度桶
        self._selected &= set(keys)
        self._selected_other[self._current_dimension()] = set(self._selected)
        self.btnStructures.setToolTip(
            "选择要在"
            + DIMENSION_NAMES.get(self._current_dimension(), "主世界")
            + "地图上标注的结构\n"
            + "\n".join(("☑ " if k in self._selected else "☐ ")
                        + STRUCT_NAMES.get(k, k) for k in keys))
        # 结构定位下拉随版本/维度可用集同步重建
        self._update_locate_menu()
        # 群系定位下拉随维度同步重建（版本不影响 id 表，重建无害）
        self._update_biome_menu()

    def _on_struct_menu(self) -> None:
        """「选择结构」弹窗：图标网格勾选，确认后写回选择集并落盘。"""
        win = ChooseStructureWindow(self, self._avail_keys(), self._selected)
        if win.exec() != ChooseStructureWindow.DialogCode.Accepted:
            return
        self._selected = win.get_selected()
        self._update_struct_menu()
        self._persist()

    # ---------- 渲染状态机 ----------
    def _on_render_clicked(self) -> None:
        if self._running:
            self._cancel_render()
        else:
            self._start_render()

    def _start_render(self) -> None:
        """校验输入 → 启动后台线程（按钮切「停止渲染」）。"""
        if self._running:
            return
        self._cancel_scan_thread()   # 全量重渲染开始，放弃在途增量扫描
        # 在途定位结果会被新地图丢弃（_apply_result 作废 epoch），
        # 提前取消省算力（重复 bump epoch 无害）
        self._cancel_locate_thread()
        self._cancel_biome_thread()
        seed_text = self.editSeed.text().strip()
        try:
            seed = self._parse_seed(seed_text)
        except ValueError as e:
            NotificationWidget.Show(
                "种子无效",
                str(e),
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )
            return
        radius = _RADIUS_MAP.get(self.comboRadius.currentText().strip(), 2048)
        keys = sorted(self._selected or set())
        # 未勾选结构也允许生成纯群系地图（功能③）

        version = self.comboVersion.currentText()
        # 初始渲染 LOD 按视野尺寸预判：大视野整图方块级渲染量巨大，
        # 先用快速档保证 <5s 出图。阈值取 cell 瓦片实际覆盖的 2048：
        # 地图本身是 cell 语义，避免加载完成后中心区域与后续增量
        # 补的 cell 瓦片档位不一致（补渲染统一沿用初始档位，不做
        # 缩放驱动的升级/降级）
        lod = "cell" if radius >= 2048 else "block"
        self._thread = MapPreviewerThread(seed, version, radius, keys,
                                          parent=self, lod=lod,
                                          hillshade=self._hillshade_on,
                                          dimension=self._current_dimension())
        self._thread.progress.connect(self._on_progress)
        self._thread.render_finished.connect(self._on_finished)
        self._thread.error.connect(self._on_error)
        # 线程安全回收：finished 在 run() 返回后才发出，deleteLater
        # 由主线程事件循环执行，析构时线程必已停止
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()
        self._running = True
        self._set_running_ui(True)
        self.labelInfo.setText("渲染中…（点击按钮停止）")

    def _cancel_render(self) -> None:
        if self._thread is not None:
            self._thread.request_cancel()
        self.labelInfo.setText("停止中…")

    def _set_running_ui(self, running: bool) -> None:
        """状态机：按钮/输入控件在渲染中的禁用态。

        按钮文案三态：生成地图（从未生成）→ 停止渲染（计算中）→
        更新结构（已有地图后重新点击）。
        """
        if running:
            self.btnRender.setText("停止渲染")
        else:
            self.btnRender.setText("更新结构" if self._has_map
                                   else "生成地图")
        for w in (self.comboVersion, self.editSeed, self.comboRadius,
                  self.btnStructures, self.worldCombo):
            w.setEnabled(not running)

    @staticmethod
    def _parse_seed(text: str) -> int:
        """解析种子输入：十进制（含负数）或 0x 十六进制。"""
        t = text.strip()
        if not t:
            raise ValueError("请输入世界种子（游戏 /seed 获取）")
        try:
            if t.lower().startswith("0x") or t.lower().startswith("-0x"):
                return int(t, 16)
            v = int(t, 10)
        except ValueError:
            raise ValueError(f"无法解析种子：{t!r}（支持十进制与 0x 十六进制）")
        # int64 范围校验（Java 有符号 64 位）
        if not (-(1 << 63) <= v < (1 << 63)):
            raise ValueError("种子超出 64 位有符号整数范围")
        return v

    # ---------- 线程回调 ----------
    def _on_progress(self, done: int, total: int, msg: str) -> None:
        """进度只在进度条展示（百分比）；labelInfo 不显示任何数字。"""
        if total > 0:
            self.progressRender.setValue(
                int(done * self.progressRender.maximum() / total))
        else:
            self.progressRender.setValue(0)

    def _on_finished(self, result: dict, summary: str) -> None:
        self._running = False
        # 回收交由 finished → deleteLater（创建处统一连接）：
        # 本回调经 queued 信号到达时线程 run() 可能尚未返回，
        # 此处 setParent(None)+丢引用会让 C++ 对象在线程仍运行时
        # 被析构 → qFatal "Destroyed while thread is still running"
        # → abort() → 0xC0000409（事件日志 12 次崩溃的根因）
        self._thread = None
        self._set_running_ui(False)
        self.progressRender.setValue(self.progressRender.maximum())
        if summary == CANCELLED_SUMMARY or not result:
            if self._suppress_finished_label:
                # 维度切换取消的旧线程迟到回调：保留切换提示
                self._suppress_finished_label = False
            else:
                self.labelInfo.setText("已停止")
            self.progressRender.setValue(0)
            return
        try:
            self._apply_result(result)
            self._has_map = True   # 此后按钮空闲文案 = 「更新结构」
            self.labelInfo.setText(summary)
            NotificationWidget.Show(
                {"nether": "下界地图生成完成",
                 "end": "末地地图生成完成"}.get(
                    result.get("dimension", "overworld"), "地图生成完成"),
                f"结构标记 {len(result.get('structures', []))} 个\n"
                f"引擎 {result.get('engine', '?')}"
                f"｜采样 {result.get('t_sample', 0):.2f}s"
                f"｜渲染 {result.get('t_render', 0):.2f}s"
                f"｜结构 {result.get('t_struct', 0):.2f}s",
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )
        finally:
            self._persist()

    def _on_error(self, msg: str) -> None:
        self._running = False
        # 回收同 _on_finished：交给 finished → deleteLater
        self._thread = None
        self._set_running_ui(False)
        self.progressRender.setValue(0)
        self.labelInfo.setText("出错")
        NotificationWidget.Show(
            "地图渲染失败",
            msg,
            _NOTIFY_DURATION_MS,
            title_size=_NOTIFY_TITLE_SIZE,
            message_size=_NOTIFY_MESSAGE_SIZE,
            padding=_NOTIFY_PADDING,
        )

    # ---------- 定位输入与坐标定位 ----------
    def _parse_coord_field(self) -> tuple[int, int] | None:
        """读坐标输入框；空 = 0（默认原点），非法内容返回 None。

        兼容一格填 "X, Z"（逗号/空格分隔，另一格留空）。"""
        xt = self.xEdit.text().strip().replace(",", " ")
        zt = self.zEdit.text().strip().replace(",", " ")
        if xt and not zt:
            parts = xt.split()
            if len(parts) >= 2:
                xt, zt = parts[0], " ".join(parts[1:])
        elif zt and not xt:
            parts = zt.split()
            if len(parts) >= 2:
                xt, zt = parts[0], " ".join(parts[1:])
        try:
            return int(float(xt or 0)), int(float(zt or 0))
        except ValueError:
            return None

    def _goto_coord(self, coord) -> bool:
        """视图中心移到指定方块坐标（不改缩放）；视野变化后调度
        增量补渲染与结构扫描。"""
        if not coord:
            return False
        x, z = coord
        self.viewMap.centerOn(float(x), float(z))
        self._fill_rounds = 0
        self._schedule_timer.start()
        self._scan_timer.start()
        return True

    def _on_locate_coord_clicked(self) -> None:
        """「定位」（X/Z 回车触发）：视图中心移到输入坐标。"""
        coord = self._parse_coord_field()
        if coord is None:
            NotificationWidget.Show(
                "坐标无效",
                "请输入整数坐标（X/Z 分格，或一格填 \"X, Z\"）",
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )
            return
        self._goto_coord(coord)

    def _fill_coord_field(self, x: int, z: int) -> None:
        """右键坐标直接填入定位输入框（X/Z 分格）；不触发跳转，
        用户可手动回车定位或直接用于结构定位起点。"""
        self.xEdit.setText(str(int(x)))
        self.zEdit.setText(str(int(z)))

    # ---------- 结构定位（下拉选中即查找，同群系定位交互） ----------
    def _update_locate_menu(self) -> None:
        """结构定位下拉 = 首项「选择结构」+ 当前版本+维度全部
        可标注结构（单选；重建时保留原选择）。"""
        box = self.structureLocateList
        keep = box.currentData()
        box.blockSignals(True)
        box.clear()
        box.addItem("选择结构", None)
        for key in self._avail_keys():
            box.addItem(STRUCT_NAMES.get(key, key), key)
        if keep is not None:
            i = box.findData(keep)
            if i >= 0:
                box.setCurrentIndex(i)
        box.blockSignals(False)

    def _on_struct_choice_changed(self, _idx: int) -> None:
        """结构下拉选择：回首项 = 撤销结构定位；选中结构 = 自动
        查找离坐标输入最近（默认 0,0）的实例（同群系定位交互）。"""
        self._persist()
        key = self.structureLocateList.currentData()
        if not key:
            # 撤销：作废迟到结果并移除定位（与群系回首项语义一致）
            self._cancel_locate_thread()
            self._locate_epoch += 1
            self._remove_locate()
            return
        self._start_struct_locate(str(key))

    def _start_struct_locate(self, key: str) -> None:
        """守卫链 + 启动结构定位线程（在途旧定位取消，迟到结果丢弃）。"""
        if self._running:
            NotificationWidget.Show(
                "正在渲染地图",
                "请等待渲染完成或先停止渲染，再定位结构",
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )
            return
        if self._last is None:
            NotificationWidget.Show(
                "请先生成地图",
                "结构定位需要种子与版本信息",
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )
            return
        coord = self._parse_coord_field()
        if coord is None:
            NotificationWidget.Show(
                "坐标无效",
                "请输入整数坐标（X/Z 分格，或一格填 \"X, Z\"）",
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )
            return
        self._cancel_locate_thread()
        self._locate_epoch += 1
        # 互斥：结构定位发起时取消在途群系定位（迟到结果按 epoch 丢弃）
        self._cancel_biome_thread()
        seed = int(self._last["seed"])
        version = str(self._last["version"])
        th = StructureLocateThread(seed, version, key,
                                   coord[0], coord[1], parent=self,
                                   dimension=str(self._last.get(
                                       "dimension", "overworld")))
        epoch = self._locate_epoch
        th.located.connect(
            lambda p, e=epoch: self._on_locate_result(p, e))
        th.error.connect(self._on_locate_error)
        th.finished.connect(lambda t=th: self._reap_locate_thread(t))
        th.finished.connect(th.deleteLater)
        self._locate_thread = th
        th.start()
        self.labelInfo.setText("结构定位中…")

    def _on_locate_result(self, payload: dict, epoch: int) -> None:
        """定位结果：画定位点+红色虚线+距离文本并适配视角；未找到
        则提示搜索范围。"""
        if epoch != self._locate_epoch:
            return    # 迟到的旧定位结果（新一轮已发出），丢弃
        self._locate_thread = None
        st = payload.get("structures")
        if isinstance(st, list) and not st:
            side = int(payload.get("searched_side", 0))
            NotificationWidget.Show(
                "未找到该结构",
                f"已在目标点周围 ±{side // 2} 方块范围内搜索",
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )
            return
        tx, tz = (int(v) for v in payload["target"])
        x, z = int(payload["x"]), int(payload["z"])
        dist = float(payload.get("dist",
                                 ((x - tx) ** 2 + (z - tz) ** 2) ** 0.5))
        # 互斥：结构定位激活时移除群系定位（下拉回首项、清定位链）
        self._remove_biome_locate(reset_combo=True)
        self._draw_locate(tx, tz, x, z, dist)
        self._fit_locate_view(tx, tz, x, z)
        # 定位激活：记结构键/定位点/实例（图标强制显示 + 撤销定位）
        self._locate_struct_key = str(payload["struct"])
        self._locate_point = (tx, tz)
        self._locate_inst = {
            "struct": payload["struct"], "name": payload.get("name",
                                                           payload["struct"]),
            "x": x, "z": z, "biome": payload.get("biome")}
        self._locate_dist = dist
        shown = st_icons.display_name(payload.get("name",
                                                  payload["struct"]),
                                      payload["struct"],
                                      payload.get("biome"))
        self.labelInfo.setText(
            f"最近{shown} ({x}, {z})，距定位点 {dist:.0f} 方块")
        self._ensure_locate_icon()   # 功能①：未勾选也显示结构图标

    def _on_locate_error(self, _msg: str) -> None:
        self._locate_thread = None
        if not self._running:
            self.labelInfo.setText("结构定位失败（可重试）")

    def _reap_locate_thread(self, th) -> None:
        """定位线程 finished 回收（迟到结果由 epoch 丢弃）。"""
        try:
            if th is self._locate_thread:
                self._locate_thread = None
            if th in self._locate_retired:
                self._locate_retired.remove(th)
        except RuntimeError:
            pass

    def _cancel_locate_thread(self) -> None:
        """放弃在途结构定位：置取消标志并转入 retired 保引用。

        运行中的 QThread 立即解引用会被析构（0xC0000409 经典崩溃）；
        迟到结果由主线程按 epoch 丢弃。"""
        th, self._locate_thread = self._locate_thread, None
        if th is None:
            return
        try:
            if th.isRunning():
                th.request_cancel()
                self._locate_retired.append(th)
        except RuntimeError:
            pass

    # ---------- 定位状态维护（功能①图标强制显示/下拉两态撤销） ----------
    def _ensure_locate_icon(self) -> None:
        """功能①：定位结构图标强制显示。

        定位成功的结构若未被「选择结构」勾选（初始渲染与增量扫描
        都不会为其建标记），单独补加图标，保证定位结果在地图上
        一眼可辨；实例已在标记/去重表中则不重复添加。"""
        if self._locate_struct_key is None or self._locate_inst is None:
            return
        x = int(self._locate_inst["x"])
        z = int(self._locate_inst["z"])
        if (self._locate_struct_key, x, z) in self._structs_seen:
            self._locate_forced_marker = None
            return
        self._locate_forced_marker = self._add_marker(self._locate_inst)

    def _clear_struct_activate(self) -> None:
        """清结构定位激活状态：强制图标撤下（去重表同步还原）、
        结构键/实例状态复位。

        不动定位链与共享定位点字段（由调用方决定重画或清除）。
        """
        forced = self._locate_forced_marker
        self._locate_forced_marker = None
        inst = self._locate_inst
        if forced is not None:
            try:
                self._scene.removeItem(forced)
            except RuntimeError:
                pass
            if forced in self._markers:
                self._markers.remove(forced)
            # 强制补显的实例才需要还原去重表；勾选结构的正常标记
            # 条目保留（pop 会让增量扫描重复加图标）
            if inst is not None and self._locate_struct_key is not None:
                self._structs_seen.pop(
                    (self._locate_struct_key, int(inst["x"]), int(inst["z"])),
                    None)
        self._locate_struct_key = None
        self._locate_inst = None

    def _remove_locate(self) -> None:
        """撤销结构定位：清定位场景项与激活状态。

        仅当结构定位激活时动作（群系定位激活时结构回首项不误清
        群系定位链）；强制补显的图标撤下（去重表同步还原，勾选后
        增量扫描可正常发现）。"""
        if self._locate_struct_key is None:
            return
        self._clear_struct_activate()
        self._locate_point = None
        self._locate_dist = 0.0
        self._clear_locate_items()

    def _reset_locate_state(self) -> None:
        """换种子/版本/维度：定位激活状态整体复位。

        仅复位状态与场景引用（场景项已随 scene.clear() 销毁），
        不动线程；结构/群系下拉同步回首项。"""
        self._locate_struct_key = None
        self._locate_point = None
        self._locate_inst = None
        self._locate_dist = 0.0
        self._locate_forced_marker = None
        self._locate_biome_id = None
        self._locate_biome_xy = None
        self._locate_biome_dist = 0.0
        self._locate_biome_icon_key = None
        self._set_struct_combo_index(0)
        self._set_biome_combo_index(0)

    # ---------- 群系定位（效果同结构定位，下拉选中即查找） ----------
    def _update_biome_menu(self) -> None:
        """群系定位下拉按当前维度重建（首项「选择群系」data=None）。

        主世界 = biome_names.BIOME_CHOICES 54 项（低版本不存在的
        群系 id 查找时自然「未找到」）；下界/末地 = 采样器同源 5 项。
        """
        box = self.biomeLocateList
        keep = box.currentData()   # 版本切换重建时保留原选择（主世界 id 表不随版本变）
        box.blockSignals(True)
        box.clear()
        box.addItem("选择群系", None)
        self._biome_key_map = self._biome_key_by_id()
        if self._current_dimension() == "overworld":
            for label, _key in biome_names.BIOME_CHOICES:
                bid = biome_names.resolve_biome(label)
                if bid is not None:
                    box.addItem(label, int(bid))
        else:
            for label, bid in DIM_BIOME_TABLES.get(
                    self._current_dimension(), ()): 
                box.addItem(str(label), int(bid))
        if keep is not None:
            i = box.findData(keep)
            if i >= 0:
                box.setCurrentIndex(i)
        box.blockSignals(False)

    def _biome_key_by_id(self) -> dict:
        """当前维度群系 id → 内部键（画群系图标用；下界/末地标签
        尾部即内部键，图标文件缺失时 _draw_locate 自然回退菱形）。"""
        if self._current_dimension() == "overworld":
            table = {}
            for label, key in biome_names.BIOME_CHOICES:
                bid = biome_names.resolve_biome(label)
                if bid is not None:
                    table[bid] = key
            return table
        return {int(bid): str(label).split(" ")[-1]
                for label, bid in DIM_BIOME_TABLES.get(
                    self._current_dimension(), ())}

    def _biome_display(self, bid: int) -> str:
        """群系显示名：下拉标签的中文前缀；未知 id 回退 biome_label。"""
        i = self.biomeLocateList.findData(int(bid))
        if i >= 0:
            return self.biomeLocateList.itemText(i).split(" ")[0]
        return biome_names.biome_label(int(bid))

    def _on_biome_choice_changed(self, _idx: int) -> None:
        """群系下拉选择：首项 = 撤销群系定位；选中群系 = 自动查找
        离坐标输入最近（默认 0,0）的出现位置（效果同结构定位）。"""
        bid = self.biomeLocateList.currentData()
        if bid is None:
            # 撤销：取消在途查找并作废迟到结果（epoch 单调递增）
            self._cancel_biome_thread()
            self._biome_epoch += 1
            self._remove_biome_locate()
            return
        self._start_biome_locate(int(bid))

    def _start_biome_locate(self, bid: int) -> None:
        """守卫链 + 启动群系定位线程（在途旧线程取消，迟到结果丢弃）。"""
        if self._running:
            NotificationWidget.Show(
                "正在渲染地图",
                "请等待渲染完成或先停止渲染，再查找群系",
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )
            return
        if self._last is None:
            NotificationWidget.Show(
                "请先生成地图",
                "群系定位需要种子与版本信息",
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )
            return
        coord = self._parse_coord_field()
        if coord is None:
            NotificationWidget.Show(
                "坐标无效",
                "请输入整数坐标（X/Z 分格，或一格填 \"X, Z\"）",
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )
            return
        self._cancel_biome_thread()
        self._biome_epoch += 1
        # 互斥：群系定位发起时取消在途结构定位（迟到结果按 epoch 丢弃）
        self._cancel_locate_thread()
        self._locate_epoch += 1
        th = BiomeLocateThread(int(self._last["seed"]),
                               str(self._last["version"]), bid,
                               coord[0], coord[1], parent=self,
                               dimension=str(self._last.get(
                                   "dimension", "overworld")))
        epoch = self._biome_epoch
        th.located.connect(
            lambda p, e=epoch: self._on_biome_locate_result(p, e))
        th.finished.connect(lambda t=th: self._reap_biome_thread(t))
        th.finished.connect(th.deleteLater)
        self._biome_thread = th
        th.start()
        self.labelInfo.setText("群系定位中…")

    def _on_biome_locate_result(self, payload: dict, epoch: int) -> None:
        """群系定位结果：互斥移除结构定位 → 画定位链与图标并适配
        视角；未找到则提示搜索范围。"""
        if epoch != self._biome_epoch:
            return    # 迟到的旧定位结果（新一轮已发出/已取消），丢弃
        self._biome_thread = None
        if payload.get("error"):
            self.labelInfo.setText("群系定位失败（可重试）")
            NotificationWidget.Show(
                "群系定位失败",
                str(payload["error"]),
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )
            return
        if isinstance(payload.get("structures"), list) \
                and not payload["structures"]:
            side = int(payload.get("searched_side", 0))
            NotificationWidget.Show(
                "未找到该群系",
                f"已在目标点周围 ±{side // 2} 方块范围内搜索",
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )
            self.labelInfo.setText("群系定位未找到（可换坐标重试）")
            return
        bid = int(payload["biome"])
        tx, tz = (int(v) for v in payload["target"])
        x, z = int(payload["x"]), int(payload["z"])
        dist = float(payload.get("dist",
                                 ((x - tx) ** 2 + (z - tz) ** 2) ** 0.5))
        # 互斥：群系定位激活时移除结构定位（清强制图标/激活状态；
        # 不动下拉——用户刚选的群系项保持选中）
        self._clear_struct_activate()
        self._draw_locate(tx, tz, x, z, dist,
                          icon_key=self._biome_key_map.get(bid))
        self._fit_locate_view(tx, tz, x, z)
        # 群系定位激活状态（定位点/距离复用共享字段，移除定位与
        # 同世界重渲染跟随用）
        self._locate_point = (tx, tz)
        self._locate_dist = dist
        self._locate_biome_id = bid
        self._locate_biome_xy = (x, z)
        self._locate_biome_icon_key = self._biome_key_map.get(bid)
        self.labelInfo.setText(
            f"最近{self._biome_display(bid)} ({x}, {z})，"
            f"距定位点 {dist:.0f} 方块")

    def _remove_biome_locate(self, reset_combo: bool = False) -> None:
        """移除群系定位：清定位链（图标随链销毁）与激活状态。

        未激活时不动作（防用户回首项/结构定位抢占时误清结构
        定位链）；结构定位抢占时把下拉回首项（blockSignals 防
        信号递归）并连带清结构激活状态（互斥）。"""
        active = self._locate_biome_id is not None
        if reset_combo:
            self._set_biome_combo_index(0)
            self._clear_struct_activate()
        if not active:
            return
        self._locate_biome_id = None
        self._locate_biome_xy = None
        self._locate_biome_dist = 0.0
        self._locate_biome_icon_key = None
        self._clear_locate_items()

    def _cancel_biome_thread(self) -> None:
        """放弃在途群系定位：置取消标志并转入 retired 保引用。

        运行中的 QThread 立即解引用会被析构（0xC0000409 经典崩溃）；
        迟到结果由主线程按 epoch 丢弃。"""
        th, self._biome_thread = self._biome_thread, None
        if th is None:
            return
        self._biome_epoch += 1
        th.request_cancel()
        if th not in self._biome_retired:
            self._biome_retired.append(th)

    def _reap_biome_thread(self, th) -> None:
        """群系定位线程 finished 回收（迟到结果由 epoch 丢弃）。"""
        try:
            if th is self._biome_thread:
                self._biome_thread = None
            if th in self._biome_retired:
                self._biome_retired.remove(th)
        except RuntimeError:
            pass
    # ---------- 定位场景项：定位点 + 红色虚线 + 距离/坐标标签 ----------
    def _clear_locate_items(self) -> None:
        """移除定位点/虚线/距离与坐标标签等场景项
        （换图/重渲染/新定位/删除路径前）。"""
        for item in getattr(self, "_locate_items", []):
            try:
                self._scene.removeItem(item)
            except RuntimeError:
                pass    # scene.clear() 后旧项 C++ 对象已析构
        self._locate_items = []
        self._coord_labels = []

    def _draw_locate(self, tx: int, tz: int, x: int, z: int,
                     dist: float, icon_key: str | None = None) -> None:
        """画定位链：定位点（红点 + 外圈）→ 红色虚线 → 锿点，
        虚线中点上方悬挂距离文本（IgnoresTransformations 恒定屏幕
        大小，同结构标记风格）。

        icon_key：群系内部键（群系定位用）→ 锿点叠加群系图标
        （assets/SeedReverser/<key>.png，缺失时菱形色块回退；
        套浮板底座同结构标记）；随定位链入 _locate_items，
        移除定位/换图同步销毁。"""
        self._clear_locate_items()
        # 0) 锿点群系图标（先加则被后续项压住；菱形底垫标识实例）
        icon = None
        if icon_key:
            icon_file = biome_names.icon_path(str(icon_key))
            pm = QPixmap(icon_file) if icon_file else QPixmap()
            if not pm.isNull():
                # 浮板式合成：灰板+图标+右下柔和暗影
                pm = _compose_plate_icon(pm)
                icon = QGraphicsPixmapItem(pm)
                icon.setOffset(-_MARK_PIX_SIZE / 2.0,
                               -_MARK_PIX_SIZE / 2.0)
                icon.setPos(float(x), float(z))
                icon.setFlag(QGraphicsPixmapItem.GraphicsItemFlag
                             .ItemIgnoresTransformations, True)
                icon.setZValue(10)
                icon.setToolTip(f"群系实例 ({x}, {z})")
                icon.setData(0, "locate")
                self._scene.addItem(icon)   # 裸构造项须手动入场景
            else:
                icon = self._scene.addPolygon(
                    QPolygonF([QPointF(0, -_MARKER_R),
                               QPointF(_MARKER_R, 0),
                               QPointF(0, _MARKER_R),
                               QPointF(-_MARKER_R, 0)]),
                    QPen(QColor(80, 200, 120), 1.5),
                    QBrush(QColor(80, 200, 120, 90)))
                icon.setPos(float(x), float(z))
                icon.setZValue(10)
                icon.setToolTip(f"群系实例 ({x}, {z})")
                icon.setData(0, "locate")
        # 1) 红色虚线（结构锿点 → 定位点）
        line = self._scene.addLine(float(x), float(z), float(tx), float(tz),
                                   QPen(_LOC_LINE_COLOR, _LOC_LINE_WIDTH,
                                        Qt.PenStyle.DashLine))
        line.setZValue(9)
        # 2) 定位点：外圈红环 + 内实心点（区别于结构标记）
        ring = self._scene.addEllipse(
            tx - _LOC_PIN_R * 1.8, tz - _LOC_PIN_R * 1.8,
            _LOC_PIN_R * 3.6, _LOC_PIN_R * 3.6,
            QPen(_LOC_PIN_COLOR, 1.5),
            QBrush(QColor(255, 64, 64, 40)))
        ring.setZValue(10)
        dot = self._scene.addEllipse(
            tx - _LOC_PIN_R * 0.55, tz - _LOC_PIN_R * 0.55,
            _LOC_PIN_R * 1.1, _LOC_PIN_R * 1.1,
            QPen(Qt.PenStyle.NoPen), QBrush(_LOC_PIN_COLOR))
        dot.setZValue(10)
        # 3) 距离文本：悬挂在虚线中点上方（场景坐标定位，恒定屏幕
        # 大小；缩放/拖动跟随，拖到世界边缘仍在两点之间）
        text = QGraphicsSimpleTextItem(
            f"{dist:.0f} 方块" if dist >= 100 else f"{dist:.1f} 方块")
        self._style_loc_label(text)
        text.setZValue(11)
        br = text.boundingRect()
        text.setPos((tx + x) / 2.0 - br.width() / 2.0,
                    (tz + z) / 2.0 - br.height() - _LOC_PIN_R * 2.0)
        self._scene.addItem(text)   # 裸构造项须手动入场景
        # 4) 起终点坐标标签（任务④：定位完成直接可见，拖动地图后
        # 隐藏；含距离信息，与虚线/定位点一体随定位链销毁）
        s_lab = self._make_coord_label(f"({tx}, {tz})", tx, tz, True)
        e_lab = self._make_coord_label(f"({x}, {z})", x, z, False)
        self._coord_labels = [s_lab, e_lab]
        for item in (line, ring, dot, text, s_lab, e_lab):
            item.setData(0, "locate")
        self._locate_items = [line, ring, dot, text, s_lab, e_lab]
        if icon is not None:
            self._locate_items.append(icon)

    def _style_loc_label(self, text: QGraphicsSimpleTextItem) -> None:
        """定位链文本统一样式：恒定屏幕大小 + 红色加粗。"""
        f = QFont()
        f.setPointSize(_LOC_TEXT_PT)
        f.setBold(True)
        text.setFont(f)
        text.setBrush(QBrush(_LOC_TEXT_COLOR))
        text.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag
                     .ItemIgnoresTransformations, True)
        text.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag
                     .ItemUsesExtendedStyleOption, True)

    def _coord_lift(self, at_target: bool) -> float:
        """端点坐标标签避让量（场景单位）：屏幕像素需求（覆盖
        28px 恒定屏幕图标半高）按当前缩放换算，另保留场景单位
        下限兑底（缩放很大时红环/回退红圈随缩放变大）。"""
        m = self.viewMap.transform().m11() or 1.0
        if at_target:
            return max((_COORD_LIFT_PX + _LOC_PIN_R * 1.2) / m,
                       _LOC_PIN_R * 2.6)
        return max(_COORD_LIFT_PX / m, _MARKER_R * 1.2)

    def _make_coord_label(self, txt: str, ax: int, az: int,
                          at_target: bool) -> QGraphicsSimpleTextItem:
        """定位链端点坐标标签：悬挂在点上方（避让量见
        _coord_lift）；含 data(1) 锚点坐标。"""
        lab = QGraphicsSimpleTextItem(txt)
        self._style_loc_label(lab)
        lift = self._coord_lift(at_target)
        br = lab.boundingRect()
        lab.setPos(float(ax) - br.width() / 2.0,
                   float(az) - br.height() - lift)
        lab.setData(1, (int(ax), int(az)))
        self._scene.addItem(lab)   # 裸构造项须手动入场景
        return lab

    def _relayout_coord_labels(self) -> None:
        """视角适配改变缩放后重算坐标标签抬升：避让量随新缩放
        换算（屏幕像素当量恒定），保证任何缩放级别下不被恒定
        屏幕大小的图标/红环压住；定位链不在时静默。"""
        labels = getattr(self, "_coord_labels", [])
        if len(labels) < 2:
            return
        for idx, lab in enumerate(labels[:2]):
            anchor = lab.data(1)
            if not anchor:
                continue
            br = lab.boundingRect()
            lift = self._coord_lift(idx == 0)
            lab.setPos(float(anchor[0]) - br.width() / 2.0,
                       float(anchor[1]) - br.height() - lift)

    def _set_coord_labels_visible(self, visible: bool) -> None:
        """拖动/缩放地图后隐藏（任务④）；新定位/同世界重渲染恢复。
        仅坐标标签两项（群系图标不在列内，拖动后保持可见）。"""
        for it in getattr(self, "_coord_labels", []):
            try:
                it.setVisible(visible)
            except RuntimeError:
                pass    # scene.clear() 后旧项 C++ 对象已析构

    def _fit_locate_view(self, tx: int, tz: int, x: int, z: int) -> None:
        """定位视角适配：两点包围盒居中并缩放到两点及文本可见
        （外扩边距；太近时拉到最小可辨识视野，避免过度放大）。
        缩放变化后重算坐标标签避让量（随当前缩放换算）。"""
        x0, x1 = sorted((float(tx), float(x)))
        z0, z1 = sorted((float(tz), float(z)))
        w, h = x1 - x0, z1 - z0
        if w < 1.0:
            x0, x1 = x0 - 1.0, x1 + 1.0
        if h < 1.0:
            z0, z1 = z0 - 1.0, z1 + 1.0
        px, py = w * _LOC_VIEW_PAD, h * _LOC_VIEW_PAD
        x0, x1, z0, z1 = (x0 - px, x1 + px, z0 - py, z1 + py)
        if x1 - x0 < _LOC_VIEW_MIN_SPAN:
            c = (x0 + x1) / 2.0
            half = _LOC_VIEW_MIN_SPAN / 2.0
            x0, x1 = c - half, c + half
        if z1 - z0 < _LOC_VIEW_MIN_SPAN:
            c = (z0 + z1) / 2.0
            half = _LOC_VIEW_MIN_SPAN / 2.0
            z0, z1 = c - half, c + half
        self.viewMap.fitInView(QRectF(x0, z0, x1 - x0, z1 - z0),
                               Qt.AspectRatioMode.KeepAspectRatio)
        self._clamp_zoom()
        self._relayout_coord_labels()
        self._fill_rounds = 0
        self._schedule_timer.start()
        self._scan_timer.start()


    # ---------- 结果应用与交互 ----------
    def _apply_result(self, result: dict) -> None:
        """采样矩阵 → 瓦片化场景；结构 → 标记图形项。

        rgb 为渲染好的整图（lod="block" 时 1 像素 = 1 方块；
        lod="cell" 时 1 像素 = 4x4 方块），切成瓦片入场景，
        瓦片坐标系 = 世界方块坐标（1 场景单位 = 1 方块）。
        """
        rgb = result["rgb"]
        h, w = rgb.shape[:2]
        origin_bx = int(result["origin_bx"])
        origin_bz = int(result["origin_bz"])
        radius = int(result["radius"])
        lod = result.get("lod", "block")
        # 下界/末地数据固定 4方块/像素（采样器直接输出 rgb，无渲染档位）
        if result.get("dimension", "overworld") != "overworld":
            cell_px = 4
        else:
            cell_px = 4 if lod == "cell" else 1   # 1 像素覆盖的方块边长

        self._scene.clear()
        self._grid_item = None
        self._markers = []
        self._hover_tip_item = None   # 旧项已随 scene.clear() 销毁
        self._locate_items = []       # 旧定位项（含群系图标）已随
                                      # scene.clear() 销毁
        self._coord_labels = []       # 端点坐标标签随场景销毁一并作废
        self._locate_epoch += 1       # 新地图作废在途/迟到定位结果
        self._biome_epoch += 1        # 群系定位迟到结果同步作废
        self._locate_forced_marker = None
        # 换种子/版本/维度：定位状态复位；同世界重渲染则保留跟随
        if self._last is not None:
            same_world = (int(result["seed"]) == int(self._last["seed"])
                          and str(result["version"])
                          == str(self._last["version"])
                          and str(result.get("dimension", "overworld"))
                          == str(self._last.get("dimension", "overworld")))
        else:
            same_world = False
        if not same_world:
            self._reset_locate_state()
        self._tiles = OrderedDict()   # LRU：保插入序，超限淘汰最旧
        self._tile_items = {}
        self._tile_lod = {}
        self._tile_epoch += 1
        self._cancel_tile_thread()

        # 整图按世界瓦片格对齐切片（瓦片键 = 世界格坐标 // 1024）。
        # 512 半径等非对齐半径的地图会跨格边界：瓦片与地图求交后
        # 只切地图内部分（部分瓦片），键/位置语义与增量调度一致
        img = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
        bx_end = origin_bx + w * cell_px
        bz_end = origin_bz + h * cell_px
        for tz in range(origin_bz // _TILE_BLOCKS,
                        (bz_end - 1) // _TILE_BLOCKS + 1):
            for tx in range(origin_bx // _TILE_BLOCKS,
                            (bx_end - 1) // _TILE_BLOCKS + 1):
                # 瓦片格 ∩ 地图（方块坐标，均为 cell_px 倍数）
                ix0 = max(tx * _TILE_BLOCKS, origin_bx)
                iz0 = max(tz * _TILE_BLOCKS, origin_bz)
                ix1 = min((tx + 1) * _TILE_BLOCKS, bx_end)
                iz1 = min((tz + 1) * _TILE_BLOCKS, bz_end)
                if ix1 <= ix0 or iz1 <= iz0:
                    continue
                px0 = (ix0 - origin_bx) // cell_px
                py0 = (iz0 - origin_bz) // cell_px
                sub = img.copy(px0, py0,
                               (ix1 - ix0) // cell_px,
                               (iz1 - iz0) // cell_px)
                pm = QPixmap.fromImage(sub)
                item = self._scene.addPixmap(pm)
                item.setPos(ix0, iz0)
                if cell_px != 1:
                    # cell 瓦片 1 像素覆盖 4x4 方块（场景单位=方块）
                    item.setScale(float(cell_px))
                    # 平滑放大消除色块/锯齿（同 _on_tile_done）
                    item.setTransformationMode(
                        Qt.TransformationMode.SmoothTransformation)
                key = (tx, tz)
                self._tiles[key] = pm
                self._tile_items[key] = item
                self._tile_lod[key] = lod

        self._last = dict(result)

        # 区块网格（16 方块一格，半透明白线，可开关；无限网格跟随
        # 视口；开关守卫在 _rebuild_grid 内）
        self._rebuild_grid()

        # 结构标记（悬停提示 = "群系名+村庄"/中文名 + 坐标；点击复制
        # /tp）村庄图标按生成群系取变体；不再绘制常驻文字标签，
        # 名称/坐标信息由悬停 tooltip 提供
        self._render_markers(result.get("structures", []))
        # 增量结构扫描基线：初始地图整体视为已扫描（拖出边界才补扫）
        self._scan_covered = self._world_rect()

        # 定位激活跟随：同种子/版本重渲染后重画定位链与强制图标
        # （结构定位链/群系定位链含图标；场景项已随 scene.clear()
        # 重建，按保存的数据恢复）
        if same_world:
            if self._locate_struct_key is not None \
                    and self._locate_inst is not None:
                tx, tz = self._locate_point
                inst = self._locate_inst
                self._draw_locate(tx, tz, int(inst["x"]),
                                  int(inst["z"]), self._locate_dist)
                self._ensure_locate_icon()
            elif self._locate_biome_id is not None \
                    and self._locate_biome_xy is not None:
                tx, tz = self._locate_point
                bx, bz = self._locate_biome_xy
                self._draw_locate(tx, tz, int(bx), int(bz),
                                  self._locate_dist,
                                  icon_key=self._locate_biome_icon_key)
            self._set_coord_labels_visible(True)   # 重渲染后坐标重新可见

        # 视图适配 + 缩放钳制（瓦片补渲染统一用初始 LOD，见
        # _ensure_viewport_tiles）
        self._fit_view()
        self._clamp_zoom()
        self._schedule_timer.start()

    # ---------- 瓦片管理与视口补渲染调度 ----------
    def _world_rect(self) -> tuple[int, int, int, int]:
        """当前地图实际渲染内容的世界范围 (bx0, bz0, bx1, bz1)。

        左闭右开：bx1/bz1 为内容末方块 +1（与切片/瓦片格换算同
        语义；radius 半径地图采样宽 = 2*radius，内容即
        [-radius, radius) 而非含端点 [-radius, radius]）。
        """
        res = self._last
        obx = int(res["origin_bx"])
        obz = int(res["origin_bz"])
        # 下界/末地数据固定 4方块/像素（同 _apply_result 口径）
        if res.get("dimension", "overworld") != "overworld":
            cell_px = 4
        else:
            cell_px = 4 if res.get("lod", "block") == "cell" else 1
        h, w = res["rgb"].shape[:2]
        return obx, obz, obx + w * cell_px, obz + h * cell_px

    def _visible_world_rect(self) -> tuple[int, int, int, int]:
        """当前视口可见的世界方块矩形。"""
        vp = self.viewMap.viewport().rect()
        tl = self.viewMap.mapToScene(vp.topLeft())
        br = self.viewMap.mapToScene(vp.bottomRight())
        return (int(tl.x()), int(tl.y()),
                int(br.x()) + 1, int(br.y()) + 1)

    def _clamp_zoom(self) -> None:
        """把视口缩放钳到 [_ZOOM_MIN_SCALE, _ZOOM_MAX_SCALE]。"""
        m = self.viewMap.transform().m11()
        if m < _ZOOM_MIN_SCALE:
            f = _ZOOM_MIN_SCALE / max(m, 1e-9)
            self.viewMap.scale(f, f)
        elif m > _ZOOM_MAX_SCALE:
            f = _ZOOM_MAX_SCALE / m
            self.viewMap.scale(f, f)

    def _cancel_tile_thread(self) -> None:
        """放弃当前瓦片批次：置取消标志并转入 retired 保引用。

        运行中的 QThread 若立即解除引用会被析构（0xC0000409 经典
        崩溃），线程自然结束后由 finished 回调 _reap_tile_thread
        统一回收；对已结束的线程本方法等价于纯回收，无副作用。
        """
        th = self._tile_thread
        self._tile_thread = None
        if th is None:
            return
        th.request_cancel()
        if th not in self._tile_retired:
            self._tile_retired.append(th)

    def _reap_tile_thread(self, th) -> None:
        """瓦片线程 finished 回调：deleteLater 回收并移出 retired。

        setParent(None) 在 Python 引用归零时立即析构 C++ 对象；
        deleteLater 延迟到事件循环执行且线程已结束，退出阶段安全。
        """
        try:
            th.deleteLater()
        except RuntimeError:
            pass
        try:
            self._tile_retired.remove(th)
        except ValueError:
            pass

    def _ensure_viewport_tiles(self) -> None:
        """检查视口内缺失瓦片，整批提交后台增量渲染（渐进铺满）。

        触发时机：初始渲染完成、拖动/缩放/定位停顿 180ms 后。
        补渲染统一沿用初始 LOD 档位（_tile_lod 与初始一致），不做
        缩放驱动的升级/降级：放大后 cell 瓦片平滑放大显示即可，
        保证任意时刻视口瓦片档位一致（避免混档接缝）。
        单批 ≤_TILE_BATCH_MAX 块（距视口中心近的优先），完成后
        batch_done 零延迟续批。
        """
        if self._last is None or self._running:
            return
        if self._tile_thread is not None:
            # 当前批次进行中：不重复提交（批次结束后 batch_done 会
            # 再调度一轮自愈，避免批次中途把未跑的瓦片重复入列）
            return
        bx0, bz0, bx1, bz1 = self._visible_world_rect()
        # 钳到可导航世界边界（防极端缩放拖出 absurd 坐标）
        bx0, bz0 = max(bx0, -_WORLD_LIMIT), max(bz0, -_WORLD_LIMIT)
        bx1, bz1 = min(bx1, _WORLD_LIMIT), min(bz1, _WORLD_LIMIT)
        if bx1 <= bx0 or bz1 <= bz0:
            return

        t0x, t0z = bx0 // _TILE_BLOCKS, bz0 // _TILE_BLOCKS
        t1x, t1z = ((bx1 - 1) // _TILE_BLOCKS,
                    (bz1 - 1) // _TILE_BLOCKS)   # 末方块所在瓦片格
        vcx, vcz = (bx0 + bx1) / 2.0, (bz0 + bz1) / 2.0
        need: list[tuple[int, int]] = []
        for tz in range(t0z, t1z + 1):
            for tx in range(t0x, t1x + 1):
                if (tx, tz) not in self._tiles:
                    need.append((tx, tz))
        if not need:
            return

        # 距视口中心近的优先 + 单批限量（每批 <1s 上屏，渐进铺满）
        need.sort(key=lambda t: (t[0] * _TILE_BLOCKS + _TILE_BLOCKS / 2
                                 - vcx) ** 2
                 + (t[1] * _TILE_BLOCKS + _TILE_BLOCKS / 2
                    - vcz) ** 2)
        batch = need[:_TILE_BATCH_MAX]
        # 续批轮次兜底：防极端视口/缓存互柜导致无限补渲染
        self._fill_rounds += 1
        if self._fill_rounds > _MAX_FILL_ROUNDS:
            return

        # 新批次：作废旧线程，重建并跑新瓦片列表（LOD = 初始地图档位）
        self._cancel_tile_thread()
        self._tile_epoch += 1
        seed = int(self._last["seed"])
        version = str(self._last["version"])
        lod = str(self._last.get("lod", "block"))
        if str(self._last.get("dimension", "overworld")) != "overworld":
            lod = "cell"   # 下界/末地数据固定 4方块/像素（线程内同规则）
        th = TileRenderThread(seed, version, batch, parent=self,
                              lod=lod, hillshade=self._hillshade_on,
                              dimension=str(self._last.get(
                                  "dimension", "overworld")))
        epoch = self._tile_epoch
        th.tile_done.connect(
            lambda payload, e=epoch: self._on_tile_done(payload, e))
        th.batch_done.connect(
            lambda e=epoch: self._on_tile_batch_done(e))
        th.error.connect(self._on_tile_error)
        th.finished.connect(
            lambda t=th: self._reap_tile_thread(t))
        th.finished.connect(th.deleteLater)
        self._tile_thread = th
        th.start()

    def _on_tile_done(self, payload: dict, epoch: int) -> None:
        """瓦片渲染完成：过期批次丢弃；否则替换场景像素项并做加权
        LRU 记账（超预算淘汰最久未用的瓦片）。"""
        if epoch != self._tile_epoch or self._last is None:
            return
        key = (int(payload["tx"]), int(payload["tz"]))
        rgb = payload["rgb"]
        h, w = rgb.shape[:2]
        cell_px = 4 if payload.get("lod") == "cell" else 1
        img = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
        pm = QPixmap.fromImage(img.copy())
        old = self._tile_items.get(key)
        if old is not None:
            self._scene.removeItem(old)
        item = self._scene.addPixmap(pm)
        item.setPos(int(payload["origin_bx"]), int(payload["origin_bz"]))
        if cell_px != 1:
            item.setScale(float(cell_px))   # 1 像素覆盖 4x4 方块
            # 平滑放大消除色块/锯齿（同 _apply_result 初始切片）
            item.setTransformationMode(
                Qt.TransformationMode.SmoothTransformation)
        item.setZValue(0)
        # LRU 记账：重插到队尾 = 最近使用
        self._tiles.pop(key, None)
        self._tiles[key] = pm
        self._tile_items[key] = item
        self._tile_lod[key] = "cell" if payload.get("lod") == "cell" \
            else "block"
        self._evict_tiles()
        # 不在此处重启调度：批次进行中 _ensure_viewport_tiles 有保护，
        # 收尾由 batch_done 统一再调度一轮（拖动中视口变化的自愈）

    def _evict_tiles(self) -> None:
        """加权 LRU 淘汰：总权重超预算时移除最久未用的（含场景项）。

        视口保护：可见瓦片（±2 瓦片格邻域）不参与淘汰——拖动/
        缩放中先把当前视野外的旧瓦片换出去，用户拖回视口内瓦片
        立即可用（防铺满过程新旧互柜）。

        权重：cell 瓦片（256²×3 ≈ 0.2MB）记 1，block 瓦片
        （1024²×3 ≈ 3MB）记 6（内存差 16 倍按价值折中）：等价于
        cell 预算 400 块 / block 预算 66 块。预算须 ≥ 极限缩小视口
        所需瓦片总量，否则铺满过程新旧互柜永远补不齐。
        """
        protected = set()
        if self._last is not None:
            bx0, bz0, bx1, bz1 = self._visible_world_rect()
            t0x, t0z = bx0 // _TILE_BLOCKS - 2, bz0 // _TILE_BLOCKS - 2
            t1x, t1z = (bx1 - 1) // _TILE_BLOCKS + 2, \
                (bz1 - 1) // _TILE_BLOCKS + 2
            for tz in range(t0z, t1z + 1):
                for tx in range(t0x, t1x + 1):
                    protected.add((tx, tz))
        total = sum(_CACHE_W_BLOCK if self._tile_lod.get(k) == "block"
                    else 1 for k in self._tiles)
        while self._tiles and total > _CACHE_WEIGHT_BUDGET:
            # 从最旧端找第一个无保护瓦片（保护瓦片跳过不淘汰）
            victim = None
            for k in self._tiles:
                if k not in protected:
                    victim = k
                    break
            if victim is None:
                break    # 全部受保护：宁可超预算也不杀视口内瓦片
            w = _CACHE_W_BLOCK if self._tile_lod.get(victim) == "block" \
                else 1
            self._tiles.pop(victim)
            total -= w
            item = self._tile_items.pop(victim, None)
            self._tile_lod.pop(victim, None)
            if item is not None:
                self._scene.removeItem(item)

    def _on_tile_batch_done(self, epoch: int) -> None:
        """整批完成：回收线程引用并零延迟续批（渐进铺满自愈）。"""
        if epoch != self._tile_epoch:
            return    # 旧批次：线程已在作废时入 retired，不碰新线程
        self._cancel_tile_thread()   # 线程已结束，仅回收引用
        self._schedule_timer.start()   # 防抖间隔后续批，渐进铺满

    def _on_tile_error(self, msg: str) -> None:
        self._cancel_tile_thread()   # 线程已结束，仅回收引用
        NotificationWidget.Show(
            "瓦片渲染失败",
            msg,
            _NOTIFY_DURATION_MS,
            title_size=_NOTIFY_TITLE_SIZE,
            message_size=_NOTIFY_MESSAGE_SIZE,
            padding=_NOTIFY_PADDING,
        )

    def _rebuild_grid(self):
        """无限区块网格：覆盖视口邻域（±2 瓦片格），跟随视口重建。

        网格不再绑定初始地图范围（地图已无边界）；悬停/拖动触发
        重建时用当前可见范围计算，防越缩越大后网格线数量爆炸。
        关闭态（_grid_on=False）直接移除现项并返回：守卫放这里
        兜住全部调用点（拖动/缩放触发重建时不检查开关，曾致
        取消勾选后缩放/拖动网格复活——用户反馈 bug）。
        """
        if self._grid_item is not None:
            try:
                self._scene.removeItem(self._grid_item)
            except RuntimeError:
                pass
            self._grid_item = None
        if not self._grid_on or self._last is None:
            return None
        step = _CHUNK_GRID_SIZE
        bx0, bz0, bx1, bz1 = self._visible_world_rect()
        pad = _TILE_BLOCKS * 2
        x0, y0 = bx0 - pad, bz0 - pad
        x1, y1 = bx1 + pad, bz1 + pad
        # 限制网格范围防极端（同步 _WORLD_LIMIT 钳制）
        x0, y0 = max(x0, -_WORLD_LIMIT), max(y0, -_WORLD_LIMIT)
        x1, y1 = min(x1, _WORLD_LIMIT), min(y1, _WORLD_LIMIT)
        path = QPainterPath()
        xx = (int(x0) // step) * step
        while xx < x1:
            path.moveTo(xx, y0)
            path.lineTo(xx, y1)
            xx += step
        zz = (int(y0) // step) * step
        while zz < y1:
            path.moveTo(x0, zz)
            path.lineTo(x1, zz)
            zz += step
        item = self._scene.addPath(path, QPen(_CHUNK_GRID_COLOR, 0.0))
        item.setZValue(5)
        self._grid_item = item
        return item

    def _fit_view(self) -> None:
        """视图适配初始地图范围（渲染完成后调用）。

        无限地图下场景矩形会随瓦片铺设不断膨胀，不能再用
        sceneRect（会越用视野越小）；固定适配首屏渲染范围。
        """
        self.viewMap.fitInView(self._fit_rect(),
                               Qt.AspectRatioMode.KeepAspectRatio)

    def _fit_rect(self):
        """首屏适配目标：初始地图的世界范围（QRectF）。"""
        x0, y0, x1, y1 = self._world_rect()
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    # ---------- 视图交互：缩放 / 拖拽 / 悬停 / 点击复制 ----------
    # 视口（viewport）会消费地图区域的鼠标事件，控件层覆写收不到；
    # 统一用 viewport 事件过滤器拦截：滚轮缩放 / 左键拖拽平移 /
    # 悬停查询 / 点击标记复制，全部在此分发。
    def eventFilter(self, obj, ev) -> bool:
        if obj is not self.viewMap.viewport():
            return super().eventFilter(obj, ev)
        et = ev.type()
        if et == QEvent.Wheel:
            if self._last is None:
                return False
            return self._on_wheel(ev)
        if et == QEvent.ContextMenu:
            self._show_context_menu(ev.globalPos())
            return True
        if self._last is None:
            return super().eventFilter(obj, ev)
        if et == QEvent.MouseButtonPress:
            return self._on_press(ev)
        if et == QEvent.MouseMove:
            return self._on_move(ev)
        if et == QEvent.MouseButtonRelease:
            return self._on_release(ev)
        return super().eventFilter(obj, ev)

    def _show_context_menu(self, global_pos) -> None:
        """右键菜单：区块网格/地形阴影开关 + 适配视野。"""
        menu = QMenu(self)
        act_grid = menu.addAction("区块网格")
        act_grid.setCheckable(True)
        act_grid.setChecked(self._grid_on)
        act_hs = menu.addAction("地形阴影")
        act_hs.setCheckable(True)
        act_hs.setChecked(self._hillshade_on)
        menu.addSeparator()
        # 有地图才提供「添加坐标」（无限地图语义下任何可见点都有效）
        act_add = None
        if self._last is not None:
            act_add = menu.addAction("填入坐标到定位栏")
        # 任务③：定位链激活时提供「删除路径」（清虚线+定位点+标签）
        act_del = None
        if self._locate_items:
            act_del = menu.addAction("删除路径")
        act_fit = menu.addAction("适配视野")
        chosen = menu.exec(global_pos)
        if chosen is act_grid:
            self._toggle_grid()
        elif chosen is act_hs:
            self._toggle_hillshade()
        elif act_del is not None and chosen is act_del:
            self._delete_locate_path()
        elif act_add is not None and chosen is act_add:
            # 右键点所在方块坐标直接填入 X/Z 定位输入框（场景单位=方块）
            sp = self.viewMap.mapToScene(
                self.viewMap.viewport().mapFromGlobal(global_pos))
            bx, bz = int(sp.x()), int(sp.y())
            if abs(bx) < _WORLD_LIMIT and abs(bz) < _WORLD_LIMIT:
                self._fill_coord_field(bx, bz)
        elif chosen is act_fit:
            self._fit_view()

    def _delete_locate_path(self) -> None:
        """任务③「删除路径」：右键清除定位链场景项（虚线+定位点+
        坐标/距离标签+图标），并复位激活状态与下拉选择。

        语义 = 用户手动撤销定位：两条定位链（结构/群系）互斥，
        按激活方回设对应下拉回首项；在途查找线程取消防迟到结果
        重建链路。"""
        if not self._locate_items:
            return
        if self._locate_struct_key is not None:
            self._cancel_locate_thread()
            self._locate_epoch += 1
            self._remove_locate()
            self._set_struct_combo_index(0)
        elif self._locate_biome_id is not None:
            self._cancel_biome_thread()
            self._remove_biome_locate()
            self._set_biome_combo_index(0)
        else:
            # 无激活状态但场景项残留（理论不可达）：仅清场景
            self._clear_locate_items()
        self.labelInfo.setText("已删除定位路径")

    def _set_struct_combo_index(self, idx: int) -> None:
        """结构下拉静默回设（blockSignals 防触发新一轮查找）。"""
        box = self.structureLocateList
        if box.currentIndex() != idx:
            box.blockSignals(True)
            box.setCurrentIndex(idx)
            box.blockSignals(False)

    def _set_biome_combo_index(self, idx: int) -> None:
        """群系下拉静默回设（blockSignals 防触发撤销/查找）。"""
        box = self.biomeLocateList
        if box.currentIndex() != idx:
            box.blockSignals(True)
            box.setCurrentIndex(idx)
            box.blockSignals(False)

    def _toggle_hillshade(self) -> None:
        """切换地形阴影：仅改状态并落盘，重新生成地图后生效。"""
        self._hillshade_on = not self._hillshade_on
        self._persist()
        if self._has_map:
            NotificationWidget.Show(
                "地形阴影已" + ("开启" if self._hillshade_on else "关闭"),
                "重新生成地图后生效",
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )

    def _toggle_grid(self) -> None:
        self._grid_on = not self._grid_on
        self._persist()
        self._rebuild_grid()   # 守卫在内：开启=重建，关闭=移除现项

    def _on_wheel(self, ev) -> bool:
        """滚轮锚点缩放（Ctrl+滚轮留给外层滚动页面）；钳制+补渲染调度。"""
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return False
        factor = 1.25 if ev.angleDelta().y() > 0 else 0.8
        m_before = self.viewMap.transform().m11()
        self.viewMap.scale(factor, factor)
        self._clamp_zoom()
        m_after = self.viewMap.transform().m11()
        if abs(m_after - m_before) > 1e-9:
            self._clear_marker_tip()   # 缩放后标记屏幕位置变化，收起旧提示
            # 任务④：缩放也属导航，隐藏端点坐标标签（同拖动语义）
            self._set_coord_labels_visible(False)
            # 缩放生效才调度（钳到边界的无效滚动不反复触发）；
            # 用户主动交互重置续批轮次，重新铺满
            self._fill_rounds = 0
            self._schedule_timer.start()
            self._scan_timer.start()   # 缩放后视野变化，结构增量扫描跟进
            self._rebuild_grid()
        return True

    def _on_press(self, ev) -> bool:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._clear_marker_tip()   # 拖拽开始前收起提示
            self._pan_start = ev.position().toPoint() \
                if hasattr(ev, "position") else ev.pos()
            self.viewMap.setCursor(Qt.CursorShape.ClosedHandCursor)
            return True
        return False

    def _on_move(self, ev) -> bool:
        pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
        # 1) 拖拽平移（滚动条跟随，Chrome 式）
        if self._pan_start is not None:
            delta = pos - self._pan_start
            self._pan_start = pos
            sb_h = self.viewMap.horizontalScrollBar()
            sb_v = self.viewMap.verticalScrollBar()
            sb_h.setValue(sb_h.value() - delta.x())
            sb_v.setValue(sb_v.value() - delta.y())
            # 任务④：用户移动地图后隐藏定位链端点坐标标签
            # （定位完成后可见，开始浏览地图即收起，避免遮挡）
            self._set_coord_labels_visible(False)
            # 拖出新区域后延迟补渲染（停顿 180ms 才调度，拖动中不卡）；
            # 用户主动拖动重置续批轮次，重新铺满
            self._fill_rounds = 0
            self._schedule_timer.start()
            self._scan_timer.start()   # 拖动后视野变化，结构增量扫描跟进
            self._rebuild_grid()
            return True
        # 2) 悬停查询：视图坐标 → 场景（方块）坐标 → 群系
        self._update_hover(pos)
        return False

    def _on_release(self, ev) -> bool:
        was_pan = self._pan_start is not None
        if was_pan:
            self._pan_start = None
            self.viewMap.setCursor(Qt.CursorShape.ArrowCursor)
        if ev.button() == Qt.MouseButton.LeftButton and not was_pan:
            pos = ev.position().toPoint() if hasattr(ev, "position") \
                else ev.pos()
            self._click_map(pos)
            return True
        return False

    def _scene_block(self, view_pos) -> tuple[int, int] | None:
        """视图坐标 → 世界方块坐标（场景坐标即世界方块坐标）。"""
        if self._last is None:
            return None
        sp = self.viewMap.mapToScene(view_pos)
        return int(sp.x()), int(sp.y())

    def _update_hover(self, pos) -> None:
        blk = self._scene_block(pos)
        if blk is None:
            self._clear_marker_tip()
            return
        bx, bz = blk
        res = self._last
        origin_bx, origin_bz = int(res["origin_bx"]), int(res["origin_bz"])
        biomes = res["biomes"]
        # 噪声格索引（方块 >> 2；群系判定层与游戏 F3 一致），
        # 矩阵渲染是方块级但群系数据仍是噪声格分辨率
        col = (bx - origin_bx) >> 2
        row = (bz - origin_bz) >> 2
        h, w = biomes.shape[:2]
        if not (0 <= row < h and 0 <= col < w):
            # 初始矩阵范围外（无限地图新区域）：按需采样该噪声格
            bid = self._probe_biome(bx, bz)
            if bid is None:
                self.labelHover.setText(f"X {bx}  Z {bz}")
                self._clear_marker_tip()
                return
            self.labelHover.setText(
                f"X {bx}  Z {bz}  |  {biome_cn_name(bid)} (id {bid})")
            self._clear_marker_tip()
            return
        bid = int(biomes[row, col])
        self.labelHover.setText(
            f"X {bx}  Z {bz}  |  {biome_cn_name(bid)} (id {bid})")
        self._update_marker_tip(pos)

    def _dim_probe_sampler(self, dim: str):
        """悬停探测用的维度采样器（按 (seed, dim) 缓存实例）。

        NetherSampler/EndSampler 初始化含 256 次洗牌 + skipNextN，
        MouseMove 高频调用必须缓存；同一 seed+dim 复用同一实例。
        """
        key = (int(self._last["seed"]), dim)
        s = self._probe_samplers.get(key)
        if s is None:
            if dim == "nether":
                from Utils.MapPreviewer.nether_end_sampler import \
                    NetherSampler
                s = NetherSampler(key[0])
            else:
                from Utils.MapPreviewer.nether_end_sampler import \
                    EndSampler
                s = EndSampler(key[0])
            self._probe_samplers[key] = s
        return s

    def _probe_biome(self, bx: int, bz: int) -> int | None:
        """范围外悬停的群系探测（单点，零 UI 阻塞风险）。

        下界：噪声格单点（1 格 = 4 方块，与地图渲染同分辨率）；
        末地：chunk 级单点（map_region 的每像素群系 = 所在 chunk
        群系，(bx>>4, bz>>4) 与地图渲染一致）；主世界沿用
        sample_region 4x4 方块窗口（无最小窗口约束）。
        """
        try:
            dim = str(self._last.get("dimension", "overworld"))
            if dim == "nether":
                return int(self._dim_probe_sampler(dim)
                           .biome_at(bx >> 2, bz >> 2))
            if dim == "end":
                return int(self._dim_probe_sampler(dim)
                           .biome_at_chunk(bx >> 4, bz >> 4))
            from Utils.MapPreviewer.map_sampler import sample_region
            res = sample_region(int(self._last["seed"]),
                                str(self._last["version"]),
                                bx & ~3, bz & ~3, 4, 4,
                                surface_mode=True)   # 与地图渲染同语义
            return int(res["biomes"][0, 0])
        except Exception:
            return None

    def _marker_at(self, scene_pos):
        """场景坐标 → 命中的结构标记（锚点距离 ≤ _MARKER_HIT_R）。

        命中点用 data(1) 存的标记锚点坐标（不依赖 item 几何：
        图标项与椭圆项的 shape/rect 语义不同）；
        点击复制与悬停 tooltip 共用此判定。
        """
        best, best_d = None, 1e18
        for item in getattr(self, "_markers", []):
            ax, az = item.data(1)
            d = (ax - scene_pos.x()) ** 2 + (az - scene_pos.y()) ** 2
            if d < best_d:
                best, best_d = item, d
        if best is not None and best_d <= _MARKER_HIT_R ** 2:
            return best
        return None

    def _update_marker_tip(self, view_pos) -> None:
        """主动悬停 tooltip：锚点距离判定，弹出最近标记的提示。

        不依赖 Qt 内建 item tooltip——ItemIgnoresTransformations 项的
        内建悬停命中在视图变换下不可靠，且视口装了 eventFilter，
        由 MouseMove 主动接管最稳；tip 文本存 data(2)。
        """
        hit = self._marker_at(self.viewMap.mapToScene(view_pos))
        if hit is None:
            self._clear_marker_tip()
            return
        if hit is self._hover_tip_item and QToolTip.isVisible():
            return   # 仍在同一标记上且提示已显示：不重复刷（防闪烁）
        tip = hit.data(2)
        if not tip:
            return
        self._hover_tip_item = hit
        QToolTip.showText(self.viewMap.viewport().mapToGlobal(view_pos), tip)

    def _clear_marker_tip(self) -> None:
        """隐藏主动 tooltip（移出标记/无地图/拖拽/缩放时）。"""
        if self._hover_tip_item is not None:
            self._hover_tip_item = None
            if QToolTip.isVisible():
                QToolTip.hideText()

    def _click_map(self, pos) -> None:
        """点击结构标记 → 复制 /tp 命令（锚点命中判定，同悬停）。"""
        hit = self._marker_at(self.viewMap.mapToScene(pos))
        if hit is not None:
            cmd = hit.data(0)
            QApplication.clipboard().setText(cmd)
            NotificationWidget.Show(
                "已复制",
                cmd,
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )

    # ---------- 结构标记渲染与视野增量扫描 ----------
    def _render_markers(self, structs: list) -> None:
        """重建全部结构标记（初始渲染/按钮重渲染时调用）。"""
        self._clear_marker_tip()
        for item in self._markers:
            try:
                self._scene.removeItem(item)
            except RuntimeError:
                pass    # scene.clear() 后旧项 C++ 对象已析构
        self._markers = []
        self._structs_seen = {}
        for st in structs:
            self._add_marker(st)

    def _add_marker(self, st: dict) -> None:
        """单个结构 → 标记图形项（图标优先，缺失回退红圈），并入去重表。"""
        key = st["struct"]
        name = st.get("name", key)
        biome = st.get("biome")
        shown = st_icons.display_name(name, key, biome)
        x, z = int(st["x"]), int(st["z"])
        self._structs_seen[(key, x, z)] = st
        tip = (f"{shown}  ({x}, {z})\n"
               f"点击复制 /tp 命令")
        icon_file = st_icons.icon_path(key, biome)
        if icon_file:
            pm = QPixmap(icon_file)
            if not pm.isNull():
                # 浮板式合成：灰板+图标+右下柔和暗影
                # （就近缩放像素风清晰，锚点命中走 data(1) 距离）
                pm = _compose_plate_icon(pm)
                item = QGraphicsPixmapItem(pm)
                item.setOffset(-_MARK_PIX_SIZE / 2.0,
                               -_MARK_PIX_SIZE / 2.0)
                item.setPos(x, z)
                # 恒定屏幕大小：不随地图缩放（JourneyMap 式标记）
                item.setFlag(QGraphicsPixmapItem.GraphicsItemFlag
                             .ItemIgnoresTransformations, True)
                item.setZValue(10)
                item.setToolTip(tip)
                item.setData(0, f"/tp @s {x} ~ {z}")
                item.setData(1, (float(x), float(z)))   # 锚点，供点击命中
                item.setData(2, tip)   # 主动 tooltip 文本（Mousemove 接管）
                self._scene.addItem(item)   # 裸构造项须手动入场景
                self._markers.append(item)
                return item

        # 回退：图标缺失（用户删除/未随版本分发）→ 原红圈标记
        item = self._scene.addEllipse(
            x - _MARKER_R, z - _MARKER_R, _MARKER_R * 2, _MARKER_R * 2,
            QPen(QColor(255, 64, 64), 2.5),
            QBrush(QColor(255, 64, 64, 40)))
        item.setZValue(10)
        item.setToolTip(tip)
        item.setData(0, f"/tp @s {x} ~ {z}")
        item.setData(1, (float(x), float(z)))   # 锚点，供点击命中
        item.setData(2, tip)   # 主动 tooltip 文本（Mousemove 接管）
        self._markers.append(item)
        return item

    def _ensure_structure_scan(self) -> None:
        """视口超出已扫描范围时提交一次结构增量扫描（防抖后调用）。

        初始地图整体视为已扫描（_scan_covered = 地图范围）；拖动/
        缩放后视口（扩 _SCAN_MARGIN）未被覆盖才扫描，扫完把覆盖
        矩形并入 _scan_covered，发现的新结构并入现有标记（去重）。
        """
        if self._last is None or self._running:
            return
        if self._scan_thread is not None:
            return    # 在途：完成后 _on_scan_done 会再调度一轮自愈
        keys = sorted(self._selected or set())
        if not keys:
            return
        bx0, bz0, bx1, bz1 = self._visible_world_rect()
        bx0, bz0 = max(bx0 - _SCAN_MARGIN, -_WORLD_LIMIT), \
            max(bz0 - _SCAN_MARGIN, -_WORLD_LIMIT)
        bx1, bz1 = min(bx1 + _SCAN_MARGIN, _WORLD_LIMIT), \
            min(bz1 + _SCAN_MARGIN, _WORLD_LIMIT)
        if bx1 <= bx0 or bz1 <= bz0:
            return
        # 极端缩小视口钳到单次扫描上限（以视口中心为准）
        if bx1 - bx0 > _SCAN_MAX_SIDE:
            c = (bx0 + bx1) // 2
            bx0, bx1 = c - _SCAN_MAX_SIDE // 2, c + _SCAN_MAX_SIDE // 2
        if bz1 - bz0 > _SCAN_MAX_SIDE:
            c = (bz0 + bz1) // 2
            bz0, bz1 = c - _SCAN_MAX_SIDE // 2, c + _SCAN_MAX_SIDE // 2
        if self._scan_covered is not None:
            cx0, cz0, cx1, cz1 = self._scan_covered
            if bx0 >= cx0 and bz0 >= cz0 and bx1 <= cx1 and bz1 <= cz1:
                return    # 视口已在已扫描范围内，无需补扫
        self._scan_epoch += 1
        seed = int(self._last["seed"])
        version = str(self._last["version"])
        th = StructureScanThread(seed, version, (bx0, bz0, bx1, bz1),
                                 keys, parent=self,
                                 dimension=str(self._last.get(
                                     "dimension", "overworld")))
        epoch = self._scan_epoch
        th.structures_done.connect(
            lambda p, e=epoch: self._on_scan_done(p, e))
        th.error.connect(self._on_scan_error)
        th.finished.connect(lambda t=th: self._reap_scan_thread(t))
        th.finished.connect(th.deleteLater)
        self._scan_thread = th
        th.start()

    def _cancel_scan_thread(self) -> None:
        """放弃在途结构扫描：置取消标志并转入 retired 保引用。

        运行中的 QThread 立即解引用会被析构（0xC0000409 经典崩溃），
        线程自然结束后由 finished 回调统一回收。
        """
        th = self._scan_thread
        self._scan_thread = None
        if th is None:
            return
        self._scan_epoch += 1   # 被放弃线程的迟到结果按序号丢弃
        th.request_cancel()
        if th not in self._scan_retired:
            self._scan_retired.append(th)

    def _reap_scan_thread(self, th) -> None:
        """扫描线程 finished 回调：deleteLater 回收并移出 retired。

        setParent(None) 在 Python 引用归零时立即析构 C++ 对象；
        deleteLater 延迟到事件循环执行且线程已结束，退出阶段安全。
        """
        try:
            th.deleteLater()
        except RuntimeError:
            pass
        try:
            self._scan_retired.remove(th)
        except ValueError:
            pass

    def _on_scan_done(self, payload: dict, epoch: int) -> None:
        """扫描完成：并入覆盖矩形与新发现结构（去重），再防抖自检一轮。

        回收交由 finished → deleteLater（创建处统一连接）：
        本回调到达时线程可能仍在 run() 收尾，不可在此析构。
        """
        self._scan_thread = None
        if epoch != self._scan_epoch or self._last is None or self._running:
            return    # 迟到结果（新批次已发起/全量重渲染中）：丢弃
        view = tuple(payload["view"])
        if self._scan_covered is not None:
            cx0, cz0, cx1, cz1 = self._scan_covered
            self._scan_covered = (min(view[0], cx0), min(view[1], cz0),
                                  max(view[2], cx1), max(view[3], cz1))
        else:
            self._scan_covered = view
        for st in payload.get("structures", []):
            k = (st["struct"], int(st["x"]), int(st["z"]))
            if k not in self._structs_seen:
                self._add_marker(st)   # 只增不删：拖回旧区域标记仍在
        # 视口可能又动了：防抖后再检查一轮（拖动连续时的自愈）
        self._scan_timer.start()

    def _on_scan_error(self, msg: str) -> None:
        """扫描线程异常：回收引用并提示（不打断地图使用）。

        已被取消的线程（孤儿）报错静默：用户没发起的扫描
        不该弹"结构扫描失败"。
        """
        orphan = self._scan_thread is None
        self._scan_thread = None   # 回收交由 finished → deleteLater
        if orphan:
            return
        print(f"结构扫描失败: {msg}")
        if not self._running:
            self.labelInfo.setText("结构扫描失败（可点「更新结构」重试）")

    # ---------- 会话持久化 ----------
    def _session_path(self) -> str:
        config_dir = QStandardPaths.writableLocation(
            QStandardPaths.AppConfigLocation)
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, _SESSION_FILE)

    def _persist(self, *_) -> None:
        """实时落盘（数据变化点调用；恢复前不写）。"""
        if not self._session_ready:
            return
        try:
            data = {
                "version": self.comboVersion.currentText(),
                "seed_text": self.editSeed.text(),
                "radius": self.comboRadius.currentText(),
                "dimension": self._active_dimension,
                "selected": sorted(self._selected or set()),
                "selected_other": {d: sorted(s)
                                   for d, s in self._selected_other.items()},
                "grid": self._grid_on,
                "hillshade": self._hillshade_on,
                "locate_struct": self.structureLocateList.currentData(),
                "locate_biome": self.biomeLocateList.currentData(),
            }
            with open(self._session_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"保存 MapPreviewer 会话失败: {e}")

    def _restore_session(self) -> None:
        path = self._session_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
        except (OSError, ValueError) as e:
            print(f"恢复 MapPreviewer 会话失败: {e}")
            return
        version = data.get("version")
        if isinstance(version, str) and \
                self.comboVersion.findText(version) >= 0:
            self.comboVersion.setCurrentText(version)
        seed_text = data.get("seed_text")
        if isinstance(seed_text, str):
            self.editSeed.setText(seed_text)
        radius = data.get("radius")
        if isinstance(radius, str) and self.comboRadius.findText(radius) >= 0:
            self.comboRadius.setCurrentText(radius)
        dim = data.get("dimension")
        if isinstance(dim, str) and dim in ("overworld", "nether", "end"):
            self._active_dimension = dim
            self.worldCombo.setCurrentIndex(
                {v: k for k, v in _DIM_COMBO_INDEX.items()}[dim])
        selected = data.get("selected")
        if isinstance(selected, list):
            keys = self._avail_keys()
            self._selected = {k for k in selected
                              if isinstance(k, str) and k in keys}
        sel_other = data.get("selected_other")
        if isinstance(sel_other, dict):
            for d, keys in sel_other.items():
                if d in ("overworld", "nether", "end") and \
                        isinstance(keys, list):
                    self._selected_other[d] = {
                        k for k in keys if isinstance(k, str)}
        # 恢复的当前维度选择覆盖 selected_other 同维度桶
        # （selected 缺失时保留 selected_other 恢复的桶）
        if self._selected is not None:
            self._selected_other[self._active_dimension] = \
                set(self._selected)
        if isinstance(data.get("grid"), bool):
            self._grid_on = data["grid"]
        if isinstance(data.get("hillshade"), bool):
            self._hillshade_on = data["hillshade"]
        locate_key = data.get("locate_struct")
        if isinstance(locate_key, str):
            i = self.structureLocateList.findData(locate_key)
            if i > 0:   # 恢复到结构项但不触发自动查找（首项 0 不回设）
                self.structureLocateList.blockSignals(True)
                self.structureLocateList.setCurrentIndex(i)
                self.structureLocateList.blockSignals(False)
        self._update_struct_menu()
        # 群系选择在菜单按恢复维度重建之后回设（跨维度 id 表不同）
        biome_key = data.get("locate_biome")
        if isinstance(biome_key, int):
            i = self.biomeLocateList.findData(biome_key)
            if i > 0:   # 恢复到群系项但不触发自动查找（首项 0 不回设）
                self.biomeLocateList.blockSignals(True)
                self.biomeLocateList.setCurrentIndex(i)
                self.biomeLocateList.blockSignals(False)

    def save_config(self) -> None:
        """主窗口退出协议（save_all_tools_config）：保存会话。"""
        self._persist()

    def _stop_thread(self) -> None:
        """停止渲染/瓦片线程（应用退出前调用；重复调用无副作用）。

        运行中的 QThread 退出阶段被析构会 0xC0000409：全部先
        request_cancel + wait，确认结束后再解除父子关系。
        """
        self._schedule_timer.stop()
        self._scan_timer.stop()
        threads = [self._thread, self._tile_thread, self._scan_thread,
                   self._locate_thread, self._biome_thread,
                   *self._tile_retired, *self._scan_retired,
                   *self._locate_retired, *self._biome_retired]
        self._thread = None
        self._tile_thread = None
        self._scan_thread = None
        self._locate_thread = None
        self._biome_thread = None
        self._tile_retired.clear()
        self._scan_retired.clear()
        self._locate_retired.clear()
        self._biome_retired.clear()
        for th in threads:
            if th is None:
                continue
            try:
                if th.isRunning():
                    th.request_cancel()
                    th.wait(5000)
                th.setParent(None)
            except RuntimeError:
                # 退出阶段 C++ 对象可能已被析构，防御性忽略
                pass

    def closeEvent(self, event) -> None:
        """窗口关闭时停止渲染线程（aboutToQuit 的双保险）。"""
        self._stop_thread()
        super().closeEvent(event)
