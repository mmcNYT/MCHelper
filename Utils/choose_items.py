from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QAbstractItemView, QMessageBox
)
from PySide6.QtCore import Qt, QEvent
from CodesUI.ChooseEnchantedItems import Ui_enchantedItems
from Utils.enchant_data_manager import DataManager

class ChooseItemsWindow(QDialog, Ui_enchantedItems):
    """
    物品选择窗口：显示可用物品列表，支持多选。
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        self.data_manager = DataManager()
        # 1. 加载 UI（包含所有 Designer 控件）
        self.setupUi(self)

        # 2. 配置上方物品栏（chosenEnchantmentList）
        self.chosenEnchantmentList.setAcceptDrops(True)
        self.chosenEnchantmentList.setDropIndicatorShown(True)
        self.chosenEnchantmentList.setDragEnabled(False)
        self.chosenEnchantmentList.setSelectionMode(QAbstractItemView.SingleSelection)
        self.chosenEnchantmentList.setDefaultDropAction(Qt.CopyAction)
        self.chosenEnchantmentList.dropped.connect(self.on_enchant_dropped)

        # 重写其拖放事件（绑定到当前类的自定义处理方法）
        # self.chosenEnchantmentList.dragEnterEvent = self.drag_enter_event
        # self.chosenEnchantmentList.dropEvent = self.drop_event

        # 3. 加载附魔数据到下方的分类列表
        self.load_enchant_data()

    def load_enchant_data(self):
        """
        将附魔数据填充到下方的各个分类列表中。
        假设在 Designer 中这些列表的 objectName 分别为：
            list_melee, list_ranged, list_armor, list_common, list_curse
        并且它们已经被提升为 EnchantListWidget（自定义子类）。
        """
        # 建立分类与对应列表控件的映射
        category_to_list = {
            "近战武器": self.meleeEnchantmentList,
            "远程武器": self.rangedEnchantmentList,
            "防具": self.armorEnchantmentList,
            "通用附魔": self.commonEnchantmentList,
            "诅咒": self.curseEnchantmentList
        }

        all_enchants = self.data_manager.get_all_enchants()

        for category, list_widget in category_to_list.items():
            list_widget.clear()
            for ench in all_enchants:
                if ench.get("category") == category:
                    # 创建列表项，并存储附魔数据到 UserRole 中
                    item = QListWidgetItem(f"{ench['name']} (等级 1)")
                    item.setData(Qt.UserRole, ench['id'])  # 附魔ID
                    item.setData(Qt.UserRole + 1, 1)  # 当前等级
                    item.setData(Qt.UserRole + 2, ench['max_level'])  # 最大等级
                    list_widget.addItem(item)

    # ---------- 拖放事件处理（拖拽到上方物品栏） ----------
    def on_enchant_dropped(self, enchant_id: str, level: int):
        """
        处理拖入的附魔数据（由 DropListWidget 的信号触发）
        """
        # 查找附魔信息
        ench = self.data_manager.get_enchant_by_id(enchant_id)
        if not ench:
            return

        name = ench["name"]
        max_level = ench["max_level"]
        level = min(level, max_level)  # 防止等级溢出

        # 检查物品栏是否已有该附魔
        existing_item = None
        for i in range(self.chosenEnchantmentList.count()):
            item = self.chosenEnchantmentList.item(i)
            if item.data(Qt.UserRole) == enchant_id:
                existing_item = item
                break

        if existing_item:
            # 取较高等级
            current_level = existing_item.data(Qt.UserRole + 1) or 1
            new_level = max(current_level, level)
            existing_item.setData(Qt.UserRole + 1, new_level)
            existing_item.setText(f"{name} (等级 {new_level})")
        else:
            # 新增
            item = QListWidgetItem(f"{name} (等级 {level})")
            item.setData(Qt.UserRole, enchant_id)
            item.setData(Qt.UserRole + 1, level)
            self.chosenEnchantmentList.addItem(item)