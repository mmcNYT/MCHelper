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
- 视野 = 以 (0,0) 为中心的方形区域；半径 512~4096 方块；
- 结构判定与 cubiomes finders.c isViableStructurePos 位级一致
  （对拍 1560 点全过，含真实存档验证的 6 条结构观测）；
- 进度数字只在进度条展示；按钮单状态机「生成地图 ↔ 停止渲染」；
- 会话持久化：版本/种子/半径/结构选择实时落盘（用户配置目录
  map_previewer_session.json），重启自动恢复；
- 工具内不调用 setApplicationName（会话目录由主进程应用名决定）。
"""

import json
import os

import numpy as np
from PySide6.QtCore import QEvent, QStandardPaths, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QGraphicsScene, QGraphicsView,
                               QMenu)

from .tool_base import BaseToolWidget
from CodesUI.MapPreviewer import Ui_mapPreviewer
from Threads.task_MapPreviewer import (
    CANCELLED_SUMMARY,
    MapPreviewerThread,
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

# 「常用」预设结构（与 SeedReverser 观测用版本表的易找顺序一致）
_COMMON_STRUCTS = ("village", "desert_pyramid", "igloo", "swamp_hut",
                   "jungle_temple", "shipwreck", "ocean_ruin")

# 山体阴影强度（0~1：阴影面变暗/阳面提亮的最大比例）
_HILLSHADE_STRENGTH = 0.55
# 区块网格（半透明，16 方块一格）
_CHUNK_GRID_SIZE = 16
_CHUNK_GRID_COLOR = QColor(255, 255, 255, 28)


def _apply_hillshade(rgb: np.ndarray, depth: np.ndarray) -> np.ndarray:
    """对 RGB 矩阵叠加山体阴影（JourneyMap 式地形明暗）。

    depth 矩阵是 1.18+ 地形起伏骨架（climate depth 参数 * 10000，噪声格
    1:4 分辨率，与 rgb 同尺寸）：梯度大的地方（山脊/峡谷）明暗对比强。
    光照方向固定西北（-1,-1），与 MC 默认斜向光照观感一致。
    """
    dzdx = np.zeros_like(depth, dtype=np.float32)
    dzdy = np.zeros_like(depth, dtype=np.float32)
    dzdx[:, 1:-1] = (depth[:, 2:] - depth[:, :-2]) / 2.0
    dzdy[1:-1, :] = (depth[2:, :] - depth[:-2, :]) / 2.0
    # 西北光（法向量点积推导）：N=(-dzdx,-dzdy,1)，L=(-1,-1,κ)，
    # N·L ∝ dzdx+dzdy → 平地=0；朝西/朝北的坡（向光面）>0 提亮，
    # 朝东/朝南的坡（背光面）<0 压暗；k 控制坡度敏感度（分母防过冲）
    k = 24.0
    shade = (dzdx + dzdy) / np.sqrt(dzdx * dzdx + dzdy * dzdy + 4.0 * k * k)
    shade = np.clip(shade, -1.0, 1.0)
    # shade ∈ [-1,1] → 明暗系数 [1-s, 1+s]
    s = _HILLSHADE_STRENGTH
    factor = 1.0 + s * shade
    out = rgb.astype(np.float32) * factor[:, :, None]
    return np.clip(out, 0, 255).astype(np.uint8)


class MapPreviewerWidget(BaseToolWidget, Ui_mapPreviewer):
    preferred_size = (1081, 801)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # 后台渲染线程（None 表示空闲）
        self._thread = None
        self._running = False
        # 最近一次渲染载荷（悬停查询/重绘开关用）
        self._last: dict | None = None
        # 阴影/网格图形项（重绘开关时快速移除/重建）
        self._shade_item = None
        self._grid_item = None
        # 结构标记（点击复制用）
        self._markers: list = []
        # 结构选择集（勾选状态；None = 尚未初始化）
        self._selected: set[str] | None = None
        # 会话持久化：恢复完成前抑制实时保存
        self._session_ready = False
        # 显示开关（右键菜单切换）
        self._hillshade_on = True
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
        self._thread = MapPreviewerThread(seed, version, radius, keys,
                                          parent=self)
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
        """采样矩阵 → QImage 场景；结构 → 标记图形项。"""
        rgb: np.ndarray = result["rgb"]
        h, w = rgb.shape[:2]
        origin_bx = int(result["origin_bx"])
        origin_bz = int(result["origin_bz"])
        biomes: np.ndarray = result["biomes"]
        radius = int(result["radius"])

        if self._hillshade_on and result.get("depth") is not None:
            rgb = _apply_hillshade(rgb, result["depth"])

        img = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
        # 拷贝一份防止 numpy 数组被回收后图像数据悬空
        pm = QPixmap.fromImage(img.copy())

        self._scene.clear()
        self._shade_item = None
        self._grid_item = None
        pix_item = self._scene.addPixmap(pm)
        # 把 (0,0) 世界原点映射到场景 (radius, radius)：
        # 场景坐标 = 世界方块坐标 + radius（1 场景单位 = 1 方块，
        # 采样矩阵按噪声格 1:4 放大到方块尺度）
        pix_item.setScale(4.0)
        pix_item.setPos(-radius, -radius)

        # 区块网格（16 方块一格，半透明白线，可开关）
        if self._grid_on:
            self._grid_item = self._add_chunk_grid(radius)

        # 结构标记（悬停提示 = 结构 + 坐标；点击复制 /tp）
        self._markers = []
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
            label = self._scene.addSimpleText(str(name), QFont("Microsoft YaHei", 9))
            label.setBrush(QBrush(QColor(255, 255, 255)))
            label.setPen(QPen(QColor(0, 0, 0, 200), 2))
            label.setPos(x + _MARKER_R + 2, z - 8)
            label.setZValue(11)

        self._last = dict(result)
        self._fit_view()

    def _add_chunk_grid(self, radius: float):
        """区块网格：覆盖全图的单个路径项，一次画完所有线（宽 0=cosmetic）。"""
        path = QPainterPath()
        step = _CHUNK_GRID_SIZE
        x0 = -radius
        x1 = radius
        y0 = -radius
        y1 = radius
        # 竖线（对齐区块边界：世界坐标 16 的倍数）
        xx = (int(x0) // step) * step
        while xx <= x1:
            path.moveTo(xx, y0)
            path.lineTo(xx, y1)
            xx += step
        zz = (int(y0) // step) * step
        while zz <= y1:
            path.moveTo(x0, zz)
            path.lineTo(x1, zz)
            zz += step
        item = self._scene.addPath(path, QPen(_CHUNK_GRID_COLOR, 0.0))
        item.setZValue(5)
        return item

    def _fit_view(self) -> None:
        """视图适配整张图（渲染完成后调用）。"""
        self.viewMap.fitInView(self._scene.sceneRect(),
                               Qt.AspectRatioMode.KeepAspectRatio)

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
        """右键菜单：山体阴影 / 区块网格开关。"""
        menu = QMenu(self)
        act_shade = menu.addAction("山体阴影")
        act_shade.setCheckable(True)
        act_shade.setChecked(self._hillshade_on)
        act_grid = menu.addAction("区块网格")
        act_grid.setCheckable(True)
        act_grid.setChecked(self._grid_on)
        menu.addSeparator()
        act_fit = menu.addAction("适配视野")
        chosen = menu.exec(global_pos)
        if chosen is act_shade:
            self._toggle_hillshade()
        elif chosen is act_grid:
            self._toggle_grid()
        elif chosen is act_fit:
            self._fit_view()

    def _toggle_hillshade(self) -> None:
        self._hillshade_on = not self._hillshade_on
        self._persist()
        if self._last is not None:
            self._apply_result(self._last)

    def _toggle_grid(self) -> None:
        self._grid_on = not self._grid_on
        self._persist()
        if self._last is not None:
            self._apply_result(self._last)

    def _on_wheel(self, ev) -> bool:
        """滚轮锚点缩放（Ctrl+滚轮留给外层滚动页面）。"""
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return False
        factor = 1.25 if ev.angleDelta().y() > 0 else 0.8
        self.viewMap.scale(factor, factor)
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
            return True
        # 2) 悬停查询：视图坐标 → 场景（方块）坐标 → 像素索引
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
        """视图坐标 → 世界方块坐标（1 场景单位 = 1 方块，原点偏移 radius）。"""
        if self._last is None:
            return None
        sp = self.viewMap.mapToScene(view_pos)
        radius = int(self._last.get("radius", 0))
        return int(sp.x()) - radius, int(sp.y()) - radius

    def _update_hover(self, pos) -> None:
        blk = self._scene_block(pos)
        if blk is None:
            return
        bx, bz = blk
        res = self._last
        origin_bx, origin_bz = int(res["origin_bx"]), int(res["origin_bz"])
        biomes = res["biomes"]
        # 噪声格索引（方块 >> 2），需落在采样矩阵内
        col = (bx - origin_bx) >> 2
        row = (bz - origin_bz) >> 2
        h, w = biomes.shape[:2]
        if not (0 <= row < h and 0 <= col < w):
            self.labelHover.setText(f"X {bx}  Z {bz}")
            return
        bid = int(biomes[row, col])
        self.labelHover.setText(
            f"X {bx}  Z {bz}  |  {biome_cn_name(bid)} (id {bid})")

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
                "hillshade": self._hillshade_on,
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
        if isinstance(data.get("hillshade"), bool):
            self._hillshade_on = data["hillshade"]
        if isinstance(data.get("grid"), bool):
            self._grid_on = data["grid"]
        self._update_struct_menu()

    def save_config(self) -> None:
        """主窗口退出协议（save_all_tools_config）：保存会话。"""
        self._persist()

    def _stop_thread(self) -> None:
        """停止渲染线程（应用退出前调用；重复调用无副作用）。"""
        thread = self._thread
        self._thread = None
        if thread is None:
            return
        try:
            if thread.isRunning():
                thread.request_cancel()
                thread.wait(5000)
        except RuntimeError:
            # 退出阶段 C++ 对象可能已被析构，防御性忽略
            pass

    def closeEvent(self, event) -> None:
        """窗口关闭时停止渲染线程（aboutToQuit 的双保险）。"""
        self._stop_thread()
        super().closeEvent(event)
