from PySide6.QtWidgets import QDialog
from CodesUI.Settings import Ui_Settings  # 编译生成的 UI 类
from Utils.signals_Settings import settings_bus

class SettingsWindow(QDialog, Ui_Settings):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)  # 加载 Designer 拖拽的控件
        self.setWindowTitle("设置")

        self.isStartOnRoot.checkStateChanged.connect(self.start_on_root_statu)
        self.isSystemTray.checkStateChanged.connect(self.system_tray_statu)

    def start_on_root_statu(self):
        statu = self.isStartOnRoot.checkState().name
        statu_bool = True if statu == "Checked" else False
        settings_bus.is_start_on_boot.emit(statu_bool)

    def system_tray_statu(self):
        statu = self.isSystemTray.checkState().name
        statu_bool = True if statu == "Checked" else False
        settings_bus.is_system_tray.emit(statu_bool)