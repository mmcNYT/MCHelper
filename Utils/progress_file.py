import os

class ProgressFile:
    """
    包装文件对象，每次 read() 后报告本次读取的字节数（增量）。
    用于 zipfile 压缩时获得实时进度。
    """
    def __init__(self, file_path, progress_callback):
        self.file = open(file_path, 'rb')
        self.callback = progress_callback  # 接收参数：本次读取的字节数

    def read(self, size=-1):
        data = self.file.read(size)
        if data:
            chunk_size = len(data)
            if self.callback:
                self.callback(chunk_size)   # 报告增量
        return data

    def close(self):
        self.file.close()

    def fileno(self):
        return self.file.fileno()   # zipfile 需要

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()