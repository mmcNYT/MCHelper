import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from main_window import MainWindow


def _apply_mc_font(app: QApplication) -> None:
    """全局 MC 像素字体（Monocraft，OFL 许可，见 assets/fonts/OFL.txt）。

    注册 assets/fonts/Monocraft.ttc（无连字版）并设为应用字体：
    NoAntialias 保持硬边像素风；16 逻辑 px 在 1.5 DPR 下 = 24 物理
    px = 字形原生 8px 网格的 3x 整数倍（最锐利档位）。字体文件缺失
    或注册失败时静默回退系统默认，不阻塞启动。局部 QFont() 无参构
    造（预览图/3D 视口 HUD/附魔卡片等）会自动继承该字体族。
    """
    ttc = Path(__file__).resolve().parent / "assets" / "fonts" \
        / "Monocraft.ttc"
    if not ttc.is_file():
        return
    fid = QFontDatabase.addApplicationFont(str(ttc))
    if fid < 0:
        return
    fams = QFontDatabase.applicationFontFamilies(fid)
    if not fams:
        return
    f = QFont(fams[0])
    f.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    f.setPixelSize(16)
    app.setFont(f)


if __name__ == "__main__":
    # NVIDIA 桌面 GL 驱动（nvoglv64.dll）在 Qt 6.11 QOpenGLWidget 第二次
    # 模型绘制的 begin-paint 阶段存在 0xC0000409 崩溃，改用软件渲染后端
    # （opengl32sw/llvmpipe）绕开。必须在 QApplication 构造之前设置。
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    app = QApplication(sys.argv)
    _apply_mc_font(app)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
