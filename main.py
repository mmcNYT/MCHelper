import sys

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QOpenGLContext, QOffscreenSurface, QSurfaceFormat
from PySide6.QtWidgets import QApplication, QMessageBox

from main_window import MainWindow

# 命令行标记：软件渲染模式。首次硬件探测失败时，自动以该标记重启，
# 使软件模式不再重复探测（避免死循环），也用于人工强制软件渲染。
SOFTWARE_FLAG = "--software-render"


def _has_flag() -> bool:
    return SOFTWARE_FLAG in sys.argv


def _probe_hardware_gl() -> bool:
    """探测硬件 GL 是否可用：能创建 offscreen GL context 即为可用。

    仅当 context 创建失败才判定不可用（保留 ANGLE/llvmpipe 等非
    LibGL 后端，让 Qt 自行决定），不误伤能跑但不标注 LibGL 的环境。
    """
    ctx = QOpenGLContext()
    surf = QOffscreenSurface()
    surf.setFormat(QSurfaceFormat.defaultFormat())
    surf.create()
    return bool(surf.isValid() and ctx.create())


def _restart_software() -> None:
    """弹窗告知后，以软件渲染模式重启本进程（当前进程退出）。"""
    # 创建软件模式用的标记参数（去重，防重复追加）
    args = [a for a in sys.argv if a != SOFTWARE_FLAG] + [SOFTWARE_FLAG]
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("渲染后端切换")
    box.setText("检测到硬件 (GPU) 渲染初始化失败。\n\n"
                "应用将以软件渲染模式自动重启（帧率受限，但保证可用）。")
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()

    from PySide6.QtCore import QProcess
    QProcess.startDetached(sys.executable, args)
    # 本进程退出，交由新进程接管
    QCoreApplication.exit(0)


def main() -> int:
    if _has_flag():
        # 软件渲染模式：设置软件后端属性（须在 QApplication 构造前）
        QCoreApplication.setAttribute(
            Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)

    app = QApplication(sys.argv)

    if not _has_flag():
        # 首次（硬件模式）：探测硬件 GL；失败则弹窗 + 自动软件重启
        if not _probe_hardware_gl():
            _restart_software()
            return 0   # 本进程退出，交由新进程接管

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())