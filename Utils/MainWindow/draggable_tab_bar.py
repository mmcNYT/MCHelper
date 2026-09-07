# -*- coding: utf-8 -*-
"""支持拖拽调整 tab 顺序的 QTabBar。

交互（对齐 Chrome / VS Code 的 tab 拖拽习惯）：
- 按住 tab 标签拖动：一枚「标签快照 + 页面缩略快照」拼合的浮动卡
  从标签原位磁吸飞向鼠标（短距离过渡 + 淡入，不瞬移）；到位后
  页面像被拎起来一样跟随鼠标，原标签在栏内隐藏；
- 光标越过相邻标签中点时该标签被「挤走」：从当前位平滑滑入被拖
  tab 空出的槽位（约 90ms ease-out 滑动动画）；
- 浮动卡是独立顶层窗口，拖出 tab 栏/窗口边界也完整可见不裁剪；
- 松手：tab 立即在最终槽位就位（顺序/持久化逻辑不受动画影响），
  浮动卡转为残影从松手位置磁吸飞回槽位并淡出，随后发射
  orderChanged；
- 只按一下没有拖动：保持 Qt 默认的点击切换行为，不受影响。

实现说明：
- 不使用 QDrag/MimeData 的跨控件拖放——tab 重排是控件内部操作，
  自管理拖动状态即可，避免与工具页内部的拖放（附魔卡片拖拽）冲突；
- 拖动阈值用 QApplication.startDragDistance()，与系统拖动手感一致；
- 跟踪被拖 tab 用「缓存索引 + 让位时同步更新」而不是清空/回填标签
  文本来反查：清空文字会让 tab 突然变窄、后续标签左移，既让预计算的
  拖放目标坐标失效，也可能在拖动中途让位时把空文本写进顺序配置；
- 让位判定用「光标越过相邻标签中点」而不是「光标进入别的标签矩形」：
  后者在拖到最右侧空白区时 tabAt 返回 -1，末尾让位会卡住；中点判定
  与 Chrome/VS Code 手感一致，且光标超出标签栏边缘也能正确停到末尾；
- 所有拖动逻辑统一使用控件局部坐标（QMouseEvent.position()）：
  offscreen 平台等场景下合成事件的全局坐标不可靠，用局部坐标
  可让真实交互与 QTest 模拟走同一套坐标体系，行为完全一致；
- 浮动层用独立顶层 QWidget 而不是 paintEvent 画在 tab 栏上：
  画在 tab 栏上会被控件矩形裁剪（拖出即消失），顶层窗口无此限制；
  页面缩略快照用 QWidget.grab() 直接抓取（对隐藏页也能渲染），
  不切换当前页、不触发 currentChanged，对主窗口自适应零扰动；
- 挤走动画的实现：moveTab 是瞬时重排，动画靠「绘制偏移」——
  moveTab 前记录各标签的 x 坐标，重排后布局立即处于最终状态，
  绘制时给被挤标签一个从旧位到新位的插值偏移（ease-out 衰减，
  QTimer 驱动逐帧重绘），视觉上即平滑滑动；动画只影响绘制，
  布局与逻辑（索引/顺序/持久化）从让位那一刻起就是最终状态；
- 拖动/动画期间自绘接管整条标签栏：先填背景再画基线和各标签
  （被拖标签在提起动画完成后跳过），避免上一帧标签像素残留成
  拖影；标签外观走原生样式 CE_TabBarTab，与平时观感一致；
- 提起/放下磁吸动画只影响浮动卡/残影的位置与透明度，不改变
  任何索引、顺序、持久化逻辑：提起动画期间若发生让位（拖得快）
  立即结算钉到鼠标；放下时真实 tab 先就位，残影纯装饰性飞回。
"""

import time

from PySide6.QtCore import QPoint, QRect, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QPen, QPixmap, QPainter, QBrush
from PySide6.QtWidgets import (QApplication, QTabBar, QWidget, QStyle,
                               QStyleOption, QStyleOptionTab)

# 拖动快照的配色（与工具页像素风格一致：深底 + 紫描边）
_DRAG_BG = QColor(30, 27, 40, 235)
_DRAG_BORDER = QColor(120, 88, 200, 235)
_DRAG_TEXT = QColor(235, 235, 235)
_DRAG_RADIUS = 4      # 快照圆角（像素风不宜大圆角）
_DRAG_GAP = 4        # 标签快照与页面快照之间的间距（px）
_DRAG_PAGE_SCALE = 0.18   # 页面快照等比缩放系数
_DRAG_MIN_PAGE_W = 160    # 页面快照最小宽度（px），过小则文字不可辨认
_DRAG_MIN_PAGE_H = 100    # 页面快照最小高度（px）
_DRAG_MAX_PAGE_H = 260    # 页面快照最大高度（px），避免竖屏工具页占满全屏

# 挤走（让位）滑动动画：时长与帧间隔（毫秒）
_SLIDE_DURATION = 90.0
_SLIDE_INTERVAL = 14

# 提起磁吸：浮动卡从标签原位飞向鼠标的时长（毫秒）
_LIFT_DURATION = 110.0
# 放下磁吸：残影从松手位置飞回最终槽位的时长（毫秒）
_DROP_DURATION = 130.0


class _TabDragOverlay(QWidget):
    """拖动时的顶层浮动卡：标签快照 + 页面缩略快照拼合跟随鼠标。

    独立顶层窗口（Qt.Tool + FramelessWindowHint + WindowStaysOnTopHint
    + WindowTransparentForInput）：
    - 不吞事件：鼠标事件继续到达下方真实窗口，拖动状态仍由
      DraggableTabBar 的鼠标事件驱动；
    - 不被 tab 栏/主窗口矩形裁剪，拖出边界完整可见；
    - Qt.Tool + WA_ShowWithoutActivating：显示时不抢主窗口焦点。
    """

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowTransparentForInput | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # 快照内容（由 DraggableTabBar 填充）
        self._pixmaps = []              # [(pixmap, 相对卡片左上角的位置), ...]
        self._content_origin = QPoint() # 内容包围盒原点在窗口内的位置
        self._drag_offset = QPoint()    # 按下点相对标签快照左上角的偏移

    # ---------- 内容与位置 ----------
    def set_content(self, pixmaps: list):
        """设置拼合内容：[(pixmap, 相对标签快照左上角的位置), ...]，
        并按内容总包围盒调整窗口大小"""
        self._pixmaps = pixmaps
        if not pixmaps:
            self.resize(1, 1)
            return
        min_x = min(pos.x() for _, pos in pixmaps)
        min_y = min(pos.y() for _, pos in pixmaps)
        max_x = max(pos.x() + pm.width() / (pm.devicePixelRatio() or 1.0)
                    for pm, pos in pixmaps)
        max_y = max(pos.y() + pm.height() / (pm.devicePixelRatio() or 1.0)
                    for pm, pos in pixmaps)
        self._content_origin = QPoint(-min_x, -min_y)
        self.resize(int(max_x - min_x), int(max_y - min_y))

    def set_drag_offset(self, offset: QPoint):
        """记录按下时鼠标在标签内的相对偏移（浮动卡跟随用）"""
        self._drag_offset = QPoint(offset)

    def move_to(self, global_pos: QPoint):
        """把浮动卡移动到全局坐标位置（保持内容相对鼠标的偏移）"""
        self.move_to_anchor(global_pos - self._drag_offset)

    def move_to_anchor(self, anchor_global: QPoint):
        """按「标签快照左上角应处的全局位置」定位浮动卡
        （提起磁吸动画的插值基准就是该锚点）"""
        self.move(anchor_global - self._content_origin)

    # ---------- 绘制 ----------
    def paintEvent(self, event):
        painter = QPainter(self)
        for pm, pos in self._pixmaps:
            painter.drawPixmap(self._content_origin + pos, pm)
        painter.end()


class _TabDragGhost(QWidget):
    """松手时的磁吸残影：从松手位置飞回最终槽位并同步淡出。

    与 _TabDragOverlay 同款外观；动画自驱动（内部 QTimer 逐帧插值
    位置与透明度，播完自毁），不拦事件、不抢焦点。
    """

    def __init__(self, pixmaps: list, start_top_left_global: QPoint,
                 target_top_left_global: QPoint, duration_ms: float,
                 on_finished=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowTransparentForInput | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._pixmaps = pixmaps

        # 布局逻辑与 _TabDragOverlay.set_content 一致
        min_x = min(pos.x() for _, pos in pixmaps)
        min_y = min(pos.y() for _, pos in pixmaps)
        max_x = max(pos.x() + pm.width() / (pm.devicePixelRatio() or 1.0)
                    for pm, pos in pixmaps)
        max_y = max(pos.y() + pm.height() / (pm.devicePixelRatio() or 1.0)
                    for pm, pos in pixmaps)
        origin = QPoint(-min_x, -min_y)
        self._origin = origin
        self.resize(int(max_x - min_x), int(max_y - min_y))

        # 磁吸飞回：起点=松手位置的标签快照左上角，终点=最终槽位左上角
        self._start_pos = start_top_left_global - origin
        delta = target_top_left_global - start_top_left_global
        self._delta = QPoint(delta.x(), delta.y())
        self._t0 = time.monotonic()
        self._duration = max(0.001, duration_ms / 1000.0)
        self._on_finished = on_finished or (lambda: None)   # 播完回调
        self._timer = QTimer(self)
        self._timer.setInterval(_SLIDE_INTERVAL)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        """动画帧：ease-out 插值位置（起步快收尾缓）+ 线性淡出"""
        progress = min(1.0, (time.monotonic() - self._t0) / self._duration)
        eased = 1.0 - (1.0 - progress) ** 2
        self.move(QPoint(self._start_pos.x() + int(self._delta.x() * eased),
                         self._start_pos.y() + int(self._delta.y() * eased)))
        self.setWindowOpacity(1.0 - progress)
        if progress >= 1.0:
            self._timer.stop()
            self._on_finished()          # 通知宿主把自己从 _live_fades 移除
            self.deleteLater()

    def _on_finished(self):
        """动画播完回调（宿主挂接）：默认无操作"""
        pass

    def paintEvent(self, event):
        painter = QPainter(self)
        for pm, pos in self._pixmaps:
            painter.drawPixmap(self._origin + pos, pm)
        painter.end()


class DraggableTabBar(QTabBar):
    """可拖拽重排 tab 的 QTabBar。

    顺序变化的通知：拖动过程中让位（moveTab）会发射 QTabBar 自带的
    tabMoved，但拖动中途的让位顺序不是最终顺序；本类在拖动结束、
    外观恢复后发射自定义的 orderChanged 信号，外部应连接 orderChanged
    做持久化（tabMoved 留给 Qt 内部机制用）。
    """

    # 拖动结束（外观已恢复）后发射：外部连接它保存最终顺序
    orderChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # 按下状态（点击切换与拖动共用）
        self._press_pos = QPoint()      # 按下时的局部坐标
        self._press_index = -1          # 按下的 tab 索引
        self._drag_active = False       # 是否已超过阈值进入拖动
        # 按下点相对标签快照左上角的偏移（浮动卡跟随用）
        self._drag_offset = QPoint()
        # 被拖 tab 的当前索引（让位 moveTab 后同步更新，避免跟错标签）
        self._drag_index_val = -1
        # 挤走动画状态：{tab 文本: (旧位→新位的像素差, 动画起始时间)}
        # 键用 tab 文本（会话内唯一）——moveTab 后索引会变，文本不变
        self._slide_offsets = {}
        self._slide_timer = None
        # 提起磁吸状态：_lift_start_anchor 为 None 表示不在提起动画中；
        # 动画期间被拖标签仍在栏内绘制（视觉上是「从标签上拎起」）
        self._lift_start_anchor = None
        self._lift_t0 = None
        self._lift_timer = None      # 提起动画驱动计时器（鼠标静止也逐帧推进）
        # 浮动卡（拖动期间创建，结束时转为放下磁吸残影销毁）
        self._overlay = None
        # 淡出/飞回中的残影 {(widget, timer), ...}（退出时统一清理）
        self._live_fades = set()
        # 残影播完回调：从 _live_fades 移除自己。必须同步移除——残影
        # 自毁时 C++ 侧连同内部 QTimer 一起销毁，集合里若残留死引用，
        # 退出清理遍历到已析构的 QTimer 会抛
        # RuntimeError（libshiboken: Internal C++ object already deleted）
        self._ghost_finished = lambda ghost: self._live_fades.discard(
            (ghost, ghost._timer))
        # 程序退出时立即清理残影：放下动画/提起动画未完成时顶层窗口
        # + 运行中的 QTimer 会在 Python 退出阶段被析构 → 原生崩溃
        # （与剪贴板线程同款根因），退出时必须先停干净
        QApplication.instance().aboutToQuit.connect(self._cleanup_fades_on_quit)

    # ---------- 鼠标交互 ----------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            self._press_index = self.tabAt(event.position().toPoint())
            self._drag_active = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.LeftButton
                and self._press_index >= 0
                and not self._drag_active
                and (event.position().toPoint() - self._press_pos).manhattanLength()
                >= QApplication.startDragDistance()):
            self._start_drag(event.position().toPoint())
        if self._drag_active:
            if self._lift_start_anchor is None:
                # 提起动画完成后：浮动卡钉到鼠标、栏内隐藏被拖标签
                self._update_drag(event.position().toPoint())
            else:
                # 提起动画中：推进磁吸飞行；让位发生则立即结算
                self._update_lift(event.position().toPoint())
            return  # 拖动期间不交给父类（避免触发 Qt 内部的点击/移动逻辑）
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        was_dragging = self._drag_active
        self._end_drag()
        if was_dragging:
            return  # 拖动结束：tab 已在让位过程中到达最终位置
        super().mouseReleaseEvent(event)

    # ---------- 提起磁吸动画 ----------
    def _start_lift_timer(self):
        """启动/复用提起动画的驱动计时器（鼠标静止时也逐帧推进）"""
        if self._lift_timer is None:
            self._lift_timer = QTimer(self)
            self._lift_timer.setInterval(_SLIDE_INTERVAL)
            self._lift_timer.timeout.connect(self._on_lift_tick)
        if not self._lift_timer.isActive():
            self._lift_timer.start()

    def _stop_lift_timer(self):
        """停止提起动画计时器（可重复调用）"""
        if self._lift_timer is not None and self._lift_timer.isActive():
            self._lift_timer.stop()

    def _on_lift_tick(self):
        """提起动画帧：鼠标不动时也向当前鼠标位置推进磁吸插值"""
        if self._drag_active and self._lift_start_anchor is not None:
            self._update_lift(self._last_local_pos)
        else:
            self._stop_lift_timer()

    def _finish_lift(self):
        """结束提起动画：浮动卡钉到鼠标（_drag_offset 生效）并隐藏栏内标签

        提起动画只是过渡：浮动卡先用「锚点=标签原位」定位，动画结束时
        把锚点切回鼠标偏移定位，两种定位共用同一坐标基准（标签快照
        左上角），切换不跳变。
        """
        if self._overlay is None:
            self._lift_start_anchor = None
            self._lift_t0 = None
            return
        anchor = self.mapToGlobal(self._last_local_pos) - self._drag_offset
        self._overlay.move_to_anchor(anchor)
        self._overlay.setWindowOpacity(1.0)
        self._lift_start_anchor = None
        self._lift_t0 = None
        self._stop_lift_timer()
        self.update()

    def _update_lift(self, local_pos: QPoint):
        """提起动画帧推进：锚点从标签原位向鼠标位置 ease-out 插值 + 淡入

        途中已越过相邻标签中点（拖得快）则立即结算进入拖动态，
        避免「页面还没拎稳就换位」的错位感。
        """
        self._last_local_pos = QPoint(local_pos)
        # 提起途中就发生让位：跳过剩余动画直接进入拖动态
        target_anchor = self.mapToGlobal(local_pos) - self._drag_offset
        if self._lift_would_swap(local_pos):
            self._finish_lift()
            self._update_drag(local_pos)
            return
        progress = min(1.0,
                       (time.monotonic() - self._lift_t0) / (_LIFT_DURATION / 1000.0))
        eased = 1.0 - (1.0 - progress) ** 2
        anchor = QPoint(self._lift_start_anchor.x()
                        + int(round((target_anchor.x() - self._lift_start_anchor.x()) * eased)),
                        self._lift_start_anchor.y()
                        + int(round((target_anchor.y() - self._lift_start_anchor.y()) * eased)))
        self._overlay.move_to_anchor(anchor)
        # 前 30% 进度淡入（0→1），之后保持不透明
        self._overlay.setWindowOpacity(min(1.0, progress / 0.3))
        if progress >= 1.0:
            self._finish_lift()

    def _lift_would_swap(self, local_pos: QPoint) -> bool:
        """提起动画中判断光标是否已越过相邻标签中点（用于提前结算）"""
        idx = self._drag_index_val
        if idx < 0:
            return False
        own_center = self.tabRect(idx).center().x()
        if (local_pos.x() > own_center
                and idx + 1 < self.count()
                and local_pos.x() >= self.tabRect(idx + 1).center().x()):
            return True
        if (local_pos.x() < own_center
                and idx - 1 >= 0
                and local_pos.x() <= self.tabRect(idx - 1).center().x()):
            return True
        return False

    # ---------- 挤走动画（绘制偏移方案） ----------
    def _prune_slide_offsets(self):
        """清理已播完的动画偏移（超过时长即播完），有清理则重绘"""
        if not self._slide_offsets:
            return
        now = time.monotonic()
        done = [k for k, (_, t0) in self._slide_offsets.items()
                if (now - t0) >= _SLIDE_DURATION / 1000.0]
        for k in done:
            del self._slide_offsets[k]
        if done:
            self.update()

    def _slide_offset_for(self, index: int) -> int:
        """某 index 标签当前的动画偏移量（未在动画中返回 0）。

        只读不清理（清理由 _prune_slide_offsets 统一做，paint 路径
        中触发 update() 会重入）。
        """
        entry = self._slide_offsets.get(self.tabText(index))
        if entry is None:
            return 0
        dx, t0 = entry
        progress = min(1.0, (time.monotonic() - t0) / (_SLIDE_DURATION / 1000.0))
        # ease-out：起步快、收尾缓（Chrome 式手感）
        eased = 1.0 - (1.0 - progress) ** 2
        return int(round(dx * (1.0 - eased)))

    def _start_slide_timer(self):
        """启动/复用滑动动画的驱动计时器：动画播完自动停止"""
        if self._slide_timer is None:
            self._slide_timer = QTimer(self)
            self._slide_timer.setInterval(_SLIDE_INTERVAL)
            self._slide_timer.timeout.connect(self._on_slide_tick)
        if not self._slide_timer.isActive():
            self._slide_timer.start()

    def _on_slide_tick(self):
        """动画帧：重绘当前插值状态；全部播完则停止计时器"""
        self._prune_slide_offsets()
        self.update()
        if not self._slide_offsets:
            self._slide_timer.stop()

    def _settle_slides(self):
        """立即结算所有滑动动画（松手时用）：清偏移、停计时器"""
        self._slide_offsets.clear()
        if self._slide_timer is not None and self._slide_timer.isActive():
            self._slide_timer.stop()

    # ---------- 绘制 ----------
    def paintEvent(self, event):
        if not (self._drag_active or self._slide_offsets):
            super().paintEvent(event)
            return
        # 拖动/动画期间自绘接管整条标签栏：必须整条重绘，否则上一帧
        # 标签像素残留成拖影。背景用 palette 窗口色（QTabBar 本身透明，
        # 其后是 QTabWidget 窗格的同色背景），基线走原生样式。
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        base_opt = QStyleOption()
        base_opt.initFrom(self)
        self.style().drawPrimitive(QStyle.PE_FrameTabBarBase, base_opt,
                                   painter, self)
        # 逐标签绘制：被拖标签在提起动画完成后跳过（由浮动卡代表，
        # 栏内留出空槽；提起动画期间标签仍在栏内，「从标签上拎起」），
        # 动画中的标签按插值偏移平移绘制，其余按最终布局绘制
        for i in range(self.count()):
            if (i == self._drag_index_val
                    and self._drag_active
                    and self._lift_start_anchor is None):
                continue
            offset = self._slide_offset_for(i)
            rect = self.tabRect(i)
            if offset:
                rect = rect.translated(offset, 0)
            self._paint_tab_at(painter, i, rect)
        painter.end()

    def _paint_tab_at(self, painter, index: int, rect: QRect):
        """用 QTabBar 原生样式在指定矩形绘制某个标签的外观
        （QStyleOptionTab.rect 决定绘制位置，平移矩形即平移标签）"""
        opt = QStyleOptionTab()
        self.initStyleOption(opt, index)
        opt.rect = QRect(rect)
        self.style().drawControl(QStyle.CE_TabBarTab, opt, painter, self)

    # ---------- 拖动流程 ----------
    def _start_drag(self, local_pos: QPoint):
        """超过阈值：抓页面快照、创建浮动卡，进入拖动态"""
        self._drag_active = True
        self._drag_index_val = self._press_index

        # 按原标签矩形渲染标签快照
        rect = self.tabRect(self._press_index)
        label_pix = self._render_drag_label(
            self.tabText(self._press_index), rect)
        # 按下点在标签内的相对位置（浮动卡保持同样的相对位置跟随）
        self._drag_offset = local_pos - rect.topLeft()

        # 抓被拖 tab 的页面快照：QWidget.grab() 对隐藏页也能渲染，
        # 不需要切换当前页，也就不会触发 currentChanged（主窗口的
        # 自适应缩放等监听零扰动）
        page_pix = None
        tab_widget = self._tab_widget()
        if tab_widget is not None:
            page_widget = tab_widget.widget(self._press_index)
            if page_widget is not None:
                page_pix = page_widget.grab()

        # 组装浮动卡内容：标签快照 + 页面缩略快照拼合（页面像被拎起来）
        content = [(label_pix, QPoint(0, 0))]
        scaled = self._scale_page_pixmap(page_pix)
        if scaled is not None:
            content.append(
                (scaled, QPoint(0, rect.height() + _DRAG_GAP)))

        self._overlay = _TabDragOverlay()
        self._overlay.set_content(content)
        self._overlay.set_drag_offset(self._drag_offset)
        # 提起磁吸：浮动卡先精确落在标签原位（透明），随后逐帧飞向
        # 鼠标并淡入；期间栏内标签仍绘制，视觉上是「从标签上拎起」
        self._lift_start_anchor = self.mapToGlobal(rect.topLeft())
        self._lift_t0 = time.monotonic()
        self._last_local_pos = QPoint(local_pos)
        self._overlay.setWindowOpacity(0.0)
        self._overlay.move_to_anchor(self._lift_start_anchor)
        self._overlay.show()
        self._start_lift_timer()

        self.update()

    def _update_drag(self, local_pos: QPoint):
        """拖动跟随（提起动画完成后）：浮动卡随鼠标移动；光标越过相邻
        标签中点时让位。

        让位用 moveTab（会发射 tabMoved），移完把缓存索引同步到新位置；
        被挤标签通过绘制偏移播放滑入动画。
        """
        moved = True
        while moved:
            moved = False
            idx = self._drag_index_val
            if idx < 0:
                break
            own_center = self.tabRect(idx).center().x()
            # 向右拖：越过右侧相邻标签的中点 → 让位
            if (local_pos.x() > own_center
                    and idx + 1 < self.count()
                    and local_pos.x() >= self.tabRect(idx + 1).center().x()):
                self._do_swap(idx, idx + 1)
                self._drag_index_val = idx + 1
                moved = True
            # 向左拖：越过左侧相邻标签的中点 → 让位
            elif (local_pos.x() < own_center
                    and idx - 1 >= 0
                    and local_pos.x() <= self.tabRect(idx - 1).center().x()):
                self._do_swap(idx, idx - 1)
                self._drag_index_val = idx - 1
                moved = True
        # 浮动卡跟随鼠标（用全局坐标；offscreen 下同源换算，无偏差）
        if self._overlay is not None:
            self._overlay.move_to(self.mapToGlobal(local_pos))
        self.update()

    def _do_swap(self, from_idx: int, to_idx: int):
        """让位核心：记录让位前布局 → moveTab → 给被挤标签登记滑动动画。

        一次相邻交换只改变被挤标签的槽位（被拖标签由浮动卡代表不参与
        滑动），其余标签位置不变。
        """
        dragged_text = self.tabText(self._drag_index_val)
        before = {self.tabText(i): self.tabRect(i).x()
                  for i in range(self.count())}
        self.moveTab(from_idx, to_idx)
        now = time.monotonic()
        for i in range(self.count()):
            text = self.tabText(i)
            if text == dragged_text:
                continue  # 被拖标签由浮动卡代替，不参与滑动
            dx = self.tabRect(i).x() - before.get(text, self.tabRect(i).x())
            if dx != 0:
                self._slide_offsets[text] = (dx, now)
        if self._slide_offsets:
            self._start_slide_timer()

    def _end_drag(self):
        """松手：真实 tab 立即在最终槽位就位（顺序/持久化不受影响），
        浮动卡转为磁吸残影从松手位置飞回最终槽位并淡出，随后通知
        外部（orderChanged）。播了一半的挤走动画立即结算。

        放下磁吸的目标位置：被拖 tab 最终槽位的左上角（全局）。
        标签快照对齐槽位左上角后，页面缩略部分自然落在标签下方。
        """
        if self._overlay is not None:
            # 最终槽位矩形（拖动状态清理前取，此时布局已是最终顺序）
            target_rect = self.tabRect(self._drag_index_val)
            target_top_left = (self.mapToGlobal(target_rect.topLeft())
                               if self._drag_index_val >= 0
                               else self._overlay.pos() + self._overlay._content_origin)
            # 磁吸残影：从浮动卡当前位置飞回槽位并同步淡出（自驱动，
            # 播完自毁）；原浮动卡立即销毁，避免遮挡
            ghost = _TabDragGhost(
                [(pm, pos) for pm, pos in self._overlay._pixmaps],
                self._overlay.pos() + self._overlay._content_origin,
                target_top_left, _DROP_DURATION)
            # 播完回调挂在构造后（lambda 默认参数求值时 ghost 已存在，
            # 不能写进构造参数——那时变量还没赋值）
            ghost._on_finished = lambda g=ghost: self._ghost_finished(g)
            ghost.show()
            self._live_fades.add((ghost, ghost._timer))
            self._overlay.deleteLater()
            self._overlay = None
        self._lift_start_anchor = None
        self._lift_t0 = None
        self._stop_lift_timer()
        self._settle_slides()
        self._drag_active = False
        self._press_index = -1
        self._drag_index_val = -1
        self.update()
        self.orderChanged.emit()

    def _cleanup_fades_on_quit(self):
        """程序退出时立即清理提起动画状态、浮动卡与放下磁吸残影
        （停计时器 + 删窗口），避免退出阶段析构运行中的顶层窗口
        与 QTimer 导致原生崩溃（与剪贴板线程同款根因）

        遍历/停止时逐项防御 RuntimeError：若某残影已自行播完销毁
        （C++ 对象连同内部 QTimer 已删）而集合引用尚未同步，停止
        已析构对象会抛 libshiboken 异常。正常路径由 _ghost_finished
        同步移除保证不会发生，此处只作兑底。
        """
        self._settle_slides()
        self._stop_lift_timer()
        self._lift_start_anchor = None
        self._lift_t0 = None
        if self._overlay is not None:
            self._overlay.deleteLater()
            self._overlay = None
        for widget, timer in list(self._live_fades):
            try:
                timer.stop()
            except RuntimeError:
                pass  # C++ 对象已析构，无需再停
            try:
                widget.deleteLater()
            except RuntimeError:
                pass  # C++ 对象已析构，无需再删
        self._live_fades.clear()

    def _tab_widget(self):
        """所属 QTabWidget（QTabBar.parentWidget()）"""
        return self.parentWidget()

    def _scale_page_pixmap(self, page_pix):
        """把页面快照等比缩放到浮动卡用的尺寸（带上下限），
        画上深底描边卡片；page_pix 为 None 时返回 None（无页面快照）"""
        if page_pix is None or page_pix.width() <= 0 or page_pix.height() <= 0:
            return None
        sw = page_pix.width() * _DRAG_PAGE_SCALE
        sh = page_pix.height() * _DRAG_PAGE_SCALE
        # 上限：高度不超过 _DRAG_MAX_PAGE_H（等比再缩）
        if sh > _DRAG_MAX_PAGE_H:
            sw *= _DRAG_MAX_PAGE_H / sh
            sh = _DRAG_MAX_PAGE_H
        # 下限：宽度过小则等比放大到最小宽
        if sw < _DRAG_MIN_PAGE_W:
            sh *= _DRAG_MIN_PAGE_W / sw
            sw = _DRAG_MIN_PAGE_W
        # 高度下限（缩放宽后重算）
        if sh < _DRAG_MIN_PAGE_H:
            sw *= _DRAG_MIN_PAGE_H / sh
            sh = _DRAG_MIN_PAGE_H
        w, h = int(sw), int(sh)

        out = QPixmap(int(w * (page_pix.devicePixelRatio() or 1.0)),
                      int(h * (page_pix.devicePixelRatio() or 1.0)))
        out.setDevicePixelRatio(page_pix.devicePixelRatio() or 1.0)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        # 卡底：深底 + 紫描边圆角矩形（与标签快照同款配色）
        painter.setPen(QPen(_DRAG_BORDER, 2))
        painter.setBrush(QBrush(QColor(30, 27, 40, 235)))
        painter.drawRoundedRect(1, 1, w - 2, h - 2, _DRAG_RADIUS, _DRAG_RADIUS)
        # 页面快照按卡内缩 4px 绘制
        painter.drawPixmap(QRect(4, 4, w - 8, h - 8), page_pix)
        painter.end()
        return out

    def current_order(self) -> list:
        """当前 tab 文本顺序（调试/测试辅助；外部持久化建议用主窗口的
        _save_tab_order，它按 widget().tool_name() 取名更稳健）"""
        return [self.tabText(i) for i in range(self.count())]

    # ---------- 标签快照渲染 ----------
    def _render_drag_label(self, text: str, rect: QRect) -> QPixmap:
        """渲染标签快照：深底 + 紫描边 + 原文字（按 dpr 提升分辨率避免模糊）"""
        dpr = self.devicePixelRatioF() or 1.0
        pix = QPixmap(int(rect.width() * dpr), int(rect.height() * dpr))
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.transparent)

        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # 背景圆角矩形（略缩 1px 避免贴边裁切描边）
        body = QRect(1, 1, rect.width() - 2, rect.height() - 2)
        painter.setPen(QPen(_DRAG_BORDER, 2))
        painter.setBrush(_DRAG_BG)
        painter.drawRoundedRect(body, _DRAG_RADIUS, _DRAG_RADIUS)
        # 文字（用控件当前字体，视觉与标签一致）
        painter.setPen(_DRAG_TEXT)
        painter.setFont(self.font())
        painter.drawText(body, Qt.AlignCenter, text)
        painter.end()
        return pix
