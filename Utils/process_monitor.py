import psutil
from PySide6.QtCore import QObject, Signal, QTimer, QThread

class ProcessMonitor(QObject):
    """
    实时监测指定进程的运行状态。
    当进程启动或关闭时，分别发射 started 和 stopped 信号。
    """
    # 信号：进程启动时发射，附带进程名和 PID
    started = Signal(str, int)
    # 信号：进程关闭时发射，附带进程名（最后一次获取的）
    stopped = Signal(str)
    # 信号：状态变化时发射（可选），附带当前状态 True/False
    status_changed = Signal(bool)

    def __init__(self, process_name=None, pid=None, parent=None):
        """
        :param process_name: 要监测的进程名（如 "notepad.exe"），不区分大小写
        :param pid: 要监测的进程 PID（如果提供，则优先使用 PID）
        :param parent: 父对象
        """
        super().__init__(parent)
        self.process_name = process_name
        self.pid = pid
        self._is_running = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check)
        # 默认间隔 1000 毫秒（1 秒）
        self._interval = 1000

    def set_interval(self, ms: int):
        """设置检查间隔（毫秒）"""
        self._interval = ms
        if self._timer.isActive():
            self._timer.stop()
            self._timer.start(self._interval)

    def start_monitoring(self):
        """开始监测"""
        if not self._timer.isActive():
            # 先立即执行一次检查，获取初始状态
            self._check()
            self._timer.start(self._interval)

    def stop_monitoring(self):
        """停止监测"""
        if self._timer.isActive():
            self._timer.stop()

    def _check(self):
        """
        检查进程是否存在，与上次状态比较，变化时发射信号。
        """
        current_running = self._is_process_running()
        if current_running != self._is_running:
            self._is_running = current_running
            if current_running:
                # 获取进程详细信息（进程名和 PID）
                proc_info = self._get_process_info()
                if proc_info:
                    name, pid = proc_info
                    self.started.emit(name, pid)
                else:
                    # 理论上不可能，但以防万一
                    self.started.emit(self.process_name or "Unknown", 0)
                self.status_changed.emit(True)
            else:
                self.stopped.emit(self.process_name or "Unknown")
                self.status_changed.emit(False)

    def _is_process_running(self) -> bool:
        """检查目标进程是否正在运行"""
        if self.pid is not None:
            # 按 PID 查找
            return psutil.pid_exists(self.pid)
        elif self.process_name:
            # 按进程名查找（不区分大小写）
            name_lower = self.process_name.lower()
            for proc in psutil.process_iter(['name']):
                try:
                    if proc.info['name'] and proc.info['name'].lower() == name_lower:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return False
        else:
            # 未指定任何条件
            return False

    def _get_process_info(self):
        """获取当前匹配的进程名和 PID（用于发射信号）"""
        if self.pid is not None:
            try:
                proc = psutil.Process(self.pid)
                return proc.name(), self.pid
            except psutil.NoSuchProcess:
                return None
        elif self.process_name:
            name_lower = self.process_name.lower()
            for proc in psutil.process_iter(['name', 'pid']):
                try:
                    if proc.info['name'] and proc.info['name'].lower() == name_lower:
                        return proc.info['name'], proc.info['pid']
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return None
        return None

    def is_running(self) -> bool:
        """获取当前状态（实时查询，不依赖缓存）"""
        return self._is_process_running()

    def get_current_info(self):
        """获取当前匹配进程的名称和 PID（如果存在）"""
        return self._get_process_info()