# -*- coding: utf-8 -*-
"""region 网格 → 俯视 RGB 图（复用 MapPreviewer 逐方块渲染管线）。

SaveManager 读存档 region 得到每列顶层方块/高度/群系，喂给 MapPreviewer 的
render_from_blocks（JourneyMap 配色 + 影调 + 坡度光照）——与 MapPreviewer
唯一差别就是数据来源（这里读存档 region，MapPreviewer 走 cubiomes 地形生成）。
方块色表（jm_palette）、坡度光照、派生方块贴图 fallback 全部公用 MapPreviewer
（jm_colors / block_textures），不再自维护一套颜色表。

纯计算、不碰 Qt，可在后台线程调用。
"""
from __future__ import annotations

import numpy as np

from Utils.MapPreviewer.block_render import _SEA, render_from_blocks
from Utils.MapPreviewer.jm_colors import build_block_palette
from Utils.Public.biome_names import resolve_biome
from Utils.Public.map_render.chunk_render import (MIN_Y, build_chunk,
                                                  surface_biome,
                                                  surface_with_overlay,
                                                  _AIR_LIKE)
from Utils.Public.map_render.region_reader import RegionFile
from Utils.SeedReverser.biome_noise import BIOME_ID

try:  # native 加速路径（_region_render.pyd，语义对齐下方纯 Python 实现）；
      # 缺失/加载失败自动降级纯 Python，对拍测试可置 world_render._NATIVE = None
    from Utils.Public.map_render._native import _region_render as _NATIVE
except Exception:
    _NATIVE = None

REGION_BLOCKS = 512   # 32 chunk × 16 方块
_CHUNK = 16

# 未生成/虚空列（surface_block 无顶层方块）的纯黑，与 terrain_view 一致
_VOID_RGB = np.array([0, 0, 0], dtype=np.uint8)

# 水面顶块（MOTION_BLOCKING 含流体，海洋/河流/湖泊顶层返回水）
_FLUID_TOP = {"minecraft:water", "minecraft:bubble_column"}
# 找海床时跳过的方块（水、空气与水中植物）
_BED_SKIP = {"minecraft:air", "minecraft:water", "minecraft:kelp",
             "minecraft:kelp_plant", "minecraft:seagrass",
             "minecraft:tall_seagrass", "minecraft:bubble_column"}
# 深水（10 格内无海床）水面列的高度：< _SEA-1 走纯水分支
_DEEP_WATER_Y = 54


def _seabed(built: dict, lx: int, lz: int, wy: int, limit: int = 10):
    """从水面下向下找海床 (block_name, y)；limit 格内没有返回 None（深水）。

    JM 水色链的语义是水列 heights=海床 y（_n=62-heights 出 7 级深浅），
    n>7 全为纯水色，故扫描 10 格足够覆盖浅水段。
    """
    blocks = built["blocks"]
    y = wy - 1
    for _ in range(limit):
        if y < MIN_Y:
            return None
        sec_y = y // 16
        lk = blocks.get(sec_y)
        if lk is not None:
            nm = lk(y - sec_y * 16, lz, lx)
            if nm and nm not in _BED_SKIP:
                return nm, y
        y -= 1
    return None


class LightPack:
    """SaveManager 的轻量渲染 pack：动态收录 region 遇到的方块，复用 MapPreviewer
    的 JourneyMap 方块色表（build_block_palette，block_textures 磁盘缓存命中快）
    + 群系 key 表。render_from_blocks 需要的字段齐备。
    """

    def __init__(self):
        self.block_names: list[str] = []
        self.name2bid: dict[str, int] = {}
        self.jm_palette: dict[str, tuple] = {}
        self.id2key: dict[int, str] = {}
        for k, v in BIOME_ID.items():
            self.id2key.setdefault(v, "minecraft:" + k)

    def ensure_blocks(self, names) -> None:
        """批量收录新方块（一次 build_block_palette，避免逐块重建磁盘缓存）。"""
        new = [n for n in names if n and n not in self.name2bid]
        if not new:
            return
        pal = build_block_palette(new)
        for name in new:
            self.name2bid[name] = len(self.block_names)
            self.block_names.append(name)
            if name in pal:
                self.jm_palette[name] = pal[name]

    def to_pack(self) -> dict:
        return {"block_names": self.block_names, "name2bid": self.name2bid,
                "jm_palette": self.jm_palette, "id2key": self.id2key}


def _render_region_native(region_file: RegionFile, lpack: LightPack,
                          chunks: list[tuple[int, int]],
                          hillshade: bool) -> np.ndarray:
    """native 路径：C++ 完成 NBT 解码 + 逐列扫描，Python 只做映射与配色。

    语义对齐 render_region_to_rgb 纯 Python 实现：两边收录集均为
    surface ∪ 换床海床名（浅水列水色混真实海床块色），bid-0 兜底不再
    触发，输出确定性逐位一致（此前海床名缺席时兜底到 block_names[0]，
    set 迭代序跨进程随机，同一 region 两次运行颜色都不同）。
    """
    raws: list[bytes] = []
    coords: list[tuple[int, int]] = []
    for (lx, lz) in chunks:
        raw = region_file.read_chunk_raw(lx, lz)
        if raw is None:
            continue   # 损坏/不可解压：native 端无此槽位 → 反向虚空标记覆盖
        raws.append(raw)
        coords.append((lx, lz))
    coords_arr = np.asarray(coords, dtype=np.int32).reshape(len(coords), 2)
    out = _NATIVE.render_region(
        raws, coords_arr, MIN_Y, _SEA, _DEEP_WATER_Y,
        sorted(_AIR_LIKE), sorted(_BED_SKIP), sorted(_FLUID_TOP))

    heights = out["heights"]
    void_mask = out["void"].astype(bool)
    block_names = list(out["block_names"])
    if block_names:
        # 收录全部名字（含换床海床名）——纯 Python 第一遍同样收集
        # surface ∪ 换床海床名（浅水列水色要混真实海床块色），两边集合
        # 一致、bid-0 兜底不再触发，输出确定性一致
        lpack.ensure_blocks(block_names)
        lut = np.array([lpack.name2bid.get(n, 0) for n in block_names],
                       dtype=np.int32)
        blocks = lut[out["blocks"]]
        bio_ids = np.array([resolve_biome(n.split(":")[-1]) or 0
                            for n in out["biome_names"]], dtype=np.int32)
        bio_n = out["biomes"]
        biome_grid = np.where(bio_n >= 0, bio_ids[np.maximum(bio_n, 0)],
                              0).astype(np.int32)
        # 透明层（栅栏/玻璃等）：native 端已穿透并记录最高透明名，这里
        # 映射成 bid（-1=无）；render_from_blocks 按 0.4 alpha 叠色。
        # disp（显示高度）：透明格用透明顶 y（1 格落差参与坡度 bevel）
        ov = out["overlay"]
        if (ov >= 0).any():
            ov_lut = np.array([lpack.name2bid.get(n, -1)
                               for n in block_names], dtype=np.int32)
            ov_bids = np.full((REGION_BLOCKS, REGION_BLOCKS), -1,
                              dtype=np.int32)
            m = ov >= 0
            ov_bids[m] = ov_lut[ov[m]]
            disp_heights = out["disp"].astype(np.float32)
        else:
            ov_bids = None
            disp_heights = None
    else:
        # 无实体方块（空 region/全部不可读）：与纯 Python 的空 palette 护栏一致
        blocks = np.zeros((REGION_BLOCKS, REGION_BLOCKS), dtype=np.int32)
        biome_grid = np.zeros((REGION_BLOCKS, REGION_BLOCKS), dtype=np.int32)
        ov_bids = None
        disp_heights = None

    # 真水掩码：native 逐列判定「表面扫描顶块本身是流体」（水/气泡柱）。
    # 不能用工件 heights < _SEA 代替：正常地形下低于海平面的露天表面
    # 几乎都被水层填充碰巧成立，但超平坦/空岛的地表 y≈-58 上方是空气，
    # 会被整片误判成水（实测超平坦全图蓝）。
    wet = out["wet"].astype(bool)
    if not lpack.block_names:
        return np.full((REGION_BLOCKS, REGION_BLOCKS, 3), _VOID_RGB,
                       dtype=np.uint8)
    rgb = render_from_blocks(blocks, heights, biome_grid, lpack.to_pack(),
                             0, 0, hillshade, wet, overlay=ov_bids,
                             disp_heights=disp_heights, void=void_mask)
    if void_mask.any():
        rgb[void_mask] = _VOID_RGB
    return rgb


def render_region_to_rgb(region_file: RegionFile, lpack: LightPack,
                         limit: int | None = None,
                         hillshade: bool = False) -> np.ndarray:
    """渲染一个 region 为 (512,512,3) uint8 RGB（复用 MapPreviewer 渲染管线）。

    native 路径优先（_region_render.pyd）：C++ 完成 NBT 解码与逐列扫描
    （cProfile 实测这两块占 ~6s/region），配色留在 Python。缺失或异常
    自动降级纯 Python 两遍实现（语义基准）。
    两遍实现：先解析所有 chunk 收集顶层方块名并批量收录进 lpack，再逐列填
    blocks/heights/biome_grid，最后交 render_from_blocks 配色 + 影调 + 坡度。
    仅渲染 Status=full 的区块：noise/carvers/features/light 等半生成区块
    已填噪音地形与液体但无地表规则/装饰，渲染会出均匀蓝水带，一律按虚空。
    """
    chunks = region_file.existing_chunks()
    if limit is not None:
        chunks = chunks[:limit]
    if _NATIVE is not None and chunks:
        try:
            return _render_region_native(region_file, lpack, chunks, hillshade)
        except Exception as exc:
            # 降级纯 Python（截断输出：TypeError 的 repr 会把全部 chunk 字节
            # 打出来，实测 240MB+）
            print(f"[world_render] native 渲染失败，降级纯 Python："
                  f"{type(exc).__name__}: {str(exc)[:300]}")

    # ---- 第一遍：解析 + 收集方块名，批量收录 ----
    parsed: list[tuple[int, int, dict]] = []
    names: set[str] = set()
    for (lx, lz) in chunks:
        chunk = region_file.read_chunk(lx, lz)
        if chunk is None:
            continue
        st = str(chunk.get("Status") or "").rsplit(":", 1)[-1]
        if st and st != "full":
            continue   # 半生成区块：无地表规则/装饰，按虚空处理
        built = build_chunk(chunk)
        parsed.append((lx, lz, built))
        for z in range(_CHUNK):
            for x in range(_CHUNK):
                name, wy, ov, _ovy = surface_with_overlay(built, x, z)
                if not name:
                    continue
                names.add(name)
                if ov:
                    names.add(ov)
                if name in _FLUID_TOP:
                    # 换床后的海床名也进收录表：浅水列（55..61）水色按
                    # (15-n)/15 权重混入海床块色（block_render 浅水透底），
                    # 若海床名缺席会兜底到 block_names[0]——set 迭代序，
                    # 跨进程随机（实测同一 region 两次运行出两种颜色）
                    bed = _seabed(built, x, z, wy)
                    if bed is not None and bed[1] < _SEA - 1:
                        names.add(bed[0])
    lpack.ensure_blocks(names)

    # ---- 第二遍：逐列填 blocks/heights/biome ----
    blocks = np.zeros((REGION_BLOCKS, REGION_BLOCKS), dtype=np.int32)
    heights = np.full((REGION_BLOCKS, REGION_BLOCKS), -64, dtype=np.int16)
    biome_grid = np.zeros((REGION_BLOCKS, REGION_BLOCKS), dtype=np.int32)
    overlay = np.full((REGION_BLOCKS, REGION_BLOCKS), -1, dtype=np.int32)
    disp_h = np.full((REGION_BLOCKS, REGION_BLOCKS), -64, dtype=np.float32)
    void_mask = np.zeros((REGION_BLOCKS, REGION_BLOCKS), dtype=bool)
    # 真水掩码（对齐 native）：表面顶块是流体才算水列。不能用
    # heights < _SEA 代替——超平坦/空岛地表低于海平面却无水，会整片误蓝
    wet = np.zeros((REGION_BLOCKS, REGION_BLOCKS), dtype=bool)
    # 反向标记：凡不在解析集合里的位置（无文件条目/读取失败/半生成）整 chunk
    # 按虚空。其列 heights=-64 会被水色链误判成极深海（实测无条目区块漏成
    # 93% 假蓝），必须显式标记，最后统一填纯黑。
    parsed_set = {(lx, lz) for (lx, lz, _b) in parsed}
    n_chunks = REGION_BLOCKS // _CHUNK
    for lx in range(n_chunks):
        for lz in range(n_chunks):
            if (lx, lz) not in parsed_set:
                void_mask[lz * _CHUNK:(lz + 1) * _CHUNK,
                          lx * _CHUNK:(lx + 1) * _CHUNK] = True
    for (lx, lz, built) in parsed:
        bx0 = lx * _CHUNK
        bz0 = lz * _CHUNK
        for z in range(_CHUNK):
            pz = bz0 + z
            for x in range(_CHUNK):
                name, wy, ov, ov_y = surface_with_overlay(built, x, z)
                if not name:
                    void_mask[pz, bx0 + x] = True   # 未生成/虚空列
                    continue
                # wet 先于换床记录：换床只改 name/wy，流体判定用原顶块
                wet[pz, bx0 + x] = name in _FLUID_TOP
                if name in _FLUID_TOP:
                    # 水列换成海床：JM 水色链按 heights=海床 y 出群系水色
                    # + 7 级深浅（水列 heights 给水面 y=62 会因 wet 语义
                    # 整片漏成 palette 平涂）。深水（10 格内无海床）压到
                    # 54 走纯水分支；海平面以上的湖床不动（palette 平涂）。
                    bed = _seabed(built, x, z, wy)
                    if bed is not None and bed[1] < _SEA - 1:
                        name, wy = bed
                    elif bed is None:
                        wy = _DEEP_WATER_Y
                blocks[pz, bx0 + x] = lpack.name2bid.get(name, 0)
                heights[pz, bx0 + x] = wy if wy is not None else -64
                if ov:
                    overlay[pz, bx0 + x] = lpack.name2bid.get(ov, -1)
                    disp_h[pz, bx0 + x] = float(ov_y)
                else:
                    disp_h[pz, bx0 + x] = float(heights[pz, bx0 + x])
                bname = surface_biome(built, x, z)
                if bname:
                    bid_b = resolve_biome(bname.split(":")[-1])
                    if bid_b is not None:
                        biome_grid[pz, bx0 + x] = bid_b

    if not lpack.block_names:
        # 整个 region 无实体方块（空壳区块/未生成）：全虚空返回，避免空
        # palette 在 _colorize_blocks 里 lut 越界崩溃
        return np.full((REGION_BLOCKS, REGION_BLOCKS, 3), _VOID_RGB,
                       dtype=np.uint8)
    rgb = render_from_blocks(blocks, heights, biome_grid, lpack.to_pack(),
                             0, 0, hillshade, wet,
                             overlay=overlay if (overlay >= 0).any() else None,
                             disp_heights=(disp_h
                                           if (overlay >= 0).any()
                                           else None),
                             void=void_mask)
    # 未生成/虚空列填纯黑，避免误用 block_names[0] 的颜色污染画面
    if void_mask.any():
        rgb[void_mask] = _VOID_RGB
    return rgb


def render_region_to_png(region_file: RegionFile, lpack: LightPack, path: str,
                         limit: int | None = None, hillshade: bool = False) -> str:
    """渲染 region 并保存为 PNG（QImage 编码），返回路径。"""
    from PySide6.QtGui import QImage
    arr = render_region_to_rgb(region_file, lpack, limit=limit, hillshade=hillshade)
    h, w = arr.shape[0], arr.shape[1]
    img = QImage(arr.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888)
    img = img.copy()   # 脱离 numpy 缓冲
    img.save(path, "PNG")
    return path
