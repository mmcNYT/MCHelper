# -*- coding: utf-8 -*-
"""StrongHoldFinder 的剪贴板监听线程。

职责：
    在独立线程中以约 200ms 的间隔轮询 Windows 剪贴板序号
    （GetClipboardSequenceNumber，一次系统调用，不打开剪贴板），
    序号发生变化即认为剪贴板内容更新，向主线程发出 clipboard_changed 信号。

设计说明：
    - Qt 的剪贴板类（QClipboard）只允许在 GUI 线程使用，因此工作线程只调用
      Win32 序号查询；剪贴板的具体内容由主线程在信号槽中用
      QApplication.clipboard() 读取。
    - 轮询序号而非剪贴板内容本身：不打开剪贴板、不与其他程序争抢剪贴板所有权，
      CPU 开销可忽略。
    - 线程启动后第一次轮询只记录基准序号、不发信号，避免把程序启动前
      遗留在剪贴板里的旧内容当作"新变化"。
"""

import sys
import time

from PySide6.QtCore import QThread, Signal

# 仅 Windows 提供剪贴板序号接口；其他平台上线程直接退出，工具退回手动粘贴
_PLATFORM_SUPPORTED = sys.platform == "win32"

# 轮询间隔（秒）：约 200ms，对人手按 F3+C 的节奏足够灵敏，CPU 开销可忽略
_POLL_INTERVAL_S = 0.2

if _PLATFORM_SUPPORTED:
    import ctypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _get_clipboard_sequence = _user32.GetClipboardSequenceNumber
    _get_clipboard_sequence.restype = ctypes.c_ulong
else:
    _get_clipboard_sequence = None


class ClipboardListenerThread(QThread):
    """后台监测剪贴板变化的常驻线程。

    信号：
        clipboard_changed(): 剪贴板序号发生变化（内容可能已更新）。
            槽在主线程执行，读取方式见工具侧 _on_clipboard_changed。

    生命周期：
        常驻运行直到 requestInterruption()；停止延迟不超过约 2 个轮询周期。
    """

    clipboard_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_seq = None  # None 表示尚未记录基准序号

    def run(self):
        """轮询主循环：序号变化即发信号。

        首次轮询只记录基准序号（不触发信号），之后每次序号变化发一次信号。
        若两次变化落在同一个轮询间隔内，只对最新状态发一次信号——
        对人手操作 F3+C 的节奏而言没有影响。
        """
        if not _PLATFORM_SUPPORTED:
            return
        while not self.isInterruptionRequested():
            seq = _get_clipboard_sequence()
            if self._last_seq is not None and seq != self._last_seq:
                self.clipboard_changed.emit()
            self._last_seq = seq
            time.sleep(_POLL_INTERVAL_S)
