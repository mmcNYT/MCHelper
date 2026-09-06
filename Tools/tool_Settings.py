from PySide6.QtWidgets import QDialog
from PySide6.QtCore import QCoreApplication, Slot, QThreadPool, QStandardPaths, QItemSelectionModel
from CodesUI.Settings import Ui_Settings  # 编译生成的 UI 类
from Utils.Settings.signals_Settings import settings_bus
import os,json

class SettingsWindow(QDialog, Ui_Settings):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowTitle("设置")

        self.is_start_on_root = False
        self.is_system_tray = False

        self.isStartOnRoot.checkStateChanged.connect(self.start_on_root_statu)
        self.isSystemTray.checkStateChanged.connect(self.system_tray_statu)

        self.read_config()

        self.start_on_root_statu()
        self.system_tray_statu()

    def start_on_root_statu(self):
        statu = self.isStartOnRoot.checkState().name
        statu_bool = True if statu == "Checked" else False
        self.is_start_on_root = statu_bool
        settings_bus.is_start_on_boot.emit(statu_bool)

    def system_tray_statu(self):
        statu = self.isSystemTray.checkState().name
        statu_bool = True if statu == "Checked" else False
        self.is_system_tray = statu_bool
        settings_bus.is_system_tray.emit(statu_bool)

    def get_config_path(self):
        # 获取应用的标准可写配置目录位置（通常是~/.config/或%APPDATA%/）
        config_dir = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)

        if not config_dir:  # writableLocation() 返回空字符串表示无法获取标准目录（权限不足等）
            # 如果无法获取标准目录，回退到当前脚本所在目录作为备用方案
            config_dir = os.path.dirname(os.path.abspath(__file__))
        # 自动创建配置目录（如果不存在）
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "settings_config.json")

    def read_config(self):
        config_path = self.get_config_path()
        if not os.path.exists(config_path):
            return
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            #提取文件中的参数
            self.is_system_tray = data.get("is_system_tray", bool)
            self.is_start_on_root = data.get("is_start_on_root", bool)
            #更新UI
            self.isStartOnRoot.setChecked(self.is_start_on_root)
            self.isSystemTray.setChecked(self.is_system_tray)

        except Exception as e:
            print(f"加载配置文件失败: {e}")

    def save_config(self):
        data = {
            "is_system_tray": getattr(self, "is_system_tray", bool),
            "is_start_on_root": getattr(self, "is_start_on_root", bool),
        }
        config_path = self.get_config_path()

        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置文件失败: {e}")

    def closeEvent(self, event):
        self.save_config()
        event.accept()