from PySide6.QtWidgets import QMainWindow, QTabWidget,QMenu
from PySide6.QtGui import QAction
from Tools import TOOL_CLASSES
from Tools.tool_Settings import SettingsWindow
from CodesUI.MCHelperMainWindow import Ui_MCHelper


class MainWindow(QMainWindow,Ui_MCHelper):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # 遍历注册列表，加载所有工具
        self.load_tools()

        # 创建并绑定菜单栏的信号
        self.create_menu()

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

    def create_menu(self):
        menu = QMenu("菜单", self)
        actions = ["设置", "关于"]
        for i, name in enumerate(actions):
            action = QAction(name, self)
            action.setData(i)  # 存储索引 0, 1, 2
            action.triggered.connect(self.menu_controller)
            menu.addAction(action)
        self.menuBar().addMenu(menu)


    def menu_controller(self):
        action = self.sender()  # 获取触发信号的动作对象
        index = action.data()  # 取出存储的索引
        if index == 0:          #打开设置
            settings_win = SettingsWindow(self)
            settings_win.exec()