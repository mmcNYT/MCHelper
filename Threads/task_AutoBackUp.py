import os
import zipfile
from datetime import datetime
from PySide6.QtCore import QRunnable
from Utils.AutoBackUp.signals_AutoBackUp import backup_bus

# =============================================================================
# BackupTask 类：备份任务的线程执行类
# 功能说明：
#   - 继承自 QRunnable，用于在多线程环境中执行备份操作
#   - 将单个文件或文件夹压缩到目标 ZIP 文件
#   - 通过信号槽机制向主界面汇报进度和状态
# =============================================================================


class BackupTask(QRunnable):
    """
    备份任务的可运行对象

    功能说明：
        - 封装单个文件的压缩逻辑
        - 支持单文件和文件夹的递归备份
        - 使用分块读取方式避免内存溢出
        - 通过 backup_bus 信号向主线程汇报状态
    """

    def __init__(self, task_id: int, file_path: str, dest_dir: str):
        """初始化备份任务

        参数：
            task_id: 任务的唯一索引标识，用于在主界面区分多个并发任务
            file_path: 源文件或文件夹的绝对路径（单文件则直接压缩，文件夹则递归）
            dest_dir: 目标 ZIP 文件的存放目录

        属性：
            self.task_id: 任务 ID 编号
            self.file_path: 待备份的文件/文件夹完整路径
            self.dest_dir: 压缩文件输出的根目录
            self.zip_name: 生成的 ZIP 文件名（格式：原文件名_时间戳.zip）
        """
        super().__init__()
        self.task_id = task_id
        self.file_path = file_path
        self.dest_dir = dest_dir

        # ----- 生成目标文件名：原文件名（不含后缀）_YYMMDD_HHMMSS.zip -----
        base_name = os.path.basename(file_path)                 # 例如 "data.txt"
        name_without_ext = os.path.splitext(base_name)[0]       # "data"
        timestamp = datetime.now().strftime("%y%m%d_%H%M%S")    # "240808_153045"
        self.zip_name = f"{name_without_ext}_{timestamp}.zip"   # "data_240808_153045.zip"

    def run(self):
        """执行备份任务的主逻辑

        功能说明：
            - 向主界面发送"任务开始"信号
            - 创建 ZIP 文件对象
            - 遍历源目录下的所有文件并压缩
            - 逐块读写避免大文件内存溢出
            - 发送进度和完成信号更新 UI

        异常处理：
            - 捕获所有异常并在完成信号中汇报错误信息
        """
        try:
            filename = os.path.basename(self.file_path)
            backup_bus.task_started.emit(self.task_id, filename)

            # 生成目标 ZIP 文件名（若为文件夹则用文件夹名）
            base_name = os.path.basename(self.file_path)
            name_without_ext = base_name if not os.path.isfile(self.file_path) else os.path.splitext(base_name)[0]
            timestamp = datetime.now().strftime("%y%m%d_%H%M%S")
            zip_name = f"{name_without_ext}_{timestamp}.zip"
            dest_path = os.path.join(self.dest_dir, zip_name)

            with zipfile.ZipFile(dest_path, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
                if os.path.isfile(self.file_path):
                    # --- 处理单个文件（原逻辑） ---
                    # 获取文件大小用于进度跟踪
                    total_size = os.path.getsize(self.file_path)
                    processed = 0
                    # 以二进制只读模式打开源文件
                    with open(self.file_path, 'rb') as src_file:
                        # 以二进制写入模式创建 ZIP 中的文件条目
                        with zipf.open(os.path.basename(self.file_path), 'w',) as dest_file:
                            # 循环分块读取文件内容（每块 8KB）
                            while True:
                                chunk = src_file.read(8192)
                                if not chunk:
                                    break
                                # 将数据块写入 ZIP 文件
                                dest_file.write(chunk)
                                processed += len(chunk)
                                # 向主界面发送进度信号（每次复制的字节数）
                                backup_bus.task_progress.emit(self.task_id, len(chunk))
                else:
                    # --- 处理文件夹（递归备份） ---
                    # 设置根目录为待备份的文件夹路径
                    root_dir = self.file_path
                    # os.walk() 递归遍历文件夹及所有子目录
                    for dirpath, dirnames, filenames in os.walk(root_dir):
                        # 遍历当前目录下所有文件
                        for fname in filenames:
                            full_path = os.path.join(dirpath, fname)
                            # 计算相对路径：相对于文件夹根目录，保留目录结构（如 folder/subfolder/file.txt）
                            arcname = os.path.relpath(full_path, start=root_dir)
                            # 以二进制模式打开源文件
                            with open(full_path, 'rb') as src_file:
                                # 将文件写入 ZIP 的相对路径位置
                                with zipf.open(arcname, 'w') as dest_file:
                                    # 分块读取并写入 ZIP（同样使用 8KB 缓冲）
                                    while True:
                                        chunk = src_file.read(8192)
                                        if not chunk:
                                            break
                                        dest_file.write(chunk)
                                        # 发送进度信号
                                        backup_bus.task_progress.emit(self.task_id, len(chunk))

            # 所有文件压缩完成，向主界面发送任务完成信号（成功）
            backup_bus.task_finished.emit(self.task_id, True, f"{zip_name} 备份成功")

        except Exception as e:
            backup_bus.task_finished.emit(self.task_id, False, f"{zip_name} 备份失败: {str(e)}")