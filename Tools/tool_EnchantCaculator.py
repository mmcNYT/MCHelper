from .tool_base import BaseToolWidget
from Utils.choose_items import ChooseItemsWindow
from CodesUI.EnchantCaculator import Ui_EnchantCaculator
from Utils.enchanted_item_card import EnchantedItemCard
from PySide6.QtCore import QCoreApplication, Slot, QThreadPool, QStandardPaths, QItemSelectionModel
from PySide6.QtWidgets import QFileDialog, QListWidgetItem, QListView

class EnchantCalculatorWidget(BaseToolWidget, Ui_EnchantCaculator):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.addItems.clicked.connect(self.do_choose_items)

        # 物品卡片横向排列：每张卡片内部仍是图标在上、附魔方框在下，
        # 多张卡片从左到右排列，排满一行后自动换行
        self.listWidget.setFlow(QListView.LeftToRight)
        self.listWidget.setWrapping(True)
        self.listWidget.setSpacing(8)

        self.selected_stuff = {}

    # ---------- 实现基类接口 ----------
    @classmethod
    def tool_name(cls) -> str:
        return "EnchantCaculator"

    def do_choose_items(self):
        win = ChooseItemsWindow()
        win.exec()
        # exec() 返回后读取打包数据（未点确认时 selected_data 为 None）
        self.selected_stuff = win.selected_data
        print(self.selected_stuff)
        # 确认后把物品卡片（图标+附魔方框）添加到展示列表
        if self.selected_stuff:
            self.add_item_card(self.selected_stuff)
        # TODO: 后续计算逻辑使用 self.selected_stuff

    def add_item_card(self, data: dict):
        """把一次确认选择的物品生成为卡片并加入 listWidget

        参数：
            data: ChooseItemsWindow 打包的数据
                  {"item_name": str, "enchants": [{"id","name","level"}, ...]}
        """
        card = EnchantedItemCard(data["item_name"], data["enchants"])
        item = QListWidgetItem()
        item.setSizeHint(card.sizeHint())
        self.listWidget.addItem(item)
        self.listWidget.setItemWidget(item, card)