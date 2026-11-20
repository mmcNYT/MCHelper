# -*- coding: utf-8 -*-
"""读 level.dat，提取存档元信息 + 解析 region 目录布局。

level.dat 是 gzip 压缩的 NBT：根 compound "" → 子 compound "Data"。
NBT 解析复用 Utils/SeedReverser/structure_models.parse_nbt（纯 Python
通用解析器，跳过根名返回 root payload = {"Data": {...}}）。这里采用
惰性导入，避免为读一个小文件而引入该模块顶部的 numpy 等重依赖。

种子说明：1.16~1.21 的 level.dat 在 Data.WorldGenSettings.seed 存种子；
26.2 起该字段被移除（Data 里已无 WorldGenSettings）。种子当前不展示，
仅提取留存，留待日后与种子破解器联动。
"""
from __future__ import annotations

import gzip
import os
import struct

from Utils.SaveManager.save_info import SaveInfo

# ---- region 目录布局（老格式 vs 1.21.5+/26.x 新格式）----
# 新格式：dimensions/minecraft/<dim>/region（根 DIM-1/DIM1 废弃为空）
_NEW_DIM_LAYOUT = {
    "overworld": os.path.join("dimensions", "minecraft", "overworld", "region"),
    "nether": os.path.join("dimensions", "minecraft", "the_nether", "region"),
    "end": os.path.join("dimensions", "minecraft", "the_end", "region"),
}
# 老格式（1.18~1.21.4）：主世界在根 region/，下界 DIM-1/region，末地 DIM1/region
_OLD_DIM_LAYOUT = {
    "overworld": "region",
    "nether": os.path.join("DIM-1", "region"),
    "end": os.path.join("DIM1", "region"),
}


def _parse_nbt(data: bytes) -> dict:
    """惰性复用 SeedReverser 的 parse_nbt；返回 root payload（{"Data": {...}}）。"""
    from Utils.SeedReverser.structure_models import parse_nbt
    return parse_nbt(data)


def _read_level_dat_bytes(world_path: str) -> bytes | None:
    """读 level.dat 原始字节；缺失时回退 level_dat_old。

    不在此处解压——parse_nbt 内部会做 gzip.decompress，传原始字节即可
    （避免双重解压）。
    """
    for fname in ("level.dat", "level.dat_old"):
        path = os.path.join(world_path, fname)
        if os.path.isfile(path):
            try:
                with open(path, "rb") as f:
                    return f.read()
            except OSError:
                continue
    return None


def _extract_data(world_path: str) -> dict | None:
    """解析 level.dat，返回内层 Data compound（dict）；失败返回 None。"""
    raw = _read_level_dat_bytes(world_path)
    if raw is None:
        return None
    try:
        root = _parse_nbt(raw)
    except (ValueError, struct.error, IndexError, KeyError, OSError):
        return None
    if not isinstance(root, dict):
        return None
    data = root.get("Data", root)
    return data if isinstance(data, dict) else None


def region_dir_for(world_path: str, dimension: str = "overworld") -> str | None:
    """解析某维度的 region 目录路径（返回实际存在的那个；都不存在返回 None）。

    优先新格式（dimensions/minecraft/<dim>/region），回退老格式
    （region / DIM-1/region / DIM1/region）。按目录是否存在判定，不靠
    版本号硬编码，兼容同一版本两种布局的过渡期存档。
    """
    new_rel = _NEW_DIM_LAYOUT.get(dimension)
    old_rel = _OLD_DIM_LAYOUT.get(dimension)
    candidates = []
    if new_rel:
        candidates.append(os.path.join(world_path, new_rel))
    if old_rel:
        candidates.append(os.path.join(world_path, old_rel))
    for cand in candidates:
        if os.path.isdir(cand):
            return cand
    return None


def has_terrain_data(region_dir: str | None) -> bool:
    """region 目录下是否存在任意 .mca 区块文件。"""
    if not region_dir or not os.path.isdir(region_dir):
        return False
    try:
        for entry in os.scandir(region_dir):
            if entry.name.endswith(".mca"):
                return True
    except OSError:
        return False
    return False


def read_save_info(world_path: str, source: str = "") -> SaveInfo | None:
    """从一个世界文件夹读取 SaveInfo；level.dat 不可读时返回 None。"""
    data = _extract_data(world_path)
    if data is None:
        return None

    name = data.get("LevelName")
    if not isinstance(name, str) or not name:
        name = os.path.basename(world_path.rstrip("\\/")) or world_path

    version = data.get("Version")
    version = version if isinstance(version, dict) else {}
    version_name = version.get("Name") if isinstance(version.get("Name"), str) else ""
    try:
        data_version = int(version.get("Id") or 0)
    except (TypeError, ValueError):
        data_version = 0

    try:
        game_type = int(data.get("GameType") or 0)
    except (TypeError, ValueError):
        game_type = 0
    try:
        last_played = int(data.get("LastPlayed") or 0)
    except (TypeError, ValueError):
        last_played = 0

    # 种子：1.16~1.21 在 WorldGenSettings.seed；26.2 起无此字段 → None
    seed = None
    wgs = data.get("WorldGenSettings")
    if isinstance(wgs, dict) and "seed" in wgs:
        try:
            seed = int(wgs["seed"])
        except (TypeError, ValueError):
            seed = None

    icon_path = os.path.join(world_path, "icon.png")
    if not os.path.isfile(icon_path):
        icon_path = None

    overworld_region = region_dir_for(world_path, "overworld")

    return SaveInfo(
        path=world_path,
        name=name,
        version_name=version_name,
        data_version=data_version,
        game_type=game_type,
        last_played=last_played,
        seed=seed,
        icon_path=icon_path,
        overworld_region_dir=overworld_region,
        has_terrain=has_terrain_data(overworld_region),
        source=source,
    )


def write_level_name(world_path: str, new_name: str) -> tuple[bool, str]:
    """外科式修改 level.dat 的 LevelName（只改这一个字符串字段，其余字节不动）。

    不做整体 NBT 重序列化——parse_nbt 丢失了整数字段宽度（Byte/Short/Int/
    Long 都变 Python int），整体重写可能写错类型损坏存档。这里改为在解压
    后的字节流里定位 LevelName 字段（tag=8 string + 名长 9 + "LevelName" +
    2 字节串长 + 串值），只替换串值后重新 gzip，其余字节原样保留，风险最低。

    写入前把原 level.dat 备份为 level.dat.bak。返回 (是否成功, 错误信息)。
    """
    if not isinstance(new_name, str) or not new_name.strip():
        return False, "名称不能为空"
    new_name = new_name.strip()
    if len(new_name.encode("utf-8")) > 0xFFFF:
        return False, "名称过长（超过 65535 字节）"

    raw = _read_level_dat_bytes(world_path)
    if raw is None:
        return False, "未找到 level.dat"
    try:
        data = gzip.decompress(raw)
    except (OSError, EOFError, gzip.BadGzipFile):
        return False, "level.dat 解压失败"

    # 字段编码：\x08(string tag) + \x00\x09(名长 9) + "LevelName" + \x00\xLL(串长) + 值
    prefix = b"\x08\x00\x09LevelName"
    idx = data.find(prefix)
    if idx < 0:
        return False, "未找到 LevelName 字段（非标准 level.dat？）"
    str_len = struct.unpack_from(">H", data, idx + len(prefix))[0]
    val_start = idx + len(prefix) + 2
    val_end = val_start + str_len
    if val_end > len(data):
        return False, "LevelName 字段长度异常"

    new_val = new_name.encode("utf-8")
    new_field = (prefix + struct.pack(">H", len(new_val)) + new_val)
    new_data = data[:idx] + new_field + data[val_end:]
    new_raw = gzip.compress(new_data)

    level_path = os.path.join(world_path, "level.dat")
    bak_path = os.path.join(world_path, "level.dat.bak")
    try:
        if os.path.isfile(level_path):
            try:
                shutil_copy2(level_path, bak_path)
            except OSError:
                pass  # 备份失败不阻塞写入
        with open(level_path, "wb") as f:
            f.write(new_raw)
    except OSError as exc:
        return False, f"写入失败：{exc}"
    return True, ""


def shutil_copy2(src: str, dst: str) -> None:
    """复制文件（保留属性），用于写前备份。"""
    import shutil
    shutil.copy2(src, dst)
