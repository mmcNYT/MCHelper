# -*- coding: utf-8 -*-
"""settings_config.json 的读写（仅负责 saves_dir 键，保留其余键）。

设置文件与 main_window / tool_Settings 同一份（QStandardPaths.AppConfigLocation
下的 settings_config.json）。这里用「读全量→改单键→写全量」避免覆盖其他设置
（tool_Settings.save_config 目前只写 2 个键，会清掉本文件写的 saves_dir，故其
save_config 也需改为保留其余键，在注册阶段一并处理）。
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QStandardPaths


def config_path() -> str:
    """settings_config.json 全路径（与 tool_Settings.get_config_path 一致）。"""
    config_dir = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    if not config_dir:
        config_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "settings_config.json")


def load_settings() -> dict:
    """读全量设置；文件缺失/损坏返回空 dict。"""
    path = config_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_saves_dir(default: str | None = None) -> str | None:
    """读取用户配置的存档扫描根目录；未设置返回 default（或 None）。"""
    val = load_settings().get("saves_dir")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return default


def save_saves_dir(saves_dir: str) -> None:
    """写入存档扫描根目录（保留其余键）。"""
    update_settings({"saves_dir": saves_dir})


def update_settings(patch: dict) -> None:
    """读全量设置 → 用 patch 覆盖 → 写回（保留其余键）。"""
    data = load_settings()
    data.update(patch)
    path = config_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
