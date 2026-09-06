# -*- coding: utf-8 -*-
"""支持拖拽调整 tab 顺序的 QTabBar。

交互（对齐 Chrome / VS Code 的 tab 拖拽习惯）：
- 按住 tab 标签拖动：跟随一枚深底紫描边的半透明标签快照，
  其余标签在拖动经过时实时左右让位；
- 松手：tab 停在最终位置，随后发射 orderChanged（外部据此持久化）；
- 只按一下没有拖动：保持 Qt 默认的点击切换行为，不受影响。

实现说明：
- 不使用 QDrag/MimeData 的跨控件拖放——tab 重排是控件内部操作，
  自管理拖动状态即可，避免与工具页内部的拖放（附魔卡片拖拽）冲突；
- 拖动阈值用 QApplication.startDragDistance()，与系统拖动手感一致；
- 跟踪被拖 tab 用「缓存索引 + 让位时同步更新」而不是清空/回填标签
  文本来反查：清空文字会让 tab 突然变窄、后续标签左移，既让预计算的
  拖放目标坐标失效，也可能在拖动中途把空文本写进顺序配置；
- 让位判定用「光标越过相邻标签中点」而不是「光标进入别的标签矩形」：
  后者在拖到最右侧空白区时 tabAt 返回 -1，末尾让位会卡住；中点判定
  与 Chrome/VS Code 手感一致，且光标超出标签栏边缘也能正确停到末尾；
- 所有拖动逻辑统一使用控件局部坐标（QMouseEvent.position()）：
  offscreen 平台等场景下合成事件的全局坐标不可靠，用局部坐标
  可让真实交互与 QTest 模拟走同一套坐标体系，行为完全一致。
"""

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPen, QPixmap, QPainter
from PySide6.QtWidgets import QApplication, QTabBar

# 拖动快照的配色（与工具页像素风格一致：深底 + 紫描边）
_DRAG_BG = QColor(30, 27, 40, 235)
_DRAG_BORDER = QColor(120, 88, 200, 235)
_DRAG_TEXT = QColor(235, 235, 235)
_DRAG_RADIUS = 4  # 快照圆角（像素风不宜大圆角）


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
        # 拖动快照与跟随位置（局部坐标）
        self._drag_pixmap = None
        self._drag_offset = QPoint()    # 按下点相对快照左上角的偏移
        self._drag_current_pos = QPoint()  # 快照左上角（局部坐标）
        # 被拖 tab 的当前索引（让位 moveTab 后同步更新，避免跟错标签）
        self._drag_index_val = -1
        # 被拖 tab 的原始外观（拖动期间保持原样，不清空文字）
        self._saved_icon = None

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
            self._update_drag(event.position().toPoint())
            return  # 拖动期间不交给父类（避免触发 Qt 内部的点击/移动逻辑）
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        was_dragging = self._drag_active
        self._end_drag()
        if was_dragging:
            return  # 拖动结束：tab 已在让位过程中到达最终位置
        super().mouseReleaseEvent(event)

    # ---------- 拖动流程 ----------
    def _start_drag(self, local_pos: QPoint):
        """超过阈值：生成拖动快照，进入拖动态（原标签保持原样）"""
        self._drag_active = True
        self._drag_index_val = self._press_index
        # 按原标签矩形渲染快照
        rect = self.tabRect(self._press_index)
        self._drag_pixmap = self._render_drag_label(
            self.tabText(self._press_index), rect)
        # 按下点在标签内的相对位置 → 快照跟随鼠标时保持同样的相对位置
        self._drag_offset = local_pos - rect.topLeft()
        self._drag_current_pos = local_pos - self._drag_offset
        self.update()

    def _update_drag(self, local_pos: QPoint):
        """拖动跟随：快照随鼠标移动；光标越过相邻标签中点时实时让位。

        让位用 moveTab（会发射 tabMoved），移完把缓存索引同步到新位置。
        用 while 循环连续让位：一次鼠标事件跨过多个标签（快速拖动）
        也能一次到位。
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
                self.moveTab(idx, idx + 1)
                self._drag_index_val = idx + 1
                moved = True
            # 向左拖：越过左侧相邻标签的中点 → 让位
            elif (local_pos.x() < own_center
                    and idx - 1 >= 0
                    and local_pos.x() <= self.tabRect(idx - 1).center().x()):
                self.moveTab(idx, idx - 1)
                self._drag_index_val = idx - 1
                moved = True
        # 快照跟随鼠标
        self._drag_current_pos = local_pos - self._drag_offset
        self.update()

    def _end_drag(self):
        """松手：清空拖动状态并通知外部（顺序已定，外部可安全持久化）"""
        self._drag_active = False
        self._press_index = -1
        self._drag_index_val = -1
        self._drag_pixmap = None
        self.update()
        self.orderChanged.emit()

    def current_order(self) -> list:
        """当前 tab 文本顺序（调试/测试辅助；外部持久化建议用主窗口的
        _save_tab_order，它按 widget().tool_name() 取名更稳健）"""
        return [self.tabText(i) for i in range(self.count())]

    # ---------- 拖动快照渲染 ----------
    def _render_drag_label(self, text: str, rect: QRect) -> QPixmap:
        """渲染拖动快照：深底 + 紫描边 + 原文字（按 dpr 提升分辨率避免模糊）"""
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

    # ---------- 绘制拖动快照 ----------
    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drag_active and self._drag_pixmap is not None:
            painter = QPainter(self)
            painter.drawPixmap(self._drag_current_pos, self._drag_pixmap)
            painter.end()
