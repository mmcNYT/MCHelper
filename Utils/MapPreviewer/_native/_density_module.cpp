// _density_module.cpp -- MapPreviewer 26.2 density engine native extension
#pragma once

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#include <array>
#include <unordered_map>

namespace py = pybind11;
using u64 = std::uint64_t;
using i64 = std::int64_t;
using u32 = std::uint32_t;
using i32 = std::int32_t;
using u8 = std::uint8_t;
using i16 = std::int16_t;
using f32 = float;
using f64 = double;

static constexpr u64 MASK64 = ~0ULL;
static constexpr u32 MASK32 = 0xFFFFFFFFu;


static inline double clamp_val(double v, double lo, double hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}
static inline int floordiv(int a, int b) {
    int q = a / b;
    if ((a % b != 0) && ((a < 0) != (b < 0))) q--;
    return q;
}
static inline double map_lin(double v, double fmin, double fmax, double tmin, double tmax) {
    if (fmax == fmin) return tmin;
    double t = (v - fmin) / (fmax - fmin);
    return tmin + t * (tmax - tmin);
}
static inline int quantize(double v, int q) {
    return static_cast<int>(std::floor(v / q) * q);
}

static inline u64 rotl64(u64 x, int k) { return (x << k) | (x >> (64 - k)); }
static inline i64 i64_of(u64 v) { return static_cast<i64>(v); }
static inline i64 wrap_mul(i64 a, i64 b) {
    return static_cast<i64>(static_cast<u64>(a) * static_cast<u64>(b));
}
static inline i64 wrap_add(i64 a, i64 b) {
    return static_cast<i64>(static_cast<u64>(a) + static_cast<u64>(b));
}
static inline i32 i32_wrap(i64 v) { return static_cast<i32>(static_cast<u32>(v)); }

// ===========================================================================
// RandomSupport / Xoroshiro128++
// ===========================================================================

static inline u64 mix_stafford13(u64 z) {
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static inline void upgrade_seed128(u64 seed, u64& lo, u64& hi) {
    u64 l = seed ^ 0x6A09E667F3BCC909ULL;
    u64 h = l + 0x9E3779B97F4A7C15ULL;
    lo = mix_stafford13(l);
    hi = mix_stafford13(h);
}

struct Xoroshiro {
    u64 lo = 0, hi = 0;

    void from_seed(i64 seed) { upgrade_seed128(static_cast<u64>(seed), lo, hi); }
    void set(u64 l, u64 h) { lo = l; hi = h; }

    u64 next_long() {
        u64 s0 = lo, s1 = hi;
        u64 result = rotl64(s0 + s1, 17) + s0;
        s1 ^= s0;
        lo = rotl64(s0, 49) ^ s1 ^ (s1 << 21);
        hi = rotl64(s1, 28);
        return result;
    }

    u32 next_int() { return static_cast<u32>(next_long()); }

    u32 next_int_bound(u32 bound) {
        u64 random_bits = static_cast<u64>(next_int());
        u64 mult = random_bits * bound;
        u64 frac = mult & 0xFFFFFFFFULL;
        if (frac < bound) {
            u64 threshold = (0x100000000ULL - bound) % bound;
            while (frac < threshold) {
                random_bits = static_cast<u64>(next_int());
                mult = random_bits * bound;
                frac = mult & 0xFFFFFFFFULL;
            }
        }
        return static_cast<u32>(mult >> 32);
    }

    double next_double() { return static_cast<double>(next_long() >> 11) * 1.1102230246251565e-16; }
    float next_float() { return static_cast<float>(next_long() >> 40) * 5.9604645e-8f; }
    bool next_bool() { return (next_long() & 1ULL) != 0; }

    void consume(int n) { for (int i = 0; i < n; i++) next_long(); }
};

// MD5-based seedFromHashOf
static void md5_digest(const void* data, size_t len, u8 out[16]);

static inline void seed_from_hash(const std::string& name, u64& lo, u64& hi) {
    u8 d[16];
    md5_digest(name.data(), name.size(), d);
    u64 l = 0, h = 0;
    for (int i = 0; i < 8; i++) l = (l << 8) | d[i];
    for (int i = 8; i < 16; i++) h = (h << 8) | d[i];
    lo = l;
    hi = h;
}

// ===========================================================================
// MD5（RFC 1321 精简实现，仅用于 seedFromHashOf）
// ===========================================================================

struct MD5Ctx {
    u32 a = 0x67452301, b = 0xefcdab89, c = 0x98badcfe, d = 0x10325476;
    u64 len = 0;
    u8 buf[64];
    size_t fill = 0;
};

static inline u32 rol32(u32 x, int c) { return (x << c) | (x >> (32 - c)); }

static void md5_block(MD5Ctx& ctx, const u8* p) {
    static const u32 K[64] = {
        0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501,
        0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821,
        0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
        0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a,
        0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
        0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
        0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
        0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391};
    static const int S[64] = {7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
                              5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
                              4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
                              6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21};
    u32 M[16];
    for (int i = 0; i < 16; i++) {
        M[i] = static_cast<u32>(p[i * 4]) | (static_cast<u32>(p[i * 4 + 1]) << 8) |
               (static_cast<u32>(p[i * 4 + 2]) << 16) | (static_cast<u32>(p[i * 4 + 3]) << 24);
    }
    u32 A = ctx.a, B = ctx.b, C = ctx.c, D = ctx.d;
    for (int i = 0; i < 64; i++) {
        u32 F;
        int g;
        if (i < 16) {
            F = (B & C) | (~B & D);
            g = i;
        } else if (i < 32) {
            F = (D & B) | (~D & C);
            g = (5 * i + 1) % 16;
        } else if (i < 48) {
            F = B ^ C ^ D;
            g = (3 * i + 5) % 16;
        } else {
            F = C ^ (B | ~D);
            g = (7 * i) % 16;
        }
        u32 tmp = D;
        D = C;
        C = B;
        B = B + rol32(A + F + K[i] + M[g], S[i]);
        A = tmp;
    }
    ctx.a += A;
    ctx.b += B;
    ctx.c += C;
    ctx.d += D;
}

static void md5_update(MD5Ctx& ctx, const u8* data, size_t len) {
    ctx.len += len;
    size_t i = 0;
    if (ctx.fill) {
        size_t need = 64 - ctx.fill;
        size_t take = std::min(need, len);
        std::memcpy(ctx.buf + ctx.fill, data, take);
        ctx.fill += take;
        i += take;
        if (ctx.fill == 64) {
            md5_block(ctx, ctx.buf);
            ctx.fill = 0;
        }
    }
    while (i + 64 <= len) {
        md5_block(ctx, data + i);
        i += 64;
    }
    if (i < len) {
        std::memcpy(ctx.buf, data + i, len - i);
        ctx.fill = len - i;
    }
}

static void md5_final(MD5Ctx& ctx, u8 out[16]) {
    u64 bits = ctx.len * 8;
    u8 pad = 0x80;
    md5_update(ctx, &pad, 1);
    u8 zero = 0;
    while (ctx.fill != 56) md5_update(ctx, &zero, 1);
    u8 lenbuf[8];
    for (int i = 0; i < 8; i++) lenbuf[i] = static_cast<u8>((bits >> (8 * i)) & 0xFF);
    md5_update(ctx, lenbuf, 8);
    u32 v[4] = {ctx.a, ctx.b, ctx.c, ctx.d};
    for (int i = 0; i < 4; i++) {
        out[i * 4] = static_cast<u8>(v[i] & 0xFF);
        out[i * 4 + 1] = static_cast<u8>((v[i] >> 8) & 0xFF);
        out[i * 4 + 2] = static_cast<u8>((v[i] >> 16) & 0xFF);
        out[i * 4 + 3] = static_cast<u8>((v[i] >> 24) & 0xFF);
    }
}

static void md5_digest(const void* data, size_t len, u8 out[16]) {
    MD5Ctx ctx;
    md5_update(ctx, static_cast<const u8*>(data), len);
    md5_final(ctx, out);
}
// ===========================================================================
// ImprovedNoise（26.2 新算法：SimplexNoise.GRADIENT 16 项 + smoothstep）
// 逐行对照 synth/ImprovedNoise.java
// ===========================================================================

static const int GRADIENT[16][3] = {
    {1, 1, 0}, {-1, 1, 0}, {1, -1, 0}, {-1, -1, 0},
    {1, 0, 1}, {-1, 0, 1}, {1, 0, -1}, {-1, 0, -1},
    {0, 1, 1}, {0, -1, 1}, {0, 1, -1}, {0, -1, -1},
    {1, 1, 0}, {0, -1, 1}, {-1, 1, 0}, {0, -1, -1}};

static inline double gm_dot(int idx, double x, double y, double z) {
    const int* g = GRADIENT[idx & 15];
    return g[0] * x + g[1] * y + g[2] * z;
}

static inline double smoothstep(double x) {
    return x * x * x * (x * (x * 6.0 - 15.0) + 10.0);
}

static inline double m_lerp(double a, double p0, double p1) { return p0 + a * (p1 - p0); }

static inline double m_lerp3(double a1, double a2, double a3,
                             double x000, double x100, double x010, double x110,
                             double x001, double x101, double x011, double x111) {
    return m_lerp(a3, m_lerp(a2, m_lerp(a1, x000, x100), m_lerp(a1, x010, x110)),
                  m_lerp(a2, m_lerp(a1, x001, x101), m_lerp(a1, x011, x111)));
}

static inline double wrap_noise(double x) {
    return x - std::floor(x / 3.3554432E7 + 0.5) * 3.3554432E7;
}

static inline int ifloor(double v) { return static_cast<int>(std::floor(v)); }

struct ImprovedNoise {
    double xo = 0, yo = 0, zo = 0;
    u8 p[256];

    void init(Xoroshiro& rng) {
        xo = rng.next_double() * 256.0;
        yo = rng.next_double() * 256.0;
        zo = rng.next_double() * 256.0;
        for (int i = 0; i < 256; i++) p[i] = static_cast<u8>(i);
        for (int i = 0; i < 256; i++) {
            int off = static_cast<int>(rng.next_int_bound(256 - i));
            u8 t = p[i];
            p[i] = p[off + i];
            p[off + i] = t;
        }
    }

    inline int pp(int x) const { return p[x & 0xFF]; }

    double noise(double _x, double _y, double _z, double yScale, double yFudge) const {
        double x = _x + xo, y = _y + yo, z = _z + zo;
        int xf = ifloor(x), yf = ifloor(y), zf = ifloor(z);
        double xr = x - xf, yr = y - yf, zr = z - zf;
        double yrFudge = 0.0;
        if (yScale != 0.0) {
            double fudgeLimit = (yFudge >= 0.0 && yFudge < yr) ? yFudge : yr;
            yrFudge = std::floor(fudgeLimit / yScale + 1.0e-7) * yScale;
        }
        return sample_and_lerp(xf, yf, zf, xr, yr - yrFudge, zr, yr);
    }

    double sample_and_lerp(int x, int y, int z, double xr, double yr, double zr,
                           double yrOriginal) const {
        int x0 = pp(x), x1 = pp(x + 1);
        int xy00 = pp(x0 + y), xy01 = pp(x0 + y + 1);
        int xy10 = pp(x1 + y), xy11 = pp(x1 + y + 1);
        double d000 = gm_dot(pp(xy00 + z), xr, yr, zr);
        double d100 = gm_dot(pp(xy10 + z), xr - 1.0, yr, zr);
        double d010 = gm_dot(pp(xy01 + z), xr, yr - 1.0, zr);
        double d110 = gm_dot(pp(xy11 + z), xr - 1.0, yr - 1.0, zr);
        double d001 = gm_dot(pp(xy00 + z + 1), xr, yr, zr - 1.0);
        double d101 = gm_dot(pp(xy10 + z + 1), xr - 1.0, yr, zr - 1.0);
        double d011 = gm_dot(pp(xy01 + z + 1), xr, yr - 1.0, zr - 1.0);
        double d111 = gm_dot(pp(xy11 + z + 1), xr - 1.0, yr - 1.0, zr - 1.0);
        return m_lerp3(smoothstep(xr), smoothstep(yrOriginal), smoothstep(zr),
                       d000, d100, d010, d110, d001, d101, d011, d111);
    }
};

// ===========================================================================
// PerlinNoise（新初始化 / legacy 初始化两种）
// ===========================================================================

struct PerlinNoise {
    int first_octave = 0;
    std::vector<double> amplitudes;
    std::vector<ImprovedNoise> levels;
    std::vector<char> level_present;
    double lowest_freq_input = 1.0;
    double lowest_freq_value = 1.0;

    void init(Xoroshiro& rng, int firstOct, const std::vector<double>& amps, bool newInit) {
        first_octave = firstOct;
        amplitudes = amps;
        int n = static_cast<int>(amplitudes.size());
        int zeroIdx = -first_octave;
        levels.assign(n, ImprovedNoise{});
        level_present.assign(n, 0);
        if (newInit) {
            u64 plo = rng.next_long(), phi = rng.next_long();
            for (int i = 0; i < n; i++) {
                if (amplitudes[i] != 0.0) {
                    int octave = first_octave + i;
                    Xoroshiro sub;
                    u64 hlo, hhi;
                    seed_from_hash("octave_" + std::to_string(octave), hlo, hhi);
                    sub.set(hlo ^ plo, hhi ^ phi);
                    levels[i].init(sub);
                    level_present[i] = 1;
                }
            }
        } else {
            ImprovedNoise zero;
            zero.init(rng);
            if (zeroIdx >= 0 && zeroIdx < n && amplitudes[zeroIdx] != 0.0) {
                levels[zeroIdx] = zero;
                level_present[zeroIdx] = 1;
            }
            for (int i = zeroIdx - 1; i >= 0; i--) {
                if (i < n) {
                    if (amplitudes[i] != 0.0) {
                        levels[i].init(rng);
                        level_present[i] = 1;
                    } else {
                        rng.consume(262);
                    }
                } else {
                    rng.consume(262);
                }
            }
        }
        lowest_freq_input = std::pow(2.0, -zeroIdx);
        lowest_freq_value = (std::pow(2.0, n - 1)) / (std::pow(2.0, n) - 1.0);
    }

    const ImprovedNoise* octave_noise(int i) const {
        int idx = static_cast<int>(levels.size()) - 1 - i;
        if (idx < 0 || idx >= static_cast<int>(levels.size())) return nullptr;
        return level_present[idx] ? &levels[idx] : nullptr;
    }

    double get_value(double x, double y, double z, double yScale = 0.0,
                     double yFudge = 0.0) const {
        double value = 0.0, factor = lowest_freq_input, vf = lowest_freq_value;
        for (size_t i = 0; i < levels.size(); i++) {
            if (level_present[i]) {
                value += amplitudes[i] *
                         levels[i].noise(wrap_noise(x * factor), wrap_noise(y * factor),
                                          wrap_noise(z * factor), yScale * factor,
                                          yFudge * factor) *
                         vf;
            }
            factor *= 2.0;
            vf /= 2.0;
        }
        return value;
    }
};

// ===========================================================================
// NormalNoise
// ===========================================================================

struct NormalNoise {
    PerlinNoise first, second;
    double value_factor = 1.0;
    static constexpr double INPUT_FACTOR = 1.0181268882175227;

    void init(Xoroshiro& rng, int firstOct, const std::vector<double>& amps) {
        first.init(rng, firstOct, amps, true);
        second.init(rng, firstOct, amps, true);
        int nzMin = -1, nzMax = -1;
        for (size_t i = 0; i < amps.size(); i++) {
            if (amps[i] != 0.0) {
                if (nzMin < 0) nzMin = static_cast<int>(i);
                nzMax = static_cast<int>(i);
            }
        }
        int span = (nzMin >= 0) ? (nzMax - nzMin) : 0;
        double dev = 0.1 * (1.0 + 1.0 / (span + 1));
        value_factor = 0.16666666666666666 / dev;
    }

    double get_value(double x, double y, double z) const {
        return (first.get_value(x, y, z) +
                second.get_value(x * INPUT_FACTOR, y * INPUT_FACTOR, z * INPUT_FACTOR)) *
               value_factor;
    }
};

// ===========================================================================
// BlendedNoise（base_3d_noise）
// ===========================================================================

struct BlendedNoise {
    PerlinNoise min_limit, max_limit, main;
    double xz_scale = 1, y_scale = 1, xz_factor = 1, y_factor = 1, smear = 1;
    double xz_mult = 1, y_mult = 1;

    void init(Xoroshiro& rng, double xzS, double yS, double xzF, double yF, double sm) {
        std::vector<double> minAmps(16, 1.0), mainAmps(8, 1.0);
        min_limit.init(rng, -15, minAmps, false);
        max_limit.init(rng, -15, minAmps, false);
        main.init(rng, -7, mainAmps, false);
        xz_scale = xzS;
        y_scale = yS;
        xz_factor = xzF;
        y_factor = yF;
        smear = sm;
        xz_mult = 684.412 * xzS;
        y_mult = 684.412 * yS;
    }

    double compute(double blockX, double blockY, double blockZ) const {
        double limitX = blockX * xz_mult, limitY = blockY * y_mult, limitZ = blockZ * xz_mult;
        double mainX = limitX / xz_factor, mainY = limitY / y_factor, mainZ = limitZ / xz_factor;
        double limitSmear = y_mult * smear;
        double mainSmear = limitSmear / y_factor;
        double blendMin = 0.0, blendMax = 0.0, mainVal = 0.0;
        double pw = 1.0;
        for (int i = 0; i < 8; i++) {
            const ImprovedNoise* nl = main.octave_noise(i);
            if (nl) {
                mainVal += nl->noise(wrap_noise(mainX * pw), wrap_noise(mainY * pw),
                                     wrap_noise(mainZ * pw), mainSmear * pw,
                                     mainY * pw) / pw;
            }
            pw /= 2.0;
        }
        double factor = (mainVal / 10.0 + 1.0) / 2.0;
        bool isMax = factor >= 1.0, isMin = factor <= 0.0;
        pw = 1.0;
        for (int i = 0; i < 16; i++) {
            double wx = wrap_noise(limitX * pw), wy = wrap_noise(limitY * pw),
                   wz = wrap_noise(limitZ * pw);
            double ys = limitSmear * pw;
            if (!isMax) {
                const ImprovedNoise* nl = min_limit.octave_noise(i);
                if (nl) blendMin += nl->noise(wx, wy, wz, ys, limitY * pw) / pw;
            }
            if (!isMin) {
                const ImprovedNoise* nl = max_limit.octave_noise(i);
                if (nl) blendMax += nl->noise(wx, wy, wz, ys, limitY * pw) / pw;
            }
            pw /= 2.0;
        }
        double t = factor;
        double r;
        if (t < 0.0) r = blendMin / 512.0;
        else if (t > 1.0) r = blendMax / 512.0;
        else r = m_lerp(t, blendMin / 512.0, blendMax / 512.0);
        return r / 128.0;
    }
};

// ===========================================================================
// CubicSpline（float32 Hermite，逐行对照 util/CubicSpline.java）
// ===========================================================================

struct SplinePoint {
    float location = 0.f;
    float value = 0.f;      // 常数
    float derivative = 0.f;
    int child = -1;         // >=0 表示子样条索引
};

// 平坦存储：所有 spline 节点放一个数组，child 指向根索引
struct SplineSet {
    std::vector<std::vector<SplinePoint>> points;   // 每个 spline 的点列表
    std::vector<int> coordFn;                       // 每个 spline 的 coordinate 函数 id
};

struct SplineEval {
    const SplineSet* set = nullptr;
    // coordFn 由外部求值器提供
    std::function<float(double, double, double)> coord_of;
    std::function<float(int, double, double, double)> value_of;   // (splineIdx, x,y,z)

    float eval_spline(int idx, double x, double y, double z) const;
    float eval_point_value(const SplinePoint& p, double x, double y, double z) const;
    float linear_extend(float input, float loc, float value, float deriv) const;
};


float SplineEval::eval_point_value(const SplinePoint& p, double x, double y, double z) const {
    if (p.child >= 0) return eval_spline(p.child, x, y, z);
    return p.value;
}

float SplineEval::linear_extend(float input, float loc, float value, float deriv) const {
    return deriv == 0.f ? value : value + deriv * (input - loc);
}

float SplineEval::eval_spline(int idx, double x, double y, double z) const {
    const auto& pts = set->points[idx];
    if (pts.empty()) return 0.f;
    float input = coord_of(x, y, z);
    // Mth.binarySearch(0, len, i -> input < locations[i]) - 1
    int lo = 0, hi = static_cast<int>(pts.size());
    while (hi - lo > 0) {
        int half = (hi - lo) / 2;
        int mid = lo + half;
        if (input < pts[mid].location) {
            hi = mid;
        } else {
            lo = mid + 1;
        }
    }
    int start = lo - 1;
    int last = static_cast<int>(pts.size()) - 1;
    if (start < 0) {
        return linear_extend(input, pts[0].location,
                             eval_point_value(pts[0], x, y, z), pts[0].derivative);
    }
    if (start == last) {
        return linear_extend(input, pts[last].location,
                             eval_point_value(pts[last], x, y, z), pts[last].derivative);
    }
    float x1 = pts[start].location, x2 = pts[start + 1].location;
    float t = (input - x1) / (x2 - x1);
    float y1 = eval_point_value(pts[start], x, y, z);
    float y2 = eval_point_value(pts[start + 1], x, y, z);
    float d1 = pts[start].derivative, d2 = pts[start + 1].derivative;
    float a = d1 * (x2 - x1) - (y2 - y1);
    float b = -d2 * (x2 - x1) + (y2 - y1);
    return m_lerp(t, y1, y2) + t * (1.0f - t) * m_lerp(t, a, b);
}

// ===========================================================================
// 密度函数节点（扁平数组 + 索引引用）
//   类型码与 Python 侧 DENSITY_OP 一致
// ===========================================================================

enum DFOp : int {
    DF_CONST = 0,
    DF_Y,            // y_clamped_gradient
    DF_ADD, DF_MUL, DF_MIN, DF_MAX,
    DF_HALF_NEG, DF_QUARTER_NEG, DF_HALF_POS, DF_QUARTER_POS,
    DF_ABS, DF_SQUARE, DF_CUBE, DF_INVERT, DF_SQUEEZE,
    DF_CLAMP,
    DF_NOISE,        // 普通 noise（含 xz/y scale）
    DF_SHIFTED_NOISE,
    DF_SHIFT_A, DF_SHIFT_B, DF_SHIFT,
    DF_OLD_BLENDED,
    DF_SPLINE,
    DF_RANGE_CHOICE,
    DF_INTERPOLATED,
    DF_FIND_TOP_SURFACE,
    DF_CACHE2D, DF_CACHE_ONCE,   // 求值时退化为透传（raw 语义）
    DF_PASSTHRU,
};

struct DFNode {
    int op = DF_CONST;
    double a = 0, b = 0, c = 0, d = 0;   // 常数 / from_y / to_y / 阈值等
    int arg0 = -1, arg1 = -2, arg2 = -3; // -2 表示"无此子节点"，-3 同理
    int noise_id = -1;
    int spline_id = -1;
    int cell_w = 4, cell_h = 8;
};

// ===========================================================================
// 阶段2：密度函数树求值 + 含水层 + 列扫描
//   JSON 解析在 Python 完成，这里只接受扁平化数值表。
// ===========================================================================

// 密度节点类型码（与 Python 编译端 map_flex 一致）
enum : int {
    OP_CONST = 0,
    OP_Y_GRAD,
    OP_ADD, OP_MUL, OP_MIN, OP_MAX,
    OP_HALF_NEG, OP_QUARTER_NEG, OP_HALF_POS, OP_QUARTER_POS,
    OP_ABS, OP_SQUARE, OP_CUBE, OP_INVERT, OP_SQUEEZE,
    OP_CLAMP,
    OP_NOISE,
    OP_SHIFTED_NOISE,
    OP_SHIFT_A, OP_SHIFT_B, OP_SHIFT,
    OP_OLD_BLENDED,
    OP_SPLINE,
    OP_RANGE_CHOICE,
    OP_INTERPOLATED,
    OP_FIND_TOP,
    OP_CACHE2D, OP_CACHE_ONCE,
    OP_PASSTHRU,
    OP_INTERVAL_SELECT,
};

struct DNode {
    int op = OP_CONST;
    double p0 = 0, p1 = 0, p2 = 0, p3 = 0;
    int a0 = -1, a1 = -1, a2 = -1;
    int noise = -1;      // 噪声表索引
    int spline = -1;     // 样条表索引
    int cw = 4, ch = 8;  // interpolated cell 尺寸；interval_select 时为阈值数
    int child_off = 0;   // 子节点索引表偏移（interval_select / 多阈值用）
    int child_cnt = 0;   // 子节点个数
};

// 样条：扁平点表 + 每样条区间
struct SPt {
    float loc = 0.f, val = 0.f, der = 0.f;
    int child = -1;
};

struct SplineData {
    std::vector<std::vector<SPt>> splines;
    std::vector<int> coord;   // 每样条 coordinate 的密度节点索引
};

struct DensityTree {
    std::vector<DNode> nodes;
    std::vector<int> children;   // 通用子节点索引表
    SplineData spl;
    int root = -1;

    std::vector<std::unique_ptr<NormalNoise>> noises;
    std::unique_ptr<BlendedNoise> blended;

    // interpolated：cell 角点缓存（按 (cellX, cellY, cellZ) 8 角求值）
    // 这里用逐点重算（正确优先）；cell 缓存留给列扫描路径优化

    double eval(int idx, double x, double y, double z) const {
        if (idx < 0 || idx >= static_cast<int>(nodes.size()))
            throw std::runtime_error("density node index out of range: " + std::to_string(idx));
        const DNode& n = nodes[idx];
        switch (n.op) {
            case OP_CONST: return n.p0;
            case OP_Y_GRAD: {
                if (y <= n.p0) return n.p2;
                if (y >= n.p1) return n.p3;
                return n.p2 + (n.p3 - n.p2) * (y - n.p0) / (n.p1 - n.p0);
            }
            case OP_ADD: return eval(n.a0, x, y, z) + eval(n.a1, x, y, z);
            case OP_MUL: {
                double a = eval(n.a0, x, y, z);
                if (a == 0.0) return 0.0;
                return a * eval(n.a1, x, y, z);
            }
            case OP_MIN: {
                double a = eval(n.a0, x, y, z), b = eval(n.a1, x, y, z);
                return a < b ? a : b;
            }
            case OP_MAX: {
                double a = eval(n.a0, x, y, z), b = eval(n.a1, x, y, z);
                return a > b ? a : b;
            }
            case OP_HALF_NEG: {
                double v = eval(n.a0, x, y, z);
                return v > 0.0 ? v : v * 0.5;
            }
            case OP_QUARTER_NEG: {
                double v = eval(n.a0, x, y, z);
                return v > 0.0 ? v : v * 0.25;
            }
            case OP_HALF_POS: {
                double v = eval(n.a0, x, y, z);
                return v < 0.0 ? v : v * 0.5;
            }
            case OP_QUARTER_POS: {
                double v = eval(n.a0, x, y, z);
                return v < 0.0 ? v : v * 0.25;
            }
            case OP_ABS: return std::fabs(eval(n.a0, x, y, z));
            case OP_SQUARE: {
                double v = eval(n.a0, x, y, z);
                return v * v;
            }
            case OP_CUBE: {
                double v = eval(n.a0, x, y, z);
                return v * v * v;
            }
            case OP_INVERT: return 1.0 / eval(n.a0, x, y, z);
            case OP_SQUEEZE: {
                double v = eval(n.a0, x, y, z);
                v = v < -1.0 ? -1.0 : (v > 1.0 ? 1.0 : v);
                return v / 2.0 - v * v * v / 24.0;
            }
            case OP_CLAMP: {
                double v = eval(n.a0, x, y, z);
                return v < n.p0 ? n.p0 : (v > n.p1 ? n.p1 : v);
            }
            case OP_NOISE: {
                if (n.noise < 0 || n.noise >= static_cast<int>(noises.size()))
                    throw std::runtime_error("noise index out of range");
                const NormalNoise* nn = noises[n.noise].get();
                if (!nn) throw std::runtime_error("null noise");
                return nn->get_value(x * n.p0, y * n.p1, z * n.p0);
            }
            case OP_SHIFTED_NOISE: {
                const NormalNoise* nn = noises[n.noise].get();
                double sx = eval(n.a0, x, y, z);
                double sy = eval(n.a1, x, y, z);
                double sz = eval(n.a2, x, y, z);
                return nn->get_value(x * n.p0 + sx, y * n.p1 + sy, z * n.p0 + sz);
            }
            case OP_SHIFT_A: {
                const NormalNoise* nn = noises[n.noise].get();
                return nn->get_value(x * 0.25, 0.0, z * 0.25) * 4.0;
            }
            case OP_SHIFT_B: {
                const NormalNoise* nn = noises[n.noise].get();
                return nn->get_value(z * 0.25, x * 0.25, 0.0) * 4.0;
            }
            case OP_SHIFT: {
                const NormalNoise* nn = noises[n.noise].get();
                return nn->get_value(x * 0.25, y * 0.25, z * 0.25) * 4.0;
            }
            case OP_OLD_BLENDED:
                if (!blended) throw std::runtime_error("blended noise missing");
                return blended->compute(x, y, z);
            case OP_SPLINE: return eval_spline(n.spline, x, y, z);
            case OP_RANGE_CHOICE: {
                double v = eval(n.a0, x, y, z);
                return (v >= n.p0 && v < n.p1) ? eval(n.a1, x, y, z)
                                              : eval(n.a2, x, y, z);
            }
            case OP_INTERPOLATED: {
                double cw = n.cw, ch = n.ch;
                int cellX = (int)std::floor(x / cw);
                int cellY = (int)std::floor(y / ch);
                int cellZ = (int)std::floor(z / cw);
                // 角点缓存：同一 (节点, cellX, cellY, cellZ) 的 8 个角点值恒定
                // （角点在世界坐标是固定的 cell 边界），列扫描时 x/z cell 不变、
                // y cell 每 ch 步才变 -> 相邻点大量命中。位精确（同角点同值）。
                struct IVal { int node, cx, cy, cz; std::array<double, 8> c; };
                static thread_local std::unordered_map<uint64_t, IVal> icache;
                static thread_local const DensityTree* iowner = nullptr;
                if (iowner != this) { icache.clear(); iowner = this; }
                uint64_t h = (uint64_t)(uint32_t)idx * 0x9E3779B97F4A7C15ull;
                h ^= (uint64_t)(uint32_t)cellX * 0xC2B2AE3D27D4EB4Full;
                h ^= (uint64_t)(uint32_t)cellY * 0x165667B19E3779F9ull;
                h ^= (uint64_t)(uint32_t)cellZ * 0x27D4EB2F165667C5ull;
                h >>= 1;
                std::array<double, 8> c;
                auto it = icache.find(h);
                if (it != icache.end() && it->second.node == idx &&
                    it->second.cx == cellX && it->second.cy == cellY &&
                    it->second.cz == cellZ) {
                    c = it->second.c;
                } else {
                    double cx = cellX * cw, cy = cellY * ch, cz = cellZ * cw;
                    c[0] = eval(n.a0, cx, cy, cz);
                    c[1] = eval(n.a0, cx + cw, cy, cz);
                    c[2] = eval(n.a0, cx, cy, cz + cw);
                    c[3] = eval(n.a0, cx + cw, cy, cz + cw);
                    c[4] = eval(n.a0, cx, cy + ch, cz);
                    c[5] = eval(n.a0, cx + cw, cy + ch, cz);
                    c[6] = eval(n.a0, cx, cy + ch, cz + cw);
                    c[7] = eval(n.a0, cx + cw, cy + ch, cz + cw);
                    if (icache.size() > 400000) icache.clear();
                    icache[h] = IVal{idx, cellX, cellY, cellZ, c};
                }
                double dx = x / cw - cellX, dy = y / ch - cellY, dz = z / cw - cellZ;
                double i00 = m_lerp(dx, c[0], c[1]), i10 = m_lerp(dx, c[2], c[3]);
                double i01 = m_lerp(dx, c[4], c[5]), i11 = m_lerp(dx, c[6], c[7]);
                return m_lerp(dy, m_lerp(dz, i00, i10), m_lerp(dz, i01, i11));
            }
            case OP_FIND_TOP: {
                double upper = eval(n.a1, x, y, z);
                int topY = ifloor(upper / n.ch) * n.ch;
                int lower = static_cast<int>(n.p2);
                if (topY <= lower) return static_cast<double>(lower);
                for (int by = topY; by >= lower; by -= n.ch) {
                    if (eval(n.a0, x, by, z) > 0.0) return static_cast<double>(by);
                }
                return static_cast<double>(lower);
            }
            case OP_INTERVAL_SELECT: {
                // 阈值在子节点之前的 p 数组里不方便 → 用 children[0..nth) 存函数，
                // 阈值存 p0..p3（nth<=4 的常见情形）
                double v = eval(n.a0, x, y, z);
                double th[4] = {n.p0, n.p1, n.p2, n.p3};
                int nth = n.cw;
                const int* ch = children.data() + n.child_off;
                for (int i = 0; i < nth; i++) {
                    if (v < th[i]) return eval(ch[i], x, y, z);
                }
                return eval(ch[nth], x, y, z);
            }
            case OP_CACHE2D:
            case OP_CACHE_ONCE:
            case OP_PASSTHRU:
            default:
                return eval(n.a0, x, y, z);
        }
    }

    double eval_spline(int sidx, double x, double y, double z) const {
        const auto& pts = spl.splines[sidx];
        if (pts.empty()) return 0.0;
        double inputRaw = eval(spl.coord[sidx], x, y, z);
        float input = static_cast<float>(inputRaw);
        int lo = 0, hi = static_cast<int>(pts.size());
        while (hi - lo > 0) {
            int half = (hi - lo) / 2;
            int mid = lo + half;
            if (input < pts[mid].loc) hi = mid; else lo = mid + 1;
        }
        int start = lo - 1;
        int last = static_cast<int>(pts.size()) - 1;
        auto pv = [&](const SPt& p) -> float {
            return p.child >= 0 ? static_cast<float>(eval_spline(p.child, x, y, z))
                                : p.val;
        };
        if (start < 0) {
            const SPt& p = pts[0];
            float v = pv(p);
            return p.der == 0.f ? v : v + p.der * (input - p.loc);
        }
        if (start == last) {
            const SPt& p = pts[last];
            float v = pv(p);
            return p.der == 0.f ? v : v + p.der * (input - p.loc);
        }
        float x1 = pts[start].loc, x2 = pts[start + 1].loc;
        float t = (input - x1) / (x2 - x1);
        float y1 = pv(pts[start]), y2 = pv(pts[start + 1]);
        float d1 = pts[start].der, d2 = pts[start + 1].der;
        float a = static_cast<float>(d1 * (x2 - x1) - (y2 - y1));
        float b = static_cast<float>(-d2 * (x2 - x1) + (y2 - y1));
        // 与 Java CubicSpline.Multipoint.sample 同序：先 lerp 并 f32 舍入，
        // 再一次 f32 舍入后乘 (t*(1-t))
        float base = static_cast<float>(m_lerp(t, y1, y2));
        float corr = static_cast<float>(m_lerp(t, a, b));
        return static_cast<float>(base + t * (1.0f - t) * corr);
    }
};

// ===========================================================================
// Mth.getSeed（26.2：末尾 >> 16）
// ===========================================================================

static inline i64 mth_get_seed(i32 x, i32 y, i32 z) {
    i64 s = static_cast<i64>(static_cast<i32>(static_cast<u32>(x) * 3129871u)) ^
            (static_cast<i64>(z) * 116129781LL) ^ static_cast<i64>(y);
    s = s * s * 42317861LL + s * 11LL;
    return s >> 16;
}

// ===========================================================================
// NoiseBasedAquifer（26.2）
// ===========================================================================

static const int AQ_OFFS[13][2] = {{0, 0},   {-2, -1}, {-1, -1}, {0, -1}, {1, -1},
                                   {-3, 0}, {-2, 0},  {-1, 0},  {1, 0},
                                   {-2, 1}, {-1, 1},  {0, 1},   {1, 1}};

struct Aquifer {
    // router 函数索引
    int df_barrier = -1, df_flooded = -1, df_spread = -1, df_lava = -1;
    int df_erosion = -1, df_depth = -1, df_prelim = -1;
    u64 aq_lo = 0, aq_hi = 0;
    long long sea = 63;
    long long way_below = -32512;
    const DensityTree* tree = nullptr;

    // 缓存
    mutable std::unordered_map<u64, std::array<int, 3>> loc_cache;
    mutable std::unordered_map<u64, std::pair<int, int>> status_cache;  // (level, typeId)
    mutable std::unordered_map<u64, int> prelim_cache;
    mutable std::unordered_map<u64, int> skip_cache;

    static constexpr int T_AIR = 0, T_WATER = 1, T_LAVA = 2;

    inline int pick_type(long long y) const { return (y < std::min<long long>(-54, sea)) ? T_LAVA : T_WATER; }
    inline int pick_level(long long y) const { return (y < std::min<long long>(-54, sea)) ? -54 : static_cast<int>(sea); }

    static inline int status_at(int level, int type, long long y) {
        return y < level ? type : T_AIR;
    }

    int prelim_surface(int x, int z) const {
        int qx = (x >> 2) << 2, qz = (z >> 2) << 2;
        u64 key = pack2(qx, qz);
        auto it = prelim_cache.find(key);
        if (it != prelim_cache.end()) return it->second;
        int v = ifloor(tree->eval(df_prelim, qx, 0.0, qz));
        prelim_cache[key] = v;
        return v;
    }

    std::array<int, 3> cell_loc(int gx, int gy, int gz) const {
        u64 key = pack3(gx, gy, gz);
        auto it = loc_cache.find(key);
        if (it != loc_cache.end()) return it->second;
        Xoroshiro r;
        r.set(static_cast<u64>(mth_get_seed(gx, gy, gz)) ^ aq_lo, aq_hi);
        std::array<int, 3> loc = {(gx << 4) + static_cast<int>(r.next_int_bound(10)),
                                  gy * 12 + static_cast<int>(r.next_int_bound(9)),
                                  (gz << 4) + static_cast<int>(r.next_int_bound(10))};
        loc_cache[key] = loc;
        return loc;
    }

    // ---- 26.2 新增：chunk 级 skipSamplingAboveY ----
    int chunk_skip_y(int x, int z) const {
        int cx = x >> 4, cz = z >> 4;
        u64 key = pack2(cx, cz);
        auto it = skip_cache.find(key);
        if (it != skip_cache.end()) return it->second;
        int minGX = (cx * 16 - 5) >> 4, maxGX = (((cx * 16 + 15) - 5) >> 4) + 1;
        int minGZ = (cz * 16 - 5) >> 4, maxGZ = (((cz * 16 + 15) - 5) >> 4) + 1;
        int x0 = minGX << 4, x1 = (maxGX << 4) + 9;
        int z0 = minGZ << 4, z1 = (maxGZ << 4) + 9;
        int mx = INT32_MIN;
        for (int zz = z0; zz <= z1; zz += 4) {
            for (int xx = x0; xx <= x1; xx += 4) {
                int lv = prelim_surface(xx, zz);
                if (lv > mx) mx = lv;
            }
        }
        int skipGridY = static_cast<int>(std::floor((mx + 8 + 12) / 12.0)) + 1;
        int v = skipGridY * 12 + 11 - 1;
        skip_cache[key] = v;
        return v;
    }

    // 返回 fluid status (level, type)
    std::pair<int, int> compute_fluid(int x, int y, int z) const {
        int globalLevel = pick_level(y), globalType = pick_type(y);
        int lowestPrelim = INT32_MAX;
        int top = y + 12, bottom = y - 12;
        bool centerUnder = false;
        for (auto& off : AQ_OFFS) {
            int sx = x + (off[0] << 4), sz = z + (off[1] << 4);
            int prelim = prelim_surface(sx, sz);
            int adj = prelim + 8;
            bool start = (off[0] == 0 && off[1] == 0);
            if (start && bottom > adj) return {globalLevel, globalType};
            bool pokes = top > adj;
            if (pokes || start) {
                int gLevel = pick_level(adj), gType = pick_type(adj);
                if (status_at(gLevel, gType, adj) != T_AIR) {
                    if (start) centerUnder = true;
                    if (pokes) return {gLevel, gType};
                }
            }
            if (prelim < lowestPrelim) lowestPrelim = prelim;
        }
        int level = compute_surface_level(x, y, z, globalLevel, lowestPrelim, centerUnder);
        int type = compute_fluid_type(x, y, z, globalType, level);
        return {level, type};
    }

    bool is_deep_dark(int x, int y, int z) const {
        return tree->eval(df_erosion, x, y, z) < -0.225 &&
               tree->eval(df_depth, x, y, z) > 0.9;
    }

    int compute_surface_level(int x, int y, int z, int globalLevel,
                              int lowestPrelim, bool centerUnder) const {
        double partially, fully;
        if (is_deep_dark(x, y, z)) {
            partially = fully = -1.0;
        } else {
            int dist = lowestPrelim + 8 - y;
            double factor = centerUnder ? clamp_val((dist - 0.0) / 64.0, 0.0, 1.0) : 0.0;
            factor = 1.0 + factor * (0.0 - 1.0);
            double fnoise = tree->eval(df_flooded, x, y, z);
            fnoise = clamp_val(fnoise, -1.0, 1.0);
            double fullyTh = map_lin(factor, 1.0, 0.0, -0.3, 0.8);
            double partTh = map_lin(factor, 1.0, 0.0, -0.8, 0.4);
            partially = fnoise - partTh;
            fully = fnoise - fullyTh;
        }
        if (fully > 0.0) return globalLevel;
        if (partially > 0.0) return compute_random_fluid_surface(x, y, z, lowestPrelim);
        return static_cast<int>(way_below);
    }

    int compute_random_fluid_surface(int x, int y, int z, int lowestPrelim) const {
        int cx = floordiv(x, 16), cy = floordiv(y, 40), cz = floordiv(z, 16);
        int mid = cy * 40 + 20;
        double spread = tree->eval(df_spread, cx, cy, cz) * 10.0;
        int q = quantize(spread, 3);
        int target = mid + q;
        return std::min(lowestPrelim, target);
    }

    int compute_fluid_type(int x, int y, int z, int globalType, int fluidSurface) const {
        int type = globalType;
        if (fluidSurface <= -10 && fluidSurface != static_cast<int>(way_below) &&
            globalType != T_LAVA) {
            int cx = floordiv(x, 64), cy = floordiv(y, 40), cz = floordiv(z, 64);
            if (std::fabs(tree->eval(df_lava, cx, cy, cz)) > 0.3) type = T_LAVA;
        }
        return type;
    }

    std::pair<int, int> get_status(int gx, int gy, int gz) const {
        u64 key = pack3(gx, gy, gz);
        auto it = status_cache.find(key);
        if (it != status_cache.end()) return it->second;
        auto loc = cell_loc(gx, gy, gz);
        auto st = compute_fluid(loc[0], loc[1], loc[2]);
        status_cache[key] = st;
        return st;
    }

    // 线程私有副本：复制只读参数与 tree 指针，所有缓存留空
    Aquifer clone_fresh() const {
        Aquifer a;
        a.df_barrier = df_barrier; a.df_flooded = df_flooded;
        a.df_spread = df_spread; a.df_lava = df_lava;
        a.df_erosion = df_erosion; a.df_depth = df_depth;
        a.df_prelim = df_prelim;
        a.aq_lo = aq_lo; a.aq_hi = aq_hi; a.sea = sea;
        a.way_below = way_below; a.tree = tree;
        return a;
    }

    static inline double similarity(int d1, int d2) { return 1.0 - (d2 - d1) / 25.0; }

    double calculate_pressure(int x, int y, int z, std::pair<int, int> s1,
                              std::pair<int, int> s2) const {
        int t1 = status_at(s1.first, s1.second, y);
        int t2 = status_at(s2.first, s2.second, y);
        bool mix = (t1 == T_LAVA && t2 == T_WATER) || (t1 == T_WATER && t2 == T_LAVA);
        if (mix) return 2.0;
        int ydiff = std::abs(s1.first - s2.first);
        if (ydiff == 0) return 0.0;
        double avg = 0.5 * (s1.first + s2.first);
        double howFar = y + 0.5 - avg;
        double basev = ydiff / 2.0;
        double dist = basev - std::fabs(howFar);
        double gradient;
        if (howFar > 0.0) {
            double cp = 0.0 + dist;
            gradient = cp > 0.0 ? cp / 1.5 : cp / 2.5;
        } else {
            double cp = 3.0 + dist;
            gradient = cp > 0.0 ? cp / 3.0 : cp / 10.0;
        }
        double noiseVal = 0.0;
        if (!(gradient < -2.0) && !(gradient > 2.0)) {
            noiseVal = tree->eval(df_barrier, x, y, z);
        }
        return 2.0 * (noiseVal + gradient);
    }

    // 返回：是否实心
    bool compute_substance(int x, int y, int z, double density) const {
        if (density > 0.0) return true;
        int globalLevel = pick_level(y), globalType = pick_type(y);
        if (y > chunk_skip_y(x, z)) return false;
        if (status_at(globalLevel, globalType, y) == T_LAVA) return false;

        int xa = (x + (-5)) >> 4, ya = floordiv(y + 1, 12), za = (z + (-5)) >> 4;
        int ds1 = INT32_MAX, ds2 = INT32_MAX, ds3 = INT32_MAX, ds4 = INT32_MAX;
        u64 ci1 = 0, ci2 = 0, ci3 = 0, ci4 = 0;
        for (int dx = 0; dx <= 1; dx++) {
            for (int dy = -1; dy <= 1; dy++) {
                for (int dz = 0; dz <= 1; dz++) {
                    int gx = xa + dx, gy = ya + dy, gz = za + dz;
                    auto loc = cell_loc(gx, gy, gz);
                    int ndx = loc[0] - x, ndy = loc[1] - y, ndz = loc[2] - z;
                    int nd = ndx * ndx + ndy * ndy + ndz * ndz;
                    u64 key = pack3(gx, gy, gz);
                    if (ds1 >= nd) {
                        ds4 = ds3; ci4 = ci3; ds3 = ds2; ci3 = ci2; ds2 = ds1; ci2 = ci1;
                        ds1 = nd; ci1 = key;
                    } else if (ds2 >= nd) {
                        ds4 = ds3; ci4 = ci3; ds3 = ds2; ci3 = ci2;
                        ds2 = nd; ci2 = key;
                    } else if (ds3 >= nd) {
                        ds4 = ds3; ci4 = ci3;
                        ds3 = nd; ci3 = key;
                    } else if (ds4 >= nd) {
                        ds4 = nd; ci4 = key;
                    }
                }
            }
        }
        auto s1 = get_status_by_key(ci1);
        double sim12 = similarity(ds1, ds2);
        int fluidState = status_at(s1.first, s1.second, y);
        if (sim12 <= 0.0) return false;
        if (fluidState == T_WATER) {
            int gLevel = pick_level(y - 1), gType = pick_type(y - 1);
            if (status_at(gLevel, gType, y - 1) == T_LAVA) return false;
        }
        auto s2 = get_status_by_key(ci2);
        double barrier12 = sim12 * calculate_pressure(x, y, z, s1, s2);
        if (density + barrier12 > 0.0) return true;
        auto s3 = get_status_by_key(ci3);
        double sim13 = similarity(ds1, ds3);
        if (sim13 > 0.0) {
            double b13 = sim12 * sim13 * calculate_pressure(x, y, z, s1, s3);
            if (density + b13 > 0.0) return true;
        }
        double sim23 = similarity(ds2, ds3);
        if (sim23 > 0.0) {
            double b23 = sim12 * sim23 * calculate_pressure(x, y, z, s2, s3);
            if (density + b23 > 0.0) return true;
        }
        return false;
    }

    std::pair<int, int> get_status_by_key(u64 key) const {
        auto it = status_cache.find(key);
        if (it != status_cache.end()) return it->second;
        int gx, gy, gz;
        unpack3(key, gx, gy, gz);
        auto loc = cell_loc(gx, gy, gz);
        auto st = compute_fluid(loc[0], loc[1], loc[2]);
        status_cache[key] = st;
        return st;
    }

    // ---- 打包 / 解包（3 个 21 位整数） ----
    static inline u64 pack2(int a, int b) {
        return (static_cast<u64>(static_cast<u32>(a)) << 32) |
               static_cast<u32>(b);
    }
    static inline u64 pack3(int a, int b, int c) {
        return (static_cast<u64>(static_cast<u32>(a)) << 42) |
               (static_cast<u64>(static_cast<u32>(b) & 0x1FFFFF) << 21) |
               static_cast<u64>(static_cast<u32>(c) & 0x1FFFFF);
    }
    static inline void unpack3(u64 k, int& a, int& b, int& c) {
        a = static_cast<int>(static_cast<i32>(static_cast<u32>(k >> 42)));
        b = static_cast<int>(static_cast<i32>(static_cast<u32>((k >> 21) & 0x1FFFFF)));
        c = static_cast<int>(static_cast<i32>(static_cast<u32>(k & 0x1FFFFF)));
    }
};

// ===========================================================================
// 阶段2 导出（简洁接口）：Python 序列化整棵树为 bytes，C++ 反序列化
//
// blob 格式（小端）：
//   magic 'MDF1'
//   u32 nodeCount
//   per node: i32 op, f64 p0,p1,p2,p3, i32 a0,a1,a2, i32 noise, i32 spline,
//             i32 cw, i32 ch
//   u32 splineCount
//   per spline: i32 coordNode, u32 ptCount, per pt: f32 loc,f32 val,f32 der, i32 child
//   i32 root
//   u32 noiseCount
//   per noise: i32 firstOctave, u32 ampCount, per amp f64
//   i32 router[7]  (barrier, flooded, spread, lava, erosion, depth, prelim)
//   i32 seaLevel
//   u8  hasBlended, then f64 bxz,bys,bxf,byf,bsm
// ===========================================================================


// ===========================================================================
// 采样上下文
// ===========================================================================

struct SamplerCtx {
    DensityTree tree;
    Aquifer aq;
    std::vector<std::unique_ptr<NormalNoise>> noise_store;

    // surface 层专用噪声（build_from_blob 末尾读取）
    u64 pos_lo = 0, pos_hi = 0;
    std::unique_ptr<NormalNoise> surface_noise;
    std::unique_ptr<NormalNoise> surface_secondary_noise;
    std::unique_ptr<NormalNoise> badlands_surface;
    std::unique_ptr<NormalNoise> badlands_pillar;
    std::unique_ptr<NormalNoise> badlands_pillar_roof;
    std::unique_ptr<NormalNoise> iceberg_surface;
    std::unique_ptr<NormalNoise> iceberg_pillar;
    std::unique_ptr<NormalNoise> iceberg_pillar_roof;
};

struct BlobReader {
    const u8* p;
    const u8* end;
    BlobReader(const u8* d, size_t n) : p(d), end(d + n) {}
    void need(size_t n) const {
        if (p + n > end) throw std::runtime_error("blob truncated");
    }
    u32 u32v() { need(4); u32 v; std::memcpy(&v, p, 4); p += 4; return v; }
    i32 i32v() { need(4); i32 v; std::memcpy(&v, p, 4); p += 4; return v; }
    float f32v() { need(4); f32 v; std::memcpy(&v, p, 4); p += 4; return v; }
    double f64v() { need(8); f64 v; std::memcpy(&v, p, 8); p += 8; return v; }
    u8 u8v() { need(1); u8 v = *p; p += 1; return v; }
    u64 u64v() { need(8); u64 v; std::memcpy(&v, p, 8); p += 8; return v; }
};

static SamplerCtx* build_from_blob(i64 seed, const std::string& blob) {
    BlobReader r(reinterpret_cast<const u8*>(blob.data()), blob.size());
    if (blob.size() < 4 || std::memcmp(r.p, "MDF1", 4) != 0)
        throw std::runtime_error("bad blob magic");
    r.p += 4;

    auto* ctx = new SamplerCtx();
    DensityTree& tree = ctx->tree;

    u32 nNodes = r.u32v();
    tree.nodes.resize(nNodes);
    for (u32 i = 0; i < nNodes; i++) {
        DNode& n = tree.nodes[i];
        n.op = r.i32v();
        n.p0 = r.f64v(); n.p1 = r.f64v(); n.p2 = r.f64v(); n.p3 = r.f64v();
        n.a0 = r.i32v(); n.a1 = r.i32v(); n.a2 = r.i32v();
        n.noise = r.i32v();
        n.spline = r.i32v();
        n.cw = r.i32v(); n.ch = r.i32v();
        n.child_off = r.i32v(); n.child_cnt = r.i32v();
    }

    u32 nChildren = r.u32v();
    tree.children.resize(nChildren);
    for (u32 i = 0; i < nChildren; i++) tree.children[i] = r.i32v();

    u32 nSplines = r.u32v();
    tree.spl.splines.resize(nSplines);
    tree.spl.coord.resize(nSplines);
    for (u32 i = 0; i < nSplines; i++) {
        tree.spl.coord[i] = r.i32v();
        u32 nPts = r.u32v();
        tree.spl.splines[i].resize(nPts);
        for (u32 j = 0; j < nPts; j++) {
            SPt& pt = tree.spl.splines[i][j];
            pt.loc = r.f32v();
            pt.val = r.f32v();
            pt.der = r.f32v();
            pt.child = r.i32v();
        }
    }
    tree.root = r.i32v();

    u32 nNoises = r.u32v();
    ctx->noise_store.resize(nNoises);
    tree.noises.resize(nNoises);
    u64 plo, phi;  // 世界 seed 的 positional factory
    {
        Xoroshiro world;
        world.from_seed(seed);
        plo = world.next_long();
        phi = world.next_long();
    }
    ctx->pos_lo = plo;
    ctx->pos_hi = phi;
    for (u32 i = 0; i < nNoises; i++) {
        i32 firstOct = r.i32v();
        u32 nAmps = r.u32v();
        std::vector<double> amps(nAmps);
        for (u32 j = 0; j < nAmps; j++) amps[j] = r.f64v();
        auto nn = std::make_unique<NormalNoise>();
        // 噪声名不参与（Python 已按"名称 hash ^ 世界 positional"算好）
        // 这里用 nameHashLo/Hi 直接传入 → blob 里追加
        u64 hlo = r.u64v();
        u64 hhi = r.u64v();
        Xoroshiro rng;
        rng.set(hlo ^ plo, hhi ^ phi);
        nn->init(rng, firstOct, amps);
        tree.noises[i] = std::move(nn);
    }

    i32 router[7];
    for (int i = 0; i < 7; i++) router[i] = r.i32v();
    ctx->aq.df_barrier = router[0];
    ctx->aq.df_flooded = router[1];
    ctx->aq.df_spread = router[2];
    ctx->aq.df_lava = router[3];
    ctx->aq.df_erosion = router[4];
    ctx->aq.df_depth = router[5];
    ctx->aq.df_prelim = router[6];
    ctx->aq.sea = r.i32v();
    ctx->aq.tree = &ctx->tree;

    u8 hasBlended = r.u8v();
    if (hasBlended) {
        double bxz = r.f64v(), bys = r.f64v(), bxf = r.f64v(), byf = r.f64v(),
            bsm = r.f64v();
        auto bl = std::make_unique<BlendedNoise>();
        Xoroshiro trng;
        u64 tlo = r.u64v();
        u64 thi = r.u64v();
        trng.set(tlo ^ plo, thi ^ phi);
        bl->init(trng, bxz, bys, bxf, byf, bsm);
        tree.blended = std::move(bl);
    }

    // ---- surface 专用噪声（8 个；blob 末尾追加）----
    {
        u32 nSurf = r.u32v();
        for (u32 i = 0; i < nSurf; i++) {
            i32 firstOct = r.i32v();
            u32 nAmps = r.u32v();
            std::vector<double> amps(nAmps);
            for (u32 j = 0; j < nAmps; j++) amps[j] = r.f64v();
            u64 hlo = r.u64v();
            u64 hhi = r.u64v();
            i32 slot = r.i32v();
            Xoroshiro rng;
            rng.set(hlo ^ plo, hhi ^ phi);
            auto nn = std::make_unique<NormalNoise>();
            nn->init(rng, firstOct, amps);
            switch (slot) {
                case 0: ctx->surface_noise = std::move(nn); break;
                case 1: ctx->surface_secondary_noise = std::move(nn); break;
                case 2: ctx->badlands_surface = std::move(nn); break;
                case 3: ctx->badlands_pillar = std::move(nn); break;
                case 4: ctx->badlands_pillar_roof = std::move(nn); break;
                case 5: ctx->iceberg_surface = std::move(nn); break;
                case 6: ctx->iceberg_pillar = std::move(nn); break;
                case 7: ctx->iceberg_pillar_roof = std::move(nn); break;
                default: break;
            }
        }
    }

    // aquifer 随机源
    {
        Xoroshiro aqrng;
        u64 alo, ahi;
        seed_from_hash("minecraft:aquifer", alo, ahi);
        aqrng.set(alo ^ plo, ahi ^ phi);
        ctx->aq.aq_lo = aqrng.next_long();
        ctx->aq.aq_hi = aqrng.next_long();
    }
    return ctx;
}

// ---- 列扫描：返回该列 fill 层最高实心 y ----
static py::array_t<i16> fill_top_grid(SamplerCtx* ctx, int x0, int z0, int w, int h,
                                      int min_y, int max_y, int threads) {
    py::array_t<i16> out({h, w});
    auto buf = out.mutable_unchecked<2>();
    int total = w * h;
    int nthreads = threads > 0 ? threads
                               : static_cast<int>(std::thread::hardware_concurrency());
    if (nthreads < 1) nthreads = 1;
    if (nthreads > total) nthreads = total;

    std::atomic<int> next_row{0};
    auto worker = [&]() {
        Aquifer aq = ctx->aq.clone_fresh();   // 线程私有缓存
        for (;;) {
            int row = next_row.fetch_add(1);
            if (row >= h) break;
            int z = z0 + row;
            for (int col = 0; col < w; col++) {
                int x = x0 + col;
                int top = min_y - 1;
                for (int y = max_y; y >= min_y; y--) {
                    double d = ctx->tree.eval(ctx->tree.root, x, y, z);
                    if (aq.compute_substance(x, y, z, d)) {
                        top = y;
                        break;
                    }
                }
                buf(row, col) = static_cast<i16>(top);
            }
        }
    };
    std::vector<std::thread> pool;
    for (int i = 1; i < nthreads; i++) pool.emplace_back(worker);
    worker();
    for (auto& t : pool) t.join();
    return out;
}


// 模块导出








// ===== SURFACE LAYER (merged) =====
// ===========================================================================
// SimplexNoise（2D）+ PerlinSimplexNoise（26.2）
// 逐行对照 synth/SimplexNoise.java / synth/PerlinSimplexNoise.java
// 供 Biome.TemperatureModifier.FROZEN 与 surface extension 使用
// ===========================================================================

static constexpr double SQRT3 = 1.7320508075688772;
static constexpr double SIMPLEX_F2 = 0.5 * (SQRT3 - 1.0);
static constexpr double SIMPLEX_G2 = (3.0 - SQRT3) / 6.0;

struct SimplexNoise {
    double xo = 0, yo = 0, zo = 0;
    u8 p[512];

    void init(Xoroshiro& rng) {
        xo = rng.next_double() * 256.0;
        yo = rng.next_double() * 256.0;
        zo = rng.next_double() * 256.0;
        for (int i = 0; i < 256; i++) p[i] = static_cast<u8>(i);
        for (int i = 0; i < 256; i++) {
            int off = static_cast<int>(rng.next_int_bound(256 - i));
            u8 t = p[i];
            p[i] = p[off + i];
            p[off + i] = t;
        }
        for (int i = 0; i < 256; i++) p[256 + i] = p[i];
    }

    inline int pv(int x) const { return p[x & 0xFF]; }

    static inline double corner3(int index, double x, double y, double z,
                                 double base) {
        double t0 = base - x * x - y * y - z * z;
        if (t0 < 0.0) return 0.0;
        t0 *= t0;
        const int* g = GRADIENT[index];
        return t0 * t0 * (g[0] * x + g[1] * y + g[2] * z);
    }

    double get_value(double xin, double yin) const {
        double s = (xin + yin) * SIMPLEX_F2;
        int i = ifloor(xin + s);
        int j = ifloor(yin + s);
        double t = (i + j) * SIMPLEX_G2;
        double x0 = xin - (i - t);
        double y0 = yin - (j - t);
        int i1, j1;
        if (x0 > y0) { i1 = 1; j1 = 0; } else { i1 = 0; j1 = 1; }
        double x1 = x0 - i1 + SIMPLEX_G2;
        double y1 = y0 - j1 + SIMPLEX_G2;
        double x2 = x0 - 1.0 + 2.0 * SIMPLEX_G2;
        double y2 = y0 - 1.0 + 2.0 * SIMPLEX_G2;
        int ii = i & 0xFF, jj = j & 0xFF;
        int gi0 = pv(ii + pv(jj)) % 12;
        int gi1 = pv(ii + i1 + pv(jj + j1)) % 12;
        int gi2 = pv(ii + 1 + pv(jj + 1)) % 12;
        double n0 = corner3(gi0, x0, y0, 0.0, 0.5);
        double n1 = corner3(gi1, x1, y1, 0.0, 0.5);
        double n2 = corner3(gi2, x2, y2, 0.0, 0.5);
        return 70.0 * (n0 + n1 + n2);
    }
};

struct PerlinSimplexNoise {
    std::vector<SimplexNoise> levels;
    std::vector<char> present;
    double highest_freq_value_factor = 1.0;
    double highest_freq_input_factor = 1.0;

    void init(Xoroshiro& rng, const std::vector<int>& octaveSet) {
        if (octaveSet.empty()) return;
        int lowFreq = -octaveSet.front();
        int highFreq = octaveSet.back();
        int octaves = lowFreq + highFreq + 1;
        if (octaves < 1) return;

        SimplexNoise zero;
        zero.init(rng);
        int zeroIdx = highFreq;
        levels.assign(octaves, SimplexNoise{});
        present.assign(octaves, 0);
        auto has = [&](int o) {
            for (int v : octaveSet) if (v == o) return true;
            return false;
        };
        if (zeroIdx >= 0 && zeroIdx < octaves && has(0)) {
            levels[zeroIdx] = zero;
            present[zeroIdx] = 1;
        }
        for (int i = zeroIdx + 1; i < octaves; i++) {
            if (i >= 0 && has(zeroIdx - i)) {
                levels[i].init(rng);
                present[i] = 1;
            } else {
                rng.consume(262);
            }
        }
        if (highFreq > 0) {
            i64 posSeed = static_cast<i64>(
                static_cast<float>(zero.get_value(zero.xo, zero.yo) * 9.223372e18));
            Xoroshiro hiRng;
            hiRng.from_seed(posSeed);
            for (int i = zeroIdx - 1; i >= 0; i--) {
                if (i < octaves && has(zeroIdx - i)) {
                    levels[i].init(hiRng);
                    present[i] = 1;
                } else {
                    hiRng.consume(262);
                }
            }
        }
        highest_freq_input_factor = std::pow(2.0, highFreq);
        highest_freq_value_factor = 1.0 / (std::pow(2.0, octaves) - 1.0);
    }

    double get_value(double x, double y, bool useNoiseStart = false) const {
        double value = 0.0;
        double factor = highest_freq_input_factor;
        double valueFactor = highest_freq_value_factor;
        for (size_t i = 0; i < levels.size(); i++) {
            if (present[i]) {
                double sx = useNoiseStart ? levels[i].xo : 0.0;
                double sy = useNoiseStart ? levels[i].yo : 0.0;
                value += levels[i].get_value(x * factor + sx, y * factor + sy) * valueFactor;
            }
            factor /= 2.0;
            valueFactor *= 2.0;
        }
        return value;
    }
};

// ===========================================================================
// Surface 层（阶段 3）：SurfaceRules + SurfaceSystem 移植
// 逐行对照 26.2 反编译 SurfaceRules.java / SurfaceSystem.java
//
// 规则节点扁平表（SRule）：
//   RULE_BLOCK        p0 = blockId
//   RULE_SEQUENCE     children[child_off .. +child_cnt)
//   RULE_CONDITION    a0 = condition 节点, a1 = then_run 节点
//   RULE_BANDLANDS    彩带（surfaceSystem.getBand）
//
// 条件节点（SCond）：
//   COND_NOT / COND_BIOME / COND_NOISE_THRESHOLD / COND_VERTICAL_GRADIENT
//   COND_ABOVE_PRELIM / COND_STONE_DEPTH / COND_Y_ABOVE / COND_WATER
//   COND_HOLE / COND_STEEP / COND_TEMPERATURE
// ===========================================================================

enum : int {
    RULE_BLOCK = 0,
    RULE_SEQUENCE,
    RULE_CONDITION,
    RULE_BANDLANDS,
};

enum : int {
    COND_NOT = 0,
    COND_BIOME,
    COND_NOISE_THRESHOLD,
    COND_VERTICAL_GRADIENT,
    COND_ABOVE_PRELIM,
    COND_STONE_DEPTH,
    COND_Y_ABOVE,
    COND_WATER,
    COND_HOLE,
    COND_STEEP,
    COND_TEMPERATURE,
};

struct SRule {
    int type = RULE_BLOCK;
    int p0 = -1;          // BLOCK: 方块 id
    int a0 = -1, a1 = -1; // CONDITION: cond, then_run
    int child_off = 0, child_cnt = 0;   // SEQUENCE
};

struct SCond {
    int type = COND_NOT;
    int a0 = -1;          // NOT 的子条件
    double p0 = 0, p1 = 0, p2 = 0, p3 = 0;
    int noise = -1;       // noise_threshold / vertical_gradient 用
    bool flag = false;    // add_stone_depth / add_surface_depth
    int i0 = 0, i1 = 0;   // offset / multiplier / secondary_range
    std::vector<int> biome_ids;   // COND_BIOME
};

struct SurfaceTree {
    std::vector<SRule> rules;
    std::vector<SCond> conds;
    std::vector<int> children;     // SEQUENCE 子规则索引
    int root = -1;

    // 方块 id -> 名称（Python 端给出）
    std::vector<std::string> block_names;

    // 彩带表（192）
    std::vector<int> clay_bands;
    int clay_offset_noise = -1;    // DensityTree 噪声索引

    // biome id -> "minecraft:key"（eroded/frozen extension 判定用）
    std::unordered_map<int, std::string> biome_names;

    // surface 编译器独立噪声表（noise_threshold / bandlands 用）
    std::vector<std::unique_ptr<NormalNoise>> noises;
};

// ---------------------------------------------------------------------------
// 方块 id 表（紧凑，仅 surface 会产出的那一批）
// ---------------------------------------------------------------------------
struct BlockTable {
    std::vector<std::string> names;
    std::unordered_map<std::string, int> idx;
    int id_of(const std::string& n) {
        auto it = idx.find(n);
        if (it != idx.end()) return it->second;
        int v = static_cast<int>(names.size());
        names.push_back(n);
        idx[n] = v;
        return v;
    }
};

// ===========================================================================
// 彩带表 + Biome 温度（surface extension 依赖）
// ===========================================================================

struct BiomeNoiseSet {
    PerlinSimplexNoise temp;    // seed 1234, {0}
    PerlinSimplexNoise frozen;  // seed 3456, {-2,-1,0}
    PerlinSimplexNoise info;    // seed 2345, {0}
    bool init_done = false;

    void init() {
        if (init_done) return;
        {
            Xoroshiro r; r.from_seed(1234);
            temp.init(r, std::vector<int>{0});
        }
        {
            Xoroshiro r; r.from_seed(3456);
            frozen.init(r, std::vector<int>{-2, -1, 0});
        }
        {
            Xoroshiro r; r.from_seed(2345);
            info.init(r, std::vector<int>{0});
        }
        init_done = true;
    }
};

static BiomeNoiseSet g_biome_noise;
static double g_biome_temps[256];
static bool g_biome_temp_set[256] = {false};
static bool g_frozen_modifier[256] = {false};

static double biome_temperature(int biomeId, int x, int y, int z, int seaLevel) {
    g_biome_noise.init();
    int key = biomeId & 0xFF;
    double base = g_biome_temp_set[key] ? g_biome_temps[key] : 0.8;
    if (g_frozen_modifier[key]) {
        double large = g_biome_noise.frozen.get_value(x * 0.05, z * 0.05) * 7.0;
        double edge = g_biome_noise.info.get_value(x * 0.2, z * 0.2);
        if (large + edge < 0.3) {
            double small = g_biome_noise.info.get_value(x * 0.09, z * 0.09);
            if (small < 0.8) base = 0.2;
        }
    }
    int snowLevel = seaLevel + 17;
    if (y > snowLevel) {
        double v = g_biome_noise.temp.get_value(x / 8.0, z / 8.0) * 8.0;
        return base - (v + y - snowLevel) * 0.05 / 40.0;
    }
    return base;
}

// SurfaceSystem.generateBands：192 长彩带表
static void generate_clay_bands(std::vector<int>& bands, BlockTable& bt,
                               Xoroshiro& rng) {
    int ORANGE = bt.id_of("minecraft:orange_terracotta");
    int YELLOW = bt.id_of("minecraft:yellow_terracotta");
    int BROWN = bt.id_of("minecraft:brown_terracotta");
    int RED = bt.id_of("minecraft:red_terracotta");
    int WHITE = bt.id_of("minecraft:white_terracotta");
    int LGRAY = bt.id_of("minecraft:light_gray_terracotta");
    int BASE = bt.id_of("minecraft:terracotta");

    bands.assign(192, BASE);
    int i = 0;
    while (i < 192) {
        i += static_cast<int>(rng.next_int_bound(5)) + 1;
        if (i < 192) bands[i] = ORANGE;
        i += 1;
    }
    auto make_bands = [&](int baseWidth, int state) {
        int count = 6 + static_cast<int>(rng.next_int_bound(10));
        for (int k = 0; k < count; k++) {
            int width = baseWidth + static_cast<int>(rng.next_int_bound(3));
            int start = static_cast<int>(rng.next_int_bound(192));
            for (int p2 = 0; start + p2 < 192 && p2 < width; p2++)
                bands[start + p2] = state;
        }
    };
    make_bands(1, YELLOW);
    make_bands(2, BROWN);
    make_bands(1, RED);
    int whiteCount = 9 + static_cast<int>(rng.next_int_bound(7));
    int wi = 0, start = 0;
    while (wi < whiteCount && start < 192) {
        bands[start] = WHITE;
        if (start - 1 > 0 && rng.next_bool()) bands[start - 1] = LGRAY;
        if (start + 1 < 192 && rng.next_bool()) bands[start + 1] = LGRAY;
        wi++;
        start += static_cast<int>(rng.next_int_bound(16)) + 4;
    }
}

// ===========================================================================
// Surface 求值器（对应 Python SurfaceRulesEngine）
// ===========================================================================

// biome 查询回调：由列扫描时提供（按 4x4 量化坐标）
struct BiomeFn {
    // biome id（Python 端约定的 int）由外部表给
    std::function<int(int, int, int)> at;   // (blockX, blockY, blockZ) -> biome id
};

struct SurfaceCtx {
    const SurfaceTree* st = nullptr;
    const DensityTree* dt = nullptr;   // 用于 noise_threshold / clay offset
    const Aquifer* aq = nullptr;
    BiomeFn biome;

    // 列状态（对应 SurfaceRules.Context）
    int block_x = 0, block_z = 0, block_y = 0;
    int surface_depth = 0;
    int stone_above = 0, stone_below = 0;
    long long water_height = INT64_MIN;
    double sec_noise = 0.0;
    bool sec_valid = false;
    int biome_id = -1;
    bool biome_valid = false;
    int min_surface_level = 0;
    bool msl_valid = false;

    // 附加上下文
    const NormalNoise* surface_noise = nullptr;     // minecraft:surface
    const NormalNoise* surface_sec_noise = nullptr; // minecraft:surface_secondary
    u64 pos_lo = 0, pos_hi = 0;

    // 列顶与水面（供 extension 用）
    int fill_top = -64;
    int first_water = INT32_MIN;
    int sea_level = 63;
    // steep 条件的邻列高度查询（(x,z) -> 最高方块 y）
    std::function<int(int, int)> surface_top_fn;

    // 输出
    int result_block = -1;

    // 调试追踪（surface_col_dbg 用）
    std::vector<std::string>* trace = nullptr;
};

// ---------------- 随机：XoroshiroRandomSource.at(x,y,z) ----------------
static inline double surface_random_double(u64 pos_lo, u64 pos_hi, i32 x, i32 y, i32 z) {
    Xoroshiro r;
    r.set(static_cast<u64>(mth_get_seed(x, y, z)) ^ pos_lo, pos_hi);
    return static_cast<double>(r.next_long() >> 11) * 1.1102230246251565e-16;
}

static inline float surface_random_float(u64 pos_lo, u64 pos_hi, i32 x, i32 y, i32 z) {
    Xoroshiro r;
    r.set(static_cast<u64>(mth_get_seed(x, y, z)) ^ pos_lo, pos_hi);
    return static_cast<float>(r.next_long() >> 40) * 5.9604645e-8f;
}

// ---------------- 条件求值 ----------------
static bool eval_cond(SurfaceCtx& c, int ci);
static bool eval_cond_inner(SurfaceCtx& c, int ci, const SCond& n);

static bool cond_biome(SurfaceCtx& c, const SCond& n) {
    if (!c.biome_valid) {
        c.biome_id = c.biome.at ? c.biome.at(c.block_x, c.block_y, c.block_z) : 0;
        c.biome_valid = true;
    }
    for (int b : n.biome_ids) {
        if (b == c.biome_id) return true;
    }
    return false;
}

static double get_surface_secondary(SurfaceCtx& c) {
    if (!c.sec_valid) {
        c.sec_noise = c.surface_sec_noise
                          ? c.surface_sec_noise->get_value(c.block_x, 0.0, c.block_z)
                          : 0.0;
        c.sec_valid = true;
    }
    return c.sec_noise;
}

static int get_min_surface_level(SurfaceCtx& c) {
    if (c.msl_valid) return c.min_surface_level;
    // Context.getMinSurfaceLevel：4 角 prelim + bilerp + surfaceDepth - 8
    int cell_x = c.block_x >> 4, cell_z = c.block_z >> 4;
    int b0 = cell_x << 4, b1 = (cell_x + 1) << 4;
    int d0 = cell_z << 4, d1 = (cell_z + 1) << 4;
    auto prelim = [&](int px, int pz) {
        int qx = (px >> 2) << 2, qz = (pz >> 2) << 2;
        return ifloor(c.dt->eval(c.aq->df_prelim, qx, 0.0, qz));
    };
    int p00 = prelim(b0, d0), p10 = prelim(b1, d0);
    int p01 = prelim(b0, d1), p11 = prelim(b1, d1);
    double dx = (c.block_x & 15) / 16.0;
    double dz = (c.block_z & 15) / 16.0;
    double v = m_lerp(dz, m_lerp(dx, p00, p10), m_lerp(dx, p01, p11));
    c.min_surface_level = ifloor(v) + c.surface_depth - 8;
    c.msl_valid = true;
    return c.min_surface_level;
}

static const char* cond_name(int t) {
    static const char* names[] = {"NOT", "BIOME", "NOISE_TH", "VGRAD",
        "APS", "STONE_DEPTH", "Y_ABOVE", "WATER", "HOLE", "STEEP", "TEMP"};
    return (t >= 0 && t <= 10) ? names[t] : "?";
}

static bool eval_cond(SurfaceCtx& c, int ci) {
    const SCond& n = c.st->conds[ci];
    bool r = eval_cond_inner(c, ci, n);
    if (c.trace) {
        char buf[160];
        snprintf(buf, sizeof(buf), "COND#%d %s -> %s (sa=%d sb=%d sd=%d wh=%lld p=[%.2f,%.2f,%.2f] i=[%d,%d] flag=%d)",
                 ci, cond_name(n.type), r ? "T" : "F",
                 c.stone_above, c.stone_below, c.surface_depth,
                 (long long)c.water_height, n.p0, n.p1, n.p2, n.i0, n.i1,
                 n.flag ? 1 : 0);
        c.trace->push_back(buf);
    }
    return r;
}

static bool eval_cond_inner(SurfaceCtx& c, int ci, const SCond& n) {
    switch (n.type) {
        case COND_NOT:
            return !eval_cond(c, n.a0);

        case COND_BIOME:
            return cond_biome(c, n);

        case COND_NOISE_THRESHOLD: {
            if (n.noise < 0 || n.noise >= (int)c.st->noises.size()) return false;
            const NormalNoise* nn = c.st->noises[n.noise].get();
            double v;
            if (n.flag) {   // is_3d
                v = nn->get_value(c.block_x, c.block_y, c.block_z);
            } else {
                v = nn->get_value(c.block_x, 0.0, c.block_z);
            }
            return v >= n.p0 && v <= n.p1;
        }

        case COND_VERTICAL_GRADIENT: {
            int y = c.block_y;
            if (y <= n.i0) return true;
            if (y >= n.i1) return false;
            double prob = 1.0 - static_cast<double>(y - n.i0) / (n.i1 - n.i0);
            return surface_random_float(c.pos_lo, c.pos_hi, c.block_x, y, c.block_z) < prob;
        }

        case COND_ABOVE_PRELIM:
            return c.block_y >= get_min_surface_level(c);

        case COND_STONE_DEPTH: {
            int depth = n.flag ? c.stone_below : c.stone_above;   // flag = ceiling
            int sdep = n.i0 ? c.surface_depth : 0;                // i0 = add_surface_depth
            int sec = 0;
            if (n.i1) {   // secondary_depth_range
                double v = get_surface_secondary(c);
                sec = static_cast<int>(n.p0 + (n.p1 - n.p0) * (v - (-1.0)) / 2.0);
            }
            return depth <= 1 + n.p2 + sdep + sec;   // p2 = offset
        }

        case COND_Y_ABOVE: {
            // flag = add_stone_depth, i1 = surface_depth_multiplier, p0 = anchor
            return (c.block_y + (n.flag ? c.stone_above : 0)) >=
                   n.p0 + c.surface_depth * n.i1;
        }

        case COND_WATER: {
            if (c.water_height == INT64_MIN) return true;
            return (c.block_y + (n.flag ? c.stone_above : 0)) >=
                   c.water_height + n.p0 + c.surface_depth * n.i1;
        }

        case COND_HOLE:
            return c.surface_depth <= 0;

        case COND_STEEP: {
            // SurfaceRules.SteepCondition：同 chunk 内南北/东西邻列高差 >= 4
            // （chunk 边界方向用本列自身高度，使该方向判 False，与 Python 一致）
            if (!c.surface_top_fn) return false;
            int cx = c.block_x & 15, cz = c.block_z & 15;
            int zn = (cz > 0) ? c.block_z - 1 : c.block_z;
            int zs = (cz < 15) ? c.block_z + 1 : c.block_z;
            int hn = c.surface_top_fn(c.block_x, zn);
            int hs = c.surface_top_fn(c.block_x, zs);
            if (hs >= hn + 4) return true;
            int xw = (cx > 0) ? c.block_x - 1 : c.block_x;
            int xe = (cx < 15) ? c.block_x + 1 : c.block_x;
            int hw = c.surface_top_fn(xw, c.block_z);
            int he = c.surface_top_fn(xe, c.block_z);
            return hw >= he + 4;
        }

        case COND_TEMPERATURE:
            // SurfaceRules.TemperatureCondition: coldEnoughToSnow(< 0.15F)
            return biome_temperature(c.biome_id, c.block_x, c.block_y,
                                     c.block_z, c.sea_level) < 0.15;

        default:
            return false;
    }
}

// ---------------- 规则求值 ----------------
// 返回方块 id，-1 表示未命中
static int eval_rule(SurfaceCtx& c, int ri) {
    const SRule& r = c.st->rules[ri];
    switch (r.type) {
        case RULE_BLOCK:
            if (c.trace) {
                char buf[96];
                snprintf(buf, sizeof(buf), "BLOCK#%d id=%d", ri, r.p0);
                c.trace->push_back(buf);
            }
            return r.p0;

        case RULE_SEQUENCE: {
            const int* ch = c.st->children.data() + r.child_off;
            for (int i = 0; i < r.child_cnt; i++) {
                int v = eval_rule(c, ch[i]);
                if (v >= 0) return v;
            }
            return -1;
        }

        case RULE_CONDITION:
            return eval_cond(c, r.a0) ? eval_rule(c, r.a1) : -1;

        case RULE_BANDLANDS: {
            if (c.st->clay_bands.empty()) return -1;
            if (c.st->clay_offset_noise < 0 ||
                c.st->clay_offset_noise >= (int)c.st->noises.size())
                return -1;
            const NormalNoise* off = c.st->noises[c.st->clay_offset_noise].get();
            double nv = off ? off->get_value(c.block_x, 0.0, c.block_z) : 0.0;
            int offset = static_cast<int>(std::floor(nv * 4.0 + 0.5));
            int idx = (c.block_y + offset + 192) % 192;
            if (idx < 0) idx += 192;
            return c.st->clay_bands[idx];
        }

        default:
            return -1;
    }
}

// ===========================================================================
// Surface 列级驱动 + bandlands + 两个 extension（修正版）
// 逐行对照 SurfaceSystem.buildSurface（L108-163）与
// erodedBadlandsExtension（L205-233）/ frozenOceanExtension（L235-284）
// ===========================================================================

struct ColumnResult {
    int top_y = -64;
    int block = -1;
};

struct SurfaceDeps {
    std::function<int(int, int)> surface_top;
    std::function<bool(int, int, int)> solid_at;
    // (isSolid, blockId)；非实心时 blockId 为 water/lava/air 的 id（air 用 -1）
    std::function<std::pair<bool, int>(int, int, int)> fill_block;
    int sea_level = 63;
    int air_id = -1;
    int water_id = -1;
    int lava_id = -1;
    int snow_block_id = -1;
    int packed_ice_id = -1;
    int stone_id = -1;

    const NormalNoise* badlands_surface = nullptr;
    const NormalNoise* badlands_pillar = nullptr;
    const NormalNoise* badlands_pillar_roof = nullptr;
    const NormalNoise* iceberg_surface = nullptr;
    const NormalNoise* iceberg_pillar = nullptr;
    const NormalNoise* iceberg_pillar_roof = nullptr;
};

// 返回被填充的 y 列表（升序无关）；空表示无扩展
static std::vector<int> eroded_badlands_extension(SurfaceCtx& c,
                                                  const SurfaceDeps& dep,
                                                  int x, int z, int height) {
    std::vector<int> filled;
    if (!dep.badlands_surface) return filled;
    double pillarBuffer = std::min(
        std::fabs(dep.badlands_surface->get_value(x, 0.0, z) * 8.25),
        dep.badlands_pillar->get_value(x * 0.2, 0.0, z * 0.2) * 15.0);
    if (!(pillarBuffer > 0.0)) return filled;
    double pillarFloor = std::fabs(
        dep.badlands_pillar_roof->get_value(x * 0.75, 0.0, z * 0.75) * 1.5);
    double extTop = 64.0 + std::min(pillarBuffer * pillarBuffer * 2.5,
                                    std::ceil(pillarFloor * 50.0) + 24.0);
    int startY = ifloor(extTop);
    if (height > startY) return filled;

    // 扫描 a：从 startY 向下，遇 stone 停；遇 water 放弃整列
    for (int y = startY; y >= -64; y--) {
        auto fb = dep.fill_block(x, y, z);
        if (fb.first) break;                        // 实心 = defaultBlock
        if (!fb.first && fb.second == dep.water_id) return {};   // 放弃
    }
    // 扫描 b：从 startY 向下，连续 air 填 stone
    for (int y = startY; y >= -64; y--) {
        auto fb = dep.fill_block(x, y, z);
        bool isAir = (!fb.first) && (fb.second < 0 || fb.second == dep.air_id);
        if (!isAir) break;
        filled.push_back(y);
    }
    return filled;
}

// frozenOceanExtension：返回 y -> blockId
static void frozen_ocean_extension(SurfaceCtx& c, const SurfaceDeps& dep,
                                   int x, int z, int height, int minSurfaceLevel,
                                   bool meltSlightly,
                                   std::unordered_map<int, int>& out) {
    if (!dep.iceberg_surface) return;
    double iceberg = std::min(
        std::fabs(dep.iceberg_surface->get_value(x, 0.0, z) * 8.25),
        dep.iceberg_pillar->get_value(x * 1.28, 0.0, z * 1.28) * 15.0);
    if (iceberg <= 1.8) return;
    double icebergRoof = std::fabs(
        dep.iceberg_pillar_roof->get_value(x * 1.17, 0.0, z * 1.17) * 1.5);
    double top = std::min(iceberg * iceberg * 1.2, std::ceil(icebergRoof * 40.0) + 14.0);
    if (meltSlightly) top -= 2.0;
    double extBottom;
    if (top > 2.0) {
        extBottom = dep.sea_level - top - 7.0;
        top += dep.sea_level;
    } else {
        top = 0.0;
        extBottom = 0.0;
    }
    double extTop = top;

    Xoroshiro rnd;
    rnd.set(static_cast<u64>(mth_get_seed(x, 0, z)) ^ c.pos_lo, c.pos_hi);
    int maxSnowDepth = 2 + static_cast<int>(rnd.next_int_bound(4));
    int minSnowHeight = dep.sea_level + 18 + static_cast<int>(rnd.next_int_bound(10));
    int snowDepth = 0;

    for (int y = std::max(height, static_cast<int>(extTop) + 1);
         y >= minSurfaceLevel; y--) {
        auto fb = dep.fill_block(x, y, z);
        bool isAir = (!fb.first) && (fb.second < 0 || fb.second == dep.air_id);
        bool isWater = (!fb.first) && fb.second == dep.water_id;
        bool cond1 = isAir && y < static_cast<int>(extTop) && rnd.next_double() > 0.01;
        bool cond2 = isWater && y > extBottom && y < dep.sea_level &&
                     extBottom != 0.0 && rnd.next_double() > 0.15;
        if (cond1 || cond2) {
            if (snowDepth <= maxSnowDepth && y > minSnowHeight) {
                out[y] = dep.snow_block_id;
                snowDepth++;
            } else {
                out[y] = dep.packed_ice_id;
            }
        }
    }
}

// ---------------- 单列完整流程 ----------------
static ColumnResult surface_column(SurfaceCtx& c, const SurfaceDeps& dep,
                                   int x, int z, int fillTop, int firstWaterY,
                                   int biomeId, bool isErodedBadlands,
                                   bool isFrozenOcean) {
    ColumnResult res;
    res.top_y = fillTop;

    // 1) eroded badlands 抬高列顶
    if (isErodedBadlands) {
        auto filled = eroded_badlands_extension(c, dep, x, z, fillTop + 1);
        if (!filled.empty()) {
            int mx = filled[0];
            for (int v : filled) mx = std::max(mx, v);
            res.top_y = mx;
        }
    }

    // 2) 单点规则
    c.block_x = x;
    c.block_z = z;
    c.block_y = res.top_y;
    c.biome_id = biomeId;
    c.biome_valid = true;
    c.sec_valid = false;
    c.msl_valid = false;
    c.fill_top = fillTop;
    c.first_water = firstWaterY;
    c.surface_depth = static_cast<int>(
        (c.surface_noise ? c.surface_noise->get_value(x, 0.0, z) : 0.0) * 2.75
        + 3.0 + surface_random_double(c.pos_lo, c.pos_hi, x, 0, z) * 0.25);
    c.stone_above = 1;
    // stone_below：自 top-1 向下到第一个非石
    {
        int ny = res.top_y - 1;
        while (ny >= -64 && dep.solid_at(x, ny, z)) ny--;
        c.stone_below = res.top_y - (ny + 1) + 1;
    }
    bool underWater = (firstWaterY != INT32_MIN) && (firstWaterY > res.top_y);
    c.water_height = underWater ? dep.sea_level : INT64_MIN;

    int blk = eval_rule(c, c.st->root);
    res.block = blk >= 0 ? blk : dep.stone_id;

    // 3) frozen ocean
    if (isFrozenOcean) {
        bool melt = biome_temperature(biomeId, x, dep.sea_level, z,
                                      dep.sea_level) > 0.1;
        std::unordered_map<int, int> ice;
        frozen_ocean_extension(c, dep, x, z, fillTop + 1,
                              get_min_surface_level(c), melt, ice);
        if (!ice.empty()) {
            int topmost = INT32_MIN;
            for (auto& kv : ice) topmost = std::max(topmost, kv.first);
            if (topmost > res.top_y) {
                res.top_y = topmost;
                res.block = ice[topmost];
            }
        }
    }
    return res;
}

// ===========================================================================
// Surface blob 反序列化（MDS1）+ surface_grid 导出
// ===========================================================================

static void load_surface_blob(SurfaceTree& st, BlockTable& bt,
                              const std::string& blob, u64 plo, u64 phi) {
    BlobReader r(reinterpret_cast<const u8*>(blob.data()), blob.size());
    if (blob.size() < 4 || std::memcmp(r.p, "MDS1", 4) != 0)
        throw std::runtime_error("bad surface blob magic");
    r.p += 4;

    u32 nNames = r.u32v();
    bt.names.clear();
    bt.idx.clear();
    for (u32 i = 0; i < nNames; i++) {
        u32 len = r.u32v();
        r.need(len);
        std::string nm(reinterpret_cast<const char*>(r.p), len);
        r.p += len;
        bt.idx[nm] = static_cast<int>(i);
        bt.names.push_back(nm);
    }

    u32 nRules = r.u32v();
    st.rules.resize(nRules);
    for (u32 i = 0; i < nRules; i++) {
        SRule& x = st.rules[i];
        x.type = r.i32v();
        x.p0 = r.i32v();
        x.a0 = r.i32v();
        x.a1 = r.i32v();
        x.child_off = r.i32v();
        x.child_cnt = r.i32v();
    }

    u32 nConds = r.u32v();
    st.conds.resize(nConds);
    for (u32 i = 0; i < nConds; i++) {
        SCond& c = st.conds[i];
        c.type = r.i32v();
        c.a0 = r.i32v();
        c.p0 = r.f64v(); c.p1 = r.f64v(); c.p2 = r.f64v(); c.p3 = r.f64v();
        c.noise = r.i32v();
        c.flag = r.u8v() != 0;
        c.i0 = r.i32v(); c.i1 = r.i32v();
        u32 nb = r.u32v();
        c.biome_ids.resize(nb);
        for (u32 k = 0; k < nb; k++) c.biome_ids[k] = r.i32v();
    }

    u32 nCh = r.u32v();
    st.children.resize(nCh);
    for (u32 i = 0; i < nCh; i++) st.children[i] = r.i32v();
    st.root = r.i32v();

    u32 nBands = r.u32v();
    st.clay_bands.resize(nBands);
    for (u32 i = 0; i < nBands; i++) st.clay_bands[i] = r.i32v();
    st.clay_offset_noise = r.i32v();

    u32 nTemp = r.u32v();
    for (u32 i = 0; i < nTemp; i++) {
        u32 bid = r.u32v();
        double tv = r.f64v();
        u8 frozen = r.u8v();
        if (bid < 256) {
            g_biome_temps[bid] = tv;
            g_biome_temp_set[bid] = true;
            g_frozen_modifier[bid] = frozen != 0;
        }
    }

    // biome 名表
    u32 nBn = r.u32v();
    for (u32 i = 0; i < nBn; i++) {
        i32 bid = r.i32v();
        u32 len = r.u32v();
        r.need(len);
        std::string nm(reinterpret_cast<const char*>(r.p), len);
        r.p += len;
        st.biome_names[bid] = nm;
    }

    // surface 噪声表
    u32 nSn = r.u32v();
    st.noises.resize(nSn);
    for (u32 i = 0; i < nSn; i++) {
        i32 firstOct = r.i32v();
        u32 nAmps = r.u32v();
        std::vector<double> amps(nAmps);
        for (u32 j = 0; j < nAmps; j++) amps[j] = r.f64v();
        u64 hlo = r.u64v();
        u64 hhi = r.u64v();
        Xoroshiro rng;
        rng.set(hlo ^ plo, hhi ^ phi);
        auto nn = std::make_unique<NormalNoise>();
        nn->init(rng, firstOct, amps);
        st.noises[i] = std::move(nn);
    }
}

// 返回 (tops, blocks)
static py::tuple surface_grid(
    SamplerCtx* ctx, const std::string& surfaceBlob,
    py::array_t<i16> fillTops, py::array_t<i32> biomeGrid,
    int x0, int z0, int seaLevel, int threads) {

    SurfaceTree st;
    BlockTable bt;
    load_surface_blob(st, bt, surfaceBlob, ctx->pos_lo, ctx->pos_hi);

    auto fbuf = fillTops.unchecked<2>();
    auto bbuf = biomeGrid.unchecked<2>();
    int h = static_cast<int>(fillTops.shape(0));
    int w = static_cast<int>(fillTops.shape(1));

    py::array_t<i16> tops({h, w});
    py::array_t<i32> blocks({h, w});
    auto tob = tops.mutable_unchecked<2>();
    auto bob = blocks.mutable_unchecked<2>();

    SurfaceDeps dep;
    dep.sea_level = seaLevel;
    auto bid_of = [&](const char* n, int dflt) {
        auto it = bt.idx.find(n);
        return it == bt.idx.end() ? dflt : it->second;
    };
    dep.air_id = bid_of("minecraft:air", -1);
    dep.water_id = bid_of("minecraft:water", -1);
    dep.lava_id = bid_of("minecraft:lava", -1);
    dep.snow_block_id = bid_of("minecraft:snow_block", -1);
    dep.packed_ice_id = bid_of("minecraft:packed_ice", -1);
    dep.stone_id = bid_of("minecraft:stone", 0);

    dep.badlands_surface = ctx->badlands_surface.get();
    dep.badlands_pillar = ctx->badlands_pillar.get();
    dep.badlands_pillar_roof = ctx->badlands_pillar_roof.get();
    dep.iceberg_surface = ctx->iceberg_surface.get();
    dep.iceberg_pillar = ctx->iceberg_pillar.get();
    dep.iceberg_pillar_roof = ctx->iceberg_pillar_roof.get();

    // solid_at/fill_block 用线程私有 aq（在每个 worker 内重绑定）
    dep.surface_top = [](int, int) { return 300; };

    int nthreads = threads > 0 ? threads
                              : static_cast<int>(std::thread::hardware_concurrency());
    if (nthreads < 1) nthreads = 1;
    std::atomic<int> nextRow{0};

    auto worker = [&]() {
        Aquifer aq = ctx->aq.clone_fresh();   // 线程私有缓存
        SurfaceCtx c;
        c.st = &st;
        c.dt = &ctx->tree;
        c.aq = &aq;
        c.pos_lo = ctx->pos_lo;
        c.pos_hi = ctx->pos_hi;
        c.surface_noise = ctx->surface_noise.get();
        c.surface_sec_noise = ctx->surface_secondary_noise.get();
        c.sea_level = seaLevel;
        SurfaceDeps tdep = dep;   // 线程私有（捕获本线程 aq）
        tdep.solid_at = [&aq, ctx](int px, int py, int pz) {
            return aq.compute_substance(px, py, pz,
                                        ctx->tree.eval(ctx->tree.root, px, py, pz));
        };
        tdep.fill_block = [&aq, ctx, &tdep](int px, int py, int pz)
            -> std::pair<bool, int> {
            double d = ctx->tree.eval(ctx->tree.root, px, py, pz);
            if (aq.compute_substance(px, py, pz, d)) return {true, -1};
            int lvl = aq.pick_level(py), tp = aq.pick_type(py);
            if (py < lvl)
                return {false, tp == Aquifer::T_LAVA ? tdep.lava_id : tdep.water_id};
            return {false, -1};
        };
        c.surface_top_fn = [&](int sx, int sz) -> int {
            int cc = sx - x0, rr = sz - z0;
            if (cc < 0 || cc >= w || rr < 0 || rr >= h) return -64;
            return static_cast<int>(fbuf(rr, cc));
        };
        for (;;) {
            int r = nextRow.fetch_add(1);
            if (r >= h) break;
            int z = z0 + r;
            for (int col = 0; col < w; col++) {
                int x = x0 + col;
                int fillTop = static_cast<int>(fbuf(r, col));
                int bid = static_cast<int>(bbuf(r, col));
                int biomeKey = bid < 0 ? 0 : bid;
                c.biome.at = [biomeKey](int, int, int) { return biomeKey; };
                auto bnit = st.biome_names.find(bid);
                bool eroded = (bnit != st.biome_names.end() &&
                               bnit->second == "minecraft:eroded_badlands");
                bool frozen = (bnit != st.biome_names.end() &&
                               (bnit->second == "minecraft:frozen_ocean" ||
                                bnit->second == "minecraft:deep_frozen_ocean"));
                // 水下列：官方 waterHeight = 最上水块 y+1 = sea_level；
                // 陆地列无上方水体 -> INT32_MIN（water 条件视为无水）
                int firstWater = (fillTop < seaLevel) ? seaLevel : INT32_MIN;
                auto res = surface_column(c, tdep, x, z, fillTop, firstWater,
                                          bid, eroded, frozen);
                tob(r, col) = static_cast<i16>(res.top_y);
                bob(r, col) = res.block;
            }
        }
    };
    std::vector<std::thread> pool;
    for (int i = 1; i < nthreads; i++) pool.emplace_back(worker);
    worker();
    for (auto& t : pool) t.join();
    return py::make_tuple(tops, blocks);
}

// ===== END SURFACE LAYER =====

PYBIND11_MODULE(_density_sampler, m) {
    m.doc() = "MapPreviewer 26.2 逐方块密度采样原生扩展";

    py::class_<SamplerCtx>(m, "SamplerCtx");

    m.def("md5_hex", [](const std::string& s) {
        u8 d[16];
        md5_digest(s.data(), s.size(), d);
        static const char* hex = "0123456789abcdef";
        std::string out;
        for (int i = 0; i < 16; i++) {
            out.push_back(hex[d[i] >> 4]);
            out.push_back(hex[d[i] & 0xF]);
        }
        return out;
    }, py::arg("s"));

    m.def("xoro_sequence", [](i64 seed, int n) {
        Xoroshiro r; r.from_seed(seed);
        py::array_t<u64> out(n);
        auto b = out.mutable_unchecked<1>();
        for (int i = 0; i < n; i++) b(i) = r.next_long();
        return out;
    }, py::arg("seed"), py::arg("n"));

    m.def("xoro_doubles", [](u64 lo, u64 hi, int n) {
        Xoroshiro r; r.set(lo, hi);
        py::array_t<double> out(n);
        auto b = out.mutable_unchecked<1>();
        for (int i = 0; i < n; i++) b(i) = r.next_double();
        return out;
    }, py::arg("lo"), py::arg("hi"), py::arg("n"));

    m.def("xoro_int_bound", [](u64 lo, u64 hi, int bound, int n) {
        Xoroshiro r; r.set(lo, hi);
        py::array_t<i64> out(n);
        auto b = out.mutable_unchecked<1>();
        for (int i = 0; i < n; i++) b(i) = static_cast<i64>(r.next_int_bound(bound));
        return out;
    }, py::arg("lo"), py::arg("hi"), py::arg("bound"), py::arg("n"));

    m.def("improved_noise", [](u64 lo, u64 hi,
                               py::array_t<double> xs, py::array_t<double> ys,
                               py::array_t<double> zs) {
        Xoroshiro r; r.set(lo, hi);
        ImprovedNoise in; in.init(r);
        auto n = xs.size();
        auto bx = xs.unchecked<1>(), by = ys.unchecked<1>(), bz = zs.unchecked<1>();
        py::array_t<double> out(n);
        auto ob = out.mutable_unchecked<1>();
        for (py::ssize_t i = 0; i < n; i++) ob(i) = in.noise(bx(i), by(i), bz(i), 0.0, 0.0);
        return out;
    }, py::arg("lo"), py::arg("hi"), py::arg("xs"), py::arg("ys"), py::arg("zs"));

    m.def("normal_noise", [](u64 lo, u64 hi, int first_octave,
                             std::vector<double> amps,
                             py::array_t<double> xs, py::array_t<double> ys,
                             py::array_t<double> zs) {
        Xoroshiro r; r.set(lo, hi);
        NormalNoise nn; nn.init(r, first_octave, amps);
        auto n = xs.size();
        auto bx = xs.unchecked<1>(), by = ys.unchecked<1>(), bz = zs.unchecked<1>();
        py::array_t<double> out(n);
        auto ob = out.mutable_unchecked<1>();
        for (py::ssize_t i = 0; i < n; i++) ob(i) = nn.get_value(bx(i), by(i), bz(i));
        return out;
    }, py::arg("lo"), py::arg("hi"), py::arg("first_octave"), py::arg("amps"),
       py::arg("xs"), py::arg("ys"), py::arg("zs"));

    // ---- 阶段2 ----
    m.def("build_from_blob", &build_from_blob, py::arg("seed"), py::arg("blob"),
          py::return_value_policy::take_ownership,
          "从 Python 序列化的 blob 编译密度树 + 含水层");

    m.def("fill_top_grid", &fill_top_grid,
          py::arg("ctx"), py::arg("x0"), py::arg("z0"), py::arg("w"), py::arg("h"),
          py::arg("min_y") = -64, py::arg("max_y") = 320,
          py::arg("threads") = 0,
          "逐列 fill 层最高实心 y 网格");

    m.def("eval_density", [](SamplerCtx* ctx, int x, int y, int z) {
        return ctx->tree.eval(ctx->tree.root, x, y, z);
    }, py::arg("ctx"), py::arg("x"), py::arg("y"), py::arg("z"),
       "单点密度（调试/对拍用）");

    m.def("is_solid", [](SamplerCtx* ctx, int x, int y, int z) {
        double d = ctx->tree.eval(ctx->tree.root, x, y, z);
        return ctx->aq.compute_substance(x, y, z, d);
    }, py::arg("ctx"), py::arg("x"), py::arg("y"), py::arg("z"));

    m.def("blended_debug", [](u64 lo, u64 hi, double xz, double ys, double xf,
                                double yf, double sm) {
        Xoroshiro rng; rng.set(lo, hi);
        BlendedNoise bl; bl.init(rng, xz, ys, xf, yf, sm);
        py::dict d;
        auto xos = [](const PerlinNoise& p) {
            py::list out;
            for (size_t i = 0; i < p.levels.size(); i++)
                out.append(p.level_present[i] ? p.levels[i].xo : -1.0);
            return out;
        };
        d["min_limit"] = xos(bl.min_limit);
        d["max_limit"] = xos(bl.max_limit);
        d["main"] = xos(bl.main);
        d["value"] = bl.compute(589, 130, 130);
        return d;
    }, py::arg("lo"), py::arg("hi"), py::arg("xz"), py::arg("ys"),
       py::arg("xf"), py::arg("yf"), py::arg("sm"));

    m.def("eval_node", [](SamplerCtx* ctx, int idx, int x, int y, int z) {
        return ctx->tree.eval(idx, x, y, z);
    }, py::arg("ctx"), py::arg("idx"), py::arg("x"), py::arg("y"), py::arg("z"));

    m.def("node_info", [](SamplerCtx* ctx, int idx) {
        const DNode& n = ctx->tree.nodes[idx];
        py::dict d;
        d["op"] = n.op;
        d["p"] = py::make_tuple(n.p0, n.p1, n.p2, n.p3);
        d["a"] = py::make_tuple(n.a0, n.a1, n.a2);
        d["noise"] = n.noise;
        d["child_off"] = n.child_off;
        d["child_cnt"] = n.child_cnt;
        return d;
    }, py::arg("ctx"), py::arg("idx"));

    m.def("surface_col_dbg", [](SamplerCtx* ctx, const std::string& surfaceBlob,
                                 int x, int z, int fillTop, int seaLevel,
                                 int biomeId) {
        SurfaceTree st;
        BlockTable bt;
        load_surface_blob(st, bt, surfaceBlob, ctx->pos_lo, ctx->pos_hi);
        SurfaceDeps dep;
        dep.sea_level = seaLevel;
        auto bid_of = [&](const char* n, int dflt) {
            auto it = bt.idx.find(n);
            return it == bt.idx.end() ? dflt : it->second;
        };
        dep.water_id = bid_of("minecraft:water", -1);
        dep.lava_id = bid_of("minecraft:lava", -1);
        dep.air_id = bid_of("minecraft:air", -1);
        dep.snow_block_id = bid_of("minecraft:snow_block", -1);
        dep.packed_ice_id = bid_of("minecraft:packed_ice", -1);
        dep.stone_id = bid_of("minecraft:stone", 0);
        dep.badlands_surface = ctx->badlands_surface.get();
        dep.badlands_pillar = ctx->badlands_pillar.get();
        dep.badlands_pillar_roof = ctx->badlands_pillar_roof.get();
        dep.iceberg_surface = ctx->iceberg_surface.get();
        dep.iceberg_pillar = ctx->iceberg_pillar.get();
        dep.iceberg_pillar_roof = ctx->iceberg_pillar_roof.get();
        dep.solid_at = [ctx](int px, int py, int pz) {
            return ctx->aq.compute_substance(px, py, pz,
                                             ctx->tree.eval(ctx->tree.root, px, py, pz));
        };
        dep.surface_top = [](int, int) { return 300; };
        dep.fill_block = [ctx, &dep](int px, int py, int pz) -> std::pair<bool, int> {
            double d = ctx->tree.eval(ctx->tree.root, px, py, pz);
            if (ctx->aq.compute_substance(px, py, pz, d)) return {true, -1};
            int lvl = ctx->aq.pick_level(py), tp = ctx->aq.pick_type(py);
            if (py < lvl) return {false, tp == Aquifer::T_LAVA ? dep.lava_id : dep.water_id};
            return {false, -1};
        };
        SurfaceCtx c2;
        c2.st = &st; c2.dt = &ctx->tree; c2.aq = &ctx->aq;
        c2.pos_lo = ctx->pos_lo; c2.pos_hi = ctx->pos_hi;
        c2.surface_noise = ctx->surface_noise.get();
        c2.surface_sec_noise = ctx->surface_secondary_noise.get();
        c2.sea_level = seaLevel;
        c2.surface_top_fn = [&](int, int) { return fillTop; };
        c2.biome.at = [biomeId](int, int, int) { return biomeId; };
        std::vector<std::string> tr;
        c2.trace = &tr;
        int firstWater = (fillTop < seaLevel) ? seaLevel : INT32_MIN;
        auto res = surface_column(c2, dep, x, z, fillTop, firstWater,
                                  biomeId, false, false);
        py::dict out;
        py::list trl;
        for (auto& s : tr) trl.append(s);
        out["trace"] = trl;
        out["top_y"] = res.top_y;
        out["block"] = res.block;
        out["surface_depth"] = c2.surface_depth;
        out["stone_above"] = c2.stone_above;
        out["stone_below"] = c2.stone_below;
        out["water_height"] = (long long)c2.water_height;
        out["noise_null"] = (c2.surface_noise == nullptr);
        return out;
    }, py::arg("ctx"), py::arg("surface_blob"), py::arg("x"), py::arg("z"),
       py::arg("fill_top"), py::arg("sea_level"), py::arg("biome_id"));

    // 逐列判定「该列顶部是否为开阔水体」（供水面着色）
    // 判据：从海平面(含)向上找，若 seaLevel 处及以下连续出现水体，
    // 且该列地表高度 < seaLevel，则为水域。冰刺/冰山尖顶（地表 >= sea）
    // 不算水域，避免把冰刺画成水。
    m.def("water_mask_grid", [](SamplerCtx* ctx, int x0, int z0, int w, int h,
                                int seaLevel, int threads) {
        py::array_t<u8> out({h, w});
        auto ob = out.mutable_unchecked<2>();
        int nth = threads > 0 ? threads
                              : (int)std::thread::hardware_concurrency();
        if (nth < 1) nth = 1;
        std::atomic<int> nextRow{0};
        auto worker = [&]() {
            Aquifer aq = ctx->aq.clone_fresh();
            for (;;) {
                int r = nextRow.fetch_add(1);
                if (r >= h) break;
                int z = z0 + r;
                for (int c = 0; c < w; c++) {
                    int x = x0 + c;
                    // 找地表顶（首个实心方块，从海平面之上开始）
                    int top = seaLevel + 1;
                    for (int y = seaLevel + 1; y >= -64; y--) {
                        double d = ctx->tree.eval(ctx->tree.root, x, y, z);
                        if (aq.compute_substance(x, y, z, d)) { top = y; break; }
                    }
                    u8 wet = 0;
                    // 只有地表低于海平面才可能存在覆盖水体
                    if (top < seaLevel) {
                        // 海平面处必须是水（不是空气），否则是干涸洼地
                        double d0 = ctx->tree.eval(ctx->tree.root, x, seaLevel, z);
                        bool solid0 = aq.compute_substance(x, seaLevel, z, d0);
                        if (!solid0 && aq.pick_type(seaLevel) == Aquifer::T_WATER)
                            wet = 1;
                    }
                    ob(r, c) = wet;
                }
            }
        };
        std::vector<std::thread> pool;
        for (int i = 1; i < nth; i++) pool.emplace_back(worker);
        worker();
        for (auto& t2 : pool) t2.join();
        return out;
    }, py::arg("ctx"), py::arg("x0"), py::arg("z0"), py::arg("w"),
       py::arg("h"), py::arg("sea_level") = 63, py::arg("threads") = 0,
       "逐列判定海平面处是否为开阔水体");

    m.def("surface_grid", &surface_grid,
          py::arg("ctx"), py::arg("surface_blob"),
          py::arg("fill_tops"), py::arg("biome_grid"),
          py::arg("x0"), py::arg("z0"), py::arg("sea_level") = 63,
          py::arg("threads") = 0,
          "surface 层：fill 顶 + biome 网格 -> (最终顶 y, 顶块 id)");
}
