# -*- coding: utf-8 -*-
"""可复用地形俯视视图控件（QGraphicsView）。

按 region（512×512 方块 = 1 瓦片）懒渲染存档真实地形：视口进入哪些 region
就后台线程渲染哪些，渲染好的瓦片以 QGraphicsPixmapItem 上屏后**永久缓存**
（切存档/切阴影才清空；不因「看不见」卸载，拖回去立即有图不重渲染），
仅当进程工作集超 _MEM_LIMIT_MB（1.5GB）才极端兜底逐出最早的视口外瓦片
（同时回退进度计数）；未生成的 region 留虚空色。支持滚轮缩放（锚点缩放）、
按住拖动平移、初始以世界 (0,0) 为中心。

数据为真实地形（region 区块文件解析 + JourneyMap 方块色 + 群系染色），见同包
region_reader / chunk_render / world_render；方块配色与坡度光照复用 MapPreviewer
的 render_from_blocks（与 MapPreviewer 同一套 JourneyMap 渲染管线，仅顶部方块来源不同）。

纯展示控件，不依赖具体工具；SaveManager 等持有实例即可。

线程模型：RegionRenderThread（QThread）在后台串行渲染 region 瓦片，经
region_ready 信号把 QImage 回主线程上屏；TerrainView（QGraphicsView）只做
视图交互与瓦片缓存，所有 QGraphicsItem / QPixmap 均在主线程创建。
"""
from __future__ import annotations

import math
import os
import sys
import threading
import time
import traceback

# 缩短 GIL 切换片（CPython 默认 5ms）：后台渲染/取色线程持 GIL 的
# 最长连续时间减半，渲染大存档时鼠标/绘制的响应更及时（代价是
# 切换开销略增，对整体吞吐影响可忽略）
sys.setswitchinterval(0.002)

from PySide6.QtCore import (QMutex, QPointF, QPoint, QRect, QRectF, QThread,
                            QTimer, Qt, Signal, QWaitCondition)
from PySide6.QtGui import (QBrush, QColor, QImage, QPainter, QPalette, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QGraphicsPixmapItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsView)

from Utils.MapPreviewer.block_names_cn import block_cn_name
from Utils.Public.map_render.chunk_render import build_chunk, surface_block
from Utils.Public.map_render.region_reader import (RegionFile, region_path_for,
                                                   read_chunk_status,
                                                   scan_chunk_coords)
from Utils.Public.map_render.world_render import (REGION_BLOCKS, LightPack,
                                                  render_region_to_rgb)

# 未生成 region 的虚空色（纯黑，区别于已渲染地形与深水色）
_VOID_COLOR = QColor(0, 0, 0)
# 场景矩形：覆盖 MC 主世界方块坐标边界（±30M）。不显式设置的话 sceneRect
# 默认收缩到已渲染瓦片的边界，拖动会被限制在已渲染范围内（往空白方向拖
# 卡住，要等那片渲完才扩张），且逐出边缘瓦片后范围还会收缩。
_SCENE_HALF = 32_000_000
_SCENE_RECT = QRectF(-_SCENE_HALF, -_SCENE_HALF,
                     _SCENE_HALF * 2, _SCENE_HALF * 2)
# 缩放下限对应的可见 region 数上限：防缩太小→视口对应的 world 范围爆炸→
# 请求无数 region→占位与渲染过载卡死。
_MAX_VISIBLE_REGIONS = 10
# 视口变化后延迟补渲染的间隔（ms）
_SCHEDULE_MS = 120
# 预取扩展：视口内瓦片全部就绪后，自动向外扩展渲染（每圈外扩
# _PREFETCH_STEP 格），拖到已预取区域立即有图。外扩到 _PREFETCH_MAX_RING
# 圈后停止；内存压力由 _evict_for_memory 兜底。
_PREFETCH_STEP = 3
_PREFETCH_MAX_RING = 2
# 预取外扩后的总钳制（region 数/边）：(_MAX_VISIBLE_REGIONS+2) + 2*2*3 = 24
_PREFETCH_MAX_SIDE = _MAX_VISIBLE_REGIONS + 2 + 2 * _PREFETCH_MAX_RING * _PREFETCH_STEP
# 内存兜底卸载（极端情况才触发；用户要求已渲染瓦片不因「看不见」卸载，
# 故阈值远高于常规工作集）：进程工作集超 _MEM_LIMIT_MB（约 1500 张
# region 瓦片）才从最早的开始逐出视口外瓦片，卸到 _MEM_TARGET_MB。
# 触发时会同步回退进度计数，进度条始终与缓存真实工作量一致。
_MEM_LIMIT_MB = 1536
_MEM_TARGET_MB = 1280

# 光标指示框（用户指定：放大才方块对齐，缩小顺滑跟随不对齐）：
# 放大到一格 ≥ _CURSOR_MIN_PX 像素时框吸附鼠标所在方块（精确方块
# 光标）；缩小后不吸附，框以鼠标位置为中心顺滑跟随，屏幕尺寸恒
# _CURSOR_MIN_PX（一格不足该值时框不会小到看不见）。
_CURSOR_MIN_PX = 16

# 悬停取色速度阈值：鼠标速度低于该值（px/s）才做 chunk 查询（完整
# 取色含方块名）；快速移动只显示纯坐标，停 80ms 后自动恢复完整取色。
# 光标框本身恒显示恒跟随（Smart 局部重绘两个 21×21px 脏区成本极低，
# 无需隐藏/限流——旧版 fast 状态机在掉帧/速度波动下反复切换导致
# 闪烁，已废弃）。
_CURSOR_HOVER_MAX_SPEED = 2500.0   # px/s
# 1 chunk = 16 方块（分量坐标是 chunk 级的，跳转/居中时换算方块坐标）
_CHUNK_BLOCKS = 16


def _process_rss_mb() -> float:
    """当前进程工作集内存（MB）；GetProcessMemoryInfo 失败返回 0
    （调用方据此跳过卸载，宁可超限不出黑洞）。"""
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            # SIZE_T 是 C 类型，ctypes.wintypes 里没有（实测 AttributeError
            # 会被下方 except 吞掉导致永远返回 0、卸载永不触发）——用
            # ctypes.c_size_t
            _fields_ = [("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        # 必须显式声明原型：不设 argtypes 时 64 位下 GetCurrentProcess 的
        # 伪句柄（0xFF..FF）经 c_int 传参被截断成无效句柄，GetProcessMemoryInfo
        # 恒失败（实测 ret=0），卸载永不触发
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetCurrentProcess.argtypes = []
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        h = k32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return pmc.WorkingSetSize / (1024.0 * 1024.0)
    except Exception:
        pass
    return 0.0


def scan_chunk_groups(world_path: str, dimension: str,
                      coords: set | None = None) -> list[dict]:
    """扫描存档某维度 region 目录：读每个 .mca 头部偏移表收集已生成的
    chunk 坐标，并查集按 8 邻接合并成连通分量（tp 指令/服务器存档的
    分散地形各自成块），返回分量列表（按 chunk 数降序）：
        [{"count": int, "anchor": (cx, cz),
          "bbox": (cx0, cz0, cx1, cz1)}]    # 均为 chunk 坐标

    anchor = 分量内 5×5 邻域 chunk 数最多的格子（局部密度峰值）：
    跳转落点选它，避免简单包围盒中心落在分量内部的空洞上。

    chunk 级（而非 region 文件名级）的原因：region 文件存在 ≠ 整片
    32×32 chunk 都生成——tp 指令在同 region 内生成的分离小岛会被
    region 级并查集误并成一块，必须降到 chunk 粒度才能拆开。
    只读每个文件前 4KB 偏移表（零解压，见 region_reader.scan_chunk_coords），
    几百个 region 文件亚秒级。

    另剔除「纯空壳」分量：渲染器只画 Status=full 的区块（半生成区块
    一律按虚空，见 world_render），全员非 full 的分量跳过去必然全黑，
    直接从列表去掉。逐分量抽读 Status（全量解压单 chunk 后搜值，
    见 region_reader.read_chunk_status），找到一个 full 即收货。
    无 region 目录/无 chunk 返回 []。
    """
    from Utils.SaveManager.level_dat import region_dir_for
    rdir = region_dir_for(world_path, dimension)
    if not rdir:
        return []
    # coords 可传入预扫结果（set_save 同一份偏移表扫描顺带产出区块计数，
    # 避免重复读全部头部）
    pts = scan_chunk_coords(rdir) if coords is None else coords
    if not pts:
        return []

    # 行游程压缩：同一 z 行内连续 x 的 chunk 相互 4 连通，压成一个游程
    # 节点。并查集节点数从 chunk 数（大存档 10 万级，逐点 8 邻实测 729ms）
    # 降到游程数（千级）；8 邻接判定化为相邻行游程区间的 ±1 重叠。
    rows: dict[int, list[int]] = {}
    for cx, cz in pts:
        rows.setdefault(cz, []).append(cx)
    runs: list[tuple[int, int, int]] = []   # (cz, x0, x1) 闭区间
    for cz, xs in rows.items():
        xs.sort()
        x0 = prev = xs[0]
        for x in xs[1:]:
            if x != prev + 1:
                runs.append((cz, x0, prev))
                x0 = x
            prev = x
        runs.append((cz, x0, prev))

    # 并查集（游程级）：相邻两行（z 与 z+1）的游程区间各向外扩 1 后有
    # 交即 8 邻接（水平 ±1 + 垂直 1，含对角；对角相接在视觉上也算挨着）。
    # 两行的游程都按 x0 有序，双指针线性配对。
    parent: list[int] = list(range(len(runs)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    by_row: dict[int, list[int]] = {}
    for i, (cz, _x0, _x1) in enumerate(runs):
        by_row.setdefault(cz, []).append(i)
    zs = sorted(by_row)
    for z, zn in zip(zs, zs[1:]):
        if zn != z + 1:
            continue
        ra_list, rb_list = by_row[z], by_row[zn]
        j = 0
        for ia in ra_list:
            a0 = runs[ia][1]
            while j < len(rb_list) and runs[rb_list[j]][2] < a0 - 1:
                j += 1   # b 右端不足 a0-1：本行后续 a 更靠右，永久跳过
            k = j
            while k < len(rb_list) and runs[rb_list[k]][1] <= runs[ia][2] + 1:
                pa, pb = find(ia), find(rb_list[k])
                if pa != pb:
                    parent[pa] = pb
                k += 1

    # 游程级分量：count/bbox 直接由游程累出，不再展开 10 万级 chunk
    comps: dict[int, list[int]] = {}
    for i in range(len(runs)):
        comps.setdefault(find(i), []).append(i)

    # 过滤纯空壳分量：抽读 Status，命中 full（有地形）即收货；全员非
    # full/不可读（渲染必黑）→ 整分量剔除。预算全局 2048 次兜底（空壳
    # ~0.3ms、富 chunk ~2-5ms/次，极端情况最名几秒）：耗尽后未判定的
    # 分量保守保留。
    rcache: dict[tuple[int, int], RegionFile] = {}
    budget = 2048

    def _chunk_is_full(cx: int, cz: int) -> bool | None:
        """True=full（有地形）；False=非 full/不可读（渲染必黑）；
        None=预算耗尽未判定（保守保留）。"""
        nonlocal budget
        if budget <= 0:
            return None
        budget -= 1
        rx, rz = cx >> 5, cz >> 5
        st = read_chunk_status(os.path.join(rdir, f"r.{rx}.{rz}.mca"), cx, cz)
        if st is None:
            # 快速路径没读到（写入器字段序异常/压缩类型罕见）→ 整解析兜底
            key = (rx, rz)
            rf = rcache.get(key)
            if rf is None:
                if len(rcache) > 16:
                    rcache.clear()
                rf = RegionFile(os.path.join(rdir, f"r.{rx}.{rz}.mca"))
                rcache[key] = rf
            st = (rf.read_chunk(cx, cz) or {}).get("Status")
        return st in ("minecraft:full", "full") if st else False

    kept: list[list[int]] = []
    for idxs in comps.values():
        kept_flag = False
        for i in idxs:
            cz, a0, a1 = runs[i]
            for x in range(a0, a1 + 1):
                r = _chunk_is_full(x, cz)
                if r is None or r:   # full 命中，或预算耗尽保守保留
                    kept_flag = True
                    break
            if kept_flag:
                break
        if kept_flag:
            kept.append(idxs)

    out = []
    for idxs in kept:
        count = 0
        x_min = z_min = 1 << 62
        x_max = z_max = -(1 << 62)
        for i in idxs:
            cz, a0, a1 = runs[i]
            count += a1 - a0 + 1
            if a0 < x_min:
                x_min = a0
            if a1 > x_max:
                x_max = a1
            if cz < z_min:
                z_min = cz
            if cz > z_max:
                z_max = cz
        # 锚点：按游程长度降序扫内部候选（x∈[x0+2, x1-2]；游程端点同行
        # 紧邻必缺、不可能 5×5 满窗），取邻域最满 chunk，满窗（25）即停。
        # 评估上限 4096 候选：真实数据几十个内命中满窗，极端细碎分量也
        # 不会超时；一个满窗都没有时退化为最长游程中点（横向最实一行）。
        idxs.sort(key=lambda i: runs[i][1] - runs[i][2])   # 长度降序（负值）
        best: tuple[int, int] | None = None
        best_n = -1
        budget = 4096
        for i in idxs:
            cz, a0, a1 = runs[i]
            for x in range(a0 + 2, a1 - 1):
                n = sum(1 for dz in range(-2, 3) for dx in range(-2, 3)
                        if (x + dx, cz + dz) in pts)
                if n > best_n:
                    best, best_n = (x, cz), n
                budget -= 1
                if best_n == 25 or budget <= 0:
                    break
            if best_n == 25 or budget <= 0:
                break
        if best is None:
            cz, a0, a1 = runs[idxs[0]]
            best = ((a0 + a1) // 2, cz)
        out.append({"count": count, "anchor": best,
                    "bbox": (x_min, z_min, x_max, z_max)})
    out.sort(key=lambda g: -g["count"])
    return out


class RegionRenderThread(QThread):
    """后台按请求渲染 region 瓦片（单线程串行，避免同时读盘/算）。

    主线程 request(rx,rz) 入队；本线程逐个出队渲染（region_reader +
    world_render 成 QImage），经 region_ready 信号回主线程上屏。请求去重
    （_inflight 防队列内重复）。QMutex + QWaitCondition 调度：request 时
    wakeAll 唤醒，cancel 时置 _active=False 并唤醒使 run 退出。
    """

    region_ready = Signal(int, int, object)   # rx, rz, QImage（None=渲染失败）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._world_path: str | None = None
        self._dimension = "overworld"
        self._hillshade = True   # 地形阴影默认开（SaveManager 复选框同步默认勾选）
        self._active = True
        self._generation = 0   # 存档/维度/阴影切换代际：防陈旧结果上屏
        self._queue: list[tuple[int, int]] = []
        self._inflight: set[tuple[int, int]] = set()
        self._lpack: LightPack | None = None

    def new_generation(self) -> None:
        """使队列外正在渲染的旧结果作废（配合场景清理调用）。"""
        self._mutex.lock()
        self._generation += 1
        self._mutex.unlock()

    def _ensure_lpack(self) -> LightPack:
        if self._lpack is None:
            self._lpack = LightPack()
        return self._lpack

    def set_save(self, world_path: str, dimension: str = "overworld") -> None:
        """切换存档/维度：更新路径、丢弃旧存档的待渲染队列与正在渲染的
        旧结果（代际 +1，否则切存档后旧存档海洋瓦片会贴到新地图上）。"""
        self._mutex.lock()
        self._world_path = world_path
        self._dimension = dimension
        self._generation += 1
        self._queue.clear()
        self._inflight.clear()
        self._cond.wakeAll()
        self._mutex.unlock()

    def request(self, rx: int, rz: int) -> None:
        """请求渲染某 region（队列内去重）。"""
        self._mutex.lock()
        key = (rx, rz)
        if key not in self._inflight:
            self._inflight.add(key)
            self._queue.append(key)
            self._cond.wakeAll()
        self._mutex.unlock()

    def reorder(self, cx: float, cz: float) -> None:
        """按到视口中心 (cx,cz)（region 坐标，浮点）的距离重排待渲染
        队列：近的先渲（稳定排序，同距保持旧序）。

        打开存档/拖动/缩放后屏幕内的新请求会被此前入队的视口外陈旧
        请求堵在后面，屏幕内区域长时间出不了图；重排后队首段永远是
        离当前视口中心最近的瓦片。渲染中的单个请求无法中断（最多
        等它一个，~0.6s）。"""
        if not self._queue:
            return
        self._mutex.lock()
        self._queue.sort(
            key=lambda k: (k[0] - cx) * (k[0] - cx)
            + (k[1] - cz) * (k[1] - cz))
        self._mutex.unlock()
        self._cond.wakeAll()

    def cancel(self) -> None:
        """停止渲染线程（退出 run 循环）。"""
        self._mutex.lock()
        self._active = False
        self._queue.clear()
        self._inflight.clear()
        self._cond.wakeAll()
        self._mutex.unlock()

    def run(self) -> None:
        while True:
            self._mutex.lock()
            while self._active and not self._queue:
                self._cond.wait(self._mutex)
            if not self._active:
                self._queue.clear()
                self._inflight.clear()
                self._mutex.unlock()
                return
            key = self._queue.pop(0)
            self._inflight.discard(key)
            world_path = self._world_path
            dimension = self._dimension
            hillshade = self._hillshade
            gen = self._generation
            self._mutex.unlock()

            img = self._render_one(world_path, dimension, key[0], key[1],
                                   hillshade)
            self._mutex.lock()
            stale = gen != self._generation
            self._mutex.unlock()
            # 失败（None）也要发信号：主线程把占位符转黑色块并计进度，
            # 否则无文件/损坏 region 的占位符永远挂着、进度卡死
            if not stale:
                self.region_ready.emit(key[0], key[1], img)

    def _render_one(self, world_path: str | None, dimension: str,
                    rx: int, rz: int, hillshade: bool) -> QImage | None:
        """渲染单 region 为 QImage（脱离 numpy 缓冲）；失败/无文件返回 None。"""
        if not world_path:
            return None
        try:
            rpath = region_path_for(world_path, dimension, rx, rz)
            if not rpath or not os.path.isfile(rpath):
                return None
            rf = RegionFile(rpath)
            lpack = self._ensure_lpack()
            arr = render_region_to_rgb(rf, lpack, hillshade=hillshade)
            h, w = arr.shape[0], arr.shape[1]
            img = QImage(arr.tobytes(), w, h, w * 3,
                         QImage.Format.Format_RGB888)
            return img.copy()   # 脱离 numpy 缓冲（arr 函数返回即回收）
        except Exception:
            return None


class _HoverWorker(QThread):
    """悬停取色后台线程：主线程提交坐标，region 读盘 + chunk 解析在
    worker 内完成，结果经 hit_ready 信号回主线程。

    此前取色在主线程同步做：未缓存 chunk 冷读（读盘 + zlib 解压 +
    NBT 解析）单次实测 10~20ms，慢速漫游跨 chunk 边界时每次
    mouseMoveEvent 都可能撞上，光标跟随明显卡顿。移入后台后主线程
    只做纯坐标 emit（微秒级），方块名异步补发。

    region 文件句柄 + 解析后 chunk 的双 LRU 由 worker 独占持有（主
    线程不再读盘，无跨线程竞争）；存档切换由请求携带的 world_path
    识别，不一致即清缓存（顺带释放旧句柄）。
    """
    hit_ready = Signal(int, str)   # seq, 完整文本（未命中为空串）；
    # 参数必须是 Qt 原生类型：实测 PySide6 对 object 类型参数的跨线程
    # queued 传递不可靠（emit 后槽收不到，静默丢事件）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._quit = False
        self._req = None        # 最新请求 (seq, wx, wz, world_path, dimension)
        self._done_seq = 0      # 已处理最大序号（更小的视为过期，跳过）
        self._wake = threading.Event()
        self._cur_world = None
        self._region_files: dict[tuple[int, int], RegionFile | None] = {}
        self._region_files_lru: list[tuple[int, int]] = []
        self._chunk_cache: dict[tuple[int, int, int, int], dict | None] = {}
        self._chunk_cache_lru: list[tuple[int, int, int, int]] = []

    def submit(self, seq: int, wx: int, wz: int,
               world_path: str, dimension: str) -> None:
        # GIL 下元组赋值原子；同一时间只保留最新请求（旧坐标无需处理）
        self._req = (seq, wx, wz, world_path, dimension)
        self._wake.set()

    def stop(self) -> None:
        self._quit = True
        self._wake.set()

    def run(self) -> None:
        while not self._quit:
            if not self._wake.wait(timeout=0.5):
                continue
            self._wake.clear()
            while not self._quit:
                req = self._req
                if req is None:
                    break
                self._req = None
                seq, wx, wz, wpath, dim = req
                if seq <= self._done_seq:
                    continue   # 过期请求（已有更新的提交），跳过
                self._done_seq = seq
                try:
                    if wpath != self._cur_world:
                        self._cur_world = wpath
                        self._clear_caches()
                    hit = self._block_at(wpath, dim, wx, wz)
                except Exception:
                    traceback.print_exc()   # 打日志定位；线程不死于偶发异常
                    hit = None              # 单次取色失败按未命中处理
                if hit:
                    name, wy = hit
                    text = (f"X: {wx}  Y: {wy}  Z: {wz}" if wy is not None
                            else f"X: {wx}  Z: {wz}")
                    cn = block_cn_name(name)   # 查不到时返回短名本身
                    text += f"  ｜  {cn}  {name}"
                else:
                    text = ""   # 未命中：主线程纯坐标已显示，无需补发
                self.hit_ready.emit(seq, text)

    def _clear_caches(self) -> None:
        self._region_files.clear()
        self._region_files_lru.clear()
        self._chunk_cache.clear()
        self._chunk_cache_lru.clear()

    # ---- 原 TerrainView 同名逻辑搬入（参数化 world_path/dimension）----
    def _block_at(self, wpath: str, dim: str,
                  wx: int, wz: int) -> tuple[str, int | None] | None:
        """读某世界坐标的顶层方块 (名字, 世界 Y)（懒加载 region 文件 + chunk）。"""
        rx = wx // REGION_BLOCKS
        rz = wz // REGION_BLOCKS
        cx = (wx % REGION_BLOCKS) // 16
        cz = (wz % REGION_BLOCKS) // 16
        lx = (wx % REGION_BLOCKS) % 16
        lz = (wz % REGION_BLOCKS) % 16
        built = self._get_chunk(wpath, dim, rx, rz, cx, cz)
        if built is None:
            return None
        name, wy = surface_block(built, lx, lz)
        if not name:
            return None
        return name, wy

    def _get_region_file(self, wpath: str, dim: str,
                         rx: int, rz: int) -> RegionFile | None:
        key = (rx, rz)
        if key in self._region_files:
            return self._region_files[key]
        rpath = region_path_for(wpath, dim, rx, rz)
        rf = RegionFile(rpath) if (rpath and os.path.isfile(rpath)) else None
        self._region_files[key] = rf
        self._region_files_lru.append(key)
        if len(self._region_files_lru) > 8:
            self._region_files.pop(self._region_files_lru.pop(0), None)
        return rf

    def _get_chunk(self, wpath: str, dim: str, rx: int, rz: int,
                   cx: int, cz: int) -> dict | None:
        key = (rx, rz, cx, cz)
        if key in self._chunk_cache:
            return self._chunk_cache[key]
        built = None
        rf = self._get_region_file(wpath, dim, rx, rz)
        if rf is not None:
            chunk = rf.read_chunk(cx, cz)
            if chunk is not None:
                built = build_chunk(chunk)
        self._chunk_cache[key] = built
        self._chunk_cache_lru.append(key)
        if len(self._chunk_cache_lru) > 256:
            self._chunk_cache.pop(self._chunk_cache_lru.pop(0), None)
        return built


class TerrainView(QGraphicsView):
    """可复用地形俯视视图：懒渲染 region 瓦片 + 缩放/平移/悬停取色。"""

    hover_info = Signal(str)   # 悬停信息（世界坐标 + 顶层方块名）
    # 悬停世界坐标（方块级 floor）：右键菜单等操作需要知道当前指向的
    # 方块，纯文本状态栏不够用。无存档/未指向地形时发 (-1, -1)。
    hover_pos = Signal(int, int)
    # 右键请求操作区块：(世界方块 x, z)。由工具侧连接，弹出区块预览等。
    chunk_action = Signal(int, int)
    # 渲染进度（按区块计数）：(total, done)。total=0 表示无活动批次
    # （完成停留结束/切存档），监听方据此隐藏进度条。
    progress_changed = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._world_path: str | None = None
        self._dimension = "overworld"
        self._render_thread: RegionRenderThread | None = None
        # (rx,rz) -> 已上屏瓦片（渲染完成的 QGraphicsPixmapItem）
        self._tile_items: dict[tuple[int, int], QGraphicsPixmapItem] = {}
        # (rx,rz) -> 渲染中占位（QGraphicsRectItem）
        self._tile_pending: dict[tuple[int, int], QGraphicsRectItem] = {}
        # 瓦片完成顺序（内存驱动卸载按此从早到晚找视口外牺牲者；
        # QImage 不另存——场景里的 QPixmapItem 即缓存）
        self._tile_order: list[tuple[int, int]] = []
        # 预取扩展圈数（视口变化重置为 0；视口内全部就绪后逐圈外扩）
        self._prefetch_ring = 0
        # 独立区域分量列表（set_save 时按已生成 chunk 扫描填充；
        # 供默认定位与 UI 跳转）
        self._region_groups: list[dict] = []
        # 各 region 的已生成区块数（set_save 时同一份偏移表扫描顺带产出，
        # 供右下角渲染进度条按区块计数）
        self._region_chunk_counts: dict[tuple[int, int], int] = {}
        # 渲染进度批次：自上次队列排空以来的全部请求（视口+预取），
        # 按区块计数；done >= total 视为一批完成
        self._prog_chunk_total = 0
        self._prog_chunk_done = 0
        # 悬停取色：后台 worker（读盘/解析在 worker 线程，主线程零阻塞）。
        # _hover_seq 为最新请求序号，回包 seq 不一致即过期丢弃；
        # _last_hover_text/_last_submitted 用于状态栏去重（同格微动
        # 不重发、纯坐标与完整文本交替闪烁的防线）
        self._hover_seq = 0
        self._last_hover_text = None
        self._last_submitted = None
        self._last_hover_pos = None   # hover_pos 去重基准
        self._hover_worker = _HoverWorker(self)
        self._hover_worker.hit_ready.connect(self._on_hover_hit)
        self._hover_worker.start()

        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(_SCENE_RECT)   # 固定大场景：拖动不受已渲染范围限制
        self.setScene(self._scene)
        # 背景刷成虚空色（黑）：快速拖动时，视口前方未占位/未渲染的场景
        # 空白会露出背景（默认是调色板白色 → 用户看到"瓦片连接处的白色
        # 细线"，实测拖动停止后即消失）。刷黑后露出即"未生成=黑"，与地图
        # 语义一致，也不再刺眼。
        self.setBackgroundBrush(QBrush(_VOID_COLOR))
        # viewport 不透明黑底：非整数 DPR（用户 2K 屏 ≈156% 缩放）下，滚动时
        # backing store 的脏区计算与 DPR 取整偶发不一致，漏绘区域保持
        # backing store 初始化的纯白（实测复现：拖动中成片白区 + 白色竖条，
        # 拖动停止后约 250ms 才被全量重绘清除）。autoFillBackground 让 Qt
        # 每次绘制前先用调色板填满 viewport，漏绘区域退化为黑色（与虚空
        # 色一致），不再出白。
        vp = self.viewport()
        vp.setAutoFillBackground(True)
        pal = vp.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
        vp.setPalette(pal)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        # 鼠标跟踪：Qt 默认不按键的鼠标移动不派发 mouseMoveEvent，悬停
        # 信息就只会在拖动时刷新；事件从 viewport 进来，view 和 viewport
        # 都要开 tracking 才能实时跟随光标移动。
        self.setMouseTracking(True)
        vp.setMouseTracking(True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        # 局部脏区重绘（Smart）：光标框/悬停/瓦片上屏/进度条只重绘自己
        # 的区域。此前 FullViewportUpdate 下任何一次重绘都是全视口绘制
        # 几百张瓦片，快速移动光标/拖动时每帧全量重绘导致卡顿。
        # 白屏风险：非整数 DPR 下拖动中漏绘区可能露白，但 viewport 已
        # 开黑底 autoFillBackground（漏绘区退化为虚空色）双保险，
        # Smart 的局部重绘链路漏绘区同样被黑底兜住。
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._schedule_timer = QTimer(self)
        self._schedule_timer.setSingleShot(True)
        self._schedule_timer.setInterval(_SCHEDULE_MS)
        self._schedule_timer.timeout.connect(self._ensure_visible_tiles)

        # 渲染总进度（用户指定：总进度而非分批）：total = 存档已生成
        # 区块总量（set_save 时扫描偏移表得出，不随漫游变化）；
        # done = 已渲染累计（跨请求持续增长，漫游/预取不清零）
        self._prog_chunk_total = 0
        self._prog_chunk_done = 0
        # 已渲染 region 的计入值表：去重防双计 + 卸载兑底回退用；
        # 切存档/切阴影（缓存清空）时一并清空
        self._prog_counted: dict[tuple[int, int], int] = {}
        self._prog_timer_hide = QTimer(self)
        self._prog_timer_hide.setSingleShot(True)
        self._prog_timer_hide.setInterval(1500)
        self._prog_timer_hide.timeout.connect(self._prog_hide)

        # 光标指示框：悬停时吸附到最近方块的 1×1 浅灰半透明框。
        # 不用场景 item（_scene.clear() 会 delete 所有 item），改在
        # drawForeground 绘制：随场景变换，cosmetic 边框恒 1px，
        # 不拦截鼠标/悬停，切存档/切阴影无需重建。
        # 地图上隐藏系统箭头（BlankCursor），方块框本身充当光标。
        self._cursor_rect: QRectF | None = None
        self._cursor_vp = None   # 最后鼠标视口位置（拖动/缩放后重新吸附用）
        self._cursor_last_pos = None   # 上次 move 视口位置（取色速度判定）
        self._cursor_last_t = 0.0      # 上次 move 时刻（monotonic 秒）
        self._hover_fast = False       # 当前快速移动（取色降级为纯坐标）
        # 快速移动取色消抖：停 _HOVER_SETTLE_MS 后自动恢复完整取色
        self._hover_settle_timer = QTimer(self)
        self._hover_settle_timer.setSingleShot(True)
        self._hover_settle_timer.setInterval(80)
        self._hover_settle_timer.timeout.connect(self._hover_settle)

    # ---------- 设置存档 ----------
    def set_save(self, world_path: str, dimension: str = "overworld") -> None:
        """切换到指定存档/维度，重置视图并以 (0,0) 为中心。"""
        self._world_path = world_path
        self._dimension = dimension
        self._scene.clear()
        self._tile_items.clear()
        self._tile_pending.clear()
        self._tile_order.clear()
        self._prefetch_ring = 0
        self._hover_seq += 1   # 切存档：旧存档在途取色结果作废
        self._last_hover_text = None
        self._last_submitted = None
        self._last_hover_pos = None

        if self._render_thread is None:
            self._render_thread = RegionRenderThread(self)
            self._render_thread.region_ready.connect(self._on_region_ready)
            # 渲染线程 OS 优先级降为 Low：渲染满负荷（大存档分钟级）
            # 时不与主线程的鼠标/绘制/上屏抢 CPU 时间片，交互优先
            self._render_thread.setPriority(QThread.Priority.LowPriority)
        self._render_thread.set_save(world_path, dimension)
        if not self._render_thread.isRunning():
            self._render_thread.start()

        # 默认定位：分散存档（如服务器下载）的内容可能远离出生点——读
        # region 头部偏移表收集已生成 chunk，并查集分量落到最大分量的局部
        # 密度峰值；正常存档原点本身就是最大分量，行为不变。列表供 UI 跳转。
        # 同一份偏移表扫描顺带产出各 region 的已生成 chunk 数（总进度
        # 分母来源）与 coords 原始集合（传下去免二次读头）。
        from Utils.SaveManager.level_dat import region_dir_for
        coords = scan_chunk_coords(region_dir_for(world_path, dimension))
        self._region_chunk_counts = {}
        for cx, cz in coords:
            rkey = (cx >> 5, cz >> 5)
            self._region_chunk_counts[rkey] = (
                self._region_chunk_counts.get(rkey, 0) + 1)
        self._prog_chunk_total = sum(self._region_chunk_counts.values())
        self._prog_reset()
        self._region_groups = scan_chunk_groups(world_path, dimension, coords)
        if self._region_groups:
            ax, az = self._region_groups[0]["anchor"]
            self._fit_initial(ax, az)
        else:
            self._fit_initial()

    def clear(self) -> None:
        """清空视图（未选择/不支持的存档）。停止渲染并显示虚空。"""
        self._world_path = None
        self._scene.clear()
        self._tile_items.clear()
        self._tile_pending.clear()
        self._tile_order.clear()
        self._region_groups = []
        self._region_chunk_counts = {}
        self._prog_chunk_total = 0   # 无存档：总进度分母清零（信号 → 隐藏）
        self._hover_seq += 1         # 清空视图：在途取色结果作废
        self._last_hover_text = None
        self._last_submitted = None
        if self._render_thread is not None:
            self._render_thread.set_save("", self._dimension)
        self._prog_reset()
        self.resetTransform()

    def jump_to_region_group(self, idx: int) -> None:
        """定位到第 idx 个独立区域（按 chunk 数降序）的锚点，并把缩放
        调整到该分量包围盒恰好可见（下限同滚轮的最小缩放钳制）。"""
        if not (0 <= idx < len(self._region_groups)):
            return
        g = self._region_groups[idx]
        ax, az = g["anchor"]
        cx0, cz0, cx1, cz1 = g["bbox"]
        self.resetTransform()
        vw = max(self.viewport().width(), 1)
        vh = max(self.viewport().height(), 1)
        size = max(cx1 - cx0 + 1, cz1 - cz0 + 1) * _CHUNK_BLOCKS
        scale = min(vw, vh) / max(size, 1.0)
        vmin = max(min(vw, vh), 1)
        min_scale = vmin / (REGION_BLOCKS * _MAX_VISIBLE_REGIONS)
        if scale < min_scale:
            scale = min_scale
        # 单 chunk 小岛的包围盒只有 16 方块：恰好充满会把缩放推到几十倍
        # （一格 40 像素过近）——钳到短边至少可见 64 方块。
        max_scale = vmin / 64.0
        if scale > max_scale:
            scale = max_scale
        self.scale(scale, scale)
        self.centerOn((ax + 0.5) * _CHUNK_BLOCKS, (az + 0.5) * _CHUNK_BLOCKS)
        self._schedule_timer.start()

    def _fit_initial(self, anchor_cx: int | None = None,
                     anchor_cz: int | None = None) -> None:
        self.resetTransform()
        vw = max(self.viewport().width(), 1)
        vh = max(self.viewport().height(), 1)
        # 让约 1024 方块（2 region）在短边方向可见
        scale = min(vw, vh) / 1024.0
        self.scale(scale, scale)
        if anchor_cx is None:
            self.centerOn(0.0, 0.0)
        else:
            self.centerOn((anchor_cx + 0.5) * _CHUNK_BLOCKS,
                          (anchor_cz + 0.5) * _CHUNK_BLOCKS)
        self._schedule_timer.start()

    # ---------- 瓦片补渲染 ----------
    def _ensure_visible_tiles(self) -> None:
        if self._world_path is None:
            return
        rect = self.mapToScene(self.viewport().rect()).boundingRect()
        # 预取外扩：_prefetch_ring>0 时把请求范围向外扩 ring*STEP 格
        pad = self._prefetch_ring * _PREFETCH_STEP
        rx0 = int(math.floor(rect.left() / REGION_BLOCKS)) - pad
        rx1 = int(math.floor(rect.right() / REGION_BLOCKS)) + pad
        rz0 = int(math.floor(rect.top() / REGION_BLOCKS)) - pad
        rz1 = int(math.floor(rect.bottom() / REGION_BLOCKS)) + pad
        # 防御：请求范围钳制到 _PREFETCH_MAX_SIDE 见方，防 transform
        # 被非滚轮路径误改至极小 scale 时请求数爆炸。
        max_side = _PREFETCH_MAX_SIDE
        if rx1 - rx0 + 1 > max_side:
            cx = (rx0 + rx1) // 2
            rx0 = cx - max_side // 2
            rx1 = rx0 + max_side - 1
        if rz1 - rz0 + 1 > max_side:
            cz = (rz0 + rz1) // 2
            rz0 = cz - max_side // 2
            rz1 = rz0 + max_side - 1
        for rz in range(rz0, rz1 + 1):
            for rx in range(rx0, rx1 + 1):
                key = (rx, rz)
                if key in self._tile_items or key in self._tile_pending:
                    continue
                self._add_placeholder(rx, rz)
                self._render_thread.request(rx, rz)
                self._prog_add_request(key)
        # 视口中心距离优先：把整个待渲染队列按离屏幕中心的远近重排，
        # 屏幕内区域先出图（入队本身是行序，含视口外陈旧请求）。
        center = rect.center()
        self._render_thread.reorder(center.x() / REGION_BLOCKS,
                                    center.y() / REGION_BLOCKS)

    def _add_placeholder(self, rx: int, rz: int) -> None:
        item = QGraphicsRectItem(rx * REGION_BLOCKS, rz * REGION_BLOCKS,
                                 REGION_BLOCKS, REGION_BLOCKS)
        item.setBrush(QBrush(_VOID_COLOR))
        item.setPen(QPen(Qt.PenStyle.NoPen))
        self._scene.addItem(item)
        self._tile_pending[(rx, rz)] = item

    def _on_region_ready(self, rx: int, rz: int, img: QImage | None) -> None:
        key = (rx, rz)
        # 顺序表与 items 强一致：先移除旧位置再追加（重复上屏刷新为最新，
        # 否则 evict 先逐出同 key 后 item 重进场景会造成「有 item 无序项」
        # 的泄漏——永不被逐出）
        if key in self._tile_order:
            self._tile_order.remove(key)
        self._tile_order.append(key)

        old = self._tile_pending.pop(key, None)
        if old is not None:
            self._scene.removeItem(old)
        if img is not None:
            pix = QPixmap.fromImage(img)
            item = QGraphicsPixmapItem(pix)
            item.setOffset(rx * REGION_BLOCKS, rz * REGION_BLOCKS)
        else:
            # 渲染失败（无文件/损坏）：转黑色实心块计入缓存，视口再扫到
            # 不重试；进度按完成计（无文件 region 计 0 区块）
            item = QGraphicsRectItem(rx * REGION_BLOCKS, rz * REGION_BLOCKS,
                                     REGION_BLOCKS, REGION_BLOCKS)
            item.setBrush(QBrush(_VOID_COLOR))
            item.setPen(QPen(Qt.PenStyle.NoPen))
        old_item = self._tile_items.get(key)
        if old_item is not None:
            self._scene.removeItem(old_item)   # 防重复上屏留孤儿 item
        self._scene.addItem(item)
        self._tile_items[key] = item
        # 进度计数：本 region 完成（成功或失败都算）
        self._prog_finish_one(key)
        # 每上屏一张就按当前视口中心重排一次队列：拖动中不用等停顿触发
        # _ensure_visible_tiles，新视口的瓦片即可持续插队到队首。
        # mapToScene(QRect) 返回 QPolygonF，无 .center()——取 boundingRect
        # 的中心（此前漏了这一步，信号槽内 AttributeError 被吞，导致
        # 下面的 evict 与预取扩展从未执行）
        center = self.mapToScene(self.viewport().rect()).boundingRect().center()
        if self._render_thread is not None:
            self._render_thread.reorder(center.x() / REGION_BLOCKS,
                                        center.y() / REGION_BLOCKS)
        # 内存驱动卸载：不设固定数量上限，超限逐最早的视口外瓦片
        self._evict_for_memory()
        # 视口内全部就绪后自动向外扩展预渲染
        self._maybe_extend_prefetch()

    def _evict_for_memory(self) -> None:
        """极端内存兜底（用户要求：已渲染瓦片不因「看不见」而卸载，
        重复渲染会让进度条失真）：进程工作集超过 _MEM_LIMIT_MB（1.5GB）
        才从最早的开始逐出视口之外瓦片，卸到 _MEM_TARGET_MB 以下为止；
        正常浏览（缓存 <1500 region）永不触发。

        视口内的瓦片绝不逐出；找不到视口外牺牲者时允许暂时超限。
        卸载时同步回退进度计数（_prog_counted 记录每瓦片计入值），
        保证「已渲染 X / Y 区块」始终等于缓存中的真实工作量；卸载后
        该瓦片重进视口会重新请求渲染并重新计入。
        RSS 读取失败（返回 0）则不卸载。
        """
        rss = _process_rss_mb()
        if rss <= 0 or rss <= _MEM_LIMIT_MB:
            return
        rect = self.mapToScene(self.viewport().rect()).boundingRect()
        while True:
            victim = None
            for key in self._tile_order:
                if key not in self._tile_items:
                    continue   # 陈旧顺序项，跳过
                rx, rz = key
                tile = QRectF(rx * REGION_BLOCKS, rz * REGION_BLOCKS,
                              REGION_BLOCKS, REGION_BLOCKS)
                if tile.intersects(rect):
                    continue   # 视口内：不逐出
                victim = key
                break
            if victim is None:
                return   # 全在视口内：允许超限
            self._tile_order.remove(victim)
            item = self._tile_items.pop(victim, None)
            if item is not None:
                self._scene.removeItem(item)
            # 同步回退进度计数：进度条数值与缓存真实工作量强一致
            # （total 为存档常量不动，只退 done）
            c = self._prog_counted.pop(victim, 0)
            if c:
                self._prog_chunk_done -= c
                self.progress_changed.emit(self._prog_chunk_total,
                                           self._prog_chunk_done)
            rss = _process_rss_mb()
            if rss <= 0 or rss <= _MEM_TARGET_MB:
                return

    def _maybe_extend_prefetch(self) -> None:
        """视口内瓦片全部就绪（无在途请求）时向外扩展预渲染一圈。

        _prefetch_ring 由视口变化（滚轮/拖动/切存档）重置为 0，扩展
        逐圈推进到 _PREFETCH_MAX_RING 上限；极端超限时旧瓦片才会被
        兜底卸载（见 _evict_for_memory），拖回去重渲。
        """
        if self._world_path is None:
            return
        if self._tile_pending or self._prefetch_ring >= _PREFETCH_MAX_RING:
            return
        self._prefetch_ring += 1
        self._ensure_visible_tiles()

    # ---------- 交互 ----------
    # 光标：默认箭头，仅按住拖动时握拳（ScrollHandDrag 默认悬停张开手，
    # 这里在 enter/press/release 后覆盖回箭头）
    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        # 地图上隐藏系统箭头：吸附方块的浅灰半透明框本身充当光标
        self.viewport().setCursor(Qt.CursorShape.BlankCursor)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)   # 离开地图恢复箭头
        self._hover_settle_timer.stop()
        self._hover_fast = False
        if self._cursor_rect is not None:   # 离开地图：光标框隐藏
            self._update_cursor_region(self._cursor_rect)
            self._cursor_rect = None
            self._cursor_vp = None
            self._cursor_last_pos = None   # 重新进入后首个 move 不判定速度

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            # 拖动中仍用方块光标（不切换闭手箭头，吸附框继续跟随）
            self.viewport().setCursor(Qt.CursorShape.BlankCursor)
        elif event.button() == Qt.MouseButton.RightButton:
            # 右键：拦截默认菜单，发世界坐标给工具侧（区块预览等）。
            # ScrollHandDrag 不消费右键，故此处接管。
            wp = self.world_pos_at(event.pos())
            if wp is not None:
                self.chunk_action.emit(wp[0], wp[1])

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.viewport().setCursor(Qt.CursorShape.BlankCursor)

    # ---------- 光标指示框 ----------
    def _update_cursor_region(self, rect_scene: QRectF) -> None:
        """光标框所在场景矩形的局部重绘。

        PySide6 的 update(QRectF) 解析到 QWidget 版本（无 scene 坐标
        重载），手动经 viewportTransform 把场景矩形映射到 viewport
        像素矩形，update viewport 的局部区域（Smart 脏区只重绘这一小
        块，不触全视口）。"""
        vt = self.viewportTransform()
        tl = vt.map(rect_scene.topLeft())
        br = vt.map(rect_scene.bottomRight())
        vp = QRect(tl.toPoint(), br.toPoint()).normalized()
        self.viewport().update(vp.adjusted(-2, -2, 2, 2))

    def _update_cursor(self, scene_x: float, scene_y: float) -> None:
        """放大（一格 ≥ _CURSOR_MIN_PX）时框吸附鼠标所在方块，形成精确
        方块光标（floor 取整对齐世界原点，负坐标含内）；缩小后不吸附，
        框以鼠标位置为中心顺滑跟随，屏幕尺寸恒 _CURSOR_MIN_PX（一格
        不足该值时框不会小到看不见）。
        重绘走局部脏区（Smart 模式下只重绘新旧框两个小矩形）；框矩形
        不变（吸附模式同格内移动）直接返回零重绘。"""
        scale = self.transform().m11()
        if scale >= _CURSOR_MIN_PX:
            # 吸附模式：一格已足够大，框对齐鼠标所在方块
            wx = int(math.floor(scene_x))
            wz = int(math.floor(scene_y))
            new = QRectF(wx, wz, 1.0, 1.0)
        else:
            # 顺滑模式：框中心 = 鼠标位置，场景边长 = 屏幕像素 / scale
            half = _CURSOR_MIN_PX / (2.0 * scale) if scale > 0 else 8.0
            new = QRectF(scene_x - half, scene_y - half,
                         half * 2.0, half * 2.0)
        old = self._cursor_rect
        if old == new:
            return
        self._cursor_rect = new
        if old is not None:
            self._update_cursor_region(old)
        self._update_cursor_region(new)

    def drawForeground(self, painter, rect) -> None:
        super().drawForeground(painter, rect)
        r = self._cursor_rect
        if r is None or not r.intersects(rect):
            return
        # 双色描边（黑 3px 外框 + 白 1px 内芯）：雪地看黑边、暗地表看
        # 白芯，任何背景至少一条线可见（反色方案在中间调背景上对比度
        # 同样不足，弃用）。cosmetic 线宽 = 屏幕像素，不随缩放。
        pen = QPen(QColor(0, 0, 0, 170))
        pen.setCosmetic(True)
        pen.setWidthF(3.0)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(220, 220, 220, 36)))
        painter.drawRect(r)
        pen2 = QPen(QColor(255, 255, 255, 210))
        pen2.setCosmetic(True)
        painter.setPen(pen2)
        painter.setBrush(Qt.BrushStyle.NoBrush)   # 填充只叠一次
        painter.drawRect(r)

    def wheelEvent(self, ev) -> None:
        steps = ev.angleDelta().y() / 120.0
        cur = self.transform().m11()
        if cur <= 0:
            return
        # 限制最小缩放：可见范围不超过 _MAX_VISIBLE_REGIONS 见方，否则
        # 视口对应的 world 坐标范围爆炸、请求无数 region 卡死。
        new_scale = cur * (1.25 ** steps)
        vmin = max(min(self.viewport().width(), self.viewport().height()), 1)
        min_scale = vmin / (REGION_BLOCKS * _MAX_VISIBLE_REGIONS)
        if new_scale < min_scale:
            new_scale = min_scale
        self.scale(new_scale / cur, new_scale / cur)
        self._prefetch_ring = 0   # 视口变化：预取圈数重置
        self._schedule_timer.start()
        # 缩放后同一视口像素对应新的场景点：光标框重新定位到鼠标
        # 下方（吸附/顺滑由 _update_cursor 按缩放档决定）
        if self._cursor_vp is not None:
            sp = self.mapToScene(self._cursor_vp)
            self._update_cursor(sp.x(), sp.y())

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        # 拖动/滚动视口变化：重置预取圈数并延迟补渲染（此前拖动后没有
        # 触发链，新视口的补渲染只能靠 wheel/fit 遗留的调度兜底）。
        self._prefetch_ring = 0
        self._schedule_timer.start()
        # 拖动中鼠标不动、地图动：用最后的鼠标视口位置重新定位
        # 光标框，保证它始终跟随鼠标下方（而非钉在地图上随地图滑走）
        if self._cursor_vp is not None:
            sp = self.mapToScene(self._cursor_vp)
            self._update_cursor(sp.x(), sp.y())

    def _emit_hover(self, wx: int, wz: int, force: bool = False) -> None:
        """悬停取色（慢速路径）：坐标与上次提交相同（吸附框同格内微动）
        时整段跳过——纯坐标与完整文本高频交替正是状态栏闪烁之源；
        不同时提交后台取色，结果回主线程补发完整文本（慢速路径不再
        单独发纯坐标，状态栏格式恒为完整文本一种，不再来回跳）。
        force=True（settle 恢复）绕过同格跳过，强制重新取色。"""
        if self._world_path is None:
            return
        if not force and (wx, wz) == self._last_submitted:
            return   # 同格：框没动、方块没变，状态栏无需任何更新
        self._last_submitted = (wx, wz)
        self._hover_seq += 1
        self._hover_worker.submit(self._hover_seq, wx, wz,
                                  self._world_path, self._dimension)

    def _on_hover_hit(self, seq: int, text: str) -> None:
        """worker 取色结果回主线程：seq 与最新请求一致才补发完整文本
        （期间鼠标又动了则已有新请求在途，本结果过期丢弃）；未命中
        （空气/未生成 chunk）为空串同样丢弃；文本与当前显示相同
        （同格重复请求）也不再刷状态栏。"""
        if seq != self._hover_seq or not text:
            return
        if text == self._last_hover_text:
            return
        self._last_hover_text = text
        self.hover_info.emit(text)

    # ---------- 右键区块预览 ----------
    def world_pos_at(self, pos) -> tuple[int, int] | None:
        """视口像素位置 -> 世界方块坐标（floor）。无存档返回 None。
        右键菜单点查用（不依赖悬停状态，点击点即时换算）。"""
        if self._world_path is None:
            return None
        sp = self.mapToScene(pos)
        return (int(math.floor(sp.x())), int(math.floor(sp.y())))

    def _hover_settle(self) -> None:
        """快速移动后静止 80ms：恢复完整悬停取色（定时器被每个快速
        move 重置，超时即鼠标已停）。force=True 绕过同格跳过——快速
        微动后坐标虽未变，仍需从纯坐标恢复完整文本。"""
        if not self._hover_fast or self._cursor_vp is None:
            return
        self._hover_fast = False
        sp = self.mapToScene(self._cursor_vp)
        self._emit_hover(int(math.floor(sp.x())), int(math.floor(sp.y())),
                         force=True)

    def mouseMoveEvent(self, ev) -> None:
        super().mouseMoveEvent(ev)
        pos = ev.pos()
        now = time.monotonic()
        scene_pt = self.mapToScene(pos)
        # 光标框：恒显示恒跟随（Smart 局部重绘成本低，无状态切换）
        self._cursor_vp = QPoint(pos.x(), pos.y())
        self._update_cursor(scene_pt.x(), scene_pt.y())
        # 悬停取色：速度低于阈值才提交后台取色（快速移动即使异步也会
        # 制造大量无谓读盘请求）；快速时只刷纯坐标 + 消抖定时器（停
        # 80ms 自动恢复完整取色）。取色本身已移入 _HoverWorker（冷
        # 读 10~20ms，主线程零阻塞）。
        dt = now - self._cursor_last_t
        if self._cursor_last_pos is not None and dt >= 0.002:
            speed = math.hypot(pos.x() - self._cursor_last_pos.x(),
                               pos.y() - self._cursor_last_pos.y()) / dt
            self._hover_fast = speed > _CURSOR_HOVER_MAX_SPEED
        self._cursor_last_pos = QPointF(pos)
        self._cursor_last_t = now
        # 取色坐标与光标框同基准（floor）：鼠标在方块右半时 round 会
        # 给出右边相邻方块，取色错位（实测方块名跳成旁边方块）
        wx = int(math.floor(scene_pt.x()))
        wz = int(math.floor(scene_pt.y()))
        # 悬停世界坐标广播（右键菜单等用）：同格微动去重，避免无谓信号
        if (wx, wz) != self._last_hover_pos:
            self._last_hover_pos = (wx, wz)
            self.hover_pos.emit(wx, wz)
        if self._hover_fast:
            text = f"X: {wx}  Z: {wz}"
            if text != self._last_hover_text:   # 同格微动不重发
                self._last_hover_text = text
                self.hover_info.emit(text)
            self._hover_settle_timer.start()
        else:
            self._hover_settle_timer.stop()
            self._emit_hover(wx, wz)

    # ---------- 渲染进度条 ----------
    def _prog_reset(self) -> None:
        """清空已渲染计数并广播（切存档/切阴影时缓存被清，进度从零重算）。

        分母（_prog_chunk_total）由 set_save 按存档总量设定，此处不动。
        """
        self._prog_chunk_done = 0
        self._prog_counted.clear()
        self._prog_timer_hide.stop()
        self.progress_changed.emit(self._prog_chunk_total, 0)

    def _prog_hide(self) -> None:
        """全存档渲染完成后的满格停留结束：隐藏进度条（计数保留，
        信号约定 total=0 → 监听方隐藏）。"""
        self._prog_timer_hide.stop()
        self.progress_changed.emit(0, 0)

    def _prog_add_request(self, key: tuple[int, int]) -> None:
        """请求发出时广播当前进度（让进度条先于首个完成出现）。"""
        self.progress_changed.emit(self._prog_chunk_total,
                                   self._prog_chunk_done)

    def _prog_finish_one(self, key: tuple[int, int]) -> None:
        """某 region 回屏（成功/失败都算）时累计已渲染区块数（全存档
        去重：_prog_counted 记录已计 key，重复回屏不双计）；全存档渲
        完（done>=total）则满格停留片刻后隐藏（QTimer → _prog_hide）。"""
        if key in self._prog_counted:
            return   # 已计入（重复回屏防双计）
        c = self._region_chunk_counts.get(key, 0)
        self._prog_counted[key] = c
        self._prog_chunk_done += c
        self.progress_changed.emit(self._prog_chunk_total,
                                   self._prog_chunk_done)
        if self._prog_chunk_done >= self._prog_chunk_total:
            self._prog_timer_hide.start()

    # ---------- 阴影 ----------
    def set_hillshade(self, on: bool) -> None:
        """开关地形阴影；切换后清瓦片缓存并按新设置重渲染可见 region。"""
        if self._render_thread is None:
            return
        self._render_thread._hillshade = bool(on)
        self._render_thread.new_generation()   # 旧阴影设置的在渲染瓦片作废
        # 阴影改变 → 已上屏/缓存瓦片需重绘：清空后重新调度可见 region
        self._scene.clear()
        self._tile_items.clear()
        self._tile_pending.clear()
        self._tile_order.clear()
        self._prefetch_ring = 0
        self._prog_reset()   # 缓存清空 → 已渲染计数归零重算
        if self._world_path is not None:
            self._schedule_timer.start()

    # ---------- 清理 ----------
    def shutdown(self) -> None:
        self._hover_worker.stop()
        self._hover_worker.wait(2000)
        if self._render_thread is not None:
            self._render_thread.cancel()
            self._render_thread.wait(2000)
