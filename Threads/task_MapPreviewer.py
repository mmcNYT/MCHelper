# -*- coding: utf-8 -*-
"""MapPreviewer 后台渲染线程（地图采样 + 结构枚举 + 瓦片增量渲染）。

职责：
    把 MapPreviewer 的计算放进工作线程：
        1. 地形采样：Utils/MapPreviewer/map_sampler.sample_region
           （native 优先，纯 Python 兜底；按行回调进度，行级取消）；
        2. 地图渲染：Utils/MapPreviewer/block_colors
           - MapPreviewerThread：整幅渲染，lod="block"（1 方块 =
             1 像素精细档）或 "cell"（4x4 方块合 1 像素快速档）；
           - TileRenderThread：视口驱动的瓦片批量增量渲染（拖动/
             缩放时只渲染新进入视口的区域，LOD 与主图一致）；
        3. 结构枚举：Utils/Public/structure_map.enumerate_structures
           （21 种结构按维度正向定位 + 群系校验，结构粒度回调进度）。

    工作线程不做任何 UI 操作，只通过信号把进度/结果/错误回主线程：
        progress(qlonglong, qlonglong, str)  统一进度 (done, total, 消息)
        render_finished(object, str)         完整结果 dict + 统计摘要
            —— 刻意不叫 finished：QThread 自带 finished 信号（Qt 内部
               用它管理线程对象生命周期），自定义同名信号会遮蔽它。
            —— 用 object 而非 dict：载荷含 numpy 数组与无符号位模式
               种子，QVariantMap 转换可能触发 shiboken 溢出钳制。
        error(str)                           错误消息

取消：
    主线程调用 request_cancel() 置位后：采样按行尽快返回（丢弃部分
    结果），结构枚举在结构间/区域间尽快退出，最终发出
    render_finished({}, CANCELLED_SUMMARY)。

进度节流：
    native 采样引擎自身按 30ms 批量回调；纯 Python 路径按行回调。
    这里统一再加 0.1s 时间节流，最后一步强制发出保证收尾。
"""

import time

import numpy as np
from PySide6.QtCore import QThread, Signal

from Utils.MapPreviewer.map_sampler import sample_region
from Utils.MapPreviewer.nether_end_sampler import (
    sample_region_nether, sample_region_end)
from Utils.MapPreviewer.block_colors import (render_block_rgb,
                                             render_cell_rgb)
from Utils.Public.structure_map import (available_structures,
                                              enumerate_structures)

# 取消结束时的 render_finished 摘要标记（区别于正常统计摘要）
CANCELLED_SUMMARY = "__cancelled__"

# 进度信号节流间隔（秒）
_PROGRESS_INTERVAL_S = 0.1

# 瓦片边长（方块）：与结构枚举/进度条单位无耦合，仅控制增量粒度
_TILE_BLOCKS = 1024
# 瓦片扩边采样：hillshade = horn 3x3 梯度 + 3x3 平滑两层邻域，
# 单瓦片边界线性外推只是近似（对比强化后曲率残余可见）。采样时
# 四边多采 _TILE_PAD_CELLS 个噪声格（每边 _TILE_PAD_CELLS*4 方块，
# 总宽 +_TILE_PAD_CELLS*8），渲染后裁掉边缘，跨瓦片阴影无缝。
# pad=2：外圈 1 格 horn（外推近似）不进入内区平滑窗口，内区与
# 整图渲染 bit-exact；渲染/采样开销仅 ~3%。
_TILE_PAD_CELLS = 2


class MapPreviewerThread(QThread):
    """后台渲染地图 + 枚举结构的计算线程。

    用法：
        thread = MapPreviewerThread(seed, "1.21", 1024, keys, parent=widget,
                                    dimension="nether")
        thread.progress.connect(...)
        thread.render_finished.connect(...)
        thread.error.connect(...)
        thread.start()
        # 需要取消时：thread.request_cancel()
    """

    progress = Signal("qlonglong", "qlonglong", str)   # done, total, msg
    render_finished = Signal(object, str)              # 结果 dict, summary
    error = Signal(str)                                # 错误消息

    def __init__(self, seed: int, version_key: str, radius_blocks: int,
                 struct_keys=None, parent=None, lod: str = "block",
                 hillshade: bool = False, dimension: str = "overworld"):
        super().__init__(parent)
        self._seed = seed
        self._version_key = version_key
        self._radius = int(radius_blocks)
        # None = 未指定（默认全部可标注结构）；[] = 明确不标任何
        # 结构（未选择结构时纯群系地图），二者不可混同（or None 会把
        # 空列表当全部）
        self._struct_keys = (list(struct_keys)
                             if struct_keys is not None else None)
        self._lod = lod if lod in ("block", "cell") else "block"
        self._hillshade = bool(hillshade)
        self._dimension = (dimension if dimension in ("overworld", "nether",
                                                       "end")
                           else "overworld")
        if self._dimension != "overworld":
            self._lod = "cell"   # 下界/末地数据固定 4方块/像素
        self._cancelled = False
        self._last_emit = 0.0   # 上次 progress 发出时刻（仅工作线程访问）

    def request_cancel(self):
        """请求取消计算（主线程调用；仅置布尔标志，线程安全）。"""
        self._cancelled = True

    def run(self):
        """两阶段主流程：地图采样 → 结构枚举 → 结果 dict。"""
        try:
            self._run_impl()
        except Exception as exc:  # 兜底：任何异常都不能无声吞掉
            self.error.emit(f"渲染线程异常：{exc!r}")

    def _run_impl(self):
        started = time.perf_counter()
        self._last_emit = 0.0

        # ---- 阶段 1：地形采样（主世界 native 优先 / 下界末地 numpy）----
        t0 = time.perf_counter()
        size = self._radius * 2
        if self._dimension == "overworld":
            map_res = sample_region(
                self._seed, self._version_key,
                0, 0, size, size,
                on_progress=self._on_sample_progress,
                cancel=lambda: self._cancelled,
                want_depth=True,        # 水深渐变/恶地色带用（零采样成本）
                want_temp_humid=True,   # 草色 tint 用（零采样成本）
                surface_mode=True,      # 表面层重判：消除高山内部切片误判溶洞
            )
        else:
            dim_sample = (sample_region_nether if self._dimension == "nether"
                          else sample_region_end)
            map_res = dim_sample(
                self._seed, 0, 0, size, size,
                on_progress=self._on_sample_progress,
                cancel=lambda: self._cancelled,
            )
        t_sample = time.perf_counter() - t0
        if self._cancelled or map_res.get("cancelled"):
            self.render_finished.emit({}, CANCELLED_SUMMARY)
            return

        # ---- 阶段 1.5：地图渲染（lod="block" 1方块=1像素精细档 /
        # lod="cell" 4x4方块合1像素快速档，色彩基调一致）----
        t_render0 = time.perf_counter()
        nh = map_res["biomes"].shape[0]
        rows_total = int(map_res.get("rows_done") or nh)

        def on_render(done, total):
            # 渲染进度折算进采样进度段（上限不越界）
            self._emit_progress(min(rows_total,
                                    rows_total * int(done) // max(total, 1)),
                                rows_total, "渲染")

        render_kwargs = dict(
            seed=self._seed,
            origin_bx=int(map_res["origin_bx"]),
            origin_bz=int(map_res["origin_bz"]),
        )
        if self._dimension != "overworld":
            # 下界/末地：采样器按 4方块/像素直接输出 rgb，无需再渲染
            block_rgb = map_res["rgb"]
        elif self._lod == "cell":
            block_rgb = render_cell_rgb(
                map_res["biomes"], map_res.get("temp"), map_res.get("humid"),
                map_res.get("depth"), hillshade=self._hillshade)
        else:
            block_rgb = render_block_rgb(
                map_res["biomes"], map_res.get("temp"), map_res.get("humid"),
                map_res.get("depth"),
                on_progress=on_render, hillshade=self._hillshade,
                **render_kwargs)
        t_render = time.perf_counter() - t_render0
        map_res["rgb"] = block_rgb
        map_res["lod"] = self._lod

        # ---- 阶段 2：结构枚举（结构粒度进度，区域间/结构间取消）----
        t1 = time.perf_counter()
        n_structs = len(self._struct_keys or
                        available_structures(self._version_key,
                                             dimension=self._dimension))
        done_base = rows_total

        def on_struct(done, total, key):
            # 结构粒度回调 → 统一进度（总量 = 采样行数 + 结构数）
            self._emit_progress(done_base + int(done),
                                rows_total + max(total, 1),
                                f"结构 {key}")

        structs = enumerate_structures(
            self._seed, self._version_key,
            (-self._radius, -self._radius, self._radius, self._radius),
            self._struct_keys,
            on_progress=on_struct,
            cancel=lambda: self._cancelled,
            dimension=self._dimension,
        )
        t_struct = time.perf_counter() - t1
        if self._cancelled:
            self.render_finished.emit({}, CANCELLED_SUMMARY)
            return

        result = dict(map_res)
        result["structures"] = structs
        result["radius"] = self._radius
        result["seed"] = self._seed
        result["version"] = self._version_key
        result["dimension"] = self._dimension
        result["t_sample"] = t_sample
        result["t_render"] = t_render
        result["t_struct"] = t_struct

        summary = (f"完成：引擎 {result.get('engine', '?')}"
                   f"｜采样 {t_sample:.2f}s｜渲染 {t_render:.2f}s"
                   f"｜结构 {t_struct:.2f}s"
                   f"｜标记 {len(structs)} 个")
        self.render_finished.emit(result, summary)

    # ---------- 内部 ----------

    def _on_sample_progress(self, done, total, msg):
        """采样进度回调（工作线程）：时间节流后转发为 progress 信号。"""
        self._emit_progress(int(done), int(total), str(msg))

    def _emit_progress(self, done, total, msg):
        now = time.monotonic()
        if done >= total or (now - self._last_emit) >= _PROGRESS_INTERVAL_S:
            self._last_emit = now
            self.progress.emit(done, total, msg)


class StructureLocateThread(QThread):
    """结构定位线程：扩窗搜索离目标点最近的真实生成结构。

    视口驱动的 StructureScanThread 是「给定矩形，一次枚举」；结构
    定位是「目标点周围找最近的」，搜索范围未知，用指数扩窗策略：
    从 512 边长起，每轮把窗扩到 2 倍（围绕目标点居中），直到在该
    结构的典型间距内找到命中（圆形判据，结构锚点到目标点距离
    ≤ 窗半径），此时窗外不可能有更近的实例，必为最近；始终未命中
    则扩到 _LOCATE_MAX_SIDE（8192）为止——与既有增量扫描上限同
    量级（毫秒级），再远交给定位失败提示。

    与 StructureScanThread 同模式：主线程 request_cancel 后枚举在
    区域间尽快退出，迟到结果按 epoch 丢弃；一次提交一次结果。

    信号：
        located(object)  载荷 dict：{struct, name, x, z, biome,
                         target: (tx, tz), dist, searched_side}
                         （未找到时 structures 为空列表，同 payload 键）
        error(str)
    """

    located = Signal(object)
    error = Signal(str)

    # 扩窗起始边长（方块）：512 覆盖末地城/要塞的典型最小间距；
    # 村庄等更密集结构首轮即命中
    _LOCATE_START_SIDE = 512
    # 扩窗上限边长（方块）：与 _SCAN_MAX_SIDE 同源（枚举单次上限）
    _LOCATE_MAX_SIDE = 8192

    def __init__(self, seed: int, version_key: str, struct_key: str,
                 tx: int, tz: int, parent=None,
                 dimension: str = "overworld"):
        super().__init__(parent)
        self._seed = seed
        self._version_key = version_key
        self._struct_key = struct_key
        self._tx = int(tx)
        self._tz = int(tz)
        self._dimension = (dimension if dimension in ("overworld", "nether",
                                                       "end")
                           else "overworld")
        self._cancelled = False

    def request_cancel(self):
        """请求放弃本次定位（主线程调用；仅置布尔标志，线程安全）。"""
        self._cancelled = True

    def run(self):
        try:
            self._run_impl()
        except Exception as exc:  # 兜底：任何异常都不能无声吞掉
            self.error.emit(f"结构定位线程异常：{exc!r}")

    def _run_impl(self):
        best = None
        searched = 0
        side = self._LOCATE_START_SIDE
        while side <= self._LOCATE_MAX_SIDE:
            searched = side
            if self._cancelled:
                return
            half = side // 2
            view = (self._tx - half, self._tz - half,
                    self._tx + half, self._tz + half)
            structs = enumerate_structures(
                self._seed, self._version_key, view, [self._struct_key],
                cancel=lambda: self._cancelled,
                dimension=self._dimension)
            if self._cancelled:
                return
            # 圆形判据取该轮最优：锚点距目标最近（同距取字典序稳定
            # 排序，保证结果可复现）
            cand = sorted(structs,
                          key=lambda st: ((int(st["x"]) - self._tx) ** 2
                                          + (int(st["z"]) - self._tz) ** 2,
                                          int(st["x"]), int(st["z"])))
            if cand:
                bx, bz = int(cand[0]["x"]), int(cand[0]["z"])
                d2 = (bx - self._tx) ** 2 + (bz - self._tz) ** 2
                if half * half >= d2:
                    # 命中：本轮窗内最优实例距离 ≤ 半径，窗外不可能
                    # 更近，无需继续扩窗
                    best = dict(cand[0])
                    best["target"] = (self._tx, self._tz)
                    best["dist"] = d2 ** 0.5
                    best["searched_side"] = side
                    break
            side *= 2   # 未命中：窗口翻倍再找
        if self._cancelled:
            return
        if best is not None:
            self.located.emit(best)
        else:
            self.located.emit({
                "structures": [], "target": (self._tx, self._tz),
                "searched_side": searched,
            })


class StructureScanThread(QThread):
    """视口驱动的结构扫描线程（地图生成后拖动/缩放，结构随视野增量更新）。

    与 TileRenderThread 同模式：主线程把可视方块矩形整批提交，本线程
    调 structure_map.enumerate_structures 正向枚举该视野内真实生成的
    结构，完成后一次性发结果。结构/区域间支持取消（用户又拖走时
    主线程 request_cancel 放弃本批，迟到结果按 epoch 丢弃）。

    与 MapPreviewerThread 不同：不做进度回报（结构枚举本身很快，
    21 种结构 × 若干区域的正向定位毫秒到亚秒级），一次提交一次结果。

    信号：
        structures_done(object)  载荷 dict：{structures: [...], view}
        error(str)
    """

    structures_done = Signal(object)
    error = Signal(str)

    def __init__(self, seed: int, version_key: str, view: tuple,
                 struct_keys=None, parent=None, dimension: str = "overworld"):
        super().__init__(parent)
        self._seed = seed
        self._version_key = version_key
        self._view = tuple(int(v) for v in view)
        # 同 MapPreviewerThread：None = 全部；[] = 明确不标
        self._struct_keys = (list(struct_keys)
                             if struct_keys is not None else None)
        self._dimension = (dimension if dimension in ("overworld", "nether",
                                                       "end")
                           else "overworld")
        self._cancelled = False

    def request_cancel(self):
        """请求放弃本次扫描（主线程调用；仅置布尔标志，线程安全）。"""
        self._cancelled = True

    def run(self):
        try:
            self._run_impl()
        except Exception as exc:  # 兜底：任何异常都不能无声吞掉
            self.error.emit(f"结构扫描线程异常：{exc!r}")

    def _run_impl(self):
        structs = enumerate_structures(
            self._seed, self._version_key, self._view,
            self._struct_keys,
            cancel=lambda: self._cancelled,
            dimension=self._dimension,
        )
        if self._cancelled:
            return
        self.structures_done.emit({
            "structures": structs,
            "view": self._view,
        })


class TileRenderThread(QThread):
    """视口驱动的瓦片批量增量渲染线程（拖动/缩放后补渲染新区域）。

    主线程把缺失瓦片的列表整批提交；本线程逐瓦片「采样 → 渲染 →
    发 tile_done(载荷)」，每完成一块立即发信号回主线程上屏（不等
    整批）。瓦片请求在渲染期间可能失效（用户又拖走了），主线程在
    tile_done 里自行丢弃不需要的瓦片即可，本线程不回溯。

    信号：
        tile_done(object)   单瓦片载荷 dict：{tx, tz, rgb, origin_bx,
                            origin_bz, engine}（tx/tz 为瓦片格坐标）
        batch_done(str)     整批完成（空串占位，便于统一 onFinished）
        error(str)
    """

    tile_done = Signal(object)
    batch_done = Signal()
    error = Signal(str)

    def __init__(self, seed: int, version_key: str, tiles: list,
                 parent=None, lod: str = "block", hillshade: bool = False,
                 dimension: str = "overworld"):
        super().__init__(parent)
        self._seed = seed
        self._version_key = version_key
        self._tiles = list(tiles)      # [(tx, tz), ...] 瓦片格坐标
        self._lod = lod if lod in ("block", "cell") else "block"
        self._hillshade = bool(hillshade)
        self._dimension = (dimension if dimension in ("overworld", "nether",
                                                       "end")
                           else "overworld")
        if self._dimension != "overworld":
            self._lod = "cell"   # 下界/末地数据固定 4方块/像素
        self._cancelled = False

    def request_cancel(self):
        """请求放弃剩余瓦片（新一批提交前由主线程调用）。"""
        self._cancelled = True

    def run(self):
        try:
            self._run_impl()
        except Exception as exc:  # 兜底：任何异常都不能无声吞掉
            self.error.emit(f"瓦片渲染线程异常：{exc!r}")

    def _run_impl(self):
        pad = _TILE_PAD_CELLS
        for tx, tz in self._tiles:
            if self._cancelled:
                break
            obx = tx * _TILE_BLOCKS
            obz = tz * _TILE_BLOCKS
            # 扩边采样：四边各多采 pad 格（贴世界边界的方向自然少采，
            # 不足 pad 时 horn 用线性外推兑底，不报错）；
            # sample_region 中心对齐，总宽 +pad*8 才能每边多出 pad*4 方块
            if self._dimension == "overworld":
                res = sample_region(
                    self._seed, self._version_key,
                    obx + _TILE_BLOCKS // 2, obz + _TILE_BLOCKS // 2,
                    _TILE_BLOCKS + pad * 8, _TILE_BLOCKS + pad * 8,
                    want_depth=True, want_temp_humid=True,
                    surface_mode=True,   # 与主渲染同语义（表面层重判）
                    cancel=lambda: self._cancelled,
                )
            else:
                dim_sample = (sample_region_nether
                              if self._dimension == "nether"
                              else sample_region_end)
                res = dim_sample(
                    self._seed,
                    obx + _TILE_BLOCKS // 2, obz + _TILE_BLOCKS // 2,
                    _TILE_BLOCKS + pad * 8, _TILE_BLOCKS + pad * 8,
                    cancel=lambda: self._cancelled,
                )
            if self._cancelled or res.get("cancelled"):
                break
            if self._dimension != "overworld":
                # 下界/末地：rgb 单位 = 4方块/像素，裁掉四边 pad 像素
                # （= pad*4 方块），观感与主世界 cell 档一致
                rgb = np.ascontiguousarray(
                    res["rgb"][pad:pad + (_TILE_BLOCKS >> 2),
                               pad:pad + (_TILE_BLOCKS >> 2)])
                self.tile_done.emit({
                    "tx": tx, "tz": tz, "rgb": rgb,
                    "origin_bx": int(res["origin_bx"]) + pad * 4,
                    "origin_bz": int(res["origin_bz"]) + pad * 4,
                    "engine": res.get("engine", "?"),
                    "lod": self._lod,
                })
                continue
            if self._lod == "cell":
                rgb_pad = render_cell_rgb(res["biomes"], res.get("temp"),
                                          res.get("humid"),
                                          res.get("depth"),
                                          hillshade=self._hillshade)
                # cell 档：rgb_pad 单位 = 噪声格，裁掉四边 pad 格
                # （裁剪视图非连续，QImage 需 C 连续数组，拷贝回补）
                rgb = np.ascontiguousarray(
                    rgb_pad[pad:pad + (_TILE_BLOCKS >> 2),
                            pad:pad + (_TILE_BLOCKS >> 2)])
            else:
                rgb_pad = render_block_rgb(
                    res["biomes"], res.get("temp"), res.get("humid"),
                    res.get("depth"), seed=self._seed,
                    origin_bx=int(res["origin_bx"]),
                    origin_bz=int(res["origin_bz"]),
                    hillshade=self._hillshade)
                # block 档：rgb_pad 单位 = 方块，裁掉四边 pad*4 方块
                # （同上：拷贝成 C 连续， QImage 要求）
                rgb = np.ascontiguousarray(
                    rgb_pad[pad * 4:pad * 4 + _TILE_BLOCKS,
                            pad * 4:pad * 4 + _TILE_BLOCKS])
            if self._cancelled:
                break
            self.tile_done.emit({
                "tx": tx, "tz": tz, "rgb": rgb,
                # 扩边采样后 origin 偏向左上 pad*4 方块，回补到瓦片真
                # 实左上角（= obx，与瓦片格坐标 tx*_TILE_BLOCKS 对齐）
                "origin_bx": int(res["origin_bx"]) + pad * 4,
                "origin_bz": int(res["origin_bz"]) + pad * 4,
                "engine": res.get("engine", "?"),
                "lod": self._lod,
            })
        if not self._cancelled:
            self.batch_done.emit()


# 群系定位（BiomeLocateThread）：效果同结构定位的扩窗搜索
# ---------------------------------------------------------------------------

# 下界/末地群系 id（cubiomes biomes.h 枚举，与 nether_end_sampler 同源）；
# 主世界下拉项用 Utils/Public/biome_names.BIOME_CHOICES（54 项）
NETHER_BIOMES = (
    ("下界荒地 nether_wastes", 8),
    ("灵魂沙峡谷 soul_sand_valley", 170),
    ("绯红森林 crimson_forest", 171),
    ("诡异森林 warped_forest", 172),
    ("玄武岩三角洲 basalt_deltas", 173),
)
END_BIOMES = (
    ("末地 the_end", 9),
    ("末地小型岛屿 small_end_islands", 40),
    ("末地中部高地 end_midlands", 41),
    ("末地高地 end_highlands", 42),
    ("末地荒地 end_barrens", 43),
)
# 维度键 → 群系 (标签, id) 表（主世界由 UI 侧按版本动态填充）
DIM_BIOME_TABLES = {
    "nether": NETHER_BIOMES,
    "end": END_BIOMES,
}


class BiomeLocateThread(QThread):
    """群系定位线程：扩窗搜索离目标点最近的群系出现位置。

    与 StructureLocateThread 同策略：从 512 边长起，每轮把窗扩到
    2 倍（围绕目标点居中），采样群系矩阵（主世界 surface_mode=True
    同主渲染语义；下界/末地直接用独立采样器），在矩阵中找目标群系
    id 距目标点最近的像素。找到即用圆形判据停窗：像素距目标 ≤ 窗
    半径时，窗外不可能有更近实例（1 像素 = 4x4 方块，像素距按格
    距 ×4 换算方块）。始终未命中则扩到 _LOCATE_MAX_SIDE 为止。

    三维度支持：overworld = sample_region，nether/end =
    sample_region_nether / sample_region_end（契约一致，biomes 均
    为 1 像素 = 4x4 方块）。

    与 StructureLocateThread 同模式：主线程 request_cancel 后采样
    在批间尽快退出，迟到结果按 epoch 丢弃；一次提交一次结果。

    信号：
        located(object)  载荷 dict：{biome, name, x, z,
                         target: (tx, tz), dist, searched_side}
                         （x/z 为该像素左上角方块坐标，即群系实例点）
    """

    located = Signal(object)

    # 扩窗起始/上限边长（方块）：512 与结构定位同源；上限 8192 与
    # 增量扫描同量级（秒级内完成，蘑菇岛/冰刺之地等稀疏群系可能
    # 超出上限 → 未找到提示扩大定位搜索范围）
    _LOCATE_START_SIDE = 512
    _LOCATE_MAX_SIDE = 8192

    def __init__(self, seed: int, version_key: str, biome_id: int,
                 tx: int, tz: int, parent=None,
                 dimension: str = "overworld"):
        super().__init__(parent)
        self._seed = seed
        self._version_key = version_key
        self._biome_id = int(biome_id)
        self._tx = int(tx)
        self._tz = int(tz)
        self._dimension = (dimension if dimension in ("overworld", "nether",
                                                       "end")
                           else "overworld")
        self._cancelled = False

    def request_cancel(self):
        """请求放弃本次定位（主线程调用；仅置布尔标志，线程安全）。"""
        self._cancelled = True

    def run(self):
        try:
            self._run_impl()
        except Exception as exc:  # 兜底：任何异常都不能无声吞掉
            self.located.emit({
                "biome": self._biome_id, "structures": [],
                "target": (self._tx, self._tz),
                "searched_side": 0, "error": f"群系定位线程异常：{exc!r}",
            })

    def _sample_window(self, view: tuple) -> dict:
        """按维度采样 view=(bx0, bz0, bx1, bz1) 群系矩阵。"""
        bx0, bz0, bx1, bz1 = view
        cx = (bx0 + bx1) // 2
        cz = (bz0 + bz1) // 2
        w, h = bx1 - bx0, bz1 - bz0
        if self._dimension == "overworld":
            return sample_region(
                self._seed, self._version_key, cx, cz, w, h,
                surface_mode=True, cancel=lambda: self._cancelled,
            )
        dim_sample = (sample_region_nether
                      if self._dimension == "nether"
                      else sample_region_end)
        return dim_sample(self._seed, cx, cz, w, h,
                          cancel=lambda: self._cancelled)

    def _run_impl(self):
        best = None
        searched = 0
        side = self._LOCATE_START_SIDE
        while side <= self._LOCATE_MAX_SIDE:
            searched = side
            if self._cancelled:
                return
            half = side // 2
            view = (self._tx - half, self._tz - half,
                    self._tx + half, self._tz + half)
            res = self._sample_window(view)
            if self._cancelled or res.get("cancelled"):
                return
            mat = np.asarray(res["biomes"])
            # 像素 = 4x4 方块：格距 ×4 = 方块距（对角同一像素视为
            # 同一实例，格距平方直接比较不放大尺度）
            rows, cols = np.nonzero(mat == self._biome_id)
            if rows.size:
                dx_n = cols.astype(np.int64) - (half >> 2)
                dz_n = rows.astype(np.int64) - (half >> 2)
                # 像素左上角对目标点格距（目标点恒在窗中心）
                d2_n = dx_n * dx_n + dz_n * dz_n
                k = int(np.argmin(d2_n))
                d2_blk = int(d2_n[k]) << 4   # 格² → 块²（×16）
                bx = int(res["origin_bx"]) + (int(cols[k]) << 2)
                bz = int(res["origin_bz"]) + (int(rows[k]) << 2)
                if half * half >= d2_blk:
                    # 圆形判据命中：窗内最优实例距目标 ≤ 窗半径，
                    # 窗外不可能更近，必为最近
                    best = {
                        "biome": self._biome_id, "x": bx, "z": bz,
                        "target": (self._tx, self._tz),
                        "dist": d2_blk ** 0.5,
                        "searched_side": side,
                    }
                    break
            side *= 2   # 未命中：窗口翻倍再找
        if self._cancelled:
            return
        if best is not None:
            self.located.emit(best)
        else:
            self.located.emit({
                "biome": self._biome_id, "structures": [],
                "target": (self._tx, self._tz), "searched_side": searched,
            })
