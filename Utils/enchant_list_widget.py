from PySide6.QtWidgets import QListWidget, QApplication
from PySide6.QtCore import Qt, QMimeData, QPoint
from PySide6.QtGui import QDrag, QPixmap, QPainter, QColor, QPen, QFont


class EnchantListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        # 禁用右键菜单，防止右键弹出干扰
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self._drag_start_pos = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return

        item = self.currentItem()
        if not item:
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
            # 判断是点击（非拖拽）
            if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
                item = self.currentItem()
                if item:
                    level = item.data(Qt.UserRole + 1) or 1
                    max_level = item.data(Qt.UserRole + 2) or 1
                    if level < max_level:
                        level += 1
                        item.setData(Qt.UserRole + 1, level)
                        base_name = item.text().split("(")[0].strip()
                        item.setText(f"{base_name} (等级 {level})")
        # 右键点击：减少等级（不判断拖拽距离，因为右键不用于拖拽）
        elif event.button() == Qt.RightButton:
            item = self.currentItem()
            if item:
                level = item.data(Qt.UserRole + 1) or 1
                if level > 1:
                    level -= 1
                    item.setData(Qt.UserRole + 1, level)
                    base_name = item.text().split("(")[0].strip()
                    item.setText(f"{base_name} (等级 {level})")

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