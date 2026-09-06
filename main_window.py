from PySide6.QtWidgets import QMainWindow, QTabWidget, QSystemTrayIcon, QMenu, QStyle, QApplication, QMessageBox
from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon, QAction
from Tools import TOOL_CLASSES
from Tools.tool_Settings import SettingsWindow
from CodesUI.MCHelperMainWindow import Ui_MCHelper
from Utils.signals_Settings import settings_bus
import winreg
import sys
import os


class MainWindow(QMainWindow,Ui_MCHelper):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        #初始化状态量
        self.is_system_tray = False     #是否最小化到托盘
        self.is_start_on_boot = False   #是否开机自启动
        self.is_quitting = False        #是否正在退出

        # 遍历注册列表，加载所有工具
        self.load_tools()

        # 切换 tab 时窗口自适应当前工具的期望尺寸
        self.tabWidget.currentChanged.connect(self.adapt_window_to_tool)
        # 启动时首个 addTab 自动选中 index 0，但此时信号尚未连接；
        # 用 0ms 延迟在事件循环启动后补一次自适应，避免程序以默认 800x600 打开
        QTimer.singleShot(0, lambda: self.adapt_window_to_tool(self.tabWidget.currentIndex()))

        # 创建并绑定菜单栏的信号
        self.create_menu()

        # 绑定设置更改的信号
        settings_bus.is_system_tray.connect(self.system_tray_controller)
        settings_bus.is_start_on_boot.connect(self.start_on_boot_controller)

        self.creat_tray_icon()

    def load_tools(self):
        for tool_cls in TOOL_CLASSES:
            # 1. 用 @classmethod 调用，不用加括号，不创建对象，直接拿名字
            tool_name = tool_cls.tool_name()

            # 2. 这里才真正创建工具对象（加括号实例化）
            tool_widget = tool_cls(self)

            # 3. 添加到 Tab 页
            self.tabWidget.addTab(tool_widget, tool_name)

    def adapt_window_to_tool(self, index: int):
        """切换 tab 时窗口自适应当前工具的期望尺寸。

        工具通过类属性 preferred_size = (宽, 高) 声明内容区期望尺寸：
        - 声明了：窗口 resize 到 期望尺寸 + 窗口装饰差值（边框/标题栏/菜单栏/tab 栏，动态计算）
        - 未声明（None）：保持当前窗口大小不动
        - 窗口最大化/最小化/全屏时不干预
        """
        if index < 0:
            return
        widget = self.tabWidget.widget(index)
        if widget is None:
            return
        preferred = getattr(widget, 'preferred_size', None)
        if not preferred:
            return
        # 最大化/最小化/全屏状态不干预用户当前窗口状态
        if self.isMaximized() or self.isMinimized() or self.isFullScreen():
            return

        # 客户区尺寸相对工具 widget 的固定开销 =
        #   菜单栏 + central widget 布局边距 + tab 栏 + tab 页边框
        # 这些开销不随窗口大小变化，用当前尺寸差直接补偿即可
        # 注意 resize() 设置的是客户区尺寸，不能用 frameGeometry()（含原生边框）
        chrome_w = self.width() - widget.width()
        chrome_h = self.height() - widget.height()

        target_content_w, target_content_h = preferred
        self.resize(target_content_w + chrome_w, target_content_h + chrome_h)

    def closeEvent(self, event):
        """
        用户点击窗口关闭按钮时：
        - 如果托盘图标可见，则隐藏窗口（最小化到托盘）并忽略关闭事件。
        - 如果正在退出程序，则正常关闭。
        - 关闭前询问各工具：备份进行中时提示用户并阻止关闭（避免留下不完整的备份文件）。
        """
        # 逐个工具检查是否允许关闭（如 AutoBackUp 备份进行中返回 False）
        for i in range(self.tabWidget.count()):
            widget = self.tabWidget.widget(i)
            if hasattr(widget, 'can_close') and callable(widget.can_close):
                if not widget.can_close():
                    # 有工具正在进行关键操作：提示用户，本次阻止关闭
                    QMessageBox.warning(
                        self, "无法关闭",
                        "工具正在执行备份任务，关闭程序会产生不完整的备份文件。\n"
                        "请等待备份完成后再关闭。")
                    event.ignore()
                    return

        if self.is_quitting or self.is_system_tray == False:
            # 正在退出，正常关闭窗口
            self.save_all_tools_config()
            event.accept()
            return
        if self.tray_icon and self.tray_icon.isVisible():
            # 隐藏窗口到系统托盘
            self.hide()
            event.ignore()  # 忽略关闭事件，程序继续运行
        else:
            # 托盘不可用，直接保存配置并关闭
            self.save_all_tools_config()
            event.accept()

    def save_all_tools_config(self):
        for i in range(self.tabWidget.count()):
            widget = self.tabWidget.widget(i)
            if hasattr(widget, 'save_config') and callable(widget.save_config):
                try:
                    widget.save_config()
                except Exception as e:
                    print(f"保存工具 {widget.tool_name()} 配置失败: {e}")

    def creat_tray_icon(self):
        # 创建托盘图标
        self.tray_icon = QSystemTrayIcon(self)

        # 设置图标（如果没有自定义图标，使用标准图标）
        # 推荐使用资源文件：QIcon(":/icons/app.ico")
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))

        # 设置悬浮提示
        self.tray_icon.setToolTip("MCHelper")

        # 创建托盘右键菜单
        tray_menu = QMenu(self)
        show_action = QAction("显示窗口", self)
        show_action.triggered.connect(self.show_window)
        quit_action = QAction("关闭程序", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(show_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)

        # 连接左键单击事件（Trigger 表示点击）
        self.tray_icon.activated.connect(self.tray_activated)

        # 显示托盘图标
        self.tray_icon.show()

    def tray_activated(self, reason):
        """托盘图标被激活（点击）时的处理"""
        # 左键单击（Trigger）时显示窗口
        if reason == QSystemTrayIcon.Trigger:
            self.show_window()

    def show_window(self):
        """显示主窗口并置前"""
        self.show()
        self.raise_()  # 提升到顶层
        self.activateWindow()  # 激活窗口（获取焦点）

    def quit_app(self):
        """彻底退出程序"""
        self.is_quitting = True
        # 保存所有工具的配置（之前已实现）
        self.save_all_tools_config()
        # 退出应用
        QApplication.quit()

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

    def system_tray_controller(self,statu):
        self.is_system_tray = statu
        print(f"系统托盘{statu}")

    def start_on_boot_controller(self,statu):
        self.is_start_on_boot = statu
        self.set_start_on_boot(statu)
        print(f"自启动{statu}")

    def set_start_on_boot(self,enable : bool):
        app_name = "MCHelper"
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"

        try:
            # 打开注册表键
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            if enable:
                # 获取当前脚本或exe的完整路径
                script_path = os.path.abspath(sys.argv[0])
                # 如果是 .py 文件，需要用 python.exe 调用
                if script_path.endswith('.py'):
                    executable = f'"{sys.executable}" "{script_path}"'
                else:  # 如果是打包后的 .exe
                    executable = f'"{script_path}"'
                # 写入注册表
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, executable)
                print(f"✓ 已添加开机自启动项: {app_name}")
            else:
                # 删除注册表项
                try:
                    winreg.DeleteValue(key, app_name)
                    print(f"✓ 已删除开机自启动项: {app_name}")
                except FileNotFoundError:
                    print(f"! 开机自启动项 '{app_name}' 不存在")
            winreg.CloseKey(key)
            return True
        except Exception as e:
            print(f"✗ 操作注册表失败: {e}")
            return False