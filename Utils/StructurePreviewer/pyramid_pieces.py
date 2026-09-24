# -*- coding: utf-8 -*-
"""StructurePreviewer：沙漠神殿 / 丛林神庙 逐方块布局（pyramid pieces）。

把 DesertPyramidPiece / JungleTemplePiece 的 postProcess（1.21.11 jar
反编译逐行转写，类 fhj / fhq；基类 ffs=StructurePiece、
ffm=ScatteredFeaturePiece）展开为模型体素 dict {(x,y,z): 值}。
两结构均为 SinglePieceStructure（26.2 未混淆源码核对）：piece 锚点 =
chunkPos.getMinBlockX/Z（区块最小角，compose 内 &~15 同 igloo 口径）。

RNG 双流语义（与项目 igloo/outpost 定案口径一致）：
- 变体流（Legacy LCG）：chunkGenerateRnd(seed, cx, cz) ->
  Plane.HORIZONTAL.getRandomDirection = nextInt(4)（faces 数组序
  {N,E,S,W}，26.2 Direction$Plane 定案），决定 piece orientation；
- postProcess 流（Xoroshiro128++）：population_seed(anchor 区块) +
  decorator + 10000*step（_SALT_1194：desert_pyramid={4,1}、
  jungle_pyramid={4,4}）。箱子由 createChest/createDispenser 放置
  （各消耗 1 个 nextLong 作 LootTableSeed，ffs 定案），走 outpost
  同款「区块 population 流直接连抽」口径（createChest 路径无 skip，
  区别于 igloo 模板 placeInWorld 路径的 skips=1）。desert/jungle 的
  箱子有 hasPlacedChest/placed* 布尔持久化保护，只在首次 postProcess
  放置；箱子前置消耗非 nextLong（desert 是 nextInt(3)、jungle 是
  逐格 nextFloat），无法用 loot_seed_for_chest 的 skips 模型表达，
  故用本模块 _Sim 模拟流同步推进，边模拟边取 seed：
  - desert：updateAverageGroundHeight 的 -nextInt(3)（调用前求值，
    恒消耗 1 个 nextInt(3)，内部拒绝采样推进 1~2 次 raw）→ 4 箱
    各 1 nextLong（Plane.HORIZONTAL 循环序 N→E→S→W，位置
    (10+stepX*2, -11, 10+stepZ*2)）；
  - jungle：MossStoneSelector 逐格 nextFloat（fillWithRandomizedBlocks
    的 alwaysReplace=false 下每格恒消耗，循环 y→x→z，按 postProcess
    语句顺序累计）→ 发射器(3,-2,1)N → 发射器(9,-2,3)W → 主箱(8,-3,3)
    → 暗箱(9,-3,10)，各 1 nextLong。

坐标与朝向（ScatteredFeaturePiece 语义，ffs a/b(x,z) switch 定案，
1.21.11 字节码与 26.2 未混淆源码双重核对）：
- facing 0..3 = {N,E,S,W}；bb：N/S -> (x..x+w-1, z..z+d-1)，
  E/W -> (x..x+d-1, z..z+w-1)（makeBoundingBox axis==Z 分支；
  jungle 12x15 交换、desert 21x21 对称）；
- getWorldPos：0 N: x=minX+x z=maxZ-z；1 E: x=minX+z z=minZ+x；
  2 S: x=minX+x z=minZ+z；3 W: x=maxX-z z=minZ+x（fortress 同表）；
- 方向性方块（楼梯 FACING）净变换 = placeBlock 内先 mirror 后
  rotate（1.21.11 setOrientation 字节码：N=(NONE,NONE)、
  E=(NONE,CW90)、S=(LEFT_RIGHT,NONE)、W=(LEFT_RIGHT,CW90)；
  StairBlock.mirror：LEFT_RIGHT 仅对 axis==Z 的楼梯 rotate 180），
  净效果见 _STAIRS_MAP。注意与 fortress _WX_STAIRS 的 S/W 两行
  不一致（fortress 表疑把 LEFT_RIGHT/FRONT_BACK 镜像互换，见汇报）。

体素值约定（structure_models.build_mesh）：整格 = 材质键 str；
方向性 = (材质键, 形状码)；AIR = 显式挖空（pop 键）。模型 (0,0,0) =
世界 (anchor_x, 64, anchor_z)，y = 局部 y + 64（平坦预览：假设
updateAverageGroundHeight 修正后 bb.minY 恰为 64；真实游戏 y 随
地表整体平移，内部布局不变）。

已知妥协：
- 无地形：desert 底座 fillColumnDown（y=-5 向下找地面）只画 y=-5
  单层；
- desert 挖掘室的沙/砂岩 2 格分布依赖 level.getRandom().nextBoolean()
  （世界装饰流，不可从种子预测），固定取 nextBoolean=true 分支
  （(15,-1,17)=sand、(16,-1,17)=sandstone）；
- afterPlace 可疑的沙子（DesertPyramidStructure.afterPlace）用
  forkPositional 独立流选取挖掘点（不消耗 postProcess 流、不影响
  箱子 seed），预览统一画普通 sand（suspicious sand 纹理同 sand）；
- 箱子朝向固定局部 north（真实游戏经 reorient 按邻居重定向，预览
  无全局世界上下文）；
- jungle 台阶/楼梯的方向性已按 _STAIRS_MAP 映射，desert 秘密室
  下行楼梯为 SANDSTONE_STAIRS.rotate(CCW90) 的局部 w 再查表。

机关方块（1.21.11 反编译 fhq L135-205 + jar 模型 JSON 定案，
全部官方几何码，无近似形状）：
- 方向属性净变换：所有方向性方块（发射器/活塞/中继器/绊线钩/
  拉杆/藤蔓/绊线/红石线）的局部朝向/连接属性经 piece
  setOrientation 的 mirror+rotate（与楼梯 _STAIRS_MAP 同表，
  _Sim.facing_of）；u/d 朝向不随 mirror/rotate；
- 绊线钩 thook:<贴边>:a（tripwire_hook_attached.json 多盒几何，
  hook/tripwire/oak planks 分区材质）；绊线 twire（0.5px 细线
  面片）；红石线 rswire（官方 multipart 几何）；拉杆
  lever:<face>:<facing>:<pw>（圆石底座 + 45° 旋转斜杆）；粘性活塞
  pist:<f>:s；中继器 repeater:<f>；藤蔓 vine:<dir>（贴边薄面
  片）；发射器 fc:<f>（dispenser front 分面）。
"""
from __future__ import annotations

from Utils.SeedReverser import block_shapes as bs
from . import loot_rng

# --------------------------------------------------------------- 材质键
SANDSTONE = "sandstone"
CUT_SANDSTONE = "cut sandstone"
CHISELED_SANDSTONE = "chiseled sandstone"
SANDSTONE_STAIRS = "sandstone stairs"
SANDSTONE_SLAB = "sandstone slab"
SAND = "sand"
ORANGE_TERRACOTTA = "orange terracotta"
BLUE_TERRACOTTA = "blue terracotta"
TNT = "tnt"
STONE_PLATE = ("stone", bs.SHAPE_PLATE)          # 石质压力板
COBBLESTONE = "cobblestone"
MOSSY_COBBLESTONE = "mossy cobblestone"
COBBLESTONE_STAIRS = "cobblestone stairs"
CHEST = ("chest", bs.SHAPE_CHEST_N)
DISPENSER = "dispenser"           # fc:<f> 形状元组逐方块生成
TRIPWIRE_HOOK = "tripwire hook"   # thook:<贴边>:a
VINE = "vine"                     # vine:<dir>
LEVER = "lever"                   # lever:<face>:<facing>:<pw>
STICKY_PISTON = "sticky piston"   # pist:<f>:s
REPEATER = "repeater"             # repeater:<f>
TRIPWIRE = "tripwire"             # twire:<n>:<s>:<e>:<w>
REDSTONE_WIRE = "redstone wire"   # rswire:<n>:<s>:<e>:<w>（合成图：
# 官方 1.21.11 line0/line1 灰度纹理按 egb COLORS[power=0] 染色，
# N/S 臂 line0 原样 + E/W 臂 line1 官方 y270 旋转转置）
CHISELED_STONE_BRICKS = "chiseled stone bricks"

# 挂件贴边 = 局部 FACING 反侧（thook 码 rest 语义，与
# block_shapes.wall_panel_edge 同表；lever 新码直接用伸出方向）
_EDGE = {"n": "s", "s": "n", "e": "w", "w": "e"}

# rswire/twire 段序 n:s:e:w -> 下标
_SEG_IDX = {"n": 0, "s": 1, "e": 2, "w": 3}

# 方向 0..3 = {N,E,S,W} 的 step（Direction.getStepX/getStepZ，C 口径；
# fhj L217-218 的 $$18.j()/$$18.l() = getStepX/getStepZ，mapping 定案）
_DIR_STEPS = ((0, -1), (1, 0), (0, 1), (-1, 0))

# 楼梯局部 FACING -> 世界 FACING（_STAIRS_MAP[facing][local]）。
# 定案链：1.21.11 setOrientation 字节码（N=(eev.a NONE,egm.a NONE)、
# E=(NONE,egm.b CW90)、S=(eev.b LEFT_RIGHT,NONE)、
# W=(LEFT_RIGHT,CW90)）+ 26.2 StairBlock.mirror 源码（LEFT_RIGHT 仅
# 对 axis==Z 楼梯 rotate 180；FRONT_BACK 仅对 axis==X）+
# Rotation.rotate（CW90 = getClockWise 链）。
_STAIRS_MAP = (
    {"n": "n", "s": "s", "e": "e", "w": "w"},           # 0 NORTH 恒等
    {"n": "e", "s": "w", "e": "s", "w": "n"},           # 1 EAST 纯 CW90
    {"n": "s", "s": "n", "e": "e", "w": "w"},           # 2 SOUTH（LEFT_RIGHT）
    {"n": "w", "s": "e", "e": "s", "w": "n"},           # 3 WEST（LEFT_RIGHT+CW90）
)


def _world_xy(x: int, z: int, facing: int, max_x: int, max_z: int):
    """ScatteredFeaturePiece getWorldX/Z（局部 -> piece 相对坐标）。

    max_x/max_z 为 piece bb 含端点最大角（相对 anchor）：
    N/S -> (w-1, d-1)；E/W -> (d-1, w-1)。
    """
    if facing == 0:                       # NORTH
        return x, max_z - z
    if facing == 1:                       # EAST
        return z, x
    if facing == 2:                       # SOUTH
        return x, z
    return max_x - z, x                   # WEST


def _thook(sim: "_Sim", local: str) -> tuple:
    """绊线钩体素值：局部 FACING -> 世界贴边（净变换）+ attached。"""
    return (TRIPWIRE_HOOK,
            "thook:" + _EDGE[sim.facing_of(local)] + ":a")


def _segs(sim: "_Sim", mat: str, kind: str, n: bool = False,
          so: bool = False, e: bool = False, w: bool = False) -> tuple:
    """四向连接段方块（rswire/twire）体素值：局部连接向 ->
    mirror+rotate 净变换 -> 世界段码（段序 n:s:e:w）。"""
    m = _STAIRS_MAP[sim.facing]
    segs = ["-", "-", "-", "-"]
    for on, d in ((n, "n"), (so, "s"), (e, "e"), (w, "w")):
        if on:
            segs[_SEG_IDX[m[d]]] = "1"
    return (mat, kind + ":" + ":".join(segs))


class _Sim:
    """单结构的 postProcess 模拟器（体素 + RNG 流同步推进）。"""

    def __init__(self, salt_key: str, world_seed: int,
                 ax: int, az: int, facing: int,
                 width: int, depth: int) -> None:
        self.voxels: dict = {}
        self.chests: list = []            # (世界 wx, 世界 wz, y_local, table, seed)
        self.ax = ax
        self.az = az
        self.facing = facing
        self.width = width
        self.depth = depth
        # bb 含端点最大角（相对 anchor；makeBoundingBox axis 语义）
        if facing in (0, 2):              # N/S：x 沿 w、z 沿 d
            self.max_x, self.max_z = width - 1, depth - 1
        else:                             # E/W：交换
            self.max_x, self.max_z = depth - 1, width - 1
        step, decorator = loot_rng.salt_configs_for_version("1.21")[salt_key]
        pop = loot_rng.get_population_seed(world_seed, ax, az)
        self.rng = loot_rng.XoroshiroJava(
            (pop + decorator + 10000 * step) & loot_rng._M64)

    # -- 坐标 ----------------------------------------------------------

    def _w(self, x: int, y: int, z: int):
        wx, wz = _world_xy(x, z, self.facing, self.max_x, self.max_z)
        return wx, y + 64, wz

    def facing_of(self, local: str) -> str:
        """局部水平朝向 -> 世界朝向（setOrientation mirror+rotate
        净变换 = _STAIRS_MAP 同表；方向性方块属性通用）。"""
        return _STAIRS_MAP[self.facing][local]

    # -- RNG 消耗原语 ---------------------------------------------------

    def next_long(self) -> int:
        return self.rng.next_long()

    def next_int(self, n: int) -> int:
        return self.rng.next_int(n)

    # -- 摆放原语 -------------------------------------------------------

    def place(self, x: int, y: int, z: int, val) -> None:
        """placeBlock（chunkBB 裁剪平坦预览恒真；val=None 为 AIR）。"""
        wx, wy, wz = self._w(x, y, z)
        if val is None:
            self.voxels.pop((wx, wy, wz), None)
        else:
            self.voxels[(wx, wy, wz)] = val

    def stairs(self, x: int, y: int, z: int, local: str, mat) -> None:
        self.place(x, y, z, (mat, bs.SHAPE_STAIRS[_STAIRS_MAP[self.facing][local]]))

    def fill_hollow(self, x1, y1, z1, x2, y2, z2, edge, inner) -> None:
        """generateBox edge/inner（skipAir=false，无 RNG）。"""
        for y in range(y1, y2 + 1):
            for x in range(x1, x2 + 1):
                for z in range(z1, z2 + 1):
                    if (y == y1 or y == y2 or x == x1 or x == x2
                            or z == z1 or z == z2):
                        self.place(x, y, z, edge)
                    else:
                        self.place(x, y, z, inner)

    def fill_air(self, x1, y1, z1, x2, y2, z2) -> None:
        """generateAirBox：显式挖空（无 RNG）。"""
        for y in range(y1, y2 + 1):
            for x in range(x1, x2 + 1):
                for z in range(z1, z2 + 1):
                    self.place(x, y, z, None)

    def fill_mossy(self, x1, y1, z1, x2, y2, z2) -> None:
        """generateBox + MossStoneSelector（fhq 内部类 a）：
        alwaysReplace=false 下每格恒消耗一次 nextFloat（顺序 y→x→z，
        ffs.generateBox(selector) 定案），<0.4 -> cobblestone、
        否则 mossy cobblestone。"""
        for y in range(y1, y2 + 1):
            for x in range(x1, x2 + 1):
                for z in range(z1, z2 + 1):
                    f = self.rng.next_float()
                    self.place(x, y, z,
                               COBBLESTONE if f < 0.4 else MOSSY_COBBLESTONE)

    def fill_down(self, x: int, z: int, val) -> None:
        """fillColumnDown（y=-5 向下找地面）：平坦预览只画 y=-5 单层。"""
        self.place(x, -5, z, val)

    def create_chest(self, x: int, y: int, z: int, table: str) -> None:
        """createChest（无朝向重载）：1 个 nextLong（LootTableSeed）
        + chest 体素（局部 north 占位，真实游戏经 reorient）。"""
        seed = self.rng.next_long()
        wx, wy, wz = self._w(x, y, z)
        self.voxels[(wx, wy, wz)] = CHEST
        self.chests.append((wx + self.ax, wz + self.az, y, table, seed))

    def create_dispenser(self, x: int, y: int, z: int, table: str,
                         local_facing: str) -> None:
        """createDispenser：1 个 nextLong + dispenser 体素（FACING
        经 piece mirror/rotate 净变换，fc 码官方 dispenser front
        分面纹理）。"""
        seed = self.rng.next_long()
        wx, wy, wz = self._w(x, y, z)
        self.voxels[(wx, wy, wz)] = (
            DISPENSER, "fc:" + self.facing_of(local_facing))
        self.chests.append((wx + self.ax, wz + self.az, y, table, seed))


# ---------------------------------------------------------------------------
# desert_pyramid（fhj.postProcess 逐行转写；a=c=21，行号 = 1.21.11 原始版）
# ---------------------------------------------------------------------------

def _sim_desert(world_seed: int, ax: int, az: int, facing: int) -> _Sim:
    """沙漠神殿 postProcess 模拟（fhj L34-231）。"""
    s = _Sim("desert_pyramid", world_seed, ax, az, facing, 21, 21)
    a = c = 21
    SS, CUT, CHIS, AIR = SANDSTONE, CUT_SANDSTONE, CHISELED_SANDSTONE, None

    # L35：updateAverageGroundHeight(level, bb, -nextInt(3))——参数
    # 先求值，恒消耗 1 个 nextInt(3)（HPos 计算本身无 RNG；平坦
    # 预览假设修正后 minY=64）。
    s.next_int(3)

    # L36：底座层
    s.fill_hollow(0, -4, 0, a - 1, 0, c - 1, SS, SS)
    # L38-41：9 层金字塔逐层缩进
    for l in range(1, 10):
        s.fill_hollow(l, l, l, a - 1 - l, l, c - 1 - l, SS, SS)
        s.fill_hollow(l + 1, l, l + 1, a - 2 - l, l, c - 2 - l, AIR, AIR)
    # L43-48：y=-5 基座（fillColumnDown 向下找地面，预览画单层）
    for x in range(0, a):
        for z in range(0, c):
            s.fill_down(x, z, SS)
    # L50-53：楼梯局部朝向（iz.c/d/f/e = N/S/E/W）
    s_n, s_s, s_e, s_w = "n", "s", "e", "w"
    # L54-59：西北角塔楼
    s.fill_hollow(0, 0, 0, 4, 9, 4, SS, AIR)
    s.fill_hollow(1, 10, 1, 3, 10, 3, SS, SS)
    s.stairs(2, 10, 0, s_n, SANDSTONE_STAIRS)
    s.stairs(2, 10, 4, s_s, SANDSTONE_STAIRS)
    s.stairs(0, 10, 2, s_e, SANDSTONE_STAIRS)
    s.stairs(4, 10, 2, s_w, SANDSTONE_STAIRS)
    # L60-65：东南角塔楼
    s.fill_hollow(a - 5, 0, 0, a - 1, 9, 4, SS, AIR)
    s.fill_hollow(a - 4, 10, 1, a - 2, 10, 3, SS, SS)
    s.stairs(a - 3, 10, 0, s_n, SANDSTONE_STAIRS)
    s.stairs(a - 3, 10, 4, s_s, SANDSTONE_STAIRS)
    s.stairs(a - 5, 10, 2, s_e, SANDSTONE_STAIRS)
    s.stairs(a - 1, 10, 2, s_w, SANDSTONE_STAIRS)
    # L66-74：北面中室 + 刻纹砂岩装饰柱
    s.fill_hollow(8, 0, 0, 12, 4, 4, SS, AIR)
    s.fill_hollow(9, 1, 0, 11, 3, 4, AIR, AIR)
    for (dx, dy, dz) in ((9, 1, 1), (9, 2, 1), (9, 3, 1), (10, 3, 1),
                         (11, 3, 1), (11, 2, 1), (11, 1, 1)):
        s.place(dx, dy, dz, CUT)
    # L75-78：东西走廊
    s.fill_hollow(4, 1, 1, 8, 3, 3, SS, AIR)
    s.fill_hollow(4, 1, 2, 8, 2, 2, AIR, AIR)
    s.fill_hollow(12, 1, 1, 16, 3, 3, SS, AIR)
    s.fill_hollow(12, 1, 2, 16, 2, 2, AIR, AIR)
    # L79-84：大厅地板 + 中央竖井口 + 四根刻纹砂岩柱
    s.fill_hollow(5, 4, 5, a - 6, 4, c - 6, SS, SS)
    s.fill_hollow(9, 4, 9, 11, 4, 11, AIR, AIR)
    s.fill_hollow(8, 1, 8, 8, 3, 8, CUT, CUT)
    s.fill_hollow(12, 1, 8, 12, 3, 8, CUT, CUT)
    s.fill_hollow(8, 1, 12, 8, 3, 12, CUT, CUT)
    s.fill_hollow(12, 1, 12, 12, 3, 12, CUT, CUT)
    # L85-90：两翼实心墙 + 上层走廊
    s.fill_hollow(1, 1, 5, 4, 4, 11, SS, SS)
    s.fill_hollow(a - 5, 1, 5, a - 2, 4, 11, SS, SS)
    s.fill_hollow(6, 7, 9, 6, 7, 11, SS, SS)
    s.fill_hollow(a - 7, 7, 9, a - 7, 7, 11, SS, SS)
    s.fill_hollow(5, 5, 9, 5, 7, 11, CUT, CUT)
    s.fill_hollow(a - 6, 5, 9, a - 6, 7, 11, CUT, CUT)
    # L91-96：走廊口挖空
    for (dx, dy) in ((5, 5), (5, 6), (6, 6),
                     (a - 6, 5), (a - 6, 6), (a - 7, 6)):
        s.place(dx, dy, 10, AIR)
    # L97-102：两翼下行竖井口 + 楼梯
    s.fill_hollow(2, 4, 4, 2, 6, 4, AIR, AIR)
    s.fill_hollow(a - 3, 4, 4, a - 3, 6, 4, AIR, AIR)
    s.stairs(2, 4, 5, s_n, SANDSTONE_STAIRS)
    s.stairs(2, 3, 4, s_n, SANDSTONE_STAIRS)
    s.stairs(a - 3, 4, 5, s_n, SANDSTONE_STAIRS)
    s.stairs(a - 3, 3, 4, s_n, SANDSTONE_STAIRS)
    # L103-110：入口室 + 台阶
    s.fill_hollow(1, 1, 3, 2, 2, 3, SS, SS)
    s.fill_hollow(a - 3, 1, 3, a - 2, 2, 3, SS, SS)
    s.place(1, 1, 2, SS)
    s.place(a - 2, 1, 2, SS)
    s.place(1, 2, 2, SANDSTONE_SLAB)
    s.place(a - 2, 2, 2, SANDSTONE_SLAB)
    s.stairs(2, 1, 2, s_w, SANDSTONE_STAIRS)
    s.stairs(a - 3, 1, 2, s_e, SANDSTONE_STAIRS)
    # L111-114：两翼下层通道
    s.fill_hollow(4, 3, 5, 4, 3, 17, SS, SS)
    s.fill_hollow(a - 5, 3, 5, a - 5, 3, 17, SS, SS)
    s.fill_hollow(3, 1, 5, 4, 2, 16, AIR, AIR)
    s.fill_hollow(a - 6, 1, 5, a - 5, 2, 16, AIR, AIR)
    # L116-121：通道装饰柱
    for z in range(5, 18, 2):
        s.place(4, 1, z, CUT)
        s.place(4, 2, z, CHIS)
        s.place(a - 5, 1, z, CUT)
        s.place(a - 5, 2, z, CHIS)
    # L123-135：大厅中央陶瓦菱形（y=0 层）
    for (dx, dz) in ((10, 7), (10, 8), (9, 9), (11, 9), (8, 10), (12, 10),
                     (7, 10), (13, 10), (9, 11), (11, 11), (10, 12), (10, 13)):
        s.place(dx, 0, dz, ORANGE_TERRACOTTA)
    s.place(10, 0, 10, BLUE_TERRACOTTA)
    # L137-159：前后墙面装饰（x=0 / x=a-1 两面）
    for xf in (0, a - 1):
        s.place(xf, 2, 1, CUT)
        s.place(xf, 2, 2, ORANGE_TERRACOTTA)
        s.place(xf, 2, 3, CUT)
        s.place(xf, 3, 1, CUT)
        s.place(xf, 3, 2, ORANGE_TERRACOTTA)
        s.place(xf, 3, 3, CUT)
        s.place(xf, 4, 1, ORANGE_TERRACOTTA)
        s.place(xf, 4, 2, CHIS)
        s.place(xf, 4, 3, ORANGE_TERRACOTTA)
        s.place(xf, 5, 1, CUT)
        s.place(xf, 5, 2, ORANGE_TERRACOTTA)
        s.place(xf, 5, 3, CUT)
        s.place(xf, 6, 1, ORANGE_TERRACOTTA)
        s.place(xf, 6, 2, CHIS)
        s.place(xf, 6, 3, ORANGE_TERRACOTTA)
        s.place(xf, 7, 1, ORANGE_TERRACOTTA)
        s.place(xf, 7, 2, ORANGE_TERRACOTTA)
        s.place(xf, 7, 3, ORANGE_TERRACOTTA)
        s.place(xf, 8, 1, CUT)
        s.place(xf, 8, 2, CUT)
        s.place(xf, 8, 3, CUT)
    # L161-183：南北门洞装饰（z=0 / z=c-1 两面，x17 ∈ {2, a-3}）
    for xg in (2, a - 3):
        s.place(xg - 1, 2, 0, CUT)
        s.place(xg, 2, 0, ORANGE_TERRACOTTA)
        s.place(xg + 1, 2, 0, CUT)
        s.place(xg - 1, 3, 0, CUT)
        s.place(xg, 3, 0, ORANGE_TERRACOTTA)
        s.place(xg + 1, 3, 0, CUT)
        s.place(xg - 1, 4, 0, ORANGE_TERRACOTTA)
        s.place(xg, 4, 0, CHIS)
        s.place(xg + 1, 4, 0, ORANGE_TERRACOTTA)
        s.place(xg - 1, 5, 0, CUT)
        s.place(xg, 5, 0, ORANGE_TERRACOTTA)
        s.place(xg + 1, 5, 0, CUT)
        s.place(xg - 1, 6, 0, ORANGE_TERRACOTTA)
        s.place(xg, 6, 0, CHIS)
        s.place(xg + 1, 6, 0, ORANGE_TERRACOTTA)
        s.place(xg - 1, 7, 0, ORANGE_TERRACOTTA)
        s.place(xg, 7, 0, ORANGE_TERRACOTTA)
        s.place(xg + 1, 7, 0, ORANGE_TERRACOTTA)
        s.place(xg - 1, 8, 0, CUT)
        s.place(xg, 8, 0, CUT)
        s.place(xg + 1, 8, 0, CUT)
    # L185-190：北门洞 + 陶瓦
    s.fill_hollow(8, 4, 0, 12, 6, 0, CUT, CUT)
    s.place(8, 6, 0, AIR)
    s.place(12, 6, 0, AIR)
    s.place(9, 5, 0, ORANGE_TERRACOTTA)
    s.place(10, 5, 0, CHIS)
    s.place(11, 5, 0, ORANGE_TERRACOTTA)
    # L191-197：TNT 陷阱竖井
    s.fill_hollow(8, -14, 8, 12, -11, 12, CUT, CUT)
    s.fill_hollow(8, -10, 8, 12, -10, 12, CHIS, CHIS)
    s.fill_hollow(8, -9, 8, 12, -9, 12, CUT, CUT)
    s.fill_hollow(8, -8, 8, 12, -1, 12, SS, SS)
    s.fill_hollow(9, -11, 9, 11, -1, 11, AIR, AIR)
    s.place(10, -11, 10, STONE_PLATE)
    s.fill_hollow(9, -13, 9, 11, -13, 11, TNT, AIR)   # 3x3 全 edge = TNT
    # L198-213：四方向臂端通道口（与四箱位置一一对应）：
    #   W: air (8,-11,10)(8,-10,10)；E: air (12,-11,10)(12,-10,10)
    #   N: air (10,-11,8)(10,-10,8)；S: air (10,-11,12)(10,-10,12)
    for dxx, dzz in ((-2, 0), (2, 0), (0, -2), (0, 2)):
        s.place(10 + dxx, -11, 10 + dzz, AIR)
        s.place(10 + dxx, -10, 10 + dzz, AIR)
    #   CHIS/CUT 封边：W (7,-10,10)(7,-11,10)；E (13,-10,10)(13,-11,10)
    #                 N (10,-10,7)(10,-11,7)；S (10,-10,13)(10,-11,13)
    for (dx, dy, dz, val) in ((7, -10, 10, CHIS), (7, -11, 10, CUT),
                              (13, -10, 10, CHIS), (13, -11, 10, CUT),
                              (10, -10, 7, CHIS), (10, -11, 7, CUT),
                              (10, -10, 13, CHIS), (10, -11, 13, CUT)):
        s.place(dx, dy, dz, val)
    # L215-221：四臂箱子（Plane.HORIZONTAL 循环序 N→E→S→W，
    # 位置 (10+stepX*2, -11, 10+stepZ*2)，各 1 nextLong）
    for d in range(4):
        dxx, dzz = _DIR_STEPS[d]
        s.create_chest(10 + dxx * 2, -11, 10 + dzz * 2,
                       "chests/desert_pyramid")
    # L223：秘密室（入口沙墙 + 挖掘室外框）
    _desert_secret_room(s)
    return s


def _desert_secret_room(s: _Sim) -> None:
    """fhj L227-306：挖掘室（可疑的沙子玩法）。

    中心 (16,-4,13)；下行楼梯为 SANDSTONE_STAIRS.rotate(CCW90)
    （FACING n -> 局部 w）；$$9 = level.getRandom().nextBoolean()
    属世界装饰流不可预测，固定取 true 分支。外框原代码
    skipExisting=true（适应地形只在非空气处覆盖），平坦预览无地形
    假设，恒写入。挖掘点记录（fhj 的 k 列表）不影响体素，不转写。
    """
    SS, CUT, CHIS, AIR = SANDSTONE, CUT_SANDSTONE, CHISELED_SANDSTONE, None
    # a(is,dxn,ffg)：入口下行楼梯 + 沙墙（$$9=true 分支）
    s.stairs(13, -1, 17, "w", SANDSTONE_STAIRS)
    s.stairs(14, -2, 17, "w", SANDSTONE_STAIRS)
    s.stairs(15, -3, 17, "w", SANDSTONE_STAIRS)
    for dx in (12, 13, 14, 15, 16):
        s.place(dx, 0, 17, SAND)
    s.place(14, -1, 17, SAND)
    s.place(15, -1, 17, SAND)          # $$9=true -> sand
    s.place(16, -1, 17, SS)            # !$9 -> sandstone
    s.place(15, -2, 17, SAND)
    s.place(16, -2, 17, SS)
    s.place(16, -3, 17, SAND)
    # b(is,dxn,ffg)：外框三层（y=-3 CUT / y=-2 CHIS / y=-1 CUT，
    # 四条边线组）+ 顶面挖空 + 陶瓦装饰
    for y, mat in ((-3, CUT), (-2, CHIS), (-1, CUT)):
        s.fill_hollow(13, y, 10, 13, y, 15, mat, mat)
        s.fill_hollow(19, y, 10, 19, y, 15, mat, mat)
        s.fill_hollow(13, y, 10, 19, y, 11, mat, mat)
        s.fill_hollow(13, y, 16, 19, y, 16, mat, mat)
    s.fill_air(14, 0, 11, 18, 0, 15)
    s.place(16, -4, 13, BLUE_TERRACOTTA)
    for (dx, dz) in ((17, 12), (17, 14), (15, 12), (15, 14), (18, 13),
                     (14, 13), (16, 15), (16, 11), (19, 13), (13, 13)):
        s.place(dx, -4, dz, ORANGE_TERRACOTTA)
    s.place(20, -3, 13, CUT)
    s.place(20, -2, 13, CHIS)
    s.place(12, -3, 13, CUT)
    s.place(12, -2, 13, CHIS)
    s.place(16, -3, 9, CUT)
    s.place(16, -2, 9, CHIS)


# ---------------------------------------------------------------------------
# jungle_temple（fhq.postProcess 逐行转写；a=12、c=15）
# ---------------------------------------------------------------------------

def _sim_jungle(world_seed: int, ax: int, az: int, facing: int) -> _Sim:
    """丛林神庙 postProcess 模拟（fhq L32-205）。

    RNG：全部 mossy 框逐格 nextFloat（按语句顺序）→ 发射器(3,-2,1)
    → 发射器(9,-2,3) → 主箱(8,-3,3) → 暗箱(9,-3,10)，各 1 nextLong。
    机关方块（绊线钩/绊线/红石线/拉杆/活塞/中继器/藤蔓）为静态
    摆放（无 RNG），官方几何码 + 方向属性净变换（模块 docstring）。
    """
    s = _Sim("jungle_pyramid", world_seed, ax, az, facing, 12, 15)
    a, c = 12, 15
    AIR = None
    MOSSY = MOSSY_COBBLESTONE

    # L33：updateAverageGroundHeight(level, bb, 0)——无随机偏移，无 RNG
    # L34-46：外壳与内部结构（MossStoneSelector 逐格 nextFloat）
    s.fill_mossy(0, -4, 0, a - 1, 0, c - 1)
    s.fill_mossy(2, 1, 2, 9, 2, 2)
    s.fill_mossy(2, 1, 12, 9, 2, 12)
    s.fill_mossy(2, 1, 3, 2, 2, 11)
    s.fill_mossy(9, 1, 3, 9, 2, 11)
    s.fill_mossy(1, 3, 1, 10, 6, 1)
    s.fill_mossy(1, 3, 13, 10, 6, 13)
    s.fill_mossy(1, 3, 2, 1, 6, 12)
    s.fill_mossy(10, 3, 2, 10, 6, 12)
    s.fill_mossy(2, 3, 2, 9, 3, 12)
    s.fill_mossy(2, 6, 2, 9, 6, 12)
    s.fill_mossy(3, 7, 3, 8, 7, 11)
    s.fill_mossy(4, 8, 4, 7, 8, 10)
    # L47-55：generateAirBox 挖空 9 处（无 RNG）
    s.fill_air(3, 1, 3, 8, 2, 11)
    s.fill_air(4, 3, 6, 7, 3, 9)
    s.fill_air(2, 4, 2, 9, 5, 12)
    s.fill_air(4, 6, 5, 7, 6, 9)
    s.fill_air(5, 7, 6, 6, 7, 8)
    s.fill_air(5, 1, 2, 6, 2, 2)
    s.fill_air(5, 2, 12, 6, 2, 12)
    s.fill_air(5, 5, 1, 6, 5, 1)
    s.fill_air(5, 5, 13, 6, 5, 13)
    # L56-59：采光孔
    for (dx, dz) in ((1, 5), (10, 5), (1, 9), (10, 9)):
        s.place(dx, 5, dz, AIR)
    # L61-66：南北面立柱
    for z in (0, 14):
        for dx in (2, 4, 7, 9):
            s.fill_mossy(dx, 4, z, dx, 5, z)
    # L68：入口梁
    s.fill_mossy(5, 6, 0, 6, 6, 0)
    # L70-77：东西面立柱与装饰
    for dx in (0, 11):
        for z in range(2, 13, 2):
            s.fill_mossy(dx, 4, z, dx, 5, z)
        s.fill_mossy(dx, 6, 5, dx, 6, 5)
        s.fill_mossy(dx, 6, 9, dx, 6, 9)
    # L79-87：顶部角柱与中心柱
    s.fill_mossy(2, 7, 2, 2, 9, 2)
    s.fill_mossy(9, 7, 2, 9, 9, 2)
    s.fill_mossy(2, 7, 12, 2, 9, 12)
    s.fill_mossy(9, 7, 12, 9, 9, 12)
    s.fill_mossy(4, 9, 4, 4, 9, 4)
    s.fill_mossy(7, 9, 4, 7, 9, 4)
    s.fill_mossy(4, 9, 10, 4, 9, 10)
    s.fill_mossy(7, 9, 10, 7, 9, 10)
    s.fill_mossy(5, 9, 7, 6, 9, 7)
    # L88-91：楼梯局部朝向（iz.f/e/d/c = E/W/S/N）
    s_e, s_w, s_s, s_n = "e", "w", "s", "n"
    # L92-95：二层楼梯（大厅）
    s.stairs(5, 9, 6, s_n, COBBLESTONE_STAIRS)
    s.stairs(6, 9, 6, s_n, COBBLESTONE_STAIRS)
    s.stairs(5, 9, 8, s_s, COBBLESTONE_STAIRS)
    s.stairs(6, 9, 8, s_s, COBBLESTONE_STAIRS)
    # L96-99：入口门廊楼梯
    for dx in (4, 5, 6, 7):
        s.stairs(dx, 0, 0, s_n, COBBLESTONE_STAIRS)
    # L100-105：两侧下行楼梯
    for dx in (4, 7):
        s.stairs(dx, 1, 8, s_n, COBBLESTONE_STAIRS)
        s.stairs(dx, 2, 9, s_n, COBBLESTONE_STAIRS)
        s.stairs(dx, 3, 10, s_n, COBBLESTONE_STAIRS)
    # L106-108：楼梯平台
    s.fill_mossy(4, 1, 9, 4, 1, 9)
    s.fill_mossy(7, 1, 9, 7, 1, 9)
    s.fill_mossy(4, 1, 10, 7, 2, 10)
    # L109-111：上层平台 + 楼梯
    s.fill_mossy(5, 4, 5, 6, 4, 5)
    s.stairs(4, 4, 5, s_e, COBBLESTONE_STAIRS)
    s.stairs(7, 4, 5, s_w, COBBLESTONE_STAIRS)
    # L113-117：出口下沉台阶（4 级，含下方挖空）
    for i in range(4):
        s.stairs(5, -i, 6 + i, s_s, COBBLESTONE_STAIRS)
        s.stairs(6, -i, 6 + i, s_s, COBBLESTONE_STAIRS)
        s.fill_air(5, -i, 7 + i, 6, -i, 9 + i)
    # L119-121：暗室挖空
    s.fill_air(1, -3, 12, 10, -1, 13)
    s.fill_air(1, -3, 1, 3, -1, 13)
    s.fill_air(1, -3, 1, 9, -1, 5)
    # L123-125：地板横梁
    for z in range(1, 14, 2):
        s.fill_mossy(1, -3, z, 1, -2, z)
    # L127-129：顶梁
    for z in range(2, 13, 2):
        s.fill_mossy(1, -1, z, 3, -1, z)
    # L131-134：暗室台阶基座
    s.fill_mossy(2, -2, 1, 5, -2, 1)
    s.fill_mossy(7, -2, 1, 9, -2, 1)
    s.fill_mossy(6, -3, 1, 6, -3, 1)
    s.fill_mossy(6, -1, 1, 6, -1, 1)
    # L135-136：陷阱 1 绊线钩（thook 码，局部 FACING E/W）
    s.place(1, -3, 8, _thook(s, "e"))
    s.place(4, -3, 8, _thook(s, "w"))
    # L137-138：绊线（twire 码，局部 E+W 连接两钩）
    s.place(2, -3, 8, _segs(s, TRIPWIRE, "twire", e=True, w=True))
    s.place(3, -3, 8, _segs(s, TRIPWIRE, "twire", e=True, w=True))
    # L139-147：红石线（rswire 码；$$17 = 局部 N+S 纵列）
    for z in range(2, 8):
        s.place(5, -3, z,
                _segs(s, REDSTONE_WIRE, "rswire", n=True, so=True))
    s.place(5, -3, 1, _segs(s, REDSTONE_WIRE, "rswire", n=True, w=True))
    s.place(4, -3, 1, _segs(s, REDSTONE_WIRE, "rswire", e=True, w=True))
    # L148：苔石
    s.place(3, -3, 1, MOSSY)
    # L149-151：陷阱发射器 1（局部 FACING north，1 nextLong）
    s.create_dispenser(3, -2, 1, "chests/jungle_temple_dispenser", "n")
    # L153：藤蔓（局部 SOUTH 面）
    s.place(3, -2, 2, (VINE, "vine:" + s.facing_of("s")))
    # L154-155：陷阱 2 绊线钩（局部 FACING N/S）
    s.place(7, -3, 1, _thook(s, "n"))
    s.place(7, -3, 5, _thook(s, "s"))
    # L156-158：绊线（局部 N+S）
    for z in (2, 3, 4):
        s.place(7, -3, z,
                _segs(s, TRIPWIRE, "twire", n=True, so=True))
    # L159-161：红石线
    s.place(8, -3, 6, _segs(s, REDSTONE_WIRE, "rswire", e=True, w=True))
    s.place(9, -3, 6, _segs(s, REDSTONE_WIRE, "rswire", so=True, w=True))
    s.place(9, -3, 5, _segs(s, REDSTONE_WIRE, "rswire", n=True, so=True))
    # L162-163：苔石 + 红石线（(9,-2,4) N+S，$$17）
    s.place(9, -3, 4, MOSSY)
    s.place(9, -2, 4, _segs(s, REDSTONE_WIRE, "rswire", n=True, so=True))
    # L164-166：陷阱发射器 2（局部 FACING west，1 nextLong）
    s.create_dispenser(9, -2, 3, "chests/jungle_temple_dispenser", "w")
    # L168-169：藤蔓（局部 EAST 面）
    s.place(8, -1, 3, (VINE, "vine:" + s.facing_of("e")))
    s.place(8, -2, 3, (VINE, "vine:" + s.facing_of("e")))
    # L170-172：主箱（1 nextLong）
    s.create_chest(8, -3, 3, "chests/jungle_temple")
    # L174-182：暗室苔石装饰
    for (dx, dy, dz) in ((9, -3, 2), (8, -3, 1), (4, -3, 5), (5, -2, 5),
                         (5, -1, 5), (6, -3, 5), (7, -2, 5), (7, -1, 5),
                         (8, -3, 5)):
        s.place(dx, dy, dz, MOSSY)
    # L183：暗室内墙
    s.fill_mossy(9, -1, 1, 9, -1, 5)
    # L184：暗室挖空
    s.fill_air(8, -3, 8, 10, -1, 10)
    # L185-187：錾制石砖开关墙
    for dx in (8, 9, 10):
        s.place(dx, -2, 11, CHISELED_STONE_BRICKS)
    # L188-191：拉杆（wall face，局部 FACING north -> 世界伸出
    # 方向即码 facing 段；powered=false）
    for dx in (8, 9, 10):
        s.place(dx, -2, 12,
                (LEVER, "lever:w:" + s.facing_of("n") + ":0"))
    # L192-193：暗室侧壁
    s.fill_mossy(8, -3, 8, 8, -3, 10)
    s.fill_mossy(10, -3, 8, 10, -3, 10)
    # L194：苔石
    s.place(10, -2, 9, MOSSY)
    # L195-197：红石线（(8,-2,9)/(8,-2,10) 纵向 + (10,-1,9) 四向）
    s.place(8, -2, 9, _segs(s, REDSTONE_WIRE, "rswire", n=True, so=True))
    s.place(8, -2, 10, _segs(s, REDSTONE_WIRE, "rswire", n=True, so=True))
    s.place(10, -1, 9, _segs(s, REDSTONE_WIRE, "rswire",
                             n=True, so=True, e=True, w=True))
    # L198-200：粘性活塞暗门（pist 码；u/d 不随 mirror/rotate）
    s.place(9, -2, 8, (STICKY_PISTON, "pist:u:s"))
    s.place(10, -2, 8, (STICKY_PISTON, "pist:" + s.facing_of("w") + ":s"))
    s.place(10, -1, 8, (STICKY_PISTON, "pist:" + s.facing_of("w") + ":s"))
    # L201：中继器（repeater 码，局部 FACING north）
    s.place(10, -2, 10, (REPEATER, "repeater:" + s.facing_of("n")))
    # L202-204：暗箱（1 nextLong）
    s.create_chest(9, -3, 10, "chests/jungle_temple")
    return s


# ---------------------------------------------------------------------------
# 对外入口（composition.compose_display_model 调用）
# ---------------------------------------------------------------------------

def build_pyramid_voxels(comp) -> tuple[dict, set]:
    """Composition -> (体素 dict, 箱子相对偏移集合)。

    体素坐标 = 世界 - anchor（x/z）、世界 - 64（y，模型基准面）。
    箱子偏移集合（RNG 预测容器的 (x,z) 相对 anchor）供 display 兜底。
    体素与容器同源（同一 _Sim 运行），坐标严格重合。
    """
    facing = comp.extra["facing"]
    ax, az = comp.anchor
    if comp.struct_key == "desert_pyramid":
        s = _sim_desert(comp.extra["world_seed"], ax, az, facing)
    elif comp.struct_key == "jungle_temple":
        s = _sim_jungle(comp.extra["world_seed"], ax, az, facing)
    else:
        raise ValueError(f"pyramid_pieces 未支持的结构键：{comp.struct_key}")
    voxels = {(x, y - 64, z): v for (x, y, z), v in s.voxels.items()}
    chest_offs = {(wx - ax, wz - az) for (wx, wz, _y, _t, _sd) in s.chests}
    return voxels, chest_offs
