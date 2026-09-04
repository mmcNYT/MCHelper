import json
import os
from typing import List, Dict, Optional, Any

class DataManager:
    """
    数据管理器（单例），负责加载和访问附魔数据。
    数据存储在 data/enchants.json 文件中。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.data = {"enchants": []}
        self.load_data()

    # ---------- 文件路径 ----------
    def _get_data_path(self) -> str:
        """获取数据文件的绝对路径（位于项目根目录下的 data 文件夹）"""
        # 当前文件在 utils/data_manager.py，向上两级到项目根目录
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(base_dir, "data")
        os.makedirs(data_dir, exist_ok=True)   # 如果 data 目录不存在则创建
        return os.path.join(data_dir, "enchants.json")

    # ---------- 加载与保存 ----------
    def load_data(self):
        """从 JSON 文件加载数据，若文件不存在则创建空数据"""
        file_path = self._get_data_path()
        if not os.path.exists(file_path):
            # 创建默认数据文件（包含示例数据）
            self._create_default_data(file_path)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"加载数据失败: {e}，使用空数据")
            self.data = {"enchants": []}

    def save_data(self):
        """将当前数据保存到 JSON 文件"""
        file_path = self._get_data_path()
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"保存数据失败: {e}")

    def _create_default_data(self, file_path: str):
        """创建默认的附魔数据文件"""
        default_data = {
            "enchants": [
                {
                    "id": "sharpness",
                    "name": "锋利",
                    "max_level": 5,
                    "level_cost": [1, 2, 4, 8, 16],
                    "applicable": ["剑", "斧"],
                    "category": "近战武器",
                    "description": "增加近战伤害"
                },
                {
                    "id": "power",
                    "name": "力量",
                    "max_level": 5,
                    "level_cost": [1, 2, 4, 8, 16],
                    "applicable": ["弓"],
                    "category": "远程武器",
                    "description": "增加弓箭伤害"
                },
                {
                    "id": "protection",
                    "name": "保护",
                    "max_level": 4,
                    "level_cost": [1, 2, 4, 8],
                    "applicable": ["头盔", "胸甲", "护腿", "靴子"],
                    "category": "防具",
                    "description": "减少受到的伤害"
                },
                {
                    "id": "unbreaking",
                    "name": "耐久",
                    "max_level": 3,
                    "level_cost": [1, 2, 4],
                    "applicable": ["剑", "斧", "镐", "锄", "铲", "弓", "盔甲"],
                    "category": "通用附魔",
                    "description": "增加物品耐久度"
                },
                {
                    "id": "binding_curse",
                    "name": "绑定诅咒",
                    "max_level": 1,
                    "level_cost": [1],
                    "applicable": ["头盔", "胸甲", "护腿", "靴子", "鞘翅"],
                    "category": "诅咒",
                    "description": "物品无法被丢弃"
                }
            ]
        }
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, ensure_ascii=False, indent=2)

    # ---------- 查询接口 ----------
    def get_all_enchants(self) -> List[Dict[str, Any]]:
        """返回所有附魔的列表"""
        return self.data.get("enchants", [])

    def get_enchant_by_id(self, enchant_id: str) -> Optional[Dict[str, Any]]:
        """根据附魔 ID 查找附魔对象"""
        for ench in self.data.get("enchants", []):
            if ench.get("id") == enchant_id:
                return ench
        return None

    def get_enchants_by_category(self, category: str) -> List[Dict[str, Any]]:
        """根据类别返回附魔列表"""
        result = []
        for ench in self.data.get("enchants", []):
            if ench.get("category") == category:
                result.append(ench)
        return result

    def get_enchants_for_item(self, item_type: str) -> List[Dict[str, Any]]:
        """返回适用于某种物品类型的所有附魔"""
        result = []
        for ench in self.data.get("enchants", []):
            if item_type in ench.get("applicable", []):
                result.append(ench)
        return result

    def get_level_cost(self, enchant_id: str, level: int) -> Optional[int]:
        """
        获取某附魔指定等级所需的经验消耗。
        :param enchant_id: 附魔 ID
        :param level: 附魔等级（1-based）
        :return: 消耗的经验值，若不存在则返回 None
        """
        ench = self.get_enchant_by_id(enchant_id)
        if not ench:
            return None
        costs = ench.get("level_cost", [])
        if 0 < level <= len(costs):
            return costs[level - 1]
        return None

    def get_max_level(self, enchant_id: str) -> Optional[int]:
        """获取某附魔的最大等级"""
        ench = self.get_enchant_by_id(enchant_id)
        return ench.get("max_level") if ench else None

    # ---------- 数据操作（扩展） ----------
    def add_enchant(self, enchant_data: Dict[str, Any]) -> bool:
        """
        添加新的附魔数据。
        :param enchant_data: 必须包含 id, name, max_level, level_cost, applicable, category
        :return: 是否添加成功
        """
        if not enchant_data.get("id"):
            return False
        # 检查是否已存在
        if self.get_enchant_by_id(enchant_data["id"]):
            return False
        self.data["enchants"].append(enchant_data)
        self.save_data()
        return True

    def update_enchant(self, enchant_id: str, new_data: Dict[str, Any]) -> bool:
        """更新某附魔的信息（ID 不可变）"""
        for i, ench in enumerate(self.data["enchants"]):
            if ench.get("id") == enchant_id:
                # 保留原 ID，更新其他字段
                new_data["id"] = enchant_id
                self.data["enchants"][i] = new_data
                self.save_data()
                return True
        return False

    def delete_enchant(self, enchant_id: str) -> bool:
        """删除某附魔"""
        for i, ench in enumerate(self.data["enchants"]):
            if ench.get("id") == enchant_id:
                del self.data["enchants"][i]
                self.save_data()
                return True
        return False