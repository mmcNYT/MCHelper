# utils/drop_list_widget.py
# 已选附魔列表控件：显示用户拖入的附魔，支持拖入添加，Del键/×图标两种方式删除
from PySide6.QtWidgets import QListWidget, QStyledItemDelegate, QStyleOptionViewItem
from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtGui import QPainter, QColor, QPen

class CloseButtonDelegate(QStyledItemDelegate):
    """在列表项右侧绘制 × 删除图标的委托

    - 默认绘制灰色 ×，悬停行高亮为红色圆底 + 白色 ×（悬停状态由控件层通过 set_hover_row 同步）
    - 点击命中判定在 DropListWidget.mousePressEvent 中处理（见 _hit_close_icon）
    """

    MARGIN = 12      # 图标与项右边缘的距离
    ICON_SIZE = 10   # 图标边长（14px 缩小 25% 取整）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover_row = -1  # 当前悬停的行号（-1 表示无）

    def set_hover_row(self, row: int) -> bool:
        """更新悬停行号，返回是否有变化（供控件层调用）"""
        if self._hover_row == row:
            return False
        self._hover_row = row
        return True

    def _icon_rect(self, option: QStyleOptionViewItem) -> QRect:
        """计算 × 图标的绘制区域（项右侧居中）"""
        s = self.ICON_SIZE
        return QRect(option.rect.right() - self.MARGIN - s,
                     option.rect.top() + (option.rect.height() - s) // 2,
                     s, s)

    def paint(self, painter, option, index):
        """先绘制标准项内容，再在右侧叠加 × 图标"""
        # 悬停状态变化时由控件层 setHoverRow 通知，这里只负责绘制
        super().paint(painter, option, index)
        rect = self._icon_rect(option)
        hovered = (index.row() == self._hover_row)
        if hovered:
            # 悬停高亮：红色实心圆底 + 白色 ×
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(232, 17, 35, 255))
            painter.drawEllipse(rect.adjusted(-3, -3, 3, 3))
            painter.setPen(QPen(QColor(255, 255, 255, 230), 2))
        else:
            # 默认：灰色 ×
            painter.setPen(QPen(QColor(160, 160, 160, 220), 2))
        painter.drawLine(rect.left(), rect.top(), rect.right(), rect.bottom())
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.top())


class DropListWidget(QListWidget):
    """
    可拖入的列表控件（自身项不可拖拽）：
    - 拖入：从下方附魔列表拖拽进来，发射 dropped 信号。
    - 删除（两种方式）：Del 或 Backspace 键 / 点击项右侧 × 图标，均发射 removed 信号。

    使用场景：
    - 在 ChooseItemsWindow（物品选择窗口）中作为"已选附魔列表"（chosenEnchantmentList）
    - 下方各分类附魔列表（EnchantListWidget）中的附魔可拖入本列表参与计算
    """
    dropped = Signal(str, int)  # 拖入成功信号，参数：(附魔ID, 等级)
    removed = Signal(str)       # 移除信号（Del/Backspace 键或 × 图标删除），参数：附魔ID

    def __init__(self, parent=None):
        """初始化已选附魔列表控件，开启拖放功能"""
        super().__init__(parent)
        # 1. 开启拖放接收：只接收外部拖入，自身项不可拖拽（拖拽删除已移除）
        self.setAcceptDrops(True)          # 接受拖入操作
        self.setDropIndicatorShown(True)   # 显示拖放位置指示线
        self.setContextMenuPolicy(Qt.NoContextMenu)  # 禁用右键菜单，防止干扰拖放

        # 2. 挂载 × 删除图标委托
        self._close_delegate = CloseButtonDelegate(self)
        self.setItemDelegate(self._close_delegate)
        self.setMouseTracking(True)  # 悬停高亮需要追踪鼠标移动

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
        """松开鼠标完成拖放时触发：处理来自下方附魔列表的拖入"""
        if not event.mimeData().hasText():
            event.ignore()
            return

        # 外部拖入（来自下方附魔列表），解析文本数据并发射信号
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

    # ---------- 删除操作（两种方式共用） ----------
    def _remove_item(self, item):
        """从列表中移除指定项并发射 removed 信号（Del 键 / × 图标删除 共用）"""
        if not item:
            return
        row = self.row(item)
        if row < 0:
            return
        removed_id = item.data(Qt.UserRole)
        self.takeItem(row)
        if removed_id:
            self.removed.emit(removed_id)

    def keyPressEvent(self, event):
        """Del/Backspace 键删除当前选中项"""
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            item = self.currentItem()
            if item:
                self._remove_item(item)
            return  # 消费按键，不传给父类（避免触发其他默认行为）
        super().keyPressEvent(event)

    # ---------- 鼠标事件（× 图标点击删除 + 悬停高亮） ----------
    def mousePressEvent(self, event):
        """鼠标按下时触发：若命中 × 图标区域则直接删除该项，其余交给父类（选中项切换）"""
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item and self._hit_close_icon(item, event.pos()):
                self._remove_item(item)
                return  # 点击了 × 图标，不再触发选中
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """鼠标移动时触发：仅更新 × 图标悬停高亮（自身项不可拖拽，不启动 QDrag）"""
        if not (event.buttons() & Qt.LeftButton):
            self._update_hover_row(event.pos())
            return
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        """鼠标离开控件时清除悬停高亮"""
        if self._close_delegate.set_hover_row(-1):
            self.viewport().update()  # 行号变化才重绘
        super().leaveEvent(event)

    # ---------- × 图标辅助方法 ----------
    def _hit_close_icon(self, item, pos) -> bool:
        """判断鼠标位置是否落在某项右侧的 × 图标区域内"""
        opt = QStyleOptionViewItem()
        opt.rect = self.visualItemRect(item)
        icon_rect = self._close_delegate._icon_rect(opt)
        # 宽容度：允许图标周围 6px 的误触范围
        return icon_rect.adjusted(-6, -6, 6, 6).contains(pos)

    def _update_hover_row(self, pos):
        """更新悬停高亮行，变化时触发重绘"""
        item = self.itemAt(pos)
        row = self.row(item) if item else -1
        if self._close_delegate.set_hover_row(row):
            self.viewport().update()  # 行号变化才重绘，避免频繁刷新
