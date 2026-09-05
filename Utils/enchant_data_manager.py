# utils/enchant_data_manager.py
# 附魔数据管理器：单例模式加载 data/enchants.json，为附魔计算器提供查询接口
import json
import os
from typing import List, Dict, Optional, Any

class DataManager:
    """
    数据管理器（单例），负责加载和访问附魔数据。
    数据存储在 data/enchants.json 文件中。

    数据结构（enchants.json）：
    {
        "enchants": [
            {
                "id": "aqua_affinity",              # 附魔 ID（英文标识，如 "水下速掘" 的 ID）
                "name": "水下速掘",                  # 附魔中文名
                "max_level": 1,                      # 最大附魔等级
                "level_cost_from_items": [4],        # 各等级经验消耗（物品上的附魔合并时）
                "level_cost_from_book": [2],         # 各等级经验消耗（从附魔书合并时）
                "applicable": ["头盔", "海龟壳"],     # 适用的物品类型列表
                "category": "防具",                   # 所属类别（近战武器/工具/远程武器/防具/通用附魔/诅咒）
                "conflicts": ["protection"],          # 互斥附魔 ID 列表（不能同时存在于同一物品）
                "description": "防止水下挖掘速度惩罚"  # 附魔效果说明
            },
            ...
        ]
    }
    """
    _instance = None  # 单例实例（类属性，所有 DataManager() 调用共享同一实例）

    def __new__(cls):
        """重写 __new__ 实现单例模式：首次调用创建实例，之后返回同一实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # 标记实例是否已完成初始化
        return cls._instance

    def __init__(self):
        """初始化数据管理器（仅首次创建时执行，重复调用直接返回）"""
        # 单例已初始化过则跳过，防止每次 DataManager() 都重新读文件
        if self._initialized:
            return
        self._initialized = True
        self.data = {"enchants": []}  # 内存中的完整附魔数据
        self.load_data()              # 首次初始化时立即从磁盘加载数据

    # ---------- 文件路径 ----------
    def _get_data_path(self) -> str:
        """获取数据文件的绝对路径（位于项目根目录下的 data 文件夹）

        返回：
            data/enchants.json 的绝对路径

        功能说明：
        - 当前文件位于 Utils/ 目录，向上两级（dirname 两次）回到项目根目录
        - 自动创建 data 目录（若不存在）
        """
        # 当前文件在 utils/data_manager.py，向上两级到项目根目录
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(base_dir, "data")
        os.makedirs(data_dir, exist_ok=True)   # 如果 data 目录不存在则创建
        return os.path.join(data_dir, "enchants.json")

    # ---------- 加载与保存 ----------
    def load_data(self):
        """从 JSON 文件加载数据，若文件不存在则创建空数据

        功能说明：
        - 获取数据文件路径，若文件不存在则先创建默认数据文件
        - 以只读方式打开并解析 JSON 内容到 self.data
        - 解析失败（JSON 格式错误或 IO 异常）时回退为空数据，保证程序不崩溃
        """
        file_path = self._get_data_path()
        if not os.path.exists(file_path):
            # 创建默认数据文件（包含示例数据）
            self._create_default_data(file_path)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            # JSON 格式损坏或读取失败：打印原因并使用空数据兜底
            print(f"加载数据失败: {e}，使用空数据")
            self.data = {"enchants": []}

    def save_data(self):
        """将当前数据保存到 JSON 文件

        功能说明：
        - 以写入模式 ('w') 打开数据文件并保存 self.data
        - ensure_ascii=False 确保中文名称正常显示
        - indent=2 美化输出格式（便于阅读和调试）
        - 捕获 IO 异常并输出错误信息，不中断程序
        """
        file_path = self._get_data_path()
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"保存数据失败: {e}")

    # ---------- 查询接口 ----------
    def get_all_enchants(self) -> List[Dict[str, Any]]:
        """返回所有附魔的列表（用于初始化分类列表时遍历筛选）"""
        return self.data.get("enchants", [])

    def get_enchant_by_id(self, enchant_id: str) -> Optional[Dict[str, Any]]:
        """根据附魔 ID 查找附魔对象

        参数：
            enchant_id: 附魔 ID（如 "aqua_affinity"）

        返回：
            匹配的附魔字典；未找到返回 None
        """
        for ench in self.data.get("enchants", []):
            if ench.get("id") == enchant_id:
                return ench
        return None

    def get_enchants_by_category(self, category: str) -> List[Dict[str, Any]]:
        """根据类别返回附魔列表

        参数：
            category: 类别名（"近战武器"/"工具"/"远程武器"/"防具"/"通用附魔"/"诅咒"）

        返回：
            该类别下所有附魔的列表；无匹配则返回空列表
        """
        result = []
        for ench in self.data.get("enchants", []):
            if ench.get("category") == category:
                result.append(ench)
        return result

    def get_enchants_for_item(self, item_type: str) -> List[Dict[str, Any]]:
        """返回适用于某种物品类型的所有附魔

        参数：
            item_type: 物品类型名（如 "剑"、"头盔"，须与 applicable 列表中的写法一致）

        返回：
            applicable 包含该物品类型的所有附魔列表
        """
        result = []
        for ench in self.data.get("enchants", []):
            if item_type in ench.get("applicable", []):
                result.append(ench)
        return result

    def get_level_cost(self, enchant_id: str, level: int, is_from_book:bool) -> Optional[int]:
        """获取某附魔指定等级所需的经验消耗

        功能说明：
        - 根据附魔是否来自附魔书，选择不同的经验消耗表
          （同一附魔同一等级，附魔书合并与物品直接合并的经验消耗不同）
        - 等级为 1-based，直接索引消耗表中对应位置

        参数：
            is_from_book: 附魔是否在附魔书上（True 用 level_cost_from_book，False 用 level_cost_from_items）
            enchant_id: 附魔 ID
            level: 附魔等级（1-based）

        返回：
            消耗的经验值，若附魔不存在或等级越界则返回 None
        """
        ench = self.get_enchant_by_id(enchant_id)
        if not ench:
            return None
        if is_from_book:
            costs = ench.get("level_cost_from_book", [])   # 附魔书经验消耗表
        else:
            costs = ench.get("level_cost_from_items", [])  # 物品附魔经验消耗表
        if 0 < level <= len(costs):
            return costs[level - 1]  # 等级转索引（1 级对应下标 0）
        return None

    def get_max_level(self, enchant_id: str) -> Optional[int]:
        """获取某附魔的最大等级

        参数：
            enchant_id: 附魔 ID

        返回：
            最大等级数值；附魔不存在返回 None
        """
        ench = self.get_enchant_by_id(enchant_id)
        return ench.get("max_level") if ench else None

    def get_conflicts(self, enchant_id: str) -> List[str]:
        """获取与某附魔互斥（不共存）的附魔 ID 列表

        参数：
            enchant_id: 附魔 ID

        返回：
            互斥附魔 ID 列表；附魔不存在或无冲突数据时返回空列表
        """
        ench = self.get_enchant_by_id(enchant_id)
        if not ench:
            return []
        return list(ench.get("conflicts", []))
