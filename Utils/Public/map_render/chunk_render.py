# -*- coding: utf-8 -*-
"""chunk 内渲染信息解码：heightmap、顶层方块、surface biome。

仅 1.18+ 格式约定：
- Heightmaps.MOTION_BLOCKING：打包长整型数组，9 位/项、7 项/long、共 37 long；
  值为该列最顶「阻挡移动或含流体」方块的 Y（±1 不确定，故向下扫几格兜底）。
  不用 WORLD_SURFACE（顶层非空气）：花/草丛/藤蔓等无碰撞植物会被当成地表，
  渲染成像素噪点（实测 r.-20.-18 有 4719 列顶在 vine/short_grass/fern 上）。
- sections[]：每项含 Y（=底界 Y/16）、block_states{palette, data}、biomes{palette,data}。
- block_states.data：palette 索引打包长整型，位宽 = max(4, ceil(log2(palette_len)))；
  块在节内索引 = ly*256 + lz*16 + lx（ly/lz/lx ∈ 0..15）。
- biomes（每节）：4×4×4 网格，位宽同上；索引 = (by*4 + bz)*4 + bx。
"""
from __future__ import annotations

# 1.18+ 世界最低 Y（区块从 -64 起）。heightmap 值 = (最高阻挡移动方块 Y + 1) - MIN_Y，
# 即相对世界底部偏移再 +1；故最高阻挡移动方块 Y = heightmap 值 + MIN_Y - 1。
MIN_Y = -64


def _palette_bits(n: int) -> int:
    """palette 索引位宽：至少 4 位，可容纳 n 个条目。"""
    b = 4
    while (1 << b) < n:
        b += 1
    return b


def decode_heightmap(longs: list[int]) -> list[int]:
    """WORLD_SURFACE 打包数组 → 256 个地表 Y（列序 z*16+x）。"""
    bits = 9
    per_long = 64 // bits   # 7
    mask = (1 << bits) - 1
    n = len(longs)
    out = [0] * 256
    for i in range(256):
        li = i // per_long
        if li < n:
            out[i] = (longs[li] >> ((i % per_long) * bits)) & mask
    return out


def _entry_name(entry) -> str:
    """palette 条目 → 名字（block 是 {Name,Properties?} dict；biome 是字符串）。"""
    if isinstance(entry, dict):
        return entry.get("Name") or ""
    return str(entry)


def _entry_props(entry) -> dict:
    """palette 条目 → Properties dict（无则空 dict）。形状方块（台阶/楼梯/
    门等）的几何还原依赖这些属性；地表渲染只用 Name，3D 精确预览才需要。"""
    if isinstance(entry, dict):
        p = entry.get("Properties")
        if isinstance(p, dict):
            return p
    return {}


# 无视觉/非实体方块：不作为地表返回（barrier 不可见，显示其下方方块）
_AIR_LIKE = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air",
             "minecraft:barrier"}


def build_block_lookup(sec: dict):
    """从一个 section 构造 (sec_y, lookup(ly,lz,lx)->block_name)；空节返回 None。"""
    if not isinstance(sec, dict):
        return None
    sec_y = sec.get("Y")
    bs = sec.get("block_states", {})
    pal = bs.get("palette", []) if isinstance(bs, dict) else []
    if not pal:
        return None
    dat = bs.get("data") if isinstance(bs, dict) else None
    if not dat:
        # 单方块节（无 data）：palette 只有 1 项
        n0 = _entry_name(pal[0])
        return (sec_y, lambda ly, lz, lx: n0)
    # MC palette 打包：每 long 放 floor(64/bits) 个完整项（不跨 long），
    # 末位剩余 bits 不用。例：bits=5 → 12 项/long → ceil(4096/12)=342 long。
    b = _palette_bits(len(pal))
    mask = (1 << b) - 1
    per_long = 64 // b

    def lookup(ly: int, lz: int, lx: int) -> str:
        idx = ly * 256 + lz * 16 + lx
        li = idx // per_long
        if li >= len(dat):
            return ""
        boff = (idx % per_long) * b
        v = (dat[li] >> boff) & mask
        return _entry_name(pal[v]) if v < len(pal) else ""
    return (sec_y, lookup)


def build_block_state_lookup(sec: dict):
    """从 section 构造 (sec_y, lookup(ly,lz,lx) -> (name, props))；空节返回 None。

    与 build_block_lookup 同打包/位宽逻辑，但 lookup 返回完整方块状态
    （名字 + Properties dict），供 3D 精确预览还原台阶/楼梯/门等形状。
    """
    if not isinstance(sec, dict):
        return None
    sec_y = sec.get("Y")
    bs = sec.get("block_states", {})
    pal = bs.get("palette", []) if isinstance(bs, dict) else []
    if not pal:
        return None
    dat = bs.get("data") if isinstance(bs, dict) else None

    def lookup(ly: int, lz: int, lx: int):
        idx = ly * 256 + lz * 16 + lx
        li = idx // per_long
        if li >= len(dat):
            return ("", {})
        boff = (idx % per_long) * b
        v = (dat[li] >> boff) & mask
        if v >= len(pal):
            return ("", {})
        return (_entry_name(pal[v]), _entry_props(pal[v]))

    if not dat:
        # 单方块节（无 data）：palette 只有 1 项
        n0 = _entry_name(pal[0])
        p0 = _entry_props(pal[0])
        return (sec_y, lambda ly, lz, lx: (n0, p0))

    b = _palette_bits(len(pal))
    mask = (1 << b) - 1
    per_long = 64 // b
    return (sec_y, lookup)


def build_biome_lookup(field: dict):
    """从一个节的 biomes 字段构造 lookup(by,bz,bx)->biome_name；无数据返回常量。

    注意 biome 的序列化位宽与 block 不同：block 有 4 位下限
    （PalettedContainer.BLOCK_STATE），biome（SECTION_PALETTE）无下限、
    就是 ceillog2(palette)——1.20.1/26.2 数据实证 palette=2 -> bits=1 ->
    64 值装 1 long。若按 4 bits 解，每 long 只解出 16 值，后 48 值越界
    判空 -> 群系缺失 -> 默认 ocean 绿草（雪原存档"绿色草方块"根因）。
    """
    pal = field.get("palette", [])
    if not pal:
        return None
    dat = field.get("data")
    if not dat:
        n0 = _entry_name(pal[0])
        return lambda by, bz, bx: n0
    b = max(1, (len(pal) - 1).bit_length())
    mask = (1 << b) - 1
    per_long = 64 // b

    def lookup(by: int, bz: int, bx: int) -> str:
        idx = (by * 4 + bz) * 4 + bx
        li = idx // per_long
        if li >= len(dat):
            return ""
        boff = (idx % per_long) * b
        v = (dat[li] >> boff) & mask
        return _entry_name(pal[v]) if v < len(pal) else ""
    return lookup


def build_chunk(chunk: dict) -> dict:
    """预处理一个 chunk，返回便于逐列查询的字典。"""
    hm = chunk.get("Heightmaps", {})
    ws = None
    if isinstance(hm, dict):
        ws = hm.get("MOTION_BLOCKING") or hm.get("WORLD_SURFACE")
    heightmap = decode_heightmap(ws) if isinstance(ws, list) and ws else [0] * 256
    blocks: dict = {}
    biomes: dict = {}
    states: dict = {}   # 完整方块状态（Name+Properties），3D 精确预览用
    for sec in chunk.get("sections", []) or []:
        if not isinstance(sec, dict):
            continue
        sec_y = sec.get("Y")
        blk = build_block_lookup(sec)
        if blk is not None:
            blocks[blk[0]] = blk[1]
        stt = build_block_state_lookup(sec)
        if stt is not None:
            states[stt[0]] = stt[1]
        bio = build_biome_lookup(sec.get("biomes", {}))
        if bio is not None:
            biomes[sec_y] = bio
    return {
        "heightmap": heightmap,
        "blocks": blocks,
        "states": states,
        "biomes": biomes,
        "xPos": chunk.get("xPos", 0),
        "zPos": chunk.get("zPos", 0),
    }


def surface_block(built: dict, lx: int, lz: int) -> tuple[str | None, int | None]:
    """列 (lx,lz) ∈ 0..15 的地表方块（阻挡移动/含流体，花茎等无碰撞植物已由
    高度图跳过）。返回 (block_name, world_y)。

    注意：这是悬停用的实体顶块语义（不穿透栅栏/玻璃等非完整方块）；
    渲染用的穿透语义见 surface_with_overlay（对齐 JourneyMap）。
    """
    col = lz * 16 + lx
    # heightmap 值 → 最高阻挡移动方块 Y（见 MIN_Y 注释）；从该 Y 向下扫几格兜底
    sy = built["heightmap"][col] + MIN_Y - 1
    blocks = built["blocks"]
    for wy in range(sy, sy - 5, -1):
        sec_y = wy // 16
        lk = blocks.get(sec_y)
        if lk is None:
            continue
        ly = wy - sec_y * 16
        name = lk(ly, lz, lx)
        if name and name not in _AIR_LIKE:
            return name, wy
    return None, None


def is_transparent_block(name: str) -> bool:
    """JourneyMap 0.4 透明家族（VanillaBlockHandler 6.0.8 反编译实证）：
    FenceBlock/FenceGateBlock/Glass/StainedGlass/StainedGlassPane/
    IronBarsBlock 全部 alpha=0.4 + Transparency 旗标（mapTransparency 默认
    开）。仅 minecraft: 前缀（mod 方块按约定不处理）。"""
    if not name.startswith("minecraft:") or len(name) <= 10:
        return False
    return (name.endswith("_fence") or name.endswith("_fence_gate")
            or name.endswith("_stained_glass")
            or name.endswith("_stained_glass_pane")
            or name in ("minecraft:glass", "minecraft:glass_pane",
                        "minecraft:iron_bars", "minecraft:tinted_glass"))


# JM VanillaBlockHandler：class_2302(CropBlock) → Crop flag，mapCrops 默认
# true → 作物作为地表渲染（NoShadow）。vanilla 的 CropBlock 子类就这四种；
# 甜菜丛/甘蔗等属 Plant，mapPlants 默认 false → 整块 Ignore 透视到下方，
# 不在此列。
_CROP_BLOCKS = {"minecraft:wheat", "minecraft:carrots",
                "minecraft:potatoes", "minecraft:beetroots"}


def surface_with_overlay(built: dict, lx: int, lz: int):
    """渲染专用地表扫描（对齐 native surface_scan / JM getBlockHeight 的
    mapTransparency 语义）：

    - 从 heightmap 顶向下全列扫描（透明方块可叠任意高，5 格窗不够）；
    - air_like 连续 5 格 → 列虚空；
    - 透明家族命中 → 记录最高透明名（overlay）及其 y 继续向下；
    - 地表 = 下方首个普通方块。

    返回 (name, wy, overlay_name|None, overlay_y|None)；虚空列 →
    (None, None, None, None)。heights/地表语义由此取下方地面 → 栅栏/
    玻璃不产生 +1 台阶，水色链/wet 语义保持；透明色由 render_from_blocks
    按 0.4 alpha 叠加，坡度 bevel 用 overlay_y（1 格落差 → 立体感）。
    悬停语义（surface_block）不受影响：仍返回实体顶块本身。
    """
    col = lz * 16 + lx
    sy = built["heightmap"][col] + MIN_Y - 1
    blocks = built["blocks"]
    overlay = None
    ov_y = None
    air_run = 0
    for wy in range(sy, MIN_Y - 1, -1):
        sec_y = wy // 16
        lk = blocks.get(sec_y)
        if lk is None:
            continue
        ly = wy - sec_y * 16
        name = lk(ly, lz, lx)
        if not name or name in _AIR_LIKE:
            air_run += 1
            if air_run >= 5:
                return None, None, None, None
            continue
        if is_transparent_block(name):
            if overlay is None:
                overlay = name
                ov_y = wy
            continue
        # JM mapCrops 默认开：作物作为地表渲染。MOTION_BLOCKING 高度图
        # 不含作物（非阻挡方块），命中地表后向上探测作物层（作物 1 格
        # 高，2 格余量）；遇空气/透明/其他实体块即停。
        hit_name, hit_y = name, wy
        for k in (1, 2):
            cy = hit_y + k
            csec = cy // 16
            lk2 = blocks.get(csec)
            if lk2 is None:
                break
            cn = lk2(cy - csec * 16, lz, lx)
            if cn not in _CROP_BLOCKS:
                break
            hit_name, hit_y = cn, cy
        return hit_name, hit_y, overlay, ov_y
    return None, None, None, None


def surface_biome(built: dict, lx: int, lz: int) -> str | None:
    """列 (lx,lz) surface 处的 biome 名（取地表方块的 biome 网格）。"""
    col = lz * 16 + lx
    sy = built["heightmap"][col] + MIN_Y - 1
    sec_y = sy // 16
    lk = built["biomes"].get(sec_y)
    if lk is None:
        for dy in (-1, 1):
            lk = built["biomes"].get(sec_y + dy)
            if lk is not None:
                break
    if lk is None:
        return None
    by = (sy - sec_y * 16) // 4
    return lk(by, lz // 4, lx // 4)


def extract_structure_starts(built: dict) -> list[dict]:
    """chunk NBT structures.starts → 锚点列表（BB 西北角近似 /locate 锚点）。

    Java 版 1.18+ chunk NBT 内嵌 structures.starts.<类型>.Children[].BB，
    BB = [minX, minY, minZ, maxX, maxY, maxZ]（世界坐标）。
    BB 西北角（minX, minZ）≈ /locate 返回的生成锚点（95% 结构准确，
    monument 例外——其锚点是中心）。精确锚点需查结构类型偏移表
    （ANCHOR_BB_OFFSETS）反推；当前版本用 BB 西北角直接近似。

    返回：
        [{"type": "village", "x": 1234, "z": -567, "bb": [...]}, ...]
    """
    starts = built.get("structures", {}).get("starts", {})
    out = []
    for struct_type, data in starts.items():
        if not isinstance(data, dict):
            continue
        for child in data.get("Children", []):
            bb = child.get("BB")
            if bb and len(bb) >= 6:
                out.append({
                    "type": struct_type,
                    "x": bb[0],   # minX = 锚点（近似，monument 例外）
                    "z": bb[2],   # minZ
                    "bb": bb,     # 完整包围盒（备用）
                })
    return out
