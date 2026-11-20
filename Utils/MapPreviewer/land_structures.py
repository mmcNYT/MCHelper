# -*- coding: utf-8 -*-
"""
陆地结构渲染器
支持在群系地图上叠加显示各种陆地结构

支持的结构类型：
- 村庄 (village)
- 神庙 (temple)
- 废墟 (ruins)
- 废弃矿井 (abandoned_mineshaft)
- 林地府邸 (mansion)
- 沙漠神殿 (desert_pyramid)

使用方法：
    renderer = LandStructureRenderer()
    rgb, height_map = renderer.render_landscape(rgb_matrix, seed, radius)
"""

from __future__ import annotations

import numpy as np
from typing import Dict, List, Tuple

from Utils.MapPreviewer.block_colors import CELL, render_block_rgb
from Utils.SeedReverser.biome_noise import BiomeSampler


# ============================================================================
# 结构配置
# ============================================================================

STRUCTURE_CONFIGS = {
    "village": {
        "name": "村庄",
        "density": 0.3,
        "size": (16, 16),
        "biomes": ["minecraft:savanna", "minecraft:plains", "minecraft:taiga", "minecraft:snowy_plains", "minecraft:snowy_taiga"],
        "color": np.array([180, 160, 120], dtype=np.float32),  # 土黄色
        "height": 32,
        "texture": "grass",
    },
    "desert_pyramid": {
        "name": "沙漠神殿",
        "density": 0.15,
        "size": (8, 8),
        "biomes": ["minecraft:desert", "minecraft:desert_hills", "minecraft:eroded_badlands"],
        "color": np.array([200, 180, 100], dtype=np.float32),  # 金黄色
        "height": 48,
        "texture": "sand",
    },
    "jungle_temple": {
        "name": "丛林神庙",
        "density": 0.1,
        "size": (8, 8),
        "biomes": ["minecraft:jungle", "minecraft:jungle_hills", "minecraft:bamboo_jungle", "minecraft:bamboo_jungle_hills"],
        "color": np.array([80, 120, 60], dtype=np.float32),  # 深绿色
        "height": 40,
        "texture": "grass",
    },
    "mansion": {
        "name": "林地府邸",
        "density": 0.05,
        "size": (8, 8),
        "biomes": ["minecraft:dark_forest", "minecraft:old_growth_pine_taiga", "minecraft:old_growth_birch_forest", "minecraft:grove"],
        "color": np.array([100, 110, 100], dtype=np.float32),  # 深绿色
        "height": 56,
        "texture": "grass",
    },
    "temple": {
        "name": "废弃神殿",
        "density": 0.08,
        "size": (6, 6),
        "biomes": ["minecraft:desert", "minecraft:jungle"],
        "color": np.array([180, 160, 120], dtype=np.float32),  # 土黄色
        "height": 40,
        "texture": "stone",
    },
    "ruins": {
        "name": "废墟",
        "density": 0.12,
        "size": (6, 6),
        "biomes": ["minecraft:snowy_plains", "minecraft:snowy_taiga", "minecraft:taiga", "minecraft:plains"],
        "color": np.array([160, 150, 140], dtype=np.float32),  # 灰色
        "height": 36,
        "texture": "stone",
    },
    "abandoned_mineshaft": {
        "name": "废弃矿井",
        "density": 0.06,
        "size": (6, 6),
        "biomes": ["minecraft:plains", "minecraft:taiga", "minecraft:savanna", "minecraft:snowy_taiga", "minecraft:snowy_beach"],
        "color": np.array([140, 130, 120], dtype=np.float32),  # 灰色
        "height": 48,
        "texture": "stone",
    },
    "igloo": {
        "name": "冰屋",
        "density": 0.08,
        "size": (4, 4),
        "biomes": ["minecraft:snowy_plains", "minecraft:snowy_taiga", "minecraft:snowy_beach", "minecraft:snowy_slopes"],
        "color": np.array([220, 230, 240], dtype=np.float32),  # 白色
        "height": 16,
        "texture": "ice",
    },
}


# ============================================================================
# 陆地结构渲染器
# ============================================================================

class LandStructureRenderer:
    """
    陆地结构渲染器
    在群系地图上叠加显示各种陆地结构
    """
    
    def __init__(self):
        self._structure_configs = STRUCTURE_CONFIGS
        self._biome_id_map = self._load_biome_id_map()
    
    def _load_biome_id_map(self) -> Dict[str, int]:
        """加载群系 ID 映射"""
        return {
            "minecraft:plains": 1,
            "minecraft:savanna": 35,
            "minecraft:desert": 2,
            "minecraft:jungle": 21,
            "minecraft:snowy_plains": 12,
            "minecraft:snowy_taiga": 30,
            "minecraft:taiga": 5,
            "minecraft:swamp": 6,
            "minecraft:dark_forest": 29,
            "minecraft:old_growth_pine_taiga": 32,
            "minecraft:old_growth_birch_forest": 155,
            "minecraft:grove": 178,
            "minecraft:cherry_grove": 185,
            "minecraft:snowy_slopes": 179,
            "minecraft:jagged_peaks": 180,
            "minecraft:frozen_peaks": 181,
            "minecraft:stony_peaks": 182,
            "minecraft:deep_dark": 183,
            "minecraft:bamboo_jungle": 168,
            "minecraft:bamboo_jungle_hills": 169,
            "minecraft:mangrove_swamp": 184,
            "minecraft:meadow": 177,
            "minecraft:eroded_badlands": 170,
        }
    
    def render_landscape(
        self,
        rgb_matrix: np.ndarray,
        seed: int,
        radius_blocks: int,
        cx_blocks: int = 0,
        cz_blocks: int = 0,
        ny: int = 16,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        在群系地图上叠加陆地结构
        
        Args:
            rgb_matrix: 原始群系 RGB 矩阵 (H, W, 3)
            seed: 世界种子
            radius_blocks: 渲染半径（方块）
            cx_blocks: 中心方块 x
            cz_blocks: 中心方块 z
            ny: 采样层（噪声格 y）
        
        Returns:
            (rgb_matrix, height_map)
                rgb_matrix: 渲染后的 RGB 矩阵
                height_map: 高度图（用于地形阴影）
        """
        # 创建采样器
        sampler = BiomeSampler(seed, "26.2")
        
        # 获取渲染区域
        nh, nw = rgb_matrix.shape[:2]
        cx_n = cx_blocks >> 2
        cz_n = cz_blocks >> 2
        radius_noise = (radius_blocks >> 2) + 1
        
        # 创建高度图
        height_map = np.zeros((nh, nw), dtype=np.uint8)
        
        # 创建结构位置缓存
        structure_positions = self._get_structure_positions(
            seed, radius_blocks, cx_blocks, cz_blocks, ny, sampler
        )
        
        # 应用结构效果
        for struct_key, positions in structure_positions.items():
            config = self._structure_configs[struct_key]
            self._apply_structure(rgb_matrix, positions, config, height_map)
        
        return rgb_matrix, height_map
    
    def _get_structure_positions(
        self,
        seed: int,
        radius_blocks: int,
        cx_blocks: int,
        cz_blocks: int,
        ny: int,
        sampler: BiomeSampler,
    ) -> Dict[str, List[Tuple[int, int]]]:
        """获取结构位置"""
        structure_positions = {}
        
        for struct_key, config in self._structure_configs.items():
            positions = []
            
            # 检查是否在允许的群系内
            if not config["biomes"]:
                # 全域生成
                radius_noise = (radius_blocks >> 2) + 1
                cx_n = cx_blocks >> 2
                cz_n = cz_blocks >> 2
                
                for i in range(-radius_noise, radius_noise + 1):
                    for j in range(-radius_noise, radius_noise + 1):
                        bx = cx_blocks + i * 4
                        bz = cz_blocks + j * 4
                        
                        # 计算距离
                        dist = math.sqrt(i * i + j * j)
                        if dist > radius_blocks >> 2:
                            continue
                        
                        # 采样群系
                        biome_id = sampler.sample_biome(bx, bz, ny)
                        
                        # 检查是否允许该结构生成
                        if self._is_biome_viable(struct_key, biome_id, config):
                            # 根据密度决定是否生成
                            if np.random.random() < config["density"]:
                                positions.append((bx, bz))
            else:
                # 指定群系生成
                radius_noise = (radius_blocks >> 2) + 1
                cx_n = cx_blocks >> 2
                cz_n = cz_blocks >> 2
                
                for i in range(-radius_noise, radius_noise + 1):
                    for j in range(-radius_noise, radius_noise + 1):
                        bx = cx_blocks + i * 4
                        bz = cz_blocks + j * 4
                        
                        # 计算距离
                        dist = math.sqrt(i * i + j * j)
                        if dist > radius_blocks >> 2:
                            continue
                        
                        # 采样群系
                        biome_id = sampler.sample_biome(bx, bz, ny)
                        
                        # 检查是否在允许的群系内
                        if self._is_biome_viable(struct_key, biome_id, config):
                            # 根据密度决定是否生成
                            if np.random.random() < config["density"]:
                                positions.append((bx, bz))
            
            structure_positions[struct_key] = positions
        
        return structure_positions
    
    def _is_biome_viable(self, struct_key: str, biome_id: int, config: Dict) -> bool:
        """检查群系是否允许该结构生成"""
        # 如果没有指定群系限制，则允许所有群系
        if not config["biomes"]:
            return True
        
        # 检查群系是否在允许的群系列表中
        for biome_name, biome_val in self._biome_id_map.items():
            if biome_val == biome_id and biome_name in config["biomes"]:
                return True
        
        return False
    
    def _apply_structure(
        self,
        rgb_matrix: np.ndarray,
        positions: List[Tuple[int, int]],
        config: Dict,
        height_map: np.ndarray,
    ) -> None:
        """应用结构效果"""
        for bx, bz in positions:
            # 计算像素坐标
            cx_n = (bx >> 2) - (rgb_matrix.shape[1] // 2)
            cz_n = (bz >> 2) - (rgb_matrix.shape[0] // 2)
            
            # 检查是否在有效范围内
            if 0 <= cx_n < rgb_matrix.shape[1] and 0 <= cz_n < rgb_matrix.shape[0]:
                # 更新高度图
                height_map[cz_n, cx_n] = config["height"]
                
                # 更新颜色
                color = config["color"].copy()
                
                # 根据群系调整颜色
                if config["texture"] == "grass":
                    color = self._adjust_grass_color(color, bx, bz)
                elif config["texture"] == "sand":
                    color = self._adjust_sand_color(color, bx, bz)
                elif config["texture"] == "stone":
                    color = self._adjust_stone_color(color, bx, bz)
                elif config["texture"] == "ice":
                    color = self._adjust_ice_color(color, bx, bz)
                
                # 应用颜色
                rgb_matrix[cz_n, cx_n] = color.astype(np.uint8)
        
        # 应用结构周围的影响
        self._apply_structure_surroundings(rgb_matrix, positions, config)
    
    def _adjust_grass_color(self, base_color: np.ndarray, bx: int, bz: int) -> np.ndarray:
        """调整草地颜色"""
        # 根据温度湿度调整草色
        # 这里简化处理，返回基础颜色
        return base_color
    
    def _adjust_sand_color(self, base_color: np.ndarray, bx: int, bz: int) -> np.ndarray:
        """调整沙地颜色"""
        # 根据深度调整沙色
        # 这里简化处理，返回基础颜色
        return base_color
    
    def _adjust_stone_color(self, base_color: np.ndarray, bx: int, bz: int) -> np.ndarray:
        """调整石地颜色"""
        # 根据深度调整石色
        # 这里简化处理，返回基础颜色
        return base_color
    
    def _adjust_ice_color(self, base_color: np.ndarray, bx: int, bz: int) -> np.ndarray:
        """调整冰地颜色"""
        # 根据深度调整冰色
        # 这里简化处理，返回基础颜色
        return base_color
    
    def _apply_structure_surroundings(
        self,
        rgb_matrix: np.ndarray,
        positions: List[Tuple[int, int]],
        config: Dict,
    ) -> None:
        """应用结构周围的影响"""
        # 结构周围的方块变化
        # 例如：村庄周围的草地、神庙周围的沙地
        pass


# ============================================================================
# 测试
# ============================================================================

if __name__ == "__main__":
    import numpy as np
    
    # 测试渲染
    renderer = LandStructureRenderer()
    
    # 创建测试 RGB 矩阵
    test_rgb = np.zeros((64, 64, 3), dtype=np.uint8)
    
    # 渲染
    result_rgb, height_map = renderer.render_landscape(
        test_rgb,
        seed=123456789,
        radius_blocks=32,
        cx_blocks=100,
        cz_blocks=100,
        ny=16,
    )
    
    print(f"渲染完成：{result_rgb.shape}")
    print(f"高度图：{height_map.shape}")
    print(f"最大高度：{height_map.max()}")
