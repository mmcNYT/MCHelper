from PySide6.QtCore import QObject, Signal


class BackupSignals(QObject):
    """全局信号总线，用于所有备份任务与主线程通信"""
    # 任务开始信号：参数 (任务ID, 文件名)
    task_started = Signal(int, str)

    # 任务进度信号：参数 (任务ID, 已压缩字节数) —— 注意这里是增量，不是百分比
    task_progress = Signal(int, int)

    # 任务完成信号：参数 (任务ID, 是否成功, 消息)
    task_finished = Signal(int, bool, str)

# 全局单例
backup_bus = BackupSignals()