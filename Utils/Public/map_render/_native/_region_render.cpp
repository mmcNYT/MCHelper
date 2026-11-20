// _region_render.cpp —— SaveManager 俯视图 region 解码核心（C++ 加速版）。
//
// 语义基准：Utils/Public/map_render/chunk_render.py + world_render.py 的纯
// Python 路径（保留作降级与对拍基准）。cProfile 实测单 region（26.2 Test
// r.0.0，profiler 下 5.75s 含插桩开销）：逐列 Python 循环 ~4.7s（lookup
// 1.54s + _seabed 1.48s + surface_block 0.82s + _entry_name 0.63s +
// resolve_biome 0.64s）+ NBT 解码 1.3s（70 万次 _read_payload）；
// 配色 _colorize_blocks 0.77s 与 zlib.decompress 0.089s 留在 Python。
//
// 本扩展搬进 C++ 的部分：
//   - NBT 游标解码（大端，越界即抛 → 该 chunk 整块虚空，对齐纯 Python
//     read_chunk 捕获异常返回 None 的行为）
//   - section palette / 位打包解码（块与群系同规则）
//   - heightmap 解码（MOTION_BLOCKING 优先，缺失/空回退 WORLD_SURFACE，
//     都无 → 全 0，即 sy=-65 扫不到任何节 → 整列虚空）
//   - 逐列地表扫描（全列向下；air_like 连续 5 格判虚空；JM 0.4 透明
//     家族——栅栏/栅栏门/玻璃/染色玻璃/玻璃板/铁栏杆（仅 minecraft:）
//     ——穿透取地表，最高透明块名作 overlay 输出）+ 流体海床穿透
//     （向下 10 格）
//   - 地表群系取值（4×4×4 网格，section 缺失按 -1/+1 回退）
//   - 反向虚空标记（未产出数据的 chunk 槽位整 16×16 标 void）
// Python 端保留：名字 → 调色板 id 映射、群系名 → BIOME_ID 映射、
// render_from_blocks 配色（JM 水色链 + 影调 + 坡度）。
//
// 与纯 Python 逐位对齐的语义（改任何一处必须两边同步）：
//   - palette 位宽：block = max(4, ceil(log2(n)))；biome = ceillog2(n)
//     （无 4 位下限，见 pal_bits/bio_bits 注释）。每 long 装 floor(64/bits) 个
//     完整项不跨 long；li >= data 长 → 空名；v >= palette 长 → 空名；
//     空名不命中（继续向下扫）。
//   - 单方块节（palette 有项但无 data）：整节常量名。
//   - surface_block：sy = hm[col] + min_y - 1，向下全列扫描（穿透/空气
//     均继续）；连续 air_like ≥ 5 → 列虚空（void=1，heights 保持 -64）。
//     JM 透明家族命中 → 记录最高透明名继续向下（overlay），地表取
//     下方首个非透明非空块（对齐 JM getBlockHeight mapTransparency）。
//     注意：悬停用的 chunk_render.surface_block 仍保持原 5 格窗语义
//     （悬停显示实体顶块本身，不穿透）。
//   - disp（显示高度）：透明格 = 最高透明块 y（栅栏/玻璃的 1 格落差
//     参与坡度 bevel → 立体感），其余格 = heights 同值；水色链/wet
//     仍用 heights。
//   - 流体顶（fluids）：向下 <=10 格找海床（跳 bed_skip 与空名）；海床
//     y < sea_level-1 → 换名换高；找不到海床 → heights = deep_y；
//     海床 y >= sea_level-1（湖床）→ 不换（palette 平涂）。
//   - 群系：取地表扫描起点 sy 处（不是换高后的 wy）的 4×4×4 网格
//     idx=(by*4+bz)*4+bx；by/bz/bx 由原始 sec_y 推；section 缺失按
//     sec_y-1 → sec_y+1 回退（by 仍按原 sec_y）；空名 → -1。
//   - Status：存在且去命名空间后非空且 != "full" → 整 chunk 虚空；
//     缺失视为 full。
//   - 同 Y 的 section 后者覆盖前者（对齐纯 Python dict 赋值）。
//   - 反向虚空：凡未产出数据的槽位（无文件条目/读取失败/半生成/解析
//     失败）整 16×16 void=1，防止 heights=-64 被水色链误判成极深海。
//
// 输出数组缺省值（与纯 Python 一致）：blocks=0、heights=-64、void=0、
// overlay=-1（无透明层）；biomes 缺省 -1（Python 端把 -1 与「resolve 失败」
// 统一映射回 0，对齐纯 Python 的默认 0，避免误用群系名表第 0 项）。
//
// 导出：render_region(raws, coords, min_y, sea_level, deep_y,
//                     air_like, bed_skip, fluids) -> dict（含 wet 真水掩码）
// 重建扩展：python Utils/Public/map_render/_native/build_region.py

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>      // std::vector<std::string> <-> Python list
#include <pybind11/gil.h>

#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace py = pybind11;
using i8 = std::int8_t;
using i16 = std::int16_t;
using i32 = std::int32_t;
using i64 = std::int64_t;
using u8 = std::uint8_t;
using u16 = std::uint16_t;
using u32 = std::uint32_t;
using u64 = std::uint64_t;

namespace {

constexpr int kRegionBlocks = 512;   // 32 chunk × 16 方块
constexpr int kChunk = 16;
constexpr int kSurfaceDive = 5;      // 地表扫描向下格数（chunk_render.surface_block）
constexpr int kSeabedDive = 10;      // 海床搜索格数（world_render._seabed limit）

const std::string kEmpty;

// Python floor 除法（b > 0）：C++ / 向零截断，负被除数会差 1
inline int fdiv(int a, int b) {
    int q = a / b, r = a % b;
    return (r != 0 && ((r < 0) != (b < 0))) ? q - 1 : q;
}

// palette 索引位宽：block 用 max(4, ceillog2(n))（chunk_render._palette_bits）。
// biome 用无下限的 ceillog2(n)（MC PalettedContainer.SECTION_PALETTE
// calculateBitsForSerialization 无 4 位下限；1.20.1/26.2 数据实证：
// palette=2 -> bits=1 -> 64 值装 1 long；若按 4 bits 只能解前 16 值，
// 后 48 值越界判空 -> 群系缺失 -> 默认 ocean 绿草——雪原存档绿色草方块根因）。
inline int pal_bits(int n) {
    int b = 0;
    while ((1 << b) < n) ++b;
    return b < 4 ? 4 : b;
}

inline int bio_bits(int n) {
    int b = 0;
    while ((1 << b) < n) ++b;
    return b < 1 ? 1 : b;
}

// ---------------------------------------------------------------------------
// 名字表：intern 按首次出现顺序编号，Python 端据此映射到 lpack 调色板 id
// ---------------------------------------------------------------------------

struct NameTable {
    std::vector<std::string> names;
    std::unordered_map<std::string, i32> index;

    i32 intern(const std::string& s) {
        auto it = index.find(s);
        if (it != index.end()) return it->second;
        i32 id = static_cast<i32>(names.size());
        names.push_back(s);
        index.emplace(s, id);
        return id;
    }
};

// ---------------------------------------------------------------------------
// NBT 游标（大端；越界抛异常 → 调用方把该 chunk 整块按虚空处理）
// ---------------------------------------------------------------------------

class Cur {
public:
    Cur(const u8* p, size_t n) : p_(p), n_(n) {}

    u8 u8v() { need(1); return p_[pos_++]; }

    i16 i16v() {
        need(2);
        i16 v = static_cast<i16>((u16)p_[pos_] << 8 | (u16)p_[pos_ + 1]);
        pos_ += 2;
        return v;
    }
    u16 u16v() { return static_cast<u16>(i16v()); }

    u32 u32v() {
        need(4);
        u32 v = (u32)p_[pos_] << 24 | (u32)p_[pos_ + 1] << 16 |
                (u32)p_[pos_ + 2] << 8 | (u32)p_[pos_ + 3];
        pos_ += 4;
        return v;
    }

    i64 i64v() {
        need(8);
        u64 v = 0;
        for (int i = 0; i < 8; ++i) v = v << 8 | (u64)p_[pos_ + i];
        pos_ += 8;
        return static_cast<i64>(v);
    }

    std::string strv() {
        u16 len = u16v();
        need(len);
        std::string s(reinterpret_cast<const char*>(p_) + pos_, len);
        pos_ += len;
        return s;
    }

    void skip(size_t k) { need(k); pos_ += k; }

private:
    void need(size_t k) const {
        if (pos_ > n_ || k > n_ - pos_) throw std::runtime_error("nbt truncated");
    }
    const u8* p_;
    size_t n_;
    size_t pos_ = 0;
};

// 跳过任意 tag 的负载（只导航兴趣字段，其余跳过；防御畸形数据）
void skip_payload(Cur& c, u8 tag) {
    switch (tag) {
    case 1: c.skip(1); break;
    case 2: c.skip(2); break;
    case 3: case 5: c.skip(4); break;
    case 4: case 6: c.skip(8); break;
    case 7: c.skip(c.u32v()); break;
    case 8: c.skip(c.u16v()); break;
    case 9: {
        u8 et = c.u8v();
        u32 n = c.u32v();
        if (et == 0 || n == 0) break;
        switch (et) {
        case 1: c.skip(static_cast<size_t>(n)); break;
        case 2: c.skip(static_cast<size_t>(n) * 2); break;
        case 3: case 5: c.skip(static_cast<size_t>(n) * 4); break;
        case 4: case 6: c.skip(static_cast<size_t>(n) * 8); break;
        default:
            // 7/8/9/10/11/12：变长负载逐个跳。Int/LongArray 元素也自带
            // 4 字节长度前缀（实测 structures.starts.*.Children[].Entrances
            // 是 List<IntArray>，按固定 4 字节跳会错位 → 后续全崩）
            for (u32 i = 0; i < n; ++i) skip_payload(c, et);
            break;
        }
        break;
    }
    case 10: {
        for (;;) {
            u8 t = c.u8v();
            if (t == 0) break;
            c.skip(c.u16v());
            skip_payload(c, t);
        }
        break;
    }
    case 11: c.skip(static_cast<size_t>(c.u32v()) * 4); break;
    case 12: c.skip(static_cast<size_t>(c.u32v()) * 8); break;
    default: throw std::runtime_error("bad nbt tag");
    }
}

// ---------------------------------------------------------------------------
// chunk 解码产物（每 chunk 一份，用完即弃）
// ---------------------------------------------------------------------------

struct SecBlocks {
    i32 y = 0;
    std::vector<std::string> pal;   // 块名（可能为空串）
    bool packed = false;            // 有 data
    std::vector<i64> data;
};

struct SecBiomes {
    i32 y = 0;
    std::vector<std::string> pal;
    bool packed = false;
    std::vector<i64> data;
};

struct ChunkData {
    i16 hmap[256] = {0};            // 已解码的 heightmap（无 → 全 0）
    std::vector<SecBlocks> secs;
    std::vector<SecBiomes> bios;
};

// section 查找（每 chunk 节数 ~24，线性扫够快）
const SecBlocks* find_sec(const ChunkData& cd, int y) {
    for (const auto& s : cd.secs)
        if (s.y == y) return &s;
    return nullptr;
}
const SecBiomes* find_bio(const ChunkData& cd, int y) {
    for (const auto& b : cd.bios)
        if (b.y == y) return &b;
    return nullptr;
}

// 打包数组通用取值：返回 palette 下标；li 越界返回 -1（调用方再查 v >= pal 数）
inline i64 packed_get(const std::vector<i64>& data, int bits, size_t per_long,
                      size_t idx) {
    size_t li = idx / per_long;
    if (li >= data.size()) return -1;
    int boff = static_cast<int>((idx % per_long) * static_cast<size_t>(bits));
    return (data[li] >> boff) & ((i64(1) << bits) - 1);
}

// 块 section 取名（对齐 chunk_render.build_block_lookup.lookup）：空串 = 未命中
inline const std::string& sec_block_name(const SecBlocks& s, int ly, int lz,
                                         int lx) {
    if (!s.packed) return s.pal.empty() ? kEmpty : s.pal[0];
    size_t idx = static_cast<size_t>(ly) * 256 + static_cast<size_t>(lz) * 16 + lx;
    int bits = pal_bits(static_cast<int>(s.pal.size()));
    i64 v = packed_get(s.data, bits, 64 / bits, idx);
    if (v < 0 || v >= static_cast<i64>(s.pal.size())) return kEmpty;
    return s.pal[static_cast<size_t>(v)];
}

// 群系取名（对齐 chunk_render.build_biome_lookup.lookup）
inline const std::string& sec_biome_name(const SecBiomes& s, int by, int bz,
                                         int bx) {
    // palette=1 的节无 data 字段（packed=false）-> 整节常量，对齐纯 Python
    // 的 `if not dat: return 常量` 分支；缺失时 packed_get 空表必返 -1 ->
    // 群系缺失 -> 默认 ocean 绿草（1.20.1 存档 97% 格群系丢失的根因）
    if (!s.packed) return s.pal.empty() ? kEmpty : s.pal[0];
    int bits = bio_bits(static_cast<int>(s.pal.size()));
    size_t idx = static_cast<size_t>(by * 16 + bz * 4 + bx);
    i64 v = packed_get(s.data, bits, 64 / bits, idx);
    if (v < 0 || v >= static_cast<i64>(s.pal.size())) return kEmpty;
    return s.pal[static_cast<size_t>(v)];
}

// ---------------------------------------------------------------------------
// NBT 结构解析
// ---------------------------------------------------------------------------

void parse_block_states(Cur& c, SecBlocks& sec) {
    for (;;) {
        u8 tag = c.u8v();
        if (tag == 0) break;
        std::string name = c.strv();
        if (tag == 9 && name == "palette") {
            u8 et = c.u8v();
            u32 n = c.u32v();
            if (et == 10) {
                sec.pal.resize(n);
                for (u32 i = 0; i < n; ++i) {
                    // palette 元素是裸 compound 负载，找 Name（缺失 → 空名，
                    // 对齐 _entry_name 的 entry.get("Name") or ""）
                    std::string nm;
                    for (;;) {
                        u8 t2 = c.u8v();
                        if (t2 == 0) break;
                        std::string k = c.strv();
                        if (t2 == 8 && k == "Name") nm = c.strv();
                        else skip_payload(c, t2);
                    }
                    sec.pal[i] = std::move(nm);
                }
            } else if (n > 0) {
                // 非预期元素类型：纯 Python 会走 str(entry)，实际格式不会
                // 出现；这里清空 palette → 整节按不存在处理
                for (u32 i = 0; i < n; ++i) skip_payload(c, et);
                sec.pal.clear();
            }
        } else if (tag == 12 && name == "data") {
            u32 n = c.u32v();
            if (n > 0) {
                sec.data.resize(n);
                for (u32 i = 0; i < n; ++i) sec.data[i] = c.i64v();
                sec.packed = true;
            }
            // n == 0：纯 Python 的 if not dat 走单方块分支（packed 不置位）
        } else {
            skip_payload(c, tag);
        }
    }
}

void parse_biomes(Cur& c, SecBiomes& bio) {
    for (;;) {
        u8 tag = c.u8v();
        if (tag == 0) break;
        std::string name = c.strv();
        if (tag == 9 && name == "palette") {
            u8 et = c.u8v();
            u32 n = c.u32v();
            if (et == 8) {
                bio.pal.resize(n);
                for (u32 i = 0; i < n; ++i) bio.pal[i] = c.strv();
            } else if (et == 10) {
                // 群系也可能写成 {Name} compound（_entry_name 兼容两者）
                bio.pal.resize(n);
                for (u32 i = 0; i < n; ++i) {
                    std::string nm;
                    for (;;) {
                        u8 t2 = c.u8v();
                        if (t2 == 0) break;
                        std::string k = c.strv();
                        if (t2 == 8 && k == "Name") nm = c.strv();
                        else skip_payload(c, t2);
                    }
                    bio.pal[i] = std::move(nm);
                }
            } else if (n > 0) {
                for (u32 i = 0; i < n; ++i) skip_payload(c, et);
                bio.pal.clear();
            }
        } else if (tag == 12 && name == "data") {
            u32 n = c.u32v();
            if (n > 0) {
                bio.data.resize(n);
                for (u32 i = 0; i < n; ++i) bio.data[i] = c.i64v();
                bio.packed = true;
            }
        } else {
            skip_payload(c, tag);
        }
    }
}

void parse_section(Cur& c, ChunkData& cd) {
    SecBlocks sec;
    SecBiomes bio;
    i32 y = 0;
    bool has_y = false;
    for (;;) {
        u8 tag = c.u8v();
        if (tag == 0) break;
        std::string name = c.strv();
        if (tag == 1 && name == "Y") {
            y = static_cast<i32>(static_cast<i8>(c.u8v()));
            has_y = true;
        } else if (tag == 10 && name == "block_states") {
            parse_block_states(c, sec);
        } else if (tag == 10 && name == "biomes") {
            parse_biomes(c, bio);
        } else {
            skip_payload(c, tag);
        }
    }
    if (!has_y) return;   // 无 Y 的节：纯 Python 挂 None 键，实际 int 键查询
                          // 永远打不中，行为等价于不存在
    sec.y = y;            // 解析出的 Y 落到节结构上（此前漏赋值导致全 0）
    bio.y = y;
    if (!sec.pal.empty()) {
        auto it = std::find_if(cd.secs.begin(), cd.secs.end(),
                               [&](const SecBlocks& s) { return s.y == y; });
        if (it != cd.secs.end()) *it = std::move(sec);   // 同 Y 后者覆盖
        else cd.secs.push_back(std::move(sec));
    }
    if (!bio.pal.empty()) {
        auto it = std::find_if(cd.bios.begin(), cd.bios.end(),
                               [&](const SecBiomes& b) { return b.y == y; });
        if (it != cd.bios.end()) *it = std::move(bio);
        else cd.bios.push_back(std::move(bio));
    }
}

void parse_sections_list(Cur& c, ChunkData& cd) {
    u8 et = c.u8v();
    u32 n = c.u32v();
    if (et == 10) {
        for (u32 i = 0; i < n; ++i) parse_section(c, cd);   // 裸 compound 负载
        return;
    }
    if (et == 0 || n == 0) return;
    for (u32 i = 0; i < n; ++i) skip_payload(c, et);
}

// 9 位/项、7 项/long（chunk_render.decode_heightmap）；缺 long 补 0
void decode_heightmap_into(const std::vector<i64>& longs, i16 out[256]) {
    constexpr int kBits = 9;
    constexpr int kPerLong = 64 / kBits;   // 7
    constexpr i64 kMask = (i64(1) << kBits) - 1;
    for (int i = 0; i < 256; ++i) {
        size_t li = static_cast<size_t>(i / kPerLong);
        i64 v = 0;
        if (li < longs.size())
            v = (longs[li] >> ((i % kPerLong) * kBits)) & kMask;
        out[i] = static_cast<i16>(v);
    }
}

void parse_heightmaps(Cur& c, ChunkData& cd) {
    bool has_mb = false, has_ws = false;
    std::vector<i64> mb, ws;
    for (;;) {
        u8 tag = c.u8v();
        if (tag == 0) break;
        std::string name = c.strv();
        if (tag == 12 && (name == "MOTION_BLOCKING" || name == "WORLD_SURFACE")) {
            u32 n = c.u32v();
            std::vector<i64> buf(n);
            for (u32 i = 0; i < n; ++i) buf[i] = c.i64v();
            if (name == "MOTION_BLOCKING") { mb = std::move(buf); has_mb = true; }
            else { ws = std::move(buf); has_ws = true; }
        } else {
            skip_payload(c, tag);
        }
    }
    // hm.get("MOTION_BLOCKING") or hm.get("WORLD_SURFACE")：MB 空/缺失回退 WS
    if (has_mb && !mb.empty()) decode_heightmap_into(mb, cd.hmap);
    else if (has_ws && !ws.empty()) decode_heightmap_into(ws, cd.hmap);
    // 都无 → 保持全 0（sy=-65 扫不到节 → 整列虚空）
}

// 解析一个 chunk；返回 false = 半生成（Status != full），整块按虚空处理
bool parse_chunk(const u8* p, size_t n, ChunkData& cd) {
    Cur c(p, n);
    u8 root_tag = c.u8v();
    if (root_tag != 10) throw std::runtime_error("root not compound");
    c.strv();   // 根名
    std::string status;
    bool has_status = false;
    for (;;) {
        u8 tag = c.u8v();
        if (tag == 0) break;
        std::string name = c.strv();
        if (tag == 8 && name == "Status") {
            status = c.strv();
            has_status = true;
        } else if (tag == 9 && name == "sections") {
            parse_sections_list(c, cd);
        } else if (tag == 10 && name == "Heightmaps") {
            parse_heightmaps(c, cd);
        } else {
            skip_payload(c, tag);
        }
    }
    if (has_status && !status.empty()) {
        // 去命名空间（str.rsplit(":", 1)[-1]）
        size_t pos = status.rfind(':');
        std::string st =
            (pos == std::string::npos) ? status : status.substr(pos + 1);
        if (st != "full") return false;
    }
    return true;
}

// ---------------------------------------------------------------------------
// 逐列语义（对齐 chunk_render.surface_block / surface_biome、
// world_render._seabed）
// ---------------------------------------------------------------------------

// 地表扫描：命中返回 true 并给出 (名字, wy, 扫描起点 sy)；失败 = 列虚空。
// 透明方块（JM VanillaBlockHandler 0.4 家族：栅栏/栅栏门/玻璃/染色玻璃/
// 玻璃板/铁栏杆，仅 minecraft: 前缀）穿透：继续向下取地表（对齐 JM
// getBlockHeight 的 mapTransparency 语义），最高透明块名经 out_overlay
// 返回供混色层用；无透明 → *out_overlay = nullptr。
// 原 5 格窗语义改为：连续 air_like ≥ 5 判虚空（heightmap 顶格在正常存档
// 必命中非空方块，穿透/空气场景需要全列扫描——玻璃塔可叠任意高）。
bool is_transparent_name(const std::string& n) {
    if (n.compare(0, 10, "minecraft:") != 0 || n.size() <= 10) return false;
    auto ends_with = [&](const char* suf) {
        size_t m = std::strlen(suf);
        return n.size() >= m
            && n.compare(n.size() - m, m, suf) == 0;
    };
    return ends_with("_fence") || ends_with("_fence_gate")
        || ends_with("_stained_glass") || ends_with("_stained_glass_pane")
        || n == "minecraft:glass" || n == "minecraft:glass_pane"
        || n == "minecraft:iron_bars" || n == "minecraft:tinted_glass";
}

// JM VanillaBlockHandler：class_2302(CropBlock) → Crop flag，mapCrops
// 默认 true → 作物作为地表渲染（NoShadow，农田平整无坡度）。vanilla 的
// CropBlock 子类就这四种；甜菜丛/甘蔗等属 Plant，mapPlants 默认 false →
// 整块 Ignore 透视到下方，不在此列。
static const std::unordered_set<std::string> kCropBlocks = {
    "minecraft:wheat", "minecraft:carrots",
    "minecraft:potatoes", "minecraft:beetroots"};

bool surface_scan(const ChunkData& cd, int lx, int lz, int min_y,
                  const std::unordered_set<std::string>& air_like,
                  const std::string** out_name, int* out_wy, int* out_sy,
                  const std::string** out_overlay, int* out_ov_y) {
    int col = lz * 16 + lx;
    int sy = cd.hmap[col] + min_y - 1;
    const std::string* overlay = nullptr;
    int ov_y = 0;
    int air_run = 0;
    for (int wy = sy; wy >= min_y; --wy) {
        int sec_y = fdiv(wy, 16);
        const SecBlocks* s = find_sec(cd, sec_y);
        if (!s) continue;   // 对齐纯 Python：lk is None → continue
        int ly = wy - sec_y * 16;
        const std::string& nm = sec_block_name(*s, ly, lz, lx);
        if (nm.empty() || air_like.find(nm) != air_like.end()) {
            if (++air_run >= kSurfaceDive) return false;   // 连续空气 → 虚空
            continue;
        }
        if (is_transparent_name(nm)) {
            if (!overlay) {
                overlay = &nm;   // 最高透明块（供 0.4 混色 + 显示高度）
                ov_y = wy;
            }
            continue;
        }
        // JM mapCrops 默认开：作物作为地表渲染。MOTION_BLOCKING 高度图
        // 不含作物（非阻挡方块），扫描命中地表后向上探测作物层（作物
        // 1 格高，2 格余量）；遇空气/透明/其他实体块即停。
        const std::string* nm_out = &nm;
        int wy_out = wy;
        int sy_out = sy;
        for (int k = 1; k <= 2; ++k) {
            int cy = wy + k;
            int csec = fdiv(cy, 16);
            const SecBlocks* cs = find_sec(cd, csec);
            if (!cs) break;
            const std::string& cn = sec_block_name(*cs, cy - csec * 16, lz, lx);
            if (kCropBlocks.find(cn) == kCropBlocks.end()) break;
            nm_out = &cn;
            wy_out = cy;
            sy_out = csec;
        }
        *out_name = nm_out;
        *out_wy = wy_out;
        *out_sy = sy_out;
        *out_overlay = overlay;
        *out_ov_y = ov_y;
        return true;
    }
    return false;
}

// 海床搜索（world_render._seabed）：命中返回 (名字, y)；limit 格内无 → false
bool find_seabed(const ChunkData& cd, int lx, int lz, int wy, int min_y,
                 const std::unordered_set<std::string>& bed_skip,
                 const std::string** out_name, int* out_y) {
    int y = wy - 1;
    for (int k = 0; k < kSeabedDive; ++k) {
        if (y < min_y) return false;
        int sec_y = fdiv(y, 16);
        const SecBlocks* s = find_sec(cd, sec_y);
        if (s) {
            int ly = y - sec_y * 16;
            const std::string& nm = sec_block_name(*s, ly, lz, lx);
            if (!nm.empty() && bed_skip.find(nm) == bed_skip.end()) {
                *out_name = &nm;
                *out_y = y;
                return true;
            }
        }
        --y;
    }
    return false;
}

// 地表群系（chunk_render.surface_biome）：空名/无 section → nullptr
const std::string* surface_biome_at(const ChunkData& cd, int lx, int lz,
                                    int sy) {
    int sec_y = fdiv(sy, 16);
    const SecBiomes* b = find_bio(cd, sec_y);
    if (!b) {
        b = find_bio(cd, sec_y - 1);   // 对齐 dy in (-1, 1) 的回退顺序
        if (!b) b = find_bio(cd, sec_y + 1);
        if (!b) return nullptr;
    }
    int ly = sy - sec_y * 16;   // 0..15（floor 语义），by 仍按原 sec_y 推
    int by = ly >> 2;
    const std::string& nm = sec_biome_name(*b, by, lz >> 2, lx >> 2);
    return nm.empty() ? nullptr : &nm;
}

}  // namespace

// ---------------------------------------------------------------------------
// 诊断辅助：解析单个 chunk，不吞异常，回报失败原因与解码产物概要
// （排查畸形存档 / 格式变化时用；正常渲染路径走 render_region）
// ---------------------------------------------------------------------------

py::dict debug_parse(py::bytes raw, int min_y,
                     std::vector<std::string> air_like_v) {
    char* buf = nullptr;
    Py_ssize_t len = 0;
    if (PyBytes_AsStringAndSize(raw.ptr(), &buf, &len) != 0)
        throw py::error_already_set();
    ChunkData cd;
    bool ok = false;
    std::string err;
    try {
        ok = parse_chunk(reinterpret_cast<const u8*>(buf),
                         static_cast<size_t>(len), cd);
    } catch (const std::exception& e) {
        err = e.what();
    }
    py::dict d;
    d["ok"] = ok;
    d["err"] = py::str(err);
    d["n_secs"] = py::int_(static_cast<py::ssize_t>(cd.secs.size()));
    d["n_bios"] = py::int_(static_cast<py::ssize_t>(cd.bios.size()));
    i16 hmax = -32768, hmin = 32767;
    for (int i = 0; i < 256; ++i) {
        hmax = std::max(hmax, cd.hmap[i]);
        hmin = std::min(hmin, cd.hmap[i]);
    }
    d["hmin"] = py::int_(hmin);
    d["hmax"] = py::int_(hmax);
    // 每节概要：(Y, palette 长度, 有 data, data 长度, 首 palette 名)
    py::list secs;
    for (const auto& s : cd.secs) {
        py::dict e;
        e["y"] = py::int_(s.y);
        e["pal"] = py::int_(static_cast<py::ssize_t>(s.pal.size()));
        e["packed"] = s.packed;
        e["data"] = py::int_(static_cast<py::ssize_t>(s.data.size()));
        e["name0"] = py::str(s.pal.empty() ? "" : s.pal[0]);
        secs.append(std::move(e));
    }
    d["secs"] = std::move(secs);
    // 列扫描探针：z=0 行前 8 列，用与 render_region 完全相同的扫描函数
    const std::unordered_set<std::string> air_like(air_like_v.begin(),
                                                   air_like_v.end());
    py::list probe;
    for (int x = 0; x < 8; ++x) {
        const std::string* nm = nullptr;
        const std::string* ov = nullptr;
        int ov_y = 0;
        int wy = 0, sy = 0;
        py::dict e;
        if (surface_scan(cd, x, 0, min_y, air_like, &nm, &wy, &sy, &ov,
                         &ov_y)) {
            e["hit"] = true;
            e["name"] = py::str(*nm);
            e["wy"] = py::int_(wy);
            e["sy"] = py::int_(sy);
            if (ov) {
                e["overlay"] = py::str(*ov);
                e["ov_y"] = py::int_(ov_y);
            }
        } else {
            e["hit"] = false;
        }
        probe.append(std::move(e));
    }
    d["probe"] = std::move(probe);
    return d;
}

// ---------------------------------------------------------------------------
// 导出函数：raws（解压后的 chunk NBT 字节流）+ 局部坐标 → 四张 512×512 数组
// ---------------------------------------------------------------------------

py::dict render_region(
    py::list raws,
    py::array_t<i32, py::array::c_style | py::array::forcecast> coords,
    int min_y, int sea_level, int deep_y, std::vector<std::string> air_like_v,
    std::vector<std::string> bed_skip_v, std::vector<std::string> fluids_v) {

    if (coords.ndim() != 2 || coords.shape(1) != 2)
        throw std::runtime_error("coords 必须是 (N, 2) int32 数组");
    const py::ssize_t n_chunks = coords.shape(0);
    if (static_cast<py::ssize_t>(raws.size()) != n_chunks)
        throw std::runtime_error("raws 与 coords 数量不一致");

    const std::unordered_set<std::string> air_like(air_like_v.begin(),
                                                   air_like_v.end());
    const std::unordered_set<std::string> bed_skip(bed_skip_v.begin(),
                                                   bed_skip_v.end());
    const std::unordered_set<std::string> fluids(fluids_v.begin(),
                                                 fluids_v.end());

    // 输出数组（缺省值对齐纯 Python；biomes 用 -1 而非 0，避免把「未取到
    // 群系」误映射成群系名表第 0 项）
    const py::ssize_t kDim = kRegionBlocks;
    py::array_t<i32> blocks({kDim, kDim});
    py::array_t<i16> heights({kDim, kDim});
    py::array_t<i32> biomes({kDim, kDim});
    py::array_t<u8> voidm({kDim, kDim});
    py::array_t<i32> overlay({kDim, kDim});
    py::array_t<i16> disp({kDim, kDim});
    py::array_t<u8> wet({kDim, kDim});
    i32* bp = blocks.mutable_data();
    i16* hp = heights.mutable_data();
    i32* bip = biomes.mutable_data();
    u8* vp = voidm.mutable_data();
    i32* op = overlay.mutable_data();
    i16* dp = disp.mutable_data();
    u8* wtp = wet.mutable_data();
    constexpr size_t kCells =
        static_cast<size_t>(kRegionBlocks) * kRegionBlocks;
    std::fill(bp, bp + kCells, static_cast<i32>(0));
    std::fill(hp, hp + kCells, static_cast<i16>(-64));
    std::fill(bip, bip + kCells, static_cast<i32>(-1));
    std::fill(vp, vp + kCells, static_cast<u8>(0));
    std::fill(op, op + kCells, static_cast<i32>(-1));
    std::fill(dp, dp + kCells, static_cast<i16>(-64));
    std::fill(wtp, wtp + kCells, static_cast<u8>(0));

    // chunk 原始字节指针（GIL 内取好；计算段全程不放回 Python）
    std::vector<const u8*> ptrs;
    std::vector<size_t> sizes;
    ptrs.reserve(static_cast<size_t>(n_chunks));
    sizes.reserve(static_cast<size_t>(n_chunks));
    for (py::ssize_t i = 0; i < n_chunks; ++i) {
        py::bytes b = py::reinterpret_borrow<py::bytes>(raws[i]);
        char* buf = nullptr;
        Py_ssize_t len = 0;
        if (PyBytes_AsStringAndSize(b.ptr(), &buf, &len) != 0)
            throw py::error_already_set();
        ptrs.push_back(reinterpret_cast<const u8*>(buf));
        sizes.push_back(static_cast<size_t>(len));
    }
    auto ci = coords.unchecked<2>();

    NameTable bt;   // 方块名表
    NameTable bit;  // 群系名表
    std::vector<u8> has_data(1024, 0);
    NameTable st;   // 扫描命中名（换床前）——Python 端 ensure_blocks 只收这些，
                    // 海床名走 name2bid.get(_, 0) 兜底，逐位复刻纯 Python 语义

    {
        py::gil_scoped_release release;
        for (py::ssize_t i = 0; i < n_chunks; ++i) {
            const int lx = ci(i, 0);
            const int lz = ci(i, 1);
            if (lx < 0 || lx > 31 || lz < 0 || lz > 31)
                throw std::runtime_error("chunk 局部坐标越界");
            ChunkData cd;
            bool ok = false;
            try {
                ok = parse_chunk(ptrs[i], sizes[i], cd);
            } catch (const std::exception&) {
                ok = false;   // 解析失败 → 整块虚空（对齐 read_chunk 返回 None）
            }
            if (!ok) continue;
            has_data[static_cast<size_t>(lz * 32 + lx)] = 1;

            const int bx0 = lx * kChunk;
            const int bz0 = lz * kChunk;
            for (int z = 0; z < kChunk; ++z) {
                const size_t row = static_cast<size_t>(bz0 + z) * kRegionBlocks;
                i32* brow = bp + row + bx0;
                i16* hrow = hp + row + bx0;
                i32* birow = bip + row + bx0;
                u8* vrow = vp + row + bx0;
                i32* orow = op + row + bx0;
                i16* drow = dp + row + bx0;
                u8* wrow = wtp + row + bx0;
                for (int x = 0; x < kChunk; ++x) {
                    const std::string* nm = nullptr;
                    const std::string* ov = nullptr;
                    int ov_y = 0;
                    int wy = 0, sy = 0;
                    if (!surface_scan(cd, x, z, min_y, air_like, &nm, &wy,
                                      &sy, &ov, &ov_y)) {
                        vrow[x] = 1;   // 未生成/虚空列
                        continue;
                    }
                    bt.intern(*nm);   // 预换名也进名表（对齐纯 Python 第一遍收集）
                    st.intern(*nm);
                    // wet = 表面扫描顶块本身是流体（水/气泡柱）：真实的
                    // 「此列有水覆盖」。不能用工件 heights < sea_level 代替
                    // ——超平坦/空岛等地表低于海平面却无水，会被整片涂蓝
                    const bool col_wet = fluids.find(*nm) != fluids.end();
                    wrow[x] = static_cast<u8>(col_wet ? 1 : 0);
                    const std::string* final_nm = nm;
                    int final_wy = wy;
                    if (fluids.find(*nm) != fluids.end()) {
                        const std::string* bed = nullptr;
                        int bed_y = 0;
                        if (find_seabed(cd, x, z, wy, min_y, bed_skip, &bed,
                                        &bed_y)) {
                            if (bed_y < sea_level - 1) {
                                final_nm = bed;
                                final_wy = bed_y;
                            }
                            // 海床 >= sea_level-1（湖床）→ 不换，palette 平涂
                        } else {
                            final_wy = deep_y;   // 深水 → 纯水分支
                        }
                    }
                    brow[x] = bt.intern(*final_nm);
                    hrow[x] = static_cast<i16>(final_wy);
                    if (ov) orow[x] = bt.intern(*ov);   // 透明层（-1=无）
                    // 显示高度：透明格用透明顶 y（栅栏比地面高 1 格的落差
                    // 参与坡度 bevel -> 立体感）；水色链/wet 仍用 heights
                    drow[x] = static_cast<i16>(ov ? ov_y : final_wy);
                    const std::string* bn = surface_biome_at(cd, x, z, sy);
                    birow[x] = bn ? bit.intern(*bn) : -1;
                }
            }
        }
        // 反向虚空标记：凡未产出数据的槽位（无文件条目/读取失败/半生成/
        // 解析失败）整 16×16 标 void
        for (int lz = 0; lz < 32; ++lz) {
            for (int lx = 0; lx < 32; ++lx) {
                if (has_data[static_cast<size_t>(lz * 32 + lx)]) continue;
                for (int z = 0; z < kChunk; ++z) {
                    u8* row = vp + static_cast<size_t>(lz * kChunk + z) *
                                        kRegionBlocks + lx * kChunk;
                    std::fill(row, row + kChunk, static_cast<u8>(1));
                }
            }
        }
    }

    py::list block_names;
    for (const auto& s : bt.names) block_names.append(py::str(s));
    py::list biome_names;
    for (const auto& s : bit.names) biome_names.append(py::str(s));
    py::list surface_names;
    for (const auto& s : st.names) surface_names.append(py::str(s));
    py::dict out;
    out["block_names"] = std::move(block_names);
    out["biome_names"] = std::move(biome_names);
    out["surface_names"] = std::move(surface_names);
    out["blocks"] = std::move(blocks);
    out["heights"] = std::move(heights);
    out["biomes"] = std::move(biomes);
    out["void"] = std::move(voidm);
    out["overlay"] = std::move(overlay);
    out["wet"] = std::move(wet);
    out["disp"] = std::move(disp);
    return out;
}

PYBIND11_MODULE(_region_render, m) {
    m.doc() = "SaveManager 俯视 region 解码核心（语义对齐 chunk_render.py / "
              "world_render.py 纯 Python 路径）";
    m.def("render_region", &render_region, py::arg("raws"), py::arg("coords"),
          py::arg("min_y"), py::arg("sea_level"), py::arg("deep_y"),
          py::arg("air_like"), py::arg("bed_skip"), py::arg("fluids"),
          "解压后的 chunk NBT 字节流列表 → 512×512 blocks/heights/biomes/"
          "void/overlay/disp/wet 数组 + block_names/biome_names 名字表");
    m.def("debug_parse", &debug_parse, py::arg("raw"), py::arg("min_y"),
          py::arg("air_like"),
          "解析单个 chunk 字节流，回报 ok/err/每节概要/列扫描探针（诊断用）");
}
