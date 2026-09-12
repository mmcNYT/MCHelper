# -*- coding: utf-8 -*-
"""SeedReverser 的结构正向复刻与逆推求解（cubiomes 权威算法 + lifting 预筛）。

正向（getFeaturePos / getLargeStructurePos 复刻，finders.h 内联版语义）：
    - 线性散布结构（沉船/沙漠神殿/雪屋/女巫小屋/丛林神庙/村庄/海底废墟/
      远古城市/试炼密室）：
          regionSeed = (structureSeed + regX*341873128712 + regZ*132897987541
                        + salt) mod 2^64
          st = setSeed(regionSeed)           # (v ^ K) mod 2^48
          offX = (st1 >> 17) % r,  st1 = LCG(st)      # 无拒绝采样
          offZ = (st2 >> 17) % r,  st2 = LCG(st1)
          结构方块坐标 = ((regX*regionSize + offX) << 4, ...)
    - 三角散布（海底神殿/林地府邸）4 次取平均：offX = (v1+v2) >> 1
      （mansion 仅 MapPreviewer 标注用，SeedReverser UI 已下架）
    - 前哨站：坐标同线性 + setAttemptSeed 概率判定 nextInt(5)==0
      （setAttemptSeed 作用在结构种子上，非区域种子——finders.c Outpost 分支）

逆推（SeedCrackerX TimeMachine lifting 思路，三层漏斗）：

    数学基础：regionSeed 的加法/异或/截断在低 L 位封闭，LCG 乘加亦然，
    故「结构种低 L 位相同 ⟹ 全部状态低 L 位相同」。而偏移
        val = (st >> 17) % r
    在 r 是 2^k 的倍数时满足 val mod 2^k = (st >> 17) mod 2^k，
    只取决于状态低 (17+k) 位。每个结构用自己的 lift_mod 参与预筛：
    r=24 的结构（沙漠神殿/雪屋/女巫小屋/丛林神庙）可用 mod8
    （低 20 位），r=20/12 用 mod4（低 19 位），r=26/22 用 mod2（低 18 位）。

    层 1：枚举低 L 位（L 取所有观测所需的最大位宽，numpy 向量化），
          对每个可 lifting 观测用自己的模数检查 offX%mod/offZ%mod，
          幸存数 ≈ 2^L / ∏mod_i^2
    层 2：每个幸存低位拼高位（组块向量化 + 压缩索引：第一观测
          4M→万级，后续观测在幸存子集上继续压缩）
    层 3：候选种子逐一精确正向复算全部观测（含三角/概率/2 幂结构）

    非 lifting 观测（monument/mansion 三角、ancient_city 2 幂 r、
    outpost 概率）只参与层 3 精确验证；mansion 参数仍可传入
    （MapPreviewer 共用参数表），但 SeedReverser UI 已不再收录。
    可 lifting 观测不足时抛错。

    站位容差（per-obs，可选）：玩家 F3+C 站位与结构锚点可差 ±tol 区块，
    三层比较从「精确相等」放宽为「距离 ≤ tol」：
        层 1：mod 预筛改集合成员 {(off±d) % mod}（d=-tol..tol）；
        层 2：完整偏移改范围校验 |off-guess| ≤ tol；
        层 3：正向复算改区块距离 ≤ tol。
    容差逐观测独立：观测 dict 可带 "tol" 键覆盖（无则用全局缺省参数），
    UI 默认容差表见 structure_params.DEFAULT_TOLERANCES。
    注意 mod 集合成员在 mod < 2tol+1 时会绕区域回卷引入弱化（方向不
    变、绝不含漏真种子）；mod=2 在 tol≥1 时退化为无预筛。容差模式下
    计算量估算超限（见 _TOLERANCE_TIME_LIMIT_S）会提前报错并指引
    补充小型结构观测。

    层 2 提供三档实现，按可用性自动选择：
        1. native（默认）：C++ 多线程扩展 _native/_solver_native.pyd
           （pybind11），语义与 numpy 档完全一致，数十倍加速；
           构建：python Utils/SeedReverser/_native/build_native.py
        2. numpy：向量化组块 + 压缩索引（无 pyd 时）
        3. 纯 Python：标量逐种子验证（无 numpy 时，极慢仅兜底）
    任一档运行期异常自动回落下一档（native 失败→numpy，不影响可用性）。

    无 numpy 时层 1/层 2 走纯 Python 逐位路径（极慢，仅兜底）。
"""

from . import mc_random
from . import seed_math
from . import structure_params

# ---- C++ 层 2 扩展（可选，缺失或异常时降级 numpy 路径）----
try:
    from ._native import _solver_native as _native_ext
except Exception:  # ImportError 以及扩展自身导入期异常，一律降级
    _native_ext = None

# 结构种位宽
_STRUCT_BITS = 48

# lifting 层 1 枚举位宽下限：mod8 需 17+3=20 位，mod4 需 19 位，mod2 需 18 位
#（solve 内按观测实际模数取 max(17+log2(mod_i))）
_MIN_LOW_BITS = 18

# 最少可 lifting 观测数（4 个 mod4 观测后层 1 幸存 ≈ 2^(20-16) = 16）
_MIN_LIFT_OBS = 4

# 层 2 单个观测验证的组块大小（约 4M，控制内存 < 百 MB）
_LIFT_BLOCK = 1 << 22

# ---- 站位容差 ----

# 容差模式守卫：耗时 / 候选数上限。超过任一上限提前抛 ValueError，
# 避免用户等待数十分钟~数天，或得到百万级无法人工核对的候选。
# 20 分钟（2026-09-09 应用户要求由 10 分钟放宽）：覆盖 8×mod8 tol=2
# 端到端场景（实测约 5 分钟）并留充足余量；仍可拦住 mod2 混合的
# 天级场景（估算 2.81e14 次验证远超 6e11 上限）。
_TOLERANCE_TIME_LIMIT_S = 1200
_NATIVE_VERIFY_RATE = 5e8   # native 层 2 实测吞吐（次验证/秒，2026-09 实测校准）
_TOLERANCE_MAX_VERIFIES = _TOLERANCE_TIME_LIMIT_S * _NATIVE_VERIFY_RATE
_TOLERANCE_MAX_CANDIDATES = 1_000_000   # 候选数可用性上限

# 站位容差上限（区块）。容差每 +1 信息量指数级下降：3 已普遍超出
# 守卫上限且村庄/试炼类完全失效，故收紧到 2（实测典型站位偏差
# 0~2 区块，2 已覆盖绝大多数场景）
_MAX_TOLERANCE = 2


def _obs_tol(ob: dict, default_tol: int = 0) -> int:
    """读观测的 per-obs 容差：ob["tol"] 优先，缺省回退 default_tol。

    非法值（非整数 / 越界）一律回退 default_tol 再钳制到 0~2，
    保证三层与守卫拿到的一直是可用整数。
    """
    t = ob.get("tol", default_tol)
    try:
        t = int(t)
    except (TypeError, ValueError):
        t = int(default_tol)
    if t < 0:
        t = 0
    if t > _MAX_TOLERANCE:
        t = _MAX_TOLERANCE
    return t


def _estimate_tolerance_work(lift_obs) -> tuple[float, float]:
    """估算容差求解的层 2 验证次数与候选数期望（守卫用，per-obs 容差）。

    层 1 按 mod 余数集合过滤（每维通过率 = min(2tol+1, mod)/mod，
    mod ≤ 2tol+1 时为 1，即该观测在层 1 完全失效——村庄/试炼 mod2
    在 tol≥1 时正是如此）；层 2 对每个幸存低位枚举全部高位做范围
    校验（每维通过率 = min(2tol+1, r)/r）。两层作用在同一锚点变量
    上，验证次数与候选数分别为（每个观测用自己的 tol）：
        验证次数 ≈ 2^48 × ∏(min(2tol_i+1, mod_i)/mod_i)²
        候选数   ≈ 2^48 × ∏(min(2tol_i+1, r_i)/r_i)²
    """
    est_time = float(1 << _STRUCT_BITS)
    est_cand = float(1 << _STRUCT_BITS)
    for ob in lift_obs:
        window = 2 * ob["tol"] + 1   # solve 入口已归一化，必存在
        est_time *= (min(window, ob["lift_mod"]) / ob["lift_mod"]) ** 2
        est_cand *= (min(window, ob["chunk_range"]) / ob["chunk_range"]) ** 2
    return est_time, est_cand


# ---------------------------------------------------------------------------
# 正向：结构坐标计算（cubiomes 精确复刻）
# ---------------------------------------------------------------------------

def get_structure_pos(struct_key: str, structure_seed: int, reg_x: int, reg_z: int,
                      version_key: str = "1.21") -> tuple[int, int]:
    """由结构种与区域坐标算出结构方块坐标（西北角，复刻 cubiomes）。

    Args:
        struct_key: 结构键。
        structure_seed: 48 位结构种。
        reg_x: 区域 X（区块单位）。
        reg_z: 区域 Z（区块单位）。
        version_key: 版本键。

    Returns:
        (方块 x, 方块 z)。
    """
    params = structure_params.get_params(struct_key, version_key)
    salt = params["salt"]
    region_size = params["region_size"]
    chunk_range = params["chunk_range"]
    scatter = params["scatter"]

    state = mc_random.region_seed(structure_seed, reg_x, reg_z, salt)
    if scatter == "triangle":
        off_x, off_z = _next_offsets_triangle(state, chunk_range)
    else:
        off_x, off_z = _next_offsets_linear(state, chunk_range)

    return (reg_x * region_size + off_x) << 4, (reg_z * region_size + off_z) << 4


def _next_offsets_linear(state: int, r: int) -> tuple[int, int]:
    """线性散布：两次 struct_next_int → (offX, offZ)（无拒绝采样）。"""
    off_x, state = mc_random.struct_next_int(state, r)
    off_z, _ = mc_random.struct_next_int(state, r)
    return off_x, off_z


def _next_offsets_triangle(state: int, r: int) -> tuple[int, int]:
    """三角散布：4 次 struct_next_int 取两次平均（monument / mansion，
    前者 SeedReverser 观测用，后者仅 MapPreviewer 标注用）。"""
    a1, state = mc_random.struct_next_int(state, r)
    a2, state = mc_random.struct_next_int(state, r)
    b1, state = mc_random.struct_next_int(state, r)
    b2, _ = mc_random.struct_next_int(state, r)
    return (a1 + a2) >> 1, (b1 + b2) >> 1


def get_structure_chunk(struct_key: str, structure_seed: int, reg_x: int, reg_z: int,
                        version_key: str = "1.21") -> tuple[int, int]:
    """结构区块坐标（区块单位）。"""
    bx, bz = get_structure_pos(struct_key, structure_seed, reg_x, reg_z, version_key)
    return bx >> 4, bz >> 4


def outpost_probability(structure_seed: int, reg_x: int, reg_z: int,
                        version_key: str = "1.21") -> bool:
    """掠夺者前哨站的额外 1/5 概率判定（cubiomes finders.c Outpost 分支）。

    复刻：
        pos = getFeaturePos(...)                    # 坐标本身
        setAttemptSeed(&seed, pos.x>>4, pos.z>>4)   # 作用在结构种子上
        return nextInt(&seed, 5) == 0
    其中 setAttemptSeed(s, cx, cz):
        s ^= (cx>>4) ^ ((cz>>4)<<4); setSeed(s, s); next(s, 31)

    Args:
        structure_seed: 48 位结构种。
        reg_x / reg_z: 区域坐标。
        version_key: 版本键。

    Returns:
        True 表示该 (种子, 区域) 实际生成前哨站。
    """
    params = structure_params.get_params("pillager_outpost", version_key)
    bx, bz = get_structure_pos("pillager_outpost", structure_seed,
                               reg_x, reg_z, version_key)
    cx, cz = bx >> 4, bz >> 4
    # setAttemptSeed 作用在结构种子（非区域种子）
    s = (structure_seed ^ (cx >> 4) ^ ((cz >> 4) << 4)) & ((1 << 64) - 1)
    state = mc_random.set_seed(s)
    state = mc_random.next_state(state)   # next(s, 31) 消耗一次
    val, _ = mc_random.next_int(state, 5)
    return val == 0


# ---------------------------------------------------------------------------
# 逆推辅助
# ---------------------------------------------------------------------------

def _lift_split(observations, version_key: str, default_tol: int = 0):
    """把观测分为可 lifting（线性散布且 lift_mod>=2）与不可 lifting 两组。

    同时把 per-obs 容差归一化进 entry（"tol" 键：obs 自带优先，
    否则用 default_tol）——后续层 1/层 2/守卫统一读 entry["tol"]。

    Returns:
        (lift_obs, other_obs)：lift_obs 为线性结构观测（含参数），按
        lift_mod 降序（mod4 的排前面，尽量用大模数压缩）。
    """
    lift_obs, other_obs = [], []
    for o in observations:
        params = structure_params.get_params(o["struct_key"], version_key)
        entry = dict(o)
        entry["salt"] = params["salt"]
        entry["chunk_range"] = params["chunk_range"]
        entry["region_size"] = params["region_size"]
        entry["scatter"] = params["scatter"]
        entry["lift_mod"] = params["lift_mod"]
        entry["tol"] = _obs_tol(o, default_tol)
        if params["scatter"] == "linear" and params["lift_mod"] >= 2:
            lift_obs.append(entry)
        else:
            other_obs.append(entry)
    # mod4 观测优先（压缩比高）
    lift_obs.sort(key=lambda e: -e["lift_mod"])
    return lift_obs, other_obs


def _layer1_lowbits_np(lift_obs, low_bits: int, on_progress=None):
    """层 1（numpy）：枚举低 low_bits 位，每个观测用自己的 lift_mod 预筛。

    对每个观测：
        state_low = vec_state_lows(lows, L, regX, regZ, salt)
        st1 = LCG(state_low); st2 = LCG(st1)
        valx = (st1 >> 17) % r 的低 log2(mod) 位 == 观测 offX%mod（r 为 mod 倍数时精确）
        valz 同理
        保留同时满足两条件的行

    low_bits 须 >= 17 + max(log2(mod_i))。
    tol > 0 的观测 mod 比较改为集合成员（off±tol 的余数集，见模块 docstring），
    tol 逐观测独立（entry["tol"]，_lift_split 已归一化）。

    Returns:
        幸存 lowerBits 的 uint64 numpy 数组（升序）。
    """
    np = mc_random._require_numpy()
    total = 1 << low_bits
    lows = np.arange(total, dtype=np.uint64)
    for ob in lift_obs:
        if len(lows) == 0:
            break
        mod = ob["lift_mod"]
        mx = np.uint64(mod - 1)
        tol = ob["tol"]
        if tol > 0:
            want_x = np.array(sorted({(ob["off_x"] + d) % mod
                                      for d in range(-tol, tol + 1)}),
                              dtype=np.uint64)
            want_z = np.array(sorted({(ob["off_z"] + d) % mod
                                      for d in range(-tol, tol + 1)}),
                              dtype=np.uint64)
        else:
            want_x = np.uint64(ob["off_x"] % mod)
            want_z = np.uint64(ob["off_z"] % mod)
        state_low = mc_random.vec_state_lows(lows, low_bits,
                                             ob["reg_x"], ob["reg_z"], ob["salt"])
        st1 = mc_random.vec_step(state_low)
        st2 = mc_random.vec_step(st1)
        # offX/offZ 的 mod 值：模为 2 幂时 % 等价于 & (mod-1)
        ox = ((st1 >> np.uint64(17)) & mx)
        oz = ((st2 >> np.uint64(17)) & mx)
        if tol > 0:
            keep = np.isin(ox, want_x) & np.isin(oz, want_z)
        else:
            keep = (ox == want_x) & (oz == want_z)
        lows = lows[keep]
        if on_progress:
            on_progress(int(ob.get("_idx", 0)) + 1, len(lift_obs), "层1")
    if on_progress:
        on_progress(len(lift_obs), len(lift_obs), "层1")
    return lows


def _layer1_lowbits_py(lift_obs, low_bits: int, on_progress=None):
    """层 1（纯 Python 兑底）：逐 low 位枚举 + 各自 mod 预筛。

    tol > 0 的观测 mod 比较改为集合成员（off±tol 的余数集），
    tol 逐观测独立（entry["tol"]）。

    Returns:
        幸存 lowerBits 列表（升序）。
    """
    keep = []
    for ob in lift_obs:
        mod = ob["lift_mod"]
        tol = ob["tol"]
        if tol > 0:
            want_x = {(ob["off_x"] + d) % mod for d in range(-tol, tol + 1)}
            want_z = {(ob["off_z"] + d) % mod for d in range(-tol, tol + 1)}
        else:
            want_x = {ob["off_x"] % mod}
            want_z = {ob["off_z"] % mod}
        keep.append((mod - 1, want_x, want_z, ob))
    survivors = []
    total = 1 << low_bits
    step = max(total // 100, 1)
    for lower in range(total):
        ok = True
        for mask_mod, want_x, want_z, ob in keep:
            state = mc_random.region_seed(lower, ob["reg_x"], ob["reg_z"], ob["salt"])
            ox, state = mc_random.struct_next_int(state, ob["chunk_range"])
            if (ox & mask_mod) not in want_x:
                ok = False
                break
            oz, _ = mc_random.struct_next_int(state, ob["chunk_range"])
            if (oz & mask_mod) not in want_z:
                ok = False
                break
        if ok:
            survivors.append(lower)
        if on_progress and (lower % step == 0):
            on_progress(lower, total, "层1")
    if on_progress:
        on_progress(total, total, "层1")
    return survivors


def _layer2_np(lift_obs, lows_arr, low_bits: int, on_progress=None, cancel=None):
    """层 2（numpy）：对每个幸存 low 枚举高 28 位，压缩索引验证完整偏移。

    对每个块（约 4M 候选种子）：
        第一观测：vec_region_seed + 两次 vec_struct_next_int，比较完整
        offX/offZ（不只是 mod），幸存种子压缩后继续下一观测
        （每个观测后种子数 ÷ r^2，第二观测后通常只剩个位数）。

    tol > 0 的观测完整偏移比较改为范围校验 |off - guess| ≤ tol（int64 距离，
    不跨区域绕回——锚点跨区域时该观测本就不可靠，UI 会另行警告），
    tol 逐观测独立（entry["tol"]，_lift_split 已归一化）。

    Returns:
        通过全部 lifting 观测的 48 位种子列表。
    """
    np = mc_random._require_numpy()
    if len(lift_obs) == 0 or len(lows_arr) == 0:
        return []
    high_bits = _STRUCT_BITS - low_bits
    total_high = 1 << high_bits
    results = []
    block = _LIFT_BLOCK
    done_blocks = 0
    total_blocks = len(lows_arr) * ((total_high + block - 1) // block)
    for lower in np.asarray(lows_arr, dtype=np.uint64).tolist():
        lower_u = np.uint64(int(lower))
        if cancel and cancel():
            break
        for start in range(0, total_high, block):
            if cancel and cancel():
                break
            end = min(start + block, total_high)
            upper = np.arange(start, end, dtype=np.uint64)
            seeds = (upper << np.uint64(low_bits)) | lower_u
            # 逐观测压缩（分步：offX 先筛，幸存者再算 offZ，省 ~45%）
            alive = seeds
            for ob in lift_obs:
                tol = ob["tol"]
                st = mc_random.vec_region_seed(alive, ob["reg_x"], ob["reg_z"], ob["salt"])
                ox, st = mc_random.vec_struct_next_int(st, ob["chunk_range"])
                if tol > 0:
                    keep = np.abs(ox.astype(np.int64) - np.int64(int(ob["off_x"]))) <= np.int64(tol)
                else:
                    keep = ox == np.uint64(ob["off_x"])
                alive = alive[keep]
                if len(alive) == 0:
                    break
                oz, _ = mc_random.vec_struct_next_int(st[keep], ob["chunk_range"])
                if tol > 0:
                    alive = alive[np.abs(oz.astype(np.int64) - np.int64(int(ob["off_z"]))) <= np.int64(tol)]
                else:
                    alive = alive[oz == np.uint64(ob["off_z"])]
                if len(alive) == 0:
                    break
            if len(alive):
                results.extend(int(s) for s in alive.tolist())
            done_blocks += 1
            if on_progress:
                on_progress(done_blocks, total_blocks, "层2")
    return results


def _layer2_py(lift_obs, lower_list, low_bits: int, on_progress=None, cancel=None):
    """层 2（纯 Python 兑底）：逐种子标量验证（极慢，仅无 numpy 时）。

    tol > 0 的观测完整偏移比较改为 |off - guess| ≤ tol 范围校验，
    tol 逐观测独立（entry["tol"]）。
    """
    high_bits = _STRUCT_BITS - low_bits
    results = []
    done = 0
    total = len(lower_list) * (1 << high_bits)
    for lower in lower_list:
        for upper in range(1 << high_bits):
            if cancel and cancel():
                break
            seed = (upper << low_bits) | lower
            ok = True
            for ob in lift_obs:
                state = mc_random.region_seed(seed, ob["reg_x"], ob["reg_z"], ob["salt"])
                ox, state = mc_random.struct_next_int(state, ob["chunk_range"])
                oz, _ = mc_random.struct_next_int(state, ob["chunk_range"])
                if ob["tol"] > 0:
                    if abs(ox - ob["off_x"]) > ob["tol"] or abs(oz - ob["off_z"]) > ob["tol"]:
                        ok = False
                        break
                elif ox != ob["off_x"] or oz != ob["off_z"]:
                    ok = False
                    break
            if ok:
                results.append(seed)
            done += 1
            if on_progress and (done % 1000000 == 0):
                on_progress(done, total, "层2")
    if on_progress:
        on_progress(total, total, "层2")
    return results


def _layer2_native(lift_obs, lower_list, low_bits: int,
                   on_progress=None, cancel=None):
    """层 2（C++ 多线程扩展）：语义与 _layer2_np 完全一致（含 per-obs tol）。

    直接把 dict 观测列表与低位列表交给扩展（内部解析后计算期零 Python
    交互）；扩展读每个 obs 的 "tol" 键（缺省 0）；on_progress/cancel
    与其它档同名同参——在 monitor 线程被调用，不得接触 Qt（与
    task_SeedReverser 现有回调约定一致）。
    取消时返回已完成部分的候选（与 numpy 档一致）。

    Raises:
        RuntimeError: 扩展缺失或内部错误（调用方负责降级）。
    """
    if _native_ext is None:
        raise RuntimeError("native 层 2 扩展不可用")
    arr = _native_ext.layer2_full(
        lift_obs, lower_list, low_bits,
        on_progress=on_progress, check_cancel=cancel,
    )
    return [int(x) for x in arr.tolist()]


def _layer3_verify(candidates, observations, version_key: str, on_progress=None,
                   default_tol: int = 0):
    """对候选逐一正向复算全部观测（含三角/概率/2 幂）。

    tol > 0 的观测区块与生成区块的距离 ≤ tol 即视为满足（玩家站位语义），
    tol 逐观测独立（obs["tol"] 优先，缺省用 default_tol）。
    """
    final = []
    for idx, seed in enumerate(candidates):
        if all(_verify_observation(seed, o, version_key,
                                   _obs_tol(o, default_tol))
               for o in observations):
            final.append(seed)
        if on_progress:
            on_progress(idx + 1, len(candidates), "层3")
    return final


def _verify_observation(seed: int, o: dict, version_key: str,
                        tol: int = 0) -> bool:
    """对一个观测做正向验证（返回该种子是否满足）。

    tol > 0：期望区块与生成区块的切比雪夫距离（max(|dx|, |dz|)）≤ tol。
    """
    struct_key = o["struct_key"]
    params = structure_params.get_params(struct_key, version_key)
    reg_x, reg_z = o["reg_x"], o["reg_z"]
    # 观测的期望区块坐标
    if "block_cx" in o:
        want_cx, want_cz = o["block_cx"], o["block_cz"]
    else:
        want_cx = o["reg_x"] * params["region_size"] + o["off_x"]
        want_cz = o["reg_z"] * params["region_size"] + o["off_z"]
    bx, bz = get_structure_pos(struct_key, seed, reg_x, reg_z, version_key)
    dx = (bx >> 4) - want_cx
    dz = (bz >> 4) - want_cz
    if tol > 0:
        if max(abs(dx), abs(dz)) > tol:
            return False
    else:
        if dx != 0 or dz != 0:
            return False
    if struct_key == "pillager_outpost":
        # 概率结构：坐标正确还必须判定生成
        if not outpost_probability(seed, reg_x, reg_z, version_key):
            return False
    return True


def verify_candidate_seed(seed: int, observations, version_key: str,
                          tol: int = 0):
    """对单个候选种子做正向全量比对（UI「验证候选种子」的唯一语义来源）。

    与手动验证按钮、层 3 复算同源：逐观测正向复算结构位置并比对区块
    坐标（tol>0 时按切比雪夫距离放宽；哨塔额外做生成概率判定）。

    Args:
        seed: 48 位结构种。
        observations: 观测 dict 列表（字段同 solve_structure_seeds；
            可含 "x"/"z"/"name" 供展示，缺失时回退由区域/偏移推算）。
        version_key: 版本键。
        tol: 站位容差缺省值（区块，0~2）：obs 无 "tol" 键时用；
            obs 自带 "tol"（UI 逐条下拉）则优先。0 = 精确。

    Returns:
        (ok, lines)：ok 为全部观测是否吻合；lines 为逐条比对文本行
        （不含首尾空行，调用方自行拼装）。
    """
    lines = []
    matched = 0
    for i, obs in enumerate(observations, 1):
        obs_tol = _obs_tol(obs, tol)
        bx, bz = get_structure_pos(
            obs["struct_key"], seed, obs["reg_x"], obs["reg_z"], version_key)
        # 观测方块坐标（自动验证透传 F3+C 原始站位；缺失则取期望区块）
        if "x" in obs:
            obs_cx, obs_cz = obs["x"] >> 4, obs["z"] >> 4
        else:
            params = structure_params.get_params(
                obs["struct_key"], version_key)
            obs_cx = obs["reg_x"] * params["region_size"] + obs["off_x"]
            obs_cz = obs["reg_z"] * params["region_size"] + obs["off_z"]
        gen_cx, gen_cz = bx >> 4, bz >> 4
        pos_ok = (gen_cx == obs_cx and gen_cz == obs_cz)
        if obs_tol > 0:
            pos_ok = (max(abs(gen_cx - obs_cx), abs(gen_cz - obs_cz)) <= obs_tol)
        outpost_prob_fail = False
        if pos_ok and obs["struct_key"] == "pillager_outpost":
            outpost_prob_fail = not outpost_probability(
                seed, obs["reg_x"], obs["reg_z"], version_key)
        if pos_ok and not outpost_prob_fail:
            matched += 1
            verdict = "  ✓ 吻合"
        elif outpost_prob_fail:
            verdict = "  ✗ 不符（未通过 1/5 生成概率判定）"
        else:
            verdict = "  ✗ 不符"
        lines.append(
            f"观测 {i}  {obs.get('name', obs['struct_key'])}"
            f"  观测区块({obs_cx}, {obs_cz})  生成区块({gen_cx}, {gen_cz})"
            f"{verdict}")

    total = len(observations)
    if total == 0:
        return False, lines + ["结果: 当前没有可比对/验证的观测。"]
    if matched == total:
        summary = f"结果: 全部 {total} 个观测吻合 ✓ —— 该种子与全部观测一致。"
    else:
        summary = (f"结果: {matched}/{total} 观测吻合，"
                   "种子可能不正确（或观测坐标有误）。")
    return matched == total, lines + [summary]


# ---------------------------------------------------------------------------
# 主入口：三层漏斗
# ---------------------------------------------------------------------------

def solve_structure_seeds(observations, version_key: str = "1.21",
                          on_progress=None, cancel=None, tol: int = 0) -> dict:
    """三层漏斗主入口：观测 → 候选 48 位结构种列表。

    Args:
        observations: 观测 dict 列表，每项须含：
            struct_key / reg_x / reg_z / off_x / off_z，
            可选 block_cx / block_cz（期望区块坐标，含省略则由偏移推算），
            可选 tol（该观测的站位容差，优先于全局 tol 参数）。
        version_key: 版本键。
        on_progress: 可选回调 (done:int, total:int, stage:str)。
        cancel: 可选回调，返回 True 时中止。
        tol: 站位容差缺省值（区块，0~2）：obs 无 "tol" 键时用。
            0 = 精确锿点语义；>0 = 站位与锿点可差 ±tol 区块。

    Returns:
        dict: {"candidates": list[int], "stages": {...统计}, "cancelled": bool}

    Raises:
        ValueError: 观测不足、可 lifting 观测不足，或容差模式下
            计算量超限（附补充观测建议）。
    """
    if len(observations) < 3:
        raise ValueError("至少需要 3 个结构观测才能计算。")
    tol = int(tol)
    if tol < 0 or tol > _MAX_TOLERANCE:
        raise ValueError(
            f"站位容差必须在 0~{_MAX_TOLERANCE} 区块之间（当前 {tol}）。")

    # 分组：可 lifting（线性散布）与不可 lifting（tol 已归一化进 entry）
    lift_obs, other_obs = _lift_split(observations, version_key, tol)
    if len(lift_obs) < _MIN_LIFT_OBS:
        raise ValueError(
            f"可用结构不足：需要至少 {_MIN_LIFT_OBS} 个可参与预筛的线性散布结构"
            "（沉船/沙漠神殿/雪屋/女巫小屋/丛林神庙/海底废墟等）。"
            "废弃传送门、海底神殿、林地府邸、远古城市、前哨站等"
            "只能作为验证观测，不能单独用于逆推。"
        )

    # 位宽：取所有观测所需位宽的最大值（17 + log2(最大模数)）
    low_bits = max(_MIN_LOW_BITS,
                   max(17 + (ob["lift_mod"].bit_length() - 1) for ob in lift_obs))

    # 可行性守卫：任一观测带容差时预筛弱化，计算量/候选数超限则提前报错
    if any(ob["tol"] > 0 for ob in lift_obs):
        est_time, est_cand = _estimate_tolerance_work(lift_obs)
        n_mod4 = sum(1 for ob in lift_obs if ob["lift_mod"] >= 4)
        hint = "" if n_mod4 >= 4 else (
            "\n当前缺少有效小型结构观测（村庄/试炼密室在容差模式下"
            "几乎不提供信息）。\n请优先补充：沙漠神殿/雪屋/女巫小屋/"
            "丛林神庙/沉船/海底废墟。")
        if est_time > _TOLERANCE_MAX_VERIFIES:
            raise ValueError(
                "容差模式下计算量过大：按当前观测预计约 "
                f"{est_time / _NATIVE_VERIFY_RATE:.0f} 秒（上限 "
                f"{_TOLERANCE_TIME_LIMIT_S} 秒）。{hint}\n"
                "也可改用「精确容差 0」模式，并配合 /locate 获取精确结构坐标。"
            )
        if est_cand > _TOLERANCE_MAX_CANDIDATES:
            raise ValueError(
                "容差模式下候选数过多：按当前观测预计约 "
                f"{est_cand / 1e6:.0f} 百万个候选（上限 "
                f"{_TOLERANCE_MAX_CANDIDATES // 1_000_000} 百万），"
                "无法逐个人工核对。请补充小型结构观测（沙漠神殿/雪屋/"
                "女巫小屋/丛林神庙/沉船/海底废墟）以压缩候选。"
            )

    # 给观测编号（进度显示用）
    for i, ob in enumerate(lift_obs):
        ob["_idx"] = i

    # ---- 层 1 ----
    if mc_random._HAVE_NUMPY:
        lows_arr = _layer1_lowbits_np(lift_obs, low_bits, on_progress)
        lower_list = lows_arr.tolist() if hasattr(lows_arr, "tolist") else list(lows_arr)
    else:
        lower_list = _layer1_lowbits_py(lift_obs, low_bits, on_progress)
    if not lower_list:
        return {
            "candidates": [],
            "stages": {"layer1": 0, "layer2": 0, "layer3": 0,
                       "low_bits": low_bits},
            "cancelled": bool(cancel and cancel()),
        }

    # ---- 层 2 ----
    if _native_ext is not None:
        try:
            stage2 = _layer2_native(lift_obs, lower_list, low_bits,
                                    on_progress, cancel)
        except Exception:
            # native 失败（扩展损毁/回调异常等）：回落 numpy/纯 Python 档
            if mc_random._HAVE_NUMPY:
                lows_arr = mc_random._np.array(lower_list,
                                               dtype=mc_random._np.uint64)
                stage2 = _layer2_np(lift_obs, lows_arr, low_bits,
                                    on_progress, cancel)
            else:
                stage2 = _layer2_py(lift_obs, lower_list, low_bits,
                                    on_progress, cancel)
    elif mc_random._HAVE_NUMPY:
        lows_arr = mc_random._np.array(lower_list, dtype=mc_random._np.uint64)
        stage2 = _layer2_np(lift_obs, lows_arr, low_bits, on_progress, cancel)
    else:
        stage2 = _layer2_py(lift_obs, lower_list, low_bits, on_progress, cancel)

    # ---- 层 3 ----
    final = _layer3_verify(stage2, observations, version_key, on_progress, tol)

    return {
        "candidates": final,
        "stages": {"layer1": len(lower_list), "layer2": len(stage2),
                   "layer3": len(final), "low_bits": low_bits},
        "cancelled": bool(cancel and cancel()),
    }
