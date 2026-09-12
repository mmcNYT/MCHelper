# -*- coding: utf-8 -*-
"""Java Random 的精确复刻（Minecraft 结构生成使用的 LCG）。

本模块复刻 java.util.Random 与 cubiomes 中与结构生成相关的接口。

两条语义线（与 cubiomes 源码严格对应，勿混用）：

1. 结构区块定位（getFeaturePos / getLargeStructurePos，finders.h 内联版）：
       regionSeed = seed + regX*341873128712 + regZ*132897987541 + salt (mod 2^64)
       state = setSeed(regionSeed) = (v ^ K) mod 2^48
       每次取偏移：state = LCG(state)；val = (state >> 17) % r   ← 无拒绝采样
   （r 为 2 的幂时：val = (r * (state >> 17)) >> 31）
   这使「val mod 2^k（r 整除 2^k）」精确等于「(state>>17) mod 2^k」，
   只取决于状态低 (17+k) 位 —— SeedReverser 逆推的数学基础。

2. 概率判定（rng.h 完整版 nextInt，含拒绝采样）：
       掠夺者前哨站的 1/5 生成判定用 nextInt(5)（cubiomes finders.c
       Outpost 分支显式调用 rng.h 的 nextInt 而非内联版）。

实现说明：
    - 状态一律保存为 0~2^48-1 的整数；移位用 >>（Python 对非负整数
      即逻辑右移，与目标位区间内的 C 算术右移等价）。
    - 拒绝采样判断用有符号 32 位语义（Java int），按掩码转写。
    - 向量化版本（numpy）为逆推层 1/层 2 提供批量计算；拒绝采样的
      向量化不需要（层 2 只验证线性结构偏移，走无拒绝语义；前哨站
      概率只在层 3 标量验证）。
    - numpy 未安装时向量化函数抛 ImportError；标量路径始终可用。
"""

try:
    import numpy as _np
    _HAVE_NUMPY = True
except ImportError:  # pragma: no cover
    _np = None
    _HAVE_NUMPY = False

# LCG 常量（Java Random / cubiomes rng.h）
_MULTIPLIER = 0x5DEECE66D          # 乘子 a
_ADDEND = 0xB                      # 增量 b
_MASK48 = (1 << 48) - 1            # 状态掩码
_MASK64 = (1 << 64) - 1            # 64 位回绕掩码（regionSeed 运算用）

# regionSeed 系数（cubiomes getRegionSeed）
_REG_X_COEF = 341873128712
_REG_Z_COEF = 132897987541


# ---------------------------------------------------------------------------
# 标量版本：单种子单次运算
# ---------------------------------------------------------------------------

def set_seed(value: int) -> int:
    """Java Random.setSeed 的标量版。

    Args:
        value: 任意 64 位整数（自动回绕到低 48 位）。

    Returns:
        掩码后的 48 位初始状态（value ^ K 后取低 48 位）。
    """
    return (value ^ _MULTIPLIER) & _MASK48


def next_state(state: int) -> int:
    """LCG 前进一步，返回新状态（仅低 48 位）。

    Args:
        state: 当前 48 位状态。

    Returns:
        一次迭代后的状态 s' = (s * K + B) mod 2^48。
    """
    return (state * _MULTIPLIER + _ADDEND) & _MASK48


def next_bits(state: int, bits: int) -> int:
    """Java Random.next(bits)：迭代一次并返回最高 bits 位（无符号）。

    Args:
        state: 当前状态。
        bits: 需要的位数（1..32，Minecraft 结构只用 17/31）。

    Returns:
        (s' >> (48 - bits))，即新状态的高 bits 位。
    """
    return next_state(state) >> (48 - bits)


def next_int(state: int, n: int) -> tuple[int, int]:
    """Java Random.nextInt(n) 的标量版（含拒绝采样，rng.h 语义）。

    供前哨站概率判定等「完整版 nextInt」场景使用；结构区块定位
    请用 struct_next_int（无拒绝采样，cubiomes 内联版语义）。

    Args:
        state: 当前 48 位状态。
        n: 模数（1..2^31-1）。

    Returns:
        (结果, 迭代后的状态)。结果满足 0 <= result < n。
    """
    m = n - 1
    if (m & n) == 0:
        # 2 的幂特判：next(31) 乘 n 后取高 31 位
        nxt = next_state(state)
        return (n * (nxt >> 17)) >> 31, nxt
    # 拒绝采样（Java 原版 / rng.h 一致）：do-while 转写
    nxt = next_state(state)
    bits = nxt >> 17
    val = bits % n
    while (((bits - val + m) & 0xFFFFFFFF) >= 0x80000000):
        nxt = next_state(nxt)
        bits = nxt >> 17
        val = bits % n
    return val, nxt


def struct_next_int(state: int, r: int) -> tuple[int, int]:
    """结构区块定位用的 nextInt（无拒绝采样，cubiomes 内联版语义）。

    对应 finders.h getFeatureChunkInRegion：
        state' = (state * K + B) & M48
        r 非 2 幂：val = (state' >> 17) % r
        r 为 2 幂：val = (r * (state' >> 17)) >> 31

    Args:
        state: 当前 48 位状态。
        r: chunkRange（结构偏移上界）。

    Returns:
        (val, 迭代后的状态)。
    """
    nxt = next_state(state)
    if r & (r - 1) == 0:
        return (r * (nxt >> 17)) >> 31, nxt
    return (nxt >> 17) % r, nxt


def next_float(state: int) -> tuple[float, int]:
    """Java Random.nextFloat 的标量版（rng.h nextFloat 语义）。

    对应 rng.h：
        nextFloat = next(24) / (float)(1 << 24)
    消耗一次 next(24)，状态推进一步。

    用途：埋藏的宝藏 1% 生成判定（finders.c Treasure 分支
    nextFloat < 0.01）。

    Args:
        state: 当前 48 位状态。

    Returns:
        (float 值 ∈ [0,1), 迭代后的状态)。
    """
    return next_bits(state, 24) / float(1 << 24), next_state(state)


def next_double(state: int) -> tuple[float, int]:
    """Java Random.nextDouble 的标量版（rng.h nextDouble 语义）。

    对应 rng.h / java.util.Random：
        nextDouble = ((next(26) << 27) + next(27)) / 2^53
    消耗 next(26) + next(27)，状态推进两步。

    用途：废弃矿井 0.4% 生成判定（finders.c getMineshafts
    1.13+ 分支 nextDouble < 0.004）。

    Args:
        state: 当前 48 位状态。

    Returns:
        (double 值 ∈ [0,1), 迭代两次后的状态)。
    """
    nxt = next_state(state)
    hi = nxt >> (48 - 26)
    nxt = next_state(nxt)
    lo = nxt >> (48 - 27)
    return ((hi << 27) + lo) / float(1 << 53), nxt


def region_seed(structure_seed: int, reg_x: int, reg_z: int, salt: int) -> int:
    """cubiomes getRegionSeed：由结构种与区域坐标算出区域 LCG 初始状态。

    即 finders.c getRegPos 中的：
        s = worldSeed + regX*341873128712 + regZ*132897987541 + salt   (mod 2^64)
        s = setSeed(s)   # ^K 后取低 48 位

    Args:
        structure_seed: 48 位结构种（世界种子低 48 位）。
        reg_x: 区域 X 坐标（区块单位）。
        reg_z: 区域 Z 坐标（区块单位）。
        salt: 结构 salt（见 structure_params）。

    Returns:
        48 位初始状态（setSeed 之后、第一次取偏移之前的状态）。
    """
    v = (structure_seed
         + reg_x * _REG_X_COEF
         + reg_z * _REG_Z_COEF
         + salt) & _MASK64
    return (v ^ _MULTIPLIER) & _MASK48


# ---------------------------------------------------------------------------
# 向量化版本（numpy，逆推层 1/层 2 用；无 numpy 时抛 ImportError）
# ---------------------------------------------------------------------------

def _require_numpy():
    if not _HAVE_NUMPY:
        raise ImportError(
            "numpy 未安装：向量化求解不可用。请在 MCHelper 的 venv 中安装 numpy"
            "（pip install numpy）。"
        )
    return _np


def _vec_uint64_consts():
    """uint64 形式的 LCG 常量（供向量化运算复用）。"""
    np = _require_numpy()
    return (np.uint64(_MULTIPLIER), np.uint64(_ADDEND), np.uint64(_MASK48))


def vec_step(states):
    """数组版 LCG 前进一步：states' = (states * K + B) mod 2^48。

    uint64 乘法/加法按 2^64 自然回绕，& M48 后与 C 的 48 位截断一致。
    低 L 位输入时输出的低 L 位同样正确（乘法低位只依赖乘数低位）。

    Args:
        states: uint64 数组（48 位状态，或仅低 L 位有效）。

    Returns:
        uint64 数组：迭代后状态（低 48 位有效；低位输入时低 L 位正确）。
    """
    K, B, M48 = _vec_uint64_consts()
    return (states * K + B) & M48


def vec_region_seed(structure_seeds, reg_x: int, reg_z: int, salt: int):
    """数组版 region_seed（输入多个候选结构种，输出各自 48 位初始状态）。

    注意：reg_x/reg_z 可为负，reg_x*341873128712 可能超出 int64，
    故全部用 uint64 运算（加法按 2^64 自然回绕，与 C 一致）。

    Args:
        structure_seeds: uint64/int64 数组（候选结构种）。
        reg_x: 区域 X（区块单位）。
        reg_z: 区域 Z（区块单位）。
        salt: 结构 salt。

    Returns:
        uint64 数组：各候选的 setSeed 后初始状态（低 48 位有效）。
    """
    np = _require_numpy()
    coef_x = (int(reg_x) * _REG_X_COEF) & _MASK64
    coef_z = (int(reg_z) * _REG_Z_COEF) & _MASK64
    salt_mod = int(salt) & _MASK64
    v = (structure_seeds.astype(np.uint64)
         + np.uint64(coef_x) + np.uint64(coef_z) + np.uint64(salt_mod)) & np.uint64(_MASK64)
    return (v ^ np.uint64(_MULTIPLIER)) & np.uint64(_MASK48)


def vec_struct_next_int(states, r: int):
    """数组版 struct_next_int（无拒绝采样）：返回 (val 数组, 状态数组)。

    Args:
        states: uint64 数组（48 位状态）。
        r: chunkRange。

    Returns:
        (uint64 val 数组, uint64 状态数组)。
    """
    np = _require_numpy()
    st = vec_step(states)
    bits = st >> np.uint64(17)
    if r & (r - 1) == 0:
        return (bits * np.uint64(r)) >> np.uint64(31), st
    return bits % np.uint64(r), st


def vec_state_lows(structure_seed_lows, L: int, reg_x: int, reg_z: int, salt: int):
    """数组版「低位 region_seed」：由结构种低 L 位推 setSeed 后状态低 L 位。

    regionSeed 的加法/异或在低 L 位上封闭（加法进位只向上传播，异或按位）：
        s0 = seed + regX*C1 + regZ*C2 + salt (mod 2^64)
        state = (s0 ^ K) & (2^48-1)
    故状态低 L 位只依赖结构种低 L 位。

    Args:
        structure_seed_lows: uint64 数组（结构种低 L 位）。
        L: 位数（层 1 用 19）。
        reg_x / reg_z / salt: 区域坐标与盐。

    Returns:
        uint64 数组：状态低 L 位（高位置零）。
    """
    np = _require_numpy()
    mask_l = (1 << L) - 1
    coef_x = (int(reg_x) * _REG_X_COEF) & mask_l
    coef_z = (int(reg_z) * _REG_Z_COEF) & mask_l
    salt_l = int(salt) & mask_l
    v = (structure_seed_lows.astype(np.uint64)
         + np.uint64(coef_x) + np.uint64(coef_z) + np.uint64(salt_l)) & np.uint64(mask_l)
    return (v ^ np.uint64(_MULTIPLIER & mask_l)) & np.uint64(mask_l)
