// _solver_native.cpp —— SeedReverser 层 2 的 C++ 多线程扩展（pybind11）。
//
// 只承载占绝大部分耗时的层 2（高位全枚举 + 逐观测压缩验证）；层 1/层 3
// 仍由 Utils/SeedReverser/structure_math.py 的 Python 实现完成。
//
// 语义承诺：与 _layer2_np 完全一致——
//   输入  lift_obs（dict 列表，须含 salt/chunk_range/reg_x/reg_z/off_x/off_z；
//         每行可选 "tol" 键：该观测的站位容差（逐观测独立），
//         0 = 精确比较，>0 = |off-guess| ≤ tol）
//         lows（幸存低位 uint64 数组，升序）、low_bits（低位位宽）
//   计算  对每个 low 枚举 2^(48-low_bits) 个高位，seed=(upper<<low_bits)|lower，
//         逐观测 region_seed → struct_next_int（offX 先筛，幸存再算 offZ）
//   输出  通过全部观测的 48 位种子，升序 uint64 numpy 数组
// RNG 复刻（mc_random.py）：
//   next_state(s)=(s*K+B)&M48；struct_next_int 无拒绝采样（2 幂走移乘，否则取模）
//   region_seed=(seed + rx*REG_X + rz*REG_Z + salt) mod 2^64 后 ^K 再 &M48
//
// 线程模型：
//   - 计算线程池：按高位区间 [begin,end) 分片（幸存低位常只有个位数，按低位
//     分片会退化成单线程；2^28 高位区间足够大，负载天然均衡），全程无 GIL。
//   - monitor 线程：每 30ms 唤醒一次，短暂持有 GIL 调用 Python 回调——
//     check_cancel() → 置取消标志（计算线程每 64 次迭代无锁轮询该标志）；
//     on_progress(done, total, "层2") → 转发进度。计算线程自身不做任何
//     Python 调用，GIL 竞争可忽略。
//
// 重建扩展：python Utils/SeedReverser/_native/build_native.py
// 手动编译（参考）：cl /nologo /O2 /EHsc /std:c++20 /utf-8 /LD
//   /I<pybind11 include> /I<python include> _solver_native.cpp
//   /Fe:_solver_native.pyd /link /LIBPATH:<python libs> python313.lib

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>

#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace py = pybind11;
using u64 = std::uint64_t;
using i64 = std::int64_t;

// ---------------------------------------------------------------------------
// RNG（mc_random.py 精确复刻）
// ---------------------------------------------------------------------------
static constexpr u64 K = 0x5DEECE66DULL;      // LCG 乘子
static constexpr u64 B = 0xBULL;              // LCG 增量
static constexpr u64 M48 = (1ULL << 48) - 1;  // 48 位状态掩码
static constexpr u64 REG_X_COEF = 341873128712ULL;
static constexpr u64 REG_Z_COEF = 132897987541ULL;

static inline u64 next_state(u64 s) { return (s * K + B) & M48; }

// 结构定位 nextInt（无拒绝采样）：2 幂走 (r*(nxt>>17))>>31，否则取模
static inline u64 struct_next_int(u64& state, u64 r) {
    u64 nxt = next_state(state);
    state = nxt;
    if ((r & (r - 1)) == 0) {
        return (r * (nxt >> 17)) >> 31;
    }
    return (nxt >> 17) % r;
}

// region_seed：结构种 + 区域坐标 + salt → setSeed 后状态（uint64 自然回绕）
static inline u64 region_seed(u64 structure_seed, i64 reg_x, i64 reg_z, u64 salt) {
    u64 v = structure_seed
          + (static_cast<u64>(reg_x) * REG_X_COEF)
          + (static_cast<u64>(reg_z) * REG_Z_COEF)
          + salt;
    return (v ^ K) & M48;
}

// ---------------------------------------------------------------------------
// 观测行（从 Python dict 解析后的扁平结构，计算期零 Python 交互）
// ---------------------------------------------------------------------------
struct ObsRow {
    u64 salt;
    u64 r;          // chunk_range
    u64 off_x, off_z;
    i64 reg_x, reg_z;
    i64 tol;        // 站位容差（0 = 精确比较）
};

// 进度上报步长（4M 迭代一次原子加；低位结束时补余数，保证计数精确）
static constexpr u64 PROG_STEP = 1ULL << 22;
// 取消检查点：每 64 次迭代读一次取消标志（无锁，开销可忽略）
static constexpr u64 CANCEL_MASK = 63ULL;

// ---------------------------------------------------------------------------
// 层 2 worker：处理高位区间 [begin, end) × 全部低位
// ---------------------------------------------------------------------------
static void layer2_worker(const std::vector<ObsRow>& obs,
                          const u64* lows, size_t n_lows,
                          int low_bits, u64 begin, u64 end,
                          std::atomic<u64>& done_cnt,
                          const std::atomic<bool>& cancelled,
                          std::vector<u64>& out,
                          std::string& err) {
    const size_t n_obs = obs.size();
    const u64 span = end - begin;
    try {
        out.reserve(256);
        for (size_t li = 0; li < n_lows; ++li) {
            if (cancelled.load(std::memory_order_relaxed)) {
                return;
            }
            const u64 lower = lows[li];
            for (u64 upper = begin; upper < end; ++upper) {
                if ((upper & CANCEL_MASK) == 0 &&
                        cancelled.load(std::memory_order_relaxed)) {
                    return;
                }
                const u64 seed = (upper << low_bits) | lower;
                bool alive = true;
                for (size_t oi = 0; oi < n_obs; ++oi) {
                    const ObsRow& ob = obs[oi];
                    u64 state = region_seed(seed, ob.reg_x, ob.reg_z, ob.salt);
                    u64 ox = struct_next_int(state, ob.r);
                    // tol = 0：精确比较；tol > 0：范围校验（int64 距离，
                    // 不跨区域绕回，与 _layer2_np 语义一致）
                    if (ob.tol > 0) {
                        if (std::abs(static_cast<i64>(ox) - static_cast<i64>(ob.off_x)) > ob.tol) {
                            alive = false; break;
                        }
                    } else if (ox != ob.off_x) {   // offX 先筛省 ~45%
                        alive = false; break;
                    }
                    u64 oz = struct_next_int(state, ob.r);
                    if (ob.tol > 0) {
                        if (std::abs(static_cast<i64>(oz) - static_cast<i64>(ob.off_z)) > ob.tol) {
                            alive = false; break;
                        }
                    } else if (oz != ob.off_z) {
                        alive = false; break;
                    }
                }
                if (alive) {
                    out.push_back(seed);
                }
                if (((upper - begin + 1) & (PROG_STEP - 1)) == 0) {
                    done_cnt.fetch_add(PROG_STEP, std::memory_order_relaxed);
                }
            }
            // 本低位完成：补报非 4M 对齐的余数（done 总量 = span × 低位数）
            done_cnt.fetch_add(span & (PROG_STEP - 1), std::memory_order_relaxed);
        }
    } catch (const std::exception& e) {
        err = e.what();
    } catch (...) {
        err = "layer2 worker: unknown error";
    }
}

// ---------------------------------------------------------------------------
// 导出函数：layer2_full
// ---------------------------------------------------------------------------
static py::array_t<u64> layer2_full(
        py::sequence obs_seq,
        py::sequence lows_seq,
        int low_bits,
        py::object on_progress,
        py::object check_cancel) {
    // ---- 解析参数（持 GIL）----
    std::vector<ObsRow> rows;
    rows.reserve(obs_seq.size());
    for (auto item : obs_seq) {
        py::dict d = item.cast<py::dict>();
        ObsRow ob;
        ob.salt = d["salt"].cast<u64>();
        ob.r = d["chunk_range"].cast<u64>();
        ob.off_x = d["off_x"].cast<u64>();
        ob.off_z = d["off_z"].cast<u64>();
        ob.reg_x = d["reg_x"].cast<i64>();
        ob.reg_z = d["reg_z"].cast<i64>();
        // per-obs 容差：每行 "tol" 键（缺省 0 = 精确比较；Python 层
        // 已归一化 0~2，此处仅兑底防御性锦制）
        if (d.contains("tol")) {
            ob.tol = d["tol"].cast<i64>();
        } else {
            ob.tol = 0;
        }
        if (ob.tol < 0) ob.tol = 0;
        if (ob.tol > 2) ob.tol = 2;
        if (ob.r == 0) {
            throw std::runtime_error("chunk_range must be positive");
        }
        rows.push_back(ob);
    }
    // 低位列表 → 连续 u64 缓冲（转换期持 GIL，计算期只用裸指针）
    const size_t n_lows = static_cast<size_t>(lows_seq.size());
    std::vector<u64> lows_buf(n_lows);
    {
        size_t i = 0;
        for (auto item : lows_seq) {
            lows_buf[i++] = item.cast<u64>();
        }
    }
    if (rows.empty() || n_lows == 0 || low_bits <= 0 || low_bits >= 48) {
        // 与 _layer2_np 一致：无观测/无低位 → 空结果
        return py::array_t<u64>({static_cast<py::ssize_t>(0)});
    }

    const int high_bits = 48 - low_bits;
    const u64 total_high = 1ULL << high_bits;
    const u64 total_iters = total_high * static_cast<u64>(n_lows);

    unsigned hc = std::thread::hardware_concurrency();
    if (hc == 0) hc = 4;
    if (hc > 64) hc = 64;
    // 分片数不超过高位总量，保证每片非空
    const int n_threads = static_cast<int>(
        std::min<u64>(hc, total_high));

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

        // monitor：低频唤醒，持 GIL 调 Python 回调（取消探测 / 进度转发）。
        // 等待用条件变量：结束时立即唤醒，不留尾延迟。
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
                        // 回调异常：取消探测失败不致命，忽略
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
                                        "层2");
                        } catch (...) {
                            // 进度回调异常不影响计算
                        }
                    }
                }
                lk.lock();
            }
        });

        std::vector<std::thread> pool;
        const u64 per = (total_high + n_threads - 1) / n_threads;
        pool.reserve(n_threads);
        for (int t = 0; t < n_threads; ++t) {
            const u64 begin = static_cast<u64>(t) * per;
            const u64 end = std::min<u64>(total_high, begin + per);
            if (begin >= end) {
                pool.emplace_back([]() {});  // 占位保持索引对齐
                continue;
            }
            pool.emplace_back([&rows, &lows_buf, &buckets, &errs, &done_cnt,
                               &cancelled, n_lows, low_bits, begin, end, t]() {
                layer2_worker(rows, lows_buf.data(), n_lows, low_bits, begin, end,
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
            throw std::runtime_error("layer2 native: " + e);
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
// 模块定义
// ---------------------------------------------------------------------------
PYBIND11_MODULE(_solver_native, m) {
    m.doc() = "SeedReverser 层 2 的 C++ 多线程扩展（语义与 _layer2_np 一致）";
    m.def("layer2_full", &layer2_full,
          py::arg("lift_obs"),
          py::arg("lows"),
          py::arg("low_bits"),
          py::arg("on_progress") = py::none(),
          py::arg("check_cancel") = py::none(),
          "层 2 高位枚举（多线程）。\n\n"
          "Args:\n"
          "    lift_obs: 观测 dict 列表（salt/chunk_range/reg_x/reg_z/off_x/off_z；"
          "每行可选 \"tol\" 键：该观测的站位容差，缺省 0）\n"
          "    lows: 幸存低位列表（升序）\n"
          "    low_bits: 低位位宽（48-high_bits）\n"
          "    on_progress: 可选回调 (done, total, '层2')\n"
          "    check_cancel: 可选回调 () -> bool，返回 True 提前取消\n\n"
          "Returns:\n"
          "    通过全部观测的 48 位种子（升序 uint64 numpy 数组）");
}
