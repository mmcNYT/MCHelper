from PySide6.QtWidgets import QListWidget, QApplication
from PySide6.QtCore import Qt, QMimeData, QPoint, Signal
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
        drag.setHotSpot(pixmap.rect().center())
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
        """生成拖拽时跟随的标签图标"""
        font = QFont("Arial", 10)
        width = max(120, len(text) * 10 + 30)
        height = 30
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setBrush(QColor(40, 40, 40, 220))
        painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
        painter.drawRoundedRect(0, 0, width - 1, height - 1, 8, 8)

        painter.setPen(Qt.white)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, text)

        painter.end()
        return pixmap