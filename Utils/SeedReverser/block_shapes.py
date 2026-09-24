# -*- coding: utf-8 -*-
"""非完整方块形状几何库（StructurePreviewer / SeedReverser 共用）。

依据 MC 官方方块状态 properties（facing/half/type/open 等）生成形状码
（16 分格 AABB 近似几何），供 build_mesh 网格化与连通性分析。
纯视觉近似：观察定位场景够用。

体素值约定（structure_models.build_mesh）：
- 值为 (tex, shape) 二元组：tex 纹理键；shape None=整格，str=形状码；
- 纯字符串值 = 老格式整格（程序化示意体/蓝图挤出）；
  "halfheight:" 前缀（蓝图侧遗留）= 底半砖。
"""
from functools import lru_cache

# ---------------------------------------------------------------- 形状码
# 半砖：half:<vh>:<blank>   vh: t 顶半 / b 底半
#   blank: a 完整（模板内实际只有完整半砖；缺角版保留供扩展）
SHAPE_SLAB_TOP = "half:t:a"
SHAPE_SLAB_BOT = "half:b:a"
# 楼梯：stairs:<quad>:<half>  quad = 官方 facing（踏步贴该侧）：
#   s 踏步贴南(+z) / n 北(-z) / e 东(+x) / w 西(-x)
#   half: b 下半 / t 上半（vert_stack 楼梯，y 镜像 = 顶半格 +
#   踏步落底半格，不越界进上方格）
SHAPE_STAIRS = {"s": "stairs:s:b", "n": "stairs:n:b",
                "e": "stairs:e:b", "w": "stairs:w:b"}
# 门：door:<半区>:<开合>:<facing>:<铰链>
#   半区 l 下半 / u 上半；开合 c 关 / o 开；铰链 left / right
SHAPE_DOOR_LC = "door:l:c:s:left"
SHAPE_DOOR_UC = "door:u:c:s:left"
# 活板门：trapdoor:<朝向>:<开合>:<半区>
#   关闭=水平薄板置于半区；开=竖薄板贴 -朝向 侧框边；半区 b 底 / t 顶
SHAPE_TRAPDOOR_CB = "trapdoor:n:c:b"
SHAPE_TRAPDOOR_CT = "trapdoor:n:c:t"
# 栅栏/栅栏门中心柱：post（官方 4/16 细柱；横臂由 build_mesh
# 依邻居连通自动补，臂为官方 2/16 截面双横轨）
SHAPE_FENCE_POST = "post"
# 墙：wall（官方 8/16 柱；连通臂 6/16 宽、高 14/16）
SHAPE_WALL = "wall"
# 横杆：bar:<axis>（x/z 水平杆；y 竖直杆 = 链）
SHAPE_BAR_X = "bar:x"
SHAPE_BAR_Y = "bar:y"
SHAPE_BAR_Z = "bar:z"
# 面板类：pane（玻璃板/铁栏杆中央竖板，连通臂自动补）
SHAPE_PANE = "pane"
# 火把：torch:v 立式细杆 / torch:n|s|e|w 墙上火把（背靠该向墙面）
SHAPE_TORCH_V = "torch:v"
SHAPE_TORCH_H = "torch:h"        # 悬挂灯笼（居中小块）
# 箱子：chest:<facing>:<type>（type：single 单箱 / left 大箱左半 /
# right 大箱右半；两段旧码 "chest:<f>" 兼容读作 single）。单箱
# 14x14x14 居中；大箱左右半 15/16 宽（接缝侧贴格界、外侧缩进
# 1/16）满深 z∈[1/16,15/16]、14/16 高，两半合拢跨两格共 30/16
# 宽。left 占 facing 左手侧格（facing 逆时针 90°：n→w/e→n/s→e/
# w→s），facing=n 基准：left 半 x∈[1/16,1]（西格，东缘贴界）、
# right 半 x∈[0,15/16]（东格，西缘贴界）。朝向面用半窗合成图
# （chest big left/right，锁扣列贴接缝缘）拼合复原双箱观感；
# 旋转后随 _ROT_FACE 换向（type 保留），与 vanilla 一致
# （facing=e 时 left 占北格，与模板实测一致）。
SHAPE_CHEST_N = "chest:n:single"
# 桶（barrel，13/16 高实心柱体，同箱子缩进风格）：barrel
SHAPE_BARREL = "barrel"
# 床（9/16 高整格）：bed
SHAPE_BED = "bed"
# 整格截层 layer（13/16）；压力板 plate（2/16）；地毯 carpet（1/16）
SHAPE_LAYER = "layer"
SHAPE_PLATE = "plate"
SHAPE_CARPET = "carpet"
# 炼药锅/堆肥桶（四壁+底杯状）：cauldron
SHAPE_CAULDRON = "cauldron"
# 拉杆 lever:<贴边|up|down>（官方 lever.json：圆石底座 6x3x8 +
# 2x10x2 杆未触发 -45° 斜置，4 段 45° 阶梯盒逼近；墙贴 = x90 家族
# 旋转，up=floor 原始 / down=ceiling x180）
SHAPE_BUTTON = "button:n"
SHAPE_LEVER = "lever:up"
# 钟（bell:<att>）：几何与官方 1.21.11 全对齐。att =
#   floor:x | floor:z   双柱+横梁（梁沿 x/z；官方 blockstate
#                       floor n/s -> 梁沿 x、e/w -> 90°旋转沿 z；
#                       旧码 "floor" 兼容读作 :x）
#   ceiling             吊杆+钟体（吊杆对称无朝向）
#   wall1:<f>           单墙梁（f=锚墙向 e/n/s/w，官方 4 向，
#                       钟体并集与官方选择盒 m/n/o/F 逐坐标一致）
#   wall2:<axis>        双墙贯通梁（梁沿 x/z，官方 k/l）
# 钟体 = BellRenderer 实体模型两段盒（bell_base 8x2x8 y[4,6] +
# bell_body 6x7x6 y[6,13]，与官方选择盒 j 精确一致），静态直立
# （摆动动画属 BER 不模拟）
SHAPE_BELL_FLOOR = "bell:floor:x"
# 堆肥桶（镂空桶，无朝向）
SHAPE_COMPOSTER = "composter"
# 落地告示牌/旗帜（十字交叉板简化）
SHAPE_CROSS = "cross"
# 农作物/花草/蘑菇等植物（真·对角 X 双面，MC template_cross 语义；
# 几何在 build_mesh 专用 quad 路径，AABB 体系不适用）
SHAPE_PLANT = "plant"
# 轴心方块 col:<axis>（原木/去皮原木/玄武岩/磨制玄武岩/石英柱等：
# 几何=整格，仅承载轴向供分面纹理选端面/侧面）
SHAPE_COL_Y = "col:y"
# 炉族前脸方块 fc:<f>[:lit]（furnace/blast_furnace/smoker：整格+朝向，
# 前脸/侧面/顶面分面；dispenser 同族但无 lit 段）
SHAPE_FC_N = "fc:n"
# 酿造台 brewing（中央杆 (7,0,7)-(9,14,9) + 三块底板，官方
# brewing_stand.json 元素原样；杆/底板 UV 与世界平铺天然吻合）
SHAPE_BREWING = "brewing"
# 花盆 flowerpot（四壁 + 底 5 元素，官方 flower_pot.json）
SHAPE_FLOWERPOT = "flowerpot"
# 蜡烛 candle（主柱 (7,0,7)-(9,6,9)，官方 template_candle.json 主元素）
SHAPE_CANDLE = "candle"
# 灯笼 lantern（主体 (5,0,5)-(11,7,11) + 顶盖 (6,7,6)-(10,9,10)，
# 官方 template_lantern.json 前两元素）
SHAPE_LANTERN = "lantern"
# 末地烛 erod:<facing 缩写|u|d>：底座 (6,0,6)-(10,1,10) + 立杆
# (7,1,7)-(9,16,9) 按朝向旋转（官方 end_rod.json）
SHAPE_END_ROD = "erod:y"
# 龙首 dhead:<f>[:w]：头部主盒 12x12x12（DragonHeadModel upper_head
# 16³ x0.75 近似）贴格底居中；:w = 墙挂（中心抬 0.25、向墙面外凸）
SHAPE_DRAGON_HEAD = "dhead:n"
# 床分半：bed:head / bed:foot（head 含枕头区顶面 rect，foot 毯子区）
SHAPE_BED_HEAD = "bed:head"
SHAPE_BED_FOOT = "bed:foot"
# 墙挂告示牌 wsign:<att>：板 24x12x2 官方比例贴墙面（1/16 缩进）
SHAPE_WALL_SIGN = "wsign:n"
# 活塞头 pisth:<f>：平台 16x16x4 + 突轴 4x4x12（官方
# template_piston_head.json，facing 即伸出方向）
SHAPE_PISTON_HEAD = "pisth:n"
# 讲台 lectern：底座 16x2x16 + 立柱 8x13x8 + 顶板（官方 lectern.json
# 顶板斜置以水平薄板近似）
SHAPE_LECTERN = "lectern"
# 红石线 rswire:<n>:<s>:<e>:<w>（每向 -/s/u = side/up 连接；官方
# multipart redstone_dust_* 几何：4px 宽辐射臂贴地 1/64 厚片 +
# up 全高贴边竖片，孤点画中心 4x4 板；纹理自制十字图，世界平铺
# UV 自动命中线带）
SHAPE_RSWIRE = "rswire:-:-:-:-"
# 中继器/比较器 repeater:<f> / comparator:<f>（facing = 输出方向；
# 官方 repeater_1tick / comparator.json：平滑石底板 2/16 + 火把柱，
# 原始朝向 n；powered/mode 纯纹理差异几何不变）
# 幽匿感测体 sculk（sculk_sensor.json：8/16 底座 + 四角触须，官方
# 45° 斜片以直立薄板近似）
# 粘性活塞/活塞 pist:<f>（整格 + 朝向分面：顶 sticky/普通、侧
# piston_side、底 piston_bottom；官方 piston.json cube 组）
# 红石灯 lamp:<0|1>（整格，lit 选 on 纹理）
# 绊线 twire:<n>:<s>:<e>:<w>（官方 tripwire_n*.json：0.5px 细线
# 面片 y=1.5，1/64 厚薄盒近似；段序同 rswire，1=连接/-=无）
# 绊线钩 thook:<贴边>[:a]（官方 tripwire_hook[_attached].json：
# 背板+横臂+钩件多盒，attached 带绊线伸出段；贴边 = 背板所在
# 格缘，facing 反侧）
# 藤蔓 vine:<dir>[+<dir>]（官方 vine.json：贴边薄面片 0.8/16
# 厚盒近似，dir = n/s/e/w/u，多面组合态 + 连接）


_E = 0.0625   # 1/16
_HALF = 0.5   # 半层边界

# MC 属性全称 -> 形状码缩写（NBT Properties 值为 north/south/east/west）
_FACING_ABBR = {"north": "n", "south": "s", "east": "e", "west": "w"}

# ---------------------------------------------------------------- 几何


def _slab(vh: str, blank: str):
    x0, z0, x1, z1 = 0.0, 0.0, 1.0, 1.0
    if blank == "m":
        z0 = _HALF
    elif blank == "s":
        z1 = _HALF
    elif blank == "e":
        x1 = _HALF
    elif blank == "w":
        x0 = _HALF
    if vh == "t":
        return ((x0, _HALF, z0, x1, 1.0, z1),)
    return ((x0, 0.0, z0, x1, _HALF, z1),)


def _stairs(quad: str, half: str):
    """楼梯（quad=踏步贴靠侧）。底层全宽半格 + 踏步半格。

    官方 1.21 形状（jar block/stairs.json，half=top = 模型绕 x 轴
    180° 旋转）：half=b 底层半格 + 踏步贴靠侧顶半格；half=t =
    整体 y 镜像 —— 顶层半格 + 踏步贴靠侧底半格（踏步不越界，
    旧版整体 +0.5 会把踏步顶推到 y=1.5 插进上方格）。
    """
    if quad == "s":
        boxes = ((0.0, 0.0, 0.0, 1.0, _HALF, 1.0),
                 (0.0, _HALF, _HALF, 1.0, 1.0, 1.0))
    elif quad == "n":
        boxes = ((0.0, 0.0, 0.0, 1.0, _HALF, 1.0),
                 (0.0, _HALF, 0.0, 1.0, 1.0, _HALF))
    elif quad == "e":
        boxes = ((0.0, 0.0, 0.0, 1.0, _HALF, 1.0),
                 (_HALF, _HALF, 0.0, 1.0, 1.0, 1.0))
    else:                                            # w
        boxes = ((0.0, 0.0, 0.0, 1.0, _HALF, 1.0),
                 (0.0, _HALF, 0.0, _HALF, 1.0, 1.0))
    if half == "t":      # 侧置楼梯：y 镜像（顶半格 + 踏步落底半格）
        return tuple((x0, 1.0 - y1, z0, x1, 1.0 - y0, z1)
                     for (x0, y0, z0, x1, y1, z1) in boxes)
    return boxes


def _door(half_part: str, open_: bool, facing: str, hinge: str):
    """门。关：3/16 厚门板贴 facing 侧框边；开：门板转 90° 贴铰链侧。

    官方 door.json：每半块（lower/upper）门板均占满本方块全高
    （elements from [0,0,0] to [16,16,3]），half_part 只影响分块
    纹理选择（_mat_shape），几何上不裁半。
    """
    t = 3 * _E
    y0, y1 = 0.0, 1.0
    del half_part        # 几何无关半区（仅纹理选择用），避免误用
    if not open_:
        if facing == "n":
            return ((0.0, y0, 0.0, 1.0, y1, t),)
        if facing == "s":
            return ((0.0, y0, 1 - t, 1.0, y1, 1.0),)
        if facing == "e":
            return ((1 - t, y0, 0.0, 1.0, y1, 1.0),)
        return ((0.0, y0, 0.0, t, y1, 1.0),)         # w
    # 开：门板贴铰链侧框边、沿门轴展开
    if hinge == "right":
        if facing in ("n", "s"):
            return ((1 - t, y0, 0.0, 1.0, y1, 1.0),)
        return ((0.0, y0, 1 - t, 1.0, y1, 1.0),)     # e/w 铰链在 +z 侧
    if facing in ("n", "s"):                         # left
        return ((0.0, y0, 0.0, t, y1, 1.0),)
    return ((0.0, y0, 0.0, 1.0, y1, t),)             # e/w 铰链在 -z 侧


def _trapdoor(facing: str, open_: bool, half: str):
    """活板门。关：3/16 厚水平薄板置于半区；开：竖薄板贴 facing
    反侧（官方 template_trapdoor_open 基准板贴南缘 z[13,16]，
    blockstates facing=north->y=0 原样、east->y=90、south->y=180、
    west->y=270，即门板所在格缘与 facing 相反）。"""
    t = 3 * _E
    if not open_:
        y0 = 0.0 if half == "b" else _HALF
        return ((0.0, y0, 0.0, 1.0, y0 + t, 1.0),)
    if facing == "n":
        return ((0.0, 0.0, 1 - t, 1.0, 1.0, 1.0),)     # 贴南缘
    if facing == "s":
        return ((0.0, 0.0, 0.0, 1.0, 1.0, t),)         # 贴北缘
    if facing == "e":
        return ((0.0, 0.0, 0.0, t, 1.0, 1.0),)         # 贴西缘
    return ((1 - t, 0.0, 0.0, 1.0, 1.0, 1.0),)         # w 贴东缘


def _bell(att: str):
    """钟。官方 1.21.11 全对齐（静态）：底座 = bell_floor/
    bell_ceiling/bell_wall/bell_between_walls.json 元素原样；
    钟体 = BellRenderer 实体模型两段盒（口座 8x2x8 y[4,6] +
    钟身 6x7x6 y[6,13]，与官方选择盒 j 精确一致），静态直立
    （摆动动画属 BER 不模拟）。att 语义见 SHAPE_BELL_FLOOR
    注释；旧码 "floor" 兼容读作 floor:x，未知值兜底。"""
    e = _E
    body = ((4 * e, 4 * e, 4 * e, 12 * e, 6 * e, 12 * e),    # 钟口座
            (5 * e, 6 * e, 5 * e, 11 * e, 13 * e, 11 * e))   # 钟身
    kind, _, arg = att.partition(":")
    if kind == "ceiling":
        return ((7 * e, 13 * e, 7 * e, 9 * e, 1.0, 9 * e),) + body
    if kind == "wall1":
        # 官方 bell_wall 模型 + blockstate y 旋转（锚墙端 2px
        # 悬空端 13px），与官方选择盒 m/n/o/F 一致
        x0, z0, x1, z1 = {"e": (3, 7, 16, 9), "w": (0, 7, 13, 9),
                          "n": (7, 0, 9, 13),
                          "s": (7, 3, 9, 16)}.get(arg, (3, 7, 16, 9))
        return ((x0 * e, 13 * e, z0 * e, x1 * e, 15 * e, z1 * e),) + body
    if kind == "wall2":
        if arg == "z":
            return ((7 * e, 13 * e, 0.0, 9 * e, 15 * e, 1.0),) + body
        return ((0.0, 13 * e, 7 * e, 1.0, 15 * e, 9 * e),) + body
    if arg == "z":    # floor:z（官方 e/w：y=90/270 旋转）
        return ((6 * e, 0.0, 0.0, 10 * e, 1.0, 2 * e),          # 柱 N
                (6 * e, 0.0, 14 * e, 10 * e, 1.0, 16 * e),      # 柱 S
                (7 * e, 13 * e, 2 * e, 9 * e, 15 * e, 14 * e),  # 横梁
                ) + body
    return ((0.0, 0.0, 6 * e, 2 * e, 1.0, 10 * e),              # 柱 W
            (14 * e, 0.0, 6 * e, 16 * e, 1.0, 10 * e),          # 柱 E
            (2 * e, 13 * e, 7 * e, 14 * e, 15 * e, 9 * e),      # 横梁
            ) + body


def _composter():
    """堆肥桶。官方 composter.json 镂空桶：底板全格 y[0,2] + 四
    壁满高厚 2/16（沿口顶面 composter_top、外侧 composter_side、
    底板底/内底 composter_bottom）。内容物（level>0 contents 模
    型）模板多为空桶，不模拟。无朝向。"""
    e = _E
    return ((0.0, 0.0, 0.0, 1.0, 2 * e, 1.0),                # 底板
            (0.0, 0.0, 0.0, 2 * e, 1.0, 1.0),                # 西壁
            (14 * e, 0.0, 0.0, 1.0, 1.0, 1.0),               # 东壁
            (2 * e, 0.0, 0.0, 14 * e, 1.0, 2 * e),           # 北壁
            (2 * e, 0.0, 14 * e, 14 * e, 1.0, 16 * e))       # 南壁


# 大箱 half -> facing 左手侧格所在方向（facing 逆时针 90°，
# 玩家面向箱子前侧：left 半在玩家左手，即 facing 逆时针 90°）：
# n→w（西格）/ e→n（北格）/ s→e（东格）/ w→s（南格）
_CHEST_LEFT_OF = {"n": "w", "e": "n", "s": "e", "w": "s"}


def _chest(typ: str, facing: str = "n"):
    """箱子。单箱：14x14x14 居中（MC 主体 14/16 宽、高 14/16）。

    大箱左右半（type=left/right）：15/16 宽（外侧缩进 1/16、
    接缝侧贴格界）、满深 z∈[1/16,15/16]、14/16 高；left 半占
    facing 左手侧格（facing=n 基准占西格 x∈[1/16,1]，东缘即
    接缝侧贴界）、right 半占余格（x∈[0,15/16]）。接缝两侧均
    贴格界可被共面剔除；旋转语义由 shape_rotation 的 facing
    换向自然承接（type 原样保留）。
    """
    if typ == "left":
        side = _CHEST_LEFT_OF.get(facing, "w")
        if side == "w":                    # 西格：x∈[1/16,1] 东缘贴界
            return ((_E, 0.0, _E, 1.0, 14 * _E, 1 - _E),)
        if side == "e":                    # 东格：x∈[0,15/16] 西缘贴界
            return ((0.0, 0.0, _E, 15 * _E, 14 * _E, 1 - _E),)
        if side == "n":                    # 北格：z∈[1/16,1] 南缘贴界
            return ((_E, 0.0, _E, 1 - _E, 14 * _E, 1.0),)
        return ((_E, 0.0, 0.0, 1 - _E, 14 * _E, 15 * _E),)   # 南格
    if typ == "right":
        side = _CHEST_LEFT_OF.get(facing, "w")
        if side == "w":                    # 东格：x∈[0,15/16] 西缘贴界
            return ((0.0, 0.0, _E, 15 * _E, 14 * _E, 1 - _E),)
        if side == "e":                    # 西格：x∈[1/16,1] 东缘贴界
            return ((_E, 0.0, _E, 1.0, 14 * _E, 1 - _E),)
        if side == "n":                    # 南格：z∈[0,15/16] 北缘贴界
            return ((_E, 0.0, 0.0, 1 - _E, 14 * _E, 15 * _E),)
        return ((_E, 0.0, _E, 1 - _E, 14 * _E, 1.0),)        # 北格
    return ((_E, 0.0, _E, 1 - _E, 14 * _E, 1 - _E),)


def _barrel():
    """桶：13/16 高 14x14 柱体（MC barrel 主箱体）。"""
    return ((_E, 0.0, _E, 1 - _E, 13 * _E, 1 - _E),)


def _torch(kind: str, facing: str):
    """火把。stick=立式 2/16 细杆（高 10/16，官方 template_torch）；
    wall=墙上火把——官方 template_torch_wall 为单根 2x10x2 斜杆
    （绕 z 轴 -22.5°，底 y 3.5 贴墙、顶 y 13.5 外倾，底/顶中心
    水平差 sin22.5°×10 ≈ 3.8px）。AABB 以三级 1px 台阶盒近似：
    y 3.5..6.5 贴墙段 / y 6.5..10.5 中段（外移 1px）/
    y 10.5..13.5 顶段（外移 2px），贴合面共面由面裁剪消除。"""
    a, b = 7 * _E, 9 * _E
    if kind == "stick":
        return ((a, 0.0, a, b, 10 * _E, b),)
    # 墙上火把：facing = 背靠墙面所在方向（n = 墙在 -z 侧，杆顶伸向
    # +z）。官方基准模型（blockstate facing=east 无旋转）杆贴西面。
    # 三级台阶段进深均为 1px（p1/p2/p3 = 1/2/3px 边界）。
    lo, m1, m2, hi = 3.5 * _E, 6.5 * _E, 10.5 * _E, 13.5 * _E
    p1, p2, p3 = _E, 2 * _E, 3 * _E
    if facing == "n":
        return ((a, lo, 0.0, b, m1, p1),
                (a, m1, p1, b, m2, p2),
                (a, m2, p2, b, hi, p3))
    if facing == "s":
        return ((a, lo, 1 - p1, b, m1, 1.0),
                (a, m1, 1 - p2, b, m2, 1 - p1),
                (a, m2, 1 - p3, b, hi, 1 - p2))
    if facing == "e":
        return ((1 - p1, lo, a, 1.0, m1, b),
                (1 - p2, m1, a, 1 - p1, m2, b),
                (1 - p3, m2, a, 1 - p2, hi, b))
    return ((0.0, lo, a, p1, m1, b),                  # w
            (p1, m1, a, p2, m2, b),
            (p2, m2, a, p3, hi, b))


def _bar(axis: str):
    a, b = 6 * _E, 10 * _E
    if axis == "x":
        return ((0.0, a, a, 1.0, b, b),)
    if axis == "z":
        return ((a, a, 0.0, b, b, 1.0),)
    return ((a, 0.0, a, b, 1.0, b),)                 # y


def _cauldron():
    """炼药锅/堆肥桶：官方 cup 形（jar models/block/cauldron.json、
    composter.json）——四壁满高（y 3..16）+ 底盘（y 0..3），
    壁底与底顶共面区由面裁剪消除。"""
    t = 3 * _E
    return ((0.0, 0.0, 0.0, 1.0, t, 1.0),            # 底
            (0.0, t, 0.0, 1.0, 1.0, t),              # 北壁
            (0.0, t, 1 - t, 1.0, 1.0, 1.0),          # 南壁
            (0.0, t, t, t, 1.0, 1 - t),              # 西壁
            (1 - t, t, t, 1.0, 1.0, 1 - t))          # 东壁


def _brewing():
    """酿造台。官方 brewing_stand.json 四元素原样：
    中央杆 (7,0,7)-(9,14,9) + 三块底板 y0..2（东南板/西北角板/
    西南角板，三板共占圆周三向，俯视呈品字缺口）。"""
    return ((7 * _E, 0.0, 7 * _E, 9 * _E, 14 * _E, 9 * _E),   # 杆
            (9 * _E, 0.0, 5 * _E, 15 * _E, 2 * _E, 11 * _E),  # 东板
            (1 * _E, 0.0, 1 * _E, 7 * _E, 2 * _E, 7 * _E),    # 西北板
            (1 * _E, 0.0, 9 * _E, 7 * _E, 2 * _E, 15 * _E))   # 西南板


def _flowerpot():
    """花盆。官方 flower_pot.json：四壁（x 5..6/10..11、z 5..6/
    10..11，高 0..6）+ 内底 (6,0,6)-(10,4,10)。"""
    a, b = 5 * _E, 11 * _E
    c, d = 6 * _E, 10 * _E
    h = 6 * _E
    return ((a, 0.0, a, c, h, b),                    # 西壁
            (d, 0.0, a, b, h, b),                    # 东壁
            (c, 0.0, a, d, h, c),                    # 北壁
            (c, 0.0, d, d, h, b),                    # 南壁
            (c, 0.0, c, d, 4 * _E, d))               # 内底


def _candle():
    """蜡烛。官方 template_candle.json 主元素：柱 (7,0,7)-(9,6,9)。
    （烛芯 1x1 斜元素省略——1 像素小于线宽，观感无差。）"""
    return ((7 * _E, 0.0, 7 * _E, 9 * _E, 6 * _E, 9 * _E),)


def _lantern(hang: bool):
    """灯笼。官方 template_lantern.json 前两元素：主体 (5,0,5)-
    (11,7,11) + 顶盖 (6,7,6)-(10,9,10)；hanging 变体整体 +1
    （主体 y1..8、顶盖 y8..10，顶与格顶留 6/16 挂链空间近似）。"""
    dy = 1 * _E if hang else 0.0
    return ((5 * _E, dy, 5 * _E, 11 * _E, 7 * _E + dy, 11 * _E),
            (6 * _E, 7 * _E + dy, 6 * _E, 10 * _E, 9 * _E + dy, 10 * _E))


def _end_rod(facing: str):
    """末地烛。官方 end_rod.json：底座 (6,0,6)-(10,1,10) + 立杆
    (7,1,7)-(9,16,9)（杆贴底座顶伸出格顶）。facing = 杆指向：
    up 竖立 / down 竖立倒置 / n|s 杆沿 z / e|w 杆沿 x（水平时
    底座贴 facing 反侧格壁）。"""
    base = (6 * _E, 0.0, 6 * _E, 10 * _E, 1 * _E, 10 * _E)
    pole_v = (7 * _E, 1 * _E, 7 * _E, 9 * _E, 1.0, 9 * _E)
    if facing == "d":                    # 倒置：镜像到格顶
        return ((6 * _E, 15 * _E, 6 * _E, 10 * _E, 1.0, 10 * _E),
                (7 * _E, 0.0, 7 * _E, 9 * _E, 15 * _E, 9 * _E))
    if facing in ("n", "s"):             # 杆沿 z：底座贴反侧壁
        zb = 0.0 if facing == "n" else 1 - 4 * _E
        base = (6 * _E, 6 * _E, zb, 10 * _E, 10 * _E, zb + 1 * _E)
        zp = zb + 1 * _E if facing == "n" else 0.0
        pole = (7 * _E, 7 * _E, zp, 9 * _E, 9 * _E, zp + 15 * _E)
        return (base, pole)
    if facing in ("e", "w"):             # 杆沿 x
        xb = 1 - 4 * _E if facing == "e" else 0.0
        base = (xb, 6 * _E, 6 * _E, xb + 1 * _E, 10 * _E, 10 * _E)
        xp = xb + 1 * _E if facing == "e" else 0.0
        pole = (xp, 7 * _E, 7 * _E, xp + 15 * _E, 9 * _E, 9 * _E)
        return (base, pole)
    return (base, pole_v)                                # up


def _dragon_head(wall: bool, facing: str):
    """龙首。DragonHeadModel head 框 16³ x0.75 = 12³ 单盒近似
    （细节鳞片/鼻孔/下颚省略，观察定位够用）。落地：贴格底居中
    (2,0,2)-(14,12,14)；墙挂：官方 SkullBlockRenderer 墙挂中心
    抬 0.25、向墙面外凸 0.25 → 盒 (2,4,2)-(14,16,14) 沿 facing
    平移 0.25（出格 2/16 保留官方凸出观感，面剔除按不贴界处理
    无副作用）。facing = 脸朝向（渲染态 = 龙脸看向的方向）。"""
    if wall:
        box = (2 * _E, 4 * _E, 2 * _E, 14 * _E, 16 * _E, 14 * _E)
        if facing == "n":
            return ((box[0], box[1], box[2] - 2 * _E,
                     box[3], box[4], box[5] - 2 * _E),)
        if facing == "s":
            return ((box[0], box[1], box[2] + 2 * _E,
                     box[3], box[4], box[5] + 2 * _E),)
        if facing == "e":
            return ((box[0] + 2 * _E, box[1], box[2],
                     box[3] + 2 * _E, box[4], box[5]),)
        return ((box[0] - 2 * _E, box[1], box[2],
                 box[3] - 2 * _E, box[4], box[5]),)
    return ((2 * _E, 0.0, 2 * _E, 14 * _E, 12 * _E, 14 * _E),)


def _wall_sign(att: str):
    """墙挂告示牌。SignRenderer wall 模型：板 24x12x2（模型单位
    /16 = 24/16 宽越格，AABB 收敛为 1.0 宽 12/16 高 2/16 厚）
    scale 0.667 后实际 ≈ 16x8x1.3 —— 直接用 1.0 x 8/16 x 2/16
    近似（板内容纹理 rect 已按 16x8 压缩合成，见 make_decor_tex）。
    att = 贴墙边（板面朝外）。"""
    t = 2 * _E
    h = 8 * _E
    y0 = 6 * _E                     # 板顶 y14/16 内（板高 8/16）
    if att == "n":
        return ((0.0, y0, 0.0, 1.0, y0 + h, t),)
    if att == "s":
        return ((0.0, y0, 1 - t, 1.0, y0 + h, 1.0),)
    if att == "e":
        return ((1 - t, y0, 0.0, 1.0, y0 + h, 1.0),)
    return ((0.0, y0, 0.0, t, y0 + h, 1.0),)         # w


def _piston_head(facing: str):
    """活塞头。官方 template_piston_head.json：平台 16x16x4
    （facing=n 基准贴格北缘）+ 突轴 4x4x16（y/x 6..10，轴朝本体
    方向越出本格 4px 与 extended 本体凹口咬合——官方 z 4..20）。
    facing = 伸出方向。"""
    if facing == "s":
        return ((0.0, 0.0, 12 * _E, 1.0, 1.0, 1.0),
                (6 * _E, 6 * _E, -4 * _E, 10 * _E, 10 * _E, 12 * _E))
    if facing == "e":
        return ((12 * _E, 0.0, 0.0, 1.0, 1.0, 1.0),
                (-4 * _E, 6 * _E, 6 * _E, 12 * _E, 10 * _E, 10 * _E))
    if facing == "w":
        return ((0.0, 0.0, 0.0, 4 * _E, 1.0, 1.0),
                (4 * _E, 6 * _E, 6 * _E, 20 * _E, 10 * _E, 10 * _E))
    if facing == "d":
        return ((0.0, 0.0, 0.0, 1.0, 4 * _E, 1.0),
                (6 * _E, 4 * _E, 6 * _E, 10 * _E, 20 * _E, 10 * _E))
    if facing == "u":
        return ((0.0, 12 * _E, 0.0, 1.0, 1.0, 1.0),
                (6 * _E, -4 * _E, 6 * _E, 10 * _E, 12 * _E, 10 * _E))
    return ((0.0, 0.0, 0.0, 1.0, 1.0, 4 * _E),       # n
            (6 * _E, 6 * _E, 4 * _E, 10 * _E, 10 * _E, 20 * _E))


def _lectern():
    """讲台。官方 lectern.json：底座 16x2x16 + 立柱 8x13x8 +
    顶板（官方斜置 -22.5°，AABB 近似为水平薄板 16x4x13 y12..16
    贴柱顶前伸）。"""
    return ((0.0, 0.0, 0.0, 1.0, 2 * _E, 1.0),       # 底座
            (4 * _E, 2 * _E, 4 * _E, 12 * _E, 15 * _E, 12 * _E),  # 柱
            (0.0, 12 * _E, 3 * _E, 1.0, 16 * _E, 16 * _E))  # 顶板


# ---------------------------------------------------------------- 解析

def shape_from_props(name: str, props: dict) -> str | None:
    """官方方块名（minecraft:xxx）+ properties -> 形状码。

    无形状语义返回 None（调用方按整格处理）。
    """
    if not isinstance(props, dict):
        props = {}
    facing = _FACING_ABBR.get(props.get("facing", ""),
                              props.get("facing", ""))
    half = props.get("half", "")
    typ = props.get("type", "")

    # 作物（官方 crop.json 四片竖直面 x=4/12、z=4/12，下探 1px）
    # 与花草（cross 对角片）分流：crop 走 build_mesh 专用四片路径
    if name.endswith("_stem") or name in (
            "minecraft:wheat", "minecraft:carrots", "minecraft:potatoes",
            "minecraft:beetroots"):
        return "crop"

    if name.endswith("_sapling") or name in (
            "minecraft:nether_wart",
            "minecraft:red_mushroom", "minecraft:brown_mushroom",
            "minecraft:sea_pickle",
            "minecraft:poppy", "minecraft:dandelion",
            "minecraft:oxeye_daisy", "minecraft:short_grass",
            "minecraft:tall_grass", "minecraft:fern",
            "minecraft:large_fern", "minecraft:dead_bush"):
        return SHAPE_PLANT

    if name.endswith("_slab"):
        if typ == "top":
            return SHAPE_SLAB_TOP
        if typ == "bottom":
            return SHAPE_SLAB_BOT
        return None                                  # double 按整格

    if name.endswith("_stairs"):
        quad = facing if facing in ("n", "s", "e", "w") else "s"
        return SHAPE_STAIRS[quad] if half != "top" \
            else SHAPE_STAIRS[quad].replace(":b", ":t")

    if name.endswith("_trapdoor"):
        op = props.get("open", "false") == "true"
        f = facing if facing in ("n", "s", "e", "w") else "n"
        hp = "t" if half == "top" else "b"
        return f"trapdoor:{f}:{'o' if op else 'c'}:{hp}"

    if name == "minecraft:bell":
        # 官方 blockstate 4 attachment × 4 facing 全携带：floor
        # n/s -> 梁沿 x、e/w -> 90°旋转梁沿 z；double_wall 反之
        # （e/w -> x、n/s -> z）；single_wall 携带锚墙向（官方
        # 语义：facing=锚墙）
        att = props.get("attachment", "floor")
        if att == "ceiling":
            return "bell:ceiling"
        if att == "double_wall":
            return "bell:wall2:x" if facing in ("e", "w") \
                else "bell:wall2:z"
        if att == "single_wall":
            return f"bell:wall1:{facing if facing in ('e', 'n', 's', 'w') else 'e'}"
        return "bell:floor:x" if facing in ("n", "s", "") \
            else "bell:floor:z"

    if name == "minecraft:composter":
        return SHAPE_COMPOSTER

    if name.endswith("_door"):
        op = props.get("open", "false") == "true"
        hinge = props.get("hinge", "left")
        f = facing if facing in ("n", "s", "e", "w") else "s"
        part = "l" if half == "lower" else "u"
        return f"door:{part}:{'o' if op else 'c'}:{f}:{hinge}"

    if name.endswith("chest") or name == "minecraft:barrel":
        # chest / trapped_chest / ender_chest 以 facing 定向（barrel 无
        # facing 属性时走默认 n）；type 属性定单箱/大箱左右半
        f = facing if facing in ("n", "s", "e", "w") else "n"
        if name == "minecraft:barrel":
            return SHAPE_BARREL
        typ = props.get("type", "single")
        if typ not in ("left", "right"):
            typ = "single"
        return f"chest:{f}:{typ}"

    if name in ("minecraft:torch", "minecraft:soul_torch",
                "minecraft:redstone_torch", "minecraft:wall_torch",
                "minecraft:soul_wall_torch", "minecraft:redstone_wall_torch"):
        if facing in ("n", "s", "e", "w"):
            return f"torch:{wall_panel_edge(facing)}"   # 墙上火把
        return SHAPE_TORCH_V

    if name == "minecraft:lantern" or name == "minecraft:soul_lantern":
        hang = props.get("hanging", "false") == "true"
        return "lantern:h" if hang else SHAPE_LANTERN

    if name in ("minecraft:furnace", "minecraft:blast_furnace",
                "minecraft:smoker", "minecraft:dispenser",
                "minecraft:vault", "minecraft:ominous_vault"):
        # 炉族/发射器/宝库：整格 + facing 前脸（lit 加亮面段）。
        # facing=up/down（竖直发射器）保 u/d，分面用竖直前脸；
        # vault 无 lit 段（模板 vault_state 全 inactive -> off 贴图）
        f = {"up": "u", "down": "d"}.get(facing, facing)
        f = f if f in ("n", "s", "e", "w", "u", "d") else "n"
        lit = ":lit" if props.get("lit") == "true" else ""
        return f"fc:{f}{lit}"

    if name.endswith("_log") \
            or name in ("minecraft:basalt", "minecraft:polished_basalt",
                        "minecraft:quartz_pillar"):
        # 轴心方块：几何整格，轴向供分面纹理（端面/侧面）。
        # _wood（木块）不进 col：原版六面同侧面纹理，无需分面。
        axis = props.get("axis", "y")
        return f"col:{axis if axis in ('x', 'y', 'z') else 'y'}"

    if name.endswith("_fence") or name.endswith("_fence_gate"):
        return SHAPE_FENCE_POST

    if name.endswith("_wall"):
        return SHAPE_WALL

    if name.endswith("_pressure_plate"):
        return SHAPE_PLATE

    if name.endswith("_carpet"):
        return SHAPE_CARPET

    if name.endswith("_bed"):
        # 分半床（bed:head|foot:<facing>：顶面纹理 rect 按朝向
        # 分枕头/毯区，床模型 rotZ 后枕头在 facing 反端）
        part = "head" if props.get("part", "foot") == "head" else "foot"
        f = facing if facing in ("n", "s", "e", "w") else "n"
        return f"bed:{part}:{f}"

    if name == "minecraft:chain":
        return f"bar:{props.get('axis', 'y')}"

    if name == "minecraft:end_rod":
        # 末地烛：底座+立杆按 facing 旋转（官方 end_rod.json）
        f = props.get("facing", "up")
        return "erod:" + {"up": "u", "down": "d", "north": "n",
                          "south": "s", "east": "e",
                          "west": "w"}.get(f, "u")

    if name == "minecraft:ladder":
        return panel_shape(wall_panel_edge(facing))

    if name == "minecraft:vine":
        # 藤蔓：官方 vine.json 贴边薄面片（0.8/16 厚盒近似，双面
        # 渲染）；多面组合态 + 连接（vine:<dir>[+<dir>...]，u=顶面）
        dirs = [ab for k, ab in (("north", "n"), ("south", "s"),
                                 ("east", "e"), ("west", "w"),
                                 ("up", "u"))
                if props.get(k) == "true"]
        return "vine:" + ("+".join(dirs) if dirs else "n")

    if name == "minecraft:tripwire_hook":
        # 绊线钩：官方 tripwire_hook[_attached].json 几何（贴边 =
        # facing 反侧；attached 带绊线伸出段，码尾 :a）
        code = "thook:" + wall_panel_edge(facing)
        if props.get("attached") == "true":
            code += ":a"
        return code

    if name.endswith("_wall_banner"):
        # 墙上横幅：banner 无独立板模型（entity 渲染），保持 panel 近似
        return panel_shape(wall_panel_edge(facing))

    if name.endswith("_wall_sign"):
        # 墙挂告示牌：官方板 24x12x2 近似（wsign 板面 rect 对位；
        # att = 贴边边，背板用侧纹近似）
        return "wsign:" + wall_panel_edge(facing)

    if name.endswith("_sign") or name.endswith("_banner"):
        return SHAPE_CROSS                           # 落地告示牌（简化）
    if name.endswith("_button"):
        return f"button:{wall_panel_edge(facing)}"

    if name == "minecraft:lever":
        if facing in ("n", "s", "e", "w"):
            return f"lever:{wall_panel_edge(facing)}"
        return f"lever:{facing or 'up'}"

    if name == "minecraft:redstone_wire":
        # 连接状态官方值 none/side/up -> 段码 -/s/u
        segs = []
        for k in ("north", "south", "east", "west"):
            v = props.get(k, "none")
            segs.append("u" if v == "up"
                        else ("s" if v == "side" else "-"))
        return "rswire:" + ":".join(segs)

    if name == "minecraft:repeater":
        f = facing if facing in ("n", "s", "e", "w") else "n"
        # delay 1..4：官方 repeater_Ntick.json 后火把柱 z=4+2*delay；
        # powered 仅火把纹理差异（亮/灭）
        try:
            delay = max(1, min(4, int(props.get("delay", "1") or 1)))
        except ValueError:
            delay = 1
        pw = ":1" if props.get("powered") == "true" else ":0"
        return f"repeater:{f}:{delay}{pw}"

    if name == "minecraft:comparator":
        f = facing if facing in ("n", "s", "e", "w") else "n"
        # mode：官方 comparator_subtract.json 附加输出火把光圈 6 薄片
        #（几何差异）；powered 亮/灭纹理
        mode = "t" if props.get("mode") == "subtract" else "c"
        pw = "1" if props.get("powered") == "true" else "0"
        return f"comparator:{f}:{mode}:{pw}"

    if name == "minecraft:sculk_sensor":
        # 无朝向属性（sculk_sensor_phase 只影响纹理）
        return "sculk"

    if name in ("minecraft:piston", "minecraft:sticky_piston"):
        # 活塞本体：sticky 后缀定平台纹理；extended 官方为缩进盒
        # （piston_extended.json：facing 端缩进 4px 露出杆室内壁）
        f = {"north": "n", "south": "s", "east": "e", "west": "w",
             "up": "u", "down": "d"}.get(props.get("facing", "north"),
                                         "n")
        code = f"pist:{f}"
        if name == "minecraft:sticky_piston":
            code += ":s"
        if props.get("extended") == "true":
            code += ":x"
        return code

    if name == "minecraft:redstone_lamp":
        return "lamp:1" if props.get("lit") == "true" else "lamp:0"

    if name == "minecraft:tripwire":
        # 绊线：官方 tripwire_n*.json 0.5px 细线（连接向 true -> 段码 1）
        segs = ["1" if props.get(k) == "true" else "-"
                for k in ("north", "south", "east", "west")]
        return "twire:" + ":".join(segs)

    if name == "minecraft:composter":
        # 官方 composter 模型：四壁全高杯状（同锅形，壁顶共面
        # 覆盖在 build_mesh 由同方块内裁剪处理）
        return SHAPE_CAULDRON

    if name == "minecraft:cauldron" or name.endswith("_cauldron"):
        # 炼药锅：官方 cup 形（四壁+底，与 composter 同形）
        return SHAPE_CAULDRON

    if name.endswith("_bars") or name == "minecraft:glass_pane":
        return SHAPE_PANE

    if name.endswith("_candle") or name == "minecraft:candle":
        # 蜡烛：主柱 2x6x2（官方 template_candle.json；多烛/点燃
        # 不影响几何，火焰为粒子渲染）
        return SHAPE_CANDLE

    if name == "minecraft:brewing_stand":
        # brewing:<b0><b1><b2>：三瓶位 has_bottle_N（26.2 官方
        # multipart：主模型 + bottleN/emptyN 条件叠加；N=0 东直片、
        # 1 西南斜片、2 西北斜片；1=满瓶左半图 0=空瓶右半图）
        bottles = "".join(
            "1" if props.get(f"has_bottle_{i}") == "true" else "0"
            for i in range(3))
        return f"brewing:{bottles}"

    if name.startswith("minecraft:potted_"):
        return SHAPE_FLOWERPOT

    if name in ("minecraft:dragon_head", "minecraft:dragon_wall_head"):
        # 龙首：dhead:<f>[:w]（wall 后缀走墙挂凸出变体）；站立
        # 变体 rotation 0..15（8=4 格步进，只有 0/4/8/12 正四向）
        if name == "minecraft:dragon_wall_head":
            f = facing if facing in ("n", "s", "e", "w") else "n"
            return f"dhead:{f}:w"
        rot = int(props.get("rotation", "8") or 0)
        f = {0: "s", 4: "w", 8: "n", 12: "e"}.get(rot & 12, "n") \
            if rot % 4 == 0 else "n"
        return f"dhead:{f}"

    if name == "minecraft:piston_head" or name == "minecraft:piston_head_short":
        f = props.get("facing", "north")
        f = {"north": "n", "south": "s", "east": "e", "west": "w",
             "up": "u", "down": "d"}.get(f, "n")
        # type=sticky：platform 外端（推板面）= 绿粘液面（jar 实证
        # piston_head_sticky.json platform=piston_top_sticky）
        return "pisth:" + f + (":s" if props.get("type") == "sticky"
                                else "")

    if name == "minecraft:lectern":
        return SHAPE_LECTERN

    return None


def shape_from_palette(name: str, props: dict | None) -> str | None:
    """jigsaw/模板 palette 条目 -> 形状码（组装层加载器专用）。

    一律转调 shape_from_props（props 缺失按空 dict）：无 Properties
    ≠ 无形状——火把/灯笼/地毯/花盆/蜡烛等无属性定型方块在
    shape_from_props 有内建默认（minecraft:torch -> torch:v、
    *_carpet -> carpet 等）。旧加载点 `if props else None` 会把
    这类方块错当整格（落地火把变整块）。返回 None = 整格，下游
    halfheight: fallback 照旧兜底。
    """
    return shape_from_props(name, props if isinstance(props, dict) else {})


# 镜像换向表：kind -> 尾段中朝向字母的下标（0 起；不在表 = 无朝向
# 语义不换向）。bar/col 为轴向、half/post/pane/wall/carpet 无朝向。
_MIRROR_KIND_FACE = {
    "torch": 0, "panel": 0, "wsign": 0, "button": 0, "lever": 0,
    "stairs": 0, "fc": 0, "dhead": 0, "erod": 0, "chest": 0,
    "trapdoor": 0, "repeater": 0, "comparator": 0, "pist": 0,
    "pisth": 0, "thook": 0,
    "bed": 1,       # bed:part:f
    "door": 2,      # door:part:op:f:hinge
}


def shape_mirror(shape: str | None, mirror: str) -> str | None:
    """形状码按放置镜像换向；NONE 或无朝向语义原样返回。

    StructureTemplate.transform 先镜像后旋转，调用方须在
    shape_rotation 之前调用本函数。FRONT_BACK（x=-x）下 e<->w、
    LEFT_RIGHT（z=-z）下 n<->s；u/d 及其它字母透传。
    """
    if not shape or mirror not in ("LEFT_RIGHT", "FRONT_BACK"):
        return shape
    kind, _, rest = shape.partition(":")
    if kind == "rswire" or kind == "twire":
        # 四向连接段镜像（段序 n,s,e,w）：FRONT_BACK（x=-x）
        # e<->w、LEFT_RIGHT（z=-z）n<->s
        segs = rest.split(":")
        if mirror == "FRONT_BACK":
            segs = [segs[0], segs[1], segs[3], segs[2]]
        else:
            segs = [segs[1], segs[0], segs[2], segs[3]]
        return kind + ":" + ":".join(segs)
    if kind == "vine":
        # 藤蔓多面段逐向换（段为 n/s/e/w/u 单字母）
        sw = {"e": "w", "w": "e"} if mirror == "FRONT_BACK" \
            else {"n": "s", "s": "n"}
        return "vine:" + "+".join(sw.get(d, d)
                                  for d in rest.split("+"))
    idx = _MIRROR_KIND_FACE.get(kind)
    if idx is None:
        return shape
    segs = rest.split(":")
    if idx >= len(segs):
        return shape
    f = segs[idx]
    if mirror == "FRONT_BACK":
        segs[idx] = {"e": "w", "w": "e"}.get(f, f)
    else:
        segs[idx] = {"n": "s", "s": "n"}.get(f, f)
    return kind + ":" + ":".join(segs)


# ---------------------------------------------------------------- 连通

def connect_kind(v) -> str | None:
    """体素值 -> 连通类别：'full' 整格 / 'post' / 'pane' / 'wall' /
    None 不连（半砖/楼梯/薄片类均不参与栅栏/面板连接）。"""
    if isinstance(v, str):
        return None if v.startswith("halfheight:") else "full"
    if not isinstance(v, tuple):
        return None
    shape = v[1]
    if not shape:
        return "full"
    kind = shape.partition(":")[0]
    if kind in ("post", "pane", "wall"):
        return kind
    if kind in ("col", "fc"):
        return "full"        # 轴心/炉族码几何整格，参与连通
    return None


def connect_arms(kind: str, nbs) -> tuple:
    """形状 kind（post/pane/wall）+ 四向邻居连通类别 -> 臂 AABB 元组。

    nbs 顺序 (n, s, e, w)（-z/+z/+x/-x）。臂沿连接方向触格边。
    官方尺寸（jar models/block/fence_side、template_wall_side）：
    - 栅栏臂 = 双横轨（各 2/16 截面，y 12..15 / 6..9）；
    - 墙臂 = 6/16 宽、高 14/16；
    - 面板臂（玻璃板/铁栏杆）= 中央 2/16 板。
    """
    if kind == "pane":
        a, b = 7 * _E, 9 * _E          # 中央 2/16 板（x/z 截面）
        tracks = ((0.0, 1.0),)         # 全高
    el    if kind == "wall":
        # 臂高矮两档（官方 template_wall_side / wall_side_tall）：
        # 邻居为整格实心（full）-> tall 满高 16/16；其余（墙/栅栏/
        # 面板/无）-> 矮 14/16（官方 wall 连接判定 isFull 同义）
        a, b = 5 * _E, 11 * _E         # 6/16 宽（x/z 截面）
        tall = 1.0
        short = 14 * _E
        arms = []
        for i, (x0, y0, z0, x1, y1, z1) in enumerate((
                (a, 0.0, 0.0, b, short, a),
                (a, 0.0, b, b, short, 1.0),
                (b, 0.0, a, 1.0, short, b),
                (0.0, 0.0, a, a, short, b))):
            if nbs[i] in (kind, "full"):
                y1 = tall if nbs[i] == "full" else short
                arms.append((x0, y0, z0, x1, y1, z1))
        return tuple(arms)
    else:                        # post：双轨 y 6..9 / 12..15
        a, b = 7 * _E, 9 * _E          # 2/16 截面（x/z）
        tracks = ((12 * _E, 15 * _E), (6 * _E, 9 * _E))
    arms = []
    for (y0, y1) in tracks:
        if nbs[0] in (kind, "full"):
            arms.append((a, y0, 0.0, b, y1, a))
        if nbs[1] in (kind, "full"):
            arms.append((a, y0, b, b, y1, 1.0))
        if nbs[2] in (kind, "full"):
            arms.append((b, y0, a, 1.0, y1, b))
        if nbs[3] in (kind, "full"):
            arms.append((0.0, y0, a, a, y1, b))
    return tuple(arms)


# ---------------------------------------------------------------- 旋转

# 朝向旋转映射（cubiomes 放置旋转 R：rot1 坐标映射 (x,z)->(-z,x)，
# 平移回正后：北缘→东缘，即 facing n→e）。
_ROT_FACE = (
    {"n": "n", "s": "s", "e": "e", "w": "w"},
    {"n": "e", "s": "w", "e": "s", "w": "n"},
    {"n": "s", "s": "n", "e": "w", "w": "e"},
    {"n": "w", "s": "e", "e": "n", "w": "s"},
)

# 面板类贴边方向 = facing 反侧（梯子/墙面告示牌/按钮/墙上火把：
# facing = 面板朝外的方向，背靠反侧墙）
_OPPOSITE = {"n": "s", "s": "n", "e": "w", "w": "e"}


def panel_shape(att: str) -> str:
    """贴边方向（已含 facing→贴边换算）-> panel 形状码。"""
    return f"panel:{att}"


def shape_rotation(shape: str | None, rot: int) -> str | None:
    """形状码按放置旋转 rot（0..3）换向；rot=0 或整格原样返回。

    铰链/开门状态不变（纯旋转无镜像，手性保持）；bar 轴向奇数
    旋转下 x/z 互换。
    """
    if not rot or not shape:
        return shape
    kind, _, rest = shape.partition(":")
    mp = _ROT_FACE[rot & 3]
    if kind == "door":
        part, op, f, hinge = rest.split(":")
        return f"door:{part}:{op}:{mp.get(f, f)}:{hinge}"
    if kind == "bar":
        if rest in ("x", "z") and rot & 1:
            return f"bar:{'z' if rest == 'x' else 'x'}"
        return shape
    if kind == "col":
        return shape                                     # 轴向无旋转语义
    if kind == "fc":
        f, _, lit = rest.partition(":")
        if f in ("u", "d"):
            return shape                                 # 竖直朝向不随 R 旋转
        return f"fc:{mp.get(f, f)}" + (f":{lit}" if lit else "")
    if kind in ("repeater", "comparator", "pist", "pisth"):
        f, _, tail = rest.partition(":")
        if f in ("u", "d"):
            return shape                     # 竖直朝向不随 R 旋转
        return f"{kind}:{mp.get(f, f)}" + (f":{tail}" if tail else "")
    if kind == "rswire" or kind == "twire":
        # 四向连接段轮换：原北连接在 rot1 下移至东段
        segs = rest.split(":")
        r = rot & 3
        if r == 1:
            segs = [segs[3], segs[2], segs[0], segs[1]]
        elif r == 2:
            segs = [segs[1], segs[0], segs[3], segs[2]]
        elif r == 3:
            segs = [segs[2], segs[3], segs[1], segs[0]]
        return kind + ":" + ":".join(segs)
    if kind == "vine":
        # 藤蔓多面段逐向映射（u 不随水平旋转）
        return "vine:" + "+".join(mp.get(d, d)
                                  for d in rest.split("+"))
    if kind in ("stairs", "chest", "trapdoor", "panel", "button",
                "lever", "torch", "dhead", "thook"):
        f, _, tail = rest.partition(":")
        return f"{kind}:{mp.get(f, f)}" + (f":{tail}" if tail else "")
    return shape                                     # half/post/pane 等不变


def wall_panel_edge(facing: str) -> str:
    """墙上挂件（梯子/告示牌/按钮/墙上火把）的贴边方向：facing 反侧。"""
    return _OPPOSITE.get(facing, "n")


# ---------------------------------------------------------------- 查询

@lru_cache(maxsize=512)
def shape_boxes(shape: str | None) -> tuple:
    """形状码 -> AABB 元组（本地方块坐标，y 向上）。None = 整格。

    返回值不可变（元组），可安全缓存；无法识别的形状码按整格兕底。
    """
    if not shape:
        return ((0.0, 0.0, 0.0, 1.0, 1.0, 1.0),)
    kind, _, rest = shape.partition(":")
    if kind in ("col", "fc"):
        return ((0.0, 0.0, 0.0, 1.0, 1.0, 1.0),)         # 整格（分面专用码）
    if kind == "half":
        vh, blank = rest.split(":")
        return _slab(vh, blank)
    if kind == "stairs":
        quad, half = rest.split(":")
        return _stairs(quad, half)
    if kind == "door":
        part, op, f, hinge = rest.split(":")
        return _door(part, op == "o", f, hinge)
    if kind == "trapdoor":
        f, op, hp = rest.split(":")
        return _trapdoor(f, op == "o", hp)
    if kind == "bell":
        return _bell(rest if rest else "floor:x")
    if kind == "composter":
        return _composter()
    if kind == "post":
        # 官方 fence_post：4/16 细柱（x/z 6..10）满高
        return ((6 * _E, 0.0, 6 * _E, 10 * _E, 1.0, 10 * _E),)
    if kind == "wall":
        # 官方 template_wall_post：8/16 柱（x/z 4..12）满高
        return ((4 * _E, 0.0, 4 * _E, 12 * _E, 1.0, 12 * _E),)
    if kind == "bar":
        return _bar(rest)
    if kind == "pane":
        return ((7 * _E, 0.0, 7 * _E, 9 * _E, 1.0, 9 * _E),)
    if kind == "torch":
        if rest == "v":
            return _torch("stick", "up")
        if rest == "h":
            return ((5 * _E, 0.0, 5 * _E, 11 * _E, 6 * _E, 11 * _E),)
        return _torch("wall", rest)
    if kind == "chest":
        # rest = "<f>[:<type>]"：两段旧码兼容；type 取次段（首段 facing）
        parts = rest.split(":")
        f = parts[0] if parts and parts[0] in ("n", "s", "e", "w") else "n"
        typ = parts[1] if len(parts) > 1 and parts[1] in (
            "left", "right") else "single"
        return _chest(typ, f)
    if kind == "barrel":
        return _barrel()
    if kind == "layer":
        return ((0.0, 0.0, 0.0, 1.0, 13 * _E, 1.0),)
    if kind == "plate":
        return ((0.0, 0.0, 0.0, 1.0, 2 * _E, 1.0),)
    if kind == "carpet":
        return ((0.0, 0.0, 0.0, 1.0, _E, 1.0),)
    if kind == "cauldron":
        return _cauldron()
    if kind == "plant":
        # 农作物/花草：对角 X 非实体（build_mesh 专用 quad 路径），
        # 空 AABB = 不参与面剔除/邻居遮挡
        return ()
    if kind == "cross":
        # 落地告示牌：十字交叉板近似（AABB 无法表达斜板）
        return ((7 * _E, 0.0, 0.0, 9 * _E, 0.8, 1.0),
                (0.0, 0.0, 7 * _E, 1.0, 0.8, 9 * _E))
    if kind == "panel":
        t = 2 * _E
        if rest == "n":
            return ((0.0, 0.0, 0.0, 1.0, 1.0, t),)
        if rest == "s":
            return ((0.0, 0.0, 1 - t, 1.0, 1.0, 1.0),)
        if rest == "e":
            return ((1 - t, 0.0, 0.0, 1.0, 1.0, 1.0),)
        return ((0.0, 0.0, 0.0, t, 1.0, 1.0),)       # w
    if kind == "button":
        t = _E
        if rest == "n":
            return ((3 * _E, 5 * _E, 0.0, 13 * _E, 11 * _E, t),)
        if rest == "s":
            return ((3 * _E, 5 * _E, 1 - t, 13 * _E, 11 * _E, 1.0),)
        if rest == "e":
            return ((1 - t, 5 * _E, 3 * _E, 1.0, 11 * _E, 13 * _E),)
        return ((0.0, 5 * _E, 3 * _E, t, 11 * _E, 13 * _E),)   # w
    if kind == "lever":
        return _lever(rest)
    if kind == "thook":
        return _tripwire_hook(rest)
    if kind == "twire":
        return _tripwire(rest)
    if kind == "vine":
        return _vine(rest)
    if kind == "brewing":
        return _brewing()
    if kind == "flowerpot":
        return _flowerpot()
    if kind == "candle":
        return _candle()
    if kind == "lantern":
        return _lantern(rest == "h")
    if kind == "erod":
        return _end_rod(rest)
    if kind == "dhead":
        f, _, w = rest.partition(":")
        return _dragon_head(w == "w", f if f in ("n", "s", "e", "w") else "n")
    if kind == "bed":
        # 分半床（26.2 template_bed_foot/head.json）：床板 y3..9 悬空
        # + 两腿 y0..3（head 在床头端 z0..3 两角、foot 在床尾端
        # z13..16 两角；facing=n 基准=床头朝北，_rot_y 转 facing）。
        # 顶面 rect 分枕/毯区照旧（_decor_face_mat bed 分支）。
        part, _, f = rest.partition(":")
        E3 = 3 * _E
        if part == "head":
            legs = ((0.0, 0.0, 0.0, E3, E3, E3),
                    (1.0 - E3, 0.0, 0.0, 1.0, E3, E3))
        else:
            legs = ((0.0, 0.0, 1.0 - E3, E3, E3, 1.0),
                    (1.0 - E3, 0.0, 1.0 - E3, 1.0, E3, 1.0))
        return tuple(_rot_y(b, f) for b in
                     ((0.0, E3, 0.0, 1.0, 9 * _E, 1.0),) + legs)
    if kind == "wsign":
        return _wall_sign(rest)
    if kind == "pisth":
        # rest 可能带 sticky 后缀（pisth:<f>[:s]），几何只认朝向段
        return _piston_head(rest.partition(":")[0])
    if kind == "lectern":
        return _lectern()
    if kind == "rswire":
        return _redstone_wire(rest)
    if kind == "repeater":
        return _diode(rest, False)
    if kind == "comparator":
        return _diode(rest, True)
    if kind == "sculk":
        return _sculk_sensor()
    if kind == "pist":
        parts = rest.split(":")
        if "x" in parts[1:]:                     # extended 缩进盒
            return _piston_base(parts[0])
        return ((0.0, 0.0, 0.0, 1.0, 1.0, 1.0),)  # 未伸出整格
    if kind == "lamp":
        return ((0.0, 0.0, 0.0, 1.0, 1.0, 1.0),)   # 整格（分面专用码）
    return ((0.0, 0.0, 0.0, 1.0, 1.0, 1.0),)         # 未知码兜底整格


# ------------------------------------------------------------ 红石族

_DUST_T = 0.25 / 16.0   # 官方红石尘面片 y=0.25px（1/64 格）


def _rot_y(box: tuple, f: str) -> tuple:
    """facing=n 基准 AABB 按 blockstate y 旋转（e=90/s=180/w=270）。

    官方 JSON 原始几何 = facing north；blockstate y=90: (x,z)->(1-z,x)、
    y=180: (x,z)->(1-x,1-z)、y=270: (x,z)->(z,1-x)（与 _ROT_FACE
    rot1 n->e 同向）。"""
    if f == "n":
        return box
    x0, y0, z0, x1, y1, z1 = box
    if f == "e":
        return (1 - z1, y0, x0, 1 - z0, y1, x1)
    if f == "s":
        return (1 - x1, y0, 1 - z1, 1 - x0, y1, 1 - z0)
    return (z0, y0, 1 - x1, z1, y1, 1 - x0)          # w


def _redstone_wire(rest: str) -> tuple:
    """红石线（1.20.1 multipart redstone_dust_* 几何）。

    - side 连接：边缘到中心的半格长臂（官方 redstone_dust_side
      [0,0.25,0]-[16,0.25,8]），线宽取官方纹理线带 4px（6..10）；
    - up 连接：该侧贴边全高竖片（官方 redstone_dust_up 零厚面
      z=0.25px -> 1/64 厚 AABB 内缩）；
    - 四向无连接：中心 4x4 孤点板（官方 redstone_dust_dot 图案
      中心区）。纹理 redstone wire.png = 官方 1.21.11 line0/line1
      灰度纹理按 egb COLORS[power] 染色合成（N/S 臂 line0 原样 +
      E/W 臂 line1 y270 旋转转置），世界平铺 UV 命中线带；全空
      态显示中心线段交叉而非 dot 斑（当前消费方全为连接态）。"""
    n, s, e, w = rest.split(":")
    a, b = 6 * _E, 10 * _E
    m = 8 * _E                       # 半格臂长
    t = _DUST_T
    boxes = []
    if (n, s, e, w) == ("-", "-", "-", "-"):
        boxes.append((a, 0.0, a, b, t, b))
    else:
        if n != "-":
            boxes.append((a, 0.0, 0.0, b, t, m))
        if s != "-":
            boxes.append((a, 0.0, 1.0 - m, b, t, 1.0))
        if e != "-":
            boxes.append((m, 0.0, a, 1.0, t, b))
        if w != "-":
            boxes.append((0.0, 0.0, a, 1.0 - m, t, b))
    if n == "u":
        boxes.append((a, 0.0, t, b, 1.0, 2 * t))
    if s == "u":
        boxes.append((a, 0.0, 1.0 - 2 * t, b, 1.0, 1.0 - t))
    if e == "u":
        boxes.append((1.0 - 2 * t, 0.0, a, 1.0 - t, 1.0, b))
    if w == "u":
        boxes.append((t, 0.0, a, 2 * t, 1.0, b))
    return tuple(boxes)


def _diode(rest: str, comparator: bool) -> tuple:
    """中继器/比较器（官方 repeater_Ntick / comparator[_subtract].json）。

    平滑石底板 2/16 + 火把柱；原始朝向 facing=n（输出朝北）。
    rest = "<f>:<delay>[:<pw>]"（repeater，delay 1..4 后火把柱
    z=4+2*delay，与官方 repeater_1tick..4tick 逐档一致）或
    "<f>:<c|t>:<pw>"（comparator，t=减法：附加输出火把光圈 6 薄片
    ——官方 comparator_subtract.json 附加元素，3x3 片环绕火把，
    可见面贴火把外缘，薄片厚 1/64，非可见面由 _decor_face_mat
    SKIP）。"""
    parts = rest.split(":")
    f = parts[0] if parts and parts[0] in ("n", "s", "e", "w") else "n"
    boxes = [(0.0, 0.0, 0.0, 1.0, 2 * _E, 1.0)]
    if comparator:
        boxes.append((4 * _E, 2 * _E, 11 * _E, 6 * _E, 7 * _E, 13 * _E))
        boxes.append((10 * _E, 2 * _E, 11 * _E, 12 * _E, 7 * _E, 13 * _E))
        boxes.append((7 * _E, 2 * _E, 2 * _E, 9 * _E, 5 * _E, 4 * _E))
        if len(parts) > 1 and parts[1] == "t":
            # 减法光圈 6 薄片（facing=n 基准）：底 y2.5、顶 y5.5、
            # 北 z1.5、南 z4.5、西 x6.5、东 x9.5（可见面 = 靠火把侧）
            t = _DUST_T
            boxes.append((6.5 * _E, 2.5 * _E - t, 1.5 * _E,
                          9.5 * _E, 2.5 * _E, 4.5 * _E))
            boxes.append((6.5 * _E, 5.5 * _E, 1.5 * _E,
                          9.5 * _E, 5.5 * _E + t, 4.5 * _E))
            boxes.append((6.5 * _E, 2.5 * _E, 1.5 * _E - t,
                          9.5 * _E, 5.5 * _E, 1.5 * _E))
            boxes.append((6.5 * _E, 2.5 * _E, 4.5 * _E,
                          9.5 * _E, 5.5 * _E, 4.5 * _E + t))
            boxes.append((6.5 * _E - t, 2.5 * _E, 1.5 * _E,
                          6.5 * _E, 5.5 * _E, 4.5 * _E))
            boxes.append((9.5 * _E, 2.5 * _E, 1.5 * _E,
                          9.5 * _E + t, 5.5 * _E, 4.5 * _E))
    else:
        try:
            delay = int(parts[1]) if len(parts) > 1 else 1
        except ValueError:
            delay = 1
        zt = (4 + 2 * max(1, min(4, delay))) * _E
        boxes.append((7 * _E, 2 * _E, zt, 9 * _E, 7 * _E, zt + 2 * _E))
        boxes.append((7 * _E, 2 * _E, 2 * _E, 9 * _E, 7 * _E, 4 * _E))
    return tuple(_rot_y(bx, f) for bx in boxes)


def _sculk_sensor() -> tuple:
    """幽匿感测体（sculk_sensor.json）：8/16 底座 + 四角触须。

    官方触须为 45° 斜片（[-1,8,3]-[7,16,3] 绕角旋转），AABB 以
    直立薄板近似：位于官方片所在 z=3/16、13/16 平面，各平面东西
    两片 x 0..8/16、8/16..1。"""
    t = _DUST_T
    return (
        (0.0, 0.0, 0.0, 1.0, 8 * _E, 1.0),
        (0.0, 8 * _E, 3 * _E, 8 * _E, 1.0, 3 * _E + t),
        (8 * _E, 8 * _E, 3 * _E, 1.0, 1.0, 3 * _E + t),
        (0.0, 8 * _E, 13 * _E - t, 8 * _E, 1.0, 13 * _E),
        (8 * _E, 8 * _E, 13 * _E - t, 1.0, 1.0, 13 * _E),
    )


def _piston_base(f: str) -> tuple:
    """extended 活塞本体（piston_extended.json，facing=n 基准：
    facing 端缩进 4px，露出杆室内壁与活塞头轴咬合；背面贴格界）。
    u/d 沿 y 缩进。"""
    t = 4 * _E
    if f == "u":
        return ((0.0, 0.0, 0.0, 1.0, 1.0 - t, 1.0),)
    if f == "d":
        return ((0.0, t, 0.0, 1.0, 1.0, 1.0),)
    # facing=n：北面（z=0 端）缩进
    return (_rot_y((0.0, 0.0, t, 1.0, 1.0, 1.0), f),)


# ------------------------------------------------------------ 机关件


def _lever(rest: str) -> tuple:
    """拉杆（jar lever.json：圆石底座 (5,0,4)-(11,3,12) + 2x10x2
    杆未触发绕 x -45° 斜置，AABB 以 4 段 45° 阶梯盒逼近斜杆）。

    码语义：up = floor（原始几何）/ down = ceiling（x180）/
    其余 = 墙贴（贴边 edge：官方 face=wall 家族 x90 旋转，f =
    edge 反侧过 _rot_y）。"""
    def _x90(b):
        # (x,y,z)->(x,z,16-y)：AABB (x0,y0,z0,x1,y1,z1) 变换
        return (b[0], b[2], 1.0 - b[4], b[3], b[5], 1.0 - b[1])

    def _x180(b):
        # (x,y,z)->(x,16-y,16-z)
        return (b[0], 1.0 - b[4], 1.0 - b[5], b[3], 1.0 - b[1],
                1.0 - b[2])

    base = (5 * _E, 0.0, 4 * _E, 11 * _E, 3 * _E, 12 * _E)
    # 杆 45° 阶梯：底段贴底座（y 1..3、z 7..9）-> 顶段（y 7..9、
    # z 1..3），北斜（floor/未触发朝 facing 倒）
    segs = tuple(
        (7 * _E, (1 + 2 * i) * _E, (7 - 2 * i) * _E,
         9 * _E, (3 + 2 * i) * _E, (9 - 2 * i) * _E)
        for i in range(4))
    if rest == "up":
        return (base,) + segs
    if rest == "down":
        return (_x180(base),) + tuple(_x180(b) for b in segs)
    f = _OPPOSITE.get(rest, "s")       # 贴边 edge -> facing 反侧
    return tuple(_rot_y(_x90(b), f) for b in (base,) + segs)


def _tripwire_hook(rest: str) -> tuple:
    """绊线钩（jar tripwire_hook[_attached].json；facing=n 基准 =
    背板贴 z=16 南墙，码用贴边 edge，f = edge 反侧过 _rot_y）。

    attached 版元素：背板 (6,1,14)-(10,9,16) + 横臂
    (7.4,5.2,10)-(8.8,6.8,14)（#wood）、钩件 (6.2,4.2,6.7)-
    (9.8,5,10.3)（#hook，官方 -22.5° 斜置以包围盒近似）+ 绊线
    伸出段 (7.75,1.5,0)-(8.25,1.5,6.7)（#tripwire，官方 -22.5°
    斜置，包围盒 y 0..2.6）。未 attached 版（tripwire_hook.json）
    横臂/钩件 ±45° 斜置，包围盒分别近似。"""
    edge, _, att = rest.partition(":")
    f = _OPPOSITE.get(edge, "s")
    back = (6 * _E, 1 * _E, 14 * _E, 10 * _E, 9 * _E, 1.0)
    if att == "a":
        boxes = (
            back,
            (7.4 * _E, 5.2 * _E, 10 * _E, 8.8 * _E, 6.8 * _E, 14 * _E),
            (6.2 * _E, 4.2 * _E, 6.7 * _E, 9.8 * _E, 5 * _E, 10.3 * _E),
            (7.75 * _E, 0.0, 0.0, 8.25 * _E, 2.6 * _E, 6.7 * _E),
        )
    else:
        # ±45° 斜件包围盒（横臂 +45° 绕 (8,6,14)、钩件 -45° 绕
        # (8,6,5.2)，逐顶点极值投影算得）
        boxes = (
            back,
            (7.4 * _E, 5.4 * _E, 10.6 * _E, 8.8 * _E, 9.0 * _E,
             14.1 * _E),
            (6.2 * _E, 6.35 * _E, 8.1 * _E, 9.8 * _E, 9.5 * _E,
             11.2 * _E),
        )
    return tuple(_rot_y(b, f) for b in boxes)


def _tripwire(rest: str) -> tuple:
    """绊线（jar tripwire_n*.json：0.5px 宽细线面片 y=1.5，连接向
    各画半格段；AABB 以 1/64 厚薄盒近似零厚面片）。段序 n:s:e:w
    同 rswire，1=连接 / - = 无。"""
    t = _DUST_T / 2.0
    n, s, e, w = rest.split(":")
    a, b = 7.75 * _E, 8.25 * _E
    y0, y1 = 1.5 * _E - t, 1.5 * _E + t
    boxes = []
    if n == "1":
        boxes.append((a, y0, 0.0, b, y1, 0.5))
    if s == "1":
        boxes.append((a, y0, 0.5, b, y1, 1.0))
    if w == "1":
        boxes.append((0.0, y0, a, 0.5, y1, b))
    if e == "1":
        boxes.append((0.5, y0, a, 1.0, y1, b))
    if not boxes:                        # 孤点（官方无此态，兜底）
        boxes.append((a, y0, a, b, y1, b))
    return tuple(boxes)


def _vine(rest: str) -> tuple:
    """藤蔓（jar vine.json：单面片 z=0.8/16 贴北墙，north/south
    双面渲染；blockstate 逐面 y 旋转，AABB 以 0.8/16 厚薄盒近似）。
    vine:<dir>[+<dir>]，n = 原始（贴北缘），u = 顶面片（x270）。"""
    t = 0.8 * _E
    boxes = []
    for d in rest.split("+"):
        if d == "u":
            boxes.append((0.0, 1.0 - t, 0.0, 1.0, 1.0, 1.0))
            continue
        boxes.append(_rot_y((0.0, 0.0, 0.0, 1.0, 1.0, t), d))
    return tuple(boxes)
