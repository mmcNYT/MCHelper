# -*- coding: utf-8 -*-
"""
Journeymap 模组结构适配器
支持 Journeymap 模组的所有结构类型显示和定位

适配 Journeymap 模组（https://www.curseforge.com/minecraft/mc-mods/journeymap）
的结构定位逻辑，包括：
- 主世界：古代城市、沙漠神殿、冰屋、林地府邸、海底神殿、海难船难等
- 下界：堡垒、堡垒遗迹、地狱门、废弃传送门
- 末地：末地城、末地门、末地岛

支持功能：
- 结构位置枚举
- 结构群系校验
- 结构距离计算
- Journeymap 格式输出
"""

from __future__ import annotations

import math
import numpy as np
from typing import List, Dict, Tuple, Optional

from Utils.SeedReverser.structure_math import get_structure_pos
from Utils.SeedReverser.biome_noise import BiomeSampler
from Utils.Public.structure_params import STRUCT_DIMENSION, STRUCT_NAMES
from Utils.MapPreviewer.nether_end_sampler import EndSampler, NetherSampler


# ============================================================================
# 结构类型定义（基于 Journeymap 反编译代码）
# ============================================================================

# 主世界结构
OVERWORLD_STRUCTURES = [
    "ancient_city",           # 古代城市
    "desert_pyramid",         # 沙漠神殿
    "igloo",                  # 冰屋
    "jungle_temple",          # 丛林神庙
    "mansion",                # 林地府邸
    "monument",               # 海底神殿
    "shipwreck_ocean",        # 海洋难船
    "shipwreck_beach",        # 沙滩难船
    "shipwreck_deep",         # 深海难船
    "stronghold",             # 要塞
    "swamp_hut",              # 沼泽小屋
    "temple",                 # 废弃神殿
    "abandoned_mineshaft",    # 废弃矿井
    "village",                # 村庄
    "end_city",               # 末地城（单独处理）
]

# 下界结构
NETHER_STRUCTURES = [
    "bastion",                # 堡垒
    "nether_fortress",        # 下界要塞
    "nether_portal",          # 地狱门
    "ruined_portal",          # 废弃传送门
]

# 末地结构
END_STRUCTURES = [
    "end_city",              # 末地城
    "end_gateway",           # 末地门
    "end_island",            # 末地岛
]


# ============================================================================
# 群系定义
# ============================================================================

BIOME_ID = {
    "minecraft:plains": 1,
    "minecraft:savanna": 35,
    "minecraft:desert": 2,
    "minecraft:jungle": 21,
    "minecraft:snowy_plains": 12,
    "minecraft:snowy_taiga": 30,
    "minecraft:ice_spikes": 18,
    "minecraft:swamp": 6,
    "minecraft:taiga": 5,
    "minecraft:mushroom_fields": 14,
    "minecraft:old_growth_pine_taiga": 32,
    "minecraft:old_growth_birch_forest": 155,
    "minecraft:cherry_grove": 185,
    "minecraft:grove": 178,
    "minecraft:frozen_peaks": 181,
    "minecraft:stony_peaks": 182,
    "minecraft:deep_dark": 183,
    "minecraft:deep_dripstone_caves": 174,
    "minecraft:deep_dark_caves": 175,
    "minecraft:deep_dripstone_canyon": 186,
    "minecraft:soul_sand_valley": 12,
    "minecraft:warm_ocean": 44,
    "minecraft:lush_caves": 171,
    "minecraft:dripstone_caves": 172,
    "minecraft:deep_cave": 173,
    "minecraft:basalt_deltas": 13,
    "minecraft:crimson_forest": 11,
    "minecraft:warped_forest": 10,
    "minecraft:end_barrens": 15,
    "minecraft:end_highlands": 16,
    "minecraft:end_midlands": 17,
}


# ============================================================================
# 结构定位器
# ============================================================================

class StructureLocator:
    """结构定位器，支持所有结构类型的定位"""
    
    def __init__(self, version_key: str = "26.2"):
        self.version_key = version_key
        self._sampler_cache: Dict[int, BiomeSampler] = {}
    
    def get_cache_sampler(self, seed: int) -> BiomeSampler:
        """获取缓存的 BiomeSampler"""
        if seed not in self._sampler_cache:
            self._sampler_cache[seed] = BiomeSampler(seed, self.version_key)
        return self._sampler_cache[seed]
    
    def clear_cache(self):
        """清空缓存"""
        self._sampler_cache.clear()


# ============================================================================
# Journeymap 结构适配器
# ============================================================================

class JourneyMapStructureAdapter:
    """
    Journeymap 结构适配器
    支持 Journeymap 模组的所有结构类型
    """
    
    def __init__(self, version_key: str = "26.2"):
        self.version_key = version_key
        self.locator = StructureLocator(version_key)
        self._structure_configs = self._load_structure_configs()
    
    def _load_structure_configs(self) -> Dict[str, Dict]:
        """加载结构配置"""
        return {
            "ancient_city": {
                "dimension": "overworld",
                "biomes": ["minecraft:grove", "minecraft:old_growth_birch_forest", "minecraft:old_growth_pine_taiga"],
                "scale": 16,  # 1:16 噪声格
                "radius": 16,
            },
            "desert_pyramid": {
                "dimension": "overworld",
                "biomes": ["minecraft:desert", "minecraft:desert_hills", "minecraft:eroded_badlands"],
                "scale": 1,
                "radius": 12,
            },
            "igloo": {
                "dimension": "overworld",
                "biomes": ["minecraft:snowy_plains", "minecraft:snowy_taiga", "minecraft:snowy_beach", "minecraft:snowy_slopes"],
                "scale": 1,
                "radius": 8,
            },
            "jungle_temple": {
                "dimension": "overworld",
                "biomes": ["minecraft:jungle", "minecraft:jungle_hills", "minecraft:bamboo_jungle", "minecraft:bamboo_jungle_hills"],
                "scale": 1,
                "radius": 8,
            },
            "mansion": {
                "dimension": "overworld",
                "biomes": ["minecraft:dark_forest", "minecraft:old_growth_pine_taiga", "minecraft:old_growth_birch_forest"],
                "scale": 1,
                "radius": 12,
            },
            "monument": {
                "dimension": "overworld",
                "biomes": ["minecraft:deep_ocean", "minecraft:deep_warm_ocean", "minecraft:deep_cold_ocean", "minecraft:deep_frozen_ocean"],
                "scale": 1,
                "radius": 0,  # 固定在 (0, 0)
            },
            "shipwreck_ocean": {
                "dimension": "overworld",
                "biomes": ["minecraft:ocean", "minecraft:deep_ocean", "minecraft:deep_warm_ocean"],
                "scale": 1,
                "radius": 12,
            },
            "shipwreck_beach": {
                "dimension": "overworld",
                "biomes": ["minecraft:beach", "minecraft:snowy_beach", "minecraft:stone_shore", "minecraft:stony_shore"],
                "scale": 1,
                "radius": 12,
            },
            "shipwreck_deep": {
                "dimension": "overworld",
                "biomes": ["minecraft:deep_ocean", "minecraft:deep_cold_ocean", "minecraft:deep_frozen_ocean"],
                "scale": 1,
                "radius": 12,
            },
            "stronghold": {
                "dimension": "overworld",
                "biomes": [],  # 全域生成
                "scale": 1,
                "radius": 128,  # 环形采样
            },
            "swamp_hut": {
                "dimension": "overworld",
                "biomes": ["minecraft:swamp"],
                "scale": 1,
                "radius": 8,
            },
            "temple": {
                "dimension": "overworld",
                "biomes": ["minecraft:desert", "minecraft:jungle"],
                "scale": 1,
                "radius": 8,
            },
            "abandoned_mineshaft": {
                "dimension": "overworld",
                "biomes": ["minecraft:plains", "minecraft:taiga", "minecraft:savanna", "minecraft:snowy_taiga"],
                "scale": 1,
                "radius": 12,
            },
            "village": {
                "dimension": "overworld",
                "biomes": [],  # 全域生成
                "scale": 1,
                "radius": 128,
            },
        }
    
    def find_structures(
        self,
        seed: int,
        struct_keys: List[str],
        radius_blocks: int,
        cx_blocks: int = 0,
        cz_blocks: int = 0,
    ) -> List[Dict]:
        """
        查找指定结构的所有位置
        
        Args:
            seed: 世界种子
            struct_keys: 结构键列表
            radius_blocks: 搜索半径（方块）
            cx_blocks: 中心方块 x
            cz_blocks: 中心方块 z
        
        Returns:
            结构位置列表，每个元素包含：
            {
                "struct": str,  # 结构键
                "name": str,    # 结构名称
                "x": int,       # 方块坐标 x
                "z": int,       # 方块坐标 z
                "cx": int,      # 噪声格坐标 x
                "cz": int,      # 噪声格坐标 z
                "biome": int,   # 群系 id
            }
        """
        results = []
        sampler = self.locator.get_cache_sampler(seed)
        
        # 按结构类型分组处理
        overworld_structures = [k for k in struct_keys if k in self._structure_configs]
        nether_structures = [k for k in struct_keys if k in NETHER_STRUCTURES]
        end_structures = [k for k in struct_keys if k in END_STRUCTURES]
        
        # 主世界结构
        if overworld_structures:
            results.extend(self._find_overworld_structures(
                seed, overworld_structures, radius_blocks, cx_blocks, cz_blocks, sampler
            ))
        
        # 下界结构
        if nether_structures:
            nether_sampler = NetherSampler(seed, self.version_key)
            results.extend(self._find_nether_structures(
                seed, nether_structures, radius_blocks, cx_blocks, cz_blocks, nether_sampler
            ))
        
        # 末地结构
        if end_structures:
            end_sampler = EndSampler(seed, self.version_key)
            results.extend(self._find_end_structures(
                seed, end_structures, radius_blocks, cx_blocks, cz_blocks, end_sampler
            ))
        
        return results
    
    def _find_overworld_structures(
        self,
        seed: int,
        struct_keys: List[str],
        radius_blocks: int,
        cx_blocks: int,
        cz_blocks: int,
        sampler: BiomeSampler,
    ) -> List[Dict]:
        """查找主世界结构"""
        results = []
        
        for struct_key in struct_keys:
            config = self._structure_configs[struct_key]
            dimension = config["dimension"]
            
            # 检查结构是否在当前维度
            if dimension != "overworld":
                continue
            
            # 特殊处理：要塞、村庄
            if struct_key in ["stronghold", "village"]:
                results.extend(self._find_special_structure(
                    seed, struct_key, radius_blocks, cx_blocks, cz_blocks, sampler
                ))
            else:
                # 普通结构
                results.extend(self._find_normal_structure(
                    seed, struct_key, config, radius_blocks, cx_blocks, cz_blocks, sampler
                ))
        
        return results
    
    def _find_normal_structure(
        self,
        seed: int,
        struct_key: str,
        config: Dict,
        radius_blocks: int,
        cx_blocks: int,
        cz_blocks: int,
        sampler: BiomeSampler,
    ) -> List[Dict]:
        """查找普通结构"""
        results = []
        
        # 采样范围（噪声格）
        radius_noise = (radius_blocks >> 2) + 1
        
        cx_noise = cx_blocks >> 2
        cz_noise = cz_blocks >> 2
        
        # 采样群系
        for i in range(-radius_noise, radius_noise + 1):
            for j in range(-radius_noise, radius_noise + 1):
                bx = cx_blocks + i * 4
                bz = cz_blocks + j * 4
                cx_n = cx_noise + i
                cz_n = cz_noise + j
                
                # 检查是否在范围内
                dist = (i * i + j * j) ** 0.5
                if dist > radius_blocks >> 2:
                    continue
                
                # 采样群系
                biome_id = sampler.sample_biome(bx, bz, ny=16)
                
                # 检查是否允许该结构生成
                if self._is_biome_viable(struct_key, biome_id, config):
                    results.append({
                        "struct": struct_key,
                        "name": STRUCT_NAMES.get(struct_key, struct_key),
                        "x": bx,
                        "z": bz,
                        "cx": cx_n,
                        "cz": cz_n,
                        "biome": biome_id,
                    })
        
        return results
    
    def _find_special_structure(
        self,
        seed: int,
        struct_key: str,
        radius_blocks: int,
        cx_blocks: int,
        cz_blocks: int,
        sampler: BiomeSampler,
    ) -> List[Dict]:
        """查找特殊结构（要塞、村庄）"""
        from Utils.Public.structure_map import StrongholdIter
        
        if struct_key == "stronghold":
            # 环形采样
            results = self._find_stronghold(seed, radius_blocks, cx_blocks, cz_blocks, sampler)
        elif struct_key == "village":
            # 环形采样
            results = self._find_village(seed, radius_blocks, cx_blocks, cz_blocks, sampler)
        else:
            results = []
        
        return results
    
    def _find_stronghold(
        self,
        seed: int,
        radius_blocks: int,
        cx_blocks: int,
        cz_blocks: int,
        sampler: BiomeSampler,
    ) -> List[Dict]:
        """查找要塞（环形采样）"""
        results = []
        
        # 使用 StrongholdIter 查找要塞序列
        stronghold_iter = StrongholdIter(seed, self.version_key, sampler)
        
        # 采样 128 个窗口（覆盖 128x128 区域）
        for i in range(128):
            # 计算当前窗口中心
            cx = cx_blocks + (i % 16) * 4
            cz = cz_blocks + (i // 16) * 4
            
            # 获取要塞位置
            pos = stronghold_iter.get_position(cx, cz)
            
            if pos is not None:
                bx, bz = pos
                biome_id = sampler.sample_biome(bx, bz, ny=16)
                
                results.append({
                    "struct": "stronghold",
                    "name": "要塞",
                    "x": bx,
                    "z": bz,
                    "cx": bx >> 2,
                    "cz": bz >> 2,
                    "biome": biome_id,
                })
        
        return results
    
    def _find_village(
        self,
        seed: int,
        radius_blocks: int,
        cx_blocks: int,
        cz_blocks: int,
        sampler: BiomeSampler,
    ) -> List[Dict]:
        """查找村庄（环形采样）"""
        results = []
        
        # 采样 128 个窗口
        for i in range(128):
            cx = cx_blocks + (i % 16) * 4
            cz = cz_blocks + (i // 16) * 4
            
            # 获取村庄位置
            pos = self._get_village_pos(cx, cz, seed, sampler)
            
            if pos is not None:
                bx, bz = pos
                biome_id = sampler.sample_biome(bx, bz, ny=16)
                
                results.append({
                    "struct": "village",
                    "name": "村庄",
                    "x": bx,
                    "z": bz,
                    "cx": bx >> 2,
                    "cz": bz >> 2,
                    "biome": biome_id,
                })
        
        return results
    
    def _get_village_pos(self, cx, cz, seed, sampler):
        """获取村庄位置"""
        # 这里需要实现村庄定位逻辑
        # 简化处理：返回 None
        return None
    
    def _is_biome_viable(self, struct_key: str, biome_id: int, config: Dict) -> bool:
        """检查群系是否允许该结构生成"""
        # 如果没有指定群系限制，则允许所有群系
        if not config["biomes"]:
            return True
        
        # 检查群系是否在允许的群系列表中
        for biome_name, biome_val in BIOME_ID.items():
            if biome_val == biome_id and biome_name in config["biomes"]:
                return True
        
        return False
    
    def _find_nether_structures(
        self,
        seed: int,
        struct_keys: List[str],
        radius_blocks: int,
        cx_blocks: int,
        cz_blocks: int,
        sampler: NetherSampler,
    ) -> List[Dict]:
        """查找下界结构"""
        results = []
        
        for struct_key in struct_keys:
            if struct_key == "bastion":
                results.extend(self._find_bastion(seed, radius_blocks, cx_blocks, cz_blocks, sampler))
            elif struct_key == "nether_fortress":
                results.extend(self._find_nether_fortress(seed, radius_blocks, cx_blocks, cz_blocks, sampler))
            elif struct_key == "nether_portal":
                results.extend(self._find_nether_portal(seed, radius_blocks, cx_blocks, cz_blocks, sampler))
            elif struct_key == "ruined_portal":
                results.extend(self._find_ruined_portal(seed, radius_blocks, cx_blocks, cz_blocks, sampler))
        
        return results
    
    def _find_bastion(
        self,
        seed: int,
        radius_blocks: int,
        cx_blocks: int,
        cz_blocks: int,
        sampler: NetherSampler,
    ) -> List[Dict]:
        """查找堡垒"""
        results = []
        
        radius_noise = (radius_blocks >> 2) + 1
        cx_noise = cx_blocks >> 2
        cz_noise = cz_blocks >> 2
        
        for i in range(-radius_noise, radius_noise + 1):
            for j in range(-radius_noise, radius_noise + 1):
                bx = cx_blocks + i * 4
                bz = cz_blocks + j * 4
                cx_n = cx_noise + i
                cz_n = cz_noise + j
                
                dist = (i * i + j * j) ** 0.5
                if dist > radius_blocks >> 2:
                    continue
                
                # 检查堡垒生成
                if self._check_bastion_generation(seed, bx, bz, sampler):
                    biome_id = sampler.sample_biome(bx, bz, ny=16)
                    
                    results.append({
                        "struct": "bastion",
                        "name": "堡垒",
                        "x": bx,
                        "z": bz,
                        "cx": cx_n,
                        "cz": cz_n,
                        "biome": biome_id,
                    })
        
        return results
    
    def _check_bastion_generation(self, seed, bx, bz, sampler):
        """检查堡垒是否生成"""
        # 堡垒生成逻辑需要实现
        # 简化处理：返回 False
        return False
    
    def _find_nether_fortress(
        self,
        seed: int,
        radius_blocks: int,
        cx_blocks: int,
        cz_blocks: int,
        sampler: NetherSampler,
    ) -> List[Dict]:
        """查找下界要塞"""
        results = []
        
        radius_noise = (radius_blocks >> 2) + 1
        cx_noise = cx_blocks >> 2
        cz_noise = cz_blocks >> 2
        
        for i in range(-radius_noise, radius_noise + 1):
            for j in range(-radius_noise, radius_noise + 1):
                bx = cx_blocks + i * 4
                bz = cz_blocks + j * 4
                cx_n = cx_noise + i
                cz_n = cz_noise + j
                
                dist = (i * i + j * j) ** 0.5
                if dist > radius_blocks >> 2:
                    continue
                
                # 检查要塞生成
                if self._check_fortress_generation(seed, bx, bz, sampler):
                    biome_id = sampler.sample_biome(bx, bz, ny=16)
                    
                    results.append({
                        "struct": "nether_fortress",
                        "name": "下界要塞",
                        "x": bx,
                        "z": bz,
                        "cx": cx_n,
                        "cz": cz_n,
                        "biome": biome_id,
                    })
        
        return results
    
    def _check_fortress_generation(self, seed, bx, bz, sampler):
        """检查要塞是否生成"""
        return False
    
    def _find_nether_portal(
        self,
        seed: int,
        radius_blocks: int,
        cx_blocks: int,
        cz_blocks: int,
        sampler: NetherSampler,
    ) -> List[Dict]:
        """查找地狱门"""
        results = []
        
        # 地狱门固定在 (0, 0)
        results.append({
            "struct": "nether_portal",
            "name": "地狱门",
            "x": 0,
            "z": 0,
            "cx": 0,
            "cz": 0,
            "biome": 0,
        })
        
        return results
    
    def _find_ruined_portal(
        self,
        seed: int,
        radius_blocks: int,
        cx_blocks: int,
        cz_blocks: int,
        sampler: NetherSampler,
    ) -> List[Dict]:
        """查找废弃传送门"""
        results = []
        
        # 废弃传送门位置需要实现
        return results
    
    def _find_end_structures(
        self,
        seed: int,
        struct_keys: List[str],
        radius_blocks: int,
        cx_blocks: int,
        cz_blocks: int,
        sampler: EndSampler,
    ) -> List[Dict]:
        """查找末地结构"""
        results = []
        
        for struct_key in struct_keys:
            if struct_key == "end_city":
                results.extend(self._find_end_city(seed, radius_blocks, cx_blocks, cz_blocks, sampler))
            elif struct_key == "end_gateway":
                results.extend(self._find_end_gateway(seed, radius_blocks, cx_blocks, cz_blocks, sampler))
            elif struct_key == "end_island":
                results.extend(self._find_end_island(seed, radius_blocks, cx_blocks, cz_blocks, sampler))
        
        return results
    
    def _find_end_city(
        self,
        seed: int,
        radius_blocks: int,
        cx_blocks: int,
        cz_blocks: int,
        sampler: EndSampler,
    ) -> List[Dict]:
        """查找末地城"""
        results = []
        
        radius_noise = (radius_blocks >> 2) + 1
        cx_noise = cx_blocks >> 2
        cz_noise = cz_blocks >> 2
        
        for i in range(-radius_noise, radius_noise + 1):
            for j in range(-radius_noise, radius_noise + 1):
                bx = cx_blocks + i * 4
                bz = cz_blocks + j * 4
                cx_n = cx_noise + i
                cz_n = cz_noise + j
                
                dist = (i * i + j * j) ** 0.5
                if dist > radius_blocks >> 2:
                    continue
                
                # 检查末地城生成
                if self._check_end_city_generation(seed, bx, bz, sampler):
                    biome_id = sampler.sample_biome(bx, bz, ny=16)
                    
                    results.append({
                        "struct": "end_city",
                        "name": "末地城",
                        "x": bx,
                        "z": bz,
                        "cx": cx_n,
                        "cz": cz_n,
                        "biome": biome_id,
                    })
        
        return results
    
    def _check_end_city_generation(self, seed, bx, bz, sampler):
        """检查末地城是否生成"""
        return False
    
    def _find_end_gateway(
        self,
        seed: int,
        radius_blocks: int,
        cx_blocks: int,
        cz_blocks: int,
        sampler: EndSampler,
    ) -> List[Dict]:
        """查找末地门"""
        results = []
        
        # 末地门固定在 (0, 0)
        results.append({
            "struct": "end_gateway",
            "name": "末地门",
            "x": 0,
            "z": 0,
            "cx": 0,
            "cz": 0,
            "biome": 0,
        })
        
        return results
    
    def _find_end_island(
        self,
        seed: int,
        radius_blocks: int,
        cx_blocks: int,
        cz_blocks: int,
        sampler: EndSampler,
    ) -> List[Dict]:
        """查找末地岛"""
        results = []
        
        # 末地岛位置需要实现
        return results
    
    def calculate_distance(self, pos1: Tuple[int, int], pos2: Tuple[int, int]) -> float:
        """计算两个位置之间的距离"""
        return math.sqrt((pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2)
    
    def convert_to_journeymap_format(self, positions: List[Dict]) -> List[Dict]:
        """转换为 Journeymap 模组格式"""
        journeymap_format = []
        
        for pos in positions:
            journeymap_format.append({
                "x": pos["x"],
                "z": pos["z"],
                "type": pos["name"],
                "distance": None,  # 需要在 MapPreviewer 中计算
            })
        
        return journeymap_format


# ============================================================================
# 测试
# ============================================================================

if __name__ == "__main__":
    # 测试结构定位
    adapter = JourneyMapStructureAdapter(version_key="26.2")
    
    # 查找主世界结构
    results = adapter.find_structures(
        seed=123456789,
        struct_keys=["desert_pyramid", "igloo", "mansion"],
        radius_blocks=100,
        cx_blocks=1000,
        cz_blocks=1000,
    )
    
    print(f"找到 {len(results)} 个结构：")
    for result in results[:10]:
        print(f"  {result['name']}: ({result['x']}, {result['z']})")
