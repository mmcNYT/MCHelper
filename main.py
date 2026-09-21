import sys

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication
from main_window import MainWindow


if __name__ == "__main__":
    # NVIDIA 桌面 GL 驱动（nvoglv64.dll）在 Qt 6.11 QOpenGLWidget 第二次
    # 模型绘制的 begin-paint 阶段存在 0xC0000409 崩溃，改用软件渲染后端
    # （opengl32sw/llvmpipe）绕开。必须在 QApplication 构造之前设置。
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
