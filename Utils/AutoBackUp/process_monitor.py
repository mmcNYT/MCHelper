# =============================================================================
# ProcessMonitor 类：进程监测器
# 功能说明：
#   - 实时监测指定进程的运行状态（支持按进程名或 PID 监测）
#   - 当目标进程启动/关闭时，通过信号向主界面汇报状态变化
#   - 使用定时轮询方式检测（可配置检查间隔）
# =============================================================================

import psutil
from PySide6.QtCore import QObject, Signal, QTimer


class ProcessMonitor(QObject):
    """
    进程监测器类

    功能说明：
        - 实时监测指定进程的运行状态
        - 支持按进程名（不区分大小写）或 PID 两种方式识别目标进程
        - 当进程启动/关闭时，发射 started/stopped/status_changed 信号通知主界面
        - 采用定时轮询机制检测（默认间隔 1 秒，可调）

    使用示例：
        monitor = ProcessMonitor(process_name="notepad.exe")
        monitor.start_monitoring()
        # 连接信号处理函数
        monitor.started.connect(lambda name, pid: print(f"进程启动：{name} (PID={pid})"))
        monitor.stopped.connect(lambda name: print(f"进程关闭：{name}"))
    """

    # ----- 信号定义 -----
    # started: 目标进程启动时发射，附带进程名和 PID（用于主界面显示或日志记录）
    started = Signal(str, int)
    # stopped: 目标进程关闭时发射，附带进程名（最后一次获取的）
    stopped = Signal(str)
    # status_changed: 进程状态变化时发射（True=启动/恢复，False=关闭），用于主界面状态更新
    status_changed = Signal(bool)

    def __init__(self, process_name=None, pid=None, parent=None):
        """初始化进程监测器

        参数：
            process_name: 要监测的进程名（如 "notepad.exe"），不区分大小写
                          通过进程名称模糊匹配，适用于多版本软件或同名列的情况
            pid: 要监测的进程 PID。如果提供则优先使用 PID，比进程名更精确
                  适用于需要精确定位特定进程实例的场景
            parent: PySide6 父对象（用于对象树管理）

        示例：
            # 按进程名监测
            monitor = ProcessMonitor(process_name="python.exe")

            # 按 PID 监测（更精确）
            monitor = ProcessMonitor(pid=1234)

            # 混合使用：PID 优先，但也可用进程名作为后备
            monitor = ProcessMonitor(process_name="python.exe", pid=1234)
        """
        super().__init__(parent)
        # process_name: 目标进程名称（用于通过名称识别进程）
        self.process_name = process_name
        # pid: 目标进程 ID（如果提供，则优先使用 PID 而非进程名进行匹配）
        self.pid = pid
        # _is_running: 缓存的进程运行状态（True/False），用于检测状态变化
        self._is_running = False
        # _timer: 定时检查器，用于周期性检测进程状态
        self._timer = QTimer(self)
        # 连接定时器的超时信号到_check 槽函数（每次超时触发一次状态检查）
        self._timer.timeout.connect(self._check)
        # _interval: 检查间隔时间（毫秒），默认 1000ms（即每秒检查一次）
        self._interval = 1000

    def set_interval(self, ms: int):
        """设置检查间隔时间

        参数：
            ms: 检查间隔（毫秒），默认 1000ms（1 秒）
                 值越小检测越频繁但 CPU 占用越高，值越大检测延迟越高

        示例：
            # 设置为每 500ms 检查一次（适合需要快速响应的场景）
            monitor.set_interval(500)

            # 设置为每 5 秒检查一次（适合不常启动的目标进程）
            monitor.set_interval(5000)

        注意：
            - 修改间隔后，如果定时器正在运行会先停止再重新以新间隔启动
            - 不建议设置过小（如<100ms），避免过度占用 CPU 资源
        """
        self._interval = ms
        if self._timer.isActive():
            self._timer.stop()
            self._timer.start(self._interval)

    def start_monitoring(self):
        """开始监测目标进程的运行状态

        功能说明：
            - 启动定时器，按配置间隔周期性检查目标进程是否存在
            - 首次启动时会立即执行一次检查，获取初始状态并触发信号
            - 如果目标进程当前已运行，会立即发射 started 信号

        使用场景：
            - 监测某个工具是否正常运行（如 Python 解释器、Notepad 等）
            - 当进程异常退出时能及时通知主界面更新 UI 或清理资源
        """
        if not self._timer.isActive():
            # 先立即执行一次检查，获取初始状态（避免首次启动时漏掉已运行的进程）
            self._check()
            # 启动定时器，按配置的间隔进行周期性检测
            self._timer.start(self._interval)

    def stop_monitoring(self):
        """停止监测目标进程

        功能说明：
            - 停止定时器，不再周期性检查进程状态
            - 已缓存的状态保持不变（如需刷新状态请调用 is_running()）
            - 如需彻底清理可调用 deleteLater() 销毁对象

        使用场景：
            - 用户取消监测时调用
            - 程序退出前释放资源
        """
        if self._timer.isActive():
            self._timer.stop()

    def _check(self):
        """检查目标进程的运行状态（内部方法，由定时器触发）

        功能流程：
            1. 调用_is_process_running() 检查目标进程是否存在
            2. 与缓存的_last_state_比较，判断是否发生状态变化
            3. 如果状态发生变化，更新缓存并发射相应信号：
               - 进程启动/恢复：发射 started(status=True) + status_changed(True)
               - 进程关闭：发射 stopped + status_changed(False)
            4. 状态无变化时不发射任何信号（避免频繁通知）

        调用时机：
            - 首次启动监测后立即调用一次（获取初始状态）
            - 定时器每 _interval_毫秒触发一次（默认 1 秒）
        """
        current_running = self._is_process_running()
        # 如果当前状态与缓存状态不一致，说明进程状态发生了变化
        if current_running != self._is_running:
            self._is_running = current_running  # 更新缓存的最新状态

            if current_running:  # 进程已启动（或重新出现）
                # 获取进程的详细信息（进程名和 PID），用于发射 started 信号
                proc_info = self._get_process_info()
                if proc_info:
                    name, pid = proc_info
                    # 发射 started 信号，通知主界面进程已启动
                    self.started.emit(name, pid)
                else:
                    # 理论上不可能发生（_is_process_running()返回 True 时应该能获取到信息）
                    # 但作为防御性编程保留此分支
                    self.started.emit(self.process_name or "Unknown", 0)

                # 状态变化：从停止变为运行（或从未知变为已知运行）
                self.status_changed.emit(True)
            else:  # 进程已关闭
                # 发射 stopped 信号，通知主界面目标进程已退出
                self.stopped.emit(self.process_name or "Unknown")
                # 状态变化：从运行变为停止
                self.status_changed.emit(False)

    def _is_process_running(self) -> bool:
        """检查目标进程是否正在运行（内部方法）

        匹配策略：
            1. 如果提供了 pid → 直接通过 PID 判断（最精确）
            2. 否则按 process_name 模糊匹配（不区分大小写）
            3. 如果两者都未提供 → 返回 False

        异常处理：
            - psutil.NoSuchProcess: 进程已不存在，跳过继续检查其他进程
            - psutil.AccessDenied: 无权限查看进程信息，跳过继续检查

        性能说明：
            - 每次调用会遍历所有进程列表（psutil.process_iter）
            - 频繁调用时可通过 PID 方式避免遍历开销
        """
        if self.pid is not None:
            # ----- 方式 1：按 PID 判断（精确） -----
            # psutil.pid_exists() 直接检查指定 PID 对应的进程是否存在
            # 优点：无需遍历进程列表，速度快
            # 适用场景：已知目标进程的 PID 号时优先使用此方式
            return psutil.pid_exists(self.pid)

        elif self.process_name:
            # ----- 方式 2：按进程名匹配（模糊） -----
            # 将目标进程名转为小写，用于后续不区分大小写的比较
            name_lower = self.process_name.lower()

            # psutil.process_iter() 遍历当前系统中所有进程
            for proc in psutil.process_iter(['name']):
                try:
                    # 检查进程信息中的 name 字段是否存在且匹配（忽略大小写）
                    if proc.info['name'] and proc.info['name'].lower() == name_lower:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # 进程已消失或权限不足，跳过继续检查下一个
                    continue

            # 遍历完所有进程仍未找到匹配的，返回 False
            return False
        else:
            # ----- 无匹配条件 -----
            # 既没有 PID 也没有进程名，无法判断任何进程是否运行
            return False

    def _get_process_info(self):
        """获取当前运行的目标进程详细信息（内部方法）

        返回值：
            - 如果找到匹配的进程：返回 (进程名，PID) 元组
            - 如果未找到：返回 None

        使用场景：
            - 用于 started/stopped 信号发射时附带进程信息
            - 主界面显示或日志记录用途

        注意：
            - 如果通过 PID 传入则直接获取该进程的 info
            - 如果通过进程名匹配则遍历查找（与_is_process_running_逻辑一致）
        """
        if self.pid is not None:
            # ----- 通过 PID 获取进程信息 -----
            try:
                proc = psutil.Process(self.pid)  # 创建 Process 对象
                # 返回进程名和 PID（注意：proc.name() 可能返回带有完整路径的名字）
                return proc.name(), self.pid
            except psutil.NoSuchProcess:
                # PID 对应的进程已不存在
                return None

        elif self.process_name:
            # ----- 通过进程名获取信息 -----
            name_lower = self.process_name.lower()

            for proc in psutil.process_iter(['name', 'pid']):
                try:
                    # 查找进程名匹配且大小写不敏感的进程
                    if proc.info['name'] and proc.info['name'].lower() == name_lower:
                        return proc.info['name'], proc.info['pid']

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            # 未找到匹配的进程，返回 None
            return None

        return None  # 无匹配条件时直接返回 None（调用者不会走到这里）

    def is_running(self) -> bool:
        """获取目标进程的当前运行状态

        特点：
            - 实时查询，不依赖任何缓存（直接调用_is_process_running_重新检查）
            - 适合在主界面显示状态按钮、刷新列表等需要最新状态的场景
            - 比直接看内部变量更可靠（即使定时器挂了也能正确判断）

        返回：
            True: 目标进程当前正在运行
            False: 目标进程未运行或未指定监测条件
        """
        return self._is_process_running()

    def get_current_info(self):
        """获取当前匹配进程的详细信息（如果存在）

        返回值：
            - 如果找到匹配的进程：返回 (进程名，PID) 元组
            - 否则返回 None

        与 is_running() 的区别：
            - is_running() 只返回布尔值（是否运行）
            - get_current_info() 返回详细信息，可用于显示"Python.exe (PID:1234)"这样的文本
            - 两者都是实时查询，不依赖缓存

        使用示例：
            info = monitor.get_current_info()
            if info:
                name, pid = info
                status_label.setText(f"{name} (PID: {pid})")
        """
        return self._get_process_info()