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
        #  加载 UI（包含所有 Designer 控件）
        self.setupUi(self)

        # 配置chosenEnchantmentList
        self.chosenEnchantmentList.setAcceptDrops(True)
        self.chosenEnchantmentList.setDropIndicatorShown(True)
        self.chosenEnchantmentList.setDragEnabled(True)
        self.chosenEnchantmentList.setSelectionMode(QAbstractItemView.SingleSelection)
        self.chosenEnchantmentList.setDefaultDropAction(Qt.CopyAction)
        self.chosenEnchantmentList.dropped.connect(self.on_enchant_dropped)

        # 定义变量
        self.current_stuff = "附魔书"
        self.enchant_levels = {}
        self.category_enchants = {}
        self.category_widgets = {}

        # 加载附魔数据到下方的分类列表
        self.load_enchant_data()

        # 绑定信号与槽
        self.itemsList.currentIndexChanged.connect(self.on_item_type_changed)

    def load_enchant_data(self):
        """加载附魔数据，创建各分类的列表控件并添加到 tab"""
        all_enchants = self.data_manager.get_all_enchants()
        # 按分类分组
        categories = {}
        for ench in all_enchants:
            cat = ench.get("category", "其他")
            categories.setdefault(cat, []).append(ench)
        self.category_enchants = categories

        # 初始化等级字典（如果未记录）
        for ench in all_enchants:
            if ench['id'] not in self.enchant_levels:
                self.enchant_levels[ench['id']] = 1

        # 显示所有分类（物品类型为空）
        self.update_tabs_and_lists("附魔书")

    def update_tabs_and_lists(self, item_type: str):
        """
        根据物品类型重建 Tab 和每个列表的内容。
        - 如果 item_type 为空，显示所有分类和所有附魔。
        - 否则只显示包含兼容附魔的分类，且每个列表只显示兼容附魔。
        """
        # 1. 获取兼容附魔 ID 集合
        if not item_type:
            compatible_ids = {ench['id'] for ench in self.data_manager.get_all_enchants()}
        else:
            compatible_enchants = self.data_manager.get_enchants_for_item(item_type)
            compatible_ids = {ench['id'] for ench in compatible_enchants}

        # 2. 保存当前选中的分类名（用于恢复）
        current_index = self.allEnchantmentTab.currentIndex()
        current_cat = self.allEnchantmentTab.tabText(current_index) if current_index >= 0 else None

        # 3. 清空 Tab，重新构建
        self.allEnchantmentTab.clear()
        self.category_widgets = {}

        for cat_name, ench_list in self.category_enchants.items():
            # 筛选出该分类中兼容的附魔
            compatible_in_cat = [ench for ench in ench_list if ench['id'] in compatible_ids]
            if not compatible_in_cat:
                # 没有兼容附魔，跳过此分类（不显示 Tab）
                continue

            # 创建列表控件
            list_widget = EnchantListWidget()
            list_widget.levelChanged.connect(self.on_enchant_level_changed)

            for ench in compatible_in_cat:
                enchant_id = ench['id']
                level = self.enchant_levels.get(enchant_id, 1)
                item = QListWidgetItem(f"{ench['name']} (等级 {level})")
                item.setData(Qt.UserRole, enchant_id)
                item.setData(Qt.UserRole + 1, level)
                item.setData(Qt.UserRole + 2, ench['max_level'])
                list_widget.addItem(item)

            self.allEnchantmentTab.addTab(list_widget, cat_name)
            self.category_widgets[cat_name] = list_widget

        # 4. 恢复之前选中的分类（如果仍存在）
        if current_cat and current_cat in self.category_widgets:
            for i in range(self.allEnchantmentTab.count()):
                if self.allEnchantmentTab.tabText(i) == current_cat:
                    self.allEnchantmentTab.setCurrentIndex(i)
                    break
        elif self.allEnchantmentTab.count() > 0:
            self.allEnchantmentTab.setCurrentIndex(0)

    def on_enchant_level_changed(self, enchant_id: str, new_level: int):
        """等级变化时更新字典"""
        self.enchant_levels[enchant_id] = new_level

    def on_item_type_changed(self, item_type):
        """物品类型下拉框变化时触发"""
        self.current_stuff = self.itemsList.currentText()
        self.update_tabs_and_lists(self.current_stuff)

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