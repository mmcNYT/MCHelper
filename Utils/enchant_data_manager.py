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

    def get_level_cost(self, enchant_id: str, level: int, is_from_book:bool) -> Optional[int]:
        """
        获取某附魔指定等级所需的经验消耗。
        :param is_from_book: 附魔是否在附魔书上
        :param enchant_id: 附魔 ID
        :param level: 附魔等级（1-based）
        :return: 消耗的经验值，若不存在则返回 None
        """
        ench = self.get_enchant_by_id(enchant_id)
        if not ench:
            return None
        if is_from_book:
            costs = ench.get("level_cost_from_book", [])
        else:
            costs = ench.get("level_cost_from_items", [])
        if 0 < level <= len(costs):
            return costs[level - 1]
        return None

    def get_max_level(self, enchant_id: str) -> Optional[int]:
        """获取某附魔的最大等级"""
        ench = self.get_enchant_by_id(enchant_id)
        return ench.get("max_level") if ench else None