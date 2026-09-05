from PySide6.QtWidgets import QListWidget, QApplication
from PySide6.QtCore import Qt, QMimeData, QPoint, Signal, QRect
from PySide6.QtGui import QDrag, QPixmap, QPainter, QColor, QPen, QFont


def _is_item_disabled(item) -> bool:
    """判断列表项是否处于禁用状态（无 ItemIsEnabled 标志）"""
    return not (item.flags() & Qt.ItemIsEnabled)


class EnchantListWidget(QListWidget):
    """可点击增减等级、可拖拽的附魔列表"""
    levelChanged = Signal(str, int)  # (enchant_id, new_level)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self._drag_start_pos = QPoint()
        self._pressed_item = None  # 鼠标按下位置的项（可能与 currentItem 不同：禁用项不会被选中）

    def mousePressEvent(self, event):
        # 记录按下位置的项：禁用项不会被选中，currentItem 会停留在旧项上，
        # 因此必须用 itemAt 判断实际按在哪个项上，避免误拖/误改旧项
        self._pressed_item = self.itemAt(event.pos())
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return

        item = self._pressed_item
        if not item:
            return
        # 禁用项（与已选附魔冲突）不可拖拽
        if _is_item_disabled(item):
            return
        enchant_id = item.data(Qt.UserRole)
        level = item.data(Qt.UserRole + 1)
        if not enchant_id:
            return

        # 生成拖拽图标
        pixmap = self._create_drag_pixmap(item.text())
        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(f"{enchant_id}:{level}")
        drag.setMimeData(mime_data)
        drag.setPixmap(pixmap)
        drag.setHotSpot(self.logical_center(pixmap))  # 热点 = 图标逻辑中心（任意缩放下都对准鼠标）
        drag.exec_(Qt.CopyAction)

    def mouseReleaseEvent(self, event):
        # 左键点击：增加等级
        if event.button() == Qt.LeftButton:
            if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
                item = self._pressed_item
                # 禁用项（与已选附魔冲突）不可点击加级
                if item and not _is_item_disabled(item):
                    level = item.data(Qt.UserRole + 1) or 1
                    max_level = item.data(Qt.UserRole + 2) or 1
                    if level < max_level:
                        level += 1
                        item.setData(Qt.UserRole + 1, level)
                        base_name = item.text().split("(")[0].strip()
                        item.setText(f"{base_name} (等级 {level})")
                        enchant_id = item.data(Qt.UserRole)
                        if enchant_id:
                            self.levelChanged.emit(enchant_id, level)  # 发射信号
        # 右键点击：减少等级
        elif event.button() == Qt.RightButton:
            item = self._pressed_item
            # 禁用项（与已选附魔冲突）不可点击减级
            if item and not _is_item_disabled(item):
                level = item.data(Qt.UserRole + 1) or 1
                if level > 1:
                    level -= 1
                    item.setData(Qt.UserRole + 1, level)
                    base_name = item.text().split("(")[0].strip()
                    item.setText(f"{base_name} (等级 {level})")
                    enchant_id = item.data(Qt.UserRole)
                    if enchant_id:
                        self.levelChanged.emit(enchant_id, level)  # 发射信号
        super().mouseReleaseEvent(event)

    def _create_drag_pixmap(self, text):
        """生成拖拽时跟随的标签图标

        - 淡灰色圆角背景 + 黑色居中文字（与 DropListWidget 拖出图标样式一致）
        - 按 devicePixelRatio 提升实际绘制分辨率，高分屏/系统缩放下清晰不模糊
        """
        font = QFont("Arial", 10)
        width = max(120, len(text) * 10 + 30)
        height = 30
        # 提升分辨率：实际像素 = 逻辑尺寸 × 屏幕缩放比
        dpr = self.devicePixelRatioF() or 1.0
        pixmap = QPixmap(int(width * dpr), int(height * dpr))
        pixmap.setDevicePixelRatio(dpr)  # 显示尺寸不变，实际像素更高
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        # 淡灰色圆角背景 + 浅色描边
        # 注意：设置 dpr 后 painter 使用逻辑坐标（自动缩放到物理像素），
        # 所有绘制必须用逻辑矩形，不可用 pixmap.rect()（那是设备像素矩形）
        logical_rect = QRect(0, 0, width, height)
        painter.setBrush(QColor(230, 230, 230, 235))
        painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
        painter.drawRoundedRect(logical_rect, 8, 8)

        # 黑色居中文本（用逻辑矩形，任意 dpr 下都严格居中）
        painter.setPen(QColor(20, 20, 20))
        painter.setFont(font)
        painter.drawText(logical_rect, Qt.AlignCenter, text)

        painter.end()
        return pixmap

    @staticmethod
    def logical_center(pixmap) -> QPoint:
        """返回 pixmap 的逻辑中心点（供 QDrag.setHotSpot 使用）

        setHotSpot 接收逻辑坐标，而 pixmap.rect() 是设备像素矩形，
        dpr>1 时直接用 rect().center() 会导致图标偏离鼠标，必须除回 dpr。
        """
        dpr = pixmap.devicePixelRatio() or 1.0
        return QPoint(int(pixmap.width() / dpr) // 2,
                      int(pixmap.height() / dpr) // 2)