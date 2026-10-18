# -*- coding: utf-8 -*-
"""方块中文译名（从客户端 assets 的官方 zh_cn 语言文件读取）。

数据源：<.minecraft>/assets/indexes/<ver>.json 里 minecraft/lang/zh_cn.json
对应的 objects/<hash前2位>/<hash>。索引版本号越大越新（1.19/17/29/32...），
取可用的最新一份。读取结果按 (语言文件 mtime, 大小) 缓存，避免重复解析。
"""
from __future__ import annotations

import json
import os

# 客户端 assets 根目录（可由调用方覆盖）
_ASSETS = r"C:\maomaochongD\.minecraft\.minecraft\assets"

_LANG: dict[str, str] = {}
_LANG_READY = False

# 索引文件名 -> 版本序号（数字越大越新）
_VER_ORDER = {"1.19": 1, "5": 5, "8": 8, "17": 17, "29": 29, "32": 32}


def _pick_lang_object(assets: str) -> str | None:
    """在 assets/indexes 里挑最新的一份 zh_cn.json 对象路径。"""
    idx_dir = os.path.join(assets, "indexes")
    if not os.path.isdir(idx_dir):
        return None
    best = None          # (version_rank, 修改时间)
    best_path = None
    for fn in os.listdir(idx_dir):
        if not fn.endswith(".json"):
            continue
        rank = _VER_ORDER.get(fn[:-5], 0)
        p = os.path.join(idx_dir, fn)
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        ent = (d.get("objects") or {}).get("minecraft/lang/zh_cn.json")
        if not ent:
            continue
        h = ent.get("hash", "")
        if len(h) < 2:
            continue
        obj = os.path.join(assets, "objects", h[:2], h)
        if not os.path.exists(obj):
            continue
        key = (rank, os.path.getmtime(p))
        if best is None or key > best:
            best = key
            best_path = obj
    return best_path


def load_translations(force: bool = False) -> dict[str, str]:
    """加载并缓存方块译名表（key 为短名，如 'grass_block'）。"""
    global _LANG, _LANG_READY
    if _LANG_READY and not force:
        return _LANG
    _LANG_READY = True
    out: dict[str, str] = {}
    path = _pick_lang_object(_ASSETS)
    if not path:
        _LANG = out
        return out
    try:
        raw = json.load(open(path, encoding="utf-8"))
    except Exception:
        _LANG = out
        return out
    # 只保留方块条目，key 去掉 'block.minecraft.' 前缀
    pre = "block.minecraft."
    for k, v in raw.items():
        if k.startswith(pre) and isinstance(v, str):
            out[k[len(pre):]] = v
    _LANG = out
    return out


def block_cn_name(block_name: str) -> str:
    """方块全名 -> 中文译名；查不到则返回短名本身。"""
    short = (block_name or "").split(":")[-1]
    if not short:
        return ""
    tab = load_translations()
    return tab.get(short, short)
