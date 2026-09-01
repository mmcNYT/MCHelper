from PySide6.QtWidgets import QMainWindow, QTabWidget
from Tools import TOOL_CLASSES
from CodesUI.MCHelperMainWindow import Ui_MCHelper


class MainWindow(QMainWindow,Ui_MCHelper):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # 遍历注册列表，加载所有工具
        self.load_tools()

    def load_tools(self):
        for tool_cls in TOOL_CLASSES:
            # 1. 用 @classmethod 调用，不用加括号，不创建对象，直接拿名字
            tool_name = tool_cls.tool_name()

            # 2. 这里才真正创建工具对象（加括号实例化）
            tool_widget = tool_cls(self)

            # 3. 添加到 Tab 页
            self.tabWidget.addTab(tool_widget, tool_name)

    def closeEvent(self, event):
        """
        在窗口关闭前调用，保存所有工具的配置。
        """
        # 调用保存所有工具配置的函数
        self.save_all_tools_config()

        # 接受关闭事件（继续关闭窗口）
        event.accept()

    def save_all_tools_config(self):
        for i in range(self.tabWidget.count()):
            widget = self.tabWidget.widget(i)
            if hasattr(widget, 'save_config') and callable(widget.save_config):
                try:
                    widget.save_config()
                except Exception as e:
                    print(f"保存工具 {widget.tool_name()} 配置失败: {e}")