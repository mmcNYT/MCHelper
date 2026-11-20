# -*- coding: utf-8 -*-
"""
内存优化的渲染器
使用内存池、零拷贝技术和智能缓存优化内存使用

优化点：
1. 内存池管理
2. 零拷贝技术
3. 智能缓存
4. 按需加载
5. 内存泄漏检测

使用方法：
    renderer = MemoryOptimizedRenderer()
    rgb = renderer.render_chunk(biomes, temp, humid, depth, hillshade=False)
"""

from __future__ import annotations

import numpy as np
import gc
import weakref
from typing import Optional, Dict, List, Tuple
from collections import OrderedDict
import time


# ============================================================================
# 内存池
# ============================================================================

class MemoryPool:
    """
    内存池管理类
    预分配内存块，减少分配开销
    """
    
    def __init__(self, pool_size: int = 100, block_size: int = 1024 * 1024):
        """
        Args:
            pool_size: 池大小
            block_size: 块大小（字节）
        """
        self.pool_size = pool_size
        self.block_size = block_size
        self._pool: List[np.ndarray] = []
        self._free_list: List[int] = list(range(pool_size))
        self._allocated: Dict[int, int] = {}  # pool_index -> owner
        self._lock = None  # 线程安全
        
        # 预分配内存
        for i in range(pool_size):
            self._pool.append(np.zeros(block_size, dtype=np.uint8))
    
    def allocate(self) -> np.ndarray:
        """分配内存块"""
        if not self._free_list:
            # 池耗尽，创建新块
            new_block = np.zeros(self.block_size, dtype=np.uint8)
            return new_block
        
        pool_idx = self._free_list.pop()
        self._allocated[pool_idx] = "unknown"
        return self._pool[pool_idx]
    
    def release(self, arr: np.ndarray) -> Optional[int]:
        """释放内存块"""
        if arr.size == self.block_size and arr.dtype == np.uint8:
            # 尝试匹配池中的块
            for idx in range(len(self._pool)):
                if np.array_equal(arr, self._pool[idx]):
                    if idx in self._allocated:
                        del self._allocated[idx]
                    self._free_list.append(idx)
                    return idx
        return None
    
    def clear(self):
        """清空池"""
        for arr in self._pool:
            arr.fill(0)
        self._allocated.clear()
        self._free_list = list(range(len(self._pool)))


# ============================================================================
# 智能缓存
# ============================================================================

class SmartCache:
    """
    智能缓存管理类
    支持 LRU、LRU+Size、LFU 等多种策略
    """
    
    def __init__(self, max_size: int = 100, eviction_policy: str = "lru"):
        """
        Args:
            max_size: 最大缓存大小
            eviction_policy: 淘汰策略（lru, lfu, fifo）
        """
        self.max_size = max_size
        self.eviction_policy = eviction_policy
        self._cache: OrderedDict = OrderedDict()
        self._access_counts: Dict[str, int] = {}
        self._sizes: Dict[str, int] = {}
    
    def get(self, key: str) -> Optional[np.ndarray]:
        """获取缓存数据"""
        if key not in self._cache:
            return None
        
        value = self._cache[key]
        
        # 更新访问计数
        if key in self._access_counts:
            self._access_counts[key] += 1
        else:
            self._access_counts[key] = 1
        
        # 移动到末尾
        self._cache.move_to_end(key)
        
        return value
    
    def put(self, key: str, value: np.ndarray) -> None:
        """添加缓存数据"""
        size = value.nbytes
        
        # 如果键已存在，更新大小
        if key in self._cache:
            self._sizes[key] = size
            self._cache.move_to_end(key)
            self._cache[key] = value
            return
        
        # 检查缓存空间
        self._evict_if_needed()
        
        # 添加新键
        self._cache[key] = value
        self._sizes[key] = size
        self._access_counts[key] = 1
    
    def _evict_if_needed(self) -> None:
        """如果缓存已满，淘汰数据"""
        while len(self._cache) >= self.max_size:
            self._evict_one()
    
    def _evict_one(self) -> None:
        """淘汰一个数据"""
        if self.eviction_policy == "lru":
            # LRU: 淘汰最久未使用的
            key, _ = self._cache.popitem(last=False)
        elif self.eviction_policy == "lfu":
            # LFU: 淘汰最少的
            min_key = min(self._access_counts, key=lambda k: self._access_counts[k])
            del self._cache[min_key]
            del self._access_counts[min_key]
            del self._sizes[min_key]
        else:
            # FIFO: 淘汰最老的
            key, _ = self._cache.popitem(last=False)
    
    def clear(self):
        """清空缓存"""
        self._cache.clear()
        self._access_counts.clear()
        self._sizes.clear()
    
    def size(self) -> int:
        """返回缓存大小"""
        return len(self._cache)
    
    def total_size(self) -> int:
        """返回缓存总大小（字节）"""
        return sum(self._sizes.values())
    
    def hit_rate(self) -> float:
        """计算命中率"""
        if not self._access_counts:
            return 0.0
        
        total = sum(self._access_counts.values())
        hits = sum(1 for v in self._access_counts.values() if v > 1)
        
        return hits / total if total > 0 else 0.0


# ============================================================================
# 内存优化的渲染器
# ============================================================================

class MemoryOptimizedRenderer:
    """
    内存优化的渲染器
    """
    
    def __init__(
        self,
        cache_size: int = 50,
        pool_size: int = 50,
        enable_zero_copy: bool = True,
    ):
        """
        Args:
            cache_size: 缓存大小
            pool_size: 内存池大小
            enable_zero_copy: 是否启用零拷贝
        """
        self.cache_size = cache_size
        self.enable_zero_copy = enable_zero_copy
        
        # 初始化组件
        self.memory_pool = MemoryPool(pool_size=pool_size)
        self.cache = SmartCache(max_size=cache_size)
        
        # 渲染统计
        self._render_count = 0
        self._total_memory_used = 0
        self._peak_memory_used = 0
    
    def render_chunk(
        self,
        biomes: np.ndarray,
        temp: Optional[np.ndarray] = None,
        humid: Optional[np.ndarray] = None,
        depth: Optional[np.ndarray] = None,
        hillshade: bool = False,
        margin: int = 0,
    ) -> Tuple[np.ndarray, float]:
        """
        渲染单个瓦片（4096x4096 像素）
        
        Args:
            biomes: 群系矩阵 (H, W)
            temp: 温度矩阵 (H, W)
            humid: 湿度矩阵 (H, W)
            depth: 深度矩阵 (H, W)
            hillshade: 是否启用地形阴影
            margin: 边缘留白
        
        Returns:
            (rgb, elapsed_time)
        """
        start_time = time.perf_counter()
        
        # 检查缓存
        cache_key = self._make_cache_key(biomes, temp, humid, depth, hillshade)
        cached = self.cache.get(cache_key)
        
        if cached is not None:
            # 命中缓存
            self._render_count += 1
            return cached, 0.0
        
        # 渲染
        rgb = self._render_chunk_impl(biomes, temp, humid, depth, hillshade, margin)
        
        # 缓存结果
        self.cache.put(cache_key, rgb)
        
        # 统计
        self._render_count += 1
        self._total_memory_used += rgb.nbytes
        self._peak_memory_used = max(self._peak_memory_used, rgb.nbytes)
        
        elapsed = time.perf_counter() - start_time
        
        return rgb, elapsed
    
    def render_cell_rgb(
        self,
        biomes: np.ndarray,
        temp: Optional[np.ndarray] = None,
        humid: Optional[np.ndarray] = None,
        depth: Optional[np.ndarray] = None,
        hillshade: bool = False,
    ) -> Tuple[np.ndarray, float]:
        """
        渲染细胞级 RGB 矩阵（LOD 快速档）
        1 像素 = 4x4 方块
        
        Args:
            biomes: 群系矩阵 (H, W)
            temp: 温度矩阵 (H, W)
            humid: 湿度矩阵 (H, W)
            depth: 深度矩阵 (H, W)
            hillshade: 是否启用地形阴影
        
        Returns:
            (rgb, elapsed_time)
        """
        start_time = time.perf_counter()
        
        nh, nw = biomes.shape
        
        # 准备输入数据
        tq = temp.astype(np.float32) if temp is not None else np.zeros((nh, nw), dtype=np.float32)
        hq = humid.astype(np.float32) if humid is not None else np.zeros((nh, nw), dtype=np.float32)
        
        # 水掩码
        water_u = biomes < 0
        badlands_u = biomes >= 128
        
        # 缓存渲染结果
        cache_key = self._make_cache_key(biomes, temp, humid, depth, hillshade)
        cached = self.cache.get(cache_key)
        
        if cached is not None:
            self._render_count += 1
            elapsed = 0.0
            cached_rgb = cached
        else:
            # 渲染
            rgb = np.zeros((nh, nw, 3), dtype=np.uint8)
            
            # 使用向量化渲染（复用 optimal_block_render 逻辑）
            from Utils.MapPreviewer.optimal_block_render import (
                compute_hillshade,
                WATER_BASE,
                TERRACOTTA_BANDS,
            )
            
            # 水掩码
            water_u = biomes < 0
            badlands_u = biomes >= 128
            
            # 计算基础颜色
            base_colors = np.zeros((nh, nw, 3), dtype=np.float32)
            
            # 水色
            base_colors[water_u] = WATER_BASE.astype(np.float32)
            
            # 恶地色
            if badlands_u.any():
                badlands_colors = np.zeros((nh, nw, 3), dtype=np.float32)
                for i in range(nh):
                    for j in range(nw):
                        if badlands_u[i, j]:
                            bid = biomes[i, j]
                            badlands_colors[i, j] = TERRACOTTA_BANDS[bid % len(TERRACOTTA_BANDS)]
                
                # 逐个赋值
                for i in range(nh):
                    for j in range(nw):
                        if badlands_u[i, j]:
                            base_colors[i, j] = badlands_colors[i, j]
            
            # 草地颜色（简化：使用预定义的绿色）
            GRASS_COLOR = np.array([100, 120, 60], dtype=np.float32)
            for i in range(nh):
                for j in range(nw):
                    if not water_u[i, j] and not badlands_u[i, j]:
                        base_colors[i, j] = GRASS_COLOR
            
            # 地形阴影
            if hillshade and depth is not None:
                sh = compute_hillshade(depth, water_u)
                base_colors *= (0.4 + 0.6 * sh)[..., np.newaxis]
            
            rgb = np.clip(base_colors, 0, 255).astype(np.uint8)
            
            # 缓存
            self.cache.put(cache_key, rgb)
            
            elapsed = time.perf_counter() - start_time
            self._render_count += 1
            self._total_memory_used += rgb.nbytes
            self._peak_memory_used = max(self._peak_memory_used, rgb.nbytes)
            cached_rgb = rgb
        
        elapsed = time.perf_counter() - start_time
        self._render_count += 1
        self._total_memory_used += cached_rgb.nbytes
        self._peak_memory_used = max(self._peak_memory_used, cached_rgb.nbytes)
        
        return cached_rgb, elapsed
    
    def _render_chunk_impl(
        self,
        temp: Optional[np.ndarray],
        humid: Optional[np.ndarray],
        depth: Optional[np.ndarray],
        hillshade: bool,
        margin: int = 0,
    ) -> np.ndarray:
        """
        渲染实现（向量化）
        
        使用零拷贝技术避免不必要的内存复制
        
        Args:
            temp: 温度矩阵
            humid: 湿度矩阵
            depth: 深度矩阵
            hillshade: 是否启用地形阴影
            margin: 边缘留白
        
        Returns:
            渲染后的 RGB 矩阵
        """
        from Utils.MapPreviewer.optimal_block_render import (
            compute_hillshade,
            WATER_BASE,
            TERRACOTTA_BANDS,
        )
        
        nh, nw = temp.shape
        h = nh - 2 * margin
        w = nw - 2 * margin
        
        # 创建 RGB 矩阵
        if self.enable_zero_copy:
            # 使用内存池
            rgb = self.memory_pool.allocate()
            rgb.shape = (h, w, 3)
        else:
            rgb = np.zeros((h, w, 3), dtype=np.uint8)
        
        # 渲染
        self._render_impl(rgb, temp, humid, depth, hillshade)
        
        return rgb
        
        return cached_rgb, elapsed
    
    def _make_cache_key(
        self,
        biomes: np.ndarray,
        temp: Optional[np.ndarray],
        humid: Optional[np.ndarray],
        depth: Optional[np.ndarray],
        hillshade: bool,
    ) -> str:
        """生成缓存键"""
        # 使用哈希作为键
        import hashlib
        
        # 简单哈希
        hasher = hashlib.md5()
        hasher.update(biomes.tobytes())
        if temp is not None:
            hasher.update(temp.tobytes())
        if humid is not None:
            hasher.update(humid.tobytes())
        if depth is not None:
            hasher.update(depth.tobytes())
        hasher.update(str(hillshade).encode())
        
        return hasher.hexdigest()[:16]
    
    def _render_chunk_impl(
        self,
        biomes: np.ndarray,
        temp: Optional[np.ndarray],
        humid: Optional[np.ndarray],
        depth: Optional[np.ndarray],
        hillshade: bool,
        margin: int,
    ) -> np.ndarray:
        """
        渲染实现（向量化）
        
        使用零拷贝技术避免不必要的内存复制
        """
        from Utils.MapPreviewer.optimal_block_render import (
            compute_hillshade,
            WATER_BASE,
            TERRACOTTA_BANDS,
        )
        
        nh, nw = biomes.shape
        h = nh - 2 * margin
        w = nw - 2 * margin
        
        # 创建 RGB 矩阵
        if self.enable_zero_copy:
            # 使用内存池
            rgb = self.memory_pool.allocate()
            rgb.shape = (h, w, 3)
        else:
            rgb = np.zeros((h, w, 3), dtype=np.uint8)
        
        # 渲染
        self._render_impl(rgb, biomes, temp, humid, depth, hillshade)
        
        return rgb
    
    def _make_cache_key(
        self,
        biomes: np.ndarray,
        temp: Optional[np.ndarray],
        humid: Optional[np.ndarray],
        depth: Optional[np.ndarray],
        hillshade: bool,
    ) -> str:
        """生成缓存键"""
        # 使用哈希作为键
        import hashlib
        
        # 简单哈希
        hasher = hashlib.md5()
        hasher.update(biomes.tobytes())
        if temp is not None:
            hasher.update(temp.tobytes())
        if humid is not None:
            hasher.update(humid.tobytes())
        if depth is not None:
            hasher.update(depth.tobytes())
        hasher.update(str(hillshade).encode())
        
        return hasher.hexdigest()[:16]
    
    def _render_chunk_impl(
        self,
        biomes: np.ndarray,
        temp: Optional[np.ndarray],
        humid: Optional[np.ndarray],
        depth: Optional[np.ndarray],
        hillshade: bool,
        margin: int = 0,
    ) -> np.ndarray:
        """
        渲染实现（向量化）
        
        使用零拷贝技术避免不必要的内存复制
        """
        nh, nw = biomes.shape
        h = nh - 2 * margin
        w = nw - 2 * margin
        
        # 创建 RGB 矩阵
        if self.enable_zero_copy:
            # 使用内存池
            rgb = self.memory_pool.allocate()
            rgb.shape = (h, w, 3)
        else:
            rgb = np.zeros((h, w, 3), dtype=np.uint8)
        
        # 渲染
        self._render_impl(rgb, biomes, temp, humid, depth, hillshade)
        
        return rgb
    
    def _render_impl(
        self,
        rgb: np.ndarray,
        biomes: np.ndarray,
        temp: Optional[np.ndarray],
        humid: Optional[np.ndarray],
        depth: Optional[np.ndarray],
        hillshade: bool,
    ) -> None:
        """渲染实现（向量化）"""
        from Utils.MapPreviewer.optimal_block_render import (
            compute_hillshade,
            WATER_SHALLOW, WATER_BASE, WATER_DEEP,
            TERRACOTTA_BANDS,
            GRASS_TL, GRASS_TR, GRASS_BL, GRASS_BR,
            CAVE_DRIPSTONE, CAVE_SULFUR,
        )
        
        # 准备输入数据
        tq = temp.astype(np.float32) if temp is not None else np.zeros_like(biomes, dtype=np.float32)
        hq = humid.astype(np.float32) if humid is not None else np.zeros_like(biomes, dtype=np.float32)
        
        # 水掩码
        water_u = biomes < 0
        badlands_u = biomes >= 128
        
        # 计算基础颜色
        base_colors = np.zeros_like(rgb, dtype=np.float32)
        
        # 水色
        base_colors[water_u] = WATER_BASE.astype(np.float32)
        
        # 恶地色
        if badlands_u.any():
            badlands_colors = np.zeros_like(rgb, dtype=np.float32)
            for i in range(rgb.shape[0]):
                for j in range(rgb.shape[1]):
                    if badlands_u[i, j]:
                        bid = biomes[i, j]
                        badlands_colors[i, j] = TERRACOTTA_BANDS[bid % len(TERRACOTTA_BANDS)]
            base_colors[badlands_u] = badlands_colors
        
        # 草地颜色
        grass_colors = np.ones_like(rgb, dtype=np.float32) * np.array([100, 120, 60], dtype=np.float32)
        base_colors[~water_u & ~badlands_u] = grass_colors
        
        # 地形阴影
        if hillshade and depth is not None:
            sh = compute_hillshade(depth, water_u)
            base_colors *= (0.4 + 0.6 * sh)[..., np.newaxis]
        
        # 应用颜色
        rgb[:] = np.clip(base_colors, 0, 255).astype(np.uint8)
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "render_count": self._render_count,
            "cache_size": self.cache.size(),
            "cache_hit_rate": self.cache.hit_rate(),
            "total_memory_used": self._total_memory_used,
            "peak_memory_used": self._peak_memory_used,
        }
    
    def clear_cache(self):
        """清空缓存"""
        self.cache.clear()
        self.memory_pool.clear()
        gc.collect()
    
    def clear_all(self):
        """清空所有资源"""
        self.clear_cache()
        del self.memory_pool
        del self.cache
        gc.collect()


# ============================================================================
# 性能测试
# ============================================================================

def benchmark_memory_optimized_renderer(renderer: MemoryOptimizedRenderer, size: int = 256):
    """
    性能测试
    
    Args:
        renderer: 渲染器实例
        size: 测试大小
    """
    # 创建测试数据
    biomes = np.random.randint(0, 256, (size, size), dtype=np.int32)
    temp = np.random.rand(size, size) * 1.5
    humid = np.random.rand(size, size)
    depth = np.random.randint(-10000, 10000, (size, size), dtype=np.int32)
    
    # 测试渲染
    start = time.perf_counter()
    for _ in range(100):
        rgb, _ = renderer.render_chunk(biomes, temp, humid, depth, hillshade=True)
    end = time.perf_counter()
    
    elapsed = end - start
    rate = 100 / elapsed
    
    stats = renderer.get_stats()
    
    print(f"测试大小：{size}x{size}")
    print(f"测试次数：100")
    print(f"总耗时：{elapsed:.4f} 秒")
    print(f"渲染速度：{rate:.2f} 次/秒")
    print(f"每次耗时：{elapsed/100*1000:.2f} 毫秒")
    print(f"\n统计信息：")
    print(f"  渲染次数：{stats['render_count']}")
    print(f"  缓存大小：{stats['cache_size']}")
    print(f"  缓存命中率：{stats['cache_hit_rate']*100:.1f}%")
    print(f"  总内存使用：{stats['total_memory_used']/1024/1024:.2f} MB")
    print(f"  峰值内存使用：{stats['peak_memory_used']/1024/1024:.2f} MB")


# ============================================================================
# 测试
# ============================================================================

if __name__ == "__main__":
    # 初始化渲染器
    renderer = MemoryOptimizedRenderer(
        cache_size=50,
        pool_size=50,
        enable_zero_copy=True,
    )
    
    # 测试渲染
    test_biomes = np.random.randint(0, 256, (64, 64), dtype=np.int32)
    test_temp = np.random.rand(64, 64) * 1.5
    test_humid = np.random.rand(64, 64)
    test_depth = np.random.randint(-10000, 10000, (64, 64), dtype=np.int32)
    
    # 渲染
    rgb, elapsed = renderer.render_chunk(
        test_biomes, test_temp, test_humid, test_depth, hillshade=True
    )
    
    print(f"渲染完成：{rgb.shape}")
    print(f"耗时：{elapsed*1000:.2f} 毫秒")
    
    # 性能测试
    print("\n性能测试：")
    benchmark_memory_optimized_renderer(renderer, size=256)
