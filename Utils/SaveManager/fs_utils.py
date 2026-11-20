# -*- coding: utf-8 -*-
"""文件系统操作助手：回收站删除、资源管理器打开。

仅 Windows 平台（项目运行环境）。删除走回收站（SHFileOperation FO_DELETE +
FOF_ALLOWUNDO），符合项目「不直接永久删除」约定；调用前由上层自行二次确认。
"""
from __future__ import annotations

import ctypes
import os

from ctypes import wintypes

# SHFileOperation wFunc
_FO_DELETE = 3
# fFlags
_FOF_ALLOWUNDO = 0x0040        # 撤销（进回收站，而非永久删除）
_FOF_NOCONFIRMATION = 0x0010   # 不弹系统确认（由上层 QMessageBox 确认）
_FOF_NOERRORUI = 0x0400        # 不弹系统错误对话框（错误由上层报告）


def move_to_recycle_bin(path: str) -> tuple[bool, str]:
    """把文件/文件夹移入回收站。返回 (是否成功, 错误信息)。"""
    if not isinstance(path, str) or not path:
        return False, "路径无效"
    if not os.path.exists(path):
        return False, "路径不存在"

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.WORD),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    # pFrom 是双 null 结尾的路径列表（单路径 = path + '\0\0'）
    op = SHFILEOPSTRUCTW()
    op.wFunc = _FO_DELETE
    op.pFrom = path + "\0\0"
    op.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_NOERRORUI
    try:
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except OSError as exc:
        return False, f"调用失败：{exc}"
    if result != 0:
        return False, f"系统错误码 {result}"
    if op.fAnyOperationsAborted:
        return False, "操作被中止"
    return True, ""


def open_in_explorer(path: str) -> None:
    """在资源管理器中打开文件/文件夹（选中打开用 /select,）。"""
    if not os.path.exists(path):
        return
    try:
        os.startfile(path)  # type: ignore[attr-defined]  # Windows only
    except OSError:
        pass
