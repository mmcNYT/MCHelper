# -*- coding: utf-8 -*-
"""原始 NBT 解析（无 gzip 解压）。

level.dat 用 SeedReverser.structure_models.parse_nbt（含 gzip）；但 region
里的 chunk 已经按压缩类型（gzip/zlib/未压缩）解压过，需要「解析未压缩
NBT」的版本。这里提供 parse_nbt_raw，返回 root compound（dict）。

标签编码（大端）：
    1 byte  2 short  3 int  4 long  5 float  6 double
    7 byte[]  8 string  9 list  10 compound  11 int[]  12 long[]

compound 用 dict、list 用 list（每项同型）、数值标量用 Python 类型。
"""
from __future__ import annotations

import struct

_TAG_END = 0
_TAG_BYTE = 1
_TAG_SHORT = 2
_TAG_INT = 3
_TAG_LONG = 4
_TAG_FLOAT = 5
_TAG_DOUBLE = 6
_TAG_BYTE_ARRAY = 7
_TAG_STRING = 8
_TAG_LIST = 9
_TAG_COMPOUND = 10
_TAG_INT_ARRAY = 11
_TAG_LONG_ARRAY = 12


def _read_payload(data: bytes, pos: int, tag: int):
    """返回 (value, new_pos)。"""
    if tag == _TAG_BYTE:
        return struct.unpack_from(">b", data, pos)[0], pos + 1
    if tag == _TAG_SHORT:
        return struct.unpack_from(">h", data, pos)[0], pos + 2
    if tag == _TAG_INT:
        return struct.unpack_from(">i", data, pos)[0], pos + 4
    if tag == _TAG_LONG:
        return struct.unpack_from(">q", data, pos)[0], pos + 8
    if tag == _TAG_FLOAT:
        return struct.unpack_from(">f", data, pos)[0], pos + 4
    if tag == _TAG_DOUBLE:
        return struct.unpack_from(">d", data, pos)[0], pos + 8
    if tag == _TAG_BYTE_ARRAY:
        n = struct.unpack_from(">i", data, pos)[0]
        return bytes(data[pos + 4:pos + 4 + n]), pos + 4 + n
    if tag == _TAG_STRING:
        n = struct.unpack_from(">H", data, pos)[0]
        return data[pos + 2:pos + 2 + n].decode("utf-8", "replace"), pos + 2 + n
    if tag == _TAG_LIST:
        et = data[pos]
        n = struct.unpack_from(">i", data, pos + 1)[0]
        pos += 5
        items = []
        for _ in range(max(0, n)):
            v, pos = _read_payload(data, pos, et)
            items.append(v)
        return items, pos
    if tag == _TAG_COMPOUND:
        out: dict = {}
        while True:
            t = data[pos]
            if t == _TAG_END:
                return out, pos + 1
            nl = struct.unpack_from(">H", data, pos + 1)[0]
            name = data[pos + 3:pos + 3 + nl].decode("utf-8", "replace")
            v, pos = _read_payload(data, pos + 3 + nl, t)
            out[name] = v
    if tag == _TAG_INT_ARRAY:
        n = struct.unpack_from(">i", data, pos)[0]
        vals = struct.unpack_from(f">{max(0, n)}i", data, pos + 4)
        return list(vals), pos + 4 + 4 * max(0, n)
    if tag == _TAG_LONG_ARRAY:
        n = struct.unpack_from(">i", data, pos)[0]
        vals = struct.unpack_from(f">{max(0, n)}q", data, pos + 4)
        return list(vals), pos + 4 + 8 * max(0, n)
    raise ValueError(f"未知 NBT 标签类型 {tag} @ {pos}")


def parse_nbt_raw(data: bytes) -> dict:
    """解析未压缩 NBT，返回 root compound（dict）。

    level.dat / chunk 解压后都可用。root 必须是 TAG_Compound（标准 NBT）。
    """
    if not data:
        return {}
    if data[0] != _TAG_COMPOUND:
        raise ValueError("NBT root 不是 TAG_Compound")
    pos = 1
    # 跳过根名（长度 + 字节）
    nl = struct.unpack_from(">H", data, pos)[0]
    pos += 2 + nl
    value, _ = _read_payload(data, pos, _TAG_COMPOUND)
    return value if isinstance(value, dict) else {}
