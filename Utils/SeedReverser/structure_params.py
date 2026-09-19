# -*- coding: utf-8 -*-
"""SeedReverser 的结构参数表（salt / regionSize / chunkRange / 首次版本 / 散布 / lifting 模数）。

数据来源：cubiomes finders.c 的 getStructureConfig()（已按 master 分支逐条核对，
salt / regionSize / chunkRange 三项与 s_xxx 结构常量完全一致）。

字段说明（与 cubiomes StructureConfig 对应）：
    salt         结构盐：regionSeed = structureSeed + regX*341873128712
                 + regZ*132897987541 + salt
    region_size  区域边长（区块单位）：offX ∈ [0, region_size)
    chunk_range  区块偏移上界（Java spacing - separation）：
                  线性散布结构 offX = nextInt(chunkRange)
    scatter      linear（线性，2 次 nextInt）/ triangle（三角，4 次取平均）
    min_ver      该结构可用的最低版本（主版本号 int，如 121 = 1.21）
    lift_mod     可参与低位 lifting 预筛的最大 2 幂模数（chunk_range 的
                 2 幂因子）：r=24→8（8|24），r=20/12→4，r=26/22→2
                 该模数 m 下「val mod m」精确等于「(state>>17) mod m」，
                 只取决于结构种低 (17+log2 m) 位
                 0 = 不可预筛（三角散布 / 2 幂 r / 概率结构）

说明：
    - SeedReverser 只支持 1.18~1.21+ 参数线（用户明确指示）。
    - mansion 的 r=60 虽为 4 的倍数，但三角散布两次 nextInt 相加后 >>1，
      低位进位依赖高位（r 非时 2 幂时两次 %60 相加可能进位），破坏低位
      同余，故 lift_mod=0。
    - ancient_city 的 r=16 是 2 的幂：next(31) 取的是状态高 31 位，偏移
      结果由高位决定，与低位枚举无关，故 lift_mod=0。
    - monument 的 r=27 为奇数且三角散布，lift_mod=0。

注：mansion（林地府邸）参数保留供 MapPreviewer 地图标注使用；
SeedReverser 逆推 UI 已下架该结构（锚点定位误差过大，无计算价值），
_VERSION_STRUCTS 各版本均不再收录。
"""

# 版本键（与 UI versionCombo 对应；按新到旧排序）
VERSION_KEYS = ("26.2", "1.21.11", "1.21")

# 版本键 → 主版本号（用于结构可用性过滤）
_VERSION_NUM = {"1.21": 121, "1.21.11": 1211, "26.2": 262}

# 每个版本可用的结构键（按 UI 易找程度排序）
# 26.2：结构与 1.21 完全一致（数据包 101.2 仅新增硫磺洞穴群系）；
# 1.21.11：1.21.x 线修正版，结构集与 1.21 一致
_STRUCTS_121 = ("shipwreck", "desert_pyramid", "igloo", "swamp_hut",
                "jungle_temple", "village", "ocean_ruin", "monument",
                "trial_chambers", "ruined_portal")
_VERSION_STRUCTS = {
    "26.2": _STRUCTS_121,
    "1.21.11": _STRUCTS_121,
    "1.21": _STRUCTS_121,
}

# 结构显示名（UI 用）
STRUCT_NAMES = {
    "shipwreck": "沉船",
    "desert_pyramid": "沙漠神殿",
    "igloo": "雪屋",
    "swamp_hut": "女巫小屋",
    "jungle_temple": "丛林神庙",
    "village": "村庄",
    "pillager_outpost": "掠夺者前哨站",
    "ocean_ruin": "海底废墟",
    "monument": "海底神殿",
    "mansion": "林地府邸",
    "ancient_city": "远古城市",
    "trail_ruins": "古迹废墟",
    "trial_chambers": "试炼密室",
    "ruined_portal": "废弃传送门",
    # MapPreviewer 扩展结构（不可逆推，SeedReverser UI 不展示：
    # _VERSION_STRUCTS 不含这些键；参数表仅供地图枚举使用）
    "stronghold": "要塞",
    "buried_treasure": "埋藏的宝藏",
    "mineshaft": "废弃矿井",
    "desert_well": "沙漠水井",
    # MapPreviewer 下界/末地扩展结构（中文 Minecraft Wiki 标准译名）
    "nether_fortress": "下界要塞",
    "bastion_remnant": "堡垒遗迹",
    "end_city": "末地城",
}

# 结构参数：(salt, region_size, chunk_range, scatter, min_ver, lift_mod)
# lift_mod = chunk_range 的最大 2 幂因子（8|24 → r=24 的结构为 8）
STRUCT_PARAMS = {
    "shipwreck":        (165745295, 24, 20, "linear",   116, 4),
    "desert_pyramid":   (14357617,  32, 24, "linear",   103, 8),
    "igloo":            (14357618,  32, 24, "linear",   109, 8),
    "swamp_hut":        (14357620,  32, 24, "linear",   104, 8),
    "jungle_temple":    (14357619,  32, 24, "linear",   103, 8),
    "village":          (10387312,  34, 26, "linear",   112, 2),
    "pillager_outpost": (165745296, 32, 24, "linear",   114, 0),  # 1/5 概率，不可 lift
    "ocean_ruin":       (14357621,  20, 12, "linear",   113, 4),
    "monument":         (10387313,  32, 27, "triangle", 108, 0),  # 奇数 r 不可 lift
    "mansion":          (10387319,  80, 60, "triangle", 111, 0),  # 三角散布不可 lift
    "ancient_city":     (20083232,  24, 16, "linear",   119, 0),  # 2 幂 r 不可 lift
    "trail_ruins":      (83469867,  34, 26, "linear",   120, 2),
    "trial_chambers":   (94251327,  34, 22, "linear",   121, 2),
    # 废弃传送门（finders.c Ruined_Portal：salt/region/chunk 已对拍验证）。
    # r=25 为奇数，「off mod 2」不等于「状态低位 mod 2」（2^17 全枚举出
    # 98303 反例且预筛会漏真种子），故 lift_mod=0，只能作验证观测。
    "ruined_portal":    (34222645, 40, 25, "linear",   116, 0),
    # ---- MapPreviewer 扩展结构（非区域制 / 特殊算法，不做逆推） ----
    # 要塞：非区域制，环形分布由 initFirstStronghold/nextStronghold 决定；
    #   salt 字段无意义占 0。1.9+ 起 y=0 校验（finders.c isStrongholdBiome）。
    "stronghold":       (0,          0,  0,  "linear",   109, 0),
    # 埋藏的宝藏：s_treasure = {10387320, 1, 1}，锚点 (cx*16+9, cz*16+9)，
    # 1% 概率用 nextFloat（非区域偏移），概率结构不可 lift。
    "buried_treasure":  (10387320,   1,  1,  "linear",   113, 0),
    # 废弃矿井：getMineshafts 专用算法（a=nextLong, b=nextLong 后
    # aix^bz 双乘散列 + nextDouble<0.004），无 salt/region 概念。
    "mineshaft":        (0,          0,  0,  "linear",   103, 0),
    # 沙漠水井：s_desert_well = {40002, 1, 1, rarity=0.001}，基于
    # getPopulationSeed + xNextIntJ(16) 偏移，概率结构不可 lift。
    "desert_well":      (40002,      1,  1,  "linear",   101, 0),
    # ---- MapPreviewer 下界/末地扩展结构（finders.c 已核对）----
    # 下界要塞：s_fortress = {30084232, 27, 23}，1.16+，线性散布，
    #   群系校验覆盖下界全部 5 群系（isViableStructurePos L1457-1468）。
    "nether_fortress":  (30084232, 27, 23, "linear",   116, 0),
    # 堡垒遗迹：s_bastion = {30084232, 27, 23}，1.16+，线性散布，
    #   额外 2/5 概率门（chunkGenerateRnd nextInt(5)>=2）与群系白名单
    #   （basalt_deltas 不生成），均不可 lift（finders.c L1471-1486）。
    "bastion_remnant":  (30084232, 27, 23, "linear",   116, 0),
    # 末地城：s_end_city = {10387313, 20, 9}，1.9+，triangle 散布，
    #   pos² >= 1008² 距离拒绝 + 群系须为 end_midlands/highlands。
    "end_city":         (10387313, 20,  9, "triangle", 109, 0),
}


# 结构默认站位容差（区块，0~2；UI 行内下拉的初始选择，可逐条修改）。
# 依据锚点可辨认程度（见 tool_SeedReverser._ANCHOR_HINTS）：
#     0 = 小型单模板结构：锚点为模板一角，站位与锚点偏差通常 <1 区块，
#         容差 0 保留全部信息量（mod8 预筛最强）；
    # 2 = 大型 / 无中心 / 深埋结构：站位误差常超 1 区块（村庄无全局
    #     中心、神殿深埋），默认 2 提高生存可用性（试炼密室 mod2 在
    #     tol≥1 时层 1 失效，tol=0 又几乎必然因站位偏差失配——默认 2
    #     是唯一自洽选择）。
DEFAULT_TOLERANCES = {
    "shipwreck": 0,
    "desert_pyramid": 0,
    "igloo": 0,
    "swamp_hut": 0,
    "jungle_temple": 0,
    "ocean_ruin": 0,
    "pillager_outpost": 0,
    "ruined_portal": 0,
    "village": 2,
    "trial_chambers": 2,
    "trail_ruins": 2,
    "ancient_city": 2,
    "monument": 2,
    # MapPreviewer 扩展结构（不进 SeedReverser UI，取值仅为完整性）：
    # 要塞内部房间入口即定位中心，偏差通常 <1 区块；宝藏锚点 (9,9)
    # 与箱子偏移固定；矿井以入口走廊中心为观测点，取 1；水井锚点为
    # 中心块，偏差小。
    "stronghold": 1,
    "buried_treasure": 0,
    "mineshaft": 1,
    "desert_well": 0,
    # 下界/末地扩展结构（体量大、无中心，取 2 提高生存可用性）
    "nether_fortress": 2,
    "bastion_remnant": 2,
    "end_city": 2,
}


# 结构键 → 所在维度（"overworld"/"nether"/"end"）。
# MapPreviewer 维度分组与标注路由用：未列出的键一律视为主世界。
# （下界要塞/堡垒遗迹与主世界结构无键冲突，末地城同理。）
STRUCT_DIMENSION = {
    "nether_fortress": "nether",
    "bastion_remnant": "nether",
    "end_city": "end",
}

# 维度键 → 显示名（worldCombo 与选择窗分组标题用）
DIMENSION_NAMES = {
    "overworld": "主世界",
    "nether": "下界",
    "end": "末地",
}


def get_params(struct_key: str, version_key: str) -> dict:
    """返回某结构在指定版本下的参数 dict。

    Args:
        struct_key: 结构键（STRUCT_PARAMS 的键）。
        version_key: 版本键（"26.2"/"1.21.11"/"1.21"）。

    Returns:
        dict：key / name / salt / region_size / chunk_range / scatter /
              min_ver / lift_mod / version。
    """
    salt, region_size, chunk_range, scatter, min_ver, lift_mod = STRUCT_PARAMS[struct_key]
    return {
        "key": struct_key,
        "name": STRUCT_NAMES.get(struct_key, struct_key),
        "salt": salt,
        "region_size": region_size,
        "chunk_range": chunk_range,
        "scatter": scatter,
        "min_ver": min_ver,
        "lift_mod": lift_mod,
        "version": version_key,
    }


def available_structures(version_key: str) -> tuple[str, ...]:
    """返回指定版本下可用的结构键元组（按易找顺序，含 min_ver 过滤）。

    Args:
        version_key: 版本键。

    Returns:
        结构键元组。
    """
    vnum = _VERSION_NUM.get(version_key, 121)
    return tuple(k for k in _VERSION_STRUCTS.get(version_key, ())
                 if STRUCT_PARAMS[k][4] <= vnum)


def get_default_tolerance(struct_key: str) -> int:
    """结构键 → 默认站位容差（区块）。未知键兜底 0。"""
    return DEFAULT_TOLERANCES.get(struct_key, 0)


def is_reversible(struct_key: str) -> bool:
    """结构键 → 是否可参与低位预筛逆推（linear 且 lift_mod >= 2）。

    与求解器 _lift_split 的分组语义严格一致：False = 仅验证观测
    （层 3 过滤假阳性，不参与层 1/2 预筛与进度条统计）。
    """
    entry = STRUCT_PARAMS.get(struct_key)
    return bool(entry) and entry[3] == "linear" and entry[5] >= 2


def struct_key_to_name(struct_key: str) -> str:
    """结构键 → 中文名。"""
    return STRUCT_NAMES.get(struct_key, struct_key)
