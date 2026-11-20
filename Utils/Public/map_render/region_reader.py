# -*- coding: utf-8 -*-
"""Anvil region 文件（.mca）读取。

格式：
- 8 KB 头：前 4 KB = 1024 个 chunk 偏移表（每 4 字节：3 字节扇区偏移 +
  1 字节扇区数，偏移 0 表示该槽位无 chunk）；后 4 KB = 时间戳表。
- chunk 数据：从「扇区偏移 × 4096」起，4 字节长度（含压缩类型字节）+ 1 字节
  压缩类型（1=gzip / 2=zlib / 3=未压缩）+ 压缩的 NBT。

槽位索引（经验证，对拍真实存档）：index = localZ * 32 + localX，
其中 localX = chunkX & 31, localZ = chunkZ & 31。
"""
from __future__ import annotations

import gzip
import os
import struct
import zlib

import numpy as np

from Utils.Public.map_render.nbt import parse_nbt_raw

_SECTOR = 4096


class RegionFile:
    """一个 .mca region 文件（覆盖 32×32 个 chunk = 512×512 方块）。"""

    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as f:
            self._data = f.read()
        # 偏移表：1024 条（每 4 字节：3 字节扇区偏移 + 1 字节扇区数，
        # 偏移 0 = 该槽位无 chunk）。numpy 向量化解析：原 1024 次
        # struct.unpack_from 的 Python 循环在后台线程 GIL 竞争下会被
        # 反复排挤（实测冷打开耗时从几 ms 恶化到 1~3s），C 层一次完成。
        # 文件可能 0 字节/截断（实测 Test 存档有 0 字节 .mca 占位文件）
        # ——不足 4KB 的尾部补零，保证恒有 1024 条。
        head = np.frombuffer(self._data[:_SECTOR].ljust(_SECTOR, b"\x00"),
                             dtype=">u4", count=1024)
        self._offs_np = head >> np.uint32(8)     # 扇区偏移，0 = 无 chunk

    @staticmethod
    def slot_index(cx: int, cz: int) -> int:
        """区域内/全局 chunk 坐标 → 头部槽位索引。"""
        return (cz & 31) * 32 + (cx & 31)

    def chunk_exists(self, cx: int, cz: int) -> bool:
        return self._offs_np[self.slot_index(cx, cz)] != 0

    def existing_chunks(self) -> list[tuple[int, int]]:
        """该 region 内已生成 chunk 的局部坐标列表 [(localX, localZ), ...]。"""
        nz = np.nonzero(self._offs_np)[0]
        return [(int(i) % 32, int(i) // 32) for i in nz]

    def read_chunk(self, cx: int, cz: int) -> dict | None:
        """读取并解析指定 chunk 的 NBT（dict）；不存在/损坏返回 None。"""
        off_sec = int(self._offs_np[self.slot_index(cx, cz)])
        if off_sec == 0:
            return None
        base = off_sec * _SECTOR
        if base + 5 > len(self._data):
            return None
        try:
            length = struct.unpack_from(">I", self._data, base)[0]
            ctype = self._data[base + 4]
            body = self._data[base + 5:base + 4 + length]
            if ctype == 1:
                raw = gzip.decompress(body)
            elif ctype == 2:
                raw = zlib.decompress(body)
            elif ctype == 3:
                raw = body
            else:
                return None
            return parse_nbt_raw(raw)
        except (OSError, ValueError, struct.error, zlib.error, EOFError):
            return None

    def read_chunk_raw(self, cx: int, cz: int) -> bytes | None:
        """读取指定 chunk 的解压后原始 NBT 字节（不解析）；不存在/损坏返回 None。

        native 渲染路径用：zlib 解压留 Python（实测 0.089s/region），
        NBT 解码与逐列扫描交 _region_render.pyd（语义对齐 read_chunk 的
        异常处理——解析失败由 C++ 端按整块虚空处理）。
        """
        off_sec = int(self._offs_np[self.slot_index(cx, cz)])
        if off_sec == 0:
            return None
        base = off_sec * _SECTOR
        if base + 5 > len(self._data):
            return None
        try:
            length = struct.unpack_from(">I", self._data, base)[0]
            ctype = self._data[base + 4]
            body = self._data[base + 5:base + 4 + length]
            if ctype == 1:
                return gzip.decompress(body)
            if ctype == 2:
                return zlib.decompress(body)
            if ctype == 3:
                return body
            return None
        except (OSError, ValueError, struct.error, zlib.error, EOFError):
            return None


def scan_chunk_coords(rdir: str) -> set[tuple[int, int]]:
    """扫描 region 目录：只读每个 .mca 的前 4KB 偏移表（零解压），
    返回已生成 chunk 的全局坐标集合 {(cx, cz), ...}。

    与按文件名扫描（region 级）不同，本函数能区分「region 文件存在
    但只生成了个别 chunk」的情况（tp 指令生成的破碎地形）：region 级
    并查集会把同 region 内的分离小岛误并成一块，chunk 级才能拆开。
    偏移 0 = 该槽位无 chunk（槽位序 = localZ * 32 + localX，同
    RegionFile）；损坏/截断文件按能读到的完整条目数解析，整读失败跳过。
    """
    out: set[tuple[int, int]] = set()
    if not rdir or not os.path.isdir(rdir):
        return out
    for name in os.listdir(rdir):
        if not (name.startswith("r.") and name.endswith(".mca")):
            continue
        parts = name.split(".")
        if len(parts) != 4:
            continue
        try:
            rx, rz = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        try:
            with open(os.path.join(rdir, name), "rb") as f:
                table = f.read(_SECTOR)
        except OSError:
            continue
        # 每项 4 字节 = 3 字节扇区偏移 + 1 字节扇区数；偏移为 0 即空槽
        # （等价 RegionFile 里的 unpack(">I", ...) >> 8 != 0）。整表一次
        # unpack 批量解，避免大存档几十万次逐项 struct/字节索引调用。
        n = len(table) // 4
        if not n:
            continue
        for i, v in enumerate(struct.unpack(f">{n}I", table)):
            if v >= 256:   # 前 3 字节（扇区偏移）非零
                lx = i % 32
                lz = i // 32
                out.add((rx * 32 + lx, rz * 32 + lz))
    return out


# Status 取值形状校验：小写字母/数字/下划线，可选命名空间前缀。
# 覆盖历代已知值（1.20.1 裸名 liquid_carvers、26.x 的 initialize_light
# 等）及未来新增，防长字符串载荷里的字节巧合误判。
_STATUS_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def _is_status_shape(s: str) -> bool:
    ns, sep, name = s.partition(":")
    if not sep:
        ns, name = s, s
    if not ns or not name:
        return False
    return all(c in _STATUS_CHARS for c in ns) and all(
        c in _STATUS_CHARS for c in name)


def _status_from_prefix(data: bytes) -> str | None:
    """在 NBT 解压数据里搜 TAG_String("Status") 字段并取值。

    TAG_String 头 = 类型 0x08 + 名长 0x0006 + "Status"；其后 2 字节大端
    长度 + UTF-8 值。取值不像 Status 名时视为没找到。
    """
    i = data.find(b"\x08\x00\x06Status")
    if i < 0:
        return None
    p = i + 9
    if len(data) < p + 2:
        return None
    n = (data[p] << 8) | data[p + 1]
    val = data[p + 2:p + 2 + n]
    if len(val) != n:
        return None
    s = val.decode("utf-8", "replace")
    return s if _is_status_shape(s) else None


def read_chunk_status(path: str, cx: int, cz: int) -> str | None:
    """读取某 chunk 的 Status（生成阶段），全量解压后搜值，不做 NBT
    对象解析。

    各代写入器字段序不同：1.20.1 把 Status 写在最前（偏移 3），
    1.21.1 写在最后（sections/entities 之后）——部分 inflate 无法覆盖
    大 chunk，直接全量解压（zlib C 级速度，富 chunk ~2-5ms，空壳
    ~0.3ms）再搜 TAG_String("Status")。返回 None = 读不到（偏移无效/
    解压失败），调用方回退整解析兜底。
    """
    ctype = -1
    try:
        with open(path, "rb") as f:
            head = f.read(_SECTOR)
            i = RegionFile.slot_index(cx, cz) * 4
            if len(head) < i + 4:
                return None
            v = struct.unpack_from(">I", head, i)[0]
            off_sec = v >> 8
            if not off_sec:
                return None
            f.seek(off_sec * _SECTOR)
            b4 = f.read(4)
            if len(b4) < 4:
                return None
            length = struct.unpack(">I", b4)[0]
            if length < 2:
                return None
            cb = f.read(1)
            if not cb:
                return None
            ctype = cb[0]
            raw = f.read(length - 1)
            if len(raw) != length - 1:
                return None
    except (OSError, struct.error):
        return None
    if ctype == 2:
        try:
            data = zlib.decompress(raw)
        except zlib.error:
            return None
    elif ctype == 1:
        try:
            data = gzip.decompress(raw)
        except (OSError, EOFError, zlib.error):
            return None
    elif ctype == 3:
        data = raw
    else:
        return None
    return _status_from_prefix(data)


def region_path_for(world_path: str, dimension: str, region_x: int,
                    region_z: int) -> str | None:
    """拼某维度某 region 文件路径（老/新格式兼容；不存在返回 None）。

    新格式（1.21.5+/26.x）：dimensions/minecraft/<dim>/region/r.<rx>.<rz>.mca
    老格式（1.18~1.21.4）：主世界 region/，下界 DIM-1/region/，末地 DIM1/region/
    """
    from Utils.SaveManager.level_dat import region_dir_for
    rdir = region_dir_for(world_path, dimension)
    if not rdir:
        return None
    return os.path.join(rdir, f"r.{region_x}.{region_z}.mca")


# ---------------------------------------------------------------------------
# 结构锚点读取（用于对比 /locate 结果）
# ---------------------------------------------------------------------------

def read_chunk_structures(path: str, cx: int, cz: int) -> list[dict]:
    """读取单 chunk 的结构锚点列表（structures.starts → BB 西北角）。

    返回：
        [{"type": "village", "x": 1234, "z": -567, "bb": [...]}, ...]
    或 None = chunk 不存在/解压失败。

    NBT 路径：chunk["structures"]["starts"][<类型>]["Children"][i]["BB"]
    BB = [minX, minY, minZ, maxX, maxY, maxZ]（世界坐标）
    BB 西北角（minX, minZ）≈ /locate 锚点（95% 准确，monument 例外）。
    """
    from Utils.Public.map_render.chunk_render import build_chunk, extract_structure_starts
    rf = RegionFile(path)
    chunk = rf.read_chunk(cx, cz)
    if chunk is None:
        return None
    built = build_chunk(chunk)
    return extract_structure_starts(built)
