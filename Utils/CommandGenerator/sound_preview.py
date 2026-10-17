# -*- coding: utf-8 -*-
"""音效试听：assets/sounds/<id 按点分段>/<id>.ogg + QSoundEffect。

音效 id（如 block.stone.hit）的 ogg 存于
assets/sounds/block/stone/hit.ogg（gen_sound_assets.py 生成）。
"""
from __future__ import annotations

import os

_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "assets", "sounds")

_effect = None      # 复用单个 QSoundEffect，避免反复创建


def sound_file(sid: str) -> str | None:
    """音效 id -> ogg 路径（无文件返回 None）。"""
    if not sid:
        return None
    base = sid.removeprefix("minecraft:")
    p = os.path.join(_DIR, *base.split(".")) + ".ogg"
    return p if os.path.isfile(p) else None


def play_sound(sid: str, volume: float = 1.0) -> bool:
    """播放音效；成功 True。无文件/后端不可用返回 False。"""
    global _effect
    p = sound_file(sid)
    if not p:
        return False
    try:
        from PySide6.QtMultimedia import QSoundEffect
        from PySide6.QtCore import QUrl
        if _effect is None:
            _effect = QSoundEffect()
        _effect.setSource(QUrl.fromLocalFile(p))
        _effect.setVolume(volume)
        _effect.play()
        return True
    except Exception:                        # noqa: BLE001
        return False
