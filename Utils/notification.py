from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QApplication
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QThread
from PySide6.QtGui import QScreen

class NotificationWidget(QWidget):
    _instances = []

    def __init__(self, title: str, message: str, duration: int = 3000, parent=None):
        super().__init__(parent)
        self.duration = duration

        # 窗口属性：无边框、置顶、透明背景
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # 主框架样式
        self.frame = QFrame(self)
        self.frame.setObjectName("NotificationFrame")
        self.frame.setStyleSheet("""
            QFrame#NotificationFrame {
                background-color: rgba(40, 40, 40, 220);
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 30);
            }
            QLabel#TitleLabel {
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
            }
            QLabel#MessageLabel {
                color: #e0e0e0;
                font-size: 12px;
            }
        """)

        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("TitleLabel")
        self.message_label = QLabel(message)
        self.message_label.setObjectName("MessageLabel")
        self.message_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.message_label)

        # 自适应大小
        self.frame.adjustSize()
        self.resize(self.frame.size())

        # 定位到右下角
        self._move_to_bottom_right()

        # 管理实例位置
        NotificationWidget._instances.append(self)
        self._adjust_positions()

        # 自动淡出定时器
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.start_fade_out)
        self.timer.start(self.duration)

    def _move_to_bottom_right(self):
        """将窗口定位到屏幕右下角（考虑任务栏）"""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        x = available.right() - self.width() - 20
        y = available.bottom() - self.height() - 20
        self.move(x, y)

    def _adjust_positions(self):
        """让通知从下往上堆叠，间距 10px"""
        if not self._instances:
            return
        # 按照创建顺序（最旧→最新），最新的在最下面
        base_x = self._instances[0].x()
        # 先获取当前所有实例的高度（可能不同）
        # 从最新的开始，依次向上偏移
        for i, widget in enumerate(reversed(self._instances)):
            offset = i * (widget.height() + 10)
            widget.move(base_x, self._instances[-1].y() - offset)

    def start_fade_out(self):
        """淡出动画"""
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(500)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.anim.finished.connect(self._on_fade_finished)
        self.anim.start()

    def _on_fade_finished(self):
        """移除自身并调整剩余通知位置"""
        if self in self._instances:
            self._instances.remove(self)
        self.close()
        # 重新调整剩余通知的位置
        if self._instances:
            base_x = self._instances[0].x()
            base_y = self._instances[-1].y()
            for i, widget in enumerate(reversed(self._instances)):
                offset = i * (widget.height() + 10)
                widget.move(base_x, base_y - offset)

    @staticmethod
    def Show(title: str, message: str, duration: int = 3000):
        """静态方法：弹出通知（必须在主线程调用）"""
        # 确保在主线程
        # if QApplication.instance().thread() != QThread.currentThread():
        #     # 如果不在主线程，建议通过信号触发，这里简单警告
        #     print("警告：通知必须在主线程调用，请使用信号转发。")
        #     return
        widget = NotificationWidget(title, message, duration)
        widget.show()
        return widget