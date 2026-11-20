# -*- coding: utf-8 -*-
"""扫描存档目录，产出 SaveInfo 列表。

兼容本项目的多版本分散布局（存档不在根 saves/，而是按版本分目录）：
    <root>/saves/<世界>/level.dat
    <root>/versions/<版本>/saves/<世界>/level.dat
另兼容直接把 root 当单个 saves 文件夹指向的用法。

<root> 默认为 MC 安装根目录（项目其余模块硬编码的同一路径），可在设置里
改用 saves_dir 覆盖。
"""
from __future__ import annotations

import os

from Utils.SaveManager.level_dat import read_save_info
from Utils.SaveManager.save_info import SaveInfo

# 项目其余模块（block_textures / block_names_cn）硬编码的 MC 根目录，作默认
_DEFAULT_MC_ROOT = r"C:\maomaochongD\.minecraft\.minecraft"


def default_saves_root() -> str:
    """默认存档扫描根（MC 安装根目录）。

    优先项目硬编码的 MC 根（存在即用），否则回退标准 ~/.minecraft。
    """
    if os.path.isdir(_DEFAULT_MC_ROOT):
        return _DEFAULT_MC_ROOT
    return os.path.expanduser(r"~\.minecraft")


def _iter_world_dirs(root: str):
    """产出 (世界文件夹绝对路径, 来源标签)。

    依次尝试 <root>/saves、<root>/versions/*/saves；都没有则把 root
    本身当作 saves 文件夹扫。用绝对路径去重，避免同一世界被列两次。
    """
    seen: set[str] = set()

    def _emit(world_dir: str, source: str):
        if world_dir not in seen:
            seen.add(world_dir)
            yield world_dir, source

    # 1) <root>/saves/<世界>
    saves = os.path.join(root, "saves")
    if os.path.isdir(saves):
        for name in sorted(os.listdir(saves)):
            w = os.path.join(saves, name)
            if os.path.isdir(w) and os.path.isfile(os.path.join(w, "level.dat")):
                yield from _emit(w, "saves")

    # 2) <root>/versions/<版本>/saves/<世界>
    versions = os.path.join(root, "versions")
    if os.path.isdir(versions):
        for vname in sorted(os.listdir(versions)):
            vsaves = os.path.join(versions, vname, "saves")
            if not os.path.isdir(vsaves):
                continue
            for name in sorted(os.listdir(vsaves)):
                w = os.path.join(vsaves, name)
                if os.path.isdir(w) and os.path.isfile(
                        os.path.join(w, "level.dat")):
                    yield from _emit(w, f"versions/{vname}/saves")

    # 3) 兜底：root 本身就是一个 saves 文件夹
    if not seen and os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            w = os.path.join(root, name)
            if os.path.isdir(w) and os.path.isfile(
                    os.path.join(w, "level.dat")):
                yield from _emit(w, os.path.basename(root.rstrip("\\/")) or root)


def scan_saves(root: str) -> list[SaveInfo]:
    """扫描 root 下所有存档，返回 SaveInfo 列表（按名称升序）。

    level.dat 不可读的世界跳过，不影响其余存档。
    """
    results: list[SaveInfo] = []
    for world_dir, source in _iter_world_dirs(root):
        info = read_save_info(world_dir, source)
        if info is not None:
            results.append(info)
    results.sort(key=lambda s: s.name.lower())
    return results
