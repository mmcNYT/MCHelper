# -*- coding: utf-8 -*-
"""音效试听：assets/CommandGenerator/sounds/<id 按点分段>/<id>.ogg。

音效 id（如 block.stone.hit）的 ogg 存于
assets/CommandGenerator/sounds/block/stone/hit.ogg
（gen_sound_assets.py 生成）。

播放器用 **QMediaPlayer**（FFmpeg 后端）而非 QSoundEffect ——
QSoundEffect 只支持 wav/aiff（实测 ogg 报 Error decoding source），
Minecraft 的音效全部是 ogg/vorbis。

FFmpeg 诊断日志（Input #0/vorbis 时间戳提示）是无害的解码器噪声，
不影响出声。静音机制（实测有效与无效的结论）：
  - **有效**：Qt 的 FFmpeg 后端把 av_log 路由进
    `qt.multimedia.ffmpeg` Qt 日志 category —— 运行时调
    QLoggingCategory.setFilterRules("qt.multimedia.*=false")
    即可全静音（QApplication 之后调用也生效）。
  - **有效**：main.py 入口设 QT_LOGGING_RULES 环境变量
    （必须**强制覆盖**而非 setdefault —— 外部环境残留值会让
    setdefault 静默跳过，GUI 仍刷日志的实测根因）。
  - **无效**：msvcrt._dup2 重绑 fd 2 —— FFmpeg/PySide6 各自带
    独立 CRT，其内部 stderr 不走 Python 进程的 fd 表（实测
    13 行日志照刷）。已移除该方案。
"""
from __future__ import annotations

import os

_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "assets", "CommandGenerator", "sounds")

_player = None      # 复用单实例（QMediaPlayer 创建开销大）
_output = None
_rule_set = False   # 运行时日志过滤规则是否已设置


def sound_file(sid: str) -> str | None:
    """音效 id -> ogg 路径（无文件返回 None）。"""
    if not sid:
        return None
    base = sid.removeprefix("minecraft:")
    p = os.path.join(_DIR, *base.split(".")) + ".ogg"
    return p if os.path.isfile(p) else None


def _silence_media_logs():
    """运行时静音 qt.multimedia category（FFmpeg 的 Input/vorbis 全走这里）。

    QLoggingCategory.setFilterRules 在 QApplication 之后调用也生效，
    不依赖环境变量 —— 覆盖「从 IDE/脚本启动时环境变量缺失或被
    外部残留值顶掉」的全部情况。
    """
    global _rule_set
    if _rule_set:
        return
    try:
        from PySide6.QtCore import QLoggingCategory
        QLoggingCategory.setFilterRules("qt.multimedia.*=false")
        _rule_set = True
    except Exception:                        # noqa: BLE001
        pass


def _ensure_player():
    """惰性创建播放器（首次调用时初始化 QtMultimedia）。

    加载前先静音日志 —— Qt FFmpeg 后端加载时会打版本横幅。
    """
    global _player, _output
    if _player is None:
        _silence_media_logs()
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
        _player = QMediaPlayer()
        _output = QAudioOutput()
        _player.setAudioOutput(_output)
        _output.setVolume(1.0)
    return _player


def play_sound(sid: str, volume: float = 1.0) -> bool:
    """播放音效；成功 True。无文件/后端异常返回 False。"""
    p = sound_file(sid)
    if not p:
        return False
    try:
        from PySide6.QtCore import QUrl
        mp = _ensure_player()
        # 上一个还没放完：直接停了换源（点按即切，傻瓜式）
        mp.stop()
        _output.setVolume(max(0.0, min(1.0, volume)))
        mp.setSource(QUrl.fromLocalFile(p))
        mp.play()
        return True
    except Exception:                        # noqa: BLE001
        return False
