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
"""

# 版本键（与 UI versionCombo 对应）
VERSION_KEYS = ("1.21", "1.20", "1.19", "1.18")

# 版本键 → 主版本号（用于结构可用性过滤）
_VERSION_NUM = {"1.18": 118, "1.19": 119, "1.20": 120, "1.21": 121}

# 每个版本可用的结构键（按 UI 易找程度排序）
_VERSION_STRUCTS = {
    "1.21": ("shipwreck", "desert_pyramid", "igloo", "swamp_hut", "jungle_temple",
             "village", "ocean_ruin", "monument", "mansion", "trial_chambers"),
    "1.20": ("shipwreck", "desert_pyramid", "igloo", "swamp_hut", "jungle_temple",
             "village", "ocean_ruin", "monument", "mansion", "trail_ruins"),
    "1.19": ("shipwreck", "desert_pyramid", "igloo", "swamp_hut", "jungle_temple",
             "village", "ocean_ruin", "monument", "mansion", "ancient_city"),
    "1.18": ("shipwreck", "desert_pyramid", "igloo", "swamp_hut", "jungle_temple",
             "village", "ocean_ruin", "monument", "mansion"),
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
}


# 结构默认站位容差（区块，0~2；UI 行内下拉的初始选择，可逐条修改）。
# 依据锚点可辨认程度（见 tool_SeedReverser._ANCHOR_HINTS）：
#     0 = 小型单模板结构：锚点为模板一角，站位与锚点偏差通常 <1 区块，
#         容差 0 保留全部信息量（mod8 预筛最强）；
#     2 = 大型 / 无中心 / 深埋结构：站位误差常超 1 区块（村庄无全局
#         中心、神殿深埋、府邸体量极大），默认 2 提高生存可用性
#         （试炼密室 mod2 在 tol≥1 时层 1 失效，tol=0 又几乎必然
#         因站位偏差失配——默认 2 是唯一自洽选择）。
DEFAULT_TOLERANCES = {
    "shipwreck": 0,
    "desert_pyramid": 0,
    "igloo": 0,
    "swamp_hut": 0,
    "jungle_temple": 0,
    "ocean_ruin": 0,
    "pillager_outpost": 0,
    "village": 2,
    "trial_chambers": 2,
    "trail_ruins": 2,
    "ancient_city": 2,
    "monument": 2,
    "mansion": 2,
}


def get_params(struct_key: str, version_key: str) -> dict:
    """返回某结构在指定版本下的参数 dict。

    Args:
        struct_key: 结构键（STRUCT_PARAMS 的键）。
        version_key: 版本键（"1.18"/"1.19"/"1.20"/"1.21"）。

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


def struct_key_to_name(struct_key: str) -> str:
    """结构键 → 中文名。"""
    return STRUCT_NAMES.get(struct_key, struct_key)
