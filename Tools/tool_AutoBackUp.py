import os
import json
import zipfile
from datetime import datetime
import shutil
from PySide6.QtCore import QCoreApplication, Slot, QThreadPool, QStandardPaths, QItemSelectionModel
from PySide6.QtWidgets import QFileDialog
from .tool_base import BaseToolWidget
from Utils.signals_AutoBackUp import backup_bus
from Utils.process_monitor import ProcessMonitor
from Threads.task_AutoBackUp import BackupTask
# 导入刚才编译生成的 UI 类
from CodesUI.AutoBackUp import Ui_AutoBackUp


class AutoBackUpWidget(BaseToolWidget, Ui_AutoBackUp):
    """自动备份工具的主窗口类，继承自 BaseToolWidget 和 UI 类"""
    target_dir_path: str = ''  # 源文件夹路径（需要备份的原始文件所在目录）
    des_dir_path: str = ''     # 目标文件夹路径（备份文件保存到的压缩文件存放目录）
    saves_list: dict = {}      # 源文件夹下的所有文件路径映射 {文件名：绝对路径}
    back_up_list: dict = {}    # 用户选中的需要备份的文件列表 {列表项文本：文件绝对路径}

    def __init__(self, parent=None):
        """初始化自动备份工具窗口"""
        # 1. 初始化父类 QWidget
        super().__init__(parent)

        # 2. 执行 UI 的 setup，创建所有界面控件和布局
        self.setupUi(self)

        # 3. 重置进度条为 0（防止上次运行遗留状态）
        self.backUpProgress.setValue(0)

        # 4. 连接所有信号槽，建立用户交互与函数处理的关联
        self.connect_slots()

        # 5. 获取全局线程池实例
        self.thread_pool = QThreadPool.globalInstance()
        # 限制最大并发线程数为 4，避免占用过多系统资源
        self.thread_pool.setMaxThreadCount(4)

        # 6. 初始化所有成员变量为默认值
        self.target_dir_path = ''   # 源文件夹路径（空表示未设置）
        self.des_dir_path = ''      # 目标备份目录路径（空表示未设置）
        self.target_process = ''    # 需要监测的进程名称（如 java.exe），用于触发自动备份
        self.saves_list = {}        # 清空上次的文件列表，避免残留数据
        self.back_up_list = {}      # 选中备份的文件列表清空
        self.total_bytes = 0        # 待备份文件的总大小（字节）
        self.finished_bytes = 0     # 已完成备份的数据量（字节）
        self.total_tasks = 0        # 备份任务总数
        self.failed_tasks = 0       # 失败的备份任务数量

        # 7. 进程监测相关变量初始化
        self.monitor = None         # ProcessMonitor 进程监测器实例
        self.is_monitoring = False  # 是否正在监测进程的状态（False=未启动）

        # 8. 读取已保存的用户配置（从 ~/.config/ 目录下的 JSON 配置文件）
        self.read_config()
        # 进程监测默认注释掉，用户可通过 UI 手动启用

    def connect_slots(self):
        """连接所有 UI 控件的信号到对应的槽函数"""
        # 源文件夹选择按钮点击 -> 打开文件对话框选择源目录
        self.chooseTargetDir.clicked.connect(self.choose_target_dir)
        # 备份目标目录选择按钮点击 -> 打开文件对话框选择备份目录
        self.chooseDesDir.clicked.connect(self.choose_des_der)
        # 源路径文本框内容变化 -> 刷新文件夹列表并标记已选中的项
        self.targetDirPath.textChanged.connect(self.refresh_dir_list)
        # 开始备份按钮点击 -> 执行备份操作
        self.startBackUp.clicked.connect( self.do_back_up)
        # 进程监测控制按钮点击 -> 切换监测状态（启动/停止）
        self.monitorController.clicked.connect(self.moniter_control)

        # 跨模块信号连接：子线程发出的备份进度信号 -> 主界面更新
        backup_bus.task_started.connect(self.on_back_up_started)
        backup_bus.task_progress.connect(self.on_back_up_progress)
        backup_bus.task_finished.connect(self.on_back_up_finished)

    # 4. 实现基类要求的类方法 —— 提供 Tab 标题
    # ==================== 工具元信息区 ====================

    @classmethod
    def tool_name(cls) -> str:
        """提供工具的元信息：返回显示在 Tab 标签上的名称"""
        return "AutoBackUp"  # 这个字符串会显示在 Tab 标签上

    @Slot()
    def choose_target_dir(self):
        """用户点击浏览按钮后，弹出文件对话框让用户选择源文件夹（需要备份的文件所在目录）"""
        dir = QFileDialog.getExistingDirectory(self, "请选择文件夹", "")
        if dir:  # 用户选择了目录并确认
            self.target_dir_path = dir   # 保存到成员变量（用于后续保存配置、遍历文件等）
            self.targetDirPath.setText(dir)  # 更新到 UI 文本框显示

    @Slot()
    def choose_des_der(self):
        """用户点击浏览按钮后，弹出文件对话框让用户选择备份目标文件夹（压缩文件存放目录）"""
        dir = QFileDialog.getExistingDirectory(self, "请选择文件夹", "")
        if dir:  # 用户选择了目录并确认
            self.des_dir_path = dir   # 保存到成员变量（用于保存配置、创建目录等）
            self.targetDesPath.setText(dir)  # 更新到 UI 文本框显示

    @Slot()
    def refresh_dir_list(self):
        """当源路径文本框内容变化时触发：遍历源文件夹下的所有文件，并加载到列表框中"""
        if self.target_dir_path:  # 只有当设置了源路径时才执行
            self.targetDirList.clear()      # 清空列表框（避免重复）
            self.saves_list.clear()         # 清空字典（保持与列表框同步）
            try:
                items = os.listdir(self.target_dir_path)  # 获取目录下的所有文件和子文件夹名称
                for item in items:
                    full_path = os.path.join(self.target_dir_path, item)  # 拼接绝对路径
                    self.saves_list[item] = full_path  # 存入映射字典：便于后续通过文件名获取完整路径

                self.targetDirList.addItems(items)  # 将文件列表添加到 UI 列表框中供用户选择

            except OSError as e:  # 捕获目录不存在、权限不足等异常
                pass  # 静默处理，不弹出错误（配置会被记住用户上次选择的正确路径）

            # 【关键功能】自动勾选之前保存配置时选中的项目：
            # 遍历列表框中所有项，如果该项的文件名在 back_up_list 键集合中，则强制选中它
            for i in range(self.targetDirList.count()):
                item = self.targetDirList.item(i)
                if item.text() in self.back_up_list.keys():  # 检查文件名是否在备份列表中
                    index = self.targetDirList.indexFromItem(item)  # 获取该项的索引位置
                    self.targetDirList.selectionModel().select(  # 强制选中该项（并传递选择给所有其他项）
                        index,
                        QItemSelectionModel.Select | QItemSelectionModel.Rows  # 按整行选中
                )

    def get_back_up_list(self):  # 获取选中的文件夹
        selected_items = self.targetDirList.selectedItems()
        self.back_up_list.clear()
        for item in selected_items:
            text = item.text()
            self.back_up_list[text] = self.saves_list[text]

    # region 用于保存和加载config
    def get_config_path(self):
        """获取配置文件路径（在用户配置目录下）"""
        config_dir = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
        if not config_dir:
            # 如果无法获取标准目录，回退到当前目录
            config_dir = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "backup_config.json")

    def read_config(self):
        """从 JSON 文件加载配置"""
        config_path = self.get_config_path()
        if not os.path.exists(config_path):
            return
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.target_dir_path = data.get("target_dir_path", "")
            self.des_dir_path = data.get("des_dir_path", "")
            self.back_up_list = data.get("back_up_list", {})
            self.target_process = data.get("target_process", "")



            self.targetDirPath.setText(self.target_dir_path)
            self.targetDesPath.setText(self.des_dir_path)
            self.processName.setText(self.target_process)

            self.refresh_dir_list()

        except Exception as e:
            print(f"加载配置文件失败: {e}")

    def save_config(self):
        """将当前配置保存到 JSON 文件"""
        self.get_back_up_list()
        data = {
            "target_dir_path": getattr(self, "target_dir_path", ""),
            "des_dir_path": getattr(self, "des_dir_path", ""),
            "back_up_list": getattr(self, "back_up_list", {}),
            "target_process": getattr(self, "target_process", ""),
        }
        config_path = self.get_config_path()
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置文件失败: {e}")

    # endregion

    # region 执行备份
    @Slot()
    def do_back_up(self,status = "手动"):  # 执行备份
        self.get_back_up_list()
        self.save_config()

        if not self.back_up_list:
            self.informationBrowser.append("错误：备份列表为空，请先设置")
            return

        os.makedirs(self.des_dir_path, exist_ok=True)

        # 1. 过滤有效文件，计算总大小
        valid_paths = []
        self.total_bytes = 0
        for item in self.back_up_list:
            # 解析路径（兼容字典或字符串）
            file_path = self.back_up_list[item]

            if not os.path.exists(file_path):
                self.text_browser.append(f"警告：路径不存在，跳过 - {file_path}")
                continue

            # 如果是文件夹，递归统计所有文件大小
            if os.path.isdir(file_path):
                total_size = 0
                for root, dirs, files in os.walk(file_path):
                    for f in files:
                        full = os.path.join(root, f)
                        total_size += os.path.getsize(full)
                self.total_bytes += total_size
                valid_paths.append(file_path)
            elif os.path.isfile(file_path):
                self.total_bytes += os.path.getsize(file_path)
                valid_paths.append(file_path)
            else:
                self.text_browser.append(f"警告：未知类型，跳过 - {file_path}")

        if not valid_paths:
            self.informationBrowser.append("没有有效文件，终止备份")
            return

        # 2. 设定初始状态
        self.finished_bytes = 0
        self.finished_tasks = 0
        self.failed_tasks = 0
        self.total_tasks = len(valid_paths)
        self.backUpProgress.setValue(0)
        self.informationBrowser.clear()
        self.startBackUp.setEnabled(False)
        self.informationBrowser.append(f"开始{status}备份，总大小：{self.total_bytes} 字节，共 {self.total_tasks} 个文件")

        # 3. 提交任务到线程
        for idx, item in enumerate(valid_paths):
            print(item)
            file_path = item
            task = BackupTask(task_id=idx, file_path=file_path, dest_dir=self.des_dir_path)
            self.thread_pool.start(task)

    # -----------主线程槽函数-----------
    @Slot()
    def on_back_up_started(self, task_id, filename):
        self.informationBrowser.append(f"[任务{task_id}] 正在备份：{filename}")

    @Slot()
    def on_back_up_progress(self, task_id, chunk_bytes):
        self.finished_bytes += chunk_bytes
        percent = int(self.finished_bytes * 100 / self.total_bytes)
        percent = min(percent, 100)
        self.backUpProgress.setValue(percent)

    @Slot()
    def on_back_up_finished(self, task_id, success, message):
        self.finished_tasks += 1
        if not success:
            self.failed_tasks += 1
            self.informationBrowser.append(f"[任务{task_id}] 失败：{message}")
        else:
            self.informationBrowser.append(f"[任务{task_id}] 完成：{message}")

        if self.finished_tasks == self.total_tasks:
            self.startBackUp.setEnabled(True)
            if self.failed_tasks == 0:
                self.informationBrowser.append("所有备份任务成功完成！")
            else:
                self.informationBrowser.append(f"备份完成，但有 {self.failed_tasks} 个任务失败。")
            self.backUpProgress.setValue(100)

    # endregion

    # region 监测进程
    @Slot()
    def moniter_control(self):
        if not self.is_monitoring:   #还未监测
            self.monitorController.setText("停止监测")
            self.start_monitoring()
            self.processName.setEnabled(False)
        else:
            self.monitorController.setText("开始监测")
            self.stop_monitoring()
            self.processName.setEnabled(True)

    def start_monitoring(self):
        # 获取进程名称，如果没有输入则默认为 java.exe
        process_name = self.processName.text() if self.processName.text() else 'java.exe'
        self.target_process = process_name

        if self.monitor:
            self.monitor.stop_monitoring()
            self.monitor.deleteLater()
        self.monitor = ProcessMonitor(process_name=process_name)
        # 连接信号
        self.monitor.started.connect(self.on_process_started)
        self.monitor.stopped.connect(self.on_process_stopped)
        # 开始监视
        self.is_monitoring = True
        self.informationBrowser.append(f"开始监测进程: {process_name}")
        self.monitor.start_monitoring()

    def stop_monitoring(self):
        """停止监测"""
        if self.monitor:
            self.informationBrowser.append(f"停止监测进程: {self.monitor.process_name} ")
            self.monitor.stop_monitoring()
            self.monitor.deleteLater()
            self.monitor = None
        self.is_monitoring = False

    def on_process_started(self, name, pid):
        """进程启动时的处理"""
        self.informationBrowser.append(f"检测到进程 {name} 已启动，PID: {pid}")

    def on_process_stopped(self, name):
        """进程退出时的处理"""
        self.informationBrowser.append(f"检测到进程 {name} 已退出")
        self.monitorController.setText("开始监测")
        # 调用备份方法
        self.do_back_up("自动")
    # endregion