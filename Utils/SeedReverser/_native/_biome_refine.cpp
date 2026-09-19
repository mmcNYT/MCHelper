// _biome_refine.cpp —— SeedReverser 二期「世界种子精化」的 C++ 多线程扩展。
//
// 语义基准：Utils/SeedReverser/biome_noise.py（已与 cubiomes 45/45 对拍通过），
// 逐函数翻译，浮点精度约定一致：
//   - RNG / Perlin / 八度：全程 double（与 noise.c 一致）
//   - 气候 shift / depth 样条：float32 域（C 代码里自然 float 运算）
//   - get_spline 最终插值与 quant：double 中间量，入口出口 float32/截断
//   - np 距离 / btree 搜索：uint64
//
// 功能：给定 48 位结构种候选 × 群系观测点（噪声格坐标），枚举高 16 位，
//       找回通过全部观测验证的 64 位世界种子。
//       seed = (high << 48) | s48，每个高位候选重建 BiomeCtx（气候参数级
//       RNG 状态依赖完整 64 位种子，无法跨高位复用）。
//
// 线程模型（与 _solver_native.cpp 相同）：
//   - 计算线程池：按高位区间 [begin,end) 分片，全程无 GIL；
//   - monitor 线程：每 30ms 唤醒，短暂持 GIL 调 Python 回调
//     （check_cancel → 置取消标志；on_progress(done,total,"refine") → 转发）。
//
// btree 数据：由 Python 端 world_seed_refine.py 首次调用前经 set_btree()
// 推入（数据源自 btree_tables.npz，与纯 Python 版共享同一份数据文件）。
//
// 重建扩展：python Utils/SeedReverser/_native/build_biome.py

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <condition_variable>
#include <cstdint>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <deque>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

// 调试日志开关：需要定位问题时改为 1 并重编译（热路径零开销）
#define BIOME_REFINE_DEBUG 0
#if BIOME_REFINE_DEBUG
static FILE* g_dbg = nullptr;
static void dbg_open() {
    if (!g_dbg) g_dbg = std::fopen("C:\\Users\\NYT\\AppData\\Local\\Temp\\native_dbg.log", "a");
}
#define DBG(...) do { dbg_open(); if (g_dbg) { std::fprintf(g_dbg, __VA_ARGS__); std::fflush(g_dbg); } } while (0)
#else
#define DBG(...) do {} while (0)
#endif

namespace py = pybind11;
using u64 = std::uint64_t;
using i64 = std::int64_t;
using u32 = std::uint32_t;
using u8 = std::uint8_t;

// ===========================================================================
// RNG：Xoroshiro128+ / SplitMix64 管线（rng.h L185-248，biome_noise.py 精确复刻）
// ===========================================================================

static inline u64 rotl64(u64 x, int k) { return (x << k) | (x >> (64 - k)); }

struct XR {
    u64 lo, hi;
};

// xSetSeed：世界种子 -> Xoroshiro 初始状态
static inline void x_set_seed(u64 value, u64& lo, u64& hi) {
    u64 l = value ^ 0x6A09E667F3BCC909ULL;
    u64 h = l + 0x9E3779B97F4A7C15ULL;
    l = (l ^ (l >> 30)) * 0xBF58476D1CE4E5B9ULL;
    h = (h ^ (h >> 30)) * 0xBF58476D1CE4E5B9ULL;
    l = (l ^ (l >> 27)) * 0x94D049BB133111EBULL;
    h = (h ^ (h >> 27)) * 0x94D049BB133111EBULL;
    l ^= l >> 31;
    h ^= h >> 31;
    lo = l;
    hi = h;
}

static inline u64 xr_next_long(XR& s) {
    const u64 l = s.lo, h = s.hi;
    const u64 n = rotl64(l + h, 17) + l;
    const u64 hh = h ^ l;
    s.lo = rotl64(l, 49) ^ hh ^ (hh << 21);
    s.hi = rotl64(hh, 28);
    return n;
}

// xNextInt（Lemon 风格拒绝采样，bound 取 32 位乘法高位）
static inline u32 xr_next_int(XR& s, u32 n) {
    u64 r = (u64)(xr_next_long(s) & 0xFFFFFFFFULL) * n;
    // Python: ((~n + 1) & 0xFFFFFFFF) % n == (2^32 - n) % n
    const u64 threshold = (0x100000000ULL - (u64)n) % n;
    while ((r & 0xFFFFFFFFULL) < threshold) {
        r = (u64)(xr_next_long(s) & 0xFFFFFFFFULL) * n;
    }
    return (u32)(r >> 32);
}

static inline double xr_next_double(XR& s) {
    return (double)(xr_next_long(s) >> (64 - 53)) * 1.1102230246251565E-16;
}

// ===========================================================================
// md5("octave_-N") 常量表与八度参数（noise.c L394-415）
// ===========================================================================

static const struct { u64 lo, hi; } MD5_OCTAVE_N[13] = {
    {0xb198de63a8012672ULL, 0x7b84cad43ef7b5a8ULL},  // octave_-12
    {0x0fd787bfbc403ec3ULL, 0x74a4a31ca21b48b8ULL},  // octave_-11
    {0x36d326eed40efeb2ULL, 0x5be9ce18223c636aULL},  // octave_-10
    {0x082fe255f8be6631ULL, 0x4e96119e22dedc81ULL},  // octave_-9
    {0x0ef68ec68504005eULL, 0x48b6bf93a2789640ULL},  // octave_-8
    {0xf11268128982754fULL, 0x257a1d670430b0aaULL},  // octave_-7
    {0xe51c98ce7d1de664ULL, 0x5f9478a733040c45ULL},  // octave_-6
    {0x6d7b49e7e429850aULL, 0x2e3063c622a24777ULL},  // octave_-5
    {0xbd90d5377ba1b762ULL, 0xc07317d419a7548dULL},  // octave_-4
    {0x53d39c6752dac858ULL, 0xbcd1c5a80ab65b3eULL},  // octave_-3
    {0xb4a24d7a84e7677bULL, 0x023ff9668e89b5c4ULL},  // octave_-2
    {0xdffa22b534c5f608ULL, 0xb9b67517d3665ca9ULL},  // octave_-1
    {0xd50708086cef4d7cULL, 0x6e1651ecc7f43309ULL},  // octave_0
};

static const double LACUNA_INI[13] = {
    1.0, 0.5, 0.25, 1.0 / 8, 1.0 / 16, 1.0 / 32, 1.0 / 64,
    1.0 / 128, 1.0 / 256, 1.0 / 512, 1.0 / 1024, 1.0 / 2048, 1.0 / 4096,
};

static const double PERSIST_INI[10] = {
    0.0, 1.0, 2.0 / 3, 4.0 / 7, 8.0 / 15, 16.0 / 31, 32.0 / 63,
    64.0 / 127, 128.0 / 255, 256.0 / 511,
};

static const double AMP_INI[10] = {
    0.0, 5.0 / 6, 10.0 / 9, 15.0 / 12, 20.0 / 15, 25.0 / 18,
    30.0 / 21, 35.0 / 24, 40.0 / 27, 45.0 / 30,
};

// ===========================================================================
// 气候参数定义（biomenoise.c L844-907）
// ===========================================================================

enum NP : int {
    NP_TEMPERATURE = 0, NP_HUMIDITY = 1, NP_CONTINENTALNESS = 2,
    NP_EROSION = 3, NP_SHIFT = 4, NP_WEIRDNESS = 5, NP_MAX = 6,
};

struct ClimateDef {
    u64 md5lo, md5hi;
    double amps[9];
    int namps;
    int omin;
};

static const ClimateDef CLIMATE_SMALL[NP_MAX] = {
    /*TEMP*/ {0x5c7e6b29735f0d7fULL, 0xf7d86f1bbc734988ULL, {1.5, 0, 1, 0, 0, 0}, 6, -10},
    /*HUM */ {0x81bb4d22e8dc168eULL, 0xf1c8b4bea16303cdULL, {1, 1, 0, 0, 0, 0}, 6, -8},
    /*CONT*/ {0x83886c9d0ae3a662ULL, 0xafa638a61b42e8adULL, {1, 1, 2, 2, 2, 1, 1, 1, 1}, 9, -9},
    /*EROS*/ {0xd02491e6058f6fd8ULL, 0x4792512c94c17a80ULL, {1, 1, 0, 1, 1}, 5, -9},
    /*SHFT*/ {0x080518cf6af25384ULL, 0x3f3dfb40a54febd5ULL, {1, 1, 1, 0}, 4, -3},
    /*WEIR*/ {0xefc8ef4d36102b34ULL, 0x1beeeb324a0f24eaULL, {1, 2, 1, 0, 0, 0}, 6, -7},
};

// large 变体：仅 T/H/C/E 四参数（biomenoise.c L854-899；SHIFT/W 固定）
static const ClimateDef CLIMATE_LARGE_T = {0x944b0073edf549dbULL, 0x4ff44347e9d22b96ULL, {1.5, 0, 1, 0, 0, 0}, 6, -12};
static const ClimateDef CLIMATE_LARGE_H = {0x71b8ab943dbd5301ULL, 0xbb63ddcf39ff7a2bULL, {1, 1, 0, 0, 0, 0}, 6, -10};
static const ClimateDef CLIMATE_LARGE_C = {0x9a3f51a113fce8dcULL, 0xee2dbd157e5dcdadULL, {1, 1, 2, 2, 2, 1, 1, 1, 1}, 9, -11};
static const ClimateDef CLIMATE_LARGE_E = {0x8c984b1f8702a951ULL, 0xead7b1f92bae535fULL, {1, 1, 0, 1, 1}, 5, -11};

// large 变体常量保留：后续接入 large biomes 时启用（当前 enumerate 只走 SMALL）

// ===========================================================================
// Perlin（noise.c xPerlinInit / samplePerlin，全程 double）
// ===========================================================================

struct Perlin {
    double a, b, c;      // 三轴偏移（next_double * 256）
    int h2;              // b 轴预计算
    double d2, t2;
    u8 perm[257];        // 0..255 洗牌 + perm[256]=perm[0]
};

static void x_perlin_init(XR& xr, Perlin& p) {
    DBG("  perlin_init enter\n");
    p.a = xr_next_double(xr) * 256.0;
    p.b = xr_next_double(xr) * 256.0;
    p.c = xr_next_double(xr) * 256.0;
    for (int i = 0; i < 256; ++i) p.perm[i] = (u8)i;
    for (int i = 0; i < 256; ++i) {
        const int j = (int)xr_next_int(xr, (u32)(256 - i)) + i;
        const u8 t = p.perm[i];
        p.perm[i] = p.perm[j];
        p.perm[j] = t;
    }
    p.perm[256] = p.perm[0];
    const double i2 = std::floor(p.b);
    p.d2 = p.b - i2;
    p.h2 = (int)i2;
    p.t2 = p.d2 * p.d2 * p.d2 * (p.d2 * (p.d2 * 6.0 - 15.0) + 10.0);
    DBG("  perlin_init exit a=%.4f b=%.4f c=%.4f\n", p.a, p.b, p.c);
}

// noise.c indexedLerp（梯度点积；表序与 biome_noise.py 一致，已 45/45 对拍）
static inline double indexed_lerp(int idx, double a, double b, double c) {
    switch (idx & 0xF) {
        case 0:  return a + b;
        case 1:  return -a + b;
        case 2:  return a - b;
        case 3:  return -a - b;
        case 4:  return a + c;
        case 5:  return -a + c;
        case 6:  return a - c;
        case 7:  return -a - c;
        case 8:  return b + c;
        case 9:  return -b + c;
        case 10: return b - c;
        case 11: return -b - c;
        case 12: return a + b;
        case 13: return -b + c;
        case 14: return -a + b;
        case 15: return -b - c;
    }
    return 0.0;
}

static double sample_perlin(const Perlin& p, double d1, double d2, double d3) {
    int h2;
    double t2;
    DBG("    spl enter d1=%.4f d2=%.4f d3=%.4f\n", d1, d2, d3);
    if (d2 == 0.0) {
        d2 = p.d2;
        h2 = p.h2;
        t2 = p.t2;
    } else {
        d2 += p.b;
        const double i2 = std::floor(d2);
        d2 -= i2;
        h2 = (int)i2;
        t2 = d2 * d2 * d2 * (d2 * (d2 * 6.0 - 15.0) + 10.0);
    }

    d1 += p.a;
    d3 += p.c;
    const double i1 = std::floor(d1), i3 = std::floor(d3);
    d1 -= i1;
    d3 -= i3;
    const int h1 = (int)i1, h3 = (int)i3;
    const double t1 = d1 * d1 * d1 * (d1 * (d1 * 6.0 - 15.0) + 10.0);
    const double t3 = d3 * d3 * d3 * (d3 * (d3 * 6.0 - 15.0) + 10.0);

    const u8* idx = p.perm;
    // 查找链语义对齐 noise.c L152-171（v4..v7 -> g1..g8，见 biome_noise.py L379-396）
    const int v1a = (idx[h1 & 0xFF] + h2) & 0xFF;
    const int v1b = (idx[(h1 + 1) & 0xFF] + h2) & 0xFF;
    const int v2a = (idx[v1a] + h3) & 0xFF;
    const int v2b = (idx[v1a + 1] + h3) & 0xFF;
    const int v3a = (idx[v1b] + h3) & 0xFF;
    const int v3b = (idx[v1b + 1] + h3) & 0xFF;
    const int g1 = idx[v2a], g2 = idx[v2a + 1];
    const int g3 = idx[v2b], g4 = idx[v2b + 1];
    const int g5 = idx[v3a], g6 = idx[v3a + 1];
    const int g7 = idx[v3b], g8 = idx[v3b + 1];

    double l1 = indexed_lerp(g1, d1, d2, d3);
    double l5 = indexed_lerp(g2, d1, d2, d3 - 1.0);
    double l2 = indexed_lerp(g5, d1 - 1.0, d2, d3);
    double l6 = indexed_lerp(g6, d1 - 1.0, d2, d3 - 1.0);
    double l3 = indexed_lerp(g3, d1, d2 - 1.0, d3);
    double l7 = indexed_lerp(g4, d1, d2 - 1.0, d3 - 1.0);
    double l4 = indexed_lerp(g7, d1 - 1.0, d2 - 1.0, d3);
    double l8 = indexed_lerp(g8, d1 - 1.0, d2 - 1.0, d3 - 1.0);

    l1 += t1 * (l2 - l1);
    l3 += t1 * (l4 - l3);
    l5 += t1 * (l6 - l5);
    l7 += t1 * (l8 - l7);
    l1 += t2 * (l3 - l1);
    l5 += t2 * (l7 - l5);
    const double rv = l1 + t3 * (l5 - l1);
    DBG("    spl exit rv=%.6f\n", rv);
    return rv;
}

// ===========================================================================
// 八度 / 双 Perlin（noise.c xOctaveInit / xDoublePerlinInit / sampleDoublePerlin）
// ===========================================================================

struct Octave {
    Perlin p;
    double amp, lac;
};

struct OctNoise {
    Octave oct[9];   // amplitudes 最长 9（continentalness）
    int n = 0;
};

static void x_octave_init(XR& xr, const double* amps, int namps, int omin,
                          OctNoise& on) {
    const double lacuna = LACUNA_INI[-omin];
    const double persist = PERSIST_INI[namps];
    const u64 xlo = xr_next_long(xr);
    const u64 xhi = xr_next_long(xr);
    on.n = 0;
    double lac = lacuna, per = persist;
    for (int i = 0; i < namps; ++i) {
        DBG("  oct i=%d n=%d amps=%.2f begin\n", i, on.n, amps[i]);
        if (amps[i] != 0.0) {
            const auto& md = MD5_OCTAVE_N[12 + omin + i];
            DBG("  oct i=%d mdidx=%d\n", i, 12 + omin + i);
            XR pxr{xlo ^ md.lo, xhi ^ md.hi};
            on.oct[on.n].amp = amps[i] * per;
            on.oct[on.n].lac = lac;
            DBG("  oct i=%d perlin call\n", i);
            x_perlin_init(pxr, on.oct[on.n].p);
            DBG("  oct i=%d perlin done\n", i);
            ++on.n;
        }
        lac *= 2.0;
        per *= 0.5;
    }
}

static double sample_octave(const OctNoise& on, double x, double y, double z) {
    // noise.h maintainPrecision 为恒等（L38-45），直接累加
    double v = 0.0;
    for (int i = 0; i < on.n; ++i) {
        const Octave& o = on.oct[i];
        v += o.amp * sample_perlin(o.p, x * o.lac, y * o.lac, z * o.lac);
    }
    return v;
}

struct DPN {
    OctNoise oa, ob;
    double amplitude;
};

static void x_double_perlin_init(XR& xr, const ClimateDef& cd, DPN& dpn) {
    x_octave_init(xr, cd.amps, cd.namps, cd.omin, dpn.oa);
    x_octave_init(xr, cd.amps, cd.namps, cd.omin, dpn.ob);
    int lo_i = 0, hi_i = cd.namps;
    while (hi_i > 0 && cd.amps[hi_i - 1] == 0.0) --hi_i;
    while (lo_i < hi_i && cd.amps[lo_i] == 0.0) ++lo_i;
    dpn.amplitude = AMP_INI[hi_i - lo_i];
}

static inline double sample_double_perlin(const DPN& dpn, double x, double y, double z) {
    // noise.c L562-572：全程 double，f = 337/331
    DBG("  dpn enter oa.n=%d ob.n=%d\n", dpn.oa.n, dpn.ob.n);
    constexpr double F = 337.0 / 331.0;
    double v = sample_octave(dpn.oa, x, y, z);
    v += sample_octave(dpn.ob, x * F, y * F, z * F);
    DBG("  dpn exit v=%.6f\n", v);
    return v * dpn.amplitude;
}

// ===========================================================================
// depth 样条（biomenoise.c getOffsetValue / initBiomeNoise / getSpline，float32 域）
// ===========================================================================

enum SplineType : int { ST_CONT = 0, ST_EROS = 1, ST_RIDGE = 2, ST_WEIRD = 3 };

struct SNode;
struct SPt {
    float loc;
    const SNode* val;
    float der;
};
struct SNode {
    bool fix;
    float fval;          // fix 节点
    SplineType typ;      // list 节点
    std::unique_ptr<SPt[]> pts;   // 堆分配，地址终身稳定
    int npts;
};

static inline float fget_offset_value(float weirdness, float continentalness) {
    // biomenoise.c getOffsetValue（L966-976），全程 float32
    const float f0 = 1.0f - ((1.0f - continentalness) * 0.5f);
    const float f1 = 0.5f * (1.0f - continentalness);
    const float f2 = (weirdness + 1.17f) * 0.46082947f;
    const float off = f2 * f0 - f1;
    if (weirdness < -0.7f) {
        return off > -0.2222f ? off : -0.2222f;
    }
    return off > 0.0f ? off : 0.0f;
}

struct SplineBuilder {
    // 全部节点堆分配并由 builder 持有：地址终身稳定（deque/vector 均不可靠）
    std::vector<std::unique_ptr<SNode>> nd;

    SNode* fix(float v) {
        auto n = std::make_unique<SNode>();
        n->fix = true;
        n->fval = v;
        n->npts = 0;
        SNode* raw = n.get();
        nd.push_back(std::move(n));
        return raw;
    }
    SNode* list(SplineType t, const std::vector<SPt>& items) {
        auto n = std::make_unique<SNode>();
        n->fix = false;
        n->typ = t;
        n->npts = (int)items.size();
        n->pts = std::make_unique<SPt[]>(items.size());
        for (size_t i = 0; i < items.size(); ++i) {
            n->pts[i] = items[i];
        }
        SNode* raw = n.get();
        nd.push_back(std::move(n));
        return raw;
    }
};

// createSpline(JaggedRange/…, cubiomes 命名 38219)（biomenoise.c L1016-1048）
static SNode* create_spline_38219(SplineBuilder& b, float f, bool bl) {
    const float i_v = fget_offset_value(-1.0f, f);
    const float k_v = fget_offset_value(1.0f, f);
    const float u_v = 0.5f * (1.0f - f);
    const float l_v = u_v / (0.46082947f * (1.0f - ((1.0f - f) * 0.5f))) - 1.17f;
    if (l_v > -0.65f && l_v < 1.0f) {
        const float u2 = fget_offset_value(-0.65f, f);
        const float p_v = fget_offset_value(-0.75f, f);
        const float q = (p_v - i_v) * 4.0f;
        const float r_v = fget_offset_value(l_v, f);
        const float s = (k_v - r_v) / (1.0f - l_v);
        std::vector<SPt> pts;
        pts.push_back({-1.0f, b.fix(i_v), q});
        pts.push_back({-0.75f, b.fix(p_v), 0.0f});
        pts.push_back({-0.65f, b.fix(u2), 0.0f});
        pts.push_back({l_v - 0.01f, b.fix(r_v), 0.0f});
        pts.push_back({l_v, b.fix(r_v), s});
        pts.push_back({1.0f, b.fix(k_v), s});
        return b.list(ST_RIDGE, pts);
    }
    const float u2 = (k_v - i_v) * 0.5f;
    std::vector<SPt> pts;
    if (bl) {
        const float v = i_v > 0.2f ? i_v : 0.2f;
        pts.push_back({-1.0f, b.fix(v), 0.0f});
        // C: lerp(0.5F, i, k) double 运算后截为 float32
        const float mid = (float)((double)i_v + 0.5 * ((double)k_v - (double)i_v));
        pts.push_back({0.0f, b.fix(mid), u2});
    } else {
        pts.push_back({-1.0f, b.fix(i_v), u2});
    }
    pts.push_back({1.0f, b.fix(k_v), u2});
    return b.list(ST_RIDGE, pts);
}

// createFlatOffsetSpline（biomenoise.c L1050-1063）
static SNode* create_flat_offset_spline(SplineBuilder& b, float f, float g,
                                        float h, float i, float j, float k) {
    float l_v = (g - f) * 0.5f;
    if (l_v < k) l_v = k;
    const float m = (h - g) * 5.0f;   // C: m = 5.0F * (h - g)
    std::vector<SPt> pts;
    pts.push_back({-1.0f, b.fix(f), l_v});
    pts.push_back({-0.4f, b.fix(g), l_v < m ? l_v : m});
    pts.push_back({0.0f, b.fix(h), m});
    pts.push_back({0.4f, b.fix(i), (i - h) * 2.0f});
    pts.push_back({1.0f, b.fix(j), (j - i) * 0.7f});
    return b.list(ST_RIDGE, pts);
}

// createLandSpline（biomenoise.c L978-1014）
static SNode* create_land_spline(SplineBuilder& b, float f, float g, float h,
                                 float i, float j, float k, bool bl) {
    const double F06 = (double)0.6f;   // np.float32(0.6) 提升 double
    SNode* sp1 = create_spline_38219(b, (float)(F06 + (double)i * (1.5 - F06)), bl);
    SNode* sp2 = create_spline_38219(b, (float)(F06 + (double)i * (1.0 - F06)), bl);
    SNode* sp3 = create_spline_38219(b, i, bl);
    const float ih = i * 0.5f;
    SNode* sp4 = create_flat_offset_spline(b, f - 0.15f, ih, ih, ih, i * 0.6f, 0.5f);
    SNode* sp5 = create_flat_offset_spline(b, f, j * i, g * i, ih, i * 0.6f, 0.5f);
    SNode* sp6 = create_flat_offset_spline(b, f, j, j, g, h, 0.5f);
    SNode* sp9 = create_flat_offset_spline(b, -0.02f, k, k, g, h, 0.0f);
    std::vector<SPt> pts8;
    pts8.push_back({-1.0f, b.fix(f), 0.0f});
    pts8.push_back({-0.4f, sp6, 0.0f});
    pts8.push_back({0.0f, b.fix(h + 0.07f), 0.0f});
    SNode* sp8 = b.list(ST_RIDGE, pts8);

    std::vector<SPt> pts;
    pts.push_back({-0.85f, sp1, 0.0f});
    pts.push_back({-0.7f, sp2, 0.0f});
    pts.push_back({-0.4f, sp3, 0.0f});
    pts.push_back({-0.35f, sp4, 0.0f});
    pts.push_back({-0.1f, sp5, 0.0f});
    pts.push_back({0.2f, sp6, 0.0f});
    if (bl) {
        pts.push_back({0.4f, sp6, 0.0f});
        pts.push_back({0.45f, sp8, 0.0f});
        pts.push_back({0.55f, sp8, 0.0f});
        pts.push_back({0.58f, sp6, 0.0f});
    }
    pts.push_back({0.7f, sp9, 0.0f});
    return b.list(ST_EROS, pts);
}

// initBiomeNoise 主体（biomenoise.c L1112-1137）
static const SNode* build_spline_root(SplineBuilder& b) {
    SNode* sp1 = create_land_spline(b, -0.15f, 0.00f, 0.0f, 0.1f, 0.00f, -0.03f, false);
    SNode* sp2 = create_land_spline(b, -0.10f, 0.03f, 0.1f, 0.1f, 0.01f, -0.03f, false);
    SNode* sp3 = create_land_spline(b, -0.10f, 0.03f, 0.1f, 0.7f, 0.01f, -0.03f, true);
    SNode* sp4 = create_land_spline(b, -0.05f, 0.03f, 0.1f, 1.0f, 0.01f, 0.01f, true);
    std::vector<SPt> pts;
    pts.push_back({-1.10f, b.fix(0.044f), 0.0f});
    pts.push_back({-1.02f, b.fix(-0.2222f), 0.0f});
    pts.push_back({-0.51f, b.fix(-0.2222f), 0.0f});
    pts.push_back({-0.44f, b.fix(-0.12f), 0.0f});
    pts.push_back({-0.18f, b.fix(-0.12f), 0.0f});
    pts.push_back({-0.16f, sp1, 0.0f});
    pts.push_back({-0.15f, sp1, 0.0f});
    pts.push_back({-0.10f, sp2, 0.0f});
    pts.push_back({0.25f, sp3, 0.0f});
    pts.push_back({1.00f, sp4, 0.0f});
    const SNode* rn = b.list(ST_CONT, pts);
    return rn;
}

static const SNode* spline_root() {
    // magic static：线程安全的一次构建；builder 静态存储期 + 堆分配节点
    // 保证所有节点/点数组指针终身稳定
    DBG("spline_root enter\n");
    static const SNode* root = [] {
        static SplineBuilder b;
        const SNode* r = build_spline_root(b);
        DBG("spline_root built nd=%zu\n", b.nd.size());
        return r;
    }();
    DBG("spline_root exit root=%p\n", (const void*)root);
    return root;
}

// getSpline（biomenoise.c L1074-1110）：中间 float32；最终插值 double
static float get_spline(const SNode* sp, const float vals[4]) {
    DBG("  gs enter sp=%p fix=%d typ=%d npts=%d\n", (const void*)sp,
        (int)sp->fix, (int)sp->typ, sp->npts);
    if (sp->fix) return sp->fval;
    const float f = vals[sp->typ];
    const SPt* pts = sp->pts.get();
    const int n = sp->npts;
    int i = 0;
    while (i < n && pts[i].loc < f) ++i;
    DBG("  gs pick i=%d\n", i);
    if (i == 0 || i == n) {
        if (i) --i;
        const SPt& p = pts[i];
        DBG("  gs edge i=%d val=%p\n", i, (const void*)p.val);
        const float r = get_spline(p.val, vals) + p.der * (f - p.loc);
        DBG("  gs edge ret=%.6f\n", r);
        return r;
    }
    const float g = pts[i - 1].loc;
    const float h = pts[i].loc;
    const float k = (f - g) / (h - g);
    const float der_l = pts[i - 1].der;
    const float der_m = pts[i].der;
    DBG("  gs inner nl=%p nr=%p\n", (const void*)pts[i-1].val, (const void*)pts[i].val);
    const float nv = get_spline(pts[i - 1].val, vals);
    const float o = get_spline(pts[i].val, vals);
    const float p_v = der_l * (h - g) - (o - nv);
    const float q = -der_m * (h - g) + (o - nv);
    // lerp(k,n,o) / lerp(k,p,q)：double；k*(1-k)：float 域
    const double kf = (double)k;
    const double a = (double)nv + kf * ((double)o - (double)nv);
    const float b1 = k * (1.0f - k);
    const double b2 = (double)p_v + kf * ((double)q - (double)p_v);
    const float rv = (float)(a + (double)b1 * b2);
    DBG("  gs inner ret=%.6f\n", rv);
    return rv;
}

// ===========================================================================
// 气候采样与 btree 最近邻（biomenoise.c sampleBiomeNoise / climateToBiome）
// ===========================================================================

static inline i64 quant_np(double v) {
    // C: (int64_t)(10000.0F * v)：float32 乘法（v 先截为 float32）后向零截断
    return (i64)(10000.0f * (float)v);
}

struct BiomeCtx {
    DPN climate[NP_MAX];
};

static void ctx_init(BiomeCtx& ctx, u64 seed) {
    DBG("ctx_init enter seed=%llu\n", (unsigned long long)seed);
    u64 lo, hi;
    x_set_seed(seed, lo, hi);
    XR xr{lo, hi};
    const u64 xlo = xr_next_long(xr);
    const u64 xhi = xr_next_long(xr);
    DBG("ctx_init xlo=%llu xhi=%llu\n", (unsigned long long)xlo, (unsigned long long)xhi);
    // init_climate_seed：SHIFT/WEIRDNESS 固定，T/H/C/E 走 SMALL（large 暂不支持）
    const ClimateDef* defs[NP_MAX] = {
        &CLIMATE_SMALL[NP_TEMPERATURE], &CLIMATE_SMALL[NP_HUMIDITY],
        &CLIMATE_SMALL[NP_CONTINENTALNESS], &CLIMATE_SMALL[NP_EROSION],
        &CLIMATE_SMALL[NP_SHIFT], &CLIMATE_SMALL[NP_WEIRDNESS],
    };
    for (int np = 0; np < NP_MAX; ++np) {
        DBG("ctx_init param %d begin\n", np);
        XR pxr{xlo ^ defs[np]->md5lo, xhi ^ defs[np]->md5hi};
        x_double_perlin_init(pxr, *defs[np], ctx.climate[np]);
        DBG("ctx_init param %d done\n", np);
    }
}

static void climate_point(const BiomeCtx& ctx, double x, double z,
                          double y, i64 np6[6]) {
    DBG("climate_point enter x=%.1f z=%.1f\n", x, z);
    const DPN& sh = ctx.climate[NP_SHIFT];
    // shift 扰动（L1156-1157）：第二次采样实参 (z, x, 0)
    const double px = x + sample_double_perlin(sh, x, 0.0, z) * 4.0;
    const double pz = z + sample_double_perlin(sh, z, x, 0.0) * 4.0;

    const double c = sample_double_perlin(ctx.climate[NP_CONTINENTALNESS], px, 0.0, pz);
    const double e = sample_double_perlin(ctx.climate[NP_EROSION], px, 0.0, pz);
    const double w = sample_double_perlin(ctx.climate[NP_WEIRDNESS], px, 0.0, pz);

    // depth（L1164-1173）：全程 float32 的 ridge + off 样条
    const float c_f = (float)c, e_f = (float)e, w_f = (float)w;
    const float ridge = -3.0f * (std::fabs(std::fabs(w_f) - 0.6666667f) - 0.33333334f);
    const float vals[4] = {c_f, e_f, ridge, w_f};
    const float off32 = get_spline(spline_root(), vals);
    // C: double off = getSpline(...) + 0.015F（0.015F 提升为 double）
    const double off = (double)off32 + (double)0.015f;
    // depth 项：d = 1.0 - (y*4)/128.0 - 83.0/160.0 + off
    // y 为噪声格坐标；地表方块层 y>>2 后约 16~24，与游戏 F3 群系判定一致
    const double d = 1.0 - (y * 4.0) / 128.0 - 83.0 / 160.0 + off;

    const double t = sample_double_perlin(ctx.climate[NP_TEMPERATURE], px, 0.0, pz);
    const double h = sample_double_perlin(ctx.climate[NP_HUMIDITY], px, 0.0, pz);

    np6[0] = quant_np(t);
    np6[1] = quant_np(h);
    np6[2] = quant_np(c);
    np6[3] = quant_np(e);
    np6[4] = quant_np(d);
    np6[5] = quant_np(w);
}

// ---------------------------------------------------------------------------
// btree（数据由 Python set_btree 推入；搜索逻辑 biomenoise.c L1369-1484）
// ---------------------------------------------------------------------------

struct BTreeStore {
    int order = 0;
    std::vector<u32> steps;
    std::vector<i64> param;    // 每项 {lo, hi}
    std::vector<u64> nodes;
};

static BTreeStore g_btrees[6];   // 0=btree18 1=btree192 2=btree19 3=btree20 4=btree21wd 5=btree262

struct BTreeC {
    int order;
    const u32* steps;
    int nsteps;
    const i64* param;
    const u64* nodes;
    int len;
};

static inline u64 get_np_dist(const BTreeC& bt, const i64* np6, int idx) {
    const u64 node = bt.nodes[idx];
    u64 ds = 0;
    for (int i = 0; i < 6; ++i) {
        const int pidx = (int)((node >> (8 * i)) & 0xFF);
        const i64 lo = bt.param[pidx * 2];
        const i64 hi = bt.param[pidx * 2 + 1];
        const i64 a = np6[i] - hi;
        const i64 b = lo - np6[i];
        const u64 dd = a > 0 ? (u64)a : (b > 0 ? (u64)b : 0);
        ds += dd * dd;
    }
    return ds;
}

static int resulting_node(const BTreeC& bt, const i64* np6, int idx, int alt,
                          u64 ds, int depth) {
    if (bt.steps[depth] == 0) return idx;
    int step = bt.steps[depth];
    ++depth;
    while (idx + step >= bt.len) {
        step = bt.steps[depth];
        ++depth;
    }
    const u64 node = bt.nodes[idx];
    int inner = (int)((node >> 48) & 0xFFFF);
    int leaf = alt;
    for (int i = 0; i < bt.order; ++i) {
        const u64 ds_inner = get_np_dist(bt, np6, inner);
        if (ds_inner < ds) {
            const int leaf2 = resulting_node(bt, np6, inner, leaf, ds, depth);
            const u64 ds_leaf2 = (inner == leaf2) ? ds_inner : get_np_dist(bt, np6, leaf2);
            if (ds_leaf2 < ds) {
                ds = ds_leaf2;
                leaf = leaf2;
            }
        }
        inner += step;
        if (inner >= bt.len) break;
    }
    return leaf;
}

static inline int climate_to_biome(const BTreeC& bt, const i64* np6) {
    const int idx = resulting_node(bt, np6, 0, 0, ~(u64)0, 0);
    return (int)((bt.nodes[idx] >> 48) & 0xFF);
}

// ===========================================================================
// 精化枚举（多线程）
// ===========================================================================

struct ObsRow {
    i64 nx, nz;
    i64 ny;      // 噪声格 y（方块 y>>2；地面观测与 F3 判定一致）
    int bid;
};

// 取消检查点：每 16 个高位读一次取消标志（无锁，开销可忽略）
static constexpr u64 CANCEL_MASK = 15ULL;
// 进度上报批量（原子计数按单次 (high, candidate) 迭代累加）
static constexpr u64 PROG_BATCH = 4096ULL;

static void refine_worker(const std::vector<u64>& cands,
                          const std::vector<ObsRow>& obs,
                          const BTreeC& bt, u64 begin, u64 end,
                          std::atomic<u64>& done_cnt,
                          const std::atomic<bool>& cancelled,
                          std::vector<u64>& out, std::string& err) {
    const size_t n_obs = obs.size();
    const size_t n_cands = cands.size();
    try {
        thread_local BiomeCtx ctx;
        i64 np6[6];
        u64 iter = 0;   // 本线程迭代计数（进度批量上报用）
        for (u64 high = begin; high < end; ++high) {
            if ((high & CANCEL_MASK) == 0 &&
                    cancelled.load(std::memory_order_relaxed)) {
                return;
            }
            for (size_t ci = 0; ci < n_cands; ++ci) {
                const u64 seed = (high << 48) | cands[ci];
                ctx_init(ctx, seed);
                bool alive = true;
                for (size_t oi = 0; oi < n_obs; ++oi) {
                    climate_point(ctx, (double)obs[oi].nx,
                                  (double)obs[oi].nz,
                                  (double)obs[oi].ny, np6);
                    if (climate_to_biome(bt, np6) != obs[oi].bid) {
                        alive = false;   // all() 语义：逐点短路
                        break;
                    }
                }
                if (alive) {
                    out.push_back(seed);
                }
                ++iter;
                if ((iter & (PROG_BATCH - 1)) == 0) {
                    done_cnt.fetch_add(PROG_BATCH, std::memory_order_relaxed);
                }
            }
        }
        // 补报非批量对齐余数（done 总量 = 枚举迭代数）
        done_cnt.fetch_add(iter & (PROG_BATCH - 1), std::memory_order_relaxed);
    } catch (const std::exception& e) {
        err = e.what();
    } catch (...) {
        err = "refine worker: unknown error";
    }
}

// ---------------------------------------------------------------------------
// btree 数据推入（Python 端从 btree_tables.npz 读取后调用）
// ---------------------------------------------------------------------------

// 版本键 -> 槽位（与 biome_noise.VERSION_TO_BTREE 对应）
static int btree_slot(const std::string& name) {
    if (name == "btree18") return 0;
    if (name == "btree192") return 1;
    if (name == "btree19") return 2;
    if (name == "btree20") return 3;
    if (name == "btree21wd") return 4;
    if (name == "btree262") return 5;
    return -1;
}

static void set_btree(const std::string& name, py::array_t<u32> steps,
                      py::array_t<i64, py::array::c_style | py::array::forcecast> param,
                      py::array_t<u64> nodes, int order) {
    const int slot = btree_slot(name);
    if (slot < 0) {
        throw std::runtime_error("unknown btree name: " + name);
    }
    if (param.ndim() != 2 || param.shape(1) != 2) {
        throw std::runtime_error("param must be (N,2) int64");
    }
    BTreeStore& st = g_btrees[slot];
    st.order = order;
    st.steps.assign(steps.data(), steps.data() + steps.size());
    st.param.assign(param.data(), param.data() + param.size());
    st.nodes.assign(nodes.data(), nodes.data() + nodes.size());
}

static const BTreeC& get_btree_c(int slot) {
    const BTreeStore& st = g_btrees[slot];
    if (st.nodes.empty()) {
        throw std::runtime_error("btree not initialized (call set_btree first)");
    }
    static thread_local BTreeC view;
    view.order = st.order;
    view.steps = st.steps.data();
    view.nsteps = (int)st.steps.size();
    view.param = st.param.data();
    view.nodes = st.nodes.data();
    view.len = (int)st.nodes.size();
    return view;
}

// ---------------------------------------------------------------------------
// 导出函数：refine_full（多线程精化枚举）
// ---------------------------------------------------------------------------

static py::array_t<u64> refine_full(
        py::sequence cands_seq,
        py::sequence obs_seq,
        const std::string& btree_name,
        int high_span,
        py::object on_progress,
        py::object check_cancel) {
    // ---- 解析参数（持 GIL）----
    const size_t n_cands = static_cast<size_t>(cands_seq.size());
    std::vector<u64> cands_buf(n_cands);
    {
        size_t i = 0;
        for (auto item : cands_seq) {
            cands_buf[i++] = item.cast<u64>() & 0xFFFFFFFFFFFFULL;  // 48 位掩码
        }
    }
    std::vector<ObsRow> rows;
    rows.reserve(obs_seq.size());
    for (auto item : obs_seq) {
        py::dict d = item.cast<py::dict>();
        ObsRow ob;
        ob.nx = d["nx"].cast<i64>();
        ob.nz = d["nz"].cast<i64>();
        // y 为可选键（旧格式 dict 无 y）——用 attr("get") 兼容，缺省 0
        py::object pyy = d.attr("get")("y", 0);
        ob.ny = pyy.is_none() ? 0 : pyy.cast<i64>();
        ob.bid = d["biome_id"].cast<int>();
        rows.push_back(ob);
    }
    const int slot = btree_slot(btree_name);
    if (slot < 0) {
        throw std::runtime_error("unknown btree name: " + btree_name);
    }
    if (rows.empty() || n_cands == 0 || high_span <= 0) {
        return py::array_t<u64>({static_cast<py::ssize_t>(0)});
    }

    const BTreeC& bt = get_btree_c(slot);
    const u64 total_iters = static_cast<u64>(n_cands) * static_cast<u64>(high_span);

    unsigned hc = std::thread::hardware_concurrency();
    if (hc == 0) hc = 4;
    if (hc > 64) hc = 64;
    // 分片数不超过高位总量，保证每片非空
    const int n_threads = static_cast<int>(std::min<u64>(hc, (u64)high_span));

    std::vector<std::vector<u64>> buckets(n_threads);
    std::vector<std::string> errs(n_threads);
    std::atomic<u64> done_cnt{0};
    std::atomic<bool> cancelled{false};
    std::atomic<bool> monitor_done{false};
    std::mutex mon_mtx;
    std::condition_variable mon_cv;

    const bool has_progress = !on_progress.is_none();
    const bool has_cancel = !check_cancel.is_none();

    // ---- 释放 GIL：spawn + join 全程不触碰 Python 对象 ----
    {
        py::gil_scoped_release release;

        std::thread monitor([&]() {
            u64 last = 0;
            std::unique_lock<std::mutex> lk(mon_mtx);
            while (true) {
                if (mon_cv.wait_for(lk, std::chrono::milliseconds(30), [&] {
                        return monitor_done.load(std::memory_order_relaxed);
                    })) {
                    break;
                }
                lk.unlock();
                if (has_cancel) {
                    bool stop = false;
                    try {
                        py::gil_scoped_acquire acquire;
                        stop = check_cancel().cast<bool>();
                    } catch (...) {
                        // 取消探测失败不致命，忽略
                    }
                    if (stop) {
                        cancelled.store(true, std::memory_order_relaxed);
                        break;
                    }
                }
                if (has_progress) {
                    u64 now = done_cnt.load(std::memory_order_relaxed);
                    if (now != last) {
                        last = now;
                        try {
                            py::gil_scoped_acquire acquire;
                            on_progress(static_cast<long long>(now),
                                        static_cast<long long>(total_iters),
                                        "refine");
                        } catch (...) {
                            // 进度回调异常不影响计算
                        }
                    }
                }
                lk.lock();
            }
        });

        std::vector<std::thread> pool;
        const u64 per = ((u64)high_span + n_threads - 1) / n_threads;
        pool.reserve(n_threads);
        for (int t = 0; t < n_threads; ++t) {
            const u64 begin = static_cast<u64>(t) * per;
            const u64 end = std::min<u64>((u64)high_span, begin + per);
            if (begin >= end) {
                pool.emplace_back([]() {});
                continue;
            }
            pool.emplace_back([&cands_buf, &rows, &bt, &buckets, &errs, &done_cnt,
                               &cancelled, high_span, begin, end, t]() {
                refine_worker(cands_buf, rows, bt, begin, end,
                              done_cnt, cancelled, buckets[t], errs[t]);
            });
        }
        for (auto& th : pool) {
            th.join();
        }
        monitor_done.store(true, std::memory_order_relaxed);
        mon_cv.notify_all();
        monitor.join();
    }
    // ---- GIL 已重新持有：汇总结果 ----
    for (const auto& e : errs) {
        if (!e.empty()) {
            throw std::runtime_error("biome refine native: " + e);
        }
    }
    size_t total = 0;
    for (const auto& b : buckets) {
        total += b.size();
    }
    std::vector<u64> all;
    all.reserve(total);
    for (auto& b : buckets) {
        all.insert(all.end(), b.begin(), b.end());
    }
    std::sort(all.begin(), all.end());
    py::array_t<u64> out_arr({static_cast<py::ssize_t>(all.size())});
    if (!all.empty()) {
        std::memcpy(out_arr.request().ptr, all.data(), all.size() * sizeof(u64));
    }
    return out_arr;
}

// ---------------------------------------------------------------------------
// 单点采样导出（对拍/调试用：与 Python biome_noise 逐值比对）
// ---------------------------------------------------------------------------

static py::dict sample_point(u64 seed, const std::string& btree_name,
                             i64 x, i64 y, i64 z) {
    const int slot = btree_slot(btree_name);
    if (slot < 0) {
        throw std::runtime_error("unknown btree name: " + btree_name);
    }
    DBG("[1] enter slot=%d seed=%llu x=%lld y=%lld z=%lld\n", slot,
        (unsigned long long)seed, (long long)x, (long long)y, (long long)z);
    const BTreeC& bt = get_btree_c(slot);
    DBG("[2] btree len=%d order=%d nsteps=%d\n", bt.len, bt.order, bt.nsteps);
    BiomeCtx ctx;
    DBG("[3] ctx declared size=%zu\n", sizeof(BiomeCtx));
    ctx_init(ctx, seed);
    DBG("[4] ctx_init done\n");
    i64 np6[6];
    climate_point(ctx, (double)x, (double)z, (double)y, np6);
    DBG("[5] climate_point done\n");
    const int bid = climate_to_biome(bt, np6);
    DBG("[6] bid=%d\n", bid);
    py::dict out;
    out["np6"] = py::make_tuple(np6[0], np6[1], np6[2], np6[3], np6[4], np6[5]);
    out["biome_id"] = bid;
    return out;
}

// ---------------------------------------------------------------------------
// 模块定义
// ---------------------------------------------------------------------------
PYBIND11_MODULE(_biome_refine, m) {
    m.doc() = "SeedReverser 二期世界种子精化的 C++ 多线程扩展（语义基准 biome_noise.py）";
    m.def("set_btree", &set_btree,
          py::arg("name"), py::arg("steps"), py::arg("param"),
          py::arg("nodes"), py::arg("order"),
          "推入一个版本的 btree 数据（param 须为 (N,2) int64）");
    m.def("refine_full", &refine_full,
          py::arg("candidates"),
          py::arg("obs"),                 // dict: nx/nz/y(可选,缺省0)/biome_id（噪声格坐标）
          py::arg("btree_name"),
          py::arg("high_span"),           // 枚举高 16 位区间大小（<= 65536）
          py::arg("on_progress") = py::none(),
          py::arg("check_cancel") = py::none(),
          "枚举 high16 ∈ [0, high_span)，返回通过全部观测的 64 位种子"
          "（升序 uint64 numpy 数组）。obs 须先由 Python 端做 >>2 换算。");
    m.def("sample_point", &sample_point,
          py::arg("seed"), py::arg("btree_name"), py::arg("x"), py::arg("y"),
          py::arg("z"),
          "单点采样（调试/对拍）：返回 dict(np6=六参数元组, biome_id=int)");
}
