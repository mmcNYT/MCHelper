# -*- coding: utf-8 -*-
"""音效试听：assets/CommandGenerator/sounds/<id 按点分段>/<id>.ogg。

音效 id（如 block.stone.hit）的 ogg 存于
assets/CommandGenerator/sounds/block/stone/hit.ogg
（gen_sound_assets.py 生成）。

播放器用 **QMediaPlayer**（FFmpeg 后端）而非 QSoundEffect ——
QSoundEffect 只支持 wav/aiff（实测 ogg 报 Error decoding source），
Minecraft 的音效全部是 ogg/vorbis。

FFmpeg 诊断日志（Input #0/vorbis 时间戳提示）已在 main.py 入口以
QT_LOGGING_RULES=qt.multimedia.*=false 静音 —— 那些是无害的解码器
噪声，不影响出声；必须在 QApplication 创建前设置才生效。
"""
from __future__ import annotations

import os

_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "assets", "CommandGenerator", "sounds")

_player = None      # 复用单实例（QMediaPlayer 创建开销大）
_output = None


def sound_file(sid: str) -> str | None:
    """音效 id -> ogg 路径（无文件返回 None）。"""
    if not sid:
        return None
    base = sid.removeprefix("minecraft:")
    p = os.path.join(_DIR, *base.split(".")) + ".ogg"
    return p if os.path.isfile(p) else None


def _ensure_player():
    """惰性创建播放器（首次调用时初始化 QtMultimedia）。"""
    global _player, _output
    if _player is None:
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
