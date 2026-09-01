from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Signal

class BaseToolWidget(QWidget):
    # 可选：每个工具可以定义自己的信号，用于和主窗口通信
    # 例如：请求主窗口显示状态栏消息等
    request_status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 工具特有的初始化

    # 必须实现的静态方法（或类方法），用于提供工具的元信息
    @classmethod
    def tool_name(cls) -> str:
        """返回工具显示名称（Tab 标题）"""
        raise NotImplementedError