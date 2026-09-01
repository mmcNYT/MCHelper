import os
import zipfile
from datetime import datetime
from PySide6.QtCore import QRunnable
from Utils.signals_AutoBackUp import backup_bus
from Utils.progress_file import ProgressFile

class BackupTask(QRunnable):
    def __init__(self, task_id: int, file_path: str, dest_dir: str):
        super().__init__()
        self.task_id = task_id
        self.file_path = file_path
        self.dest_dir = dest_dir

        # ----- 生成目标文件名：原文件名（不含后缀）_YYMMDD_HHMMSS.zip -----
        base_name = os.path.basename(file_path)                 # 例如 "data.txt"
        name_without_ext = os.path.splitext(base_name)[0]       # "data"
        timestamp = datetime.now().strftime("%y%m%d_%H%M%S")    # "240808_153045"
        self.zip_name = f"{name_without_ext}_{timestamp}.zip"  # "data_240808_153045.zip"

    def run(self):
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
                    total_size = os.path.getsize(self.file_path)
                    processed = 0
                    with open(self.file_path, 'rb') as src_file:
                        with zipf.open(os.path.basename(self.file_path), 'w',) as dest_file:
                            while True:
                                chunk = src_file.read(8192)
                                if not chunk:
                                    break
                                dest_file.write(chunk)
                                processed += len(chunk)
                                backup_bus.task_progress.emit(self.task_id, len(chunk))
                else:
                    # --- 处理文件夹（新逻辑） ---
                    # 获取文件夹的根目录，用于计算相对路径
                    root_dir = self.file_path
                    for dirpath, dirnames, filenames in os.walk(root_dir):
                        for fname in filenames:
                            full_path = os.path.join(dirpath, fname)
                            # 计算在 ZIP 中的相对路径（保留目录结构）
                            arcname = os.path.relpath(full_path, start=root_dir)
                            # 逐块读取并写入
                            with open(full_path, 'rb') as src_file:
                                with zipf.open(arcname, 'w') as dest_file:
                                    while True:
                                        chunk = src_file.read(8192)
                                        if not chunk:
                                            break
                                        dest_file.write(chunk)
                                        backup_bus.task_progress.emit(self.task_id, len(chunk))

            backup_bus.task_finished.emit(self.task_id, True, f"{zip_name} 备份成功")

        except Exception as e:
            backup_bus.task_finished.emit(self.task_id, False, f"{zip_name} 备份失败: {str(e)}")