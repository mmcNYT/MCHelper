# utils/drop_list_widget.py
# 已选附魔列表控件：显示用户拖入的附魔，支持拖入添加、拖出删除
from PySide6.QtWidgets import QListWidget, QApplication
from PySide6.QtCore import Qt, QMimeData, QPoint, Signal
from PySide6.QtGui import QDrag, QPixmap, QPainter, QColor, QPen, QFont

class DropListWidget(QListWidget):
    """
    可拖入/拖出的列表控件：
    - 拖入：从下方附魔列表拖拽进来，发射 dropped 信号。
    - 拖出：将自身项拖拽到空白区域，删除该项。

    使用场景：
    - 在 ChooseItemsWindow（物品选择窗口）中作为"已选附魔列表"（chosenEnchantmentList）
    - 下方各分类附魔列表（EnchantListWidget）中的附魔可拖入本列表参与计算
    - 拖拽本列表中的项到窗口空白区域即可移除该附魔
    """
    dropped = Signal(str, int)  # 拖入成功信号，参数：(附魔ID, 等级)
    removed = Signal(str)       # 拖出删除/移除信号，参数：附魔ID

    def __init__(self, parent=None):
        """初始化已选附魔列表控件，开启拖放功能"""
        super().__init__(parent)
        # 1. 开启拖放功能：允许接收外部拖入，也允许自身项被拖出
        self.setAcceptDrops(True)          # 接受拖入操作
        self.setDragEnabled(True)          # 允许启动拖拽（拖出删除）
        self.setDefaultDropAction(Qt.CopyAction)  # 默认拖放动作为"复制"
        self.setDropIndicatorShown(True)   # 显示拖放位置指示线
        self.setContextMenuPolicy(Qt.NoContextMenu)  # 禁用右键菜单，防止干扰拖放

        # 2. 初始化拖拽状态记录变量
        self._drag_start_pos = QPoint()  # 鼠标按下时的起始位置（用于判断拖拽距离）
        self._drag_item = None           # 正在被拖拽的列表项（用于拖出后删除）
        self._is_dragging = False        # 当前是否处于拖拽过程中的标志

    # ---------- 拖入处理 ----------
    def dragEnterEvent(self, event):
        """拖拽进入本控件区域时触发：只接受携带文本数据的拖拽（附魔数据格式为 "附魔ID:等级"）"""
        if event.mimeData().hasText():
            event.setDropAction(Qt.CopyAction)
            event.accept()  # 接受该拖拽
        else:
            event.ignore()  # 无文本数据则拒绝，鼠标显示禁止符号

    def dragMoveEvent(self, event):
        """拖拽在本控件区域内移动时触发：持续接受带文本的拖拽，防止鼠标显示禁止符号"""
        # 接受所有带文本的拖拽，防止鼠标显示禁止符号
        if event.mimeData().hasText():
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """松开鼠标完成拖放时触发：区分"自身项的移动删除"和"外部附魔的拖入"两种情况"""
        if not event.mimeData().hasText():
            event.ignore()
            return

        # 情况一：如果拖拽来自自身（即拖出后落在自己身上），删除该项
        if event.source() is self:
            if self._drag_item:
                row = self.row(self._drag_item)
                if row >= 0:
                    removed_id = self._drag_item.data(Qt.UserRole)  # 记录被移除的附魔 ID
                    self.takeItem(row)  # 从列表中移除该项
                    if removed_id:
                        self.removed.emit(removed_id)  # 通知外部：该附魔已被移除
                self._drag_item = None
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return

        # 情况二：外部拖入（来自下方附魔列表），解析文本数据并发射信号
        data = event.mimeData().text()
        try:
            enchant_id, level_str = data.split(":")  # 解析 "附魔ID:等级" 格式
            level = int(level_str)
            # 发射 dropped 信号，由 ChooseItemsWindow.on_enchant_dropped 处理
            # （实际添加列表项的逻辑在槽函数中完成，如查重、等级取较高等）
            self.dropped.emit(enchant_id, level)
            event.setDropAction(Qt.CopyAction)
            event.accept()
        except ValueError:
            # 文本格式不合法（缺少 ":" 或等级不是数字），拒绝本次拖放
            event.ignore()

    # ---------- 拖出处理（启动拖拽） ----------
    def mousePressEvent(self, event):
        """鼠标按下时触发：记录按下的起始位置和当前项，为后续拖拽判断做准备"""
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()  # 记录起始位置（用于计算拖拽距离）
            self._drag_item = self.currentItem()  # 记录当前选中项（可能是被拖出的项）
            self._is_dragging = False
        super().mousePressEvent(event)  # 保留父类的默认行为（如选中项切换）

    def mouseMoveEvent(self, event):
        """鼠标按住移动时触发：超过系统拖拽阈值后启动 QDrag 拖拽，实现拖出删除"""
        # 未按住左键直接返回
        if not (event.buttons() & Qt.LeftButton):
            return
        # 移动距离小于系统定义的拖拽阈值（startDragDistance），视为普通点击不触发拖拽
        if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return

        item = self._drag_item
        if not item:
            return

        # 从列表项的 UserRole 中取出附魔数据（由 on_enchant_dropped 槽函数存入）
        enchant_id = item.data(Qt.UserRole)        # 附魔 ID
        level = item.data(Qt.UserRole + 1)         # 当前等级
        if not enchant_id:
            return

        # 生成拖拽图标（附魔名称标签）
        pixmap = self._create_drag_pixmap(item.text())
        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(f"{enchant_id}:{level}")  # 拖拽数据格式："附魔ID:等级"
        drag.setMimeData(mime_data)
        drag.setPixmap(pixmap)                 # 设置拖拽时跟随鼠标的图标
        drag.setHotSpot(pixmap.rect().center())  # 热点设为图标中心（鼠标指向的位置）

        # ---- 设置自定义光标：拖到无效区域时显示删除图标（叉号） ----
        # 绘制一个 32x32 的红色叉号作为"拖到无效区域"时的光标，提示用户松手即可删除
        cursor_pixmap = QPixmap(32, 32)
        cursor_pixmap.fill(Qt.transparent)
        painter = QPainter(cursor_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor(255, 0, 0, 200))
        painter.setFont(QFont("Arial", 24, QFont.Bold))
        painter.drawText(cursor_pixmap.rect(), Qt.AlignCenter, "✕")
        painter.end()
        drag.setDragCursor(cursor_pixmap, Qt.IgnoreAction)
        # -------------------------------------------------------------

        self._is_dragging = True
        # 执行拖拽（阻塞直到松开鼠标），允许 Copy 和 Move 动作，默认 Copy
        result = drag.exec_(Qt.CopyAction | Qt.MoveAction, Qt.CopyAction)

        # 如果拖拽被忽略（没有目标接受，即拖到了空白区域），删除该项 —— 拖出即删除
        if result == Qt.IgnoreAction:
            if self._drag_item:
                row = self.row(self._drag_item)
                if row >= 0:
                    removed_id = self._drag_item.data(Qt.UserRole)  # 记录被移除的附魔 ID
                    self.takeItem(row)
                    if removed_id:
                        self.removed.emit(removed_id)  # 通知外部：该附魔已被移除
                self._drag_item = None

        self._is_dragging = False

    def mouseReleaseEvent(self, event):
        """鼠标松开时触发：若刚结束一次拖拽则清理状态，否则恢复父类默认行为"""
        if self._is_dragging:
            # 拖拽刚结束，清理拖拽状态，不再让父类处理本次释放事件
            self._is_dragging = False
            self._drag_item = None
            return
        super().mouseReleaseEvent(event)

    def _create_drag_pixmap(self, text):
        """生成拖拽时跟随的附魔标签图标

        功能说明：
        - 根据附魔名称文本绘制一个深色圆角标签图（用于拖拽时的视觉反馈）
        - 图标宽度随文本长度自适应，高度固定 30px
        - 返回绘制的 QPixmap 对象

        参数：
            text: 显示在标签上的文本（通常为 "附魔名 (等级 N)"）

        返回：
            pixmap: 深色圆角背景 + 白色居中文字的 QPixmap
        """
        font = QFont("Arial", 10)
        width = max(120, len(text) * 10 + 30)  # 宽度至少 120px，按字符数自适应扩展
        height = 30
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.transparent)  # 背景透明（只有圆角矩形部分可见）

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)  # 抗锯齿，圆角更平滑

        # 绘制深色半透明圆角背景 + 浅色描边
        painter.setBrush(QColor(40, 40, 40, 220))
        painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
        painter.drawRoundedRect(0, 0, width-1, height-1, 8, 8)  # 圆角半径 8px

        # 绘制白色居中文本
        painter.setPen(Qt.white)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, text)

        painter.end()
        return pixmap
