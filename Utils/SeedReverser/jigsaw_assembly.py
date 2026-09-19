# -*- coding: utf-8 -*-
"""堡垒遗迹 jigsaw 拼装引擎 v2 —— 逐字节码复刻 1.21.1 原版生成算法。

字节码定案依据（工作空间 .temp/jigsaw_classes/*.txt）：
- ejk.a(...)      起点入口：rot=rotation_get_random(1 次)；
                  elem=起点池 weight 展开列表[nextInt(len)](1 次)；
                  pos=(chunkX*16, 33, chunkZ*16)；box=getBoundingBox(pos,rot)；
                  move(0, 33-(box.minY+1), 0)   [ekz.g()==1]
- ekv.a(...) 18参 外层大盒（max_distance=80, y∈[-47,114]），
  freeSpace = 大盒 ─ 起点box（VoxelShape, exg.e=ONLY_FIRST）
- ekv.a(...) 13参 驱动：new ekv$b 后立即对起点调
  tryPlacingChildren(起点, new MutableObject(freeSpace), 0, ...)，
  之后循环 ayz 队列：出队 ekv$a(piece, mutableDomain, depth)，
  用 item 自带的 mutableDomain 继续放置（bastion 全 0 优先级 → FIFO）
- ekv$b.a(...)    tryPlacingChildren：
  * 标记集 = 模板 jigsaw 方块（mode=solid），世界坐标 = piecePos+rot(局部)
  * 域选择：父标记 targetPos ∈ 父 box → 用 piece 私有 MutableObject
    （懒初始化 = 父 box 形状拷贝，**整棵子树共享**）；否则用 piece 携带的
    MutableObject。子 piece 入队时携带本次实际使用的域引用（ekv$a）
  * 候选 = [main池 shuffle(len-1) 若 depth!=maxDepth]
           + [fallback 池 shuffle(len-1)]（weight 展开，bastion 全 rigid）
  * 每候选（非 empty 元素）：rotations=rotation_shuffled（3 次消耗）
  * 每旋转：childMarkers = getJigsawBlocks(ZERO, rot)
    = 收集 jigsaw 方块 → shuffle(M-1) → selection_priority 降序稳定排序
    （bastion 全 0 → 排序 no-op）
  * 连接判定 dka.a(父标记, 子标记)：父front==opposite(子front)
    且 (父joint==ROLLABLE 或 父top==子top) 且 父target==子name
    （joint 缺省：父 front 水平→ROLLABLE，竖直→ALIGNED）
  * anchor = targetPos(父标记世界位+rot(父front).step) − rot(子标记局部位)
    [jd.b(Lkh;) 为取负相加；dka.m(父front).k() 为 front.stepY]
  * rigid-rigid：freeY = 父box.minY+(父标记世界Y−父box.minY)−子标记局部Y
    +rot(父front).stepY == anchor.y（代数恒等）→ dy = 0
  * 碰撞 exs.c(域, child.deflate(0.25), exg.c=ONLY_SECOND)：
    join(域, child收缩, ONLY_SECOND) 非空 = child 露出域外 → 拒绝；
    通过 → 域 = join(域, child全盒, exg.e=ONLY_FIRST)（挖掉整个 child）；
    整数对齐盒下 deflate(0.25) 退化为：child 完整⊆域边界盒 且
    不与任何已挖除盒共享整数格（贴面合法）。
- eju/eku 记账仅为游戏内部用途，渲染不需要，未实现。

对外接口：
    assemble_bastion(level_seed, chunk_x, chunk_z) -> AssemblyResult
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .mc_rng import (LegacyRandomSource, make_layout_rng,
                     mth_get_seed, rotation_get_random, rotation_shuffled,
                     shuffle_list)
from .structure_models import parse_nbt

# ===========================================================================
# 常量（bastion_remnant.json + 字节码）
# ===========================================================================
BASTION_MAX_DEPTH = 6          # size=6
BASTION_MAX_DIST = 80          # max_distance
BASTION_START_Y = 33           # start_height absolute=33
BASTION_PAD_BOTTOM = 0
BASTION_PAD_TOP = 0
BEARDIZER_MIN_Y = -64
BEARDIZER_MAX_Y = 320
PROJ_ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = PROJ_ROOT / "assets" / "SeedReverser" / "bastion"


def _tpl_path(key: str) -> Path:
    """'bastion/units/air_base' -> templates/units/air_base.nbt
    （资产目录已以 bastion 为根，资源 key 里的 bastion/ 前缀去掉一层）
    trial 同理：'trial_chambers/hallway/straight' ->
    trial_chambers/templates/hallway/straight.nbt（trial_assembly 注入
    自己的加载器，不走本函数；bastion 路径仅用 bastion 前缀）。"""
    parts = key.split("/")
    if parts and parts[0] == "bastion":
        parts = parts[1:]
    return ASSET_DIR / "templates" / Path(*parts).with_suffix(".nbt")


def _pool_path(pool_id: str) -> Path:
    # 池 JSON 实际存放在 template_pool/bastion/<id>.json，保留完整 key
    return (ASSET_DIR / "template_pool"
            / Path(*pool_id.split("/")).with_suffix(".json"))

# ===========================================================================
# 方向 / 旋转 / 形状（ji / dmm / orientation）
# ===========================================================================
DIR_VECTORS: Dict[str, Tuple[int, int, int]] = {
    "down": (0, -1, 0), "up": (0, 1, 0),
    "north": (0, 0, -1), "south": (0, 0, 1),
    "west": (-1, 0, 0), "east": (1, 0, 0),
}
_DIRS = {v: k for k, v in DIR_VECTORS.items()}
OPPOSITE: Dict[str, str] = {
    "down": "up", "up": "down",
    "north": "south", "south": "north",
    "west": "east", "east": "west",
}


def rot_rotate_dir(rot: str, d: str) -> str:
    """dmm.a(ji)：方向向量旋转（水平旋转，竖直不变）。"""
    x, y, z = DIR_VECTORS[d]
    if rot == "NONE":
        return d
    if rot == "CLOCKWISE_90":
        return _DIRS[(-z, y, x)]
    if rot == "CLOCKWISE_180":
        return _DIRS[(-x, y, -z)]
    if rot == "COUNTERCLOCKWISE_90":
        return _DIRS[(z, y, -x)]
    raise ValueError(rot)


def rot_piece_pos(rot: str, pos: Tuple[int, int, int],
                  size_x: int, size_z: int) -> Tuple[int, int, int]:
    """dmm.a(int,int,int)：体素/局部坐标旋转（Y 不变）。"""
    x, y, z = pos
    if rot == "NONE":
        return (x, y, z)
    if rot == "CLOCKWISE_90":
        return (size_z - 1 - z, y, x)
    if rot == "CLOCKWISE_180":
        return (size_x - 1 - x, y, size_z - 1 - z)
    if rot == "COUNTERCLOCKWISE_90":
        return (z, y, size_x - 1 - x)
    raise ValueError(rot)


def rot_size(rot: str, size_x: int, size_y: int, size_z: int
             ) -> Tuple[int, int, int]:
    if rot in ("CLOCKWISE_90", "COUNTERCLOCKWISE_90"):
        return (size_z, size_y, size_x)
    return (size_x, size_y, size_z)


class BBox:
    """整方块包围盒 [minX, maxX] × [minY, maxY] × [minZ, maxZ]（闭区间）。"""
    __slots__ = ("x0", "y0", "z0", "x1", "y1", "z1")

    def __init__(self, x0: int, y0: int, z0: int, x1: int, y1: int, z1: int):
        self.x0, self.y0, self.z0 = x0, y0, z0
        self.x1, self.y1, self.z1 = x1, y1, z1

    @classmethod
    def from_pos_size(cls, pos: Tuple[int, int, int],
                      size: Tuple[int, int, int]) -> "BBox":
        return cls(pos[0], pos[1], pos[2], pos[0] + size[0] - 1,
                   pos[1] + size[1] - 1, pos[2] + size[2] - 1)

    def moved(self, dx: int, dy: int, dz: int) -> "BBox":
        return BBox(self.x0 + dx, self.y0 + dy, self.z0 + dz,
                    self.x1 + dx, self.y1 + dy, self.z1 + dz)

    def contains(self, x: int, y: int, z: int) -> bool:
        return (self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1
                and self.z0 <= z <= self.z1)


def _contains(child: BBox, region: BBox) -> bool:
    """child 完整落在 region 边界盒内（整数格，闭区间）。"""
    return (region.x0 <= child.x0 and child.x1 <= region.x1
            and region.y0 <= child.y0 and child.y1 <= region.y1
            and region.z0 <= child.z0 and child.z1 <= region.z1)


def _encapsulate(boxes: List[BBox]) -> BBox:
    """BoundingBox.encapsulatingBoxes：多盒最小包围盒。"""
    return BBox(min(b.x0 for b in boxes), min(b.y0 for b in boxes),
                min(b.z0 for b in boxes), max(b.x1 for b in boxes),
                max(b.y1 for b in boxes), max(b.z1 for b in boxes))


def _flat_terrain_height(x: int, z: int) -> int:
    """terrain_matching getFirstFreeHeight 的缺省近似（无高度图注入时）：
    返回海平面 63（WORLD_SURFACE_WG 无地形数据的平坦基准）。"""
    return 63


def _share_cell(a: BBox, b: BBox) -> bool:
    """两盒是否共享至少一个整数格（贴面相邻 = False）。"""
    return (a.x0 <= b.x1 and b.x0 <= a.x1
            and a.y0 <= b.y1 and b.y0 <= a.y1
            and a.z0 <= b.z1 and b.z0 <= a.z1)


class Domain:
    """freeSpace 允许域（VoxelShape AABB 近似）：
    - bounds: 域边界盒（初始 = 大盒 或 父box）
    - holes:  已挖除盒列表
    拒绝 = child 收缩 0.25 后露出域外 = child 不完整在 bounds 内
           或与任一 hole 共享整数格（deflate(0.25) 在整数栅格上退化为
           无格重叠判定，贴面合法）。
    """

    def __init__(self, bounds: BBox):
        self.bounds = bounds
        self.holes: List[BBox] = []

    def subtract(self, box: BBox) -> None:
        self.holes.append(box)

    def rejects(self, child: BBox) -> bool:
        if not _contains(child, self.bounds):
            return True
        return any(_share_cell(child, h) for h in self.holes)


# ===========================================================================
# 域（exs VoxelShape 的「允许域+挖除」模型，见模块头语义说明）
# ===========================================================================



# ===========================================================================
# 模板模型（ekz + ent NBT）
# ===========================================================================
@dataclass
class JigsawMarker:
    local_pos: Tuple[int, int, int]        # （旋转后）世界或局部坐标
    front: str
    top: str
    joint: Optional[str]                   # NBT joint（bastion 全显式）
    name: str
    target: str
    pool: str
    placement_priority: int


@dataclass
class TemplateModel:
    key: str
    size_x: int
    size_y: int
    size_z: int
    markers: List[JigsawMarker] = field(default_factory=list)

    def markers_at(self, rot: str) -> List[JigsawMarker]:
        """getJigsawBlocks 的标记部分：局部 pos/front/top 经 rot 变换。"""
        out: List[JigsawMarker] = []
        for m in self.markers:
            p = rot_piece_pos(rot, m.local_pos, self.size_x, self.size_z)
            out.append(JigsawMarker(
                local_pos=p,
                front=rot_rotate_dir(rot, m.front),
                top=rot_rotate_dir(rot, m.top),
                joint=m.joint, name=m.name, target=m.target, pool=m.pool,
                placement_priority=m.placement_priority))
        return out

    def get_bounding_box(self, piece_pos: Tuple[int, int, int], rot: str
                         ) -> BBox:
        sx, sy, sz = rot_size(rot, self.size_x, self.size_y, self.size_z)
        return BBox.from_pos_size(piece_pos, (sx, sy, sz))


def parse_orientation(ori: str) -> Tuple[str, str]:
    """'north_up' -> ('north','up')。"""
    front, top = ori.split("_", 1)
    return front, top


_TEMPLATE_CACHE: Dict[str, TemplateModel] = {}


def _parse_template(key: str, path: Path) -> TemplateModel:
    """模板 NBT 解析（load_template / trial_assembly 共用，纯解析无缓存）。"""
    root = parse_nbt(path.read_bytes())
    size = root["size"][1]                     # TAG_Int_List -> (9, [x,y,z])
    sx, sy, sz = int(size[0]), int(size[1]), int(size[2])
    palette = root["palette"][1]
    jigsaw_ori = {}
    for i, st in enumerate(palette):
        name = st.get("Name", st.get("name", ""))
        if name == "minecraft:jigsaw":
            props = st.get("Properties") or st.get("properties") or {}
            jigsaw_ori[i] = parse_orientation(props.get("orientation", "up_up"))
    markers: List[JigsawMarker] = []
    for blk in root["blocks"][1]:
        ori = jigsaw_ori.get(blk["state"])
        if ori is None:
            continue
        nbt = blk.get("nbt") or {}
        bp = blk["pos"][1]                     # TAG_Int_List -> (9, [x,y,z])
        markers.append(JigsawMarker(
            local_pos=(int(bp[0]), int(bp[1]), int(bp[2])),
            front=ori[0], top=ori[1],
            joint=nbt.get("joint"),
            name=nbt.get("name", "minecraft:empty"),
            target=nbt.get("target", "minecraft:empty"),
            pool=nbt.get("pool", "minecraft:empty"),
            placement_priority=int(nbt.get("placement_priority", 0))))
    return TemplateModel(key=key, size_x=sx, size_y=sy, size_z=sz,
                         markers=markers)


def load_template(key: str) -> TemplateModel:
    tm = _TEMPLATE_CACHE.get(key)
    if tm is not None:
        return tm
    tm = _parse_template(key, _tpl_path(key))
    _TEMPLATE_CACHE[key] = tm
    return tm


# ===========================================================================
# 结构池（jm/elb）
# ===========================================================================
@dataclass
class PoolElement:
    location: str
    projection: str
    element_type: str
    weight: int
    # 池 JSON 元素的 processors 字段（字符串 id；dict/缺失 = None）。
    # bastion/trial 池全无此字段；village 各池逐元素引用处理器 id，
    # 经 JigsawPiece.processor 传到渲染层分发降解。
    processors: Optional[str] = None


@dataclass
class ListPoolElementSpec:
    """list_pool_element 候选（towers 池）：getShuffledJigsawBlocks
    委托 elements[0]（ListPoolElement.java L55-57），place 依序放置
    全部子元素（L79-83），bbox = 子元素盒 encapsulating（L60-63）。
    其余 element 类型字段沿用 PoolElement 语义：location=elements[0]
    模板 key（标记源）、sub_locations=全部子模板 key（放置源）。
    sub_processors=各子元素处理器 id（None=无；outpost overgrown 子
    元素带 minecraft:outpost_rot，渲染层按此选择性降解）。"""
    location: str
    projection: str
    weight: int
    sub_locations: List[str] = field(default_factory=list)
    sub_processors: List[Optional[str]] = field(default_factory=list)


@dataclass
class StructureTemplatePool:
    pool_id: str
    elements: List[PoolElement]
    fallback: Optional[str]
    # 1.21.11 起始池语义（elb.getRandomTemplate → WeightedList）：
    # None = 旧式展开列表抽取；("list", items) = 预展开抽索引。
    start_variant: Optional[tuple] = None


_POOL_CACHE: Dict[str, StructureTemplatePool] = {}


def _pool_from_json(pool_id: str, data: dict,
                    list_element_hook=None) -> StructureTemplatePool:
    elems = []
    for e in data.get("elements", []):
        el = e["element"]
        if (el.get("element_type", "").endswith("list_pool_element")
                and list_element_hook is not None):
            elems.append(list_element_hook(el))
            continue
        elems.append(PoolElement(
            location=el.get("location", "").split(":", 1)[-1],
            projection=el.get("projection", "rigid"),
            element_type=el.get("element_type", ""),
            weight=int(e.get("weight", 1)),
            processors=_proc_id(el.get("processors"))))
    fb = data.get("fallback", None)
    if fb is not None:
        fb = str(fb).split(":", 1)[-1]
    return StructureTemplatePool(pool_id=pool_id, elements=elems,
                                 fallback=fb)


def load_pool(pool_id: str) -> StructureTemplatePool:
    p = _POOL_CACHE.get(pool_id)
    if p is not None:
        return p
    if pool_id == "empty":
        # minecraft:empty：注册过的空池（0 元素、无 fallback），无 JSON 文件
        p = StructureTemplatePool(pool_id=pool_id, elements=[], fallback=None)
        _POOL_CACHE[pool_id] = p
        return p
    path = _pool_path(pool_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    p = _pool_from_json(pool_id, data)
    _POOL_CACHE[pool_id] = p
    return p


def parse_pool_dict(pool_id: str, data: dict,
                    list_element_hook=None) -> StructureTemplatePool:
    """从已解析的池 JSON dict 构建池（trial_assembly 内嵌池数据用，
    语义与 load_pool 的 JSON 解析段一致；同样走 _POOL_CACHE）。
    trial 池含 feature_pool_element 等无 location 的元素：location 存
    空串，Placer 按 element_type 过滤（feature→continue，
    empty→break 终止候选），与 fgs$b 语义一致。
    list_element_hook(list_spec_dict) -> PoolElement：可选，把
    list_pool_element 原始 dict 转为引擎可放置的候选表示。"""
    p = _POOL_CACHE.get(pool_id)
    if p is not None:
        return p
    elems = []
    for e in data.get("elements", []):
        el = e["element"]
        if (el.get("element_type", "").endswith("list_pool_element")
                and list_element_hook is not None):
            elems.append(list_element_hook(el))
            continue
        elems.append(PoolElement(
            location=el.get("location", "").split(":", 1)[-1],
            projection=el.get("projection", "rigid"),
            element_type=el.get("element_type", ""),
            weight=int(e.get("weight", 1)),
            processors=_proc_id(el.get("processors"))))
    fb = data.get("fallback", None)
    if fb is not None:
        fb = str(fb).split(":", 1)[-1]
    p = StructureTemplatePool(pool_id=pool_id, elements=elems, fallback=fb)
    _POOL_CACHE[pool_id] = p
    return p


def _proc_id(proc) -> Optional[str]:
    """池元素 processors 字段 -> 处理器 id（字符串 = 剥命名空间；
    dict/缺失 = None。内联 dict 处理器链村庄全为空 dict，同 None）。"""
    if isinstance(proc, str):
        return proc.split(":", 1)[-1]
    return None


def expanded_pool(pool: StructureTemplatePool) -> List:
    """elb.b(ayw) shuffle 前的 weight 展开列表（JSON 顺序）。"""
    out: List = []
    for e in pool.elements:
        out.extend([e] * e.weight)
    return out


def pool_max_yspan(pool: StructureTemplatePool,
                   load_template_fn=None) -> int:
    """elb.getMaxSize（StructureTemplatePool.java L83-94）：非 empty
    候选模板在 Rotation.NONE 下的 y 跨度最大值（缓存于池对象）。"""
    if getattr(pool, "_max_yspan", None) is not None:
        return pool._max_yspan
    _lt = load_template_fn or load_template
    best = 0
    for e in pool.elements:
        if getattr(e, "element_type", "").endswith("empty_pool_element"):
            continue
        locs = getattr(e, "sub_locations", None) or [e.location]
        for k in locs:
            if not k:
                continue
            best = max(best, _lt(k).size_y)
    pool._max_yspan = best
    return best


def _strip(rid: Optional[str]) -> Optional[str]:
    if rid is None:
        return None
    return rid.split(":", 1)[-1] if ":" in rid else rid


# ===========================================================================
# Piece 与结果
# ===========================================================================
@dataclass
class JigsawPiece:
    template: TemplateModel
    rot: str
    piece_pos: Tuple[int, int, int]
    box: BBox
    depth: int
    # getProjection（$$11/$$43）：rigid 判定用（try_placing_children
    # 的 y 定位分支）；起点件由 assemble_jigsaw 按 start pool 元素填
    projection: str = "rigid"
    # list_pool_element 放置的子模板全集（template 字段 = elements[0]；
    # 渲染层依序全部叠加，ListPoolElement.place L79-83）。
    # sub_processors 与 sub_templates 一一对应（None=无处理器）
    sub_templates: Optional[List[str]] = None
    sub_processors: Optional[List[Optional[str]]] = None
    # 池元素处理器 id（single/legacy 候选；list 候选用 sub_processors）
    processor: Optional[str] = None
    _world_markers: Optional[List[JigsawMarker]] = None

    def world_markers(self) -> List[JigsawMarker]:
        if self._world_markers is None:
            base = self.template.markers_at(self.rot)
            px, py, pz = self.piece_pos
            self._world_markers = [
                JigsawMarker(
                    local_pos=(m.local_pos[0] + px, m.local_pos[1] + py,
                               m.local_pos[2] + pz),
                    front=m.front, top=m.top, joint=m.joint, name=m.name,
                    target=m.target, pool=m.pool,
                    placement_priority=m.placement_priority)
                for m in base]
        return self._world_markers


@dataclass
class AssemblyResult:
    pieces: List[JigsawPiece]
    start_index: int
    rng_calls: List[str]


# ===========================================================================
# ayz 优先队列（bastion 全 0 → FIFO；仍按 (priority, 插入序) 实现通用语义）
# ===========================================================================
class PriorityWorkQueue:
    def __init__(self) -> None:
        self._items: List[Tuple[int, int, JigsawPiece, object]] = []
        self._seq = 0

    def append(self, piece: JigsawPiece, domain, priority: int) -> None:
        self._items.append((priority, self._seq, piece, domain))
        self._seq += 1

    def pop_front(self):
        if not self._items:
            return None
        best_i = 0
        for i in range(1, len(self._items)):
            if self._items[i][:2] < self._items[best_i][:2]:
                best_i = i
        item = self._items.pop(best_i)
        return item[2], item[3]


# ===========================================================================
# 连接判定（dka.a）
# ===========================================================================
def _default_joint(front: str) -> str:
    # dka 私有 a(ji)：ji.o().d()==isVertical → ALIGNED else ROLLABLE
    return "aligned" if front in ("up", "down") else "rollable"


def _connects(parent: JigsawMarker, child: JigsawMarker) -> bool:
    parent_joint = parent.joint or _default_joint(parent.front)
    if parent.front != OPPOSITE[child.front]:
        return False
    if not (parent_joint == "rollable" or parent.top == child.top):
        return False
    return _strip(parent.target) == _strip(child.name)


# ===========================================================================
# Placer（ekv$b）
# ===========================================================================
class _Placer:
    def __init__(self, rng: LegacyRandomSource, rng_log: List[str],
                 max_depth: int = 6,
                 load_pool_fn=None, load_template_fn=None,
                 expansion_hack: bool = False,
                 terrain_height_fn=None):
        self.rng = rng
        self.log = rng_log
        self.max_depth = max_depth
        # 池/模板加载器（默认 = 本模块 bastion 资产根的 load_pool /
        # load_template；trial_assembly 注入绑定自己资产根的版本）
        self._load_pool = load_pool_fn or load_pool
        self._load_template = load_template_fn or load_template
        # use_expansion_hack（JigsawStructure）：子件盒顶部按池 maxSize
        # 扩展（fgs$b L315-342/L368-371）；bastion/trial 均为 False
        self.expansion_hack = expansion_hack
        # terrain_matching 子件 y 定位（getFirstFreeHeight 近似；
        # bastion/trial 全 rigid 不经此路径）
        self.terrain_height = terrain_height_fn or _flat_terrain_height

    def _child_markers_shuffled(self, template: TemplateModel, rot: str
                                ) -> List[JigsawMarker]:
        ms = template.markers_at(rot)
        if len(ms) > 1:
            self.log.append(f"marker_shuffle(M={len(ms)})")
            ms = shuffle_list(self.rng, ms)
        # selection_priority 降序稳定排序（bastion/trial 全 0 → no-op）
        return sorted(ms, key=lambda m: -m.placement_priority)

    def _parent_markers_shuffled(self, piece: JigsawPiece
                                 ) -> List[JigsawMarker]:
        """父件标记 = element.getShuffledJigsawBlocks(piecePos, rot, rng)
        （JigsawPlacement.java L264 → SinglePoolElement L108-113）：
        getJigsaws（世界坐标）→ Util.shuffle（每次 tryPlacingChildren
        都消耗，M>1 时 M-1 次 nextInt）→ selection_priority 降序稳定
        排序（L111）。list_pool_element 委托 elements[0]，与引擎把
        候选 location 指向 elements[0] 模板的表示一致。"""
        ms = piece.world_markers()
        if len(ms) > 1:
            self.log.append(f"parent_marker_shuffle(M={len(ms)})")
            ms = shuffle_list(self.rng, ms)
        return sorted(ms, key=lambda m: -m.placement_priority)

    def _candidate_boxes(self, cand, rot: str) -> List[Tuple[str, BBox]]:
        """候选元素在 rot 下的 (模板key, box) 列表（BlockPos.ZERO 局部）。
        single/legacy：单模板盒；list：子元素盒 encapsulating
        （ListPoolElement.getBoundingBox L60-63）。"""
        if isinstance(cand, ListPoolElementSpec):
            boxes = [self._load_template(k).get_bounding_box((0, 0, 0), rot)
                     for k in cand.sub_locations]
            return [(cand.sub_locations[0], _encapsulate(boxes))]
        tpl = self._load_template(cand.location)
        return [(cand.location, tpl.get_bounding_box((0, 0, 0), rot))]

    def _candidate_projection(self, cand) -> str:
        if isinstance(cand, ListPoolElementSpec):
            return cand.projection
        return getattr(cand, "projection", "rigid")

    def try_placing_children(self, piece: JigsawPiece,
                             carried_domain: Domain, depth: int,
                             workq: PriorityWorkQueue,
                             pieces: List[JigsawPiece]) -> None:
        """ekv$b.tryPlacingChildren（JigsawPlacement.java L244-416）逐行
        转写。结构：父标记循环 → 域选择 → 候选池 → 候选循环（empty
        break / 其他先 rotation_shuffled）→ 旋转循环（expansion hack
        的 $$37 在旋转循环内）→ 子标记循环（canAttach → y 定位 → 盒
        扩展 → 碰撞 → 放置）。"""
        rng = self.rng
        private_domain = None                     # 懒初始化（MutableObject）
        expansion_hack = self.expansion_hack
        # fgs$b：父 box minY 记账（L261 $$15 = $$14.minY()）
        parent_min_y = piece.box.y0
        # $$21 = 标记世界Y − 父box.minY（L269，父标记循环体常量）
        # $$22 = getFirstFreeHeight 缓存（L270 初值 MIN_VALUE，L358 惰性求值）
        terrain_y_cache: dict = {}
        rigid_parent = piece.projection == "rigid"       # $$12（L257-258）

        # L264：父标记 = element.getShuffledJigsawBlocks(pos, rot, rng)
        for pmark in self._parent_markers_shuffled(piece):
            pw = pmark.local_pos
            fvec = DIR_VECTORS[pmark.front]
            target_pos = (pw[0] + fvec[0], pw[1] + fvec[1], pw[2] + fvec[2])
            # $$21（L269）与 front.stepY（L353 用）
            mark_rel_y = pw[1] - parent_min_y
            step_y = fvec[1]

            # ---- 域选择（L285-294）：父标记 targetPos ∈ 父 box → 私有域
            if piece.box.contains(*target_pos):
                if private_domain is None:
                    private_domain = Domain(piece.box)   # 新鲜父盒拷贝
                domain = private_domain
            else:
                domain = carried_domain

            # ---- 候选池（L271-301）----
            pool_id = _strip(pmark.pool)
            if pool_id is None or pool_id == "empty":
                continue
            pool = self._load_pool(pool_id)
            fallback_id = _strip(pool.fallback) if pool.fallback else None
            if fallback_id is None:
                continue
            candidates: List = []
            if depth != self.max_depth:
                self.log.append(f"main_shuffle(pool={pool_id})")
                candidates += shuffle_list(rng, expanded_pool(pool))
            fb_pool = self._load_pool(fallback_id)
            self.log.append(f"fallback_shuffle(pool={fallback_id})")
            candidates += shuffle_list(rng, expanded_pool(fb_pool))

            # L302 $$31 = 父标记 placementPriority（入队用）
            for cand in candidates:                  # $$30 候选循环
                ctype = getattr(cand, "element_type", "") or (
                    "minecraft:list_pool_element"
                    if isinstance(cand, ListPoolElementSpec) else "")
                if ctype.endswith("empty_pool_element"):
                    break                          # $$32 == INSTANCE 终止
                if ctype.endswith("feature_pool_element"):
                    # getShuffledJigsawBlocks 固定单元素不消耗 RNG、
                    # getSize=ZERO 永不连接；但外层 Rotation.getShuffled
                    # （L309）对非 empty 候选无条件消耗 → continue
                    self.log.append("rotation_shuffled")
                    rotation_shuffled(rng)
                    continue
                if not (ctype.endswith("single_pool_element")
                        or isinstance(cand, ListPoolElementSpec)):
                    continue
                self.log.append("rotation_shuffled")
                rotations = rotation_shuffled(rng)
                # 子件标记源模板（list 候选 = elements[0] 委托）
                cand_tpl_key = (cand.sub_locations[0]
                                if isinstance(cand, ListPoolElementSpec)
                                else cand.location)

                for rot in rotations:                # L309 旋转循环
                    # $$34 = 子标记（L310-312 getShuffledJigsawBlocks）
                    cmarks = self._child_markers_shuffled(
                        self._load_template(cand_tpl_key), rot)
                    # $$35 = 候选盒（L313，BlockPos.ZERO 局部）
                    cand_boxes = self._candidate_boxes(cand, rot)
                    yspan = (max(b[1].y1 for b in cand_boxes)
                             - min(b[1].y0 for b in cand_boxes))
                    # $$37（L314-342）：expansion hack 且候选盒 yspan<=16
                    # 时 = 子标记 targetPos ∈ 候选盒者所引池（含 fallback）
                    # getMaxSize 最大值；否则 0
                    free_y_span = 0
                    if expansion_hack and yspan <= 16:
                        for cm0 in cmarks:
                            tp0 = (cm0.local_pos[0]
                                   + DIR_VECTORS[cm0.front][0],
                                   cm0.local_pos[1]
                                   + DIR_VECTORS[cm0.front][1],
                                   cm0.local_pos[2]
                                   + DIR_VECTORS[cm0.front][2])
                            if not any(b[1].contains(*tp0)
                                       for b in cand_boxes):
                                continue
                            cm_pool = self._load_pool(_strip(cm0.pool))
                            fb2 = self._load_pool(_strip(cm_pool.fallback)) \
                                if cm_pool.fallback else None
                            free_y_span = max(
                                free_y_span,
                                pool_max_yspan(cm_pool, self._load_template),
                                pool_max_yspan(fb2, self._load_template)
                                if fb2 else 0)
                    for cm in cmarks:                # L344 子标记循环
                        if not _connects(pmark, cm):  # canAttach L345
                            continue
                        # L346-347：anchor = targetPos − rot(子标记局部位)
                        child_pos = (target_pos[0] - cm.local_pos[0],
                                     target_pos[1] - cm.local_pos[1],
                                     target_pos[2] - cm.local_pos[2])
                        # $$41（L348）= 候选盒 @ anchor
                        box_at = _encapsulate(
                            [b[1].moved(child_pos[0], child_pos[1],
                                        child_pos[2])
                             for b in cand_boxes])
                        box_min_y = box_at.y0                # $$42
                        # $$43/$$44（L350-351）：候选投影 / rigid 判定
                        cand_proj = self._candidate_projection(cand)
                        rigid_child = cand_proj == "rigid"
                        # $$45（L352）= 子标记局部 Y（旋转后）
                        mark_local_y = cm.local_pos[1]
                        # $$46（L353）= $$21 − $$45 + front.stepY
                        rel_y = mark_rel_y - mark_local_y + step_y
                        # $$47（L354-363）：y 定位。
                        # rigid-rigid：$$47 = $$15+$$46 = pw.y − cm.y
                        # + stepY = target.y − cm.y = anchor.y（box_at
                        # .y0 == child_pos.y，模板局部含原点 → dy 恒 0）；
                        # 否则 $$47 = $$22 − $$45（getFirstFreeHeight
                        # @ 父标记 (x,z) − 子标记局部 y，L358-362 缓存）
                        if rigid_parent and rigid_child:
                            anchor_y = parent_min_y + rel_y
                        else:
                            key = (pw[0], pw[2])
                            if key not in terrain_y_cache:
                                terrain_y_cache[key] = \
                                    self.terrain_height(pw[0], pw[2])
                            anchor_y = terrain_y_cache[key] - mark_local_y
                        # $$49（L365）= $$47 − $$42；$$50（L366）= 盒平移
                        dy = anchor_y - box_min_y
                        child_box = box_at.moved(0, dy, 0)
                        # $$51（L367）= anchor + (0, dy, 0)
                        child_piece_pos = (child_pos[0],
                                           child_pos[1] + dy,
                                           child_pos[2])
                        # L368-371：$$37>0 时盒顶扩展到 max($$37+1, yspan)
                        if free_y_span > 0:
                            yspan_moved = child_box.y1 - child_box.y0
                            ext = max(free_y_span + 1, yspan_moved)
                            child_box = _encapsulate([
                                child_box,
                                BBox(child_box.x0, child_box.y0,
                                     child_box.z0, child_box.x1,
                                     child_box.y0 + ext,
                                     child_box.z1)])
                        # L373：joinIsNotEmpty(域, child.deflate(0.25),
                        # ONLY_SECOND) 非空 = 拒绝
                        if domain.rejects(child_box):
                            continue                   # 下一子标记
                        domain.subtract(child_box)     # L374 挖除
                        child_tpl = self._load_template(cand_tpl_key)
                        child_piece = JigsawPiece(
                            template=child_tpl, rot=rot,
                            piece_pos=child_piece_pos,
                            box=child_box, depth=depth + 1,
                            projection=cand_proj,
                            sub_templates=(cand.sub_locations
                                           if isinstance(
                                               cand, ListPoolElementSpec)
                                           else None),
                            sub_processors=(cand.sub_processors
                                            if isinstance(
                                                cand, ListPoolElementSpec)
                                            else None),
                            processor=getattr(cand, "processors", None))
                        pieces.append(child_piece)     # L401
                        self.log.append(
                            f"PLACED {cand_tpl_key} rot={rot} "
                            f"pos={child_piece.piece_pos} "
                            f"depth={depth + 1}")
                        if depth + 1 <= self.max_depth:   # L402
                            workq.append(child_piece, domain,
                                         pmark.placement_priority)  # $$31
                        break                          # L406 continue label129

    def run(self, start: JigsawPiece, outer: Domain
            ) -> List[JigsawPiece]:
        pieces: List[JigsawPiece] = [start]
        workq = PriorityWorkQueue()
        # ekv 13参：new MutableObject(freeSpace) 携带起点
        workq.append(start, outer, 0)
        while True:
            got = workq.pop_front()
            if got is None:
                return pieces
            cur, domain = got
            self.try_placing_children(cur, domain, cur.depth, workq,
                                      pieces)


# ===========================================================================
# 入口（ejk.a）
# ===========================================================================
def assemble_bastion(level_seed: int, chunk_x: int, chunk_z: int,
                     start_pool_id: str = "bastion/starts") -> AssemblyResult:
    """bastion 快捷入口（参数 = 通用入口的 bastion 默认值）。
    通用实现见 assemble_jigsaw；试炼密室入口见
    Utils/StructurePreviewer/trial_assembly.py。"""
    return assemble_jigsaw(
        level_seed, chunk_x, chunk_z,
        start_pool_id=start_pool_id,
        max_depth=BASTION_MAX_DEPTH,
        start_y=BASTION_START_Y,
        start_y_is_offset=True,      # bastion：dy = start_y-(minY+1)，基准面 y=64
        max_dist=BASTION_MAX_DIST,
        pad_bottom=BASTION_PAD_BOTTOM,
        pad_top=BASTION_PAD_TOP,
    )


def assemble_jigsaw(level_seed: int, chunk_x: int, chunk_z: int, *,
                    start_pool_id: str,
                    max_depth: int,
                    start_y: int,
                    start_y_is_offset: bool,
                    max_dist: int,
                    pad_bottom: int = 0,
                    pad_top: int = 0,
                    skip_y_bound: Optional[int] = None,
                    load_pool_fn=None,
                    load_template_fn=None,
                    expansion_hack: bool = False,
                    terrain_height_fn=None,
                    start_jigsaw_name: Optional[str] = None) -> AssemblyResult:
    """通用 jigsaw 拼装入口（fgs.a + ekv$b 1.21 语义，bastion/trial 共用）。

    显示基准面（bastion 64 / trial 90）是 composition.py 显示层概念，
    不属于拼装层，不在此传。

    与 1.21.11 反编译 fgs.a 逐行对齐（工作空间 .temp/ekv_probe/fgs_1211.txt）：
      1. rotation = Rotation.getRandom（egm.a → bhs.a：nextInt(4)）
      2. startElement = startPool.getRandom（elb.b weight 展开 + nextInt(len)）
         —— fgw.a 走 cbn.a 同式 nextInt(totalWeight)；
         cubiomes 跳过这一步仅因两起点件尺寸相同，RNG 消耗存在
      3. pos=(chunkX*16, y, chunkZ*16)；start_height 采样已在
         structure_map._jigsaw_variant 完成（trial 的 y 直接传入）
      4. 无 projection：k = pos.y → dy = k - (box.minY + groundLevelDelta)
         （start_y_is_offset=True 即 bastion 的 dy = start_y-(minY+1)，
          groundLevelDelta=1；False 即 trial 的 k==pos.y，delta=0）
      5. 外层大盒：max(起点y-maxDist, minY+pad) ≤ y <
         min(起点y+maxDist+1, maxY-pad)，xz = 中心±maxDist（含端 +1）
      6. freeSpace = 大盒挖起点；_Placer 逐 jigsaw 标记扩展
         （连接判定/域选择/候选池 shuffle 与 bastion 版完全一致）

    load_pool_fn / load_template_fn: 结构专属加载器（资产根绑定 +
    各自缓存；缺省 = bastion 的 load_pool / load_template）。
    start_pool_id / 加载器 key 里的命名空间前缀由加载器自行处理。

    skip_y_bound: start_height 采样补位。trial 的 start_height 是
    uniform(-40,-20)，在 fhp.a 里位于 rotation 之前消耗 nextInt(21)
    （与 cubiomes y=nextInt(21)-40 同序）；调用方（structure_map /
    trial_assembly）已用同一条流采出 y，本函数重建流后须先丢弃等量
    消耗再接 rotation，否则 rotation/start_pool 全部错位。
    bastion 的 start_height 是 constant 33（零消耗），传 None。

    start_jigsaw_name: 起点重定位（fgs.a L105-214 字节码定案，
    ancient_city 专用；bastion/trial/outpost 均无此字段传 None）。
    语义：start pool pick 之后，getShuffledJigsawBlocks 洗牌起点模板
    全部 jigsaw 标记（Util.shuffle，M>1 时 M-1 次主流 nextInt 消耗），
    找 name 匹配的标记（如 minecraft:city_anchor），起点件锚点改
    定到 templatePosition = pos - (anchorWorld - pos) = pos - R(local)，
    使 anchor 标记世界坐标恰好落在 pos；dy 公式的 k 同步改用
    templatePosition.y（k = piece_pos[1]）。找不到匹配标记时游戏
    日志报错并整体放弃生成（fgs.a L146-180），此处同语义抛错。
    """
    rng = make_layout_rng(level_seed, chunk_x, chunk_z)
    rng_log: List[str] = []

    # ---- 0. start_height 采样补位（fgp.a 在 rotation 之前消耗）----
    if skip_y_bound is not None:
        rng_log.append(f"start_height_skip(n={skip_y_bound})")
        rng.next_int(skip_y_bound)

    # ---- 1. 起点旋转（1 次消耗）----
    rng_log.append("rotation_get_random")
    rot = rotation_get_random(rng)

    # ---- 2. 起点池选取（1 次消耗；fgw.a / ekv.b 同式 nextInt(totalWeight)）----
    pool = (load_pool_fn or load_pool)(start_pool_id)
    expanded = expanded_pool(pool)
    rng_log.append(f"start_pool_pick(n={len(expanded)})")
    start_pick = rng.next_int(len(expanded))
    elem = expanded[start_pick]
    start_tpl = (load_template_fn or load_template)(elem.location)

    # ---- 2b. start_jigsaw_name 重定位（fgs.a L105-214）----
    # findStartJigsawBlock：起点模板 jigsaw 标记洗牌（M-1 次主流消耗）
    # + name 匹配；templatePosition = pos - R(local)，使 anchor 世界
    # 坐标 = pos。dy 公式的 k 随之改用 templatePosition.y。
    if start_jigsaw_name is not None:
        anchor_name = _strip(start_jigsaw_name)
        markers = start_tpl.markers_at(rot)
        if len(markers) > 1:
            rng_log.append(f"start_anchor_shuffle(M={len(markers)})")
            markers = shuffle_list(rng, markers)
        anchor = None
        for m in markers:
            if _strip(m.name) == anchor_name:
                anchor = m
                break
        if anchor is None:
            # fgs.a L146-180：游戏日志 + Optional.empty = 结构不存在
            raise ValueError(
                f"No starting jigsaw {anchor_name} in start pool "
                f"{start_pool_id}（起点件 {start_tpl.key}）")
        ax, ay, az = anchor.local_pos      # markers_at 已旋转
        piece_pos = (chunk_x * 16 - ax, start_y - ay,
                     chunk_z * 16 - az)
        rng_log.append("start_anchor_relocate")
    else:
        piece_pos = (chunk_x * 16, start_y, chunk_z * 16)

    # ---- 3/4. 起始件位置与 dy（fgs.a L288-356：无投影 k=piece_pos.y）----
    box = start_tpl.get_bounding_box(piece_pos, rot)
    if start_y_is_offset:
        dy = piece_pos[1] - (box.y0 + 1)          # bastion：dy = k-(minY+1)，
        #                                          groundLevelDelta=1
        #（fgw.h() 基类恒 1：javap iconst_1 实证；重定位后 k=
        #  piece_pos.y，无重定位时 piece_pos.y == start_y 同值）
    else:
        dy = piece_pos[1] - box.y0                # trial：dy = k-minY；
        #                                          起点件本地 minY=0 → dy=0，
        #                                          ≠0 时按字节码真式修正
    box = box.moved(0, dy, 0)
    piece_pos = (piece_pos[0], piece_pos[1] + dy, piece_pos[2])
    # placement depth=0（ekv 13 参显式 iconst_0）；ejn 内部另有记账 depth
    # = ekz.g()==1（仅 eju/eku 高度记账用，渲染不需要）；
    # projection = 起点池元素声明（$$8.getProjection，bastion 全 rigid）
    start = JigsawPiece(template=start_tpl, rot=rot, piece_pos=piece_pos,
                        box=box, depth=0,
                        projection=getattr(elem, "projection", "rigid"),
                        sub_templates=(elem.sub_locations
                                       if isinstance(elem,
                                                     ListPoolElementSpec)
                                       else None),
                        processor=getattr(elem, "processors", None))

    # ---- 5. 外层大盒 + freeSpace（fgs.a L446-533 的 AABB 语义）----
    cx = (box.x0 + box.x1) // 2
    cz = (box.z0 + box.z1) // 2
    outer = BBox(
        cx - max_dist,
        max(start_y - max_dist,
            BEARDIZER_MIN_Y + pad_bottom),
        cz - max_dist,
        cx + max_dist + 1,
        min(start_y + max_dist + 1,
            BEARDIZER_MAX_Y - pad_top),
        cz + max_dist + 1,
    )
    placer = _Placer(rng, rng_log, max_depth=max_depth,
                     load_pool_fn=load_pool_fn,
                     load_template_fn=load_template_fn,
                     expansion_hack=expansion_hack,
                     terrain_height_fn=terrain_height_fn)
    free_space = Domain(outer)          # 初始 freeSpace = 大盒
    free_space.subtract(box)            # exs.a(大盒, 起点盒, ONLY_FIRST) 挖掉起点
    pieces = placer.run(start, free_space)
    # start_index = start pool 真实选取索引（重量展开列表，JSON 序）。
    # trial 起点池 chamber/end 两元素 end_1/end_2 等权，抽中 1 = end_2；
    # 此前写死 0 会导致抽中 end_2 的种子拼出 end_1 几何（seed=42 对拍
    # 实证）。bastion 调用方不读该字段，零行为影响。
    return AssemblyResult(pieces=pieces, start_index=start_pick,
                          rng_calls=rng_log)


# ===========================================================================
# 降解处理器（enm RuleProcessor + eni 规则，bastion_generic_degradation）
# ===========================================================================
# enm.a(dcz,jd,jd,ent$c,ent$c,enp)：
#   rng = ayw.a(ayo.a(相对块位))          ← RandomSource.create(Mth.getSeed(pos))
#     （ayo.a(Lkh;)J = Mth.getSeed(Vec3i) 重载；mc_rng.mth_get_seed 已定案）
#   worldState = dcz.a_(方块位)             ← location_predicate（bastion 全 always_true）
#   for rule in rules（按 JSON 顺序）:
#       if rule.a(模板态, 世界态, 位, 位, 邻位, rng):
#           return ent$c(位, rule.a()(rng, nbt), rule.a(rng, nbt))
#   return 原状态
# eni.a 六参（Rule.test）：input_predicate.test(rng) &&
#   location_predicate.test(...)；enp（nbt）无短路关系，bastion 无 nbt
# eni.a 二参（Rule.getFinalState）：output = 随机 output_state 列表项
#   （bastion 全单值）；无 output_nbt → 原样返回
#
# ayo.a(Lkh;)J = Mth.getSeed(Vec3i)：mc_rng.mth_get_seed 已对拍定案
# ayw.a(long) = RandomSource.create(seed)：
#   setSeed(seed)；LegacyRandomSource 与布局 RNG 同构（mc_rng.LegacyRandomSource）
# ===========================================================================
_BASTION_RULES = (
    # (block, probability, output)
    ("minecraft:polished_blackstone_bricks", 0.3,
     "minecraft:cracked_polished_blackstone_bricks"),
    ("minecraft:blackstone", 1.0e-4, "minecraft:air"),
    ("minecraft:gold_block", 0.3,
     "minecraft:cracked_polished_blackstone_bricks"),
    ("minecraft:gilded_blackstone", 0.5, "minecraft:blackstone"),
    ("minecraft:blackstone", 0.01, "minecraft:gilded_blackstone"),
)


# 可被降解规则命中的输入方块集合（rules 的 block 字段）：快速路径
# 用——bastion 体素绝大多数是黑石系但也大量不在规则内（箱子/栏杆/
# 镶金黑石字符串常驻等），不在集合内直接返回原样，免建 RNG。
# （state.is(block) 短路语义：不命中集合 = 循环不命中 = 原样返回）
_DEGRADABLE_BLOCKS = frozenset(r[0] for r in _BASTION_RULES)

# LCG 常量（与 mc_rng.MULT/ADD/MASK_48 同源；内联免逐方块对象创建）
_LCG_MULT = 25214903917
_LCG_ADD = 11
_LCG_MASK48 = (1 << 48) - 1
_INV_2POW24 = 1.0 / float(1 << 24)
# 降解规则按 block 预分组（保序、允许同 block 多条规则——blackstone
# 有 air 1e-4 与 gilded 0.01 两条，评估共用同一条随机流直到首次命中）；
# dict 误用单值覆盖会改变 RNG 消耗次数（对拍实证），必须用列表。
_DEGRADABLE_ITEMS: dict = {}
for _r in _BASTION_RULES:
    _DEGRADABLE_ITEMS.setdefault(_r[0], []).append((_r[1], _r[2]))
_DEGRADABLE_ITEMS = {k: tuple(v) for k, v in _DEGRADABLE_ITEMS.items()}


def apply_degradation(state_name: str, x: int, y: int, z: int) -> str:
    """bastion_generic_degradation 单方块降解（eni/enm 字节码语义）。

    每方块独立 LegacyRandomSource(Mth.getSeed(x,y,z))；规则按序共用
    该源，state.is(block) 短路：不匹配的规则不消耗随机数。

    性能：不可降解方块（frozenset 快速路径）直接返回；可降解方块
    内联 48 位 LCG（state = state*25214903917+11 mod 2^48，
    next(24)*2^-24 = LegacyRandomSource.next_float 同式，数学恒等
    无语义分支差异），免 4.4 万次对象创建；bastion 规则每方块至
    多命中一条（state 只等于一个 block），单步 LCG 即完成判定。
    """
    items = _DEGRADABLE_ITEMS.get(state_name)
    if items is None:
        return state_name
    # Mth.getSeed(x, y, z)（mc_rng.mth_get_seed 逐符号内联）：
    # t = _u(java_int(java_int(x)*3129871))：imul 32 位回绕后符号扩展 64 位
    # z/y 项 = _u(java_int(z/y))：先有符号 32 位回绕，再 64 位符号扩展
    #   （负数高 32 位全 1，与 32 位无符号解释不同——对拍实证）；
    #   z 项乘 116129781 在 64 位图案上进行，最终 & MASK_64 截断
    xi = x & 0xFFFFFFFF
    xi = xi - 0x100000000 if xi >= 0x80000000 else xi       # java_int(x)
    t = (xi * 3129871) & 0xFFFFFFFF
    t = t - 0x100000000 if t >= 0x80000000 else t           # java_int(imul)
    t = t & 0xFFFFFFFFFFFFFFFF                              # _u 符号扩展
    zi = z & 0xFFFFFFFF
    zi = zi - 0x100000000 if zi >= 0x80000000 else zi       # java_int(z)
    zt = (zi & 0xFFFFFFFFFFFFFFFF) * 116129781              # _u 后乘常数
    yi = y & 0xFFFFFFFF
    yi = yi - 0x100000000 if yi >= 0x80000000 else yi       # java_int(y)
    yu = yi & 0xFFFFFFFFFFFFFFFF                            # _u 符号扩展
    l = (t ^ zt ^ yu) & 0xFFFFFFFFFFFFFFFF
    l = (l * l * 42317861 + l * 11) & 0xFFFFFFFFFFFFFFFF
    l = l - (1 << 64) if l >= (1 << 63) else l              # java_long
    seed = l >> 16                                          # 算术右移
    # LegacyRandomSource(seed)（同式内联，规则循环共用该流直到命中）：
    # next_float() = next(24) * 2^-24 = ((state*MULT+ADD) >> 24) * 2^-24
    state = ((seed & 0xFFFFFFFFFFFFFFFF) ^ _LCG_MULT) & _LCG_MASK48
    for prob, out in items:
        state = (state * _LCG_MULT + _LCG_ADD) & _LCG_MASK48
        if (state >> 24) * _INV_2POW24 < prob:
            return out
    return state_name
