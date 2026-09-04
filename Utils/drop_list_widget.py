from PySide6.QtWidgets import QListWidget
from PySide6.QtCore import Qt, Signal


class DropListWidget(QListWidget):
    """
    专门接收拖放附魔的列表控件。
    当有效数据被拖入时，发射 dropped 信号（附魔ID, 等级）。
    """
    dropped = Signal(str, int)  # (enchant_id, level)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(False)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setDropIndicatorShown(True)

    # ---------- 重写拖放事件（确保 100% 捕获） ----------
    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            # 显式设置动作为 Copy，并接受
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        # 必须重写！否则移动时会变为禁止符号
        if event.mimeData().hasText():
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasText():
            event.ignore()
            return

        data = event.mimeData().text()
        try:
            enchant_id, level_str = data.split(":")
            level = int(level_str)
            # 发射信号，交由主窗口处理具体业务逻辑
            self.dropped.emit(enchant_id, level)
            event.setDropAction(Qt.CopyAction)
            event.accept()
        except ValueError:
            event.ignore()