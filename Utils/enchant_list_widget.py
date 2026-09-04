from PySide6.QtWidgets import QListWidget, QApplication
from PySide6.QtCore import Qt, QMimeData, QPoint
from PySide6.QtGui import QDrag


class EnchantListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)  # 允许拖出
        self.setAcceptDrops(False)  # 不接收拖入
        self._drag_start_pos = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # 判断是否达到拖拽阈值
        if not (event.buttons() & Qt.LeftButton):
            return
        if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return

        item = self.currentItem()
        if not item:
            return

        # 从 item 中取出我们存储的数据（附魔ID和当前等级）
        enchant_id = item.data(Qt.UserRole)
        level = item.data(Qt.UserRole + 1)
        if not enchant_id:
            return

        # 开始拖拽
        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(f"{enchant_id}:{level}")  # 传递数据
        drag.setMimeData(mime_data)
        drag.exec_(Qt.CopyAction)

    def dragMoveEvent(self, event):
        """当拖动进入物品栏时，接受文本数据"""
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            # 判断是“点击”而不是“拖拽”
            if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
                item = self.currentItem()
                if item:
                    # 获取当前等级和最大等级
                    level = item.data(Qt.UserRole + 1) or 1
                    max_level = item.data(Qt.UserRole + 2) or 1
                    if level < max_level:
                        level += 1
                        item.setData(Qt.UserRole + 1, level)
                        # 更新显示文本（假设原文本格式为 "附魔名 (等级 X)"）
                        base_name = item.text().split("(")[0].strip()
                        item.setText(f"{base_name} (等级 {level})")
        super().mouseReleaseEvent(event)