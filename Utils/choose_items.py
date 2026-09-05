from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QAbstractItemView, QMessageBox, QTabWidget
)
from PySide6.QtCore import Qt, QEvent
from CodesUI.ChooseEnchantedItems import Ui_enchantedItems
from Utils.enchant_data_manager import DataManager
from Utils.enchant_list_widget import EnchantListWidget

class ChooseItemsWindow(QDialog, Ui_enchantedItems):
    """
    物品选择窗口：显示可用物品列表，支持多选。
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        self.data_manager = DataManager()
        # 1. 加载 UI（包含所有 Designer 控件）
        self.setupUi(self)

        # 2. 配置chosenEnchantmentList
        self.chosenEnchantmentList.setAcceptDrops(True)
        self.chosenEnchantmentList.setDropIndicatorShown(True)
        self.chosenEnchantmentList.setDragEnabled(True)
        self.chosenEnchantmentList.setSelectionMode(QAbstractItemView.SingleSelection)
        self.chosenEnchantmentList.setDefaultDropAction(Qt.CopyAction)
        self.chosenEnchantmentList.dropped.connect(self.on_enchant_dropped)

        # 3. 加载附魔数据到下方的分类列表
        self.load_enchant_data()

        # 4.绑定信号与槽
        self.itemsList.currentIndexChanged.connect(self.on_item_type_changed)

        # 5.定义变量
        self.current_stuff = "附魔书"
        self.enchant_levels = {}


    def load_enchant_data(self):
        """加载附魔数据，创建各分类的列表控件并添加到 tab"""
        all_enchants = self.data_manager.get_all_enchants()
        # 按分类分组
        categories = {}
        for ench in all_enchants:
            cat = ench.get("category", "其他")
            categories.setdefault(cat, []).append(ench)

        # 清空原有 tab 和记录
        self.allEnchantmentTab.clear()
        self.category_order = []
        self.category_widgets = {}

        # 按原数据顺序创建 tab（保持 categories 的插入顺序）
        for cat_name, ench_list in categories.items():
            list_widget = EnchantListWidget()
            for ench in ench_list:
                item = QListWidgetItem(f"{ench['name']} (等级 1)")
                item.setData(Qt.UserRole, ench['id'])
                item.setData(Qt.UserRole + 1, 1)           # 当前等级
                item.setData(Qt.UserRole + 2, ench['max_level'])  # 最大等级
                list_widget.addItem(item)
            self.allEnchantmentTab.addTab(list_widget, cat_name)
            self.category_order.append(cat_name)
            self.category_widgets[cat_name] = list_widget

    def update_tabs_for_item(self, item_type):
        """
        根据物品类型，决定显示哪些分类的 tab。
        如果 item_type 为空，则显示所有分类。
        """
        if not item_type:
            compatible_categories = set(self.category_order)
        else:
            # 获取该物品适用的所有附魔
            compatible_enchants = self.data_manager.get_enchants_for_item(item_type)
            # 提取分类
            compatible_categories = {ench['category'] for ench in compatible_enchants}

        # 保存当前选中的分类名称（用于恢复）
        current_index = self.allEnchantmentTab.currentIndex()
        current_cat = None
        if current_index >= 0:
            current_cat = self.allEnchantmentTab.tabText(current_index)

        # 清除所有 tab
        self.allEnchantmentTab.clear()

        # 重新添加需要显示的 tab（按原有顺序）
        for cat in self.category_order:
            if cat in compatible_categories:
                list_widget = self.category_widgets[cat]
                self.allEnchantmentTab.addTab(list_widget, cat)

        # 恢复之前选中的分类（如果仍然存在）
        if current_cat:
            for i in range(self.allEnchantmentTab.count()):
                if self.allEnchantmentTab.tabText(i) == current_cat:
                    self.allEnchantmentTab.setCurrentIndex(i)
                    break

    def on_item_type_changed(self, item_type):
        """物品类型下拉框变化时触发"""
        self.current_stuff = self.itemsList.currentText()
        self.update_tabs_for_item(self.current_stuff)

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