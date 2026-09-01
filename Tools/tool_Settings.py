from PySide6.QtWidgets import QDialog
from CodesUI.Settings import Ui_Settings  # 编译生成的 UI 类


class SettingsWindow(QDialog, Ui_Settings):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)  # 加载 Designer 拖拽的控件
        self.setWindowTitle("设置")