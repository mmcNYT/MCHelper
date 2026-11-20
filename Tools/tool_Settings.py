from PySide6.QtWidgets import QDialog, QFileDialog
from PySide6.QtCore import QCoreApplication, Slot, QThreadPool, QStandardPaths
from CodesUI.Settings import Ui_Settings  # 编译生成的 UI 类
from Utils.Settings.signals_Settings import settings_bus
from Utils.SaveManager.save_config import load_settings, update_settings
from Utils.SaveManager.save_scanner import default_saves_root
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
        self.savesDirBrowseButton.clicked.connect(self._on_browse_saves_dir)

        self.checkRenderingSupportButton.clicked.connect(
            self.check_rendering_support)

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

    def _on_browse_saves_dir(self):
        """选择存档扫描根目录（MC 安装根目录，含 versions/ 与 saves/）。"""
        start = self.savesDirEdit.text().strip() or default_saves_root()
        chosen = QFileDialog.getExistingDirectory(
            self, "选择存档目录（MC 安装根目录）", start)
        if chosen:
            self.savesDirEdit.setText(chosen)

    def read_config(self):
        data = load_settings()
        self.is_system_tray = bool(data.get("is_system_tray", False))
        self.is_start_on_root = bool(data.get("is_start_on_root", False))
        saves_dir = data.get("saves_dir")
        self.savesDirEdit.setText(saves_dir if isinstance(saves_dir, str)
                                  else default_saves_root())
        #更新UI
        self.isStartOnRoot.setChecked(self.is_start_on_root)
        self.isSystemTray.setChecked(self.is_system_tray)

    def save_config(self):
        update_settings({
            "is_system_tray": getattr(self, "is_system_tray", False),
            "is_start_on_root": getattr(self, "is_start_on_root", False),
            "saves_dir": self.savesDirEdit.text().strip(),
        })

    def closeEvent(self, event):
        self.save_config()
        event.accept()

    def _gl_str(self, fn, enum):
        """读 GL 字符串（GL_VENDOR/GL_RENDERER/GL_VERSION），带异常防护。"""
        try:
            v = fn.glGetString(enum)
            if v is None:
                return None
            return v.decode("utf-8", "replace") if isinstance(v, bytes) \
                else str(v)
        except Exception:
            return None

    def check_rendering_support(self):
        """检测当前环境是否支持 OpenGL 渲染，并报告实际渲染后端。

        复用 main.py 的硬件探测语义：能创建 offscreen GL context 即视为
        可渲染；进一步读取 GL_RENDERER 区分硬件/软件后端，便于用户判断
        是否需要软件渲染降级。
        """
        from PySide6.QtGui import (QOpenGLContext, QOffscreenSurface,
                                   QSurfaceFormat)
        from PySide6.QtWidgets import QMessageBox
        fmt = QSurfaceFormat.defaultFormat()
        surf = QOffscreenSurface()
        surf.setFormat(fmt)
        surf.create()
        ctx = QOpenGLContext()
        ctx.setFormat(fmt)
        ok = bool(surf.isValid() and ctx.create())
        vendor = renderer = version = None
        if ok:
            try:
                if ctx.makeCurrent(surf):
                    fn = ctx.functions()
                    vendor = self._gl_str(fn, 0x1F00)    # GL_VENDOR
                    renderer = self._gl_str(fn, 0x1F01)  # GL_RENDERER
                    version = self._gl_str(fn, 0x1F02)   # GL_VERSION
                    ctx.doneCurrent()
            except Exception:
                vendor = renderer = version = None
        if ok:
            soft_markers = ("llvmpipe", "software", "swiftshader",
                            "basic render", "microsoft basic",
                            "warp", "gdi generic")
            soft = (renderer or "").lower()
            if any(m in soft for m in soft_markers):
                title = "渲染支持检测 - 软件渲染"
                msg = ("当前环境能创建 OpenGL 渲染上下文，但检测到的是"
                       "软件渲染后端（帧率受限）。\n\n"
                       f"渲染器: {renderer}\n"
                       f"厂商: {vendor}\n"
                       f"OpenGL 版本: {version}")
            else:
                title = "渲染支持检测 - 硬件加速"
                msg = ("环境支持 OpenGL 渲染（硬件加速可用）。\n\n"
                       f"渲染器: {renderer}\n"
                       f"厂商: {vendor}\n"
                       f"OpenGL 版本: {version}")
        else:
            title = "渲染支持检测 - 不支持"
            msg = ("环境无法创建 OpenGL 渲染上下文，3D 结构预览等"
                   "渲染功能不可用。")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        box.setText(msg)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()