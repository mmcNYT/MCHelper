# utils/notification.py
# 桌面通知控件：在屏幕右下角弹出可堆叠的气泡通知，支持自动淡出
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QApplication
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QThread
from PySide6.QtGui import QScreen

class NotificationWidget(QWidget):
    """桌面通知控件：在屏幕右下角显示深色圆角气泡通知

    功能说明：
    - 无边框、置顶、半透明的通知窗口，不抢焦点
    - 多条通知从下往上堆叠（间距 10px）
    - 显示 duration 毫秒后自动淡出并销毁
    - 通过类方法 NotificationWidget.Show(title, message, duration) 快捷调用

    使用场景（已接入）：
    - AutoBackUpWidget：备份完成/部分完成、监测进程启动时弹出
    """
    _instances = []  # 类级列表：记录当前所有存活的通知实例（用于多通知堆叠排布）

    def __init__(self, title: str, message: str, duration: int = 3000, parent=None):
        """初始化通知窗口

        参数：
            title: 通知标题（加粗白字）
            message: 通知正文（支持自动换行）
            duration: 通知显示时长（毫秒），超时后开始淡出，默认 3000ms
        """
        super().__init__(parent)
        self.duration = duration

        # 1. 窗口属性：无边框、置顶、透明背景
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |        # 无边框（系统标题栏/边框隐藏）
            Qt.WindowType.Tool |                       # 工具窗口：不在任务栏显示图标
            Qt.WindowType.WindowStaysOnTopHint         # 始终置顶
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)    # 背景透明（圆角外无矩形底）
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)    # 显示时不抢焦点

        # 2. 主框架样式（深色圆角容器 + 标题/正文字体样式）
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

        # 3. 框架内垂直布局：标题在上、正文在下
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(15, 12, 15, 12)  # 内边距
        layout.setSpacing(4)                       # 标题与正文间距

        self.title_label = QLabel(title)           # 标题标签
        self.title_label.setObjectName("TitleLabel")
        self.message_label = QLabel(message)       # 正文标签
        self.message_label.setObjectName("MessageLabel")
        self.message_label.setWordWrap(True)       # 正文过长时自动换行

        layout.addWidget(self.title_label)
        layout.addWidget(self.message_label)

        # 4. 自适应大小（按内容计算窗口尺寸）
        self.frame.adjustSize()
        self.resize(self.frame.size())

        # 5. 定位到右下角
        self._move_to_bottom_right()

        # 6. 管理实例位置：注册到类级列表并重排所有通知的堆叠位置
        NotificationWidget._instances.append(self)
        self._adjust_positions()

        # 7. 自动淡出定时器：duration 毫秒后触发 start_fade_out 开始淡出
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)  # 单次触发
        self.timer.timeout.connect(self.start_fade_out)
        self.timer.start(self.duration)

    def _move_to_bottom_right(self):
        """将窗口定位到屏幕右下角（考虑任务栏）

        功能说明：
        - 使用 availableGeometry() 获取排除任务栏后的可用区域
        - 距右下边缘各留 20px 边距
        """
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()  # 可用区域（不含任务栏）
        x = available.right() - self.width() - 20
        y = available.bottom() - self.height() - 20
        self.move(x, y)

    def _adjust_positions(self):
        """让通知从下往上堆叠，间距 10px

        功能说明：
        - 以最新通知为基准（最靠右下角），较旧的通知依次向上偏移
        - 偏移量按各通知自身高度计算（不同通知高度可能不同）
        - _instances 顺序为创建顺序：[0] 最旧、[-1] 最新（最下面）
        """
        if not self._instances:
            return
        # 按照创建顺序（最旧→最新），最新的在最下面
        base_x = self._instances[0].x()  # 所有通知水平对齐（取最旧通知的 x）
        # 先获取当前所有实例的高度（可能不同）
        # 从最新的开始，依次向上偏移
        for i, widget in enumerate(reversed(self._instances)):
            offset = i * (widget.height() + 10)  # 第 i 新的通知向上偏移 i 个（高度+10px）
            widget.move(base_x, self._instances[-1].y() - offset)

    def start_fade_out(self):
        """淡出动画：将窗口不透明度从 1.0 渐变到 0.0（500ms，先快后缓）"""
        self.anim = QPropertyAnimation(self, b"windowOpacity")  # 动画目标：窗口不透明度
        self.anim.setDuration(500)                 # 动画时长 500ms
        self.anim.setStartValue(1.0)               # 完全不透明
        self.anim.setEndValue(0.0)                 # 完全透明
        self.anim.setEasingCurve(QEasingCurve.Type.OutQuad)  # 缓动曲线：开始快结束慢
        self.anim.finished.connect(self._on_fade_finished)   # 动画结束回调
        self.anim.start()

    def _on_fade_finished(self):
        """淡出动画结束后：移除自身并调整剩余通知位置

        功能说明：
        - 从 _instances 列表中注销自己，关闭窗口
        - 以剩余通知中最新的一条为基准，重新从下往上堆叠
        """
        if self in self._instances:
            self._instances.remove(self)
        self.close()
        # 重新调整剩余通知的位置（与 _adjust_positions 逻辑一致）
        if self._instances:
            base_x = self._instances[0].x()   # 水平对齐
            base_y = self._instances[-1].y()  # 最新（最下）通知的 y 作为基准
            for i, widget in enumerate(reversed(self._instances)):
                offset = i * (widget.height() + 10)
                widget.move(base_x, base_y - offset)

    @staticmethod
    def Show(title: str, message: str, duration: int = 3000):
        """静态方法：弹出通知（必须在主线程调用）

        功能说明：
        - 创建通知控件实例、显示窗口并返回实例引用
        - 供其他模块静态调用（如 NotificationWidget.Show("备份完成", "...", 3000)）
        - 注意：Qt 控件必须在主线程创建/操作，子线程需通过信号转发到主线程调用

        参数：
            title: 通知标题
            message: 通知正文
            duration: 显示时长（毫秒），默认 3000ms

        返回：
            widget: 创建的通知实例（便于外部跟踪或主动关闭）
        """
        # 确保在主线程
        # if QApplication.instance().thread() != QThread.currentThread():
        #     # 如果不在主线程，建议通过信号触发，这里简单警告
        #     print("警告：通知必须在主线程调用，请使用信号转发。")
        #     return
        widget = NotificationWidget(title, message, duration)
        widget.show()
        return widget
