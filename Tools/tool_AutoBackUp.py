import os
import json
import zipfile
from datetime import datetime
import shutil
from PySide6.QtCore import QCoreApplication, Slot, QThreadPool, QStandardPaths, QItemSelectionModel, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QListWidgetItem
from .tool_base import BaseToolWidget
from Utils.AutoBackUp.signals_AutoBackUp import backup_bus
from Utils.AutoBackUp.process_monitor import ProcessMonitor
from Utils.AutoBackUp.notification import NotificationWidget
from Utils.AutoBackUp.right_icon_delegate import RightIconDelegate
from Threads.task_AutoBackUp import BackupTask

from CodesUI.AutoBackUp import Ui_AutoBackUp


def format_bytes(num_bytes: int) -> str:
    """字节数格式化为易读单位（1024 进制，保留 1 位小数，整数时省略 .0）

    示例：123456789 → "117.7 MB"；532 → "532 B"；1024 → "1 KB"
    """
    if num_bytes < 1024:
        return f"{num_bytes} B"
    units = ["KB", "MB", "GB", "TB"]
    value = float(num_bytes)
    for unit in units:
        value /= 1024
        if value < 1024 or unit == "TB":
            text = f"{value:.1f}"
            if text.endswith(".0"):
                text = text[:-2]  # 整数值省略小数（1024 → "1 KB"）
            return f"{text} {unit}"
    return f"{value:.1f} TB"


class AutoBackUpWidget(BaseToolWidget, Ui_AutoBackUp):
    """自动备份工具的主窗口类，继承自 BaseToolWidget 和 UI 类"""
    target_dir_path: str = ''  # 源文件夹路径（需要备份的原始文件所在目录）
    des_dir_path: str = ''     # 目标文件夹路径（备份文件保存到的压缩文件存放目录）
    saves_list: dict = {}      # 源文件夹下的所有文件路径映射 {文件名：绝对路径}
    back_up_list: dict = {}    # 用户选中的需要备份的文件列表 {列表项文本：文件绝对路径}
    _ICON_NAMES = ("icon.png", "icon.jpg", "icon.jpeg", "icon.webp", "icon.bmp")  # 存档封面图标候选文件名
    preferred_size = (628, 475)  # UI 设计尺寸，主窗口切到本 tab 时自适应

    def __init__(self, parent=None):
        """初始化自动备份工具窗口"""
        # 1. 初始化父类 QWidget
        super().__init__(parent)

        # 2. 执行 UI 的 setup，创建所有界面控件和布局
        self.setupUi(self)

        # 2.5 存档列表接入委托：MC 存档文件夹（内含 icon.png）的封面图标固定显示在行最右侧
        self._save_icon_delegate = RightIconDelegate(icon_size=32, parent=self.targetDirList)
        self.targetDirList.setItemDelegate(self._save_icon_delegate)

        # 2.6 目录列表刷新防抖定时器：路径输入每变一次就重开 300ms 计时，
        # 停止输入 300ms 后才真正刷新（避免逐字符刷新卡顿）
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(300)
        self._refresh_timer.timeout.connect(self._do_refresh_dir_list)

        # 2.7 存档图标缓存 {icon文件绝对路径: QPixmap}：同一目录多次刷新
        # 时不重复读盘解码；目录变化时旧条目自然废弃
        self._icon_cache = {}

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
        self.is_backing_up = False  # 是否正在进行备份（重入保护：备份中拒绝再次发起；关闭保护：主窗口关窗前询问）
        self.is_auto_back_up = True # 是否进行自动备份

        # 7. 进程监测相关变量初始化
        self.monitor = None         # ProcessMonitor 进程监测器实例
        self.is_monitoring = False  # 是否正在监测进程的状态（False=未启动）

        # 8. 读取已保存的用户配置（从 ~/.config/ 目录下的 JSON 配置文件）
        self.read_config()

        # 9. 自动进行监测
        if self.target_process:
            self.moniter_control()

    def connect_slots(self):
        """连接所有 UI 控件的信号到对应的槽函数"""
        # 源文件夹选择按钮点击 -> 打开文件对话框选择源目录
        self.chooseTargetDir.clicked.connect(self.choose_target_dir)
        # 备份目标目录选择按钮点击 -> 打开文件对话框选择备份目录
        self.chooseDesDir.clicked.connect(self.choose_des_der)
        # 源路径文本框内容变化 -> 刷新文件夹列表并标记已选中的项
        self.targetDirPath.textChanged.connect(self.refresh_dir_list)
        # 开始备份按钮点击 -> 执行备份操作
        self.startBackUp.clicked.connect(lambda :self.do_back_up("手动"))
        # 进程监测控制按钮点击 -> 切换监测状态（启动/停止）
        self.monitorController.clicked.connect(self.moniter_control)
        # 是否勾选自动备份
        self.isAutoBackUp.checkStateChanged.connect(self.on_back_up_check_box_changed)
        # 监测进程输入框变化 -> 更新变量
        self.processName.textChanged.connect(self.on_process_name_text_changed)

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
        # 调用系统文件对话框，获取用户选择的目录路径
        dir = QFileDialog.getExistingDirectory(self, "请选择文件夹", "")

        if dir:  # 用户选择了目录并确认（QFileDialog 返回空字符串表示取消）
            self.target_dir_path = dir   # 保存到成员变量
            self.targetDirPath.setText(dir)  # 更新到 UI 文本框显示，让用户看到选择的源目录路径

    @Slot()
    def choose_des_der(self):
        """用户点击浏览按钮后，弹出文件对话框让用户选择备份目标文件夹（压缩文件存放目录）"""
        # 调用系统文件对话框，获取用户选择的备份目标目录路径
        dir = QFileDialog.getExistingDirectory(self, "请选择文件夹", "")

        if dir:  # 用户选择了目录并确认（QFileDialog 返回空字符串表示取消）
            self.des_dir_path = dir   # 保存到成员变量（用于保存配置、创建备份目录、验证路径存在性等）
            self.targetDesPath.setText(dir)  # 更新到 UI 文本框显示，让用户看到选择的备份目标目录路径

    @Slot()
    def refresh_dir_list(self):
        """当源路径文本框内容变化时触发：防抖后刷新文件夹列表

        直接刷新代价高（listdir + 逐个加载存档 icon），逐字符触发会卡顿；
        这里只重启 300ms 单次定时器，用户停止输入后才真正执行刷新。
        """
        self._refresh_timer.start()

    def _do_refresh_dir_list(self):
        """实际刷新逻辑（防抖到期后执行）：遍历源文件夹下的所有条目并加载到列表框

        - 目录不存在 / 无法读取 → 列表显示一行不可选的提示项（不再静默空白）
        - 正常时列出所有条目，MC 存档文件夹在名称右缘显示封面图标
        - 自动恢复之前保存的选中项状态（从配置中读取）
        """
        # 只有当设置了源路径时才执行，避免对空路径进行文件操作导致异常
        if self.target_dir_path:
            self.targetDirList.clear()      # 清空列表框（避免重复加载相同文件造成界面卡顿和内存浪费）
            self.saves_list.clear()         # 清空字典（保持与列表框同步，用于存储文件名到绝对路径的映射关系）

            try:
                # 先校验目录可访问（不存在/权限不足时给出明确提示，而非静默空白）
                if not os.path.isdir(self.target_dir_path):
                    raise OSError("目录不存在")
                # os.listdir 读取目标目录下的所有条目（文件和子文件夹名称，不包括符号链接）
                items = os.listdir(self.target_dir_path)

                for item in items:  # 遍历获取到的每个文件/文件夹名称
                    full_path = os.path.join(self.target_dir_path, item)  # 拼接文件名和目录路径得到文件的绝对路径
                    self.saves_list[item] = full_path  # 存入映射字典：键为文件名，值为绝对路径，便于后续通过文件名快速查找完整路径

                self._add_list_items(items)  # 逐项构建列表项：MC 存档文件夹（内含 icon.png）在行右缘显示封面图标

            except OSError as e:  # 捕获目录不存在、权限不足、路径无效等操作系统相关异常
                # 目录无效：显示一行不可选的置灰提示项，告知用户原因（不弹窗打扰）
                self._show_dir_error_item(
                    "无法读取源目录：" + self.target_dir_path + "（路径不存在或无权限）")
                return  # 目录无效时没有条目可恢复选中，直接返回

            # 【关键功能】自动勾选之前保存配置时选中的项目：
            # 从配置文件读取用户之前选中的文件列表，恢复选中状态
            # 遍历列表框中所有项，检查该项的文件名是否在之前保存的 back_up_list 键集合中
            for i in range(self.targetDirList.count()):  # count() 返回列表中项目的数量
                item = self.targetDirList.item(i)  # 获取第 i 个列表项的 QListWidgetItem 对象
                if item.text() in self.back_up_list.keys():  # 检查该项的文件名是否在备份列表的键中（需要在备份前选中）
                    index = self.targetDirList.indexFromItem(item)  # 获取该项在列表中的索引位置（用于后续选区操作）
                    self.targetDirList.selectionModel().select(  # select() 强制选中该项，并传递选择给其他项
                        index,
                        QItemSelectionModel.Select | QItemSelectionModel.Rows  # Select: 按整行选中所有子项；Rows: 同时选中该行中的所有单元格
                    )

    def _show_dir_error_item(self, message: str):
        """在列表中显示一行不可选的置灰提示（源目录无效时）"""
        hint = QListWidgetItem(message)
        hint.setFlags(Qt.ItemFlag.NoItemFlags)  # 不可选、不可交互
        self.targetDirList.addItem(hint)

    def _load_save_icon(self, full_path: str):
        """加载存档文件夹的封面图标（带缓存），失败返回 None

        候选文件名：icon.png / icon.jpg / icon.jpeg / icon.webp / icon.bmp；
        缓存键为 icon 文件绝对路径，同一目录反复刷新不重复读盘解码。
        """
        for icon_name in self._ICON_NAMES:
            icon_path = os.path.join(full_path, icon_name)
            if icon_path in self._icon_cache:
                return self._icon_cache[icon_path]
            if os.path.exists(icon_path):
                pixmap = QPixmap(icon_path)
                if not pixmap.isNull():
                    self._icon_cache[icon_path] = pixmap  # 缓存有效图标
                    return pixmap
        return None

    def _add_list_items(self, items):
        """将目录条目逐项添加到列表框，并为 MC 存档文件夹设置行右缘的封面图标

        判断依据：文件夹内存档根目录下直接存在 icon 文件（icon.png / icon.jpg /
        icon.jpeg / icon.webp / icon.bmp），则认为它是 MC 地图存档，
        加载其封面图标固定显示在该行最右侧；普通文件/无 icon 的文件夹不设图标。

        注意：列表项的 text 必须保持原始文件夹名不变（它是 saves_list/back_up_list
        的字典键，选中恢复逻辑依赖 text 匹配），图标通过自定义数据角色携带，不影响 text。
        """
        for name in items:
            list_item = QListWidgetItem(name)  # text 保持原始文件夹名
            full_path = self.saves_list.get(name, "")
            if os.path.isdir(full_path):  # 只有文件夹才可能是地图存档（普通文件如 session.lock 跳过）
                pixmap = self._load_save_icon(full_path)
                if pixmap is not None:
                    self._save_icon_delegate.set_right_icon(list_item, pixmap)
            self.targetDirList.addItem(list_item)

    def get_back_up_list(self):  # 获取用户选中的需要备份的文件列表
        """获取当前列表中用户选中的所有文件项，构建文件名到绝对路径的映射字典

        返回：
            back_up_list: {选中文本：文件绝对路径} 的字典，后续用于执行备份操作
        """
        selected_items = self.targetDirList.selectedItems()  # selectedItems() 返回列表中所有被用户勾选的 QListWidgetItem 对象
        self.back_up_list.clear()  # 清空旧的备份列表，避免重复数据

        for item in selected_items:  # 遍历所有选中的文件项
            text = item.text()  # 获取该项显示的文件名（字典的键）
            self.back_up_list[text] = self.saves_list[text]  # 将文件名映射到对应的绝对路径，存入 back_up_list 字典中

    def get_config_path(self):
        """获取配置文件路径（在用户配置目录下）

        功能说明：
        - 优先使用 QStandardPaths.AppConfigLocation 标准配置目录
        - 如果无法获取标准目录，回退到脚本所在目录
        - 确保配置目录存在
        - 返回配置文件完整路径

        返回：
            config_path: JSON 配置文件的绝对路径
        """
        # 获取应用的标准可写配置目录位置（通常是~/.config/或%APPDATA%/）
        config_dir = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)

        if not config_dir:  # writableLocation() 返回空字符串表示无法获取标准目录（权限不足等）
            # 如果无法获取标准目录，回退到当前脚本所在目录作为备用方案
            config_dir = os.path.dirname(os.path.abspath(__file__))
        # 自动创建配置目录（如果不存在）
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "backup_config.json")

    def read_config(self):
        """从 JSON 文件加载配置

        功能说明：
        - 调用 get_config_path() 获取配置文件路径
        - 检查配置文件是否存在，不存在则直接返回（首次启动时）
        - 以只读方式打开并解析 JSON 内容
        - 将配置项读取到成员变量（target_dir_path、des_dir_path、back_up_list、target_process）
        - 更新 UI 控件显示保存的配置
        - 调用 refresh_dir_list() 刷新文件列表并恢复选中状态
        - 捕获 JSON 解析错误或文件读取异常，输出错误信息到控制台
        """
        config_path = self.get_config_path()
        if not os.path.exists(config_path):
            return
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            #提取文件中的参数
            self.target_dir_path = data.get("target_dir_path", "")
            self.des_dir_path = data.get("des_dir_path", "")
            self.back_up_list = data.get("back_up_list", {})
            self.target_process = data.get("target_process", "")
            self.is_auto_back_up = data.get("is_auto_back_up", True)  # 缺省 True（首次启动默认开启自动备份）

            #更新UI
            self.targetDirPath.setText(self.target_dir_path)
            self.targetDesPath.setText(self.des_dir_path)
            self.processName.setText(self.target_process)
            self.isAutoBackUp.setChecked(self.is_auto_back_up)

            self.refresh_dir_list()

        except Exception as e:
            print(f"加载配置文件失败: {e}")

    def save_config(self):
        """将当前配置保存到 JSON 文件

        功能说明：
        - 调用 get_back_up_list() 获取用户选中的文件列表
        - 构建包含所有配置项的字典（源目录、目标目录、选中文件、监测进程）
        - 调用 get_config_path() 获取配置文件路径
        - 以写入模式 ('w') 打开 JSON 文件并保存数据
        - 使用 ensure_ascii=False 确保中文正常显示
        - 使用 indent=2 美化输出（便于阅读和调试）
        - 捕获保存失败异常并输出错误信息
        """
        self.get_back_up_list()
        data = {
            "target_dir_path": getattr(self, "target_dir_path", ""),
            "des_dir_path": getattr(self, "des_dir_path", ""),
            "back_up_list": getattr(self, "back_up_list", {}),
            "target_process": getattr(self, "target_process", ""),
            "is_auto_back_up": getattr(self, "is_auto_back_up", True)
        }
        config_path = self.get_config_path()
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置文件失败: {e}")

    @Slot()
    def do_back_up(self, status):
        """执行备份操作

        功能说明：
        - 先调用 get_back_up_list() 更新当前文件列表到成员变量
        - 调用 save_config() 将配置持久化到 JSON 文件
        - 检查备份列表是否为空，空则提示用户并终止
        - 创建目标备份目录（若不存在），避免后续写入失败
        - 遍历过滤有效文件，计算需要备份的总大小
        - 对不存在的文件或未知类型给予警告信息

        参数：
            status: 备份触发方式
        """
        # 调用 get_back_up_list() 更新成员变量 back_up_list（从文本框读取用户选中的文件路径）
        self.get_back_up_list()
        # 调用 save_config() 先将配置保存，确保配置文件为最新状态
        self.save_config()

        # 重入保护：备份进行中拒绝再次发起（手动点击已被按钮禁用拦截，
        # 此处主要拦截进程退出触发的自动备份，防止计数被重置导致进度错乱）
        if self.is_backing_up:
            self.informationBrowser.append("提示：已有备份正在进行，本次触发已忽略")
            return

        if not self.back_up_list:
            # 向信息输出区提示用户需要先在上方添加备份项目
            self.informationBrowser.append("错误：备份列表为空，请先设置")
            return

        if not self.des_dir_path:
            # 目标目录未设置时 makedirs('') 会抛 FileNotFoundError，提前拦截
            self.informationBrowser.append("错误：请先设置备份目标目录")
            return

        # 自动创建目标备份目录（若不存在），避免后续写入出错
        os.makedirs(self.des_dir_path, exist_ok=True)

        # ====== 阶段一：过滤有效文件，计算总大小 ======
        valid_paths = []
        self.total_bytes = 0
        for item in self.back_up_list:
            # back_up_list 既可以是字典{"文件名": "完整路径"}也可以是字符串列表，取对应值
            file_path = self.back_up_list[item]

            if not os.path.exists(file_path):
                # 用户输入的路径不存在（可能文件已删除或路径写错）
                self.informationBrowser.append(f"警告：路径不存在，跳过 - {file_path}")
                continue

            # 判断是文件夹还是单文件
            if os.path.isdir(file_path):
                # 如果是文件夹，递归遍历该目录下所有子文件和目录
                total_size = 0
                for root, dirs, files in os.walk(file_path):
                    for f in files:
                        full = os.path.join(root, f)
                        total_size += os.path.getsize(full)
                self.total_bytes += total_size
                valid_paths.append(file_path)
            elif os.path.isfile(file_path):
                # 单文件情况，直接添加大小到统计
                self.total_bytes += os.path.getsize(file_path)
                valid_paths.append(file_path)
            else:
                # 既不是文件夹也不是文件的异常情况（理论上不会发生）
                self.informationBrowser.append(f"警告：未知类型，跳过 - {file_path}")

        if not valid_paths:
            # 所有路径都不合法或无效时终止备份流程
            self.informationBrowser.append("没有有效文件，终止备份")
            return

        # ====== 阶段二：设定备份初始状态 ======
        self.finished_bytes = 0
        self.finished_tasks = 0
        self.failed_tasks = 0
        self.total_tasks = len(valid_paths)
        self.is_backing_up = True           # 标记备份进行中（重入保护 + 关闭保护）
        self.backUpProgress.setValue(0)
        self.informationBrowser.clear()
        # 禁用开始按钮防止重复点击
        self.startBackUp.setEnabled(False)
        # 备份期间禁用路径编辑与列表选择：防止用户修改路径/选区与正在进行的备份交错
        self._set_backup_controls_enabled(False)
        # 输出备份任务概览（含用户传入的 status 参数，总大小格式化为易读单位）
        self.informationBrowser.append(
            f"开始{status}备份，总大小：{format_bytes(self.total_bytes)}，共 {self.total_tasks} 个文件")

        # ====== 阶段三：提交任务到多线程池 ======
        for idx, item in enumerate(valid_paths):
            file_path = item
            # 创建备份任务对象，传入文件路径和目标目录
            task = BackupTask(task_id=idx, file_path=file_path, dest_dir=self.des_dir_path)
            # 将任务提交到线程池异步执行
            self.thread_pool.start(task)

    def _set_backup_controls_enabled(self, enabled: bool):
        """备份期间禁用/恢复路径编辑与列表选择（按钮不在此列，由 finished 统一恢复）"""
        self.chooseTargetDir.setEnabled(enabled)
        self.targetDirPath.setReadOnly(not enabled)
        self.targetDirList.setEnabled(enabled)

    def can_close(self) -> bool:
        """主窗口关闭前调用：备份进行中时告知用户并阻止关闭（避免留下不完整的 zip）

        返回 True 表示可以关闭；False 表示正在备份，需用户确认后再关闭。
        """
        return not self.is_backing_up

    # -----------主线程槽函数-----------
    @Slot()
    def on_back_up_started(self, task_id, filename):
        """接收子线程进度信号，实时更新备份进度条

        功能说明：
        - 当任意备份任务开始文件复制时触发
        - 向输出区显示该任务正在进行的提示消息

        参数：
            task_id: 任务索引标识（对应 valid_paths 中的位置）
            filename: 当前正在备份的文件名（不含路径）
        """
        self.informationBrowser.append(f"[任务{task_id}] 正在备份：{filename}")

    @Slot()
    def on_back_up_progress(self, task_id, chunk_bytes):
        """接收子线程的进度信号，累计已完成备份大小

        功能说明：
        - 每次子线程复制一块文件数据后触发
        - 将已完成的块大小累加到 finished_bytes
        - 计算完成百分比并更新进度条显示
        - 使用 min(percent, 100) 防止百分比超过 100（多任务时）

        参数：
            task_id: 当前任务的索引标识
            chunk_bytes: 本次复制完成的字节数
        """
        self.finished_bytes += chunk_bytes
        # 计算完成百分比，限制不超过 100%
        percent = int(self.finished_bytes * 100 / self.total_bytes)
        percent = min(percent, 100)
        self.backUpProgress.setValue(percent)

    @Slot()
    def on_back_up_finished(self, task_id, success, message):
        """接收子线程完成信号，处理成功或失败结果

        功能说明：
        - 统计已完成任务数和失败任务数
        - 失败时在输出区显示错误消息并计数
        - 成功时显示对应的完成消息
        - 所有任务完成后启用开始按钮
        - 全部成功提示"所有备份任务成功完成！"，否则提示失败数量

        参数：
            task_id: 当前任务的索引标识
            success: 布尔值，True 表示成功，False 表示失败
            message: 任务结束时的消息（如文件已复制或复制失败的原因）
        """
        self.finished_tasks += 1
        if not success:
            self.failed_tasks += 1
            self.informationBrowser.append(f"[任务{task_id}] 失败：{message}")
        else:
            self.informationBrowser.append(f"[任务{task_id}] 完成：{message}")

        # 检查是否所有子任务都已完成
        if self.finished_tasks == self.total_tasks:
            self.is_backing_up = False      # 清除备份进行中标志（重入/关闭保护解除）
            self.startBackUp.setEnabled(True)
            self._set_backup_controls_enabled(True)  # 恢复路径编辑与列表选择
            if self.failed_tasks == 0:
                self.informationBrowser.append("所有备份任务成功完成！")
                NotificationWidget.Show("备份完成", "所有文件已成功备份。", 3000)
            else:
                self.informationBrowser.append(f"备份完成，但有 {self.failed_tasks} 个任务失败。")
                NotificationWidget.Show("备份部分完成", f"有 {self.failed_tasks} 个任务失败。", 3000)
            self.backUpProgress.setValue(100)

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
        NotificationWidget.Show("进程监测",f"{name}已启动",3000)

    def on_process_stopped(self, name):
        """进程退出时的处理"""
        self.informationBrowser.append(f"检测到进程 {name} 已退出")
        self.monitorController.setText("开始监测")
        # 调用备份方法
        if self.is_auto_back_up == True:
            self.do_back_up(status="自动")

    def on_back_up_check_box_changed(self):
        statu = self.isAutoBackUp.checkState().name
        statu_bool = True if statu == "Checked" else False
        self.is_auto_back_up = statu_bool

    def on_process_name_text_changed(self):
        self.target_process = self.processName.text()