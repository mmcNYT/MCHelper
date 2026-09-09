# -*- coding: utf-8 -*-
"""MapPreviewer 工具：世界俯视群系图渲染 + 13 种结构精确定位标注。

使用流程：
1. 选择游戏版本、输入种子（支持负数与 0x 十六进制）、选视野半径；
2. 「结构 ▾」选择要标注的结构（常用/全选为预设），点「生成地图」；
3. 后台线程两阶段计算：地形采样（native 引擎秒级）→ 结构枚举
   （正向定位 + cubiomes 位级群系校验，杜绝「应生成却没生成」误报）；
4. 地图上：滚轮缩放（锚点缩放）、按住拖动平移、悬停查看坐标与群系、
   点击结构标记复制对应 /tp 传送命令。

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

from PySide6.QtCore import (QEvent, QPointF, QRectF, QStandardPaths, Qt,
                            QTimer)
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QGraphicsScene, QGraphicsView,
                               QMenu)

from .tool_base import BaseToolWidget
from CodesUI.MapPreviewer import Ui_mapPreviewer
from Threads.task_MapPreviewer import (
    CANCELLED_SUMMARY,
    MapPreviewerThread,
    TileRenderThread,
    _TILE_BLOCKS,
)
from Utils.AutoBackUp.notification import NotificationWidget
from Utils.MapPreviewer.biome_colors import biome_cn_name
from Utils.MapPreviewer.structure_map import available_structures
from Utils.SeedReverser.structure_params import STRUCT_NAMES

# 会话文件名（用户配置目录下）
_SESSION_FILE = "map_previewer_session.json"
# 结构标记半径（场景像素，即方块单位）
_MARKER_R = 10.0
# 通知样式（与 SeedReverser 一致）
_NOTIFY_DURATION_MS = 6000
_NOTIFY_TITLE_SIZE = 16
_NOTIFY_MESSAGE_SIZE = 14
_NOTIFY_PADDING = (20, 16, 20, 16)

# 视野半径下拉文本 → 方块半径（与 CodesUI 下拉项一致）
_RADIUS_MAP = {"512": 512, "1024": 1024, "2048": 2048, "4096": 4096}

# LOD 阈值：视口可见区域宽度（方块）。≤ 512 方块时用 1方块=1像素
# 精细渲染（细节可见）；更宽视野用 4合1 快速渲染（保证大视野 <5s）
_LOD_VIEW_BLOCKS = 512
# 缩放钳制范围（视口缩放比 = 屏幕像素/方块）：最小取全图适配值
# 略下（4096 半径适配约 0.13，不裁边）；再小会让视口需要的瓦片
# 总量超出缓存预算导致重复渲染（见 _CACHE_WEIGHT_BUDGET 注释）。
# 最大 4.0 = 1 方块占 4x4 屏幕像素：必须足够大以保证 block 精细
# 档可达（可见宽 ≤512 要求 m11 ≥ 视口宽/512，1081 宽窗口约 2.11）
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
# 续批轮次上限（兜底：防极端视口/缓存互柜导致无限补渲染）
_MAX_FILL_ROUNDS = 60
# 可导航世界边界（方块）：±2^21，与采样器安全范围一致。必须显式
# 设为场景矩形，否则 QGraphicsScene 的自动 sceneRect 跟随已铺
# 瓦片包围盒，视图拖拽/centerOn 会被钳在已渲染区域内，永远
# 滚不出去，也永远触发不了范围外补渲染（无限地图失效）
_WORLD_LIMIT = 1 << 21

# 「常用」预设结构（与 SeedReverser 观测用版本表的易找顺序一致）
_COMMON_STRUCTS = ("village", "desert_pyramid", "igloo", "swamp_hut",
                   "jungle_temple", "shipwreck", "ocean_ruin")

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
        # 当前 LOD（"block" 精细 / "cell" 快速；随缩放比切换）
        self._lod = "block"
        # 网格图形项（重绘开关时快速移除/重建）
        self._grid_item = None
        # 结构标记（点击复制用）
        self._markers: list = []
        # 结构选择集（勾选状态；None = 尚未初始化）
        self._selected: set[str] | None = None
        # 会话持久化：恢复完成前抑制实时保存
        self._session_ready = False
        # 显示开关（右键菜单切换；山体阴影已按用户要求移除）
        self._grid_on = True

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

        # 版本下拉默认 1.21（UI 已置项，代码再兜底一次）
        if self.comboVersion.currentIndex() < 0:
            self.comboVersion.setCurrentIndex(0)
        # 视野半径默认 1024
        self.comboRadius.setCurrentIndex(1)

        self.progressRender.setRange(0, 100)
        self.progressRender.setValue(0)
        self.progressRender.setTextVisible(False)

        self._update_struct_menu()

    def _init_signals(self) -> None:
        self.btnRender.clicked.connect(self._on_render_clicked)
        self.editSeed.returnPressed.connect(self._on_render_clicked)
        self.btnStructures.clicked.connect(self._on_struct_menu)
        self.btnCommon.clicked.connect(self._on_common)
        self.btnAll.clicked.connect(self._on_all)
        self.comboRadius.currentIndexChanged.connect(self._persist)
        self.comboVersion.currentIndexChanged.connect(self._on_version_changed)

    # ---------- 结构选择菜单 ----------
    def _on_version_changed(self, _) -> None:
        """版本切换：可用结构集变化，清理失效选择并实时落盘。"""
        self._update_struct_menu()
        self._persist()

    def _avail_keys(self) -> tuple[str, ...]:
        """当前版本可标注的结构键。"""
        return available_structures(self.comboVersion.currentText())

    def _update_struct_menu(self) -> None:
        """重建结构多选菜单（版本切换后可用集变化）。"""
        keys = self._avail_keys()
        if self._selected is None:
            self._selected = set(_COMMON_STRUCTS) & set(keys)
        # 清掉不可用的选择
        self._selected &= set(keys)
        self.btnStructures.setToolTip(
            "选择要在地图上标注的结构\n"
            + "\n".join(("☑ " if k in self._selected else "☐ ")
                        + STRUCT_NAMES.get(k, k) for k in keys))

    def _on_struct_menu(self) -> None:
        """「结构 ▾」弹出多选菜单（勾选即生效并实时落盘）。"""
        keys = self._avail_keys()
        menu = QMenu(self)
        for key in keys:
            act = menu.addAction(STRUCT_NAMES.get(key, key))
            act.setCheckable(True)
            act.setChecked(key in self._selected)
            act.toggled.connect(lambda on, k=key: self._toggle_struct(k, on))
        menu.exec(self.btnStructures.mapToGlobal(
            self.btnStructures.rect().bottomLeft()))

    def _toggle_struct(self, key: str, on: bool) -> None:
        if on:
            self._selected.add(key)
        else:
            self._selected.discard(key)
        self._update_struct_menu()
        self._persist()

    def _on_common(self) -> None:
        self._selected = set(_COMMON_STRUCTS) & set(self._avail_keys())
        self._update_struct_menu()
        self._persist()

    def _on_all(self) -> None:
        self._selected = set(self._avail_keys())
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
        radius = _RADIUS_MAP.get(self.comboRadius.currentText().strip(), 1024)
        keys = sorted(self._selected or set())
        if not keys:
            NotificationWidget.Show(
                "未选择结构",
                "请先在「结构 ▾」选择要标注的结构（或点「常用/全选」）",
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )
            return

        version = self.comboVersion.currentText()
        # 初始渲染 LOD 按视野尺寸预判（与 _lod_for_zoom 同一套规则：
        # 大视野整图方块级渲染量巨大，先用快速档保证 <5s 出图，
        # 放大后由瓦片线程逐块升级为精细渲染）
        lod = "cell" if radius >= 2048 else "block"
        self._lod = lod
        self._thread = MapPreviewerThread(seed, version, radius, keys,
                                          parent=self, lod=lod)
        self._thread.progress.connect(self._on_progress)
        self._thread.render_finished.connect(self._on_finished)
        self._thread.error.connect(self._on_error)
        self._thread.start()
        self._running = True
        self._set_running_ui(True)
        self.labelInfo.setText("渲染中…（点击按钮停止）")

    def _cancel_render(self) -> None:
        if self._thread is not None:
            self._thread.request_cancel()
        self.labelInfo.setText("停止中…")

    def _set_running_ui(self, running: bool) -> None:
        """状态机：按钮/输入控件在渲染中的禁用态。"""
        self.btnRender.setText("停止渲染" if running else "生成地图")
        for w in (self.comboVersion, self.editSeed, self.comboRadius,
                  self.btnStructures, self.btnCommon, self.btnAll):
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
        if self._thread is not None:
            self._thread.setParent(None)   # 解引用，交还 Python 侧清理
            self._thread = None
        self._set_running_ui(False)
        self.progressRender.setValue(self.progressRender.maximum())
        if summary == CANCELLED_SUMMARY or not result:
            self.labelInfo.setText("已停止")
            self.progressRender.setValue(0)
            return
        try:
            self._apply_result(result)
            self.labelInfo.setText(summary)
            NotificationWidget.Show(
                "地图生成完成",
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
        if self._thread is not None:
            self._thread.setParent(None)
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
        cell_px = 4 if lod == "cell" else 1   # 1 像素覆盖的方块边长

        self._scene.clear()
        self._grid_item = None
        self._markers = []
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
                key = (tx, tz)
                self._tiles[key] = pm
                self._tile_items[key] = item
                self._tile_lod[key] = lod

        self._last = dict(result)

        # 区块网格（16 方块一格，半透明白线，可开关；无限网格跟随视口）
        if self._grid_on:
            self._rebuild_grid()

        # 结构标记（悬停提示 = 结构 + 坐标；点击复制 /tp）
        for st in result.get("structures", []):
            name = st.get("name", st["struct"])
            x, z = int(st["x"]), int(st["z"])
            tip = (f"{name}  ({x}, {z})\n"
                   f"点击复制 /tp 命令")
            item = self._scene.addEllipse(
                x - _MARKER_R, z - _MARKER_R, _MARKER_R * 2, _MARKER_R * 2,
                QPen(QColor(255, 64, 64), 2.5),
                QBrush(QColor(255, 64, 64, 40)))
            item.setZValue(10)
            item.setToolTip(tip)
            item.setData(0, f"/tp @s {x} ~ {z}")
            self._markers.append(item)

            # 常驻文字标签（JourneyMap 地标风格）：带描边，保证亮暗背景都可读
            label = self._scene.addSimpleText(str(name), QFont("Microsoft YaHei", 8))
            label.setBrush(QBrush(QColor(255, 255, 255)))
            label.setPen(QPen(QColor(0, 0, 0, 220), 3))
            label.setPos(x + _MARKER_R + 2, z - 8)
            label.setZValue(11)

        # 视图适配 + 缩放钳制 + 触发一轮 LOD 调度
        self._fit_view()
        self._clamp_zoom()
        self._lod = self._lod_for_zoom()
        self._schedule_timer.start()

    # ---------- 瓦片管理与 LOD 调度 ----------
    def _world_rect(self) -> tuple[int, int, int, int]:
        """当前地图实际渲染内容的世界范围 (bx0, bz0, bx1, bz1)。

        左闭右开：bx1/bz1 为内容末方块 +1（与切片/瓦片格换算同
        语义；radius 半径地图采样宽 = 2*radius，内容即
        [-radius, radius) 而非含端点 [-radius, radius]）。
        """
        res = self._last
        obx = int(res["origin_bx"])
        obz = int(res["origin_bz"])
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

    def _lod_for_zoom(self) -> str:
        """按视口可见宽度（方块数）选 LOD：≤512 → block 精细档。

        不用「缩放比」判定：同值缩放下不同半径地图的可见范围差异
        巨大（4096 半径全图适配约 0.13，1024 半径约 0.5），可见
        宽度才是与渲染耗时直接相关的量（≤512 方块宽的视口至多
        跨 2x2 块瓦片，增量渲染秒级内）。
        """
        if self._last is None:
            return "block"
        bx0, _, bx1, _ = self._visible_world_rect()
        return "cell" if (bx1 - bx0) > _LOD_VIEW_BLOCKS else "block"

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
        """瓦片线程 finished 回调：解除父子关系并移出 retired。"""
        try:
            th.setParent(None)
        except RuntimeError:
            pass    # 退出阶段 C++ 对象可能已析构
        try:
            self._tile_retired.remove(th)
        except ValueError:
            pass

    def _ensure_viewport_tiles(self) -> None:
        """检查视口内缺失/降级的瓦片，整批提交后台增量渲染。

        触发时机：初始渲染完成、拖动/缩放停顿 180ms 后。
        无限地图：不再与初始半径求交，视口滚到哪渲染到哪；
        单批 ≤_TILE_BATCH_MAX 块（距视口中心近的优先），完成后
        batch_done 零延迟续批，渐进铺满整个视口。
        """
        if self._last is None or self._running:
            return
        if self._tile_thread is not None:
            # 当前批次进行中：不重复提交（批次结束后 batch_done 会
            # 再调度一轮自愈，避免批次中途把未跑的瓦片重复入列）
            return
        want_lod = self._lod_for_zoom()
        bx0, bz0, bx1, bz1 = self._visible_world_rect()
        # 无限地图：视口即渲染范围，不再与初始半径求交；
        # 钳到 [0, 2^21] 方块量级（防极端缩放拖出 absurd 坐标）
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
                elif want_lod == "block" \
                        and self._tile_lod.get((tx, tz)) != "block":
                    # 缓存的是 cell 档瓦片，放大后升级为 block 精细档
                    # （block 瓦片缩视显示≈cell，不降级重渲染）
                    need.append((tx, tz))
        if not need:
            return

        # 距视口中心近的优先 + 单批限量（每批 <1s 上屏，渐进铺满）：
        # 长列表全量排序浪费，用 heapq.nsmallest 取最近的 N 块
        need.sort(key=lambda t: (t[0] * _TILE_BLOCKS + _TILE_BLOCKS / 2
                                 - vcx) ** 2
                 + (t[1] * _TILE_BLOCKS + _TILE_BLOCKS / 2
                    - vcz) ** 2)
        batch = need[:_TILE_BATCH_MAX]
        # 续批轮次兜底：防极端视口/缓存互柜导致无限补渲染
        self._fill_rounds += 1
        if self._fill_rounds > _MAX_FILL_ROUNDS:
            return

        # 新批次：作废旧线程，重建并跑新瓦片列表
        self._cancel_tile_thread()
        self._tile_epoch += 1
        seed = int(self._last["seed"])
        version = str(self._last["version"])
        th = TileRenderThread(seed, version, batch, parent=self,
                              lod=want_lod)
        epoch = self._tile_epoch
        th.tile_done.connect(
            lambda payload, e=epoch: self._on_tile_done(payload, e))
        th.batch_done.connect(
            lambda e=epoch: self._on_tile_batch_done(e))
        th.error.connect(self._on_tile_error)
        th.finished.connect(
            lambda t=th: self._reap_tile_thread(t))
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

        权重：cell 瓦片（256²×3 ≈ 0.2MB）记 1，block 瓦片
        （1024²×3 ≈ 3MB）记 6（内存差 16 倍按价值折中）：等价于
        cell 预算 400 块 / block 预算 66 块。预算须 ≥ 极限缩小视口
        所需瓦片总量，否则铺满过程新旧互柜永远补不齐。
        """
        total = sum(_CACHE_W_BLOCK if self._tile_lod.get(k) == "block"
                    else 1 for k in self._tiles)
        while self._tiles and total > _CACHE_WEIGHT_BUDGET:
            key, _ = self._tiles.popitem(last=False)
            total -= _CACHE_W_BLOCK if self._tile_lod.get(key) == "block" \
                else 1
            item = self._tile_items.pop(key, None)
            self._tile_lod.pop(key, None)
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
        """
        if self._grid_item is not None:
            try:
                self._scene.removeItem(self._grid_item)
            except RuntimeError:
                pass
            self._grid_item = None
        if self._last is None:
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
        """右键菜单：区块网格开关 + 适配视野。"""
        menu = QMenu(self)
        act_grid = menu.addAction("区块网格")
        act_grid.setCheckable(True)
        act_grid.setChecked(self._grid_on)
        menu.addSeparator()
        act_fit = menu.addAction("适配视野")
        chosen = menu.exec(global_pos)
        if chosen is act_grid:
            self._toggle_grid()
        elif chosen is act_fit:
            self._fit_view()

    def _toggle_grid(self) -> None:
        self._grid_on = not self._grid_on
        self._persist()
        if self._grid_on:
            self._rebuild_grid()
        elif self._grid_item is not None:
            try:
                self._scene.removeItem(self._grid_item)
            except RuntimeError:
                pass
            self._grid_item = None

    def _on_wheel(self, ev) -> bool:
        """滚轮锚点缩放（Ctrl+滚轮留给外层滚动页面）；钳制+LOD 调度。"""
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return False
        factor = 1.25 if ev.angleDelta().y() > 0 else 0.8
        m_before = self.viewMap.transform().m11()
        self.viewMap.scale(factor, factor)
        self._clamp_zoom()
        m_after = self.viewMap.transform().m11()
        if abs(m_after - m_before) > 1e-9:
            # 缩放生效才调度（钳到边界的无效滚动不反复触发）；
            # 用户主动交互重置续批轮次，重新铺满
            self._fill_rounds = 0
            self._schedule_timer.start()
            self._rebuild_grid()
        return True

    def _on_press(self, ev) -> bool:
        if ev.button() == Qt.MouseButton.LeftButton:
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
            # 拖出新区域后延迟补渲染（停顿 180ms 才调度，拖动中不卡）；
            # 用户主动拖动重置续批轮次，重新铺满
            self._fill_rounds = 0
            self._schedule_timer.start()
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
                return
            self.labelHover.setText(
                f"X {bx}  Z {bz}  |  {biome_cn_name(bid)} (id {bid})")
            return
        bid = int(biomes[row, col])
        self.labelHover.setText(
            f"X {bx}  Z {bz}  |  {biome_cn_name(bid)} (id {bid})")

    def _probe_biome(self, bx: int, bz: int) -> int | None:
        """范围外悬停的群系探测（4x4 噪声格，零 UI 阻塞风险）。"""
        try:
            from Utils.MapPreviewer.map_sampler import sample_region
            res = sample_region(int(self._last["seed"]),
                                str(self._last["version"]),
                                bx & ~3, bz & ~3, 4, 4)
            return int(res["biomes"][0, 0])
        except Exception:
            return None

    def _click_map(self, pos) -> None:
        """点击结构标记 → 复制 /tp 命令（命中半径 14 场景单位）。"""
        sp = self.viewMap.mapToScene(pos)
        best, best_d = None, 1e18
        for item in getattr(self, "_markers", []):
            c = item.rect().center()
            d = (c.x() - sp.x()) ** 2 + (c.y() - sp.y()) ** 2
            if d < best_d:
                best, best_d = item, d
        if best is not None and best_d <= 14 ** 2:
            cmd = best.data(0)
            QApplication.clipboard().setText(cmd)
            NotificationWidget.Show(
                "已复制",
                cmd,
                _NOTIFY_DURATION_MS,
                title_size=_NOTIFY_TITLE_SIZE,
                message_size=_NOTIFY_MESSAGE_SIZE,
                padding=_NOTIFY_PADDING,
            )

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
                "selected": sorted(self._selected or set()),
                "grid": self._grid_on,
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
        selected = data.get("selected")
        if isinstance(selected, list):
            keys = self._avail_keys()
            self._selected = {k for k in selected
                              if isinstance(k, str) and k in keys}
        if isinstance(data.get("grid"), bool):
            self._grid_on = data["grid"]
        # 旧会话的 hillshade 字段已废弃（山体阴影移除），忽略即可
        self._update_struct_menu()

    def save_config(self) -> None:
        """主窗口退出协议（save_all_tools_config）：保存会话。"""
        self._persist()

    def _stop_thread(self) -> None:
        """停止渲染/瓦片线程（应用退出前调用；重复调用无副作用）。

        运行中的 QThread 退出阶段被析构会 0xC0000409：全部先
        request_cancel + wait，确认结束后再解除父子关系。
        """
        self._schedule_timer.stop()
        threads = [self._thread, self._tile_thread, *self._tile_retired]
        self._thread = None
        self._tile_thread = None
        self._tile_retired.clear()
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
